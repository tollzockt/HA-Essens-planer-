"""1.4: receipts (Kassenzettel) – local text parser of German receipts, AI Task photos,
mapping receipt abbreviations to articles, saving the store's own prices, the price list
source, the upload / image views, storage limits and cleanup.

All receipt texts are written for these tests (anonymized; addresses are the test user's
branches or invented)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import json
from pathlib import Path
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.essensplaner import receipts as receipts_module
from custom_components.essensplaner.const import DOMAIN
from custom_components.essensplaner.receipts import (
    AI_INSTRUCTIONS,
    ReceiptMapper,
    ReceiptStore,
    extract_json,
    line_pack,
    name_tokens,
    own_price,
    parse_ai_receipt,
    parse_receipt_date,
    parse_receipt_text,
)

TODAY = date(2026, 11, 4)  # the frozen test day (setup_integration)
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

# ----------------------------------------------------------------------
# receipt texts (one per chain)
# ----------------------------------------------------------------------

REWE = """REWE
REWE Markt GmbH
Bahnhofstr. 3
57601 Bergdorf
Tel.: 02681-98765
UID Nr.: DE123456789
                                  EUR
H-MILCH 1,5%                     1,09 B
GOUDA JUNG SCHEIB                1,99 B
BIO EIER 10ER                    3,29 B
HACKFL.GEM.                      5,98 B
          2 Stk x    2,99
BANANE                           1,10 B
          0,856 kg x    1,29 EUR/kg
PFAND 0,25 EURO                  0,25 A *
FRITZ KOLA 1,0L                   1,49 A
--------------------------------------
SUMME                    EUR     15,19
======================================
Geg. Mastercard          EUR     15,19

Steuer   %     Netto    Steuer    Brutto
A=     19,0%    1,46      0,28      1,74
B=      7,0%   12,57      0,88     13,45
Gesamtbetrag  14,03  1,16  15,19

03.11.2026        10:15     Bon-Nr.:1234
Markt:1234        Kasse:2     Bed.:123456
"""

LIDL = """Lidl
Lindenweg 2
56501 Lindenau
                                     EUR
Milbona H-Milch 1,5%             0,99 A
Gouda jung Scheiben              1,79 A
Bananen                          1,12 A
  0,868 kg x 1,29 EUR/kg
Joghurt mild 3,5%                0,98 A
  2 x 0,49
Pfand 0,25 EW                    0,25 B
Fritz-Kola 1,5l                   1,59 B
Preisvorteil                    -0,30
Toilettenpapier 3-lagig          2,45 B
----------------------------------------
zu zahlen                        8,87
Bar                             10,00
Rückgeld                        -1,13

MWST%  MWST    + Netto  = Brutto
A 7%   0,32       4,56     4,88
Summe  0,96       7,91     8,87

02.11.26 10:15  1234  5678  90/12
"""

# the quantity line above its article (fits only the next article)
ALDI = """ALDI SÜD
Hauptstr. 12
56501 Lindenau
                                EUR
BUTTER MILSANI 250G           1,15 A
2 x 0,69
SPAGHETTI 500G                1,38 A
FR.VOLLMILCH 3,5% 1L          0,95 A
FREILAND-EIER 10ER            2,99 A
PAPRIKA ROT                   0,79 A
SUMME                         7,26
Kartenzahlung                 7,26
Datum: 03.11.2026  Uhrzeit 18:15
"""

# a name line whose weight line carries the total; empties
EDEKA = """EDEKA Muster
Lindenweg 1
56501 Lindenau
Tel. 02687 1234
                              EUR
GUT&GÜNSTIG BUTTER          1,39  A
JA VOLLMILCH 3,5% 1L        1,05  A
GOUDA SCHEIBEN 400G         2,98  A
   2 x 1,49
RISPENTOMATEN
   0,642 kg x 2,99 EUR/kg   1,92  A
LEERGUT                    -0,75  B
SUMME                 EUR   6,59
01.11.2026 17:02
"""

NETTO = """Netto Marken-Discount
Kornweg 7
57602 Feldheim
                               EUR
Hähnchenbrustfilet 400g      4,49 A
Rabatt 20%                  -0,90
Kartoffeln festk. 2,5kg      2,79 A
Zwiebeln 1kg                 1,29 A
Toastbrot 500g               0,99 A
------------------------------------
Summe                        8,66
EC-Cash                      8,66
03.11.2026 10:15:00
"""

# the first article is a name line plus a quantity line with its total; "Summe" alone
NORMA = """NORMA
Lebensmittelfilialbetrieb
Kornweg 1
57602 Feldheim
Mozzarella
  3 x 0,69                   2,07 A
Spaghetti                    0,79 A
Passierte Tomaten            0,59 A
Summe
EUR 3,45
03.11.2026
"""

PENNY = """PENNY Markt GmbH
Musterstr. 5
50667 Köln
NATURJOGHURT 3,5%           0,49 A
SAHNE 30%                   0,99 A
APFEL ELSTAR 1KG            1,99 A
  Sofortrabatt             -0,20
SUMME EUR                   3,27
02.11.2026 08:30
"""

# quantity inside the article line; a cancelled article
KAUFLAND = """Kaufland
Musterweg 1
10115 Berlin
K-CLASSIC ZUCKER 1KG        0,99 B
WEIZENMEHL 405 1KG          0,59 B
JOGHURT 2 x 0,49            0,98 B
BUTTER 250G                 1,79 B
STORNO BUTTER 250G         -1,79 B
SUMME                       2,56
Karte                       2,56
03.11.26
"""

ROSSMANN = """ROSSMANN
Dirk Rossmann GmbH
Rheinweg 5
56501 Lindenau
                         EUR
