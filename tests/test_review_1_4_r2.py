"""1.4.0 review round 2: backend fixes (matching, receipts, refresh, voice).

Each test names the review finding it guards against."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.essensplaner import edeka
from custom_components.essensplaner.catalog import KeyMatcher
from custom_components.essensplaner.offers import flavour_only, offer_matches, product_head

# ----------------------------------------------------------------------
# fix-regressions-r2-1: "tiefgefroren" in the description is a TK product
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Gut & Günstig Erbsen tiefgefroren", True),
        ("Erbsen tiefgekühlt", True),
        ("Tiefkühl-Erbsen", True),
        ("Erbsen frisch", False),
    ],
)
def test_tk_written_out_after_singular(text: str, expected: bool) -> None:
    """'tiefgefroren' is singularised to 'tiefgefrore' and still counts as "tk"."""
    assert offer_matches(text, "tk erbse") is expected


@pytest.mark.parametrize(
    ("product", "description", "expected"),
    [
        ("Iglo Junge Erbsen", "tiefgefroren, je 750-g-Beutel", {"tk erbse", "erbse"}),
        ("Iglo Blatt-Spinat", "natur, tiefgefroren, je 500-g-Pckg.", {"tk spinat", "spinat"}),
        ("Erbsen", "je 450-g-Dose", {"erbse"}),
        ("Spinat", "aus Deutschland, je 500 g", {"spinat"}),
        ("Weidemilch", "haltbar, 1,5 % Fett, je 1 l", {"h milch", "milch"}),
        ("Bergbauern-Milch", "gekühlt länger haltbar, 3,5% Fett", {"milch"}),
    ],
)
def test_tk_word_of_the_description(product: str, description: str, expected: set) -> None:
    """The short word of a key may come from the description, the long ones from the
    product (fix-regressions-r2-1)."""
    matcher = KeyMatcher(["tk erbse", "erbse", "tk spinat", "spinat", "h milch", "milch"])
    offer = {"product": product, "description": description}
    assert set(matcher.offer_keys(offer)) == expected


# ----------------------------------------------------------------------
# fix-regressions-r2-6: enumerations are no ALDI variant, alternatives no flavour
# ----------------------------------------------------------------------


def test_product_head_keeps_enumerations() -> None:
    """Only ALDI's "Name 360 g, Variante" is cut at the comma (fix-regressions-r2-6)."""
    assert product_head("Apfelmus 360 g, Apfel") == "Apfelmus 360 g"
    assert product_head("Meerrettich, Sahne 185 g") == "Meerrettich"
    assert product_head("Backzutaten, Mehl & Zucker") == "Mehl & Zucker"
    birkel = "Birkel’s No. 1, 7-Hühnchen oder 3 Glocken Nudeln"
    assert product_head(birkel) == birkel
    assert product_head("iglo Rahm-, Würz- oder Blatt-Spinat") == (
        "iglo Rahm-, Würz- oder Blatt-Spinat"
    )
    assert product_head("Kartoffeln 2 kg, festkochend oder mehligkochend") == "Kartoffeln 2 kg"


@pytest.mark.parametrize(
    ("product", "description", "expected"),
    [
        ("Birkel’s No. 1, 7-Hühnchen oder 3 Glocken Nudeln", "je 500 g", {"nudel"}),
        ("iglo Rahm-, Würz- oder Blatt-Spinat", "tiefgefroren", {"spinat", "tk spinat"}),
        ("Mövenpick Joghurt oder Pudding", "je 150 g", {"joghurt", "pudding"}),
        ("Bürger Gefüllte Kartoffel Gnocchi", "je 400 g", {"gnocchi"}),
        # still a ready meal / a flavour
        ("Petz Gefüllte Paprika", "mit Schweine-Hackfleisch", set()),
        ("Arla Skyr Drink Erdbeere oder Himbeere", "je 330-ml-Fl.", set()),
    ],
)
def test_enumerated_offers_keep_their_keys(product: str, description: str, expected: set) -> None:
    """Commas of an enumeration, "X oder Y" and filled pasta keep their keys
    (fix-regressions-r2-6)."""
    keys = [
        "nudel",
        "spinat",
        "tk spinat",
        "joghurt",
        "pudding",
        "kartoffel",
        "gnocchi",
        "paprika",
        "erdbeere",
        "himbeere",
    ]
    offer = {"product": product, "description": description}
    assert set(KeyMatcher(keys).offer_keys(offer)) == expected


