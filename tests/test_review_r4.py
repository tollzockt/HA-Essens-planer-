"""Review round 4: branded coffee offers, compounds at the main store, learned Bund prices,
trip_min after a store choice, offer refresh during a refresh, egg weight classes, "immer
hier" at a further branch, notes on generated items, offers for "Hauptladen", offer
questions with a store, offers that start today."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import intent
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.essensplaner.const import (
    CONF_OFFERS_SOURCE,
    CONF_SPLIT_TRIP_MIN,
    CONF_WATCHLIST,
    CONF_ZIP,
    DOMAIN,
)
from custom_components.essensplaner.offers import (
    MARKTGURU_API,
    MARKTGURU_HOME,
    names_key_product,
    names_other_compound,
    normalize_marktguru,
    offer_matches,
    parse_pack,
)
from custom_components.essensplaner.rewe import best_product

from .test_economy import HOME_HTML, _mg_offer

SEARCH_URL = f"{MARKTGURU_API}/offers/search"
TODO = "todo.essensplaner_shopping_list"


@pytest.fixture(autouse=True)
def no_request_delay(monkeypatch) -> None:
    monkeypatch.setattr("custom_components.essensplaner.offers.REQUEST_DELAY", 0)


async def _setup(hass: HomeAssistant, entry: MockConfigEntry, freezer, **options):
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(datetime.fromisoformat("2026-11-04T10:00:00+01:00"))
    assert await async_setup_component(hass, "homeassistant", {})
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def _speech(hass: HomeAssistant, intent_type: str, **slots) -> str:
    response = await intent.async_handle(
        hass,
        "test",
        intent_type,
        {key: {"value": value} for key, value in slots.items()},
        language="de",
    )
    return response.speech["plain"]["speech"]


async def _refresh(hass: HomeAssistant) -> dict:
    result = await hass.services.async_call(
        DOMAIN, "refresh_offers", {}, blocking=True, return_response=True
    )
    await hass.async_block_till_done()
    return result


def _item(manager, summary: str) -> dict:
    return next(i for i in manager.shopping if i["summary"] == summary)


async def _coffee(hass, config_entry, freezer, aioclient_mock, results, stores):
    """Kaffee (no estimate) on the list, the offers found by marktguru."""
    aioclient_mock.get(MARKTGURU_HOME, text=HOME_HTML)
    aioclient_mock.get(SEARCH_URL, json={"results": results})
    manager = await _setup(
        hass,
        config_entry,
        freezer,
        **{CONF_OFFERS_SOURCE: "marktguru", CONF_ZIP: "80331", CONF_WATCHLIST: "Kaffee"},
    )
    branches = [manager.save_branch({"store": s, "postcode": "80331"}) for s in stores]
    manager.shopping_add("Kaffee")
    await _refresh(hass)
    return manager, branches, _item(manager, "Kaffee")


# ----------------------------------------------------------------------
# offers of the product itself: brands, compounds (r4-1, r4-2)
# ----------------------------------------------------------------------


def test_names_key_product_brands_and_compounds() -> None:
    """Brand names are decided by the description, compounds by what they name."""
    assert names_key_product("Krönung", "kaffee", "Röstkaffee, gemahlen, je 500-g-Packung")
    assert names_key_product("Prodomo", "kaffee", "Kaffee, ganze Bohne")
    for product in ("Röstkaffee", "Filterkaffee", "Bohnenkaffee", "Kaffeebohnen", "Kaffee-Pads"):
        assert names_key_product(product, "kaffee"), product
    for product in ("Eiskaffee 500-ml-Becher", "Milchkaffee", "Malzkaffee", "Kaffeesahne"):
        assert not names_key_product(product, "kaffee"), product
    assert not names_key_product("Mövenpick", "kaffee", "Eiskaffee, 500-ml-Becher")
    assert names_other_compound("Eiskaffee", "kaffee")
    assert not names_other_compound("Krönung", "kaffee")
    assert not names_other_compound("Röstkaffee", "kaffee")


async def test_branded_coffee_offer_moves_unpriced_item(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock
) -> None:
    """ "Kaffee" moves to "Jacobs Krönung" (Röstkaffee in the description) (regression)."""
    krone = _mg_offer(
        1, "Krönung", "penny", "Penny", 4.99, 7.49, 9.98, "kg", "Röstkaffee, gemahlen, 500 g"
    )
    krone["brand"] = {"name": "Jacobs"}
    prodomo = _mg_offer(
        2, "Prodomo", "lidl", "Lidl", 5.49, 7.99, 10.98, "kg", "Kaffee, ganze Bohne, 500 g"
    )
    prodomo["brand"] = {"name": "Dallmayr"}
    manager, (_, penny, lidl), item = await _coffee(
        hass, config_entry, freezer, aioclient_mock, [krone, prodomo], ["Aldi Süd", "Penny", "Lidl"]
    )
    assert (item["branch_id"], item["store_reason"], item["price"]) == (penny["id"], "offer", 4.99)
    assert lidl["id"] in [a["branch_id"] for a in item["alternatives"]]
    # the old prices are learned as the regular coffee prices of these stores
    assert manager.store_book("penny").lookup("Kaffee").price == 7.49


async def test_compound_offer_at_main_store_is_no_price(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock
) -> None:
    """An "Eiskaffee" offer of the main store neither prices Kaffee nor keeps it there."""
    results = [
        _mg_offer(1, "Eiskaffee", "aldi-sued", "Aldi Süd", 0.79, 1.19, 1.58, "l", "500-ml-Becher"),
        _mg_offer(
            3, "Kaffee Crema, ganze Bohne", "penny", "Penny", 9.99, 13.99, 9.99, "kg", "1 kg"
        ),
    ]
    manager, (_, penny), item = await _coffee(
        hass, config_entry, freezer, aioclient_mock, results, ["Aldi Süd", "Penny"]
    )
    assert (item["branch_id"], item["store_reason"], item["price"]) == (penny["id"], "offer", 9.99)
    assert "Eiskaffee" not in str(item["alternatives"])
    # the iced coffee's old price is no regular coffee price of Aldi either
    assert manager.store_book("aldi-sued").lookup("Kaffee") is None


# ----------------------------------------------------------------------
# learned prices for estimates per Bund / Kopf / piece (r4-3)
# ----------------------------------------------------------------------


async def test_learned_bund_prices_only_for_the_product(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Pesto is no price of a Bund Basilikum, Gurken-Dill none of Dill (regression)."""
    manager = setup_integration.runtime_data
    refused = [
        ("basilikum", "Pesto Basilikum", 2.49, 190),
        ("basilikum", "REWE Beste Wahl Pesto alla Genovese mit Basilikum", 2.49, 190),
        ("dill", "Gurken-Dill", 1.79, 670),
        ("salat", "Kartoffelsalat", 1.99, 500),
        ("salat", "Fleischsalat", 1.49, 400),
        ("petersilie", "Petersilie gefriergetrocknet", 1.29, 10),
    ]
    for key, name, price, grams in refused:
        assert not manager.learn_store_price("lidl", key, name, price, grams, "g", "leaflet"), name
    kept = [
        ("baguette", "Baguette", 0.99, 250),
        ("weisskohl", "Weißkohl", 0.99, 1000),
        ("hefe", "Frische Hefe", 0.15, 42),
        ("salat", "Eisbergsalat", 0.99, 500),
    ]
    for key, name, price, grams in kept:
        assert manager.learn_store_price("lidl", key, name, price, grams, "g", "leaflet"), name
    assert "basilikum" not in manager.store_prices_learned.get("lidl", {})


