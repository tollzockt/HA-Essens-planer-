"""1.4.0 review round 3: backend fixes (matching, voice, catalog, receipts).

Each test names the review finding it guards against."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.essensplaner import catalog as cat
from custom_components.essensplaner.catalog import KeyMatcher, _key_query
from custom_components.essensplaner.offers import enumeration, product_head

NETTO = "netto-marken-discount"
SENTENCES = Path(__file__).parent.parent / "custom_sentences" / "de" / "essensplaner.yaml"


@pytest.fixture
async def stores_manager(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, tmp_path
) -> Any:
    """The integration on Wednesday 2026-11-04 with REWE (main), Netto and Lidl."""
    from datetime import datetime

    from homeassistant.setup import async_setup_component

    hass.config.config_dir = str(tmp_path / "config")
    hass.config.media_dirs = {"local": str(tmp_path / "media")}
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(datetime.fromisoformat("2026-11-04T10:00:00+01:00"))
    assert await async_setup_component(hass, "homeassistant", {})
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    manager = config_entry.runtime_data
    manager.save_branch({"store": "REWE", "street": "Bahnhofstraße 3", "postcode": "57601"})
    manager.save_branch({"store": "Netto", "street": "Kornweg 7", "postcode": "57602"})
    manager.save_branch({"store": "Lidl", "street": "Lindenweg 2", "postcode": "56501"})
    return manager


# ----------------------------------------------------------------------
# fix-regressions-r3-1: variants after a comma are no products of their own
# ----------------------------------------------------------------------

_KEYS = [
    "spaghetti",
    "salami",
    "schinke",
    "erdbeere",
    "banane",
    "paprika",
    "brokkoli",
    "erbse",
    "tk erbse",
    "bohne",
    "kakao",
    "orange",
    "butter",
    "hokkaido kuerbi",
    "spinat",
    "tk spinat",
    "nudel",
    "tomate",
    "gurke",
    "kaffee",
    "pizza",
    "kirsche",
    "lasagne",
]


@pytest.mark.parametrize(
    ("product", "description", "expected"),
    [
        ("Speisekürbis Hokkaido, Butternut oder Spaghetti", "je Stück", {"hokkaido kuerbi"}),
        ("Knorr Fix, Spaghetti Bolognese oder Lasagne", "je 40-g-Btl.", set()),
        ("Buitoni Pizza, Salami oder Schinken", "je 350 g", {"pizza"}),
        ("Schwartau Extra Konfitüre, Erdbeere oder Kirsche", "je 340-g-Glas", set()),
        ("Danone Fruchtzwerge, Erdbeere oder Banane", "6 x 50 g", set()),
        ("Pringles, Original oder Paprika", "je 185-g-Dose", set()),
        ("Frosta Gemüse Pfanne, Brokkoli oder Erbsen", "tiefgefroren", set()),
        ("Kaffee, ganze Bohne oder gemahlen", "je 500 g", {"kaffee"}),
        ("Lindt Excellence, 70% Kakao oder Orange", "je 100 g", set()),
        # enumerations keep their keys (fix-regressions-r2-6)
        ("iglo Rahm-, Würz- oder Blatt-Spinat", "tiefgefroren", {"spinat", "tk spinat"}),
        ("Birkel’s No. 1, 7-Hühnchen oder 3 Glocken Nudeln", "je 500 g", {"nudel"}),
        # a list of products: every part is a product of its own
        ("Tomaten, Gurken oder Paprika", "aus Deutschland", {"tomate", "gurke", "paprika"}),
    ],
)
def test_variants_after_a_comma_are_no_products(
    product: str, description: str, expected: set
) -> None:
    """Flavours and varieties listed after the brand are no keys of their own
    (fix-regressions-r3-1)."""
    offer = {"product": product, "description": description}
    assert set(KeyMatcher(_KEYS).offer_keys(offer)) == expected


def test_product_head_and_enumeration() -> None:
    """The head is cut at the comma unless it ends with '-'; enumeration() lists the
    alternatives (none for ALDI's pack size before the comma)."""
    assert product_head("Buitoni Pizza, Salami oder Schinken") == "Buitoni Pizza"
    assert product_head("iglo Rahm-, Würz- oder Blatt-Spinat") == (
        "iglo Rahm-, Würz- oder Blatt-Spinat"
    )
    assert enumeration("Tomaten, Gurken oder Paprika") == ("Tomaten", ["Gurken", "Paprika"])
    assert enumeration("Kartoffeln 2 kg, festkochend oder mehligkochend") is None
    assert enumeration("iglo Rahm-, Würz- oder Blatt-Spinat") is None
    assert enumeration("Apfelmus 360 g, Apfel") is None
    assert enumeration("Meerrettich, Sahne 185 g") is None


async def test_variants_are_not_learned_as_regular_prices(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """A struck price of 'Buitoni Pizza, Salami oder Schinken' is no regular price of
    Salami or Schinken (fix-regressions-r3-1)."""
    manager = setup_integration.runtime_data
    for name in ("Spaghetti", "Salami", "Erdbeeren", "Paprika", "Bananen", "Brokkoli", "Schinken"):
        manager.shopping_add(name)
    rows = [
        ("Knorr Fix, Spaghetti Bolognese oder Lasagne", "je 40-g-Btl.", 0.59, 0.89, 40, "g"),
        ("Buitoni Pizza, Salami oder Schinken", "tiefgefroren", 1.99, 2.99, 350, "g"),
        ("Speisekürbis Hokkaido, Butternut oder Spaghetti", "je Stück", 1.49, 1.99, 1, "Stück"),
        ("Pringles, Original oder Paprika", "je 185-g-Dose", 1.99, 2.79, 185, "g"),
        ("Danone Fruchtzwerge, Erdbeere oder Banane", "6 x 50 g", 1.29, 1.89, 300, "g"),
        ("Frosta Gemüse Pfanne, Brokkoli oder Erbsen", "tiefgefroren", 2.99, 3.99, 480, "g"),
    ]
    offers: list[dict[str, Any]] = [
        {
            "id": f"o{i}",
            "product": name,
            "description": description,
            "price": price,
            "old_price": old,
            "pack_amount": amount,
            "pack_unit": unit,
            "retailer": "edeka",
            "source": "edeka",
        }
        for i, (name, description, price, old, amount, unit) in enumerate(rows)
    ]
    await cat.async_match_offers(manager, offers, cat.all_keys(manager))
    keys = {key for offer in offers for key in offer["keys"]}
    assert not keys & {"spaghetti", "salami", "schinke", "erdbeere", "paprika", "brokkoli"}
    manager.learn_from_offers(offers)
    learned = set(manager.store_prices_learned.get("edeka", {}))
    assert not learned & {"spaghetti", "salami", "schinke", "erdbeere", "paprika", "brokkoli"}


# ----------------------------------------------------------------------
# completeness-r3-5: Kräuterbutter, Kaffeemilch, Kaffeesahne, Buttermilch
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("product", "key", "expected"),
    [
        ("Kerrygold Kräuterbutter", "butter", False),
        ("Meggle Knoblauchbutter", "butter", False),
        ("Meggle Kräuter-Butter", "butter", False),
        ("Bärenmarke Kaffeemilch", "milch", False),
        ("Weihenstephan Buttermilch", "milch", False),
        ("Glücksklee Kaffeesahne", "sahne", False),
        ("Granatäpfel", "apfel", False),
        ("Erdnussbutter", "butter", False),
        # the product itself; other products keep their compounds
        ("Kerrygold Butter", "butter", True),
        ("Bio-Butter", "butter", True),
        ("Weidemilch", "milch", True),
        ("Schlagsahne", "sahne", True),
        ("Kräutersalz", "salz", True),
    ],
)
def test_compounds_of_another_product(product: str, key: str, expected: bool) -> None:
    """Head-specific compounds are no offers of the key, for the catalog matcher and
    for Jarvis' product questions (completeness-r3-5)."""
    keys = [key, "buttermilch", "erdnussbutter", "schlagsahne"]
    assert (key in KeyMatcher(keys).offer_keys({"product": product})) is expected
    assert _key_query(key)({"product": product}) is expected


# ----------------------------------------------------------------------
# fix-regressions-r3-2 / r3-8: price questions are no prices; a pack in the product
# ----------------------------------------------------------------------


async def _speech(hass: HomeAssistant, intent_type: str, **slots: Any) -> str:
    from homeassistant.helpers import intent

    response = await intent.async_handle(
        hass,
        "test",
        intent_type,
        {key: {"value": value} for key, value in slots.items()},
        language="de",
    )
    return response.speech["plain"]["speech"]


@pytest.mark.parametrize(
    ("sentence", "slots"),
    [
        ("butter kostet bei netto 1,79 euro", {"product": "butter", "price": "1,79"}),
        ("Butter kostet bei Netto 1,79 €", {"product": "Butter", "price": "1,79"}),
        ("butter kostet bei netto 1 euro 79", {"price": "1", "price_cent": "79"}),
        ("milch kostet bei lidl 99 cent", {"price": "99", "price_unit": "cent"}),
        ("merk dir milch kostet bei lidl 0,99", {"product": "milch", "price": "0,99"}),
        ("was kostet bei lidl 1 kg hackfleisch", None),
        ("Was kostet bei Lidl 1 kg Hackfleisch?", None),
        ("wie viel kostet beim lidl ein 500 g paket kaffee", None),
        ("was kostet im lidl 2 liter milch", None),
        ("was kostet bei rewe die butter", None),
        ("wieviel kostet bei netto die milch", None),
    ],
)
def test_set_price_sentences_need_a_price(sentence: str, slots: dict[str, str] | None) -> None:
    """The price of the sentence ends with its currency; a bare number only after "merk
    dir" – questions with the store first are no prices (fix-regressions-r3-2)."""
    from hassil import Intents, recognize_best
    import yaml

    intents = Intents.from_dict(yaml.safe_load(SENTENCES.read_text(encoding="utf-8")))
    result = recognize_best(sentence, intents)
    name = result.intent.name if result is not None else None
    if slots is None:
        assert name != "essensplaner_set_price"
        return
    assert name == "essensplaner_set_price"
    found = {k: str(v.value).removesuffix(".0").strip() for k, v in result.entities.items()}
    assert {k: found.get(k) for k in slots} == slots


async def test_set_price_question_is_not_stored(hass: HomeAssistant, stores_manager: Any) -> None:
    """A question caught by a sentence of the built-in agent stores nothing and is left
    to the conversation agent (no FAILED_TO_HANDLE answer); a tool call gets a spoken
    error; spoken forms of the sentence slots still work (fix-regressions-r3-2)."""
    from homeassistant.helpers import intent

    manager = stores_manager
    for product, price in (
        ("Was", "1 kg Hackfleisch"),
        ("Wie viel", "ein 500 g Paket Kaffee"),
        ("Butter", "die Butter"),
    ):
        slots = {
            "product": {"value": product},
            "store": {"value": "Lidl"},
            "price": {"value": price},
        }
        with pytest.raises(intent.MatchFailedError):
            await intent.async_handle(
                hass, "conversation", "essensplaner_set_price", slots, language="de"
            )
        response = await intent.async_handle(
            hass, "openai_conversation", "essensplaner_set_price", slots, language="de"
        )
        assert response.error_code == intent.IntentResponseErrorCode.FAILED_TO_HANDLE
        assert "kein P" in response.speech["plain"]["speech"]
    assert not manager.store_prices_user.get("lidl")
    await _speech(
        hass, "essensplaner_set_price", product="Butter", store="Lidl", price="1", price_cent=59
    )
    await _speech(
        hass, "essensplaner_set_price", product="Milch", store="Lidl", price="99", price_unit="cent"
    )
    lidl = manager.store_prices_user["lidl"]
    assert (lidl["butter"]["price"], lidl["milch"]["price"]) == (1.59, 0.99)


async def test_set_price_question_through_the_conversation(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, tmp_path
) -> None:
    """With the shipped sentence file, 'Was kostet bei Lidl 1 kg Hackfleisch?' saves no
    price 'Was' at Lidl (fix-regressions-r3-2)."""
    from datetime import datetime
    import shutil

    from homeassistant.components import conversation
    from homeassistant.core import Context
    from homeassistant.setup import async_setup_component

    hass.config.config_dir = str(tmp_path / "config")
    target = tmp_path / "config" / "custom_sentences" / "de"
    target.mkdir(parents=True)
    shutil.copy(SENTENCES, target / "essensplaner.yaml")
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(datetime.fromisoformat("2026-11-04T10:00:00+01:00"))
    assert await async_setup_component(hass, "homeassistant", {})
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert await async_setup_component(hass, "conversation", {})
    manager = config_entry.runtime_data
    manager.save_branch({"store": "Lidl", "street": "Lindenweg 2", "postcode": "56501"})
    for text in (
        "Was kostet bei Lidl 1 kg Hackfleisch?",
        "Wie viel kostet beim Lidl ein 500 g Paket Kaffee?",
        "Was kostet bei Lidl die Butter?",
    ):
        result = await conversation.async_converse(hass, text, None, Context(), language="de")
        speech = result.response.speech.get("plain", {}).get("speech", "")
        assert "Normalpreis" not in speech and "nicht verstanden" not in speech, speech
    assert not manager.store_prices_user.get("lidl")
    result = await conversation.async_converse(
        hass, "Butter kostet bei Lidl 1 Euro 59", None, Context(), language="de"
    )
    assert result.response.intent.intent_type == "essensplaner_set_price"
    assert manager.store_prices_user["lidl"]["butter"]["price"] == 1.59


async def test_set_price_with_the_pack_in_the_product(
    hass: HomeAssistant, stores_manager: Any
) -> None:
    """'Butter 250 g' is the price of Butter in 250 g, no row 'butter 250 g'; the same for
    an offer typed with its pack (fix-regressions-r3-8)."""
    manager = stores_manager
    manager.set_price("Butter", 1.99, 250, "g", "Lidl")
    speech = await _speech(
        hass, "essensplaner_set_price", product="Butter 250 g", store="Lidl", price="1,59 Euro"
    )
    assert speech.startswith("Okay, Butter kostet bei Lidl 1,59 € (250 g).")
    lidl = manager.store_prices_user["lidl"]
    assert set(lidl) == {"butter"}
    assert (lidl["butter"]["price"], lidl["butter"]["amount"]) == (1.59, 250)
    assert manager.store_book("lidl").lookup("Butter").price == 1.59
    offer = manager.add_offer("Hackfleisch 500 g", "Netto", 3.49)
    assert offer["keys"] == ["hackfleisch"]
    assert (offer["pack_amount"], offer["pack_unit"]) == (500, "g")


# ----------------------------------------------------------------------
# fix-regressions-r3-6: a tie names only the stores with that price
# ----------------------------------------------------------------------


async def test_compare_prices_tie_names_only_the_cheapest(
    hass: HomeAssistant, stores_manager: Any
) -> None:
    """REWE and Lidl 1,99 €, Netto 2,49 €: Netto is no store "für 1,99 €"; "überall" only
    when every store has the price (fix-regressions-r3-6)."""
    manager = stores_manager
    manager.save_branch({"store": "Norma", "street": "Kornweg 1", "postcode": "57602"})
    labels = {b["retailer"]: manager.branch_label(b) for b in manager.selected_branches()}
    rewe, lidl, netto, norma = (labels[r] for r in ("rewe", "lidl", NETTO, "norma"))
    manager.set_price("Butter", 1.99, 250, "g", "REWE")
    manager.set_price("Butter", 1.99, 250, "g", "Lidl")
    manager.set_price("Butter", 2.49, 250, "g", "Netto")
    result = manager.compare_prices("Butter")
    assert [r["retailer"] for r in result["tied"]] == ["rewe", "lidl"]
    assert await _speech(hass, "essensplaner_compare_prices", item="Butter") == (
        f"Butter gibt es bei {rewe} und bei {lidl} für 1,99 € (250 g). Bei {netto} 2,49 € (250 g)."
    )
    manager.set_price("Butter", 1.99, 250, "g", "Norma")
    manager.set_price("Butter", 1.99, 250, "g", "Netto")
    manager.set_price("Butter", 2.29, 250, "g", "REWE")
    assert await _speech(hass, "essensplaner_compare_prices", item="Butter") == (
        f"Butter gibt es bei {netto}, bei {lidl} und bei {norma} für 1,99 € (250 g). "
        f"Bei {rewe} 2,29 € (250 g)."
    )
    manager.set_price("Butter", 1.99, 250, "g", "REWE")
    assert await _speech(hass, "essensplaner_compare_prices", item="Butter") == (
        "Butter gibt es überall für 1,99 € (250 g)."
    )


# ----------------------------------------------------------------------
# completeness-r3-2: a store's offer is its price, also above the Richtwert
# ----------------------------------------------------------------------


async def test_compare_prices_offer_above_the_estimate(
    hass: HomeAssistant, stores_manager: Any
) -> None:
    """An offer dearer than or as dear as the Richtwert is the store's price in the price
    comparison, not the estimate (completeness-r3-2)."""
    manager = stores_manager
    rewe = manager.branch_label(manager.get_main_branch())
    manager.add_offer("Butter 250 g", "REWE", 2.49)
    result = manager.compare_prices("Butter")
    by_retailer = {r["retailer"]: r for r in result["results"]}
    assert by_retailer["rewe"]["real"] is True
    assert by_retailer["rewe"]["price"] == 2.49
    assert by_retailer["rewe"]["offer"]
    assert result["estimate"]["price"] == 1.99
    assert await _speech(hass, "essensplaner_compare_prices", item="Butter") == (
        f"Ich kenne nur den Preis bei {rewe}: 2,49 € (250 g) im Angebot."
    )
    # as dear as the Richtwert
    manager.add_offer("Milch 1 l", "Lidl", 0.99)
    milk = {r["retailer"]: r for r in manager.compare_prices("Milch")["results"]}
    assert milk["lidl"]["real"] is True and milk["lidl"]["offer"]
    # the shopping list still takes the cheapest way to buy (price_at() unchanged)
    item = {"name": "Butter", "key": "butter", "amounts": {}, "source": "manual"}
    assert manager.price_at(item, "rewe", by_unit=True)["price"] == 1.99


# ----------------------------------------------------------------------
# fix-regressions-r3-3: typing an offer from the leaflet keeps the leaflet tiles
# (tests/test_review_1_4_r2.py::test_own_offers_in_the_store_view_and_price_list)
# completeness-r3-1: items added after a catalog refresh get their offers locally
# ----------------------------------------------------------------------


@pytest.fixture
def catalog_clock(freezer, monkeypatch) -> None:
    """The catalog tests' day without politeness delays."""
    from custom_components.essensplaner import aldi, articles, edeka, offers

    from .test_catalog_1_4 import NOW

    freezer.move_to(NOW)
    monkeypatch.setattr(cat, "REQUEST_DELAY", 0)
    monkeypatch.setattr(offers, "REQUEST_DELAY", 0)
    monkeypatch.setattr(edeka, "REQUEST_DELAY", 0)
    monkeypatch.setattr(aldi, "REQUEST_DELAY", 0)
    monkeypatch.setattr(articles, "LIVE_MIN_INTERVAL", 0)


def _assigned(manager: Any, name: str) -> tuple[Any, ...]:
    item = next(i for i in manager.shopping if i.get("summary") == name)
    offer = item.get("offer") or {}
    return item.get("store_label"), item.get("store_reason"), offer.get("title")


async def test_item_added_after_the_refresh_gets_its_offer(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: Any,
    catalog_clock: None,
) -> None:
    """Kaffee put on the list after the catalog refresh goes to Netto's offer without
    another request (30 s later); the daily check and the manual refresh in its cooldown
    match the catalog again too (completeness-r3-1)."""
    from datetime import timedelta

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    from custom_components.essensplaner.catalog import planning_keys, store_offers_view
    from custom_components.essensplaner.const import DOMAIN

    from .test_catalog_1_4 import _mock_marktguru, _refresh, _user

    _mock_marktguru(aioclient_mock)
    manager, branches = await _user(hass, config_entry, freezer, offers_watchlist="Butter, Milch")
    await _refresh(hass)
    assert "kaffee" not in planning_keys(manager)
    netto = manager.branch_label(branches["netto-marken-discount"])
    calls = len(aioclient_mock.mock_calls)

    await hass.services.async_call(DOMAIN, "add_shopping_item", {"item": "Kaffee"}, blocking=True)
    await hass.async_block_till_done()
    assert _assigned(manager, "Kaffee")[1] == "main"
    freezer.tick(timedelta(seconds=31))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    label, reason, title = _assigned(manager, "Kaffee")
    assert (label, reason) == (netto, "offer")
    assert "Kaffee" in title
    assert any("kaffee" in (o.get("keys") or []) for o in manager.offers)
    mine = store_offers_view(manager, mine=True, when="all")["offers"]
    assert any("kaffee" in o["keys"] for o in mine)
    assert len(aioclient_mock.mock_calls) == calls  # no request

    # a change without new keys matches nothing again
    signature = manager.catalog.match_signature
    assert not await cat.async_rematch_catalog(manager)
    assert manager.catalog.match_signature == signature

    # the manual refresh in its cooldown matches the catalog (no request either)
    manager.shopping_add("Frischkäse")
    result = await _refresh(hass)
    assert result["message"].startswith("Angebote neu abgeglichen – neu abrufen ab ")
    assert len(aioclient_mock.mock_calls) == calls
    result = await _refresh(hass)
    assert result["message"].startswith("Gerade erst aktualisiert")


# ----------------------------------------------------------------------
# completeness-r3-3: reduced REWE articles of the online prices are offers
# ----------------------------------------------------------------------


async def test_reduced_rewe_articles_are_offers(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock: Any, monkeypatch
) -> None:
    """'Weidebutter' reduced to 1,49 € (regular 2,49 €) is a REWE offer until Saturday;
    the regular price is still learned, REWE's chip names the source
    (completeness-r3-3)."""
    from custom_components.essensplaner.catalog import own_offers, store_offers_view
    from custom_components.essensplaner.rewe import async_refresh_rewe_prices

    from .test_rewe import _mock_searches, _rewe_entry

    monkeypatch.setattr("custom_components.essensplaner.rewe.REQUEST_DELAY", 0)
    monkeypatch.setattr("custom_components.essensplaner.rewe.MAX_TERMS", 3)
    entry = await _rewe_entry(hass, config_entry, freezer)
    manager = entry.runtime_data
    _mock_searches(aioclient_mock)
    status = await async_refresh_rewe_prices(hass, manager)
    assert status["status"] == "ok"

    reduced = [o for o in manager.offers if o.get("source") == "rewe_online"]
    assert [(o["product"], o["price"], o["old_price"], o["keys"]) for o in reduced] == [
        ("Weidebutter", 1.49, 2.49, ["butter"])
    ]
    assert reduced[0]["valid_to"] == "2026-11-07"  # the coming Saturday
    learned = manager.store_prices_learned["rewe"]["butter"]
    assert (learned["price"], learned["source"]) == (1.99, "rewe_online")
    assert [o["id"] for o in own_offers(manager, manager.today())] == [reduced[0]["id"]]
    view = store_offers_view(manager, when="all")
    rewe = next(s for s in view["stores"] if s["retailer"] == "rewe")
    assert rewe["sources"] == ["rewe_online"]
    assert (rewe["count_current"], rewe["status"]) == (1, "ok")
    row = next(r for r in manager.store_price_matrix()["rows"] if r["key"] == "butter")
    assert row["offers"]["rewe"]["price"] == 1.49


# ----------------------------------------------------------------------
# fix-regressions-r3-5: a truncated word known only from an estimate's alias is a guess
# ----------------------------------------------------------------------


async def test_receipt_completions_of_aliases_are_suggestions(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """'BUTTERSCHM.' (Butterschmalz, an alias of Butter), 'RAEUCHERL.' (Räucherlachs under
    Lachsfilet) and the like are only suggestions; own names still complete for sure
    (fix-regressions-r3-5)."""
    from custom_components.essensplaner.receipts import MIN_CONFIDENCE, ReceiptMapper

    manager = setup_integration.runtime_data
    mapper = ReceiptMapper(manager, "rewe")
    for name in (
        "BUTTERSCHM. 500G",
        "RAEUCHERL. 100G",
        "EIERNUD.",
        "BUTTERKAES.",
        "GAENSESCHM.",
        "SCHOKOL. VOLLM.",
    ):
        found = mapper.map(name)
        assert found["confidence"] < MIN_CONFIDENCE, (name, found)
    for name, key in (
        ("WEIZENM. 1KG", "weizenmehl"),
        ("SONNENBL.OEL 1L", "sonnenblumenoel"),
        ("SCHWEINESCHM.", "schweineschmalz"),
    ):
        found = mapper.map(name)
        assert (found["key"], found["confidence"] >= MIN_CONFIDENCE) == (key, True), name
