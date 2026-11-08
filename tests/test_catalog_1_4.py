"""1.4 phase C: all offers of the saved stores (offer catalog).

marktguru answers are trimmed from the live answers of 2026-11-07 (tests/fixtures/
mg_catalog.json, no API keys); EDEKA / ALDI SÜD answers as in phase B."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import json
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.essensplaner import aldi, articles, catalog, edeka, offers
from custom_components.essensplaner.aldi import SEARCH_URL as ALDI_SEARCH_URL, SERVICE_POINTS_URL
from custom_components.essensplaner.catalog import (
    KeyMatcher,
    OfferCatalog,
    async_variant_offers,
    catalog_plan,
    catalog_stale,
    classify_offer,
    kind_matches,
    kind_text,
    parse_leaflet,
    parse_publishers,
)
from custom_components.essensplaner.const import (
    CONF_ALDI_ONLINE,
    CONF_EDEKA_OFFERS,
    CONF_OFFERS_SOURCE,
    CONF_WATCHLIST,
    DOMAIN,
)
from custom_components.essensplaner.edeka import OFFERS_URL as EDEKA_OFFERS_URL
from custom_components.essensplaner.offers import (
    MARKTGURU_API,
    MARKTGURU_HOME,
    normalize_marktguru_short,
    parse_offer_notes,
)

from .mg_catalog import PUBLISHERS_URL, catalog_url, leaflets_url
from .test_economy import HOME_HTML

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime.fromisoformat("2026-11-04T10:00:00+01:00")  # Wednesday
MG = json.loads((FIXTURES / "mg_catalog.json").read_text(encoding="utf-8"))
SEARCH_URL = f"{MARKTGURU_API}/offers/search"
# the user's stores (diagnostics of 11/2026)
BRANCHES = [
    {"store": "REWE", "postcode": "57610", "street": "Bahnhofstraße 30"},
    {"store": "Netto", "postcode": "57632", "street": "Kornbitze 7"},
    {"store": "Norma", "postcode": "57632", "street": "Kornbitze 1"},
    {"store": "EDEKA", "postcode": "56593", "street": "Landblum 1", "label": "EDEKA Hoffmann"},
    {"store": "Lidl", "postcode": "56593", "street": "Landblum 2"},
    {"store": "Rossmann", "postcode": "56593", "street": "Rheinstraße 55"},
]


def _load(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _raw(store: str, product: str) -> dict[str, Any]:
    return next(r for r in MG["catalogs"][store] if r["product"]["name"] == product)


@pytest.fixture(autouse=True)
def clock(freezer) -> None:
    """The frozen test day (before the websocket token is made, it must not be from the
    future)."""
    freezer.move_to(NOW)


@pytest.fixture(autouse=True)
def no_delays(monkeypatch) -> None:
    """No politeness delays (the clock is frozen)."""
    monkeypatch.setattr(catalog, "REQUEST_DELAY", 0)
    monkeypatch.setattr(offers, "REQUEST_DELAY", 0)
    monkeypatch.setattr(edeka, "REQUEST_DELAY", 0)
    monkeypatch.setattr(aldi, "REQUEST_DELAY", 0)
    monkeypatch.setattr(aldi, "MAX_TERMS", 3)
    monkeypatch.setattr(articles, "LIVE_MIN_INTERVAL", 0)


@pytest.fixture
def berlin():
    """Local dates are German dates (the parsers without a running Home Assistant)."""
    old = dt_util.get_default_time_zone()
    dt_util.set_default_time_zone(dt_util.get_time_zone("Europe/Berlin"))
    yield
    dt_util.set_default_time_zone(old)


def _mock_marktguru(aioclient_mock: AiohttpClientMocker) -> None:
    """The user's three postcodes: discovery, catalogs and leaflet lists."""
    aioclient_mock.get(MARKTGURU_HOME, text=HOME_HTML)
    for zip_code, answer in MG["publishers"].items():
        aioclient_mock.get(PUBLISHERS_URL, params={"zipCode": zip_code}, json=answer)
    for key, results in MG["catalogs"].items():
        unique, zip_code = key.split("@")
        aioclient_mock.get(
            catalog_url(unique),
            params={"zipCode": zip_code},
            json={"totalResults": 999, "skippedResults": 0, "results": results},
        )
    for key, answer in MG["leaflets"].items():
        industry, zip_code = key.split("@")
        aioclient_mock.get(leaflets_url(industry), params={"zipCode": zip_code}, json=answer)


def _mg_calls(aioclient_mock: AiohttpClientMocker) -> list[str]:
    """marktguru requests made (path + zip code), in order."""
    calls = []
    for call in aioclient_mock.mock_calls:
        url = call[1]
        if url.host == "www.marktguru.de":
            calls.append("home")
        elif url.host == "api.marktguru.de":
            calls.append(f"{url.path.removeprefix('/api/v1')}@{url.query.get('zipCode')}")
    return calls


async def _setup(
    hass: HomeAssistant, entry: MockConfigEntry, freezer, now: datetime = NOW, **options
) -> Any:
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(now)
    assert await async_setup_component(hass, "homeassistant", {})
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def _user(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    freezer,
    now: datetime = NOW,
    marktguru: bool = True,
    **options,
) -> tuple[Any, dict[str, dict[str, Any]]]:
    """The user's setup: six stores, REWE the main branch."""
    if marktguru:
        options[CONF_OFFERS_SOURCE] = "marktguru"
    options.setdefault(CONF_WATCHLIST, "Butter, Milch, Hackfleisch, Kaffee")
    manager = await _setup(hass, entry, freezer, now, **options)
    branches = {}
    for data in BRANCHES:
        saved = manager.save_branch(dict(data))
        branches[saved["retailer"]] = saved
    assert manager.main_retailer == "rewe"
    return manager, branches