async def test_own_bund_price_kept_against_leaflet(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The user's price for a Bund Basilikum stays the price at the store."""
    manager = setup_integration.runtime_data
    manager.save_branch({"store": "Lidl", "postcode": "80331"})
    manager.set_price("Basilikum", 0.99, 1, "Bund")
    manager.learn_from_offers(
        [
            {
                "id": "mg_1",
                "product": "Pesto Basilikum",
                "retailer": "lidl",
                "old_price": 2.49,
                "price": 1.79,
                "pack_amount": 190,
                "pack_unit": "g",
                "keys": ["basilikum"],
            }
        ]
    )
    item = manager.shopping_add("1 Bund Basilikum")
    assert item["price"] == 0.99


def test_rewe_bund_estimate_without_bund_products() -> None:
    """REWE: no price by weight for a Bund estimate (the cheapest per g is pesto)."""
    products = [
        {
            "product": "REWE Beste Wahl Pesto alla Genovese mit Basilikum",
            "title": "Pesto",
            "price": 2.49,
            "pack_amount": 190,
            "pack_unit": "g",
            "product_id": "b",
        },
        {
            "product": "Basilikum getrocknet",
            "title": "Basilikum getrocknet",
            "price": 1.29,
            "pack_amount": 15,
            "pack_unit": "g",
            "product_id": "c",
        },
    ]
    assert best_product(products, "basilikum", "Bund") is None
    # a piece estimate with a known piece weight still compares by weight (Paprika 500 g)
    paprika = [
        {
            "product": "Paprika rot",
            "title": "Paprika rot",
            "price": 1.99,
            "pack_amount": 500,
            "pack_unit": "g",
            "product_id": "p",
        }
    ]
    assert best_product(paprika, "paprika", "Stück")["product_id"] == "p"


# ----------------------------------------------------------------------
# trip_min after a store choice (r4-6)
# ----------------------------------------------------------------------


async def test_trip_min_follows_store_choice(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer
) -> None:
    """Choosing (or no longer choosing) a store moves the offers there right away."""
    manager = await _setup(hass, config_entry, freezer, **{CONF_SPLIT_TRIP_MIN: 2})
    aldi = manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})
    lidl = manager.save_branch({"store": "Lidl", "postcode": "80331"})
    manager.add_offer("Butter", "Lidl", 1.29, "250 g")
    butter = manager.shopping_add("Butter")
    milk = manager.shopping_add("Milch")
    assert butter["branch_id"] == aldi["id"]  # saving 0,70 € < 2 €

    await _speech(hass, "essensplaner_set_shopping_store", item="Milch", store="Lidl")
    assert (milk["branch_id"], milk["store_reason"]) == (lidl["id"], "manual")
    assert (butter["branch_id"], butter["store_reason"]) == (lidl["id"], "offer")
    assert "🏪 Lidl" in butter["description"]

    manager.set_shopping_store(milk["uid"], "auto")
    assert (butter["branch_id"], butter["store_reason"]) == (aldi["id"], "main")

    manager.shopping_add("Brot", store=lidl["id"])
    assert (butter["branch_id"], butter["store_reason"]) == (lidl["id"], "offer")
    manager.shopping_delete([_item(manager, "Brot")["uid"]])
    assert butter["branch_id"] == aldi["id"]


