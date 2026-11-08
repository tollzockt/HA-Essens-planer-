"""1.5 phase P5: occasions ("Anlässe") – templates, courses, suggestions, costs, budget, the
shopping list, the calendar, sensors, services, websockets, the AI menu and the intents.

The collection holds made-up test recipes only (no starter recipes); the AI is faked."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import intent
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.essensplaner import occasions as occ
from custom_components.essensplaner.const import (
    CONF_AI_ENTITY,
    CONF_BUDGET,
    CONF_DEFAULT_MEAL,
    CONF_DEFAULT_SERVINGS,
    CONF_DRINKS_ALCOHOL,
    CONF_ENABLED_MEALS,
    CONF_IMPORT_STARTER,
    CONF_OCCASIONS_IN_BUDGET,
    CONF_PANTRY,
    CONF_REGISTER_INTENTS,
    CONF_SHOW_PANEL,
    DOMAIN,
)
from custom_components.essensplaner.dates import advent_start, easter, parse_date

TODAY = date(2026, 11, 4)  # Wednesday (conftest freezes the clock)
SATURDAY = "2026-11-07"
CALENDAR = "calendar.essensplaner_meal_plan"
TASK = "ai_task.koch"

RECIPES: list[dict[str, Any]] = [
    {
        "name": "Bratwurst vom Grill",
        "tags": ["Hauptgericht", "Grillen", "Schwein"],
        "servings": 4,
        "ingredients": ["8 Bratwürste", "1 EL Senf"],
    },
    {
        "name": "Rindersteak vom Grill",
        "tags": ["Hauptgericht", "Grillen", "Rind"],
        "servings": 2,
        "ingredients": ["400 g Rindersteak", "1 EL Öl"],
    },
    {
        "name": "Lasagne",
        "tags": ["Hauptgericht", "Pasta", "Italienisch"],
        "servings": 4,
        "ingredients": ["500 g Hackfleisch", "400 g gehackte Tomaten", "250 g Lasagneplatten"],
    },
    {
        "name": "Pizza Margherita",
        "tags": ["Hauptgericht", "Party", "Italienisch"],
        "servings": 2,
        "ingredients": ["1 Pizzateig", "200 g passierte Tomaten", "125 g Mozzarella"],
    },
    {
        "name": "Kartoffelsalat",
        "tags": ["Beilage", "Salat"],
        "servings": 4,
        "ingredients": ["1 kg Kartoffeln", "1 Zwiebel", "4 Gewürzgurken"],
    },
    {
        "name": "Tzatziki",
        "tags": ["Beilage", "Dip", "Grillen"],
        "servings": 4,
        "ingredients": ["500 g Joghurt", "1 Gurke"],
    },
    {
        "name": "Tiramisu",
        "tags": ["Dessert"],
        "servings": 6,
        "ingredients": ["500 g Mascarpone", "200 g Löffelbiskuits"],
    },
    {
        "name": "Nachos mit Käsedip",
        "tags": ["Snack", "Party", "Fingerfood"],
        "servings": 4,
        "ingredients": ["200 g Tortilla-Chips", "150 g Cheddar"],
    },
    {
        "name": "Erdbeerbowle",
        "tags": ["Getränk", "Bowle"],
        "servings": 8,
        "ingredients": ["500 g Erdbeeren", "1,5 l Weißwein", "0,75 l Sekt"],
    },
    {
        "name": "Kinderpunsch",
        "tags": ["Getränk", "Punsch", "Kinder"],
        "servings": 6,
        "ingredients": ["1 l Früchtetee", "0,5 l Apfelsaft"],
    },
]


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """No starter recipes: only the test recipes."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Essensplaner",
        data={CONF_IMPORT_STARTER: False},
        options={
            CONF_DEFAULT_SERVINGS: 2,
            CONF_DEFAULT_MEAL: "abendessen",
            CONF_ENABLED_MEALS: ["fruehstueck", "mittagessen", "abendessen"],
            CONF_PANTRY: "Salz, Pfeffer, Wasser, Öl",
            CONF_REGISTER_INTENTS: True,
            CONF_SHOW_PANEL: True,
        },
    )


@pytest.fixture
async def manager(hass: HomeAssistant, setup_integration: MockConfigEntry) -> Any:
    """The manager with the test recipes."""
    manager = setup_integration.runtime_data
    for recipe in RECIPES:
        manager.add_recipe(recipe)
    return manager


def _recipe(manager: Any, name: str) -> dict[str, Any]:
    return manager.get_recipe_by_name(name)


async def _call(hass: HomeAssistant, service: str, **data: Any) -> Any:
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


async def _ws(hass: HomeAssistant, hass_ws_client, command: str, **data: Any) -> dict[str, Any]:
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/{command}", **data})
    return await client.receive_json()


async def _speech(hass: HomeAssistant, intent_type: str, **slots: Any) -> str:
    response = await intent.async_handle(
        hass,
        "test",
        intent_type,
        {key: {"value": value} for key, value in slots.items()},
        language="de",
    )
    return response.speech["plain"]["speech"]


async def _use(hass: HomeAssistant, entry: MockConfigEntry, **options: Any) -> Any:
    """Set options (reloads the entry) and return the new manager."""
    hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
    await hass.async_block_till_done()
    return entry.runtime_data


def _titles(occasion: dict[str, Any], course: str) -> list[str]:
    return [i["title"] for i in occasion["items"] if i["course"] == course]


# ----------------------------------------------------------------------
# Dates, templates and courses
# ----------------------------------------------------------------------


def test_holidays_in_dates() -> None:
    """Holidays are dates (the next one); Easter and Advent are computed."""
    assert easter(2026) == date(2026, 4, 5)
    assert easter(2027) == date(2027, 3, 28)
    assert advent_start(2026) == date(2026, 11, 29)
    assert advent_start(2025) == date(2025, 11, 30)
    assert parse_date("Heiligabend", TODAY) == (date(2026, 12, 24), None)
    assert parse_date("an Weihnachten", TODAY) == (date(2026, 12, 25), None)
    assert parse_date("2. Weihnachtstag", TODAY) == (date(2026, 12, 26), None)
    assert parse_date("Silvester", TODAY) == (date(2026, 12, 31), None)
    assert parse_date("Neujahr", TODAY) == (date(2027, 1, 1), None)
    # Easter 2026 is over: the next one
    assert parse_date("Ostern", TODAY) == (date(2027, 3, 28), None)
    assert parse_date("Ostermontag abend", TODAY) == (date(2027, 3, 29), "abendessen")
    # weekdays still work
    assert parse_date("am Samstag", TODAY) == (date(2026, 11, 7), None)


