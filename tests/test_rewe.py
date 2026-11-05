"""Experimental REWE online shop prices and market search (1.3, all HTTP mocked)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)
import voluptuous as vol

from custom_components.essensplaner import articles, rewe
from custom_components.essensplaner.const import (
    CONF_OFFERS_SOURCE,
    CONF_REWE_ONLINE,
    CONF_WATCHLIST,
    CONF_ZIP,
    DOMAIN,
    HTTP_USER_AGENT,
)
from custom_components.essensplaner.ingredients import ingredient_key
from custom_components.essensplaner.offers import MARKTGURU_API, MARKTGURU_HOME
from custom_components.essensplaner.rewe import (
    MARKETS_URL,
    SEARCH_URL,
    ReweUnexpected,
    async_refresh_rewe_prices,
    best_product,
    cents_to_eur,
    flat_price,
    learn_price,
    parse_grammage,
    parse_markets,
    parse_product,
    parse_products,
)

from .test_economy import HOME_HTML, _mg_offer

MARKET = "1940178"
NOW = datetime.fromisoformat("2026-11-04T10:00:00+01:00")


@pytest.fixture(autouse=True)
def no_delays(monkeypatch) -> None:
    """No politeness delays (the clock is frozen) and only the watchlist as search terms."""
    monkeypatch.setattr("custom_components.essensplaner.rewe.REQUEST_DELAY", 0)
    monkeypatch.setattr("custom_components.essensplaner.rewe.MAX_TERMS", 3)
    monkeypatch.setattr("custom_components.essensplaner.articles.LIVE_MIN_INTERVAL", 0)


def _product(
    pid: str,
    name: str,
    cents: int,
    grammage: str,
    regular: int | None = None,
    brand: str = "ja!",
) -> dict:
    """A product as the REWE shop API nests it."""
    pricing: dict = {"currentRetailPrice": cents, "currency": "EUR", "grammage": grammage}
    if regular:
        pricing["discount"] = {"regularPrice": regular, "validTo": "2026-11-08"}
    return {
        "id": pid,
        "productName": name,
        "brand": {"name": brand},
        "media": {
            "images": [{"_links": {"self": {"href": f"https://img.rewe-static.de/{pid}.png"}}}]
        },
        "_embedded": {
            "articles": [
                {
                    "id": f"a{pid}",
                    "gtin": "4388860000000",
                    "_embedded": {"listing": {"id": f"l{pid}", "pricing": pricing}},
                }
            ]
        },
    }


def _answer(*products: dict) -> dict:
    return {"_embedded": {"products": list(products)}, "totalCount": len(products)}


BUTTER = _answer(
    _product("B1", "ja! Deutsche Markenbutter", 199, "250g (1 kg = 7,96 €)"),
    _product(
        "B2", "Kerrygold Original Irische Butter", 279, "250g (1 kg = 11,16 €)", brand="Kerrygold"
    ),
    _product("B3", "ja! Butterkekse", 99, "200g (1 kg = 4,95 €)"),
    # reduced this week: the regular price counts (2,49 €)
    _product("B4", "Weidebutter", 149, "250g (1 kg = 5,96 €)", regular=249),
)
# flat shape (EUR as decimal number, cents as integer)
MILK = [
    {
        "id": "M1",
        "name": "ja! Frische Vollmilch 3,5%",
        "price": 1.19,
        "grammage": "1l (1 l = 1,19 €)",
    },
    {"id": "M2", "name": "Bärenmarke Frische Alpenmilch", "price": 179, "grammage": "1l"},
    {"id": "M3", "name": "Kokosmilch", "price": 249, "grammage": "400ml (1 l = 6,23 €)"},
]
GOUDA = {"products": [_product("G1", "ja! Gouda jung in Scheiben", 199, "400g (1 kg = 4,98 €)")]}
EMPTY = {"_embedded": {}, "totalCount": 0}
MARKETS = [
    {
        "wwIdent": MARKET,
        "companyName": "REWE Markt GmbH",
        "contactStreet": "Sendlinger Str. 2",
        "contactZipCode": "80331",
        "contactCity": "München",
        "location": {"latitude": 48.1361, "longitude": 11.5713},
    },
    {
        "id": "560812",
        "name": "REWE City",
        "address": {"street": "Tal 1", "zipCode": "80333", "city": "München"},
    },
    {"companyName": "ohne ID"},
    {"wwIdent": MARKET, "companyName": "doppelt"},
]


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


async def _rewe_entry(
    hass: HomeAssistant, entry: MockConfigEntry, freezer, enabled: bool = True
) -> MockConfigEntry:
    """REWE prices on (or off), a REWE main branch with market id, three watchlist terms."""
    options = {CONF_WATCHLIST: "Butter, Milch, Eier"}
    if enabled:
        options[CONF_REWE_ONLINE] = True
    await _setup(hass, entry, freezer, **options)
    entry.runtime_data.save_branch(
        {
            "store": "REWE",
            "postcode": "80331",
            "street": "Sendlinger Str. 2",
            "rewe_market_id": MARKET,
        }
    )
    return entry


@pytest.fixture
async def rewe_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer
) -> MockConfigEntry:
    """REWE prices on (set up before the websocket token is made, the clock is frozen)."""
    return await _rewe_entry(hass, config_entry, freezer)


@pytest.fixture
async def rewe_off_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer
) -> MockConfigEntry:
    """Like rewe_entry, but the REWE option is not set (default: off)."""
    return await _rewe_entry(hass, config_entry, freezer, enabled=False)


def _mock_searches(aioclient_mock: AiohttpClientMocker, butter: dict = BUTTER) -> None:
    for term, answer in (("Butter", butter), ("Milch", MILK), ("Eier", EMPTY), ("Gouda", GOUDA)):
        aioclient_mock.get(SEARCH_URL, params={"search": term}, json=answer)


def _calls(aioclient_mock: AiohttpClientMocker, url: str = SEARCH_URL) -> list:
    return [c for c in aioclient_mock.mock_calls if str(c[1]).startswith(url)]


# ----------------------------------------------------------------------
# Parsers
# ----------------------------------------------------------------------


def test_prices_and_grammage() -> None:
    """Cents -> EUR, flat prices, pack and base price from the grammage text."""
    assert cents_to_eur(199) == 1.99
    assert cents_to_eur("229") == 2.29
    assert cents_to_eur(0) is None
    assert cents_to_eur(None) is None
    assert flat_price(199) == 1.99  # integers are cents
    assert flat_price(1.99) == 1.99
    assert flat_price("1,99 €") == 1.99
    assert flat_price("199 ct") == 1.99
    assert flat_price(True) is None
    assert flat_price({"value": 2.5}) == 2.5

    pack, per = parse_grammage("500g (1 kg = 3,98 €)")
    assert pack == (500.0, "g")
    assert per[1] == "g" and per[0] == pytest.approx(0.00398)
    pack, per = parse_grammage("6x1,5l (1 l = 0,30 €)")
    assert pack == (9000.0, "ml") and per[0] == pytest.approx(0.0003)
    assert parse_grammage("250g (100 g = 0,92 €)")[1][0] == pytest.approx(0.0092)
    assert parse_grammage("10 Stück (1 Stück = 0,25 €)") == ((10.0, "Stück"), (0.25, "Stück"))
    # no pack before the brackets: the base price is not mistaken for the pack
    assert parse_grammage("je Stück (1 Stück = 0,59 €)") == (None, (0.59, "Stück"))
    pack, per = parse_grammage("ca. 400g", 3.96)
    assert pack == (400.0, "g") and per[0] == pytest.approx(0.0099)
    assert parse_grammage("") == (None, None)


def test_parse_nested_product() -> None:
    """The nested shop answer: name, price in cents, pack, base price, image, reduction."""
    product = parse_product(BUTTER["_embedded"]["products"][0], "Butter")
    assert product is not None
    assert (product["id"], product["product_id"], product["title"]) == (
        "rewe_B1",
        "B1",
        "ja! Deutsche Markenbutter",
    )
    assert (product["price"], product["regular_price"]) == (1.99, None)
    assert (product["pack_amount"], product["pack_unit"]) == (250.0, "g")
    assert product["unit_price"] == pytest.approx(0.00796)
    assert product["base_unit"] == "g"
    assert (product["retailer"], product["store"], product["source"]) == (
        "rewe",
        "REWE",
        "rewe_online",
    )
    assert product["brand"] == "ja!"
    assert product["image"] == "https://img.rewe-static.de/B1.png"
    assert product["description"] == "250g (1 kg = 7,96 €)"
    assert (product["valid_from"], product["valid_to"], product["query"]) == (None, None, "Butter")

    reduced = parse_product(BUTTER["_embedded"]["products"][3])
    assert (reduced["price"], reduced["regular_price"], learn_price(reduced)) == (1.49, 2.49, 2.49)
    # without a price or name nothing is returned
    broken = _product("X", "ja! Butter", 0, "250g")
    assert parse_product(broken) is None
    assert parse_product({"id": "1"}) is None
    assert parse_product("text") is None
    # base price from basePrice/baseUnit and the pack from the name
    raw = _product("Y", "ja! Bio Joghurt 500g", 99, "")
    raw["_embedded"]["articles"][0]["_embedded"]["listing"]["pricing"].update(
        {"basePrice": 198, "baseUnit": {"KGM": 1}}
    )
    yoghurt = parse_product(raw)
    assert (yoghurt["pack_amount"], yoghurt["pack_unit"]) == (500.0, "g")
    assert yoghurt["unit_price"] == pytest.approx(0.00198)


def test_parse_flat_products_and_shapes() -> None:
    """Flat products, other answer shapes; unknown structures raise."""
    products = parse_products(MILK, "Milch")
    assert [(p["title"], p["price"]) for p in products] == [
        ("ja! Frische Vollmilch 3,5%", 1.19),
        ("Bärenmarke Frische Alpenmilch", 1.79),
        ("Kokosmilch", 2.49),
    ]
    assert (products[0]["pack_amount"], products[0]["pack_unit"]) == (1000.0, "ml")
    assert products[1]["unit_price"] == pytest.approx(0.00179)
    assert products[0]["id"] == "rewe_M1"

    eggs = parse_products(
        [
            {"id": "E1", "name": "ja! Eier Bodenhaltung", "price": 249, "grammage": "10 Stück"},
            {"productName": "Kein Preis"},
            {"name": "Gouda am Stück", "price": "2,99 €", "grammage": "400 g"},
        ]
    )
    assert [(p["title"], p["price"], p["pack_amount"], p["pack_unit"]) for p in eggs] == [
        ("ja! Eier Bodenhaltung", 2.49, 10.0, "Stück"),
        ("Gouda am Stück", 2.99, 400.0, "g"),
    ]
    assert len(parse_products({"products": MILK})) == 3
    assert len(parse_products({"data": {"products": MILK}})) == 3
    assert len(parse_products(GOUDA)) == 1
    assert parse_products(EMPTY) == []
    assert parse_products({"totalCount": 0}) == []
    assert parse_products([]) == []
    for data in ({"error": "nope"}, "text", None, [{"foo": 1}, {"bar": 2}, {"baz": 3}]):
        with pytest.raises(ReweUnexpected):
            parse_products(data)


def test_parse_markets() -> None:
    """Markets from a list or {"markets": [...]}, nested addresses, duplicates dropped."""
    markets = parse_markets(MARKETS)
    assert [m["id"] for m in markets] == [MARKET, "560812"]
    assert markets[0] == {
        "id": MARKET,
        "name": "REWE Markt GmbH",
        "street": "Sendlinger Str. 2",
        "postcode": "80331",
        "city": "München",
        "label": "REWE Markt GmbH, Sendlinger Str. 2, 80331 München",
        "lat": 48.1361,
        "lon": 11.5713,
    }
    assert markets[1]["label"] == "REWE City, Tal 1, 80333 München"
    assert markets[1]["lat"] is None
    assert parse_markets({"markets": MARKETS}) == markets
    assert parse_markets([]) == []
    with pytest.raises(ReweUnexpected):
        parse_markets({"foo": 1})


def test_best_product() -> None:
    """Cheapest matching product per kg / l / piece with a plausible pack."""
    butter = parse_products(BUTTER)
    assert best_product(butter, "butter")["product_id"] == "B1"
    assert best_product(butter, "milch") is None
    # the reduced price does not count, the regular one does
    assert best_product(butter[1:], "butter")["product_id"] == "B4"
    # implausible pack sizes are ignored
    huge = parse_product(
        {"id": "H", "name": "Butter Großgebinde", "price": 99.0, "grammage": "100kg"}
    )
    assert huge["pack_amount"] is None
    assert best_product([huge, *butter], "butter")["product_id"] == "B1"

    milk = parse_products(MILK)
    assert best_product(milk, "milch")["product_id"] == "M1"
    eggs = parse_products(
        [
            {"id": "E6", "name": "Eier 6 Stück", "price": 1.89, "grammage": "6 Stück"},
            {"id": "E10", "name": "Eier 10 Stück", "price": 2.49, "grammage": "10 Stück"},
            {"id": "EG", "name": "Eierlikör", "price": 7.99, "grammage": "700ml"},
        ]
    )
    assert ingredient_key("Eier") == "ei"  # short key: matched word by word
    assert best_product(eggs, "ei")["product_id"] == "E10"
    assert best_product(eggs[2:], "ei") is None  # Eierlikör is no egg
    # the unit of the estimate is preferred
    mixed = parse_products(
        [
            {"id": "P1", "name": "Champignons 250g", "price": 1.49, "grammage": "250g"},
            {"id": "P2", "name": "Champignons 6 Stück", "price": 0.99, "grammage": "6 Stück"},
        ]
    )
    assert best_product(mixed, "champignon", base="g")["product_id"] == "P1"
    assert best_product(mixed, "champignon", base="Stück")["product_id"] == "P2"
    assert best_product([], "butter") is None


# ----------------------------------------------------------------------
# Off by default
# ----------------------------------------------------------------------


async def test_off_by_default(
    hass: HomeAssistant,
    rewe_off_entry: MockConfigEntry,
    freezer,
    hass_ws_client,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Without the option nothing is sent to REWE (refresh, schedule, article search)."""
    entry = rewe_off_entry
    manager = entry.runtime_data
    assert articles.LIVE_PROVIDERS["rewe"] is rewe.async_rewe_live

    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/data"})
    msg = await client.receive_json()
    assert msg["result"]["economy"]["price_sources"]["rewe"]["status"] == "off"

    status = await async_refresh_rewe_prices(hass, manager, force=True)
    assert (status["status"], status["enabled"], status["experimental"]) == ("off", False, True)
    assert "aus" in status["message"]
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "refresh_prices", {"source": "rewe"}, blocking=True, return_response=True
        )
    assert err.value.translation_key == "rewe_disabled"

    response = await manager.async_search_articles_live("Butter")
    assert (response["live"], response["results"]) == (False, [])

    minute = sum(ord(c) for c in entry.entry_id) % 50 + 5
    target = datetime(2026, 11, 5, 4, minute, 1, tzinfo=dt_util.get_time_zone("Europe/Berlin"))
    freezer.move_to(target)
    async_fire_time_changed(hass, target)
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == 0
    assert "rewe" not in manager.price_sources_meta


