"""1.5 phase P3: the article search across all saved stores and the shopping list from the
product database.

Search (scope all: the article itself first, cheapest within, new fields, live sources of
every chain in parallel), the product of every list item (recipe product → ⭐ → pick →
cheapest, ⭐ binds the store), alternatives with products, descriptions, shopping_add with
product_id, "Produkt wechseln" (shopping_set_product, websocket, service), compare_prices
and the intents naming products, the list without store split, speed.

All stores, addresses and postcodes are fictional (Musterstadt, 12345, Lindenweg); brands
like "Bergland", "Sonnenhof" and "Wiesental" are made up."""

from __future__ import annotations

import asyncio
from datetime import datetime
import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import intent
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.essensplaner import articles
from custom_components.essensplaner.articles import (
    TIER_ARTICLE,
    TIER_WORD,
    cached_live_fetch,
    sort_all,
)
from custom_components.essensplaner.const import CONF_SPLIT_MODE
from custom_components.essensplaner.ingredients import aggregate, ingredient_key
from custom_components.essensplaner.products import (
    PICK_PICKED,
    ProductStore,
    ingest_offer,
    ingest_shop_products,
    record_pick,
    save_manual,
    set_favorite,
)

from .test_products_1_5 import _branches, _call, _offer, _setup, _shop, _ws

TODO = "todo.essensplaner_shopping_list"


@pytest.fixture(autouse=True)
def no_live_delay(monkeypatch) -> None:
    """No politeness delay between live requests (the clock is frozen)."""
    monkeypatch.setattr(articles, "LIVE_MIN_INTERVAL", 0)


def _products(manager: Any) -> dict[str, dict[str, Any]]:
    """Butter at the three chains (Lidl is the main branch) and a milk of Lidl.

    Lidl: Bergland 250 g 1,79 € (offer, normally 2,29 €), Sonnenhof 500 g 3,29 € (own),
    Sonnenhof Butterkekse 0,89 € (with the wrong ingredient "butter"), Wiesental milk
    1,19 €; ALDI SÜD: Milsani 250 g 1,59 € (weekly offer); REWE: ja! 250 g 1,89 € (online
    price) and the Bergland twin 2,39 €."""
    store: ProductStore = manager.products
    ingest_shop_products(
        manager,
        "rewe",
        [_shop("8-AB12", "ja! Deutsche Markenbutter 250g", 1.89, brand="ja!")],
        "butter",
        "rewe_online",
    )
    return {
        "bergland": ingest_offer(
            manager, _offer("mg_1", "Butter", 1.79, brand="Bergland", old=2.29)
        ),
        "sonnenhof": save_manual(
            manager,
            {
                "store": "Lidl",
                "name": "Butter",
                "brand": "Sonnenhof",
                "pack": "500 g",
                "price": 3.29,
            },
        ),
        "kekse": ingest_offer(
            manager, _offer("mg_3", "Butterkekse", 0.89, brand="Sonnenhof", pack=(200, "g"))
        ),
        "milch": save_manual(
            manager,
            {
                "store": "Lidl",
                "name": "Frische Vollmilch",
                "brand": "Wiesental",
                "pack": "1 l",
                "price": 1.19,
                "ingredient": "Milch",
            },
        ),
        "milsani": ingest_offer(
            manager,
            _offer(
                "mg_2", "Butter", 1.59, brand="Milsani", retailer="aldi-sued", source="aldi_weekly"
            ),
        ),
        "ja": store.get("rewe:8-AB12"),
        "bergland_rewe": ingest_offer(
            manager, _offer("mg_4", "Butter", 2.39, brand="Bergland", retailer="rewe")
        ),
    }


def _butter(manager: Any) -> dict[str, Any]:
    return next(i for i in manager.shopping if i.get("key") == "butter")


async def _intent_speech(hass: HomeAssistant, intent_type: str, **slots: Any) -> str:
    response = await intent.async_handle(
        hass,
        "test",
        intent_type,
        {key: {"value": value} for key, value in slots.items()},
        language="de",
    )
    return response.speech["plain"]["speech"]


# ----------------------------------------------------------------------
# Search across all stores
# ----------------------------------------------------------------------