def test_templates_and_course_words() -> None:
    """Template and course words; every template has its texts and valid extras."""
    assert occ.resolve_template("Grillabend") == "grillen"
    assert occ.resolve_template("grillen") == "grillen"
    assert occ.resolve_template("Weihnachtsessen bei Oma") == "weihnachten"
    assert occ.resolve_template("Omas Geburtstag") == "geburtstag"
    assert occ.resolve_template("Kindergeburtstag") == "geburtstag"
    assert occ.resolve_template("Raclette-Abend") == "raclette"
    assert occ.resolve_template("Spieleabend") is None
    assert occ.resolve_course("Nachtisch") == "dessert"
    assert occ.resolve_course("Getränke") == "drink"
    assert occ.resolve_course("Zubehör") == "extra"
    assert occ.resolve_course("Suppe") is None
    for key, info in occ.TEMPLATES.items():
        assert info["title"] and info["emoji"] and info["to"], key
        assert set(info["courses"]) <= set(occ.DISH_COURSES), key
        for rule in info["extras"]:
            assert rule[3] >= 1 and (len(rule) < 5 or rule[4] in occ.COURSES), (key, rule)
    assert [t["id"] for t in occ.templates_view()] == list(occ.TEMPLATES)
    assert [c["id"] for c in occ.courses_view()] == list(occ.COURSES)


def test_recipe_courses() -> None:
    """Courses from tags, then from the name; a drink is only a drink."""

    def courses(name: str, tags: list[str]) -> tuple[set[str], str]:
        recipe = {"name": name, "tags": tags}
        return occ.recipe_courses(recipe), occ.recipe_course(recipe)

    assert courses("Erdbeerbowle", ["Getränk"]) == ({"drink"}, "drink")
    assert courses("Glühwein", []) == ({"drink"}, "drink")
    assert courses("Kartoffelsalat", ["Beilage", "Salat"]) == ({"side", "starter"}, "side")
    assert courses("Tiramisu", ["Dessert"]) == ({"dessert"}, "dessert")
    assert courses("Kürbissuppe", ["Hauptgericht", "Suppe"]) == ({"main", "starter"}, "main")
    assert courses("Griechischer Salat", ["Hauptgericht", "Salat"])[1] == "main"
    assert "side" in courses("Griechischer Salat", ["Hauptgericht", "Salat"])[0]
    assert courses("Waffeln", ["Snack", "süß"]) == ({"snack"}, "snack")
    assert courses("Apfelkuchen", ["Kuchen", "Snack"])[1] == "dessert"
    assert courses("Rotkohl", []) == ({"side"}, "side")
    assert courses("Mousse au Chocolat", []) == ({"dessert"}, "dessert")
    assert courses("Overnight Oats", ["Frühstück"]) == ({"main"}, "main")
    # a dish named after a drink is still a dish
    assert courses("Rotweinkuchen", ["Backen"])[1] == "dessert"
    assert occ.guess_course("Apfelschorle") == "drink"
    assert occ.guess_course("Grillkohle") == "extra"
    assert occ.guess_course("Servietten") == "extra"
    assert occ.guess_course("Kartoffelsalat") == "side"
    assert occ.guess_course("Popcorn") == "snack"
    assert occ.guess_course("Gänsebraten") == "main"


async def test_components_never_fill_meal_slots(hass: HomeAssistant, manager: Any) -> None:
    """Drinks, sides, dips and starters stay out of the week plan (suggestions and the auto
    plan); 1.5.1: a dip is a component even when tagged "Snack" (never a meal of its own)."""
    manager.add_recipe(
        {"name": "Guacamole", "tags": ["Dip", "Snack"], "ingredients": ["2 Avocados"]}
    )
    for _ in range(5):
        for meal in ("abendessen", "mittagessen", None):
            names = {r["name"] for r in manager.suggest(20, meal=meal)}
            assert not names & {"Erdbeerbowle", "Kinderpunsch", "Kartoffelsalat", "Tzatziki"}
            assert "Guacamole" not in names
    assert "Guacamole" not in {r["name"] for r in manager.suggest(20, meal="snack")}
    assert manager.get_recipe_by_name("Guacamole")["kind"] == "component"
    planned = manager.auto_plan(TODAY, 7, overwrite=True)
    titles = {p["title"] for p in planned}
    assert titles and not titles & {"Erdbeerbowle", "Kinderpunsch", "Kartoffelsalat", "Tzatziki"}


async def test_suggest_weight_shared(hass: HomeAssistant, manager: Any) -> None:
    """suggest() and the occasions share _suggest_weight(): favourites weigh more, a recipe
    planned nearby much less."""
    lasagne = _recipe(manager, "Lasagne")
    pizza = _recipe(manager, "Pizza Margherita")
    ctx = manager._suggest_context(TODAY, budget=False, variety=False)
    base = manager._suggest_weight(lasagne, ctx)
    manager.update_recipe(lasagne["id"], {"favorite": True})
    assert manager._suggest_weight(manager.recipes[lasagne["id"]], ctx) > base
    manager.plan_meal(TODAY + timedelta(days=1), "abendessen", pizza)
    ctx = manager._suggest_context(TODAY, budget=False, variety=False)
    assert pizza["id"] in ctx["recent"]
    assert manager._suggest_weight(pizza, ctx) < base


# ----------------------------------------------------------------------
# Create, change, delete
# ----------------------------------------------------------------------