def test_flavour_only_alternatives() -> None:
    """A carrier joined to the key by "oder" is an alternative, not the kind of product."""
    assert not flavour_only("Mövenpick Joghurt oder Pudding", "joghurt")
    assert not flavour_only("Mövenpick Joghurt oder Pudding", "pudding")
    assert flavour_only("Arla Skyr Drink Erdbeere", "erdbeere")
    assert flavour_only("Ingwer Shots", "ingwer")


# ----------------------------------------------------------------------
# fix-regressions-r2-4 (+ r2-1): EDEKA's planning offers use the catalog matcher
# ----------------------------------------------------------------------


def _edeka_doc(base: dict[str, Any], offer_id: int, title: str, description: str) -> dict:
    return {**base, "angebotid": offer_id, "titel": title, "beschreibung": description}


async def test_edeka_planning_offers_use_the_catalog_matcher(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch,
) -> None:
    """Granatäpfel are no Äpfel, an Ingwer Shot no Ingwer, Kondensmilch no Milch, a Skyr
    Drink no Erdbeere – in the planning offers as in the catalog; frozen peas named
    "tiefgefroren" only in the description are TK-Erbsen (fix-regressions-r2-4, r2-1)."""
    from custom_components.essensplaner.edeka import (
        OFFERS_URL as EDEKA_OFFERS_URL,
        async_refresh_edeka_offers,
    )

    from .test_chain_sources_1_4 import _edeka_entry, _load

    monkeypatch.setattr(edeka, "REQUEST_DELAY", 0)
    entry = await _edeka_entry(hass, config_entry, freezer)
    manager = entry.runtime_data
    for name in ("Butter", "Äpfel", "Erdbeeren", "Ingwer", "Zitrone", "Milch", "TK-Erbsen"):
        manager.shopping_add(name)
    answer = _load("edeka_offers")
    base = answer["docs"][4]
    answer["docs"] = [
        _edeka_doc(base, 7000001, "Granatäpfel", "aus Spanien, je Stück"),
        _edeka_doc(base, 7000002, "Arla Skyr Drink Erdbeere", "je 350-g-Flasche"),
        _edeka_doc(base, 7000003, "Bangs Bio Ingwer Shot", "je 60 ml Flasche"),
        _edeka_doc(base, 7000004, "Kondensmilch", "7,5 % Fett, je 340 g Dose"),
        _edeka_doc(base, 7000005, "Premium Eistee Zitrone-Himbeere", "je 1,5 l Flasche"),
        _edeka_doc(base, 7000006, "Iglo Junge Erbsen", "tiefgefroren, je 750-g-Beutel"),
        _edeka_doc(base, 7000007, "Kerrygold Butter", "je 250 g Packung"),
        _edeka_doc(base, 7000008, "Tafeläpfel Elstar", "aus Deutschland, je kg"),
    ]
    aioclient_mock.get(EDEKA_OFFERS_URL, json=answer)

    status = await async_refresh_edeka_offers(hass, manager)
    assert status["status"] == "ok"
    stored = {o["product"]: o["keys"] for o in manager.offers if o["source"] == "edeka"}
    assert set(stored) == {"Iglo Junge Erbsen", "Kerrygold Butter", "Tafeläpfel Elstar"}
    assert "tk erbse" in stored["Iglo Junge Erbsen"]
    assert stored["Kerrygold Butter"] == ["butter"]
    assert stored["Tafeläpfel Elstar"] == ["aepfel"]
    # the catalog sees the same
    matcher = KeyMatcher(["butter", "aepfel", "erdbeere", "ingwer", "zitrone", "milch"])
    for doc in answer["docs"][:5]:
        assert matcher.offer_keys({"product": doc["titel"], "description": ""}) == []