ISANA DUSCHGEL 300ML     0,95 A
ROSSMANN ZAHNPASTA       0,75 A
FROSCH SPUELMITTEL       1,29 A
TOILETTENPAPIER 8 ROLLEN 2,79 A
SUMME EUR                5,78
03.11.2026 12:01
"""

DM = """dm-drogerie markt
Musterstr. 3
76131 Karlsruhe
Balea Duschgel 300ml      0,95 2
Ebelin Wattepads 80St     0,85 2
dmBio Haferflocken 500g   0,85 1
SUMME EUR                 2,65
03.11.2026 09:12
"""


def _items(parsed: dict[str, Any]) -> list[tuple[Any, ...]]:
    return [
        (i["name"], i["price"], i["quantity"], i["weight"], i["kind"], i["ignored"])
        for i in parsed["items"]
    ]


# ----------------------------------------------------------------------
# text parser (pure)
# ----------------------------------------------------------------------


def test_parse_rewe_header_quantity_weight_deposit() -> None:
    """REWE: store and address from the header, quantity and weight lines belong to the
    article above them, Pfand is kept as ignored line, nothing after SUMME counts."""
    parsed = parse_receipt_text(REWE, TODAY)
    assert parsed["retailer"] == "rewe"
    assert (parsed["postcode"], parsed["city"], parsed["street"]) == (
        "57601",
        "Bergdorf",
        "Bahnhofstr. 3",
    )
    assert parsed["date"] == "2026-11-03"
    assert (parsed["total"], parsed["sum"], parsed["checked"]) == (15.19, 15.19, True)
    assert _items(parsed) == [
        ("H-MILCH 1,5%", 1.09, 1.0, None, "article", False),
        ("GOUDA JUNG SCHEIB", 1.99, 1.0, None, "article", False),
        ("BIO EIER 10ER", 3.29, 1.0, None, "article", False),
        ("HACKFL.GEM.", 5.98, 2.0, None, "article", False),
        ("BANANE", 1.1, 1.0, 0.856, "article", False),
        ("PFAND 0,25 EURO", 0.25, 1.0, None, "deposit", True),
        ("FRITZ KOLA 1,0L", 1.49, 1.0, None, "article", False),
    ]
    hack = parsed["items"][3]
    assert hack["unit_price"] == 2.99 and "2 Stk x" in hack["line"]
    assert parsed["items"][4]["unit_price"] == 1.29


def test_parse_lidl_discount_and_payment() -> None:
    """Lidl: 'zu zahlen' is the total, 'Preisvorteil' reduces the article above, cash and
    change are no articles, the two-digit year is read."""
    parsed = parse_receipt_text(LIDL, TODAY)
    assert parsed["retailer"] == "lidl"
    assert parsed["postcode"] == "56501"
    assert parsed["date"] == "2026-11-02"
    assert (parsed["total"], parsed["checked"]) == (8.87, True)
    cola = next(i for i in parsed["items"] if i["name"].startswith("Fritz"))
    assert (cola["price"], cola["discount"]) == (1.29, 0.3)
    joghurt = next(i for i in parsed["items"] if i["name"].startswith("Joghurt"))
    assert (joghurt["quantity"], joghurt["unit_price"]) == (2.0, 0.49)
    assert [i["name"] for i in parsed["items"]][-1] == "Toilettenpapier 3-lagig"


def test_parse_aldi_quantity_line_before_its_article() -> None:
    """A '2 x 0,69' line that fits only the next article goes to that one."""
    parsed = parse_receipt_text(ALDI, TODAY)
    assert parsed["retailer"] == "aldi-sued"
    assert parsed["date"] == "2026-11-03"
    assert parsed["checked"]
    butter, spaghetti = parsed["items"][:2]
    assert (butter["quantity"], butter["price"]) == (1.0, 1.15)
    assert (spaghetti["quantity"], spaghetti["unit_price"], spaghetti["price"]) == (2.0, 0.69, 1.38)


def test_parse_edeka_name_line_and_empties() -> None:
    """A name line followed by its weight line with the total; Leergut is ignored."""
    parsed = parse_receipt_text(EDEKA, TODAY)
    assert (parsed["retailer"], parsed["store"]) == ("edeka", "EDEKA Muster")
    assert parsed["checked"] and parsed["total"] == 6.59
    assert _items(parsed)[2:] == [
        ("GOUDA SCHEIBEN 400G", 2.98, 2.0, None, "article", False),
        ("RISPENTOMATEN", 1.92, 1.0, 0.642, "article", False),
        ("LEERGUT", -0.75, 1.0, None, "deposit", True),
    ]


@pytest.mark.parametrize(
    ("text", "retailer", "postcode", "total", "names"),
    [
        (
            NETTO,
            "netto-marken-discount",
            "57602",
            8.66,
            [
                "Hähnchenbrustfilet 400g",
                "Kartoffeln festk. 2,5kg",
                "Zwiebeln 1kg",
                "Toastbrot 500g",
            ],
        ),
        (NORMA, "norma", "57602", 3.45, ["Mozzarella", "Spaghetti", "Passierte Tomaten"]),
        (PENNY, "penny", "50667", 3.27, ["NATURJOGHURT 3,5%", "SAHNE 30%", "APFEL ELSTAR 1KG"]),
        (
            ROSSMANN,
            "rossmann",
            "56501",
            5.78,
            [
                "ISANA DUSCHGEL 300ML",
                "ROSSMANN ZAHNPASTA",
                "FROSCH SPUELMITTEL",
                "TOILETTENPAPIER 8 ROLLEN",
            ],
        ),
        (
            DM,
            "dm-drogerie-markt",
            "76131",
            2.65,
            ["Balea Duschgel 300ml", "Ebelin Wattepads 80St", "dmBio Haferflocken 500g"],
        ),
    ],
)
def test_parse_more_chains(
    text: str, retailer: str, postcode: str, total: float, names: list[str]
) -> None:
    """Netto, Norma, Penny, Rossmann and dm (tax classes 1/2): store, postcode, total and
    the articles; the sum of the lines equals the total."""
    parsed = parse_receipt_text(text, TODAY)
    assert (parsed["retailer"], parsed["postcode"], parsed["total"]) == (retailer, postcode, total)
    assert parsed["checked"], (parsed["sum"], total)
    assert [i["name"] for i in parsed["items"] if not i["ignored"]] == names


def test_parse_details_of_netto_norma_penny() -> None:
    """Rabatt without keyword-free fallback, a first name line + quantity line with its
    total, 'Summe' with the amount on the next line, an indented discount."""
    netto = parse_receipt_text(NETTO, TODAY)
    chicken = netto["items"][0]
    assert (chicken["price"], chicken["discount"]) == (3.59, 0.9)
    norma = parse_receipt_text(NORMA, TODAY)
    mozzarella = norma["items"][0]
    assert (mozzarella["quantity"], mozzarella["unit_price"], mozzarella["price"]) == (
        3.0,
        0.69,
        2.07,
    )
    assert norma["store"] == "NORMA"
    penny = parse_receipt_text(PENNY, TODAY)
    assert penny["items"][-1]["price"] == 1.79 and penny["items"][-1]["discount"] == 0.2


def test_parse_kaufland_inline_quantity_and_storno() -> None:
    """'JOGHURT 2 x 0,49 0,98' carries its quantity; a STORNO line cancels the article."""
    parsed = parse_receipt_text(KAUFLAND, TODAY)
    assert parsed["retailer"] == "kaufland"
    assert parsed["date"] == "2026-11-03"
    joghurt = next(i for i in parsed["items"] if i["name"] == "JOGHURT")
    assert (joghurt["quantity"], joghurt["unit_price"], joghurt["price"]) == (2.0, 0.49, 0.98)
    butter = [i for i in parsed["items"] if "BUTTER" in i["name"]]
    assert all(i["ignored"] and i["kind"] == "storno" for i in butter)
    assert (parsed["total"], parsed["sum"], parsed["checked"]) == (2.56, 2.56, True)


def test_parse_without_total_ignores_payment_and_info_lines() -> None:
    """No SUMME: payment lines and base price lines are still no articles."""
    text = "Butter 1,19 A\n(1 kg = 4,76 €)\n1 kg = 4,76\nBar 5,00\nRückgeld -3,81\n"
    parsed = parse_receipt_text(text, TODAY)
    assert _items(parsed) == [("Butter", 1.19, 1.0, None, "article", False)]
    assert parsed["total"] is None and parsed["checked"] is False
    assert parsed["retailer"] is None and parsed["postcode"] is None


def test_parse_brand_total_and_household_einweg() -> None:
    """'TOTAL' with a tax class is an article (a yoghurt brand), 'Einweghandschuhe' no
    deposit, a trailing minus is a negative amount."""
    text = (
        "FAGE TOTAL 0% 1,99 B\nTOTAL GRIECH. JOGHURT 2,29 B\nEinweghandschuhe 1,49 A\n"
        "EINWEG 0,25 A\nLEERGUT 0,25-\nSUMME 5,77\n"
    )
    parsed = parse_receipt_text(text, TODAY)
    assert _items(parsed) == [
        ("FAGE TOTAL 0%", 1.99, 1.0, None, "article", False),
        ("TOTAL GRIECH. JOGHURT", 2.29, 1.0, None, "article", False),
        ("Einweghandschuhe", 1.49, 1.0, None, "article", False),
        ("EINWEG", 0.25, 1.0, None, "deposit", True),
        ("LEERGUT", -0.25, 1.0, None, "deposit", True),
    ]
    assert parsed["total"] == 5.77 and parsed["checked"]


def test_parse_receipt_date() -> None:
    """'Datum' lines first; future and very old dates are no receipt dates."""
    assert parse_receipt_date("Bon 12\nDatum: 01.11.2026", TODAY) == date(2026, 11, 1)
    assert parse_receipt_date("03.11.26 10:15", TODAY) == date(2026, 11, 3)
    assert parse_receipt_date("2026-10-30", TODAY) == date(2026, 10, 30)
    assert parse_receipt_date("MHD 24.12.2026\nDatum 02.11.2026", TODAY) == date(2026, 11, 2)
    assert parse_receipt_date("24.12.2026", TODAY) is None  # in the future
    assert parse_receipt_date("01.01.2019", TODAY) is None
    assert parse_receipt_date("31.02.2026", TODAY) is None
    assert parse_receipt_date("", TODAY) is None


def test_line_pack_and_tokens() -> None:
    """Pack sizes printed in names; abbreviations expanded, quality words dropped."""
    assert line_pack("BUTTER MILSANI 250G") == (250.0, "g")
    assert line_pack("H-MILCH 1,5% 1L") == (1000.0, "ml")
    assert line_pack("BIO EIER 10ER") == (10.0, "Stück")
    assert line_pack("WASSER 6X1,5L") == (9000.0, "ml")
    assert line_pack("TOILETTENPAPIER 8 ROLLEN") == (8.0, "Rolle")
    assert line_pack("H-MILCH 1,5%") is None
    assert name_tokens("HACKFL.GEM.") == ["hackfleisch", "gemischt"]
    assert name_tokens("GOUDA JUNG SCHEIB") == ["gouda", "scheiben"]
    assert name_tokens("BIO EIER 10ER") == ["eier"]
    assert name_tokens("H-MILCH 1,5%") == ["h", "milch"]


def test_own_price_of_a_line() -> None:
    """The regular price of one piece (before a discount); weighed articles per kg."""
    assert own_price({"price": 5.98, "quantity": 2, "amount": 500, "unit": "g"}) == (
        2.99,
        500.0,
        "g",
    )
    assert own_price({"price": 1.29, "discount": 0.3, "amount": 1500, "unit": "ml"}) == (
        1.59,
        1500.0,
        "ml",
    )
    assert own_price({"price": 1.10, "weight": 0.856, "unit_price": 1.29}) == (1.29, 1000.0, "g")
    assert own_price({"price": 0, "quantity": 1}) is None


# ----------------------------------------------------------------------
# AI answers (pure)
# ----------------------------------------------------------------------

AI_RECEIPT = {
    "store": "Lidl",
    "address": "Lindenweg 2, 56501 Lindenau",
    "date": "02.11.2026",
    "items": [
        {"name": "Milbona H-Milch 1,5%", "quantity": 1, "unit_price": 0.99, "total": 0.99},
        {"name": "Bananen", "quantity": 0.868, "unit_price": 1.29, "total": 1.12},
        {"name": "Joghurt mild", "quantity": 2, "unit_price": "0,49", "total": "0,98"},
        {"name": "Pfand", "quantity": 1, "unit_price": 0.25, "total": 0.25},
        {"name": "Fritz-Kola 1,5l", "quantity": 1, "unit_price": 1.59, "total": 1.59},
        {"name": "Preisvorteil", "quantity": 1, "unit_price": None, "total": -0.30},
        {"name": None, "total": 3},
        {"name": "???", "total": None},
    ],
    "total": 4.63,
}


def test_extract_json_tolerates_fences_text_and_trailing_commas() -> None:
    """Code fences, text around the JSON and trailing commas are fine; no JSON raises."""
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Hier ist der Bon: {"a": [1, 2,], "b": "x}"} Viel Spaß!') == {
        "a": [1, 2],
        "b": "x}",
    }
    assert extract_json("[1, 2]") == [1, 2]
    with pytest.raises(ValueError):
        extract_json("Ich kann das Bild leider nicht lesen.")
    with pytest.raises(ValueError):
        extract_json('{"items": [')


def test_parse_ai_receipt() -> None:
    """Text or object answers; numbers as text; weight in kg; Pfand ignored; the
    discount reduces the article before; broken lines are dropped."""
    for answer in (
        {"data": json.dumps(AI_RECEIPT)},
        {"data": AI_RECEIPT},
        {"conversation_id": "x", "data": f"```json\n{json.dumps(AI_RECEIPT)}\n```"},
    ):
        parsed = parse_ai_receipt(answer, TODAY)
        assert parsed["source"] == "photo"
        assert (parsed["retailer"], parsed["postcode"], parsed["date"]) == (
            "lidl",
            "56501",
            "2026-11-02",
        )
        assert (parsed["total"], parsed["sum"], parsed["checked"]) == (4.63, 4.63, True)
        assert _items(parsed) == [
            ("Milbona H-Milch 1,5%", 0.99, 1.0, None, "article", False),
            ("Bananen", 1.12, 1.0, 0.868, "article", False),
            ("Joghurt mild", 0.98, 2.0, None, "article", False),
            ("Pfand", 0.25, 1.0, None, "deposit", True),
            ("Fritz-Kola 1,5l", 1.29, 1.0, None, "article", False),
        ]
    for garbage in ({"data": "Das Bild ist unscharf."}, {"data": {"items": []}}, {"data": 3}):
        with pytest.raises(ValueError):
            parse_ai_receipt(garbage, TODAY)


# ----------------------------------------------------------------------
# with Home Assistant: mapping, branches, saving
# ----------------------------------------------------------------------


@pytest.fixture
async def receipts_setup(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, tmp_path: Path
) -> MockConfigEntry:
    """The integration with config and media folders of its own (tmp) and the test user's
    stores."""
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
    manager.save_branch({"store": "Lidl", "street": "Lindenweg 2", "postcode": "56501"})
    manager.save_branch(
        {"store": "EDEKA", "name": "EDEKA Muster", "street": "Lindenweg 1", "postcode": "56501"}
    )
    manager.save_branch({"store": "Rossmann", "street": "Rheinweg 5", "postcode": "56501"})
    return config_entry


def _branch(manager, retailer: str) -> dict[str, Any]:
    return next(b for b in manager.branches if b["retailer"] == retailer)


async def _call(hass: HomeAssistant, service: str, **data) -> dict[str, Any]:
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


async def test_mapping_receipt_abbreviations(hass: HomeAssistant, receipts_setup) -> None:
    """Receipt abbreviations become ingredient keys; other products stay unknown."""
    manager = receipts_setup.runtime_data
    mapper = ReceiptMapper(manager, "rewe")
    expected = {
        "H-MILCH 1,5%": "milch",
        "GOUDA JUNG SCHEIB": "gouda",
        "HACKFL.GEM.": "hackfleisch",
        "BIO EIER 10ER": "ei",
        "BUTTER MILSANI 250G": "butter",
        "FR.VOLLMILCH 3,5% 1L": "milch",
        "Milbona H-Milch 1,5%": "milch",
        "RISPENTOMATEN": "tomate",
        "Bio-Möhren 1kg": "karotte",
        "SPEISEQ. 40%": "magerquark",
        "ERDNUSS BUTTER": "erdnussbutter",  # one compound, not butter
        "KOKOSMILCH 400ML": "kokosmilch",  # not milk
        "FROSCH SPUELMITTEL": "spuelmittel",
        "TOILETTENPAPIER 8 ROLLEN": "toilettenpapier",
    }
    for name, key in expected.items():
        assert mapper.map(name)["key"] == key, name
    for name in ("SCHOKO EIER", "MILCHSCHNITTE", "BUTTERKEKSE", "TRAGETASCHE"):
        assert mapper.map(name)["key"] is None, name
    assert mapper.map("H-MILCH 1,5%")["confidence"] >= 0.9


async def test_proposal_detects_branch_and_packs(hass: HomeAssistant, receipts_setup) -> None:
    """The header postcode finds the chain's branch; pack sizes come from the line, the
    store's price or the estimate; weighed articles are priced per kg."""
    manager = receipts_setup.runtime_data
    rewe = _branch(manager, "rewe")
    manager.set_store_price("rewe", "Gouda", 1.79, 150, "g")  # the REWE pack: 150 g
    proposal = await _call(hass, "receipt_parse_text", text=REWE)
    assert (proposal["retailer"], proposal["branch_id"], proposal["branch_match"]) == (
        "rewe",
        rewe["id"],
        "postcode",
    )
    assert proposal["date"] == "2026-11-03" and proposal["checked"] is True
    items = {i["name"]: i for i in proposal["items"]}
    assert items["GOUDA JUNG SCHEIB"]["key"] == "gouda"
    assert (items["GOUDA JUNG SCHEIB"]["amount"], items["GOUDA JUNG SCHEIB"]["pack_source"]) == (
        150.0,
        "store",
    )
    assert items["GOUDA JUNG SCHEIB"]["current"]["price"] == 1.79
    eggs = items["BIO EIER 10ER"]
    assert (eggs["key"], eggs["amount"], eggs["unit"], eggs["pack_source"]) == (
        "ei",
        10.0,
        "Stück",
        "line",
    )
    hack = items["HACKFL.GEM."]
    assert hack["own_price"] == {"price": 2.99, "amount": 500, "unit": "g"}  # estimate pack
    banana = items["BANANE"]
    assert banana["own_price"] == {"price": 1.29, "amount": 1000.0, "unit": "g"}
    assert items["PFAND 0,25 EURO"]["status"] == "ignored"
    assert items["FRITZ KOLA 1,0L"]["status"] == "unknown"
    assert (proposal["mapped"], proposal["unknown"], proposal["ignored"]) == (5, 1, 1)
    # Lidl and the drugstore at the same postcode: each receipt finds its own branch
    lidl = await _call(hass, "receipt_parse_text", text=LIDL)
    assert lidl["branch_id"] == _branch(manager, "lidl")["id"]
    rossmann = await _call(hass, "receipt_parse_text", text=ROSSMANN)
    assert rossmann["branch_id"] == _branch(manager, "rossmann")["id"]
    assert rossmann["kind"] == "drugstore"
    # a receipt without chain name: the postcode alone is not unique (3 branches there)
    anonymous = await _call(
        hass, "receipt_parse_text", text="Lindenweg 9\n56501 Lindenau\nButter 1,19 A"
    )
    assert anonymous["branch_id"] is None and anonymous["warnings"]
    given = await _call(
        hass, "receipt_parse_text", text="Butter 1,19 A", branch=_branch(manager, "edeka")["id"]
    )
    assert (given["retailer"], given["branch_match"]) == ("edeka", "given")
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "receipt_parse_text", text="Kassenbon\nVielen Dank")
    assert err.value.translation_key == "receipt_no_items"


