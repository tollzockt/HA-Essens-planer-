"""Integration tests for the Essensplaner."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import intent, llm
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.essensplaner.const import DOMAIN
from custom_components.essensplaner.intents import INTENT_HANDLERS

from .test_parsers import PAGE

TODAY_SENSOR = "sensor.essensplaner_today"
TOMORROW_SENSOR = "sensor.essensplaner_tomorrow"
NEXT_SENSOR = "sensor.essensplaner_next_meal"
WEEK_SENSOR = "sensor.essensplaner_week_plan"
RECIPES_SENSOR = "sensor.essensplaner_recipes"
CALENDAR = "calendar.essensplaner_meal_plan"
TODO = "todo.essensplaner_shopping_list"
STARTER_COUNT = len(
    json.loads(
        (
            Path(__file__).parent.parent / "custom_components/essensplaner/starter_recipes.json"
        ).read_text()
    )
)


async def _call(hass: HomeAssistant, service: str, **data):
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


async def _intent(hass: HomeAssistant, intent_type: str, **slots) -> intent.IntentResponse:
    return await intent.async_handle(
        hass,
        "test",
        intent_type,
        {key: {"value": value} for key, value in slots.items()},
        language="de",
    )


async def test_setup_creates_entities(hass: HomeAssistant, setup_integration) -> None:
    """All entities exist and starter recipes are imported."""
    for entity_id in (
        TODAY_SENSOR,
        TOMORROW_SENSOR,
        NEXT_SENSOR,
        WEEK_SENSOR,
        RECIPES_SENSOR,
        CALENDAR,
        TODO,
    ):
        assert hass.states.get(entity_id) is not None, entity_id
    assert int(hass.states.get(RECIPES_SENSOR).state) == STARTER_COUNT >= 100
    assert hass.states.get(TODAY_SENSOR).state == "Nichts geplant"
    assert hass.states.get(TODO).state == "0"


async def test_plan_and_query(hass: HomeAssistant, setup_integration) -> None:
    """Plan meals via service and read them back via sensors and services."""
    response = await _call(hass, "plan_meal", date="heute", recipe="lasagne")
    assert response["recipe_found"] is True
    assert response["entry"]["title"] == "Lasagne"
    assert response["entry"]["meal"] == "abendessen"
    await _call(hass, "plan_meal", date="morgen mittag", title="Pizza bestellen")
    await hass.async_block_till_done()

    assert hass.states.get(TODAY_SENSOR).state == "Lasagne"
    assert hass.states.get(TODAY_SENSOR).attributes["abendessen"] == "Lasagne"
    assert hass.states.get(TOMORROW_SENSOR).state == "Pizza bestellen"
    next_meal = hass.states.get(NEXT_SENSOR)
    assert next_meal.state == "Lasagne"
    assert "250 g Lasagneplatten" in next_meal.attributes["ingredients"][0] or any(
        "Lasagneplatten" in line for line in next_meal.attributes["ingredients"]
    )
    assert hass.states.get(WEEK_SENSOR).state == "2"

    plan = await _call(hass, "get_plan", days=2)
    assert [len(day["meals"]) for day in plan["days"]] == [1, 1]

    removed = await _call(hass, "remove_meal", date="morgen")
    assert removed["removed"][0]["title"] == "Pizza bestellen"


async def test_recipe_crud(hass: HomeAssistant, setup_integration) -> None:
    """Add, scale, update and delete recipes."""
    added = await _call(
        hass,
        "add_recipe",
        name="Testsuppe",
        servings=2,
        ingredients="500 g Drachenfrucht\n1 Zwiebel\n400 ml Kokosmilch",
        steps="Schneiden.\nKochen.",
        tags="Suppe, vegetarisch",
        total_time=30,
    )
    recipe = added["recipe"]
    assert recipe["ingredient_lines"] == ["500 g Drachenfrucht", "1 Zwiebel", "400 ml Kokosmilch"]
    assert recipe["steps"] == ["Schneiden.", "Kochen."]

    scaled = await _call(hass, "get_recipe", recipe="testsuppe", servings=4)
    assert scaled["recipe"]["ingredient_lines"] == [
        "1 kg Drachenfrucht",
        "2 Zwiebeln",
        "800 ml Kokosmilch",
    ]

    found = await _call(hass, "get_recipes", query="drachenfrucht")
    assert [r["name"] for r in found["recipes"]] == ["Testsuppe"]

    updated = await _call(hass, "update_recipe", recipe="Testsuppe", favorite=True)
    assert updated["recipe"]["favorite"] is True

    await _call(hass, "delete_recipe", recipe="Testsuppe")
    found = await _call(hass, "get_recipes", query="drachenfrucht")
    assert found["count"] == 0


async def test_shopping_list(hass: HomeAssistant, setup_integration) -> None:
    """Shopping list is generated from the plan and merges ingredients."""
    await _call(hass, "plan_meal", date="heute", recipe="Spaghetti Bolognese", servings=4)
    await _call(hass, "plan_meal", date="morgen", recipe="Chili con Carne", servings=2)
    result = await _call(hass, "generate_shopping_list", days=2)
    summaries = [i["summary"] for i in result["items"]]
    assert result["meals"] == 2
    assert "750 g Rinderhackfleisch" in summaries
    assert "2 Zwiebeln" in summaries
    assert not any("Salz" in s for s in summaries)
    await hass.async_block_till_done()
    assert hass.states.get(TODO).state == str(len(summaries))

    # completed items stay completed when regenerating
    items = await hass.services.async_call(
        "todo", "get_items", {"entity_id": TODO}, blocking=True, return_response=True
    )
    first = items[TODO]["items"][0]
    await hass.services.async_call(
        "todo",
        "update_item",
        {"entity_id": TODO, "item": first["uid"], "status": "completed"},
        blocking=True,
    )
    await hass.services.async_call(
        "todo", "add_item", {"entity_id": TODO, "item": "Klopapier"}, blocking=True
    )
    await _call(hass, "generate_shopping_list", days=2)
    items = await hass.services.async_call(
        "todo", "get_items", {"entity_id": TODO}, blocking=True, return_response=True
    )
    by_summary = {i["summary"]: i for i in items[TODO]["items"]}
    assert by_summary[first["summary"]]["status"] == "completed"
    assert "Klopapier" in by_summary


async def test_shopping_list_sync(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer
) -> None:
    """Items are copied to another todo list."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(datetime.fromisoformat("2026-11-04T10:00:00+01:00"))
    assert await async_setup_component(hass, "homeassistant", {})
    shopping_entry = MockConfigEntry(domain="shopping_list")
    shopping_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(shopping_entry.entry_id)
    await hass.async_block_till_done()
    target = next(iter(hass.states.async_entity_ids("todo")))
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, options={**config_entry.options, "shopping_sync_entity": target}
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    async def clear_target() -> None:
        items = await hass.services.async_call(
            "todo", "get_items", {"entity_id": target}, blocking=True, return_response=True
        )
        uids = [i["uid"] for i in items[target]["items"]]
        if uids:
            await hass.services.async_call(
                "todo", "remove_item", {"entity_id": target, "item": uids}, blocking=True
            )

    await clear_target()  # shopping_list persists its items in the test config dir
    await _call(hass, "plan_meal", date="heute", recipe="Spaghetti Aglio e Olio")
    result = await _call(hass, "generate_shopping_list", days=1)
    assert result["synced_to"] == target
    assert result["synced_items"] == len(result["items"])
    # second run does not duplicate
    result = await _call(hass, "generate_shopping_list", days=1)
    assert result["synced_items"] == 0
    await clear_target()