# ----------------------------------------------------------------------
# fix-regressions-r2-3: an offer price needs the same price and the same article
# ----------------------------------------------------------------------


@pytest.fixture
async def receipts_manager(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, tmp_path
) -> Any:
    """The integration with its own config / media folders, REWE, Netto and Lidl."""
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
    manager.save_branch({"store": "REWE", "street": "Bahnhofstraße 30", "postcode": "57610"})
    manager.save_branch({"store": "Netto", "street": "Kornbitze 7", "postcode": "57632"})
    manager.save_branch({"store": "Lidl", "street": "Landblum 2", "postcode": "56593"})
    return manager


async def _service(hass: HomeAssistant, service: str, **data: Any) -> Any:
    from custom_components.essensplaner.const import DOMAIN

    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


NETTO_HEAD = "NETTO\nKornbitze 7\n57632 Flammersfeld\n"
NETTO = "netto-marken-discount"


async def test_receipt_offer_needs_the_same_article(
    hass: HomeAssistant, receipts_manager: Any
) -> None:
    """Another brand at (about) the offer's price is a regular price; the same brand at
    the offer's price is the offer (fix-regressions-r2-3)."""
    from datetime import date

    from custom_components.essensplaner.receipts import _same_article

    manager = receipts_manager
    manager.add_offer(
        "Kerrygold Butter", "Netto", 1.79, "250 g", date(2026, 11, 2), date(2026, 11, 7), 2.39
    )
    for line in ("GUT LAND DEUTSCHE MARKENBUTTER 1,75 A", "GUT LAND DEUTSCHE MARKENBUTTER 1,79 A"):
        text = f"{NETTO_HEAD}{line}\nSUMME {line[-6:-2]}\n03.11.2026"
        proposal = await _service(hass, "receipt_parse_text", text=text)
        item = proposal["items"][0]
        assert (item["key"], item["offer"]) == ("butter", None), line
        assert not (item["warning"] or "").startswith("Angebotspreis")
    result = await _service(hass, "receipt_save", receipt=proposal)
    assert (result["saved"], result["offer"]) == (1, 0)
    butter = manager.store_prices_user[NETTO]["butter"]
    assert (butter["price"], butter["source"]) == (1.79, "receipt")
    # the offer's brand (also truncated) at the offer's price is the offer
    for line in ("KERRYGOLD IRISCHE BUTTER 1,79 A", "BUTTER 1,79 A"):
        text = f"{NETTO_HEAD}{line}\nSUMME 1,79\n03.11.2026"
        proposal = await _service(hass, "receipt_parse_text", text=text)
        assert proposal["items"][0]["offer"]["price"] == 1.79, line
    offer = {"product": "Kerrygold Butter", "brand": "Kerrygold"}
    assert _same_article(offer, "butter", "KERRYG. BUTTER")
    assert not _same_article(offer, "butter", "GUT LAND DEUTSCHE MARKENBUTTER")
    assert _same_article({"product": "Deutsche Markenbutter"}, "butter", "GUT LAND BUTTER")


async def test_receipt_offer_line_saved_as_regular_price(
    hass: HomeAssistant, receipts_manager: Any
) -> None:
    """'trotzdem als Normalpreis' (item "regular") saves an offer line as the regular
    price (fix-regressions-r2-3)."""
    from datetime import date

    manager = receipts_manager
    manager.add_offer(
        "Kerrygold Butter", "Netto", 1.79, "250 g", date(2026, 11, 2), date(2026, 11, 7), 2.39
    )
    text = f"{NETTO_HEAD}KERRYGOLD IRISCHE BUTTER 1,79 A\nSUMME 1,79\n03.11.2026"
    proposal = await _service(hass, "receipt_parse_text", text=text)
    assert proposal["items"][0]["offer"]
    assert proposal["items"][0]["regular"] is False
    proposal["items"][0]["regular"] = True
    result = await _service(hass, "receipt_save", receipt=proposal)
    assert (result["saved"], result["offer"]) == (1, 0)
    assert manager.store_prices_user[NETTO]["butter"]["price"] == 1.79
    assert result["receipt"]["items"][0]["regular"] is True


