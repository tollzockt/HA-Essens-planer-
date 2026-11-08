"""1.4.0 review round 1: backend fixes (matching, receipts, refresh, voice).

Each test names the review finding it guards against."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.essensplaner.catalog import KeyMatcher
from custom_components.essensplaner.offers import names_key_product, offer_matches, product_head

# ----------------------------------------------------------------------
# backend-logic-r1-1: short words of multi-word keys
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "key", "expected"),
    [
        ("Priva Schwämme Geschirrreiniger oder Topfreiniger", "wc reiniger", False),
        ("Sidolin Glasreiniger", "wc reiniger", False),
        ("Frosch Backofenreiniger", "wc reiniger", False),
        ("Frische Barbarie-Ente", "wc ente", False),
        ("Junge Ente küchenfertig", "wc ente", False),
        ("Domestos WC-Reiniger", "wc reiniger", True),
        ("WC Ente Gel", "wc ente", True),
        ("TK-Erbsen 750 g", "tk erbse", True),
        ("Tiefkühl-Erbsen", "tk erbse", True),
        ("Erbsen frisch", "tk erbse", False),
        ("H-Milch 1,5 %", "h milch", True),
        ("haltbare Milch", "h milch", True),
        ("Frische Vollmilch", "h milch", False),
    ],
)
def test_short_words_of_keys_are_whole_words(text: str, key: str, expected: bool) -> None:
    """'WC-Reiniger' is no '…reiniger', 'WC-Ente' no duck (backend-logic-r1-1)."""
    assert offer_matches(text, key) is expected


def test_key_matcher_keeps_short_words() -> None:
    """The catalog matcher: a duck or a dish sponge gets no WC key (backend-logic-r1-1)."""
    matcher = KeyMatcher(["wc reiniger", "wc ente", "ente", "tk erbse", "erbse"])
    assert matcher.match("Frische Barbarie-Ente", "Frische Barbarie-Ente") == ["ente"]
    assert matcher.match("Schwämme Geschirrreiniger", "Schwämme Geschirrreiniger") == []
    assert matcher.match("Domestos WC-Reiniger", "Domestos WC-Reiniger") == ["wc reiniger"]
    assert set(matcher.match("TK-Erbsen", "TK-Erbsen")) == {"tk erbse", "erbse"}
    assert matcher.match("Erbsen", "Erbsen") == ["erbse"]
    assert not names_key_product("Geschirrreiniger", "wc reiniger")


# ----------------------------------------------------------------------
# backend-logic-r1-2: the product head decides, flavours are no product
# ----------------------------------------------------------------------

_KEYS = [
    "apfel",
    "sahne",
    "olivenoel",
    "knoblauch",
    "honig",
    "gouda",
    "lachsfilet",
    "blaetterteig",
    "essig",
    "kaper",
    "erdbeere",
    "himbeere",
    "zitrone",
    "paprika",
    "ingwer",
    "milch",
    "salz",
    "butter",
    "joghurt",
    "naturjoghurt",
    "backpulver",
    "schokolade",
]


@pytest.mark.parametrize(
    ("product", "description", "expected"),
    [
        # ALDI SÜD: "Name, Variante" (live weekly offers of 08.11.2026)
        ("Apfelmus 360 g, Apfel", "", set()),
        ("Meerrettich, Sahne 185 g", "", set()),
        ("Bio-Gourmet Kapern 180 g, Olivenöl", "", {"kaper"}),
        ("Bio-Gourmet Kapern 180 g, Mit Knoblauch", "", {"kaper"}),
        ("Filoncino 400 g, Walnuss-Honig", "", set()),
        ("Schmelzkäsezubereitung 200 g, Gouda", "", set()),
        ("Wildlachsfilet in Blätterteig 300 g, Spinat", "", set()),
        ("Bio-Honig 500 g, Flüssig", "", {"honig"}),
        ("Almighurt 150 g, Erdbeere", "", set()),
        ("Backzutaten, Backpulver 160 g", "", {"backpulver"}),
        # marktguru / REWE / Netto: the flavour follows the product
        ("Almighurt Erdbeere", "", set()),
        ("Arla Skyr Drink Erdbeere Himbeere", "je 330-ml-Fl.", set()),
        ("Syburg Limonaden", "Zitrone oder Orange 12 x 0,7 L", set()),
        ("Petz Gefüllte Paprika", "mit Schweine-Hackfleisch", set()),
        ("Alioli Knoblauch Dip", "je 200-g-Glas", set()),
        ("Ingwer Shots", "Honig-Zitrone, je 360-ml-Fl.", set()),
        ("Mikado Milch Schokolade", "", {"schokolade"}),
        ("Kondensmilch XXL", "500 g 4% Fett", set()),
        ("Granatapfel", "2 Stück", set()),
        ("Granatäpfel", "", set()),
        ("Auftausalz", "im Eimer 10 kg", set()),
        # still the product itself
        ("Kerrygold Butter", "", {"butter"}),
        ("Frische Erdbeeren", "500 g Schale", {"erdbeere"}),
        ("Bio Zitronen", "", {"zitrone"}),
        ("Bio Weidemilch", "3,8% Fett", {"milch"}),
        ("Naturjoghurt 3,5 %", "", {"naturjoghurt", "joghurt"}),
        ("Joghurt Erdbeere", "", {"joghurt"}),
        ("Rote Paprika", "500 g", {"paprika"}),
    ],
)
def test_catalog_keys_of_the_product_head(product: str, description: str, expected: set) -> None:
    """Flavour and variant words give no key (backend-logic-r1-2)."""
    matcher = KeyMatcher(_KEYS)
    offer = {"product": product, "description": description}
    assert set(matcher.offer_keys(offer)) == expected


def test_product_head() -> None:
    """ALDI's variant after the comma, what the product comes in, ready meals."""
    assert product_head("Apfelmus 360 g, Apfel") == "Apfelmus 360 g"
    assert product_head("Eier aus Freilandhaltung, 10er-Packung") == "Eier"
    assert product_head("Frische Vollmilch 3,5 % 1 l") == "Frische Vollmilch 3,5 % 1 l"
    assert product_head("Thunfisch in Sonnenblumenöl") == "Thunfisch"
    assert product_head("Wildlachsfilet in Blätterteig 300 g") == ""
    assert product_head("Backzutaten, Mehl & Zucker") == "Mehl & Zucker"


