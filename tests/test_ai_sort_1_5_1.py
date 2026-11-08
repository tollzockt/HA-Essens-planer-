"""1.5.1: AI sorting of articles and recipes (ai_sort.py), unknown articles kept unsorted,
the user's own sorting, the weekly check, the leaflet allowance and the Sunday leaflets.

The AI is always faked (a registered ai_task.generate_data that answers from the data of
the prompt); all products, brands, recipes and stores are made up."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import json
from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.essensplaner import ai, ai_sort, catalog
from custom_components.essensplaner.catalog import CatalogClient, classify_offer
from custom_components.essensplaner.const import DOMAIN
from custom_components.essensplaner.products import (
    classify_product,
    ingest_offer,
    is_unsorted,
    product_counts,
    products_view,
    set_favorite,
)

from .test_ai_1_5 import TASK, _fake_task
from .test_leaflets_1_5 import _leaflet_calls, _mock_marktguru, _refresh, _user
from .test_products_1_5 import _offer

NOW = datetime.fromisoformat("2026-11-04T10:00:00+01:00")  # Wednesday


def _data(call: dict[str, Any]) -> dict[str, Any]:
    """The JSON data of a prompt."""
    text = call["instructions"].split("Daten (JSON):\n", 1)[1]
    return json.loads(text.rsplit("\n\n", 1)[0])


def _answer_all(**fields: Any):
    """An AI that answers every product (or recipe) of the data with the same fields."""

    async def answer(call: ServiceCall) -> dict[str, Any]:
        data = _data(dict(call.data))
        if "products" in data:
            items = [{"id": p["id"], **fields} for p in data["products"]]
            return {"data": {"products": items}}
        return {"data": {"recipes": [{"id": r["id"], **fields} for r in data["recipes"]]}}

    return answer


async def _with_ai(hass: HomeAssistant, entry: MockConfigEntry, answer: Any, **options: Any):
    """The fake AI Task and the options (reload); returns (calls, manager)."""
    calls = _fake_task(hass, answer)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "ai_entity": TASK, **options}
    )
    await hass.async_block_till_done()
    return calls, entry.runtime_data


def _unknown(manager: Any, oid: str, name: str, **kw: Any) -> dict[str, Any]:
    kw.setdefault("keys", ())
    kw.setdefault("kind", "unknown")
    product = ingest_offer(manager, _offer(oid, name, 1.99, **kw), kw.pop("day", None))
    assert product is not None
    return product


@pytest.fixture
async def bare(hass: HomeAssistant, freezer) -> MockConfigEntry:
    """An entry without the bundled recipes (Wednesday 2026-11-04, 10:00)."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(NOW)
    assert await async_setup_component(hass, "homeassistant", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"import_starter_recipes": False},
        options={"show_panel": False, "register_intents": False},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


# ----------------------------------------------------------------------
# Unknown articles are kept (unsorted)
# ----------------------------------------------------------------------


async def test_unknown_kind_is_stored_unsorted(hass: HomeAssistant, bare: MockConfigEntry) -> None:
    """An offer the rules cannot classify is stored as "unsorted" (no check); non-food
    never; a product the rules know is checked by them; drinks by their pack."""
    manager = bare.runtime_data
    classic = ingest_offer(manager, _offer("mg_1", "Classic", 1.49, kind=None, keys=()))
    assert classic is not None and classic["kind"] == "unknown" and is_unsorted(classic)
    assert "checked" not in classic
    shirt = _offer("mg_2", "Damen-Funktionsshirt", 9.99, kind=None, keys=())
    assert ingest_offer(manager, shirt) is None
    butter = ingest_offer(manager, _offer("mg_3", "Bergland Butter", 1.79, kind=None))
    assert butter["checked"] == {"by": "rule", "at": "2026-11-04"}
    wine = ingest_offer(
        manager,
        _offer("mg_4", "Toscana Rosso", 3.99, kind=None, keys=(), description="IGT 0,75 l"),
    )
    assert wine["kind"] == "drinks" and not is_unsorted(wine)
    assert product_counts(manager)["unsorted"] == 1
    view = products_view(manager, only="unsorted")
    assert view["total"] == 1
    card = view["products"][0]
    assert card["id"] == classic["id"] and card["unsorted"] and card["checked"] is None
    assert products_view(manager, query="butter")["products"][0]["checked"] == "rule"


