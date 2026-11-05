"""Store assignment stays up to date; picked prices, price comparison, planning (review fixes)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.essensplaner.const import DOMAIN


def _item(manager, summary: str) -> dict:
    return next(i for i in manager.shopping if i["summary"] == summary)


def _where(manager, summary: str) -> tuple[str | None, str | None]:
    item = _item(manager, summary)
    return item.get("retailer"), item.get("store_reason")


async def test_open_items_follow_branch_changes(hass: HomeAssistant, setup_integration) -> None:
    """First branch, new main branch, pausing and removing a branch re-assign open items."""
    manager = setup_integration.runtime_data
    for summary in ("250 g Butter", "1 l Milch"):
        manager.shopping_add(summary)
    assert "branch_id" not in _item(manager, "250 g Butter")  # 1.2: one list

    aldi = manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})  # first = main
    assert _where(manager, "250 g Butter") == ("aldi-sued", "main")
    selection = manager.shopping_overview("Hauptladen")["selection"]
    assert (selection["label"], selection["open"]) == ("Aldi Süd", 2)
    assert _item(manager, "1 l Milch")["description"].startswith("🏪 Aldi Süd")

    lidl = manager.save_branch({"store": "Lidl", "postcode": "80331"})
    manager.set_main_branch(lidl["id"])
    assert _where(manager, "250 g Butter") == ("lidl", "main")
    assert [(g["label"], g["main"], g["open"]) for g in manager.stores_summary()] == [
        ("Lidl", True, 2)
    ]

    # a manual choice of a paused branch waits until the branch is active again
    manager.set_shopping_store("Milch", "Aldi Süd")
    assert _where(manager, "1 l Milch") == ("aldi-sued", "manual")
    manager.save_branch({"id": aldi["id"], "selected": False})
    assert _where(manager, "1 l Milch") == ("lidl", "main")
    manager.save_branch({"id": aldi["id"], "selected": True})
    assert _where(manager, "1 l Milch") == ("aldi-sued", "manual")

    # removing the main branch: the other one becomes main, nothing lands in "Ohne Laden"
    manager.save_branch({"id": aldi["id"], "selected": True})
    manager.remove_branch(lidl["id"])
    assert manager.main_branch == aldi["id"]
    assert _where(manager, "250 g Butter") == ("aldi-sued", "main")
    assert [g["label"] for g in manager.stores_summary()] == ["Aldi Süd"]

    # the last branch removed: back to one list (1.2 price, no store)
    manager.remove_branch(aldi["id"])
    butter = _item(manager, "250 g Butter")
    assert "branch_id" not in butter and "store_reason" not in butter
    assert (butter["price"], butter["description"]) == (1.99, "")


async def test_offers_and_prices_move_open_items(hass: HomeAssistant, setup_integration) -> None:
    """New / ended offers and store prices re-assign open items (also overnight)."""
    manager = setup_integration.runtime_data
    manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})
    manager.save_branch({"store": "Lidl", "postcode": "80331"})
    manager.shopping_add("250 g Butter")
    manager.shopping_add("1 l Milch")

    offer = manager.add_offer("Butter", "Lidl", 1.29, "250 g", valid_to=date(2026, 11, 5))
    assert _where(manager, "250 g Butter") == ("lidl", "offer")
    manager.set_store_price("Lidl", "Milch", 0.69, 1000, "ml")  # 0,30 € / 30 % cheaper
    assert _where(manager, "1 l Milch") == ("lidl", "cheaper")
    manager.remove_store_price("Lidl", "Milch")
    assert _where(manager, "1 l Milch") == ("aldi-sued", "main")

    # the offer ended: after midnight the butter goes back to the main branch
    tz = dt_util.get_time_zone("Europe/Berlin")
    night = datetime(2026, 11, 6, 0, 1, 0, tzinfo=tz)
    async_fire_time_changed(hass, night)  # not yet: the clock still says 4 Nov
    await hass.async_block_till_done()
    assert _where(manager, "250 g Butter") == ("lidl", "offer")

    manager_today = manager.today
    manager.today = lambda: date(2026, 11, 6)  # type: ignore[method-assign]
    try:
        async_fire_time_changed(hass, night + timedelta(days=1))
        await hass.async_block_till_done()
        butter = _item(manager, "250 g Butter")
        assert (butter["retailer"], butter["offer"], butter["price"]) == ("aldi-sued", None, 1.99)
        assert "🏷️" not in butter["description"]
        assert offer["id"] not in [o["id"] for o in manager.offers]
    finally:
        manager.today = manager_today  # type: ignore[method-assign]


async def test_picked_offer_ends(hass: HomeAssistant, setup_integration) -> None:
    """A price picked from an offer counts while the offer is valid, then the store's prices."""
    manager = setup_integration.runtime_data
    aldi = manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})
    manager.save_branch({"store": "Lidl", "postcode": "80331"})
    manager.set_store_price("Lidl", "Butter", 1.49, 250, "g")
    offer = manager.add_offer("Butter", "Aldi Süd", 0.99, "250 g", valid_to=date(2026, 11, 5))
    item = manager.shopping_add(
        "Butter", store=aldi["id"], price=0.99, pack="250 g", offer_id=offer["id"]
    )
    assert (item["retailer"], item["price"], item["offer"]["id"]) == (
        "aldi-sued",
        0.99,
        offer["id"],
    )

    manager.today = lambda: date(2026, 11, 8)  # type: ignore[method-assign]
    manager.new_day()
    assert item["offer"] is None
    assert (item["retailer"], item["price"]) == ("aldi-sued", 1.99)  # manual store choice
    manager.set_shopping_store("Butter", "automatisch")
    assert (item["retailer"], item["store_reason"], item["price"]) == ("lidl", "cheaper", 1.49)


