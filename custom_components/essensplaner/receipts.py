"""Receipts (Kassenzettel): keep them and take the store's current prices from them (1.4).

A receipt comes in as pasted text (parsed locally, always available) or as a photo / PDF
(uploaded to a private folder and read by the user's AI Task entity, optional). Both
give a proposal: store, branch (header postcode), date, total and the articles mapped to
ingredient keys. The user reviews it; receipt_save stores the receipt and sets the mapped
articles as the store's OWN prices (store_prices_user[retailer][key], source "receipt").
No price of another chain is ever estimated from a receipt.

Storage: its own file essensplaner.receipts.<entry_id> {version, receipts: [...],
uploads: {upload_id: ...}, aliases: {...}} (≤ MAX_RECEIPTS receipts, the oldest go) and
the images in <config>/.storage/essensplaner_receipts/<id>.<ext> – not in a media folder,
which every Home Assistant user may browse: only admins see them (image view, panel); the
AI Task gets them through the integration's own media source (media_source.py), which
lists nothing. Only receipt files (<hex id>.<ext>) are ever deleted.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from http import HTTPStatus
import logging
from pathlib import Path
import re
import secrets
import shutil
import time
from typing import TYPE_CHECKING, Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView, require_admin
from homeassistant.components.http.const import KEY_HASS_REFRESH_TOKEN_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.http import KEY_HASS
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
import voluptuous as vol

from . import ai
from .ai import extract_json  # moved to ai.py in 1.5
from .catalog import KeyMatcher
from .const import AI_FEATURE_RECEIPTS, DOMAIN, STORAGE_KEY
from .ingredients import _singular, fold, guess_category, ingredient_key
from .offers import names_other_compound, offer_matches, parse_pack_text, short_key
from .pricing import lookup_keys, make_entry, pack_text, unit_price
from .retailers import (
    ALDI_NORD,
    ALDI_SUED,
    aldi_for_postcode,
    retailer_kind,
    retailer_matches,
    retailer_name,
    retailers_named,
)

if TYPE_CHECKING:
    from .manager import EssensplanerManager

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
MAX_RECEIPTS = 200
MAX_UPLOADS = 20
UPLOAD_KEEP_HOURS = 24
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARS = 20000
MAX_ITEMS = 150
MAX_ALIASES = 1000
MAX_PRICE = 10000.0
MAX_QUANTITY = 1000.0
# folder below the media directory (media-source://media_source/<dir>/essensplaner/receipts)
# the stored image path of a receipt ("essensplaner/receipts/<file>"; 1.4 development
# versions kept the files in that media folder, they are moved on load)
MEDIA_SUBDIR = "essensplaner/receipts"
RECEIPTS_DIR = "essensplaner_receipts"  # in <config>/.storage
MEDIA_SOURCE_RECEIPT = "receipt"  # media-source://essensplaner/receipt/<file>
_FILE_RE = re.compile(r"[a-f0-9]{8,32}\.(?:jpg|png|webp|pdf)")
_LEFTOVER_RE = re.compile(r"\.?[a-f0-9]{8,32}\.(?:jpg|png|webp|pdf)(?:\.part)?")
ORPHAN_MINUTES = 60  # an unknown file this old is left over (an upload is written at once)
CONTENT_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "application/pdf": "pdf",
}
EXTENSION_TYPES = {ext: ctype for ctype, ext in CONTENT_TYPES.items()} | {"jpeg": "image/jpeg"}
UPLOAD_URL = "/api/essensplaner/receipt_upload"
IMAGE_URL = "/api/essensplaner/receipt_image/{receipt_id}"
# lifetime of the signed image links the panel gets (<img> cannot send a token)
IMAGE_LINK_HOURS = 24
# seconds the AI Task entity may take for one receipt (local models are slow)
AI_TIMEOUT = 240
AI_TASK_NAME = "Essensplaner Kassenzettel"
SOURCE_TEXT = "text"
SOURCE_PHOTO = "photo"
SOURCE_RECEIPT = "receipt"
# mapping confidence from which an article counts as recognized
MIN_CONFIDENCE = 0.5
# cent tolerance of quantity x price checks (receipts round to the cent)
_TOLERANCE = 0.015
_ID_RE = re.compile(r"^[a-f0-9]{8,32}$")

# German instructions for the AI Task entity: only the receipt is attached, nothing about
# the user (no branches, prices or plan) is sent
AI_INSTRUCTIONS = (
    "Lies den angehängten Kassenzettel eines deutschen Supermarkts oder einer Drogerie. "
    "Antworte NUR mit einem JSON-Objekt, ohne Erklärung und ohne Markdown, genau in dieser "
    'Form: {"store": "Name des Ladens", "address": "Straße Hausnummer, PLZ Ort", '
    '"date": "TT.MM.JJJJ", "items": [{"name": "Artikeltext wie gedruckt", "quantity": 1, '
    '"unit_price": 1.09, "total": 1.09}], "total": 12.34}. Regeln: jede Artikelzeile '
    "einzeln in der Reihenfolge des Zettels; Preise als Zahlen mit Punkt (1.09); quantity "
    "ist die Stückzahl, bei gewogener Ware das Gewicht in kg (z. B. 0.512) mit dem "
    "Kilopreis als unit_price; Pfand und Leergut als eigene Zeile; Rabatte und "
    "Preisvorteile als eigene Zeile mit negativem total direkt nach dem Artikel; Summe, "
    "Zahlungsart (bar, Karte), Rückgeld, MwSt und Werbung weglassen; nichts erfinden – "
    "Unlesbares als null."
)

# ----------------------------------------------------------------------------------
# Line patterns
# ----------------------------------------------------------------------------------

_PRICE = r"-?\d{1,5}[.,]\d{2}-?"
_TAX = r"(?:\s+[A-Za-z0-9]{1,2})?(?:\s*\*+)?"
_ARTICLE_RE = re.compile(
    rf"^(?P<name>.*?[^\W\d_].*?)\s+(?P<price>{_PRICE})(?:\s*(?:€|eur\b))?(?P<tax>{_TAX})\s*$",
    re.IGNORECASE,
)
_AMOUNT_ONLY_RE = re.compile(rf"^(?:eur|€)?\s*(?P<price>{_PRICE})\s*(?:eur|€)?{_TAX}\s*$", re.I)
_WEIGHT_RE = re.compile(
    r"^(?P<w>\d{1,3}[.,]\d{1,3})\s*kg\s*[x×*@à]\s*(?P<u>\d{1,4}[.,]\d{2})\s*(?:eur|€)?"
    rf"\s*/\s*kg(?:\s+(?P<total>{_PRICE}){_TAX})?\s*$",
    re.IGNORECASE,
)
_QTY_RE = re.compile(
    r"^(?P<q>\d{1,3})\s*(?:stk\.?|st\.?|stück|stueck)?\s*[x×*]\s*(?P<u>\d{1,5}[.,]\d{2})"
    r"\s*(?:eur|€)?(?:\s*/\s*(?:stk|st|stück)\.?)?"
    rf"(?:\s+(?P<total>{_PRICE}){_TAX})?\s*$",
    re.IGNORECASE,
)
_QTY_REVERSED_RE = re.compile(
    r"^(?P<u>\d{1,5}[.,]\d{2})\s*(?:eur|€)?\s*[x×*]\s*(?P<q>\d{1,3})\s*(?:stk\.?|st\.?|stück)?"
    rf"(?:\s+(?P<total>{_PRICE}){_TAX})?\s*$",
    re.IGNORECASE,
)
# "JOGHURT 2 x 0,49" (quantity inside the article line, before its total)
_INLINE_QTY_RE = re.compile(
    r"^(?P<name>.*?\S)\s+(?:(?P<q>\d{1,3})\s*(?:stk\.?|st\.?)?\s*[x×*]\s*(?P<u>\d{1,5}[.,]\d{2})"
    r"|(?P<u2>\d{1,5}[.,]\d{2})\s*[x×*]\s*(?P<q2>\d{1,3}))\s*$",
    re.IGNORECASE,
)
_SEPARATOR_RE = re.compile(r"^[\s\-=*_#~.:+]+$")
_TOTAL_RE = re.compile(
    r"^\s*(?:summe|gesamt\w*|zu\s*zahlen|end(?:summe|betrag)|total|zahlbetrag|bar\s*summe)\b",
    re.IGNORECASE,
)
# an amount with a tax class ("1,99 B") is an article line, never the total ("TOTAL …"
# is also a yoghurt brand)
_TAXED_RE = re.compile(rf"{_PRICE}\s+[A-Za-z0-9]{{1,2}}\s*\**\s*$")
_SUBTOTAL_RE = re.compile(r"^\s*(?:zwischen\s*summe|zw\.?\s*summe|subtotal)", re.IGNORECASE)
# base price / info lines ("1 kg = 9,95", "(1 l = 3,17 €)", "Grundpreis …")
_INFO_RE = re.compile(
    r"^\(?\s*\d+(?:[.,]\d+)?\s*(?:kg|g|l|ml|stk|st|stück)\s*=|grundpreis|^\(.*\)$",
    re.IGNORECASE,
)
_PAYMENT_WORDS = (
    "bar",
    "barzahlung",
    "gegeben",
    "geg",
    "rueckgeld",
    "wechselgeld",
    "ec",
    "ec cash",
    "ec karte",
    "girocard",
    "kreditkarte",
    "karte",
    "kartenzahlung",
    "mastercard",
    "visa",
    "maestro",
    "v pay",
    "vpay",
    "apple pay",
    "google pay",
    "paypal",
    "zahlung",
    "zahlart",
    "mwst",
    "ust",
    "steuer",
    "netto",
    "brutto",
    "tse",
    "bon",
    "beleg",
    "kasse",
    "terminal",
    "trace",
    "genehmigung",
    "kundenbeleg",
    "posten",
    "anzahl",
)
# Pfand / Leergut lines ("EINWEG 0,25"; not "Einweghandschuhe")
_DEPOSIT_RE = re.compile(r"pfand|leergut|\bpfd\b|\b(?:einweg|mehrweg)\b", re.IGNORECASE)
_STORNO_RE = re.compile(r"\bstorno\b|\bstorniert\b|\bkorrektur\b", re.IGNORECASE)
_DISCOUNT_RE = re.compile(
    r"rabatt|preisvorteil|nachlass|sofortrabatt|aktion|coupon|gutschein|ersparnis|"
    r"vorteil|bonus|lidl ?plus|abzgl|abzüglich|reduziert|preisreduz",
    re.IGNORECASE,
)
_POSTCODE_RE = re.compile(r"\b(?P<zip>\d{5})\s+(?P<city>[A-ZÄÖÜa-zäöüß][^\d,;|]{1,40})")
_STREET_RE = re.compile(
    r"(str\.|straße|strasse|weg\b|platz\b|allee\b|ring\b|gasse\b|damm\b|ufer\b|chaussee|"
    r"markt\b|\b\d{1,4}\s*[a-z]?$)",
    re.IGNORECASE,
)
_DATE_RE = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})(?![\d.])")
_ISO_DATE_RE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")

# ----------------------------------------------------------------------------------
# Article names: abbreviations, pack sizes, words that name no product
# ----------------------------------------------------------------------------------

# folded receipt abbreviations -> folded words ("HACKFL.GEM." = Hackfleisch gemischt)
ABBREVIATIONS: dict[str, str] = {
    "gem": "gemischt",
    "gemi": "gemischt",
    "gemis": "gemischt",
    "hackfl": "hackfleisch",
    "hackfle": "hackfleisch",
    "hack": "hackfleisch",
    "scheib": "scheiben",
    "scheibe": "scheiben",
    "schb": "scheiben",
    "schei": "scheiben",
    "fr": "frische",
    "frisch": "frische",
    "vollm": "vollmilch",
    "kart": "kartoffeln",
    "kartof": "kartoffeln",
    "kartoff": "kartoffeln",
    "zwieb": "zwiebeln",
    "zwiebel": "zwiebeln",
    "tom": "tomaten",
    "rispentom": "rispentomaten",
    "jog": "joghurt",
    "jogh": "joghurt",
    "joghu": "joghurt",
    "frischk": "frischkaese",
    "schlags": "schlagsahne",
    "schlagsa": "schlagsahne",
    "mozz": "mozzarella",
    "mozzar": "mozzarella",
    "haehn": "haehnchen",
    "haehnch": "haehnchen",
    "haehnchenbr": "haehnchenbrust",
    "brustf": "brustfilet",
    "schw": "schweine",
    "spag": "spaghetti",
    "spagh": "spaghetti",
    "nud": "nudeln",
    "toastbr": "toastbrot",
    "broetch": "broetchen",
    "dtsch": "deutsche",
    "markenb": "markenbutter",
    "zuck": "zucker",
    "gurk": "gurke",
    "eisbergs": "eisbergsalat",
    "speiseq": "speisequark",
    "magerq": "magerquark",
    "kochschink": "kochschinken",
    "orangens": "orangensaft",
    "apfels": "apfelsaft",
    "mineralw": "mineralwasser",
    "toilettenp": "toilettenpapier",
    "kuechenr": "kuechenrolle",
    "spuelm": "spuelmittel",
    "waschm": "waschmittel",
    "zahnp": "zahnpasta",
    "eier10": "eier",
    # egg farming and canned tomatoes ("EIER BOD.10ER M", "JA! PASS.TOMATEN")
    "bod": "bodenhaltung",
    "bodenh": "bodenhaltung",
    "freil": "freiland",
    "freilandh": "freiland",
    "pass": "passierte",
    "passiert": "passierte",
    "geh": "gehackte",
}
# words of a receipt line that name no product (quality, packing, brand-like markers)
STOP_WORDS = {
    "bio",
    "jung",
    "mittelalt",
    "alt",
    "sb",
    "lose",
    "tk",
    "ca",
    "aktion",
    "angebot",
    "neu",
    "klassik",
    "classic",
    "klassisch",
    "original",
    "premium",
    "extra",
    "eur",
    "euro",
    "stk",
    "st",
    "stueck",
    "pack",
    "packung",
    "pkg",
    "pck",
    "fl",
    "flasche",
    "dose",
    "ds",
    "glas",
    "becher",
    "btl",
    "beutel",
    "schale",
    "netz",
    "gr",
    "kl",
    "x",
    "a",
    "b",
    "bodenhaltung",
    "freiland",
    "ja",  # REWE's brand "ja!"
}
_PACK_TOKEN_RE = re.compile(
    r"\b\d+\s*[x×]\s*\d+(?:[.,]\d+)?\s*(?:kg|g|gr|ml|l|ltr|cl)\b"
    r"|\b\d+(?:[.,]\d+)?\s*(?:kg|g|gr|ml|l|ltr|cl|er|stk|st|stück|rollen?|wl|%)(?![a-zäöüß])"
    r"|\b\d+(?:[.,]\d+)?\b",
    re.IGNORECASE,
)
_COUNT_PACK_RE = re.compile(r"\b(\d{1,3})\s*-?\s*(?:er|stk|st|stück|stueck)\b", re.IGNORECASE)


# ----------------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------------


def _amount(text: str | None) -> float | None:
    """'1,09' -> 1.09, '-0,30' / '0,30-' -> -0.30 (None if no number)."""
    if text is None:
        return None
    raw = str(text).strip()
    negative = raw.startswith("-") or raw.endswith("-")
    raw = raw.strip("-").strip()
    try:
        value = float(raw.replace(",", "."))
    except ValueError:
        return None
    return round(-value if negative else value, 2)


def _number(value: Any) -> float | None:
    """A number of an AI answer: 1.09, "1,09", "1.09 €" (None for anything else)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        match = re.search(r"-?\d+(?:[.,]\d+)?", value.replace(" ", ""))
        if not match:
            return None
        number = float(match.group().replace(",", "."))
    else:
        return None
    if number != number or abs(number) > MAX_PRICE * 10:  # NaN / absurd
        return None
    return number


