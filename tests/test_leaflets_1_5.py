"""1.5 phase P4: leaflets of all saved branches ("📰 Prospekte").

Every answer is made up (fictional stores in Musterstadt, postcodes 12345 / 12347 / 12349,
leaflet ids 9001xx …); no live data."""

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
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.essensplaner import aldi, catalog
from custom_components.essensplaner.aldi import (
    LEAFLETS_PAGE_URL,
    SEARCH_URL as ALDI_SEARCH_URL,
    parse_aldi_leaflets,
)
from custom_components.essensplaner.catalog import (
    async_refresh_catalog,
    leaflet_due,
    leaflet_pairs,
    leaflets_view,
    store_offers_view,
)
from custom_components.essensplaner.const import (
    CONF_ALDI_ONLINE,
    CONF_ALL_LEAFLETS,
    CONF_OFFERS_SOURCE,
    CONF_WATCHLIST,
    DOMAIN,
)
from custom_components.essensplaner.diagnostics import async_get_config_entry_diagnostics
from custom_components.essensplaner.offers import MARKTGURU_HOME
from custom_components.essensplaner.retailers import LEAFLET_LINKS, RETAILERS, leaflet_link

from .mg_catalog import PUBLISHERS_URL, catalog_url, leaflets_url, publishers_answer
from .test_economy import HOME_HTML

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime.fromisoformat("2026-11-04T10:00:00+01:00")  # Wednesday
CURRENT = ("2026-11-01T23:00:00Z", "2026-11-07T22:59:59Z")  # Mon 02.11. – Sat 07.11.
UPCOMING = ("2026-11-08T23:00:00Z", "2026-11-14T22:59:59Z")  # Mon 09.11. – Sat 14.11.
ENDED = ("2026-10-25T23:00:00Z", "2026-10-31T22:59:59Z")
NAMES = {
    "rewe": "REWE",
    "edeka": "EDEKA",
    "lidl": "Lidl",
    "penny": "PENNY",
    "rossmann": "ROSSMANN",
    "netto-marken-discount": "Netto Marken-Discount",
    "norma": "NORMA",
}
# the fictional stores: REWE the main branch, two Lidl branches at different postcodes,
# NORMA without single offers (leaflet images only)
BRANCHES = [
    {"store": "REWE", "postcode": "12345", "street": "Lindenweg 1"},
    {"store": "Lidl", "postcode": "12345", "street": "Lindenweg 2"},
    {"store": "Rossmann", "postcode": "12345", "street": "Lindenweg 4"},
    {"store": "Netto", "postcode": "12347", "street": "Musterweg 3"},
    {"store": "Norma", "postcode": "12347", "street": "Musterweg 5"},
    {"store": "Lidl", "postcode": "12349", "street": "Bahnhofstraße 9", "label": "Lidl Arbeit"},
]


def _leaflet(lid: int, unique: str, valid: tuple[str, str], pages: int = 30) -> dict[str, Any]:
    """A leaflet of marktguru's leaflet list (made up)."""
    return {
        "id": 300000 + lid % 1000,
        "advertiser": {"id": f"retailers/{lid}", "name": NAMES[unique], "uniqueName": unique},
        "mainLeafletId": lid,
        "mainLeafletPageIndex": 0,
        "validFrom": valid[0],
        "validTo": valid[1],
        "pageCount": pages,
        "offerCount": 100,
    }


LEAFLETS: dict[str, list[dict[str, Any]]] = {
    "supermaerkte@12345": [
        _leaflet(900101, "rewe", CURRENT, 24),
        _leaflet(900102, "rewe", UPCOMING, 26),
        _leaflet(900103, "edeka", CURRENT),  # no EDEKA branch: left out
    ],
    "discounter@12345": [
        _leaflet(900201, "lidl", CURRENT, 60),
        _leaflet(900202, "lidl", UPCOMING, 58),
        _leaflet(900203, "penny", CURRENT),  # no Penny branch
        _leaflet(900205, "lidl", ENDED),  # ended
    ],
    "drogerie-gesundheit@12345": [_leaflet(900301, "rossmann", CURRENT, 20)],
    "discounter@12347": [
        _leaflet(900401, "netto-marken-discount", CURRENT, 40),
        _leaflet(900402, "norma", CURRENT, 16),
        _leaflet(900201, "lidl", CURRENT, 60),  # no Lidl branch at 12347
    ],
    # the same national Lidl leaflets at the other Lidl branch
    "discounter@12349": [
        _leaflet(900201, "lidl", CURRENT, 60),
        _leaflet(900202, "lidl", UPCOMING, 58),
    ],
}
PUBLISHERS = {
    "12345": ["rewe", "lidl", "rossmann"],
    "12347": ["netto-marken-discount"],  # NORMA has no single offers
    "12349": ["lidl"],
}

