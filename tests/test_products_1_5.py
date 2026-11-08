"""1.5 phase P2: the product database (products.py).

Identity (stable chain ids, signatures, twins), ingest from the offer catalog, the online
price refresh, the live article search, receipts and the shopping list, prices and the
product choice, pruning and caps, views, websockets, services, seeding, storage and
diagnostics.

All stores, addresses, postcodes and most brands are fictional (Musterstadt, 12345,
Lindenweg; "Bergland", "Sonnenhof"); the offer shapes are those of the marktguru / EDEKA /
ALDI SÜD / REWE fixtures."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import json
from pathlib import Path
import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.essensplaner import aldi, articles, edeka, products as products_module
from custom_components.essensplaner.aldi import SEARCH_URL as ALDI_SEARCH_URL
from custom_components.essensplaner.catalog import async_rematch_catalog
from custom_components.essensplaner.const import (
    CONF_ALDI_ONLINE,
    CONF_EDEKA_OFFERS,
    CONF_OFFERS_SOURCE,
    CONF_WATCHLIST,
    DOMAIN,
)
from custom_components.essensplaner.diagnostics import async_get_config_entry_diagnostics
from custom_components.essensplaner.edeka import OFFERS_URL as EDEKA_OFFERS_URL
from custom_components.essensplaner.ingredients import normalize_ingredient
from custom_components.essensplaner.products import (
    MAX_PRODUCTS,
    PICK_BOUGHT,
    PICK_PICKED,
    ProductStore,
    async_ingest_offers,
    best_for,
    choose_for_item,
    core_name,
    ingest_offer,
    ingest_receipt,
    ingest_shop_products,
    product_alternatives,
    product_detail,
    product_entry,
    product_to_recipe,
    products_view,
    protected_ids,
    prune_products,
    record_pick,
    save_manual,
    set_favorite,
    signature,
    stable_id,
)
from custom_components.essensplaner.receipts import async_save_receipt
from custom_components.essensplaner.retailers import is_store_brand, retailer_name

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime.fromisoformat("2026-11-04T10:00:00+01:00")  # Wednesday
TODAY = date(2026, 11, 4)
ALDI_STORE = "B999"  # a made-up service point


def _load(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def no_delays(monkeypatch) -> None:
    """No politeness delays (the clock is frozen), few search terms."""
    monkeypatch.setattr(aldi, "REQUEST_DELAY", 0)
    monkeypatch.setattr(aldi, "MAX_TERMS", 3)
    monkeypatch.setattr(edeka, "REQUEST_DELAY", 0)
    monkeypatch.setattr(articles, "LIVE_MIN_INTERVAL", 0)


def _offer(
    oid: str,
    product: str,
    price: float,
    *,
    brand: str = "",
    retailer: str = "lidl",
    pack: tuple[float, str] | None = (250, "g"),
    old: float | None = None,
    keys: tuple[str, ...] = ("butter",),
    valid_from: str | None = "2026-11-02",
    valid_to: str | None = "2026-11-07",
    kind: str | None = "food",
    source: str = "marktguru",
    **extra: Any,
) -> dict[str, Any]:
    """An offer in the catalog's format (like a normalized marktguru offer)."""
    data: dict[str, Any] = {
        "id": oid,
        "title": f"{brand} {product}".strip(),
        "product": product,
        "brand": brand,
        "description": "",
        "store": retailer_name(retailer),
        "store_id": retailer,
        "retailer": retailer,
        "price": price,
        "old_price": old,
        "pack_amount": pack[0] if pack else None,
        "pack_unit": pack[1] if pack else None,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "image": f"https://cdn.example.org/{oid}.webp",
        "keys": list(keys),
        "source": source,
        "zip_codes": ["12345"],
    }
    if kind is not None:
        data["kind"] = kind
    data.update(extra)
    return data


def _shop(
    product_id: str,
    name: str,
    price: float,
    *,
    brand: str = "",
    retailer: str = "rewe",
    pack: tuple[float, str] = (250, "g"),
    regular: float | None = None,
) -> dict[str, Any]:
    """A product of an online shop search (like rewe.parse_product())."""
    prefix = "rewe" if retailer == "rewe" else "aldi"
    return {
        "id": f"{prefix}_{product_id}",
        "product_id": product_id,
        "title": name,
        "product": name,
        "brand": brand,
        "description": "",
        "store": retailer_name(retailer),
        "store_id": retailer,
        "retailer": retailer,
        "price": price,
        "regular_price": regular,
        "old_price": None,
        "unit_price": round(price / pack[0], 6),
        "base_unit": "g" if pack[1] == "g" else pack[1],
        "pack_amount": pack[0],
        "pack_unit": pack[1],
        "valid_from": None,
        "valid_to": None,
        "image": f"https://img.example.org/{product_id}.jpg",
        "source": "rewe_online" if retailer == "rewe" else "aldi_online",
    }


def _branches(manager: Any) -> dict[str, dict[str, Any]]:
    """Three fictional branches in Musterstadt (Lidl is the main branch)."""
    result = {}
    for store, street in (
        ("Lidl", "Lindenweg 1"),
        ("REWE", "Lindenweg 3"),
        ("Aldi Süd", "Lindenweg 5"),
    ):
        saved = manager.save_branch(
            {"store": store, "street": street, "postcode": "12345", "city": "Musterstadt"}
        )
        result[saved["retailer"]] = saved
    return result


async def _ws(hass: HomeAssistant, hass_ws_client, command: str, **data: Any) -> dict[str, Any]:
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/{command}", **data})
    return await client.receive_json()


async def _call(hass: HomeAssistant, service: str, **data: Any) -> Any:
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry, freezer, **options: Any) -> Any:
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(NOW)
    assert await async_setup_component(hass, "homeassistant", {})
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry.runtime_data


# ----------------------------------------------------------------------
# Identity
# ----------------------------------------------------------------------