async def test_save_sets_own_prices_and_matrix_source(
    hass: HomeAssistant, receipts_setup, hass_storage, freezer
) -> None:
    """Saving a proposal sets the mapped articles as own store prices (source receipt,
    receipt id and date); the price list shows them as "Kassenzettel" of that day."""
    manager = receipts_setup.runtime_data
    proposal = await _call(hass, "receipt_parse_text", text=LIDL)
    result = await _call(hass, "receipt_save", receipt=proposal)
    receipt = result["receipt"]
    assert receipt["retailer"] == "lidl" and receipt["date"] == "2026-11-02"
    assert result["saved"] == 5 and result["kept"] == 0 and result["unknown"] == 1
    milk = manager.store_prices_user["lidl"]["milch"]
    assert milk["source"] == "receipt" and milk["receipt_id"] == receipt["id"]
    assert (milk["price"], milk["amount"], milk["unit"]) == (0.99, 1000, "ml")
    assert milk["receipt_date"] == "2026-11-02"
    assert milk["history"][-1] == {
        "date": "2026-11-02",
        "price": 0.99,
        "source": "receipt",
        "receipt": receipt["id"],
        "amount": 1000.0,
        "unit": "ml",
        "name": "Milch",
    }
    # the discount is no regular price: Fritz-Kola is unknown, the yoghurt per piece
    assert manager.store_prices_user["lidl"]["joghurt"]["price"] == 0.49
    assert manager.store_prices_user["lidl"]["banane"]["price"] == 1.29  # per kg
    matrix = manager.store_price_matrix("Milch")
    row = next(r for r in matrix["rows"] if r["key"] == "milch")
    cell = row["stores"]["lidl"]
    assert cell["source"] == "receipt"
    assert cell["receipt_id"] == receipt["id"]
    assert cell["updated"] == "2026-11-02"
    # the own price counts for planning like a typed one
    assert manager.store_book("lidl").lookup("Milch").price == 0.99
    freezer.tick(timedelta(seconds=5))  # the receipts file is written shortly after
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    stored = hass_storage[ReceiptStore.store_key(receipts_setup.entry_id)]["data"]
    assert [r["id"] for r in stored["receipts"]] == [receipt["id"]]
    assert stored["receipts"][0]["items"][0]["status"] == "saved"