async def test_receipt_saved_again_as_offer_restores_the_price_before(
    hass: HomeAssistant, receipts_manager: Any
) -> None:
    """A line saved as regular price that is an offer when saved again gives the price
    before the receipt back (or none) (fix-regressions-r2-3)."""
    from datetime import date

    manager = receipts_manager
    manager.set_store_price("Netto", "Butter", 2.39, 250, "g")
    manager.set_store_price("Netto", "Milch", 1.09, 1, "l")
    text = f"{NETTO_HEAD}KERRYGOLD IRISCHE BUTTER 1,79 A\nWEIDEMILCH 0,99 A\nSUMME 2,78\n04.11.2026"
    proposal = await _service(hass, "receipt_parse_text", text=text)
    first = await _service(hass, "receipt_save", receipt=proposal)
    assert first["saved"] == 2
    bucket = manager.store_prices_user[NETTO]
    assert (bucket["butter"]["price"], bucket["butter"]["source"]) == (1.79, "receipt")
    # the leaflet offers become known later
    manager.add_offer(
        "Kerrygold Butter", "Netto", 1.79, "250 g", date(2026, 11, 2), date(2026, 11, 7), 2.39
    )
    manager.add_offer(
        "Weidemilch", "Netto", 0.99, "1 l", date(2026, 11, 2), date(2026, 11, 7), 1.19
    )
    again = await _service(hass, "receipt_save", receipt={**proposal, "id": first["receipt"]["id"]})
    assert (again["saved"], again["offer"]) == (0, 2)
    bucket = manager.store_prices_user[NETTO]
    assert (bucket["butter"]["price"], bucket["butter"]["source"]) == (2.39, "user")
    assert [h["price"] for h in bucket["butter"]["history"] if h.get("offer")] == [1.79]
    assert (bucket["milch"]["price"], bucket["milch"]["source"]) == (1.09, "user")


async def test_receipt_saved_again_as_offer_without_a_price_before(
    hass: HomeAssistant, receipts_manager: Any
) -> None:
    """Without a price before the receipt, its price goes when it turns out to be an
    offer (fix-regressions-r2-3)."""
    from datetime import date

    manager = receipts_manager
    text = f"{NETTO_HEAD}KERRYGOLD IRISCHE BUTTER 1,79 A\nSUMME 1,79\n04.11.2026"
    proposal = await _service(hass, "receipt_parse_text", text=text)
    first = await _service(hass, "receipt_save", receipt=proposal)
    assert manager.store_prices_user[NETTO]["butter"]["price"] == 1.79
    manager.add_offer(
        "Kerrygold Butter", "Netto", 1.79, "250 g", date(2026, 11, 2), date(2026, 11, 7), 2.39
    )
    again = await _service(hass, "receipt_save", receipt={**proposal, "id": first["receipt"]["id"]})
    assert again["offer"] == 1
    assert "butter" not in manager.store_prices_user.get(NETTO, {})


# ----------------------------------------------------------------------
# fix-regressions-r2-5: linking the ALDI SÜD service point is no store change
# ----------------------------------------------------------------------


