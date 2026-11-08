"""1.5.1: the profile – diet, allergies, liked cuisines and flavours, kitchen devices,
cooking days and time limits (profile.py) and how planning and suggestions use them.

The setup has the starter recipes (conftest: Wednesday 2026-11-04, 10:00)."""

from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path
import random
from typing import Any

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.essensplaner import options_schema as schema
from custom_components.essensplaner.const import DOMAIN
from custom_components.essensplaner.ingredients import normalize_ingredient
from custom_components.essensplaner.profile import (
    DEFAULT_KITCHEN,
    Profile,
    diet_allows,
    missing_devices,
    profile_filter,
    profile_from_options,
    profile_score,
    recipe_allergens,
    recipe_cuisines,
    recipe_devices,
    recipe_diet,
    recipe_minutes,
)
from custom_components.essensplaner.season import ai_payload, rank_candidates

ROOT = Path(__file__).parent.parent / "custom_components" / DOMAIN
PACK = {r["name"]: r for r in json.loads((ROOT / "starter_recipes.json").read_text("utf-8"))}
MONDAY = date(2026, 11, 9)
DINNER = "abendessen"


def _starter(name: str) -> dict[str, Any]:
    recipe = dict(PACK[name])
    recipe["ingredients"] = [normalize_ingredient(i) for i in recipe["ingredients"]]
    return recipe


def _lines(*lines: str) -> dict[str, Any]:
    return {"name": "Test", "ingredients": [normalize_ingredient(x) for x in lines]}


async def _profile(hass: HomeAssistant, entry: MockConfigEntry, **options: Any) -> Any:
    """Set profile options (the entry reloads) and return the new manager."""
    hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
    await hass.async_block_till_done()
    return entry.runtime_data


# ----------------------------------------------------------------------
# Detection
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "diet", "has", "has_not"),
    [
        ("Spaghetti Bolognese", "fleisch", {"gluten", "laktose", "sellerie"}, {"ei", "nuesse"}),
        # Kokosmilch, mehligkochende Kartoffeln and Muskatnuss: no milk, gluten or nuts
        ("Kürbissuppe", "vegan", set(), {"laktose", "gluten", "nuesse"}),
        ("Lachs mit Ofenkartoffeln und Brokkoli", "pescetarisch", {"fisch"}, {"krebstiere"}),
        ("Garnelen-Knoblauch-Pfanne mit Baguette", "pescetarisch", {"krebstiere"}, {"fisch"}),
        # soy sauce: soy and wheat; "Reis" is no egg – the eggs are
        ("Gebratener Reis mit Ei", "vegetarisch", {"ei", "soja", "gluten"}, {"laktose"}),
        ("Falafel-Bowl mit Hummus", "vegan", {"sesam", "gluten"}, {"ei", "laktose"}),
        # a ready meal without a "vegetarisch" tag: the filling is not known
        ("Ravioli aus der Dose", "fleisch", {"gluten"}, set()),
    ],
)
def test_diet_and_allergens_of_starter_recipes(
    name: str, diet: str, has: set[str], has_not: set[str]
) -> None:
    recipe = _starter(name)
    assert recipe_diet(recipe) == diet
    allergens = recipe_allergens(recipe)
    assert has <= allergens, allergens
    assert not allergens & has_not, allergens


@pytest.mark.parametrize(
    ("lines", "has", "has_not"),
    [
        (("200 g Reis", "1 Kugel Vanilleeis", "1/2 Eisbergsalat"), set(), {"ei"}),
        (("2 Eier", "1 EL Mayonnaise"), {"ei"}, set()),
        (("400 ml Kokosmilch",), set(), {"laktose", "nuesse"}),
        (("500 ml laktosefreie Milch",), set(), {"laktose"}),
        (("500 ml Milch",), {"laktose"}, set()),
        (("250 ml Mandelmilch",), {"nuesse"}, {"laktose"}),
        (("250 ml Hafermilch",), {"gluten"}, {"laktose"}),
        (("3 EL Sojasauce",), {"soja", "gluten"}, set()),
        (("3 EL glutenfreie Sojasauce",), {"soja"}, {"gluten"}),
        (("50 g vegane Butter",), set(), {"laktose"}),
        (("2 EL Erdnussbutter",), {"erdnuesse"}, {"laktose", "nuesse"}),
        (("1 Prise Muskatnuss",), set(), {"nuesse"}),
        (("1 kg Kartoffeln (mehligkochend)",), set(), {"gluten"}),
        (("200 g glutenfreie Nudeln", "100 g Reisnudeln"), set(), {"gluten"}),
        (("200 g Spaghetti",), {"gluten"}, set()),
        (("1 TL Senf", "1 Stange Staudensellerie"), {"senf", "sellerie"}, set()),
    ],
)
def test_allergen_words(lines: tuple[str, ...], has: set[str], has_not: set[str]) -> None:
    allergens = recipe_allergens(_lines(*lines))
    assert has <= allergens, allergens
    assert not allergens & has_not, allergens


