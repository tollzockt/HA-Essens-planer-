"""1.4: drugstores (Rossmann, dm, Müller, Budni) as chains, their aisles, the drugstore
branch on the shopping list, the v4 migration and the marktguru fixes (honest
User-Agent, local dates, no placeholder brand)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.essensplaner.branches import SHOP_PATTERN, build_query, parse_elements
from custom_components.essensplaner.const import HTTP_USER_AGENT, STORAGE_KEY
from custom_components.essensplaner.ingredients import (
    CATEGORY_ORDER,
    guess_category,
    is_nonfood_category,
    parse_ingredient,
)
from custom_components.essensplaner.offers import (
    MARKTGURU_API,
    MARKTGURU_HOME,
    MarktguruClient,
    normalize_marktguru,
    parse_pack,
    parse_pack_text,
)
from custom_components.essensplaner.pricing import pack_text
from custom_components.essensplaner.retailers import (
    DEFAULT_STORES,
    RETAILERS,
    is_chain_name,
    is_drugstore,
    resolve_retailer,
    retailer_for_osm,
    retailer_kind,
    retailers_named,
)

DRUGSTORE = "Drogerie & Körperpflege"
HOUSEHOLD = "Haushalt & Reinigung"

# a Rossmann branch as OpenStreetMap maps it (fictional place and id, real tag layout)
ROSSMANN_NODE = {
    "type": "node",
    "id": 1000000001,
    "lat": 48.0917869,
    "lon": 11.5316102,
    "tags": {
        "addr:city": "Lindenau",
        "addr:housenumber": "5",
        "addr:postcode": "56501",
        "addr:street": "Rheinweg",
        "brand": "Rossmann",
        "brand:wikidata": "Q316004",
        "name": "Rossmann",
        "operator": "Dirk Rossmann GmbH",
        "shop": "chemist",
    },
}
MUELLER_LIGHTING = {
    "type": "node",
    "id": 9496008662,
    "lat": 47.9376227,
    "lon": 11.399747,
    "tags": {"name": "Müller", "shop": "lighting"},
}
MUELLER_OPTICIAN = {
    "type": "node",
    "id": 13585247511,
    "lat": 47.9385517,
    "lon": 11.4015108,
    "tags": {"addr:postcode": "56626", "name": "Müller + Daum", "shop": "optician"},
}
ZERRES = {
    "type": "node",
    "id": 2358292310,
    "lat": 48.0987765,
    "lon": 11.6113367,
    "tags": {"name": "Zerres Parfümerie und Drogerie", "shop": "chemist"},
}

# a real marktguru search result (trimmed): an unbranded Lidl offer valid 09.–14.11.
NO_BRAND_OFFER = {
    "id": 25587492,
    "description": "BIOLAND Deutscher , lose Klasse I kg",
    "price": 1.99,
    "oldPrice": None,
    "referencePrice": 1.99,
    "requiresLoyalityMembership": False,
    "validityDates": [{"from": "2026-11-08T23:00:00Z", "to": "2026-11-14T22:59:59Z"}],
    "unit": {"shortName": "kg", "id": 2, "name": "Kilogramm"},
    "product": {"id": 1111349, "name": "Bio Speisekürbis Butternut", "description": None},
    "brand": {"uniqueName": "thisisnobrand123", "id": 125322, "name": "thisisnobrand123"},
    "advertisers": [{"uniqueName": "lidl", "id": "retailers/126679", "name": "Lidl"}],
}


# ----------------------------------------------------------------------
# Chains
# ----------------------------------------------------------------------


def test_drugstore_chains() -> None:
    """Rossmann, dm, Müller and Budni are drugstores with marktguru ids; not default."""
    assert {r: RETAILERS[r]["name"] for r in RETAILERS if is_drugstore(r)} == {
        "rossmann": "Rossmann",
        "dm-drogerie-markt": "dm",
        "mueller-drogeriemarkt": "Müller",
        "budnikowsky": "Budni",
    }
    assert all(info["kind"] in ("grocery", "drugstore") for info in RETAILERS.values())
    assert retailer_kind("rewe") == "grocery"
    assert retailer_kind("rewe-petz") == "grocery"  # regional marktguru variant
    assert retailer_kind("rossmann") == "drugstore"
    assert retailer_kind("metro") is None
    assert not set(DEFAULT_STORES) & {r for r in RETAILERS if is_drugstore(r)}
    assert RETAILERS["rossmann"]["wikidata"] == ["Q316004"]
    assert RETAILERS["dm-drogerie-markt"]["wikidata"] == ["Q266572"]
    assert RETAILERS["mueller-drogeriemarkt"]["wikidata"] == ["Q1958759"]
    assert RETAILERS["budnikowsky"]["wikidata"] == ["Q1001516"]


def test_resolve_drugstores() -> None:
    """Store texts of drugstores; "Müller" is also a surname."""
    assert resolve_retailer("Rossmann") == "rossmann"
    assert resolve_retailer("ROSSMANN Drogeriemarkt") == "rossmann"
    assert resolve_retailer("dm") == "dm-drogerie-markt"
    assert resolve_retailer("dm-drogerie markt") == "dm-drogerie-markt"
    assert resolve_retailer("Müller") == "mueller-drogeriemarkt"
    assert resolve_retailer("Mueller") == "mueller-drogeriemarkt"
    assert resolve_retailer("Müller Arbeit") == "mueller-drogeriemarkt"
    assert resolve_retailer("Drogerie Müller") == "mueller-drogeriemarkt"
    assert resolve_retailer("Budni") == resolve_retailer("Budnikowsky") == "budnikowsky"
    # a surname inside a longer text is no Müller drugstore
    assert resolve_retailer("EDEKA Müller") == "edeka"
    assert resolve_retailer("Bäckerei Müller") is None
    assert resolve_retailer("Bio Markt Müller") is None
    assert is_chain_name("Rossmann") and is_chain_name("dm") and is_chain_name("Müller")
    assert retailers_named("REWE neben Rossmann") == {"rewe", "rossmann"}
    assert retailers_named("ROSSMANN Drogeriemarkt") == {"rossmann"}


def test_retailer_for_osm_shop_types() -> None:
    """brand:wikidata always counts, a chain name only on a shop of the chain's kind."""
    assert retailer_for_osm(ROSSMANN_NODE["tags"]) == ("rossmann", False)
    assert retailer_for_osm({"shop": "chemist", "name": "Rossmann"}) == ("rossmann", False)
    assert retailer_for_osm({"shop": "chemist", "name": "dm"}) == ("dm-drogerie-markt", False)
    assert retailer_for_osm({"shop": "chemist", "name": "Müller"}) == (
        "mueller-drogeriemarkt",
        False,
    )
    assert retailer_for_osm({"shop": "chemist", "name": "Budni"}) == ("budnikowsky", False)
    # "Müller" lighting shop / optician / bakery: no drugstore
    assert retailer_for_osm(MUELLER_LIGHTING["tags"]) == (None, False)
    assert retailer_for_osm(MUELLER_OPTICIAN["tags"]) == (None, False)
    assert retailer_for_osm({"shop": "bakery", "name": "Bäckerei Müller"}) == (None, False)
    assert retailer_for_osm({"shop": "supermarket", "name": "Bio Markt Müller"}) == (None, False)
    assert retailer_for_osm({"shop": "supermarket", "name": "EDEKA Müller"}) == ("edeka", False)
    # an independent chemist is no chain; a grocery name on a chemist does not count
    assert retailer_for_osm(ZERRES["tags"]) == (None, False)
    assert retailer_for_osm({"shop": "chemist", "name": "REWE"}) == (None, False)
    # a mistagged drugstore: brand:wikidata decides
    assert retailer_for_osm({"shop": "supermarket", "brand:wikidata": "Q266572"}) == (
        "dm-drogerie-markt",
        False,
    )