def _close(a: float | None, b: float | None, tolerance: float = _TOLERANCE) -> bool:
    return a is not None and b is not None and abs(a - b) <= tolerance


def _clean_line(line: str) -> str:
    return re.sub(r"[ \t   ]+", " ", line.replace("€", " € ")).strip()


def _starts_with_word(folded: str, words: tuple[str, ...]) -> bool:
    padded = f"{folded} "
    return any(padded.startswith(f"{word} ") for word in words)


def parse_receipt_date(text: str | None, today: date | None = None) -> date | None:
    """The receipt date of a text: 'Datum: 07.11.2026', '07.11.26 10:15', '2026-11-07'.

    Lines with "Datum" first, else the first plausible date (not in the future, at most
    three years old when today is given). None if there is none.
    """
    if not text:
        return None
    lines = str(text).splitlines() or [str(text)]
    ordered = [line for line in lines if "datum" in line.lower()] + lines
    for line in ordered:
        for match in _DATE_RE.finditer(line):
            day, month, year = (int(g) for g in match.groups())
            if year < 100:
                year += 2000
            found = _valid_date(year, month, day, today)
            if found:
                return found
        for match in _ISO_DATE_RE.finditer(line):
            year, month, day = (int(g) for g in match.groups())
            found = _valid_date(year, month, day, today)
            if found:
                return found
    return None


def _valid_date(year: int, month: int, day: int, today: date | None) -> date | None:
    try:
        found = date(year, month, day)
    except ValueError:
        return None
    if today is not None and not (today - timedelta(days=3 * 366) <= found <= today):
        return None
    return found


def _address(lines: list[str]) -> tuple[str | None, str | None, str | None]:
    """(postcode, city, street) of the first 'PLZ Ort' line (street = the line before)."""
    for index, line in enumerate(lines):
        match = _POSTCODE_RE.search(line)
        if not match:
            continue
        city = match.group("city").strip(" .-")
        street = None
        before = line[: match.start()].strip(" ,;-")
        if before and _STREET_RE.search(before):
            street = before
        elif index and _STREET_RE.search(lines[index - 1]) and not _price_in(lines[index - 1]):
            street = lines[index - 1].strip()
        return match.group("zip"), city or None, street
    return None, None, None


def _price_in(line: str) -> bool:
    return bool(re.search(r"\d,\d{2}\b", line))


def _store_retailer(lines: list[str], postcode: str | None) -> tuple[str | None, str | None]:
    """(retailer, store line) named first in the given lines (a plain "Aldi" decided by the
    postcode)."""
    for line in lines:
        found = retailers_named(line)
        if not found:
            continue
        if found == {ALDI_SUED, ALDI_NORD}:
            return aldi_for_postcode(postcode) or ALDI_SUED, line.strip()
        if len(found) == 1:
            return next(iter(found)), line.strip()
        # several chains in one line: the one named first
        folded = fold(line)
        best = min(
            found,
            key=lambda rid: min(
                (folded.find(fold(n)) for n in (rid, retailer_name(rid)) if fold(n) in folded),
                default=999,
            ),
        )
        return best, line.strip()
    return None, None


# ----------------------------------------------------------------------------------
# Text parser
# ----------------------------------------------------------------------------------


_NO_NAME_RE = re.compile(
    r"^(?:tel|fax|uid|ust|st\.?-?nr|steuer|www|http|e-?mail|öffnungs|oeffnungs|mo\b|eur\b|€)",
    re.IGNORECASE,
)


def _name_like(line: str) -> bool:
    """True if a line without price may be an article name (not "EUR", a phone number or
    an address)."""
    return (
        bool(re.search(r"[^\W\d_]{3,}", line))
        and not _NO_NAME_RE.match(line.strip())
        and not _POSTCODE_RE.search(line)
    )


def _new_item(line: str, name: str, price: float, confidence: float) -> dict[str, Any]:
    return {
        "line": line,
        "name": name.strip(" :-*"),
        "quantity": 1.0,
        "weight": None,
        "unit_price": price,
        "price": price,
        "discount": 0.0,
        "ignored": False,
        "kind": "article",
        "confidence": confidence,
    }


def _attach_quantity(
    item: dict[str, Any], quantity: float, unit: float, line: str | None = None
) -> bool:
    """Apply a "2 x 0,99" line to an article; True if the line total fits it."""
    item["quantity"] = quantity
    item["unit_price"] = unit
    if line:
        item["line"] = f"{item['line']}\n{line}"
    fits = _close(quantity * unit, item["price"] + item["discount"])
    if not fits:
        item["confidence"] = min(item["confidence"], 0.6)
    return fits


def _attach_weight(
    item: dict[str, Any], weight: float, unit: float, line: str | None = None
) -> bool:
    """Apply a "0,512 kg x 7,99 EUR/kg" line to an article."""
    item["weight"] = weight
    item["quantity"] = 1.0
    item["unit_price"] = unit
    if line:
        item["line"] = f"{item['line']}\n{line}"
    fits = _close(weight * unit, item["price"] + item["discount"], 0.02)
    if not fits:
        item["confidence"] = min(item["confidence"], 0.6)
    return fits


_COLUMN_HEAD_RE = re.compile(r"^(?:eur|€|euro|preis|betrag)$", re.IGNORECASE)
# a phone's text recognition of a receipt photo splits wide rows: the names of the
# articles first, then their prices (confidence of such pairs)
COLUMN_CONFIDENCE = 0.6
SPLIT_CONFIDENCE = 0.8


def _total_label(line: str) -> bool:
    """A total line without its amount ("SUMME EUR")."""
    return (
        bool(_TOTAL_RE.match(line.lower()))
        and not _TAXED_RE.search(line)
        and not re.search(_PRICE, line)
    )


def _column_name(line: str) -> bool:
    """A line that may be an article name of a split row (no price, no quantity line)."""
    return (
        _name_like(line)
        and not _price_in(line)
        and not _total_label(line)
        and not _INFO_RE.search(line)
        and not _QTY_RE.match(line)
        and not _WEIGHT_RE.match(line)
        and not _starts_with_word(fold(line), _PAYMENT_WORDS)
    )


def _join_columns(lines: list[str]) -> tuple[list[str], dict[int, tuple[str, float]]]:
    """Pair the names and prices of rows a text recognition split into two blocks
    ("H-MILCH" "BUTTER" … then "1,09 B" "2,39 B" …): n name lines (a column head "EUR"
    between them is skipped; a total label "SUMME EUR" may close the names) followed by
    as many amount lines. Returns the lines with each pair as one row and {row index:
    (the two original lines, confidence)}."""
    out: list[str] = []
    joined: dict[int, tuple[str, float]] = {}
    index = 0
    while index < len(lines):
        if not _AMOUNT_ONLY_RE.match(lines[index]):
            out.append(lines[index])
            index += 1
            continue
        end = index
        while end < len(lines) and _AMOUNT_ONLY_RE.match(lines[end]):
            end += 1
        amounts = lines[index:end]
        # the lines before the amounts (already copied to out): column heads, a total
        # label, then the names
        back = len(out)
        while back and _COLUMN_HEAD_RE.match(out[back - 1]):
            back -= 1
        total_label = None
        if back and _total_label(out[back - 1]):
            total_label = back - 1
            back -= 1
        count = len(amounts) - (1 if total_label is not None else 0)
        names = out[back - count : back] if count >= 2 and back >= count else []
        if len(names) != count or not all(_column_name(n) for n in names):
            out.extend(amounts)
            index = end
            continue
        start = back - count
        rest = out[back:]  # column heads and the total label
        del out[start:]
        for name, amount in zip(names, amounts, strict=False):
            joined[len(out)] = (f"{name}\n{amount}", COLUMN_CONFIDENCE)
            out.append(f"{name} {amount}")
        for line in rest:
            out.append(f"{line} {amounts[-1]}" if _total_label(line) else line)
        index = end
    return out, joined


