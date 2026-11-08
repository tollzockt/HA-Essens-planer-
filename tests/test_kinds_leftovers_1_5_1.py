"""1.5.1: recipe kinds (meals, snacks, drinks, sides, components …) and cooking for another
day (leftovers, "🍲 Reste"), plus the hints for what whole packs leave over.

The setup has the starter recipes (conftest: Wednesday 2026-11-04, 10:00)."""

from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import intent
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.essensplaner import occasions as occ
from custom_components.essensplaner.const import DOMAIN, STORAGE_KEY
from custom_components.essensplaner.kinds import (
    KINDS,
    PART_KINDS,
    classify_kind,
    recipe_kind,
    set_kind,
)

ROOT = Path(__file__).parent.parent / "custom_components" / DOMAIN
PACK: list[dict[str, Any]] = json.loads((ROOT / "starter_recipes.json").read_text("utf-8"))
TODAY = date(2026, 11, 4)  # Wednesday
TUESDAY = date(2026, 11, 10)
WEDNESDAY = date(2026, 11, 11)
THURSDAY = date(2026, 11, 12)
DINNER = "abendessen"
LUNCH = "mittagessen"


async def _call(hass: HomeAssistant, service: str, **data: Any) -> Any:
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


async def _speech(hass: HomeAssistant, intent_type: str, **slots: Any) -> str:
    response = await intent.async_handle(
        hass,
        "test",
        intent_type,
        {key: {"value": value} for key, value in slots.items()},
        language="de",
    )
    return response.speech["plain"]["speech"]


@pytest.fixture
def manager(setup_integration: MockConfigEntry) -> Any:
    """The manager with the starter recipes."""
    return setup_integration.runtime_data


def _recipe(manager: Any, name: str) -> dict[str, Any]:
    recipe = manager.get_recipe_by_name(name)
    assert recipe is not None, name
    return recipe


# ----------------------------------------------------------------------
# Kinds
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "tags", "kind"),
    [
        # what the user named: drinks and components are never a meal
        ("Eistee", [], "drink"),
        ("Pfirsich-Eistee", ["Sommer"], "drink"),
        ("Erdbeerbowle", [], "drink"),
        ("Kinderpunsch", [], "drink"),
        ("Glühwein", [], "drink"),
        ("Rhabarberschorle", [], "drink"),
        ("Kräuterbutter", [], "component"),
        ("Aioli", [], "component"),
        ("Tzatziki", [], "component"),
        ("Caesar Dressing", [], "component"),
        ("Sauce Hollandaise", [], "component"),
        ("Knoblauch-Dip", [], "component"),
        ("Kartoffelsalat", [], "side"),
        ("Kartoffelsalat mit Speck", [], "side"),
        ("Basmatireis", [], "side"),
        ("Pommes", [], "side"),
        ("Tiramisu", [], "dessert"),
        ("Vanilleeis", [], "dessert"),
        ("Apfelkuchen", [], "snack"),
        ("Popcorn", [], "snack"),
        ("Porridge", [], "breakfast"),
        # dishes with a component in the name are meals
        ("Spaghetti mit Tomatensauce", [], "meal"),
        ("Nudeln in Lachs-Sahne-Sauce", [], "meal"),
        ("Pellkartoffeln mit Quark", [], "meal"),
        ("Gebratener Reis mit Ei", [], "meal"),
        ("Pfannkuchen", [], "meal"),
        ("Bierteig-Fisch", [], "meal"),
        ("Hühnersuppe", [], "meal"),
        # tags first: a main dish tag wins, a dip tagged "Snack" stays a component
        ("Frühlingsrollen", ["Hauptgericht", "Snack"], "meal"),
        ("Guacamole", ["Dip", "Snack"], "component"),
        ("Feldsalat", ["Vorspeise", "Salat"], "side"),
        ("Räucherlachs-Häppchen", ["Vorspeise", "Fingerfood"], "snack"),
        ("Hausgetränk", ["Getränk"], "drink"),
    ],
)
def test_classify_kind(name: str, tags: list[str], kind: str) -> None:
    """The rules classify by tags, then the dish's name."""
    assert classify_kind({"name": name, "tags": tags}) == kind