ALDI_HTML = """<html><body>
<div class="teaser"><img src="https://dm.emea.cms.aldi.cx/is/image/aldiprodeu/prospekte-opmp-kw45-1?wid=3240&amp;fmt=png-alpha">
<p>Prospekt der aktuellen Woche.</p><a href="https://prospekt.aldi-sued.de/kw45-26-op-mp">Prospekt ansehen</a></div>
<div class="teaser"><source srcset="https://dm.emea.cms.aldi.cx/is/image/aldiprodeu/prospekte-op-kw46%3A16-9?wid=992&amp;fit=constrain">
<p>Prospekt der nächsten Woche.</p><a href="https://prospekt.aldi-sued.de/kw46-26-op">Prospekt ansehen</a></div>
<a href="https://prospekt.aldi-sued.de/kw47-26-vop">Prospekt der übernächsten Woche</a>
<a href="https://prospekt.aldi-sued.de/kw44-26-op">vorige Woche</a>
<a href="https://prospekt.aldi-sued.de/kw60-26-op">kaputt</a>
<a href="https://prospekt.aldi-sued.de/reisemagazin-november-2026">Reisen</a>
<img src="https://dm.emea.cms.aldi.cx/is/image/aldiprodeu/prospekte-service-reise_2026_kw46%3A2-1?wid=700">
</body></html>"""


@pytest.fixture(autouse=True)
def clock(freezer) -> None:
    """The frozen test day (before the websocket token is made, it must not be from the
    future)."""
    freezer.move_to(NOW)


@pytest.fixture(autouse=True)
def no_delays(monkeypatch) -> None:
    """No politeness delays (the clock is frozen)."""
    monkeypatch.setattr(catalog, "REQUEST_DELAY", 0)
    monkeypatch.setattr(aldi, "REQUEST_DELAY", 0)


def _offer(offer_id: int, unique: str, product: str, price: float) -> dict[str, Any]:
    """A current catalog offer (short format, made up)."""
    return {
        "id": offer_id,
        "description": "Je 250 g",
        "product": {"id": offer_id, "name": product},
        "retailer": {"id": 1, "name": NAMES[unique], "uniqueName": unique},
        "brand": {"id": 1, "name": "Musterhof"},
        "unit": {"shortName": "kg", "id": 1, "name": "Kilogramm"},
        "price": price,
        "oldPrice": 0.0,
        "referencePrice": round(price * 4, 2),
        "volume": 0.25,
        "quantity": 1,
        "validFrom": CURRENT[0],
        "validTo": CURRENT[1],
    }


def _mock_marktguru(aioclient_mock: AiohttpClientMocker, leaflets=None) -> None:
    aioclient_mock.get(MARKTGURU_HOME, text=HOME_HTML)
    for zip_code, uniques in PUBLISHERS.items():
        aioclient_mock.get(
            PUBLISHERS_URL, params={"zipCode": zip_code}, json=publishers_answer(uniques)
        )
        for position, unique in enumerate(uniques):
            offers = [_offer(int(zip_code) * 10 + position, unique, "Butter", 1.79)]
            aioclient_mock.get(
                catalog_url(unique),
                params={"zipCode": zip_code},
                json={"totalResults": 1, "skippedResults": 0, "results": offers},
            )
    for key, results in (leaflets or LEAFLETS).items():
        industry, zip_code = key.split("@")
        aioclient_mock.get(
            leaflets_url(industry),
            params={"zipCode": zip_code},
            json={"totalResults": len(results), "skippedResults": 0, "results": results},
        )


def _calls(aioclient_mock: AiohttpClientMocker) -> list[str]:
    """marktguru / ALDI requests made (path + zip code), in order."""
    found = []
    for call in aioclient_mock.mock_calls:
        url = call[1]
        if url.host == "www.marktguru.de":
            found.append("home")
        elif url.host == "api.marktguru.de":
            found.append(f"{url.path.removeprefix('/api/v1')}@{url.query.get('zipCode')}")
        elif str(url) == LEAFLETS_PAGE_URL:
            found.append("aldi-leaflets")
    return found


def _leaflet_calls(aioclient_mock: AiohttpClientMocker) -> list[str]:
    return [c for c in _calls(aioclient_mock) if "/leaflets" in c]