async def test_suggest_and_auto_plan(hass: HomeAssistant, setup_integration) -> None:
    """Suggestions respect tags/meals, auto plan fills empty days."""
    result = await _call(hass, "suggest_recipes", count=20, tag="vegetarisch")
    assert result["recipes"]
    assert all(any(t.lower() == "vegetarisch" for t in r["tags"]) for r in result["recipes"])
    breakfast = await _call(hass, "suggest_recipes", count=20, meal="frühstück")
    assert breakfast["recipes"]
    assert all("Frühstück" in r["tags"] for r in breakfast["recipes"])
    dinner = await _call(hass, "suggest_recipes", count=20, meal="abendessen")
    names = {r["name"] for r in dinner["recipes"]}
    assert "Overnight Oats" not in names
    assert "Bananenbrot" not in names

    await _call(hass, "plan_meal", date="morgen", recipe="Lasagne")
    planned = await _call(hass, "auto_plan", days=7)
    assert len(planned["planned"]) == 6  # tomorrow was already planned
    titles = [p["title"] for p in planned["planned"]]
    assert len(set(titles)) == len(titles)
    assert "Lasagne" not in titles


async def test_calendar(hass: HomeAssistant, setup_integration) -> None:
    """Meals appear as calendar events and can be created/deleted."""
    await _call(hass, "plan_meal", date="heute", recipe="Lasagne")
    await hass.services.async_call(
        "calendar",
        "create_event",
        {
            "entity_id": CALENDAR,
            "summary": "Mittagessen: Kartoffelsuppe",
            "start_date": "2026-11-05",
            "end_date": "2026-11-06",
        },
        blocking=True,
    )
    events = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": CALENDAR,
            "start_date_time": "2026-11-04T00:00:00+01:00",
            "end_date_time": "2026-11-06T00:00:00+01:00",
        },
        blocking=True,
        return_response=True,
    )
    summaries = [e["summary"] for e in events[CALENDAR]["events"]]
    assert summaries == ["Abendessen: Lasagne", "Mittagessen: Kartoffelsuppe"]
    state = hass.states.get(CALENDAR)
    assert state.attributes["message"] == "Abendessen: Lasagne"