async def test_newer_wins_typed_price_after_receipt_stays(
    hass: HomeAssistant, receipts_setup
) -> None:
    """A newer receipt replaces an older own price; a price typed after the receipt's
    date stays (the receipt's price goes into the history)."""
    manager = receipts_setup.runtime_data
    base = {"store": "Lidl", "items": [{"name": "Butter", "key": "butter", "price": 1.69}]}
    await _call(hass, "receipt_save", receipt={**base, "date": "2026-10-20"})
    assert manager.store_prices_user["lidl"]["butter"]["price"] == 1.69
    # typed today (04.11.): an older receipt does not overwrite it
    manager.set_store_price("lidl", "Butter", 1.99, 250, "g")
    older = {**base, "date": "2026-11-01", "items": [{**base["items"][0], "price": 1.59}]}
    result = await _call(hass, "receipt_save", receipt=older)
    assert result["prices"][0]["status"] == "kept"
    butter = manager.store_prices_user["lidl"]["butter"]
    assert (butter["price"], butter["source"]) == (1.99, "user")
    assert [h["price"] for h in butter["history"]] == [1.69, 1.59, 1.99]
    # a receipt of today is not older: it replaces the typed price
    today = {**base, "date": "04.11.2026", "items": [{**base["items"][0], "price": 1.49}]}
    result = await _call(hass, "receipt_save", receipt=today)
    assert result["prices"][0]["status"] == "saved"
    butter = manager.store_prices_user["lidl"]["butter"]
    assert (butter["price"], butter["source"], butter["amount"]) == (1.49, "receipt", 250)
    # a future date is refused
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "receipt_save", receipt={**base, "date": "2026-11-05"})
    assert err.value.translation_key == "invalid_date"
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "receipt_save", receipt={"items": base["items"]})
    assert err.value.translation_key == "store_required"
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "receipt_save", receipt={"store": "Lidl", "items": []})
    assert err.value.translation_key == "receipt_no_items"


