"""Review round 2: eggs, offer picks, voice lookups, store options, offers per branch."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import intent
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.essensplaner.const import (
    CONF_OFFERS_SOURCE,
    CONF_SPLIT_MODE,
    CONF_WATCHLIST,
    CONF_ZIP,
    DOMAIN,
    SPLIT_MAIN_ONLY,
    SPLIT_OFF,
)
from custom_components.essensplaner.ingredients import normalize_spoken_quantity
from custom_components.essensplaner.offers import (
    MARKTGURU_API,
    MARKTGURU_HOME,
    normalize_marktguru,
    offer_matches,
)

from .test_economy import HOME_HTML, _mg_offer


async def _setup(hass: HomeAssistant, entry: MockConfigEntry, freezer, **options):
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(datetime.fromisoformat("2026-11-04T10:00:00+01:00"))
    assert await async_setup_component(hass, "homeassistant", {})
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


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


def _aldi_lidl(manager, label: str | None = None) -> tuple[dict, dict]:
    aldi = manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})
    lidl = {"store": "Lidl", "postcode": "80331"}
    if label:
        lidl["label"] = label
    lidl = manager.save_branch(lidl)
    assert manager.main_branch == aldi["id"]
    return aldi, lidl


def _item(manager, summary: str) -> dict:
    return next(i for i in manager.shopping if i["summary"] == summary)


# ----------------------------------------------------------------------
# chocolate eggs are no egg offers
# ----------------------------------------------------------------------


def test_short_key_offer_matching() -> None:
    """ "ei" needs eggs sold by count, not sweets, liqueur or noodles."""
    assert offer_matches("Eier aus Bodenhaltung, 10 Stück", "ei")
    assert offer_matches("Bio-Eier 10er-Packung", "ei")
    assert offer_matches("Eier Größe M (53-63 g), 10 Stück", "ei")
    for title in (
        "Schoko-Eier 100-g-Beutel",
        "Kinder Überraschung Eier",
        "Eier Likör",
        "Eier-Nudeln",
        "Zartbitter Eier",
        "Eier 250 g",
        "Eierlikör",
    ):
        assert not offer_matches(title, "ei"), title


async def test_chocolate_eggs_teach_nothing(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock, monkeypatch
) -> None:
    """Leaflet sweets found for "Eier" get no egg key, price and store (regression)."""
    monkeypatch.setattr("custom_components.essensplaner.offers.REQUEST_DELAY", 0)
    aioclient_mock.get(MARKTGURU_HOME, text=HOME_HTML)
    aioclient_mock.get(
        f"{MARKTGURU_API}/offers/search",
        json={
            "results": [
                _mg_offer(
                    77, "Schoko-Eier", "lidl", "Lidl", 0.99, 1.79, 9.90, "kg", "100-g-Beutel"
                ),
                _mg_offer(78, "Kinder Überraschung Eier", "lidl", "Lidl", 2.49, 3.29, None, ""),
                _mg_offer(79, "Eier aus Bodenhaltung", "lidl", "Lidl", 1.89, 2.29, 0.19, "stück"),
            ]
        },
    )
    manager = await _setup(
        hass,
        config_entry,
        freezer,
        **{CONF_OFFERS_SOURCE: "marktguru", CONF_ZIP: "80331", CONF_WATCHLIST: "Eier"},
    )
    _aldi_lidl(manager)
    await hass.services.async_call(
        DOMAIN, "refresh_offers", {}, blocking=True, return_response=True
    )
    await hass.async_block_till_done()
    keys = {o["title"]: o.get("keys") for o in manager.offers}
    assert "ei" not in (keys.get("Schoko-Eier") or [])
    assert "ei" not in (keys.get("Kinder Überraschung Eier") or [])
    assert "ei" in keys["Eier aus Bodenhaltung"]
    # the regular price of real eggs is learned, never one of the chocolate eggs
    learned = manager.store_prices_learned["lidl"]["ei"]
    assert (learned["name"], learned["price"], learned["unit"]) == (
        "Eier aus Bodenhaltung",
        2.29,
        "Stück",
    )
    assert "ei" not in manager.prices_learned

    # "2 Eier" goes to Lidl for the real egg offer only
    item = manager.shopping_add("2 Eier")
    assert (item["retailer"], item["store_reason"], item["offer"]["id"]) == (
        "lidl",
        "offer",
        "mg_79",
    )
    offers = [(r["offer"] or {}).get("id") for r in manager.compare_prices("Eier")["results"]]
    assert offers == ["mg_79", None]


async def test_incomparable_units_are_not_learned(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """A price per 100 g is no egg price; with a piece weight it is checked (Paprika)."""
    manager = setup_integration.runtime_data
    assert not manager.learn_store_price("lidl", "ei", "Schoko-Eier", 1.79, 100, "g", "leaflet")
    assert manager.learn_store_price("lidl", "paprika", "Paprika", 2.49, 500, "g", "leaflet")
    assert not manager.learn_store_price("lidl", "paprika", "Paprika", 9.99, 500, "g", "leaflet")


# ----------------------------------------------------------------------
# picked offers of the main store keep the item automatic
# ----------------------------------------------------------------------


async def test_main_store_offer_pick_stays_automatic(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Saved and live offers of the main store are no store choice (regression)."""
    manager = setup_integration.runtime_data
    _aldi, lidl = _aldi_lidl(manager)
    saved = manager.add_offer("Butter", "Aldi Süd", 1.49, "250 g")
    item = manager.shopping_add("Butter", price=1.49, pack="250 g", offer_id=saved["id"])
    assert "store_override" not in item
    assert (item["retailer"], item["store_reason"], item["price"]) == ("aldi-sued", "main", 1.49)

    # a live leaflet hit of the main store (from the article search cache)
    live = normalize_marktguru(
        _mg_offer(11, "Meggle Feine Butter", "aldi-sued", "Aldi Süd", 1.39, 2.19, 5.56)
        | {"description": "250-g-Packung"},
        "Butter",
    )
    manager._live_cache[("butter", "80331")] = (0.0, [live])
    picked = manager.shopping_add(
        "Meggle Feine Butter", price=1.39, pack="250 g", offer_id=live["id"]
    )
    assert "store_override" not in picked
    assert (picked["store_reason"], picked["price"]) == ("main", 1.39)

    # a cheaper Lidl offer moves both
    manager.add_offer("Butter", "Lidl", 0.89, "250 g")
    for entry in (item, picked):
        assert (entry["branch_id"], entry["store_reason"]) == (lidl["id"], "offer")