async def test_create_with_auto_fill(hass: HomeAssistant, manager: Any) -> None:
    """A barbecue for 6 adults and 2 children: grill dishes, sides, dessert, drinks (beer
    and at least two without alcohol, one for children) and extras for 8 persons."""
    occasion = occ.create_occasion(
        manager, "Grillabend", SATURDAY, guests=6, children=2, auto_fill=True
    )
    assert occasion["template"] == "grillen" and occasion["title"] == "Grillabend"
    assert occasion["time"] == "18:00" and occasion["duration_h"] == 4.0
    assert len(occasion["id"]) == 8 and "_" not in occasion["id"]
    assert set(_titles(occasion, "main")) == {"Bratwurst vom Grill", "Rindersteak vom Grill"}
    assert set(_titles(occasion, "side")) == {"Kartoffelsalat", "Tzatziki", "Grillsoße"}
    assert _titles(occasion, "dessert") == ["Tiramisu"]
    drinks = [i for i in occasion["items"] if i["course"] == "drink"]
    assert any(d["alcohol"] and d["title"] == "Bier" for d in drinks)
    assert sum(1 for d in drinks if not d["alcohol"]) >= 2
    assert all(d.get("auto") == "drink" and d.get("quantity") for d in drinks)
    extras = {i["title"]: i for i in occasion["items"] if i.get("auto") == "extra"}
    assert extras["Grillkohle"]["quantity"] == 5.0 and extras["Grillkohle"]["unit"] == "kg"
    assert extras["Grillkohle"]["course"] == "extra"
    assert extras["Grillsoße"]["course"] == "side"
    assert extras["Servietten"]["quantity"] == 1
    assert occ.servings_of(occasion) == 7 and occ.persons_of(occasion) == 8
    assert manager.occasions[occasion["id"]] is occasion
    # a film night: pizza (party), nachos as snack, popcorn and chips as snacks
    film = occ.create_occasion(manager, "filmabend", "Freitag", guests=4, auto_fill=True)
    assert _titles(film, "main") == ["Pizza Margherita"]
    assert "Nachos mit Käsedip" in _titles(film, "snack")
    assert {"Popcorn", "Chips"} <= set(_titles(film, "snack"))
    popcorn = next(i for i in film["items"] if i["title"] == "Popcorn")
    assert popcorn["quantity"] == 200 and popcorn["unit"] == "g"
    assert {"Cola", "Bier"} & set(_titles(film, "drink"))


async def test_update_rescales_automatic_items(hass: HomeAssistant, manager: Any) -> None:
    """More guests: automatic extras and drinks follow; what the user changed stays."""
    occasion = occ.create_occasion(manager, "grillen", SATURDAY, guests=6, auto_fill=True)
    beer = next(i for i in occasion["items"] if i["title"] == "Bier")
    before = beer["quantity"]
    items = [dict(i) for i in occasion["items"]]
    napkins = next(i for i in items if i["title"] == "Servietten")
    napkins["quantity"] = 3  # the user wants more
    occ.update_occasion(manager, occasion["id"], {"items": items})
    occ.update_occasion(manager, occasion["id"], {"guests": 12})
    by_title = {i["title"]: i for i in occasion["items"]}
    assert by_title["Grillkohle"]["quantity"] == 5.0  # 12 persons: 2 × 2,5 kg
    assert by_title["Bier"]["quantity"] > before
    assert by_title["Servietten"]["quantity"] == 3 and "auto" not in by_title["Servietten"]
    occ.update_occasion(
        manager,
        occasion["id"],
        {
            "time": "19:30",
            "title": "Grillen bei uns",
            "notes": "Nachbarn fragen",
            "date": "2026-11-08",
        },
    )
    assert occasion["time"] == "19:30" and occasion["title"] == "Grillen bei uns"
    assert occasion["date"] == "2026-11-08" and occasion["notes"] == "Nachbarn fragen"
    occ.update_occasion(manager, occasion["id"], {"time": ""})
    assert occasion["time"] is None  # all day
    for data, key in (
        ({"time": "25 Uhr"}, "invalid_time"),
        ({"template": "Spieleabend"}, "invalid_template"),
        ({"title": " "}, "name_required"),
        ({"add_items": [{"title": "Salz", "course": "Suppe"}]}, "invalid_course"),
        ({"add_items": [{"recipe_id": "nope"}]}, "recipe_not_found"),
        ({"date": "irgendwann"}, "invalid_date"),
    ):
        with pytest.raises(ServiceValidationError) as err:
            occ.update_occasion(manager, occasion["id"], data)
        assert err.value.translation_key == key, data
    with pytest.raises(ServiceValidationError) as err:
        occ.update_occasion(manager, "nope", {})
    assert err.value.translation_key == "occasion_not_found"


async def test_items_find_and_remove(hass: HomeAssistant, manager: Any) -> None:
    """A said dish is a recipe of that name, else free text with a guessed course; items
    are removed by uid or name; occasions are found by title, template and date."""
    family = occ.create_occasion(manager, "familienessen", "Sonntag", title="Omas Geburtstag")
    assert family["template"] == "familienessen" and family["title"] == "Omas Geburtstag"
    party = occ.create_occasion(manager, "Omas Geburtstag", SATURDAY)
    assert party["template"] == "geburtstag" and party["title"] == "Omas Geburtstag"
    item = occ.add_item(manager, family["id"], "Kartoffelsalat")
    assert item["recipe_id"] == _recipe(manager, "Kartoffelsalat")["id"]
    assert item["course"] == "side"
    item = occ.add_item(manager, family["id"], "Apfelschorle")
    assert item["course"] == "drink" and item["alcohol"] is False
    item = occ.add_item(manager, family["id"], {"title": "Rotwein", "quantity": 2, "unit": "Liter"})
    assert item["course"] == "drink" and item["alcohol"] is True and item["unit"] == "l"
    item = occ.add_item(manager, family["id"], "Gänsebraten")
    assert item["course"] == "main" and "recipe_id" not in item
    removed = occ.remove_item(manager, family["id"], "gänsebraten")
    assert removed["title"] == "Gänsebraten"
    with pytest.raises(ServiceValidationError) as err:
        occ.remove_item(manager, family["id"], "Tiramisu")
    assert err.value.translation_key == "occasion_item_not_found"
    assert occ.resolve_occasion(manager, "Omas Geburtstag")["id"] == party["id"]  # next first
    assert occ.resolve_occasion(manager, "Familienessen")["id"] == family["id"]
    assert occ.resolve_occasion(manager, None, date(2026, 11, 7))["id"] == party["id"]
    assert occ.resolve_occasion(manager, family["id"]) is family
    with pytest.raises(ServiceValidationError):
        occ.resolve_occasion(manager, "Grillabend")
    occ.delete_occasion(manager, party["id"])
    assert party["id"] not in manager.occasions


