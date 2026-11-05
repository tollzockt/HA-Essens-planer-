"""Article search for the "Artikel hinzufügen" field: local ranking, history, live (1.3)."""

from __future__ import annotations

from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.essensplaner import articles
from custom_components.essensplaner.articles import ARTICLE_HISTORY_MAX, parse_pack_text
from custom_components.essensplaner.const import CONF_OFFERS_SOURCE, CONF_ZIP, DOMAIN
from custom_components.essensplaner.offers import MARKTGURU_API, MARKTGURU_HOME

from .test_economy import HOME_HTML, _mg_offer


@pytest.fixture(autouse=True)
def no_live_delay(monkeypatch) -> None:
    """No politeness delay between live requests (the clock is frozen in tests)."""
    monkeypatch.setattr("custom_components.essensplaner.articles.LIVE_MIN_INTERVAL", 0)


async def _setup(
    hass: HomeAssistant, entry: MockConfigEntry, freezer, **options
) -> MockConfigEntry:
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(datetime.fromisoformat("2026-11-04T10:00:00+01:00"))
    assert await async_setup_component(hass, "homeassistant", {})
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _titles(results: list[dict]) -> list[tuple[str, str]]:
    return [(r["title"], r["source"]) for r in results]


def test_parse_pack_text() -> None:
    """Pack sizes typed by the user or shown in search results."""
    assert parse_pack_text("250 g") == (250.0, "g")
    assert parse_pack_text("1,5 l") == (1500.0, "ml")
    assert parse_pack_text("2 x 125 g") == (250.0, "g")
    assert parse_pack_text("10 Stück") == (10.0, "Stück")
    assert parse_pack_text("groß") is None
    assert parse_pack_text(None) is None


async def test_local_ranking(hass: HomeAssistant, setup_integration) -> None:
    """Offers and exact/prefix matches first; store prices replace the estimate."""
    manager = setup_integration.runtime_data
    aldi = manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})
    lidl = manager.save_branch({"store": "Lidl", "postcode": "80331"})
    manager.set_store_price("Aldi Süd", "Butter", 1.69, 250, "g")
    assert manager.learn_store_price(
        "aldi-sued", "milch", "Milch", 1.09, 1000, "ml", "leaflet", ref="mg_1"
    )
    offer = manager.add_offer("Kerrygold Irische Butter", "Aldi Süd", 2.22, "250 g")
    lidl_offer = manager.add_offer("Butter", "Lidl", 1.49, "250 g")
    expired = manager.add_offer("Butterkekse", "Aldi Süd", 0.99, "200 g")
    expired["valid_to"] = "2026-11-01"

    results = manager.search_articles("butter")
    assert results[0]["title"] == "Kerrygold Irische Butter"
    assert results[0]["source"] == "offer"
    assert results[0]["offer"]["id"] == offer["id"]
    assert (results[0]["price"], results[0]["pack"]) == (2.22, "250 g")
    assert results[0]["branch_id"] == aldi["id"]
    butter = results[1]
    assert (butter["title"], butter["source"], butter["price"], butter["pack"]) == (
        "Butter",
        "store",
        1.69,
        "250 g",
    )
    assert (butter["retailer"], butter["real"], butter["key"]) == ("aldi-sued", True, "butter")
    # one row per product and pack: the estimate (1,99 €) is replaced by the store price
    assert [r["title"] for r in results].count("Butter") == 1
    # the Lidl offer and expired offers are not shown for Aldi
    assert all(r["retailer"] == "aldi-sued" for r in results)
    assert lidl_offer["id"] not in [(r["offer"] or {}).get("id") for r in results]
    assert "Butterkekse" not in [r["title"] for r in results]
    # prefix matches before substring matches
    titles = [r["title"] for r in results]
    assert titles.index("Buttermilch") < titles.index("Erdnussbutter")
    assert len(results) <= 10

    milk = manager.search_articles("Milch", limit=3)
    assert (milk[0]["title"], milk[0]["source"], milk[0]["price"]) == ("Milch", "learned", 1.09)
    assert len(milk) == 3

    # another store: its offer replaces the estimate of the same product and pack
    results = manager.search_articles("butter", store="Lidl")
    assert _titles(results)[:2] == [("Butter", "offer"), ("Butterkäse", "default")]
    assert (results[0]["branch_id"], results[0]["price"]) == (lidl["id"], 1.49)
    assert "butter" not in [r["key"] for r in results[1:]]
    # a retailer without branch works, an unknown store does not
    assert manager.search_articles("butter", store="Penny")[0]["retailer"] == "penny"
    with pytest.raises(ServiceValidationError):
        manager.search_articles("butter", store="Metro")
    assert manager.search_articles("   ") == []


