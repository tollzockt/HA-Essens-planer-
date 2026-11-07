"""Retailers, layered price books and store specific prices (1.3)."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import pytest

from custom_components.essensplaner import offers as offers_module
from custom_components.essensplaner.const import DOMAIN
from custom_components.essensplaner.pricing import (
    LayeredPriceBook,
    PriceBook,
    PriceEntry,
    PriceIndex,
    cheaper_by,
    offer_as_entry,
)
from custom_components.essensplaner.retailers import (
    DEFAULT_STORES,
    STORES,
    aldi_for_postcode,
    resolve_retailer,
    retailer_for_osm,
    retailer_for_store_id,
    retailer_matches,
    retailer_name,
)

DEFAULTS = [
    {"name": "Milch", "amount": 1000, "unit": "ml", "price": 0.99, "aliases": ["Vollmilch"]},
    {"name": "Kokosmilch", "amount": 400, "unit": "ml", "price": 1.29},
    {"name": "Butter", "amount": 250, "unit": "g", "price": 1.99},
]


async def _call(hass: HomeAssistant, service: str, **data):
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


# ----------------------------------------------------------------------------
# Retailers
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Aldi Süd", "aldi-sued"),
        ("ALDI SÜD", "aldi-sued"),
        ("aldi sued", "aldi-sued"),
        ("Aldi-Süd", "aldi-sued"),
        ("Aldi Sud", "aldi-sued"),
        ("aldi-nord", "aldi-nord"),
        ("Aldi Nord", "aldi-nord"),
        ("Netto", "netto-marken-discount"),
        ("netto marken-discount", "netto-marken-discount"),
        ("REWE City", "rewe"),
        ("rewe", "rewe"),
        ("Edeka Südwest", "edeka"),
        ("E center", "edeka"),
        ("Lidl Filiale", "lidl"),
        ("Penny Markt", "penny"),
        ("kaufland", "kaufland"),
        ("Metro", None),
        ("", None),
        (None, None),
    ],
)
def test_resolve_retailer(text, expected) -> None:
    """Names, ids and variants are case and umlaut insensitive."""
    assert resolve_retailer(text) == expected


def test_resolve_plain_aldi() -> None:
    """A plain 'Aldi' is the selected variant, else guessed from the zip code."""
    assert resolve_retailer("Aldi", ["aldi-nord", "lidl"]) == "aldi-nord"
    assert resolve_retailer("aldi", ["lidl", "aldi-sued"], "20095") == "aldi-sued"
    assert resolve_retailer("Aldi", ["aldi-sued", "aldi-nord"], "20095") == "aldi-nord"
    assert resolve_retailer("bei Aldi", None, "80331") == "aldi-sued"
    assert resolve_retailer("Aldi") is None
    assert resolve_retailer("Aldi", ["aldi-sued", "aldi-nord"]) is None


@pytest.mark.parametrize(
    ("postcode", "expected"),
    [
        ("40210", "aldi-sued"),  # Düsseldorf
        ("45127", "aldi-nord"),  # Essen
        ("44135", "aldi-nord"),  # Dortmund
        ("47051", "aldi-sued"),  # Duisburg
        ("50667", "aldi-sued"),  # Köln
        ("59065", "aldi-nord"),  # Hamm
        ("10115", "aldi-nord"),  # Berlin
        ("01067", "aldi-nord"),  # Dresden
        ("80331", "aldi-sued"),  # München
        ("99084", "aldi-sued"),  # Erfurt (first digit heuristic)
        ("43000", None),
        ("", None),
        (None, None),
    ],
)
def test_aldi_postcode_heuristic(postcode, expected) -> None:
    """Aldi Süd / Nord border (Ruhrgebiet) and first-digit fallback."""
    assert aldi_for_postcode(postcode) == expected


def test_retailer_for_store_id_and_names() -> None:
    """marktguru ids incl. regional variants; display names; re-exports."""
    assert retailer_for_store_id("edeka-suedwest") == "edeka"
    assert retailer_for_store_id("EDEKA-Nordbayern") == "edeka"
    assert retailer_for_store_id("netto-marken-discount") == "netto-marken-discount"
    assert retailer_for_store_id("aldi-sued") == "aldi-sued"
    assert retailer_for_store_id("metro") is None
    assert retailer_for_store_id(None) is None
    assert retailer_name("aldi-sued") == "Aldi Süd"
    assert retailer_name("netto-marken-discount") == "Netto"
    assert retailer_name("metro") == "metro"
    # moved from offers.py, still importable there
    assert offers_module.STORES is STORES
    assert offers_module.DEFAULT_STORES is DEFAULT_STORES
    assert STORES["aldi-sued"] == "Aldi Süd"
    assert len(STORES) == 15  # 11 groceries + 4 drugstores (1.4)
    assert "rossmann" not in DEFAULT_STORES


def test_retailer_for_osm() -> None:
    """Wikidata first, then brand/name, then the postcode heuristic for a plain Aldi."""
    assert retailer_for_osm({"brand": "Aldi", "brand:wikidata": "Q41171373"}) == (
        "aldi-nord",
        False,
    )
    assert retailer_for_osm({"name": "ALDI SÜD"}) == ("aldi-sued", False)
    assert retailer_for_osm({"brand": "Aldi", "name": "Aldi Süd"}) == ("aldi-sued", False)
    assert retailer_for_osm({"name": "Aldi", "addr:postcode": "80331"}) == ("aldi-sued", True)
    assert retailer_for_osm({"name": "Aldi"}, "20095") == ("aldi-nord", True)
    assert retailer_for_osm({"name": "Aldi"}) == (None, True)
    assert retailer_for_osm({"brand": "Netto", "brand:wikidata": "Q552652"}) == (None, False)
    assert retailer_for_osm({"brand": "Netto Marken-Discount"}) == (
        "netto-marken-discount",
        False,
    )
    assert retailer_for_osm({"name": "Netto"}) == ("netto-marken-discount", True)
    assert retailer_for_osm({"brand": "REWE", "name": "REWE City"}) == ("rewe", False)
    assert retailer_for_osm({"name": "Bäckerei Müller"}) == (None, False)


def test_retailer_matches() -> None:
    """Same retailer in different spellings; a plain Aldi matches both variants."""
    assert retailer_matches("Aldi Süd", "aldi-sued")
    assert retailer_matches("Aldi", "aldi-nord")
    assert retailer_matches("Netto", "netto-marken-discount")
    assert retailer_matches("edeka-suedwest", "EDEKA")
    assert not retailer_matches("aldi-sued", "aldi-nord")
    assert not retailer_matches("Metro", "Metro")
    assert not retailer_matches(None, "lidl")


# ----------------------------------------------------------------------------
# Price books
# ----------------------------------------------------------------------------


def _index(items: list[dict], source: str, store_id: str | None = None) -> PriceIndex:
    index = PriceIndex()
    for item in items:
        index.add(item, source, store_id=store_id)
    return index


def test_layered_lookup_precedence() -> None:
    """Exact keys over all layers first, then the most specific compound match."""
    defaults = _index(DEFAULTS, "default")
    own = _index([{"name": "Butter", "price": 1.49, "amount": 250, "unit": "g"}], "user", "lidl")
    learned = _index(
        [
            {"name": "Butter", "price": 1.79, "amount": 250, "unit": "g"},
            {"name": "Milch", "price": 1.09, "amount": 1000, "unit": "ml"},
        ],
        "leaflet",
        "lidl",
    )
    book = LayeredPriceBook([own, learned, defaults])
    butter = book.lookup("Butter")
    assert (butter.price, butter.source, butter.store_id, butter.real) == (
        1.49,
        "user",
        "lidl",
        True,
    )
    assert book.lookup("Butter") is butter  # cached
    assert book.lookup("Milch").price == 1.09
    # an exact estimate beats a compound match of a higher layer
    assert book.lookup("Kokosmilch").name == "Kokosmilch"
    # compound words: the longest key wins, not the higher layer ("milch" in "kokosmilch")
    assert book.lookup("Kokosmilch light").name == "Kokosmilch"
    # equal keys: the higher layer wins
    assert book.lookup("Süßrahmbutter").price == 1.49
    assert LayeredPriceBook([learned, own, defaults]).lookup("Butter").price == 1.79
    assert LayeredPriceBook([defaults]).lookup("Butter").real is False
    assert LayeredPriceBook([own]).lookup("Quark") is None


def test_compat_price_book() -> None:
    """The 1.2 PriceBook still gives user > learned > default."""
    user = {"butter": {"name": "Butter", "price": 1.49, "amount": 250, "unit": "g"}}
    learned = {"butter": {"name": "Butter", "price": 1.79, "amount": 250, "unit": "g"}}
    assert PriceBook(DEFAULTS, user, learned).lookup("Butter").source == "user"
    assert PriceBook(DEFAULTS, None, learned).lookup("Butter").price == 1.79
    assert PriceBook(DEFAULTS, None, learned).lookup("Butter").source == "offer_regular"
    book = PriceBook(DEFAULTS)
    assert book.lookup("Butter").source == "default"
    assert book.lookup("Vollmilch").name == "Milch"
    assert [e.name for e in book.entries()] == ["Butter", "Kokosmilch", "Milch"]
    entry = PriceEntry(name="X", amount=1, unit="Stück", price=1, source="user", store_id="lidl")
    assert entry.as_dict()["store_id"] == "lidl"


TOMATOES = [
    {"name": "Tomaten", "amount": 500, "unit": "g", "price": 1.49, "aliases": ["Rispentomaten"]},
    {
        "name": "Gehackte Tomaten",
        "amount": 400,
        "unit": "g",
        "price": 0.59,
        "aliases": ["stückige Tomaten", "geschälte Tomaten"],
    },
]


def test_short_key_never_replaces_a_real_product() -> None:
    """'Gehackte Tomaten' (short key 'tomate') must not take over plain 'Tomaten'."""
    for items in (TOMATOES, list(reversed(TOMATOES))):
        book = PriceBook(items)
        assert book.lookup("Tomaten").name == "Tomaten"
        assert book.lookup("Tomate").name == "Tomaten"
        assert book.lookup("gehackte Tomaten").name == "Gehackte Tomaten"
        assert book.lookup("2 Dosen gehackte Tomaten").name == "Gehackte Tomaten"
        # an adjective without its own entry still finds the plain product
        assert book.lookup("frische Tomaten").name == "Tomaten"
    # an own price for canned tomatoes does not change the price of fresh ones
    user = {
        "gehackte tomate": {"name": "Gehackte Tomaten", "price": 0.49, "amount": 400, "unit": "g"}
    }
    book = PriceBook(TOMATOES, user)
    assert book.lookup("Tomaten").price == 1.49
    assert book.lookup("gehackte Tomaten").price == 0.49


async def test_learned_fresh_price_stays_off_canned_tomatoes(
    hass: HomeAssistant, setup_integration
) -> None:
    """A leaflet price for 'Rispentomaten' (key tomate) is not the price of canned tomatoes."""
    manager = setup_integration.runtime_data
    assert manager.defaults_index().get("tomate").name == "Tomaten"
    _main_branch(manager, "lidl")
    assert manager.learn_store_price("lidl", "tomate", "Rispentomaten", 1.99, 500, "g", "leaflet")
    book = manager.store_book("lidl")
    assert book.lookup("Tomaten").price == 1.99
    assert book.lookup("Rispentomaten").price == 1.99
    for canned in ("Gehackte Tomaten", "2 Dosen gehackte Tomaten", "geschälte Tomaten"):
        entry = book.lookup(canned)
        assert (entry.name, entry.source) == ("Gehackte Tomaten", "default"), canned
    rows = {r["name"]: r for r in manager.store_price_matrix(query="tomate")["rows"]}
    assert rows["Tomaten"]["stores"]["lidl"]["price"] == 1.99
    assert "lidl" not in rows["Gehackte Tomaten"]["stores"]


def test_offer_as_entry_derives_pack() -> None:
    """Pack size from price / unit price when no pack is known."""
    entry = offer_as_entry(
        {
            "title": "Butter",
            "price": 1.99,
            "unit_price": 0.00796,
            "base_unit": "g",
            "store_id": "lidl",
        }
    )
    assert (entry.amount, entry.unit, entry.price, entry.store_id) == (250, "g", 1.99, "lidl")
    eggs = offer_as_entry(
        {"title": "Eier", "price": 2.49, "unit_price": 0.249, "base_unit": "Stück"}
    )
    assert (eggs.amount, eggs.unit, eggs.price) == (10, "Stück", 2.49)
    # implausible (100 kg): old fallback 1 kg at the unit price
    odd = offer_as_entry({"title": "X", "price": 100, "unit_price": 0.001, "base_unit": "g"})
    assert (odd.amount, odd.price) == (1000, 1.0)
    no_price = offer_as_entry({"title": "X", "unit_price": 0.002, "base_unit": "ml"})
    assert (no_price.amount, no_price.price) == (1000, 2.0)
    packed = offer_as_entry(
        {
            "title": "Käse",
            "price": 2.29,
            "pack_amount": 400,
            "pack_unit": "g",
            "store_id": "edeka-suedwest",
        }
    )
    assert (packed.amount, packed.store_id) == (400, "edeka")
    tagged = offer_as_entry(
        {"title": "Käse", "price": 2.29, "pack_amount": 400, "pack_unit": "g", "retailer": "rewe"}
    )
    assert tagged.store_id == "rewe"
    assert offer_as_entry({"title": "X", "price": 1}) is None


def test_cheaper_by() -> None:
    """Absolute and relative saving."""
    assert cheaper_by(1.49, 1.99) == (0.5, 25.1)
    assert cheaper_by(2.0, 1.0) == (-1.0, -100.0)
    assert cheaper_by(1.0, 0) == (-1.0, 0.0)


# ----------------------------------------------------------------------------
# Store prices in the manager
# ----------------------------------------------------------------------------


def _main_branch(manager, retailer: str = "aldi-sued", postcode: str = "80331") -> None:
    manager.branches = [
        {
            "id": "man_main",
            "retailer": retailer,
            "name": "Hauptladen",
            "postcode": postcode,
            "selected": True,
            "priority": 0,
        },
        {
            "id": "man_lidl",
            "retailer": "lidl",
            "name": "Lidl",
            "postcode": postcode,
            "selected": True,
            "priority": 1,
        },
    ]
    manager.main_branch = "man_main"


async def test_best_price_with_retailer(hass: HomeAssistant, setup_integration) -> None:
    """Store prices are used per retailer; without main branch everything stays 1.2."""
    manager = setup_integration.runtime_data
    default = manager.best_price("Butter")[1]
    assert default.source == "default"
    entry = manager.set_store_price("Aldi Süd", "Butter", 1.49, 250, "g")
    assert entry["retailer"] == "aldi-sued"
    assert manager.store_prices_user["aldi-sued"]["butter"]["price"] == 1.49

    aldi = manager.best_price("Butter", retailer="aldi-sued")[1]
    assert (aldi.price, aldi.source, aldi.store_id, aldi.store) == (
        1.49,
        "user",
        "aldi-sued",
        "Aldi Süd",
    )
    assert manager.best_price("Butter", retailer="lidl")[1].price == default.price
    # no main branch: the general (1.2) prices
    assert manager.best_price("Butter")[1].price == default.price

    # the store price also counts for names of the same estimate ("Butterschmalz")
    manager.set_store_price("lidl", "Hähnchenbrust", 7.99, 1000, "g")
    assert manager.best_price("Hähnchenbrustfilet", retailer="lidl")[1].price == 7.99

    # recipe costs follow the main branch (cache keyed by the price context)
    recipe = manager.add_recipe(
        {"name": "Butterbrot", "servings": 1, "ingredients": ["250 g Butter"]}
    )
    before = manager.recipe_cost(recipe)["total"]
    assert before == default.price
    _main_branch(manager)
    assert manager.active_retailers() == ["aldi-sued", "lidl"]
    assert manager.main_retailer == "aldi-sued"
    assert manager.best_price("Butter")[1].price == 1.49
    assert manager.recipe_cost(recipe)["total"] == 1.49
    manager.main_branch = None
    assert manager.recipe_cost(recipe)["total"] == before

    with pytest.raises(ServiceValidationError) as err:
        manager.set_store_price("Metro", "Butter", 1.0)
    assert err.value.translation_key == "unknown_store"
    assert manager.remove_store_price("aldi-sued", "Butter") is True
    assert manager.remove_store_price("aldi-sued", "Butter") is False
    assert "aldi-sued" not in manager.store_prices_user


async def test_store_offers_and_learned_prices(hass: HomeAssistant, setup_integration) -> None:
    """Offers per retailer, learned store prices (fresh only, REWE online first)."""
    manager = setup_integration.runtime_data
    offer = manager.add_offer("Butter", "Lidl", 0.99, "250 g")
    assert offer["retailer"] == "lidl"
    assert manager.best_price("Butter", retailer="lidl")[0].offer["id"] == offer["id"]
    assert manager.best_price("Butter", retailer="aldi-sued")[0].offer is None
    assert manager.best_price("Butter")[0].offer is not None  # 1.2: any offer counts

    today = manager.today()
    manager.store_prices_learned = {
        "rewe": {
            "butter": {
                "name": "Butter",
                "price": 1.59,
                "amount": 250,
                "unit": "g",
                "source": "leaflet",
                "updated": (today - timedelta(days=10)).isoformat(),
            },
            "markenbutter": {
                "name": "Butter",
                "price": 1.69,
                "amount": 250,
                "unit": "g",
                "source": "rewe_online",
                "updated": (today - timedelta(days=3)).isoformat(),
            },
        },
        "penny": {
            "butter": {
                "name": "Butter",
                "price": 1.39,
                "amount": 250,
                "unit": "g",
                "source": "leaflet",
                "updated": (today - timedelta(days=200)).isoformat(),
            }
        },
    }
    manager._invalidate_prices()
    rewe = manager.best_price("Butter", retailer="rewe")[1]
    assert (rewe.price, rewe.source, rewe.real) == (1.69, "rewe_online", True)
    penny = manager.best_price("Butter", retailer="penny")[1]
    assert penny.source == "default"  # older than 180 days
    assert "butter" in manager.store_prices_learned["penny"]  # but kept

    # with selected branches only their retailers' online offers count
    manager.offers.append(
        {
            "id": "mg_9",
            "title": "Butter",
            "product": "Butter",
            "store": "Kaufland",
            "store_id": "kaufland",
            "retailer": "kaufland",
            "price": 0.89,
            "pack_amount": 250,
            "pack_unit": "g",
            "source": "marktguru",
            "keys": ["butter"],
        }
    )
    manager._invalidate_prices()
    assert manager.best_price("Butter")[0].offer["id"] == "mg_9"
    _main_branch(manager)
    assert manager.best_price("Butter")[0].offer["id"] == offer["id"]
    assert all(o["id"] != "mg_9" for o in manager.offers_view())


async def test_set_price_with_store(hass: HomeAssistant, setup_integration) -> None:
    """set_price with a store fills the store's price list and keeps the 1.2 price."""
    manager = setup_integration.runtime_data
    result = await _call(
        hass, "set_price", ingredient="Butter", price=1.29, amount=250, unit="g", store="Lidl"
    )
    assert result["price"]["retailer"] == "lidl"
    assert manager.prices_user["butter"]["store"] == "Lidl"
    assert manager.store_prices_user["lidl"]["butter"]["price"] == 1.29
    assert manager.best_price("Butter")[1].price == 1.29  # no main branch: like 1.2
    assert manager.best_price("Butter", retailer="lidl")[1].price == 1.29
    # a price labelled with another store does not count for Aldi
    assert manager.best_price("Butter", retailer="aldi-sued")[1].source == "default"

    await _call(hass, "set_price", ingredient="Milch", price=1.15, amount=1000, unit="ml")
    assert manager.best_price("Milch", retailer="aldi-sued")[1].price == 1.15  # unlabelled

    result = await _call(hass, "set_price", ingredient="Butter", remove=True, store="Lidl")
    assert result["removed"] is True
    assert "butter" not in manager.prices_user
    assert "lidl" not in manager.store_prices_user


