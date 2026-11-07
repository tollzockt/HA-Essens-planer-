"""1.4 phase B: chain sources – ALDI SÜD prices / reduced articles / weekly offers and the
offers of the user's EDEKA market (all HTTP mocked with answers shaped like the live ones of
11/2026, trimmed: tests/fixtures/*.json)."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.essensplaner import aldi, articles, edeka, rewe
from custom_components.essensplaner.aldi import (
    SEARCH_URL as ALDI_SEARCH_URL,
    SERVICE_POINTS_URL,
    AldiUnexpected,
    async_fetch_aldi_offers,
    async_refresh_aldi_prices,
)
from custom_components.essensplaner.const import (
    CONF_ALDI_ONLINE,
    CONF_EDEKA_OFFERS,
    CONF_WATCHLIST,
    DOMAIN,
    HTTP_USER_AGENT,
)
from custom_components.essensplaner.edeka import (
    MARKETS_URL as EDEKA_MARKETS_URL,
    OFFERS_URL as EDEKA_OFFERS_URL,
    EdekaUnexpected,
    async_fetch_edeka_offers,
    async_refresh_edeka_offers,
)
from custom_components.essensplaner.offers import key_only_as_modifier
from custom_components.essensplaner.online_prices import (
    SourceBlocked,
    SourceUnexpected,
    best_product,
    reduced_products,
)
from custom_components.essensplaner.stores import LEARNED_SOURCES

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime.fromisoformat("2026-11-04T10:00:00+01:00")  # Wednesday
EDEKA_MARKET = "2644015"  # EDEKA Hoffmann, Landblum 1, 56593 Horhausen
ALDI_STORE = "B402"


def _load(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def clock(freezer) -> None:
    """The frozen test day (before the websocket token is made, it must not be from the
    future)."""
    freezer.move_to(NOW)


@pytest.fixture
def berlin():
    """Local dates are German dates (the parsers without a running Home Assistant)."""
    old = dt_util.get_default_time_zone()
    dt_util.set_default_time_zone(dt_util.get_time_zone("Europe/Berlin"))
    yield
    dt_util.set_default_time_zone(old)


@pytest.fixture(autouse=True)
def no_delays(monkeypatch) -> None:
    """No politeness delays (the clock is frozen), few search terms."""
    monkeypatch.setattr(aldi, "REQUEST_DELAY", 0)
    monkeypatch.setattr(aldi, "MAX_TERMS", 3)
    monkeypatch.setattr(edeka, "REQUEST_DELAY", 0)
    monkeypatch.setattr(rewe, "REQUEST_DELAY", 0)
    monkeypatch.setattr(articles, "LIVE_MIN_INTERVAL", 0)


async def _setup(
    hass: HomeAssistant, entry: MockConfigEntry, freezer, **options
) -> MockConfigEntry:
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(NOW)
    assert await async_setup_component(hass, "homeassistant", {})
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _calls(aioclient_mock: AiohttpClientMocker, url: str) -> list:
    return [c for c in aioclient_mock.mock_calls if str(c[1]).startswith(url)]


def _mock_aldi(aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(SERVICE_POINTS_URL, json=_load("aldi_service_points"))
    for term, name in (
        ("Butter", "aldi_search_butter"),
        ("Milch", "aldi_search_milch"),
        ("Eier", "aldi_search_eier"),
        ("Hackfleisch", "aldi_search_hackfleisch"),
    ):
        aioclient_mock.get(ALDI_SEARCH_URL, params={"q": term}, json=_load(name))


async def _aldi_entry(
    hass: HomeAssistant, entry: MockConfigEntry, freezer, enabled: bool = True, **branch: Any
) -> MockConfigEntry:
    options: dict[str, Any] = {CONF_WATCHLIST: "Butter, Milch, Eier"}
    if enabled:
        options[CONF_ALDI_ONLINE] = True
    await _setup(hass, entry, freezer, **options)
    entry.runtime_data.save_branch(
        {"store": "Aldi Süd", "postcode": "53567", "street": "Zum Jägertal 1", **branch}
    )
    return entry


async def _edeka_entry(
    hass: HomeAssistant, entry: MockConfigEntry, freezer, enabled: bool = True, link: bool = True
) -> MockConfigEntry:
    options: dict[str, Any] = {CONF_WATCHLIST: "Milch, Kartoffeln, Möhren"}
    if enabled:
        options[CONF_EDEKA_OFFERS] = True
    await _setup(hass, entry, freezer, **options)
    data: dict[str, Any] = {"store": "EDEKA", "postcode": "56593", "street": "Landblum 1"}
    if link:
        data["edeka_market_id"] = EDEKA_MARKET
    entry.runtime_data.save_branch(data)
    return entry


async def _call(hass: HomeAssistant, service: str, **data: Any) -> Any:
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


# ----------------------------------------------------------------------
# ALDI SÜD: parsers
# ----------------------------------------------------------------------


def test_aldi_parse_products() -> None:
    """Cents, was-price, pack from sellingSize / name, base price, deposit, brand, image."""
    butter = aldi.parse_products(_load("aldi_search_butter"), "Butter")
    first = butter[0]
    assert (first["id"], first["product_id"]) == (
        "aldi_000000000000202682",
        "000000000000202682",
    )
    assert (first["title"], first["product"], first["brand"]) == (
        "Milsani Deutsche Markenbutter 250 g",
        "Deutsche Markenbutter 250 g",
        "Milsani",
    )
    # reduced: 1,15 € instead of 1,19 € ("wasPriceDisplay")
    assert (first["price"], first["regular_price"], rewe.learn_price(first)) == (1.15, 1.19, 1.19)
    assert (first["pack_amount"], first["pack_unit"]) == (250.0, "g")
    assert first["unit_price"] == pytest.approx(0.0046)  # "4,60 €/1 kg"
    assert (first["retailer"], first["store"], first["source"]) == (
        "aldi-sued",
        "ALDI SÜD",
        "aldi_online",
    )
    assert first["image"].startswith("https://dm.emea.cms.aldi.cx/")
    assert "{width}" not in first["image"] and first["image"].endswith(
        "/milsani-deutsche-markenbutter-250-g"
    )
    assert butter[1]["regular_price"] is None  # Meersalzbutter: not reduced

    # no sellingSize and no base price: pack from the name, unit price computed
    milk = aldi.parse_products(_load("aldi_search_milch"), "Milch")[0]
    assert (milk["title"], milk["price"]) == ("Milsani Frische Vollmilch 3,5 % 1 l", 0.95)
    assert (milk["pack_amount"], milk["pack_unit"], milk["unit_price"]) == (1000.0, "ml", 0.00095)
    eggs = aldi.parse_products(_load("aldi_search_eier"), "Eier")
    assert (eggs[0]["pack_amount"], eggs[0]["pack_unit"]) == (10.0, "Stück")  # "10er-Packung"
    assert eggs[2]["pack_amount"] is None  # Weihnachts-Sticker

    weekly = {p["product"]: p for p in aldi.parse_products(_load("aldi_weekly_offers"))}
    lemons = weekly["Kleine Schätze Zitronen, Stück"]
    assert (lemons["pack_amount"], lemons["pack_unit"], lemons["price"]) == (1.0, "Stück", 0.59)
    cola = weekly["Cola Original 1,25 l"]
    # the bottle deposit is never part of the price, only a note
    assert (cola["price"], cola["regular_price"], cola["deposit"]) == (1.19, 1.59, 0.25)
    assert cola["description"] == "1,25 l · zzgl. 0,25 € Pfand"
    assert cola["brand"] == "Coca-Cola"
    pads = weekly["Slipeinlagen, Cotton Feel Normal 56 Stück"]
    assert (pads["pack_amount"], pads["pack_unit"]) == (56.0, "Stück")
    assert weekly["Orangen 2 kg"]["pack_amount"] == 2000.0
    assert weekly["Frischkäse 195 g, Original"]["regular_price"] is None


def test_aldi_parse_other_answers() -> None:
    """Service points, the weekly category, unexpected structures."""
    stores = aldi.parse_service_points(_load("aldi_service_points"))
    assert [s["id"] for s in stores] == ["B402", "B455", "B456"]
    assert stores[0] == {
        "id": "B402",
        "name": "ALDI SÜD",
        "street": "Zum Jägertal 1",
        "postcode": "53567",
        "city": "Asbach",
        "label": "ALDI SÜD, Zum Jägertal 1, 53567 Asbach",
        "lat": 50.656182,
        "lon": 7.418499,
        "distance_km": 4.1,
    }
    assert aldi.weekly_category(_load("aldi_category_tree")) == "1588161426582123"
    assert aldi.weekly_category({"data": []}) is None
    assert aldi.total_count(_load("aldi_weekly_offers")) == 9
    assert aldi.display_price("1,19 €") == 1.19
    assert aldi.display_price(None) is None
    for data in ({"foo": 1}, [], "text", None):
        with pytest.raises(AldiUnexpected):
            aldi.parse_products(data)
    with pytest.raises(AldiUnexpected):
        aldi.parse_products({"data": [{"name": "x"}, {"name": "y"}, {"sku": "1"}]})
    assert aldi.parse_products({"meta": {}, "data": []}) == []


def test_reduced_products_and_best_product() -> None:
    """A reduced product counts with its regular price; reduced ones become offers."""
    minced = aldi.parse_products(_load("aldi_search_hackfleisch"), "Hackfleisch")
    # cheapest regular price per kg: the XXL pack (6,61 €/kg), not the reduced 500 g (5,79 €)
    assert best_product(minced, "hackfleisch")["product"] == "Hackfleisch gemischt XXL 800 g"
    assert [p["product"] for p in reduced_products(minced, "hackfleisch")] == [
        "Hackfleisch vom Rind 500 g"
    ]
    assert reduced_products(minced, "butter") == []


def test_learned_source_ranking() -> None:
    """ALDI SÜD online prices are trusted like REWE's, before leaflet prices."""
    assert LEARNED_SOURCES.index("aldi_online") < LEARNED_SOURCES.index("leaflet")
    assert LEARNED_SOURCES[0] == "rewe_online"