async def test_storage_and_prune(
    hass: HomeAssistant, manager: Any, setup_integration: MockConfigEntry
) -> None:
    """Occasions are saved with the main data and come back after a reload; a year after
    their date they are gone."""
    occasion = occ.create_occasion(manager, "brunch", "Sonntag", guests=5, auto_fill=True)
    old = occ.create_occasion(manager, "party", "2026-11-01")
    old["date"] = "2025-10-01"  # more than a year ago
    await manager.async_save_now()
    await hass.config_entries.async_reload(setup_integration.entry_id)
    await hass.async_block_till_done()
    reloaded = setup_integration.runtime_data
    assert reloaded is not manager
    assert list(reloaded.occasions) == [occasion["id"]]
    assert reloaded.occasions[occasion["id"]]["items"] == occasion["items"]


# ----------------------------------------------------------------------
# Suggestions and AI
# ----------------------------------------------------------------------


async def test_suggest_course(hass: HomeAssistant, manager: Any) -> None:
    """Course suggestions: course tags, template preferences, not twice, reasons, cost."""
    occasion = occ.create_occasion(manager, "grillen", SATURDAY, guests=4)
    mains = occ.suggest_course(manager, occasion, "main", 5)
    assert [s["title"] for s in mains[:2]] == sorted(
        ["Bratwurst vom Grill", "Rindersteak vom Grill"],
        key=lambda t: -next(s["score"] for s in mains if s["title"] == t),
    )
    assert {s["title"] for s in mains[:2]} == {"Bratwurst vom Grill", "Rindersteak vom Grill"}
    assert "🔥 passt zu Grillabend" in mains[0]["reasons"]
    assert mains[0]["servings"] == 4 and mains[0]["cost"] >= 0
    assert all(s["course"] == "main" for s in mains)
    names = {s["title"] for s in mains}
    assert not names & {"Kartoffelsalat", "Erdbeerbowle", "Tiramisu"}
    sides = occ.suggest_course(manager, occasion, "side")
    assert sides[0]["title"] == "Tzatziki"  # a grill dip first
    occ.add_item(manager, occasion["id"], "Tzatziki")
    assert "Tzatziki" not in {s["title"] for s in occ.suggest_course(manager, occasion, "side")}
    assert occ.suggest_course(manager, occasion, "drink") == []
    menu = occ.suggest_menu(manager, occasion)
    assert list(menu) == ["main", "side", "dessert", "drink", "extra"]
    assert {e["title"] for e in menu["extra"]} >= {"Grillkohle", "Servietten"}
    assert "Tzatziki" not in {s["title"] for s in menu["side"]}


async def test_suggest_menu_service_apply(hass: HomeAssistant, manager: Any) -> None:
    """suggest_occasion_menu: rule suggestions; apply fills the missing courses, drinks and
    extras; one course on its own."""
    await _call(hass, "save_occasion", template="weihnachten", date="Heiligabend", guests=4)
    result = await _call(hass, "suggest_occasion_menu", occasion="Weihnachtsessen")
    assert result["ai"] is None and result["applied"] == []
    assert set(result["suggestions"]) == {"starter", "main", "side", "dessert", "drink", "extra"}
    result = await _call(hass, "suggest_occasion_menu", occasion="Weihnachtsessen", apply=True)
    occasion = result["occasion"]
    assert occasion["date"] == "2026-12-24" and occasion["label"] == "🎄 Weihnachtsessen"
    items = {i["uid"]: i for i in occasion["items"]}
    courses = {c["id"]: [items[uid] for uid in c["uids"]] for c in occasion["courses"]}
    assert courses["main"] and courses["dessert"][0]["title"] == "Tiramisu"
    assert courses["drink"] and courses["extra"]
    assert all(i["cost"] is None or i["cost"] >= 0 for i in occasion["items"])
    assert "items" not in occasion["cost"] and occasion["cost"]["total"] > 0
    # drinks for the dishes put in first: sparkling wine to toast, ≥ 2 alcohol-free
    drinks = courses["drink"]
    assert "Sekt" in [i["title"] for i in drinks]
    assert sum(1 for i in drinks if not i["alcohol"]) >= 2
    result = await _call(
        hass, "suggest_occasion_menu", occasion="Weihnachtsessen", course="main", apply=True
    )
    assert len(result["applied"]) == 1
    mains = [i for i in result["occasion"]["items"] if i["course"] == "main"]
    assert len(mains) == 2