def test_classify_by_ingredients() -> None:
    """Mostly drinks among the ingredients: a drink (an unknown name)."""
    recipe = {
        "name": "Sommernachtstraum",
        "tags": [],
        "ingredients": [{"name": "Orangensaft"}, {"name": "Weißwein"}, {"name": "Zitrone"}],
    }
    assert classify_kind(recipe) == "drink"
    recipe["ingredients"] = [{"name": "Hähnchenbrust"}, {"name": "Orangensaft"}]
    assert classify_kind(recipe) == "meal"


def test_bundled_recipes_have_sensible_kinds() -> None:
    """Every bundled drink is a drink, every side / dip never a meal, every main dish a
    meal; all kinds occur."""
    kinds = {r["name"]: classify_kind(r) for r in PACK}
    assert set(kinds.values()) == set(KINDS)
    for recipe in PACK:
        tags = {t.lower() for t in recipe["tags"]}
        if "getränk" in tags:
            assert kinds[recipe["name"]] == "drink", recipe["name"]
        elif "hauptgericht" in tags:
            assert kinds[recipe["name"]] == "meal", recipe["name"]
        elif tags & {"beilage", "dip"}:
            assert kinds[recipe["name"]] in ("side", "component"), recipe["name"]
    assert kinds["Kräuterbutter"] == "component"
    assert kinds["Kartoffelsalat"] == "side"
    assert kinds["Eistee"] == "drink"


def test_kind_sources() -> None:
    """The user's choice is never overwritten (not by the rules, not by the AI); the AI
    overwrites the rules; "auto" from the user hands the kind back to the rules."""
    recipe: dict[str, Any] = {"name": "Kräuterbutter", "tags": []}
    assert set_kind(recipe, None, "rule")
    assert (recipe["kind"], recipe["kind_source"]) == ("component", "rule")
    assert set_kind(recipe, "side", "ai")
    assert (recipe["kind"], recipe["kind_source"]) == ("side", "ai")
    assert not set_kind(recipe, None, "rule")  # the rules keep the AI's choice
    assert set_kind(recipe, "snack", "user")
    assert not set_kind(recipe, "drink", "ai")
    assert not set_kind(recipe, None, "rule")
    assert (recipe["kind"], recipe["kind_source"]) == ("snack", "user")
    assert set_kind(recipe, "auto", "user")
    assert (recipe["kind"], recipe["kind_source"]) == ("component", "rule")


async def test_recipe_kind_services(hass: HomeAssistant, manager: Any) -> None:
    """add_recipe / update_recipe take a kind (also German words); a rule kind follows
    the tags, a chosen one stays; an unknown kind is an error."""
    result = await _call(hass, "add_recipe", name="Knoblauchsoße nach Oma", kind="Bestandteil")
    recipe = manager.recipes[result["recipe"]["id"]]
    assert (recipe["kind"], recipe["kind_source"]) == ("component", "user")
    result = await _call(hass, "add_recipe", name="Grillteller")
    rid = result["recipe"]["id"]
    assert (manager.recipes[rid]["kind"], manager.recipes[rid]["kind_source"]) == ("meal", "rule")
    await _call(hass, "update_recipe", recipe=rid, tags="Beilage, Grillen")
    assert manager.recipes[rid]["kind"] == "side"  # the rules follow the tags
    await _call(hass, "update_recipe", recipe=rid, kind="meal")
    await _call(hass, "update_recipe", recipe=rid, tags="Beilage, Dip")
    assert (manager.recipes[rid]["kind"], manager.recipes[rid]["kind_source"]) == ("meal", "user")
    await _call(hass, "update_recipe", recipe=rid, kind="auto")
    assert (manager.recipes[rid]["kind"], manager.recipes[rid]["kind_source"]) == (
        "component",
        "rule",
    )
    summary = (await _call(hass, "get_recipes", query="Grillteller"))["recipes"][0]
    assert summary["kind"] == "component" and summary["kind_source"] == "rule"
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "update_recipe", recipe=rid, kind="Hauptsache")
    assert err.value.translation_key == "invalid_kind"
    # exported and imported again with its kind
    exported = manager.export_recipes([result["recipe"]["id"]])[0]
    assert exported["kind"] == "component" and exported["kind_source"] == "rule"
    own = manager.export_recipes([recipe["id"]])[0]
    manager.delete_recipe(recipe["id"])
    manager.import_recipes([own])
    imported = manager.get_recipe_by_name("Knoblauchsoße nach Oma")
    assert (imported["kind"], imported["kind_source"]) == ("component", "user")