def test_branch_search_finds_drugstores() -> None:
    """The query asks for chemists; only chemists of drugstore chains are kept."""
    home = {"zone": "zone.home", "name": "Zuhause", "lat": 48.09, "lon": 11.53, "home": True}
    query = build_query([home], 25000, False, 800)
    assert SHOP_PATTERN == "^(supermarket|discount|chemist)$"
    assert 'nwr["shop"~"^(supermarket|discount|chemist)$"](around:25000,48.090,11.530);' in query
    assert query.rstrip().endswith("out center tags 800;")
    chemist_with_grocery_brand = {
        "type": "node",
        "id": 7,
        "lat": 48.091,
        "lon": 11.532,
        "tags": {"shop": "chemist", "name": "REWE Drogerie", "brand:wikidata": "Q16968817"},
    }
    stats: dict[str, int] = {}
    results = parse_elements(
        {
            "elements": [
                ROSSMANN_NODE,
                ZERRES,
                MUELLER_LIGHTING,
                MUELLER_OPTICIAN,
                chemist_with_grocery_brand,
            ]
        },
        [home],
        [],
        radius_m=25000,
        stats=stats,
    )
    assert [(r["id"], r["retailer"], r["label"], r["postcode"]) for r in results] == [
        ("osm_node_1000000001", "rossmann", "Rossmann Rheinweg 5", "56501")
    ]
    assert results[0]["retailer_name"] == "Rossmann"
    assert stats["unknown"] == 4


