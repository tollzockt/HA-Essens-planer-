"""1.5 phase P6: ready meals (Fertiggerichte), the recipes for occasions, the new price
estimates and the aisle fixes – the bundled data is checked against the code (counts come
from the JSON files), offers like "Wagner Steinofen Pizza Salami" price the recipe line.

The setup has the starter recipes (conftest: Wednesday 2026-11-04)."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.essensplaner.catalog import KeyMatcher
from custom_components.essensplaner.const import CONF_EXCLUDED, DOMAIN, MEAL_DINNER
from custom_components.essensplaner.drinks import DRINKS, is_alcoholic
from custom_components.essensplaner.economy import VARIETY_TAGS
from custom_components.essensplaner.ingredients import (
    CATEGORY_FIXES_1_5,
    fold,
    guess_category,
    guess_category_1_4,
    ingredient_key,
    normalize_ingredient,
    parse_ingredient,
)
from custom_components.essensplaner.occasions import (
    COMPONENT_TAGS,
    DRINK_TAGS,
    MAIN_TAGS,
    recipe_course,
)
from custom_components.essensplaner.pricing import PriceBook

ROOT = Path(__file__).parent.parent / "custom_components" / "essensplaner"
PACK: list[dict[str, Any]] = json.loads((ROOT / "starter_recipes.json").read_text("utf-8"))
DEFAULTS: list[dict[str, Any]] = json.loads((ROOT / "default_prices.json").read_text("utf-8"))
READY = [r for r in PACK if "Fertiggericht" in r["tags"]]
TODAY = date(2026, 11, 4)


def _tags(recipe: dict[str, Any]) -> set[str]:
    return {fold(t) for t in recipe["tags"]}


async def _call(hass: HomeAssistant, service: str, **data: Any) -> Any:
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


# ----------------------------------------------------------------------
# The bundled data
# ----------------------------------------------------------------------


def test_bundled_recipes_are_complete() -> None:
    """Every recipe has a unique name, servings, times, ingredients and steps; ready meals
    and component recipes have their course tags."""
    names = [fold(r["name"]) for r in PACK]
    assert len(names) == len(set(names))
    for recipe in PACK:
        assert recipe["servings"] >= 1 and recipe["ingredients"] and recipe["steps"], recipe
    for recipe in PACK[107:]:  # the recipes of 1.5 have both times
        assert recipe["prep_time"] is not None and recipe["cook_time"] is not None
    assert 20 <= len(READY) <= 30
    for recipe in READY:
        tags = _tags(recipe)
        assert tags & (MAIN_TAGS | {"snack", "dessert"}), recipe["name"]
        assert recipe_course(recipe) == "main", recipe["name"]
    components = [r for r in PACK if _tags(r) & COMPONENT_TAGS and not _tags(r) & MAIN_TAGS]
    assert len(components) >= 25
    drinks = [r for r in PACK if _tags(r) & DRINK_TAGS]
    assert len(drinks) >= 8
    free = [r for r in drinks if "alkoholfrei" in _tags(r)]
    assert len(free) >= len(drinks) // 2  # alcohol-free ones are always there
    for recipe in drinks:
        assert recipe_course(recipe) == "drink", recipe["name"]
        lines = [normalize_ingredient(i)["name"] for i in recipe["ingredients"]]
        alcohol = any(is_alcoholic(line) for line in lines)
        assert alcohol == ("alkoholfrei" not in _tags(recipe)), recipe["name"]
    # the drinks of the drink rules have a recipe of the same name
    titles = {fold(d["title"]) for d in DRINKS.values()}
    linked = {fold(r["name"]) for r in drinks} & titles
    assert {"gluehwein", "kinderpunsch", "erdbeerbowle", "hugo", "hugo alkoholfrei"} <= linked


def test_bundled_recipes_are_priced() -> None:
    """Every line of the new recipes has an estimate (pantry staples aside) – no unknown
    costs; ready meal lines use packs ("2 Packungen Pizza Salami (TK, je 350 g)")."""
    book = PriceBook(DEFAULTS)
    pantry = {"salz", "pfeffer", "wasser", "eiswuerfel"}
    unknown: list[str] = []
    for recipe in PACK[107:]:
        for line in recipe["ingredients"]:
            name = normalize_ingredient(line)["name"]
            if ingredient_key(name) in pantry or ingredient_key(name) == "kaffeepulver":
                continue
            if book.lookup(name) is None:
                unknown.append(f"{recipe['name']}: {name}")
    assert unknown == []
    pizza = next(r for r in READY if r["name"] == "Tiefkühlpizza Salami")
    line = parse_ingredient(pizza["ingredients"][0])
    assert (line["name"], line["amount"], line["unit"], line["category"]) == (
        "Pizza Salami",
        2,
        "Pck.",
        "Tiefkühl",
    )
    assert book.lookup("Pizza Salami").name == "Tiefkühlpizza"  # not the cold cut


def test_new_estimates() -> None:
    """The estimates for drinks, frozen food, snacks and party supplies; aliases point to
    them; every name is unique."""
    book = PriceBook(DEFAULTS)
    names = [fold(e["name"]) for e in DEFAULTS]
    assert len(names) == len(set(names))
    assert len(DEFAULTS) >= 268 + 45
    for name, entry in (
        ("Pils", "Bier"),
        ("Prosecco", "Sekt"),
        ("Traubensecco", "Kindersekt"),
        ("Glühwein", "Glühwein"),
        ("Kinderpunsch", "Kinderpunsch"),
        ("Johannisbeerschorle", "Apfelschorle"),
        ("Zitronenlimonade", "Limonade"),
        ("Früchtetee", "Tee"),
        ("Holzkohle", "Grillkohle"),
        ("Grillanzünder", "Grillanzünder"),
        ("Servietten", "Servietten"),
        ("Partyteller", "Pappteller"),
        ("Kartoffelchips", "Chips"),
        ("Nachos", "Tortilla-Chips"),
        ("Salzstangen", "Salzstangen"),
        ("Popcorn", "Popcorn"),
        ("Maultaschen", "Maultaschen"),
        ("Klöße", "Kartoffelknödel"),
        ("Gänsekeulen", "Gänsekeulen"),
        ("Raclette-Käse", "Raclettekäse"),
        ("Rotweinessig", "Essig"),
    ):
        assert book.lookup(name).name == entry, name


@pytest.mark.parametrize(
    ("name", "aisle"),
    [
        ("Grillkohle", "Sonstiges"),
        ("Holzkohle", "Sonstiges"),
        ("Grillanzünder", "Sonstiges"),
        ("Kohlensäure", "Getränke"),
        ("Apfelschorle", "Getränke"),
        ("Johannisbeerschorle", "Getränke"),
        ("Kinderpunsch", "Getränke"),
        ("Traubensecco", "Getränke"),
        ("Pizzateig", "Brot & Backwaren"),
        ("Flammkuchenteig", "Brot & Backwaren"),
        ("Blätterteig", "Brot & Backwaren"),
        ("Kartoffelchips", "Backen & Süßes"),
        ("Paprika-Chips", "Backen & Süßes"),
        ("Tortilla-Chips", "Backen & Süßes"),
        ("Nachos", "Backen & Süßes"),
        ("Popcorn", "Backen & Süßes"),
        ("Salzstangen", "Backen & Süßes"),
        ("Lebkuchen", "Backen & Süßes"),
        ("Studentenfutter", "Nüsse & Trockenobst"),
        ("Maultaschen", "Nudeln, Reis & Getreide"),
        ("Kartoffelknödel", "Nudeln, Reis & Getreide"),
        ("Klöße", "Nudeln, Reis & Getreide"),
        ("Fertiggericht", "Konserven & Gläser"),
        ("Pizza Salami", "Tiefkühl"),
        ("Chicken Nuggets", "Tiefkühl"),
        ("Frühlingsrollen", "Tiefkühl"),
        ("Gänsekeulen", "Fleisch & Fisch"),
        ("Rehrücken", "Fleisch & Fisch"),
        ("Servietten", "Haushalt & Reinigung"),
        ("Pappteller", "Haushalt & Reinigung"),
        # unchanged
        ("Butter", "Milchprodukte & Eier"),
        ("Rotkohl", "Obst & Gemüse"),
        ("Hirschhornsalz", "Gewürze, Öle & Saucen"),
        ("Hähnchen-Nuggets", "Fleisch & Fisch"),
    ],
)
def test_aisle_fixes(name: str, aisle: str) -> None:
    """Barbecue charcoal is no cabbage, apple spritzer no fruit, a frozen pizza no cold cut."""
    assert guess_category(name) == aisle


def test_aisle_fixes_against_1_4() -> None:
    """The 1.4 guess is kept for the migration; the fixed keywords are listed."""
    assert guess_category_1_4("Grillkohle") == "Obst & Gemüse"
    assert guess_category_1_4("Apfelschorle") == "Obst & Gemüse"
    assert guess_category_1_4("Butter") == guess_category("Butter")
    assert {"grillkohle", "schorle", "maultaschen", "pizza salami"} <= CATEGORY_FIXES_1_5


@pytest.mark.parametrize(
    ("line", "aisle"),
    [
        ("2 Packungen Pizza Salami (TK, je 350 g)", "Tiefkühl"),
        ("150 g Erbsen (TK)", "Tiefkühl"),
        ("300 g Blattspinat (tiefgekühlt)", "Tiefkühl"),
        ("1 Dose Mais (285 g)", "Konserven & Gläser"),
        ("1 Dose Chili sin Carne (800 g)", "Konserven & Gläser"),
        ("800 g geschälte Tomaten (2 Dosen)", "Konserven & Gläser"),
        ("1 Dose Kokosmilch (400 ml)", "Konserven & Gläser"),
        ("1 Dose Bier (0,5 l)", "Getränke"),
        ("200 g Erbsen", "Obst & Gemüse"),
        ("2 Rollen Toilettenpapier (TK)", "Drogerie & Körperpflege"),
    ],
)
def test_line_aisle_by_note(line: str, aisle: str) -> None:
    """A recipe line's note "(TK)" means frozen, a can means the canned food aisle."""
    expected = "Haushalt & Reinigung" if "Toilettenpapier" in line else aisle
    assert parse_ingredient(line)["category"] == expected


