"""Branches (Filialen), offer postcodes and the shopping list per store (1.3)."""

from __future__ import annotations

from datetime import datetime

from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import intent, llm
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.essensplaner.const import CONF_STORES, CONF_ZIP, DOMAIN, STORAGE_KEY


async def _call(hass: HomeAssistant, service: str, **data):
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


async def _setup(
    hass: HomeAssistant, entry: MockConfigEntry, freezer, **options
) -> MockConfigEntry:
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(datetime.fromisoformat("2026-11-04T10:00:00+01:00"))
    assert await async_setup_component(hass, "homeassistant", {})
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _intent(hass: HomeAssistant, intent_type: str, **slots) -> intent.IntentResponse:
    return await intent.async_handle(
        hass,
        "test",
        intent_type,
        {key: {"value": value} for key, value in slots.items()},
        language="de",
    )


async def _speech(hass: HomeAssistant, intent_type: str, **slots) -> str:
    return (await _intent(hass, intent_type, **slots)).speech["plain"]["speech"]


def _error_key(manager, method, *args) -> str:
    with pytest.raises(ServiceValidationError) as err:
        getattr(manager, method)(*args)
    return err.value.translation_key


async def test_branch_crud(hass: HomeAssistant, setup_integration) -> None:
    """Manual branches: ids, labels, Aldi guess, duplicates, OSM ids, errors."""
    manager = setup_integration.runtime_data
    assert manager.branches_export() == {"branches": [], "main_branch": None, "offer_targets": []}

    lidl = manager.save_branch(
        {"store": "Lidl", "street": "Hauptstraße 5", "postcode": "80331", "city": "München"}
    )
    assert lidl["id"].startswith("man_")
    assert (lidl["retailer"], lidl["retailer_name"], lidl["name"]) == ("lidl", "Lidl", "Lidl")
    assert lidl["label"] == "Lidl Hauptstraße 5"
    assert (lidl["source"], lidl["selected"], lidl["priority"]) == ("manual", True, 0)
    assert lidl["retailer_guessed"] is False
    assert lidl["added"] and lidl["updated"]
    # the only selected branch becomes the main branch
    assert lidl["main"] is True
    assert manager.main_branch == lidl["id"]

    aldi = manager.save_branch({"store": "Aldi", "postcode": "20095", "city": "Hamburg"})
    assert aldi["id"] != lidl["id"]  # unique although the clock is frozen
    assert (aldi["retailer"], aldi["retailer_guessed"]) == ("aldi-nord", True)
    assert aldi["label"] == "Aldi Nord Hamburg"
    assert (aldi["priority"], aldi["main"]) == (1, False)
    assert manager.main_branch == lidl["id"]

    # a corrected postcode re-guesses the Aldi variant, the automatic label follows
    aldi = manager.save_branch({"id": aldi["id"], "postcode": "80333"})
    assert (aldi["retailer"], aldi["label"]) == ("aldi-sued", "Aldi Süd Hamburg")
    # own labels are kept, an empty label means the automatic one again
    aldi = manager.save_branch(
        {"id": aldi["id"], "label": "Aldi Arbeit", "street": "Bahnhofstraße 1"}
    )
    assert aldi["label"] == "Aldi Arbeit"
    aldi = manager.save_branch({"id": aldi["id"], "city": "München"})
    assert aldi["label"] == "Aldi Arbeit"
    aldi = manager.save_branch({"id": aldi["id"], "label": ""})
    assert aldi["label"] == "Aldi Süd Bahnhofstraße 1"
    # an explicit store is not a guess
    assert manager.save_branch({"id": aldi["id"], "store": "Aldi Süd"})["retailer_guessed"] is False

    # same retailer and address: updated instead of a second branch
    again = manager.save_branch(
        {
            "store": "Lidl",
            "street": "Hauptstraße 5",
            "postcode": "80331",
            "city": "München",
            "rewe_market_id": "",
        }
    )
    assert again["id"] == lidl["id"]
    assert len(manager.branches) == 2

    # OpenStreetMap results keep their id
    osm = manager.save_branch(
        {
            "id": "osm_node_123",
            "store": "REWE",
            "name": "REWE Markt Müller",
            "lat": 48.1371234567,
            "lon": "11.5754",
            "source": "osm",
            "near": {"zone.home": 420.4, "zone.arbeit": "x"},
            "route": {"zone.arbeit": 95},
            "selected": False,
        }
    )
    assert (osm["id"], osm["source"], osm["retailer"]) == ("osm_node_123", "osm", "rewe")
    assert (osm["lat"], osm["lon"]) == (48.137123, 11.5754)
    assert osm["near"] == {"zone.home": 420}
    assert osm["route"] == {"zone.arbeit": 95}
    assert osm["selected"] is False
    assert osm["label"] == "REWE"

    for data, key in [
        ({}, "store_required"),
        ({"street": "Irgendwo 1"}, "store_required"),
        ({"store": "Metro"}, "unknown_store"),
        ({"store": "Lidl", "postcode": "8033"}, "invalid_postcode"),
        ({"id": "man_missing", "store": "Lidl"}, "branch_not_found"),
        ({"id": "anything", "store": "Lidl"}, "branch_not_found"),
    ]:
        assert _error_key(manager, "save_branch", data) == key
    assert len(manager.branches) == 3
    # stored sorted by priority
    assert [b["id"] for b in manager.branches] == [lidl["id"], aldi["id"], "osm_node_123"]