# ----------------------------------------------------------------------
# a branch saved while an offer refresh runs (r4-8)
# ----------------------------------------------------------------------


async def test_branch_saved_during_refresh_is_searched(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, monkeypatch
) -> None:
    """The debounced refresh joins the running one; the new postcode is searched after."""
    calls: list[list[str]] = []
    gate = asyncio.Event()

    async def fake_fetch(hass_, terms, targets):
        calls.append([zip_code for zip_code, _ in targets])
        if len(calls) == 1:
            await gate.wait()
        return [], []

    monkeypatch.setattr(
        "custom_components.essensplaner.offers.async_fetch_target_offers", fake_fetch
    )
    manager = await _setup(
        hass, config_entry, freezer, **{CONF_OFFERS_SOURCE: "marktguru", CONF_ZIP: "80331"}
    )
    freezer.tick(timedelta(seconds=100))  # the start-up refresh begins (and hangs)
    async_fire_time_changed(hass)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert calls == [["80331"]]
    manager.save_branch({"store": "Lidl", "postcode": "80807", "label": "Lidl Arbeit"})
    freezer.tick(timedelta(seconds=70))  # the debounced refresh joins the running one
    async_fire_time_changed(hass)
    for _ in range(5):
        await asyncio.sleep(0)
    gate.set()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert manager._new_offer_targets()
    freezer.tick(timedelta(seconds=70))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert "80807" in calls[-1]
    assert not manager._new_offer_targets()
    assert manager._offer_refresh_timer is None