# ----------------------------------------------------------------------
# Refresh
# ----------------------------------------------------------------------


async def test_refresh_learns_store_prices(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """The cheapest matching article per term becomes a REWE store price (with history)."""
    entry = await _rewe_entry(hass, config_entry, freezer)
    manager = entry.runtime_data
    branch = manager.get_main_branch()
    manager.shopping_add("Gouda")  # open shopping items are searched too
    status = rewe.rewe_status(manager)
    assert (status["status"], status["market_id"], status["branch_id"]) == (
        "pending",
        MARKET,
        branch["id"],
    )
    _mock_searches(aioclient_mock)

    status = await async_refresh_rewe_prices(hass, manager)
    assert status["status"] == "ok"
    assert (status["searched"], status["count"], status["learned"], status["prices"]) == (
        4,
        3,
        3,
        3,
    )
    assert status["errors"] == []
    assert status["blocked_until"] is None
    assert status["last_success"] == status["last_run"] == dt_util.utcnow().isoformat()
    assert "3 Preise gelernt" in status["message"]
    calls = _calls(aioclient_mock)
    assert [c[1].query["search"] for c in calls] == ["Butter", "Milch", "Eier", "Gouda"]
    assert calls[0][1].query["market"] == MARKET
    assert (calls[0][1].query["objectsPerPage"], calls[0][1].query["page"]) == ("20", "1")
    assert calls[0][3]["User-Agent"] == HTTP_USER_AGENT
    assert calls[0][3]["Accept"] == "application/json"

    learned = manager.store_prices_learned["rewe"]
    butter = learned["butter"]
    assert (butter["price"], butter["amount"], butter["unit"], butter["source"]) == (
        1.99,
        250.0,
        "g",
        "rewe_online",
    )
    assert (butter["name"], butter["ref"]) == ("ja! Deutsche Markenbutter", "B1")
    assert butter["history"] == [{"date": "2026-11-04", "price": 1.99, "source": "rewe_online"}]
    assert (learned["milch"]["price"], learned["milch"]["amount"]) == (1.19, 1000.0)
    assert learned["gouda"]["ref"] == "G1"
    entry_price = manager.store_book("rewe").lookup("Butter")
    assert (entry_price.price, entry_price.source, entry_price.store_id) == (
        1.99,
        "rewe_online",
        "rewe",
    )
    meta = manager.price_sources_meta["rewe"]
    assert (meta["status"], meta["market_id"], meta["count"]) == ("ok", MARKET, 3)

    # fresh: the next (scheduled) refresh sends nothing
    await async_refresh_rewe_prices(hass, manager)
    assert len(_calls(aioclient_mock)) == 4

    # a week later the prices are refreshed; the history grows
    freezer.move_to(NOW + timedelta(days=8))
    aioclient_mock.clear_requests()
    _mock_searches(
        aioclient_mock,
        _answer(_product("B1", "ja! Deutsche Markenbutter", 209, "250g (1 kg = 8,36 €)")),
    )
    status = await async_refresh_rewe_prices(hass, manager)
    assert status["status"] == "ok"
    butter = manager.store_prices_learned["rewe"]["butter"]
    assert butter["price"] == 2.09
    assert [h["price"] for h in butter["history"]] == [1.99, 2.09]

    # stored with the other data
    await manager.async_save_now()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    reloaded = entry.runtime_data
    assert reloaded.price_sources_meta["rewe"]["status"] == "ok"
    assert reloaded.store_prices_learned["rewe"]["butter"]["price"] == 2.09


@pytest.mark.parametrize(
    ("kwargs", "status", "detail"),
    [
        ({"status": 403}, "blocked", "HTTP 403"),
        ({"status": 429}, "blocked", "HTTP 429"),
        (
            {
                "text": "<html><body>Bitte bestätigen</body></html>",
                "headers": {"Content-Type": "text/html"},
            },
            "blocked",
            "Webseite statt Daten",
        ),
        ({"text": "\n<!DOCTYPE html><html></html>"}, "blocked", "Webseite statt Daten"),
        ({"json": {"error": "nope"}}, "error", "unerwartete Antwort"),
        ({"status": 404}, "error", "HTTP 404"),
    ],
)
async def test_refresh_blocked_backoff(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
    kwargs: dict,
    status: str,
    detail: str,
) -> None:
    """403/429/HTML/unknown answers: paused for 7 days, no further requests, old prices stay."""
    entry = await _rewe_entry(hass, config_entry, freezer)
    manager = entry.runtime_data
    assert manager.learn_store_price(
        "rewe", "butter", "Butter", 1.89, 250, "g", "rewe_online", ref="old"
    )
    aioclient_mock.get(SEARCH_URL, **kwargs)

    result = await async_refresh_rewe_prices(hass, manager, force=True)
    assert result["status"] == status
    assert detail in result["errors"][0]
    until = dt_util.utcnow() + timedelta(days=7)
    assert result["blocked_until"] == until.isoformat()
    assert "11.11.2026" in result["message"]
    assert result["last_success"] is None
    assert len(_calls(aioclient_mock)) == 1  # stopped at the first answer
    assert manager.store_prices_learned["rewe"]["butter"]["price"] == 1.89  # kept

    # while blocked: no requests (refresh with force, service, article search)
    assert (await async_refresh_rewe_prices(hass, manager, force=True))["status"] == status
    service = await hass.services.async_call(
        DOMAIN, "refresh_prices", {"source": "rewe"}, blocking=True, return_response=True
    )
    assert service["blocked_until"] == until.isoformat()
    live = await manager.async_search_articles_live("Butter")
    assert live["live"] is True
    assert "pausiert bis 11.11.2026" in live["error"]
    assert len(_calls(aioclient_mock)) == 1

    # after the backoff the next check asks again
    freezer.move_to(NOW + timedelta(days=7, minutes=1))
    aioclient_mock.clear_requests()
    _mock_searches(aioclient_mock)
    result = await async_refresh_rewe_prices(hass, manager)
    assert result["status"] == "ok"
    assert result["blocked_until"] is None
    assert len(_calls(aioclient_mock)) == 3


async def test_refresh_errors_without_backoff(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Server errors are retried on the next check (no backoff); single failures are skipped."""
    entry = await _rewe_entry(hass, config_entry, freezer)
    manager = entry.runtime_data
    aioclient_mock.get(SEARCH_URL, status=500)
    result = await async_refresh_rewe_prices(hass, manager)
    assert result["status"] == "error"
    assert result["blocked_until"] is None
    assert result["errors"] == [
        "Butter: Die Abfrage beim REWE-Onlineshop ist fehlgeschlagen (HTTP 500)."
    ]
    assert len(_calls(aioclient_mock)) == 1  # nothing worked: stopped
    assert "fehlgeschlagen" in result["message"]

    # one failing term after a success does not stop the refresh
    aioclient_mock.clear_requests()
    aioclient_mock.get(SEARCH_URL, params={"search": "Butter"}, json=BUTTER)
    aioclient_mock.get(SEARCH_URL, params={"search": "Milch"}, status=502)
    aioclient_mock.get(SEARCH_URL, params={"search": "Eier"}, json=EMPTY)
    result = await async_refresh_rewe_prices(hass, manager)
    assert (result["status"], result["learned"], result["searched"]) == ("ok", 1, 3)
    assert result["errors"] == [
        "Milch: Die Abfrage beim REWE-Onlineshop ist fehlgeschlagen (HTTP 502)."
    ]


async def test_scheduler_only_when_stale(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """The daily check at 04:xx fetches prices only when the last success is a week old."""
    entry = await _rewe_entry(hass, config_entry, freezer)
    _mock_searches(aioclient_mock)
    minute = sum(ord(c) for c in entry.entry_id) % 50 + 5
    tz = dt_util.get_time_zone("Europe/Berlin")

    async def check(day: int) -> int:
        target = datetime(2026, 11, day, 4, minute, 0, tzinfo=tz)
        freezer.move_to(target)
        async_fire_time_changed(hass, target)
        await hass.async_block_till_done()
        return len(_calls(aioclient_mock))

    assert await check(5) == 3  # never fetched
    assert entry.runtime_data.price_sources_meta["rewe"]["status"] == "ok"
    assert await check(6) == 3  # fresh
    assert await check(11) == 3
    assert await check(12) == 6  # a week after the last success


# ----------------------------------------------------------------------
# Services, websocket, export, diagnostics
# ----------------------------------------------------------------------


async def test_services(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    hass_ws_client,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """refresh_prices (rewe / offers) and find_rewe_markets (also without the price option)."""
    manager = setup_integration.runtime_data

    async def call(service: str, **data):
        return await hass.services.async_call(
            DOMAIN, service, data, blocking=True, return_response=True
        )

    with pytest.raises(ServiceValidationError) as err:
        await call("refresh_prices", source="offers")
    assert err.value.translation_key == "offers_disabled"
    with pytest.raises((vol.Invalid, ServiceValidationError)):
        await call("refresh_prices", source="lidl")

    # market search: an explicit action, works with the price option off
    with pytest.raises(ServiceValidationError) as err:
        await call("find_rewe_markets")
    assert err.value.translation_key == "rewe_postcode_required"
    with pytest.raises(ServiceValidationError) as err:
        await call("find_rewe_markets", zip="123")
    assert err.value.translation_key == "invalid_postcode"
    aioclient_mock.get(MARKETS_URL, params={"searchTerm": "80331"}, json=MARKETS)
    aioclient_mock.get(MARKETS_URL, params={"searchTerm": "80333"}, json={"markets": MARKETS[1:2]})
    result = await call("find_rewe_markets", zip="80331")
    assert result["zip_code"] == "80331"
    assert [(m["id"], m["branch_id"]) for m in result["markets"]] == [
        (MARKET, None),
        ("560812", None),
    ]
    request = _calls(aioclient_mock, MARKETS_URL)[0]
    assert request[1].query["searchTerm"] == "80331"
    assert request[3]["User-Agent"] == HTTP_USER_AGENT

    # default postcode: the REWE branch; markets already used by a branch are marked
    branch = manager.save_branch({"store": "REWE", "postcode": "80333"})
    result = await call("find_rewe_markets")
    assert result["zip_code"] == "80333"
    assert [m["id"] for m in result["markets"]] == ["560812"]
    manager.save_branch({"id": branch["id"], "rewe_market_id": "560812"})
    result = await call("find_rewe_markets")
    assert result["markets"][0]["branch_id"] == branch["id"]

    # websocket for the panel ("Markt suchen")
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/rewe_markets", "zip": "80331"})
    msg = await client.receive_json()
    assert msg["success"]
    assert (
        msg["result"]["markets"][0]["label"] == "REWE Markt GmbH, Sendlinger Str. 2, 80331 München"
    )
    await client.send_json({"id": 2, "type": f"{DOMAIN}/rewe_markets", "zip": "1"})
    msg = await client.receive_json()
    assert (msg["success"], msg["error"]["code"]) == (False, "invalid_postcode")

    # refused market search: a clear error, the price source is not paused by it
    aioclient_mock.clear_requests()
    aioclient_mock.get(MARKETS_URL, status=403)
    with pytest.raises(HomeAssistantError) as err:
        await call("find_rewe_markets", zip="80331")
    assert err.value.translation_key == "rewe_blocked"
    assert "rewe" not in manager.price_sources_meta
    await client.send_json({"id": 3, "type": f"{DOMAIN}/rewe_markets", "zip": "80331"})
    msg = await client.receive_json()
    assert msg["error"]["code"] == "rewe_blocked"
    assert "keine automatischen Abfragen" in msg["error"]["message"]

    # get_offers also shows the REWE status
    offers = await call("get_offers")
    assert offers["price_sources"]["rewe"]["status"] == "off"


async def test_refresh_prices_service(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """refresh_prices source=rewe needs a market id and runs even when prices are fresh."""
    await _setup(
        hass,
        config_entry,
        freezer,
        **{CONF_REWE_ONLINE: True, CONF_WATCHLIST: "Butter, Milch, Eier"},
    )
    manager = config_entry.runtime_data
    assert rewe.rewe_status(manager)["message"] == rewe.MSG_NO_MARKET
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "refresh_prices", {"source": "rewe"}, blocking=True, return_response=True
        )
    assert err.value.translation_key == "rewe_no_market"

    manager.save_branch({"store": "REWE", "postcode": "80331", "rewe_market_id": MARKET})
    aioclient_mock.get(SEARCH_URL, json=BUTTER)

    async def refresh() -> dict:
        return await hass.services.async_call(
            DOMAIN, "refresh_prices", {"source": "rewe"}, blocking=True, return_response=True
        )

    result = await refresh()
    assert (result["status"], result["learned"]) == ("ok", 1)
    assert len(_calls(aioclient_mock)) == 3  # 3 terms
    # tapping again right away sends nothing (at most once per MANUAL_MIN_HOURS)
    again = await refresh()
    assert len(_calls(aioclient_mock)) == 3
    assert again["status"] == "ok"
    assert again["message"] == "Gerade erst aktualisiert – wieder möglich ab 16:00 Uhr."
    assert again["cooldown_until"] == "2026-11-04T15:00:00+00:00"
    # force: runs again later although the prices are still fresh (< REFRESH_DAYS)
    freezer.tick(timedelta(hours=rewe.MANUAL_MIN_HOURS))
    result = await refresh()
    assert (result["status"], result["learned"]) == ("ok", 1)
    assert "cooldown_until" not in result
    assert len(_calls(aioclient_mock)) == 6


async def test_article_search_live_rewe(
    hass: HomeAssistant,
    rewe_entry: MockConfigEntry,
    hass_ws_client,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """The live part of the article search uses the REWE shop for REWE (cached 1 h)."""
    manager = rewe_entry.runtime_data
    branch = manager.get_main_branch()
    aioclient_mock.get(SEARCH_URL, params={"search": "Butter"}, json=BUTTER)
    aioclient_mock.get(SEARCH_URL, params={"search": "Milch"}, status=403)
    client = await hass_ws_client(hass)

    await client.send_json(
        {"id": 1, "type": f"{DOMAIN}/article_search", "query": "Butter", "live": True}
    )
    msg = await client.receive_json()
    assert msg["success"]
    result = msg["result"]
    assert (result["live"], result["error"], result["store"]["retailer"]) == (True, None, "rewe")
    live = {r["title"]: r for r in result["results"] if r["source"] == "live"}
    assert set(live) == {
        "ja! Deutsche Markenbutter",
        "Kerrygold Original Irische Butter",
        "ja! Butterkekse",
        "Weidebutter",
    }
    hit = live["ja! Deutsche Markenbutter"]
    assert (hit["price"], hit["pack"], hit["provider"]) == (1.99, "250 g", "rewe_online")
    assert (hit["branch_id"], hit["retailer"]) == (branch["id"], "rewe")
    assert hit["offer"]["image"] == "https://img.rewe-static.de/B1.png"
    assert live["Weidebutter"]["price"] == 1.49  # what it costs this week
    assert len(_calls(aioclient_mock)) == 1
    request = _calls(aioclient_mock)[0]
    assert (request[1].query["market"], request[3]["User-Agent"]) == (MARKET, HTTP_USER_AGENT)

    # cached for an hour
    response = await manager.async_search_articles_live("butter")
    assert len(response["results"]) == 4
    assert len(_calls(aioclient_mock)) == 1
    # other stores do not ask REWE (and marktguru is off)
    assert (await manager.async_search_articles_live("Butter", "Lidl"))["live"] is False

    # refused: reported and paused for a week, cached results still work
    response = await manager.async_search_articles_live("Milch")
    assert "keine automatischen Abfragen" in response["error"]
    assert manager.price_sources_meta["rewe"]["status"] == "blocked"
    assert rewe.rewe_status(manager)["blocked_until"] is not None
    response = await manager.async_search_articles_live("Eier")
    assert "pausiert" in response["error"]
    assert (await manager.async_search_articles_live("Butter"))["results"]
    assert len(_calls(aioclient_mock)) == 2

    # a REWE branch without market id
    manager.save_branch({"id": branch["id"], "rewe_market_id": ""})
    response = await manager.async_search_articles_live("Quark")
    assert response["error"] == rewe.MSG_NO_MARKET
    assert len(_calls(aioclient_mock)) == 2


async def test_live_newest_search_wins(
    hass: HomeAssistant, rewe_entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    """While a request runs, a newer search replaces a waiting one (nothing is sent for it)."""
    manager = rewe_entry.runtime_data
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow(method, url, data):
        started.set()
        await release.wait()
        return AiohttpClientMockResponse(method, url, json=BUTTER)

    aioclient_mock.get(SEARCH_URL, params={"search": "Butter"}, side_effect=slow)
    aioclient_mock.get(SEARCH_URL, json=MILK)
    first = asyncio.ensure_future(manager.async_search_articles_live("Butter"))
    await started.wait()
    second = asyncio.ensure_future(manager.async_search_articles_live("Milch"))
    third = asyncio.ensure_future(manager.async_search_articles_live("Vollmilch"))
    for _ in range(5):
        await asyncio.sleep(0)
    release.set()
    butter, milk, whole_milk = await asyncio.gather(first, second, third)
    assert len(butter["results"]) == 4
    assert not butter.get("superseded")
    assert milk.get("superseded") is True
    assert milk["results"] == []
    assert not whole_milk.get("superseded")
    assert whole_milk["results"][0]["title"] == "ja! Frische Vollmilch 3,5%"
    assert [c[1].query["search"] for c in _calls(aioclient_mock)] == ["Butter", "Vollmilch"]


async def test_live_two_sources_newest_wins(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """REWE and marktguru in one search share its turn: the newer search is not replaced."""
    entry = await _rewe_entry(hass, config_entry, freezer)
    hass.config_entries.async_update_entry(
        entry,
        options={**entry.options, CONF_OFFERS_SOURCE: "marktguru", CONF_ZIP: "80331"},
    )
    await hass.async_block_till_done()
    manager = entry.runtime_data
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow(method, url, data):
        started.set()
        await release.wait()
        return AiohttpClientMockResponse(method, url, json=BUTTER)

    aioclient_mock.get(SEARCH_URL, params={"search": "Butter"}, side_effect=slow)
    aioclient_mock.get(SEARCH_URL, json=MILK)
    aioclient_mock.get(MARKTGURU_HOME, text=HOME_HTML)
    aioclient_mock.get(
        f"{MARKTGURU_API}/offers/search",
        json={"results": [_mg_offer(21, "Milch", "rewe", "REWE", 0.99, 1.19, 0.99, "l", "1 l")]},
    )
    older = asyncio.ensure_future(manager.async_search_articles_live("Butter"))
    await started.wait()
    newer = asyncio.ensure_future(manager.async_search_articles_live("Milch"))
    for _ in range(5):
        await asyncio.sleep(0)
    release.set()
    older_result, newer_result = await asyncio.gather(older, newer)
    assert older_result.get("superseded") is True
    assert not newer_result.get("superseded")
    assert {r["provider"] for r in newer_result["results"]} == {"rewe_online", "marktguru"}


async def test_export_and_diagnostics(
    hass: HomeAssistant,
    rewe_entry: MockConfigEntry,
    hass_ws_client,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """The panel data has the REWE status; diagnostics have the meta without market ids."""
    from custom_components.essensplaner.diagnostics import async_get_config_entry_diagnostics

    entry = rewe_entry
    manager = entry.runtime_data
    _mock_searches(aioclient_mock)
    await async_refresh_rewe_prices(hass, manager)

    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/data"})
    msg = await client.receive_json()
    status = msg["result"]["economy"]["price_sources"]["rewe"]
    assert (status["enabled"], status["status"], status["learned"]) == (True, "ok", 2)
    assert status["market_id"] == MARKET

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    meta = diagnostics["price_sources_meta"]["rewe"]
    assert (meta["status"], meta["count"]) == ("ok", 2)
    assert meta["market_id"] == "**REDACTED**"
    assert diagnostics["branches"][0]["rewe_market_id"] == "**REDACTED**"
    assert MARKET not in str(diagnostics)