def _fake_task(hass: HomeAssistant, answer: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def handler(call: ServiceCall) -> Any:
        calls.append(dict(call.data))
        if isinstance(answer, BaseException):
            raise answer
        return answer

    hass.services.async_register(
        "ai_task", "generate_data", handler, supports_response=SupportsResponse.ONLY
    )
    hass.states.async_set(TASK, "unknown", {"friendly_name": "Koch-KI"})
    return calls


async def test_ai_menu_checked(
    hass: HomeAssistant, manager: Any, setup_integration: MockConfigEntry
) -> None:
    """The AI menu is checked: known recipe ids, names matched to recipes, unknown dishes as
    free items (🤖), no alcohol when switched off, only the asked courses; the payload has
    no title, notes or places. A failing AI keeps the rule suggestions."""
    manager = await _use(
        hass, setup_integration, **{CONF_AI_ENTITY: TASK, CONF_DRINKS_ALCOHOL: False}
    )
    lasagne = _recipe(manager, "Lasagne")
    answer = {
        "data": {
            "menu": [
                {"gang": "main", "rezept_id": lasagne["id"], "grund": "Klassiker"},
                {"gang": "Dessert", "titel": "Tiramisu"},
                {"gang": "side", "titel": "Rosmarinkartoffeln", "grund": "passt"},
                {"gang": "drink", "titel": "Rotwein"},
                {"gang": "drink", "titel": "Holunderschorle"},
                {"gang": "suppe", "titel": "Kürbissuppe"},
                {"gang": "main", "rezept_id": "erfunden", "titel": "Lasagne"},
            ]
        }
    }
    calls = _fake_task(hass, answer)
    occasion = occ.create_occasion(
        manager, "familienessen", "Sonntag", title="Opa Willis 80.", notes="Lindenweg 1"
    )
    result = await occ.async_suggest_menu(hass, manager, occasion, ai=True)
    assert result["ai"] == {"ok": True}
    menu = result["suggestions"]
    assert menu["main"][0]["recipe_id"] == lasagne["id"] and menu["main"][0]["ai"]
    assert [s["title"] for s in menu["main"]].count("Lasagne") == 1
    assert menu["dessert"][0]["title"] == "Tiramisu" and menu["dessert"][0]["recipe_id"]
    assert menu["side"][0] == {
        "recipe_id": None,
        "title": "Rosmarinkartoffeln",
        "course": "side",
        "reasons": ["🤖 passt"],
        "ai": True,
    }
    drinks = [s["title"] for s in menu["drink"]]
    assert "Holunderschorle" in drinks and "Rotwein" not in drinks
    assert all(not s.get("alcohol") for s in menu["drink"])
    prompt = calls[0]["instructions"]
    assert "Opa Willis" not in prompt and "Lindenweg" not in prompt
    assert "Familienessen" in prompt and "Benutze keine Werkzeuge" in prompt
    applied = await occ.async_suggest_menu(hass, manager, occasion, ai=True, apply=True)
    assert "Rosmarinkartoffeln" in applied["applied"]
    added = next(i for i in occasion["items"] if i["title"] == "Rosmarinkartoffeln")
    assert added["ai"] is True and added["course"] == "side"
    # the AI fails: rule suggestions with the error
    _fake_task(hass, HomeAssistantError("kaputt"))
    other = occ.create_occasion(manager, "party", SATURDAY)
    result = await occ.async_suggest_menu(hass, manager, other, ai=True)
    assert result["ai"]["ok"] is False and result["ai"]["code"] == "ai_failed"
    assert result["suggestions"]["main"]


# ----------------------------------------------------------------------
# Costs, budget, shopping list
# ----------------------------------------------------------------------


async def test_costs_and_budget(
    hass: HomeAssistant, manager: Any, setup_integration: MockConfigEntry
) -> None:
    """Occasions are part of the day's and week's costs and of the budget – unless
    switched off."""
    manager = await _use(hass, setup_integration, **{CONF_BUDGET: 50})
    occasion = occ.create_occasion(manager, "grillen", SATURDAY, guests=6, auto_fill=True)
    cost = occ.occasion_cost(manager, occasion)
    assert cost["total"] > 0 and cost["per_person"] == round(cost["total"] / 6, 2)
    assert cost["courses"]["main"] > 0 and set(cost["items"]) == {
        i["uid"] for i in occasion["items"]
    }
    week = manager.week_overview()
    saturday = next(d for d in week["days"] if d["date"] == SATURDAY)
    assert saturday["occasions"] == [
        {"id": occasion["id"], "title": "Grillabend", "emoji": "🔥", "cost": cost["total"]}
    ]
    assert week["occasions_total"] == cost["total"] and week["total"] >= cost["total"]
    assert week["budget_total"] == week["total"] and week["occasions_in_budget"] is True
    assert week["remaining"] == round(50 - week["total"], 2)
    manager = await _use(hass, setup_integration, **{CONF_OCCASIONS_IN_BUDGET: False})
    week = manager.week_overview()
    assert week["occasions_total"] == cost["total"]
    assert week["budget_total"] == round(week["total"] - cost["total"], 2)
    assert week["remaining"] == round(50 - week["budget_total"], 2)
    speech = await _speech(hass, "essensplaner_get_costs")
    assert "Dazu kommt Grillabend mit etwa" in speech and "(nicht im Budget)" in speech


async def test_shopping_list_week_and_own(hass: HomeAssistant, manager: Any) -> None:
    """The week's list takes in the occasions of its days; a list of its own replaces only
    its items and takes its share out of the week's items; a started own list stays."""
    lasagne = _recipe(manager, "Lasagne")
    manager.plan_meal(TODAY, "abendessen", _recipe(manager, "Kartoffelsalat"), servings=4)
    manager.plan_meal(TODAY + timedelta(days=1), "abendessen", lasagne, servings=4)
    occasion = occ.create_occasion(manager, "grillen", SATURDAY, guests=4)
    occ.add_item(manager, occasion["id"], "Kartoffelsalat")
    occ.add_item(manager, occasion["id"], {"title": "Grillkohle", "quantity": 2.5, "unit": "kg"})
    occ.add_item(manager, occasion["id"], "Gänsebraten")  # no recipe, no quantity
    result = await _call(hass, "generate_shopping_list", days=7)
    assert result["occasions"] == [{"id": occasion["id"], "title": "Grillabend", "date": SATURDAY}]
    assert result["meals"] == 3 and "Gänsebraten" in result["meals_without_recipe"]
    potatoes = next(i for i in manager.shopping if i["key"] == "kartoffel")
    assert potatoes["summary"] == "2 kg Kartoffeln"  # plan 1 kg + occasion 1 kg
    assert potatoes["recipes"] == ["Kartoffelsalat", "🔥 Grillabend"]
    assert potatoes["occasion_amounts"] == {occasion["id"]: {"g": 1000.0}}
    coal = next(i for i in manager.shopping if "Grillkohle" in i["summary"])
    assert coal["summary"] == "2,5 kg Grillkohle"
    # a list of its own for the occasion: its share leaves the week's items
    result = await _call(hass, "generate_shopping_list", occasion="Grillabend")
    assert result["occasion"]["id"] == occasion["id"] and result["start_date"] == SATURDAY
    week_potatoes = [
        i for i in manager.shopping if i["key"] == "kartoffel" and not i.get("occasion_id")
    ]
    own = [i for i in manager.shopping if i.get("occasion_id") == occasion["id"]]
    assert [i["summary"] for i in week_potatoes] == ["1 kg Kartoffeln"]
    assert "occasion_amounts" not in week_potatoes[0]
    assert not any(
        "Grillkohle" in i["summary"] and not i.get("occasion_id") for i in manager.shopping
    )
    assert {i["summary"] for i in own} >= {"1 kg Kartoffeln", "2,5 kg Grillkohle"}
    assert all(i["source"] == "plan" and "🔥 Grillabend" in i["recipes"] for i in own)
    # again: only its own items are replaced
    await _call(hass, "generate_shopping_list", occasion=occasion["id"])
    assert len([i for i in manager.shopping if i.get("occasion_id") == occasion["id"]]) == len(own)
    # shopping for it has begun: the week's list keeps it apart
    own_coal = next(
        i for i in manager.shopping if i.get("occasion_id") and "Grillkohle" in i["summary"]
    )
    manager.shopping_update(own_coal["uid"], status="completed")
    result = await _call(hass, "generate_shopping_list", days=7)
    assert result["occasions"] == []
    assert result["occasions_separate"][0]["id"] == occasion["id"]
    assert any(i.get("occasion_id") == occasion["id"] for i in manager.shopping)
    # without occasions
    result = await _call(hass, "generate_shopping_list", days=7, include_occasions=False)
    assert "occasions" not in result
    with pytest.raises(ServiceValidationError):
        await _call(hass, "generate_shopping_list", occasion="Silvesterparty")


async def test_offer_terms_drinks_only_planned(hass: HomeAssistant, manager: Any) -> None:
    """Drinks are searched for offers only when planned: an occasion's drinks, a meal's
    drinks; drinks of favourite recipes are not."""
    manager.add_recipe(
        {
            "name": "Risotto",
            "tags": ["Hauptgericht"],
            "favorite": True,
            "ingredients": ["100 ml Weißwein", "300 g Risottoreis"],
        }
    )
    keys = {k for _, k in manager.offer_search_terms(60)}
    assert "risottorei" in keys and "weisswein" not in keys and "cola" not in keys
    occasion = occ.create_occasion(manager, "familienessen", "Sonntag")
    occ.add_item(manager, occasion["id"], {"title": "Cola", "quantity": 3, "unit": "l"})
    manager.plan_meal(TODAY, "abendessen", _recipe(manager, "Lasagne"), drinks=["Rotwein"])
    keys = {k for _, k in manager.offer_search_terms(60)}
    assert {"cola", "rotwein"} <= keys and "weisswein" not in keys
    # an occasion in three weeks is not searched yet
    later = occ.create_occasion(manager, "party", "2026-11-28")
    occ.add_item(manager, later["id"], {"title": "Sekt", "quantity": 3, "unit": "l"})
    assert "sekt" not in {k for _, k in manager.offer_search_terms(60)}


async def test_auto_plan_leaves_occasion_meal(hass: HomeAssistant, manager: Any) -> None:
    """The auto plan leaves the meal free that an occasion with a main course replaces."""
    occasion = occ.create_occasion(manager, "grillen", SATURDAY, guests=4, auto_fill=True)
    planned = manager.auto_plan(date(2026, 11, 7), 1, meals=["mittagessen", "abendessen"])
    assert [(p["date"], p["meal"]) for p in planned] == [(SATURDAY, "mittagessen")]
    assert occ.occasion_meals(manager, date(2026, 11, 7)) == {"abendessen"}
    occasion["items"] = [i for i in occasion["items"] if i["course"] not in ("main", "starter")]
    assert occ.occasion_meals(manager, date(2026, 11, 7)) == set()


# ----------------------------------------------------------------------
# Calendar, sensors, export
# ----------------------------------------------------------------------


async def test_calendar_occasions(hass: HomeAssistant, manager: Any) -> None:
    """Occasions are calendar events ("<date>_occasion-<id>"); "Anlass: …" creates one,
    deleting the event deletes it; meal uids still work."""
    occasion = occ.create_occasion(manager, "filmabend", SATURDAY, guests=4, auto_fill=True)
    await hass.async_block_till_done()
    events = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": CALENDAR,
            "start_date_time": "2026-11-07T00:00:00+01:00",
            "duration": {"days": 1},
        },
        blocking=True,
        return_response=True,
    )
    found = events[CALENDAR]["events"]
    film = next(e for e in found if e["summary"] == "🎬 Filmabend")
    assert (
        film["start"] == "2026-11-07T20:00:00+01:00" and film["end"] == "2026-11-07T23:00:00+01:00"
    )
    assert (
        "👥 4 Gäste" in film["description"] and "Hauptgang: Pizza Margherita" in film["description"]
    )
    assert "Getränke:" in film["description"]
    entity = hass.data["entity_components"]["calendar"].get_entity(CALENDAR)
    assert entity.event is not None
    await hass.services.async_call(
        "calendar",
        "create_event",
        {
            "entity_id": CALENDAR,
            "summary": "Anlass: Grillabend",
            "start_date_time": "2026-11-08T17:00:00+01:00",
            "end_date_time": "2026-11-08T22:00:00+01:00",
            "description": "Bei den Nachbarn",
        },
        blocking=True,
    )
    grill = next(o for o in manager.occasions.values() if o["template"] == "grillen")
    assert grill["date"] == "2026-11-08" and grill["time"] == "17:00"
    assert grill["duration_h"] == 5.0 and grill["notes"] == "Bei den Nachbarn"
    assert not manager.plan.get("2026-11-08")  # no meal
    await entity.async_delete_event(occ.calendar_uid(occasion))
    assert occasion["id"] not in manager.occasions
    # all day without time
    occ.update_occasion(manager, grill["id"], {"time": ""})
    event = entity._occasion_event(grill)
    assert event.all_day and event.start == date(2026, 11, 8)
    # a meal event is still removed by its uid
    manager.plan_meal(TODAY, "abendessen", _recipe(manager, "Lasagne"), drinks=["Rotwein"])
    view = manager.day_meals(TODAY)[0]
    assert "Getränke: Rotwein" in entity._event(view).description
    await entity.async_delete_event(f"{TODAY.isoformat()}_abendessen")
    assert not manager.plan.get(TODAY.isoformat())


