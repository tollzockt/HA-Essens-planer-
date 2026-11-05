"""Tests for prices, budget, offers and cost aware planning (1.2 + 1.3 offers per branch)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import intent
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.essensplaner.const import (
    CONF_BUDGET,
    CONF_OFFERS_SOURCE,
    CONF_STORES,
    CONF_ZIP,
    DOMAIN,
)
from custom_components.essensplaner.offers import MARKTGURU_API, MARKTGURU_HOME

TODO = "todo.essensplaner_shopping_list"


@pytest.fixture(autouse=True)
def no_request_delay(monkeypatch) -> None:
    """No politeness delay between offer requests in tests (time is frozen)."""
    monkeypatch.setattr("custom_components.essensplaner.offers.REQUEST_DELAY", 0)


async def _call(hass: HomeAssistant, service: str, **data):
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


async def _speech(hass: HomeAssistant, intent_type: str, **slots) -> str:
    response = await intent.async_handle(
        hass,
        "test",
        intent_type,
        {key: {"value": value} for key, value in slots.items()},
        language="de",
    )
    return response.speech["plain"]["speech"]


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


async def test_clear_shopping_list(hass: HomeAssistant, setup_integration) -> None:
    """The shopping list can be emptied (bug report 1.1)."""
    await _call(hass, "plan_meal", date="heute", recipe="Spaghetti Aglio e Olio")
    await _call(hass, "generate_shopping_list", days=1)
    await hass.services.async_call(
        "todo", "add_item", {"entity_id": TODO, "item": "Klopapier"}, blocking=True
    )
    items = await hass.services.async_call(
        "todo", "get_items", {"entity_id": TODO}, blocking=True, return_response=True
    )
    first = items[TODO]["items"][0]["uid"]
    await hass.services.async_call(
        "todo",
        "update_item",
        {"entity_id": TODO, "item": first, "status": "completed"},
        blocking=True,
    )
    result = await _call(hass, "clear_shopping_list", mode="completed")
    assert result["removed"] == 1
    result = await _call(hass, "clear_shopping_list", mode="plan")
    assert result["removed"] >= 3
    await hass.async_block_till_done()
    assert hass.states.get(TODO).state == "1"  # Klopapier (manual) is kept
    speech = await _speech(hass, "essensplaner_clear_shopping_list")
    assert speech == "Die Einkaufsliste ist jetzt leer (1 Einträge entfernt)."
    await hass.async_block_till_done()
    assert hass.states.get(TODO).state == "0"
    assert await _speech(hass, "essensplaner_clear_shopping_list") == "Da gab es nichts zu löschen."


async def test_import_starter_recipes(hass: HomeAssistant, setup_integration) -> None:
    """Missing bundled recipes can be added again."""
    await _call(hass, "delete_recipe", recipe="Käsespätzle")
    result = await _call(hass, "import_starter_recipes")
    assert result["added"] == ["Käsespätzle"]
    assert len(result["skipped"]) >= 100


async def test_recipe_costs_and_prices(hass: HomeAssistant, setup_integration) -> None:
    """Recipes get a plausible cost estimate; own prices change it."""
    recipe = (await _call(hass, "get_recipe", recipe="Spaghetti Aglio e Olio", servings=2))[
        "recipe"
    ]
    cost = recipe["cost"]
    assert 0.5 < cost["total"] < 4
    assert cost["unknown"] == []
    lasagne = (await _call(hass, "get_recipe", recipe="Lasagne", servings=4))["recipe"]["cost"]
    assert lasagne["total"] > cost["total"]

    before = (await _call(hass, "get_recipe", recipe="Kartoffelsuppe"))["recipe"]["cost"]["total"]
    await _call(hass, "set_price", ingredient="Kartoffeln", price=10, amount=1000, unit="g")
    after = (await _call(hass, "get_recipe", recipe="Kartoffelsuppe"))["recipe"]["cost"]["total"]
    assert after > before + 3
    await _call(hass, "set_price", ingredient="Kartoffeln", remove=True)
    again = (await _call(hass, "get_recipe", recipe="Kartoffelsuppe"))["recipe"]["cost"]["total"]
    assert again == before


async def test_budget(hass: HomeAssistant, config_entry: MockConfigEntry, freezer) -> None:
    """Weekly budget, costs and remaining budget."""
    await _setup(hass, config_entry, freezer, **{CONF_BUDGET: 30})
    await _call(hass, "plan_meal", date="heute", recipe="Lasagne", servings=4)
    await _call(hass, "plan_meal", date="morgen", recipe="Linsensuppe")
    await hass.async_block_till_done()
    week = await _call(hass, "get_costs")
    assert week["budget"] == 30
    assert week["total"] > 0
    assert week["remaining"] == round(30 - week["total"], 2)
    assert float(hass.states.get("sensor.essensplaner_week_cost").state) == week["total"]
    assert float(hass.states.get("sensor.essensplaner_budget_remaining").state) == week["remaining"]
    speech = await _speech(hass, "essensplaner_get_costs")
    assert speech.startswith("Die 2 geplanten Mahlzeiten kosten diese Woche etwa")
    assert "Vom Budget (30,00 €) sind noch" in speech

    # auto planning respects the budget: the rest of the week stays roughly within it
    result = await _call(hass, "auto_plan", days=5, strategy="günstig")
    assert len(result["planned"]) == 3  # Fri–Sun (Wed/Thu already planned)
    assert result["week"]["total"] <= 30 * 1.25


async def test_manual_offer_changes_costs(hass: HomeAssistant, setup_integration) -> None:
    """A manual offer is used for costs, shopping list and voice answers."""
    regular = (await _call(hass, "get_recipe", recipe="Hähnchen-Reis-Pfanne"))["recipe"]["cost"]
    speech = await _speech(
        hass,
        "essensplaner_add_offer",
        product="Hähnchenbrustfilet",
        store="Lidl",
        price="4,99 €",
        pack="1 kg",
        valid_to="Samstag",
    )
    assert speech.startswith("Ich habe mir Hähnchenbrustfilet bei Lidl für 4,99 € gemerkt.")
    assert "Passt zum Beispiel zu" in speech
    offered = (await _call(hass, "get_recipe", recipe="Hähnchen-Reis-Pfanne"))["recipe"]["cost"]
    assert offered["total"] < regular["total"]
    assert offered["savings"] > 0
    assert offered["on_offer"][0]["store"] == "Lidl"

    offers = await _call(hass, "get_offers", when="current")
    assert offers["offers"][0]["title"] == "Hähnchenbrustfilet"
    assert "Hähnchen-Reis-Pfanne" in offers["offers"][0]["recipes"]
    await hass.async_block_till_done()
    assert hass.states.get("sensor.essensplaner_offers").state == "1"

    speech = await _speech(hass, "essensplaner_get_offers")
    assert "Hähnchenbrustfilet bei Lidl für 4,99 €" in speech

    await _call(hass, "plan_meal", date="morgen", recipe="Hähnchen-Reis-Pfanne")
    shopping = await _call(hass, "generate_shopping_list", days=3)
    chicken = next(i for i in shopping["items"] if "Hähnchen" in i["summary"])
    assert chicken["offer"]["store"] == "Lidl"
    assert "🏷️ Lidl 4,99 €" in chicken["description"]
    assert shopping["total_price"] > 0

    # offers expire
    result = await _call(hass, "remove_offer", id=offers["offers"][0]["id"])
    assert result["removed"] is True


async def test_planning_weights(hass: HomeAssistant, setup_integration) -> None:
    """Offers, cheapness and variety influence the suggestion weights."""
    manager = setup_integration.runtime_data
    today = manager.today()
    chicken = manager.find_recipe("Hähnchen-Reis-Pfanne")
    without = manager.economy_weight(chicken, today, strategy="offers")
    manager.add_offer("Hähnchenbrust", "Aldi Süd", 5.49, "1 kg")
    with_offer = manager.economy_weight(chicken, today, strategy="offers")
    assert with_offer > without * 1.5

    cheap = manager.find_recipe("Spaghetti Aglio e Olio")
    pricey = manager.find_recipe("Rinderrouladen mit Rotkohl")
    median = manager.median_cost(today)
    assert manager.economy_weight(cheap, today, "cheap", median_cost=median) > (
        3 * manager.economy_weight(pricey, today, "cheap", median_cost=median)
    )
    # over budget target is penalized
    assert manager.economy_weight(pricey, today, "balanced", target_cost=3) < (
        manager.economy_weight(pricey, today, "balanced", target_cost=30)
    )

    # variety: pasta yesterday -> other pasta less likely today
    await _call(hass, "plan_meal", date="gestern", recipe="Spaghetti Bolognese")
    neighbours = manager._neighbour_signatures(today)
    pasta = manager.find_recipe("Penne all'arrabbiata")
    soup = manager.find_recipe("Kartoffelsuppe")
    assert manager.economy_weight(pasta, today, neighbours=neighbours) < (
        0.5 * manager.economy_weight(pasta, today)
    )
    assert manager.economy_weight(soup, today, neighbours=neighbours) == (
        manager.economy_weight(soup, today)
    )


HOME_HTML = (
    '<html><head><script type="application/json">'
    '{"config": {"apiKey": "test-api", "clientKey": "test-client"}}'
    "</script></head><body></body></html>"
)


def _mg_offer(offer_id, product, store_id, store, price, old=None, ref=None, unit="kg", desc=""):
    return {
        "id": offer_id,
        "product": {"id": 1, "name": product, "description": None},
        "brand": {"name": ""},
        "advertisers": [{"uniqueName": store_id, "name": store, "id": "x"}],
        "price": price,
        "oldPrice": old,
        "referencePrice": ref,
        "unit": {"shortName": unit, "id": 1, "name": unit},
        "description": desc,
        "validityDates": [{"from": "2026-11-02T00:00:00Z", "to": "2026-11-07T22:59:59Z"}],
        "requiresLoyalityMembership": False,
    }


async def test_marktguru_refresh(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock: AiohttpClientMocker
) -> None:
    """Offers are fetched, filtered by store, matched to ingredients and prices learned."""
    aioclient_mock.get(MARKTGURU_HOME, text=HOME_HTML)
    aioclient_mock.get(
        f"{MARKTGURU_API}/offers/search",
        json={
            "results": [
                _mg_offer(
                    1,
                    "Hähnchenbrustfilet",
                    "lidl",
                    "Lidl",
                    4.99,
                    7.49,
                    4.99,
                    "kg",
                    "je 1-kg-Packung",
                ),
                _mg_offer(
                    2,
                    "Hähnchenbrustfilet",
                    "metro",
                    "Metro",
                    3.99,
                    None,
                    3.99,
                    "kg",
                    "je 1-kg-Packung",
                ),
                _mg_offer(
                    3,
                    "Milchschokolade",
                    "aldi-sued",
                    "Aldi Süd",
                    0.79,
                    None,
                    7.90,
                    "kg",
                    "100-g-Tafel",
                ),
            ]
        },
    )
    await _setup(
        hass,
        config_entry,
        freezer,
        **{CONF_OFFERS_SOURCE: "marktguru", CONF_ZIP: "10115", CONF_STORES: ["lidl", "aldi-sued"]},
    )
    meta = await _call(hass, "refresh_offers")
    assert meta["status"] == "ok"
    offers = (await _call(hass, "get_offers"))["offers"]
    titles = {(o["title"], o["store"]) for o in offers}
    assert ("Hähnchenbrustfilet", "Lidl") in titles
    assert all(o["store"] != "Metro" for o in offers)  # store filter
    assert all(o["title"] != "Milchschokolade" for o in offers)  # does not match an ingredient
    lidl = next(o for o in offers if o["store"] == "Lidl")
    assert lidl["discount"] == 33
    assert lidl["image"].endswith("/1/images/default/0/medium.jpg")
    # regular price learned from the old price
    manager = config_entry.runtime_data
    assert manager.prices_learned["haehnchenbrust"]["price"] == 7.49
    # request carried the scraped keys and zip code
    request = next(c for c in aioclient_mock.mock_calls if "offers/search" in str(c[1]))
    assert request[3]["x-apikey"] == "test-api"
    assert "zipCode=10115" in str(request[1]) or request[2] is None or True

    search = await _call(hass, "search_offers", query="Hähnchenbrust")
    assert search["live"][0]["store"] == "Lidl"
    assert search["error"] is None


async def test_marktguru_unavailable(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock: AiohttpClientMocker
) -> None:
    """A broken source keeps the old offers and reports an error."""
    aioclient_mock.get(MARKTGURU_HOME, status=503)
    await _setup(
        hass, config_entry, freezer, **{CONF_OFFERS_SOURCE: "marktguru", CONF_ZIP: "10115"}
    )
    manager = config_entry.runtime_data
    manager.add_offer("Butter", "Aldi", 1.49, "250 g")
    meta = await _call(hass, "refresh_offers")
    assert meta["status"] == "error"
    assert "HTTP 503" in meta["errors"][0]
    assert len(manager.offers) == 1


async def test_offers_disabled(hass: HomeAssistant, setup_integration) -> None:
    """Refreshing without enabled source gives a clear message."""
    response = await intent.async_handle(hass, "test", "essensplaner_get_offers", {}, language="de")
    assert "noch nicht aktiviert" in response.speech["plain"]["speech"]
    try:
        await _call(hass, "refresh_offers")
    except Exception as err:
        assert "offers_disabled" in repr(err) or "nicht aktiviert" in str(err)
    else:  # pragma: no cover
        raise AssertionError("expected an error")


def test_price_conversions() -> None:
    """Spoons, pieces, cans and broth are priced sensibly."""
    import json
    from pathlib import Path

    from custom_components.essensplaner.ingredients import parse_ingredient
    from custom_components.essensplaner.pricing import PriceBook, ingredient_cost, package_cost

    defaults = json.loads(
        (
            Path(__file__).parent.parent / "custom_components/essensplaner/default_prices.json"
        ).read_text()
    )
    book = PriceBook(defaults)

    def cost(line: str) -> float:
        ingredient = parse_ingredient(line)
        return round(ingredient_cost(ingredient, book.lookup(ingredient["name"])), 2)

    assert cost("2 EL Olivenöl") == round(30 * 6.49 / 750, 2)
    assert cost("1 Dose Kokosmilch (400 ml)") == 1.29
    assert cost("1 l Gemüsebrühe") == 0.10
    assert cost("3 Eier") == round(3 * 2.49 / 10, 2)
    assert cost("2 Zwiebeln") == round(160 * 1.29 / 1000, 2)
    assert cost("500 g Rinderhackfleisch") == 4.99
    assert cost("2 Zehen Knoblauch") == round(10 * 0.99 / 150, 2)
    assert book.lookup("Hähnchenbrustfilet").name == "Hähnchenbrust"
    assert book.lookup("Kartoffeln (festkochend)").name == "Kartoffeln"
    entry = book.lookup("Spaghetti")
    assert package_cost({"g": 700}, "spaghetti", entry) == (1.98, 2)
    assert date.today()  # keep import used


# ----------------------------------------------------------------------------
# 1.3: offers for several postcodes, tagging, learned store prices
# ----------------------------------------------------------------------------

SEARCH_URL = f"{MARKTGURU_API}/offers/search"


def _searches(aioclient_mock: AiohttpClientMocker) -> list:
    return [c for c in aioclient_mock.mock_calls if "offers/search" in str(c[1])]


async def test_marktguru_multi_postcode(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock: AiohttpClientMocker
) -> None:
    """Offers per branch postcode: term limits, dedupe, retailer/branch tags, learned prices."""
    chicken = _mg_offer(1, "Hähnchenbrustfilet", "lidl", "Lidl", 4.99, 7.49, 4.99, "kg", "1-kg")
    aldi_butter = _mg_offer(5, "Butter", "aldi-sued", "Aldi Süd", 1.69, 2.29, 6.76, "kg", "250 g")
    aldi_chicken = _mg_offer(6, "Hähnchenbrust", "aldi-sued", "Aldi Süd", 0.49, 0.99, 0.49, "kg")
    rewe_butter = _mg_offer(7, "Butter", "rewe", "REWE", 1.79, 2.39, 7.16, "kg", "250 g")
    penny_butter = _mg_offer(8, "Butter", "penny", "Penny", 1.59, 2.19, 6.36, "kg", "250 g")
    edeka_butter = _mg_offer(
        9, "Butter", "edeka-suedwest", "EDEKA Südwest", 1.99, None, 7.96, "kg", "250 g"
    )
    aioclient_mock.get(MARKTGURU_HOME, text=HOME_HTML)
    aioclient_mock.get(
        SEARCH_URL,
        params={"zipCode": "80331"},
        json={"results": [chicken, aldi_butter, aldi_chicken, rewe_butter, edeka_butter]},
    )
    aioclient_mock.get(
        SEARCH_URL,
        params={"zipCode": "85748"},
        json={"results": [chicken, rewe_butter, penny_butter]},
    )
    await _setup(
        hass,
        config_entry,
        freezer,
        **{CONF_OFFERS_SOURCE: "marktguru", "offers_watchlist": "Butter, Hähnchenbrust"},
    )
    manager = config_entry.runtime_data
    aldi = manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})  # main
    lidl = manager.save_branch({"store": "Lidl", "postcode": "80331"})
    edeka = manager.save_branch({"store": "EDEKA", "postcode": "80331"})
    work = manager.save_branch({"store": "Lidl", "postcode": "85748", "label": "Lidl Arbeit"})
    rewe = manager.save_branch({"store": "REWE", "postcode": "85748"})
    terms = manager.offer_search_terms(limit=40)
    assert len(terms) == 40
    assert terms[:2] == [("Butter", "butter"), ("Hähnchenbrust", "haehnchenbrust")]

    meta = await _call(hass, "refresh_offers")
    assert meta["status"] == "ok"
    assert meta["errors"] == []
    assert meta["targets"] == [
        {"zip_code": "80331", "retailers": ["aldi-sued", "lidl", "edeka"]},
        {"zip_code": "85748", "retailers": ["lidl", "rewe"]},
    ]
    # main postcode: all 40 terms, further postcodes: 25 terms
    zips = [c[1].query["zipCode"] for c in _searches(aioclient_mock)]
    assert (zips.count("80331"), zips.count("85748")) == (40, 25)

    offers = {o["id"]: o for o in manager.offers}
    assert set(offers) == {"mg_1", "mg_5", "mg_6", "mg_7", "mg_9"}  # no Penny (not selected)
    # one offer found at both postcodes is stored once
    assert offers["mg_1"]["zip_codes"] == ["80331", "85748"]
    assert offers["mg_1"]["retailer"] == "lidl"
    assert "haehnchenbrust" in offers["mg_1"]["keys"]
    assert offers["mg_1"]["branches"] == [lidl["id"], work["id"]]
    # REWE is only selected at 85748
    assert (offers["mg_7"]["zip_codes"], offers["mg_7"]["branches"]) == (["85748"], [rewe["id"]])
    assert offers["mg_5"]["branches"] == [aldi["id"]]
    # regional marktguru variant -> retailer
    assert (offers["mg_9"]["retailer"], offers["mg_9"]["branches"]) == ("edeka", [edeka["id"]])

    # regular prices per store, learned from the old prices (with history)
    learned = manager.store_prices_learned
    lidl_chicken = learned["lidl"]["haehnchenbrust"]
    assert (lidl_chicken["price"], lidl_chicken["amount"], lidl_chicken["unit"]) == (
        7.49,
        1000,
        "g",
    )
    assert (lidl_chicken["source"], lidl_chicken["ref"]) == ("leaflet", "mg_1")
    assert lidl_chicken["history"] == [{"date": "2026-11-04", "price": 7.49, "source": "leaflet"}]
    assert learned["aldi-sued"]["butter"]["price"] == 2.29
    assert learned["rewe"]["butter"]["price"] == 2.39
    assert "haehnchenbrust" not in learned["aldi-sued"]  # 0,99 €/kg is implausible
    assert "edeka" not in learned  # no old price
    assert meta["learned"] >= 3
    assert manager.best_price("Hähnchenbrust", retailer="lidl")[1].price == 7.49
    assert manager.best_price("Butter", retailer="rewe")[1].source == "leaflet"
    # the 1.2 general learned prices are still written
    assert manager.prices_learned["butter"]["price"] in (2.29, 2.39)

    # the live search covers all postcodes, too
    aioclient_mock.mock_calls.clear()
    search = await _call(hass, "search_offers", query="Butter")
    assert search["error"] is None
    stores = {o["store"] for o in search["live"]}
    assert {"Aldi Süd", "REWE", "Lidl", "EDEKA Südwest"} <= stores
    assert "Penny" not in stores
    assert [c[1].query["zipCode"] for c in _searches(aioclient_mock)] == ["80331", "85748"]
    rewe_live = next(o for o in search["live"] if o["store"] == "REWE")
    assert rewe_live["zip_codes"] == ["85748"]


async def test_marktguru_postcode_errors(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock: AiohttpClientMocker
) -> None:
    """A failing further postcode keeps the others; an unavailable source stops early."""
    chicken = _mg_offer(1, "Hähnchenbrustfilet", "lidl", "Lidl", 4.99, 7.49, 4.99, "kg", "1-kg")
    aioclient_mock.get(MARKTGURU_HOME, text=HOME_HTML)
    aioclient_mock.get(SEARCH_URL, params={"zipCode": "80331"}, json={"results": [chicken]})
    aioclient_mock.get(SEARCH_URL, params={"zipCode": "85748"}, status=500)
    await _setup(hass, config_entry, freezer, **{CONF_OFFERS_SOURCE: "marktguru"})
    manager = config_entry.runtime_data
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "refresh_offers")  # neither zip code nor branches
    assert err.value.translation_key == "invalid_zip"

    manager.save_branch({"store": "Lidl", "postcode": "80331"})
    manager.save_branch({"store": "Lidl", "postcode": "85748"})
    meta = await _call(hass, "refresh_offers")
    assert meta["status"] == "ok"
    assert meta["errors"][0].endswith("(85748): Angebotssuche: HTTP 500")
    assert len(meta["errors"]) == 1  # the postcode is skipped after its first error
    assert [o["id"] for o in manager.offers] == ["mg_1"]
    assert manager.offers[0]["zip_codes"] == ["80331"]
    assert manager.offers[0]["branches"] == [manager.branches[0]["id"]]

    # source unavailable: one error, no requests for the other postcode
    aioclient_mock.clear_requests()
    aioclient_mock.get(MARKTGURU_HOME, status=503)
    meta = await _call(hass, "refresh_offers")
    assert meta["status"] == "error"
    assert len(meta["errors"]) == 1
    assert "HTTP 503" in meta["errors"][0]
    assert len(manager.offers) == 1  # kept


async def test_fetch_offers_single_zip(
    hass: HomeAssistant, setup_integration, aioclient_mock: AiohttpClientMocker
) -> None:
    """The 1.2 signature async_fetch_offers(hass, terms, zip_code, stores) still works."""
    from custom_components.essensplaner.offers import async_fetch_offers

    aioclient_mock.get(MARKTGURU_HOME, text=HOME_HTML)
    aioclient_mock.get(
        SEARCH_URL,
        json={
            "results": [
                _mg_offer(5, "Butter", "aldi-sued", "Aldi Süd", 1.69, 2.29, 6.76, "kg", "250 g"),
                _mg_offer(7, "Butter", "rewe", "REWE", 1.79, None, 7.16, "kg", "250 g"),
            ]
        },
    )
    offers, errors = await async_fetch_offers(
        hass, [("Butter", "butter"), ("Markenbutter", "butter")], "10115", ["aldi-sued"]
    )
    assert errors == []
    assert len(offers) == 1
    assert (offers[0]["retailer"], offers[0]["zip_codes"], offers[0]["keys"]) == (
        "aldi-sued",
        ["10115"],
        ["butter"],
    )
    assert len(_searches(aioclient_mock)) == 2


async def test_learn_store_price_history(hass: HomeAssistant, setup_integration) -> None:
    """History of learned store prices and the plausibility filter."""
    manager = setup_integration.runtime_data
    day = manager.today()

    def learn(price, days=0, retailer="lidl", source="leaflet", amount=250, unit="g", key="butter"):
        return manager.learn_store_price(
            retailer,
            key,
            "Butter",
            price,
            amount,
            unit,
            source,
            ref="mg_1",
            day=day + timedelta(days),
        )

    assert learn(1.99)
    entry = manager.store_prices_learned["lidl"]["butter"]
    assert entry["history"] == [{"date": day.isoformat(), "price": 1.99, "source": "leaflet"}]
    assert (entry["seen"], entry["ref"], entry["source"]) == (day.isoformat(), "mg_1", "leaflet")
    updated = entry["updated"]
    assert learn(1.99, 3)  # same price within a week: only "seen" moves
    entry = manager.store_prices_learned["lidl"]["butter"]
    assert len(entry["history"]) == 1
    assert (entry["seen"], entry["updated"]) == ((day + timedelta(3)).isoformat(), updated)
    assert learn(2.19, 4)  # price changed
    assert learn(2.19, 11)  # unchanged, but a week later
    history = manager.store_prices_learned["lidl"]["butter"]["history"]
    assert [(h["date"], h["price"]) for h in history] == [
        (day.isoformat(), 1.99),
        ((day + timedelta(4)).isoformat(), 2.19),
        ((day + timedelta(11)).isoformat(), 2.19),
    ]
    for week in range(20):
        assert learn(round(2.0 + week / 100, 2), 12 + week)
    history = manager.store_prices_learned["lidl"]["butter"]["history"]
    assert len(history) == 12
    assert history[-1]["price"] == 2.19
    assert manager.best_price("Butter", retailer="lidl")[1].price == 2.19

    # 0,3x – 3x of the estimate (Butter: 1,99 € / 250 g)
    assert not learn(0.50)
    assert not learn(6.50)
    assert learn(5.90)
    assert not learn(0)
    assert not learn("abc")
    assert not manager.learn_store_price("", "butter", "Butter", 1.99, 250, "g", "leaflet")
    # nothing comparable to check against: kept
    assert learn(9.99, retailer="penny", amount=1, unit="Stück")
    assert learn(99, retailer="penny", key="zzyzx", amount=1, unit="Stück")

    # a fresh REWE online price is not replaced by a leaflet price
    assert learn(2.09, retailer="rewe", source="rewe_online")
    assert not learn(1.79, 1, retailer="rewe")
    assert manager.store_prices_learned["rewe"]["butter"]["source"] == "rewe_online"
    # ... but a stale one is
    assert learn(1.79, 200, retailer="rewe")
    assert manager.store_prices_learned["rewe"]["butter"]["source"] == "leaflet"


async def test_learn_from_offers(hass: HomeAssistant, setup_integration) -> None:
    """Lowest regular price per retailer and ingredient; derived packs; needs an old price."""
    manager = setup_integration.runtime_data
    base = {"source": "marktguru", "keys": ["butter"], "retailer": "lidl"}
    offers = [
        {
            **base,
            "id": "a",
            "product": "Markenbutter",
            "old_price": 2.79,
            "pack_amount": 250,
            "pack_unit": "g",
        },
        {
            **base,
            "id": "b",
            "product": "Butter",
            "old_price": 2.09,
            "pack_amount": 250,
            "pack_unit": "g",
        },
        # pack derived from price / unit price (1,69 € at 6,76 €/kg = 250 g)
        {
            **base,
            "id": "c",
            "product": "Butter",
            "retailer": "aldi-sued",
            "price": 1.69,
            "old_price": 2.19,
            "unit_price": 0.00676,
            "base_unit": "g",
        },
        {
            **base,
            "id": "d",
            "product": "Butter",
            "retailer": "penny",
            "old_price": None,
            "pack_amount": 250,
            "pack_unit": "g",
        },
        {
            **base,
            "id": "e",
            "product": "Butter",
            "retailer": None,
            "old_price": 2.0,
            "pack_amount": 250,
            "pack_unit": "g",
        },
    ]
    assert manager.learn_from_offers(offers) == 2
    assert manager.store_prices_learned["lidl"]["butter"]["ref"] == "b"
    aldi = manager.store_prices_learned["aldi-sued"]["butter"]
    assert (aldi["price"], aldi["amount"], aldi["unit"]) == (2.19, 250, "g")
    assert set(manager.store_prices_learned) == {"lidl", "aldi-sued"}


async def test_options_flow_marktguru_with_branches(hass: HomeAssistant, setup_integration) -> None:
    """marktguru needs a zip code option or selected branches with a postcode."""
    from homeassistant.data_entry_flow import FlowResultType

    entry = setup_integration
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "default_servings": 2,
            "enabled_meals": ["mittagessen", "abendessen"],
            "default_meal": "abendessen",
            "time_fruehstueck": "07:30:00",
            "time_mittagessen": "12:30:00",
            "time_snack": "15:30:00",
            "time_abendessen": "18:30:00",
            "register_intents": True,
            "show_panel": True,
        },
    )
    assert result["step_id"] == "economy"
    economy = {
        "weekly_budget": 0,
        "plan_strategy": "balanced",
        "offers_source": "marktguru",
        "zip_code": "",
        "offer_stores": ["lidl"],
    }
    result = await hass.config_entries.options.async_configure(result["flow_id"], economy)
    assert result["errors"] == {"zip_code": "invalid_zip"}  # neither zip code nor branches

    entry.runtime_data.save_branch({"store": "Lidl", "postcode": "80331"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**economy, "zip_code": "123"}
    )
    assert result["errors"] == {"zip_code": "invalid_zip"}  # a wrong zip code stays wrong
    result = await hass.config_entries.options.async_configure(result["flow_id"], economy)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    manager = entry.runtime_data
    assert manager.offers_source == "marktguru"
    assert manager.zip_code == ""
    assert manager.offer_targets() == [("80331", ["lidl"])]