async def test_only_slot_kinds_fill_meal_slots(hass: HomeAssistant, manager: Any) -> None:
    """Suggestions and the auto plan never fill a slot with a drink, side, component or
    dessert – not even the snack slot; a meal tagged "Frühstück" fits the breakfast."""
    _recipe(manager, "Tiramisu")
    for _ in range(4):
        for meal in (DINNER, LUNCH, "snack", "fruehstueck", None):
            for recipe in manager.suggest(30, meal=meal):
                assert recipe_kind(recipe) not in PART_KINDS, (meal, recipe["name"])
    snack = {r["name"] for r in manager.suggest(60, meal="snack")}
    assert "Tiramisu" not in snack and "Apfelkuchen vom Blech" in snack
    assert manager._fits_meal(_recipe(manager, "Pfannkuchen"), "fruehstueck")
    assert manager._fits_meal(_recipe(manager, "Pfannkuchen"), DINNER)
    assert not manager._fits_meal(_recipe(manager, "Overnight Oats"), DINNER)
    planned = manager.auto_plan(TUESDAY, 7, meals=["fruehstueck", LUNCH, DINNER], overwrite=True)
    assert planned
    for view in planned:
        assert recipe_kind(manager.recipes[view["recipe_id"]]) not in PART_KINDS, view