async def test_search_all_stores_article_first_cheapest_first(
    hass: HomeAssistant, setup_integration: MockConfigEntry, hass_ws_client
) -> None:
    """scope all: products of every saved store, the article itself before other products,
    cheapest per kg within; image, brand, product, store and regular price of each hit; own
    store prices stay, learned ones only where the product database knows nothing."""
    manager = setup_integration.runtime_data
    branches = _branches(manager)
    products = _products(manager)

    results = manager.search_articles("Butter", scope="all")
    hits = [(r["title"], r["retailer"], r["price"]) for r in results]
    assert hits[:5] == [
        ("Milsani Butter", "aldi-sued", 1.59),  # 6,36 € / kg
        ("Sonnenhof Butter", "lidl", 3.29),  # 500 g: 6,58 € / kg
        ("Bergland Butter", "lidl", 1.79),
        ("ja! Deutsche Markenbutter 250g", "rewe", 1.89),
        ("Bergland Butter", "rewe", 2.39),
    ]
    assert {r["tier"] for r in results[:5]} == {TIER_ARTICLE}
    # "Butterkekse" (with the wrong ingredient butter) is no butter: after it, though cheaper
    kekse = next(r for r in results if r["title"] == "Sonnenhof Butterkekse")
    assert kekse["tier"] == TIER_WORD and results.index(kekse) == 5
    # the estimate of butter is left out (real prices), other estimates come without store
    assert all(r["title"] != "Butter" for r in results)
    milk = next(r for r in results if r["title"] == "Buttermilch")
    assert (milk["source"], milk["retailer"], milk["store_label"]) == ("default", None, None)

    first = results[0]
    assert first["source"] == "product" and first["real"] is True
    assert first["product_id"] == products["milsani"]["id"]
    assert (first["brand"], first["image"]) == ("Milsani", "https://cdn.example.org/mg_2.webp")
    assert first["branch_id"] == branches["aldi-sued"]["id"]
    assert first["store_label"] == "Aldi Süd Lindenweg 5"
    assert (first["pack"], first["unit_price"], first["base"]) == ("250 g", 0.00636, "g")
    assert first["offer"]["valid_to"] == "2026-11-07"
    bergland = results[2]
    assert bergland["regular_price"] == 2.29 and bergland["offer"]["old_price"] == 2.29
    assert bergland["branch_id"] == branches["lidl"]["id"]

    # an own store price is a hit; a learned one only where the database knows no product
    manager.set_store_price("Aldi Süd", "Butter", 1.49, 250, "g")
    assert manager.learn_store_price(
        "rewe", "butter", "REWE Butter", 1.29, 250, "g", "rewe_online", ref="8-ZZ99"
    )
    results = manager.search_articles("Butter", scope="all")
    assert (results[0]["title"], results[0]["source"], results[0]["price"]) == (
        "Butter",
        "store",
        1.49,
    )
    assert results[0]["store_label"] == "Aldi Süd Lindenweg 5"
    assert "REWE Butter" not in [r["title"] for r in results]

    # only one chain with store; scope main (voice, services) as in 1.4
    rewe_only = manager.search_articles("Butter", "REWE", scope="all")
    assert {r["retailer"] for r in rewe_only if r["retailer"]} == {"rewe"}
    main = manager.search_articles("Butter")
    assert {r["retailer"] for r in main} == {"lidl"}
    assert all("store_label" in r and "product_id" in r for r in main)
    assert len(manager.search_articles("Butter", scope="all", limit=3)) == 3

    # websocket: scope, default limit 20 for all, at most 50
    result = await _ws(hass, hass_ws_client, "article_search", query="Butter", scope="all")
    assert result["success"], result
    data = result["result"]
    assert (data["scope"], data["store"], data["live"]) == ("all", None, False)
    assert [r["title"] for r in data["results"][:2]] == ["Butter", "Milsani Butter"]
    assert len(data["results"]) <= 20
    result = await _ws(hass, hass_ws_client, "article_search", query="Butter")
    assert result["result"]["scope"] == "main"
    assert result["result"]["store"]["retailer"] == "lidl"
    result = await _ws(hass, hass_ws_client, "article_search", query="Butter", scope="x")
    assert not result["success"]


