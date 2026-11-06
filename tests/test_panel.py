"""Websocket API details used by the panel (1.3)."""

from __future__ import annotations

from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.essensplaner.branches import search_defaults
from custom_components.essensplaner.const import (
    CONF_BRANCH_RADIUS,
    CONF_BRANCH_ROUTE,
    CONF_BRANCH_ROUTE_RADIUS,
    CONF_OFFERS_SOURCE,
    CONF_ZIP,
    DOMAIN,
)
from custom_components.essensplaner.offers import MARKTGURU_API, MARKTGURU_HOME

from .test_economy import HOME_HTML, _mg_offer


def test_search_defaults() -> None:
    """Preset of the search form: option values, clamped, with the 1.3 defaults."""
    assert search_defaults({}) == {"radius_km": 3.0, "route": True, "route_radius_m": 800}
    assert search_defaults(
        {CONF_BRANCH_RADIUS: 99, CONF_BRANCH_ROUTE: False, CONF_BRANCH_ROUTE_RADIUS: 10}
    ) == {"radius_km": 25.0, "route": False, "route_radius_m": 100}
    assert search_defaults({CONF_BRANCH_RADIUS: "kaputt"})["radius_km"] == 3.0


@pytest.fixture
async def branch_options_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer
) -> MockConfigEntry:
    """Integration with branch search options (clock moved before the ws token)."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(datetime.fromisoformat("2026-11-04T10:00:00+01:00"))
    assert await async_setup_component(hass, "homeassistant", {})
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry,
        options={**config_entry.options, CONF_BRANCH_RADIUS: 5, CONF_BRANCH_ROUTE: False},
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


async def test_ws_find_branches_defaults(
    hass: HomeAssistant, branch_options_entry: MockConfigEntry, hass_ws_client
) -> None:
    """The cached-only answer (no request) carries the option defaults for the form."""
    hass.states.async_set(
        "zone.home", "0", {"latitude": 48.1, "longitude": 11.5, "friendly_name": "Zuhause"}
    )

    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/find_branches", "cached_only": True})
    msg = await client.receive_json()
    assert msg["success"]
    result = msg["result"]
    assert result["defaults"] == {"radius_km": 5.0, "route": False, "route_radius_m": 800}
    assert result["cached"] is False
    assert result["results"] == []
    assert result["zones"] == [{"zone": "zone.home", "name": "Zuhause", "default": True}]


@pytest.fixture
async def marktguru_aldi(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch,
) -> MockConfigEntry:
    """marktguru on, main store Aldi Süd with butter offers (and others) only found live."""
    monkeypatch.setattr("custom_components.essensplaner.articles.LIVE_MIN_INTERVAL", 0)

    def offer(oid: int, product: str, brand: str, price: float, old: float | None) -> dict:
        result = _mg_offer(oid, product, "aldi-sued", "Aldi Süd", price, old, None, "kg", "")
        result["brand"] = {"name": brand}
        result["description"] = "250-g-Packung" if "utter" in product else "200-g-Packung"
        return result

    aioclient_mock.get(MARKTGURU_HOME, text=HOME_HTML)
    aioclient_mock.get(
        f"{MARKTGURU_API}/offers/search",
        json={
            "results": [
                offer(13, "Butterkekse", "ja!", 0.79, None),
                offer(11, "Feine Butter", "Meggle", 1.49, 2.19),
                offer(14, "Deutsche Markenbutter", "Kerrygold", 1.99, 2.79),
                offer(15, "Erdnussbutter", "Mars", 1.29, None),
            ]
        },
    )
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(datetime.fromisoformat("2026-11-04T10:00:00+01:00"))
    assert await async_setup_component(hass, "homeassistant", {})
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry,
        options={**config_entry.options, CONF_OFFERS_SOURCE: "marktguru", CONF_ZIP: "80331"},
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    config_entry.runtime_data.save_branch({"store": "Aldi Süd", "postcode": "80331"})
    return config_entry


async def test_ws_article_search_live_order(
    hass: HomeAssistant, marktguru_aldi: MockConfigEntry, hass_ws_client
) -> None:
    """Live offers are ranked together with the local hits (offers for the article first).

    Offers that only start with the article ("Butterkekse") are other products and come
    after it; the order of the local hits stays the same as in the local answer.
    """
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/article_search", "query": "Butter"})
    local = [r["title"] for r in (await client.receive_json())["result"]["results"]]
    await client.send_json(
        {"id": 2, "type": f"{DOMAIN}/article_search", "query": "Butter", "live": True}
    )
    msg = await client.receive_json()
    assert msg["success"]
    results = msg["result"]["results"]
    titles = [r["title"] for r in results]
    assert titles[:3] == ["Meggle Feine Butter", "Kerrygold Deutsche Markenbutter", "Butter"]
    assert results[0]["source"] == "live"
    assert titles.index("ja! Butterkekse") > titles.index("Buttermilch")
    assert [t for t in titles if t in local] == local
    assert len(results) <= 10

    await client.send_json(
        {"id": 3, "type": f"{DOMAIN}/article_search", "query": "Butter", "live": True, "limit": 3}
    )
    msg = await client.receive_json()
    assert [r["title"] for r in msg["result"]["results"]] == titles[:3]


async def test_ws_article_search_keeps_backend_rank(
    hass: HomeAssistant, marktguru_aldi: MockConfigEntry, hass_ws_client
) -> None:
    """Offers for other products never move ahead of the article in the merged answer.

    Compound heads ("Erdnussbutter", "Kokosmilch") are other products: the websocket keeps
    the manager's rank for them, saved and live ones, and the typed article comes first.
    """
    manager = marktguru_aldi.runtime_data
    manager.add_offer("Erdnussbutter", "Aldi Süd", 1.79, "350 g")
    manager.add_offer("Kokosmilch", "Aldi Süd", 0.99, "400 ml")
    manager.add_offer("Oro di Parma Gehackte Tomaten", "Aldi Süd", 0.59, "400 g")
    client = await hass_ws_client(hass)
    for msg_id, query in enumerate(("Butter", "Milch", "Tomaten"), start=1):
        await client.send_json(
            {"id": msg_id, "type": f"{DOMAIN}/article_search", "query": query, "limit": 20}
        )
        results = (await client.receive_json())["result"]["results"]
        assert results[0]["title"] == query, (query, [r["title"] for r in results])
        backend = {r["title"]: r["match"] for r in manager.search_articles(query, None, 20)}
        for result in results:
            assert result["match"] >= backend[result["title"]], (query, result["title"])

    await client.send_json(
        {"id": 9, "type": f"{DOMAIN}/article_search", "query": "Butter", "live": True, "limit": 20}
    )
    results = (await client.receive_json())["result"]["results"]
    titles = [r["title"] for r in results]
    assert titles[:3] == ["Meggle Feine Butter", "Kerrygold Deutsche Markenbutter", "Butter"]
    live = {
        r["title"]: r["match"]
        for r in (await manager.async_search_articles_live("Butter", None, 20))["results"]
    }
    peanut = next(r for r in results if r["title"] == "Mars Erdnussbutter")
    assert peanut["match"] == live["Mars Erdnussbutter"] == 3
    assert titles.index("Mars Erdnussbutter") > titles.index("Butter")


async def test_article_pick_of_main_store_stays_automatic(
    hass: HomeAssistant, setup_integration: MockConfigEntry, hass_ws_client
) -> None:
    """A hit of the main store, sent like the panel does (without store), is no manual choice.

    It keeps the store's price and pack at the main store and still moves to a cheaper offer
    elsewhere ("Läden neu zuordnen").
    """
    manager = setup_integration.runtime_data
    aldi = manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})
    manager.save_branch({"store": "Lidl", "postcode": "80331"})
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/article_search", "query": "Butter"})
    result = (await client.receive_json())["result"]
    hit = result["results"][0]
    assert (hit["title"], hit["branch_id"]) == ("Butter", result["store"]["branch_id"])

    response = await hass.services.async_call(
        DOMAIN,
        "add_shopping_item",
        {"item": hit["title"], "price": hit["price"], "pack": hit["pack"]},
        blocking=True,
        return_response=True,
    )
    item = next(i for i in manager.shopping if i["uid"] == response["item"]["uid"])
    assert "store_override" not in item
    assert (item["branch_id"], item["store_reason"], item["price"]) == (aldi["id"], "main", 1.99)

    manager.add_offer("Butter", "Lidl", 0.99, "250 g")
    manager.assign_shopping_stores()
    assert (item["retailer"], item["store_reason"], item["price"]) == ("lidl", "offer", 0.99)


async def test_offer_card_merken_keeps_the_offer(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The offer card's "🛒 Merken" (add_shopping_item with offer_id) buys it at the offer.

    Also when the offer saves less than the "Ausnahme" threshold against the main store.
    """
    manager = setup_integration.runtime_data
    manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})
    lidl = manager.save_branch({"store": "Lidl", "postcode": "80331"})
    offer = manager.add_offer("Butter", "Lidl", 1.79, "250 g")
    response = await hass.services.async_call(
        DOMAIN,
        "add_shopping_item",
        {"item": offer["title"], "offer_id": offer["id"]},
        blocking=True,
        return_response=True,
    )
    item = next(i for i in manager.shopping if i["uid"] == response["item"]["uid"])
    assert (item["branch_id"], item["retailer"], item["price"]) == (lidl["id"], "lidl", 1.79)
    assert response["item"]["store_label"] == item["store_label"]


async def test_price_list_new_article(
    hass: HomeAssistant, setup_integration: MockConfigEntry, hass_ws_client
) -> None:
    """An article that is not in the list ("Kaffee") gets a row once a price is saved for it."""
    manager = setup_integration.runtime_data
    manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})
    manager.save_branch({"store": "Lidl", "postcode": "80331"})
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/store_prices", "query": "Kaffee"})
    assert (await client.receive_json())["result"]["rows"] == []

    # what the panel's "＋ „Kaffee“ als Artikel anlegen" dialog sends
    await hass.services.async_call(
        DOMAIN,
        "set_price",
        {"ingredient": "Kaffee", "price": 4.99, "amount": 500, "unit": "g", "store": "lidl"},
        blocking=True,
        return_response=True,
    )
    await client.send_json({"id": 2, "type": f"{DOMAIN}/store_prices", "query": "Kaffee"})
    rows = (await client.receive_json())["result"]["rows"]
    assert [(r["name"], r["stores"]["lidl"]["price"]) for r in rows] == [("Kaffee", 4.99)]