async def test_picked_live_offer(hass: HomeAssistant, setup_integration) -> None:
    """A leaflet offer of the live search (not saved) is used until it ends."""
    manager = setup_integration.runtime_data
    manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})
    lidl = manager.save_branch({"store": "Lidl", "postcode": "80331"})
    live = {
        "id": "mg_77",
        "title": "Weidebutter",
        "product": "Weidebutter",
        "store": "Lidl",
        "store_id": "lidl",
        "retailer": "lidl",
        "price": 1.19,
        "pack_amount": 250,
        "pack_unit": "g",
        "valid_from": "2026-11-02",
        "valid_to": "2026-11-07",
        "source": "marktguru",
    }
    manager._live_cache[("butter", "80331")] = (dt_util.utcnow().timestamp(), [live])
    item = manager.shopping_add(
        "Weidebutter", store=lidl["id"], price=1.19, pack="250 g", offer_id="mg_77"
    )
    assert (item["retailer"], item["price"], item["offer"]["id"]) == ("lidl", 1.19, "mg_77")
    assert item["chosen"]["offer"]["valid_to"] == "2026-11-07"
    manager.today = lambda: date(2026, 11, 8)  # type: ignore[method-assign]
    manager.assign_shopping_stores()
    assert (item["price"], item["offer"]) == (1.99, None)


async def test_price_without_pack(hass: HomeAssistant, setup_integration) -> None:
    """A picked price without pack is the price of the usual pack (not of "1 Stück")."""
    manager = setup_integration.runtime_data
    aldi = manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})
    offer = manager.add_offer("Rinderhackfleisch", "Aldi Süd", 4.49)
    item = manager.shopping_add(
        "500 g Rinderhackfleisch", store=aldi["id"], price=4.49, offer_id=offer["id"]
    )
    assert (item["price"], item["packs"]) == (4.49, 1)
    item = manager.shopping_add("500 g Tomaten", price=1.29)
    assert (item["price"], item["packs"]) == (1.29, 1)
    assert (item["chosen"]["amount"], item["chosen"]["unit"]) == (500, "g")


async def test_compare_bigger_offer_pack(hass: HomeAssistant, setup_integration) -> None:
    """Without an amount the cheapest price per kg counts, also for a bigger offer pack."""
    manager = setup_integration.runtime_data
    manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})
    manager.save_branch({"store": "Lidl", "postcode": "80331"})
    manager.set_store_price("Aldi Süd", "Butter", 1.69, 250, "g")
    manager.set_store_price("Lidl", "Butter", 1.79, 250, "g")
    manager.add_offer("Butter", "Lidl", 2.99, "500 g")
    result = manager.compare_prices("Butter")
    cheapest = result["cheapest"]
    assert (cheapest["retailer"], cheapest["price"], cheapest["pack"]) == ("lidl", 2.99, "500 g")
    assert cheapest["offer"] is not None
    assert manager.compare_prices("250 g Butter")["cheapest"]["retailer"] == "aldi-sued"