# ----------------------------------------------------------------------
# egg weight classes written out (r4-9)
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "description",
    [
        "Bodenhaltung, Gewichtsklasse M (53 g bis unter 63 g), 10 Stück",
        "Freiland, Größe L (ab 63 g), 10 Stück",
        "Größe XL (über 73 g), 10 Stück",
        "Größe S (unter 53 g), 10 Stück",
    ],
)
def test_written_weight_class_is_no_pack(description: str) -> None:
    """ "ab 63 g" or "53 g bis unter 63 g" is the weight class, the pack is 10 eggs."""
    assert parse_pack(description) is None
    offer = normalize_marktguru(
        _mg_offer(1, "Eier", "lidl", "Lidl", 2.29, None, 0.23, "stück", description), "Eier"
    )
    assert (offer["pack_amount"], offer["pack_unit"]) == (10.0, "Stück")
    assert offer_matches(f"Eier {description}", "ei")
    assert parse_pack("je 500-g-Packung") == (500.0, "g")
    assert parse_pack("ab 1 kg") == (1000.0, "g")


# ----------------------------------------------------------------------
# "immer hier" at a further branch of a chain (completeness-r4-1)
# ----------------------------------------------------------------------


async def test_always_at_second_branch_of_chain(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """ "Kaffee immer bei Lidl Arbeit" keeps Kaffee at Lidl Arbeit next week (regression)."""
    entry = setup_integration
    manager = entry.runtime_data
    aldi = manager.save_branch({"store": "Aldi Süd", "postcode": "80331", "label": "Aldi Zuhause"})
    home = manager.save_branch({"store": "Lidl", "postcode": "80331", "label": "Lidl Zuhause"})
    work = manager.save_branch({"store": "Lidl", "postcode": "80807", "label": "Lidl Arbeit"})
    assert manager.main_branch == aldi["id"]
    coffee = manager.shopping_add("Kaffee")
    # the panel's ⇄ picker: item uid, branch id, "Immer in diesem Laden kaufen"
    await hass.services.async_call(
        DOMAIN,
        "set_shopping_store",
        {"item": coffee["uid"], "store": work["id"], "always": True},
        blocking=True,
        return_response=True,
    )
    assert manager.store_preferences == {"kaffee": "lidl"}
    assert manager.store_preference_branches == {"kaffee": work["id"]}
    manager.shopping_delete([coffee["uid"]])
    coffee = manager.shopping_add("Kaffee")
    assert (coffee["branch_id"], coffee["store_reason"]) == (work["id"], "preferred")

    # by voice, for a product that is not on the list
    speech = await _speech(
        hass, "essensplaner_set_shopping_store", item="Tee", store="Lidl Arbeit", always=True
    )
    assert "Lidl Arbeit" in speech
    # a plain chain name means the chain (its first branch)
    await _speech(hass, "essensplaner_set_shopping_store", item="Milch", store="Lidl", always=True)
    assert "milch" not in manager.store_preference_branches
    assert manager.shopping_add("Milch")["branch_id"] == home["id"]

    work_products = manager.preferred_products("Lidl Arbeit")
    assert (work_products["label"], work_products["items"]) == ("Lidl Arbeit", ["Kaffee", "Tee"])
    assert manager.preferred_products("Lidl Zuhause")["items"] == ["Milch"]
    assert manager.preferred_products("Lidl")["items"] == ["Kaffee", "Milch", "Tee"]

    # kept over a restart
    await manager.async_save_now()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    manager = entry.runtime_data
    assert _item(manager, "Kaffee")["branch_id"] == work["id"]

    # the branch is removed: the chain's first branch again
    manager.remove_branch(work["id"])
    assert manager.store_preference_branches == {}
    assert _item(manager, "Kaffee")["branch_id"] == home["id"]

    # "auto" forgets both
    manager.set_shopping_store("Kaffee", "auto", always=True)
    assert "kaffee" not in manager.store_preferences


# ----------------------------------------------------------------------
# notes on generated items (completeness-r4-2)
# ----------------------------------------------------------------------


async def test_note_on_plan_item_survives_reassign(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer
) -> None:
    """A note written in the to-do app stays when the open items are assigned again."""
    manager = await _setup(hass, config_entry, freezer)
    manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})
    manager.save_branch({"store": "Lidl", "postcode": "80331"})
    recipe = manager.get_recipe_by_name("Spaghetti Bolognese")
    manager.plan_meal(date(2026, 11, 5), "abendessen", recipe)
    manager.generate_shopping_list(date(2026, 11, 4), 7)
    item = next(i for i in manager.shopping if i["source"] == "plan")
    summary, generated = item["summary"], item["description"]
    assert "Spaghetti Bolognese" in generated
    await hass.services.async_call(
        "todo",
        "update_item",
        {"entity_id": TODO, "item": summary, "description": f"{generated} · Bio bitte"},
        blocking=True,
    )
    manager.add_offer("Butter", "Lidl", 1.29, "250 g")  # assigns the open items again
    assert item["description"] == f"{generated} · Bio bitte"

    await manager.async_save_now()
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    item = _item(config_entry.runtime_data, summary)
    assert item["description"] == f"{generated} · Bio bitte"