def test_signature_stable_ids_and_store_brands() -> None:
    """Core name without brand, pack and filler words; stable ids of REWE / ALDI SÜD;
    the chains' own brands."""
    assert core_name("Bergland Butter je 250-g-Packung", "Bergland") == "butter"
    assert core_name("Joghurt, versch. Sorten", "") == "joghurt"
    assert core_name("ja! Deutsche Markenbutter 250g", "ja!") == "deutsche markenbutter"
    assert signature("Butter 250 g", "Bergland", (250.0, "g")) == "bergland|butter|250g"
    assert signature("Deutsche Markenbutter", "ja!", (250.0, "g")) == signature(
        "ja! Deutsche Markenbutter 250g", "ja!", (250.0, "g")
    )
    assert signature("Butter", "Bergland", (250, "g")) != signature(
        "Butter", "Bergland", (500, "g")
    )
    assert stable_id({"id": "aldi_000000000000202682"}, "aldi-sued") == "000000000000202682"
    assert stable_id({"product_id": "8-AB12"}, "rewe") == "8-AB12"
    assert stable_id({"id": "rewe_8-AB12"}, "rewe") == "8-AB12"
    assert stable_id({"id": "mg_123"}, "lidl") is None
    assert stable_id({"id": "edeka_6447725"}, "edeka") is None
    for brand in ("ja!", "Milsani", "GUT&GÜNSTIG", "K-Classic Bio", "Gut Bio", "Balea"):
        assert is_store_brand(brand), brand
    for brand in ("Bergland", "Sonnenhof", "", None):
        assert not is_store_brand(brand), brand
    assert is_store_brand("Lidl", "lidl") and is_store_brand("EDEKA Bio")
    # an ingredient keeps the product it is bought as
    assert (
        normalize_ingredient({"name": "Pizza", "amount": 1, "product_id": "lidl:s1"})["product_id"]
        == "lidl:s1"
    )
    assert "product_id" not in normalize_ingredient({"name": "Pizza", "product_id": ""})