async def test_user_kind_counts_for_plan_and_occasions(
    hass: HomeAssistant, manager: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dish the user calls a side is no main course of an occasion and no meal of the
    week; one the user calls a meal is."""
    monkeypatch.setattr(occ, "MAX_SUGGESTIONS", 500)
    salad = _recipe(manager, "Kartoffelsalat")
    assert "main" not in occ.recipe_courses(salad)
    salad = manager.update_recipe(salad["id"], {"kind": "meal"})
    assert "main" in occ.recipe_courses(salad) and manager._fits_meal(salad, DINNER)
    lasagne = manager.update_recipe(_recipe(manager, "Lasagne")["id"], {"kind": "side"})
    assert occ.recipe_courses(lasagne) == {"side"}
    occasion = occ.save_occasion(manager, {"title": "Familienessen", "date": "2026-11-14"})
    mains = {s["recipe_id"] for s in occ.suggest_course(manager, occasion, "main", count=500)}
    assert lasagne["id"] not in mains and salad["id"] in mains
    assert all(
        manager._fits_meal(manager.recipes[rid], None) for rid in mains
    )  # no drink, side or dessert as the main course


async def test_kinds_migration(
    hass: HomeAssistant, config_entry: MockConfigEntry, hass_storage, freezer
) -> None:
    """v6: stored recipes without a kind get one by the rules (once; a second run changes
    nothing), a user's kind stays."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(datetime.fromisoformat("2026-11-04T10:00:00+01:00"))
    key = f"{STORAGE_KEY}.{config_entry.entry_id}"
    hass_storage[key] = {
        "version": 1,
        "minor_version": 1,
        "key": key,
        "data": {
            "recipes": {
                "a": {"id": "a", "name": "Eistee", "tags": [], "ingredients": [], "steps": []},
                "b": {"id": "b", "name": "Kräuterbutter", "tags": ["Grillen"]},
                "c": {"id": "c", "name": "Lasagne", "tags": ["Pasta"]},
                "d": {"id": "d", "name": "Aioli", "kind": "meal", "kind_source": "user"},
            },
            "plan": {},
            "shopping": [],
            "starter_names": [p["name"] for p in PACK],
            "data_version": 5,
        },
    }
    assert await async_setup_component(hass, "homeassistant", {})
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    manager = config_entry.runtime_data
    assert manager.data_version == 6
    kinds = {rid: (r["kind"], r["kind_source"]) for rid, r in manager.recipes.items()}
    assert kinds == {
        "a": ("drink", "rule"),
        "b": ("component", "rule"),
        "c": ("meal", "rule"),
        "d": ("meal", "user"),
    }
    stored = hass_storage[key]["data"]
    assert stored["data_version"] == 6 and stored["recipes"]["a"]["kind"] == "drink"
    assert manager._migrate_kinds() == 0
    assert manager._migrate_v2() is False


# ----------------------------------------------------------------------
# Extras ("Dazu")
# ----------------------------------------------------------------------


async def test_component_joins_the_meal(hass: HomeAssistant, manager: Any) -> None:
    """A component planned onto a meal becomes its extra; extras join the shopping list
    and the costs; the same dish keeps them, [] removes them."""
    steaks = _recipe(manager, "Marinierte Nackensteaks vom Grill")
    butter = _recipe(manager, "Kräuterbutter")
    manager.plan_meal(TUESDAY, DINNER, steaks, servings=4)
    result = await _call(
        hass, "plan_meal", date=TUESDAY.isoformat(), meal=DINNER, recipe="Kräuterbutter"
    )
    assert result["entry"]["added_as_extra"] == "Kräuterbutter"
    entry = manager.plan[TUESDAY.isoformat()][DINNER]
    assert entry["recipe_id"] == steaks["id"]
    assert entry["extras"] == [{"title": "Kräuterbutter", "recipe_id": butter["id"]}]
    view = manager.entry_view(TUESDAY, DINNER, entry)
    assert view["extras"][0]["kind"] == "component" and view["extras"][0]["servings"] == 4
    # the costs and the shopping list include the extra
    costs = manager.plan_costs(TUESDAY, 1)["days"][0]["meals"][0]["cost"]
    alone = manager.recipe_cost(steaks, 4, TUESDAY)["total"]
    assert costs == pytest.approx(alone + manager.recipe_cost(butter, 4, TUESDAY)["total"])
    shopping = manager.generate_shopping_list(TUESDAY, 1)
    recipes = {r for i in manager.shopping for r in i.get("recipes") or []}
    assert {"Kräuterbutter", steaks["name"]} <= recipes and shopping["meals"] == 1
    # free extras via the service, the same dish keeps them, [] removes them
    await _call(
        hass,
        "plan_meal",
        date=TUESDAY.isoformat(),
        meal=DINNER,
        recipe=steaks["id"],
        extras="Kräuterbutter, Senf vom Markt",
    )
    titles = [x["title"] for x in manager.plan[TUESDAY.isoformat()][DINNER]["extras"]]
    assert titles == ["Kräuterbutter", "Senf vom Markt"]
    assert "Senf vom Markt" in manager.generate_shopping_list(TUESDAY, 1)["meals_without_recipe"]
    manager.plan_meal(TUESDAY, DINNER, steaks, servings=2)
    assert len(manager.plan[TUESDAY.isoformat()][DINNER]["extras"]) == 2
    manager.plan_meal(TUESDAY, DINNER, steaks, extras=[])
    assert "extras" not in manager.plan[TUESDAY.isoformat()][DINNER]
    # a component in an empty slot is planned as asked (allowed, the panel puts it "Dazu")
    manager.plan_meal(WEDNESDAY, DINNER, butter)
    assert manager.plan[WEDNESDAY.isoformat()][DINNER]["recipe_id"] == butter["id"]


# ----------------------------------------------------------------------
# Leftovers ("Dienstag für Mittwoch kochen")
# ----------------------------------------------------------------------


def _amounts(manager: Any) -> dict[str, dict[str, float]]:
    return {i["key"]: i["amounts"] for i in manager.shopping if i.get("source") == "plan"}


async def test_leftovers_shopping_and_costs(hass: HomeAssistant, manager: Any) -> None:
    """The cooking day is bought and priced for its servings plus the leftovers'; the
    leftovers cost nothing and add nothing to the list."""
    lasagne = _recipe(manager, "Lasagne")
    manager.plan_meal(TUESDAY, DINNER, lasagne, servings=4)
    manager.generate_shopping_list(TUESDAY, 2)
    four = _amounts(manager)
    cost_four = manager.plan_costs(TUESDAY, 2)["total"]

    manager.plan_meal(TUESDAY, DINNER, lasagne, servings=2)
    result = await _call(
        hass,
        "plan_leftover",
        date=WEDNESDAY.isoformat(),
        from_date=TUESDAY.isoformat(),
        servings=2,
    )
    entry = result["entry"]
    assert entry["title"] == "🍲 Reste von Dienstag (Lasagne)"
    assert entry["dish"] == "Lasagne" and entry["meal"] == DINNER
    assert entry["leftover_of"]["date"] == TUESDAY.isoformat()
    assert result["cooking"]["cook_servings"] == 4
    assert result["cooking"]["leftovers"] == [
        {"date": WEDNESDAY.isoformat(), "meal": DINNER, "weekday": "Mittwoch", "servings": 2}
    ]
    shopping = manager.generate_shopping_list(TUESDAY, 2)
    assert _amounts(manager) == four
    assert shopping["meals"] == 1 and shopping["meals_without_recipe"] == []
    costs = manager.plan_costs(TUESDAY, 2)
    assert costs["total"] == pytest.approx(cost_four)
    assert costs["days"][1]["meals"][0] == {
        "meal": DINNER,
        "meal_label": "Abendessen",
        "title": "🍲 Reste von Dienstag (Lasagne)",
        "recipe_id": lasagne["id"],
        "cost": 0,
        "on_offer": [],
        "leftover": True,
    }
    # only the leftovers' day: nothing to buy (bought on the cooking day)
    assert manager.generate_shopping_list(WEDNESDAY, 1)["items"] == []
    # leftovers of the leftovers come from the cooking day; not before cooking
    view = manager.plan_leftover(THURSDAY, LUNCH, WEDNESDAY, DINNER, servings=1)
    assert view["leftover_of"]["date"] == TUESDAY.isoformat()
    assert (
        manager.entry_view(TUESDAY, DINNER, manager.plan[TUESDAY.isoformat()][DINNER])[
            "cook_servings"
        ]
        == 5
    )
    with pytest.raises(ServiceValidationError) as err:
        manager.plan_leftover(TUESDAY, LUNCH, TUESDAY, DINNER)
    assert err.value.translation_key == "leftover_not_after"
    with pytest.raises(ServiceValidationError):
        manager.plan_leftover(date(2026, 11, 20), DINNER, TUESDAY, DINNER)  # 10 days later


async def test_leftovers_shown_everywhere(hass: HomeAssistant, manager: Any) -> None:
    """Sensors, the calendar and voice name the leftovers."""
    lasagne = _recipe(manager, "Lasagne")
    manager.plan_meal(TODAY, LUNCH, lasagne, servings=2)
    manager.plan_leftover(TODAY, DINNER, TODAY, LUNCH)
    manager.plan_leftover(date(2026, 11, 5), DINNER, TODAY, LUNCH)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.essensplaner_tomorrow").state == (
        "🍲 Reste von Mittwoch (Lasagne)"
    )
    assert "Abendessen: 🍲 Reste vom Mittagessen (Lasagne)" in (
        hass.states.get("sensor.essensplaner_today").state
    )
    events = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": "calendar.essensplaner_meal_plan",
            "start_date_time": "2026-11-04T00:00:00+01:00",
            "end_date_time": "2026-11-06T00:00:00+01:00",
        },
        blocking=True,
        return_response=True,
    )
    by_summary = {e["summary"]: e for e in events["calendar.essensplaner_meal_plan"]["events"]}
    cooking = by_summary["Mittagessen: Lasagne"]
    assert (
        "Mitkochen für Mittwoch (2 Portionen), Donnerstag (2 Portionen)" in (cooking["description"])
    )
    leftover = by_summary["Abendessen: 🍲 Reste von Mittwoch (Lasagne)"]
    assert "Vorgekocht am Mittwoch (Mittagessen)" in leftover["description"]
    assert "Zutaten" not in leftover["description"]
    speech = await _speech(hass, "essensplaner_get_meals", date="morgen")
    assert speech == "Morgen gibt es zum Abendessen Reste von Mittwoch (Lasagne)."