def parse_receipt_text(text: str, today: date | None = None) -> dict[str, Any]:
    """Parse the text of a German receipt (REWE, EDEKA, Lidl, ALDI, Netto, Norma, Penny,
    Kaufland, Rossmann, dm …) without any AI.

    Article lines end in a price and an optional tax class ("BUTTER MILSANI 250G 1,15 A");
    a quantity line ("2 x 0,99", "2 Stk x 0,99") or weight line ("0,512 kg x 7,99 EUR/kg")
    belongs to the article before it (or to the next one when only that fits the
    arithmetic; with a name-only line before it, it carries the total); a name-only line
    followed by an amount line ("H-MILCH 1,5%" / "1,09 B") is one article, also a block of
    names followed by a block of as many amounts (rows a phone's text recognition split
    into two columns; lower confidence); deposit / empties
    lines (Pfand, Leergut) are kept as ignored lines; discounts ("Rabatt -0,30",
    "Preisvorteil") reduce the article before them; "SUMME" / "zu zahlen" is the total,
    payment lines and everything after the total are no articles. The header (lines before
    the first article) gives the store and its address (postcode).

    Returns {store, retailer, postcode, city, street, date, total, sum, checked, items:
    [{line, name, quantity, weight, unit_price, price, discount, ignored, kind
    (article|deposit|discount), confidence}], unparsed: [line], source: "text"}.
    """
    raw_lines = str(text or "")[:MAX_TEXT_CHARS].splitlines()
    lines, joined = _join_columns([c for c in (_clean_line(line) for line in raw_lines) if c])
    header: list[str] = []
    footer: list[str] = []
    items: list[dict[str, Any]] = []
    unparsed: list[str] = []
    total: float | None = None
    after_total = False
    expect_total = False
    header_last = False  # the line before was a header line
    pending: str | None = None  # a name-only line (its price follows on the next line)
    # a measure line that fitted no article yet: (kind q|w, value, unit price, line)
    orphan: tuple[str, float, float, str] | None = None

    def last_article() -> dict[str, Any] | None:
        for item in reversed(items):
            if item["kind"] == "article" and not item["ignored"]:
                return item
        return None

    def attach(kind: str, item: dict[str, Any], value: float, unit: float, line: str | None):
        if kind == "q":
            _attach_quantity(item, value, unit, line)
        else:
            _attach_weight(item, value, unit, line)

    def add_measure(kind: str, value: float, unit: float, line_total: float | None, line: str):
        nonlocal pending, orphan
        if pending is None and header_last and header and _name_like(header[-1]):
            pending = header.pop()  # the first article is a name line + this line
        if pending is not None:
            price = line_total if line_total is not None else round(value * unit, 2)
            item = _new_item(f"{pending}\n{line}", pending, price, 0.95 if line_total else 0.75)
            attach(kind, item, value, unit, None)
            items.append(item)
            pending = None
            return
        previous = last_article()
        fits = previous is not None and previous["quantity"] == 1 and previous["weight"] is None
        if fits and _close(value * unit, previous["price"] + previous["discount"], 0.02):
            attach(kind, previous, value, unit, line)
            return
        if line_total is not None:
            # "2 x 0,99   1,98" without a name line: an article without a name
            item = _new_item(line, line, line_total, 0.4)
            attach(kind, item, value, unit, None)
            items.append(item)
            return
        if orphan is not None and previous is not None:
            attach(orphan[0], previous, orphan[1], orphan[2], orphan[3])
        orphan = (kind, value, unit, line)

    for index, line in enumerate(lines):
        if not line:
            continue
        low = line.lower()
        split = joined.get(index)  # (original lines, confidence) of a split row
        was_header, header_last = header_last, False
        if after_total:
            footer.append(line)
            continue
        if _SEPARATOR_RE.match(line):
            header_last = was_header
            continue
        if expect_total:
            expect_total = False
            if match := _AMOUNT_ONLY_RE.match(line):
                total = _amount(match.group("price"))
                after_total = True
                continue
        if _SUBTOTAL_RE.match(low):
            continue
        if _TOTAL_RE.match(low) and not _TAXED_RE.search(line):
            amounts = re.findall(_PRICE, line)
            if amounts:
                total = _amount(amounts[-1])
                after_total = True
            else:
                expect_total = True
            continue
        header_last = was_header
        measure: tuple[str, float, float, float | None] | None = None
        if match := _WEIGHT_RE.match(line):
            measure = (
                "w",
                float(match.group("w").replace(",", ".")),
                float(match.group("u").replace(",", ".")),
                _amount(match.group("total")),
            )
        elif match := _QTY_RE.match(line) or _QTY_REVERSED_RE.match(line):
            quantity = float(match.group("q"))
            if 0 < quantity <= MAX_QUANTITY:
                measure = (
                    "q",
                    quantity,
                    float(match.group("u").replace(",", ".")),
                    _amount(match.group("total")),
                )
        if measure is not None:
            add_measure(*measure, line)
            header_last = False
            continue
        header_last = False
        if _INFO_RE.search(line):
            continue
        if _AMOUNT_ONLY_RE.match(line):
            if pending is None and was_header and header and _name_like(header[-1]):
                pending = header.pop()  # the first article: a name line + this line
            if pending is not None:
                # the price of the name line before ("H-MILCH 1,5%" / "1,09 B")
                split = (f"{pending}\n{line}", SPLIT_CONFIDENCE)
                line = f"{pending} {line}"
                pending = None
        match = _ARTICLE_RE.match(line)
        if match is None:
            if items or pending is not None or orphan is not None:
                if pending is not None:
                    unparsed.append(pending)
                pending = line if _name_like(line) else None
            else:
                header.append(line)
                header_last = True
            continue
        name = match.group("name").strip()
        price = _amount(match.group("price"))
        if price is None or abs(price) > MAX_PRICE:
            continue
        if _starts_with_word(fold(line), _PAYMENT_WORDS):
            continue
        if pending is not None:
            unparsed.append(pending)
            pending = None
        confidence = 0.95 if match.group("tax").strip(" *") else 0.85
        if split is not None:
            line, confidence = split[0], min(confidence, split[1])
        if _DEPOSIT_RE.search(name):
            item = _new_item(line, name, price, confidence)
            item.update({"ignored": True, "kind": "deposit"})
            items.append(item)
            continue
        if price < 0:
            if _STORNO_RE.search(name):
                for previous in reversed(items):
                    if (
                        previous["kind"] == "article"
                        and not previous["ignored"]
                        and _close(previous["price"], -price)
                    ):
                        previous.update({"ignored": True, "kind": "storno"})
                        break
                item = _new_item(line, name, price, confidence)
                item.update({"ignored": True, "kind": "storno"})
                items.append(item)
                continue
            previous = last_article()
            if previous is not None and -price <= previous["price"] + 0.001:
                previous["discount"] = round(previous["discount"] - price, 2)
                previous["price"] = round(previous["price"] + price, 2)
                previous["line"] = f"{previous['line']}\n{line}"
                if not _DISCOUNT_RE.search(name):
                    previous["confidence"] = min(previous["confidence"], 0.7)
                continue
            item = _new_item(line, name, price, 0.5)
            item.update({"ignored": True, "kind": "discount"})
            items.append(item)
            continue
        item = _new_item(line, name, price, confidence)
        if inline := _INLINE_QTY_RE.match(name):
            item["name"] = inline.group("name").strip(" :-*")
            _attach_quantity(
                item,
                float(inline.group("q") or inline.group("q2")),
                float((inline.group("u") or inline.group("u2")).replace(",", ".")),
            )
        if orphan is not None:
            kind, value, unit, measure_line = orphan
            orphan = None
            if item["quantity"] == 1 and _close(value * unit, price, 0.02):
                # a measure line before its article ("2 x 0,69" above "SPAGHETTI 1,38")
                attach(kind, item, value, unit, None)
                item["line"] = f"{measure_line}\n{line}"
            elif (previous := last_article()) is not None:
                attach(kind, previous, value, unit, measure_line)  # fits nothing: the one before
        items.append(item)
        if len(items) >= MAX_ITEMS:
            break
    if pending is not None:
        unparsed.append(pending)
    if orphan is not None and (previous := last_article()) is not None:
        attach(orphan[0], previous, orphan[1], orphan[2], orphan[3])

    postcode, city, street = _address(header)
    if postcode is None:
        postcode, city, street = _address([line for line in footer if not _price_in(line)])
    retailer, store = _store_retailer(header, postcode)
    if retailer is None:
        # "Vielen Dank für Ihren Einkauf bei …" – not the tax table ("Netto 12,34")
        retailer, store = _store_retailer(
            [line for line in footer if not re.search(r"\d", line)], postcode
        )
    total_sum = round(sum(i["price"] for i in items if i["kind"] != "storno"), 2)
    return {
        "source": SOURCE_TEXT,
        "store": store,
        "retailer": retailer,
        "postcode": postcode,
        "city": city,
        "street": street,
        "date": (d.isoformat() if (d := parse_receipt_date(text, today)) else None),
        "total": total,
        "sum": total_sum,
        "checked": total is not None and _close(total, total_sum, 0.011),
        "items": items,
        "unparsed": unparsed[:30],
    }


# ----------------------------------------------------------------------------------
# AI answers
# ----------------------------------------------------------------------------------


def parse_ai_receipt(data: Any, today: date | None = None) -> dict[str, Any]:
    """The answer of the AI Task entity ({"data": text | object}) as a parsed receipt (the
    format of parse_receipt_text, source "photo"). Raises ValueError for garbage."""
    value = data.get("data", data) if isinstance(data, dict) and "data" in data else data
    if isinstance(value, str):
        value = extract_json(value)
    if isinstance(value, list):
        value = {"items": value}
    if not isinstance(value, dict):
        raise ValueError("no object")
    raw_items = value.get("items") or value.get("artikel") or value.get("positions")
    if not isinstance(raw_items, list):
        raise ValueError("no items")
    items: list[dict[str, Any]] = []
    for raw in raw_items[:MAX_ITEMS]:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or raw.get("text") or raw.get("artikel") or "").strip()
        name = re.sub(r"\s+", " ", name)[:120]
        quantity = _number(raw.get("quantity", raw.get("menge")))
        unit = _number(raw.get("unit_price", raw.get("einzelpreis")))
        line_total = _number(raw.get("total", raw.get("price", raw.get("preis"))))
        if not name or not re.search(r"[^\W\d_]", name):
            continue
        if quantity is not None and not 0 < abs(quantity) <= MAX_QUANTITY:
            quantity = None
        if line_total is None and unit is not None:
            line_total = round(unit * (quantity or 1), 2)
        if line_total is None or abs(line_total) > MAX_PRICE:
            continue
        weighed = quantity is not None and not float(quantity).is_integer()
        weighed = weighed or str(raw.get("unit") or "").strip().lower() == "kg"
        item = _new_item(name, name, round(line_total, 2), 0.8)
        if weighed and quantity and unit:
            item.update({"weight": abs(quantity), "unit_price": unit})
            if _close(abs(quantity) * unit, line_total, 0.02):
                item["confidence"] = 0.9
        elif quantity and quantity > 1 and unit is not None:
            item.update({"quantity": float(quantity), "unit_price": unit})
            item["confidence"] = 0.9 if _close(quantity * unit, line_total, 0.02) else 0.6
        elif quantity and quantity > 1:
            item.update({"quantity": float(quantity), "unit_price": line_total / quantity})
        if _DEPOSIT_RE.search(name):
            item.update({"ignored": True, "kind": "deposit"})
        elif line_total < 0:
            previous = next(
                (i for i in reversed(items) if i["kind"] == "article" and not i["ignored"]),
                None,
            )
            if previous is not None and -line_total <= previous["price"]:
                previous["discount"] = round(previous["discount"] - line_total, 2)
                previous["price"] = round(previous["price"] + line_total, 2)
                previous["line"] = f"{previous['line']}\n{name} {line_total:.2f}"
                continue
            item.update({"ignored": True, "kind": "discount"})
        items.append(item)
    if not any(i["kind"] == "article" for i in items):
        raise ValueError("no articles")
    address = str(value.get("address") or value.get("adresse") or "")
    store = str(value.get("store") or value.get("laden") or "").strip() or None
    postcode, city, street = _address([address.replace("\n", ", ")]) if address else (None,) * 3
    if street is None and address:
        street = address.split(",")[0].strip() or None
    retailer, _ = _store_retailer([store or "", address], postcode)
    total = _number(value.get("total", value.get("summe")))
    total_sum = round(sum(i["price"] for i in items), 2)
    day = parse_receipt_date(str(value.get("date") or value.get("datum") or ""), today)
    return {
        "source": SOURCE_PHOTO,
        "store": store,
        "retailer": retailer,
        "postcode": postcode,
        "city": city,
        "street": street,
        "date": day.isoformat() if day else None,
        "total": round(total, 2) if total is not None and 0 <= total <= MAX_PRICE else None,
        "sum": total_sum,
        "checked": total is not None and _close(total, total_sum, 0.011),
        "items": items,
        "unparsed": [],
    }