def _leaflet_offer(product: str, price: float, old: float, amount: float) -> dict[str, Any]:
    return {
        "id": f"aldi_{product}",
        "product": product,
        "title": product,
        "retailer": "aldi-sued",
        "price": price,
        "old_price": old,
        "pack_amount": amount,
        "pack_unit": "g",
        "valid_from": "2026-11-02",
        "valid_to": "2026-11-07",
        "source": "aldi_weekly",
    }


async def test_learning_needs_the_product_itself(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """A wrongly keyed offer teaches no regular price, even with an estimate whose price
    range it fits (backend-logic-r1-2)."""
    manager = setup_integration.runtime_data
    offers = [
        {
            **_leaflet_offer("Bio-Gourmet Kapern 180 g, Olivenöl", 2.19, 3.49, 180),
            "keys": ["olivenoel"],
        },
        {**_leaflet_offer("Filoncino 400 g, Walnuss-Honig", 1.49, 1.89, 400), "keys": ["honig"]},
        {**_leaflet_offer("Meerrettich, Sahne 185 g", 0.89, 1.29, 185), "keys": ["sahne"]},
        {**_leaflet_offer("Almighurt Erdbeere", 0.59, 0.89, 150), "keys": ["erdbeere"]},
        {**_leaflet_offer("Schweine-Bratwurst 400 g", 2.29, 2.79, 400), "keys": ["bratwurst"]},
    ]
    assert manager.learn_from_offers(offers) == 1
    learned = manager.store_prices_learned.get("aldi-sued", {})
    assert set(learned) == {"bratwurst"}


# ----------------------------------------------------------------------
# backend-logic-r1-8: food at a drugstore is food
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("product", "description", "kind"),
    [
        ("Krüger Cappuccino", "500 g", "food"),
        ("enerBiO Haferdrink Natur", "Naturland 1 Liter", "drinks"),
        ("Snickers Riegel", "oder Twix Riegel je 5er-Pack/250 g", "food"),
        ("Proteinriegel", "40 - 50 g", "food"),
        ("Milka Choco Mini Stars", "185 g", "food"),
        ("Milka Favourites", "141 g oder Ritter Sport Schokowürfel 155 g", "food"),
        ("Protein Waffeln", "90 - 100 g", "food"),
        ("Bio Dinkel Eierwaffeln", "165 g", "food"),
        ("Bio Flohsamen Schalen", "200 g", "food"),
        # still drugstore products
        ("Ligretto", "", "drugstore"),
        ("Hydro Boost Aqua Creme", "oder Nachtcreme je 50 ml", "drugstore"),
        ("WC-Gel Duftstempel Starter-Set", "75 ml", "drugstore"),
        ("Duschgel", "", "drugstore"),
    ],
)
def test_drugstore_food_is_food(product: str, description: str, kind: str) -> None:
    """Rossmann's coffee, bars and snacks show under "Lebensmittel" (backend-logic-r1-8)."""
    from custom_components.essensplaner.catalog import classify_offer, kind_matches

    value = classify_offer(product, description, "rossmann", None)
    assert value == kind
    if kind in ("food", "drinks"):
        assert kind_matches({"kind": value, "retailer": "rossmann"}, "food")


# ----------------------------------------------------------------------
# receipts: phone OCR layouts, abbreviations, offer prices, restoring prices, files
# ----------------------------------------------------------------------

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
OCR_HEAD = "REWE\nBahnhofstraße 30\n57610 Altenkirchen\n"