async def test_leftovers_cooked(hass: HomeAssistant, manager: Any) -> None:
    """The cooking day counts as cooked once; the leftovers never count."""
    lasagne = _recipe(manager, "Lasagne")
    before = int(lasagne.get("cooked_count") or 0)
    manager.plan_meal(TUESDAY, DINNER, lasagne)
    manager.plan_leftover(WEDNESDAY, DINNER, TUESDAY, DINNER)
    manager.mark_cooked(None, WEDNESDAY, DINNER)  # eaten: it was cooked on Tuesday
    assert manager.plan[TUESDAY.isoformat()][DINNER]["cooked"] is True
    assert manager.plan[WEDNESDAY.isoformat()][DINNER]["cooked"] is True
    assert lasagne["cooked_count"] == before + 1
    assert lasagne["last_cooked"] == TUESDAY.isoformat()
    manager.mark_cooked(None, TUESDAY, DINNER)
    manager.mark_cooked(lasagne, WEDNESDAY)
    assert lasagne["cooked_count"] == before + 1


async def test_leftovers_follow_moves_and_deletes(hass: HomeAssistant, manager: Any) -> None:
    """Moving the cooking meal earlier keeps the link, after the leftovers or another
    dish there ends it, deleting it too – the leftovers are then cooked on their own day."""
    lasagne = _recipe(manager, "Lasagne")
    monday = date(2026, 11, 9)
    manager.plan_meal(TUESDAY, DINNER, lasagne)
    manager.plan_leftover(WEDNESDAY, DINNER, TUESDAY, DINNER)
    manager.move_meal(TUESDAY, DINNER, monday, DINNER)
    link = manager.plan[WEDNESDAY.isoformat()][DINNER]["leftover_of"]
    assert link == {"date": monday.isoformat(), "meal": DINNER}
    result = manager.move_meal(monday, DINNER, THURSDAY, DINNER)
    assert [v["date"] for v in result["leftovers_unlinked"]] == [WEDNESDAY.isoformat()]
    assert "leftover_of" not in manager.plan[WEDNESDAY.isoformat()][DINNER]
    # delete: the leftovers become a normal meal (with a message)
    manager.plan_leftover(date(2026, 11, 13), DINNER, THURSDAY, DINNER)
    removed = (await _call(hass, "remove_meal", date=THURSDAY.isoformat(), meal=DINNER))["removed"]
    assert [v["title"] for v in removed[0]["leftovers_unlinked"]] == ["Lasagne"]
    friday = manager.plan["2026-11-13"][DINNER]
    assert "leftover_of" not in friday and friday["recipe_id"] == lasagne["id"]
    # another dish on the cooking day ends the link too
    manager.plan_meal(TUESDAY, DINNER, lasagne)
    manager.plan_leftover(WEDNESDAY, LUNCH, TUESDAY, DINNER)
    manager.plan_meal(TUESDAY, DINNER, _recipe(manager, "Chili con Carne"))
    assert "leftover_of" not in manager.plan[WEDNESDAY.isoformat()][LUNCH]
    # copying a week copies the link with it
    manager.plan_meal(TUESDAY, DINNER, lasagne)
    manager.plan_leftover(WEDNESDAY, LUNCH, TUESDAY, DINNER)
    manager.copy_plan(monday, date(2026, 11, 16), 7, overwrite=True)
    assert manager.plan["2026-11-18"][LUNCH]["leftover_of"] == {
        "date": "2026-11-17",
        "meal": DINNER,
    }