async def _setup(hass: HomeAssistant, entry: MockConfigEntry, freezer, **options) -> Any:
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(NOW)
    assert await async_setup_component(hass, "homeassistant", {})
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def _user(
    hass: HomeAssistant, entry: MockConfigEntry, freezer, **options
) -> tuple[Any, dict[str, dict[str, Any]]]:
    """The fictional stores with marktguru on (option all_leaflets: default)."""
    options.setdefault(CONF_OFFERS_SOURCE, "marktguru")
    options.setdefault(CONF_WATCHLIST, "Butter")
    manager = await _setup(hass, entry, freezer, **options)
    branches: dict[str, dict[str, Any]] = {}
    for data in BRANCHES:
        saved = manager.save_branch(dict(data))
        branches[data.get("label") or saved["retailer"]] = saved
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
    await client.send_json({"id": 1, "type": f"{DOMAIN}/leaflets", **data})
    msg = await client.receive_json()
    assert msg["success"], msg
    return msg["result"]


def _ids(view: dict[str, Any]) -> list[int | str]:
    return [lf["leaflet_id"] for lf in view["leaflets"]]


# ----------------------------------------------------------------------
# Pure helpers
# ----------------------------------------------------------------------


def test_leaflet_links() -> None:
    """Every chain's own leaflet page is a plain https link (no request); regional
    variants use their chain's page; chains without a leaflet page of their own have none."""
    assert set(LEAFLET_LINKS) <= set(RETAILERS)
    for retailer, url in LEAFLET_LINKS.items():
        assert url.startswith("https://"), retailer
        assert leaflet_link(retailer) == url
    assert leaflet_link("lidl") == "https://www.lidl.de/c/online-prospekte/s10005610"
    assert leaflet_link("aldi-sued") == "https://www.aldi-sued.de/prospekte"
    assert leaflet_link("edeka-suedwest") == LEAFLET_LINKS["edeka"]
    for retailer in ("globus", "marktkauf", "dm-drogerie-markt", "unbekannt", None):
        assert leaflet_link(retailer) is None


def test_parse_aldi_leaflets() -> None:
    """ALDI SÜD's leaflet overview: the weekly leaflets of this and the next weeks
    (Monday to Saturday of the calendar week), the cover named after the week; ended
    weeks, broken weeks and special leaflets are left out."""
    found = parse_aldi_leaflets(ALDI_HTML, date(2026, 11, 4))
    assert [lf["leaflet_id"] for lf in found] == ["kw45-26-op-mp", "kw46-26-op", "kw47-26-vop"]
    current = found[0]
    assert current["valid_from"] == "2026-11-02" and current["valid_to"] == "2026-11-07"
    assert current["url"] == "https://prospekt.aldi-sued.de/kw45-26-op-mp"
    assert current["cover"].startswith(
        "https://dm.emea.cms.aldi.cx/is/image/aldiprodeu/prospekte-opmp-kw45-1?"
    )
    assert current["retailer"] == "aldi-sued" and current["source"] == "aldi_direct"
    assert current["name"] == "ALDI SÜD Prospekt KW 45"
    assert current["page_count"] is None
    # the next week's cover is in a srcset; the week after has none
    assert "prospekte-op-kw46%3A16-9" in found[1]["cover"]
    assert found[2]["cover"] is None
    assert found[2]["valid_from"] == "2026-11-16"
    # on Sunday the current week has ended
    later = parse_aldi_leaflets(ALDI_HTML, date(2026, 11, 8))
    assert [lf["leaflet_id"] for lf in later] == ["kw46-26-op", "kw47-26-vop"]
    assert parse_aldi_leaflets("<html>nichts</html>", date(2026, 11, 4)) == []