@pytest.mark.parametrize(
    ("text", "confidence"),
    [
        # alternating: name line, price line
        (
            OCR_HEAD + "H-MILCH 1,5%\n1,09 B\nBUTTER\n2,39 B\nGOUDA JUNG SCHEIB\n1,99 B\n"
            "SUMME EUR\n5,47\n07.11.2026",
            0.8,
        ),
        # two columns: all names, then all prices (a column head between them)
        (
            OCR_HEAD + "H-MILCH 1,5%\nBUTTER\nGOUDA JUNG SCHEIB\nEUR\n1,09 B\n2,39 B\n1,99 B\n"
            "SUMME EUR 5,47\n07.11.2026",
            0.6,
        ),
        # two columns with the total label in the name column
        (
            OCR_HEAD + "H-MILCH 1,5%\nBUTTER\nGOUDA JUNG SCHEIB\nSUMME EUR\n1,09 B\n2,39 B\n"
            "1,99 B\n5,47\n07.11.2026",
            0.6,
        ),
    ],
)
def test_receipt_text_of_a_phone_photo(text: str, confidence: float) -> None:
    """Rows a phone's text recognition split into names and prices are articles
    (backend-logic-r1-3)."""
    from datetime import date

    from custom_components.essensplaner.receipts import parse_receipt_text

    parsed = parse_receipt_text(text, date(2026, 11, 8))
    items = [(i["name"], i["price"]) for i in parsed["items"]]
    assert items == [("H-MILCH 1,5%", 1.09), ("BUTTER", 2.39), ("GOUDA JUNG SCHEIB", 1.99)]
    assert all(i["confidence"] == confidence for i in parsed["items"])
    assert parsed["items"][0]["line"] == "H-MILCH 1,5%\n1,09 B"
    assert (parsed["total"], parsed["checked"], parsed["retailer"]) == (5.47, True, "rewe")


def test_receipt_split_discount_and_unpaired_columns() -> None:
    """A split discount line still reduces its article; names and prices that do not pair
    up stay as they were."""
    from datetime import date

    from custom_components.essensplaner.receipts import parse_receipt_text

    parsed = parse_receipt_text(
        "NETTO\nKornbitze 7\n57632 Flammersfeld\nBUTTER\n2,39 A\nRabatt\n-0,30 A\nSUMME\n2,09",
        date(2026, 11, 8),
    )
    assert [(i["name"], i["price"], i["discount"]) for i in parsed["items"]] == [
        ("BUTTER", 2.09, 0.3)
    ]
    parsed = parse_receipt_text(
        OCR_HEAD + "H-MILCH 1,5%\nBUTTER\n1,09 B\n2,39 B\n1,99 B\nSUMME EUR 5,47",
        date(2026, 11, 8),
    )
    assert [i["name"] for i in parsed["items"]] == ["BUTTER"]  # 2 names, 3 prices


@pytest.fixture
async def receipts_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, tmp_path
) -> MockConfigEntry:
    """The integration with its own config and media folders and the user's stores."""
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
    return config_entry


async def _service(hass: HomeAssistant, service: str, **data: Any) -> dict[str, Any]:
    from custom_components.essensplaner.const import DOMAIN

    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


async def test_receipt_abbreviations_do_not_guess(
    hass: HomeAssistant, receipts_entry: MockConfigEntry
) -> None:
    """'BOD.' is Bodenhaltung, not Bodylotion; 'PASS.TOMATEN' passata, not fresh tomatoes;
    an abbreviation not understood before the product makes only a suggestion
    (backend-logic-r1-4)."""
    from custom_components.essensplaner.receipts import ReceiptMapper

    mapper = ReceiptMapper(receipts_entry.runtime_data, "rewe")
    assert mapper.map("EIER BOD.10ER M")["key"] == "ei"
    assert mapper.map("BOD.EIER 10ER")["key"] == "ei"
    assert mapper.map("FREIL.EIER 10ER")["key"] == "ei"
    assert mapper.map("JA! PASS.TOMATEN 500G")["key"] == "passierte tomate"
    assert mapper.map("GEH.TOMATEN 400G")["key"] == "gehackte tomate"
    unsure = mapper.map("XYZQ.TOMATEN 400G")
    assert unsure["key"] == "tomate" and unsure["confidence"] < 0.5
    proposal = await _service(
        hass, "receipt_parse_text", text=OCR_HEAD + "XYZQ.TOMATEN 400G 0,89 B\nSUMME 0,89"
    )
    item = proposal["items"][0]
    assert (item["status"], item["key"], item["suggestion"]) == ("unknown", None, "Tomaten")
    # a unique completion of 5+ letters is no guess; it beats a suggestion of the printed
    # words ("SONNENBL.OEL" is no Rapsöl) (fix-regressions-r2-2)
    lines = {
        "WEIZENM. 405 1KG": "weizenmehl",
        "SONNENBL.OEL 1L": "sonnenblumenoel",
        "MARGAR. 500G": "margarine",
        "CHAMPIGN. 400G": "champignon",
        "ZUCCH.": "zucchini",
    }
    for line, key in lines.items():
        found = mapper.map(line)
        assert (found["key"], found["confidence"] >= 0.5) == (key, True), line
    prices = "".join(f"{line} 0,99 B\n" for line in lines)
    proposal = await _service(
        hass, "receipt_parse_text", text=f"{OCR_HEAD}{prices}SUMME 4,95\n04.11.2026"
    )
    assert [(i["status"], i["key"]) for i in proposal["items"]] == [
        ("mapped", key) for key in lines.values()
    ]
    assert mapper.map("BOD.EIER 10ER")["key"] == "ei"