# ----------------------------------------------------------------------
# Aisles, packs, estimates
# ----------------------------------------------------------------------


def test_nonfood_categories() -> None:
    """Two new aisles before "Sonstiges"; food with similar words stays food."""
    assert CATEGORY_ORDER[-3:] == [DRUGSTORE, HOUSEHOLD, "Sonstiges"]
    for name in (
        "Zahnpasta",
        "Zahnbürsten",
        "Duschgel",
        "Shampoo",
        "Haarspülung",
        "Deo",
        "Deo-Roller",
        "Rasierschaum",
        "Taschentücher",
        "Feuchttücher",
        "Windeln",
        "Wattepads",
        "Sonnencreme",
        "Handcreme",
        "Babyöl",
    ):
        assert guess_category(name) == DRUGSTORE, name
    for name in (
        "Waschmittel",
        "Weichspüler",
        "Spülmittel",
        "Spülmaschinentabs",
        "Geschirrspültabs",
        "Spülmaschinensalz",
        "Müllbeutel",
        "Küchenrolle",
        "Toilettenpapier",
        "Alufolie",
        "Frischhaltefolie",
        "Backpapier",
        "Schwamm",
        "Allzweckreiniger",
        "WC-Reiniger",
        "Batterien",
    ):
        assert guess_category(name) == HOUSEHOLD, name
    # no bare "creme" / "watte" / "binde" / "papier" / "deo"
    assert guess_category("Crème fraîche") == "Milchprodukte & Eier"
    assert guess_category("Creme fraiche") == "Milchprodukte & Eier"
    assert guess_category("Kokoscreme") == "Konserven & Gläser"
    assert guess_category("Zuckerwatte") == "Backen & Süßes"
    assert guess_category("Reispapier") == "Nudeln, Reis & Getreide"
    assert guess_category("Kondensmilch") == "Milchprodukte & Eier"
    assert guess_category("Salz") == "Gewürze, Öle & Saucen"
    assert guess_category("Olivenöl") == "Gewürze, Öle & Saucen"
    assert guess_category("Schwammerl") == "Obst & Gemüse"
    assert guess_category("Video") == "Sonstiges"
    assert is_nonfood_category(DRUGSTORE) and is_nonfood_category(HOUSEHOLD)
    assert not is_nonfood_category("Sonstiges")


def test_panel_categories() -> None:
    """The panel's shared module knows the new aisles (entries only added)."""
    common = (
        Path(__file__).parent.parent
        / "custom_components/essensplaner/frontend"
        / "essensplaner-common.js"
    ).read_text(encoding="utf-8")
    for name in (DRUGSTORE, HOUSEHOLD):
        assert f'  "{name}",' in common
        assert f'  "{name}": "' in common
    assert common.index(f'  "{HOUSEHOLD}",') < common.index('  "Sonstiges",')