def test_leaflet_due_rules(hass: HomeAssistant) -> None:
    """When a leaflet list is asked again."""
    dt_util.set_default_time_zone(dt_util.get_time_zone("Europe/Berlin"))
    now = datetime.fromisoformat("2026-11-04T10:00:00+01:00")  # Wednesday
    today = date(2026, 11, 4)
    current = {"retailer": "lidl", "valid_from": "2026-11-02", "valid_to": "2026-11-07"}
    upcoming = {"retailer": "lidl", "valid_from": "2026-11-09", "valid_to": "2026-11-14"}

    def entry(fetched: datetime | None, items=None, tried=None, **extra) -> dict[str, Any]:
        return {
            "fetched": fetched.isoformat() if fetched else None,
            "tried": (tried or fetched or now).isoformat(),
            "retailers": ["lidl"],
            "items": items if items is not None else [current],
            **extra,
        }

    yesterday = now - timedelta(days=1)
    assert leaflet_due(None, ["lidl"], now, today)
    assert not leaflet_due(entry(yesterday), ["lidl"], now, today)
    # 3 days old
    assert leaflet_due(entry(now - timedelta(days=3)), ["lidl"], now, today)
    # another chain at the postcode (stores changed)
    assert leaflet_due(entry(yesterday), ["lidl", "norma"], now, today)
    # a chain without a current leaflet: after 24 hours
    assert not leaflet_due(entry(now - timedelta(hours=5), [upcoming]), ["lidl"], now, today)
    assert leaflet_due(entry(now - timedelta(hours=25), [upcoming]), ["lidl"], now, today)
    # never answered: again after 24 hours
    failed = entry(None, [], tried=now - timedelta(hours=2), error="kaputt")
    assert not leaflet_due(failed, ["lidl"], now, today)
    failed = entry(None, [], tried=now - timedelta(hours=24), error="kaputt")
    assert leaflet_due(failed, ["lidl"], now, today)
    # refused: never while paused
    paused = entry(now - timedelta(days=5), blocked_until=(now + timedelta(days=1)).isoformat())
    assert not leaflet_due(paused, ["lidl"], now, today)
    # Sunday / Monday: a leaflet for the new week, once a day
    sunday = datetime.fromisoformat("2026-11-08T07:00:00+01:00")
    saturday = sunday - timedelta(days=1)
    assert leaflet_due(entry(saturday), ["lidl"], sunday, date(2026, 11, 8))
    assert not leaflet_due(
        entry(saturday, [current, upcoming]), ["lidl"], sunday, date(2026, 11, 8)
    )
    asked_today = entry(saturday, tried=sunday - timedelta(hours=1))
    assert not leaflet_due(asked_today, ["lidl"], sunday, date(2026, 11, 8))
    monday = datetime.fromisoformat("2026-11-09T07:00:00+01:00")
    assert leaflet_due(entry(sunday, [current]), ["lidl"], monday, date(2026, 11, 9))


# ----------------------------------------------------------------------
# Refresh
# ----------------------------------------------------------------------