async def test_main_branch_and_order(hass: HomeAssistant, setup_integration) -> None:
    """Main branch rules, priorities, active retailers and price context."""
    manager = setup_integration.runtime_data
    manager.set_store_price("Aldi Süd", "Butter", 1.49, 250, "g")
    recipe = manager.add_recipe(
        {"name": "Butterbrot", "servings": 1, "ingredients": ["250 g Butter"]}
    )
    assert manager.recipe_cost(recipe)["total"] == 1.99  # no branch: like 1.2

    aldi = manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})
    assert manager.main_branch == aldi["id"]
    assert manager.recipe_cost(recipe)["total"] == 1.49  # main branch prices

    lidl = manager.save_branch({"store": "Lidl", "postcode": "80333"})
    rewe = manager.save_branch({"store": "REWE", "postcode": "85748", "main": True})
    assert manager.main_branch == rewe["id"]
    assert manager.recipe_cost(recipe)["total"] == 1.99  # REWE has no own butter price
    assert [b["id"] for b in manager.selected_branches()] == [rewe["id"], aldi["id"], lidl["id"]]
    assert manager.active_retailers() == ["rewe", "aldi-sued", "lidl"]
    assert (manager.main_retailer, manager.main_postcode) == ("rewe", "85748")

    view = manager.reorder_branches([lidl["id"], "unknown", aldi["id"], lidl["id"]])
    assert [b["id"] for b in view] == [lidl["id"], aldi["id"], rewe["id"]]
    assert [b["priority"] for b in view] == [0, 1, 2]
    assert manager.active_retailers() == ["rewe", "lidl", "aldi-sued"]  # main first

    # deselecting the main branch: no main branch (two selected branches are left)
    manager.save_branch({"id": rewe["id"], "selected": False})
    assert manager.main_branch is None
    assert manager.active_retailers() == ["lidl", "aldi-sued"]
    assert manager.recipe_cost(recipe)["total"] == 1.99

    # by store name ("Aldi" = the selected Aldi Süd), selecting it again by id
    assert manager.set_main_branch("Aldi")["id"] == aldi["id"]
    assert manager.recipe_cost(recipe)["total"] == 1.49
    assert manager.set_main_branch(rewe["id"])["main"] is True
    assert manager.get_branch(rewe["id"])["selected"] is True
    assert manager.set_main_branch(None) is None
    assert manager.main_branch is None
    assert _error_key(manager, "set_main_branch", "Penny") == "branch_not_found"

    # main=False is respected even for the only selected branch
    manager.save_branch({"id": aldi["id"], "selected": False})
    manager.save_branch({"id": rewe["id"], "selected": False, "main": False})
    assert manager.main_branch is None
    manager.save_branch({"id": lidl["id"], "main": False})
    assert manager.main_branch is None
    manager.save_branch({"id": lidl["id"], "city": "München"})
    assert manager.main_branch == lidl["id"]  # the only selected branch

    # removing the main branch: the only remaining selected branch takes over
    manager.save_branch({"id": aldi["id"], "selected": True})
    manager.set_main_branch(aldi["id"])
    removed = manager.remove_branch(aldi["id"])
    assert (removed["id"], removed["main"]) == (aldi["id"], True)
    assert manager.main_branch == lidl["id"]
    assert manager.get_branch(aldi["id"]) is None


async def test_resolve_branch(hass: HomeAssistant, setup_integration) -> None:
    """Ids, labels, 'Hauptladen', store names and places."""
    manager = setup_integration.runtime_data
    lidl = manager.save_branch(
        {"store": "Lidl", "street": "Hauptstraße 5", "postcode": "80331", "city": "München"}
    )
    work = manager.save_branch(
        {
            "store": "Lidl",
            "street": "Bahnhofplatz 2",
            "postcode": "85748",
            "city": "Garching",
            "label": "Lidl Arbeit",
        }
    )
    aldi = manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})
    off = manager.save_branch({"store": "Penny", "city": "Freising", "selected": False})

    cases = {
        lidl["id"]: lidl,
        "Lidl Arbeit": work,
        "bei Lidl Arbeit": work,
        "Lidl Hauptstraße 5": lidl,
        "Hauptladen": lidl,
        "im Hauptladen": lidl,
        "main": lidl,
        "mein Laden": lidl,
        "Lidl": lidl,  # main branch / priority first
        "Lidl Garching": work,
        "lidl 85748": work,
        "Garching": work,
        "Aldi": aldi,
        "bei Aldi Süd": aldi,
        "Penny": off,  # deselected branches are found, too
    }
    for text, expected in cases.items():
        assert manager.resolve_branch(text)["id"] == expected["id"], text
    for text in ("Netto", "Nirgendwo", "", None, "bei der"):
        assert manager.resolve_branch(text) is None, text

    assert _error_key(manager, "remove_branch", "Lidl") == "branch_ambiguous"
    assert _error_key(manager, "remove_branch", "Netto") == "branch_not_found"
    assert manager.remove_branch("Lidl Arbeit")["id"] == work["id"]
    assert manager.remove_branch("Lidl")["id"] == lidl["id"]  # unambiguous now


async def test_remove_branch_clears_store_choices(hass: HomeAssistant, setup_integration) -> None:
    """Shopping items and offers pointing to a removed branch are cleaned up."""
    manager = setup_integration.runtime_data
    lidl = manager.save_branch({"store": "Lidl", "postcode": "80331"})
    work = manager.save_branch({"store": "Lidl", "postcode": "85748", "label": "Lidl Arbeit"})
    aldi = manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})
    offer = manager.add_offer("Butter", "Lidl", 0.99, "250 g")
    assert offer["branches"] == [lidl["id"], work["id"]]  # manual offer: all Lidl branches
    assert manager.add_offer("Milch", "Metro", 0.79, "1 l")["branches"] == []

    manager.shopping = [
        {
            "uid": "1",
            "summary": "Butter",
            "status": "needs_action",
            "branch_id": work["id"],
            "retailer": "lidl",
            "store_label": "Lidl Arbeit",
            "store_reason": "manual",
            "store_override": work["id"],
            "saving": 0.3,
            "alternatives": [],
        },
        {
            "uid": "2",
            "summary": "Milch",
            "status": "needs_action",
            "branch_id": aldi["id"],
            "retailer": "aldi-sued",
        },
    ]
    manager.remove_branch(work["id"])
    first, second = manager.shopping
    # the manual choice is gone, the open item is assigned again (main branch)
    assert "store_override" not in first
    assert (first["branch_id"], first["retailer"], first["store_reason"]) == (
        lidl["id"],
        "lidl",
        "main",
    )
    assert first["description"].startswith("🏪 Lidl")
    assert (second["branch_id"], second["retailer"]) == (lidl["id"], "lidl")
    assert offer["branches"] == [lidl["id"]]  # retagged

    # completed items keep no store of a removed branch
    manager.shopping.append(
        {
            "uid": "3",
            "summary": "Kaffee",
            "status": "completed",
            "branch_id": aldi["id"],
            "retailer": "aldi-sued",
            "store_label": "Aldi Süd",
        }
    )
    manager.remove_branch(aldi["id"])
    assert manager.shopping[2] == {"uid": "3", "summary": "Kaffee", "status": "completed"}