def test_drink_pack_rule() -> None:
    """Only unknown products become drinks by their pack (alcohol, deposit, crate, a
    bottle ≤ 5 l) – no soup, no bin."""
    assert classify_offer("Claret Bordeaux", "0,75 Liter", "netto-marken-discount") == "drinks"
    assert classify_offer("Pils", "je 20 x 0,5-l-Fl.-Kasten", "rewe") == "drinks"
    assert classify_offer("Holla die Waldfee", "15% Vol. je 0,7-l-Fl", "rewe") == "drinks"
    assert classify_offer("Suppenliebe Suppe", "versch. Sorten 0,5 l - 1 l", "rewe") == "unknown"
    assert classify_offer("Mülleimer", "30 l", "rewe") == "unknown"
    assert classify_offer("Kräuter-Shampoo", "0,5 l", "rewe") == "drugstore"


# ----------------------------------------------------------------------
# Articles: batches, privacy, validation
# ----------------------------------------------------------------------


async def test_batches_order_and_privacy(
    hass: HomeAssistant, bare: MockConfigEntry, monkeypatch
) -> None:
    """Unsorted products first, ≤ BATCH_SIZE per request, ≤ MAX_REQUESTS per run; the AI
    gets name, brand, pack and the rules' category / kind / keys plus the known keys –
    no prices, chains, branches or postcodes."""
    monkeypatch.setattr(ai_sort, "BATCH_SIZE", 10)
    monkeypatch.setattr(ai_sort, "MAX_REQUESTS", 2)
    calls, manager = await _with_ai(
        hass, bare, _answer_all(category="Backen & Süßes", kind="food", keys=[], confidence=0.9)
    )
    manager.save_branch({"store": "Lidl", "street": "Lindenweg 1", "postcode": "12345"})
    for n in range(14):
        _unknown(manager, f"mg_u{n}", f"Knusperding {n}", brand="Sonnenhof")
    for n in range(10):
        ingest_offer(manager, _offer(f"mg_b{n}", f"Bergland Butter {n}", 1.79 + n / 100))
    result = await ai_sort.async_sort(hass, manager, "products")
    assert len(calls) == 2
    first, second = (_data(c) for c in calls)
    assert sorted(first) == ["known_keys", "products"]
    assert len(first["products"]) == 10 and len(second["products"]) == 10
    names = [p["name"] for p in first["products"]]
    assert all(n.startswith("Knusperding") for n in names)  # unsorted first
    assert {p["name"][:6] for p in second["products"]} == {"Knuspe", "Bergla"}
    for item in first["products"] + second["products"]:
        assert set(item) <= {"id", "name", "brand", "pack", "category", "kind", "keys"}
    assert "butter" in second["known_keys"]
    prompt = calls[1]["instructions"]
    for secret in ("1,79", "1.79", "Lidl", "lidl", "12345", "Lindenweg", "cdn.example.org"):
        assert secret not in prompt, secret
    assert prompt.endswith(ai.NO_TOOLS)
    assert result["ok"] and result["products"]["requests"] == 2
    assert result["checked"] == 20 and result["products"]["remaining"] == 4
    assert result["status"]["products"]["result"]["remaining"] == 4
    # the button continues with the rest
    await ai_sort.async_sort(hass, manager, "products")
    assert len(calls) == 3 and len(_data(calls[2])["products"]) == 4
    assert product_counts(manager)["unsorted"] == 0 and product_counts(manager)["ai_checked"] == 24