async def test_leaflets_of_all_branches(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client,
) -> None:
    """With marktguru: after the offers one leaflet list per (postcode, industry) of the
    saved branches – the chain without single offers (NORMA) first; the same leaflet at
    two postcodes is one entry with both branches; other chains and ended leaflets are
    left out; the panel gets page templates for viewer, zoom and thumbnails."""
    _mock_marktguru(aioclient_mock)
    manager, branches = await _user(hass, config_entry, freezer)
    assert leaflet_pairs(manager) == {
        ("12345", "supermaerkte"): ["rewe"],
        ("12345", "discounter"): ["lidl"],
        ("12345", "drogerie-gesundheit"): ["rossmann"],
        ("12347", "discounter"): ["netto-marken-discount", "norma"],
        ("12349", "discounter"): ["lidl"],
    }
    meta = await _refresh(hass)
    assert meta["status"] == "ok", meta
    calls = _calls(aioclient_mock)
    offers_end = max(i for i, c in enumerate(calls) if "/offers" in c)
    assert all(i > offers_end for i, c in enumerate(calls) if "/leaflets" in c)
    assert _leaflet_calls(aioclient_mock) == [
        "/industries/discounter/leaflets@12347",  # NORMA: leaflet images only
        "/industries/supermaerkte/leaflets@12345",
        "/industries/discounter/leaflets@12345",
        "/industries/drogerie-gesundheit/leaflets@12345",
        "/industries/discounter/leaflets@12349",
    ]
    assert meta["requests"] == len(calls)
    for call in aioclient_mock.mock_calls:
        assert "HA-Essensplaner/1.5" in (call[3] or {}).get("User-Agent", "")

    stored = manager.catalog.data["leaflets_by_zip"]
    rewe = stored["12345"]["supermaerkte"]
    assert rewe["retailers"] == ["rewe"] and rewe["error"] is None
    assert [lf["leaflet_id"] for lf in rewe["items"]] == [900101, 900102]
    assert set(rewe["items"][0]) <= set(catalog._LEAFLET_FIELDS)  # slim: no page links
    assert [lf["leaflet_id"] for lf in stored["12345"]["discounter"]["items"]] == [
        900201,
        900202,
    ]
    assert [lf["leaflet_id"] for lf in stored["12347"]["discounter"]["items"]] == [
        900401,
        900402,
    ]

    view = leaflets_view(manager)
    assert _ids(view) == [900101, 900102, 900201, 900202, 900301, 900401, 900402]
    lidl = next(lf for lf in view["leaflets"] if lf["leaflet_id"] == 900201)
    assert lidl["branch_ids"] == [branches["lidl"]["id"], branches["Lidl Arbeit"]["id"]]
    assert lidl["labels"][1] == "Lidl Arbeit"
    assert lidl["source"] == "marktguru" and lidl["store"] == "Lidl"
    assert (lidl["valid_from"], lidl["valid_to"]) == ("2026-11-02", "2026-11-07")
    assert lidl["current"] is True and lidl["page_count"] == 60 and lidl["page_base"] == 0
    template = lidl["page_url_template"]
    assert (
        template
        == "https://cdn.marktguru.de/api/v1/leaflets/900201/images/pages/{page}/medium.webp"
    )
    assert lidl["zoom_url_template"].endswith("/pages/{page}/large.webp")
    assert lidl["thumb_url_template"].endswith("/pages/{page}/small.webp")
    assert template.format(page=3).endswith("/pages/3/medium.webp")
    assert lidl["cover"].endswith("/900201/images/pages/0/small.webp")
    assert (
        len(lidl["pages"]) == 4 and lidl["url"] == "https://www.marktguru.de/leaflets/900201/page/0"
    )
    upcoming = next(lf for lf in view["leaflets"] if lf["leaflet_id"] == 900202)
    assert upcoming["current"] is False
    assert view["meta"]["marktguru"] and view["meta"]["all_leaflets"]
    assert not view["meta"]["aldi_direct"] and view["meta"]["count"] == 7
    assert view["meta"]["errors"] == []
    rewe_row = next(b for b in view["branches"] if b["retailer"] == "rewe")
    assert (rewe_row["count_current"], rewe_row["count_upcoming"], rewe_row["main"]) == (
        1,
        1,
        True,
    )
    assert rewe_row["link"] == LEAFLET_LINKS["rewe"]
    links = {link["retailer"]: link for link in view["links"]}
    assert set(links) == {"rewe", "lidl", "rossmann", "netto-marken-discount", "norma"}
    assert links["lidl"]["branch_ids"] == lidl["branch_ids"] and links["lidl"]["has_leaflets"]

    # time filter and branch filter
    current = leaflets_view(manager, when="current")
    assert _ids(current) == [900101, 900201, 900301, 900401, 900402]
    assert _ids(leaflets_view(manager, when="upcoming")) == [900102, 900202]
    only = leaflets_view(manager, branch_ids=[branches["Lidl Arbeit"]["id"]])
    assert _ids(only) == [900201, 900202]

    # the 1.4 leaflet tile of NORMA in the store view stays
    stores = {s["retailer"]: s for s in store_offers_view(manager)["stores"]}
    assert (
        stores["norma"]["leaflet_only"] and stores["norma"]["leaflets"][0]["leaflet_id"] == 900402
    )
    assert stores["norma"]["leaflets"][0]["pages"][0].endswith("/900402/images/pages/0/small.webp")
    assert not stores["lidl"]["leaflet_only"]

    # the websocket
    result = await _ws(hass, hass_ws_client, when="current")
    assert _ids(result) == [900101, 900201, 900301, 900401, 900402]

    # the daily check right after: the offers and the leaflets are fresh – nothing is sent
    aioclient_mock.mock_calls.clear()
    await async_refresh_catalog(hass, manager)
    assert _calls(aioclient_mock) == []
    # a new chain at a postcode already asked: its list is asked again soon
    manager.save_branch({"store": "Penny", "postcode": "12345", "street": "Lindenweg 7"})
    assert leaflet_due(
        manager.catalog.data["leaflets_by_zip"]["12345"]["discounter"],
        leaflet_pairs(manager)[("12345", "discounter")],
        dt_util.utcnow(),
        manager.today(),
    )

    # diagnostics: counts only, no postcodes
    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)
    info = diagnostics["offer_catalog"]
    assert info["leaflet_lists"] == 5 and info["leaflet_items"] == 9
    assert "12347" not in json.dumps(info) and "12349" not in json.dumps(info)


async def test_leaflet_budget_and_daily_check(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch,
) -> None:
    """At most MAX_LEAFLET_REQUESTS leaflet lists per run; the rest comes with the next
    daily check without asking the offers again; a new week asks again on Sunday."""
    monkeypatch.setattr(catalog, "MAX_LEAFLET_REQUESTS", 2)
    _mock_marktguru(aioclient_mock)
    manager, _ = await _user(hass, config_entry, freezer)
    await _refresh(hass)
    assert _leaflet_calls(aioclient_mock) == [
        "/industries/discounter/leaflets@12347",
        "/industries/supermaerkte/leaflets@12345",
    ]
    # the next check (offers still fresh): only the leaflet lists left over
    freezer.tick(timedelta(hours=2))
    aioclient_mock.mock_calls.clear()
    meta = await async_refresh_catalog(hass, manager)
    assert meta["catalog"]["status"] == "ok"
    assert _calls(aioclient_mock) == [
        "home",
        "/industries/discounter/leaflets@12345",
        "/industries/drogerie-gesundheit/leaflets@12345",
    ]
    aioclient_mock.mock_calls.clear()
    await async_refresh_catalog(hass, manager)
    assert _calls(aioclient_mock) == ["home", "/industries/discounter/leaflets@12349"]
    aioclient_mock.mock_calls.clear()
    await async_refresh_catalog(hass, manager)
    assert _calls(aioclient_mock) == []
    assert len(leaflets_view(manager)["leaflets"]) == 7

    # Thursday, Friday: fresh
    freezer.move_to(datetime.fromisoformat("2026-11-06T06:30:00+01:00"))
    aioclient_mock.mock_calls.clear()
    manager.catalog.data["last_success"] = dt_util.utcnow().isoformat()  # offers fresh
    await async_refresh_catalog(hass, manager)
    assert _leaflet_calls(aioclient_mock) == []