async def test_offer_targets(hass: HomeAssistant, config_entry: MockConfigEntry, freezer) -> None:
    """Postcodes for offers: 1.2 options without branches, else the branches' postcodes."""
    await _setup(hass, config_entry, freezer, **{CONF_ZIP: "10115", CONF_STORES: ["lidl", "penny"]})
    manager = config_entry.runtime_data
    assert manager.offer_targets() == [("10115", ["lidl", "penny"])]  # like 1.2
    assert manager.branch_postcodes() == []

    aldi = manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})  # main
    manager.save_branch({"store": "Lidl", "postcode": "80331"})
    rewe = manager.save_branch({"store": "REWE"})  # no postcode: the zip code option
    manager.save_branch({"store": "Penny", "postcode": "85748"})
    manager.save_branch({"store": "Edeka", "postcode": "85221"})
    kaufland = manager.save_branch({"store": "Kaufland", "postcode": "82008"})  # 5th postcode
    manager.save_branch({"store": "Netto", "postcode": "81000", "selected": False})
    assert manager.main_branch == aldi["id"]
    assert manager.offer_targets() == [
        ("80331", ["aldi-sued", "lidl", "kaufland"]),
        ("10115", ["rewe"]),
        ("85748", ["penny"]),
        ("85221", ["edeka"]),
    ]
    assert manager.branch_postcodes() == ["80331", "85748", "85221", "82008"]
    views = {b["id"]: b for b in manager.branches_view()}
    assert views[kaufland["id"]]["offer_zip"] == "80331"
    assert views[rewe["id"]]["offer_zip"] == "10115"
    assert manager.offer_targets_view()[0] == {
        "zip_code": "80331",
        "retailers": ["aldi-sued", "lidl", "kaufland"],
        "stores": ["Aldi Süd", "Lidl", "Kaufland"],
    }


async def test_offer_targets_without_zip_option(hass: HomeAssistant, setup_integration) -> None:
    """Without zip code option a branch without postcode is searched at the first postcode."""
    manager = setup_integration.runtime_data
    manager.save_branch({"store": "REWE"})
    assert manager.offer_targets() == []
    manager.save_branch({"store": "Lidl", "postcode": "80331"})
    assert manager.offer_targets() == [("80331", ["lidl", "rewe"])]


async def test_branch_services_and_websocket(
    hass: HomeAssistant, setup_integration, hass_ws_client
) -> None:
    """save_branch / get_branches / remove_branch and the websocket commands."""
    result = await _call(
        hass,
        "save_branch",
        store="Lidl",
        street="Hauptstraße 5",
        postcode="80331",
        city="München",
        lat=48.13,
        lon=11.57,
    )
    lidl = result["branch"]
    assert (lidl["retailer"], lidl["main"], lidl["label"]) == ("lidl", True, "Lidl Hauptstraße 5")
    aldi = (await _call(hass, "save_branch", store="Aldi", postcode="80331", priority=5))["branch"]
    assert (aldi["retailer"], aldi["priority"]) == ("aldi-sued", 5)

    result = await _call(hass, "get_branches")
    assert result["main_branch"] == lidl["id"]
    assert [b["id"] for b in result["branches"]] == [lidl["id"], aldi["id"]]
    assert result["offer_targets"] == [
        {"zip_code": "80331", "retailers": ["lidl", "aldi-sued"], "stores": ["Lidl", "Aldi Süd"]}
    ]
    result = await _call(hass, "save_branch", id=aldi["id"], main=True)
    assert result["branch"]["main"] is True

    with pytest.raises(ServiceValidationError):
        await _call(hass, "save_branch", store="Lidl", postcode="123")
    with pytest.raises(ServiceValidationError):
        await _call(hass, "save_branch", city="München")
    with pytest.raises(ServiceValidationError):
        await _call(hass, "remove_branch", branch="Penny")

    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/branches"})
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"]["main_branch"] == aldi["id"]
    assert msg["result"]["offer_targets"][0]["retailers"] == ["aldi-sued", "lidl"]

    await client.send_json(
        {"id": 2, "type": f"{DOMAIN}/reorder_branches", "ids": [aldi["id"], lidl["id"]]}
    )
    msg = await client.receive_json()
    assert msg["success"]
    assert [(b["id"], b["priority"]) for b in msg["result"]["branches"]] == [
        (aldi["id"], 0),
        (lidl["id"], 1),
    ]

    await client.send_json({"id": 3, "type": f"{DOMAIN}/data"})
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"]["main_branch"] == aldi["id"]
    assert [b["id"] for b in msg["result"]["branches"]] == [aldi["id"], lidl["id"]]
    assert msg["result"]["offer_targets"][0]["zip_code"] == "80331"

    result = await _call(hass, "remove_branch", branch="Aldi Süd")
    assert result["removed"]["id"] == aldi["id"]
    assert result["main_branch"] == lidl["id"]  # the only one left


async def test_branches_are_stored(hass: HomeAssistant, setup_integration, hass_storage) -> None:
    """Branches and the main branch survive a reload."""
    entry = setup_integration
    manager = entry.runtime_data
    lidl = manager.save_branch({"store": "Lidl", "postcode": "80331", "label": "Lidl Zuhause"})
    manager.save_branch({"store": "REWE", "postcode": "85748", "selected": False})
    await manager.async_save_now()
    stored = hass_storage[f"{STORAGE_KEY}.{entry.entry_id}"]["data"]
    assert stored["main_branch"] == lidl["id"]
    assert [b["retailer"] for b in stored["branches"]] == ["lidl", "rewe"]

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    reloaded = entry.runtime_data
    assert reloaded is not manager
    assert reloaded.main_branch == lidl["id"]
    assert reloaded.resolve_branch("Lidl Zuhause")["id"] == lidl["id"]
    assert reloaded.active_retailers() == ["lidl"]


# ----------------------------------------------------------------------
# Shopping list per store ("Hauptladen + Ausnahmen")
# ----------------------------------------------------------------------


def _three_stores(manager) -> tuple[dict, dict, dict]:
    """Aldi Süd (main), Lidl and REWE Arbeit at the same postcode."""
    aldi = manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})
    lidl = manager.save_branch({"store": "Lidl", "postcode": "80331"})
    rewe = manager.save_branch({"store": "REWE", "postcode": "80331", "label": "REWE Arbeit"})
    assert manager.main_branch == aldi["id"]
    return aldi, lidl, rewe


def _store_of(manager, summary: str) -> tuple[str | None, str | None]:
    item = next(i for i in manager.shopping if i["summary"] == summary)
    return item.get("retailer"), item.get("store_reason")