async def test_receipt_offer_price_is_no_regular_price(
    hass: HomeAssistant, receipts_entry: MockConfigEntry, freezer
) -> None:
    """A line at the price of the store's leaflet offer on the receipt's day only goes into
    the price history; the typed regular price stays (backend-logic-r1-5)."""
    from datetime import date, datetime

    manager = receipts_entry.runtime_data
    manager.set_store_price("Netto", "Butter", 2.39, 250, "g")
    manager.add_offer(
        "Kerrygold Butter", "Netto", 1.79, "250 g", date(2026, 11, 2), date(2026, 11, 7), 2.39
    )
    text = "NETTO\nKornbitze 7\n57632 Flammersfeld\nKerrygold Irische Butter 1,79 A\nSUMME 1,79\n03.11.2026"
    proposal = await _service(hass, "receipt_parse_text", text=text)
    item = proposal["items"][0]
    assert item["key"] == "butter" and item["offer"]["price"] == 1.79
    assert item["warning"].startswith("Angebotspreis")
    result = await _service(hass, "receipt_save", receipt=proposal)
    assert (result["saved"], result["offer"]) == (0, 1)
    butter = manager.store_prices_user["netto-marken-discount"]["butter"]
    assert (butter["price"], butter["source"]) == (2.39, "user")
    assert [h["price"] for h in butter["history"] if h.get("offer")] == [1.79]
    freezer.move_to(datetime.fromisoformat("2026-11-18T10:00:00+01:00"))
    assert manager.store_book("netto-marken-discount").lookup("Butter").price == 2.39
    # without an offer on that day the receipt's price is the regular price
    text = text.replace("03.11.2026", "17.11.2026").replace("1,79", "2,29")
    result = await _service(
        hass, "receipt_save", receipt=await _service(hass, "receipt_parse_text", text=text)
    )
    assert result["saved"] == 1
    assert manager.store_prices_user["netto-marken-discount"]["butter"]["price"] == 2.29


async def test_deleting_a_receipt_restores_the_price_before(
    hass: HomeAssistant, receipts_entry: MockConfigEntry, freezer
) -> None:
    """'Mit Preisen löschen' brings back the typed price or the older receipt's price it
    replaced (backend-logic-r1-6)."""
    from datetime import datetime

    manager = receipts_entry.runtime_data
    netto = "netto-marken-discount"
    freezer.move_to(datetime.fromisoformat("2026-10-20T10:00:00+02:00"))
    manager.set_store_price("Netto", "Butter", 2.39, 250, "g")
    freezer.move_to(datetime.fromisoformat("2026-11-04T10:00:00+01:00"))
    base = {"store": "Netto", "items": [{"name": "Butter", "key": "butter", "price": 1.99}]}
    first = await _service(hass, "receipt_save", receipt={**base, "date": "2026-11-01"})
    assert manager.store_prices_user[netto]["butter"]["price"] == 1.99
    second = await _service(
        hass,
        "receipt_save",
        receipt={**base, "date": "2026-11-03", "items": [{**base["items"][0], "price": 2.49}]},
    )
    assert manager.store_prices_user[netto]["butter"]["price"] == 2.49
    await _service(hass, "delete_receipt", id=second["receipt"]["id"], remove_prices=True)
    butter = manager.store_prices_user[netto]["butter"]
    assert (butter["price"], butter["source"], butter["receipt_id"]) == (
        1.99,
        "receipt",
        first["receipt"]["id"],
    )
    await _service(hass, "delete_receipt", id=first["receipt"]["id"], remove_prices=True)
    butter = manager.store_prices_user[netto]["butter"]
    assert (butter["price"], butter["amount"], butter["unit"], butter["source"]) == (
        2.39,
        250,
        "g",
        "user",
    )
    assert all(not h.get("receipt") for h in butter.get("history") or [])
    # a receipt price without anything before it goes
    third = await _service(
        hass,
        "receipt_save",
        receipt={"store": "Lidl", "items": [{"name": "Butter", "key": "butter", "price": 1.69}]},
    )
    assert manager.store_prices_user["lidl"]["butter"]["price"] == 1.69
    await _service(hass, "delete_receipt", id=third["receipt"]["id"], remove_prices=True)
    assert "lidl" not in manager.store_prices_user