# ----------------------------------------------------------------------
# ALDI SÜD: off by default, refresh, backoff
# ----------------------------------------------------------------------


async def test_aldi_off_by_default(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    hass_ws_client,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Without the option nothing is sent to ALDI SÜD (refresh, schedule, live, offers)."""
    entry = await _aldi_entry(hass, config_entry, freezer, enabled=False)
    manager = entry.runtime_data
    assert articles.LIVE_PROVIDERS["aldi-sued"] is aldi.async_aldi_live
    status = await async_refresh_aldi_prices(hass, manager, force=True)
    assert (status["status"], status["enabled"], status["experimental"]) == ("off", False, True)
    assert "aus" in status["message"]
    assert await async_fetch_aldi_offers(hass, manager) == (
        [],
        {"status": "off", "count": 0, "errors": [], "service_point": None},
    )
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "refresh_prices", source="aldi")
    assert err.value.translation_key == "aldi_disabled"
    assert (await manager.async_search_articles_live("Butter"))["live"] is False

    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/data"})
    msg = await client.receive_json()
    sources = msg["result"]["economy"]["price_sources"]
    assert (sources["aldi"]["status"], sources["edeka"]["status"]) == ("off", "off")
    assert sources["rewe"]["status"] == "off"

    minute = sum(ord(c) for c in entry.entry_id) % 50 + 5
    tz = dt_util.get_time_zone("Europe/Berlin")
    for hour, mins in ((4, minute), (4, (minute + 30) % 60), (6, (minute + 5) % 60)):
        target = datetime(2026, 11, 5, hour, mins, 1, tzinfo=tz)
        freezer.move_to(target)
        async_fire_time_changed(hass, target)
        await hass.async_block_till_done()
    assert aioclient_mock.call_count == 0
    assert "aldi" not in manager.price_sources_meta


async def test_aldi_refresh_learns_prices_and_offers(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Nearest service point (stored on the branch), regular prices, reduced = offers."""
    entry = await _aldi_entry(hass, config_entry, freezer, lat=50.6201, lon=7.4312)
    manager = entry.runtime_data
    branch = manager.get_main_branch()
    status = aldi.aldi_status(manager)
    assert (status["status"], status["service_point"], status["branch_id"]) == (
        "pending",
        None,
        branch["id"],
    )
    assert "Noch nicht abgerufen" in status["message"]
    _mock_aldi(aioclient_mock)

    status = await async_refresh_aldi_prices(hass, manager)
    assert status["status"] == "ok"
    assert (status["service_point"], status["searched"], status["learned"]) == (ALDI_STORE, 3, 3)
    assert status["offers"] == 1
    assert status["store_label"] == "ALDI SÜD, Zum Jägertal 1, 53567 Asbach"
    assert "3 Preise gelernt, 1 reduzierte Artikel als Angebot." in status["message"]
    # one service point request at the branch (rounded), then one search per term
    points = _calls(aioclient_mock, SERVICE_POINTS_URL)
    assert len(points) == 1
    assert (points[0][1].query["latitude"], points[0][1].query["longitude"]) == (
        "50.6201",
        "7.4312",
    )
    searches = _calls(aioclient_mock, ALDI_SEARCH_URL)
    assert [c[1].query["q"] for c in searches] == ["Butter", "Milch", "Eier"]
    query = searches[0][1].query
    assert (query["servicePoint"], query["limit"], query["serviceType"], query["currency"]) == (
        ALDI_STORE,
        "24",
        "walk-in",
        "EUR",
    )
    assert searches[0][3]["User-Agent"] == HTTP_USER_AGENT
    assert manager.get_branch(branch["id"])["aldi_service_point"] == ALDI_STORE

    learned = manager.store_prices_learned["aldi-sued"]
    butter = learned["butter"]
    # the reduced Markenbutter (1,15 €) is learned with its regular price 1,19 €
    assert (butter["price"], butter["amount"], butter["source"], butter["ref"]) == (
        1.19,
        250.0,
        "aldi_online",
        "000000000000202682",
    )
    assert (learned["milch"]["price"], learned["ei"]["price"]) == (0.85, 2.99)
    entry_price = manager.store_book("aldi-sued").lookup("Butter")
    assert (entry_price.price, entry_price.source) == (1.19, "aldi_online")

    offers = [o for o in manager.offers if o["source"] == "aldi_online"]
    assert len(offers) == 1
    offer = offers[0]
    assert (offer["product"], offer["price"], offer["old_price"]) == (
        "Deutsche Markenbutter 250 g",
        1.15,
        1.19,
    )
    assert (offer["valid_from"], offer["valid_to"]) == ("2026-11-04", "2026-11-07")  # Saturday
    assert offer["keys"] == ["butter"]
    assert offer["branches"] == [branch["id"]]
    assert manager.offers_meta == {}  # marktguru's meta is untouched

    # fresh: the next check sends nothing; the stored service point is used later on
    await async_refresh_aldi_prices(hass, manager)
    assert aioclient_mock.call_count == 4
    freezer.move_to(NOW + timedelta(days=8))
    aioclient_mock.clear_requests()
    _mock_aldi(aioclient_mock)
    assert (await async_refresh_aldi_prices(hass, manager))["status"] == "ok"
    assert _calls(aioclient_mock, SERVICE_POINTS_URL) == []
    assert len(_calls(aioclient_mock, ALDI_SEARCH_URL)) == 3


async def test_aldi_service_point_from_home_zone(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A branch without coordinates: the store nearest to home is used."""
    entry = await _aldi_entry(hass, config_entry, freezer)
    manager = entry.runtime_data
    await hass.config.async_update(latitude=50.6302, longitude=7.4441)
    await hass.async_block_till_done()
    _mock_aldi(aioclient_mock)
    status = await async_refresh_aldi_prices(hass, manager)
    assert (status["status"], status["service_point"]) == ("ok", ALDI_STORE)
    point = _calls(aioclient_mock, SERVICE_POINTS_URL)[0][1].query
    assert (point["latitude"], point["longitude"]) == ("50.6302", "7.4441")


@pytest.mark.parametrize(
    ("kwargs", "status", "detail"),
    [
        ({"status": 403}, "blocked", "HTTP 403"),
        ({"status": 429}, "blocked", "HTTP 429"),
        (
            {
                "text": "<html><body>Access Denied</body></html>",
                "headers": {"Content-Type": "text/html"},
            },
            "blocked",
            "Webseite statt Daten",
        ),
        ({"status": 400}, "error", "HTTP 400"),
        (
            {"json": {"errors": [{"status": 400, "code": "3731", "message": "invalid limit"}]}},
            "error",
            "Fehler 3731",
        ),
        ({"json": {"foo": 1}}, "error", "unerwartete Antwort"),
    ],
)
async def test_aldi_blocked_backoff(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
    kwargs: dict,
    status: str,
    detail: str,
) -> None:
    """403/429/HTML: blocked; HTTP 400 / {errors} / other shapes: error – 7 days pause."""
    entry = await _aldi_entry(hass, config_entry, freezer, aldi_service_point=ALDI_STORE)
    manager = entry.runtime_data
    aioclient_mock.get(ALDI_SEARCH_URL, **kwargs)
    result = await async_refresh_aldi_prices(hass, manager, force=True)
    assert result["status"] == status
    assert detail in result["errors"][0]
    assert result["blocked_until"] == (dt_util.utcnow() + timedelta(days=7)).isoformat()
    assert "11.11.2026" in result["message"]
    assert len(_calls(aioclient_mock, ALDI_SEARCH_URL)) == 1
    # paused: no requests (refresh with force, live search, weekly offers)
    assert (await async_refresh_aldi_prices(hass, manager, force=True))["status"] == status
    live = await manager.async_search_articles_live("Butter")
    assert "pausiert bis 11.11.2026" in live["error"]
    assert (await async_fetch_aldi_offers(hass, manager))[1]["status"] == "blocked"
    assert len(_calls(aioclient_mock, ALDI_SEARCH_URL)) == 1


async def test_aldi_service_point_lookup_refused(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A refused store lookup pauses the source as well (nothing else is sent)."""
    entry = await _aldi_entry(hass, config_entry, freezer, lat=50.62, lon=7.43)
    manager = entry.runtime_data
    aioclient_mock.get(SERVICE_POINTS_URL, status=403)
    result = await async_refresh_aldi_prices(hass, manager)
    assert result["status"] == "blocked"
    assert result["blocked_until"] is not None
    assert _calls(aioclient_mock, ALDI_SEARCH_URL) == []
    assert "aldi_service_point" not in manager.get_main_branch()


async def test_aldi_weekly_offers(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """aldi_offers(): the "Wochenangebote" category page by page (for the offer catalog)."""
    entry = await _aldi_entry(hass, config_entry, freezer, aldi_service_point=ALDI_STORE)
    manager = entry.runtime_data
    weekly = _load("aldi_weekly_offers")
    first = {**weekly, "data": weekly["data"][:5]}
    second = {**weekly, "data": weekly["data"][5:]}
    aioclient_mock.get(ALDI_SEARCH_URL, params={"offset": "0"}, json=first)
    aioclient_mock.get(ALDI_SEARCH_URL, params={"offset": "5"}, json=second)
    offers, meta = await async_fetch_aldi_offers(hass, manager)
    assert (meta["status"], meta["count"], meta["service_point"]) == ("ok", 9, ALDI_STORE)
    calls = _calls(aioclient_mock, ALDI_SEARCH_URL)
    assert [c[1].query["offset"] for c in calls] == ["0", "5"]
    assert calls[0][1].query["categoryKey"] == "1588161426582123"
    assert calls[0][1].query["limit"] == "60"
    minced = next(o for o in offers if o["product"] == "Hackfleisch vom Rind 500 g")
    assert (minced["price"], minced["old_price"], minced["valid_to"], minced["weekly"]) == (
        4.59,
        5.79,
        "2026-11-07",
        True,
    )
    assert minced["source"] == "aldi_online"
    assert "keys" not in minced
    assert not [o for o in manager.offers if o["source"] == "aldi_online"]  # nothing stored


async def test_aldi_weekly_category_moved(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """No weekly offers under the known category: it is looked up in the category tree."""
    entry = await _aldi_entry(hass, config_entry, freezer, aldi_service_point=ALDI_STORE)
    tree = _load("aldi_category_tree")
    tree["data"][0]["key"] = "999"
    aioclient_mock.get(
        ALDI_SEARCH_URL,
        params={"categoryKey": "1588161426582123"},
        json={"meta": {"pagination": {"offset": 0, "limit": 60, "totalCount": 0}}, "data": []},
    )
    aioclient_mock.get(aldi.CATEGORY_TREE_URL, json=tree)
    aioclient_mock.get(
        ALDI_SEARCH_URL, params={"categoryKey": "999"}, json=_load("aldi_weekly_offers")
    )
    offers, meta = await async_fetch_aldi_offers(hass, entry.runtime_data)
    assert (meta["status"], len(offers)) == ("ok", 9)


async def test_aldi_live_article_search(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """ "Artikel hinzufügen" asks ALDI SÜD for an ALDI SÜD branch (option on)."""
    entry = await _aldi_entry(hass, config_entry, freezer, aldi_service_point=ALDI_STORE)
    manager = entry.runtime_data
    aioclient_mock.get(ALDI_SEARCH_URL, json=_load("aldi_search_butter"))
    response = await manager.async_search_articles_live("Butter")
    assert (response["live"], response["error"]) == (True, None)
    hits = {r["title"]: r for r in response["results"]}
    hit = hits["Milsani Deutsche Markenbutter 250 g"]
    assert (hit["price"], hit["provider"], hit["retailer"]) == (1.15, "aldi_online", "aldi-sued")
    # cached for an hour
    await manager.async_search_articles_live("butter")
    assert len(_calls(aioclient_mock, ALDI_SEARCH_URL)) == 1


async def test_find_aldi_stores(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    hass_ws_client,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """find_aldi_stores: coordinates, a known postcode, the branch; also with the option off."""
    entry = await _aldi_entry(hass, config_entry, freezer, enabled=False, lat=50.62, lon=7.43)
    manager = entry.runtime_data
    aioclient_mock.get(SERVICE_POINTS_URL, json=_load("aldi_service_points"))

    result = await _call(hass, "find_aldi_stores", lat=50.65, lon=7.42)
    assert result["location"] == {
        "lat": 50.65,
        "lon": 7.42,
        "source": "coordinates",
        "zip_code": None,
    }
    # nearest first (distance to the searched place, not to the interface's guess)
    assert [s["id"] for s in result["stores"]] == ["B402", "B456", "B455"]
    assert result["stores"][0]["distance_km"] == pytest.approx(0.6, abs=0.1)
    request = _calls(aioclient_mock, SERVICE_POINTS_URL)[0]
    assert request[3]["User-Agent"] == HTTP_USER_AGENT
    # default: the ALDI SÜD branch
    result = await _call(hass, "find_aldi_stores")
    assert result["location"]["source"] == "branch"
    # a postcode is located with a saved branch at that postcode
    result = await _call(hass, "find_aldi_stores", zip="53567")
    assert result["location"]["source"] == "postcode"
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "find_aldi_stores", zip="99999")
    assert err.value.translation_key == "aldi_postcode_unknown"
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "find_aldi_stores", zip="12")
    assert err.value.translation_key == "invalid_postcode"

    # a store used by a branch is marked; the panel's websocket
    branch = manager.get_main_branch()
    manager.save_branch({"id": branch["id"], "aldi_service_point": "B455"})
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/aldi_stores"})
    msg = await client.receive_json()
    assert msg["success"]
    assert {s["id"]: s["branch_id"] for s in msg["result"]["stores"]}["B455"] == branch["id"]
    await client.send_json({"id": 2, "type": f"{DOMAIN}/aldi_stores", "zip": "99999"})
    msg = await client.receive_json()
    assert (msg["success"], msg["error"]["code"]) == (False, "aldi_postcode_unknown")
    assert "Kartensuche" in msg["error"]["message"]

    # refused: a clear error, the price source is not paused by it
    aioclient_mock.clear_requests()
    aioclient_mock.get(SERVICE_POINTS_URL, status=403)
    with pytest.raises(HomeAssistantError) as err:
        await _call(hass, "find_aldi_stores", lat=50.65, lon=7.42)
    assert err.value.translation_key == "aldi_blocked"
    assert "aldi" not in manager.price_sources_meta


async def test_save_branch_validates_chain_ids(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """EDEKA market ids are digits, ALDI SÜD store numbers like B402; empty unlinks."""
    manager = setup_integration.runtime_data
    with pytest.raises(ServiceValidationError) as err:
        manager.save_branch({"store": "EDEKA", "edeka_market_id": "12a"})
    assert err.value.translation_key == "invalid_edeka_market"
    with pytest.raises(ServiceValidationError) as err:
        manager.save_branch({"store": "Aldi Süd", "aldi_service_point": "B 402!"})
    assert err.value.translation_key == "invalid_aldi_store"
    branch = manager.save_branch({"store": "EDEKA", "edeka_market_id": " 2644015 "})
    assert branch["edeka_market_id"] == "2644015"
    branch = await _call(hass, "save_branch", id=branch["id"], edeka_market_id="")
    assert branch["branch"]["edeka_market_id"] == ""
    aldi_branch = await _call(hass, "save_branch", store="Aldi Süd", aldi_service_point="B402")
    assert aldi_branch["branch"]["aldi_service_point"] == "B402"


# ----------------------------------------------------------------------
# EDEKA: parsers
# ----------------------------------------------------------------------


def test_edeka_parse_offers(berlin) -> None:
    """Leaflet week as local dates, NBSP base prices, deposits, multipacks, notes."""
    result = edeka.parse_offers(_load("edeka_offers"), EDEKA_MARKET)
    # gueltig_von / gueltig_bis are midnight UTC: 02.11. – 07.11. in Germany
    assert (result["valid_from"], result["valid_to"], result["count"]) == (
        "2026-11-02",
        "2026-11-07",
        14,
    )
    offers = {o["product"]: o for o in result["offers"]}
    spekulatius = offers["Butter-Spekulatius oder Butter-Mandel-Spekulatius"]
    assert (spekulatius["id"], spekulatius["brand"], spekulatius["price"]) == (
        "edeka_6447531",
        "EDEKA",
        1.99,
    )
    assert (spekulatius["pack_amount"], spekulatius["pack_unit"]) == (
        200.0,
        "g",
    )  # "je 200 g Beutel"
    assert spekulatius["unit_price"] == pytest.approx(0.00995)  # "1\xa0kg\xa0= €\xa09.95"
    assert spekulatius["loyalty_note"] == "PAYBACK-Punkte"
    assert spekulatius["loyalty"] is False  # the price applies to everyone
    assert (spekulatius["valid_from"], spekulatius["valid_to"]) == ("2026-11-02", "2026-11-07")
    assert spekulatius["image"].startswith("https://offer-images.api.edeka/")
    assert (spekulatius["retailer"], spekulatius["store"], spekulatius["source"]) == (
        "edeka",
        "EDEKA",
        "edeka",
    )
    assert spekulatius["category"] == "Knabbern & Naschen"
    assert spekulatius["market_id"] == EDEKA_MARKET

    water = offers["Vöslauer Mineralwasser"]
    assert (water["pack_amount"], water["pack_unit"]) == (9000.0, "ml")  # "je Packung = 6 x 1,5 l"
    assert (water["price"], water["deposit"]) == (3.99, 1.5)  # deposit is not in the price
    assert "zzgl. € 1.50 Pfand" in water["description"]
    beer = offers["Veltins Pilsener"]
    assert (beer["pack_amount"], beer["deposit"]) == (10000.0, 3.1)  # first of "20 x 0,5 l / …"
    assert beer["unit_price"] == pytest.approx(0.0011)  # first of "1 l = € 1.10 / € 1.39"
    babybel = offers["Mini Babybel Original, Balance, High Protein oder Mini Rolls"]
    assert (babybel["pack_amount"], babybel["loyalty"]) == (100.0, True)  # App-Preis
    assert babybel["loyalty_note"] == "Preis mit der EDEKA-App"
    leerdammer = offers["Leerdammer"]
    assert leerdammer["pack_amount"] is None  # "je 100 g - 150 g Packung"
    assert (leerdammer["unit_price_from"], leerdammer["highlight"]) == (True, "Superknüller")
    kohlrabi = offers["Kohlrabi"]
    assert (kohlrabi["origin"], kohlrabi["pack_amount"], kohlrabi["pack_unit"]) == (
        "Deutschland",
        1.0,
        "Stück",
    )
    assert kohlrabi["description"].startswith("Herkunft: Deutschland")
    carrots = offers["Möhren"]
    assert (carrots["brand"], carrots["origin"], carrots["pack_amount"]) == (
        "GUT & GÜNSTIG",
        "Deutschland",
        2000.0,
    )
    assert offers["Frisches Hähnchenbrustfilet"]["pack_amount"] == 100.0  # "je 100 g"
    softener = offers["Kuschelweich Weichspüler"]
    assert (softener["pack_amount"], softener["pack_unit"], softener["unit_price"]) == (
        38.0,
        "WL",
        0.05,
    )
    paper = offers["Toilettenpapier Kamille"]
    assert (paper["pack_amount"], paper["pack_unit"]) == (8.0, "Rolle")


def test_edeka_parse_helpers(berlin) -> None:
    """Epoch ms as local dates (also 23:00 UTC), base prices, deposits, packs, markets."""
    assert edeka.local_date(1794009600000) == "2026-11-07"  # 07.11. 00:00 UTC
    assert edeka.local_date(1794006000000) == "2026-11-07"  # 06.11. 23:00 UTC = 07.11. local
    assert edeka.local_date(None) is None
    assert edeka.basic_price("1\xa0kg\xa0= €\xa09.95") == (pytest.approx(0.00995), "g", False)
    assert edeka.basic_price("1\xa0kg\xa0= ab €\xa011.10")[2] is True
    assert edeka.basic_price("100 g = € 1.20")[:2] == (pytest.approx(0.012), "g")
    assert edeka.basic_price("1\xa0WA\xa0= €\xa00.05")[:2] == (0.05, "WL")
    assert edeka.basic_price(None) is None
    assert edeka.deposit("je 0,5 l Dose zzgl. € 0.25 Pfand") == (0.25, "je 0,5 l Dose")
    assert edeka.deposit("je 1 l Packung") == (None, "je 1 l Packung")
    assert edeka.pack_of("je 16 - 36 Stück Packung") is None  # a range of pieces
    assert edeka.pack_of("je 6 Stück = 540 g Glas / 250 g Abtropfg.") == (540.0, "g")
    assert edeka.pack_of("je 10 Stück Packung") == (10.0, "Stück")
    assert edeka.pack_of("je Stück") == (1.0, "Stück")
    assert edeka.pack_of("4 x 250 g = 1 kg Vorteilspackung") == (1000.0, "g")

    # "Butter-Spekulatius" is no butter, "Bio-Butter" is
    assert key_only_as_modifier("Butter-Spekulatius oder Butter-Mandel-Spekulatius", "butter")
    assert key_only_as_modifier("Butter-, Krusten- oder Kochschinken", "butter")
    assert not key_only_as_modifier("Bio-Butter", "butter")
    assert not key_only_as_modifier("Kräuter-/Knoblauchbutter 120 g", "butter")
    assert not key_only_as_modifier("H-Milch", "milch")
    # the description only names the kind of product, not what is in it
    kind = edeka._kind_text
    assert (
        kind({"description": "französischer Hartkäse, 50% Fett i. Tr."}) == "französischer Hartkäse"
    )
    assert kind({"description": "mit Röstzwiebeln und Käse, je 100 g"}) == ""
    assert kind({"description": "versch. Sorten, ohne Zucker, je 75 g Beutel"}) == ""
    assert kind({"description": "Ballaststoff Limo, Zero Zucker"}) == "Ballaststoff Limo"

    markets = edeka.parse_markets(_load("edeka_markets"))
    assert [m["id"] for m in markets] == ["2644015", "8000788", "10005029"]
    assert markets[0] == {
        "id": "2644015",
        "name": "EDEKA Hoffmann",
        "channel": "EDEKA",
        "street": "Landblum 1",
        "postcode": "56593",
        "city": "Horhausen",
        "label": "EDEKA Hoffmann, Landblum 1, 56593 Horhausen",
        "lat": 50.593412,
        "lon": 7.528812,
    }
    assert markets[1]["channel"] == "nah & gut"
    with pytest.raises(EdekaUnexpected):
        edeka.parse_markets({"foo": []})
    with pytest.raises(EdekaUnexpected):
        edeka.parse_offers({"anzahl": 0})
    assert edeka.parse_offers({"docs": [], "anzahl": 0})["offers"] == []


# ----------------------------------------------------------------------
# EDEKA: off by default, market search, refresh
# ----------------------------------------------------------------------


async def test_edeka_off_by_default(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Without the option nothing is fetched (refresh, schedule, catalog)."""
    entry = await _edeka_entry(hass, config_entry, freezer, enabled=False)
    manager = entry.runtime_data
    status = await async_refresh_edeka_offers(hass, manager, force=True)
    assert (status["status"], status["enabled"], status["experimental"]) == ("off", False, False)
    assert status["message"] == "EDEKA-Angebote sind aus (in den Optionen einschaltbar)."
    assert (await async_fetch_edeka_offers(hass, manager))[1]["status"] == "off"
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "refresh_prices", source="edeka")
    assert err.value.translation_key == "edeka_disabled"
    minute = sum(ord(c) for c in entry.entry_id) % 50 + 5
    target = datetime(
        2026, 11, 5, 6, (minute + 5) % 60, 1, tzinfo=dt_util.get_time_zone("Europe/Berlin")
    )
    freezer.move_to(target)
    async_fire_time_changed(hass, target)
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == 0


async def test_find_edeka_markets(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    hass_ws_client,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """find_edeka_markets: postcode of the EDEKA branch, linked market marked, errors."""
    entry = await _edeka_entry(hass, config_entry, freezer, enabled=False, link=False)
    manager = entry.runtime_data
    aioclient_mock.get(EDEKA_MARKETS_URL, json=_load("edeka_markets"))
    result = await _call(hass, "find_edeka_markets")
    assert result["zip_code"] == "56593"
    assert [(m["id"], m["branch_id"]) for m in result["markets"]] == [
        ("2644015", None),
        ("8000788", None),
        ("10005029", None),
    ]
    request = _calls(aioclient_mock, EDEKA_MARKETS_URL)[0]
    assert request[1].query["searchstring"] == "56593"
    assert request[3]["User-Agent"] == HTTP_USER_AGENT
    branch = manager.get_main_branch()
    manager.save_branch({"id": branch["id"], "edeka_market_id": EDEKA_MARKET})
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/edeka_markets", "zip": "56593"})
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"]["markets"][0]["branch_id"] == branch["id"]
    await client.send_json({"id": 2, "type": f"{DOMAIN}/edeka_markets", "zip": "1"})
    msg = await client.receive_json()
    assert (msg["success"], msg["error"]["code"]) == (False, "invalid_postcode")

    aioclient_mock.clear_requests()
    aioclient_mock.get(
        EDEKA_MARKETS_URL, text="<html></html>", headers={"Content-Type": "text/html"}
    )
    with pytest.raises(HomeAssistantError) as err:
        await _call(hass, "find_edeka_markets", zip="56593")
    assert err.value.translation_key == "edeka_blocked"
    assert "edeka" not in manager.price_sources_meta


async def test_edeka_refresh_keeps_matching_offers(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """The market's offers matching plan / watchlist go to the offers, for that branch."""
    entry = await _edeka_entry(hass, config_entry, freezer)
    manager = entry.runtime_data
    branch = manager.get_main_branch()
    other = manager.save_branch(
        {"store": "EDEKA", "postcode": "56305", "street": "Urbacher Straße 35"}
    )
    status = edeka.edeka_status(manager)
    assert (status["status"], status["market_id"]) == ("pending", EDEKA_MARKET)
    answer = _load("edeka_offers")
    # what is in a product is no offer of it: no onion offer
    answer["docs"].append(
        {
            **answer["docs"][4],
            "angebotid": 6447999,
            "titel": "Frische Bratwurst",
            "beschreibung": "mit Röstzwiebeln und Käse oder Chili-Cheese, je 100 g",
        }
    )
    aioclient_mock.get(EDEKA_OFFERS_URL, json=answer)
    manager.shopping_add("Zwiebeln")

    status = await async_refresh_edeka_offers(hass, manager)
    assert status["status"] == "ok"
    assert (status["count"], status["valid_from"], status["valid_to"]) == (
        15,
        "2026-11-02",
        "2026-11-07",
    )
    assert status["matched"] == 5
    assert "15 Angebote bis 07.11." in status["message"]
    calls = _calls(aioclient_mock, EDEKA_OFFERS_URL)
    assert len(calls) == 1
    assert (calls[0][1].query["marketId"], calls[0][1].query["limit"]) == (EDEKA_MARKET, "500")
    assert calls[0][3]["User-Agent"] == HTTP_USER_AGENT

    stored = {o["product"]: o for o in manager.offers if o["source"] == "edeka"}
    assert {"Bärenmarke Frische Milch", "Speisekartoffeln", "Möhren"} <= set(stored)
    assert {k: v["keys"] for k, v in stored.items()} == {
        "Frisches Hähnchenbrustfilet": ["haehnchenbrust"],  # a starter recipe ingredient
        "Bärenmarke Frische Milch": ["milch"],
        "Speisekartoffeln": ["kartoffel"],
        "Möhren": ["moehre"],
        "Président Meersalzbutter": ["butter"],
    }
    # not kept: what matches nothing, "Butter-Spekulatius" (no butter offer), a sausage
    # "mit Röstzwiebeln" (no onion offer)
    assert "Kuschelweich Weichspüler" not in stored
    milk = stored["Bärenmarke Frische Milch"]
    assert "milch" in milk["keys"]
    assert (milk["retailer"], milk["price"], milk["valid_to"]) == ("edeka", 1.11, "2026-11-07")
    assert milk["branches"] == [branch["id"]]  # this market's branch, not the other EDEKA
    assert other["id"] not in milk["branches"]
    assert manager.offers_meta == {}  # marktguru's status is untouched
    assert edeka.edeka_status(manager)["prices"] == len(stored)
    assert manager.offers_view(query="Milch", store="EDEKA")

    # fresh: nothing sent; a manual refresh at most once an hour
    await async_refresh_edeka_offers(hass, manager)
    again = await _call(hass, "refresh_prices", source="edeka")
    assert again["cooldown_until"]
    assert len(_calls(aioclient_mock, EDEKA_OFFERS_URL)) == 1
    freezer.tick(timedelta(hours=1))
    assert (await _call(hass, "refresh_prices", source="edeka"))["status"] == "ok"
    assert len(_calls(aioclient_mock, EDEKA_OFFERS_URL)) == 2
    # the next day (20 h later) the scheduled check fetches again
    freezer.tick(timedelta(hours=20))
    await async_refresh_edeka_offers(hass, manager)
    assert len(_calls(aioclient_mock, EDEKA_OFFERS_URL)) == 3

    # all offers for the catalog (nothing stored, no matching)
    offers, meta = await async_fetch_edeka_offers(hass, manager)
    assert (len(offers), meta["status"], meta["valid_to"]) == (15, "ok", "2026-11-07")
    assert all("keys" not in o for o in offers)
    assert offers[0]["branch_ids"] == [branch["id"]]


@pytest.mark.parametrize(
    ("kwargs", "status"),
    [
        ({"status": 403}, "blocked"),
        ({"text": "<!DOCTYPE html><html></html>"}, "blocked"),
        ({"json": {"error": "nope"}}, "error"),
    ],
)
async def test_edeka_blocked_keeps_offers(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
    kwargs: dict,
    status: str,
) -> None:
    """A refusal pauses EDEKA for 7 days; the offers fetched before stay."""
    entry = await _edeka_entry(hass, config_entry, freezer)
    manager = entry.runtime_data
    aioclient_mock.get(EDEKA_OFFERS_URL, json=_load("edeka_offers"))
    await async_refresh_edeka_offers(hass, manager)
    before = [o["id"] for o in manager.offers if o["source"] == "edeka"]
    assert before
    freezer.tick(timedelta(hours=21))
    aioclient_mock.clear_requests()
    aioclient_mock.get(EDEKA_OFFERS_URL, **kwargs)
    result = await async_refresh_edeka_offers(hass, manager)
    assert result["status"] == status
    assert result["blocked_until"] is not None
    assert [o["id"] for o in manager.offers if o["source"] == "edeka"] == before
    assert (await async_refresh_edeka_offers(hass, manager, force=True))["status"] == status
    assert len(_calls(aioclient_mock, EDEKA_OFFERS_URL)) == 1


async def test_edeka_week_ended_is_stale(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """After the leaflet week the offers are fetched again; expired ones are not kept."""
    entry = await _edeka_entry(hass, config_entry, freezer)
    manager = entry.runtime_data
    aioclient_mock.get(EDEKA_OFFERS_URL, json=_load("edeka_offers"))
    await async_refresh_edeka_offers(hass, manager)
    # Sunday morning: the stored week ended on Saturday, the same leaflet is still served
    freezer.move_to(datetime.fromisoformat("2026-11-08T06:30:00+01:00"))
    status = await async_refresh_edeka_offers(hass, manager)
    assert len(_calls(aioclient_mock, EDEKA_OFFERS_URL)) == 2
    assert status["count"] == 0
    assert not [o for o in manager.offers if o["source"] == "edeka"]


async def test_edeka_daily_schedule(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """The daily check at 06:xx fetches the offers when they are a day old."""
    entry = await _edeka_entry(hass, config_entry, freezer)
    aioclient_mock.get(EDEKA_OFFERS_URL, json=_load("edeka_offers"))
    minute = (sum(ord(c) for c in entry.entry_id) % 50 + 5 + 5) % 60
    tz = dt_util.get_time_zone("Europe/Berlin")

    async def check(day: int) -> int:
        target = datetime(2026, 11, day, 6, minute, 0, tzinfo=tz)
        freezer.move_to(target)
        async_fire_time_changed(hass, target)
        await hass.async_block_till_done()
        return len(_calls(aioclient_mock, EDEKA_OFFERS_URL))

    assert await check(5) == 1
    assert entry.runtime_data.price_sources_meta["edeka"]["status"] == "ok"
    assert await check(6) == 2


async def test_refresh_prices_needs_store(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
) -> None:
    """refresh_prices aldi / edeka need a branch of the chain (EDEKA: with a market id)."""
    await _setup(hass, config_entry, freezer, **{CONF_ALDI_ONLINE: True, CONF_EDEKA_OFFERS: True})
    manager = config_entry.runtime_data
    await hass.config.async_update(latitude=0, longitude=0)
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "refresh_prices", source="aldi")
    assert err.value.translation_key == "aldi_no_store"
    assert aldi.aldi_status(manager)["message"] == aldi.MSG_NO_STORE
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "refresh_prices", source="edeka")
    assert err.value.translation_key == "edeka_no_market"
    assert edeka.edeka_status(manager)["message"] == edeka.MSG_NO_MARKET


async def test_diagnostics_redact_chain_ids(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """EDEKA market ids and ALDI SÜD service points point to one shop: redacted."""
    from custom_components.essensplaner.diagnostics import async_get_config_entry_diagnostics

    entry = await _edeka_entry(hass, config_entry, freezer)
    manager = entry.runtime_data
    manager.save_branch(
        {"store": "Aldi Süd", "postcode": "53567", "aldi_service_point": ALDI_STORE}
    )
    aioclient_mock.get(EDEKA_OFFERS_URL, json=_load("edeka_offers"))
    await async_refresh_edeka_offers(hass, manager)
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    text = str(diagnostics)
    assert EDEKA_MARKET not in text
    assert ALDI_STORE not in text
    assert diagnostics["price_sources_meta"]["edeka"]["status"] == "ok"


def test_source_errors_are_typed() -> None:
    """The adapters' errors are the shared blocked / unexpected kinds (backoff)."""
    assert issubclass(aldi.AldiBlocked, SourceBlocked)
    assert issubclass(edeka.EdekaUnexpected, SourceUnexpected)
    assert issubclass(rewe.ReweBlocked, SourceBlocked)
    assert issubclass(rewe.ReweUnexpected, SourceUnexpected)