async def test_assign_thresholds(hass: HomeAssistant, setup_integration) -> None:
    """Real store prices move an item if >= 1 € or >= 20 % cheaper (floor 0,20 €)."""
    manager = setup_integration.runtime_data
    _three_stores(manager)
    manager.set_store_price("Lidl", "Butter", 1.79, 250, "g")  # 0,20 € / 10 % cheaper
    manager.set_store_price("Aldi Süd", "Backpulver", 0.59, 1, "Pck.")
    manager.set_store_price("Lidl", "Backpulver", 0.40, 1, "Pck.")  # 32 %, but 0,19 €
    manager.set_store_price("Aldi Süd", "Rinderfilet", 24.99, 1, "kg")
    manager.set_store_price("Lidl", "Rinderfilet", 24.09, 1, "kg")  # 0,90 € / 3,6 %
    manager.set_store_price("Aldi Süd", "Milch", 1.49, 1, "l")  # others: estimate 0,99 €
    for summary in ("250 g Butter", "Backpulver", "1 kg Rinderfilet", "1 l Milch", "Eier"):
        manager.shopping_add(summary)
    for summary in ("250 g Butter", "Backpulver", "1 kg Rinderfilet"):
        assert _store_of(manager, summary) == ("aldi-sued", "main"), summary
    # an estimate elsewhere is no reason to go there
    assert _store_of(manager, "1 l Milch") == ("aldi-sued", "main")
    milk = next(i for i in manager.shopping if i["summary"] == "1 l Milch")
    assert milk["price"] == 1.49
    assert [(a["retailer"], a["price"], a["real"]) for a in milk["alternatives"]] == [
        ("lidl", 0.99, False),
        ("rewe", 0.99, False),
    ]
    # without store specific prices an item costs the same everywhere and stays
    assert _store_of(manager, "Eier") == ("aldi-sued", "main")

    manager.set_store_price("Lidl", "Butter", 1.59, 250, "g")  # 0,40 € = 20,1 %
    manager.set_store_price("Lidl", "Backpulver", 0.39, 1, "Pck.")  # 0,20 € floor reached
    manager.set_store_price("Lidl", "Rinderfilet", 23.99, 1, "kg")  # 1,00 €
    result = manager.assign_shopping_stores()
    assert result == {"active": True, "assigned": 5}
    for summary in ("250 g Butter", "Backpulver", "1 kg Rinderfilet"):
        assert _store_of(manager, summary) == ("lidl", "cheaper"), summary
    butter = next(i for i in manager.shopping if i["summary"] == "250 g Butter")
    assert (butter["price"], butter["packs"], butter["saving"]) == (1.59, 1, 0.4)
    assert butter["store_label"] == "Lidl"
    assert butter["description"] == "🏪 Lidl · ≈ 1,59 €"
    assert butter["alternatives"][0] == {
        "branch_id": manager.main_branch,
        "retailer": "aldi-sued",
        "label": "Aldi Süd",
        "price": 1.99,
        "real": False,
    }


async def test_assign_offers_and_packages(hass: HomeAssistant, setup_integration) -> None:
    """Offers need >= 0,30 € saving; costs are compared in whole packs."""
    manager = setup_integration.runtime_data
    aldi, lidl, _ = _three_stores(manager)
    recipe = manager.add_recipe(
        {"name": "Butterkuchen", "servings": 1, "ingredients": ["300 g Butter", "200 g Mehl"]}
    )
    manager.plan_meal(manager.today(), "abendessen", recipe=recipe, servings=1)

    # 300 g: two 250-g packs (3,98 €) at Aldi, one 500-g pack at Lidl
    manager.set_store_price("Lidl", "Butter", 3.29, 500, "g")  # 0,69 € / 17 % cheaper
    result = manager.generate_shopping_list(manager.today(), 1)
    butter = next(i for i in manager.shopping if i["key"] == "butter")
    assert (butter["retailer"], butter["price"], butter["packs"]) == ("aldi-sued", 3.98, 2)
    assert butter["amounts"] == {"g": 300.0}
    assert butter["description"].startswith("🏪 Aldi Süd · Milchprodukte & Eier · ≈ 3,98 €")
    assert butter["description"].endswith("· Butterkuchen")
    assert result["stores"][0]["branch_id"] == aldi["id"]
    assert result["items"][0]["store_label"]

    manager.set_store_price("Lidl", "Butter", 2.99, 500, "g")  # 0,99 € / 24,9 % cheaper
    result = manager.generate_shopping_list(manager.today(), 1)
    butter = next(i for i in manager.shopping if i["key"] == "butter")
    assert (butter["retailer"], butter["store_reason"]) == ("lidl", "cheaper")
    assert (butter["price"], butter["packs"], butter["saving"]) == (2.99, 1, 0.99)
    assert [g["label"] for g in result["stores"]] == ["Aldi Süd", "Lidl"]
    assert result["total_price"] == round(sum(g["subtotal"] for g in result["stores"]), 2)

    # offers: 0,24 € saving is not enough, 0,30 € is
    manager.remove_store_price("Lidl", "Butter")
    offer = manager.add_offer("Butter", "Lidl", 1.75, "250 g")
    manager.shopping_add("250 g Butter")
    assert _store_of(manager, "250 g Butter") == ("aldi-sued", "main")
    item = next(i for i in manager.shopping if i["summary"] == "250 g Butter")
    assert item["alternatives"][0]["offer"]["id"] == offer["id"]
    manager.remove_offer(offer["id"])
    offer = manager.add_offer("Butter", "Lidl", 1.69, "250 g")
    manager.assign_shopping_stores()
    assert _store_of(manager, "250 g Butter") == ("lidl", "offer")
    item = next(i for i in manager.shopping if i["summary"] == "250 g Butter")
    assert (item["price"], item["saving"], item["offer"]["id"]) == (1.69, 0.3, offer["id"])
    assert item["description"] == "🏪 Lidl · ≈ 1,69 € · 🏷️ Lidl 1,69 € bis 07.11."
    assert lidl["id"] in offer["branches"]

    # an offer found for another postcode does not count for this branch
    offer["branches"] = []
    manager._invalidate_prices()
    manager.assign_shopping_stores()
    assert _store_of(manager, "250 g Butter") == ("aldi-sued", "main")


