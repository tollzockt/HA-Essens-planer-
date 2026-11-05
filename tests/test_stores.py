"""Branches (Filialen): CRUD, main branch, resolving, offer postcodes, services (1.3)."""

from __future__ import annotations

from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
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
    assert first == {"uid": "1", "summary": "Butter", "status": "needs_action"}
    assert (second["branch_id"], second["retailer"]) == (aldi["id"], "aldi-sued")
    assert offer["branches"] == [lidl["id"]]  # retagged


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
