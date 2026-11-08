"""1.5.1: the product of a shopping item for the needed amount – the smallest sufficient
pack when the costs are about the same, and fresh produce bought loose (one carrot is no
2-kg bag with "↪ 1920 g übrig").

All stores, addresses and brands are fictional (Musterstadt, 12345, Lindenweg)."""

from __future__ import annotations

from typing import Any

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.essensplaner.pricing import loose_produce
from custom_components.essensplaner.products import best_for, ingest_offer, save_manual

from .test_products_1_5 import TODAY, _branches, _offer


def _carrots(manager: Any, small_price: float) -> tuple[dict[str, Any], dict[str, Any]]:
    """Lidl: carrots in a 2-kg bag on offer (0,85 €) and in a 500-g bag."""
    big = ingest_offer(
        manager,
        _offer("mg_k2", "Karotten", 0.85, old=1.69, pack=(2000, "g"), keys=("karotte",)),
    )
    small = save_manual(
        manager,
        {
            "store": "Lidl",
            "name": "Karotten",
            "brand": "Sonnenhof",
            "pack": "500 g",
            "price": small_price,
            "ingredient": "Karotte",
        },
    )
    return big, small


async def test_smallest_sufficient_pack_when_costs_are_close(
    setup_integration: MockConfigEntry,
) -> None:
    """Cheapest for the needed amount in whole packs; within PACK_CLOSE_SHARE the smallest
    pack that is enough wins, a clearly cheaper bigger pack still wins."""
    manager = setup_integration.runtime_data
    _branches(manager)
    big, small = _carrots(manager, 0.89)
    # 400 g: 0,89 € (500 g) is about 0,85 € (2 kg) – the 500-g bag
    best = best_for(manager, "karotte", "lidl", {"g": 400}, TODAY, category="Obst & Gemüse")
    assert best["product"]["id"] == small["id"]
    assert (best["price"], best["packs"]) == (0.89, 1)
    # 1,5 kg: three 500-g bags (2,67 €) against one 2-kg bag (0,85 €)
    best = best_for(manager, "karotte", "lidl", {"g": 1500}, TODAY, category="Obst & Gemüse")
    assert best["product"]["id"] == big["id"]
    assert (best["price"], best["packs"]) == (0.85, 1)


async def test_much_cheaper_big_pack_still_wins(setup_integration: MockConfigEntry) -> None:
    manager = setup_integration.runtime_data
    _branches(manager)
    big, _small = _carrots(manager, 1.29)  # 52 % more than the 2-kg bag
    best = best_for(manager, "karotte", "lidl", {"g": 400}, TODAY, category="Obst & Gemüse")
    assert best["product"]["id"] == big["id"]


def test_loose_produce_rule() -> None:
    assert loose_produce("Obst & Gemüse", 25.0)  # 2 kg for one carrot (80 g)
    assert not loose_produce("Obst & Gemüse", 4.0)  # exactly 3× the need left over
    assert not loose_produce("Obst & Gemüse", None)
    assert not loose_produce("Fleisch & Fisch", 25.0)  # not sold loose


async def test_one_carrot_keeps_its_estimate(setup_integration: MockConfigEntry) -> None:
    """Only a 2-kg bag at the main store (1,69 €): "1 Karotte" keeps the estimate, gets no
    product and no leftover hint; 1,5 kg get the bag."""
    manager = setup_integration.runtime_data
    _branches(manager)
    bag = save_manual(
        manager,
        {
            "store": "Lidl",
            "name": "Karotten 2kg",
            "pack": "2 kg",
            "price": 1.69,
            "ingredient": "Karotte",
        },
    )
    recipe = manager.add_recipe(
        {"name": "Karottensalat", "servings": 2, "ingredients": "1 Karotte\n1 Zitrone"}
    )
    manager.plan_meal(manager.today(), "abendessen", recipe=recipe, servings=2)
    result = manager.generate_shopping_list(manager.today(), 1)
    carrot = next(i for i in manager.shopping if i.get("key") == "karotte")
    assert "product" not in carrot
    assert carrot["price"] is not None and carrot["price"] < 1.69
    assert "übrig" not in carrot["description"]
    assert "leftover" not in carrot
    assert "Karotte" not in {x["name"] for x in result["leftovers"]}

    manager.update_recipe(recipe["id"], {"ingredients": "1,5 kg Karotten\n1 Zitrone"})
    manager.generate_shopping_list(manager.today(), 1)
    carrot = next(i for i in manager.shopping if i.get("key") == "karotte")
    assert carrot["product"]["id"] == bag["id"]
    assert (carrot["price"], carrot["packs"]) == (1.69, 1)