async def _refresh(hass: HomeAssistant) -> dict[str, Any]:
    result = await hass.services.async_call(
        DOMAIN, "refresh_offers", {}, blocking=True, return_response=True
    )
    await hass.async_block_till_done()
    return result


async def _ws(hass: HomeAssistant, hass_ws_client, **data) -> dict[str, Any]:
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/store_offers", **data})
    msg = await client.receive_json()
    assert msg["success"], msg
    return msg["result"]


# ----------------------------------------------------------------------
# short format, notes, kinds
# ----------------------------------------------------------------------


def test_normalize_short_notes(berlin) -> None:
    """App prices, Normalpreis, REWE Bonus, online-only, packs and local dates."""
    milk = normalize_marktguru_short(_raw("lidl@56593", "Frische Bio-Vollmilch"))
    assert (milk["price"], milk["regular_price"], milk["loyalty"]) == (1.19, 1.35, True)
    assert milk["loyalty_note"] == "Preis nur mit App"
    assert (milk["pack_amount"], milk["pack_unit"]) == (1000, "ml")
    assert (milk["valid_from"], milk["valid_to"]) == ("2026-11-02", "2026-11-07")
    assert milk["retailer"] == "lidl" and milk["store_id"] == "lidl"
    assert milk["image"].startswith("https://cdn.marktguru.de/api/v1/offers/")
    assert "HINWEIS" not in milk["description"] and "Normalpreis" not in milk["description"]

    snack = normalize_marktguru_short(_raw("lidl@56593", "Intermezzo"))
    assert (snack["app_price"], snack["loyalty"], snack["loyalty_note"]) == (
        1.59,
        False,
        "mit App 1,59 €",
    )
    assert (snack["pack_amount"], snack["pack_unit"]) == (190, "g")
    wine = normalize_marktguru_short(_raw("lidl@56593", "Identità Primitivo di Manduria"))
    assert wine["online_only"] and wine["pack_amount"] == 750

    rinse = normalize_marktguru_short(_raw("rossmann@56593", "Spülmittel"))
    assert (rinse["app_price"], rinse["valid_from"], rinse["valid_to"]) == (
        0.8,
        "2026-11-09",  # validFrom 2026-11-08T23:00:00Z is Monday in Germany
        "2026-11-13",
    )
    cheese = normalize_marktguru_short(_raw("rewe-petz@57610", "Quäse Körniger Frischkäse"))
    assert (cheese["loyalty"], cheese["loyalty_note"]) == (False, "mit App 0,10 € Bonus")
    assert cheese["description"] == "je 200-g-Becher"
    mince = normalize_marktguru_short(_raw("rewe-petz@57610", "Hackfleisch gemischt"))
    assert (mince["brand"], mince["title"], mince["retailer"]) == (
        "",
        "Hackfleisch gemischt",
        "rewe",
    )
    assert mince["store_id"] == "rewe-petz"
    # "Einzelpreis" of a multipack is never a regular price; 12 x 1 l
    crate = normalize_marktguru_short(_raw("netto-marken-discount@57632", "H-Vollmilch"))
    assert (crate["regular_price"], crate["pack_amount"], crate["pack_unit"]) == (
        None,
        12000,
        "ml",
    )
    # oldPrice 0.0 is no old price; a real one is
    assert normalize_marktguru_short(_raw("rossmann@56593", "Shampoo"))["old_price"] is None
    cappuccino = normalize_marktguru_short(_raw("rossmann@56593", "Cappuccino"))
    assert (cappuccino["price"], cappuccino["old_price"]) == (2.79, 4.99)


def test_short_pack_fallbacks(berlin) -> None:
    """volume x quantity when it fits price / referencePrice, else price / referencePrice."""
    base = {
        "id": 1,
        "product": {"name": "Zaziki"},
        "retailer": {"name": "Lidl", "uniqueName": "lidl"},
        "brand": {"name": "Milbona"},
        "unit": {"shortName": "kg"},
        "price": 1.29,
        "oldPrice": 0.0,
        "referencePrice": 2.58,
        "volume": 0,
        "quantity": 1,
        "description": "Gekühlt.",
        "validFrom": "2026-11-01T23:00:00Z",
        "validTo": "2026-11-07T22:59:59Z",
    }
    assert normalize_marktguru_short(base)["pack_amount"] == 500
    rolls = {**base, "unit": {"shortName": "Stk"}, "price": 0.98, "referencePrice": 0.33}
    assert normalize_marktguru_short({**rolls, "volume": 1, "quantity": 3})["pack_amount"] == 3
    # volume 1 of a 1,5-kg pack (marktguru stores whole numbers) does not fit the price
    pears = {**base, "price": 1.95, "referencePrice": 1.3, "volume": 1}
    assert normalize_marktguru_short(pears)["pack_amount"] == 1500
    assert normalize_marktguru_short({**base, "price": None}) is None