# ----------------------------------------------------------------------------------
# Mapping receipt names to ingredient keys
# ----------------------------------------------------------------------------------


def line_pack(name: str) -> tuple[float, str] | None:
    """Pack size printed in an article name: '250G', '1L', '6X1,5L', '10ER', '8 Rollen'."""
    text = str(name or "")
    if size := parse_pack_text(text):
        return size
    if match := _COUNT_PACK_RE.search(text):
        count = float(match.group(1))
        return (count, "Stück") if 1 < count <= 100 else None
    return None


# marks of name tokens: completed from a known word (a unique completion of 5+ letters,
# "WEIZENM." -> Weizenmehl), guessed (a completion of a short prefix, "BOD." could be
# anything), truncated and not understood
_COMPLETED = "completed"
_GUESSED = "guessed"
_TRUNCATED = "truncated"
# the shortest prefix whose unique completion is trusted
MIN_COMPLETION = 5
# marks of a word before a hit that make the hit unsure (the word may change the product)
_UNSURE_MARKS = (_COMPLETED, _GUESSED, _TRUNCATED)


def _marked_tokens(
    name: str, vocabulary: dict[str, str] | None = None, complete: bool = True
) -> list[tuple[str, str]]:
    """name_tokens() with a mark per token: "" (as printed, a known word or an
    abbreviation), "completed" (a truncated word of 5+ letters completed from the
    vocabulary), "guessed" (a shorter one or a stop word completed) or "truncated" (a
    truncated word that was not understood or not completed)."""
    text = _PACK_TOKEN_RE.sub(" ", str(name or ""))
    tokens: list[tuple[str, str]] = []
    for raw in re.split(r"\s+", text.replace(".", ". ")):
        truncated = raw.endswith(".")
        for word in fold(raw).split():
            if word.isdigit() or len(word) == 0:
                continue
            mark = ""
            if word in ABBREVIATIONS:
                word = ABBREVIATIONS[word]
            elif truncated and len(word) >= 3 and not (vocabulary and word in vocabulary):
                completion = vocabulary.get(f"{word}*") if vocabulary and complete else None
                if completion:
                    # a word only known from an estimate's alias may be another product
                    # ("BUTTERSCHM." is Butterschmalz, an alias of Butter): a suggestion
                    sure = (
                        len(word) >= MIN_COMPLETION
                        and word not in STOP_WORDS
                        and f"{completion}~" not in vocabulary
                    )
                    word, mark = completion, _COMPLETED if sure else _GUESSED
                else:
                    mark = _TRUNCATED
            for part in word.split():
                if part not in STOP_WORDS:
                    tokens.append((part, mark))
    return tokens


def name_tokens(name: str, vocabulary: dict[str, str] | None = None) -> list[str]:
    """Folded product words of a receipt name: pack sizes, numbers and stop words removed,
    abbreviations expanded ("HACKFL.GEM." -> hackfleisch gemischt, "SCHEIB" -> scheiben),
    a truncated word ("SPEISEQ.") completed when exactly one known word starts with it."""
    return [token for token, _ in _marked_tokens(name, vocabulary)]


def _vocabulary(names: list[str], weak: list[str] | tuple[str, ...] = ()) -> dict[str, str]:
    """{word: word} of known product words plus {prefix*: word} for prefixes that only one
    word starts with (completes truncated receipt words). Words only named by the weak
    names (the aliases of the estimates, which group other products under one price:
    Butterschmalz under Butter, Räucherlachs under Lachsfilet) are marked {word~: word}."""
    strong = {w for name in names for w in fold(name).split() if len(w) >= 4}
    words = strong | {w for name in weak for w in fold(name).split() if len(w) >= 4}
    vocabulary = {w: w for w in words}
    for word in words - strong:
        vocabulary[f"{word}~"] = word
    prefixes: dict[str, set[str]] = {}
    for word in words:
        for end in range(3, len(word)):
            prefixes.setdefault(word[:end], set()).add(word)
    for prefix, found in prefixes.items():
        if len(found) == 1 and prefix not in vocabulary:
            vocabulary[f"{prefix}*"] = next(iter(found))
    return vocabulary


class ReceiptMapper:
    """Maps receipt article names of one retailer to ingredient keys.

    Sources, most trusted first: names the user assigned on an earlier receipt (aliases),
    the retailer's own and learned store prices, own general prices, recently added
    articles, the bundled estimates (names and aliases). A name is tried as a whole, then
    by its longest word groups (joined, also as one compound word: "ERDNUSS BUTTER" ->
    Erdnussbutter), leftmost first – receipts name the product first ("BUTTER MILSANI"),
    a brand or quality word around it is skipped. A part that names another product
    ("SCHOKO EIER" is no egg, "Kokosmilch" no milk) does not count.
    """

    def __init__(self, manager: EssensplanerManager, retailer: str | None) -> None:
        """Index the known names of the retailer."""
        self.manager = manager
        self.retailer = retailer
        self.names: dict[str, tuple[str, str, str]] = {}  # phrase -> (key, product, source)
        defaults = manager.defaults_index()
        all_names: list[str] = []
        alias_names: list[str] = []
        for entry in defaults.entries():
            key = ingredient_key(entry.name)
            self._add(entry.name, key, entry.name, "estimate")
            all_names.append(entry.name)
            for name in entry.aliases:
                self._add(name, key, entry.name, "estimate")
                alias_names.append(name)
        for article in reversed(manager.article_history[:200]):
            key = str(article.get("key") or "")
            summary = str(article.get("summary") or "")
            if key and summary and len(summary) <= 60:
                self._add(summary, key, self._product(key, summary), "history")
                all_names.append(summary)
        buckets: list[tuple[dict[str, Any], str]] = [(manager.prices_user, "own")]
        if retailer:
            for learned in manager.fresh_store_prices(retailer).values():
                buckets.append((learned, "store"))
            buckets.append((manager.store_prices_user.get(retailer, {}), "store"))
        for bucket, source in buckets:
            for key, item in bucket.items():
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or key)
                product = self._product(key, name)
                self._add(key, key, product, source)
                if len(name) <= 40:
                    self._add(name, key, product, source)
                all_names.append(name)
        self.vocabulary = _vocabulary(all_names, alias_names)
        self.aliases = manager.receipts.aliases_for(retailer)
        self._matcher: KeyMatcher | None = None

    def _product(self, key: str, name: str) -> str:
        """Display name of a key: the bundled product's name, else the stored name."""
        default = self.manager.defaults_index().get(key)
        return default.name if default is not None else name

    def _add(self, name: str, key: str, product: str, source: str) -> None:
        for phrase in {fold(name), lookup_keys(name)[0], ingredient_key(name)}:
            if phrase:
                self.names[phrase] = (key, product, source)
                self.names.setdefault(phrase.replace(" ", ""), (key, product, source))

    def _lookup(self, words: list[str]) -> tuple[str, str, str] | None:
        joined = " ".join(words)
        forms = [
            joined,
            " ".join(_singular(w) for w in words),
            ingredient_key(joined),
            "".join(words),
            "".join(_singular(w) for w in words),
        ]
        for form in forms:
            if form and (found := self.names.get(form)):
                return found
        return None

    def map(self, name: str) -> dict[str, Any]:
        """{key, product, match (alias|store|own|history|estimate|fuzzy), confidence} of a
        receipt name (key None if unknown)."""
        none = {"key": None, "product": None, "match": None, "confidence": 0.0}
        alias = self.aliases.get(_alias_name(name))
        if alias:
            return {
                "key": alias["key"],
                "product": alias.get("product") or alias["key"],
                "match": "alias",
                "confidence": 0.98,
            }
        # the words as printed first; a truncated word completed from the known words
        # ("WEIZENM." -> Weizenmehl) only when they name nothing for sure: a guessed word
        # must not outvote a recognised one ("EIER BOD.10ER M"), a completion may beat a
        # suggestion ("SONNENBL.OEL" is Sonnenblumenöl, no Rapsöl)
        plain = _marked_tokens(name, self.vocabulary, complete=False)
        if not plain:
            return none
        found = self._map_tokens(plain)
        marked = plain
        if found is None or found["confidence"] < MIN_CONFIDENCE:
            completed = _marked_tokens(name, self.vocabulary)
            if completed != plain:
                better = self._map_tokens(completed)
                if found is None:
                    marked = completed
                if better is not None and (
                    found is None or better["confidence"] > found["confidence"]
                ):
                    found = better
        if found is None:
            found = self._fuzzy(" ".join(token for token, _ in marked))
        return found or none

    def _map_tokens(self, marked: list[tuple[str, str]]) -> dict[str, Any] | None:
        """The exact match of the longest word group (see map())."""
        tokens = [token for token, _ in marked]
        cleaned = " ".join(tokens)
        count = len(tokens)
        for size in range(min(count, 4), 0, -1):
            hits: list[tuple[int, tuple[str, str, str]]] = []
            for start in range(0, count - size + 1):
                words = tokens[start : start + size]
                if size == 1 and len(words[0]) < 3 and count > 1:
                    continue
                found = self._lookup(words)
                if found is None:
                    continue
                if size < count and not self._part_counts(cleaned, " ".join(words), found):
                    continue
                hits.append((start, found))
            if not hits:
                continue
            start, (key, product, source) = hits[0]
            # the whole name; else its first words (the product) or a later part
            confidence = 0.95 if size == count else 0.8 if start == 0 else 0.65
            if len({h[1][0] for h in hits}) > 1:
                confidence -= 0.1
            marks = [mark for _, mark in marked[start : start + size]]
            if _GUESSED in marks or (start and marked[start - 1][1] in _UNSURE_MARKS):
                # a guessed word, or a word not understood right before the hit
                # ("GESCH.TOMATEN" may be no fresh tomatoes): only a suggestion
                confidence = min(confidence, MIN_CONFIDENCE - 0.05)
            return {"key": key, "product": product, "match": source, "confidence": confidence}
        return None

    def _part_counts(self, cleaned: str, part: str, found: tuple[str, str, str]) -> bool:
        """True if a word group of a longer name may stand for the whole name."""
        key, product, _ = found
        if short_key(key) and not offer_matches(cleaned, key):
            return False  # "Schoko Eier"
        if names_other_compound(cleaned, ingredient_key(part)):
            return False
        manager = self.manager
        if manager.names_other_product(cleaned, key):
            return False
        whole = guess_category(cleaned)
        return whole in ("Sonstiges", guess_category(product))

    def _fuzzy(self, cleaned: str) -> dict[str, Any] | None:
        """A known key whose words are compound parts of the name ("Rinderhackfleisch"):
        the longest one that is no other product."""
        if self._matcher is None:
            self._matcher = KeyMatcher(k for k, _, _ in self.names.values() if len(k) >= 4)
        best: tuple[int, str] | None = None
        for key in self._matcher.match(cleaned, cleaned):
            if self.manager.names_other_product(cleaned, key) or names_other_compound(cleaned, key):
                continue
            if best is None or len(key) > best[0]:
                best = (len(key), key)
        if best is None:
            return None
        key, product, _ = self.names[best[1]]
        if guess_category(cleaned) not in ("Sonstiges", guess_category(product)):
            return None
        return {"key": key, "product": product, "match": "fuzzy", "confidence": 0.5}


def _alias_name(name: str) -> str:
    """The remembered form of a receipt name (folded, numbers and pack sizes kept)."""
    return fold(name)[:80]


# ----------------------------------------------------------------------------------
# Branch detection and the proposal
# ----------------------------------------------------------------------------------