def test_diet_words() -> None:
    assert recipe_diet(_lines("1 Dose gehackte Tomaten", "200 g Nudeln")) == "vegan"
    assert recipe_diet(_lines("400 g Hähnchenbrustfilet")) == "fleisch"
    assert recipe_diet(_lines("100 g Lachsschinken")) == "fleisch"
    assert recipe_diet(_lines("2 Fleischtomaten", "1 Ei")) == "vegetarisch"
    assert recipe_diet(_lines("200 g Thunfisch (Dose)")) == "pescetarisch"
    assert recipe_diet(_lines("1 Packung vegane Bratwurst")) == "vegan"
    assert diet_allows("vegan", "vegetarisch") and diet_allows("pescetarisch", "pescetarisch")
    assert not diet_allows("pescetarisch", "vegetarisch") and not diet_allows("fleisch", "vegan")
    assert diet_allows("fleisch", "flexitarisch")


def test_devices() -> None:
    kitchen = list(DEFAULT_KITCHEN)  # oven, stove, microwave
    assert missing_devices(_starter("Waffeln"), kitchen) == ["waffeleisen"]
    assert missing_devices(_starter("Käsefondue"), kitchen) == ["fondue"]
    assert missing_devices(_starter("Bratwürste vom Grill"), kitchen) == ["grill"]
    # a side for a barbecue does not need the grill
    assert missing_devices(_starter("Kartoffelsalat"), kitchen) == []
    # "auf den Grillrost … (oder im Ofen)": either
    assert missing_devices(_starter("Folienkartoffeln mit Kräuterquark"), kitchen) == []
    assert missing_devices(_starter("Folienkartoffeln mit Kräuterquark"), ["grill"]) == []
    # "braten (oder im Ofen backen)": the pan is enough
    fish = _starter("Fischstäbchen mit Püree aus der Packung")
    assert missing_devices(fish, ["herd"]) == []
    assert frozenset({"backofen", "herd"}) in recipe_devices(fish)
    assert missing_devices(_starter("Lasagne"), ["herd"]) == ["backofen"]
    assert missing_devices(_starter("Spaghetti Bolognese"), ["herd"]) == []
    # "im Ofen oder in der Mikrowelle" (a ready meal)
    ready = {
        "name": "Fertig-Lasagne",
        "tags": ["Fertiggericht"],
        "ingredients": [normalize_ingredient("1 Packung Lasagne (400 g)")],
        "steps": ["Die Lasagne im Backofen oder in der Mikrowelle nach Packungsangabe erhitzen."],
    }
    assert missing_devices(ready, ["mikrowelle"]) == []
    assert missing_devices(ready, ["herd"]) == ["backofen"]


def test_cuisines_and_time() -> None:
    assert recipe_cuisines(_starter("Spaghetti Bolognese")) == {"italienisch"}
    assert "asiatisch" in recipe_cuisines(_starter("Bami Goreng"))
    assert recipe_minutes({"prep_time": 10, "cook_time": 20}) == 30
    assert recipe_minutes({"total_time": 45, "prep_time": 10}) == 45
    assert recipe_minutes({}) is None


def test_profile_filter_and_score() -> None:
    bolognese = _starter("Spaghetti Bolognese")
    profile = Profile(diet="vegetarisch", allergies=frozenset({"gluten"}), excluded=("Karotte",))
    ok, reasons = profile_filter(bolognese, profile)
    assert not ok
    assert reasons == ["🥩 nicht vegetarisch", "⚠️ Gluten", "🚫 Karotte"]
    assert profile_filter(bolognese, Profile())[0]  # the defaults: as before
    # devices only when asked (occasions: no)
    waffles = _starter("Waffeln")
    assert profile_filter(waffles, Profile()) == (False, ["🔥 braucht Waffeleisen"])
    assert profile_filter(waffles, Profile(), devices=False) == (True, [])
    italian = Profile(cuisines=frozenset({"italienisch"}), flavors=frozenset({"scharf"}))
    assert profile_score(bolognese, italian) > profile_score(_starter("Linsensuppe"), italian)
    assert profile_score(bolognese, Profile()) == 1.0
    flexi = Profile(diet="flexitarisch")
    assert profile_score(bolognese, flexi) < profile_score(_starter("Linsensuppe"), flexi)