async def test_assign_override_and_preference(hass: HomeAssistant, setup_integration) -> None:
    """Manual store choice and "immer hier" win; they survive regenerating the list."""
    manager = setup_integration.runtime_data
    _aldi, lidl, rewe = _three_stores(manager)
    manager.set_store_price("Lidl", "Butter", 1.29, 250, "g")
    recipe = manager.add_recipe(
        {"name": "Butterbrot", "servings": 1, "ingredients": ["250 g Butter", "1 Brot"]}
    )
    manager.plan_meal(manager.today(), "abendessen", recipe=recipe, servings=1)
    manager.generate_shopping_list(manager.today(), 1)
    assert _store_of(manager, "250 g Butter") == ("lidl", "cheaper")

    item = manager.set_shopping_store("Butter", "REWE Arbeit")
    assert (item["store_override"], item["retailer"], item["store_reason"]) == (
        rewe["id"],
        "rewe",
        "manual",
    )
    assert (item["price"], item["saving"]) == (1.99, 0.0)
    assert item["description"].startswith("🏪 REWE Arbeit · ")
    assert [a["retailer"] for a in item["alternatives"]] == ["lidl", "aldi-sued"]
    # kept when the list is generated again
    manager.generate_shopping_list(manager.today(), 1)
    assert _store_of(manager, "250 g Butter") == ("rewe", "manual")
    # "auto" resets the choice
    item = manager.set_shopping_store("250 g Butter", "automatisch")
    assert "store_override" not in item
    assert (item["retailer"], item["store_reason"]) == ("lidl", "cheaper")

    # "immer hier": remembered per product (also for new lists), main branch by name
    item = manager.set_shopping_store("Brot", "Hauptladen", always=True)
    assert manager.store_preferences == {"brot": "aldi-sued"}
    item = manager.set_shopping_store(item["uid"], "auto")
    assert (item["retailer"], item["store_reason"]) == ("aldi-sued", "preferred")
    manager.set_shopping_store("Butter", "REWE", always=True)
    assert manager.store_preferences["butter"] == "rewe"
    # the panel's store picker sees the remembered stores
    assert manager.export()["store_preferences"] == {"brot": "aldi-sued", "butter": "rewe"}
    manager.set_shopping_store("Butter", "auto")
    manager.generate_shopping_list(manager.today(), 1)
    assert _store_of(manager, "250 g Butter") == ("rewe", "preferred")
    manager.set_shopping_store("Butter", "auto", always=True)
    assert "butter" not in manager.store_preferences

    assert _error_key(manager, "set_shopping_store", "Marmelade", "Lidl") == (
        "shopping_item_not_found"
    )
    assert _error_key(manager, "set_shopping_store", "Butter", "Penny") == "branch_not_found"
    assert lidl["id"]


async def test_trip_minimum(hass: HomeAssistant, config_entry: MockConfigEntry, freezer) -> None:
    """With store_split_trip_min an extra store must save enough in total."""
    await _setup(hass, config_entry, freezer, store_split_trip_min=1.0)
    manager = config_entry.runtime_data
    _three_stores(manager)
    manager.set_store_price("Lidl", "Butter", 1.59, 250, "g")  # saves 0,40 €
    manager.set_store_price("REWE", "Milch", 0.49, 1, "l")  # saves 0,50 € each
    manager.shopping_add("250 g Butter")
    assert _store_of(manager, "250 g Butter") == ("aldi-sued", "main")
    butter = next(i for i in manager.shopping if i["summary"] == "250 g Butter")
    assert butter["alternatives"][0]["retailer"] == "lidl"
    assert butter["price"] == 1.99
    manager.shopping_add("1 l Milch")
    assert _store_of(manager, "1 l Milch") == ("aldi-sued", "main")
    manager.shopping_add("2 l Milch")  # 1,00 € at REWE: worth the trip
    assert _store_of(manager, "2 l Milch") == ("rewe", "cheaper")
    manager.assign_shopping_stores()
    assert _store_of(manager, "1 l Milch") == ("rewe", "cheaper")  # 1,50 € in total
    assert _store_of(manager, "250 g Butter") == ("aldi-sued", "main")


async def test_main_only(hass: HomeAssistant, config_entry: MockConfigEntry, freezer) -> None:
    """Mode main_only: everything at the main branch, alternatives still shown."""
    await _setup(hass, config_entry, freezer, store_split_mode="main_only")
    manager = config_entry.runtime_data
    _three_stores(manager)
    manager.set_store_price("Lidl", "Butter", 0.99, 250, "g")
    manager.add_offer("Milch", "REWE", 0.49, "1 l")
    manager.shopping_add("250 g Butter")
    manager.shopping_add("1 l Milch")
    assert _store_of(manager, "250 g Butter") == ("aldi-sued", "main")
    assert _store_of(manager, "1 l Milch") == ("aldi-sued", "main")
    milk = next(i for i in manager.shopping if i["summary"] == "1 l Milch")
    assert milk["alternatives"][0]["retailer"] == "rewe"
    assert milk["alternatives"][0]["offer"]["price"] == 0.49
    assert manager.split_settings()["mode"] == "main_only"
    # a manual choice still works
    assert manager.set_shopping_store("Butter", "Lidl")["retailer"] == "lidl"


async def test_split_off_behaves_like_12(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer
) -> None:
    """store_split_mode off (or no main branch): no store fields, 1.2 descriptions."""
    await _setup(hass, config_entry, freezer, store_split_mode="off")
    manager = config_entry.runtime_data
    _three_stores(manager)
    manager.set_store_price("Lidl", "Butter", 0.99, 250, "g")
    recipe = manager.add_recipe(
        {"name": "Butterkuchen", "servings": 1, "ingredients": ["300 g Butter"]}
    )
    manager.plan_meal(manager.today(), "abendessen", recipe=recipe, servings=1)
    result = manager.generate_shopping_list(manager.today(), 1)
    assert result["stores"] == []
    item = result["items"][0]
    assert "branch_id" not in item
    assert item["description"] == "Milchprodukte & Eier · ≈ 3,98 € · Butterkuchen"
    stored = manager.shopping[0]
    assert not set(stored) & {"branch_id", "retailer", "store_label", "store_reason"}
    assert manager.stores_summary() == []
    overview = manager.shopping_overview("Lidl")
    assert (overview["split_active"], overview["stores"], overview["selection"]) == (
        False,
        [],
        None,
    )
    manual = manager.shopping_add("Klopapier", description="die weiche Sorte")
    assert manual["description"] == "die weiche Sorte"
    assert _error_key(manager, "set_shopping_store", "Butter", "Lidl") == "store_split_off"
    assert manager.assign_shopping_stores() == {"active": False, "assigned": 0}