async def test_offer_of_another_branch_of_a_chain(hass: HomeAssistant, setup_integration) -> None:
    """An offer found only at the second REWE (near work) is used for the store split."""
    manager = setup_integration.runtime_data
    manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})
    manager.save_branch({"store": "REWE", "postcode": "80331", "label": "REWE Zuhause"})
    work = manager.save_branch({"store": "REWE", "postcode": "85748", "label": "REWE Arbeit"})
    offer = {
        "id": "mg_5",
        "title": "Butter",
        "product": "Butter",
        "store": "REWE",
        "store_id": "rewe",
        "retailer": "rewe",
        "price": 1.19,
        "pack_amount": 250,
        "pack_unit": "g",
        "valid_from": "2026-11-02",
        "valid_to": "2026-11-08",
        "source": "marktguru",
        "keys": ["butter"],
        "zip_codes": ["85748"],
    }
    manager.replace_source_offers("marktguru", [offer], {"status": "ok"})
    assert manager.offers[0]["branches"] == [work["id"]]
    manager.shopping_add("250 g Butter")
    item = _item(manager, "250 g Butter")
    assert (item["branch_id"], item["store_reason"], item["price"]) == (work["id"], "offer", 1.19)
    assert item["store_label"] == "REWE Arbeit"


async def test_auto_plan_never_repeats_a_planned_dish(
    hass: HomeAssistant, setup_integration, monkeypatch
) -> None:
    """A dish planned in the same week is not planned again (even if it is the favourite)."""
    manager = setup_integration.runtime_data
    lasagne = manager.get_recipe_by_name("Lasagne")
    weight = manager.economy_weight
    monkeypatch.setattr(
        manager,
        "economy_weight",
        lambda recipe, *a, **kw: 1e9 if recipe["id"] == lasagne["id"] else weight(recipe, *a, **kw),
    )
    tomorrow = manager.today() + timedelta(days=1)
    manager.plan_meal(tomorrow, "abendessen", recipe=lasagne)
    planned = manager.auto_plan(manager.today(), 7)
    assert len(planned) == 6
    assert "Lasagne" not in [p["title"] for p in planned]
    # overwrite: tomorrow's Lasagne is replaced, so it may be planned again
    planned = await hass.services.async_call(
        DOMAIN,
        "auto_plan",
        {"start_date": "morgen", "days": 1, "overwrite": True},
        blocking=True,
        return_response=True,
    )
    assert [p["title"] for p in planned["planned"]] == ["Lasagne"]


async def test_article_search_puts_the_article_first(
    hass: HomeAssistant, setup_integration, monkeypatch
) -> None:
    """Offers for the typed article come before "Butterkäse" & co, also live ones."""
    from custom_components.essensplaner import articles

    manager = setup_integration.runtime_data
    manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})
    offer = manager.add_offer("Deutsche Markenbutter", "Aldi Süd", 1.39, "250 g")
    assert "butter" in offer["keys"]
    titles = [r["title"] for r in manager.search_articles("Butter")]
    assert titles[:2] == ["Deutsche Markenbutter", "Butter"]
    assert titles.index("Butterkäse") > 1

    names = [
        "Butterkäse",
        "Butterzopf",
        "ja! Butterkekse",
        "Buttermilch",
        "Butterbrezel",
        "Buttergebäck",
        "Butterspätzle",
        "Butterkeks Mini",
        "Buttercroissant",
        "Erdnussbutter",
        "Deutsche Markenbutter",
        "Süßrahmbutter",
    ]

    async def provider(manager, query, branch, retailer):
        return [
            {
                "id": f"live_{n}",
                "title": name,
                "product": name,
                "store": "Aldi Süd",
                "store_id": "aldi-sued",
                "retailer": "aldi-sued",
                "price": 1.0 + n / 10,
                "source": "marktguru",
            }
            for n, name in enumerate(names)
        ]

    monkeypatch.setitem(articles.LIVE_PROVIDERS, "aldi-sued", provider)
    monkeypatch.setattr(articles, "LIVE_MIN_INTERVAL", 0)
    response = await manager.async_search_articles_live("Butter", limit=10)
    live = [r["title"] for r in response["results"]]
    assert set(live[:2]) == {"Deutsche Markenbutter", "Süßrahmbutter"}  # not cut off
    assert len(live) == 10