async def test_strict_validation(hass: HomeAssistant, bare: MockConfigEntry) -> None:
    """Only ids that were sent, aisles of CATEGORY_ORDER, the five kinds (consistent with
    the aisle) and keys that were sent count; low confidence keeps the rules."""
    answers = {
        "Bergland Butter Classic": {
            "category": "Milchprodukte & Eier",
            "kind": "food",
            "keys": ["butter", "goldbarren"],
            "confidence": 0.95,
        },
        "Musterfix Schuhcreme": {"category": "Schuhe", "kind": "household", "confidence": 1},
        "Sonnenhof Klare Sache": {
            "category": "Drogerie & Körperpflege",
            "kind": "food",
            "confidence": 0.9,
        },
        "Sonnenhof Dies und Das": {"category": "Sonstiges", "kind": "food", "confidence": 0.2},
        "Bergland Duschzauber": {"category": "Sonstiges", "kind": "drugstore", "confidence": 90},
        "Sonnenhof Wundertüte": {"category": "Backen & Süßes", "kind": "toys", "confidence": 1},
    }

    async def answer(call: ServiceCall) -> dict[str, Any]:
        data = _data(dict(call.data))
        items = [{"id": p["id"], **answers[p["name"]]} for p in data["products"]]
        items.append({"id": "p99", "category": "Getränke", "kind": "drinks"})  # not sent
        items.append({**items[0], "category": "Getränke", "kind": "drinks"})  # twice
        return {"data": json.dumps({"products": items})}

    calls, manager = await _with_ai(hass, bare, answer)
    products = {name: _unknown(manager, f"mg_{n}", name) for n, name in enumerate(answers)}
    result = await ai_sort.async_sort(hass, manager, "products")
    sent = _data(calls[0])
    assert "butter" in sent["known_keys"] and "goldbarren" not in sent["known_keys"]
    store = manager.products
    butter = store.get(products["Bergland Butter Classic"]["id"])
    assert (butter["category"], butter["kind"], butter["keys"]) == (
        "Milchprodukte & Eier",
        "food",
        ["butter"],
    )
    assert butter["checked"]["by"] == "ai"
    assert butter["ai_fix"]["before"] == {
        "category": "Milchprodukte & Eier",  # the rules' aisle of its name
        "kind": "unknown",
        "keys": [],
    }
    assert butter["ai_fix"]["confidence"] == 0.95
    assert store.by_key("butter") == [butter]
    shower = store.get(products["Bergland Duschzauber"]["id"])
    # a drugstore product is in its aisle; 90 means 90 %
    assert (shower["category"], shower["kind"]) == ("Drogerie & Körperpflege", "drugstore")
    for name in (
        "Musterfix Schuhcreme",
        "Sonnenhof Klare Sache",
        "Sonnenhof Dies und Das",
        "Sonnenhof Wundertüte",
    ):
        product = store.get(products[name]["id"])
        assert is_unsorted(product) and product["kind"] == "unknown", name
        assert product["ai_seen"]  # answered: the weekly check does not send it again
    assert (result["checked"], result["changed"], result["skipped"]) == (2, 2, 4)
    # an answer without JSON: the rules stay, the reason is reported
    _fake_task(hass, {"data": "Das weiß ich nicht."})
    _unknown(manager, "mg_new", "Sonnenhof Neuheit")
    result = await ai_sort.async_sort(hass, manager, "products")
    assert not result["ok"] and result["products"]["code"] == "ai_invalid"
    assert result["errors"] == [
        f"Die KI {TASK} hat keine verwertbare Antwort (JSON) geliefert – bitte erneut versuchen."
    ]