@pytest.fixture
def catalog_user(freezer, monkeypatch) -> None:
    """The frozen day and no politeness delays of the catalog tests."""
    from custom_components.essensplaner import aldi, articles, catalog, offers

    from .test_catalog_1_4 import NOW

    freezer.move_to(NOW)
    monkeypatch.setattr(catalog, "REQUEST_DELAY", 0)
    monkeypatch.setattr(offers, "REQUEST_DELAY", 0)
    monkeypatch.setattr(edeka, "REQUEST_DELAY", 0)
    monkeypatch.setattr(aldi, "REQUEST_DELAY", 0)
    monkeypatch.setattr(aldi, "MAX_TERMS", 3)
    monkeypatch.setattr(articles, "LIVE_MIN_INTERVAL", 0)


async def _minutes(hass: HomeAssistant, freezer, count: int) -> None:
    from datetime import timedelta

    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    for _ in range(count):
        freezer.tick(timedelta(seconds=61))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()


async def test_aldi_auto_link_starts_no_second_refresh(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
    catalog_user: None,
) -> None:
    """A new ALDI SÜD branch: the refresh links its service point and fetches every source
    once – the link does not count as another store change (fix-regressions-r2-5)."""
    from collections import Counter

    from custom_components.essensplaner.aldi import (
        SEARCH_URL as ALDI_SEARCH_URL,
        SERVICE_POINTS_URL,
    )
    from custom_components.essensplaner.catalog import catalog_untried
    from custom_components.essensplaner.const import CONF_ALDI_ONLINE

    from .test_catalog_1_4 import _load, _mg_calls, _mock_marktguru, _user

    _mock_marktguru(aioclient_mock)
    aioclient_mock.get(SERVICE_POINTS_URL, json=_load("aldi_service_points"))
    aioclient_mock.get(ALDI_SEARCH_URL, json=_load("aldi_weekly_offers"))
    manager, _ = await _user(hass, config_entry, freezer, **{CONF_ALDI_ONLINE: True})
    await _minutes(hass, freezer, 5)  # the start checks
    aioclient_mock.mock_calls.clear()
    manager.save_branch(
        {
            "store": "Aldi Süd",
            "postcode": "56593",
            "street": "Hauptstr. 1",
            "lat": 50.62,
            "lon": 7.43,
        }
    )
    await _minutes(hass, freezer, 10)
    aldi = [b for b in manager.branches if b.get("retailer") == "aldi-sued"]
    assert aldi[0].get("aldi_service_point")
    calls = Counter(_mg_calls(aioclient_mock))
    assert calls and max(calls.values()) == 1, calls
    points = [c for c in aioclient_mock.mock_calls if str(c[1]).startswith(SERVICE_POINTS_URL)]
    assert len(points) == 1
    assert not catalog_untried(manager)


# ----------------------------------------------------------------------
# completeness-r2-1: Jarvis never names an estimate as a store's price
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


async def test_compare_prices_names_only_real_prices(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, catalog_user: None
) -> None:
    """Only the main store known: no "überall"; a store without a price is never the
    cheapest by its estimate; a drugstore's own price is the only one (completeness-r2-1)."""
    from .test_catalog_1_4 import _user

    manager, branches = await _user(hass, config_entry, freezer, marktguru=False)
    rewe = manager.branch_label(branches["rewe"])
    manager.set_store_price("REWE", "Butter", 2.29, 250, "g")
    assert await _speech(hass, "essensplaner_compare_prices", item="Butter") == (
        f"Ich kenne nur den Preis bei {rewe}: 2,29 € (250 g)."
    )
    for store, price in (("Norma", 2.39), ("Lidl", 2.49), ("EDEKA", 2.59), ("Rossmann", 2.99)):
        manager.set_store_price(store, "Butter", price, 250, "g")
    result = manager.compare_prices("Butter")
    assert result["cheapest"]["retailer"] == "rewe"
    assert result["estimate"]["price"] == 1.99
    assert [r["retailer"] for r in result["results"] if not r["real"]] == ["netto-marken-discount"]
    speech = await _speech(hass, "essensplaner_compare_prices", item="Butter")
    assert speech.startswith(f"Am günstigsten gibt es Butter bei {rewe}: 2,29 € (250 g).")
    assert "Netto" not in speech and "1,99" not in speech

    manager.set_store_price("Rossmann", "Zahnpasta", 0.95, 75, "ml")
    rossmann = manager.branch_label(branches["rossmann"])
    assert await _speech(hass, "essensplaner_compare_prices", item="Zahnpasta") == (
        f"Ich kenne nur den Preis bei {rossmann}: 0,95 € (75 ml)."
    )
    speech = await _speech(hass, "essensplaner_compare_prices", item="Duschgel")
    assert speech.startswith("Für Duschgel kenne ich noch keinen Ladenpreis (Richtwert ")


