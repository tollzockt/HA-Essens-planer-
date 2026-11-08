"""1.5.1: editable amounts of occasion items, products of the user's stores for drinks,
snacks and extras, single days of the auto plan suggested again ("🔄 Neu vorschlagen"),
richer AI menus (occasions and the auto plan) and "Aktuell" on Sundays.

Made-up recipes, products and brands only; the clock is frozen (conftest: Wednesday
2026-11-04); the AI is faked."""

from __future__ import annotations

from datetime import date, datetime
import json
from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.essensplaner import occasions as occ, season as sea
from custom_components.essensplaner.catalog import store_offers_view
from custom_components.essensplaner.const import (
    CONF_AI_ENTITY,
    CONF_BUDGET,
    CONF_DEFAULT_MEAL,
    CONF_DEFAULT_SERVINGS,
    CONF_DRINKS_ALCOHOL,
    CONF_ENABLED_MEALS,
    CONF_IMPORT_STARTER,
    CONF_PANTRY,
    CONF_REGISTER_INTENTS,
    CONF_SHOW_PANEL,
    DOMAIN,
)
from custom_components.essensplaner.products import save_manual

from .test_occasions_1_5 import RECIPES

TODAY = date(2026, 11, 4)  # Wednesday
SATURDAY = "2026-11-07"
TASK = "ai_task.koch"
DINNER = "abendessen"

MORE_RECIPES: list[dict[str, Any]] = [
    {
        "name": "Kürbissuppe",
        "tags": ["Hauptgericht", "Suppe", "Herbst"],
        "servings": 4,
        "ingredients": ["1 kg Kürbis", "1 Zwiebel", "200 ml Sahne"],
    },
    {
        "name": "Linsencurry",
        "tags": ["Hauptgericht", "Vegetarisch"],
        "servings": 4,
        "ingredients": ["250 g Linsen", "400 ml Kokosmilch"],
        "notes": "Rezept von Tante Fiktiva, Musterweg 7",
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
            CONF_DEFAULT_MEAL: DINNER,
            CONF_ENABLED_MEALS: ["fruehstueck", "mittagessen", DINNER],
            CONF_PANTRY: "Salz, Pfeffer, Wasser, Öl",
            CONF_REGISTER_INTENTS: True,
            CONF_SHOW_PANEL: True,
        },
    )


@pytest.fixture
async def manager(hass: HomeAssistant, setup_integration: MockConfigEntry) -> Any:
    manager = setup_integration.runtime_data
    for recipe in [*RECIPES, *MORE_RECIPES]:
        manager.add_recipe(recipe)
    return manager


async def _use(hass: HomeAssistant, entry: MockConfigEntry, **options: Any) -> Any:
    hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
    await hass.async_block_till_done()
    return entry.runtime_data


async def _call(hass: HomeAssistant, service: str, **data: Any) -> Any:
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


async def _ws(client: Any, command: str, **data: Any) -> dict[str, Any]:
    _ws.counter = getattr(_ws, "counter", 0) + 1
    await client.send_json({"id": _ws.counter, "type": f"{DOMAIN}/{command}", **data})
    return await client.receive_json()