def detect_branch(
    manager: EssensplanerManager,
    retailer: str | None,
    postcode: str | None,
    street: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    """(branch, how: postcode|retailer|None) of a receipt header.

    The chain's branch at the receipt's postcode (several: the one in the printed street);
    without a chain the only branch at the postcode; without a postcode the only selected
    branch of the chain.
    """
    branches = [*manager.selected_branches()]
    branches += [b for b in manager.branches if b not in branches]

    def same_chain(branch: dict[str, Any]) -> bool:
        return retailer_matches(branch.get("retailer"), retailer)

    if postcode:
        here = [b for b in branches if b.get("postcode") == postcode]
        chain = [b for b in here if same_chain(b)] if retailer else here
        if len(chain) > 1 and street:
            words = [w for w in fold(street).split() if len(w) >= 3 and not w.isdigit()]
            numbers = re.findall(r"\d+", street)
            scored = [
                (
                    sum(w in fold(b.get("street") or "") for w in words)
                    + sum(n in re.findall(r"\d+", str(b.get("street") or "")) for n in numbers),
                    b,
                )
                for b in chain
            ]
            best = max(s for s, _ in scored)
            if best > 0:
                chain = [b for s, b in scored if s == best]
        if chain and (retailer or len(chain) == 1):
            return chain[0], "postcode"
    if retailer:
        chain = [b for b in manager.selected_branches() if same_chain(b)]
        if len(chain) == 1:
            return chain[0], "retailer"
    return None, None


def _pack_for(
    manager: EssensplanerManager,
    key: str | None,
    retailer: str | None,
    name: str,
) -> tuple[float, str, str]:
    """(amount, unit, source line|store|estimate|none) of one piece of an article."""
    if size := line_pack(name):
        return size[0], size[1], "line"
    if key and retailer:
        for bucket in (
            manager.store_prices_user.get(retailer, {}),
            *manager.fresh_store_prices(retailer).values(),
        ):
            item = bucket.get(key)
            if isinstance(item, dict) and (entry := make_entry(item, "store")) is not None:
                return entry.amount, entry.unit, "store"
    if key and (default := manager.defaults_index().get(key)) is not None:
        return default.amount, default.unit, "estimate"
    return 1.0, "Stück", "none"


def own_price(item: dict[str, Any]) -> tuple[float, float, str] | None:
    """(price, amount, unit) an article line gives as the store's regular price: the price
    of one piece before a discount (a coupon or app price is no regular price), a weighed
    article per kg."""
    try:
        price = float(item.get("price") or 0) + float(item.get("discount") or 0)
        quantity = float(item.get("quantity") or 1)
    except (TypeError, ValueError):
        return None
    if price <= 0 or quantity <= 0:
        return None
    weight = item.get("weight")
    unit_value = item.get("unit_price")
    if weight:
        try:
            weight_kg = float(weight)
        except (TypeError, ValueError):
            weight_kg = 0
        if weight_kg > 0:
            per_kg = round(price / weight_kg, 2)
            if unit_value and _close(float(unit_value), per_kg, 0.05):
                per_kg = round(float(unit_value), 2)
            return per_kg, 1000.0, "g"
    try:
        amount = float(item.get("amount") or 1)
    except (TypeError, ValueError):
        amount = 1.0
    return (
        round(price / quantity, 2),
        amount if amount > 0 else 1.0,
        str(item.get("unit") or "Stück"),
    )


# the receipt's price is the offer's price (cent rounding of a price per piece)
OFFER_TOLERANCE = 0.01
# words of an article name that tell nothing about which product it is
_PLAIN_WORDS = {
    "frisch",
    "frische",
    "frischer",
    "deutsch",
    "deutsche",
    "deutscher",
    "echt",
    "echte",
    "fein",
    "feine",
    "feiner",
    "natur",
    "marken",
    "markenqualitaet",
    "qualitaet",
    "sorte",
    "sorten",
    "versch",
    "verschiedene",
}


def _product_words(text: str, key: str) -> set[str]:
    """The words of an article name that tell one product of a key from another (brand,
    variety), without the key itself, plain and pack words ('Kerrygold' of 'Kerrygold
    Irische Butter'; nothing of 'Deutsche Markenbutter')."""
    key_words = [w for w in key.split() if len(w) >= 3]
    words: set[str] = set()
    for token in name_tokens(text):
        if len(token) < 3 or token.isdigit() or token in _PLAIN_WORDS:
            continue
        if any(w in token or token in w for w in key_words):
            continue
        words.add(token)
    return words


def _same_article(offer: dict[str, Any], key: str, name: str) -> bool:
    """True if a receipt line may be the offer's article: when both names tell which
    product of the key it is (a brand, a variety), they share such a word ('KERRYGOLD
    IRISCHE BUTTER' is the offer 'Kerrygold Butter', 'GUT LAND DEUTSCHE MARKENBUTTER' is
    not); a truncated receipt word counts ('KERRYG.')."""
    offer_name = " ".join(
        str(offer.get(field) or "") for field in ("brand", "product") if offer.get(field)
    ) or str(offer.get("title") or "")
    wanted = _product_words(offer_name, key)
    printed = _product_words(name, key)
    if not wanted or not printed:
        return True  # "BUTTER" or the offer "Butter": the key and the price decide
    return any(
        word == token
        or (len(token) >= 4 and word.startswith(token))
        or (len(word) >= 4 and token.startswith(word))
        for word in wanted
        for token in printed
    )


def receipt_offer(
    manager: EssensplanerManager,
    retailer: str | None,
    key: str | None,
    day: date,
    item: dict[str, Any],
) -> dict[str, Any] | None:
    """The leaflet offer of the receipt's chain for this article that was valid on the
    receipt's day at the line's price (an offer price is no regular price), else None:
    the same key, the same price (to the cent) and, when both names tell it, the same
    brand or variety (see _same_article()). Weighed articles and lines the user marked
    as regular price ("regular") are not checked."""
    if not (retailer and key) or item.get("weight") or item.get("regular"):
        return None
    try:
        price = (float(item.get("price") or 0) + float(item.get("discount") or 0)) / float(
            item.get("quantity") or 1
        )
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    if price <= 0:
        return None
    text = day.isoformat()
    candidates = [*manager.offers, *manager.catalog.current_offers(day)]
    for offer in candidates:
        if not isinstance(offer, dict) or offer.get("online_only"):
            continue
        try:
            offer_price = float(offer.get("price"))
        except (TypeError, ValueError):
            continue
        old = offer.get("old_price") or offer.get("regular_price")
        if (
            abs(offer_price - price) > OFFER_TOLERANCE + 1e-6
            or (old and float(old) <= offer_price)  # no price cut
            or str(offer.get("valid_from") or "")[:10] > text
            or str(offer.get("valid_to") or "9999")[:10] < text
            or not retailer_matches(manager.offer_retailer(offer), retailer)
        ):
            continue
        keys = offer.get("keys") or [ingredient_key(str(offer.get("product") or ""))]
        if key in keys and _same_article(offer, key, str(item.get("name") or "")):
            return offer
    return None


def _plausibility(manager: EssensplanerManager, key: str, price: tuple[float, float, str]) -> bool:
    """False if the price per base unit is far off the estimate (pack size wrong?)."""
    default = manager.defaults_index().get(key)
    if default is None:
        return True
    entry = make_entry({"name": key, "price": price[0], "amount": price[1], "unit": price[2]}, "x")
    if entry is None:
        return True
    mine, reference = unit_price(entry), unit_price(default)
    if not mine or not reference or mine[1] != reference[1] or reference[0] <= 0:
        return True
    return 0.25 <= mine[0] / reference[0] <= 4


def build_proposal(
    manager: EssensplanerManager,
    parsed: dict[str, Any],
    branch: str | None = None,
    upload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The review proposal of a parsed receipt: store / branch, date and every line with its
    ingredient key, pack size and the price it would set (status mapped | unknown |
    ignored). The result can be passed to receipt_save as it is."""
    from .manager import _error  # avoid an import cycle

    warnings: list[str] = []
    retailer = parsed.get("retailer")
    branch_obj: dict[str, Any] | None = None
    how: str | None = None
    if branch:
        branch_obj = manager.resolve_branch(branch)
        if branch_obj is None:
            found = manager.resolve_store(branch)
            if found is None:
                raise _error("branch_not_found", branch=branch)
            if retailer and not retailer_matches(found, retailer):
                warnings.append(
                    f"Der Kassenzettel scheint von {retailer_name(retailer)} zu sein, nicht von "
                    f"{retailer_name(found)}."
                )
            retailer = found
        else:
            how = "given"
    if branch_obj is None and how is None:
        branch_obj, how = detect_branch(
            manager, retailer, parsed.get("postcode"), parsed.get("street")
        )
    if branch_obj is not None:
        own = branch_obj.get("retailer")
        if retailer and own and not retailer_matches(own, retailer):
            warnings.append(
                f"Der Kassenzettel scheint von {retailer_name(retailer)} zu sein, die Filiale "
                f"ist {manager.branch_label(branch_obj)}."
            )
        retailer = own or retailer
    if retailer is None:
        warnings.append("Laden nicht erkannt – bitte die Filiale auswählen.")
    if parsed.get("total") is not None and not parsed.get("checked"):
        warnings.append(
            f"Die Zeilen ergeben {_eur(parsed.get('sum'))}, der Kassenzettel "
            f"{_eur(parsed['total'])} – bitte die Zeilen prüfen."
        )
    mapper = ReceiptMapper(manager, retailer)
    book = manager.store_book(retailer) if retailer else None
    try:
        receipt_day = _receipt_day(manager, parsed.get("date"))
    except HomeAssistantError:
        receipt_day = manager.today()  # a date the review asks for anyway
    items = []
    for raw in parsed.get("items") or []:
        item = {k: raw.get(k) for k in ("line", "name", "quantity", "weight", "unit_price")}
        item.update(
            {
                "regular": bool(raw.get("regular")),
                "price": raw.get("price"),
                "discount": raw.get("discount") or 0.0,
                "kind": raw.get("kind") or "article",
                "ignored": bool(raw.get("ignored")),
                "confidence": raw.get("confidence"),
            }
        )
        items.append(_proposal_item(manager, mapper, book, retailer, item, receipt_day))
    day = parsed.get("date")
    return {
        "source": parsed.get("source") or SOURCE_TEXT,
        "upload_id": (upload or {}).get("id"),
        "media_content_id": manager.receipts.media_content_id(upload) if upload else None,
        "store": parsed.get("store"),
        "retailer": retailer,
        "retailer_name": retailer_name(retailer) if retailer else None,
        "kind": retailer_kind(retailer),
        "branch_id": branch_obj.get("id") if branch_obj else None,
        "branch_label": manager.branch_label(branch_obj) if branch_obj else None,
        "branch_match": how,
        "postcode": parsed.get("postcode"),
        "city": parsed.get("city"),
        "street": parsed.get("street"),
        "date": day,
        "total": parsed.get("total"),
        "sum": parsed.get("sum"),
        "checked": bool(parsed.get("checked")),
        "items": items,
        "mapped": sum(1 for i in items if i["status"] == "mapped"),
        "unknown": sum(1 for i in items if i["status"] == "unknown"),
        "ignored": sum(1 for i in items if i["status"] == "ignored"),
        "unparsed": list(parsed.get("unparsed") or []),
        "warnings": warnings,
    }


def _eur(value: Any) -> str:
    try:
        return f"{float(value):.2f} €".replace(".", ",")
    except (TypeError, ValueError):
        return "?"


async def async_parse_receipt_text(
    manager: EssensplanerManager, text: str, branch: str | None = None
) -> dict[str, Any]:
    """Proposal of a pasted receipt text (parsed locally). Error receipt_no_items when no
    article line was found."""
    from .manager import _error

    parsed = parse_receipt_text(text, manager.today())
    if not any(i["kind"] == "article" for i in parsed["items"]):
        raise _error("receipt_no_items")
    await asyncio.sleep(0)
    return build_proposal(manager, parsed, branch)


def _proposal_item(
    manager: EssensplanerManager,
    mapper: ReceiptMapper,
    book: Any,
    retailer: str | None,
    item: dict[str, Any],
    day: date,
) -> dict[str, Any]:
    name = str(item.get("name") or "")
    result = {**item, "key": None, "product": None, "match": None, "status": "ignored"}
    result.update({"amount": None, "unit": None, "pack": None, "pack_source": None})
    result.update({"own_price": None, "current": None, "warning": None, "offer": None})
    if item["ignored"]:
        return result
    mapping = mapper.map(name)
    key = mapping["key"] if mapping["confidence"] >= MIN_CONFIDENCE else None
    if item.get("weight"):
        amount, unit, source = round(float(item["weight"]) * 1000, 1), "g", "weight"
    else:
        amount, unit, source = _pack_for(manager, key, retailer, name)
    result.update(
        {
            "key": key,
            "product": mapping["product"] if key else None,
            "suggestion": mapping["product"] if mapping["key"] and not key else None,
            "match": mapping["match"] if key else None,
            "confidence": round(min(float(item.get("confidence") or 1), mapping["confidence"]), 2),
            "status": "mapped" if key else "unknown",
            "amount": amount,
            "unit": unit,
            "pack": pack_text(amount, unit) or None,
            "pack_source": source,
        }
    )
    price = own_price(result)
    if price is not None:
        result["own_price"] = {"price": price[0], "amount": price[1], "unit": price[2]}
        if key and not _plausibility(manager, key, price):
            result["warning"] = "Preis weicht stark vom Richtwert ab – Packungsgröße prüfen."
        if offer := receipt_offer(manager, retailer, key, day, result):
            result["offer"] = {
                "product": offer.get("product") or offer.get("title"),
                "price": offer.get("price"),
                "old_price": offer.get("old_price") or offer.get("regular_price"),
                "valid_to": offer.get("valid_to"),
            }
            result["warning"] = (
                "Angebotspreis – bleibt nur im Preisverlauf, der Normalpreis wird nicht geändert."
            )
    if key and book is not None and (entry := book.lookup(result["product"] or key)):
        result["current"] = {
            "price": round(entry.price, 2),
            "amount": entry.amount,
            "unit": entry.unit,
            "source": entry.source,
        }
    return result


# ----------------------------------------------------------------------------------
# AI Task
# ----------------------------------------------------------------------------------


def ai_entity(manager: EssensplanerManager, entity_id: str | None = None) -> str | None:
    """The AI Task entity for receipt photos: the given one, else the receipt option, else
    (1.5) the AI entity of the settings' "KI" section when it is an AI Task. None when
    "Kassenzettel-Fotos" is switched off in the AI features (a given entity still counts)."""
    if entity_id:
        return entity_id
    if not ai.ai_enabled(manager, AI_FEATURE_RECEIPTS):
        return None
    return ai.ai_entity(manager, AI_FEATURE_RECEIPTS)


def ai_available(hass: HomeAssistant, entity_id: str | None) -> bool:
    """True if the entity is an AI Task that exists, is available and
    ai_task.generate_data is registered."""
    if ai.ai_mode(entity_id) != ai.MODE_AI_TASK:
        return False
    return ai.ai_available(hass, entity_id)


async def async_scan_receipt(
    hass: HomeAssistant,
    manager: EssensplanerManager,
    upload_id: str | None = None,
    media_content_id: str | None = None,
    entity_id: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Read a receipt photo / PDF with the AI Task entity and return the proposal.

    Only the receipt (as attachment) and the fixed German instructions are sent – no data
    of the user. Errors: receipt_ai_not_configured, receipt_ai_unavailable,
    receipt_ai_failed, receipt_ai_invalid, receipt_upload_not_found, receipt_media_invalid.
    """
    from .manager import _error

    store = manager.receipts
    upload = None
    if upload_id:
        upload = store.upload(upload_id) or store.receipt_upload(upload_id)
        if upload is None:
            raise _error("receipt_upload_not_found", upload_id=upload_id)
        media_content_id = store.media_content_id(upload)
        content_type = upload["content_type"]
    else:
        content_type = media_type(media_content_id)
        if content_type is None:
            raise _error("receipt_media_invalid", media=media_content_id or "")
    entity = ai_entity(manager, entity_id)
    if not entity:
        if ai.ai_entity(manager, AI_FEATURE_RECEIPTS) is not None:
            raise _error("ai_feature_off", feature=ai.FEATURE_LABELS_DE[AI_FEATURE_RECEIPTS])
        raise _error("receipt_ai_not_configured")
    if not ai_available(hass, entity):
        raise _error("receipt_ai_unavailable", entity=entity)
    token = ai.AI_ACTIVE.set(True)  # no Essensplaner tools meanwhile (1.5)
    try:
        async with asyncio.timeout(AI_TIMEOUT):
            response = await hass.services.async_call(
                "ai_task",
                "generate_data",
                {
                    "task_name": AI_TASK_NAME,
                    "entity_id": entity,
                    "instructions": AI_INSTRUCTIONS,
                    "attachments": [
                        {"media_content_id": media_content_id, "media_content_type": content_type}
                    ],
                },
                blocking=True,
                return_response=True,
            )
    except TimeoutError as err:
        raise _error("receipt_ai_failed", error="keine Antwort") from err
    except (HomeAssistantError, vol.Invalid) as err:
        raise _error("receipt_ai_failed", error=str(err) or type(err).__name__) from err
    finally:
        ai.AI_ACTIVE.reset(token)
    try:
        parsed = parse_ai_receipt(response, manager.today())
    except (ValueError, TypeError) as err:
        _LOGGER.debug("Unreadable receipt answer of %s: %r", entity, response)
        raise _error("receipt_ai_invalid") from err
    return build_proposal(manager, parsed, branch, upload)


def media_type(media_content_id: str | None) -> str | None:
    """Content type of a local media file (or an uploaded receipt) the AI may read as a
    receipt (None otherwise)."""
    text = str(media_content_id or "")
    if ".." in text or not text.startswith(
        ("media-source://media_source/", f"media-source://{DOMAIN}/{MEDIA_SOURCE_RECEIPT}/")
    ):
        return None
    extension = text.rsplit(".", 1)[-1].lower() if "." in text else ""
    return EXTENSION_TYPES.get(extension)


# ----------------------------------------------------------------------------------
# Save / delete / view
# ----------------------------------------------------------------------------------


def _resolve_key(manager: EssensplanerManager, retailer: str, text: str) -> tuple[str, str]:
    """(key, product name) of a key or product name the user chose for an article."""
    raw = str(text).strip()
    bucket = manager.store_prices_user.get(retailer, {})
    if raw in bucket:
        return raw, str(bucket[raw].get("name") or raw)
    defaults = manager.defaults_index()
    if (default := defaults.get(raw)) is not None or (default := defaults.exact(raw)) is not None:
        return ingredient_key(default.name), default.name
    key = ingredient_key(raw)
    if key in bucket:
        return key, str(bucket[key].get("name") or raw)
    return key, raw[:1].upper() + raw[1:]


def _resolve_store(
    manager: EssensplanerManager, data: dict[str, Any]
) -> tuple[dict[str, Any] | None, str]:
    from .manager import _error

    text = data.get("branch_id") or data.get("branch")
    if text:
        branch = manager.get_branch(str(text)) or manager.resolve_branch(str(text))
        if branch is not None and branch.get("retailer"):
            return branch, branch["retailer"]
        if branch is None and not data.get("store") and not data.get("retailer"):
            found = manager.resolve_store(str(text))
            if found:
                return None, found
            raise _error("branch_not_found", branch=str(text))
    # a proposal carries the recognized chain id (its "store" is the printed header)
    store = data.get("retailer") or data.get("store")
    if store:
        return None, manager.require_retailer(str(store))
    raise _error("store_required")


def _receipt_day(manager: EssensplanerManager, value: Any) -> date:
    from .manager import _error

    today = manager.today()
    if value in (None, ""):
        return today
    if isinstance(value, date):
        day = value
    else:
        day = parse_receipt_date(str(value), None)
        if day is None:
            raise _error("invalid_date", date=str(value))
    if day > today or day < today - timedelta(days=5 * 366):
        raise _error("invalid_date", date=str(value))
    return day


def _clean_items(raw_items: Any) -> list[dict[str, Any]]:
    """The items of receipt_save, validated (prices, quantities, sizes)."""
    from .manager import _error

    if not isinstance(raw_items, list) or not raw_items:
        raise _error("receipt_no_items")
    items: list[dict[str, Any]] = []
    for raw in raw_items[:MAX_ITEMS]:
        if not isinstance(raw, dict):
            continue
        name = re.sub(r"\s+", " ", str(raw.get("name") or raw.get("line") or "")).strip()[:120]
        price = _number(raw.get("price"))
        if not name or price is None or abs(price) > MAX_PRICE:
            raise _error("invalid_price", price=raw.get("price"))
        item: dict[str, Any] = {
            "line": str(raw.get("line") or name)[:300],
            "name": name,
            "price": round(price, 2),
            "ignored": bool(raw.get("ignored")) or raw.get("status") == "ignored",
        }
        for field, limit in (("quantity", MAX_QUANTITY), ("amount", 100000.0)):
            value = _number(raw.get(field))
            item[field] = value if value is not None and 0 < value <= limit else None
        for field in ("discount", "unit_price", "weight"):
            value = _number(raw.get(field))
            item[field] = round(value, 3) if value is not None and abs(value) < MAX_PRICE else None
        item["unit"] = str(raw.get("unit") or "").strip()[:20] or None
        # "trotzdem als Normalpreis": no offer check for this line
        item["regular"] = bool(raw.get("regular"))
        key = raw.get("key")
        item["key"] = str(key).strip()[:80] if key not in (None, "") else None
        item["product"] = str(raw.get("product") or "").strip()[:80] or None
        items.append(item)
    if not items:
        raise _error("receipt_no_items")
    return items


async def async_save_receipt(manager: EssensplanerManager, data: dict[str, Any]) -> dict[str, Any]:
    """Store a reviewed receipt and set its mapped articles as the store's own prices.

    data: {branch | branch_id | store, date, items: [{name, key?, price, amount?, unit?,
    quantity?, ignored?, discount?, weight?, unit_price?}], total?, upload_id?, id? (an
    existing receipt is updated)}. A price of a newer receipt replaces an older own price;
    an own price typed (or a receipt) after the receipt's date is kept. Names the user
    assigned to another key are remembered for the next receipt of the chain.
    Result {receipt, prices: [{key, name, price, amount, unit, status saved|kept|offer}],
    saved, kept, offer, unknown}. A line at the price of a leaflet offer of the store on
    the receipt's day (status "offer", see receipt_offer()) only goes into the price
    history, unless the item says "regular": true ("trotzdem als Normalpreis").
    """
    from .manager import _error

    store = manager.receipts
    branch, retailer = _resolve_store(manager, data)
    day = _receipt_day(manager, data.get("date"))
    items = _clean_items(data.get("items"))
    previous = store.get(str(data["id"])) if data.get("id") else None
    upload = None
    if upload_id := data.get("upload_id"):
        upload = store.upload(str(upload_id))
        if upload is None and previous is None:
            # the proposal of a saved receipt read again: update that receipt
            previous = store.get(str(upload_id))
        if upload is None and previous is None:
            raise _error("receipt_upload_not_found", upload_id=str(upload_id))
    receipt_id = (
        previous["id"]
        if previous
        else (upload["id"] if upload and store.get(upload["id"]) is None else secrets.token_hex(8))
    )
    mapper = ReceiptMapper(manager, retailer)
    prices: list[dict[str, Any]] = []
    saved_keys: set[tuple[str, str]] = set()
    for item in items:
        if item["ignored"]:
            item["status"] = "ignored"
            continue
        automatic = mapper.map(item["name"])
        if item["key"] is None:
            item["status"] = "unknown"
            continue
        key, product = _resolve_key(manager, retailer, item["key"])
        item["key"], item["product"] = key, item["product"] or product
        if automatic["key"] != key or automatic["confidence"] < MIN_CONFIDENCE:
            store.remember_alias(retailer, item["name"], key, item["product"])
        if item["amount"] is None and not item["weight"]:
            amount, unit, _ = _pack_for(manager, key, retailer, item["name"])
            item["amount"], item["unit"] = amount, unit
        if not item["unit"]:
            item["unit"] = "Stück"
        price = own_price(item)
        if price is None:
            item["status"] = "skipped"
            continue
        # an offer price of the store on that day is no regular price (history only)
        offer = receipt_offer(manager, retailer, key, day, item) is not None
        status = manager.put_receipt_price(
            retailer, key, item["product"], *price, receipt_id=receipt_id, day=day, offer=offer
        )
        item["status"] = status
        saved_keys.add((retailer, key))
        prices.append(
            {
                "key": key,
                "name": item["product"],
                "price": price[0],
                "amount": price[1],
                "unit": price[2],
                "status": status,
            }
        )
    if previous is not None:
        # prices this receipt no longer sets (other lines, another store) are removed
        manager.remove_receipt_prices(receipt_id, keep=saved_keys)
    total = _number(data.get("total"))
    receipt = {
        "id": receipt_id,
        "branch_id": branch.get("id") if branch else None,
        "retailer": retailer,
        "store_label": manager.branch_label(branch) if branch else retailer_name(retailer),
        "date": day.isoformat(),
        "total": round(total, 2) if total is not None else None,
        "sum": round(sum(i["price"] for i in items), 2),
        "items": [
            {
                k: item.get(k)
                for k in (
                    "line",
                    "name",
                    "key",
                    "product",
                    "quantity",
                    "amount",
                    "unit",
                    "price",
                    "unit_price",
                    "discount",
                    "weight",
                    "ignored",
                    "regular",
                    "status",
                )
            }
            for item in items
        ],
        "source": str(data.get("source") or (SOURCE_PHOTO if upload else SOURCE_TEXT)),
        "image": (previous or {}).get("image"),
        "upload_id": (previous or {}).get("upload_id"),
        "created": (previous or {}).get("created") or dt_util.utcnow().isoformat(),
        "updated": dt_util.utcnow().isoformat(),
    }
    if receipt["source"] not in (SOURCE_PHOTO, SOURCE_TEXT):
        receipt["source"] = SOURCE_TEXT
    if upload is not None:
        receipt["image"] = f"{MEDIA_SUBDIR}/{upload['file']}"
        receipt["upload_id"] = upload["id"]
        receipt["content_type"] = upload["content_type"]
        store.claim_upload(upload["id"])
    elif previous is not None and previous.get("content_type"):
        receipt["content_type"] = previous["content_type"]
    dropped = store.put(receipt)
    # its products (linked to known ones of the chain, else receipt products) and a
    # "bought" pick each – once, not again when the receipt is corrected (1.5)
    from .products import ingest_receipt

    try:
        ingest_receipt(manager, receipt, record=previous is None)
    except Exception:
        _LOGGER.exception("Storing the products of a receipt failed")
    replaced = (previous or {}).get("image")
    if upload is not None and replaced and replaced != receipt["image"]:
        dropped.append({"image": replaced})  # a new photo of a saved receipt
    await store.async_delete_files([r.get("image") for r in dropped])
    if prices or previous is not None:
        manager._invalidate_prices()
        manager._after_price_change("prices")
    store.save_later()
    return {
        "receipt": receipt_view(manager, receipt),
        "prices": prices,
        "saved": sum(1 for p in prices if p["status"] == "saved"),
        "kept": sum(1 for p in prices if p["status"] == "kept"),
        "offer": sum(1 for p in prices if p["status"] == "offer"),
        "unknown": sum(1 for i in items if i["status"] == "unknown"),
    }


async def async_delete_receipt(
    manager: EssensplanerManager, receipt_id: str, remove_prices: bool = False
) -> dict[str, Any]:
    """Delete a receipt and its image; its prices stay unless remove_prices."""
    from .manager import _error

    store = manager.receipts
    receipt = store.pop(receipt_id)
    if receipt is None:
        raise _error("receipt_not_found", id=receipt_id)
    removed = manager.remove_receipt_prices(receipt_id) if remove_prices else 0
    images = await store.async_delete_files([receipt.get("image")])
    if removed:
        manager._invalidate_prices()
        manager._after_price_change("prices")
    store.save_later()
    return {"id": receipt_id, "removed": True, "prices_removed": removed, "image_removed": images}


def receipt_view(
    manager: EssensplanerManager, receipt: dict[str, Any], sign: Any = None
) -> dict[str, Any]:
    """A stored receipt for services / the panel (with the media id and, given a signer,
    a signed image link)."""
    view = {k: v for k, v in receipt.items() if k != "upload_id"}
    view["retailer_name"] = retailer_name(receipt.get("retailer"))
    view["media_content_id"] = (
        manager.receipts.media_content_id({"file": receipt["image"].rsplit("/", 1)[-1]})
        if receipt.get("image")
        else None
    )
    view["image_url"] = sign(receipt["id"]) if sign and receipt.get("image") else None
    view["prices"] = sum(1 for i in receipt.get("items") or [] if i.get("status") == "saved")
    return view


def receipts_view(
    manager: EssensplanerManager, limit: int = 50, sign: Any = None
) -> dict[str, Any]:
    """The newest receipts first: {count, receipts: [...], ai: {entity, available}}."""
    receipts = sorted(
        manager.receipts.receipts,
        key=lambda r: (str(r.get("date") or ""), str(r.get("created") or "")),
        reverse=True,
    )
    return {
        "count": len(receipts),
        "receipts": [receipt_view(manager, r, sign) for r in receipts[: max(1, int(limit))]],
        **receipts_summary(manager),
    }


def receipts_summary(manager: EssensplanerManager) -> dict[str, Any]:
    """{receipts, last_date, prices, ai_entity, ai_available} (panel, diagnostics)."""
    entity = ai_entity(manager)
    receipts = manager.receipts.receipts
    prices = sum(
        1
        for bucket in manager.store_prices_user.values()
        for item in bucket.values()
        if isinstance(item, dict) and item.get("source") == SOURCE_RECEIPT
    )
    return {
        "total_receipts": len(receipts),
        "last_date": max((str(r.get("date") or "") for r in receipts), default=None) or None,
        "receipt_prices": prices,
        "ai_entity": entity,
        "ai_available": ai_available(manager.hass, entity),
    }


# ----------------------------------------------------------------------------------
# Store (own file) and the image files
# ----------------------------------------------------------------------------------


def media_root(hass: HomeAssistant) -> tuple[str, Path]:
    """(media source dir id, path) receipts are stored in: the "local" media folder."""
    dirs = hass.config.media_dirs or {}
    if "local" in dirs:
        return "local", Path(dirs["local"])
    if dirs:
        first = next(iter(dirs))
        return first, Path(dirs[first])
    return "local", Path(hass.config.path("media"))


def receipts_folder(hass: HomeAssistant) -> Path:
    """The private folder of the receipt files (not browsable as media)."""
    return Path(hass.config.path(".storage", RECEIPTS_DIR))


def _empty() -> dict[str, Any]:
    return {"version": STORE_VERSION, "receipts": [], "uploads": {}, "aliases": {}}


def sniff_type(data: bytes) -> str | None:
    """Content type by the file's first bytes (jpg / png / webp / pdf), else None."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def _safe_name(name: str | None) -> str:
    """The uploaded file name for display only (never used as a path)."""
    text = re.sub(r"[^\w.\- ]+", "_", str(name or ""))[:80].strip(" ._")
    return text or "kassenzettel"


class ReceiptStore:
    """The receipts of one config entry (own Store file, images in a private folder)."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize (empty until async_load)."""
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(hass, STORE_VERSION, self.store_key(entry_id))
        self.data: dict[str, Any] = _empty()
        self.unloaded = False

    @staticmethod
    def store_key(entry_id: str) -> str:
        """Storage key of the receipts file of an entry."""
        return f"{STORAGE_KEY}.receipts.{entry_id}"

    async def async_load(self) -> None:
        """Read the file (missing or unreadable = no receipts); old uploads are removed."""
        try:
            data = await self._store.async_load()
        except (OSError, ValueError) as err:  # pragma: no cover - defensive
            _LOGGER.warning("Could not read the receipts: %s", err)
            data = None
        base = _empty()
        if isinstance(data, dict):
            if isinstance(data.get("receipts"), list):
                base["receipts"] = [
                    r for r in data["receipts"] if isinstance(r, dict) and r.get("id")
                ]
            for key in ("uploads", "aliases"):
                if isinstance(data.get(key), dict):
                    base[key] = data[key]
        self.data = base
        if stale := self._stale_uploads():
            await self.async_delete_files([f"{MEDIA_SUBDIR}/{u['file']}" for u in stale])
            self.save_later()
        await self.hass.async_add_executor_job(self._tidy_files, self._file_names())

    def _file_names(self) -> set[str]:
        """The files the receipts and pending uploads refer to."""
        names = {str(r["image"]).rsplit("/", 1)[-1] for r in self.receipts if r.get("image")}
        names |= {
            str(u["file"])
            for u in self.data["uploads"].values()
            if isinstance(u, dict) and u.get("file")
        }
        return {n for n in names if _FILE_RE.fullmatch(n)}

    def _tidy_files(self, names: set[str]) -> None:
        """Move files of 1.4 development versions out of the media folder; delete receipt
        files nothing refers to any more (an interrupted upload, a replaced image)."""
        folder = self.folder
        old = media_root(self.hass)[1] / MEDIA_SUBDIR
        try:
            if old.is_dir():
                for name in names:
                    if (old / name).is_file() and not (folder / name).exists():
                        folder.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(old / name), str(folder / name))
                for directory in (old, old.parent):
                    directory.rmdir()  # only when empty
        except OSError:
            pass
        if not folder.is_dir():
            return
        cutoff = time.time() - ORPHAN_MINUTES * 60
        for path in folder.iterdir():
            try:
                if (
                    _LEFTOVER_RE.fullmatch(path.name)
                    and path.name not in names
                    and path.stat().st_mtime < cutoff
                ):
                    path.unlink()
            except OSError as err:
                _LOGGER.debug("Could not tidy receipt file %s: %s", path.name, err)

    async def async_save(self) -> None:
        """Write the file now."""
        if not self.unloaded:
            await self._store.async_save(self.data)

    def save_later(self) -> None:
        """Write the file soon."""
        if not self.unloaded:
            self._store.async_delay_save(lambda: self.data, 2)

    async def async_remove(self) -> None:
        """Delete the receipt images listed in the file, then the file itself."""
        try:
            data = await self._store.async_load()
        except (OSError, ValueError):  # pragma: no cover - defensive
            data = None
        files: list[Any] = []
        if isinstance(data, dict):
            files = [r.get("image") for r in data.get("receipts") or [] if isinstance(r, dict)]
            files += [
                f"{MEDIA_SUBDIR}/{u.get('file')}"
                for u in (data.get("uploads") or {}).values()
                if isinstance(u, dict) and u.get("file")
            ]
        await self.hass.async_add_executor_job(self._remove_all_files, files)
        await self._store.async_remove()

    def _remove_all_files(self, files: list[Any]) -> None:
        """Every receipt file of the private folder (also ones nothing refers to) and the
        listed ones still in the media folder of a 1.4 development version."""
        names = {str(f).rsplit("/", 1)[-1] for f in files if f}
        old = media_root(self.hass)[1] / MEDIA_SUBDIR
        for folder, wanted in ((self.folder, None), (old, names)):
            if not folder.is_dir():
                continue
            for path in folder.iterdir():
                if _LEFTOVER_RE.fullmatch(path.name) and (wanted is None or path.name in wanted):
                    try:
                        path.unlink()
                    except OSError as err:
                        _LOGGER.warning("Could not delete receipt file %s: %s", path.name, err)
            for directory in (folder, folder.parent) if wanted else (folder,):
                try:
                    directory.rmdir()  # only when empty
                except OSError:
                    break

    # -- receipts -----------------------------------------------------------------

    @property
    def receipts(self) -> list[dict[str, Any]]:
        """All stored receipts (oldest first)."""
        return self.data["receipts"]

    def get(self, receipt_id: str) -> dict[str, Any] | None:
        """One receipt (None if unknown)."""
        return next((r for r in self.receipts if r.get("id") == receipt_id), None)

    def put(self, receipt: dict[str, Any]) -> list[dict[str, Any]]:
        """Add or replace a receipt; returns the receipts dropped over MAX_RECEIPTS."""
        self.data["receipts"] = [r for r in self.receipts if r.get("id") != receipt["id"]]
        self.receipts.append(receipt)
        dropped: list[dict[str, Any]] = []
        if len(self.receipts) > MAX_RECEIPTS:
            ordered = sorted(
                self.receipts,
                key=lambda r: (str(r.get("date") or ""), str(r.get("created") or "")),
            )
            dropped = ordered[: len(self.receipts) - MAX_RECEIPTS]
            ids = {r["id"] for r in dropped}
            self.data["receipts"] = [r for r in self.receipts if r["id"] not in ids]
        return dropped

    def pop(self, receipt_id: str) -> dict[str, Any] | None:
        """Remove a receipt (None if unknown)."""
        receipt = self.get(receipt_id)
        if receipt is not None:
            self.data["receipts"] = [r for r in self.receipts if r.get("id") != receipt_id]
        return receipt

    # -- learned names --------------------------------------------------------------

    def aliases_for(self, retailer: str | None) -> dict[str, dict[str, Any]]:
        """{receipt name: {key, product}} the user assigned (this chain's, then any)."""
        aliases = self.data["aliases"]
        result: dict[str, dict[str, Any]] = {}
        for stored, value in aliases.items():
            chain, _, name = stored.partition("|")
            if (
                isinstance(value, dict)
                and value.get("key")
                and chain in ("", retailer or "")
                and (chain or name not in result)
            ):
                result[name] = value
        return result

    def remember_alias(self, retailer: str | None, name: str, key: str, product: str) -> None:
        """Remember the key the user chose for a receipt name (at most MAX_ALIASES)."""
        aliases = self.data["aliases"]
        aliases[f"{retailer or ''}|{_alias_name(name)}"] = {
            "key": key,
            "product": product,
            "updated": dt_util.utcnow().isoformat(),
        }
        if len(aliases) > MAX_ALIASES:
            oldest = sorted(aliases, key=lambda k: str(aliases[k].get("updated") or ""))
            for stored in oldest[: len(aliases) - MAX_ALIASES]:
                del aliases[stored]

    # -- uploads and files -----------------------------------------------------------

    @property
    def folder(self) -> Path:
        """The private receipts folder."""
        return receipts_folder(self.hass)

    def media_content_id(self, upload: dict[str, Any]) -> str:
        """media-source id of an uploaded file (the integration's own media source)."""
        return f"media-source://{DOMAIN}/{MEDIA_SOURCE_RECEIPT}/{upload['file']}"

    def file_info(self, name: str) -> tuple[Path, str, str] | None:
        """(path, content type, upload or receipt id) of a receipt file a pending upload
        or a receipt refers to."""
        if not _FILE_RE.fullmatch(str(name)):
            return None
        for upload in self.data["uploads"].values():
            if isinstance(upload, dict) and upload.get("file") == name and upload.get("id"):
                ctype = str(upload.get("content_type") or "image/jpeg")
                return self.folder / name, ctype, str(upload["id"])
        for receipt in self.receipts:
            if str(receipt.get("image") or "").rsplit("/", 1)[-1] == name:
                found = self.receipt_upload(receipt["id"])
                ctype = found["content_type"] if found else "image/jpeg"
                return self.folder / name, ctype, str(receipt["id"])
        return None

    def upload(self, upload_id: str) -> dict[str, Any] | None:
        """A pending upload (not saved as a receipt yet)."""
        found = self.data["uploads"].get(str(upload_id))
        return found if isinstance(found, dict) else None

    def receipt_upload(self, receipt_id: str) -> dict[str, Any] | None:
        """The image of a saved receipt in the shape of an upload (to scan it again)."""
        receipt = self.get(str(receipt_id))
        if not receipt or not receipt.get("image"):
            return None
        name = receipt["image"].rsplit("/", 1)[-1]
        ctype = receipt.get("content_type") or EXTENSION_TYPES.get(name.rsplit(".", 1)[-1])
        return {"id": receipt["id"], "file": name, "content_type": ctype or "image/jpeg"}

    def claim_upload(self, upload_id: str) -> None:
        """The upload became a receipt (its file stays)."""
        self.data["uploads"].pop(upload_id, None)

    def image_path(self, ident: str) -> tuple[Path, str] | None:
        """(path, content type) of the image of a receipt or pending upload."""
        if not _ID_RE.match(str(ident)):
            return None
        upload = self.upload(ident) or self.receipt_upload(ident)
        if upload is None:
            return None
        name = upload["file"]
        if not _FILE_RE.fullmatch(name):
            return None
        return self.folder / name, upload["content_type"]

    def _stale_uploads(self) -> list[dict[str, Any]]:
        """Remove pending uploads older than UPLOAD_KEEP_HOURS (or over MAX_UPLOADS)."""
        uploads = self.data["uploads"]
        cutoff = dt_util.utcnow() - timedelta(hours=UPLOAD_KEEP_HOURS)
        stale: list[dict[str, Any]] = []
        ordered = sorted(uploads.values(), key=lambda u: str(u.get("created") or ""))
        for position, upload in enumerate(ordered):
            created = dt_util.parse_datetime(str(upload.get("created") or ""))
            too_many = len(ordered) - position > MAX_UPLOADS
            if created is None or created < cutoff or too_many:
                stale.append(upload)
        for upload in stale:
            uploads.pop(upload.get("id"), None)
        return [u for u in stale if u.get("file")]

    async def async_add_upload(
        self, content: bytes, content_type: str, filename: str | None = None
    ) -> dict[str, Any]:
        """Write an uploaded receipt file and remember it as a pending upload."""
        upload_id = secrets.token_hex(8)
        extension = CONTENT_TYPES[content_type]
        name = f"{upload_id}.{extension}"
        folder = self.folder

        def write() -> None:
            folder.mkdir(parents=True, exist_ok=True)
            temp = folder / f".{name}.part"
            try:
                temp.write_bytes(content)
                temp.replace(folder / name)
            except OSError:
                temp.unlink(missing_ok=True)  # e.g. the disk is full
                raise

        await self.hass.async_add_executor_job(write)
        if self.unloaded:
            # the entry was reloaded meanwhile: the new store does not know this file
            await self.async_delete_files([f"{MEDIA_SUBDIR}/{name}"])
            raise HomeAssistantError("reloaded")
        upload = {
            "id": upload_id,
            "file": name,
            "content_type": content_type,
            "size": len(content),
            "name": _safe_name(filename),
            "created": dt_util.utcnow().isoformat(),
        }
        self.data["uploads"][upload_id] = upload
        if stale := self._stale_uploads():
            await self.async_delete_files([f"{MEDIA_SUBDIR}/{u['file']}" for u in stale])
        self.save_later()
        return upload

    async def async_delete_files(self, paths: list[Any], prune_dirs: bool = False) -> int:
        """Delete receipt files (media paths "essensplaner/receipts/<id>.<ext>"; anything
        else is ignored). Returns the number of deleted files."""
        folder = self.folder
        names = [
            str(p).rsplit("/", 1)[-1]
            for p in paths
            if p
            and str(p).startswith(f"{MEDIA_SUBDIR}/")
            and _FILE_RE.fullmatch(str(p).rsplit("/", 1)[-1])
        ]

        def delete() -> int:
            deleted = 0
            for name in names:
                try:
                    (folder / name).unlink()
                    deleted += 1
                except FileNotFoundError:
                    continue
                except OSError as err:
                    _LOGGER.warning("Could not delete receipt file %s: %s", name, err)
            if prune_dirs:
                for directory in (folder, folder.parent):
                    try:
                        directory.rmdir()  # only when empty
                    except OSError:
                        break
            return deleted

        if not names and not prune_dirs:
            return 0
        return await self.hass.async_add_executor_job(delete)


# ----------------------------------------------------------------------------------
# HTTP: upload and image views
# ----------------------------------------------------------------------------------


def _loaded_manager(hass: HomeAssistant) -> EssensplanerManager | None:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    return entries[0].runtime_data if entries else None


def image_link(hass: HomeAssistant, receipt_id: str, refresh_token_id: str | None = None) -> str:
    """Signed link to a receipt image (an <img> cannot send the access token)."""
    from homeassistant.components.http.auth import async_sign_path

    return async_sign_path(
        hass,
        IMAGE_URL.format(receipt_id=receipt_id),
        timedelta(hours=IMAGE_LINK_HOURS),
        refresh_token_id=refresh_token_id,
    )


def async_register_views(hass: HomeAssistant) -> None:
    """Register the upload and image views (needs the http component)."""
    if getattr(hass, "http", None) is None:
        return
    hass.http.register_view(ReceiptUploadView())
    hass.http.register_view(ReceiptImageView())


class ReceiptUploadView(HomeAssistantView):
    """POST multipart field "file" (jpg, png, webp or pdf, ≤ 10 MB, admins only).

    Result {upload_id, media_content_id, url (signed preview link), content_type, size}.
    Errors (JSON {message, code}): 400 receipt_file_missing, 413 receipt_file_too_large,
    415 receipt_file_type, 404 not_loaded.
    """

    url = UPLOAD_URL
    name = "api:essensplaner:receipt_upload"

    @require_admin
    async def post(self, request: web.Request) -> web.Response:
        """Store an uploaded receipt."""
        hass: HomeAssistant = request.app[KEY_HASS]
        not_loaded = self.json_message(
            "Der Essensplaner ist nicht eingerichtet.", HTTPStatus.NOT_FOUND, "not_loaded"
        )
        if _loaded_manager(hass) is None:
            return not_loaded
        too_large = self.json_message(
            "Die Datei ist zu groß (höchstens 10 MB).",
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            "receipt_file_too_large",
        )
        if request.content_length and request.content_length > MAX_UPLOAD_BYTES + 65536:
            return too_large
        missing = self.json_message(
            "Bitte ein Foto oder PDF des Kassenzettels im Feld „file“ senden.",
            HTTPStatus.BAD_REQUEST,
            "receipt_file_missing",
        )
        try:
            reader = await request.multipart()
        except (AssertionError, ValueError, KeyError):
            return missing
        content = b""
        part_type = ""
        filename = None
        while True:
            try:
                part = await reader.next()
            except ValueError:
                return missing
            if part is None:
                break
            if getattr(part, "name", None) != "file":
                continue
            chunks: list[bytes] = []
            size = 0
            while chunk := await part.read_chunk(65536):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    return too_large
                chunks.append(chunk)
            content = b"".join(chunks)
            part_type = str(part.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            filename = part.filename
            break
        if not content:
            return missing
        sniffed = sniff_type(content)
        if part_type == "image/jpg":
            part_type = "image/jpeg"
        if part_type in ("", "application/octet-stream") and sniffed:
            part_type = sniffed
        if part_type not in CONTENT_TYPES or sniffed != part_type:
            return self.json_message(
                "Nur Fotos (JPG, PNG, WebP) oder PDF-Dateien von Kassenzetteln.",
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                "receipt_file_type",
            )
        # the manager after reading the (slow, phone) body: saving the settings meanwhile
        # reloads the entry
        manager = _loaded_manager(hass)
        if manager is None:
            return not_loaded
        try:
            upload = await manager.receipts.async_add_upload(content, part_type, filename)
        except HomeAssistantError:
            return self.json_message(
                "Der Essensplaner wurde gerade neu geladen – bitte noch einmal hochladen.",
                HTTPStatus.SERVICE_UNAVAILABLE,
                "not_loaded",
            )
        except OSError as err:
            _LOGGER.warning("Could not store a receipt upload: %s", err)
            return self.json_message(
                "Die Datei konnte nicht gespeichert werden.",
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "receipt_file_write",
            )
        return self.json(
            {
                "upload_id": upload["id"],
                "media_content_id": manager.receipts.media_content_id(upload),
                "url": image_link(hass, upload["id"], request.get(KEY_HASS_REFRESH_TOKEN_ID)),
                "content_type": part_type,
                "size": upload["size"],
            }
        )


class ReceiptImageView(HomeAssistantView):
    """GET the image of a receipt or pending upload (admins; signed links work)."""

    url = IMAGE_URL
    name = "api:essensplaner:receipt_image"

    @require_admin
    async def get(self, request: web.Request, receipt_id: str) -> web.StreamResponse:
        """Send the file."""
        hass: HomeAssistant = request.app[KEY_HASS]
        manager = _loaded_manager(hass)
        found = manager.receipts.image_path(receipt_id) if manager is not None else None
        if found is None:
            raise web.HTTPNotFound
        path, content_type = found
        if not await hass.async_add_executor_job(path.is_file):
            raise web.HTTPNotFound
        return web.FileResponse(
            path,
            headers={
                "Content-Type": content_type,
                "Cache-Control": "private, max-age=3600",
                "X-Content-Type-Options": "nosniff",
            },
        )