async def test_sensors(hass: HomeAssistant, manager: Any, freezer) -> None:
    """sensor next_occasion and the attribute occasions of the day sensors."""
    entity_id = "sensor.essensplaner_next_occasion"
    assert hass.states.get(entity_id).state == "unknown"
    occasion = occ.create_occasion(
        manager, "filmabend", "heute", guests=3, children=1, auto_fill=True
    )
    occ.create_occasion(manager, "brunch", "Sonntag", guests=6)
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state.state == "Filmabend"
    assert state.attributes["days_until"] == 0 and state.attributes["time"] == "20:00"
    assert state.attributes["guests"] == 3 and state.attributes["children"] == 1
    assert state.attributes["courses"]["Hauptgang"] == ["Pizza Margherita"]
    assert state.attributes["emoji"] == "🎬" and state.attributes["cost"] >= 0
    today = hass.states.get("sensor.essensplaner_today")
    assert today.attributes["occasions"] == [
        {
            "id": occasion["id"],
            "title": "Filmabend",
            "emoji": "🎬",
            "time": "20:00",
            "guests": 3,
            "children": 1,
        }
    ]
    # after the film night the brunch is next
    freezer.move_to(datetime.fromisoformat("2026-11-04T23:30:00+01:00"))
    manager.async_refresh_listeners()
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "Brunch"