async def test_assigned_names_are_remembered(hass: HomeAssistant, receipts_setup) -> None:
    """An unknown line the user assigns is recognized on the next receipt of the chain."""
    manager = receipts_setup.runtime_data
    proposal = await _call(hass, "receipt_parse_text", text=REWE)
    cola = next(i for i in proposal["items"] if i["name"] == "FRITZ KOLA 1,0L")
    assert cola["status"] == "unknown"
    cola["key"] = "Cola"
    cola["amount"], cola["unit"] = 1000, "ml"
    await _call(hass, "receipt_save", receipt=proposal)
    assert manager.store_prices_user["rewe"]["cola"]["price"] == 1.49
    again = await _call(hass, "receipt_parse_text", text=REWE)
    cola = next(i for i in again["items"] if i["name"] == "FRITZ KOLA 1,0L")
    assert (cola["key"], cola["match"], cola["status"]) == ("cola", "alias", "mapped")


async def test_get_update_and_delete_receipts(hass: HomeAssistant, receipts_setup) -> None:
    """get_receipts lists the newest first; saving with the id updates a receipt (keys
    it no longer sets lose its price); delete keeps the prices unless remove_prices."""
    manager = receipts_setup.runtime_data
    first = await _call(
        hass, "receipt_save", receipt=await _call(hass, "receipt_parse_text", text=EDEKA)
    )
    second = await _call(
        hass, "receipt_save", receipt=await _call(hass, "receipt_parse_text", text=NETTO)
    )
    listed = await _call(hass, "get_receipts")
    assert listed["count"] == 2
    assert [r["id"] for r in listed["receipts"]] == [
        second["receipt"]["id"],
        first["receipt"]["id"],
    ]
    assert listed["receipts"][0]["retailer_name"] == "Netto"
    assert listed["ai_entity"] is None and listed["ai_available"] is False
    # update: the EDEKA receipt without the tomatoes
    receipt = dict(first["receipt"])
    receipt["items"] = [i for i in receipt["items"] if i["name"] != "RISPENTOMATEN"]
    assert "tomate" in manager.store_prices_user["edeka"]
    await _call(hass, "receipt_save", receipt=receipt)
    assert "tomate" not in manager.store_prices_user["edeka"]
    assert (await _call(hass, "get_receipts"))["count"] == 2
    # delete keeps / removes prices
    result = await _call(hass, "delete_receipt", id=second["receipt"]["id"])
    assert result == {
        "id": second["receipt"]["id"],
        "removed": True,
        "prices_removed": 0,
        "image_removed": 0,
    }
    assert "zwiebel" in manager.store_prices_user["netto-marken-discount"]
    result = await _call(hass, "delete_receipt", id=first["receipt"]["id"], remove_prices=True)
    assert result["prices_removed"] == 3
    assert "edeka" not in manager.store_prices_user
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "delete_receipt", id="nope")
    assert err.value.translation_key == "receipt_not_found"