# ----------------------------------------------------------------------
# Options
# ----------------------------------------------------------------------


def test_options_validation() -> None:
    cleaned, errors = schema.validate({"cook_days": []})
    assert errors == {"cook_days": "no_cook_days"}
    assert "mindestens einen Tag" in schema.error_messages(errors)["cook_days"]
    _, errors = schema.validate({"weekday_time": 300, "weekend_time": -5})
    assert errors == {"weekday_time": "out_of_range", "weekend_time": "out_of_range"}
    cleaned, errors = schema.validate(
        {"weekday_time": "30", "weekend_time": 0, "cook_days": ["mon", "fri"], "kitchen": []}
    )
    assert not errors
    assert cleaned == {
        "weekday_time": 30,
        "weekend_time": 0,
        "cook_days": ["mon", "fri"],
        "kitchen": [],
    }
    _, errors = schema.validate({"diet": "keto", "allergies": ["gluten", "pollen"]})
    assert errors == {"diet": "invalid_choice", "allergies": "invalid_choice"}
    # the defaults keep the behaviour of 1.5
    defaults = schema.default_values()
    assert defaults["diet"] == "alles" and defaults["allergies"] == []
    assert defaults["cook_days"] == ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    assert defaults["kitchen"] == ["backofen", "herd", "mikrowelle"]
    assert defaults["weekday_time"] == 0 and defaults["weekend_time"] == 0
    assert profile_from_options({}) == Profile()
    # an emptied allergy list stays empty (not the default)
    assert schema.current_values({"allergies": []})["allergies"] == []


async def test_settings_websocket(
    hass: HomeAssistant, setup_integration: MockConfigEntry, hass_ws_client
) -> None:
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/get_settings"})
    res = (await client.receive_json())["result"]
    assert res["values"]["diet"] == "alles"
    assert {c["value"] for c in res["choices"]["diets"]} >= {"vegan", "flexitarisch"}
    assert [c["label"] for c in res["choices"]["allergens"]][:3] == ["Gluten", "Laktose", "Ei"]
    assert res["choices"]["times"][0] == {"value": 0, "label": "egal"}
    assert res["fields"]["weekday_time"] == {
        "section": "profile",
        "type": "int",
        "min": 0,
        "max": 240,
        "step": 5,
    }
    await client.send_json(
        {"id": 2, "type": f"{DOMAIN}/save_settings", "values": {"cook_days": []}}
    )
    res = (await client.receive_json())["result"]
    assert res["saved"] is False and "cook_days" in res["errors"]
    await client.send_json(
        {"id": 3, "type": f"{DOMAIN}/save_settings", "values": {"diet": "vegan"}}
    )
    assert (await client.receive_json())["result"] == {"saved": True, "reload": True}
    await hass.async_block_till_done()
    assert setup_integration.runtime_data.profile.diet == "vegan"


# ----------------------------------------------------------------------
# Planning and suggestions
# ----------------------------------------------------------------------