async def test_new_week_on_sunday(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Sunday: the lists without a leaflet for the new week are asked once; ended leaflets
    are pruned, the announced ones are still upcoming."""
    _mock_marktguru(aioclient_mock)
    manager, _ = await _user(hass, config_entry, freezer)
    freezer.move_to(datetime.fromisoformat("2026-11-06T10:00:00+01:00"))  # Friday
    await _refresh(hass)
    freezer.move_to(datetime.fromisoformat("2026-11-08T06:30:00+01:00"))  # Sunday
    # the offers are fresh: only the leaflets have their own rules
    manager.catalog.data["last_success"] = dt_util.utcnow().isoformat()
    aioclient_mock.mock_calls.clear()
    await catalog.async_refresh_leaflets(hass, manager)
    # REWE and Lidl announced the new week already, the others not
    assert _leaflet_calls(aioclient_mock) == [
        "/industries/discounter/leaflets@12347",
        "/industries/drogerie-gesundheit/leaflets@12345",
    ]
    aioclient_mock.mock_calls.clear()
    await catalog.async_refresh_leaflets(hass, manager)
    assert _leaflet_calls(aioclient_mock) == []  # once a day
    assert manager.catalog.prune(manager.today())
    stored = manager.catalog.data["leaflets_by_zip"]["12345"]["discounter"]["items"]
    assert [lf["leaflet_id"] for lf in stored] == [900202]
    view = leaflets_view(manager)
    assert _ids(view) == [900102, 900202]
    # 1.5.1: on Sunday the leaflets of the week starting tomorrow are this week's
    assert all(lf["current"] for lf in view["leaflets"])
    assert [lf["valid_from"] for lf in view["leaflets"]] == ["2026-11-09", "2026-11-09"]


async def test_option_off_and_marktguru_off(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Without the option all_leaflets only the chains without single offers get their
    leaflets (1.4); without marktguru there are no leaflet images, only the chains' links."""
    _mock_marktguru(aioclient_mock)
    manager, _ = await _user(hass, config_entry, freezer, **{CONF_ALL_LEAFLETS: False})
    await _refresh(hass)
    assert _leaflet_calls(aioclient_mock) == ["/industries/discounter/leaflets@12347"]
    view = leaflets_view(manager)
    assert _ids(view) == [900402]  # NORMA only (Netto has single offers)
    assert not view["meta"]["all_leaflets"]
    assert len(view["links"]) == 5
    assert set(manager.catalog.data["leaflets_by_zip"]) == {"12347"}

    # switched on: the next check asks the lists of the other branches
    hass.config_entries.async_update_entry(
        config_entry, options={**config_entry.options, CONF_ALL_LEAFLETS: True}
    )
    await hass.async_block_till_done()
    manager = config_entry.runtime_data
    aioclient_mock.mock_calls.clear()
    await async_refresh_catalog(hass, manager)
    assert _leaflet_calls(aioclient_mock) == [
        # NORMA's list again: Netto was not asked for (stores changed)
        "/industries/discounter/leaflets@12347",
        "/industries/supermaerkte/leaflets@12345",
        "/industries/discounter/leaflets@12345",
        "/industries/drogerie-gesundheit/leaflets@12345",
        "/industries/discounter/leaflets@12349",
    ]
    assert len(leaflets_view(manager)["leaflets"]) == 7

    # marktguru off: its leaflets go at once, the links stay
    hass.config_entries.async_update_entry(
        config_entry, options={**config_entry.options, CONF_OFFERS_SOURCE: "off"}
    )
    await hass.async_block_till_done()
    manager = config_entry.runtime_data
    assert manager.catalog.data["leaflets_by_zip"] == {}
    aioclient_mock.mock_calls.clear()
    await async_refresh_catalog(hass, manager)
    assert _calls(aioclient_mock) == []
    view = leaflets_view(manager)
    assert view["leaflets"] == [] and not view["meta"]["marktguru"]
    assert {link["retailer"] for link in view["links"]} == {
        "rewe",
        "lidl",
        "rossmann",
        "netto-marken-discount",
        "norma",
    }
    assert not any(link["has_leaflets"] for link in view["links"])


async def test_refused_leaflet_list_pauses_marktguru(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A refusal of a leaflet list between two offer refreshes pauses marktguru like any
    other marktguru request; a failing list keeps the leaflets fetched before."""
    _mock_marktguru(aioclient_mock)
    manager, _ = await _user(hass, config_entry, freezer)
    await _refresh(hass)
    freezer.tick(timedelta(days=1, hours=1))  # Thursday: the offers are fresh
    manager.catalog.data["last_success"] = dt_util.utcnow().isoformat()
    store = manager.catalog.data["leaflets_by_zip"]
    # the Rossmann list had no current leaflet: due after 24 hours; it fails
    store["12345"]["drogerie-gesundheit"]["items"] = []
    aioclient_mock.clear_requests()
    aioclient_mock.get(MARKTGURU_HOME, text=HOME_HTML)
    aioclient_mock.get(leaflets_url("drogerie-gesundheit"), status=500)
    await catalog.async_refresh_leaflets(hass, manager)
    entry = store["12345"]["drogerie-gesundheit"]
    assert entry["error"] and entry["fetched"]  # the earlier answer stays
    assert catalog.marktguru_paused(manager) is None
    view = leaflets_view(manager)
    assert view["meta"]["errors"] and "Rossmann" in view["meta"]["errors"][0]
    # a day later it is asked again and refused: marktguru pauses
    freezer.tick(timedelta(days=1, hours=1))
    manager.catalog.data["last_success"] = dt_util.utcnow().isoformat()
    aioclient_mock.clear_requests()
    aioclient_mock.get(MARKTGURU_HOME, text=HOME_HTML)
    aioclient_mock.get(leaflets_url("drogerie-gesundheit"), status=429)
    await catalog.async_refresh_leaflets(hass, manager)
    assert catalog.marktguru_paused(manager) is not None
    aioclient_mock.mock_calls.clear()
    await catalog.async_refresh_leaflets(hass, manager)
    assert _calls(aioclient_mock) == []


# ----------------------------------------------------------------------
# ALDI SÜD's own leaflet list
# ----------------------------------------------------------------------


async def test_aldi_direct_leaflets(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """With the ALDI SÜD option and without marktguru: one request to ALDI SÜD's leaflet
    overview, the leaflets as tiles with cover and link (no page images); not asked again
    while fresh; a refusal pauses it. With marktguru's leaflets of every branch it is not
    asked at all."""
    aioclient_mock.get(
        ALDI_SEARCH_URL, json=json.loads((FIXTURES / "aldi_weekly_offers.json").read_text())
    )
    aioclient_mock.get(LEAFLETS_PAGE_URL, text=ALDI_HTML)
    manager = await _setup(hass, config_entry, freezer, **{CONF_ALDI_ONLINE: True})
    aldi_branch = manager.save_branch(
        {
            "store": "Aldi Süd",
            "street": "Lindenweg 5",
            "postcode": "12345",
            "aldi_service_point": "B999",
        }
    )
    manager.save_branch({"store": "Lidl", "postcode": "12345", "street": "Lindenweg 2"})
    meta = await _refresh(hass)
    assert meta["status"] == "ok", meta
    assert _calls(aioclient_mock).count("aldi-leaflets") == 1
    request = next(c for c in aioclient_mock.mock_calls if str(c[1]) == LEAFLETS_PAGE_URL)
    assert "HA-Essensplaner/1.5" in request[3]["User-Agent"]
    view = leaflets_view(manager)
    assert view["meta"]["aldi_direct"] and not view["meta"]["marktguru"]
    assert _ids(view) == ["kw45-26-op-mp", "kw46-26-op", "kw47-26-vop"]
    first = view["leaflets"][0]
    assert first["source"] == "aldi_direct" and first["branch_ids"] == [aldi_branch["id"]]
    assert first["url"] == "https://prospekt.aldi-sued.de/kw45-26-op-mp"
    assert first["current"] and first["page_count"] is None
    assert first["page_url_template"] is None and first["pages"] == [first["cover"]]
    assert [lf["current"] for lf in view["leaflets"]] == [True, False, False]
    assert {link["retailer"] for link in view["links"]} == {"aldi-sued", "lidl"}

    # fresh: the next refresh does not ask again
    freezer.tick(timedelta(hours=2))
    aioclient_mock.mock_calls.clear()
    await _refresh(hass)
    assert "aldi-leaflets" not in _calls(aioclient_mock)

    # 3 days later the overview refuses: paused 7 days, the leaflets stay
    freezer.tick(timedelta(days=3))
    aioclient_mock.clear_requests()
    aioclient_mock.get(
        ALDI_SEARCH_URL, json=json.loads((FIXTURES / "aldi_weekly_offers.json").read_text())
    )
    aioclient_mock.get(LEAFLETS_PAGE_URL, status=403)
    await _refresh(hass)
    entry = manager.catalog.data["leaflets_direct"]["aldi-sued"]
    assert entry["blocked_until"] and entry["error"]
    assert entry["items"]  # kept (pruned when they end)
    aioclient_mock.mock_calls.clear()
    await catalog.async_refresh_leaflets(hass, manager)
    assert _calls(aioclient_mock) == []

    # ALDI SÜD switched off: its leaflets go
    hass.config_entries.async_update_entry(
        config_entry, options={**config_entry.options, CONF_ALDI_ONLINE: False}
    )
    await hass.async_block_till_done()
    manager = config_entry.runtime_data
    assert "aldi-sued" not in manager.catalog.data["leaflets_direct"]
    assert leaflets_view(manager)["leaflets"] == []


async def test_aldi_direct_not_with_marktguru_leaflets(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """marktguru brings the leaflets of every branch (also ALDI SÜD): the overview of
    ALDI SÜD is not asked."""
    _mock_marktguru(aioclient_mock)
    aioclient_mock.get(
        ALDI_SEARCH_URL, json=json.loads((FIXTURES / "aldi_weekly_offers.json").read_text())
    )
    aioclient_mock.get(LEAFLETS_PAGE_URL, text=ALDI_HTML)
    manager, _ = await _user(hass, config_entry, freezer, **{CONF_ALDI_ONLINE: True})
    manager.save_branch(
        {
            "store": "Aldi Süd",
            "street": "Lindenweg 5",
            "postcode": "12345",
            "aldi_service_point": "B999",
        }
    )
    await _refresh(hass)
    assert "aldi-leaflets" not in _calls(aioclient_mock)
    assert not leaflets_view(manager)["meta"]["aldi_direct"]


# ----------------------------------------------------------------------
# Service
# ----------------------------------------------------------------------


async def test_get_leaflets_service(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """get_leaflets: all leaflets, those of a chain (every branch), of one branch (own
    label) or none for a chain without a saved branch."""
    _mock_marktguru(aioclient_mock)
    await _user(hass, config_entry, freezer)
    await _refresh(hass)

    async def call(**data: Any) -> dict[str, Any]:
        return await hass.services.async_call(
            DOMAIN, "get_leaflets", data, blocking=True, return_response=True
        )

    everything = await call()
    assert len(everything["leaflets"]) == 7 and everything["links"]
    assert _ids(await call(store="Lidl")) == [900201, 900202]
    assert _ids(await call(store="Lidl Arbeit", when="upcoming")) == [900202]
    assert _ids(await call(store="Hauptladen", when="current")) == [900101]
    assert (await call(store="Kaufland"))["leaflets"] == []
    with pytest.raises(ServiceValidationError):
        await call(store="Gibtsnicht Markt")


async def test_leaflets_kept_per_chain(hass: HomeAssistant) -> None:
    """Per chain and list at most LEAFLET_KEEP leaflets that have not ended – the latest
    ones (this and the next week before old long-running special leaflets) – stored by
    start; the same leaflet twice is kept once."""
    dt_util.set_default_time_zone(dt_util.get_time_zone("Europe/Berlin"))
    store = catalog.OfferCatalog(hass, "leaflet-test")
    weeks = [
        (f"2026-10-{day:02d}T23:00:00Z", "2026-12-31T22:59:59Z") for day in (4, 11, 18, 25)
    ] + [CURRENT, UPCOMING, ("2026-11-15T23:00:00Z", "2026-11-21T22:59:59Z"), ENDED]
    raw = [_leaflet(900500 + i, "lidl", valid) for i, valid in enumerate(weeks)]
    raw.append(_leaflet(900505, "lidl", UPCOMING))  # the same leaflet again

    class FakeClient:
        requests = 0

        async def async_leaflets(self, industry: str, zip_code: str) -> list[dict[str, Any]]:
            self.requests += 1
            return [lf for r in raw if (lf := catalog.parse_leaflet(r)) is not None]

    client = FakeClient()
    errors: list[str] = []
    answered = await catalog._async_all_leaflets(
        client, store, {("12345", "discounter"): ["lidl"]}, NOW, date(2026, 11, 4), errors
    )
    assert answered == {("12345", "discounter")} and client.requests == 1 and errors == []
    items = store.data["leaflets_by_zip"]["12345"]["discounter"]["items"]
    assert [lf["leaflet_id"] for lf in items] == [
        900501,
        900502,
        900503,
        900504,
        900505,
        900506,
    ]