async def test_receipt_files_are_private_and_tidy(
    hass: HomeAssistant,
    receipts_entry: MockConfigEntry,
    tmp_path,
    freezer,
    hass_ws_client,
    hass_read_only_access_token,
) -> None:
    """Receipt photos are not in a media folder (any user may browse those); the AI Task
    still gets them through the integration's media source, which lists nothing; a new
    photo of a saved receipt replaces the old file; leftovers go on load; the receipt
    services are for admins (security-privacy-r1-3/-4, ha-integration-r1-2/-3)."""
    from datetime import timedelta
    import os
    import time

    from homeassistant.components import media_source
    from homeassistant.setup import async_setup_component

    manager = receipts_entry.runtime_data
    store = manager.receipts
    folder = tmp_path / "config" / ".storage" / "essensplaner_receipts"
    first = await store.async_add_upload(JPEG, "image/jpeg")
    assert (folder / first["file"]).read_bytes() == JPEG
    assert not (tmp_path / "media").exists()
    saved = await _service(
        hass,
        "receipt_save",
        receipt={
            "store": "Lidl",
            "upload_id": first["id"],
            "items": [{"name": "Butter", "price": 1.69}],
        },
    )
    receipt_id = saved["receipt"]["id"]
    # the media source: resolvable for the AI Task, nothing to browse
    assert await async_setup_component(hass, "media_source", {})
    await hass.async_block_till_done()
    media_id = store.media_content_id(first)
    assert media_id == f"media-source://essensplaner/receipt/{first['file']}"
    resolved = await media_source.async_resolve_media(hass, media_id, None)
    assert resolved.path == folder / first["file"] and resolved.mime_type == "image/jpeg"
    assert resolved.url == f"/api/essensplaner/receipt_image/{receipt_id}"
    browsed = await media_source.async_browse_media(hass, "media-source://essensplaner")
    assert browsed.children == []
    with pytest.raises(media_source.Unresolvable):
        await media_source.async_resolve_media(
            hass, "media-source://essensplaner/receipt/0123456789abcdef.jpg", None
        )
    # a non-admin reaches nothing: neither websockets nor services
    reader = await hass_ws_client(hass, hass_read_only_access_token)
    for msg_id, (service, data) in enumerate(
        (("get_receipts", {}), ("delete_receipt", {"id": receipt_id, "remove_prices": True})),
        start=1,
    ):
        await reader.send_json(
            {
                "id": msg_id,
                "type": "call_service",
                "domain": "essensplaner",
                "service": service,
                "service_data": data,
                "return_response": True,
            }
        )
        msg = await reader.receive_json()
        assert not msg["success"] and "Unauthorized" in msg["error"]["message"], service
    assert len(store.receipts) == 1
    # a new photo of the saved receipt: the old file goes
    second = await store.async_add_upload(PNG, "image/png")
    await _service(
        hass,
        "receipt_save",
        receipt={
            "id": receipt_id,
            "store": "Lidl",
            "upload_id": second["id"],
            "items": [{"name": "Butter", "price": 1.69}],
        },
    )
    await hass.async_block_till_done()
    assert not (folder / first["file"]).exists()
    assert (folder / second["file"]).exists()
    # a failed write leaves nothing behind
    with patch("pathlib.Path.replace", side_effect=OSError("disk full")), pytest.raises(OSError):
        await store.async_add_upload(JPEG, "image/jpeg")
    assert sorted(p.name for p in folder.iterdir()) == [second["file"]]
    # leftovers nothing refers to (an upload of an unloaded store) go on load
    orphan = folder / "0123456789abcdef.jpg"
    orphan.write_bytes(JPEG)
    old = time.time() - 2 * 3600
    os.utime(orphan, (old, old))
    keep = folder / "notiz.txt"
    keep.write_text("bleibt")
    await store.async_save()
    freezer.tick(timedelta(minutes=1))
    await hass.config_entries.async_reload(receipts_entry.entry_id)
    await hass.async_block_till_done()
    assert not orphan.exists() and keep.exists()
    assert (folder / second["file"]).exists()


# ----------------------------------------------------------------------
# refresh: no endless loop, linked stores fetched soon, sources switched off, pause
# ----------------------------------------------------------------------


async def _entry_with(hass: HomeAssistant, entry: MockConfigEntry, freezer, **options: Any):
    from datetime import datetime

    from homeassistant.setup import async_setup_component

    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(datetime.fromisoformat("2026-11-04T10:00:00+01:00"))
    assert await async_setup_component(hass, "homeassistant", {})
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _minutes(hass: HomeAssistant, freezer, count: int) -> None:
    from datetime import timedelta

    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    for _ in range(count):
        freezer.tick(timedelta(seconds=61))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()