def test_parse_offer_notes() -> None:
    """The note texts seen in the catalogs."""
    notes = parse_offer_notes("HINWEIS: MIT ROSSMANN APP COUPON 1.- € 20 WL")
    assert (notes["app_price"], notes["app_only"], notes["text"]) == (1.0, False, "20 WL")
    notes = parse_offer_notes("HINWEIS: MIT PENNY APP je 30 g. Ohne Penny App 1.79")
    assert (notes["app_only"], notes["without_app"], notes["text"]) == (True, 1.79, "je 30 g")
    notes = parse_offer_notes("HINWEIS: MIT LIDL PLUS APP 1kg, Normalpreis  3.99")
    assert (notes["regular_price"], notes["app_only"], notes["text"]) == (3.99, True, "1kg")
    notes = parse_offer_notes("je 20 x 0,5-l-Fl.-Kasten zzgl. 3.10 Pfand")
    assert (notes["deposit"], notes["text"]) == (3.1, "je 20 x 0,5-l-Fl.-Kasten")
    notes = parse_offer_notes("versch. Sorten 32 x 100 g Einzelpreis: 0.25")
    assert (notes["regular_price"], notes["text"]) == (None, "versch. Sorten 32 x 100 g")
    assert parse_offer_notes("Details im Prospekt")["text"] == ""
    assert parse_offer_notes("HINWEIS: NUR ONLINE VERFÜGBAR Je 0,7 l")["online_only"]


@pytest.mark.parametrize(
    ("product", "description", "retailer", "categories", "kind"),
    [
        ("Frische Bio-Vollmilch", "", "lidl", None, "food"),
        ("Glühwein", "", "lidl", None, "drinks"),
        ("Original Spiced Gold Rum", "", "lidl", None, "drinks"),
        ("Damen-Funktionsshirt", "", "lidl", None, "nonfood"),
        ("Kaffeevollautomat Sensation EA910A", "", "lidl", None, "nonfood"),
        ("Knusprige Kroketten Hundefutter", "", "lidl", None, "nonfood"),
        ("Studentenfutter", "", "netto-marken-discount", None, "food"),
        ("Duschgel", "", "rewe", None, "drugstore"),
        ("Kräuter-Shampoo", "", "rewe", None, "drugstore"),
        ("Waschmittel", "", "lidl", None, "household"),
        ("Hydro Boost Aqua Creme", "", "rossmann", None, "drugstore"),
        ("Leibniz Butterkeks", "", "rossmann", None, "food"),
        ("Ligretto", "", "rossmann", None, "drugstore"),
        ("Classic", "frz. Schnittkäse, je 150-g-Pckg", "rewe", None, "food"),
        ("Intermezzo", "190g/185g", "lidl", None, "unknown"),
        ("Bonbel", "", "edeka", ["Molkerei & Käse"], "food"),
        ("Odol-med3", "", "edeka", ["Drogerie"], "drugstore"),
        ("Cola", "", "aldi-sued", ["Getränke", "Cola"], "drinks"),
    ],
)
def test_classify_offer(product, description, retailer, categories, kind) -> None:
    """Food / drinks / drugstore / household / nonfood by a local heuristic."""
    assert classify_offer(product, description, retailer, categories) == kind


def test_kind_filter_and_kind_text() -> None:
    """The panel's kind filter; the kind named by a description."""
    assert kind_matches({"kind": "unknown", "retailer": "lidl"}, "food")
    assert not kind_matches({"kind": "unknown", "retailer": "rossmann"}, "food")
    assert kind_matches({"kind": "unknown", "retailer": "rossmann"}, "drugstore")
    assert kind_matches({"kind": "drinks", "retailer": "lidl"}, "food")
    assert not kind_matches({"kind": "nonfood", "retailer": "lidl"}, "food")
    assert kind_matches({"kind": "household", "retailer": "lidl"}, "household")
    assert kind_text("frz. Schnittkäse, je 150-g-Pckg") == "frz. Schnittkäse"
    assert kind_text("oder Mayonnaise je 400-ml-Fl") == ""
    assert kind_text("versch. Sorten, je 800-g-Dose") == ""
    assert kind_text("Herkunft: Spanien · Klasse I") == "Klasse I"


def test_key_matcher() -> None:
    """Token index + offer_matches(): compounds, the product name decides."""
    matcher = KeyMatcher(["butter", "milch", "hackfleisch", "ei", "kaffee", "schnittkaese"])
    assert matcher.match("Süßrahmbutter", "Süßrahmbutter") == ["butter"]
    assert matcher.match("Butter-Spekulatius", "Butter-Spekulatius") == []
    assert matcher.match("Frische Bio-Vollmilch", "Frische Bio-Vollmilch") == ["milch"]
    assert matcher.match("Bio-Eier, 10 Stück", "Bio-Eier") == ["ei"]
    assert matcher.match("Eierlikör", "Eierlikör") == []
    classic = {"product": "Classic", "description": "frz. Schnittkäse, je 150-g-Pckg"}
    assert matcher.offer_keys(classic) == ["schnittkaese"]
    # the description names the kind, not what is in it
    tzatziki = {"product": "Zaziki", "description": "Mit Gurken und Knoblauch"}
    assert KeyMatcher(["gurke"]).offer_keys(tzatziki) == []


# ----------------------------------------------------------------------
# answers: discovery, paging, leaflets
# ----------------------------------------------------------------------