def test_drugstore_packs() -> None:
    """Washing loads, rolls and "St" are package sizes."""
    assert parse_pack("39 WL") == (39, "WL")
    assert parse_pack("22 Wl") == (22, "WL")
    assert parse_pack("Flüssig 1,1 l = 20 WL") == (20, "WL")
    assert parse_pack("20 Waschladungen") == (20, "WL")
    assert parse_pack("8 Rollen") == (8, "Rolle")
    assert parse_pack("3-lagig 3 x 100 Blatt") == (3, "Rolle")
    assert parse_pack("Oreo Rolle 154 g") == (154, "g")  # a weight wins
    assert parse_pack_text("10 St") == (10, "Stück")
    assert parse_pack_text("2 St.") == (2, "Stück")
    assert parse_pack_text("40 Stk") == (40, "Stück")
    assert parse_pack_text("40 Stangen") is None
    assert pack_text(8, "Rolle") == "8 Rollen"
    assert pack_text(1, "Rolle") == "1 Rolle"
    assert pack_text(20, "WL") == "20 WL"
    toilet = parse_ingredient("16 Rollen Toilettenpapier")
    assert (toilet["amount"], toilet["unit"], toilet["name"]) == (16, "Rolle", "Toilettenpapier")
    detergent = parse_ingredient("40 WL Waschmittel")
    assert (detergent["amount"], detergent["unit"], detergent["category"]) == (40, "WL", HOUSEHOLD)


async def test_drugstore_estimates(hass: HomeAssistant, setup_integration) -> None:
    """About 30 drugstore / household estimates, priced in whole packs."""
    manager = setup_integration.runtime_data
    nonfood = [
        e for e in manager.defaults_index().entries() if is_nonfood_category(guess_category(e.name))
    ]
    assert len(nonfood) >= 30
    assert manager.has_estimate("Zahnpasta") and manager.has_estimate("Klopapier")
    toilet = manager.shopping_add("16 Rollen Toilettenpapier")
    assert (toilet["price"], toilet["packs"]) == (7.9, 2)  # 2 x 10 Rollen
    detergent = manager.shopping_add("Waschmittel")
    assert (detergent["price"], detergent["packs"]) == (3.45, 1)
    # "Zahnpasta" is no pasta
    assert manager.price_book.lookup("Zahnpasta").name == "Zahnpasta"


# ----------------------------------------------------------------------
# Shopping list: the drugstore branch
# ----------------------------------------------------------------------


def _stores(manager):
    rossmann = manager.save_branch(
        {"store": "Rossmann", "street": "Rheinweg 5", "postcode": "56501", "city": "Lindenau"}
    )
    rewe = manager.save_branch({"store": "REWE", "street": "Bahnhofstraße 3", "postcode": "57601"})
    lidl = manager.save_branch({"store": "Lidl", "street": "Lindenweg 2", "postcode": "56501"})
    return rossmann, rewe, lidl


def _item(manager, summary):
    return next(i for i in manager.shopping if i["summary"] == summary)


async def test_drugstore_is_never_the_automatic_main(
    hass: HomeAssistant, setup_integration
) -> None:
    """The only selected supermarket becomes the main branch, a drugstore only by choice."""
    manager = setup_integration.runtime_data
    rossmann = manager.save_branch({"store": "Rossmann", "postcode": "56501"})
    assert rossmann["main"] is False
    assert manager.main_branch is None
    rewe = manager.save_branch({"store": "REWE", "postcode": "57601"})
    assert rewe["main"] is True  # the only grocery, although two branches are selected
    manager.set_main_branch(rossmann["id"])  # the user's choice counts
    assert manager.main_branch == rossmann["id"]