async def test_export_and_views(hass: HomeAssistant, manager: Any) -> None:
    """export(): occasions from 30 days back with labels, courses and costs; templates."""
    recent = occ.create_occasion(manager, "party", "2026-10-20")
    occ.create_occasion(manager, "party", "2026-09-01")  # more than 30 days ago
    future = occ.create_occasion(manager, "weihnachten", "Heiligabend", guests=6, auto_fill=True)
    data = manager.export()
    assert [o["id"] for o in data["occasions"]] == [recent["id"], future["id"]]
    view = data["occasions"][1]
    assert view["weekday"] == "Donnerstag" and view["emoji"] == "🎄" and view["past"] is False
    assert view["uid"] == f"2026-12-24_occasion-{future['id']}"
    assert view["days_until"] == 50 and view["servings"] == 6
    assert [c["id"] for c in view["courses"]][:4] == ["starter", "main", "side", "dessert"]
    assert view["cost"]["total"] >= 0 and view["summary"]
    assert data["occasions"][0]["past"] is True
    assert [t["id"] for t in data["occasion_meta"]["templates"]][:2] == ["filmabend", "grillen"]
    assert data["occasion_meta"]["alcohol"] is True
    entry = manager.plan_meal(TODAY, "abendessen", _recipe(manager, "Lasagne"))
    assert entry["drinks"] == []


# ----------------------------------------------------------------------
# Services and websockets
# ----------------------------------------------------------------------


async def test_services(hass: HomeAssistant, manager: Any) -> None:
    """save_occasion (create, change, add, remove), get_occasions, delete_occasion."""
    result = await _call(
        hass,
        "save_occasion",
        template="grillen",
        date="Samstag",
        guests=6,
        children=2,
        items=["Kartoffelsalat", "Maiskolben"],
        auto_fill=True,
    )
    occasion = result["occasion"]
    assert occasion["date"] == SATURDAY and occasion["guests"] == 6 and occasion["children"] == 2
    titles = [i["title"] for i in occasion["items"]]
    assert titles.count("Kartoffelsalat") == 1 and "Maiskolben" in titles
    result = await _call(
        hass,
        "save_occasion",
        occasion="Grillabend",
        items="Tiramisu",
        course="dessert",
        remove="Maiskolben",
        time="19:00",
        duration=5,
    )
    occasion = result["occasion"]
    assert occasion["time"] == "19:00" and occasion["duration_h"] == 5.0
    assert "Maiskolben" not in [i["title"] for i in occasion["items"]]
    assert [i["title"] for i in occasion["items"] if i["course"] == "dessert"].count(
        "Tiramisu"
    ) >= 1
    result = await _call(hass, "get_occasions")
    assert [o["id"] for o in result["occasions"]] == [occasion["id"]]
    assert (await _call(hass, "get_occasions", start_date="2026-12-01"))["occasions"] == []
    result = await _call(hass, "get_occasions", occasion="grillen")
    assert result["occasions"][0]["title"] == "Grillabend"
    result = await _call(hass, "delete_occasion", occasion="Grillabend")
    assert result["deleted"] == {"id": occasion["id"], "title": "Grillabend", "date": SATURDAY}
    with pytest.raises(ServiceValidationError):
        await _call(hass, "delete_occasion", occasion="Grillabend")
    entry = await _call(
        hass, "plan_meal", date="heute", recipe="Lasagne", drinks="Rotwein, Apfelschorle"
    )
    assert entry["entry"]["drinks"] == [
        {"title": "Rotwein", "alcohol": True},
        {"title": "Apfelschorle", "alcohol": False},
    ]