def test_parse_publishers_and_leaflets(berlin) -> None:
    """Variants of known chains with numeric ids; leaflet tiles with page images."""
    found = parse_publishers(MG["publishers"]["57610"])
    by_name = {p["unique_name"]: p for p in found}
    assert by_name["rewe-petz"] == {
        "id": 128150,
        "unique_name": "rewe-petz",
        "name": "REWE Petz",
        "retailer": "rewe",
    }
    assert {"lidl", "penny", "aldi-sued", "rossmann", "netto-marken-discount"} <= set(by_name)
    assert "kik" not in by_name and "xxxl" not in by_name  # no grocery / drugstore chain
    norma = [
        parse_leaflet(r)
        for r in MG["leaflets"]["discounter@57632"]["results"]
        if r["advertiser"]["uniqueName"] == "norma"
    ]
    assert [(n["leaflet_id"], n["valid_from"], n["valid_to"], n["page_count"]) for n in norma] == [
        (6500922, "2026-11-09", "2026-11-14", 30),
        (6453737, "2026-11-02", "2026-11-07", 29),
    ]
    assert norma[0]["pages"][0] == (
        "https://cdn.marktguru.de/api/v1/leaflets/6500922/images/pages/0/small.webp"
    )
    assert len(norma[0]["pages"]) == catalog.LEAFLET_PREVIEW_PAGES
    assert norma[0]["url"] == "https://www.marktguru.de/leaflets/6500922/page/0"


async def test_paging_stops_at_expired_and_short_pages(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, monkeypatch, freezer
) -> None:
    """Full pages are followed, the first expired offer or a short page ends the catalog
    (totalResults is not trusted), at most MAX_PAGES pages."""
    monkeypatch.setattr(catalog, "PAGE_LIMIT", 4)
    freezer.move_to(NOW)
    lidl = MG["catalogs"]["lidl@56593"]
    filler = MG["catalogs"]["rewe-petz@57610"][-1]  # expired in September
    pages = [lidl[0:4], lidl[4:8], [lidl[8], lidl[9], filler, lidl[10]]]
    aioclient_mock.get(MARKTGURU_HOME, text=HOME_HTML)
    for offset, page in zip((0, 4, 8), pages, strict=True):
        aioclient_mock.get(
            catalog_url("lidl"),
            params={"offset": offset},
            json={"totalResults": 853, "results": page},
        )
    client = catalog.CatalogClient(hass)
    raw, count = await async_variant_offers(client, "lidl", "56593", dt_util.utcnow())
    assert count == 3
    assert [r["id"] for r in raw] == [r["id"] for r in lidl[:10]]  # stops at the filler
    assert client.requests == 4  # home page + 3 pages

    # a page with only expired filler offers: nothing current, no further page
    aioclient_mock.clear_requests()
    aioclient_mock.get(MARKTGURU_HOME, text=HOME_HTML)
    aioclient_mock.get(catalog_url("norma"), json={"results": MG["catalogs"]["norma@57632"]})
    raw, count = await async_variant_offers(
        catalog.CatalogClient(hass), "norma", "57632", dt_util.utcnow()
    )
    assert (raw, count) == ([], 1)

    # never more than MAX_PAGES pages
    monkeypatch.setattr(catalog, "MAX_PAGES", 2)
    aioclient_mock.clear_requests()
    aioclient_mock.get(MARKTGURU_HOME, text=HOME_HTML)
    aioclient_mock.get(catalog_url("lidl"), json={"results": lidl[0:4]})
    raw, count = await async_variant_offers(
        catalog.CatalogClient(hass), "lidl", "56593", dt_util.utcnow()
    )
    assert (len(raw), count) == (8, 2)


# ----------------------------------------------------------------------
# refresh: request budget, leaflets, offers for planning, learning
# ----------------------------------------------------------------------


async def test_refresh_six_stores(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock, hass_ws_client
) -> None:
    """The user's six stores: about a dozen requests, every chain's offers, leaflets of
    NORMA and EDEKA, matching offers for planning, learned regular prices."""
    _mock_marktguru(aioclient_mock)
    manager, branches = await _user(hass, config_entry, freezer)
    meta = await _refresh(hass)
    assert meta["status"] == "ok", meta
    calls = _mg_calls(aioclient_mock)
    assert calls == [
        "home",
        "/offers/publishers@57610",
        "/publishers/retailer/rewe-petz/offers@57610",
        "/offers/publishers@57632",
        "/publishers/retailer/netto-marken-discount/offers@57632",
        "/industries/discounter/leaflets@57632",  # NORMA: leaflet images only
        "/offers/publishers@56593",
        "/publishers/retailer/lidl/offers@56593",
        "/publishers/retailer/rossmann/offers@56593",
        "/industries/supermaerkte/leaflets@56593",  # EDEKA: leaflet images only
    ]
    assert len(calls) <= 15
    assert meta["requests"] == len(calls)
    # every marktguru request is an honest one
    for call in aioclient_mock.mock_calls:
        assert "HA-Essensplaner/1.4" in (call[3] or {}).get("User-Agent", "")

    store = manager.catalog
    today = manager.today()
    current = store.current_offers(today)
    by_retailer: dict[str, int] = {}
    for offer in current:
        by_retailer[offer["retailer"]] = by_retailer.get(offer["retailer"], 0) + 1
    assert by_retailer == {
        "rewe": 11,
        "netto-marken-discount": 10,
        "lidl": 17,
        "rossmann": 10,
    }
    leaflets = store.leaflets(today)
    assert {(lf["retailer"], lf["zip_code"]) for lf in leaflets} == {
        ("norma", "57632"),
        ("edeka", "56593"),
    }
    # offers that fit the plan / watchlist went to the offers used for planning
    planned = {o["id"]: o for o in manager.offers if o.get("source") == "marktguru"}
    butter = [o for o in planned.values() if "butter" in o["keys"]]
    assert {o["retailer"] for o in butter} >= {"rewe", "lidl", "netto-marken-discount"}
    assert not any(o["product"] == "Butter-Spekulatius" for o in planned.values())
    assert not any(o.get("online_only") for o in planned.values())
    rewe_butter = next(o for o in butter if o["retailer"] == "rewe")
    assert rewe_butter["branches"] == [branches["rewe"]["id"]]
    assert rewe_butter["zip_codes"] == ["57610"]
    assert manager.offers_meta["targets"] == [
        {"zip_code": "57610", "retailers": ["rewe"]},
        {"zip_code": "57632", "retailers": ["netto-marken-discount", "norma"]},
        {"zip_code": "56593", "retailers": ["edeka", "lidl", "rossmann"]},
    ]
    assert manager.offers_meta["count"] == len(planned)
    assert meta["catalog"]["count"] == len(current)

    # regular prices printed in the leaflets: Lidl's "Normalpreis", Rossmann's old price
    learned = manager.store_prices_learned
    lidl_butter = learned["lidl"]["butter"]
    assert (lidl_butter["price"], lidl_butter["amount"], lidl_butter["source"]) == (
        2.69,
        250,
        "leaflet",
    )
    assert learned["lidl"]["schlagsahne"]["price"] == 0.89
    assert meta["learned"] == manager.catalog.data["learned"] >= 4
    # online-only offers teach nothing
    assert not any(
        item.get("ref") == "mg_25477587" for bucket in learned.values() for item in bucket.values()
    )

    # the catalog is in its own file, the main store does not hold it
    assert manager.catalog.data["last_success"] is not None
    assert "buckets" not in manager._data_to_store()

    # a second manual refresh right away sends nothing
    aioclient_mock.mock_calls.clear()
    again = await _refresh(hass)
    assert _mg_calls(aioclient_mock) == []
    assert "Gerade erst aktualisiert" in again["message"]
    # an hour later: the discovery is cached (7 days)
    freezer.tick(timedelta(hours=1, minutes=1))
    aioclient_mock.mock_calls.clear()
    await _refresh(hass)
    calls = _mg_calls(aioclient_mock)
    assert not [c for c in calls if c.startswith("/offers/publishers")]
    assert len(calls) == 7