async def test_plan_leftover_intent(hass: HomeAssistant, manager: Any) -> None:
    """ "Koch am Dienstag für Mittwoch mit": the planned dish of the cooking day."""
    manager.plan_meal(TUESDAY, DINNER, _recipe(manager, "Lasagne"), servings=2)
    speech = await _speech(
        hass,
        "essensplaner_plan_leftover",
        from_date=TUESDAY.isoformat(),
        to_date=WEDNESDAY.isoformat(),
    )
    assert speech.startswith("Alles klar: Lasagne wird am Dienstag")
    assert "für 4 Portionen gekocht" in speech and "zum Abendessen gibt es die Reste" in speech
    assert manager.plan[WEDNESDAY.isoformat()][DINNER]["leftover_of"]["date"] == "2026-11-10"
    speech = await _speech(
        hass, "essensplaner_plan_leftover", from_date="2026-11-12", to_date="2026-11-13"
    )
    assert "nichts geplant" in speech
    speech = await _speech(hass, "essensplaner_remove_meal", date=TUESDAY.isoformat())
    assert speech.endswith("wird Lasagne jetzt frisch gekocht.")
    assert "leftover_of" not in manager.plan[WEDNESDAY.isoformat()][DINNER]


# ----------------------------------------------------------------------
# What whole packs leave over
# ----------------------------------------------------------------------