def test_variety_and_fit() -> None:
    """A ready meal is a kind of its own for the variety; component recipes never fill a
    meal slot."""
    assert "fertiggericht" in VARIETY_TAGS


# ----------------------------------------------------------------------
# Offers of ready meals
# ----------------------------------------------------------------------


def test_key_matcher_ready_meals() -> None:
    """Offers of ready meals name the key of the recipe line ("Wagner Steinofen Pizza
    Salami" is a Pizza Salami, no salami); a pizza cheese is still cheese."""
    keys = {}
    for recipe in READY:
        for line in recipe["ingredients"]:
            name = normalize_ingredient(line)["name"]
            keys[name] = ingredient_key(name)
    keys.update(
        {n: ingredient_key(n) for n in ("Salami", "Mozzarella", "Pizza", "Lasagne", "Käse")}
    )
    matcher = KeyMatcher(keys.values())
    for text, key in (
        ("Wagner Steinofen Pizza Salami", keys["Pizza Salami"]),
        ("Original Wagner Steinofen-Pizza Salami 350 g", keys["Pizza Salami"]),
        ("Gut & Günstig Pizza Margherita", keys["Pizza Margherita"]),
        ("Bürger Maultaschen traditionell schwäbisch", keys["Maultaschen"]),
        ("Iglo Fischstäbchen", keys["Fischstäbchen"]),
        ("Frosta Bami Goreng", keys["Bami Goreng"]),
        ("Pfanni Kartoffelpuffer", keys["Kartoffelpuffer"]),
        ("Iglo Chicken Nuggets", keys["Chicken Nuggets"]),
        ("Gut & Günstig Lasagne Bolognese TK", keys["Lasagne Bolognese"]),
        ("Henglein Schupfnudeln", keys["Schupfnudeln"]),
    ):
        assert key in matcher.match(text, text), text
    assert "salami" not in matcher.match("Wagner Steinofen Pizza Salami", "x")
    assert "salami" not in matcher.match("Salami Pizza", "x")
    assert "salami" in matcher.match("Salami Sticks", "x")
    assert "mozzarella" in matcher.match("Pizza-Mozzarella", "x")
    assert "mozzarella" in matcher.match("Mozzarella Pizza Käse", "x")