async def test_drugstore_items_go_to_the_drugstore(hass: HomeAssistant, setup_integration) -> None:
    """Drogerie / Haushalt items go to the drugstore, food stays at the main branch."""
    manager = setup_integration.runtime_data
    rossmann, rewe, lidl = _stores(manager)
    assert manager.main_branch == rewe["id"]
    manager.shopping_add("Zahnpasta")
    manager.shopping_add("Spülmittel")
    manager.shopping_add("250 g Butter")
    zahnpasta, spuelmittel, butter = (
        _item(manager, s) for s in ("Zahnpasta", "Spülmittel", "250 g Butter")
    )
    assert (zahnpasta["branch_id"], zahnpasta["store_reason"]) == (rossmann["id"], "drugstore")
    assert (zahnpasta["price"], zahnpasta["saving"]) == (0.75, 0.0)
    assert (spuelmittel["branch_id"], spuelmittel["store_reason"]) == (rossmann["id"], "drugstore")
    assert (butter["branch_id"], butter["store_reason"]) == (rewe["id"], "main")
    assert zahnpasta["description"].startswith("🏪 Rossmann Rheinweg 5 · ")
    summary = manager.stores_summary()
    assert [(g["label"], g["open"]) for g in summary] == [
        ("REWE Bahnhofstraße 3", 1),
        ("Rossmann Rheinweg 5", 2),
    ]

    # a cheaper regular price at the drugstore does not move food there ...
    manager.set_store_price("Rossmann", "Butter", 0.99, 250, "g")
    assert _item(manager, "250 g Butter")["branch_id"] == rewe["id"]
    # ... a real offer of the product does
    manager.set_store_price("Rossmann", "Butter", 2.29, 250, "g")
    manager.add_offer("Butter", "Rossmann", 1.19, "250 g")
    butter = _item(manager, "250 g Butter")
    assert (butter["branch_id"], butter["store_reason"]) == (rossmann["id"], "offer")
    assert butter["saving"] == 0.8

    # a drugstore item moves to another store for an offer (saving against the drugstore)
    manager.add_offer("Zahnpasta", "Lidl", 0.29, "75 ml")
    zahnpasta = _item(manager, "Zahnpasta")
    assert (zahnpasta["branch_id"], zahnpasta["store_reason"]) == (lidl["id"], "offer")
    assert zahnpasta["saving"] == 0.46
    # an own store choice wins
    manager.set_shopping_store("Spülmittel", "REWE")
    spuelmittel = _item(manager, "Spülmittel")
    assert (spuelmittel["branch_id"], spuelmittel["store_reason"]) == (rewe["id"], "manual")

    # "Alles im Hauptladen": the drugstore is only an alternative
    manager.hass.config_entries.async_update_entry(
        manager.entry, options={**manager.entry.options, "store_split_mode": "main_only"}
    )
    await hass.async_block_till_done()
    manager = setup_integration.runtime_data
    manager.assign_shopping_stores()
    zahnpasta = _item(manager, "Zahnpasta")
    assert (zahnpasta["branch_id"], zahnpasta["store_reason"]) == (rewe["id"], "main")


async def test_nonfood_offers_never_price_food(hass: HomeAssistant, setup_integration) -> None:
    """ "Babyöl" found for "Öl", "W5 Spülmittel Zitrone" for "Zitrone": no food offers."""
    manager = setup_integration.runtime_data
    _stores(manager)
    assert manager.offer_keys({"product": "Penaten Babyöl", "keys": ["oel"]}) == []
    assert manager.offer_keys(
        {"product": "W5 Spülmittel Zitrone", "keys": ["zitrone", "spuelmittel"]}
    ) == ["spuelmittel"]
    assert manager.offer_keys({"product": "Bio-Zitronen", "keys": ["zitrone"]}) == ["zitrone"]
    # stored before 1.4 with a food key: never used for food (recipe costs, list)
    manager.offers.append(
        {
            "id": "mg_1",
            "title": "Penaten Babyöl",
            "product": "Penaten Babyöl",
            "store": "ROSSMANN",
            "store_id": "rossmann",
            "retailer": "rossmann",
            "price": 0.49,
            "pack_amount": 500,
            "pack_unit": "ml",
            "valid_from": "2026-11-02",
            "valid_to": "2026-11-07",
            "source": "marktguru",
            "keys": ["oel"],
        }
    )
    manager._invalidate_prices()
    assert manager.offers_for("Öl", manager.today()) == []
    recipe = manager.add_recipe({"name": "Ölbrot", "servings": 1, "ingredients": ["100 ml Öl"]})
    assert manager.recipe_cost(recipe)["on_offer"] == []
    # compare: no estimate of Butter "at Rossmann"
    compared = manager.compare_prices("Butter")
    assert "rossmann" not in [r["retailer"] for r in compared["results"]]
    assert "rossmann" in [r["retailer"] for r in manager.compare_prices("Zahnpasta")["results"]]