@pytest.fixture
def no_source_delays(monkeypatch: pytest.MonkeyPatch) -> None:
    from custom_components.essensplaner import aldi, articles, edeka

    monkeypatch.setattr(aldi, "REQUEST_DELAY", 0)
    monkeypatch.setattr(edeka, "REQUEST_DELAY", 0)
    monkeypatch.setattr(articles, "LIVE_MIN_INTERVAL", 0)


async def test_failing_aldi_is_not_asked_every_minute(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock, no_source_delays
) -> None:
    """ALDI SÜD on, marktguru off, ALDI answering HTTP 500: the branch change and the start
    check ask, then nothing until the daily check – no refresh every 60 s
    (migration-compat-r1-1, security-privacy-r1-1)."""
    from custom_components.essensplaner.aldi import SEARCH_URL, SERVICE_POINTS_URL
    from custom_components.essensplaner.const import CONF_ALDI_ONLINE

    aioclient_mock.get(SERVICE_POINTS_URL, status=500)
    aioclient_mock.get(SEARCH_URL, status=500)
    entry = await _entry_with(hass, config_entry, freezer, **{CONF_ALDI_ONLINE: True})
    manager = entry.runtime_data
    manager.save_branch(
        {
            "store": "Aldi Süd",
            "postcode": "53567",
            "street": "Zum Jägertal 1",
            "aldi_service_point": "B402",
        }
    )
    await _minutes(hass, freezer, 5)
    asked = aioclient_mock.call_count
    assert 0 < asked <= 8
    await _minutes(hass, freezer, 15)
    assert aioclient_mock.call_count == asked
    assert manager._offer_refresh_timer is None
    assert not manager._new_offer_targets()


async def test_linking_an_edeka_market_fetches_soon(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock, no_source_delays
) -> None:
    """EDEKA offers on (marktguru off): linking the market after the start checks fetches
    its offers a minute later, not the next morning (ha-integration-r1-4)."""
    import json
    from pathlib import Path

    from custom_components.essensplaner.const import CONF_EDEKA_OFFERS
    from custom_components.essensplaner.edeka import OFFERS_URL

    fixture = Path(__file__).parent / "fixtures" / "edeka_offers.json"
    aioclient_mock.get(OFFERS_URL, json=json.loads(fixture.read_text()))
    entry = await _entry_with(hass, config_entry, freezer, **{CONF_EDEKA_OFFERS: True})
    manager = entry.runtime_data
    branch = manager.save_branch(
        {"store": "EDEKA", "name": "EDEKA Hoffmann", "street": "Landblum 1", "postcode": "56593"}
    )
    await _minutes(hass, freezer, 4)  # start checks: nothing linked yet
    assert aioclient_mock.call_count == 0
    manager.save_branch({"id": branch["id"], "edeka_market_id": "2644015"})
    await _minutes(hass, freezer, 2)
    assert aioclient_mock.call_count == 1
    await _minutes(hass, freezer, 10)
    assert aioclient_mock.call_count == 1


async def test_switching_marktguru_off_drops_its_offers(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer
) -> None:
    """After marktguru is switched off its offers are no longer listed, planned or shown as
    images (backend-logic-r1-9, security-privacy-r1-5)."""
    from custom_components.essensplaner.catalog import store_offers_view
    from custom_components.essensplaner.const import CONF_OFFERS_SOURCE

    entry = await _entry_with(hass, config_entry, freezer, **{CONF_OFFERS_SOURCE: "marktguru"})
    manager = entry.runtime_data
    manager.save_branch({"store": "REWE", "postcode": "57610", "street": "Bahnhofstraße 30"})
    offer = {
        "id": "mg_1",
        "product": "Knoblauch",
        "title": "Knoblauch",
        "retailer": "rewe",
        "price": 0.49,
        "valid_from": "2026-11-02",
        "valid_to": "2026-11-07",
        "keys": ["knoblauch"],
        "image": "https://cdn.marktguru.de/api/v1/offers/1/images/default/0/small.webp",
        "source": "marktguru",
        "zip_codes": ["57610"],
    }
    manager.catalog.set_bucket("marktguru", "rewe", "57610", [dict(offer)], "ok")
    manager.offers.append(dict(offer))
    await manager.catalog.async_save()
    await manager.async_save_now()
    assert store_offers_view(manager)["total"] == 1
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_OFFERS_SOURCE: "off"}
    )
    await hass.async_block_till_done()
    manager = entry.runtime_data
    assert store_offers_view(manager)["total"] == 0
    assert not [o for o in manager.offers if o.get("source") == "marktguru"]
    assert not manager.catalog.best_offers(manager.today())