async def test_intents(hass: HomeAssistant, setup_integration) -> None:
    """Intents give German spoken answers."""
    response = await _intent(hass, "essensplaner_get_meals", date="heute")
    assert response.speech["plain"]["speech"] == "Für heute ist noch nichts geplant."

    response = await _intent(
        hass, "essensplaner_plan_meal", dish="bolognese", date="Freitag", meal="abends"
    )
    assert response.response_type == intent.IntentResponseType.ACTION_DONE
    assert (
        response.speech["plain"]["speech"]
        == "Ich habe Spaghetti Bolognese für übermorgen zum Abendessen eingeplant."
    )

    response = await _intent(hass, "essensplaner_plan_meal", dish="Döner", date="morgen")
    assert "Notiz" in response.speech["plain"]["speech"]

    response = await _intent(hass, "essensplaner_get_meals", date="übermorgen")
    assert (
        response.speech["plain"]["speech"]
        == "Übermorgen gibt es zum Abendessen Spaghetti Bolognese."
    )

    response = await _intent(hass, "essensplaner_get_week_plan")
    speech = response.speech["plain"]["speech"]
    assert "Donnerstag: Abendessen Döner" in speech
    assert "Freitag: Abendessen Spaghetti Bolognese" in speech

    response = await _intent(hass, "essensplaner_get_recipe", dish="Aglio Olio", servings=4)
    speech = response.speech["plain"]["speech"]
    assert speech.startswith("Spaghetti Aglio e Olio für 4 Portionen")
    assert "500 g Spaghetti" in speech

    response = await _intent(hass, "essensplaner_suggest_recipes", tag="vegetarisch")
    assert response.speech["plain"]["speech"].startswith("Wie wäre es mit")

    response = await _intent(hass, "essensplaner_create_shopping_list", days=3)
    assert response.speech["plain"]["speech"].startswith("Die Einkaufsliste ist fertig")
    assert "Döner" in response.speech["plain"]["speech"]

    response = await _intent(hass, "essensplaner_remove_meal", date="morgen")
    assert response.speech["plain"]["speech"] == "Ich habe Döner für morgen aus dem Plan entfernt."

    response = await _intent(hass, "essensplaner_get_recipe", dish="Schweinshaxe")
    assert response.response_type == intent.IntentResponseType.ERROR
    assert response.speech["plain"]["speech"] == "Ich habe kein Rezept „Schweinshaxe“ gefunden."

    response = await _intent(hass, "essensplaner_get_meals", date="Blumenkohl")
    assert response.response_type == intent.IntentResponseType.ERROR

    response = await _intent(
        hass,
        "essensplaner_add_recipe",
        name="Rührei",
        ingredients="3 Eier, 1 EL Butter, Salz",
        tags="Frühstück, schnell",
    )
    assert (
        response.speech["plain"]["speech"]
        == "Ich habe das Rezept Rührei mit 3 Zutaten gespeichert."
    )

    response = await _intent(hass, "essensplaner_search_recipes", query="Hähnchen")
    assert "Hähnchen-Reis-Pfanne" in response.speech["plain"]["speech"]

    response = await _intent(hass, "essensplaner_mark_cooked", dish="Rührei")
    assert "Rührei" in response.speech["plain"]["speech"]