# ----------------------------------------------------------------------
# completeness-r2-2: product questions find the product, not any text containing it
# ----------------------------------------------------------------------


async def test_voice_offer_questions_match_the_product(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
    catalog_user: None,
) -> None:
    """'Wo ist Kaffee im Angebot?' names no coffee machine, 'Apfel' no Granatapfel,
    'Butter' no Butter-Spekulatius / Butterkeks / Butterschmalz; the panel's search box
    still finds any text (completeness-r2-2)."""
    from custom_components.essensplaner.catalog import store_offers_view

    from .test_catalog_1_4 import _mock_marktguru, _refresh, _user

    _mock_marktguru(aioclient_mock)
    manager, _ = await _user(hass, config_entry, freezer)
    await _refresh(hass)

    def titles(query: str, match: str) -> list[str]:
        view = store_offers_view(manager, when="all", query=query, limit=200, match=match)
        return [o["title"] for o in view["offers"]]

    assert any("Kaffeevollautomat" in t for t in titles("Kaffee", "text"))
    assert not any("Kaffeevollautomat" in t for t in titles("Kaffee", "key"))
    assert titles("Kaffee", "key")
    assert any("Granatapfel" in t for t in titles("Apfel", "text"))
    assert not any("Granatapfel" in t for t in titles("Apfel", "key"))
    butter = titles("Butter", "key")
    assert butter
    assert not any(
        word in title.lower()
        for title in butter
        for word in ("spekulatius", "butterkeks", "schmalz")
    ), butter
    for query in ("Kaffee", "Apfel", "Butter"):
        speech = await _speech(hass, "essensplaner_get_offers", query=query, when="alle")
        assert "Kaffeevollautomat" not in speech
        assert "Granatapfel" not in speech
        assert "Spekulatius" not in speech


# ----------------------------------------------------------------------
# completeness-r2-3: offers typed from a leaflet (and reduced ALDI items) per store
# ----------------------------------------------------------------------


async def test_own_offers_in_the_store_view_and_price_list(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
    catalog_user: None,
) -> None:
    """An offer typed from the NORMA leaflet shows under the NORMA chip (no longer
    leaflet-only) and in the price list's butter row (completeness-r2-3)."""
    from datetime import date

    from custom_components.essensplaner.catalog import store_offers_view

    from .test_catalog_1_4 import _mock_marktguru, _refresh, _user

    _mock_marktguru(aioclient_mock)
    manager, branches = await _user(hass, config_entry, freezer)
    await _refresh(hass)
    norma = branches["norma"]["id"]
    before = next(s for s in store_offers_view(manager)["stores"] if s["branch_id"] == norma)
    assert (before["count_current"], before["leaflet_only"]) == (0, True)

    offer = manager.add_offer("Butter", manager.branch_label(branches["norma"]), 1.49, "250 g")
    view = store_offers_view(manager, branch_ids=[norma], when="all")
    chip = next(s for s in view["stores"] if s["branch_id"] == norma)
    assert (chip["count_current"], chip["leaflet_only"]) == (1, False)
    assert [(o["id"], o["source"], o["branch_ids"]) for o in view["offers"]] == [
        (offer["id"], "manual", [norma])
    ]
    # only for the branch it was entered for, also in a product search
    netto = branches["netto-marken-discount"]["id"]
    assert offer["id"] not in [
        o["id"] for o in store_offers_view(manager, branch_ids=[netto], when="all")["offers"]
    ]
    assert offer["id"] in [
        o["id"] for o in store_offers_view(manager, query="Butter", match="key")["offers"]
    ]
    row = next(r for r in manager.store_price_matrix()["rows"] if r["key"] == "butter")
    assert row["offers"]["norma"]["price"] == 1.49
    assert row["offers"]["norma"]["source"] == "manual"
    # a catalog offer pinned with "📌 Merken" (a manual copy) is listed once
    lidl = branches["lidl"]["id"]
    original = store_offers_view(manager, branch_ids=[lidl], when="current")["offers"][0]
    manager.add_offer(
        original["title"],
        manager.branch_label(branches["lidl"]),
        original["price"],
        None,
        None,
        date.fromisoformat(original["valid_to"]),
    )
    titles = [
        o["title"] for o in store_offers_view(manager, branch_ids=[lidl], when="all")["offers"]
    ]
    assert titles.count(original["title"]) == 1
    # an ended offer is gone again
    manager.offers = [
        {**o, "valid_to": "2026-11-01"} if o["id"] == offer["id"] else o for o in manager.offers
    ]
    assert offer["id"] not in [o["id"] for o in store_offers_view(manager, when="all")["offers"]]