async def test_without_branches_like_12(hass: HomeAssistant, setup_integration) -> None:
    """Without branches the shopping list is exactly the 1.2 list."""
    manager = setup_integration.runtime_data
    recipe = manager.add_recipe(
        {"name": "Butterkuchen", "servings": 1, "ingredients": ["300 g Butter", "2 Eier"]}
    )
    manager.plan_meal(manager.today(), "abendessen", recipe=recipe, servings=1)
    result = manager.generate_shopping_list(manager.today(), 1)
    assert [(i["summary"], i["description"], i["price"]) for i in result["items"]] == [
        ("300 g Butter", "Milchprodukte & Eier · ≈ 3,98 € · Butterkuchen", 3.98),
        ("2 Eier", "Milchprodukte & Eier · ≈ 2,49 € · Butterkuchen", 2.49),
    ]
    assert result["total_price"] == 6.47
    assert result["stores"] == []
    assert all("branch_id" not in i for i in manager.shopping)
    manual = manager.shopping_add("2 Butter")  # a count of butter = two packs
    assert (manual["price"], manual["packs"], manual["description"]) == (3.98, 2, "")
    overview = manager.shopping_overview()
    assert overview["estimated_total"] == 10.45
    assert overview["stores"] == []
    assert manager.split_settings()["active"] is False


async def test_alternatives_and_summary(hass: HomeAssistant, setup_integration) -> None:
    """At most 4 alternatives (cheapest first); open items per store."""
    manager = setup_integration.runtime_data
    aldi, lidl, rewe = _three_stores(manager)
    for store in ("Edeka", "Penny", "Kaufland"):
        manager.save_branch({"store": store, "postcode": "80331"})
    for store, price in (
        ("Lidl", 1.89),
        ("REWE", 2.19),
        ("Edeka", 2.29),
        ("Penny", 1.39),
        ("Kaufland", 1.95),
    ):
        manager.set_store_price(store, "Butter", price, 250, "g")
    manager.shopping_add("250 g Butter")
    manager.shopping_add("Blumenerde")  # no estimate (Klopapier has one since 1.4)
    butter = next(i for i in manager.shopping if i["summary"] == "250 g Butter")
    assert (butter["retailer"], butter["store_reason"], butter["saving"]) == (
        "penny",
        "cheaper",
        0.6,
    )
    assert [(a["retailer"], a["price"]) for a in butter["alternatives"]] == [
        ("lidl", 1.89),
        ("kaufland", 1.95),
        ("aldi-sued", 1.99),
        ("rewe", 2.19),
    ]
    # items added while the split was off have no store
    manager.shopping.append(
        {"uid": "x", "summary": "Kerzen", "status": "needs_action", "source": "manual"}
    )
    manager.shopping.append(
        {"uid": "y", "summary": "Alt", "status": "completed", "branch_id": lidl["id"]}
    )
    summary = manager.stores_summary()
    assert [(g["label"], g["open"], g["subtotal"], g["saving"]) for g in summary] == [
        ("Aldi Süd", 1, 0.0, 0.0),
        ("Penny", 1, 1.39, 0.6),
        ("Ohne Laden", 1, 0.0, 0.0),
    ]
    assert summary[0]["main"] is True
    assert summary[1]["items"] == ["250 g Butter"]

    overview = manager.shopping_overview("Penny")
    assert overview["split_active"] is True
    assert overview["selection"]["items"] == ["250 g Butter"]
    assert (overview["selection"]["subtotal"], overview["selection"]["saving"]) == (1.39, 0.6)
    assert manager.shopping_overview("Hauptladen")["selection"]["items"] == ["Blumenerde"]
    assert manager.shopping_overview("REWE Arbeit")["selection"]["open"] == 0
    with pytest.raises(ServiceValidationError):
        manager.shopping_overview("Netto")
    assert rewe["id"] and aldi["id"]


async def test_compare_prices(hass: HomeAssistant, setup_integration) -> None:
    """Prices of a product at every selected store."""
    manager = setup_integration.runtime_data
    # without branches: the active retailers (offer_stores option), all estimates
    result = manager.compare_prices("Butter")
    assert result["cheapest"] is None
    assert {r["price"] for r in result["results"]} == {1.99}
    assert result["results"][0]["branch_id"] is None

    _three_stores(manager)
    manager.set_store_price("Lidl", "Butter", 3.29, 500, "g")
    manager.add_offer("Butter", "REWE", 1.79, "250 g")
    result = manager.compare_prices("Butter")
    assert result["compared_by"] == "unit_price"
    assert [(r["retailer"], r["price"], r["pack"]) for r in result["results"]] == [
        ("lidl", 3.29, "500 g"),
        ("rewe", 1.79, "250 g"),
        ("aldi-sued", 1.99, "250 g"),
    ]
    assert result["cheapest"]["retailer"] == "lidl"
    assert result["results"][1]["offer"]["price"] == 1.79
    assert result["results"][0]["real"] is True
    assert result["results"][2]["real"] is False
    # with an amount the cost of the needed packs counts
    result = manager.compare_prices("250 g Butter")
    assert result["compared_by"] == "price"
    assert result["cheapest"]["retailer"] == "rewe"
    assert result["amount"] == "250 g"
    assert _error_key(manager, "compare_prices", "") == "name_required"


async def test_store_split_services(hass: HomeAssistant, setup_integration) -> None:
    """Services for the store split and the shopping list per store."""
    manager = setup_integration.runtime_data
    aldi, lidl, _ = _three_stores(manager)
    manager.set_store_price("Lidl", "Butter", 1.49, 250, "g")
    offer = manager.add_offer("Kaffee", "REWE", 4.99, "500 g")

    added = (await _call(hass, "add_shopping_item", item="250 g Butter"))["item"]
    assert (added["retailer"], added["price"]) == ("lidl", 1.49)
    chosen = (
        await _call(
            hass, "add_shopping_item", item="Joghurt", store="Aldi", price=0.65, pack="500 g"
        )
    )["item"]
    assert (chosen["retailer"], chosen["store_reason"], chosen["price"]) == (
        "aldi-sued",
        "manual",
        0.65,
    )
    assert chosen["chosen"] == {
        "name": "Joghurt",
        "price": 0.65,
        "amount": 500.0,
        "unit": "g",
        "retailer": "aldi-sued",
    }
    picked = (await _call(hass, "add_shopping_item", item="Kaffee", offer_id=offer["id"]))["item"]
    assert (picked["retailer"], picked["offer"]["id"], picked["price"]) == (
        "rewe",
        offer["id"],
        4.99,
    )
    assert manager.article_history[0]["summary"] == "Kaffee"

    result = await _call(hass, "set_shopping_store", item="Butter", store="Hauptladen")
    assert result["item"]["branch_id"] == aldi["id"]
    assert result["stores"][0]["label"] == "Aldi Süd"
    result = await _call(hass, "assign_shopping_stores", reset=True)
    assert result["active"] is True
    assert result["assigned"] == 3
    assert _store_of(manager, "250 g Butter") == ("lidl", "cheaper")
    assert _store_of(manager, "Joghurt") == ("aldi-sued", "main")

    overview = await _call(hass, "get_shopping_list", store="Lidl")
    assert overview["selection"]["items"] == ["250 g Butter"]
    assert overview["selection"]["branch_id"] == lidl["id"]
    compare = await _call(hass, "compare_prices", item="Butter")
    assert compare["cheapest"]["retailer"] == "lidl"
    with pytest.raises(ServiceValidationError):
        await _call(hass, "set_shopping_store", item="Butter", store="Netto")