async def test_user_choice_wins(hass: HomeAssistant, bare: MockConfigEntry) -> None:
    """What the user sorted is never sent to the AI and no later offer changes it; keys
    the user took away do not come back."""
    calls, manager = await _with_ai(
        hass, bare, _answer_all(category="Sonstiges", kind="nonfood", confidence=1)
    )
    store = manager.products
    juice = _unknown(manager, "mg_1", "Sonnenhof Morgengold")
    butter = ingest_offer(manager, _offer("mg_2", "Bergland Butterkekse", 1.29))
    assert butter["keys"] == ["butter"]
    classify_product(manager, juice["id"], category="Getränke", kind="drinks", keys=["Apfelsaft"])
    classify_product(manager, butter["id"], category="Backen & Süßes", keys=[])
    juice, butter = store.get(juice["id"]), store.get(butter["id"])
    assert juice["checked"]["by"] == "user" and juice["keys"] == ["apfelsaft"]
    assert (butter["category"], butter["keys"], butter["keys_off"]) == (
        "Backen & Süßes",
        [],
        ["butter"],
    )
    result = await ai_sort.async_sort(hass, manager, "products")
    assert calls == [] and result["checked"] == 0  # nothing left for the AI
    # the next week's offers: kind, aisle and keys stay
    ingest_offer(manager, _offer("mg_3", "Morgengold", 1.99, brand="Sonnenhof", kind="food"))
    ingest_offer(manager, _offer("mg_4", "Bergland Butterkekse", 1.19))
    juice, butter = store.get(juice["id"]), store.get(butter["id"])
    assert (juice["kind"], juice["category"], juice["keys"]) == (
        "drinks",
        "Getränke",
        ["apfelsaft"],
    )
    assert (butter["category"], butter["keys"]) == ("Backen & Süßes", [])
    assert butter["offer"]["id"] == "mg_4"


async def test_nonfood_removed_unless_protected(hass: HomeAssistant, bare: MockConfigEntry) -> None:
    """Non-food goes (and is not stored again); a ⭐ product stays (sorted as non-food);
    an uncertain answer only sets the kind."""
    confidence = {"Lichterbild Stern": 0.9, "Lichterbild Mond": 0.9, "Gartenzwerg Paul": 0.6}

    async def answer(call: ServiceCall) -> dict[str, Any]:
        items = [
            {
                "id": p["id"],
                "category": "Sonstiges",
                "kind": "nonfood",
                "confidence": confidence[p["name"]],
            }
            for p in _data(dict(call.data))["products"]
        ]
        return {"data": {"products": items}}

    _, manager = await _with_ai(hass, bare, answer)
    store = manager.products
    star = _unknown(manager, "mg_1", "Lichterbild Stern")
    moon = _unknown(manager, "mg_2", "Lichterbild Mond")
    gnome = _unknown(manager, "mg_3", "Gartenzwerg Paul")
    set_favorite(manager, moon["id"], "lichterbild")
    result = await ai_sort.async_sort(hass, manager, "products")
    assert result["removed"] == 1 and result["checked"] == 3
    assert store.get(star["id"]) is None
    assert store.get(moon["id"])["kind"] == "nonfood"  # protected
    assert store.get(gnome["id"])["kind"] == "nonfood"
    # the next catalog refresh does not store it again
    assert ingest_offer(manager, _offer("mg_9", "Lichterbild Stern", 2.49, kind="unknown")) is None
    assert products_view(manager, kind="food")["total"] == 0


# ----------------------------------------------------------------------
# Recipes
# ----------------------------------------------------------------------