# ----------------------------------------------------------------------
# Migration v4: the user's Rossmann saved as Marktkauf
# ----------------------------------------------------------------------


def _branch(branch_id, retailer, name, label, street, postcode, priority, **extra):
    return {
        "id": branch_id,
        "retailer": retailer,
        "name": name,
        "label": label,
        "street": street,
        "postcode": postcode,
        "city": "",
        "postcode_guessed": False,
        "lat": None,
        "lon": None,
        "source": "manual",
        "selected": True,
        "priority": priority,
        "near": {},
        "route": {},
        "rewe_market_id": "",
        "retailer_guessed": False,
        "added": "2026-11-01T10:00:00+00:00",
        "updated": "2026-11-01T10:00:00+00:00",
        **extra,
    }


async def test_migrate_rossmann_saved_as_marktkauf(
    hass: HomeAssistant, config_entry: MockConfigEntry, hass_storage, freezer
) -> None:
    """A branch named "ROSSMANN Drogeriemarkt" but saved as Marktkauf becomes Rossmann."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(datetime.fromisoformat("2026-11-04T10:00:00+01:00"))
    rewe = _branch(
        "man_1",
        "rewe",
        "REWE",
        "REWE Bahnhofstraße 3",
        "Bahnhofstraße 3",
        "57601",
        0,
        rewe_market_id="8500001",
    )
    rossmann = _branch(
        "man_2",
        "marktkauf",
        "ROSSMANN Drogeriemarkt",
        "Marktkauf Rheinweg 5",
        "Rheinweg 5",
        "56501",
        5,
        retailer_guessed=True,
    )
    # never touched: a surname, a label mentioning another chain
    edeka = _branch("man_3", "edeka", "Müller", "EDEKA Lindenweg 1", "Lindenweg 1", "56501", 3)
    rewe_work = _branch("man_4", "rewe", "REWE", "REWE neben Rossmann", "Hauptstraße 1", "56501", 4)
    hass_storage[f"{STORAGE_KEY}.{config_entry.entry_id}"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"{STORAGE_KEY}.{config_entry.entry_id}",
        "data": {
            "recipes": {},
            "plan": {},
            "shopping": [],
            "starter_names": [],
            "data_version": 3,
            "branches": [rewe, edeka, rewe_work, rossmann],
            "main_branch": "man_1",
            "store_prices_user": {
                "marktkauf": {
                    "zahnpasta": {
                        "name": "Zahnpasta",
                        "price": 0.65,
                        "amount": 75,
                        "unit": "ml",
                        "source": "user",
                        "updated": "2026-11-01T10:00:00+00:00",
                    }
                }
            },
            "store_preferences": {"duschgel": "marktkauf"},
            "offers": [
                {
                    "id": "man_9",
                    "title": "Duschgel",
                    "product": "Duschgel",
                    "store": "Marktkauf",
                    "store_id": "marktkauf",
                    "retailer": "marktkauf",
                    "branch_id": "man_2",
                    "price": 0.55,
                    "pack_amount": 300,
                    "pack_unit": "ml",
                    "valid_from": "2026-11-02",
                    "valid_to": "2026-11-07",
                    "source": "manual",
                    "keys": ["duschgel"],
                }
            ],
        },
    }
    assert await async_setup_component(hass, "homeassistant", {})
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    manager = config_entry.runtime_data

    assert manager.data_version == 4
    migrated = manager.get_branch("man_2")
    assert migrated["retailer"] == "rossmann"
    assert migrated["retailer_guessed"] is False
    assert (migrated["name"], migrated["label"]) == (
        "ROSSMANN Drogeriemarkt",
        "Rossmann Rheinweg 5",  # the automatic label follows the chain
    )
    assert (migrated["street"], migrated["postcode"], migrated["priority"]) == (
        "Rheinweg 5",
        "56501",
        5,
    )
    assert manager.get_branch("man_1") == rewe
    assert manager.get_branch("man_3") == edeka
    assert manager.get_branch("man_4") == rewe_work
    assert manager.main_branch == "man_1"
    # what was entered for this shop follows it (no other Marktkauf branch)
    assert manager.store_prices_user == {
        "rossmann": {
            "zahnpasta": {
                "name": "Zahnpasta",
                "price": 0.65,
                "amount": 75,
                "unit": "ml",
                "source": "user",
                "updated": "2026-11-01T10:00:00+00:00",
            }
        }
    }
    assert manager.store_preferences == {"duschgel": "rossmann"}
    offer = manager.offers[0]
    assert (offer["retailer"], offer["store_id"], offer["store"]) == (
        "rossmann",
        "rossmann",
        "Rossmann",
    )
    stored = hass_storage[f"{STORAGE_KEY}.{config_entry.entry_id}"]["data"]
    assert stored["data_version"] == 4
    assert next(b for b in stored["branches"] if b["id"] == "man_2")["retailer"] == "rossmann"

    # drugstore items go there now
    manager.shopping_add("Zahnpasta")
    item = _item(manager, "Zahnpasta")
    assert (item["branch_id"], item["store_reason"], item["price"]) == ("man_2", "drugstore", 0.65)

    # idempotent: nothing left to switch
    assert manager._migrate_drugstore_branches() == []
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.runtime_data.get_branch("man_2")["retailer"] == "rossmann"


# ----------------------------------------------------------------------
# marktguru: honest User-Agent, local dates, placeholder brand
# ----------------------------------------------------------------------


async def test_marktguru_local_dates_and_no_brand(hass: HomeAssistant) -> None:
    """UTC timestamps become German dates; "thisisnobrand123" is no brand."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    offer = normalize_marktguru(NO_BRAND_OFFER, "Kürbis")
    assert (offer["valid_from"], offer["valid_to"]) == ("2026-11-09", "2026-11-14")
    assert offer["brand"] == ""
    assert offer["title"] == "Bio Speisekürbis Butternut"
    assert (offer["retailer"], offer["store"]) == ("lidl", "Lidl")
    plain = normalize_marktguru(
        {**NO_BRAND_OFFER, "validityDates": [{"from": "2026-11-09", "to": "2026-11-14"}]}
    )
    assert (plain["valid_from"], plain["valid_to"]) == ("2026-11-09", "2026-11-14")


async def test_marktguru_honest_user_agent(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Both marktguru requests send the integration's User-Agent (no browser)."""
    aioclient_mock.get(
        MARKTGURU_HOME,
        text=(
            '<html><head><script type="application/json">'
            '{"config": {"apiKey": "test-api", "clientKey": "test-client"}}'
            "</script></head></html>"
        ),
    )
    aioclient_mock.get(f"{MARKTGURU_API}/offers/search", json={"results": [NO_BRAND_OFFER]})
    results = await MarktguruClient(hass).async_search("Kürbis", "56501")
    assert len(results) == 1
    assert HTTP_USER_AGENT.startswith("HA-Essensplaner/1.4 (+https://github.com/")
    assert len(aioclient_mock.mock_calls) == 2
    for call in aioclient_mock.mock_calls:
        assert call[3]["User-Agent"] == HTTP_USER_AGENT
        assert "Mozilla" not in call[3]["User-Agent"]