def test_sort_all_comparable_prices() -> None:
    """Within a tier the most common unit first (per piece for eggs), each by its price per
    unit; hits without a unit price after, estimates last within their tier."""

    def hit(title: str, price: float, per: float | None, base: str | None, **extra: Any):
        return {
            "title": title,
            "price": price,
            "unit_price": per,
            "base": base,
            "tier": TIER_ARTICLE,
            "source": "product",
            "offer": None,
            **extra,
        }

    results = [
        hit("Flüssigei 500 g", 2.49, 0.00498, "g"),
        hit("Eier 10 Stück", 2.99, 0.299, "Stück"),
        hit("Eier 6 Stück", 1.49, 0.248, "Stück"),
        hit("Eier lose", 0.35, None, None),
        hit("Eier (Richtwert)", 0.2, 0.2, "Stück", source="default"),
        hit("Eierlikör", 4.99, 0.00998, "ml", tier=TIER_WORD),
    ]
    assert [r["title"] for r in sort_all(results)] == [
        "Eier 6 Stück",
        "Eier 10 Stück",
        "Flüssigei 500 g",
        "Eier lose",
        "Eier (Richtwert)",
        "Eierlikör",
    ]


async def test_live_search_all_chains_in_parallel(
    hass: HomeAssistant, setup_integration: MockConfigEntry, monkeypatch
) -> None:
    """scope all asks the live source of every saved chain at once (one lock per provider
    host): a slow REWE answer does not hold up ALDI SÜD; the hits carry their branch and
    product, cheapest first."""
    manager = setup_integration.runtime_data
    branches = _branches(manager)
    rewe_started = asyncio.Event()
    rewe_release = asyncio.Event()
    aldi_done = asyncio.Event()
    calls: list[tuple[str, str | None, str | None]] = []

    async def rewe(manager: Any, query: str, branch: Any, retailer: str | None) -> list:
        calls.append(("rewe", (branch or {}).get("id"), retailer))

        async def fetch() -> list:
            rewe_started.set()
            await rewe_release.wait()
            return [_shop("8-CD34", "ja! Süßrahmbutter 250g", 1.99, brand="ja!")]

        return await cached_live_fetch(manager, (query, "rewe"), fetch, "rewe")

    async def aldi(manager: Any, query: str, branch: Any, retailer: str | None) -> list:
        calls.append(("aldi", (branch or {}).get("id"), retailer))

        async def fetch() -> list:
            aldi_done.set()
            return [
                _shop("000000000000202682", "Milsani Butter", 1.65, retailer="aldi-sued"),
                _shop("000000000000777777", "Butterkekse", 0.79, retailer="aldi-sued"),
            ]

        return await cached_live_fetch(manager, (query, "aldi"), fetch, "aldi")

    for retailer, provider in (("rewe", rewe), ("aldi-sued", aldi)):
        monkeypatch.setitem(articles.LIVE_PROVIDERS, retailer, provider)
        monkeypatch.delitem(articles.LIVE_PROVIDER_CHECKS, retailer, raising=False)
    search = asyncio.ensure_future(manager.async_search_articles_live("Butter", scope="all"))
    await rewe_started.wait()
    await asyncio.wait_for(aldi_done.wait(), 1)  # ALDI SÜD answered while REWE is busy
    rewe_release.set()
    response = await search
    assert response["live"] is True and response["error"] is None
    assert sorted(calls) == [
        ("aldi", branches["aldi-sued"]["id"], "aldi-sued"),
        ("rewe", branches["rewe"]["id"], "rewe"),
    ]
    hits = [(r["title"], r["retailer"], r["branch_id"]) for r in response["results"]]
    assert hits == [
        ("Milsani Butter", "aldi-sued", branches["aldi-sued"]["id"]),
        ("ja! Süßrahmbutter 250g", "rewe", branches["rewe"]["id"]),
        ("Butterkekse", "aldi-sued", branches["aldi-sued"]["id"]),
    ]
    first = response["results"][0]
    assert first["product_id"] == "aldi-sued:000000000000202682"  # stored by the search
    assert (first["store_label"], first["provider"]) == ("Aldi Süd Lindenweg 5", "aldi_online")
    # scope main: only the main store's chain (Lidl has no live source here)
    assert (await manager.async_search_articles_live("Butter"))["live"] is False