async def test_recipes_sorted(hass: HomeAssistant, bare: MockConfigEntry) -> None:
    """Recipes of the rules (never the user's) are sent with name, tags and ingredient
    names only; the kind is set by the AI, only allowed tags are added (vegetarisch only
    without meat), low confidence keeps the rules."""
    answers = {
        "Kräuterquark-Dip": {"kind": "snack", "tags": ["Party", "Raketen"], "confidence": 0.9},
        "Lasagne della Casa": {"kind": "meal", "tags": "vegetarisch, Winter", "confidence": 1},
        "Schoko-Muffins": {"kind": "dessert", "tags": ["Kinder"], "confidence": 0.3},
    }

    async def answer(call: ServiceCall) -> dict[str, Any]:
        data = _data(dict(call.data))
        return {
            "data": {"recipes": [{"id": r["id"], **answers[r["name"]]} for r in data["recipes"]]}
        }

    calls, manager = await _with_ai(hass, bare, answer)
    dip = manager.add_recipe(
        {"name": "Kräuterquark-Dip", "ingredients": ["250 g Quark", "1 Bund Schnittlauch"]}
    )
    lasagne = manager.add_recipe(
        {
            "name": "Lasagne della Casa",
            "tags": ["Pasta"],
            "ingredients": ["500 g Rinderhackfleisch", "12 Lasagneplatten"],
            "notes": "Geheimrezept von Oma",
            "source_url": "https://example.org/lasagne",
        }
    )
    muffins = manager.add_recipe({"name": "Schoko-Muffins", "ingredients": ["200 g Mehl"]})
    punch = manager.add_recipe({"name": "Winterpunsch", "kind": "drink"})  # the user's
    assert punch["kind_source"] == "user" and dip["kind"] == "component"
    result = await ai_sort.async_sort(hass, manager, "recipes")
    sent = _data(calls[0])["recipes"]
    assert sorted(r["name"] for r in sent) == sorted(answers)
    for item in sent:
        assert set(item) == {"id", "name", "tags", "ingredients", "kind"}
    assert "Geheimrezept" not in calls[0]["instructions"]
    assert "example.org" not in calls[0]["instructions"]
    lasagne_sent = next(r for r in sent if r["name"] == "Lasagne della Casa")
    assert lasagne_sent["ingredients"] == ["Rinderhackfleisch", "Lasagneplatten"]
    recipes = manager.recipes
    assert (recipes[dip["id"]]["kind"], recipes[dip["id"]]["kind_source"]) == ("snack", "ai")
    assert recipes[dip["id"]]["tags"] == ["Party"]
    assert recipes[dip["id"]]["ai_sorted"]["before"] == "component"
    assert recipes[lasagne["id"]]["kind_source"] == "ai"
    assert recipes[lasagne["id"]]["tags"] == ["Pasta", "Winter"]  # no "vegetarisch"
    assert recipes[muffins["id"]]["kind_source"] == "rule"  # too uncertain
    assert recipes[punch["id"]]["kind"] == "drink"
    assert (result["checked"], result["changed"], result["skipped"]) == (2, 2, 1)
    # the weekly check leaves out what the AI answered; the button asks again
    assert [r["id"] for r in ai_sort.recipe_candidates(manager, auto=True)] == []
    assert [r["id"] for r in ai_sort.recipe_candidates(manager)] == [muffins["id"]]
    # the user's choice later: the rules and the AI keep out
    manager.update_recipe(dip["id"], {"kind": "Beilage"})
    assert recipes[dip["id"]]["kind_source"] == "user"
    status = ai_sort.sort_status(manager)
    assert status["recipes"]["pending"] == 1 and status["recipes"]["result"]["changed"] == 2


# ----------------------------------------------------------------------
# Without AI, unavailable, feature off
# ----------------------------------------------------------------------