async def test_llm_tools(hass: HomeAssistant, setup_integration) -> None:
    """The intents are exposed as LLM tools of the Assist API (used by Jarvis/MCP)."""
    llm_context = llm.LLMContext(
        platform="test",
        context=Context(),
        language="de",
        assistant="conversation",
        device_id=None,
    )
    api = await llm.async_get_api(hass, "assist", llm_context)
    tool_names = {tool.name for tool in api.tools}
    for handler in INTENT_HANDLERS:
        assert handler.intent_type in tool_names

    # Tool parameters can be converted to JSON schema (needed by LLM providers / MCP)
    from voluptuous_openapi import convert

    for tool in api.tools:
        if tool.name.startswith("essensplaner_"):
            schema = convert(tool.parameters)
            assert schema["type"] == "object"

    result = await api.async_call_tool(
        llm.ToolInput(
            tool_name="essensplaner_plan_meal",
            tool_args={"dish": "Lasagne", "date": "morgen"},
        )
    )
    assert result["response_type"] == "action_done"
    assert "Lasagne" in result["speech"]["plain"]["speech"]

    result = await api.async_call_tool(
        llm.ToolInput(tool_name="essensplaner_get_meals", tool_args={"date": "morgen"})
    )
    assert result["speech"]["plain"]["speech"] == "Morgen gibt es zum Abendessen Lasagne."
    assert result["speech_slots"]["meals"][0]["title"] == "Lasagne"


async def test_import_recipe(
    hass: HomeAssistant, setup_integration, aioclient_mock: AiohttpClientMocker
) -> None:
    """Recipes are imported from web pages."""
    aioclient_mock.get("https://example.com/rezept", text=PAGE)
    result = await _call(hass, "import_recipe", url="https://example.com/rezept")
    assert result["created"] is True
    assert result["recipe"]["name"] == "Omas Käsespätzle"
    assert result["recipe"]["ingredient_lines"][1] == "5 Eier"
    # importing again updates instead of duplicating
    result = await _call(hass, "import_recipe", url="https://example.com/rezept")
    assert result["created"] is False

    aioclient_mock.get("https://example.com/leer", text="<html></html>")
    response = await _intent(hass, "essensplaner_import_recipe", url="https://example.com/leer")
    assert response.response_type == intent.IntentResponseType.ERROR
    assert "kein Rezept" in response.speech["plain"]["speech"]


async def test_persistence_and_unload(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Data survives a reload, intents are removed on unload."""
    await _call(hass, "plan_meal", date="heute", recipe="Linsensuppe")
    assert await hass.config_entries.async_reload(setup_integration.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(TODAY_SENSOR).state == "Linsensuppe"

    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()
    assert setup_integration.state is ConfigEntryState.NOT_LOADED
    handlers = {h.intent_type for h in intent.async_get(hass)}
    assert "essensplaner_get_meals" not in handlers