async def test_store_split_intents(hass: HomeAssistant, setup_integration) -> None:
    """Jarvis: what to buy where, cheapest store, choose store, add item."""
    manager = setup_integration.runtime_data
    assert await _speech(hass, "essensplaner_add_shopping_item", item="Butter") == (
        "Ich habe Butter auf die Einkaufsliste gesetzt (etwa 1,99 €)."
    )
    assert await _speech(hass, "essensplaner_get_shopping_list", store="Aldi") == (
        "Die Einkaufsliste ist nicht nach Läden aufgeteilt – dafür brauche ich einen "
        "Hauptladen (im Essensplaner-Panel unter „Läden und Preise“). Auf der Einkaufsliste "
        "steht 1 Eintrag. Milchprodukte und Eier: Butter."
    )
    manager.shopping_clear()

    _three_stores(manager)
    manager.set_store_price("Lidl", "Butter", 1.59, 250, "g")
    manager.add_offer("Milch", "REWE", 0.69, "1 l")
    assert await _speech(hass, "essensplaner_add_shopping_item", item="die Butter") == (
        "Ich habe Butter auf die Einkaufsliste gesetzt – bei Lidl etwa 1,59 €."
    )
    speech = await _speech(hass, "essensplaner_add_shopping_item", item="2 l Milch")
    assert speech == (
        "Ich habe 2 l Milch auf die Einkaufsliste gesetzt – bei REWE Arbeit etwa 1,38 €. "
        "Gerade im Angebot bei REWE für 0,69 €."
    )
    await _speech(hass, "essensplaner_add_shopping_item", item="6 Eier", store="Lidl")
    assert _store_of(manager, "6 Eier") == ("lidl", "manual")

    assert await _speech(hass, "essensplaner_get_shopping_list", store="Lidl") == (
        "Bei Lidl kaufst du 2 Artikel für ungefähr 4,08 €: Butter und 6 Eier. "
        "Dort sparst du etwa 0,40 €."
    )
    assert await _speech(hass, "essensplaner_get_shopping_list", store="Hauptladen") == (
        "Bei Aldi Süd musst du gerade nichts kaufen."
    )
    speech = await _speech(hass, "essensplaner_get_shopping_list")
    assert speech.startswith(
        "Auf der Einkaufsliste stehen 3 Einträge. Davon 2 bei Lidl und 1 bei REWE Arbeit. "
    )
    # an unknown store or a word like "Supermarkt": the whole list
    speech = await _speech(hass, "essensplaner_get_shopping_list", store="Netto")
    assert speech.startswith(
        "Die Filiale „Netto“ habe ich nicht gefunden. Auf der Einkaufsliste stehen 3 Einträge."
    )
    speech = await _speech(hass, "essensplaner_get_shopping_list", store="im Supermarkt")
    assert speech.startswith("Auf der Einkaufsliste stehen 3 Einträge.")

    assert await _speech(hass, "essensplaner_compare_prices", item="Butter") == (
        "Am günstigsten gibt es Butter bei Lidl: 1,59 € (250 g). "
        "Bei Aldi Süd 1,99 € (250 g) und bei REWE Arbeit 1,99 € (250 g)."
    )
    assert await _speech(hass, "essensplaner_compare_prices", item="Eier") == (
        "Eier gibt es überall für etwa 2,49 € (10 Stück, Richtwert)."
    )
    assert await _speech(hass, "essensplaner_compare_prices", item="Milch") == (
        "Am günstigsten gibt es Milch bei REWE Arbeit: 0,69 € (1 l) im Angebot. "
        "Bei Aldi Süd 0,99 € (1 l) und bei Lidl 0,99 € (1 l)."
    )
    assert await _speech(hass, "essensplaner_compare_prices", item="Blumenerde") == (
        "Für Blumenerde habe ich keinen Preis."
    )
    # 1.4: drugstore / household estimates (pack in rolls)
    assert await _speech(hass, "essensplaner_compare_prices", item="Klopapier") == (
        "Klopapier gibt es überall für etwa 3,95 € (10 Rollen, Richtwert)."
    )

    assert await _speech(
        hass, "essensplaner_set_shopping_store", item="die Butter", store="REWE"
    ) == ("Okay, Butter kaufst du bei REWE Arbeit (etwa 1,99 €).")
    speech = await _speech(
        hass, "essensplaner_set_shopping_store", item="Milch", store="Aldi Süd", always=True
    )
    assert speech == (
        "Okay, Milch kaufst du bei Aldi Süd (etwa 1,98 €). "
        "Das merke ich mir auch für die nächsten Einkäufe."
    )
    assert manager.store_preferences == {"milch": "aldi-sued"}
    assert await _speech(
        hass, "essensplaner_set_shopping_store", item="Butter", store="automatisch"
    ) == ("Okay, für Butter wähle ich den Laden wieder automatisch: Lidl (etwa 1,59 €).")


