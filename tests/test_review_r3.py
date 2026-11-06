"""Review round 3: unpriced items, offer picks per branch, learned prices, voice lookups,
eggs by weight class, offers without end, offers for new branches, split off, trip_min."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import intent
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.essensplaner.const import (
    CONF_OFFERS_SOURCE,
    CONF_SPLIT_MODE,
    CONF_SPLIT_TRIP_MIN,
    CONF_WATCHLIST,
    CONF_ZIP,
    DOMAIN,
    SPLIT_OFF,
)
from custom_components.essensplaner.offers import (
    MARKTGURU_API,
    MARKTGURU_HOME,
    leaflet_week_end,
    names_key_product,
    normalize_marktguru,
    parse_pack,
)

from .test_economy import HOME_HTML, _mg_offer

SEARCH_URL = f"{MARKTGURU_API}/offers/search"


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


def _aldi_lidl(manager) -> tuple[dict, dict]:
    aldi = manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})
    lidl = manager.save_branch({"store": "Lidl", "postcode": "80331"})
    assert manager.main_branch == aldi["id"]
    return aldi, lidl


def _only_at(manager, offer: dict, postcode: str) -> None:
    """Make a saved offer one found by marktguru at one postcode only."""
    offer["zip_codes"] = [postcode]
    offer["source"] = "marktguru"
    manager.tag_offer_branches()
    manager._invalidate_prices()


# ----------------------------------------------------------------------
# items without a main-store price move only for an offer of the product itself
# ----------------------------------------------------------------------


def test_names_key_product() -> None:
    """The key as whole words: no compounds that are other products."""
    assert names_key_product("Kaffee Crema, ganze Bohne", "kaffee")
    assert names_key_product("Bio-Kaffee", "kaffee")
    assert names_key_product("Kaffee", "kaffee")
    for product in ("Eiskaffee 500-ml-Becher", "Milchkaffee", "Kaffeesahne"):
        assert not names_key_product(product, "kaffee"), product


async def test_unpriced_item_ignores_compound_offers(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock
) -> None:
    """ "Kaffee" (no estimate) is not sent to Lidl for an iced coffee (regression)."""
    aioclient_mock.get(MARKTGURU_HOME, text=HOME_HTML)
    aioclient_mock.get(
        SEARCH_URL,
        json={
            "results": [
                _mg_offer(1, "Eiskaffee", "lidl", "Lidl", 0.79, 1.19, 1.58, "l", "500-ml-Becher"),
                _mg_offer(2, "Milchkaffee", "penny", "Penny", 0.99, 1.29, 4.0, "l", "250-ml-Dose"),
            ]
        },
    )
    manager = await _setup(
        hass,
        config_entry,
        freezer,
        **{CONF_OFFERS_SOURCE: "marktguru", CONF_ZIP: "80331", CONF_WATCHLIST: "Kaffee"},
    )
    aldi, lidl = _aldi_lidl(manager)
    manager.save_branch({"store": "Penny", "postcode": "80331"})
    manager.shopping_add("Kaffee")
    await _refresh(hass)
    assert "kaffee" in next(o for o in manager.offers if o["title"] == "Eiskaffee")["keys"]

    item = _item(manager, "Kaffee")
    assert (item["branch_id"], item["store_reason"], item["price"]) == (aldi["id"], "main", None)
    assert "🏷️" not in item["description"]
    # an iced coffee is no price of Kaffee at Lidl either (review round 4)
    assert lidl["id"] not in [a["branch_id"] for a in item["alternatives"]]


async def test_unpriced_item_moves_by_unit_price(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock
) -> None:
    """Among real coffee offers the lowest price per kg wins, not the smallest pack."""
    aioclient_mock.get(MARKTGURU_HOME, text=HOME_HTML)
    aioclient_mock.get(
        SEARCH_URL,
        json={
            "results": [
                _mg_offer(1, "Eiskaffee", "lidl", "Lidl", 0.79, 1.19, 1.58, "l", "500-ml-Becher"),
                _mg_offer(2, "Kaffee Klassik", "lidl", "Lidl", 5.49, 6.99, 10.98, "kg", "500 g"),
                _mg_offer(
                    3,
                    "Kaffee Crema, ganze Bohne",
                    "penny",
                    "Penny",
                    9.99,
                    13.99,
                    9.99,
                    "kg",
                    "1 kg",
                ),
            ]
        },
    )
    manager = await _setup(
        hass,
        config_entry,
        freezer,
        **{CONF_OFFERS_SOURCE: "marktguru", CONF_ZIP: "80331", CONF_WATCHLIST: "Kaffee"},
    )
    _aldi_lidl(manager)
    penny = manager.save_branch({"store": "Penny", "postcode": "80331"})
    manager.shopping_add("Kaffee")
    await _refresh(hass)

    item = _item(manager, "Kaffee")
    assert (item["branch_id"], item["store_reason"]) == (penny["id"], "offer")
    assert (item["price"], item["offer"]["id"], item["saving"]) == (9.99, "mg_3", None)


# ----------------------------------------------------------------------
# a picked offer of a further branch of a chain ("Lidl Arbeit")
# ----------------------------------------------------------------------


async def test_offer_pick_for_second_chain_branch(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """ "🛒 Merken" on an offer found only near work lands at that branch (regression)."""
    manager = setup_integration.runtime_data
    aldi = manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})
    home = manager.save_branch({"store": "Lidl", "postcode": "80331", "label": "Lidl Zuhause"})
    work = manager.save_branch({"store": "Lidl", "postcode": "80807", "label": "Lidl Arbeit"})
    assert manager.main_branch == aldi["id"]

    small = manager.add_offer("Butter", "Lidl", 1.79, "250 g")
    _only_at(manager, small, "80807")
    assert small["branches"] == [work["id"]]
    item = manager.shopping_add("Butter", offer_id=small["id"])
    assert (item["branch_id"], item["store_reason"], item["price"]) == (work["id"], "manual", 1.79)
    assert item["store_override"] == work["id"]
    # the offer price is no price of the Lidl near home
    prices = {a["branch_id"]: a["price"] for a in item["alternatives"]}
    assert prices[home["id"]] == 1.99

    big = manager.add_offer("Butter", "Lidl", 0.99, "250 g")
    _only_at(manager, big, "80807")
    picked = manager.shopping_add("Butter", offer_id=big["id"])
    assert (picked["branch_id"], picked["price"]) == (work["id"], 0.99)
    automatic = manager.shopping_add("250 g Butter")
    assert (automatic["branch_id"], automatic["store_reason"]) == (work["id"], "offer")


async def test_offer_pick_for_work_branch_of_main_chain(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """An offer only at "Aldi Arbeit" puts the item there, not at the main Aldi."""
    manager = setup_integration.runtime_data
    home = manager.save_branch({"store": "Aldi Süd", "postcode": "80331", "label": "Aldi Zuhause"})
    manager.save_branch({"store": "Lidl", "postcode": "80331"})
    work = manager.save_branch({"store": "Aldi Süd", "postcode": "80807", "label": "Aldi Arbeit"})
    assert manager.main_branch == home["id"]
    offer = manager.add_offer("Butter", "Aldi Süd", 0.99, "250 g")
    _only_at(manager, offer, "80807")

    item = manager.shopping_add("Butter", offer_id=offer["id"])
    assert (item["branch_id"], item["store_override"], item["price"]) == (
        work["id"],
        work["id"],
        0.99,
    )
    assert {a["branch_id"]: a["price"] for a in item["alternatives"]}[home["id"]] == 1.99


# ----------------------------------------------------------------------
# learned prices of products with an estimate per piece
# ----------------------------------------------------------------------


async def test_per_piece_estimates_learn_weight_prices(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock
) -> None:
    """Baguette 250 g, Weißkohl 1 kg: learned although the estimate is per piece."""
    aioclient_mock.get(MARKTGURU_HOME, text=HOME_HTML)
    aioclient_mock.get(
        SEARCH_URL,
        json={
            "results": [
                _mg_offer(1, "Baguette", "lidl", "Lidl", 0.49, 0.79, 1.96, "kg", "250-g-Stück"),
                _mg_offer(2, "Weißkohl", "lidl", "Lidl", 0.59, 0.99, 0.59, "kg", "je 1 kg"),
            ]
        },
    )
    manager = await _setup(
        hass,
        config_entry,
        freezer,
        **{
            CONF_OFFERS_SOURCE: "marktguru",
            CONF_ZIP: "80331",
            CONF_WATCHLIST: "Baguette, Weißkohl",
        },
    )
    _aldi_lidl(manager)
    await _refresh(hass)
    learned = manager.store_prices_learned["lidl"]
    assert (learned["baguette"]["price"], learned["baguette"]["unit"]) == (0.79, "g")
    assert (learned["weisskohl"]["price"], learned["weisskohl"]["amount"]) == (0.99, 1000.0)
    assert manager.store_book("lidl").lookup("Baguette").price == 0.79

    # still refused: another product for a short key, a piece price for a weight estimate
    assert not manager.learn_store_price("lidl", "ei", "Schoko-Eier", 1.79, 100, "g", "leaflet")
    assert not manager.learn_store_price("lidl", "butter", "Butter", 9.99, 1, "Stück", "leaflet")


# ----------------------------------------------------------------------
# voice: "Milch" is no "Buttermilch", every remembered product is named
# ----------------------------------------------------------------------


async def test_loose_lookup_only_for_the_same_kind(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """ "Milch kaufe ich immer bei Lidl" with only Buttermilch on the list (regression)."""
    manager = setup_integration.runtime_data
    _aldi, lidl = _aldi_lidl(manager)
    buttermilk = manager.shopping_add("500 ml Buttermilch")
    sugar = manager.shopping_add("250 g Puderzucker")

    speech = await _speech(
        hass, "essensplaner_set_shopping_store", item="Milch", store="Lidl", always=True
    )
    assert speech == "Okay, Milch kaufst du ab jetzt immer bei Lidl."
    assert manager.store_preferences == {"milch": "lidl"}
    assert (buttermilk["store_reason"], "store_override" in buttermilk) == ("main", False)

    with pytest.raises(ServiceValidationError):
        manager.set_shopping_store("Zucker", "Lidl")
    assert "store_override" not in sugar

    # the same kind still works: "Hackfleisch" finds "Rinderhackfleisch"
    mince = manager.shopping_add("500 g Rinderhackfleisch")
    manager.set_shopping_store("Hackfleisch", "Lidl")
    assert (mince["branch_id"], mince["store_reason"]) == (lidl["id"], "manual")


async def test_preferred_products_names_every_product(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer
) -> None:
    """ "Was kaufe ich immer bei Lidl?" lists Kokosmilch next to Milch (regression)."""
    manager = await _setup(hass, config_entry, freezer)
    _aldi_lidl(manager)
    manager.shopping_add("250 g Cherrytomaten")
    for product in ("Milch", "Kokosmilch", "Butter", "Erdnussbutter", "Tomaten"):
        manager.set_shopping_store(product, "Lidl", always=True)
    assert manager.store_preferences["cherrytomate"] == "lidl"
    expected = ["Butter", "Erdnussbutter", "Kokosmilch", "Milch", "Tomaten"]
    assert manager.preferred_products("Lidl")["items"] == expected
    speech = await _speech(
        hass, "essensplaner_set_shopping_store", item="was", store="Lidl", always=True
    )
    assert speech == (
        "Bei Lidl kaufst du immer Butter, Erdnussbutter, Kokosmilch, Milch und Tomaten."
    )

    # kept after a restart
    await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.runtime_data.preferred_products("Lidl")["items"] == expected

    # named by itself: listed by itself
    manager = config_entry.runtime_data
    manager.set_shopping_store("Cherrytomaten", "Lidl", always=True)
    assert "Cherrytomaten" in manager.preferred_products("Lidl")["items"]


# ----------------------------------------------------------------------
# eggs: the weight class is no pack size
# ----------------------------------------------------------------------


def test_weight_class_is_no_pack() -> None:
    """ "Größe M (53-63 g), 10 Stück" is a pack of 10, ranges are no sizes."""
    assert parse_pack("Bodenhaltung, Größe M (53-63 g), 10 Stück") is None
    assert parse_pack("500-600 g") is None
    assert parse_pack("je 500-g-Packung") == (500.0, "g")
    assert parse_pack("1,5-l-Flasche") == (1500.0, "ml")
    raw = _mg_offer(
        1, "Eier", "lidl", "Lidl", 1.49, 2.29, None, "", "Bodenhaltung, Größe M (53-63 g), 10 Stück"
    )
    offer = normalize_marktguru(raw, "Eier")
    assert (offer["pack_amount"], offer["pack_unit"]) == (10.0, "Stück")
    # sold by weight: the count is no pack (derived from the price per kg as before)
    chicken = normalize_marktguru(
        _mg_offer(2, "Hähnchenschenkel", "lidl", "Lidl", 2.99, None, 5.98, "kg", "4 Stück"), "x"
    )
    assert chicken["pack_amount"] is None


async def test_egg_offer_with_weight_class(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock
) -> None:
    """A real egg offer with its weight class is used and teaches the egg price."""
    aioclient_mock.get(MARKTGURU_HOME, text=HOME_HTML)
    aioclient_mock.get(
        SEARCH_URL,
        json={
            "results": [
                _mg_offer(
                    1,
                    "Eier",
                    "lidl",
                    "Lidl",
                    1.49,
                    2.29,
                    0.149,
                    "stück",
                    "Bodenhaltung, Größe M (53-63 g), 10 Stück",
                ),
            ]
        },
    )
    manager = await _setup(
        hass,
        config_entry,
        freezer,
        **{CONF_OFFERS_SOURCE: "marktguru", CONF_ZIP: "80331", CONF_WATCHLIST: "Eier"},
    )
    _aldi, lidl = _aldi_lidl(manager)
    await _refresh(hass)
    offer = manager.offers[0]
    assert offer["keys"] == ["ei"]
    assert (offer["pack_amount"], offer["pack_unit"]) == (10.0, "Stück")
    learned = manager.store_prices_learned["lidl"]["ei"]
    assert (learned["price"], learned["amount"], learned["unit"]) == (2.29, 10.0, "Stück")
    item = manager.shopping_add("10 Eier")
    assert (item["branch_id"], item["store_reason"], item["offer"]["id"]) == (
        lidl["id"],
        "offer",
        "mg_1",
    )


# ----------------------------------------------------------------------
# offers entered without an end date end with the leaflet week
# ----------------------------------------------------------------------


def test_leaflet_week_end() -> None:
    assert leaflet_week_end(date(2026, 11, 4)) == date(2026, 11, 7)  # Wednesday
    assert leaflet_week_end(date(2026, 11, 7)) == date(2026, 11, 7)  # Saturday
    assert leaflet_week_end(date(2026, 11, 8)) == date(2026, 11, 14)  # Sunday


async def test_offer_without_end_expires(
    hass: HomeAssistant, setup_integration: MockConfigEntry, freezer
) -> None:
    """An offer said without "bis …" ends on Saturday and the item goes back (regression)."""
    manager = setup_integration.runtime_data
    aldi, lidl = _aldi_lidl(manager)
    speech = await _speech(
        hass, "essensplaner_add_offer", product="Hähnchenbrust", store="Lidl", price="4,99"
    )
    assert "gemerkt, gültig bis Samstag." in speech
    offer = manager.offers[-1]
    assert offer["valid_to"] == "2026-11-07"
    item = manager.shopping_add("1 kg Hähnchenbrust")
    assert (item["branch_id"], item["store_reason"]) == (lidl["id"], "offer")

    freezer.move_to(datetime.fromisoformat("2026-11-09T10:00:00+01:00"))
    manager.new_day()
    assert offer not in manager.offers
    assert (item["branch_id"], item["store_reason"], item["offer"]) == (aldi["id"], "main", None)

    # offers saved without an end (1.2 / 1.3.0) end with the current leaflet week
    old = manager.add_offer("Butter", "Lidl", 1.29, "250 g")
    old["valid_to"] = None
    assert manager._migrate_v2()
    assert old["valid_to"] == "2026-11-14"


# ----------------------------------------------------------------------
# a new branch at a new postcode: offers are searched soon, not next morning
# ----------------------------------------------------------------------


async def test_new_branch_postcode_refreshes_offers(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock
) -> None:
    """Saving "Lidl Arbeit" at 80807 searches offers there a minute later."""
    aioclient_mock.get(MARKTGURU_HOME, text=HOME_HTML)
    aioclient_mock.get(SEARCH_URL, json={"results": []})
    manager = await _setup(
        hass, config_entry, freezer, **{CONF_OFFERS_SOURCE: "marktguru", CONF_ZIP: "80331"}
    )
    freezer.tick(timedelta(seconds=100))  # start-up refresh (stale data)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    def zips() -> set[str]:
        return {
            str(call[1].query.get("zipCode"))
            for call in aioclient_mock.mock_calls
            if "offers/search" in str(call[1])
        }

    assert zips() == {"80331"}
    calls = aioclient_mock.call_count

    # a branch at the searched postcode: nothing new to search
    manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})
    freezer.tick(timedelta(seconds=70))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == calls

    manager.save_branch({"store": "Lidl", "postcode": "80807", "label": "Lidl Arbeit"})
    manager.save_branch({"store": "Penny", "postcode": "80807"})  # one search for both
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == calls
    freezer.tick(timedelta(seconds=70))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert "80807" in zips()
    targets = manager.offers_meta["targets"]
    assert {"zip_code": "80807", "retailers": ["lidl", "penny"]} in targets
    assert not manager._new_offer_targets()


async def test_branch_change_without_marktguru_searches_nothing(
    hass: HomeAssistant, setup_integration: MockConfigEntry, freezer, aioclient_mock
) -> None:
    """Offers off (default): no request after saving branches."""
    manager = setup_integration.runtime_data
    manager.save_branch({"store": "Lidl", "postcode": "80807"})
    freezer.tick(timedelta(seconds=70))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == 0


# ----------------------------------------------------------------------
# split "Aus" with a main branch keeps the picked price
# ----------------------------------------------------------------------


async def test_split_off_keeps_picked_price(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer
) -> None:
    """A picked 500-g pack is priced at 3,29 € while the split is off (regression)."""
    manager = await _setup(hass, config_entry, freezer, **{CONF_SPLIT_MODE: SPLIT_OFF})
    manager.save_branch({"store": "REWE", "postcode": "80331"})
    assert manager.main_retailer == "rewe" and not manager.store_split_active
    response = await hass.services.async_call(
        DOMAIN,
        "add_shopping_item",
        {"item": "Butter", "price": 3.29, "pack": "500 g"},
        blocking=True,
        return_response=True,
    )
    assert response["item"]["price"] == 3.29
    manager.set_price("Zucker", 1.0, 1000, "g")  # prices changed: assigned again
    assert _item(manager, "Butter")["price"] == 3.29


# ----------------------------------------------------------------------
# "Extra-Laden lohnt sich ab": a store visited anyway is no extra trip
# ----------------------------------------------------------------------


async def test_trip_min_keeps_offers_of_a_visited_store(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer
) -> None:
    """Milch is bought at Lidl anyway: the Lidl butter offer stays at Lidl."""
    manager = await _setup(hass, config_entry, freezer, **{CONF_SPLIT_TRIP_MIN: 2})
    aldi, lidl = _aldi_lidl(manager)
    manager.add_offer("Butter", "Lidl", 1.29, "250 g")
    butter = manager.shopping_add("Butter")
    assert (butter["branch_id"], butter["store_reason"]) == (aldi["id"], "main")  # 0,70 € < 2 €

    milk = manager.shopping_add("Milch", store=lidl["id"])
    assert milk["store_reason"] == "manual"
    manager.assign_shopping_stores()
    assert (butter["branch_id"], butter["store_reason"], butter["price"]) == (
        lidl["id"],
        "offer",
        1.29,
    )
    more = manager.shopping_add("2 Butter")
    assert (more["branch_id"], more["store_reason"]) == (lidl["id"], "offer")

    # "immer hier" counts as well
    manager.shopping_delete([milk["uid"], more["uid"]])
    manager.assign_shopping_stores()
    assert butter["branch_id"] == aldi["id"]
    manager.set_shopping_store("Kaffee", "Lidl", always=True)
    coffee = manager.shopping_add("Kaffee")
    assert coffee["store_reason"] == "preferred"
    manager.assign_shopping_stores()
    assert (butter["branch_id"], butter["store_reason"]) == (lidl["id"], "offer")