async def test_without_main_branch(hass: HomeAssistant, setup_integration) -> None:
    """Without a main branch the general prices are searched."""
    manager = setup_integration.runtime_data
    manager.set_price("Butter", 1.49, 250, "g")
    results = manager.search_articles("Butt")
    assert (results[0]["title"], results[0]["source"], results[0]["price"]) == (
        "Butter",
        "store",
        1.49,
    )
    assert results[0]["retailer"] is None
    assert results[0]["branch_id"] is None
    assert manager.article_target() == (None, None)
    # aliases are found (with the price of their product)
    vollmilch = manager.search_articles("vollmi")[0]
    assert (vollmilch["title"], vollmilch["price"]) == ("Vollmilch", 0.99)


async def test_history(hass: HomeAssistant, setup_integration) -> None:
    """Added articles are remembered and suggested (frequent ones first)."""
    manager = setup_integration.runtime_data
    manager.shopping_add("Klopapier")
    manager.shopping_add("Klöße")
    manager.shopping_add("Klopapier")
    assert [(a["summary"], a["count"]) for a in manager.article_history] == [
        ("Klopapier", 2),
        ("Klöße", 1),
    ]
    assert manager.article_history[0]["key"] == "klopapier"
    results = manager.search_articles("klo")
    assert _titles(results)[:2] == [("Klopapier", "history"), ("Klöße", "history")]
    assert results[0]["count"] == 2
    assert results[0]["price"] is None

    for number in range(ARTICLE_HISTORY_MAX + 5):
        manager.remember_article(f"Artikel {number}", f"artikel {number}", None)
    assert len(manager.article_history) == ARTICLE_HISTORY_MAX
    assert manager.article_history[0]["summary"] == f"Artikel {ARTICLE_HISTORY_MAX + 4}"

    # stored with the other data
    await manager.async_save_now()
    assert await hass.config_entries.async_reload(setup_integration.entry_id)
    await hass.async_block_till_done()
    assert len(setup_integration.runtime_data.article_history) == ARTICLE_HISTORY_MAX