async def test_websockets(hass: HomeAssistant, manager: Any, hass_ws_client) -> None:
    """occasion_save / occasion_delete / occasion_suggest / drinks_suggest."""
    msg = await _ws(
        hass,
        hass_ws_client,
        "occasion_save",
        occasion={"template": "filmabend", "date": SATURDAY, "guests": 4, "auto_fill": True},
    )
    assert msg["success"], msg
    occasion = msg["result"]["occasion"]
    assert occasion["template"] == "filmabend" and occasion["items"]
    items = [i for i in occasion["items"] if i["course"] != "snack"]
    items.append({"course": "snack", "title": "Salzstangen", "quantity": 2, "unit": "Tüte"})
    msg = await _ws(
        hass,
        hass_ws_client,
        "occasion_save",
        occasion={"id": occasion["id"], "items": items, "children": 2},
    )
    assert msg["success"], msg
    saved = msg["result"]["occasion"]
    assert [i["title"] for i in saved["items"] if i["course"] == "snack"] == ["Salzstangen"]
    assert saved["children"] == 2
    msg = await _ws(hass, hass_ws_client, "occasion_save", occasion={"id": "nope"})
    assert not msg["success"] and msg["error"]["code"] == "occasion_not_found"
    assert "nicht gefunden" in msg["error"]["message"]
    msg = await _ws(
        hass, hass_ws_client, "occasion_save", occasion={"template": "filmabend", "time": "abends"}
    )
    assert msg["error"]["code"] == "invalid_time"
    msg = await _ws(
        hass, hass_ws_client, "occasion_suggest", occasion_id=occasion["id"], course="snack"
    )
    assert msg["success"] and list(msg["result"]["suggestions"]) == ["snack"]
    assert msg["result"]["suggestions"]["snack"][0]["title"] == "Nachos mit Käsedip"
    msg = await _ws(
        hass,
        hass_ws_client,
        "occasion_suggest",
        occasion_id=occasion["id"],
        course="snack",
        apply=True,
    )
    assert msg["result"]["applied"] == ["Nachos mit Käsedip"]
    msg = await _ws(hass, hass_ws_client, "drinks_suggest", occasion_id=occasion["id"])
    assert msg["success"] and msg["result"]["quantities"]["guests"] == 4
    assert sum(1 for d in msg["result"]["drinks"] if not d["alcohol"]) >= 2
    msg = await _ws(hass, hass_ws_client, "drinks_suggest", recipe_ids=["nope"])
    assert msg["error"]["code"] == "recipe_not_found"
    msg = await _ws(hass, hass_ws_client, "occasion_delete", occasion_id=occasion["id"])
    assert msg["result"] == {"deleted": occasion["id"]}
    assert occasion["id"] not in manager.occasions


# ----------------------------------------------------------------------
# Intents
# ----------------------------------------------------------------------


async def test_intent_plan_occasion(hass: HomeAssistant, manager: Any) -> None:
    """ "Plane einen Filmabend am Samstag für 4" plans it with menu and drinks; again: the
    number of guests changes."""
    speech = await _speech(
        hass, "essensplaner_plan_occasion", occasion="filmabend", date="am samstag", guests=4
    )
    assert speech.startswith("Ich habe Filmabend am Samstag um 20:00 Uhr für 4 Personen geplant.")
    assert "Hauptgang: Pizza Margherita" in speech and "Getränke:" in speech
    assert "Zubehör" not in speech
    occasion = next(iter(manager.occasions.values()))
    assert occasion["date"] == SATURDAY and occasion["guests"] == 4
    speech = await _speech(
        hass,
        "essensplaner_plan_occasion",
        occasion="filmabend",
        date="samstag",
        guests=6,
        children=2,
    )
    assert "schon geplant – jetzt für 6 Erwachsene und 2 Kinder" in speech
    assert len(manager.occasions) == 1
    speech = await _speech(
        hass, "essensplaner_plan_occasion", occasion="Omas Geburtstag", date="sonntag", guests=10
    )
    assert "Omas Geburtstag" in speech
    birthday = next(o for o in manager.occasions.values() if o["template"] == "geburtstag")
    assert birthday["title"] == "Omas Geburtstag"


async def test_intent_get_occasion(hass: HomeAssistant, manager: Any) -> None:
    """ "Was gibt es Weihnachten?" names the occasion near the holiday; without one the
    meals of that day; without words the next occasion."""
    speech = await _speech(hass, "essensplaner_get_occasion")
    assert speech == "Es ist gerade kein Anlass geplant."
    speech = await _speech(hass, "essensplaner_get_occasion", date="weihnachten")
    assert speech == "Für Freitag, 25.12. ist noch nichts geplant."
    occasion = occ.create_occasion(manager, "weihnachten", "Heiligabend", guests=4)
    occ.add_item(manager, occasion["id"], "Lasagne")
    occ.add_item(manager, occasion["id"], "Tiramisu")
    speech = await _speech(hass, "essensplaner_get_occasion", date="weihnachten")
    assert speech.startswith("Weihnachtsessen am Donnerstag, 24.12. um 18:00 Uhr für 4 Personen:")
    assert "Hauptgang: Lasagne; Dessert: Tiramisu." in speech
    speech = await _speech(hass, "essensplaner_get_occasion", occasion="weihnachtsessen")
    assert "Hauptgang: Lasagne" in speech
    speech = await _speech(hass, "essensplaner_get_occasion")
    assert speech.startswith("Weihnachtsessen am Donnerstag, 24.12.")
    manager.plan_meal(date(2026, 12, 31), "abendessen", _recipe(manager, "Pizza Margherita"))
    speech = await _speech(hass, "essensplaner_get_occasion", date="silvester")
    assert speech == (
        "Für Donnerstag, 31.12. ist kein Anlass geplant, aber es gibt zum Abendessen "
        "Pizza Margherita."
    )


async def test_intent_edit_occasion(hass: HomeAssistant, manager: Any) -> None:
    """ "Füge Kartoffelsalat zum Grillabend hinzu", remove, guests."""
    occasion = occ.create_occasion(manager, "grillen", SATURDAY, guests=4)
    speech = await _speech(
        hass, "essensplaner_edit_occasion", dish="kartoffelsalat", occasion="grillabend"
    )
    assert speech == "Ich habe Kartoffelsalat zum Grillabend hinzugefügt (Beilagen)."
    speech = await _speech(
        hass,
        "essensplaner_edit_occasion",
        dish="das kartoffelsalat",
        occasion="grillabend",
        action="entfernen",
    )
    assert speech == "Ich habe Kartoffelsalat vom Grillabend gestrichen."
    speech = await _speech(hass, "essensplaner_edit_occasion", occasion="grillabend", guests=8)
    assert speech == "Zum Grillabend kommen jetzt 8 Personen."
    assert occasion["guests"] == 8
    speech = await _speech(
        hass,
        "essensplaner_edit_occasion",
        dish="Würstchen",
        occasion="grillabend",
        course="Hauptgang",
    )
    assert "(Hauptgang)" in speech
    speech = await _speech(hass, "essensplaner_edit_occasion", dish="Tiramisu", action="streichen")
    assert speech == "„Tiramisu“ steht nicht auf dem Plan für „Grillabend“."
    speech = await _speech(
        hass, "essensplaner_edit_occasion", occasion="silvesterparty", dish="Sekt"
    )
    assert speech == "Den Anlass „silvesterparty“ habe ich nicht gefunden."