def _fake_task(hass: HomeAssistant, answer: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def handler(call: ServiceCall) -> Any:
        calls.append(dict(call.data))
        return answer

    hass.services.async_register(
        "ai_task", "generate_data", handler, supports_response=SupportsResponse.ONLY
    )
    hass.states.async_set(TASK, "unknown", {"friendly_name": "Koch-KI"})
    return calls


def _payload(call: dict[str, Any]) -> dict[str, Any]:
    text = call["instructions"]
    return json.loads(text.split("Daten (JSON):\n", 1)[1].rsplit("\n\n", 1)[0])


def _item(occasion: dict[str, Any], title: str) -> dict[str, Any]:
    return next(i for i in occasion["items"] if i["title"] == title)


def _stock(manager: Any) -> dict[str, dict[str, Any]]:
    """A Lidl branch with made-up products: cola, chips, beer, napkins."""
    manager.save_branch({"store": "Lidl", "postcode": "80331"})
    return {
        "cola": save_manual(
            manager,
            {"store": "Lidl", "name": "Cola", "brand": "Kolafix", "pack": "1,5 l", "price": 0.79},
        ),
        "cola_big": save_manual(
            manager,
            {
                "store": "Lidl",
                "name": "Cola Party",
                "brand": "Kolafix",
                "pack": "2 l",
                "price": 1.49,
                "ingredient": "Cola",
            },
        ),
        "chips": save_manual(
            manager,
            {
                "store": "Lidl",
                "name": "Chips",
                "brand": "Knusperland",
                "pack": "200 g",
                "price": 1.19,
            },
        ),
        "beer": save_manual(
            manager,
            {
                "store": "Lidl",
                "name": "Pils",
                "brand": "Brauhaus Fiktiv",
                "pack": "0,5 l",
                "price": 0.69,
                "ingredient": "Bier",
            },
        ),
        "napkins": save_manual(
            manager,
            {
                "store": "Lidl",
                "name": "Servietten",
                "brand": "Weichfein",
                "pack": "50 Stück",
                "price": 1.29,
            },
        ),
    }


# ----------------------------------------------------------------------
# Editable amounts
# ----------------------------------------------------------------------


async def test_cola_and_party_drinks_have_a_price(hass: HomeAssistant, manager: Any) -> None:
    """ "Ohne Preis: Cola" is gone: Cola, Bowle & Co. have default prices; with products
    of the user's stores a free drink costs what the product costs."""
    occasion = occ.create_occasion(manager, "party", SATURDAY, guests=10, auto_fill=True)
    cost = occ.occasion_cost(manager, occasion)
    assert "Cola" in [i["title"] for i in occasion["items"]]
    assert cost["unknown"] == []
    for name in ("Cola", "Cola Zero", "Spezi", "Fanta", "Erdbeerbowle", "Kinderbowle"):
        assert manager.best_price(name)[0] is not None, name
    # no recipe twice (the pizza is the main dish, not also a snack)
    recipe_ids = [i["recipe_id"] for i in occasion["items"] if i.get("recipe_id")]
    assert len(recipe_ids) == len(set(recipe_ids))
    # a real product beats the estimate: 3.5 l = 3 bottles of 1.5 l at 0.79 €
    _stock(manager)
    cola = _item(occasion, "Cola")
    assert occ.occasion_cost(manager, occasion)["items"][cola["uid"]] == round(3 * 0.79, 2)


async def test_update_items_amounts(hass: HomeAssistant, manager: Any, hass_ws_client) -> None:
    """update_items changes one item in place: servings of a dish (None = the occasion's),
    quantity and unit of a drink, snack or extra; a changed amount no longer follows the
    guests; costs and the shopping entries follow at once."""
    occasion = occ.create_occasion(manager, "party", SATURDAY, guests=10, auto_fill=True)
    cola = _item(occasion, "Cola")
    chips = _item(occasion, "Chips")
    pizza = next(i for i in occasion["items"] if i.get("recipe_id"))
    before = occ.occasion_cost(manager, occasion)
    client = await hass_ws_client(hass)
    msg = await _ws(
        client,
        "occasion_save",
        occasion={
            "id": occasion["id"],
            "update_items": [
                {"uid": cola["uid"], "quantity": "6,5", "unit": "l"},
                {"uid": chips["uid"], "quantity": 4},
                {"uid": pizza["uid"], "servings": 16},
            ],
        },
    )
    assert msg["success"], msg
    view = msg["result"]["occasion"]
    by_uid = {i["uid"]: i for i in view["items"]}
    assert (by_uid[cola["uid"]]["quantity"], by_uid[cola["uid"]]["unit"]) == (6.5, "l")
    assert by_uid[cola["uid"]]["quantity_text"] == "6,5 l"
    assert "auto" not in occasion["items"][occasion["items"].index(_item(occasion, "Cola"))]
    assert by_uid[chips["uid"]]["quantity_text"] == "4 Tüte"
    assert by_uid[pizza["uid"]]["servings"] == 16
    after = occ.occasion_cost(manager, occasion)
    assert after["items"][cola["uid"]] > before["items"][cola["uid"]]
    assert after["items"][pizza["uid"]] > before["items"][pizza["uid"]]
    assert after["total"] == view["cost"]["total"]
    # the shopping entries have the new amounts
    entries, _without, _dishes = occ.occasion_entries(manager, occasion)
    assert {"name": "Cola", "amount": 6.5, "unit": "l"} in [e for e, _ in entries]
    # more guests: the changed amounts stay, the automatic ones follow
    occ.update_occasion(manager, occasion["id"], {"guests": 20})
    assert _item(occasion, "Cola")["quantity"] == 6.5
    assert _item(occasion, "Salzstangen")["quantity"] > 2
    # back to the occasion's servings; no quantity; junk is clamped or ignored
    occ.update_occasion(
        manager,
        occasion["id"],
        {
            "update_items": [
                {"uid": pizza["uid"], "servings": None},
                {"uid": chips["uid"], "quantity": None},
                {"uid": cola["uid"], "quantity": 99999},
            ]
        },
    )
    assert "servings" not in _item(occasion, pizza["title"])
    assert "quantity" not in _item(occasion, "Chips")
    assert _item(occasion, "Cola")["quantity"] == occ.MAX_QUANTITY
    msg = await _ws(
        client, "occasion_save", occasion={"id": occasion["id"], "update_items": [{"uid": "x"}]}
    )
    assert msg["error"]["code"] == "occasion_item_not_found"


async def test_link_products_to_items(hass: HomeAssistant, manager: Any, hass_ws_client) -> None:
    """📦: the products of the user's stores for an item, priced for its amount (cheapest
    first); linking turns the amount into packs, unlinking back into litres; the cost is
    the product's, the shopping list has the product."""
    products = _stock(manager)
    occasion = occ.create_occasion(manager, "party", SATURDAY, guests=10, auto_fill=True)
    cola = _item(occasion, "Cola")
    occ.update_occasion(
        manager, occasion["id"], {"update_items": [{"uid": cola["uid"], "quantity": 5}]}
    )
    client = await hass_ws_client(hass)
    msg = await _ws(client, "occasion_products", occasion_id=occasion["id"], uid=cola["uid"])
    assert msg["success"], msg
    result = msg["result"]
    assert (result["name"], result["quantity"], result["unit"], result["current"]) == (
        "Cola",
        5.0,
        "l",
        None,
    )
    rows = result["products"]
    assert [r["id"] for r in rows] == [products["cola"]["id"], products["cola_big"]["id"]]
    assert (rows[0]["packs"], rows[0]["cost"], rows[0]["store"]) == (4, 3.16, "Lidl")
    assert rows[0]["brand"] == "Kolafix" and rows[0]["pack"] == "1,5 l"
    # search: any product of the stores
    msg = await _ws(
        client, "occasion_products", occasion_id=occasion["id"], uid=cola["uid"], query="knusper"
    )
    assert products["chips"]["id"] in [r["id"] for r in msg["result"]["products"]]

    msg = await _ws(
        client,
        "occasion_save",
        occasion={
            "id": occasion["id"],
            "update_items": [{"uid": cola["uid"], "product_id": products["cola_big"]["id"]}],
        },
    )
    item = next(i for i in msg["result"]["occasion"]["items"] if i["uid"] == cola["uid"])
    assert (item["product_id"], item["quantity"], item["title"]) == (
        products["cola_big"]["id"],
        3.0,  # 5 l in 2 l bottles
        "Cola",
    )
    assert item["quantity_text"] == "3 Pck." and item["product"]["brand"] == "Kolafix"
    assert item["cost"] == round(3 * 1.49, 2)
    stored = _item(occasion, "Cola")
    assert "unit" not in stored and "auto" not in stored
    entries, _without, _dishes = occ.occasion_entries(manager, occasion)
    assert {
        "name": "Cola",
        "amount": 3.0,
        "unit": "Pck.",
        "product_id": products["cola_big"]["id"],
    } in [e for e, _ in entries]
    msg = await _ws(client, "occasion_products", occasion_id=occasion["id"], uid=cola["uid"])
    assert msg["result"]["current"] == products["cola_big"]["id"]
    assert (msg["result"]["quantity"], msg["result"]["unit"]) == (6.0, "l")
    # packs stepped; an unknown product is refused; unlinking gives litres again
    occ.update_occasion(
        manager, occasion["id"], {"update_items": [{"uid": cola["uid"], "quantity": 2.2}]}
    )
    assert _item(occasion, "Cola")["quantity"] == 3.0  # whole packs
    with pytest.raises(ServiceValidationError) as err:
        occ.update_occasion(
            manager,
            occasion["id"],
            {"update_items": [{"uid": cola["uid"], "product_id": "gibt-es-nicht"}]},
        )
    assert err.value.translation_key == "product_not_found"
    occ.update_occasion(
        manager, occasion["id"], {"update_items": [{"uid": cola["uid"], "product_id": None}]}
    )
    stored = _item(occasion, "Cola")
    assert "product_id" not in stored and (stored["quantity"], stored["unit"]) == (6.0, "l")
    msg = await _ws(client, "occasion_products", occasion_id="nope")
    assert msg["error"]["code"] == "occasion_not_found"


# ----------------------------------------------------------------------
# One day of the auto plan suggested again
# ----------------------------------------------------------------------


async def test_replan_meal_service(hass: HomeAssistant, manager: Any) -> None:
    """replan_meal: another recipe for exactly that slot – never the dish planned there,
    none of the week while there are others, not the excluded ones; with reasons, cost and
    the week's total; without another recipe the slot stays."""
    result = await _call(hass, "auto_plan", days=2, meals=[DINNER])
    planned = result["planned"]
    assert len(planned) == 2 and all("cost" in p and "reasons" in p for p in planned)
    first, second = planned
    meals = {r["id"] for r in manager.recipes.values() if manager._fits_meal(r, DINNER)}
    shown = {first["recipe_id"]}
    for _ in range(len(meals) - 2):
        result = await _call(
            hass, "replan_meal", date=first["date"], meal=DINNER, exclude=sorted(shown)
        )
        assert result["found"] is True
        entry = result["entry"]
        assert entry["recipe_id"] in meals - shown - {second["recipe_id"]}
        assert entry["date"] == first["date"] and entry["meal"] == DINNER
        assert isinstance(entry["reasons"], list) and entry["cost"] is not None
        assert result["week"]["total"] == manager.week_overview(TODAY)["total"]
        assert manager.plan[first["date"]][DINNER]["recipe_id"] == entry["recipe_id"]
        shown.add(entry["recipe_id"])
    # names work as well; only the dish of the other day is left: it may come now
    names = [manager.recipes[r]["name"] for r in shown]
    result = await _call(hass, "replan_meal", date=first["date"], meal=DINNER, exclude=names)
    assert result["entry"]["recipe_id"] == second["recipe_id"]
    # nothing else: the slot stays
    current = manager.plan[first["date"]][DINNER]["recipe_id"]
    result = await _call(
        hass, "replan_meal", date=first["date"], meal=DINNER, exclude=sorted(meals)
    )
    assert result["found"] is False and result["entry"] is None
    assert result["previous"]["recipe_id"] == current
    assert manager.plan[first["date"]][DINNER]["recipe_id"] == current
    # an empty slot gets a dish, the servings of the slot are kept
    manager.plan_meal(date(2026, 11, 6), DINNER, title="Pizza bestellen", servings=5)
    result = await _call(hass, "replan_meal", date="2026-11-06", meal=DINNER)
    assert result["entry"]["recipe_id"] and result["entry"]["servings"] == 5
    assert result["previous"] == {"recipe_id": None, "title": "Pizza bestellen"}


async def test_replan_meal_keeps_the_budget(
    hass: HomeAssistant, manager: Any, setup_integration: MockConfigEntry
) -> None:
    """With the strategy "günstig" and a small budget the cheapest fitting recipe wins
    most of the time (the weights of the auto plan)."""
    manager = await _use(hass, setup_integration, **{CONF_BUDGET: 20})
    manager.plan_meal(TODAY, DINNER, recipe=manager.get_recipe_by_name("Rindersteak vom Grill"))
    costs = {
        r["id"]: manager.recipe_cost(r, 2, TODAY)["total"]
        for r in manager.recipes.values()
        if manager._fits_meal(r, DINNER)
    }
    picked = []
    for _ in range(8):
        result = await _call(hass, "replan_meal", meal=DINNER, strategy="günstig")
        picked.append(costs[result["entry"]["recipe_id"]])
        manager.plan_meal(TODAY, DINNER, recipe=manager.get_recipe_by_name("Rindersteak vom Grill"))
    expensive = max(costs.values())
    assert sum(1 for c in picked if c < expensive) >= 6


# ----------------------------------------------------------------------
# The AI menu of an occasion
# ----------------------------------------------------------------------


async def test_ai_menu_payload_has_candidates_and_no_private_data(
    hass: HomeAssistant, manager: Any, setup_integration: MockConfigEntry
) -> None:
    """The AI gets the occasion (kind, date, season, guests, children, duration, alcohol,
    budget), per course the rules' recipes (id, name, kind, tags, cost) and the products
    of the user's stores (id, name, brand, pack, price, chain, offer), what is planned –
    never the title, notes, addresses or postcodes; it waits AI_TIMEOUT seconds."""
    manager = await _use(hass, setup_integration, **{CONF_AI_ENTITY: TASK, CONF_BUDGET: 80})
    manager.save_branch({"store": "Lidl", "street": "Lindenweg 1", "postcode": "80331"})
    products = _stock(manager)
    calls = _fake_task(hass, {"data": {"items": []}})
    timeouts: list[float] = []
    from custom_components.essensplaner import ai as ai_module

    real = ai_module._async_request

    async def spy(hass_: Any, entity: str, task: str, prompt: str, timeout: float) -> Any:
        timeouts.append(timeout)
        return await real(hass_, entity, task, prompt, timeout)

    ai_module._async_request = spy
    try:
        occasion = occ.create_occasion(
            manager,
            "party",
            SATURDAY,
            guests=8,
            children=2,
            title="Lenas 30. bei Familie Beispiel",
            notes="Schlüssel bei Nachbarin Musterfrau",
        )
        occ.add_item(manager, occasion["id"], "Kartoffelsalat")
        result = await occ.async_suggest_menu(hass, manager, occasion, ai=True)
    finally:
        ai_module._async_request = real
    assert result["ai"] == {"ok": True}
    assert timeouts == [occ.AI_TIMEOUT]
    prompt = calls[0]["instructions"]
    for private in ("Lena", "Beispiel", "Musterfrau", "Lindenweg", "80331", "Fiktiva"):
        assert private not in prompt, private
    assert "Denke gründlich" in prompt and "Benutze keine Werkzeuge" in prompt
    payload = _payload(calls[0])
    anlass = payload["anlass"]
    assert (anlass["art"], anlass["datum"], anlass["gaeste"], anlass["kinder"]) == (
        "Party",
        SATURDAY,
        8,
        2,
    )
    assert anlass["alkohol_erlaubt"] is True and anlass["dauer_h"] and anlass["jahreszeit"]
    assert payload["budget"]["woche"] == 80
    courses = {c["id"] for c in payload["gaenge"]}
    assert {"main", "snack", "drink", "extra"} <= courses
    by_name = {r["name"]: r for r in payload["rezepte"]}
    assert by_name["Pizza Margherita"]["gang"] in ("main", "snack")
    assert by_name["Pizza Margherita"]["art"] and by_name["Pizza Margherita"]["kosten_portion"]
    assert "Kartoffelsalat" not in by_name  # planned already
    assert {"gang": "side", "titel": "Kartoffelsalat", "menge": "9 Portionen"} in payload[
        "schon_geplant"
    ]
    articles = {a["id"]: a for a in payload["artikel"]}
    assert products["cola"]["id"] in articles and products["chips"]["id"] in articles
    cola = articles[products["cola"]["id"]]
    assert (cola["marke"], cola["packung"], cola["preis"], cola["laden"], cola["gang"]) == (
        "Kolafix",
        "1,5 l",
        0.79,
        "Lidl",
        "drink",
    )
    assert articles[products["chips"]["id"]]["gang"] == "snack"
    assert payload["richtwerte"]["getraenke_l"] > 0


async def test_ai_menu_is_validated_and_applied(
    hass: HomeAssistant, manager: Any, setup_integration: MockConfigEntry
) -> None:
    """Only given ids, known courses, no duplicates (also of what is planned, folded),
    no alcohol when switched off, amounts clamped, at most AI_PER_COURSE dishes per course;
    free items only when nothing fits (ai: true); the note comes back; apply puts the
    whole plan in with amounts and reasons."""
    manager = await _use(
        hass, setup_integration, **{CONF_AI_ENTITY: TASK, CONF_DRINKS_ALCOHOL: False}
    )
    products = _stock(manager)
    ids = {r["name"]: r["id"] for r in manager.recipes.values()}
    occasion = occ.create_occasion(manager, "grillen", SATURDAY, guests=6)
    occ.add_item(manager, occasion["id"], {"title": "Grillkohle", "course": "extra"})
    answer = {
        "data": {
            "items": [
                {
                    "gang": "main",
                    "rezept_id": ids["Bratwurst vom Grill"],
                    "portionen": 999,
                    "grund": "Klassiker vom Grill",
                },
                {"gang": "main", "rezept_id": ids["Bratwurst vom Grill"]},  # twice
                {"gang": "main", "rezept_id": "erfunden"},  # unknown id, no title
                {"gang": "main", "titel": "RINDERSTEAK VOM GRILL", "portionen": 3},
                {"gang": "side", "titel": "kartoffelsalat", "grund": "passt zum Grillen"},
                {"gang": "side", "rezept_id": ids["Tzatziki"]},
                {"gang": "dessert", "rezept_id": ids["Lasagne"]},  # a main: goes there
                {"gang": "suppe", "titel": "Kürbissuppe"},  # not a course
                {
                    "gang": "drink",
                    "artikel_id": products["cola"]["id"],
                    "menge": 500,
                    "grund": "für alle",
                },
                {"gang": "drink", "artikel_id": products["beer"]["id"], "menge": 6},  # alcohol
                {"gang": "drink", "titel": "Rotwein", "menge": 2, "einheit": "l"},  # alcohol
                {"gang": "drink", "titel": "Holunderschorle", "menge": 0.1, "einheit": "l"},
                {"gang": "extra", "titel": "grillkohle"},  # planned already
                {"gang": "extra", "artikel_id": products["napkins"]["id"]},
                {
                    "gang": "extra",
                    "artikel_id": "erfunden",
                    "titel": "Grillanzünder",
                    "menge": 2,
                    "einheit": "Pck.",
                },
            ],
            "notiz": "Deftig vom Grill, dazu frische Beilagen.",
        }
    }
    _fake_task(hass, answer)
    result = await occ.async_suggest_menu(hass, manager, occasion, ai=True)
    assert result["ai"] == {"ok": True, "notes": "Deftig vom Grill, dazu frische Beilagen."}
    menu = result["suggestions"]
    ai = {c: [s for s in found if s.get("ai")] for c, found in menu.items()}
    mains = [s["title"] for s in ai["main"]]
    assert mains == ["Bratwurst vom Grill", "Rindersteak vom Grill", "Lasagne"]
    assert ai["main"][0]["servings_ai"] == 3 * occ.servings_of(occasion)
    assert ai["main"][0]["reason"] == "Klassiker vom Grill"
    assert ai["main"][1]["servings_ai"] == 3
    assert [s["title"] for s in ai["side"]] == ["Kartoffelsalat", "Tzatziki"]
    assert ai["side"][0]["recipe_id"] == ids["Kartoffelsalat"]
    assert "dessert" not in ai or not ai["dessert"]
    drinks = {s["title"]: s for s in ai["drink"]}
    assert set(drinks) == {"Kolafix Cola", "Holunderschorle"}
    assert drinks["Kolafix Cola"]["product_id"] == products["cola"]["id"]
    assert drinks["Kolafix Cola"]["quantity"] == 3 * occ.persons_of(occasion)  # clamped
    assert (drinks["Holunderschorle"]["quantity"], drinks["Holunderschorle"]["unit"]) == (
        0.5,
        "l",
    )
    assert all(not s.get("alcohol") for s in ai["drink"])
    extras = {s["title"]: s for s in ai["extra"]}
    assert set(extras) == {"Weichfein Servietten", "Grillanzünder"}
    assert (extras["Grillanzünder"]["quantity"], extras["Grillanzünder"]["unit"]) == (2.0, "Pck.")
    assert all(s["ai"] for c in ai.values() for s in c)

    applied = await occ.async_suggest_menu(hass, manager, occasion, ai=True, apply=True)
    assert "Bratwurst vom Grill" in applied["applied"]
    wurst = _item(occasion, "Bratwurst vom Grill")
    assert wurst["servings"] == 3 * occ.servings_of(occasion) and wurst["ai"] is True
    assert wurst["reason"] == "Klassiker vom Grill"
    cola = _item(occasion, "Kolafix Cola")
    assert cola["product_id"] == products["cola"]["id"] and cola["course"] == "drink"
    assert _item(occasion, "Grillanzünder")["quantity"] == 2.0
    titles = [i["title"] for i in occasion["items"]]
    assert len(titles) == len({t.casefold() for t in titles})
    view = occ.occasion_view(manager, occasion)
    assert next(i for i in view["items"] if i["uid"] == wurst["uid"])["reason"]


def test_ai_quantity_clamps() -> None:
    """Sane amounts: packs 1 … 3 per person, litres from 0.5, grams from 50, pieces from 1."""
    assert occ.ai_quantity(500, "", 4, packs=True) == (12.0, "")
    assert occ.ai_quantity(0.2, "", 4, packs=True) == (1.0, "")
    assert occ.ai_quantity("2,25", "l", 4) == (2.5, "l")
    assert occ.ai_quantity(100, "l", 2) == (8.0, "l")
    assert occ.ai_quantity(10, "g", 4) == (50.0, "g")
    assert occ.ai_quantity(3, "Tüte", 1) == (3.0, "Tüte")
    assert occ.ai_quantity("viel", "l", 4) is None


# ----------------------------------------------------------------------
# The auto plan with AI
# ----------------------------------------------------------------------


async def test_auto_plan_ai_gets_days_and_picks(
    hass: HomeAssistant, manager: Any, setup_integration: MockConfigEntry
) -> None:
    """The AI gets per day the candidates the rules rank best that day and per recipe its
    kind, cost, season and offers (no notes); its plan per slot is used when it fits
    (wrong days, meals, ids and doubles are dropped), the reason shows; its note comes
    back."""
    manager = await _use(hass, setup_integration, **{CONF_AI_ENTITY: TASK, CONF_BUDGET: 60})
    ids = {r["name"]: r["id"] for r in manager.recipes.values()}
    answer = {
        "data": {
            "plan": [
                {
                    "date": "2026-11-04",
                    "meal": "Abendessen",
                    "id": ids["Linsencurry"],
                    "reason": "schnell und günstig",
                },
                {"date": "2026-11-05", "meal": DINNER, "id": ids["Linsencurry"]},  # twice
                {"date": "2026-11-05", "meal": DINNER, "id": ids["Tiramisu"]},  # no meal
                {"date": "2026-11-05", "meal": DINNER, "id": "Kürbissuppe", "reason": "Saison"},
                {"date": "2026-11-20", "meal": DINNER, "id": ids["Lasagne"]},  # not asked
                {"date": "2026-11-06", "meal": "fruehstueck", "id": ids["Lasagne"]},
            ],
            "notes": "Viel Herbst, wenig Fleisch.",
        }
    }
    calls = _fake_task(hass, answer)
    result = await _call(hass, "auto_plan", days=3, ai=True)
    assert result["ai"] == {"ok": True, "notes": "Viel Herbst, wenig Fleisch."}
    planned = {p["date"]: p for p in result["planned"]}
    assert planned["2026-11-04"]["recipe_id"] == ids["Linsencurry"]
    assert planned["2026-11-04"]["reasons"][0] == "🤖 schnell und günstig"
    assert planned["2026-11-05"]["recipe_id"] == ids["Kürbissuppe"]
    assert planned["2026-11-05"]["reasons"][0] == "🤖 Saison"
    assert len(planned) == 3 and all(p["cost"] is not None for p in planned.values())
    assert not any(r.startswith("🤖") for r in planned["2026-11-06"]["reasons"])
    prompt = calls[0]["instructions"]
    assert "Fiktiva" not in prompt and "Musterweg" not in prompt
    payload = _payload(calls[0])
    assert [d["date"] for d in payload["days"]] == ["2026-11-04", "2026-11-05", "2026-11-06"]
    assert all(d["candidates"] for d in payload["days"])
    assert payload["meals"] == [{"id": DINNER, "name": "Abendessen"}]
    known = {c["id"] for c in payload["candidates"]}
    assert all(set(d["candidates"]) <= known for d in payload["days"])
    curry = next(c for c in payload["candidates"] if c["name"] == "Linsencurry")
    assert curry["kind"] and curry["cost_per_serving"] and curry["meals"] == [DINNER]
    assert payload["budget"]["week"] == 60 and payload["servings"] == 2


def test_parse_ai_plan_checks_slots(hass: HomeAssistant) -> None:
    """Slots of the request only, meals by id or name, candidates by id or name, each
    recipe once, one per slot."""

    class Fake:
        def _fits_meal(self, recipe: dict[str, Any], meal: str) -> bool:
            return recipe["id"] != "dessert"

    candidates = [
        {"id": "a", "name": "Kürbissuppe"},
        {"id": "b", "name": "Linsencurry"},
        {"id": "dessert", "name": "Tiramisu"},
    ]
    answer = {
        "plan": [
            {"date": "2026-11-04", "meal": "abendessen", "id": "a", "reason": "x" * 300},
            {"date": "2026-11-04", "meal": "abendessen", "id": "b"},  # slot taken
            {"date": "2026-11-05", "meal": "Abendessen", "id": "linsencurry"},
            {"date": "2026-11-06", "meal": "abendessen", "id": "dessert"},
            {"date": "2026-11-03", "meal": "abendessen", "id": "b"},
            "unsinn",
        ]
    }
    picks = sea.parse_ai_plan(Fake(), answer, candidates, TODAY, 3, [DINNER])
    assert set(picks) == {("2026-11-04", DINNER), ("2026-11-05", DINNER)}
    assert picks[("2026-11-05", DINNER)] == {"id": "b", "reason": ""}
    assert len(picks[("2026-11-04", DINNER)]["reason"]) == sea.REASON_MAX
    assert sea.parse_ai_plan(Fake(), {"order": ["a"]}, candidates, TODAY, 3, [DINNER]) == {}


# ----------------------------------------------------------------------
# Offers: "Aktuell" on Sundays
# ----------------------------------------------------------------------


async def test_current_offers_on_sunday(hass: HomeAssistant, manager: Any, freezer) -> None:
    """On Sunday the offers starting Monday count as this week's (like the leaflets)."""
    manager.save_branch({"store": "Lidl", "postcode": "80331"})
    await _call(
        hass,
        "add_offer",
        product="Hackfleisch",
        store="Lidl",
        price=3.49,
        valid_from="2026-11-09",
        valid_to="2026-11-14",
    )
    assert not any(o["title"] == "Hackfleisch" for o in manager.offers_view("current"))
    assert store_offers_view(manager, when="current")["total"] == 0
    freezer.move_to(datetime.fromisoformat("2026-11-08T10:00:00+01:00"))  # Sunday
    current = manager.offers_view("current")
    assert any(o["title"] == "Hackfleisch" and o["current"] for o in current)
    assert not any(o["title"] == "Hackfleisch" for o in manager.offers_view("upcoming"))
    view = store_offers_view(manager, when="current")
    assert [(o["title"], o["current"]) for o in view["offers"]] == [("Hackfleisch", True)]
    assert store_offers_view(manager, when="upcoming")["total"] == 0
    assert view["stores"][0]["count_current"] == 1


def test_panel_uses_the_new_calls() -> None:
    """The panel's auto plan rows and the occasion editor use the new calls."""
    from pathlib import Path

    panel = (
        Path(__file__).parent.parent
        / "custom_components"
        / DOMAIN
        / "frontend"
        / "essensplaner-panel.js"
    ).read_text(encoding="utf-8")
    for needle in (
        '"replan_meal"',
        "🔄",
        "Neu vorschlagen",
        "✏️",
        "occasion_products",
        "update_items",
        "servings_ai",
        "Woche ≈",
    ):
        assert needle in panel, needle