async def test_websocket_local(
    hass: HomeAssistant, setup_integration, hass_ws_client, aioclient_mock: AiohttpClientMocker
) -> None:
    """essensplaner/article_search without live results; adding a hit."""
    manager = setup_integration.runtime_data
    aldi = manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})
    offer = manager.add_offer("Kerrygold Butter", "Aldi Süd", 2.22, "250 g")
    client = await hass_ws_client(hass)

    await client.send_json({"id": 1, "type": f"{DOMAIN}/article_search", "query": "butter"})
    msg = await client.receive_json()
    assert msg["success"]
    result = msg["result"]
    assert result["store"] == {
        "branch_id": aldi["id"],
        "retailer": "aldi-sued",
        "retailer_name": "Aldi Süd",
        "label": "Aldi Süd",
        "postcode": "80331",
        "main": True,
    }
    assert (result["live"], result["error"]) == (False, None)
    hit = result["results"][0]
    assert hit["offer"]["id"] == offer["id"]

    # live requested, but no online source enabled: nothing is sent
    await client.send_json(
        {"id": 2, "type": f"{DOMAIN}/article_search", "query": "butter", "live": True}
    )
    msg = await client.receive_json()
    assert msg["result"]["live"] is False
    assert aioclient_mock.call_count == 0

    await client.send_json(
        {"id": 3, "type": f"{DOMAIN}/article_search", "query": "butter", "store": "Metro"}
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "invalid_store"

    # tapping the hit adds it with store, price and offer
    item = manager.shopping_add(
        hit["title"],
        store=hit["branch_id"],
        price=hit["price"],
        pack=hit["pack"],
        offer_id=hit["offer"]["id"],
    )
    assert (item["store_override"], item["store_reason"]) == (aldi["id"], "manual")
    assert (item["price"], item["offer"]["id"]) == (2.22, offer["id"])
    assert item["description"] == "🏪 Aldi Süd · ≈ 2,22 € · 🏷️ Aldi Süd 2,22 €"

    await client.send_json({"id": 4, "type": f"{DOMAIN}/compare_prices", "item": "Butter"})
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"]["results"][0]["retailer"] == "aldi-sued"


@pytest.fixture
async def marktguru_entry(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
) -> MockConfigEntry:
    """Integration with marktguru offers enabled (clock moved before the ws token)."""
    aioclient_mock.get(MARKTGURU_HOME, text=HOME_HTML)
    aioclient_mock.get(
        f"{MARKTGURU_API}/offers/search",
        json={
            "results": [
                _mg_offer(
                    11,
                    "Weidebutter",
                    "aldi-sued",
                    "Aldi Süd",
                    1.79,
                    2.19,
                    7.16,
                    "kg",
                    "250-g-Packung",
                ),
                _mg_offer(12, "Butter", "lidl", "Lidl", 1.59, None, 6.36, "kg", "250-g-Packung"),
            ]
        },
    )
    return await _setup(
        hass, config_entry, freezer, **{CONF_OFFERS_SOURCE: "marktguru", CONF_ZIP: "10115"}
    )


async def test_live_marktguru(
    hass: HomeAssistant,
    marktguru_entry: MockConfigEntry,
    freezer,
    hass_ws_client,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Live offers for the main branch's postcode, filtered to its retailer and cached."""
    config_entry = marktguru_entry
    manager = config_entry.runtime_data
    aldi = manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})
    client = await hass_ws_client(hass)

    await client.send_json(
        {"id": 1, "type": f"{DOMAIN}/article_search", "query": "butter", "live": True}
    )
    msg = await client.receive_json()
    assert msg["success"]
    result = msg["result"]
    assert (result["live"], result["error"]) == (True, None)
    live = [r for r in result["results"] if r["source"] == "live"]
    assert [(r["title"], r["price"], r["pack"]) for r in live] == [("Weidebutter", 1.79, "250 g")]
    assert live[0]["offer"]["id"] == "mg_11"
    assert live[0]["branch_id"] == aldi["id"]
    assert live[0]["offer"]["image"].endswith("/11/images/default/0/medium.jpg")
    searches = [c for c in aioclient_mock.mock_calls if "offers/search" in str(c[1])]
    assert len(searches) == 1
    assert "80331" in str(searches[0][1])  # the branch postcode, not the zip option

    # cached for an hour (also for another store at the same postcode)
    await client.send_json(
        {"id": 2, "type": f"{DOMAIN}/article_search", "query": "Butter", "live": True}
    )
    msg = await client.receive_json()
    assert [r["title"] for r in msg["result"]["results"] if r["source"] == "live"] == [
        "Weidebutter"
    ]
    response = await manager.async_search_articles_live("butter", "Lidl")
    assert [r["title"] for r in response["results"]] == ["Butter"]
    assert len([c for c in aioclient_mock.mock_calls if "offers/search" in str(c[1])]) == 1

    # short queries are not sent; after an hour the cache is refreshed
    assert (await manager.async_search_articles_live("bu"))["live"] is False
    freezer.tick(3601)
    await manager.async_search_articles_live("butter")
    assert len([c for c in aioclient_mock.mock_calls if "offers/search" in str(c[1])]) == 2


async def test_live_unavailable_and_provider(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Errors are reported; providers per retailer can be added (REWE in a later phase)."""
    aioclient_mock.get(MARKTGURU_HOME, status=503)
    await _setup(
        hass, config_entry, freezer, **{CONF_OFFERS_SOURCE: "marktguru", CONF_ZIP: "10115"}
    )
    manager = config_entry.runtime_data
    manager.save_branch({"store": "REWE", "postcode": "80331"})
    response = await manager.async_search_articles_live("butter")
    assert response["live"] is True
    assert response["results"] == []
    assert "HTTP 503" in response["error"]

    calls = []

    async def provider(manager, query, branch, retailer):
        calls.append((query, branch["retailer"], retailer))
        return [
            {
                "id": "rewe_1",
                "title": "ja! Butter",
                "product": "ja! Butter",
                "store": "REWE",
                "store_id": "rewe",
                "retailer": "rewe",
                "price": 1.69,
                "pack_amount": 250.0,
                "pack_unit": "g",
            }
        ]

    articles.register_live_provider("rewe", provider)
    try:
        response = await manager.async_search_articles_live("Butter")
    finally:
        articles.LIVE_PROVIDERS.pop("rewe")
    assert calls == [("Butter", "rewe", "rewe")]
    assert [(r["title"], r["price"], r["source"]) for r in response["results"]] == [
        ("ja! Butter", 1.69, "live")
    ]
    assert "HTTP 503" in response["error"]  # marktguru still failed