async def test_offer_identity_week_to_week_and_kinds(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The same product next week (new marktguru id) stays one product; ended, online-only,
    non-food and unknown products without an ingredient are not stored."""
    manager = setup_integration.runtime_data
    store: ProductStore = manager.products
    first = ingest_offer(
        manager, _offer("mg_1001", "Butter", 1.79, brand="Bergland", old=2.29), TODAY
    )
    assert first is not None and first["id"].startswith("lidl:s")
    assert first["regular"] == {"price": 2.29, "source": "leaflet", "seen": "2026-11-04"}
    assert first["offer"]["price"] == 1.79 and first["offer"]["id"] == "mg_1001"
    assert first["offer"]["zip_codes"] == ["12345"]
    assert first["image"] == "https://cdn.example.org/mg_1001.webp"
    assert (first["pack_amount"], first["pack_unit"], first["keys"]) == (250, "g", ["butter"])
    assert (first["category"], first["kind"]) == ("Milchprodukte & Eier", "food")
    assert sorted(h[2] for h in first["history"]) == ["o", "r"]
    # next week's leaflet: announced while this week's offer runs – this week's stays
    nxt = _offer(
        "mg_2002",
        "Butter",
        1.99,
        brand="Bergland",
        valid_from="2026-11-09",
        valid_to="2026-11-14",
    )
    assert ingest_offer(manager, nxt, TODAY)["id"] == first["id"]
    assert store.get(first["id"])["offer"]["id"] == "mg_1001"
    # Monday: this week's offer ended, the new one is the offer
    assert ingest_offer(manager, nxt, date(2026, 11, 9))["offer"]["id"] == "mg_2002"
    assert len(store.products) == 1
    assert store.by_offer("mg_2002")["id"] == first["id"]
    # what is not stored
    assert (
        ingest_offer(manager, _offer("mg_9", "Damen-Funktionsshirt", 9.99, kind="nonfood")) is None
    )
    assert (
        ingest_offer(manager, _offer("mg_10", "Butter", 1.5, brand="X", online_only=True)) is None
    )
    assert ingest_offer(manager, _offer("mg_11", "Butter", 1.5, valid_to="2026-11-01")) is None
    assert ingest_offer(manager, _offer("mg_12", "Classic", 1.5, kind="unknown", keys=())) is None
    unknown = ingest_offer(manager, _offer("mg_13", "Classic", 1.5, brand="Y", kind="unknown"))
    assert unknown is not None and unknown["keys"] == ["butter"]
    # a drugstore product is kept (Drogerie), classified when the source has no kind
    shampoo = ingest_offer(
        manager, _offer("mg_14", "Kräuter-Shampoo", 1.95, kind=None, keys=(), pack=(300, "ml"))
    )
    assert shampoo is not None and shampoo["kind"] == "drugstore"


async def test_stable_id_takes_over_and_twins(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """A leaflet product becomes the shop's product (its REWE id) – the ⭐ and picks follow,
    the old id still resolves; branded products are twins at other chains, own brands not."""
    manager = setup_integration.runtime_data
    store: ProductStore = manager.products
    leaflet = ingest_offer(
        manager,
        _offer("mg_501", "Deutsche Markenbutter", 1.69, brand="ja!", retailer="rewe", old=1.89),
    )
    old_id = leaflet["id"]
    set_favorite(manager, old_id, "butter")
    record_pick(manager, "butter", old_id, PICK_PICKED)
    assert (
        ingest_shop_products(
            manager,
            "rewe",
            [_shop("8-AB12", "ja! Deutsche Markenbutter 250g", 1.89, brand="ja!")],
            "butter",
            "rewe_online",
        )
        == 1
    )
    product = store.get("rewe:8-AB12")
    assert product is not None and product is store.get(old_id)
    assert product["stable_id"] == "8-AB12" and product["name"] == "ja! Deutsche Markenbutter 250g"
    assert product["regular"]["source"] == "rewe_online" and product["offer"]["id"] == "mg_501"
    assert store.favorites["butter"] == "rewe:8-AB12"
    assert store.picks["butter"][0][0] == "rewe:8-AB12"
    assert len(store.products) == 1
    # twins: a branded product at two chains, an own brand never
    lidl = ingest_offer(manager, _offer("mg_601", "Butter", 2.19, brand="Bergland"))
    rewe = ingest_offer(
        manager, _offer("mg_602", "Butter", 2.39, brand="Bergland", retailer="rewe")
    )
    assert [t["id"] for t in store.twins(lidl["id"])] == [rewe["id"]]
    milsani = ingest_offer(
        manager, _offer("mg_603", "Butter", 1.59, brand="Milsani", retailer="aldi-sued")
    )
    other = ingest_offer(manager, _offer("mg_604", "Butter", 1.59, brand="Milsani"))
    assert milsani["id"] != other["id"] and store.twins(milsani["id"]) == []


async def test_regular_price_trust_and_history_cap(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """A fresh own price is not replaced by a leaflet's normal price; the history keeps at
    most 8 prices."""
    manager = setup_integration.runtime_data
    _branches(manager)
    own = save_manual(
        manager,
        {"store": "Lidl", "name": "Butter", "brand": "Bergland", "pack": "250 g", "price": 2.49},
    )
    assert own["manual"] and own["regular"]["source"] == "user"
    again = ingest_offer(manager, _offer("mg_700", "Butter", 1.79, brand="Bergland", old=2.29))
    assert again["id"] == own["id"]
    assert again["regular"] == {"price": 2.49, "source": "user", "seen": "2026-11-04"}
    assert again["offer"]["price"] == 1.79
    for week in range(12):
        start = date(2026, 11, 2) + timedelta(days=7 * week)
        ingest_offer(
            manager,
            _offer(
                f"mg_{800 + week}",
                "Butter",
                1.5 + week / 100,
                brand="Bergland",
                valid_from=start.isoformat(),
                valid_to=(start + timedelta(days=5)).isoformat(),
            ),
            start,
        )
    history = manager.products.get(own["id"])["history"]
    assert len(history) == 8 and history == sorted(history)
    assert history[-1][1] == 1.61


# ----------------------------------------------------------------------
# Pruning and caps
# ----------------------------------------------------------------------


async def test_prune_keeps_protected_and_cap(
    hass: HomeAssistant, setup_integration: MockConfigEntry, monkeypatch
) -> None:
    """Products not seen for 120 days go – not own products, ⭐, picks or products on the
    shopping list / in recipes; above the cap the oldest without an offer go first."""
    manager = setup_integration.runtime_data
    store: ProductStore = manager.products
    old_day = TODAY - timedelta(days=200)
    old = {}
    for n, name in enumerate(("Quark", "Sahne", "Joghurt", "Kefir", "Skyr", "Ayran")):
        old[name] = ingest_offer(
            manager,
            _offer(
                f"mg_old{n}",
                name,
                0.99,
                brand="Sonnenhof",
                keys=(name.lower(),),
                valid_from=old_day.isoformat(),
                valid_to=(old_day + timedelta(days=5)).isoformat(),
            ),
            old_day,
        )
    set_favorite(manager, old["Quark"]["id"])
    record_pick(manager, "sahne", old["Sahne"]["id"], PICK_BOUGHT)
    manager.shopping_add("Joghurt")
    manager.shopping[-1]["chosen"] = {
        "name": "Joghurt",
        "price": 0.99,
        "product_id": old["Joghurt"]["id"],
    }
    recipe = manager.add_recipe(
        {
            "name": "Kefir-Shake",
            "ingredients": [
                {"name": "Kefir", "amount": 500, "unit": "ml", "product_id": old["Kefir"]["id"]}
            ],
        }
    )
    assert recipe["ingredients"][0]["product_id"] == old["Kefir"]["id"]
    store.get(old["Skyr"]["id"])["manual"] = True
    assert protected_ids(manager) >= {old["Joghurt"]["id"], old["Kefir"]["id"]}
    assert prune_products(manager) == 1
    assert old["Ayran"]["id"] not in store.products
    assert all(store.get(p["id"]) for k, p in old.items() if k != "Ayran")
    assert all("offer" not in p for p in store.products.values())  # ended offers dropped
    # the cap: 5 current products more than allowed – the oldest without offer go first
    monkeypatch.setattr(products_module, "MAX_PRODUCTS", 7)
    for n in range(5):
        ingest_offer(
            manager,
            _offer(f"mg_new{n}", f"Pudding {n}", 0.59, brand="Sonnenhof", keys=("pudding",)),
        )
    ingest_offer(
        manager,
        _offer("mg_seen", "Milchreis", 0.79, brand="Sonnenhof", keys=("milchreis",), valid_to=None),
        TODAY - timedelta(days=30),
    )
    store.get(store.by_offer("mg_seen")["id"]).pop("offer")
    prune_products(manager)
    assert len(store.products) == 7
    names = {p["name"] for p in store.products.values()}
    assert "Milchreis" not in names  # the oldest without an offer
    assert {"Quark", "Sahne", "Joghurt", "Kefir", "Skyr"} <= names  # protected


async def test_ingest_5000_offers_fast_and_capped(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """5000 different offers (a big catalog) are stored in chunks within a time budget;
    the database keeps MAX_PRODUCTS and stays small."""
    manager = setup_integration.runtime_data
    store: ProductStore = manager.products
    retailers = ["lidl", "rewe", "penny", "netto-marken-discount", "kaufland", "edeka"]
    names = [
        "Butter",
        "Milch",
        "Joghurt",
        "Käse",
        "Nudeln",
        "Reis",
        "Kaffee",
        "Tee",
        "Saft",
        "Brot",
    ]
    offers = [
        _offer(
            f"mg_{n}",
            f"{names[n % len(names)]} Sorte {n}",
            0.49 + (n % 300) / 100,
            brand=f"Marke{n % 40}",
            retailer=retailers[n % len(retailers)],
            pack=(100 + (n % 7) * 50, "g"),
            old=2.99 if n % 3 == 0 else None,
            keys=(names[n % len(names)].lower(),),
        )
        for n in range(5000)
    ]
    started = time.process_time()
    count = await async_ingest_offers(manager, offers)
    seconds = time.process_time() - started
    assert count == 5000
    print(f"ingest of 5000 offers: {seconds:.2f} s CPU")
    assert seconds < 5, f"ingest took {seconds:.1f} s"
    assert len(store.products) == MAX_PRODUCTS
    size = len(json.dumps(store.data, ensure_ascii=False))
    assert size < 2_500_000, size
    # the views stay quick
    started = time.process_time()
    view = products_view(manager, query="butter", sort="unit_price", limit=100)
    assert view["total"] > 100 and len(view["products"]) == 100
    assert time.process_time() - started < 3


# ----------------------------------------------------------------------
# Ingest hooks
# ----------------------------------------------------------------------


async def test_catalog_refresh_and_rematch_store_products(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock
) -> None:
    """ALDI SÜD's weekly offers of a catalog refresh become products with the ALDI sku as
    stable id; a rematch gives products the ingredients their offers got."""
    aioclient_mock.get(ALDI_SEARCH_URL, json=_load("aldi_weekly_offers"))
    manager = await _setup(
        hass, config_entry, freezer, **{CONF_ALDI_ONLINE: True, CONF_WATCHLIST: "Hackfleisch"}
    )
    manager.save_branch(
        {
            "store": "Aldi Süd",
            "street": "Lindenweg 5",
            "postcode": "12345",
            "aldi_service_point": ALDI_STORE,
        }
    )
    meta = await _call(hass, "refresh_prices", source="offers")
    assert meta["status"] == "ok", meta
    store: ProductStore = manager.products
    mince = store.get("aldi-sued:000000000000550925")
    assert mince is not None and mince["stable_id"] == "000000000000550925"
    assert mince["offer"]["price"] == 4.59 and mince["offer"]["source"] == "aldi_weekly"
    assert mince["regular"]["price"] == 5.79 and mince["regular"]["source"] == "aldi_online"
    assert mince["keys"] and mince["image"].startswith("https://")
    key = mince["keys"][0]
    assert "hackfleisch" in key
    assert mince["brand"] == "Meine Metzgerei"
    kinds = {p["name"]: p["kind"] for p in store.products.values()}
    assert kinds["Slipeinlagen, Cotton Feel Normal 56 Stück"] == "drugstore"
    assert all(p["retailer"] == "aldi-sued" for p in store.products.values())
    # a rematch: offers whose ingredients changed update their products
    bucket = next(iter(manager.catalog.buckets.values()))
    for offer in bucket["offers"]:
        if offer["id"] == "aldi_000000000000550925":
            offer["keys"] = []
    store._unindex(mince)
    mince["keys"] = []
    store._index(mince)
    assert await async_rematch_catalog(manager, force=True)
    assert key in store.get(mince["id"])["keys"]
    assert store.by_key(key) == [mince]


async def test_edeka_list_stored_in_background(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock
) -> None:
    """The EDEKA refresh stores its list in the catalog (put_source); the products follow
    in the background – non-food is never stored."""
    manager = await _setup(hass, config_entry, freezer, **{CONF_EDEKA_OFFERS: True})
    manager.save_branch(
        {
            "store": "EDEKA",
            "street": "Lindenweg 7",
            "postcode": "12345",
            "edeka_market_id": "2600099",
        }
    )
    aioclient_mock.get(EDEKA_OFFERS_URL, json=_load("edeka_offers"))
    status = await edeka.async_refresh_edeka_offers(hass, manager, force=True)
    assert status["status"] == "ok"
    await hass.async_block_till_done(wait_background_tasks=True)
    store: ProductStore = manager.products
    names = {p["name"]: p for p in store.products.values()}
    chicken = names["Frisches Hähnchenbrustfilet"]
    assert chicken["retailer"] == "edeka" and chicken["offer"]["source"] == "edeka"
    assert chicken["offer"]["valid_to"] == "2026-11-07"
    assert all(p["kind"] != "nonfood" for p in store.products.values())
    assert len(store.products) >= 10


async def test_aldi_price_refresh_and_live_search_store_shop_products(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock
) -> None:
    """The ALDI SÜD price refresh stores the fitting products of every search (≤ 6 per
    term, shop price as regular price, a reduction as offer); the live article search
    stores its shop hits (≤ 10)."""
    manager = await _setup(
        hass,
        config_entry,
        freezer,
        **{CONF_ALDI_ONLINE: True, CONF_WATCHLIST: "Butter, Milch, Eier"},
    )
    manager.save_branch(
        {
            "store": "Aldi Süd",
            "street": "Lindenweg 5",
            "postcode": "12345",
            "aldi_service_point": ALDI_STORE,
        }
    )
    for term, name in (
        ("Butter", "aldi_search_butter"),
        ("Milch", "aldi_search_milch"),
        ("Eier", "aldi_search_eier"),
    ):
        aioclient_mock.get(ALDI_SEARCH_URL, params={"q": term}, json=_load(name))
    status = await aldi.async_refresh_aldi_prices(hass, manager, force=True)
    assert status["status"] == "ok"
    store: ProductStore = manager.products
    butter = store.get("aldi-sued:000000000000202682")
    assert butter is not None
    assert butter["regular"] == {"price": 1.19, "source": "aldi_online", "seen": "2026-11-04"}
    assert butter["offer"]["price"] == 1.15 and butter["offer"]["valid_to"] == "2026-11-07"
    assert butter["brand"] == "Milsani" and "butter" in butter["keys"]
    for key in ("butter", "milch", "ei"):
        found = store.by_key(key)
        assert 1 <= len(found) <= 6, key
    assert all(p["kind"] != "nonfood" for p in store.products.values())
    before = len(store.products)

    aioclient_mock.clear_requests()
    aioclient_mock.get(ALDI_SEARCH_URL, json=_load("aldi_search_hackfleisch"))
    response = await manager.async_search_articles_live("Hackfleisch")
    assert response["live"] and response["results"]
    mince = store.by_key("hackfleisch")
    assert 1 <= len(mince) <= 10 and len(store.products) > before
    assert all(p["sources"][-1] == "aldi_online" for p in mince)


async def test_receipt_links_products_and_counts_bought(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """A receipt line within ±15 % of a known product of the chain is that product (its
    price becomes the receipt price), others become receipt products; each is bought once
    (saving the receipt again counts nothing)."""
    manager = setup_integration.runtime_data
    _branches(manager)
    store: ProductStore = manager.products
    known = ingest_offer(
        manager,
        _offer("mg_901", "Butter", 1.79, brand="Bergland", old=2.29, valid_to="2026-11-02")
        | {"valid_from": "2026-10-27"},
        date(2026, 10, 30),
    )
    data = {
        "store": "Lidl",
        "date": "2026-11-03",
        "items": [
            {
                "name": "BERGLAND BUTTER 250G",
                "key": "butter",
                "price": 2.25,
                "amount": 250,
                "unit": "g",
            },
            {
                "name": "GOUDA JUNG SCHEIB",
                "key": "gouda",
                "price": 1.79,
                "amount": 150,
                "unit": "g",
            },
        ],
    }
    result = await async_save_receipt(manager, data)
    assert result["saved"] == 2
    butter = store.get(known["id"])
    assert butter["regular"] == {"price": 2.25, "source": "receipt", "seen": "2026-11-03"}
    assert "receipt" in butter["sources"]
    gouda = store.by_key("gouda", ["lidl"])
    assert len(gouda) == 1 and gouda[0]["name"] == "Gouda"
    assert gouda[0]["description"] == "GOUDA JUNG SCHEIB"
    assert (gouda[0]["pack_amount"], gouda[0]["pack_unit"]) == (150, "g")
    assert store.picks["butter"] == [[butter["id"], 1, "2026-11-03", PICK_BOUGHT]]
    assert store.picks["gouda"][0][3] == PICK_BOUGHT
    # corrected and saved again: no second purchase
    await async_save_receipt(manager, {**data, "id": result["receipt"]["id"]})
    assert store.picks["butter"][0][1] == 1
    # far off the price (+40 %): another product
    ingest_receipt(
        manager,
        {
            "retailer": "lidl",
            "date": "2026-11-04",
            "items": [
                {
                    "name": "BUTTER",
                    "key": "butter",
                    "price": 3.19,
                    "amount": 250,
                    "unit": "g",
                    "status": "saved",
                }
            ],
        },
    )
    assert len(store.by_key("butter", ["lidl"])) == 2


async def test_shopping_pick_and_bought(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """An offer put on the shopping list: its product is picked for the ingredient (also a
    catalog offer that was not stored yet); ticking the item off counts as bought."""
    manager = setup_integration.runtime_data
    _branches(manager)
    store: ProductStore = manager.products
    manager.catalog.set_bucket(
        "marktguru", "lidl", "12345", [_offer("mg_3003", "Butter", 1.79, brand="Bergland")], "ok"
    )
    item = manager.shopping_add("Butter", offer_id="mg_3003")
    product = store.by_offer("mg_3003")
    assert product is not None
    assert item["chosen"]["product_id"] == product["id"]
    assert store.picks["butter"] == [[product["id"], 1, "2026-11-04", PICK_PICKED]]
    manager.shopping_update(item["uid"], status="completed")
    assert store.picks["butter"] == [[product["id"], 2, "2026-11-04", PICK_BOUGHT]]
    manager.shopping_update(item["uid"], status="completed")  # no change: nothing counted
    assert store.picks["butter"][0][1] == 2


# ----------------------------------------------------------------------
# Prices and the product choice
# ----------------------------------------------------------------------


async def test_prices_and_choice_order(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """product_entry (offer, fresh regular price, nothing when stale or without pack),
    best_for (only the product itself, cheapest for the amount) and choose_for_item
    (recipe product → ⭐ → pick → cheapest)."""
    manager = setup_integration.runtime_data
    _branches(manager)
    store: ProductStore = manager.products
    small = ingest_offer(manager, _offer("mg_1", "Butter", 1.79, brand="Bergland", old=2.19))
    big = save_manual(
        manager,
        {"store": "Lidl", "name": "Butter", "brand": "Sonnenhof", "pack": "500 g", "price": 3.29},
    )
    cookies = ingest_offer(
        manager, _offer("mg_2", "Butterkekse", 0.89, brand="Sonnenhof", pack=(200, "g"))
    )
    assert "butter" in cookies["keys"]  # a wrong ingredient of the offer
    entry = product_entry(small, TODAY)
    assert (entry.price, entry.amount, entry.unit, entry.source) == (1.79, 250, "g", "offer")
    assert entry.offer["product_id"] == small["id"] and entry.offer["old_price"] == 2.19
    entry = product_entry(small, date(2026, 11, 10))  # offer over: the regular price
    assert (entry.price, entry.source) == (2.19, "leaflet")
    assert product_entry(small, TODAY + timedelta(days=120)) is None  # stale
    no_pack = ingest_offer(manager, _offer("mg_3", "Butter", 1.99, brand="Wiesental", pack=None))
    assert product_entry(no_pack, TODAY) is None

    best = best_for(manager, "butter", "lidl", {"g": 500}, TODAY)
    assert best["product"]["id"] == big["id"] and best["price"] == 3.29
    best = best_for(manager, "butter", "lidl", {"g": 250}, TODAY)
    assert best["product"]["id"] == small["id"] and best["entry"].offer is not None
    assert best_for(manager, "butterkeks", "lidl", {}, TODAY) is None  # no such key

    item = {"key": "butter", "name": "Butter", "amounts": {"g": 250}, "source": "manual"}
    assert choose_for_item(manager, item, "lidl") == (small, "offer")
    for _ in range(2):
        record_pick(manager, "butter", big["id"], PICK_PICKED)
    assert choose_for_item(manager, item, "lidl") == (big, "picked")
    # a branded ⭐ of another chain is used through its twin here
    rewe = ingest_offer(manager, _offer("mg_4", "Butter", 2.39, brand="Bergland", retailer="rewe"))
    set_favorite(manager, rewe["id"], "butter")
    assert choose_for_item(manager, item, "lidl") == (small, "favorite")
    assert choose_for_item(manager, {**item, "product_id": big["id"]}, "lidl") == (big, "manual")
    assert choose_for_item(manager, item, "penny") == (None, None)
    assert store.favorites == {"butter": rewe["id"]}


# ----------------------------------------------------------------------
# Views
# ----------------------------------------------------------------------


async def test_products_view_filters_and_detail(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Filters (text, chain, branch, aisle, kind, ⭐ / offers / bought / own), sorting,
    pages, store and aisle counts; the detail with history, twins and ingredients."""
    manager = setup_integration.runtime_data
    branches = _branches(manager)
    butter = ingest_offer(manager, _offer("mg_1", "Butter", 1.79, brand="Bergland", old=2.29))
    twin = ingest_offer(manager, _offer("mg_2", "Butter", 2.09, brand="Bergland", retailer="rewe"))
    ingest_offer(
        manager,
        _offer("mg_3", "Kräuter-Shampoo", 1.95, kind="drugstore", keys=(), pack=(300, "ml")),
    )
    milk = save_manual(
        manager,
        {
            "store": "REWE",
            "name": "Vollmilch",
            "brand": "Sonnenhof",
            "pack": "1 l",
            "price": 1.15,
            "image": "https://img.example.org/milch.jpg",
        },
    )
    set_favorite(manager, milk["id"])

    view = products_view(manager)
    assert view["total"] == 4 and view["counts"]["products"] == 4
    assert [p["price"] for p in view["products"]] == sorted(p["price"] for p in view["products"])
    card = next(p for p in view["products"] if p["id"] == butter["id"])
    assert (card["title"], card["price"], card["old_price"], card["saving"]) == (
        "Bergland Butter",
        1.79,
        2.29,
        0.5,
    )
    assert card["on_offer"] and card["discount"] == 22 and card["pack"] == "250 g"
    assert card["unit_price"] == pytest.approx(1.79 / 250)
    assert card["branch_ids"] == [branches["lidl"]["id"]] and card["store"] == "Lidl"
    stores = {s["retailer"]: s["count"] for s in view["stores"]}
    assert stores == {"lidl": 2, "rewe": 2, "aldi-sued": 0}
    assert {c["name"] for c in view["categories"]} >= {"Milchprodukte & Eier"}

    assert [p["id"] for p in products_view(manager, query="bergland butter")["products"]] == [
        butter["id"],
        twin["id"],
    ]
    assert products_view(manager, retailers=["rewe"])["total"] == 2
    assert products_view(manager, branch_ids=[branches["lidl"]["id"]])["total"] == 2
    assert products_view(manager, kind="drugstore")["total"] == 1
    assert products_view(manager, kind="food")["total"] == 3
    assert products_view(manager, category="Drogerie & Körperpflege")["total"] == 1
    assert [p["id"] for p in products_view(manager, only="favorites")["products"]] == [milk["id"]]
    assert products_view(manager, only="manual")["products"][0]["manual"]
    assert products_view(manager, only="offers")["total"] == 3
    assert products_view(manager, only="bought")["total"] == 0
    names = [p["title"] for p in products_view(manager, sort="name")["products"]]
    assert names == sorted(names, key=str.lower)
    assert products_view(manager, sort="saving")["products"][0]["id"] == butter["id"]
    page = products_view(manager, sort="name", offset=1, limit=2)
    assert (page["total"], len(page["products"]), page["offset"]) == (4, 2, 1)

    detail = product_detail(manager, butter["id"])
    assert [t["id"] for t in detail["twins"]] == [twin["id"]]
    assert {h["kind"] for h in detail["history"]} == {"offer", "regular"}
    assert detail["keys"] == [{"key": "butter", "name": "Butter"}]
    with pytest.raises(ServiceValidationError) as err:
        product_detail(manager, "lidl:nope")
    assert err.value.translation_key == "product_not_found"


async def test_alternatives_and_recipe(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Products of a shopping item at all saved chains, cheapest for the needed amount;
    a ready meal saved as a recipe with the product as its ingredient."""
    manager = setup_integration.runtime_data
    _branches(manager)
    lidl = ingest_offer(manager, _offer("mg_1", "Butter", 1.79, brand="Bergland"))
    rewe = ingest_offer(
        manager, _offer("mg_2", "Butter", 3.39, brand="Sonnenhof", retailer="rewe", pack=(500, "g"))
    )
    aldi_ = ingest_offer(
        manager, _offer("mg_3", "Butter", 1.69, brand="Milsani", retailer="aldi-sued")
    )
    item = manager.shopping_add("500 g Butter")
    result = product_alternatives(manager, uid=item["uid"])
    assert result["key"] == "butter" and result["amounts"] == {"g": 500.0}
    assert [a["id"] for a in result["alternatives"]] == [aldi_["id"], rewe["id"], lidl["id"]]
    assert [a["cost"] for a in result["alternatives"]] == [3.38, 3.39, 3.58]
    by_key = product_alternatives(manager, key="Butter")
    assert by_key["alternatives"][0]["cost"] == 1.69  # one pack
    assert product_alternatives(manager, product_id=lidl["id"])["current"] == lidl["id"]

    pizza = ingest_offer(
        manager,
        _offer(
            "mg_4",
            "Steinofen-Pizza Salami",
            2.49,
            brand="Bergland",
            pack=(350, "g"),
            keys=("pizza",),
            kind="food",
        ),
    )
    recipe = product_to_recipe(manager, pizza["id"])
    assert recipe["name"] == "Bergland Steinofen-Pizza Salami"
    assert recipe["steps"] == ["Nach Packungsanleitung zubereiten."]
    assert recipe["tags"] == ["Fertiggericht"] and recipe["image"] == pizza["image"]
    ingredient = recipe["ingredients"][0]
    assert (ingredient["amount"], ingredient["unit"], ingredient["note"]) == (1, "Pck.", "350 g")
    assert ingredient["product_id"] == pizza["id"]
    assert manager.recipe_cost(recipe)["total"] > 0
    with pytest.raises(ServiceValidationError) as err:
        product_to_recipe(manager, pizza["id"])
    assert err.value.translation_key == "recipe_exists"


# ----------------------------------------------------------------------
# Websockets and services
# ----------------------------------------------------------------------


async def test_product_websockets(
    hass: HomeAssistant, setup_integration: MockConfigEntry, hass_ws_client
) -> None:
    """products, product_save (with errors), product_detail, product_favorite,
    product_alternatives, product_to_recipe and product_delete."""
    manager = setup_integration.runtime_data
    _branches(manager)
    events = []
    hass.bus.async_listen(f"{DOMAIN}_updated", lambda e: events.append(e.data["change"]))

    msg = await _ws(
        hass,
        hass_ws_client,
        "product_save",
        product={
            "store": "REWE",
            "name": "Tiefkühl-Pizza Margherita",
            "brand": "Sonnenhof",
            "pack": "320 g",
            "price": "2,19".replace(",", "."),
            "image": "https://img.example.org/pizza.jpg",
            "ingredient": "Pizza",
            "favorite": True,
        },
    )
    assert msg["success"], msg
    card = msg["result"]["product"]
    assert (card["retailer"], card["price"], card["pack"], card["manual"]) == (
        "rewe",
        2.19,
        "320 g",
        True,
    )
    assert card["favorite"] and card["favorite_keys"] == ["pizza"]
    await hass.async_block_till_done()
    assert "products" in events
    for product, code in (
        ({"store": "REWE"}, "name_required"),
        ({"name": "Pizza"}, "store_required"),
        ({"name": "Pizza", "store": "Musterkauf"}, "unknown_store"),
        (
            {"name": "Pizza", "store": "REWE", "image": "http://img.example.org/x.jpg"},
            "invalid_url",
        ),
        ({"name": "Pizza", "store": "REWE", "price": "gratis"}, "invalid_price"),
        ({"id": "rewe:nope", "name": "Pizza"}, "product_not_found"),
    ):
        msg = await _ws(hass, hass_ws_client, "product_save", product=product)
        assert not msg["success"] and msg["error"]["code"] == code, (product, msg)
        assert msg["error"]["message"]

    # change it: another price, no image
    msg = await _ws(
        hass,
        hass_ws_client,
        "product_save",
        product={"id": card["id"], "name": "Tiefkühl-Pizza Margherita", "price": 1.99, "image": ""},
    )
    assert msg["success"] and msg["result"]["product"]["price"] == 1.99
    assert (
        msg["result"]["product"]["image"] is None and msg["result"]["product"]["id"] == card["id"]
    )

    msg = await _ws(hass, hass_ws_client, "products", query="pizza", only="manual")
    assert msg["success"] and [p["id"] for p in msg["result"]["products"]] == [card["id"]]
    msg = await _ws(hass, hass_ws_client, "products", sort="cheapest")
    assert not msg["success"]  # an unknown sort
    msg = await _ws(hass, hass_ws_client, "product_detail", product_id=card["id"])
    assert msg["success"] and msg["result"]["favorite_for"] == ["pizza"]
    assert [h["price"] for h in msg["result"]["history"]] == [1.99]
    msg = await _ws(hass, hass_ws_client, "product_favorite", product_id=card["id"], favorite=False)
    assert msg["success"] and msg["result"] == {"key": "pizza", "product_id": None, "favorites": {}}
    msg = await _ws(hass, hass_ws_client, "product_alternatives", key="Pizza")
    assert msg["success"] and msg["result"]["alternatives"][0]["id"] == card["id"]
    msg = await _ws(hass, hass_ws_client, "product_alternatives", uid="nope")
    assert msg["error"]["code"] == "shopping_item_not_found"
    msg = await _ws(
        hass,
        hass_ws_client,
        "product_to_recipe",
        product_id=card["id"],
        tags=["Fertiggericht", "Hauptgericht"],
    )
    assert msg["success"] and msg["result"]["recipe"]["tags"] == ["Fertiggericht", "Hauptgericht"]
    msg = await _ws(hass, hass_ws_client, "product_delete", product_id=card["id"])
    assert msg["success"] and msg["result"] == {"deleted": card["id"]}
    msg = await _ws(hass, hass_ws_client, "product_delete", product_id=card["id"])
    assert msg["error"]["code"] == "product_not_found"
    assert "Artikel-Datenbank" in msg["error"]["message"]
    assert manager.products.products == {}


async def test_product_services_and_data_counts(
    hass: HomeAssistant, setup_integration: MockConfigEntry, hass_ws_client
) -> None:
    """search_products and save_product; the panel's data only carries counts."""
    manager = setup_integration.runtime_data
    _branches(manager)
    ingest_offer(manager, _offer("mg_1", "Butter", 1.79, brand="Bergland", old=2.29))
    ingest_offer(manager, _offer("mg_2", "Butter", 1.69, brand="Milsani", retailer="aldi-sued"))
    saved = await _call(
        hass,
        "save_product",
        store="Lidl",
        name="Vollmilch",
        pack="1 l",
        price=0.99,
        ingredient="Milch",
    )
    assert saved["product"]["keys"] == ["milch"] and saved["product"]["manual"]
    result = await _call(hass, "search_products", query="Butter")
    assert [p["price"] for p in result["products"]] == [1.69, 1.79]
    assert result["total"] == 2 and result["counts"]["products"] == 3
    result = await _call(hass, "search_products", query="Butter", store="Lidl")
    assert [p["retailer"] for p in result["products"]] == ["lidl"]
    result = await _call(hass, "search_products", only="manual", sort="name", count=1)
    assert [p["product"] for p in result["products"]] == ["Vollmilch"]
    with pytest.raises(ServiceValidationError):
        await _call(hass, "search_products", store="Musterkauf")
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "save_product", name="Quark")
    assert err.value.translation_key == "store_required"
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/data"})
    data = (await client.receive_json())["result"]
    assert data["products"]["products"] == 3 and data["products"]["manual"] == 1
    assert data["products"]["offers"] == 2


# ----------------------------------------------------------------------
# Seeding, storage, diagnostics
# ----------------------------------------------------------------------


async def test_seed_once_store_reload_and_remove(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, hass_storage
) -> None:
    """A 1.4 install: the database is filled once from the stored catalog, the learned
    REWE prices with their product id, the receipts of the last 90 days and the offer on
    the shopping list; kept over a reload (no second filling), removed with the entry."""
    entry_id = config_entry.entry_id
    offer = _offer("mg_71", "Butter", 1.79, brand="Bergland", old=2.29)
    live = _offer("mg_72", "Kaffee", 4.99, brand="Bergland", pack=(500, "g"), keys=())
    hass_storage[f"essensplaner.catalog.{entry_id}"] = {
        "version": 1,
        "data": {
            "buckets": {
                "marktguru|lidl|12345": {
                    "source": "marktguru",
                    "retailer": "lidl",
                    "zip_code": "12345",
                    "status": "ok",
                    "offers": [offer],
                }
            }
        },
    }
    hass_storage[f"essensplaner.{entry_id}"] = {
        "version": 1,
        "data": {
            "recipes": {},
            "plan": {},
            "starter_names": [],
            "data_version": 4,
            "shopping": [
                {
                    "uid": "u1",
                    "summary": "Kaffee",
                    "status": "needs_action",
                    "source": "manual",
                    "key": "kaffee",
                    "name": "Kaffee",
                    "amounts": {},
                    "chosen": {"name": "Kaffee", "price": 4.99, "offer_id": "mg_72", "offer": live},
                }
            ],
            "store_prices_learned": {
                "rewe": {
                    "milch": {
                        "name": "ja! H-Milch 1,5%",
                        "price": 1.09,
                        "amount": 1000,
                        "unit": "ml",
                        "source": "rewe_online",
                        "seen": "2026-11-01",
                        "ref": "8-MILCH1",
                    }
                }
            },
        },
    }
    hass_storage[f"essensplaner.receipts.{entry_id}"] = {
        "version": 1,
        "data": {
            "receipts": [
                {
                    "id": "r1",
                    "retailer": "lidl",
                    "date": "2026-10-20",
                    "items": [
                        {
                            "name": "GOUDA",
                            "key": "gouda",
                            "product": "Gouda",
                            "price": 1.79,
                            "amount": 150,
                            "unit": "g",
                            "status": "saved",
                        }
                    ],
                },
                {
                    "id": "r0",
                    "retailer": "lidl",
                    "date": "2026-06-01",
                    "items": [
                        {
                            "name": "QUARK",
                            "key": "quark",
                            "product": "Quark",
                            "price": 0.59,
                            "amount": 250,
                            "unit": "g",
                            "status": "saved",
                        }
                    ],
                },
            ]
        },
    }
    manager = await _setup(hass, config_entry, freezer, **{CONF_OFFERS_SOURCE: "marktguru"})
    store: ProductStore = manager.products
    assert store.data["seeded"]
    names = sorted(p["name"] for p in store.products.values())
    assert names == ["Butter", "Gouda", "Kaffee", "ja! H-Milch 1,5%"]
    milk = store.get("rewe:8-MILCH1")
    assert milk["regular"] == {"price": 1.09, "source": "rewe_online", "seen": "2026-11-01"}
    coffee = store.by_key("kaffee")[0]
    assert coffee["offer"]["id"] == "mg_72"
    assert manager.shopping[0]["chosen"]["product_id"] == coffee["id"]
    assert store.picks["gouda"][0][3] == PICK_BOUGHT
    assert not store.by_key("quark")  # older than 90 days

    record_pick(manager, "butter", store.by_offer("mg_71")["id"])
    assert await hass.config_entries.async_reload(entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    key = f"essensplaner.products.{entry_id}"
    assert key in hass_storage
    manager = config_entry.runtime_data
    assert sorted(p["name"] for p in manager.products.products.values()) == names
    assert manager.products.picks["butter"][0][1] == 1
    assert manager.products.picks["gouda"][0][1] == 1  # not filled a second time

    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)
    counts = diagnostics["products"]
    assert counts["products"] == 4 and counts["seeded"] and counts["max_products"] == MAX_PRODUCTS
    assert counts["retailers"] == {"lidl": 3, "rewe": 1}
    assert counts["stable_ids"] == 1 and counts["picks"] == 2
    assert counts["file_bytes"] is None or counts["file_bytes"] > 0
    text = json.dumps(counts)
    assert "Gouda" not in text and "Bergland" not in text and "12345" not in text

    # marktguru switched off: its offers go (the product keeps its regular price; the
    # coffee on the shopping list stays without offer)
    hass.config_entries.async_update_entry(
        config_entry, options={**config_entry.options, CONF_OFFERS_SOURCE: "off"}
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    manager = config_entry.runtime_data
    store = manager.products
    butter = store.by_key("butter")[0]
    assert "offer" not in butter and butter["regular"]["price"] == 2.29
    assert "offer" not in store.get(coffee["id"])

    assert await hass.config_entries.async_remove(entry_id)
    await hass.async_block_till_done()
    assert key not in hass_storage