async def test_store_price_matrix(hass: HomeAssistant, setup_integration, hass_ws_client) -> None:
    """Matrix of estimates and store prices (service + websocket)."""
    manager = setup_integration.runtime_data
    manager.set_store_price("Aldi Süd", "Butter", 1.49, 250, "g")
    manager.set_store_price("Lidl", "Butter", 1.79, 250, "g")
    manager.set_store_price("Globus", "Deutsche Markenbutter", 1.69, 250, "g")

    matrix = manager.store_price_matrix("butter")
    ids = [r["id"] for r in matrix["retailers"]]
    assert ids[: len(DEFAULT_STORES)] == DEFAULT_STORES
    assert "globus" in ids  # has store prices although not selected
    row = next(r for r in matrix["rows"] if r["key"] == "butter")
    assert row["default"]["price"] == 1.99
    assert row["default"]["base"] == "g"
    assert row["stores"]["aldi-sued"]["price"] == 1.49
    assert row["stores"]["aldi-sued"]["source"] == "user"
    assert row["stores"]["aldi-sued"]["updated"]
    assert row["cheapest"] == "aldi-sued"
    assert matrix["rows"][0]["stores"]  # rows with store prices first
    everything = manager.store_price_matrix()
    assert everything["total"] > 200
    assert len(manager.store_price_matrix(limit=5)["rows"]) == 5

    result = await _call(hass, "get_store_prices", store="Lidl", query="Butter")
    assert result["retailers"] == [{"id": "lidl", "name": "Lidl", "kind": "grocery"}]
    row = next(r for r in result["rows"] if r["key"] == "butter")
    assert list(row["stores"]) == ["lidl"]
    assert row["cheapest"] is None
    with pytest.raises(ServiceValidationError):
        await _call(hass, "get_store_prices", store="Metro")

    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/store_prices", "query": "butter"})
    msg = await client.receive_json()
    assert msg["success"]
    rows = {r["key"]: r for r in msg["result"]["rows"]}
    assert rows["butter"]["stores"]["lidl"]["price"] == 1.79
    assert {"id": "aldi-sued", "name": "Aldi Süd", "kind": "grocery"} in msg["result"]["retailers"]