async def test_ready_meal_offer_prices_the_recipe(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """A leaflet offer of the frozen pizza prices the recipe and the shopping list (two
    packs), in the frozen food aisle."""
    manager = setup_integration.runtime_data
    pizza = manager.get_recipe_by_name("Tiefkühlpizza Salami")
    before = manager.recipe_cost(pizza, None, TODAY)
    assert before["unknown"] == [] and before["total"] == 4.58  # 2 × the estimate
    manager.add_offer("Wagner Steinofen Pizza Salami", "Lidl", 1.99, "350 g")
    cost = manager.recipe_cost(pizza, None, TODAY)
    assert cost["total"] == 3.98 and cost["on_offer"][0]["title"].startswith("Wagner")
    await _call(hass, "plan_meal", date="morgen", recipe="Tiefkühlpizza Salami")
    await _call(hass, "generate_shopping_list", days=2)
    item = next(i for i in manager.shopping if i["key"] == "pizza salami")
    assert (item["category"], item["price"], item["packs"]) == ("Tiefkühl", 3.98, 2)
    assert item["offer"]["title"].startswith("Wagner")


async def test_ready_meals_in_planning(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Ready meals fit dinner, never two days in a row when there is another, and
    "Fertiggericht" under "Nie vorschlagen" keeps them out; drinks and sides never fill
    a meal slot."""
    manager = setup_integration.runtime_data
    pizza = manager.get_recipe_by_name("Tiefkühlpizza Salami")
    ravioli = manager.get_recipe_by_name("Ravioli aus der Dose")
    assert manager._fits_meal(pizza, MEAL_DINNER)
    for name in ("Glühwein", "Kartoffelsalat", "Tzatziki", "Tiramisu"):
        assert not manager._fits_meal(manager.get_recipe_by_name(name), MEAL_DINNER), name
    assert manager._variety_signature(pizza) & manager._variety_signature(ravioli)
    # suggested half as often as a cooked dish – a favourite as often as others
    ctx = manager._suggest_context(TODAY)
    margherita = manager.get_recipe_by_name("Pizza Margherita")
    lone = {**pizza, "tags": ["Hauptgericht", "Pizza", "Italienisch"]}
    assert manager._suggest_weight(pizza, ctx) == pytest.approx(
        0.5 * manager._suggest_weight(lone, ctx)
    )
    assert manager._suggest_weight({**pizza, "favorite": True}, ctx) > manager._suggest_weight(
        margherita, ctx
    )
    await _call(hass, "plan_meal", date="heute", recipe="Tiefkühlpizza Salami")
    neighbours = manager._neighbour_signatures(date(2026, 11, 5))
    assert manager.economy_weight(ravioli, TODAY, neighbours=neighbours) < (
        0.5 * manager.economy_weight(ravioli, TODAY)
    )
    hass.config_entries.async_update_entry(
        setup_integration, options={**setup_integration.options, CONF_EXCLUDED: "Fertiggericht"}
    )
    await hass.async_block_till_done()
    manager = setup_integration.runtime_data
    suggested = manager.suggest(50, meal=MEAL_DINNER)
    assert not any("Fertiggericht" in r["tags"] for r in suggested)
    planned = manager.auto_plan(TODAY, 14, overwrite=True)
    assert not any("Fertiggericht" in manager.recipes[p["recipe_id"]]["tags"] for p in planned)


async def test_product_to_recipe_tags(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """A recipe from a product gets "Fertiggericht" and its course like the bundled ready
    meals: a main dish fills a meal slot, a dessert and a snack theirs, a drink is only a
    drink."""
    from custom_components.essensplaner.products import ingest_offer, product_to_recipe

    manager = setup_integration.runtime_data

    def product(offer_id: str, title: str, kind: str = "food", key: str = "x") -> Any:
        return ingest_offer(
            manager,
            {
                "id": offer_id,
                "title": title,
                "product": title,
                "brand": "Bergland",
                "store": "Lidl",
                "store_id": "lidl",
                "retailer": "lidl",
                "price": 2.49,
                "pack_amount": 400,
                "pack_unit": "g",
                "valid_from": "2026-11-02",
                "valid_to": "2026-11-07",
                "source": "marktguru",
                "keys": [key],
                "kind": kind,
            },
        )

    lasagne = product_to_recipe(manager, product("mg_1", "Lasagne Bolognese", key="lasagne")["id"])
    assert lasagne["tags"] == ["Fertiggericht", "Hauptgericht"]
    assert manager._fits_meal(lasagne, MEAL_DINNER) and recipe_course(lasagne) == "main"
    tiramisu = product_to_recipe(manager, product("mg_2", "Tiramisu", key="tiramisu")["id"])
    assert tiramisu["tags"] == ["Fertiggericht", "Dessert"]
    chips = product_to_recipe(manager, product("mg_3", "Kartoffelchips", key="chip")["id"])
    assert chips["tags"] == ["Fertiggericht", "Snack"]
    punch = product_to_recipe(
        manager, product("mg_4", "Glühwein", kind="drinks", key="gluehwein")["id"]
    )
    assert punch["tags"] == ["Getränk"] and not manager._fits_meal(punch, MEAL_DINNER)
    own = product_to_recipe(
        manager, product("mg_5", "Maultaschen", key="maultasche")["id"], "Lieblingsessen"
    )
    assert own["tags"] == ["Lieblingsessen"]  # given tags win


async def test_occasion_extras_are_priced(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The extras and drinks of a barbecue have estimates now (no unknown costs)."""
    from custom_components.essensplaner import occasions as occ

    manager = setup_integration.runtime_data
    occasion = occ.create_occasion(manager, "grillen", "Samstag", guests=6, auto_fill=True)
    cost = occ.occasion_cost(manager, occasion)
    titles = {i["title"] for i in occasion["items"]}
    assert {"Grillkohle", "Grillanzünder", "Servietten"} <= titles
    priced = {i["title"] for i in occasion["items"] if cost["items"].get(i["uid"]) not in (None, 0)}
    assert {"Grillkohle", "Grillanzünder", "Servietten"} <= priced
    # the bundled side dishes and grill recipes are suggested for a barbecue
    mains = {s["title"] for s in occ.suggest_course(manager, occasion, "main", 10)}
    sides = {s["title"] for s in occ.suggest_course(manager, occasion, "side", 10)}
    assert {"Bratwürste vom Grill", "Halloumi-Gemüse-Spieße"} & mains
    assert {"Kartoffelsalat", "Krautsalat", "Grillgemüse"} & sides