async def test_store_offers_websocket(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock, hass_ws_client
) -> None:
    """All offers of the saved stores: filters, paging, stores with counts and leaflets."""
    _mock_marktguru(aioclient_mock)
    manager, branches = await _user(hass, config_entry, freezer)
    await _refresh(hass)
    aioclient_mock.mock_calls.clear()

    result = await _ws(hass, hass_ws_client, limit=100)
    assert _mg_calls(aioclient_mock) == []  # the websocket never fetches
    stores = {s["retailer"]: s for s in result["stores"]}
    assert list(stores) == ["rewe", "netto-marken-discount", "norma", "edeka", "lidl", "rossmann"]
    assert stores["norma"]["leaflet_only"] and stores["edeka"]["leaflet_only"]
    # this week's leaflet first, then the one of next week
    assert [lf["page_count"] for lf in stores["norma"]["leaflets"]] == [29, 30]
    assert stores["norma"]["sources"] == ["marktguru"]
    assert not stores["lidl"]["leaflet_only"]
    assert stores["rewe"]["status"] == "ok" and stores["rewe"]["main"]
    # Rossmann's offers start next Monday
    assert (stores["rossmann"]["count_current"], stores["rossmann"]["count_upcoming"]) == (0, 10)
    upcoming_lidl = {
        o["id"]
        for o in manager.catalog.current_offers(manager.today())
        if o["retailer"] == "lidl" and o["valid_from"] > "2026-11-04" and not o.get("online_only")
    }
    assert stores["lidl"]["count_upcoming"] == len(upcoming_lidl) >= 2
    assert result["meta"]["marktguru"] and result["meta"]["status"] == "ok"
    ids = {o["id"] for o in result["offers"]}
    assert all(o["current"] for o in result["offers"])
    assert not any(o["online_only"] for o in result["offers"])  # hidden by default
    assert result["total"] == len(ids)
    first = result["offers"][0]
    assert {
        "id",
        "title",
        "brand",
        "description",
        "price",
        "old_price",
        "regular_price",
        "app_price",
        "loyalty",
        "online_only",
        "unit_price",
        "base_unit",
        "pack_amount",
        "pack_unit",
        "valid_from",
        "valid_to",
        "image",
        "kind",
        "retailer",
        "store",
        "branch_ids",
        "keys",
        "source",
    } <= set(first)
    # sorted by saving: Lidl's butter (Normalpreis 2.69 -> 2.42) before plain offers
    savings = [o["saving"] or 0 for o in result["offers"]]
    assert savings == sorted(savings, reverse=True)

    # one store, upcoming offers
    lidl = await _ws(hass, hass_ws_client, branch_ids=[branches["lidl"]["id"]], when="upcoming")
    assert {o["id"] for o in lidl["offers"]} == upcoming_lidl
    assert {"Meggle Feine Butter", "Floralys Toilettenpapier XXL"} <= {
        o["title"] for o in lidl["offers"]
    }
    assert all(o["branch_ids"] == [branches["lidl"]["id"]] for o in lidl["offers"])
    # kinds
    food = await _ws(hass, hass_ws_client, kind="food", limit=100)
    assert not any(o["kind"] in ("nonfood", "household", "drugstore") for o in food["offers"])
    drug = await _ws(hass, hass_ws_client, kind="drugstore", when="all", limit=100)
    assert {o["retailer"] for o in drug["offers"]} >= {"rossmann", "rewe"}  # Fa Duschgel
    household = await _ws(hass, hass_ws_client, kind="household", when="all", limit=100)
    assert any(o["title"].endswith("Toilettenpapier") for o in household["offers"])
    # search, own ingredients, sorting, paging
    butter = await _ws(hass, hass_ws_client, query="Butter", sort="price")
    titles = [o["title"] for o in butter["offers"]]
    assert "Favorina Butter-Spekulatius" in titles  # text search finds it
    prices = [o["price"] for o in butter["offers"]]
    assert prices == sorted(prices)
    mine = await _ws(hass, hass_ws_client, mine=True, limit=100)
    assert mine["total"] < result["total"]
    assert all(o["keys"] for o in mine["offers"])
    page = await _ws(hass, hass_ws_client, limit=5, offset=5, sort="name")
    names = await _ws(hass, hass_ws_client, limit=10, sort="name")
    assert [o["id"] for o in page["offers"]] == [o["id"] for o in names["offers"][5:10]]
    online = await _ws(hass, hass_ws_client, include_online=True, limit=100)
    assert any(o["online_only"] for o in online["offers"])
    assert ids <= {o["id"] for o in online["offers"]}