async def test_storage_limit_drops_oldest_receipts(
    hass: HomeAssistant, receipts_setup, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Over MAX_RECEIPTS the oldest receipts go, with their images."""
    monkeypatch.setattr(receipts_module, "MAX_RECEIPTS", 2)
    manager = receipts_setup.runtime_data
    upload = await manager.receipts.async_add_upload(JPEG, "image/jpeg", "bon.jpg")
    image = tmp_path / "config" / ".storage" / "essensplaner_receipts" / upload["file"]
    assert image.is_file()
    base = {"store": "Lidl", "items": [{"name": "Butter", "price": 1.69}]}
    oldest = await _call(
        hass, "receipt_save", receipt={**base, "date": "2026-10-01", "upload_id": upload["id"]}
    )
    assert oldest["receipt"]["id"] == upload["id"]
    assert oldest["receipt"]["image"] == f"essensplaner/receipts/{upload['file']}"
    await _call(hass, "receipt_save", receipt={**base, "date": "2026-10-10"})
    await _call(hass, "receipt_save", receipt={**base, "date": "2026-10-05"})
    dates = sorted(r["date"] for r in manager.receipts.receipts)
    assert dates == ["2026-10-05", "2026-10-10"]
    await hass.async_block_till_done()
    assert not image.exists()


# ----------------------------------------------------------------------
# AI Task (photo)
# ----------------------------------------------------------------------


def _fake_ai(hass: HomeAssistant, answer: Any) -> list[dict[str, Any]]:
    """Register a fake ai_task.generate_data returning answer; returns the calls."""
    calls: list[dict[str, Any]] = []

    async def handler(call: ServiceCall) -> dict[str, Any]:
        calls.append(dict(call.data))
        if isinstance(answer, Exception):
            raise answer
        return answer

    hass.services.async_register(
        "ai_task", "generate_data", handler, supports_response=SupportsResponse.ONLY
    )
    hass.states.async_set("ai_task.bon_leser", "unknown")
    return calls


async def test_scan_sends_only_the_receipt(hass: HomeAssistant, receipts_setup) -> None:
    """The AI Task gets only the receipt image and the fixed instructions; its answer
    becomes the same proposal as a pasted text."""
    manager = receipts_setup.runtime_data
    calls = _fake_ai(
        hass, {"conversation_id": "1", "data": f"```json\n{json.dumps(AI_RECEIPT)}\n```"}
    )
    upload = await manager.receipts.async_add_upload(JPEG, "image/jpeg", "Kassenzettel 1.jpg")
    proposal = await _call(
        hass, "receipt_scan", upload_id=upload["id"], entity_id="ai_task.bon_leser"
    )
    assert calls == [
        {
            "task_name": "Essensplaner Kassenzettel",
            "entity_id": "ai_task.bon_leser",
            "instructions": AI_INSTRUCTIONS,
            "attachments": [
                {
                    "media_content_id": f"media-source://essensplaner/receipt/{upload['file']}",
                    "media_content_type": "image/jpeg",
                }
            ],
        }
    ]
    assert proposal["source"] == "photo" and proposal["upload_id"] == upload["id"]
    assert proposal["branch_id"] == _branch(manager, "lidl")["id"]
    assert proposal["media_content_id"].endswith(upload["file"])
    assert {i["key"] for i in proposal["items"] if i["status"] == "mapped"} == {
        "milch",
        "banane",
        "joghurt",
    }
    # saving keeps the photo with the receipt
    result = await _call(hass, "receipt_save", receipt=proposal)
    assert result["receipt"]["source"] == "photo"
    assert result["receipt"]["id"] == upload["id"]
    assert manager.receipts.upload(upload["id"]) is None  # no longer pending
    # an object answer of a structured task works as well; reading the saved receipt
    # again and saving updates it (no second receipt)
    _fake_ai(hass, {"data": AI_RECEIPT})
    again = await _call(hass, "receipt_scan", upload_id=upload["id"], entity_id="ai_task.bon_leser")
    assert again["retailer"] == "lidl" and again["upload_id"] == upload["id"]
    again["items"] = [i for i in again["items"] if i["name"] != "Bananen"]
    result = await _call(hass, "receipt_save", receipt=again)
    assert result["receipt"]["id"] == upload["id"]
    assert len(manager.receipts.receipts) == 1
    assert manager.receipts.receipts[0]["image"].endswith(upload["file"])
    assert "banane" not in manager.store_prices_user["lidl"]


async def test_scan_errors(hass: HomeAssistant, receipts_setup) -> None:
    """Clear errors: no entity, entity unavailable, failing task, garbage answer,
    unknown upload, a file that is no receipt image."""
    manager = receipts_setup.runtime_data
    upload = await manager.receipts.async_add_upload(PNG, "image/png")

    async def scan(**data) -> str:
        with pytest.raises(ServiceValidationError) as err:
            await _call(hass, "receipt_scan", **data)
        return err.value.translation_key

    assert await scan(upload_id=upload["id"]) == "receipt_ai_not_configured"
    assert await scan(upload_id=upload["id"], entity_id="ai_task.bon_leser") == (
        "receipt_ai_unavailable"
    )
    _fake_ai(hass, {"data": "Ich sehe leider nur einen Daumen."})
    assert await scan(upload_id=upload["id"], entity_id="ai_task.bon_leser") == (
        "receipt_ai_invalid"
    )
    hass.states.async_set("ai_task.bon_leser", "unavailable")
    assert await scan(upload_id=upload["id"], entity_id="ai_task.bon_leser") == (
        "receipt_ai_unavailable"
    )
    _fake_ai(hass, HomeAssistantError("Modell nicht geladen"))
    assert await scan(upload_id=upload["id"], entity_id="ai_task.bon_leser") == (
        "receipt_ai_failed"
    )
    assert await scan(upload_id="0123456789abcdef", entity_id="ai_task.bon_leser") == (
        "receipt_upload_not_found"
    )
    assert await scan(media_content_id="media-source://camera/camera.tuer") == (
        "receipt_media_invalid"
    )
    assert await scan() == "receipt_media_invalid"


async def test_scan_uses_the_option_and_websockets(
    hass: HomeAssistant, receipts_setup, hass_ws_client
) -> None:
    """The option's entity is used; the panel websockets parse, save, list and delete."""
    entry = receipts_setup
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "receipt_ai_task_entity": "ai_task.bon_leser"}
    )
    await hass.async_block_till_done()  # options change = reload
    manager = entry.runtime_data
    calls = _fake_ai(hass, {"data": json.dumps(AI_RECEIPT)})
    upload = await manager.receipts.async_add_upload(JPEG, "image/jpeg")
    client = await hass_ws_client(hass)

    async def ws(message_id: int, **data) -> dict[str, Any]:
        await client.send_json({"id": message_id, **data})
        return await client.receive_json()

    msg = await ws(1, type=f"{DOMAIN}/receipt_parse", upload_id=upload["id"])
    assert msg["success"], msg
    assert calls[-1]["entity_id"] == "ai_task.bon_leser"
    proposal = msg["result"]
    assert proposal["image_url"].startswith(
        f"/api/essensplaner/receipt_image/{upload['id']}?authSig="
    )
    msg = await ws(2, type=f"{DOMAIN}/receipt_parse", text=PENNY)
    assert msg["success"] and msg["result"]["retailer"] == "penny"
    msg = await ws(3, type=f"{DOMAIN}/receipt_parse", text="nichts")
    assert not msg["success"] and msg["error"]["code"] == "receipt_no_items"
    assert "keine Artikel" in msg["error"]["message"]
    msg = await ws(4, type=f"{DOMAIN}/receipt_save", receipt=proposal)
    assert msg["success"], msg
    receipt = msg["result"]["receipt"]
    assert receipt["image_url"].startswith(f"/api/essensplaner/receipt_image/{receipt['id']}")
    msg = await ws(5, type=f"{DOMAIN}/receipts")
    assert msg["success"] and msg["result"]["count"] == 1
    assert msg["result"]["ai_entity"] == "ai_task.bon_leser" and msg["result"]["ai_available"]
    assert msg["result"]["receipts"][0]["image_url"]
    msg = await ws(6, type=f"{DOMAIN}/receipt_delete", receipt_id=receipt["id"], remove_prices=True)
    assert msg["success"] and msg["result"]["image_removed"] == 1
    assert msg["result"]["prices_removed"] == 3
    msg = await ws(7, type=f"{DOMAIN}/receipt_delete", receipt_id=receipt["id"])
    assert msg["error"]["code"] == "receipt_not_found"
    # the panel data knows whether photos can be read
    assert manager.economy_export()["receipts"]["ai_available"] is True


