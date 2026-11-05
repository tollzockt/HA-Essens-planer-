"""Upgrading from 1.0/1.1 adds the new bundled recipes once."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.essensplaner.const import DOMAIN, STORAGE_KEY

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
