"""Store prices, canned tomatoes, offers without size, eggs and 1.2/1.3.0 data (review fixes)."""

from __future__ import annotations

from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.essensplaner.const import CONF_ZIP, DOMAIN, STORAGE_KEY
from custom_components.essensplaner.ingredients import aggregate, parse_ingredient
from custom_components.essensplaner.manager import _load_starter_recipes
from custom_components.essensplaner.offers import manual_offer, offer_matches


async def _call(hass: HomeAssistant, service: str, **data):
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


def _aldi_lidl(manager) -> tuple[dict, dict]:
    aldi = manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})
    lidl = manager.save_branch({"store": "Lidl", "postcode": "80331"})
    assert manager.main_branch == aldi["id"]
    return aldi, lidl


def _item(manager, summary: str) -> dict:
    return next(i for i in manager.shopping if i["summary"] == summary)


async def _load_12(
    hass: HomeAssistant, entry: MockConfigEntry, hass_storage, freezer, data: dict, **options
):
    """Set up the integration with stored 1.2 data."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(datetime.fromisoformat("2026-11-04T10:00:00+01:00"))
    key = f"{STORAGE_KEY}.{entry.entry_id}"
    hass_storage[key] = {
        "version": 1,
        "minor_version": 1,
        "key": key,
        "data": {
            "recipes": {},
            "plan": {},
            "shopping": [],
            "starter_names": [r["name"] for r in _load_starter_recipes()],
            "prices": {},
            "prices_learned": {},
            "offers": [],
            "offers_meta": {},
            **data,
        },
    }
    assert await async_setup_component(hass, "homeassistant", {})
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


# ----------------------------------------------------------------------
# own prices: store cell vs. general price
# ----------------------------------------------------------------------


async def test_store_price_keeps_general_price(hass: HomeAssistant, setup_integration) -> None:
    """Editing a store cell never replaces (or deletes) the general own price."""
    manager = setup_integration.runtime_data
    _aldi_lidl(manager)
    await _call(hass, "set_price", ingredient="Butter", price=1.79, amount=250, unit="g")
    assert manager.store_book("aldi-sued").lookup("Butter").price == 1.79

    # what the panel's price list sends for the Lidl cell
    result = await _call(
        hass, "set_price", ingredient="Butter", price=1.49, amount=250, unit="g", store="lidl"
    )
    assert (result["price"]["price"], result["price"]["retailer"]) == (1.49, "lidl")
    general = manager.prices_user["butter"]
    assert (general["price"], general["store"]) == (1.79, None)
    assert manager.store_book("aldi-sued").lookup("Butter").price == 1.79  # still own price
    assert manager.store_book("lidl").lookup("Butter").price == 1.49
    row = next(r for r in manager.store_price_matrix("Butter")["rows"] if r["key"] == "butter")
    assert (row["general"]["price"], row["general"]["store"]) == (1.79, None)

    # resetting the Lidl cell removes only the Lidl price
    result = await _call(hass, "set_price", ingredient="Butter", remove=True, store="lidl")
    assert result["removed"] is True
    assert manager.prices_user["butter"]["price"] == 1.79
    assert manager.store_book("lidl").lookup("Butter").price == 1.79


async def test_store_price_without_branches_keeps_unlabelled(
    hass: HomeAssistant, setup_integration
) -> None:
    """1.2 mode: a price with store label never overwrites a general price without one."""
    manager = setup_integration.runtime_data
    manager.set_price("Milch", 1.15, 1000, "ml")
    entry = manager.set_price("Milch", 0.89, 1000, "ml", store="Lidl")
    assert entry["retailer"] == "lidl"
    assert manager.prices_user["milch"]["price"] == 1.15
    assert manager.store_prices_user["lidl"]["milch"]["price"] == 0.89
    assert manager.best_price("Milch")[1].price == 1.15
    # a labelled general price is replaced like in 1.2
    manager.set_price("Butter", 1.79, 250, "g", store="Aldi Süd")
    manager.set_price("Butter", 1.29, 250, "g", store="Lidl")
    assert (manager.prices_user["butter"]["price"], manager.prices_user["butter"]["store"]) == (
        1.29,
        "Lidl",
    )
    assert manager.store_prices_user["aldi-sued"]["butter"]["price"] == 1.79


async def test_remove_general_price_removes_its_store_copy(
    hass: HomeAssistant, config_entry: MockConfigEntry, hass_storage, freezer
) -> None:
    """set_price remove without store (1.2 way, panel "Richtwerte") also drops the copy."""
    manager = await _load_12(
        hass,
        config_entry,
        hass_storage,
        freezer,
        {
            "prices": {
                "butter": {
                    "name": "Butter",
                    "price": 1.79,
                    "amount": 250,
                    "unit": "g",
                    "store": "Lidl",
                }
            }
        },
    )
    assert manager.store_prices_user["lidl"]["butter"]["migrated"] is True
    result = await _call(hass, "set_price", ingredient="Butter", remove=True)
    assert result["removed"] is True
    assert manager.prices_user == {}
    assert manager.store_prices_user == {}
    manager.save_branch({"store": "Lidl", "postcode": "80331"})
    assert manager.regular_book().lookup("Butter").source == "default"


# ----------------------------------------------------------------------
# canned tomatoes are not fresh tomatoes
# ----------------------------------------------------------------------


async def test_adjective_prices_stay_with_their_product(
    hass: HomeAssistant, setup_integration
) -> None:
    """ "gewürfelte Tomaten" (key "tomate") never become the price of "Tomaten"."""
    manager = setup_integration.runtime_data
    manager.prices_user["tomate"] = {
        "name": "gewürfelte Tomaten",
        "price": 0.49,
        "amount": 400,
        "unit": "g",
        "store": None,
    }
    manager._invalidate_prices()
    assert manager.regular_book().lookup("Tomaten").source == "default"  # 1.2
    _aldi_lidl(manager)
    tomatoes = manager.regular_book().lookup("Tomaten")
    assert (tomatoes.name, tomatoes.price, tomatoes.source) == ("Tomaten", 1.49, "default")
    assert manager.regular_book().lookup("gewürfelte Tomaten").price == 0.49

    manager.set_store_price("Aldi Süd", "gewürfelte Tomaten", 0.39, 400, "g")
    assert manager.store_book("aldi-sued").lookup("Tomaten").source == "default"
    assert manager.store_book("aldi-sued").lookup("gewürfelte Tomaten").price == 0.39
    rows = {r["key"]: r for r in manager.store_price_matrix("tomat")["rows"]}
    assert "aldi-sued" not in rows["tomate"]["stores"]
    assert rows["gewuerfelte tomate"]["stores"]["aldi-sued"]["price"] == 0.39
    # the cell of that row can be reset
    assert manager.remove_price("gewürfelte Tomaten", "Aldi Süd") is True


async def test_canned_tomato_offers(hass: HomeAssistant, setup_integration) -> None:
    """Offers for canned tomatoes neither price nor move fresh tomatoes (and vice versa)."""
    manager = setup_integration.runtime_data
    _aldi_lidl(manager)
    offer = manager.add_offer("Gehackte Tomaten", "Lidl", 0.39, "400 g")
    assert offer["keys"] == ["gehackte tomate"]
    manager.shopping_add("1 kg Tomaten")
    item = _item(manager, "1 kg Tomaten")
    assert (item["retailer"], item["store_reason"], item["offer"]) == ("aldi-sued", "main", None)
    assert manager.best_price("Tomaten", retailer="lidl")[0].source == "default"
    assert manager.best_price("Gehackte Tomaten", retailer="lidl")[0].offer["id"] == offer["id"]

    # a fresh tomato offer is no offer for canned tomatoes
    fresh = manager.add_offer("Tomaten", "Lidl", 0.49, "1 kg")
    assert fresh["keys"] == ["tomate"]
    assert manager.best_price("Gehackte Tomaten", retailer="lidl")[0].offer["id"] == offer["id"]
    assert manager.best_price("Tomaten", retailer="lidl")[0].offer["id"] == fresh["id"]

    # a leaflet offer found for the term "Tomaten" (key "tomate") gets its own key
    leaflet = {
        "id": "mg_1",
        "title": "Oro di Parma Gehackte Tomaten",
        "product": "Oro di Parma Gehackte Tomaten",
        "store": "Lidl",
        "store_id": "lidl",
        "retailer": "lidl",
        "price": 0.69,
        "old_price": 0.99,
        "pack_amount": 400,
        "pack_unit": "g",
        "valid_from": "2026-11-02",
        "valid_to": "2026-11-08",
        "source": "marktguru",
        "keys": ["tomate"],
        "zip_codes": ["80331"],
    }
    manager.replace_source_offers("marktguru", [leaflet], {"status": "ok"})
    stored = next(o for o in manager.offers if o["id"] == "mg_1")
    assert stored["keys"] == ["gehackte tomate"]
    assert "tomate" not in manager.prices_learned
    assert "tomate" not in manager.store_prices_learned.get("lidl", {})
    assert manager.store_prices_learned["lidl"]["gehackte tomate"]["price"] == 0.99
    assert manager.store_book("lidl").lookup("Tomaten").source == "default"
    item = _item(manager, "1 kg Tomaten")
    assert item["retailer"] == "lidl" and item["offer"]["id"] == fresh["id"]


def test_eggs_match_offers() -> None:
    """Short keys ("ei") match whole words only."""
    assert offer_matches("Frische Eier aus Freilandhaltung 10 Stück", "ei")
    assert offer_matches("Eier", "ei")
    assert not offer_matches("Eierlikör", "ei")
    assert not offer_matches("Reis", "ei")


async def test_offers_without_size(hass: HomeAssistant, setup_integration) -> None:
    """Voice offers without pack and "10 Stück" packs count for prices and stores."""
    manager = setup_integration.runtime_data
    _aldi_lidl(manager)
    eggs = manager.add_offer("Eier", "Lidl", 1.79, "10 Stück")
    assert (eggs["pack_amount"], eggs["pack_unit"]) == (10, "Stück")
    hack = manager.add_offer("Hackfleisch", "Lidl", 2.49)
    assert hack["pack_amount"] is None
    manager.shopping_add("500 g Hackfleisch")
    manager.shopping_add("10 Eier")
    item = _item(manager, "500 g Hackfleisch")
    assert (item["retailer"], item["store_reason"], item["price"]) == ("lidl", "offer", 2.49)
    assert item["offer"]["id"] == hack["id"]
    item = _item(manager, "10 Eier")
    assert (item["retailer"], item["store_reason"], item["price"]) == ("lidl", "offer", 1.79)
    assert manual_offer("Eier", "Lidl", 1.79, "6 Stk")["pack_amount"] == 6


# ----------------------------------------------------------------------
# upgrades
# ----------------------------------------------------------------------


async def test_upgrade_moves_canned_tomatoes(
    hass: HomeAssistant, config_entry: MockConfigEntry, hass_storage, freezer
) -> None:
    """1.2 prices / items / offers under "tomate" named "gehackte Tomaten" get their key."""
    canned = {"name": "Gehackte Tomaten", "price": 0.49, "amount": 400, "unit": "g"}
    summary = aggregate([(parse_ingredient("1 Dose gehackte Tomaten (400 g)"), "Soße")], [])[0][
        "summary"
    ]
    manager = await _load_12(
        hass,
        config_entry,
        hass_storage,
        freezer,
        {
            "prices": {"tomate": {**canned, "store": "Lidl"}},
            "prices_learned": {"tomate": {**canned, "price": 0.59, "store": "Lidl"}},
            "shopping": [
                {
                    "uid": "1",
                    "summary": summary,
                    "status": "completed",
                    "source": "plan",
                    "key": "tomate",
                    "category": "Konserven & Gläser",
                }
            ],
            "offers": [
                {
                    "id": "man_1",
                    "title": "Gehackte Tomaten",
                    "product": "Gehackte Tomaten",
                    "store": "Lidl",
                    "store_id": "lidl",
                    "price": 0.39,
                    "pack_amount": 400,
                    "pack_unit": "g",
                    "source": "manual",
                    "keys": ["tomate"],
                }
            ],
        },
    )
    assert set(manager.prices_user) == {"gehackte tomate"}
    assert set(manager.prices_learned) == {"gehackte tomate"}
    assert set(manager.store_prices_user["lidl"]) == {"gehackte tomate"}
    assert manager.offers[0]["keys"] == ["gehackte tomate"]
    assert manager.shopping[0]["key"] == "gehackte tomate"

    _aldi_lidl(manager)
    assert manager.store_book("lidl").lookup("Tomaten").source == "default"
    assert manager.store_book("lidl").lookup("Gehackte Tomaten").price == 0.49
    # regenerating keeps the ticked item ticked
    recipe = manager.add_recipe(
        {"name": "Soße", "servings": 2, "ingredients": ["1 Dose gehackte Tomaten (400 g)"]}
    )
    manager.plan_meal(manager.today(), "abendessen", recipe=recipe, servings=2)
    manager.generate_shopping_list(manager.today(), 1)
    item = next(i for i in manager.shopping if i["key"] == "gehackte tomate")
    assert item["status"] == "completed"
    assert manager.remove_price("Gehackte Tomaten", "Lidl") is True


async def test_upgrade_guessed_aldi_follows_branch(
    hass: HomeAssistant, config_entry: MockConfigEntry, hass_storage, freezer
) -> None:
    """A plain "Aldi" price decided by the postcode moves to the user's real Aldi."""
    manager = await _load_12(
        hass,
        config_entry,
        hass_storage,
        freezer,
        {
            "prices": {
                "kaese": {
                    "name": "Gouda",
                    "price": 1.49,
                    "amount": 400,
                    "unit": "g",
                    "store": "Aldi",
                }
            }
        },
        **{CONF_ZIP: "45468"},
    )
    assert set(manager.store_prices_user) == {"aldi-nord"}  # postcode guess
    assert "retailer" not in manager.prices_user["kaese"]
    assert manager.best_price("Gouda")[1].price == 1.49
    manager.save_branch({"store": "Aldi Süd", "postcode": "45468", "main": True})
    assert set(manager.store_prices_user) == {"aldi-sued"}
    assert manager.regular_book().lookup("Gouda").price == 1.49
    assert manager.store_price_matrix("Gouda")["retailers"] == [
        {"id": "aldi-sued", "name": "Aldi Süd"}
    ]