async def test_store_sensors_todo_and_diagnostics(hass: HomeAssistant, setup_integration) -> None:
    """Sensors per store and total, store in the todo description, redacted diagnostics."""
    from custom_components.essensplaner.diagnostics import async_get_config_entry_diagnostics

    manager = setup_integration.runtime_data
    state = hass.states.get("sensor.essensplaner_shopping_stores")
    assert state.state == "0"
    assert state.attributes["split_active"] is False
    assert hass.states.get("sensor.essensplaner_shopping_total").state == "0.0"

    manager.save_branch(
        {
            "store": "Aldi Süd",
            "street": "Hauptstraße 5",
            "postcode": "80331",
            "lat": 48.1,
            "lon": 11.5,
        }
    )
    manager.save_branch({"store": "Lidl", "postcode": "80331"})
    manager.set_store_price("Lidl", "Butter", 1.59, 250, "g")
    await hass.services.async_call(
        "todo",
        "add_item",
        {"entity_id": "todo.essensplaner_shopping_list", "item": "250 g Butter"},
        blocking=True,
    )
    manager.shopping_add("6 Eier")
    await hass.async_block_till_done()
    state = hass.states.get("sensor.essensplaner_shopping_stores")
    assert state.state == "2"
    assert state.attributes["main_store"] == "Aldi Süd Hauptstraße 5"
    assert [(s["label"], s["open"], s["subtotal"]) for s in state.attributes["stores"]] == [
        ("Aldi Süd Hauptstraße 5", 1, 2.49),
        ("Lidl", 1, 1.59),
    ]
    total = hass.states.get("sensor.essensplaner_shopping_total")
    assert float(total.state) == 4.08
    assert total.attributes["unit_of_measurement"] == "EUR"
    assert total.attributes["saving_by_stores"] == 0.4

    items = await hass.services.async_call(
        "todo",
        "get_items",
        {"entity_id": "todo.essensplaner_shopping_list"},
        blocking=True,
        return_response=True,
    )
    butter = next(
        i for i in items["todo.essensplaner_shopping_list"]["items"] if "Butter" in i["summary"]
    )
    assert butter["description"] == "🏪 Lidl · ≈ 1,59 €"

    diagnostics = await async_get_config_entry_diagnostics(hass, setup_integration)
    branch = diagnostics["branches"][0]
    for field in ("lat", "lon", "street", "label", "id", "postcode", "name"):
        assert branch[field] == "**REDACTED**", field
    assert branch["city"] in ("", "**REDACTED**")  # empty values stay empty
    assert (branch["retailer"], branch["main"]) == ("aldi-sued", True)
    assert diagnostics["offer_targets"] == [{"retailers": ["aldi-sued", "lidl"]}]
    assert "80331" not in str(diagnostics)
    assert diagnostics["counts"]["store_prices_user"] == {"lidl": 1}
    assert diagnostics["store_split"]["active"] is True
    assert "Hauptstraße" not in str(diagnostics)


async def test_store_intents_as_llm_tools(hass: HomeAssistant, setup_integration) -> None:
    """The new intents are Assist API tools with described slots (Jarvis / MCP)."""
    from voluptuous_openapi import convert

    api = await llm.async_get_api(
        hass,
        "assist",
        llm.LLMContext(
            platform="test",
            context=Context(),
            language="de",
            assistant="conversation",
            device_id=None,
        ),
    )
    tools = {tool.name: tool for tool in api.tools}
    expected = {
        "essensplaner_get_shopping_list": ({"store"}, set()),
        "essensplaner_compare_prices": ({"item"}, {"item"}),
        "essensplaner_set_shopping_store": ({"item", "store", "always"}, {"item", "store"}),
        "essensplaner_add_shopping_item": ({"item", "store"}, {"item"}),
    }
    for name, (properties, required) in expected.items():
        schema = convert(tools[name].parameters)
        assert set(schema["properties"]) == properties, name
        assert set(schema.get("required", [])) == required, name
        assert all(p.get("description") for p in schema["properties"].values()), name
        assert tools[name].description.startswith("Essensplaner:")

    manager = setup_integration.runtime_data
    _three_stores(manager)
    manager.set_store_price("Lidl", "Butter", 1.59, 250, "g")
    result = await api.async_call_tool(
        llm.ToolInput(tool_name="essensplaner_add_shopping_item", tool_args={"item": "Butter"})
    )
    assert result["response_type"] == "action_done"
    assert result["speech"]["plain"]["speech"].endswith("bei Lidl etwa 1,59 €.")
    result = await api.async_call_tool(
        llm.ToolInput(tool_name="essensplaner_get_shopping_list", tool_args={"store": "Lidl"})
    )
    assert result["speech"]["plain"]["speech"].startswith("Bei Lidl kaufst du 1 Artikel")
    assert result["speech_slots"]["selection"]["items"] == ["Butter"]
    result = await api.async_call_tool(
        llm.ToolInput(tool_name="essensplaner_compare_prices", tool_args={"item": "Butter"})
    )
    assert result["speech_slots"]["cheapest"]["retailer"] == "lidl"
    result = await api.async_call_tool(
        llm.ToolInput(
            tool_name="essensplaner_set_shopping_store",
            tool_args={"item": "Butter", "store": "Hauptladen", "always": True},
        )
    )
    assert result["speech"]["plain"]["speech"].startswith("Okay, Butter kaufst du bei Aldi Süd")


async def test_edit_item_and_unknown_store(hass: HomeAssistant, setup_integration) -> None:
    """A changed item text is priced again; an unknown store is reported."""
    manager = setup_integration.runtime_data
    _three_stores(manager)
    manager.set_store_price("Lidl", "Milch", 0.79, 1, "l")
    item = manager.shopping_add("Butter")
    assert (item["price"], item["retailer"]) == (1.99, "aldi-sued")
    await hass.services.async_call(
        "todo",
        "update_item",
        {"entity_id": "todo.essensplaner_shopping_list", "item": item["uid"], "rename": "2 Butter"},
        blocking=True,
    )
    assert (item["summary"], item["amounts"], item["price"], item["packs"]) == (
        "2 Butter",
        {"": 2.0},
        3.98,
        2,
    )
    manager.shopping_update(item["uid"], summary="3 l Milch")
    assert (item["key"], item["retailer"], item["price"]) == ("milch", "lidl", 2.37)
    assert item["description"] == "🏪 Lidl · ≈ 2,37 €"
    # only the status changes: nothing is recalculated
    manager.shopping_update(item["uid"], summary="3 l Milch", status="completed")
    assert item["status"] == "completed"

    assert _error_key(manager, "shopping_add", "Butter", None, "needs_action", "Netto") == (
        "branch_not_found"
    )


async def test_add_item_with_pack(hass: HomeAssistant, setup_integration) -> None:
    """A pack without price is priced by unit price at that store."""
    manager = setup_integration.runtime_data
    _three_stores(manager)
    manager.set_store_price("Lidl", "Butter", 1.60, 250, "g")
    item = manager.shopping_add("Butter", store="Lidl", pack="500 g")
    assert item["chosen"] == {
        "name": "Butter",
        "price": 3.2,
        "amount": 500.0,
        "unit": "g",
        "retailer": "lidl",
    }
    assert (item["retailer"], item["price"], item["packs"]) == ("lidl", 3.2, 1)
    # the picked price only counts at that store
    assert [(a["retailer"], a["price"]) for a in item["alternatives"]] == [
        ("aldi-sued", 1.99),
        ("rewe", 1.99),
    ]
    with pytest.raises(ServiceValidationError):
        manager.shopping_add("Butter", price=-1)