async def test_pack_leftover_hint(hass: HomeAssistant, manager: Any) -> None:
    """500 g minced meat bought, 300 g needed: "↪ 200 g übrig – z. B. für …" with up to
    two meals that use it (not the one it is bought for); nothing is planned."""
    recipe = manager.add_recipe(
        {
            "name": "Testpfanne mit Hack",
            "servings": 2,
            "ingredients": "300 g Hackfleisch\n1 Zwiebel",
            "tags": "Hauptgericht",
        }
    )
    manager.plan_meal(TUESDAY, DINNER, recipe, servings=2)
    planned = json.dumps(manager.plan, sort_keys=True)
    result = await _call(hass, "generate_shopping_list", start_date=TUESDAY.isoformat(), days=1)
    assert json.dumps(manager.plan, sort_keys=True) == planned
    leftovers = {x["name"]: x for x in result["leftovers"]}
    hint = leftovers["Hackfleisch"]
    assert (hint["amount"], hint["unit"], hint["text"]) == (200.0, "g", "200 g")
    assert 1 <= len(hint["recipes"]) <= 2
    for found in hint["recipes"]:
        assert manager.recipes[found["id"]]["kind"] == "meal"
        assert found["name"] != "Testpfanne mit Hack"
    item = next(i for i in result["items"] if i["summary"].endswith("Hackfleisch"))
    assert f"↪ 200 g übrig – z. B. für {hint['recipes'][0]['name']}" in item["description"]
    assert item["leftover"]["text"] == "200 g"
    # the whole pack used: no hint
    manager.update_recipe(recipe["id"], {"ingredients": "500 g Hackfleisch\n1 Zwiebel"})
    result = await _call(hass, "generate_shopping_list", start_date=TUESDAY.isoformat(), days=1)
    assert "Hackfleisch" not in {x["name"] for x in result["leftovers"]}


# ----------------------------------------------------------------------
# Panel and card (static checks; the UI itself is checked in the browser)
# ----------------------------------------------------------------------


def test_panel_uses_kinds_and_leftovers() -> None:
    """The panel filters by kind, puts parts "Dazu", plans leftovers with the services
    that exist; panel and card name the leftovers (helpers not in common.js: a cached old
    common.js must not break them)."""
    panel = (ROOT / "frontend" / "essensplaner-panel.js").read_text("utf-8")
    card = (ROOT / "frontend" / "essensplaner-card.js").read_text("utf-8")
    common = (ROOT / "frontend" / "essensplaner-common.js").read_text("utf-8")
    for label in (
        "🍽️ Mahlzeiten",
        "🥪 Snacks",
        "🍰 Desserts",
        "🥤 Getränke",
        "🧈 Beilagen & Bestandteile",
        "☕ Frühstück",
        "➕ Dazu",
        "🍲 Für einen weiteren Tag mitkochen",
        "🍲 Reste essen",
    ):
        assert label in panel, label
    for kind in KINDS:
        assert f"{kind}: " in panel.split("const KIND_LABELS = ", 1)[1].split("};", 1)[0], kind
    assert '_service("plan_leftover"' in panel and "extras:" in panel
    assert "leftovers_unlinked" in panel
    for source in (panel, card):
        assert "const entryTitle = " in source and "🍲 Reste" in source
    assert "entryTitle" not in common