# ----------------------------------------------------------------------
# completeness-r2-5: a store with only leaflet images says so
# ----------------------------------------------------------------------


async def test_voice_offers_of_a_leaflet_only_store(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer,
    aioclient_mock: AiohttpClientMocker,
    catalog_user: None,
) -> None:
    """'Was hat Norma im Angebot?' with only leaflet pages: where to find them; EDEKA with
    its own offers switched off: the setting that brings them (completeness-r2-5)."""
    from .test_catalog_1_4 import _mock_marktguru, _refresh, _user

    _mock_marktguru(aioclient_mock)
    await _user(hass, config_entry, freezer)
    await _refresh(hass)
    speech = await _speech(hass, "essensplaner_get_offers", store="Norma")
    assert speech.startswith("Ich habe keine passenden Angebote gefunden.")
    assert "gibt es nur den Prospekt als Bilder" in speech
    assert "Angebote, Alle Angebote meiner Läden" in speech
    assert "EDEKA" not in speech
    speech = await _speech(hass, "essensplaner_get_offers", store="EDEKA")
    assert "gibt es nur den Prospekt als Bilder" in speech
    assert "Mit „EDEKA-Angebote“ in den Einstellungen" in speech
    # a store with offers: no hint
    speech = await _speech(hass, "essensplaner_get_offers", store="Lidl")
    assert "Prospekt als Bilder" not in speech


# ----------------------------------------------------------------------
# completeness-r2-9: brand names of drugstore and household products
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "category"),
    [
        ("Persil", "Haushalt & Reinigung"),
        ("Zewa", "Haushalt & Reinigung"),
        ("Somat", "Haushalt & Reinigung"),
        ("Finish Tabs", "Haushalt & Reinigung"),
        ("Frosch", "Haushalt & Reinigung"),
        ("Tempo", "Drogerie & Körperpflege"),
        ("Elmex", "Drogerie & Körperpflege"),
        ("Oral-B", "Drogerie & Körperpflege"),
        ("Nivea Creme", "Drogerie & Körperpflege"),
        # whole words only: no food is hit
        ("Froschschenkel", "Sonstiges"),
        ("April-Tomaten", "Obst & Gemüse"),
        ("Butter", "Milchprodukte & Eier"),
    ],
)
def test_brand_names_of_nonfood(name: str, category: str) -> None:
    """Brand names used as product names get their aisle (completeness-r2-9)."""
    from custom_components.essensplaner.ingredients import guess_category

    assert guess_category(name) == category