async def test_receipt_websockets_need_an_admin(
    hass: HomeAssistant, receipts_setup, hass_ws_client, hass_read_only_access_token
) -> None:
    """Receipts are for admins (like the upload)."""
    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/receipts"})
    msg = await client.receive_json()
    assert not msg["success"] and msg["error"]["code"] == "unauthorized"


# ----------------------------------------------------------------------
# upload and image views
# ----------------------------------------------------------------------


def _form(content: bytes, content_type: str, field: str = "file") -> aiohttp.FormData:
    form = aiohttp.FormData()
    form.add_field(field, content, filename="bon.jpg", content_type=content_type)
    return form


async def test_upload_and_image_views(
    hass: HomeAssistant,
    receipts_setup,
    hass_client,
    hass_client_no_auth,
    hass_read_only_access_token,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Admins upload jpg/png/webp/pdf ≤ 10 MB; the type must match the content; the image
    is served with the token or the signed link, never without."""
    client = await hass_client()
    resp = await client.post("/api/essensplaner/receipt_upload", data=_form(JPEG, "image/jpeg"))
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    upload_id = body["upload_id"]
    assert body["media_content_id"] == f"media-source://essensplaner/receipt/{upload_id}.jpg"
    assert (body["content_type"], body["size"]) == ("image/jpeg", len(JPEG))
    assert (
        tmp_path / "config" / ".storage" / "essensplaner_receipts" / f"{upload_id}.jpg"
    ).read_bytes() == JPEG
    # the image: with the token, with the signed link, not without
    resp = await client.get(f"/api/essensplaner/receipt_image/{upload_id}")
    assert resp.status == 200 and await resp.read() == JPEG
    assert resp.headers["Content-Type"] == "image/jpeg"
    anonymous = await hass_client_no_auth()
    resp = await anonymous.get(body["url"])
    assert resp.status == 200 and await resp.read() == JPEG
    resp = await anonymous.get(f"/api/essensplaner/receipt_image/{upload_id}")
    assert resp.status == 401
    resp = await client.get("/api/essensplaner/receipt_image/ffffffffffffffff")
    assert resp.status == 404
    resp = await client.get("/api/essensplaner/receipt_image/..%2F..%2Fsecrets")
    assert resp.status in (400, 404)
    # a PDF works as well; no multipart body is a missing file
    pdf = b"%PDF-1.7\n" + b"0" * 50
    resp = await client.post("/api/essensplaner/receipt_upload", data=_form(pdf, "application/pdf"))
    assert resp.status == 200 and (await resp.json())["content_type"] == "application/pdf"
    resp = await client.post("/api/essensplaner/receipt_upload", json={"file": "x"})
    assert resp.status == 400
    # a browser sending application/octet-stream: the content decides
    resp = await client.post(
        "/api/essensplaner/receipt_upload", data=_form(PNG, "application/octet-stream")
    )
    assert resp.status == 200 and (await resp.json())["content_type"] == "image/png"
    # wrong type, type not matching the content, no file, too large, not an admin
    resp = await client.post("/api/essensplaner/receipt_upload", data=_form(b"hello", "text/plain"))
    assert resp.status == 415 and (await resp.json())["code"] == "receipt_file_type"
    resp = await client.post("/api/essensplaner/receipt_upload", data=_form(b"<svg/>", "image/png"))
    assert resp.status == 415
    resp = await client.post(
        "/api/essensplaner/receipt_upload", data=_form(JPEG, "image/jpeg", "foto")
    )
    assert resp.status == 400 and (await resp.json())["code"] == "receipt_file_missing"
    monkeypatch.setattr(receipts_module, "MAX_UPLOAD_BYTES", 100)
    resp = await client.post("/api/essensplaner/receipt_upload", data=_form(JPEG, "image/jpeg"))
    assert resp.status == 413 and (await resp.json())["code"] == "receipt_file_too_large"
    reader = await hass_client(hass_read_only_access_token)
    resp = await reader.post("/api/essensplaner/receipt_upload", data=_form(PNG, "image/png"))
    assert resp.status == 401
    resp = await anonymous.post("/api/essensplaner/receipt_upload", data=_form(PNG, "image/png"))
    assert resp.status == 401
    pending = receipts_setup.runtime_data.receipts.data["uploads"]
    assert len(pending) == 3


async def test_old_uploads_are_removed_on_load(
    hass: HomeAssistant, receipts_setup, freezer, tmp_path: Path
) -> None:
    """Uploads that never became a receipt are deleted after a day (file and entry)."""
    manager = receipts_setup.runtime_data
    upload = await manager.receipts.async_add_upload(JPEG, "image/jpeg")
    path = tmp_path / "config" / ".storage" / "essensplaner_receipts" / upload["file"]
    await manager.receipts.async_save()
    freezer.tick(timedelta(hours=25))
    await hass.config_entries.async_reload(receipts_setup.entry_id)
    await hass.async_block_till_done()
    assert receipts_setup.runtime_data.receipts.upload(upload["id"]) is None
    assert not path.exists()


async def test_remove_entry_deletes_only_receipt_files(
    hass: HomeAssistant, receipts_setup, hass_storage, tmp_path: Path
) -> None:
    """Removing the integration deletes the receipts file and the receipt images – other
    files stay."""
    manager = receipts_setup.runtime_data
    upload = await manager.receipts.async_add_upload(JPEG, "image/jpeg")
    await _call(
        hass,
        "receipt_save",
        receipt={
            "store": "Lidl",
            "upload_id": upload["id"],
            "items": [{"name": "Butter", "price": 1.69}],
        },
    )
    pending = await manager.receipts.async_add_upload(PNG, "image/png")
    folder = tmp_path / "config" / ".storage" / "essensplaner_receipts"
    other = tmp_path / "media" / "urlaub.jpg"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_bytes(JPEG)
    stranger = folder / "eigene-notiz.txt"
    stranger.write_text("bleibt")
    await manager.receipts.async_save()
    key = ReceiptStore.store_key(receipts_setup.entry_id)
    assert key in hass_storage
    assert await hass.config_entries.async_remove(receipts_setup.entry_id)
    await hass.async_block_till_done()
    assert key not in hass_storage
    assert not (folder / upload["file"]).exists()
    assert not (folder / pending["file"]).exists()
    assert other.read_bytes() == JPEG and stranger.read_text() == "bleibt"


async def test_receipt_ai_option(hass: HomeAssistant, receipts_setup, hass_ws_client) -> None:
    """The panel's settings offer the AI Task entity (empty by default) and store / clear it
    (1.4: no longer in the options flow, which only toggles the sidebar panel)."""
    entry = receipts_setup
    hass.states.async_set("ai_task.bon_leser", "unknown", {"friendly_name": "Bon-Leser"})
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "essensplaner/get_settings"})
    msg = await client.receive_json()
    assert msg["result"]["values"]["receipt_ai_task_entity"] is None
    assert msg["result"]["defaults"]["receipt_ai_task_entity"] is None
    assert {"value": "ai_task.bon_leser", "label": "Bon-Leser", "available": True} in msg["result"][
        "choices"
    ]["ai_task_entities"]
    await client.send_json(
        {
            "id": 2,
            "type": "essensplaner/save_settings",
            "values": {"receipt_ai_task_entity": "ai_task.bon_leser"},
        }
    )
    assert (await client.receive_json())["result"] == {"saved": True, "reload": True}
    await hass.async_block_till_done()
    assert entry.options["receipt_ai_task_entity"] == "ai_task.bon_leser"
    # the options dialog of Home Assistant keeps it
    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(result["flow_id"], {"show_panel": False})
    await hass.async_block_till_done()
    assert entry.options["receipt_ai_task_entity"] == "ai_task.bon_leser"
    # an emptied picker removes it (receipts as pasted text only)
    await client.send_json(
        {"id": 3, "type": "essensplaner/save_settings", "values": {"receipt_ai_task_entity": ""}}
    )
    assert (await client.receive_json())["result"] == {"saved": True, "reload": True}
    await hass.async_block_till_done()
    assert "receipt_ai_task_entity" not in entry.options