# ----------------------------------------------------------------------
# The shopping list from the product database
# ----------------------------------------------------------------------


async def test_list_products_choice_order_and_favorite_store(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Every item gets the product of its store: the recipe's product, else ⭐, a pick there,
    the cheapest (the offer it is priced with). ⭐ binds the store like "immer hier" (main
    store if it has the product or its twin; ignored for a paused store); picks do not."""
    manager = setup_integration.runtime_data
    branches = _branches(manager)
    products = _products(manager)
    store: ProductStore = manager.products
    recipe = manager.add_recipe(
        {
            "name": "Butterbrot",
            "servings": 1,
            "ingredients": [
                "250 g Butter",
                {"name": "Milch", "amount": 1, "unit": "l", "product_id": products["milch"]["id"]},
            ],
        }
    )
    assert recipe["ingredients"][1]["product_id"] == products["milch"]["id"]
    manager.plan_meal(manager.today(), "abendessen", recipe=recipe, servings=1)
    result = manager.generate_shopping_list(manager.today(), 1)

    butter = _butter(manager)
    assert (butter["retailer"], butter["store_reason"]) == ("lidl", "main")
    # the cheapest product of the main store (its offer replaces the estimate 1,99 €)
    assert butter["product"]["id"] == products["bergland"]["id"]
    assert (butter["product_reason"], butter["price"], butter["packs"]) == ("offer", 1.79, 1)
    assert butter["product"] == {
        "id": products["bergland"]["id"],
        "name": "Butter",
        "brand": "Bergland",
        "title": "Bergland Butter",
        "image": "https://cdn.example.org/mg_1.webp",
        "retailer": "lidl",
        "pack_amount": 250.0,
        "pack_unit": "g",
        "price": 1.79,
        "on_offer": True,
    }
    assert butter["offer"]["id"] == "mg_1"
    assert butter["description"].startswith(
        "🏪 Lidl Lindenweg 1 · 📦 Bergland Butter · Milchprodukte & Eier · ≈ 1,79 €"
    )
    # the other stores name their product
    alternatives = {a["retailer"]: a for a in butter["alternatives"]}
    assert alternatives["aldi-sued"]["product"] == {
        "id": products["milsani"]["id"],
        "name": "Butter",
        "brand": "Milsani",
        "title": "Milsani Butter",
        "image": "https://cdn.example.org/mg_2.webp",
    }
    assert alternatives["aldi-sued"]["price"] == 1.59
    assert alternatives["rewe"]["product"]["id"] == "rewe:8-AB12"
    # the recipe's product
    milk = next(i for i in manager.shopping if i["key"] == "milch")
    assert (milk["product"]["id"], milk["product_reason"]) == (products["milch"]["id"], "manual")
    assert milk["price"] == 1.19 and milk["product_id"] == products["milch"]["id"]
    assert "📦 Wiesental Frische Vollmilch" in milk["description"]
    listed = next(i for i in result["items"] if i["summary"] == butter["summary"])
    assert (listed["product"]["id"], listed["product_reason"]) == (
        products["bergland"]["id"],
        "offer",
    )
    # the to-do list shows the product
    response = await hass.services.async_call(
        "todo", "get_items", {"entity_id": TODO}, blocking=True, return_response=True
    )
    descriptions = [i.get("description") or "" for i in response[TODO]["items"]]
    assert any("📦 Bergland Butter" in d for d in descriptions)

    # picks: a product picked twice at the main store; one at ALDI SÜD does not move it
    for _ in range(2):
        record_pick(manager, "butter", products["sonnenhof"]["id"], PICK_PICKED)
        record_pick(manager, "butter", products["milsani"]["id"], PICK_PICKED)
    manager.assign_shopping_stores()
    butter = _butter(manager)
    assert (butter["retailer"], butter["store_reason"]) == ("lidl", "main")
    assert (butter["product"]["id"], butter["product_reason"]) == (
        products["sonnenhof"]["id"],
        "picked",
    )
    assert (butter["price"], butter["packs"], butter["offer"]) == (3.29, 1, None)
    # moved for another butter's offer: no pick there replaces the price that moved it
    for _ in range(2):
        record_pick(manager, "butter", products["ja"]["id"], PICK_PICKED)
    offer = manager.add_offer("Butter", "REWE", 1.49, "250 g")
    butter = _butter(manager)
    assert (butter["retailer"], butter["store_reason"], butter["price"]) == ("rewe", "offer", 1.49)
    assert "product" not in butter and butter["offer"]["id"] == offer["id"]
    manager.remove_offer(offer["id"])

    # ⭐ of another chain (own brand, no twin): the item goes there
    set_favorite(manager, products["ja"]["id"], "butter")
    manager.assign_shopping_stores()
    butter = _butter(manager)
    assert (butter["branch_id"], butter["store_reason"]) == (branches["rewe"]["id"], "favorite")
    assert (butter["product"]["id"], butter["product_reason"], butter["price"]) == (
        "rewe:8-AB12",
        "favorite",
        1.89,
    )
    # a branded ⭐ whose twin the main store has: the main store
    set_favorite(manager, products["bergland_rewe"]["id"], "butter")
    manager.assign_shopping_stores()
    butter = _butter(manager)
    assert (butter["retailer"], butter["store_reason"]) == ("lidl", "favorite")
    assert (butter["product"]["id"], butter["product_reason"]) == (
        products["bergland"]["id"],
        "favorite",
    )
    # "immer hier" and an own store choice beat the ⭐
    set_favorite(manager, products["ja"]["id"], "butter")
    manager.set_shopping_store("Butter", "Aldi Süd", always=True)
    butter = _butter(manager)
    assert (butter["retailer"], butter["store_reason"]) == ("aldi-sued", "manual")
    assert (butter["product"]["id"], butter["product_reason"]) == (
        products["milsani"]["id"],
        "picked",
    )
    manager.set_shopping_store("Butter", "auto", always=True)
    assert _butter(manager)["store_reason"] == "favorite"
    # a paused store: the ⭐ is ignored, the item is automatic again
    manager.save_branch({"id": branches["rewe"]["id"], "selected": False})
    manager.assign_shopping_stores()
    butter = _butter(manager)
    assert (butter["retailer"], butter["store_reason"]) == ("lidl", "main")
    assert butter["product"]["id"] == products["sonnenhof"]["id"]  # the pick there
    assert store.favorites["butter"] == products["ja"]["id"]


async def test_add_product_to_list(
    hass: HomeAssistant, setup_integration: MockConfigEntry, freezer
) -> None:
    """shopping_add(product_id): the item is the product, priced at its chain and bought
    there like a picked offer (an offer only while it runs), remembered as picked."""
    manager = setup_integration.runtime_data
    branches = _branches(manager)
    products = _products(manager)
    store: ProductStore = manager.products

    item = manager.shopping_add("", product_id=products["ja"]["id"])
    assert item["summary"] == "ja! Deutsche Markenbutter 250g"
    assert (item["key"], item["product_id"]) == ("butter", "rewe:8-AB12")
    assert item["store_override"] == branches["rewe"]["id"]
    assert (item["store_reason"], item["price"]) == ("manual", 1.89)
    assert (item["product"]["id"], item["product_reason"]) == ("rewe:8-AB12", "manual")
    assert item["chosen"]["product_id"] == "rewe:8-AB12"
    assert store.picks["butter"][0][:2] == ["rewe:8-AB12", 1]
    # it stays this product: another butter's offer there does not price it, a new shop
    # price of the product does
    offer = manager.add_offer("Butter", "REWE", 1.49, "250 g")
    item = next(i for i in manager.shopping if i["uid"] == item["uid"])
    assert (item["price"], item["offer"], item["product"]["id"]) == (1.89, None, "rewe:8-AB12")
    manager.remove_offer(offer["id"])
    ingest_shop_products(
        manager,
        "rewe",
        [_shop("8-AB12", "ja! Deutsche Markenbutter 250g", 1.95, brand="ja!")],
        "butter",
        "rewe_online",
    )
    manager.assign_shopping_stores()
    item = next(i for i in manager.shopping if i["uid"] == item["uid"])
    assert (item["price"], item["product"]["price"]) == (1.95, 1.95)

    # an offer of ALDI SÜD: the copy keeps image and brand; bought there until it ends
    offer_item = manager.shopping_add("Butter", product_id=products["milsani"]["id"])
    assert offer_item["store_override"] == branches["aldi-sued"]["id"]
    chosen = offer_item["chosen"]
    assert (chosen["offer_id"], chosen["pins_store"]) == ("mg_2", True)
    assert chosen["offer"]["image"] == "https://cdn.example.org/mg_2.webp"
    assert chosen["offer"]["brand"] == "Milsani"
    assert (offer_item["price"], offer_item["offer"]["id"]) == (1.59, "mg_2")
    assert "📦 Milsani Butter" in offer_item["description"]

    # a product of the main store keeps the item automatic
    main_item = manager.shopping_add("Butter", product_id=products["bergland"]["id"])
    assert "store_override" not in main_item
    assert (main_item["retailer"], main_item["product"]["id"]) == (
        "lidl",
        products["bergland"]["id"],
    )
    # another store: the same branded product there
    twin_item = manager.shopping_add("Butter", store="REWE", product_id=products["bergland"]["id"])
    assert twin_item["store_override"] == branches["rewe"]["id"]
    assert (twin_item["product"]["id"], twin_item["price"]) == (
        products["bergland_rewe"]["id"],
        2.39,
    )
    # the own product's twin prices the item at REWE: another butter's offer there does not
    # move it away from the main store
    offer = manager.add_offer("Butter", "REWE", 1.49, "250 g")
    main_item = next(i for i in manager.shopping if i["uid"] == main_item["uid"])
    assert (main_item["retailer"], main_item["product"]["id"], main_item["price"]) == (
        "lidl",
        products["bergland"]["id"],
        1.79,
    )
    rewe = next(a for a in main_item["alternatives"] if a["retailer"] == "rewe")
    assert (rewe["price"], rewe["product"]["id"]) == (2.39, products["bergland_rewe"]["id"])
    manager.remove_offer(offer["id"])
    with pytest.raises(ServiceValidationError) as err:
        manager.shopping_add("Butter", product_id="lidl:nope")
    assert err.value.translation_key == "product_not_found"

    # the service
    response = await _call(
        hass, "add_shopping_item", item="Butter", product_id=products["sonnenhof"]["id"]
    )
    assert response["item"]["product"]["id"] == products["sonnenhof"]["id"]
    assert response["item"]["price"] == 3.29

    # next week: the ALDI SÜD offer ended – the item is automatic again (main store)
    freezer.move_to(datetime.fromisoformat("2026-11-09T10:00:00+01:00"))
    manager.new_day()
    offer_item = next(i for i in manager.shopping if i["uid"] == offer_item["uid"])
    assert "store_override" not in offer_item
    assert offer_item["retailer"] == "lidl"
    assert offer_item["product_id"] == products["milsani"]["id"]  # no twin at Lidl


async def test_set_shopping_product(
    hass: HomeAssistant, setup_integration: MockConfigEntry, hass_ws_client
) -> None:
    """ "Produkt wechseln": the item becomes the product (its store with a store split),
    remembered as picked or ⭐; kept when the list is created again; reset; errors."""
    manager = setup_integration.runtime_data
    branches = _branches(manager)
    products = _products(manager)
    store: ProductStore = manager.products
    recipe = manager.add_recipe(
        {"name": "Butterbrot", "servings": 1, "ingredients": ["250 g Butter"]}
    )
    manager.plan_meal(manager.today(), "abendessen", recipe=recipe, servings=1)
    manager.generate_shopping_list(manager.today(), 1)
    uid = _butter(manager)["uid"]

    result = await _ws(
        hass,
        hass_ws_client,
        "shopping_set_product",
        uid=uid,
        product_id="rewe:8-AB12",
        remember="pick",
    )
    assert result["success"], result
    item = result["result"]["item"]
    assert (item["branch_id"], item["store_reason"]) == (branches["rewe"]["id"], "manual")
    assert (item["product"]["id"], item["product_reason"], item["price"]) == (
        "rewe:8-AB12",
        "manual",
        1.89,
    )
    assert store.picks["butter"][0][:2] == ["rewe:8-AB12", 1]
    assert [g["retailer"] for g in result["result"]["stores"]] == ["rewe"]

    # ⭐ with the service (item by name); the next list keeps the product and its store
    response = await _call(
        hass,
        "set_shopping_product",
        item="Butter",
        product_id=products["milsani"]["id"],
        remember="favorite",
    )
    assert response["item"]["retailer"] == "aldi-sued"
    assert store.favorites["butter"] == products["milsani"]["id"]
    manager.generate_shopping_list(manager.today(), 1)
    butter = _butter(manager)
    assert butter["uid"] != uid and butter["product_id"] == products["milsani"]["id"]
    assert (butter["retailer"], butter["product"]["id"], butter["price"]) == (
        "aldi-sued",
        products["milsani"]["id"],
        1.59,
    )

    # reset: the list chooses again – the store went with the product, the ⭐ binds ALDI SÜD
    result = await _ws(
        hass, hass_ws_client, "shopping_set_product", uid=butter["uid"], product_id=None
    )
    item = result["result"]["item"]
    assert "product_id" not in item and "chosen" not in item
    assert "store_override" not in item
    assert (item["retailer"], item["store_reason"], item["product_reason"]) == (
        "aldi-sued",
        "favorite",
        "favorite",
    )

    # errors
    result = await _ws(
        hass, hass_ws_client, "shopping_set_product", uid="nope", product_id="rewe:8-AB12"
    )
    assert result["error"]["code"] == "shopping_item_not_found"
    result = await _ws(
        hass, hass_ws_client, "shopping_set_product", uid=butter["uid"], product_id="x:1"
    )
    assert result["error"]["code"] == "product_not_found"
    result = await _ws(
        hass, hass_ws_client, "shopping_set_product", uid=butter["uid"], remember="always"
    )
    assert not result["success"]
    with pytest.raises(ServiceValidationError) as err:
        manager.shopping_set_product(butter["uid"], "rewe:8-AB12", "always")
    assert err.value.translation_key == "invalid_remember"


async def test_compare_prices_and_voice_name_products(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """compare_prices names the product behind each store's price (a real product price
    replaces an estimate); Jarvis says it and the ⭐ product of an added item."""
    manager = setup_integration.runtime_data
    _branches(manager)
    products = _products(manager)

    result = manager.compare_prices("Butter")
    by_store = {r["retailer"]: r for r in result["results"]}
    assert by_store["aldi-sued"]["product"]["title"] == "Milsani Butter"
    assert by_store["lidl"]["product"]["id"] == products["bergland"]["id"]
    assert (by_store["lidl"]["price"], by_store["lidl"]["real"]) == (1.79, True)  # not 1,99
    assert by_store["rewe"]["product"]["id"] == "rewe:8-AB12"
    assert result["cheapest"]["retailer"] == "aldi-sued"
    speech = await _intent_speech(hass, "essensplaner_compare_prices", item="Butter")
    assert speech.startswith(
        "Am günstigsten gibt es Butter bei Aldi Süd Lindenweg 5: 1,59 € (Milsani Butter, 250 g)"
    )

    set_favorite(manager, "rewe:8-AB12", "butter")
    speech = await _intent_speech(hass, "essensplaner_add_shopping_item", item="Butter")
    assert speech == (
        "Ich habe Butter auf die Einkaufsliste gesetzt – dein Lieblingsprodukt ja! Deutsche "
        "Markenbutter 250g bei REWE Lindenweg 3 etwa 1,89 €."
    )
    item = manager.shopping[-1]
    assert (item["store_reason"], item["product_reason"]) == ("favorite", "favorite")


async def test_list_without_store_split(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer
) -> None:
    """Without a store split the items get the product of the main store's chain (a ⭐ of
    another chain does not move anything); generated and added items alike."""
    manager = await _setup(hass, config_entry, freezer, **{CONF_SPLIT_MODE: "off"})
    _branches(manager)
    products = _products(manager)
    recipe = manager.add_recipe(
        {"name": "Butterbrot", "servings": 1, "ingredients": ["250 g Butter"]}
    )
    manager.plan_meal(manager.today(), "abendessen", recipe=recipe, servings=1)
    result = manager.generate_shopping_list(manager.today(), 1)
    butter = _butter(manager)
    assert "branch_id" not in butter
    assert (butter["product"]["id"], butter["price"]) == (products["bergland"]["id"], 1.79)
    assert butter["description"].startswith("📦 Bergland Butter · Milchprodukte & Eier · ≈ 1,79 €")
    assert result["total_price"] == 1.79
    set_favorite(manager, products["milsani"]["id"], "butter")  # ALDI SÜD, no twin at Lidl
    item = manager.shopping_add("Butter")
    assert "branch_id" not in item
    assert (item["product"]["id"], item["product_reason"]) == (
        products["bergland"]["id"],
        "offer",
    )
    set_favorite(manager, products["sonnenhof"]["id"], "butter")
    manager.shopping_update(item["uid"], summary="2 Butter")
    item = next(i for i in manager.shopping if i["uid"] == item["uid"])
    assert (item["product"]["id"], item["product_reason"], item["price"]) == (
        products["sonnenhof"]["id"],
        "favorite",
        6.58,
    )


def test_aggregate_keeps_the_recipe_product() -> None:
    """The product of a recipe ingredient goes with the merged list item (the first one)."""
    items = aggregate(
        [
            ({"name": "Butter", "amount": 100, "unit": "g", "product_id": "lidl:s1"}, "Kuchen"),
            ({"name": "Butter", "amount": 50, "unit": "g", "product_id": "rewe:2"}, "Brot"),
            ({"name": "Mehl", "amount": 500, "unit": "g"}, "Kuchen"),
        ]
    )
    by_key = {i["key"]: i for i in items}
    assert by_key["butter"]["product_id"] == "lidl:s1"
    assert by_key["butter"]["amounts"] == {"g": 150.0}
    assert "product_id" not in by_key[ingredient_key("Mehl")]


async def test_assign_with_products_fast(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """60 open items, 10 branches of 6 chains, about 2000 products: assigning all items
    again (stores, products, alternatives) stays fast."""
    manager = setup_integration.runtime_data
    chains = {
        "lidl": "Lidl",
        "rewe": "REWE",
        "aldi-sued": "Aldi Süd",
        "netto": "Netto",
        "norma": "Norma",
        "edeka": "EDEKA",
    }
    number = 0
    for retailer, name in chains.items():
        for _ in range(2 if retailer in ("lidl", "rewe", "netto", "norma") else 1):
            number += 1
            manager.save_branch(
                {
                    "store": name,
                    "street": f"Lindenweg {number}",
                    "postcode": "12345",
                    "city": "Musterstadt",
                }
            )
    words = [
        "Butter", "Milch", "Joghurt", "Quark", "Käse", "Hackfleisch", "Tomaten", "Zwiebeln",
        "Kartoffeln", "Nudeln", "Reis", "Mehl", "Zucker", "Eier", "Sahne", "Paprika",
        "Gurke", "Äpfel", "Bananen", "Brot", "Kaffee", "Tee", "Orangensaft", "Schokolade",
        "Chips", "Hähnchenbrust", "Lachs", "Spinat", "Brokkoli", "Möhren",
    ]  # fmt: skip
    count = 0
    for retailer in chains:
        for word in words:
            for brand in range(11):
                count += 1
                ingest_offer(
                    manager,
                    _offer(
                        f"mg_{count}",
                        word,
                        0.99 + brand / 10,
                        brand=f"Marke {brand}",
                        retailer=retailer,
                        keys=(ingredient_key(word),),
                        old=1.5 + brand / 10,
                    ),
                )
    assert len(manager.products.products) > 1900
    for word in words:
        manager.shopping_add(f"500 g {word}")
        manager.shopping_add(f"2 {word}")
    start = time.process_time()
    manager._reassign_open_items()
    elapsed = time.process_time() - start
    assert elapsed < 0.5, elapsed  # about 0.03 s on a desktop
    assert sum(1 for i in manager.shopping if i.get("product")) == 60