async def test_auto_plan_respects_diet_allergies_and_devices(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    manager = await _profile(
        hass,
        setup_integration,
        diet="vegetarisch",
        allergies=["gluten"],
        kitchen=["herd"],
    )
    planned = manager.auto_plan(MONDAY, 7, meals=[DINNER, "mittagessen"])
    assert len(planned) == 14
    for entry in planned:
        recipe = manager.recipes[entry["recipe_id"]]
        assert recipe_diet(recipe) in ("vegetarisch", "vegan"), recipe["name"]
        assert "gluten" not in recipe_allergens(recipe), recipe["name"]
        assert missing_devices(recipe, ["herd"]) == [], recipe["name"]
    # suggestions and the AI's candidates use the same rules
    for recipe in manager.suggest(10, meal=DINNER, around=MONDAY):
        assert not manager.profile_conflicts(recipe)
    for recipe in rank_candidates(manager, MONDAY, 7, [DINNER]):
        assert not manager.profile_conflicts(recipe)
    # the panel: badges for the recipes that do not fit
    data = manager.export()
    bolognese = manager.get_recipe_by_name("Spaghetti Bolognese")
    assert "🥩 nicht vegetarisch" in data["recipe_profile"][bolognese["id"]]
    assert data["profile"]["diet"] == "vegetarisch"


async def test_auto_plan_cook_days_and_time_limit(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    manager = await _profile(
        hass,
        setup_integration,
        cook_days=["mon", "tue", "wed", "thu", "fri"],
        weekday_time=30,
        enabled_meals=["fruehstueck", "mittagessen", "abendessen"],
    )
    planned = manager.auto_plan(MONDAY, 7, meals=["fruehstueck", DINNER])
    by_slot = {(e["date"], e["meal"]): e for e in planned}
    saturday, sunday = MONDAY + timedelta(days=5), MONDAY + timedelta(days=6)
    for offset in range(5):
        day = (MONDAY + timedelta(days=offset)).isoformat()
        recipe = manager.recipes[by_slot[(day, DINNER)]["recipe_id"]]
        assert (recipe_minutes(recipe) or 0) <= 30, recipe["name"]
    # Saturday: no cooking – the leftovers of Friday's dinner; Sunday stays free
    sat = by_slot[(saturday.isoformat(), DINNER)]
    assert sat["leftover_of"]["date"] == (MONDAY + timedelta(days=4)).isoformat()
    assert sat["title"].startswith("🍲 Reste von Freitag")
    assert (sunday.isoformat(), DINNER) not in by_slot
    # breakfast is planned every day
    assert all(
        ((MONDAY + timedelta(days=o)).isoformat(), "fruehstueck") in by_slot for o in range(7)
    )
    # 🔄 for one day still works (and keeps the time limit)
    result = manager.replan_meal(MONDAY, DINNER)
    assert result["entry"] is not None
    assert (recipe_minutes(manager.recipes[result["entry"]["recipe_id"]]) or 0) <= 30
    # the AI sees the limits per day and the profile
    candidates = rank_candidates(manager, MONDAY, 7, [DINNER])
    payload = ai_payload(manager, MONDAY, 7, [DINNER], candidates, None, None)
    assert payload["days"][0]["max_minutes"] == 30
    assert payload["days"][5].get("no_cooking") is True
    assert payload["profile"]["kochtage"] == ["Mo", "Di", "Mi", "Do", "Fr"]


async def test_time_limit_relaxes_with_a_reason(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    manager = await _profile(hass, setup_integration, weekday_time=15)
    quick = [
        r
        for r in manager.recipes.values()
        if manager._fits_meal(r, DINNER) and (recipe_minutes(r) or 0) <= 15
    ]
    # more suggestions than quick recipes: longer ones come too, with a reason
    found = manager.suggest(len(quick) + 3, meal=DINNER, around=MONDAY, rng=random.Random(1))
    slow = [r for r in found if (recipe_minutes(r) or 0) > 15]
    assert slow
    assert manager.time_reason(slow[0], MONDAY, DINNER).startswith("⏱️ ")
    assert manager.time_reason(slow[0], MONDAY, "fruehstueck") is None


async def test_flexitarian_meat_per_week(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    manager = await _profile(hass, setup_integration, diet="flexitarisch")
    planned = manager.auto_plan(MONDAY, 7, meals=[DINNER, "mittagessen"])
    assert len(planned) == 14
    meat = [e for e in planned if recipe_diet(manager.recipes[e["recipe_id"]]) == "fleisch"]
    assert len(meat) <= 2


async def test_liked_cuisine_is_suggested_more_often(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    def italian_share(manager: Any) -> int:
        count = 0
        for seed in range(40):
            for recipe in manager.suggest(3, meal=DINNER, around=MONDAY, rng=random.Random(seed)):
                count += "italienisch" in recipe_cuisines(recipe)
        return count

    manager = setup_integration.runtime_data
    before = italian_share(manager)
    bolognese = manager.get_recipe_by_name("Spaghetti Bolognese")
    ctx = manager._suggest_context(MONDAY)
    weight = manager._suggest_weight(bolognese, ctx)
    manager = await _profile(hass, setup_integration, liked_cuisines=["italienisch"])
    assert manager._suggest_weight(bolognese, manager._suggest_context(MONDAY)) > weight
    assert italian_share(manager) > before
    # the reason in the suggestion
    from custom_components.essensplaner.season import suggest_reasons

    assert "😋 Italienisch" in suggest_reasons(manager, bolognese, MONDAY)


async def test_occasions_only_diet_and_allergies_are_hard(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    manager = await _profile(hass, setup_integration, diet="vegetarisch", kitchen=["herd"])
    grill = manager.get_recipe_by_name("Halloumi-Gemüse-Spieße")  # vegetarian, needs a grill
    assert manager.is_excluded(grill)
    assert not manager.is_excluded(grill, devices=False)
    assert manager.is_excluded(manager.get_recipe_by_name("Bratwürste vom Grill"), devices=False)
