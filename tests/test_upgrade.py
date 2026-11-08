"""Upgrades: 1.0/1.1 get the new bundled recipes once, 1.2 data is migrated to 1.3."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.essensplaner.const import CONF_OFFERS_SOURCE, CONF_ZIP, DOMAIN, STORAGE_KEY

PACK = json.loads(
    (
        Path(__file__).parent.parent / "custom_components/essensplaner/starter_recipes.json"
    ).read_text()
)


async def test_upgrade_adds_new_recipes(
    hass: HomeAssistant, config_entry: MockConfigEntry, hass_storage, freezer
) -> None:
    """Old storage (15 recipes, one deleted, one own) gets the new recipes, not the deleted one."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(datetime.fromisoformat("2026-11-05T10:00:00+01:00"))
    old_recipes = {}
    for index, recipe in enumerate(PACK[:15]):
        if recipe["name"] == "Lasagne":
            continue  # the user deleted it in 1.1
        old_recipes[f"r{index}"] = {
            "id": f"r{index}",
            "name": recipe["name"],
            "servings": 4,
            "ingredients": [],
            "steps": [],
            "tags": [],
        }
    old_recipes["own"] = {
        "id": "own",
        "name": "Omas Gulasch",
        "servings": 4,
        "ingredients": [],
        "steps": [],
        "tags": [],
    }
    hass_storage[f"{STORAGE_KEY}.{config_entry.entry_id}"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"{STORAGE_KEY}.{config_entry.entry_id}",
        "data": {"recipes": old_recipes, "plan": {}, "shopping": []},
    }
    assert await async_setup_component(hass, "homeassistant", {})
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    manager = config_entry.runtime_data
    names = {r["name"] for r in manager.recipes.values()}
    assert len(manager.recipes) == 14 + 1 + (len(PACK) - 15)
    assert "Lasagne" not in names  # deleted recipes stay deleted
    assert "Omas Gulasch" in names
    assert "Käsespätzle" in names

    # a reload does not add anything again
    await manager.async_save_now()
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert len(config_entry.runtime_data.recipes) == len(manager.recipes)
    result = await hass.services.async_call(
        DOMAIN, "import_starter_recipes", {}, blocking=True, return_response=True
    )
    assert result["added"] == ["Lasagne"]  # explicit import brings it back


async def test_upgrade_1_2_to_1_3(
    hass: HomeAssistant, config_entry: MockConfigEntry, hass_storage, freezer
) -> None:
    """1.2 data: labelled own prices become store prices, offers get a retailer (idempotent)."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(datetime.fromisoformat("2026-11-04T10:00:00+01:00"))
    key = f"{STORAGE_KEY}.{config_entry.entry_id}"
    prices = {
        "butter": {
            "name": "Butter",
            "price": 1.79,
            "amount": 250,
            "unit": "g",
            "store": "Lidl",
            "updated": "2026-10-01T10:00:00+00:00",
        },
        "kaese": {"name": "Käse", "price": 2.49, "amount": 400, "unit": "g", "store": "Aldi"},
        "milch": {"name": "Milch", "price": 1.09, "amount": 1000, "unit": "ml", "store": None},
        "quark": {"name": "Quark", "price": 0.89, "amount": 500, "unit": "g", "store": "Markt"},
    }

    def offer(offer_id: str, store: str, store_id: str, source: str) -> dict:
        return {
            "id": offer_id,
            "title": "Butter",
            "product": "Butter",
            "store": store,
            "store_id": store_id,
            "price": 1.11,
            "pack_amount": 250,
            "pack_unit": "g",
            "valid_to": "2026-11-30",
            "source": source,
            "keys": ["butter"],
        }

    hass_storage[key] = {
        "version": 1,
        "minor_version": 1,
        "key": key,
        "data": {
            "recipes": {},
            "plan": {},
            "shopping": [],
            "starter_names": [p["name"] for p in PACK],
            "prices": prices,
            "prices_learned": {},
            "offers": [
                offer("mg_1", "EDEKA Südwest", "edeka-suedwest", "marktguru"),
                offer("man_1", "Lidl", "lidl", "manual"),
                offer("man_2", "Wochenmarkt", "wochenmarkt", "manual"),
            ],
            "offers_meta": {},
        },
    }
    assert await async_setup_component(hass, "homeassistant", {})
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry,
        # the marktguru offer stays only while marktguru is on (1.4: offers of a source
        # switched off are dropped)
        options={**config_entry.options, CONF_ZIP: "80331", CONF_OFFERS_SOURCE: "marktguru"},
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    manager = config_entry.runtime_data

    assert manager.data_version == 4  # 1.4: drugstore branches (v4)
    assert manager.branches == []  # no legacy branches
    assert manager.main_branch is None
    assert manager.store_prices_user["lidl"]["butter"]["price"] == 1.79
    assert manager.store_prices_user["lidl"]["butter"]["updated"] == prices["butter"]["updated"]
    assert manager.store_prices_user["aldi-sued"]["kaese"]["price"] == 2.49  # zip 80331
    # a plain "Aldi" decided by the postcode is a guess: it follows the user's Aldi branch
    assert manager.store_prices_user["aldi-sued"]["kaese"]["guessed"] is True
    assert "retailer" not in manager.prices_user["kaese"]
    assert set(manager.store_prices_user) == {"lidl", "aldi-sued"}
    assert manager.prices_user["butter"]["store"] == "Lidl"  # general price kept
    assert manager.prices_user["butter"]["retailer"] == "lidl"
    assert "retailer" not in manager.prices_user["quark"]
    assert {o["id"]: o.get("retailer") for o in manager.offers} == {
        "mg_1": "edeka",
        "man_1": "lidl",
        "man_2": None,
    }
    # without branches prices work like 1.2
    assert manager.best_price("Butter")[1].price == 1.79
    # migrated data was written right away
    stored = hass_storage[key]["data"]
    assert stored["data_version"] == 4
    assert stored["store_prices_user"]["lidl"]["butter"]["price"] == 1.79

    # idempotent: a second run changes nothing, a reload neither
    snapshot = json.dumps(manager._data_to_store(), sort_keys=True, default=str)
    assert manager._migrate_v2() is False
    assert json.dumps(manager._data_to_store(), sort_keys=True, default=str) == snapshot
    manager.remove_store_price("lidl", "Butter")  # the user removes the store price
    await manager.async_save_now()
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    reloaded = config_entry.runtime_data
    assert "lidl" not in reloaded.store_prices_user  # not copied again
    assert reloaded.store_prices_user["aldi-sued"]["kaese"]["price"] == 2.49
    assert len(reloaded.offers) == 3