async def test_marktguru_pause_holds_for_live_searches(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock, no_source_delays
) -> None:
    """While marktguru is paused (it refused) neither search_offers nor the article search
    asks it; a refusal of a live search starts the pause (security-privacy-r1-2)."""
    from custom_components.essensplaner.const import CONF_OFFERS_SOURCE
    from custom_components.essensplaner.offers import MARKTGURU_API, MARKTGURU_HOME

    from .test_economy import HOME_HTML

    aioclient_mock.get(MARKTGURU_HOME, text=HOME_HTML)
    aioclient_mock.get(f"{MARKTGURU_API}/offers/search", status=429)
    entry = await _entry_with(hass, config_entry, freezer, **{CONF_OFFERS_SOURCE: "marktguru"})
    manager = entry.runtime_data
    manager.save_branch({"store": "REWE", "postcode": "57610", "street": "Bahnhofstraße 30"})
    # a refusal of the article search: paused, no request for the next searches
    response = await manager.async_search_articles_live("Kaffee")
    assert "pausiert" in response["error"]
    assert manager.catalog.data["blocked_until"]
    asked = aioclient_mock.call_count
    response = await manager.async_search_articles_live("Käse")
    assert "pausiert" in response["error"]
    result = await _service(hass, "search_offers", query="Butter")
    assert "pausiert" in result["error"] and result["live"] == []
    assert aioclient_mock.call_count == asked


# ----------------------------------------------------------------------
# migration from 1.3: aisles of open items, new units in recipes, phantom chain column
# ----------------------------------------------------------------------


async def test_upgrade_from_1_3_items_recipes_and_learned_prices(
    hass: HomeAssistant, config_entry: MockConfigEntry, hass_storage, freezer
) -> None:
    """1.3 data: 'Toilettenpapier' (Sonstiges) and 'Zahnpasta' (pasta!) get their 1.4
    aisles and go to the drugstore; '1 Rolle Blätterteig' gets the unit Rolle; leaflet
    prices learned for the Rossmann saved as Marktkauf leave no Marktkauf column
    (migration-compat-r1-2/-3/-4)."""
    from datetime import datetime

    from homeassistant.setup import async_setup_component

    from custom_components.essensplaner.const import STORAGE_KEY

    from .test_drugstores_1_4 import _branch

    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(datetime.fromisoformat("2026-11-04T10:00:00+01:00"))
    rewe = _branch("man_1", "rewe", "REWE", "REWE Bahnhofstraße 30", "Bahnhofstraße 30", "57610", 0)
    rossmann = _branch(
        "man_2",
        "marktkauf",
        "ROSSMANN Drogeriemarkt",
        "Marktkauf Rheinstraße 55",
        "Rheinstraße 55",
        "56593",
        5,
    )

    def item(item_id: str, name: str, category: str) -> dict[str, Any]:
        return {
            "id": item_id,
            "name": name,
            "amount": None,
            "unit": "",
            "category": category,
            "checked": False,
            "source": "manual",
            "key": name.lower(),
        }

    hass_storage[f"{STORAGE_KEY}.{config_entry.entry_id}"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"{STORAGE_KEY}.{config_entry.entry_id}",
        "data": {
            "recipes": {
                "r1": {
                    "id": "r1",
                    "name": "Lachs im Blätterteig",
                    "servings": 2,
                    "ingredients": [
                        {
                            "name": "Rolle Blätterteig",
                            "amount": 1,
                            "unit": "",
                            "note": "",
                            "category": "Sonstiges",
                        },
                        {
                            "name": "Lachsfilet",
                            "amount": 300,
                            "unit": "g",
                            "note": "",
                            "category": "Fisch",
                        },
                    ],
                    "updated": "2026-10-01T10:00:00+00:00",
                }
            },
            "plan": {},
            "shopping": [
                item("s1", "Toilettenpapier", "Sonstiges"),
                item("s2", "Zahnpasta", "Nudeln, Reis & Getreide"),
                item("s3", "Butter", "Milchprodukte & Eier"),
            ],
            "starter_names": [],
            "data_version": 3,
            "branches": [rewe, rossmann],
            "main_branch": "man_1",
            "store_prices_learned": {
                "marktkauf": {
                    "duschgel": {
                        "name": "Duschgel",
                        "price": 1.29,
                        "amount": 250,
                        "unit": "ml",
                        "source": "leaflet",
                        "updated": "2026-11-01T10:00:00+00:00",
                        "seen": "2026-11-01",
                        "history": [],
                    }
                }
            },
        },
    }
    assert await async_setup_component(hass, "homeassistant", {})
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    manager = config_entry.runtime_data

    items = {i["name"]: i for i in manager.shopping}
    assert items["Toilettenpapier"]["category"] == "Haushalt & Reinigung"
    assert items["Zahnpasta"]["category"] == "Drogerie & Körperpflege"
    assert items["Butter"]["category"] == "Milchprodukte & Eier"
    assert items["Zahnpasta"]["branch_id"] == "man_2"
    assert items["Zahnpasta"]["store_reason"] == "drugstore"

    line = manager.recipes["r1"]["ingredients"][0]
    assert (line["name"], line["amount"], line["unit"]) == ("Blätterteig", 1, "Rolle")
    assert manager.recipes["r1"]["ingredients"][1]["name"] == "Lachsfilet"

    assert "marktkauf" not in manager.store_prices_learned
    columns = [c["retailer"] if isinstance(c, dict) else c for c in manager._matrix_columns()]
    assert "marktkauf" not in columns and "rossmann" in columns