async def test_other_store_offer_pick_ends_with_the_offer(
    hass: HomeAssistant, setup_integration: MockConfigEntry, freezer
) -> None:
    """An offer of another store pins the item there until the offer ends."""
    manager = setup_integration.runtime_data
    aldi, lidl = _aldi_lidl(manager)
    offer = manager.add_offer(
        "Butter", "Lidl", 1.89, "250 g", valid_to=manager.today() + timedelta(days=1)
    )
    item = manager.shopping_add("Butter", offer_id=offer["id"])
    assert (item["store_override"], item["store_reason"]) == (lidl["id"], "manual")

    freezer.move_to(datetime.fromisoformat("2026-11-06T10:00:00+01:00"))
    manager.new_day()
    assert "store_override" not in item
    assert (item["branch_id"], item["store_reason"]) == (aldi["id"], "main")


# ----------------------------------------------------------------------
# voice: items by their common name, questions are no products
# ----------------------------------------------------------------------


async def test_item_found_by_common_name(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """ "Hackfleisch" finds "Rinderhackfleisch", "Tomaten" the "Cherrytomaten" (regression)."""
    manager = setup_integration.runtime_data
    _aldi, lidl = _aldi_lidl(manager)
    hack = manager.shopping_add("500 g Rinderhackfleisch")
    tomatoes = manager.shopping_add("250 g Cherrytomaten")
    coconut = manager.shopping_add("400 ml Kokosmilch")

    speech = await _speech(
        hass, "essensplaner_set_shopping_store", item="Hackfleisch", store="Lidl"
    )
    assert speech.startswith("Okay, Rinderhackfleisch kaufst du bei Lidl")
    assert (hack["branch_id"], hack["store_reason"]) == (lidl["id"], "manual")

    speech = await _speech(
        hass, "essensplaner_set_shopping_store", item="Tomaten", store="Lidl", always=True
    )
    assert speech.startswith("Okay, Cherrytomaten kaufst du bei Lidl")
    assert tomatoes["branch_id"] == lidl["id"]
    assert manager.store_preferences == {"cherrytomate": "lidl", "tomate": "lidl"}
    assert manager.preferred_products("Lidl")["items"] == ["Tomaten"]

    # another product stays where it is: "Milch" is no "Kokosmilch"
    with pytest.raises(ServiceValidationError):
        manager.set_shopping_store("Milch", "Lidl")
    assert "store_override" not in coconut


async def test_ambiguous_item_is_not_remembered(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Two items of the kind: no silent preference for a key that fits none of them."""
    manager = setup_integration.runtime_data
    _aldi_lidl(manager)
    manager.shopping_add("250 g Cherrytomaten")
    manager.shopping_add("250 g Kirschtomaten")
    with pytest.raises(ServiceValidationError):
        manager.set_shopping_store("Tomaten", "Lidl", always=True)
    assert manager.store_preferences == {}


async def test_question_is_no_store_preference(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """ "Was kaufe ich immer bei Lidl?" names the products, it stores nothing (regression)."""
    manager = setup_integration.runtime_data
    _aldi_lidl(manager)
    speech = await _speech(
        hass, "essensplaner_set_shopping_store", item="Was", store="Lidl", always=True
    )
    assert speech == "Für Lidl habe ich mir noch keine Produkte gemerkt."
    assert manager.store_preferences == {}

    await _speech(hass, "essensplaner_set_shopping_store", item="Kaffee", store="Lidl", always=True)
    manager.shopping_add("1 l Milch")
    manager.set_shopping_store("Milch", "Lidl", always=True)
    speech = await _speech(
        hass, "essensplaner_set_shopping_store", item="was", store="beim Lidl", always=True
    )
    assert speech == "Bei Lidl kaufst du immer Kaffee und Milch."
    with pytest.raises(ServiceValidationError):
        manager.set_shopping_store("welche Sachen", "Lidl", always=True)
    assert set(manager.store_preferences) == {"kaffee", "milch"}


# ----------------------------------------------------------------------
# spoken quantities
# ----------------------------------------------------------------------


def test_normalize_spoken_quantity() -> None:
    """Number words and bare units of voice input become digits."""
    cases = {
        "zwei Liter Milch": "2 Liter Milch",
        "drei Packungen Butter": "3 Packungen Butter",
        "einen Liter Milch": "1 Liter Milch",
        "Liter Milch": "1 Liter Milch",
        "Kilo Hackfleisch": "1 Kilo Hackfleisch",
        "eine halbe Gurke": "0,5 Gurke",
        "ein Pfund Hackfleisch": "500 g Hackfleisch",
        "zweihundertfünfzig Gramm Butter": "250 Gramm Butter",
        "zwölf Eier": "12 Eier",
        "eine Gurke": "eine Gurke",
        "Rundkornreis": "Rundkornreis",
        "Glasnudeln": "Glasnudeln",
        "3 Butter": "3 Butter",
    }
    for text, expected in cases.items():
        assert normalize_spoken_quantity(text) == expected, text


async def test_spoken_quantities_on_the_list(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """ "drei Packungen Butter" is 3 packs and follows "immer bei Lidl" (regression)."""
    manager = setup_integration.runtime_data
    _aldi, lidl = _aldi_lidl(manager)
    await _speech(hass, "essensplaner_set_shopping_store", item="Butter", store="Lidl", always=True)
    speech = await _speech(hass, "essensplaner_add_shopping_item", item="drei Packungen Butter")
    item = manager.shopping[-1]
    assert item["summary"] == "3 Packungen Butter"
    assert (item["key"], item["branch_id"], item["store_reason"]) == (
        "butter",
        lidl["id"],
        "preferred",
    )
    assert item["packs"] == 3

    one = manager.shopping_add("1 l Milch")
    two = manager.shopping_add("zwei Liter Milch")
    assert two["key"] == "milch"
    assert two["price"] == pytest.approx(2 * one["price"])
    speech = await _speech(hass, "essensplaner_add_shopping_item", item="einen Liter Milch")
    assert speech.startswith("Ich habe 1 Liter Milch auf die Einkaufsliste gesetzt")
    assert manager.shopping[-1]["key"] == "milch"
    assert manager.compare_prices("zwei Liter Milch")["amount"] == "2000 ml"


# ----------------------------------------------------------------------
# store options, unpriced items, offers per branch, search terms, voice summary
# ----------------------------------------------------------------------


async def test_store_options_reassign_open_items(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer
) -> None:
    """A new split mode applies to the open items right after the reload (regression)."""
    manager = await _setup(hass, config_entry, freezer)
    aldi, lidl = _aldi_lidl(manager)
    manager.add_offer("Butter", "Lidl", 1.29, "250 g")
    manager.shopping_add("Butter")
    assert _item(manager, "Butter")["branch_id"] == lidl["id"]

    hass.config_entries.async_update_entry(
        config_entry, options={**config_entry.options, CONF_SPLIT_MODE: SPLIT_MAIN_ONLY}
    )
    await hass.async_block_till_done()
    manager = config_entry.runtime_data
    item = _item(manager, "Butter")
    assert (item["branch_id"], item["store_reason"]) == (aldi["id"], "main")
    assert [g["label"] for g in manager.stores_summary()] == ["Aldi Süd"]

    hass.config_entries.async_update_entry(
        config_entry, options={**config_entry.options, CONF_SPLIT_MODE: SPLIT_OFF}
    )
    await hass.async_block_till_done()
    manager = config_entry.runtime_data
    item = _item(manager, "Butter")
    assert "branch_id" not in item
    assert "🏪" not in item["description"]


async def test_offer_moves_item_without_main_price(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Kaffee has no estimate: an offer at Lidl still moves it there (regression)."""
    manager = setup_integration.runtime_data
    _aldi, lidl = _aldi_lidl(manager)
    offer = manager.add_offer("Kaffee", "Lidl", 4.99, "500 g")
    for summary in ("Kaffee", "500 g Kaffee"):
        item = manager.shopping_add(summary)
        assert (item["branch_id"], item["store_reason"]) == (lidl["id"], "offer")
        assert (item["price"], item["offer"]["id"], item["saving"]) == (4.99, offer["id"], None)
    # without an offer it stays at the main store
    other = manager.shopping_add("Spülmittel")
    assert other["store_reason"] == "main"


async def test_offers_by_branch_label(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Offer questions understand own labels and "Hauptladen" (regression)."""
    manager = setup_integration.runtime_data
    _aldi_lidl(manager, label="Lidl Arbeit")
    manager.add_offer("Butter", "Lidl", 1.29, "250 g")
    manager.add_offer("Hackfleisch", "Aldi Süd", 2.99, "500 g")

    def titles(store: str) -> list[str]:
        return [o["title"] for o in manager.offers_view("all", None, store)]

    assert titles("Lidl") == ["Butter"]
    assert titles("Lidl Arbeit") == ["Butter"]
    assert titles("Hauptladen") == ["Hackfleisch"]
    assert titles("mein Hauptladen") == ["Hackfleisch"]
    assert titles("Aldi") == ["Hackfleisch"]
    assert titles("Penny") == []
    speech = await _speech(hass, "essensplaner_get_offers", store="Lidl Arbeit", when="alle")
    assert "Butter bei Lidl" in speech


async def test_manual_items_are_searched_for_offers(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Open items added by hand are offer search terms (any aisle)."""
    manager = setup_integration.runtime_data
    manager.shopping_add("Kaffee")
    manager.shopping_add("Spülmittel")
    done = manager.shopping_add("Toilettenpapier")
    manager.shopping_update(done["uid"], status="completed")
    keys = [key for _, key in manager.offer_search_terms(40)]
    assert len(keys) <= 40
    assert {"kaffee", "spuelmittel"} <= set(keys)
    assert "toilettenpapier" not in keys
    assert len(keys) == len(set(keys))


async def test_shopping_list_intent_names_the_stores(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """ "Erstelle die Einkaufsliste" says where to shop (and returns the stores)."""
    manager = setup_integration.runtime_data
    _aldi_lidl(manager)
    recipe = manager.get_recipe_by_name("Spaghetti Bolognese")
    manager.plan_meal(manager.today(), "abendessen", recipe)
    manager.add_offer("Spaghetti", "Lidl", 0.49, "500 g")
    response = await _intent(hass, "essensplaner_create_shopping_list")
    speech = response.speech["plain"]["speech"]
    assert "Nach Laden:" in speech
    assert "bei Lidl" in speech and "bei Aldi Süd" in speech
    assert "das spart etwa" in speech
    stores = response.speech_slots["stores"]
    assert [s["label"] for s in stores] == ["Aldi Süd", "Lidl"]
    assert stores[1]["saving"] > 0
    assert set(stores[0]) == {"label", "open", "subtotal", "saving"}


async def test_without_branches_no_store_summary(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """1.2 behaviour: no stores in the answer."""
    manager = setup_integration.runtime_data
    recipe = manager.get_recipe_by_name("Spaghetti Bolognese")
    manager.plan_meal(manager.today(), "abendessen", recipe)
    response = await _intent(hass, "essensplaner_create_shopping_list")
    assert "Nach Laden" not in response.speech["plain"]["speech"]
    assert "stores" not in response.speech_slots


# ----------------------------------------------------------------------
# article search
# ----------------------------------------------------------------------


async def test_local_search_ranks_other_product_offers_last(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """A canned-tomato offer is no first hit for "Tomaten" (regression)."""
    manager = setup_integration.runtime_data
    _aldi_lidl(manager)
    canned = manager.add_offer("Oro di Parma Gehackte Tomaten", "Aldi Süd", 0.59, "400 g")
    fresh = manager.add_offer("Rispentomaten", "Aldi Süd", 1.29, "500 g")
    titles = [r["title"] for r in manager.search_articles("Tomaten", limit=20)]
    assert titles.index(fresh["title"]) < titles.index("Tomaten")
    assert titles.index("Tomaten") < titles.index(canned["title"])