async def test_add_catalog_offer_to_list(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock
) -> None:
    """An offer of "Alle Angebote meiner Läden" goes on the list at that store, with the
    offer's price and pack."""
    _mock_marktguru(aioclient_mock)
    manager, branches = await _user(hass, config_entry, freezer)
    await _refresh(hass)
    planned = {o["id"] for o in manager.offers}
    offer = next(
        o
        for o in manager.catalog.current_offers(manager.today())
        if o["retailer"] == "netto-marken-discount" and o["id"] not in planned
    )
    netto = branches["netto-marken-discount"]["id"]
    result = await hass.services.async_call(
        DOMAIN,
        "add_shopping_item",
        {"item": offer["product"], "offer_id": offer["id"], "store": netto},
        blocking=True,
        return_response=True,
    )
    item = result["item"]
    assert item["branch_id"] == netto
    assert (item["chosen"]["price"], item["chosen"]["amount"], item["chosen"]["unit"]) == (
        offer["price"],
        offer["pack_amount"],
        offer["pack_unit"],
    )
    assert item["chosen"]["offer_id"] == offer["id"]
    assert item["chosen"]["offer"]["valid_to"] == "2026-11-07"  # kept while valid
    # without a store: the branch the offer belongs to
    item = manager.shopping_add(
        "Kaffee",
        offer_id=next(
            o["id"]
            for o in manager.catalog.current_offers(manager.today())
            if o["product"] == "Prodomo Kaffee"
        ),
    )
    assert item["branch_id"] == branches["netto-marken-discount"]["id"]
    assert item["chosen"]["price"] == 6.49


async def test_price_list_offer_overlay(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock
) -> None:
    """The cheapest current offer per article and store is shown in the price list (never
    stored as a regular price); every selected store is a column."""
    _mock_marktguru(aioclient_mock)
    manager, _ = await _user(hass, config_entry, freezer)
    before = manager.store_price_matrix()
    assert [r["id"] for r in before["retailers"]] == [
        "rewe",
        "netto-marken-discount",
        "norma",
        "edeka",
        "lidl",
        "rossmann",
    ]
    await _refresh(hass)
    matrix = manager.store_price_matrix(query="Butter")
    row = next(r for r in matrix["rows"] if r["key"] == "butter")
    assert row["offers"]["rewe"]["price"] == 1.15  # ja! Markenbutter
    assert row["offers"]["netto-marken-discount"]["price"] == 1.79
    lidl = row["offers"]["lidl"]
    assert lidl["price"] == 1.39 and lidl["valid_to"] == "2026-11-07"  # cheapest per kg
    assert set(lidl) >= {"price", "valid_to", "id", "loyalty", "app_price"}
    # the learned regular price stays the leaflet's "Normalpreis"
    assert row["stores"]["lidl"]["price"] == 2.69
    assert row["stores"]["lidl"]["offer"] == lidl
    assert "rossmann" not in row["offers"]
    # upcoming offers are no current offer
    milk = manager.store_price_matrix(query="Toilettenpapier")
    paper = next(r for r in milk["rows"] if r["key"] == "toilettenpapier")
    assert "lidl" not in paper.get("offers", {})
    assert paper["offers"]["rewe"]["price"] == 5.49


async def test_live_search_only_own_chains(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock
) -> None:
    """The live offer search asks marktguru only for the user's chains (numeric ids of the
    discovery)."""
    _mock_marktguru(aioclient_mock)
    aioclient_mock.get(SEARCH_URL, json={"results": []})
    await _user(hass, config_entry, freezer)
    await _refresh(hass)
    aioclient_mock.mock_calls.clear()
    await hass.services.async_call(
        DOMAIN, "search_offers", {"query": "Butter"}, blocking=True, return_response=True
    )
    searches = [c[1] for c in aioclient_mock.mock_calls if "offers/search" in str(c[1])]
    assert {u.query["zipCode"]: u.query.get("retailers") for u in searches} == {
        "57610": "128150",
        "57632": "126735",  # NORMA has no single offers
        "56593": "126679,126811",
    }