# ----------------------------------------------------------------------
# voice: offers of the whole catalog, the drugstore, the hint
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


async def test_voice_offers_of_the_whole_catalog(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock
) -> None:
    """Store and product questions are answered from every offer of the saved stores, also
    drugstore offers and products nobody planned (voice-docs-r1-1, voice-docs-r1-2)."""
    from .test_catalog_1_4 import _mock_marktguru, _refresh, _user

    _mock_marktguru(aioclient_mock)
    manager, _branches = await _user(hass, config_entry, freezer)
    await _refresh(hass)
    # Rossmann's new week starts on Monday: said so, with its (drugstore) offers
    speech = await _speech(hass, "essensplaner_get_offers", store="Rossmann")
    assert speech.startswith("Gerade nicht, aber am Montag gibt es 10 Angebote")
    assert "Domol Spülmittel bei ROSSMANN für 0,99 €" in speech
    assert ".." not in speech
    speech = await _speech(hass, "essensplaner_get_offers", store="Rossmann", when="nächste Woche")
    assert speech.startswith("Ich habe 10 Angebote gefunden")
    # "die Drogerie" is the saved drugstore
    speech = await _speech(hass, "essensplaner_get_offers", store="Drogerie")
    assert "bei ROSSMANN" in speech and "10 Angebote" in speech
    # a product nobody planned
    assert not [o for o in manager.offers if "Duschgel" in str(o.get("title"))]
    speech = await _speech(hass, "essensplaner_get_offers", query="Duschgel")
    assert speech == (
        "Ich habe ein Angebot gefunden: Fa Duschgel bei REWE Petz für 1,19 € bis Samstag."
    )
    # all of a chain's offers, not only those of planned products
    planned = len(manager.offers_view("current", None, "Lidl", 50))
    speech = await _speech(hass, "essensplaner_get_offers", store="Lidl")
    assert planned < 10 and speech.startswith("Ich habe 10 Angebote gefunden")
    # without store and product: the offers matching the recipes (as before)
    speech = await _speech(hass, "essensplaner_get_offers")
    assert speech.startswith(f"Ich habe {len(manager.offers_view('current', None, None, 50))} ")


async def test_voice_drugstore_shopping_list(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """'Was kaufe ich in der Drogerie?' reads the items of the saved drugstore, also one
    named just "Rossmann" (voice-docs-r1-2)."""
    manager = setup_integration.runtime_data
    manager.save_branch({"store": "REWE", "postcode": "57610", "street": "Bahnhofstraße 30"})
    manager.set_main_branch(manager.branches[0]["id"])
    rossmann = manager.save_branch({"store": "Rossmann", "postcode": "56593", "name": "Rossmann"})
    manager.shopping_add("Zahnpasta")
    manager.shopping_add("Duschgel")
    manager.shopping_add("Butter")
    speech = await _speech(hass, "essensplaner_get_shopping_list", store="Drogerie")
    assert "nicht gefunden" not in speech
    assert speech.startswith(f"Bei {manager.branch_label(rossmann)} kaufst du 2 Artikel")
    assert [b["id"] for b in manager._match_branches("in der Drogerie")] == [rossmann["id"]]


async def test_voice_offer_hint_names_the_reason(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer
) -> None:
    """No offer: the hint says what is missing – no source on, the EDEKA market not linked,
    nothing fetched yet – and where to change it (voice-docs-r1-3)."""
    from custom_components.essensplaner.const import CONF_ALDI_ONLINE, CONF_EDEKA_OFFERS

    entry = await _entry_with(hass, config_entry, freezer)
    speech = await _speech(hass, "essensplaner_get_offers")
    assert speech == (
        "Ich habe keine passenden Angebote gefunden. Online-Angebote sind nicht eingeschaltet "
        "(im Essensplaner-Panel unter Einstellungen, Angebote und Preisquellen)."
    )
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_EDEKA_OFFERS: True, CONF_ALDI_ONLINE: True}
    )
    await hass.async_block_till_done()
    entry.runtime_data.save_branch({"store": "EDEKA", "postcode": "56593"})
    speech = await _speech(hass, "essensplaner_get_offers")
    assert "nicht eingeschaltet" not in speech
    assert "Markt-ID" in speech and "noch nicht abgerufen" in speech