async def test_plain_aldi_offer_follows_branch(
    hass: HomeAssistant, config_entry: MockConfigEntry, hass_storage, freezer
) -> None:
    """Manual "Aldi" offers without a known variant are resolved with the branches."""
    manager = await _load_12(
        hass,
        config_entry,
        hass_storage,
        freezer,
        {
            "offers": [
                {
                    "id": "man_1",
                    "title": "Butter",
                    "product": "Butter",
                    "store": "Aldi",
                    "store_id": "aldi",
                    "price": 0.99,
                    "pack_amount": 250,
                    "pack_unit": "g",
                    "source": "manual",
                    "keys": ["butter"],
                }
            ]
        },
    )
    offer = manager.offers[0]
    assert not offer.get("retailer")
    branch = manager.save_branch({"store": "Aldi Süd", "main": True})
    assert manager.offer_retailer(offer) == "aldi-sued"
    assert offer["branches"] == [branch["id"]]
    item = manager.shopping_add("Butter")
    assert (item["price"], item["offer"]["id"]) == (0.99, "man_1")


async def test_upgrade_mixed_units_keep_price(
    hass: HomeAssistant, config_entry: MockConfigEntry, hass_storage, freezer
) -> None:
    """1.2 items like "Butter (2 EL + 25 g)" are priced at the stores."""
    manager = await _load_12(
        hass,
        config_entry,
        hass_storage,
        freezer,
        {
            "shopping": [
                {
                    "uid": "1",
                    "summary": "Butter (2 EL + 25 g)",
                    "status": "needs_action",
                    "source": "plan",
                    "key": "butter",
                    "category": "Milchprodukte & Eier",
                    "price": 1.79,
                }
            ]
        },
    )
    manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})
    item = manager.shopping[0]
    assert (item["retailer"], item["price"]) == ("aldi-sued", 1.99)
    assert manager._item_amounts(item) == {"EL": 2.0, "g": 25.0}