async def test_marktguru_off_sends_nothing(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock
) -> None:
    """Without the marktguru option no request goes to marktguru – not at start, not at
    06:xx, not with a refresh; without any offer source refresh_offers is refused."""
    _mock_marktguru(aioclient_mock)
    manager, _ = await _user(hass, config_entry, freezer, marktguru=False)
    with pytest.raises(ServiceValidationError) as err:
        await _refresh(hass)
    assert err.value.translation_key == "offers_disabled"
    result = await catalog.async_refresh_catalog(hass, manager, force=True)
    assert result["status"] == "off"
    freezer.tick(timedelta(days=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert aioclient_mock.mock_calls == []
    assert manager.catalog.current_offers(manager.today()) == []


async def test_edeka_market_offers_in_catalog(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock, hass_ws_client
) -> None:
    """EDEKA direct (marktguru off): the whole market leaflet is in the catalog for the
    EDEKA branch; marktguru is never asked."""
    _mock_marktguru(aioclient_mock)
    aioclient_mock.get(EDEKA_OFFERS_URL, json=_load("edeka_offers"))
    manager, branches = await _user(
        hass, config_entry, freezer, marktguru=False, **{CONF_EDEKA_OFFERS: True}
    )
    manager.save_branch({"id": branches["edeka"]["id"], "edeka_market_id": "2644015"})
    assert catalog_plan(manager)["edeka"]
    meta = await _refresh(hass)
    assert meta["status"] == "ok", meta
    assert _mg_calls(aioclient_mock) == []
    current = manager.catalog.current_offers(manager.today())
    assert current and {o["source"] for o in current} == {"edeka"}
    assert all(o.get("kind") for o in current)
    result = await _ws(hass, hass_ws_client, branch_ids=[branches["edeka"]["id"]], when="all")
    assert result["total"] == len(current)
    edeka_store = next(s for s in result["stores"] if s["retailer"] == "edeka")
    assert edeka_store["sources"] == ["edeka"] and edeka_store["status"] == "ok"
    rewe = next(s for s in result["stores"] if s["retailer"] == "rewe")
    assert (rewe["sources"], rewe["status"]) == ([], "off")  # no source for REWE offers

    # marktguru on as well: EDEKA is served directly, marktguru is not asked for it
    hass.config_entries.async_update_entry(
        config_entry, options={**config_entry.options, CONF_OFFERS_SOURCE: "marktguru"}
    )
    await hass.async_block_till_done()
    manager = config_entry.runtime_data
    freezer.tick(timedelta(hours=2))
    aioclient_mock.mock_calls.clear()
    await _refresh(hass)
    calls = _mg_calls(aioclient_mock)
    assert "/industries/supermaerkte/leaflets@56593" not in calls
    assert "/publishers/retailer/lidl/offers@56593" in calls
    assert not manager.catalog.bucket("marktguru", "edeka", "56593")


async def test_aldi_weekly_offers_in_catalog(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock
) -> None:
    """ALDI SÜD direct: the weekly offers are in the catalog; the ones of planned
    ingredients are offers for planning (source aldi_weekly)."""
    aioclient_mock.get(SERVICE_POINTS_URL, json=_load("aldi_service_points"))
    aioclient_mock.get(ALDI_SEARCH_URL, json=_load("aldi_weekly_offers"))
    manager = await _setup(
        hass,
        config_entry,
        freezer,
        **{CONF_ALDI_ONLINE: True, CONF_WATCHLIST: "Hackfleisch, Cola, Frischkäse"},
    )
    manager.save_branch({"store": "Aldi Süd", "postcode": "53567", "lat": 50.62, "lon": 7.43})
    meta = await _refresh(hass)
    assert meta["status"] == "ok", meta
    current = manager.catalog.current_offers(manager.today())
    assert current and {o["source"] for o in current} == {"aldi_weekly"}
    assert all(o["valid_to"] == "2026-11-07" for o in current)
    planned = [o for o in manager.offers if o.get("source") == "aldi_weekly"]
    assert planned and all(o["keys"] for o in planned)
    assert all(o["branches"] == [manager.branches[0]["id"]] for o in planned)
    assert not [c for c in aioclient_mock.mock_calls if "marktguru" in str(c[1])]


async def test_blocked_marktguru_pauses(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock
) -> None:
    """HTTP 403 after reading the keys again: marktguru is paused, the previous offers
    stay, no request until the pause ends."""
    _mock_marktguru(aioclient_mock)
    manager, _ = await _user(hass, config_entry, freezer)
    await _refresh(hass)
    count = len(manager.catalog.current_offers(manager.today()))
    aioclient_mock.clear_requests()
    aioclient_mock.get(MARKTGURU_HOME, text=HOME_HTML)
    aioclient_mock.get(PUBLISHERS_URL, status=403)
    aioclient_mock.get(catalog_url("rewe-petz"), status=403)
    manager.catalog.data["publishers"].clear()
    freezer.tick(timedelta(hours=2))
    meta = await _refresh(hass)
    assert meta["status"] == "blocked"
    assert "keine automatischen Abfragen" in meta["errors"][0]
    assert _mg_calls(aioclient_mock).count("home") == 2  # keys read again once
    assert len(manager.catalog.current_offers(manager.today())) == count  # kept
    aioclient_mock.mock_calls.clear()
    freezer.tick(timedelta(days=1))
    meta = await _refresh(hass)
    assert meta["status"] == "blocked" and _mg_calls(aioclient_mock) == []
    assert manager.catalog.summary(manager)["blocked_until"] is not None


async def test_refresh_schedule(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock
) -> None:
    """Start check, then nothing while fresh; Saturday after a Friday success fetches."""
    _mock_marktguru(aioclient_mock)
    manager, _ = await _user(hass, config_entry, freezer)
    freezer.tick(timedelta(seconds=95))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert manager.catalog.data["last_success"] is not None
    first = len(_mg_calls(aioclient_mock))
    assert first >= 8
    # the daily check the next morning: fresh, nothing sent
    freezer.move_to(datetime.fromisoformat("2026-11-05T06:59:00+01:00"))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(_mg_calls(aioclient_mock)) == first


def test_catalog_stale(hass: HomeAssistant, berlin) -> None:
    """3 days, a new leaflet week (Saturday, Sunday, Monday: REWE and Netto publish the new
    week only on Sunday) or other stores."""
    store = OfferCatalog(hass, "x")
    plan = {"signature": "a"}

    def stale(last: str, now: str, signature: str = "a") -> bool:
        store.data["last_success"] = datetime.fromisoformat(last).isoformat()
        store.data["signature"] = signature
        return catalog_stale(store, plan, datetime.fromisoformat(now))

    assert stale("2026-11-02T07:00:00+01:00", "2026-11-05T06:30:00+01:00")  # Mon -> Thu
    assert not stale("2026-11-02T07:00:00+01:00", "2026-11-04T06:30:00+01:00")  # Wed
    assert stale("2026-11-06T07:00:00+01:00", "2026-11-07T06:30:00+01:00")  # Fri -> Sat
    assert stale("2026-11-07T07:00:00+01:00", "2026-11-08T06:30:00+01:00")  # Sat -> Sun
    assert not stale("2026-11-08T06:30:00+01:00", "2026-11-08T21:00:00+01:00")  # Sun again
    assert stale("2026-11-08T06:30:00+01:00", "2026-11-09T06:30:00+01:00")  # -> Monday
    assert stale("2026-11-07T07:00:00+01:00", "2026-11-09T06:30:00+01:00")  # Sat -> Monday
    assert not stale("2026-11-07T07:00:00+01:00", "2026-11-07T21:00:00+01:00")  # Sat again
    assert not stale("2026-11-09T06:30:00+01:00", "2026-11-09T18:00:00+01:00")
    assert stale("2026-11-09T06:30:00+01:00", "2026-11-09T18:00:00+01:00", signature="b")
    store.data["last_success"] = None
    assert catalog_stale(store, plan, datetime.fromisoformat("2026-11-09T06:30:00+01:00"))


async def test_catalog_file_kept_and_removed(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock, hass_storage
) -> None:
    """Own storage file: reloaded after a restart, removed with the integration."""
    _mock_marktguru(aioclient_mock)
    manager, _ = await _user(hass, config_entry, freezer)
    await _refresh(hass)
    key = f"essensplaner.catalog.{config_entry.entry_id}"
    assert key in hass_storage
    count = len(manager.catalog.current_offers(manager.today()))
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    manager = config_entry.runtime_data
    assert len(manager.catalog.current_offers(manager.today())) == count
    # the price list overlay still knows the offers
    assert manager.store_price_matrix(query="Butter")["rows"][0].get("offers")
    diagnostics = await __import__(
        "custom_components.essensplaner.diagnostics", fromlist=["x"]
    ).async_get_config_entry_diagnostics(hass, config_entry)
    counts = diagnostics["offer_catalog"]
    assert counts["offers"] == count and counts["by_retailer"]["lidl"] == 17
    assert "57610" not in json.dumps(counts)  # no postcodes
    assert await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()
    assert key not in hass_storage


async def test_expired_offers_dropped(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock
) -> None:
    """Ended offers leave the catalog views; leaflets that ended too."""
    _mock_marktguru(aioclient_mock)
    manager, _ = await _user(hass, config_entry, freezer)
    await _refresh(hass)
    freezer.move_to(datetime.fromisoformat("2026-11-10T12:00:00+01:00"))
    today = manager.today()
    assert today == date(2026, 11, 10)
    left = manager.catalog.current_offers(today)
    assert {o["retailer"] for o in left} == {"lidl", "rossmann"}  # next week's offers
    assert {lf["retailer"] for lf in manager.catalog.leaflets(today)} == {"norma"}


async def test_store_offers_without_branches(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock, hass_ws_client
) -> None:
    """1.2 setup (postcode + chains in the options, no branches): the chosen chains'
    catalogs, every offer shown without a branch."""
    _mock_marktguru(aioclient_mock)
    await _setup(
        hass,
        config_entry,
        freezer,
        **{
            CONF_OFFERS_SOURCE: "marktguru",
            "zip_code": "56593",
            "offer_stores": ["lidl", "rossmann"],
        },
    )
    meta = await _refresh(hass)
    assert meta["status"] == "ok"
    assert meta["targets"] == [{"zip_code": "56593", "retailers": ["lidl", "rossmann"]}]
    result = await _ws(hass, hass_ws_client, when="all", limit=100)
    assert result["stores"] == []
    assert {o["retailer"] for o in result["offers"]} == {"lidl", "rossmann"}
    assert all(o["branch_ids"] == [] for o in result["offers"])


async def test_failed_refresh_is_retried(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock
) -> None:
    """marktguru unreachable: an error, nothing counts as fresh – the next refresh (also a
    manual one right away) asks again."""
    aioclient_mock.get(MARKTGURU_HOME, status=503)
    manager, _ = await _user(hass, config_entry, freezer)
    meta = await _refresh(hass)
    assert meta["status"] == "error"
    assert "HTTP 503" in meta["errors"][0]
    assert _mg_calls(aioclient_mock) == ["home"]  # nothing more after the home page
    assert manager.catalog.data["last_success"] is None
    aioclient_mock.clear_requests()
    _mock_marktguru(aioclient_mock)
    meta = await _refresh(hass)
    assert meta["status"] == "ok"
    assert manager.catalog.data["last_success"] is not None