async def test_without_or_failing_ai(hass: HomeAssistant, bare: MockConfigEntry) -> None:
    """Without an AI entity, with the feature off or an unreachable AI nothing changes and
    the summary says why (German); the weekly check sends nothing without an AI."""
    manager = bare.runtime_data
    _unknown(manager, "mg_1", "Sonnenhof Rätsel")
    result = await ai_sort.async_sort(hass, manager, "products")
    assert not result["ok"] and result["products"]["code"] == "ai_not_configured"
    assert result["errors"] and "KI" in result["errors"][0]
    assert await ai_sort.async_weekly_check(hass, manager) is None
    calls, manager = await _with_ai(
        hass, bare, _answer_all(category="Sonstiges", kind="food"), ai_features=["drinks"]
    )
    result = await ai_sort.async_sort(hass, manager, "all")
    assert result["targets"] == ["products"] and result["products"]["code"] == "ai_feature_off"
    calls, manager = await _with_ai(
        hass, bare, _answer_all(category="Sonstiges", kind="food"), ai_features=["products"]
    )
    unknown = _unknown(manager, "mg_2", "Sonnenhof Rätsel")
    hass.states.async_set(TASK, "unavailable")
    result = await ai_sort.async_sort(hass, manager, "products")
    assert result["products"]["code"] == "ai_unavailable" and calls == []
    assert is_unsorted(manager.products.get(unknown["id"]))
    status = ai.ai_status(hass, manager)["sort"]["products"]
    assert status["last_ok"] is False and status["result"]["code"] == "ai_unavailable"


# ----------------------------------------------------------------------
# The weekly check
# ----------------------------------------------------------------------


async def test_weekly_check_only_new(hass: HomeAssistant, bare: MockConfigEntry, freezer) -> None:
    """Sunday 03:xx: the unsorted products and those first seen since the last check (the
    first time: the last 7 days) – older ones the rules sorted stay; Monday nothing; a
    failed check is tried again the next night."""
    calls, manager = await _with_ai(
        hass, bare, _answer_all(category="Backen & Süßes", kind="food", confidence=0.9)
    )
    old = ingest_offer(manager, _offer("mg_old", "Bergland Butter", 1.79), date(2026, 10, 1))
    new = ingest_offer(manager, _offer("mg_new", "Bergland Sahne", 1.19, keys=("sahne",)))
    unknown = _unknown(manager, "mg_u", "Sonnenhof Knusperzeug", day=date(2026, 10, 1))
    minute = ai_sort.weekly_minute(bare.entry_id)
    sunday = datetime(2026, 11, 8, 3, minute, tzinfo=dt_util.get_default_time_zone())
    assert ai_sort.next_weekly_run(manager) == sunday
    assert ai_sort.sort_status(manager)["next_run"] == sunday.isoformat()
    freezer.move_to(sunday)
    async_fire_time_changed(hass, sunday)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(calls) == 1  # no recipes: nothing sent for them
    sent = sorted(p["name"] for p in _data(calls[0])["products"])
    assert sent == ["Bergland Sahne", "Sonnenhof Knusperzeug"]
    store = manager.products
    assert store.get(old["id"])["checked"]["by"] == "rule"
    assert store.get(new["id"])["checked"]["by"] == "ai"
    assert store.get(unknown["id"])["checked"]["by"] == "ai"
    state = manager.ai_sort_state["products"]
    assert state["auto_ok"] is True and state["last_auto"] and state["since"]
    # Monday: nothing
    monday = sunday + timedelta(days=1)
    freezer.move_to(monday)
    async_fire_time_changed(hass, monday)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(calls) == 1
    # the next Sunday: only what is new since then; the AI is unreachable
    quark = _offer(
        "mg_next",
        "Bergland Quark",
        0.99,
        keys=("quark",),
        valid_from="2026-11-09",
        valid_to="2026-11-21",
    )
    assert ingest_offer(manager, quark) is not None
    hass.states.async_set(TASK, "unavailable")
    sunday2 = sunday + timedelta(days=7)
    freezer.move_to(sunday2)
    async_fire_time_changed(hass, sunday2)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(calls) == 1
    assert manager.ai_sort_state["products"]["auto_ok"] is False
    # ... tried again the next night
    hass.states.async_set(TASK, "unknown")
    monday2 = sunday2 + timedelta(days=1)
    freezer.move_to(monday2)
    async_fire_time_changed(hass, monday2)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert [p["name"] for p in _data(calls[-1])["products"]] == ["Bergland Quark"]
    assert manager.ai_sort_state["products"]["auto_ok"] is True