async def test_plan_description_unchanged_without_note(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Rebuilding keeps the 1.2 form 'aisle · ≈ price · recipes' (nothing duplicated)."""
    manager = setup_integration.runtime_data
    item = {
        "summary": "500 g Hackfleisch",
        "source": "plan",
        "category": "Fleisch & Fisch",
        "price": 3.49,
        "recipes": ["Chili con Carne", "Lasagne"],
        "description": "Fleisch & Fisch · ≈ 3,49 € · Chili con Carne, Lasagne",
    }
    manager.update_shopping_description(item)
    manager.update_shopping_description(item)
    assert item["description"] == "Fleisch & Fisch · ≈ 3,49 € · Chili con Carne, Lasagne"


# ----------------------------------------------------------------------
# offers and prices for "Hauptladen" / an own label (completeness-r4-3)
# ----------------------------------------------------------------------


async def test_offer_and_price_for_main_store(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """ "Hauptladen" and own labels are the branch, not an unknown store (regression)."""
    manager = setup_integration.runtime_data
    aldi = manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})
    lidl = manager.save_branch({"store": "Lidl", "postcode": "80331"})
    corner = manager.save_branch({"store": "Lidl", "postcode": "85748", "label": "Ecke"})
    butter = manager.shopping_add("Butter")

    speech = await _speech(
        hass, "essensplaner_add_offer", product="Butter", store="Hauptladen", price="1,49"
    )
    assert speech.startswith(f"Ich habe mir Butter bei {manager.branch_label(aldi)} für 1,49 €")
    offer = manager.offers[-1]
    assert (offer["retailer"], offer["store"], offer["branches"]) == (
        "aldi-sued",
        "Aldi Süd",
        [aldi["id"]],
    )
    assert (butter["branch_id"], butter["price"], butter["offer"]["id"]) == (
        aldi["id"],
        1.49,
        offer["id"],
    )
    assert "Butter" in await _speech(hass, "essensplaner_get_offers", store="Hauptladen")

    milk = manager.add_offer("Milch", "Ecke", 0.79, "1 l")
    assert (milk["retailer"], milk["branches"]) == ("lidl", [corner["id"]])
    manager.save_branch({"id": lidl["id"], "label": "Lidl Zuhause"})  # tags all offers again
    assert milk["branches"] == [corner["id"]]
    # a chain name: all branches of the chain (as before)
    assert manager.add_offer("Quark", "Lidl", 0.59)["branches"] == [lidl["id"], corner["id"]]

    await hass.services.async_call(
        DOMAIN,
        "set_price",
        {"ingredient": "Milch", "price": 0.55, "amount": 1000, "unit": "ml", "store": "Hauptladen"},
        blocking=True,
        return_response=True,
    )
    assert "milch" not in manager.prices_user  # no general price for every store
    assert manager.store_prices_user["aldi-sued"]["milch"]["price"] == 0.55
    assert manager.remove_price("Milch", store="Hauptladen")
    assert "milch" not in manager.store_prices_user.get("aldi-sued", {})


async def test_hauptladen_without_branches_is_a_label(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Without branches "Hauptladen" stays a free text (1.2 behaviour)."""
    manager = setup_integration.runtime_data
    offer = manager.add_offer("Butter", "Hauptladen", 1.49)
    assert (offer["store"], offer["retailer"]) == ("Hauptladen", None)
    entry = manager.set_price("Milch", 0.55, 1000, "ml", store="Hauptladen")
    assert entry["store"] == "Hauptladen"
    assert manager.prices_user["milch"]["store"] == "Hauptladen"


async def test_hauptladen_without_main_branch_is_refused(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """With branches but no main branch an offer for "Hauptladen" is not saved unusable."""
    manager = setup_integration.runtime_data
    manager.save_branch({"store": "Lidl", "postcode": "80331"})
    manager.main_branch = None
    with pytest.raises(ServiceValidationError):
        manager.add_offer("Butter", "Hauptladen", 1.49)
    assert manager.offers == []


# ----------------------------------------------------------------------
# offer questions with a store (completeness-r4-4)
# ----------------------------------------------------------------------


async def test_offer_question_with_branch_in_query(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """ "Wo ist Butter bei Lidl Arbeit im Angebot?" (one wildcard) asks Lidl Arbeit."""
    manager = setup_integration.runtime_data
    manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})
    manager.save_branch({"store": "Lidl", "postcode": "80807", "label": "Lidl Arbeit"})
    manager.add_offer("Deutsche Markenbutter", "Lidl Arbeit", 1.49, "250 g")
    speech = await _speech(hass, "essensplaner_get_offers", query="butter bei lidl arbeit")
    assert "Markenbutter bei Lidl für 1,49 €" in speech
    speech = await _speech(hass, "essensplaner_get_offers", query="butter bei lidl")
    assert "Markenbutter" in speech
    assert "keine passenden" in await _speech(
        hass, "essensplaner_get_offers", query="butter", store="Aldi Süd"
    )


# ----------------------------------------------------------------------
# offers that start today (completeness-r4-5)
# ----------------------------------------------------------------------


async def test_offer_starting_today_moves_item_at_midnight(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer
) -> None:
    """An offer valid from tomorrow moves the item after the 00:01 run."""
    manager = await _setup(hass, config_entry, freezer)
    aldi = manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})
    lidl = manager.save_branch({"store": "Lidl", "postcode": "80331"})
    butter = manager.shopping_add("Butter")
    manager.add_offer(
        "Butter", "Lidl", 1.29, "250 g", valid_from=date(2026, 11, 5), valid_to=date(2026, 11, 7)
    )
    assert butter["branch_id"] == aldi["id"]
    tick = datetime.fromisoformat("2026-11-05T00:01:00+01:00")
    freezer.move_to(tick)
    async_fire_time_changed(hass, tick)
    await hass.async_block_till_done()
    assert (butter["branch_id"], butter["store_reason"], butter["price"]) == (
        lidl["id"],
        "offer",
        1.29,
    )
