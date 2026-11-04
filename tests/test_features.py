"""Tests for the features added in 1.1."""

from __future__ import annotations

from datetime import datetime
import json

from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.essensplaner.const import CONF_EXCLUDED, DOMAIN
from custom_components.essensplaner.diagnostics import async_get_config_entry_diagnostics

TODO = "todo.essensplaner_shopping_list"


async def _call(hass: HomeAssistant, service: str, **data):
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


async def _speech(hass: HomeAssistant, intent_type: str, **slots) -> str:
    response = await intent.async_handle(
        hass,
        "test",
        intent_type,
        {key: {"value": value} for key, value in slots.items()},
        language="de",
    )
    return response.speech["plain"]["speech"]


async def test_move_and_swap(hass: HomeAssistant, setup_integration) -> None:
    """Meals can be moved; occupied targets are swapped."""
    await _call(hass, "plan_meal", date="Freitag", recipe="Lasagne")
    await _call(hass, "plan_meal", date="Samstag", recipe="Linsensuppe")

    result = await _call(hass, "move_meal", recipe="Lasagne", to_date="Samstag")
    assert result["moved"]["date"] == "2026-11-07"
    assert result["swapped"]["title"] == "Linsensuppe"
    assert result["swapped"]["date"] == "2026-11-06"

    speech = await _speech(hass, "essensplaner_move_meal", dish="die Lasagne", to_date="Sonntag")
    assert speech == "Ich habe Lasagne auf Sonntag zum Abendessen verschoben."

    speech = await _speech(
        hass, "essensplaner_move_meal", dish="das Essen von Freitag", to_date="morgen"
    )
    assert speech.startswith("Ich habe Linsensuppe auf morgen")

    speech = await _speech(hass, "essensplaner_move_meal", dish="Schnitzel", to_date="morgen")
    assert "nicht geplant" in speech


async def test_copy_plan(hass: HomeAssistant, setup_integration) -> None:
    """Last week can be copied into this week."""
    await _call(hass, "plan_meal", date="2026-10-26", recipe="Lasagne")
    await _call(hass, "plan_meal", date="2026-10-28", meal="mittagessen", title="Reste")
    result = await _call(hass, "copy_plan")
    assert [(c["date"], c["title"]) for c in result["copied"]] == [
        ("2026-11-02", "Lasagne"),
        ("2026-11-04", "Reste"),
    ]
    assert all(not c["cooked"] for c in result["copied"])
    # running again does not overwrite
    result = await _call(hass, "copy_plan")
    assert result["copied"] == []


async def test_find_by_ingredients(hass: HomeAssistant, setup_integration) -> None:
    """Recipes are ranked by the ingredients at hand."""
    result = await _call(hass, "find_by_ingredients", ingredients="Hähnchen, Reis und Paprika")
    best = result["recipes"][0]
    assert best["name"] == "Hähnchen-Reis-Pfanne"
    assert set(best["uses"]) == {"Hähnchen", "Reis", "Paprika"}
    assert "500 g Hähnchenbrust" not in best["missing"]

    speech = await _speech(hass, "essensplaner_cook_with", ingredients="Feta und Zucchini")
    assert speech.startswith("Mit Feta und Zucchini kannst du Ofengemüse mit Feta kochen")

    speech = await _speech(hass, "essensplaner_cook_with", ingredients="Marshmallows")
    assert speech == "Mit Marshmallows habe ich leider kein passendes Rezept."


async def test_shopping_overview(hass: HomeAssistant, setup_integration) -> None:
    """The shopping list can be read back (e.g. by Jarvis)."""
    assert await _speech(hass, "essensplaner_get_shopping_list") == "Die Einkaufsliste ist leer."
    await _call(hass, "plan_meal", date="heute", recipe="Spaghetti Aglio e Olio")
    await _call(hass, "generate_shopping_list", days=1)
    overview = await _call(hass, "get_shopping_list")
    assert next(iter(overview["groups"])) == "Obst & Gemüse"
    assert "250 g Spaghetti" in overview["groups"]["Nudeln, Reis & Getreide"]
    speech = await _speech(hass, "essensplaner_get_shopping_list")
    assert speech.startswith(f"Auf der Einkaufsliste stehen {overview['open']} Einträge.")
    assert "Obst und Gemüse:" in speech


async def test_export_import(hass: HomeAssistant, setup_integration) -> None:
    """Recipes survive an export/import round trip."""
    exported = await _call(hass, "export_recipes", recipes=["Lasagne"])
    assert [r["name"] for r in exported["recipes"]] == ["Lasagne"]
    lasagne = exported["recipes"][0]
    assert "id" not in lasagne

    result = await _call(hass, "import_recipes", recipes=exported["recipes"])
    assert result == {"added": [], "updated": [], "skipped": ["Lasagne"]}

    new = {**lasagne, "name": "Vegetarische Lasagne", "tags": ["vegetarisch"]}
    result = await _call(hass, "import_recipes", recipes=json.dumps({"recipes": [new]}))
    assert result["added"] == ["Vegetarische Lasagne"]
    found = await _call(hass, "get_recipe", recipe="Vegetarische Lasagne")
    assert found["recipe"]["ingredient_lines"][0] == "250 g Lasagneplatten"


async def test_auto_mark_cooked(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer
) -> None:
    """Planned meals of past days count as cooked."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(datetime.fromisoformat("2026-11-03T10:00:00+01:00"))
    assert await async_setup_component(hass, "homeassistant", {})
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    await _call(hass, "plan_meal", date="heute", recipe="Lasagne")

    # next day the planned meal is counted
    freezer.move_to(datetime.fromisoformat("2026-11-04T10:00:00+01:00"))
    manager = config_entry.runtime_data
    assert manager.async_auto_mark_cooked() == 1
    lasagne = manager.find_recipe("Lasagne")
    assert lasagne["cooked_count"] == 1
    assert lasagne["last_cooked"] == "2026-11-03"
    # no double counting
    assert manager.async_auto_mark_cooked() == 0
    await _call(hass, "mark_cooked", date="gestern", recipe="Lasagne")
    assert lasagne["cooked_count"] == 1


async def test_exclusions(hass: HomeAssistant, config_entry: MockConfigEntry, freezer) -> None:
    """Excluded tags/ingredients are never suggested."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(datetime.fromisoformat("2026-11-04T10:00:00+01:00"))
    assert await async_setup_component(hass, "homeassistant", {})
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, options={**config_entry.options, CONF_EXCLUDED: "Fisch, Hackfleisch"}
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    result = await _call(hass, "suggest_recipes", count=20, meal="abendessen")
    names = {r["name"] for r in result["recipes"]}
    assert names
    assert not names & {
        "Lachs mit Ofenkartoffeln und Brokkoli",
        "Spaghetti Bolognese",
        "Chili con Carne",
        "Lasagne",
    }


async def test_buttons_and_diagnostics(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Buttons trigger planning and the shopping list."""
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.essensplaner_auto_plan_week"}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get("sensor.essensplaner_week_plan").state == "7"
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": "button.essensplaner_create_shopping_list"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert int(hass.states.get(TODO).state) > 10

    diagnostics = await async_get_config_entry_diagnostics(hass, setup_integration)
    assert diagnostics["counts"]["recipes"] == 15
    assert diagnostics["counts"]["planned_next_7_days"] == 7