# ----------------------------------------------------------------------
# Websockets, service, settings
# ----------------------------------------------------------------------


async def test_websockets_and_service(
    hass: HomeAssistant, bare: MockConfigEntry, hass_ws_client
) -> None:
    """essensplaner/ai_sort, essensplaner/product_classify and the service sort_with_ai;
    the status is in ai_status and the panel data."""
    _, manager = await _with_ai(
        hass, bare, _answer_all(category="Backen & Süßes", kind="food", confidence=0.8)
    )
    first = _unknown(manager, "mg_1", "Sonnenhof Knusperzeug")
    second = _unknown(manager, "mg_2", "Sonnenhof Wunderding")
    client = await hass_ws_client(hass)
    await client.send_json(
        {
            "id": 1,
            "type": f"{DOMAIN}/product_classify",
            "product_id": second["id"],
            "category": "Getränke",
            "kind": "drinks",
            "keys": ["Apfelsaft"],
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert msg["result"]["product"]["checked"] == "user"
    await client.send_json({"id": 2, "type": f"{DOMAIN}/ai_sort", "target": "products"})
    msg = await client.receive_json()
    assert msg["success"], msg
    assert msg["result"]["checked"] == 1 and msg["result"]["status"]["products"]["last_ok"]
    assert manager.products.get(first["id"])["checked"]["by"] == "ai"
    await client.send_json({"id": 3, "type": f"{DOMAIN}/products", "only": "unsorted"})
    msg = await client.receive_json()
    assert msg["success"] and msg["result"]["total"] == 0
    await client.send_json(
        {"id": 4, "type": f"{DOMAIN}/product_classify", "product_id": "lidl:nix", "kind": "food"}
    )
    msg = await client.receive_json()
    assert not msg["success"] and msg["error"]["code"] == "product_not_found"
    result = await hass.services.async_call(
        DOMAIN, "sort_with_ai", {"target": "recipes"}, blocking=True, return_response=True
    )
    assert result["targets"] == ["recipes"] and result["checked"] == 0 and result["ok"]
    assert "status" not in result
    panel = manager.export()["ai"]["sort"]
    assert panel["products"]["enabled"] and panel["products"]["result"]["checked"] == 1
    assert panel["running"] is None


async def test_features_migrated_once(hass: HomeAssistant, freezer) -> None:
    """A saved AI selection of 1.5 gets the sorting of articles and recipes once; a later
    choice of the user stays."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(NOW)
    assert await async_setup_component(hass, "homeassistant", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"import_starter_recipes": False},
        options={"show_panel": False, "ai_features": ["drinks", "season"]},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.options["ai_features"] == ["drinks", "season", "products", "recipes"]
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "ai_features": ["drinks"]}
    )
    await hass.async_block_till_done()
    assert entry.options["ai_features"] == ["drinks"]
    assert entry.runtime_data.ai_sort_state["features_151"] is True


# ----------------------------------------------------------------------
# marktguru leaflets (1.5.1 fixes)
# ----------------------------------------------------------------------


async def test_leaflets_have_their_own_allowance(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch,
) -> None:
    """Many branches use up the offers' requests: the leaflet lists are still asked in the
    same run (their own allowance)."""
    monkeypatch.setattr(catalog, "MAX_REQUESTS", 4)
    _mock_marktguru(aioclient_mock)
    await _user(hass, config_entry, freezer)
    result = await _refresh(hass)
    assert any("Anfragelimit" in e for e in result["errors"])
    assert len(_leaflet_calls(aioclient_mock)) >= 3


async def test_client_allowance(hass: HomeAssistant) -> None:
    """allow() raises the limit, never lowers it."""
    client = CatalogClient(hass, delay=0)
    client.requests = 30
    client.allow(13)
    assert client.limit == 43
    client.allow(1)
    assert client.limit == 43
