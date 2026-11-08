"""1.3.2: REWE shop interface moved (service type, market search), Overpass retries."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)
from yarl import URL

from custom_components.essensplaner import branches, rewe
from custom_components.essensplaner.branches import OVERPASS_URL, async_overpass_query
from custom_components.essensplaner.rewe import (
    CLIENT_VERSION,
    MARKETS_URL,
    PICKUP_MARKETS_URL,
    SEARCH_URL,
    async_refresh_rewe_prices,
    parse_markets,
)

from .test_rewe import BUTTER, MARKET, _calls, _mock_searches, _rewe_entry

# the shop answers a search without hits (or without service type) like this
NO_HIT = {
    "type": "NO_HIT",
    "search": {"term": "x"},
    "pagination": {"page": 1, "totalPages": 0, "objectsPerPage": 20, "totalResultCount": 0},
    "_embedded": {},
}
# www.rewe.de/api/wksmarketsearch (11/2026)
WKS = {
    "markets": [
        {
            "wwIdent": "1400001",
            "name": "REWE",
            "companyName": "REWE Anna Beispiel oHG",
            "street": "Hauptstr. 8",
            "zipCode": "53501",
            "city": "Musterstadt",
            "location": {"latitude": 48.12237, "longitude": 11.43224},
            "category": {"marketTypeDisplayName": "REWE", "type": "MARKET"},
        }
    ],
    "paging": {"page": 1},
}
# www.rewe.de/shop/api/marketselection/zipcodes/<zip>/services/pickup
PICKUP = [
    {
        "wwIdent": "1400001",
        "displayName": "REWE Markt",
        "distance": 1531,
        "latitude": "48.12237",
        "longitude": "11.43224",
        "companyName": "REWE Anna Beispiel oHG",
        "zipCode": "53501",
        "street": "Hauptstr. 8",
        "city": "Musterstadt",
    }
]


@pytest.fixture(autouse=True)
def no_delays(monkeypatch) -> None:
    """No politeness delays (frozen clock), three watchlist terms."""
    monkeypatch.setattr(rewe, "REQUEST_DELAY", 0)
    monkeypatch.setattr(rewe, "MAX_TERMS", 3)


# ----------------------------------------------------------------------
# REWE
# ----------------------------------------------------------------------


async def test_search_sends_market_and_service_type(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock
) -> None:
    """Prices only come with a market and a service type, from www.rewe.de/shop/api."""
    assert SEARCH_URL == "https://www.rewe.de/shop/api/products"
    entry = await _rewe_entry(hass, config_entry, freezer)
    _mock_searches(aioclient_mock)
    status = await async_refresh_rewe_prices(hass, entry.runtime_data)
    assert status["status"] == "ok"
    query = _calls(aioclient_mock)[0][1].query
    assert (query["market"], query["serviceTypes"]) == (MARKET, "PICKUP")
    assert entry.runtime_data.price_sources_meta["rewe"]["client"] == CLIENT_VERSION


async def test_pause_of_old_client_is_ignored(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock
) -> None:
    """An error / pause stored by 1.3.0/1.3.1 (old interface) does not block the new client."""
    entry = await _rewe_entry(hass, config_entry, freezer)
    manager = entry.runtime_data
    until = (dt_util.utcnow() + timedelta(days=6)).isoformat()
    manager.price_sources_meta["rewe"] = {
        "status": "error",
        "last_run": dt_util.utcnow().isoformat(),
        "errors": ["Die Abfrage beim REWE-Onlineshop ist fehlgeschlagen (keine lesbaren Daten)."],
        "blocked_until": until,
        "market_id": MARKET,
    }
    status = rewe.rewe_status(manager)
    assert (status["status"], status["blocked_until"], status["errors"]) == ("pending", None, [])
    assert "Preise aktualisieren" in status["message"]

    _mock_searches(aioclient_mock)
    status = await async_refresh_rewe_prices(hass, manager)
    assert status["status"] == "ok"
    assert status["errors"] == []
    assert len(_calls(aioclient_mock)) == 3


async def test_pause_of_current_client_is_kept(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock
) -> None:
    """A refusal recorded by this client version still pauses all requests."""
    entry = await _rewe_entry(hass, config_entry, freezer)
    manager = entry.runtime_data
    manager.price_sources_meta["rewe"] = {
        "status": "blocked",
        "errors": ["abgelehnt"],
        "blocked_until": (dt_util.utcnow() + timedelta(days=6)).isoformat(),
        "client": CLIENT_VERSION,
    }
    _mock_searches(aioclient_mock)
    status = await async_refresh_rewe_prices(hass, manager, force=True)
    assert status["status"] == "blocked"
    assert _calls(aioclient_mock) == []


async def test_market_without_articles_pauses_one_day(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock
) -> None:
    """Every search without a single article: the market id is wrong – a short pause."""
    entry = await _rewe_entry(hass, config_entry, freezer)
    manager = entry.runtime_data
    aioclient_mock.get(SEARCH_URL, json=NO_HIT)
    status = await async_refresh_rewe_prices(hass, manager)
    assert status["status"] == "error"
    assert f"REWE-Markt {MARKET} liefert keine Artikel" in status["message"]
    assert "Markt suchen" in status["message"]
    until = dt_util.parse_datetime(status["blocked_until"])
    assert until - dt_util.utcnow() == timedelta(days=1)
    assert status["last_success"] is None
    assert manager.store_prices_learned.get("rewe", {}) == {}


async def test_a_search_without_hits_is_no_error(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock
) -> None:
    """One term without hits (NO_HIT) among priced ones is normal."""
    entry = await _rewe_entry(hass, config_entry, freezer)
    aioclient_mock.get(SEARCH_URL, params={"search": "Butter"}, json=BUTTER)
    aioclient_mock.get(SEARCH_URL, json=NO_HIT)
    status = await async_refresh_rewe_prices(hass, entry.runtime_data)
    assert (status["status"], status["learned"], status["blocked_until"]) == ("ok", 1, None)


def test_parse_new_market_shapes() -> None:
    """wksmarketsearch ({markets, paging}) and the pickup list (strings as coordinates)."""
    (market,) = parse_markets(WKS)
    assert market == {
        "id": "1400001",
        "name": "REWE Anna Beispiel oHG",
        "street": "Hauptstr. 8",
        "postcode": "53501",
        "city": "Musterstadt",
        "label": "REWE Anna Beispiel oHG, Hauptstr. 8, 53501 Musterstadt",
        "lat": 48.12237,
        "lon": 11.43224,
    }
    (pickup,) = parse_markets(PICKUP)
    assert (pickup["id"], pickup["lat"], pickup["lon"]) == ("1400001", 48.12237, 11.43224)


async def test_market_search_new_endpoint_and_pickup_fallback(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock
) -> None:
    """The market search uses wksmarketsearch; without markets there the pickup list."""
    assert MARKETS_URL == "https://www.rewe.de/api/wksmarketsearch"
    await _rewe_entry(hass, config_entry, freezer)
    aioclient_mock.get(MARKETS_URL, params={"searchTerm": "53501"}, json=WKS)
    result = await hass.services.async_call(
        "essensplaner", "find_rewe_markets", {"zip": "53501"}, blocking=True, return_response=True
    )
    assert [m["id"] for m in result["markets"]] == ["1400001"]

    aioclient_mock.clear_requests()
    aioclient_mock.get(MARKETS_URL, status=404, json={"title": "Not Found"})
    aioclient_mock.get(PICKUP_MARKETS_URL.format(zip="53501"), json=PICKUP)
    result = await hass.services.async_call(
        "essensplaner", "find_rewe_markets", {"zip": "53501"}, blocking=True, return_response=True
    )
    assert [m["id"] for m in result["markets"]] == ["1400001"]
    assert [str(c[1]).split("?")[0] for c in aioclient_mock.mock_calls] == [
        MARKETS_URL,
        PICKUP_MARKETS_URL.format(zip="53501"),
    ]


async def test_prices_are_fetched_shortly_after_start(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock
) -> None:
    """Never fetched prices do not wait for the night: a check ~2.5 minutes after start."""
    entry = await _rewe_entry(hass, config_entry, freezer)
    _mock_searches(aioclient_mock)
    freezer.tick(timedelta(seconds=60))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert _calls(aioclient_mock) == []
    freezer.tick(timedelta(seconds=100))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(_calls(aioclient_mock)) == 3
    assert entry.runtime_data.price_sources_meta["rewe"]["status"] == "ok"


# ----------------------------------------------------------------------
# Overpass
# ----------------------------------------------------------------------

OVERPASS_OK = {"version": 0.6, "elements": [{"type": "node", "id": 1, "tags": {}}]}
MIRROR = "https://overpass.kumi.systems/api/interpreter"


def _sequence(aioclient_mock: AiohttpClientMocker, url: str, answers: list[dict]) -> None:
    """Answer the requests to `url` one after the other."""
    queue = list(answers)

    async def side_effect(method, request_url, data):
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        return AiohttpClientMockResponse(method, URL(url), **answer)

    aioclient_mock.post(url, side_effect=side_effect)


async def test_overpass_retries_a_busy_server(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, monkeypatch
) -> None:
    """502 "at capacity" (or 429/503, a reset connection) is retried after a pause."""
    monkeypatch.setattr(branches, "RETRY_DELAYS", (0, 0))
    _sequence(
        aioclient_mock,
        OVERPASS_URL,
        [{"status": 502, "text": "at capacity"}, {"status": 429}, {"json": OVERPASS_OK}],
    )
    data = await async_overpass_query(hass, "[out:json];")
    assert data["elements"][0]["id"] == 1
    assert aioclient_mock.call_count == 3


async def test_overpass_uses_the_mirror_last(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, monkeypatch
) -> None:
    """When the main server stays busy, the mirror answers."""
    monkeypatch.setattr(branches, "RETRY_DELAYS", (0,))
    monkeypatch.setattr(branches, "OVERPASS_MIRRORS", (MIRROR,))
    aioclient_mock.post(OVERPASS_URL, status=504)
    aioclient_mock.post(MIRROR, json=OVERPASS_OK)
    data = await async_overpass_query(hass, "[out:json];")
    assert data["elements"]
    assert [str(c[1]) for c in aioclient_mock.mock_calls] == [OVERPASS_URL, OVERPASS_URL, MIRROR]


async def test_overpass_gives_up_with_the_last_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, monkeypatch
) -> None:
    """Busy everywhere: the busy message; other errors are not retried."""
    monkeypatch.setattr(branches, "RETRY_DELAYS", (0, 0))
    monkeypatch.setattr(branches, "OVERPASS_MIRRORS", (MIRROR,))
    aioclient_mock.post(OVERPASS_URL, status=502)
    aioclient_mock.post(MIRROR, exc=TimeoutError())
    with pytest.raises(HomeAssistantError) as err:
        await async_overpass_query(hass, "[out:json];")
    assert err.value.translation_key == "overpass_timeout"
    assert aioclient_mock.call_count == 4

    aioclient_mock.clear_requests()
    aioclient_mock.post(OVERPASS_URL, status=400)
    with pytest.raises(HomeAssistantError) as err:
        await async_overpass_query(hass, "[out:json];")
    assert err.value.translation_key == "overpass_failed"
    assert aioclient_mock.call_count == 1


def test_overpass_timeouts_fit_a_queued_server() -> None:
    """The public server often answers after a minute when its queue is full; small
    server-side limits get a query admitted sooner."""
    assert branches.REQUEST_TIMEOUT >= 75
    assert branches.QUERY_TIMEOUT <= 30
    assert branches.QUERY_MAXSIZE <= 256 * 1024 * 1024
    assert branches.TOTAL_TIMEOUT >= branches.REQUEST_TIMEOUT * 2