async def test_brand_names_go_to_the_drugstore(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, catalog_user: None
) -> None:
    """'Persil' and 'Tempo' go to the user's Rossmann like 'Waschmittel' (main store +
    exceptions) (completeness-r2-9)."""
    from .test_catalog_1_4 import _user

    manager, branches = await _user(
        hass, config_entry, freezer, marktguru=False, store_split_mode="main_exceptions"
    )
    for name in ("Persil", "Tempo", "Waschmittel", "Butter"):
        manager.shopping_add(name)
    items = {i["name"]: i for i in manager.shopping}
    rossmann = branches["rossmann"]["id"]
    assert [n for n, i in items.items() if i.get("branch_id") == rossmann] == [
        "Persil",
        "Tempo",
        "Waschmittel",
    ]


# ----------------------------------------------------------------------
# completeness-r2-10: a voice tool for the regular price of a store
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sentence", "slots"),
    [
        ("butter kostet bei netto 1,79 euro", {"product": "butter", "store": "netto"}),
        ("merk dir milch kostet bei lidl 99 cent", {"product": "milch", "store": "lidl"}),
    ],
)
def test_set_price_sentences(sentence: str, slots: dict[str, str]) -> None:
    """The sentences of essensplaner_set_price (completeness-r2-10)."""
    from pathlib import Path

    from hassil import Intents, recognize_best
    import yaml

    path = Path(__file__).parent.parent / "custom_sentences" / "de" / "essensplaner.yaml"
    intents = Intents.from_dict(yaml.safe_load(path.read_text(encoding="utf-8")))
    result = recognize_best(sentence, intents)
    assert result is not None and result.intent.name == "essensplaner_set_price"
    found = {name: str(entity.value).strip() for name, entity in result.entities.items()}
    assert {k: found[k] for k in slots} == slots
    assert found["price"]
    # "was kostet …" questions are no prices
    other = recognize_best("was kostet der essensplan diese woche", intents)
    assert other is not None and other.intent.name == "essensplaner_get_costs"


async def test_set_price_intent_is_a_regular_price(
    hass: HomeAssistant, receipts_manager: Any
) -> None:
    """'Butter kostet bei Netto 1,79 Euro' stores Netto's own regular price (with the usual
    pack), no offer that ends on Saturday (completeness-r2-10)."""
    from homeassistant.helpers import llm

    manager = receipts_manager
    speech = await _speech(
        hass, "essensplaner_set_price", product="Butter", store="Netto", price="1,79 Euro"
    )
    assert speech == (
        "Okay, Butter kostet bei Netto 1,79 € (250 g). Das ist jetzt der Normalpreis dort."
    )
    butter = manager.store_prices_user[NETTO]["butter"]
    assert (butter["price"], butter["amount"], butter["unit"], butter["source"]) == (
        1.79,
        250,
        "g",
        "user",
    )
    assert not [o for o in manager.offers if o.get("source") == "manual"]
    speech = await _speech(
        hass, "essensplaner_set_price", product="Milch", store="Lidl", price="99 Cent", pack="1 l"
    )
    assert speech.startswith("Okay, Milch kostet bei Lidl 0,99 € (1 l).")
    assert manager.store_prices_user["lidl"]["milch"]["price"] == 0.99
    await _speech(hass, "essensplaner_set_price", product="Eier", store="REWE", price="2 Euro 49")
    assert manager.store_prices_user["rewe"]["ei"]["price"] == 2.49
    # an unknown store is an error, no general price
    response_speech = await _speech(
        hass, "essensplaner_set_price", product="Käse", store="Mondmarkt", price="3"
    )
    assert "Mondmarkt" in response_speech
    assert "kaese" not in manager.prices_user
    # an LLM tool with a description that tells it from add_offer
    api = await llm.async_get_api(
        hass,
        llm.LLM_API_ASSIST,
        llm.LLMContext(
            platform="test", context=None, language="de", assistant="conversation", device_id=None
        ),
    )
    tools = {tool.name: tool for tool in api.tools}
    assert "Normalpreis" in tools["essensplaner_set_price"].description
    assert "essensplaner_set_price" in tools["essensplaner_add_offer"].description
