"""Supermarket and drugstore offers (Aldi, Lidl, Rewe, Edeka, Penny, Netto, Kaufland, Rossmann …).

Sources:
- manual offers (panel, service, voice)
- optional: marktguru.de (aggregates the weekly leaflets of German supermarkets).
  This uses the *unofficial* web API that marktguru.de itself uses; it is not documented
  and may change at any time. Only enabled when the user opts in.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
import json
import logging
import re
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .const import HTTP_USER_AGENT
from .ingredients import _singular, fold, ingredient_key, to_base
from .pricing import format_eur, plausible_pack

# STORES / DEFAULT_STORES moved to retailers.py in 1.3, re-exported here
from .retailers import DEFAULT_STORES as DEFAULT_STORES, STORES as STORES, retailer_for_store_id

_LOGGER = logging.getLogger(__name__)

MARKTGURU_HOME = "https://www.marktguru.de/"
MARKTGURU_API = "https://api.marktguru.de/api/v1"
# marktguru's media host (config.mediaHostAddress of the web site, checked 11/2026); the
# browser loads the images directly (no keys needed)
MEDIA_HOST = "https://cdn.marktguru.de"
IMAGE_URL = f"{MEDIA_HOST}/api/v1/offers/{{id}}/images/default/0/small.webp"
LEAFLET_PAGE_URL = f"{MEDIA_HOST}/api/v1/leaflets/{{id}}/images/pages/{{page}}/small.webp"
LEAFLET_LINK = "https://www.marktguru.de/leaflets/{id}/page/0"

REQUEST_DELAY = 0.4
# search terms per refresh: main postcode / each further postcode
MAX_QUERIES = 40
EXTRA_TARGET_QUERIES = 25

# the integration's honest User-Agent (1.4; no browser impersonation)
_USER_AGENT = HTTP_USER_AGENT
# marktguru's placeholder brand of unbranded offers
_NO_BRAND = "thisisnobrand123"
_CONFIG_RE = re.compile(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', re.DOTALL)
_PACK_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*-?\s*(kg|g|ml|l|liter)\b", re.IGNORECASE)
_MULTI_RE = re.compile(
    r"(\d+)\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*-?\s*(kg|g|ml|l|liter)\b", re.IGNORECASE
)
# a weight class or range ("Größe M (53-63 g)", "500-600 g") is no package size
_RANGE_RE = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:kg|g|ml|l)?\s*[-–]\s*\d+(?:[.,]\d+)?\s*-?\s*(?:kg|g|ml|l|liter)\b",
    re.IGNORECASE,
)
# the same written out: egg weight classes "(53 g bis unter 63 g)", "(ab 63 g)", "über 73 g"
_WEIGHT_CLASS_RE = re.compile(
    r"\d+(?:[.,]\d+)?\s*g\s+bis\s+(?:unter\s+)?\d+(?:[.,]\d+)?\s*g\b"
    r"|\b(?:ab|über|ueber|unter|bis(?:\s+unter)?)\s+\d+(?:[.,]\d+)?\s*g\b",
    re.IGNORECASE,
)
# drugstore / household packs (1.4): detergent by washing loads ("39 WL", "20
# Waschladungen", EDEKA's "38 WA" Waschanwendungen), paper by rolls ("8 Rollen",
# "3 x 100 Blatt" = 3 rolls)
_LOADS_RE = re.compile(
    r"(\d+)\s*-?\s*(?:wl|wa|waschladung(?:en)?|waschanwendung(?:en)?)\b", re.IGNORECASE
)
_ROLLS_RE = re.compile(r"(\d+)\s*-?\s*rollen?\b|(\d+)\s*[x×]\s*\d+\s*blatt\b", re.IGNORECASE)


class OfferError(Exception):
    """Raised when offers could not be fetched."""


class OfferBlocked(OfferError):
    """marktguru refused the request (HTTP 401/403 again after new keys, 429, a web page
    instead of data): no more requests for a while (catalog.pause_marktguru())."""


def parse_pack(text: str | None) -> tuple[float, str] | None:
    """Package size from texts like 'je 500-g-Packung', '2 x 125 g', '1,5-l-Flasche'.

    Ranges and weight classes are skipped: 'Eier Größe M (53-63 g), 10 Stück' or 'Größe L
    (ab 63 g)' has no size in grams. Detergents are sized by washing loads ('1,1 l = 20 WL'
    -> (20, 'WL'), EDEKA's '38 WA' too), toilet paper and kitchen rolls by rolls ('8 Rollen', '3 x 100 Blatt'
    -> (3, 'Rolle')) when no weight or volume is given.
    """
    if not text:
        return None
    text = _WEIGHT_CLASS_RE.sub(" ", _RANGE_RE.sub(" ", text))
    if (match := _LOADS_RE.search(text)) and (loads := float(match.group(1))) > 0:
        return loads, "WL"
    if match := _MULTI_RE.search(text):
        count = float(match.group(1))
        value = float(match.group(2).replace(",", "."))
        amount, unit = to_base(count * value, match.group(3).lower().replace("liter", "l"))
        return (amount or 0, unit) if amount else None
    if match := _PACK_RE.search(text):
        value = float(match.group(1).replace(",", "."))
        unit = match.group(2).lower().replace("liter", "l")
        amount, base = to_base(value, unit)
        return (amount or 0, base) if amount else None
    if (match := _ROLLS_RE.search(text)) and (rolls := float(match.group(1) or match.group(2))):
        return rolls, "Rolle"
    return None


_STUECK_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:stück|stueck|stk\b|st\b)", re.IGNORECASE)


def parse_pack_text(text: str | None) -> tuple[float, str] | None:
    """'250 g', '1,5 l', '2 x 125 g', '10 Stück' -> (amount, base unit)."""
    if not text:
        return None
    if size := parse_pack(str(text)):
        return size
    if match := _STUECK_RE.search(str(text)):
        amount = float(match.group(1).replace(",", "."))
        return (amount, "Stück") if amount > 0 else None
    return None


def _date(value: Any) -> str | None:
    """Local date of a timestamp: marktguru's '2026-11-08T23:00:00Z' starts on 09.11. in
    Germany (UTC timestamps become the local date; a plain date stays as it is)."""
    if not value:
        return None
    text = str(value).strip()
    try:
        parsed = dt_util.parse_datetime(text)
    except ValueError:
        parsed = None
    if parsed is not None:
        return dt_util.as_local(parsed).date().isoformat()
    return text[:10] if re.match(r"\d{4}-\d{2}-\d{2}", text) else None


def short_key(key: str) -> bool:
    """Keys without a word of 3+ letters ("ei" for Eier): matched by whole words only."""
    return bool(key) and all(len(w) < 3 for w in key.split())


# words that make an "Eier" offer another product (chocolate eggs, egg liqueur, noodles)
_SHORT_KEY_OTHER = (
    "schoko",
    "ueberraschung",
    "kinder",
    "likoer",
    "nudel",
    "spaetzle",
    "zartbitter",
    "vollmilch",
    "oster",
    "marzipan",
    "nougat",
    "praline",
    "trueffel",
    "milka",
    "lindt",
    "ferrero",
    "salat",
    "creme",
    "waffel",
    "gummi",
    "zucker",
    "hohl",
    "fondant",
    "keks",
    "plaetzchen",
)
_COUNT_RE = re.compile(r"(\d+)\s*(?:stück|stueck|stk\b|st\.|st\b|er\b)", re.IGNORECASE)


def _parse_count(text: str | None) -> tuple[float, str] | None:
    """'10 Stück', '10er-Packung', '6 St.' -> (10, 'Stück') (1–100 pieces)."""
    match = _COUNT_RE.search(text or "")
    if match is None:
        return None
    count = float(match.group(1))
    return (count, "Stück") if 1 <= count <= 100 else None


def _short_key_matches(offer_text: str, key: str) -> bool:
    """'Frische Eier', 'Bio-Eier, 10 Stück' fit "ei"; 'Eierlikör', 'Eier-Nudeln',
    'Schoko-Eier', 'Kinder Überraschung Eier' or a 100-g bag do not (eggs are sold by count).
    """
    heads: set[str] = set()
    for word in offer_text.split():
        parts = fold(word).split()
        if parts:
            heads.add(_singular(parts[-1]))  # the head of "Bio-Eier" is "Eier"
    if not all(w in heads for w in key.split()):
        return False
    tokens = fold(offer_text).split()
    if any(t.startswith(_SHORT_KEY_OTHER) for t in tokens):
        return False
    pack = parse_pack(offer_text)
    return not (pack and pack[1] in ("g", "ml") and not _COUNT_RE.search(offer_text))


# written-out forms of the short words of keys ("Tiefkühl-Erbsen" for "TK-Erbsen",
# "haltbare Milch" for "H-Milch")
_SHORT_WORD_FORMS = {
    "tk": ("tiefkuehl", "tiefgekuehlt", "tiefgefroren"),
    "h": ("haltbar",),
}


def _short_word_found(tokens: list[str], word: str) -> bool:
    """A short word of a longer key ("wc" of "WC-Reiniger", "tk" of "TK-Erbsen") is a word
    of its own in the text (fold() splits "WC-Ente" into "wc ente"), or written out."""
    forms = _SHORT_WORD_FORMS.get(word, ())
    return any(t == word or (forms and t.startswith(forms)) for t in tokens)


def offer_matches(offer_text: str, key: str) -> bool:
    """True if an offer title fits an ingredient key ('haehnchenbrust' ~ 'Hähnchenbrustfilet').

    Every word of the key counts: a short one ("wc" of "wc reiniger") as a word of its
    own, so 'Geschirrreiniger' is no WC-Reiniger and 'Barbarie-Ente' no WC-Ente.
    """
    if not key:
        return False
    if short_key(key):
        return _short_key_matches(offer_text, key)
    tokens = [_singular(w) for w in fold(offer_text).split()]
    words = key.split()
    return all(
        _short_word_found(tokens, w) if len(w) < 3 else any(_token_match(t, w) for t in tokens)
        for w in words
    )


def key_only_as_modifier(text: str, key: str) -> bool:
    """True if every mention of a key word in a product name is the first part of a
    hyphenated compound naming another product: 'Butter-Spekulatius' or
    'Butter-Mandel-Spekulatius' for "butter", 'Kartoffel-Gratin' for "kartoffel" (fold()
    splits them into words that offer_matches() accepts), also a shortened compound
    ('Butter-, Krusten- oder Kochschinken'). Not 'Bio-Butter', 'Kräuter-/Knoblauchbutter'
    or 'H-Milch' (the key is the head)."""
    words = [w for w in key.split() if len(w) >= 3]
    for word in words:
        head_found = modifier_found = False
        for raw in re.split(r"[\s,;()]+", text or ""):
            parts = [fold(p).replace(" ", "") for p in re.split(r"[-/]+", raw) if p.strip()]
            parts = [p for p in parts if p]
            if not parts:
                continue
            if raw.endswith("-"):
                # "Butter-" of "Butter-, Krusten- oder Kochschinken": only a first part
                modifier_found = modifier_found or any(word in part for part in parts)
            elif _token_match(_singular(parts[-1]), word):
                head_found = True
            elif any(word in part for part in parts[:-1]):
                modifier_found = True
        if modifier_found and not head_found:
            return True
    return False


# what may follow an ingredient word inside a compound ("Hähnchenbrust|filet")
_ALLOWED_REST = (
    "filet",
    "fleisch",
    "stueck",
    "scheibe",
    "wuerfel",
    "streifen",
    "mix",
    "sorte",
    "schnitzel",
    "steak",
    "brust",
    "keule",
    "schenkel",
    "packung",
    "spiess",
    "ragout",
)
_PLURAL_REST = {"n", "e", "en", "s", "er", "nen"}


def _token_match(token: str, word: str) -> bool:
    """German compounds: the head is at the end ('Vollmilch' ~ 'milch', not 'Milchschokolade')."""
    if token == word or token.endswith(word):
        return True
    if token.startswith(word):
        rest = token[len(word) :]
        return rest in _PLURAL_REST or rest.startswith(_ALLOWED_REST)
    return False


# the first part of a compound that makes it another product ("Eis|kaffee", "Milch|kaffee",
# "Malz|kaffee"); other compounds are the same product ("Röst|kaffee", "Filter|kaffee")
_OTHER_PRODUCT_MODIFIERS = (
    "eis",
    "milch",
    "malz",
    "getreide",
    "gerste",
    "zichorie",
    "lupine",
    "dinkel",
    "kinder",
    "kokos",
    "mandel",
    "hafer",
    "soja",
    "reis",
    "butter",
    "schoko",
    "kakao",
)
# what may follow the key inside a compound of the same product ("Kaffee|bohnen",
# "Kaffee|pads"); else the compound is another product ("Kaffee|sahne", "Kaffee|filter")
_SAME_PRODUCT_REST = (*_ALLOWED_REST, "bohne", "pad", "kapsel", "pulver")


def _key_product_verdict(text: str, key: str) -> bool | None:
    """How a text names the key's product: True (the product: whole words or a compound of
    the same product), False (a compound naming another product), None (not mentioned)."""
    tokens = [_singular(w) for w in fold(text).split()]
    words = key.split()
    if all(w in tokens for w in words):
        return True
    if not all(_short_word_found(tokens, w) for w in words if len(w) < 3):
        return None  # "Geschirrreiniger" does not name "wc reiniger"
    mentioned = 0
    for word in [w for w in words if len(w) >= 3]:
        found = word in tokens
        for token in tokens:
            if token == word or word not in token:
                continue
            if token.endswith(word):
                modifier = token[: -len(word)]
                forms = {modifier, modifier[:-1] if modifier.endswith("s") else modifier}
                if any(
                    form.startswith(_OTHER_PRODUCT_MODIFIERS)
                    or form.endswith(_OTHER_PRODUCT_MODIFIERS)
                    for form in forms
                ):
                    return False  # "Eiskaffee", "Vollmilchkaffee"
                found = True  # "Röstkaffee", "Bohnenkaffee"
            elif token.startswith(word):
                rest = token[len(word) :]
                if rest not in _PLURAL_REST and not rest.startswith(_SAME_PRODUCT_REST):
                    return False  # "Kaffeesahne"
                found = True  # "Kaffeebohnen"
        mentioned += found
    if mentioned and mentioned == len([w for w in words if len(w) >= 3]):
        return True
    return None


def names_other_compound(text: str, key: str) -> bool:
    """True if a text names another product in a compound with the key ('Eiskaffee',
    'Kaffeesahne' for "kaffee"); False for the product itself or a text without the key."""
    return bool(key) and _key_product_verdict(text, key) is False


def names_key_product(product: str, key: str, description: str = "") -> bool:
    """True if an offer is of the key's product itself, not of a compound that
    offer_matches() accepts but that is another product.

    The product name decides when it names the key: 'Kaffee Crema, ganze Bohne',
    'Bio-Kaffee' or 'Röstkaffee' for "kaffee", not 'Eiskaffee', 'Milchkaffee' or
    'Kaffeesahne'. A brand name without it ('Krönung', 'Prodomo') is decided by the
    description the offer was matched with ('Röstkaffee, gemahlen').
    """
    if not key:
        return False
    if ingredient_key(product) == key:
        return True
    for text in (product, description, f"{product} {description}"):
        verdict = _key_product_verdict(text, key)
        if verdict is not None:
            return verdict
    return False


# the product name ends at a comma or a preposition: ALDI's "Apfelmus 360 g, Apfel" or
# "Bio-Gourmet Kapern 180 g, Olivenöl" (the variant follows the comma), "Wildlachsfilet in
# Blätterteig", "Thunfisch in Sonnenblumenöl", "Eier aus Freilandhaltung"
_HEAD_CUT_RE = re.compile(r",\s+|\s+(?:in|mit|aus|auf)\s+", re.IGNORECASE)


# a ready meal: "Wildlachsfilet in Blätterteig", "Lachs in Senf-Dill-Sauce", "Schnitzel
# mit Panade" is no Lachsfilet / Blätterteig / Schnitzel
_READY_MEAL_RE = re.compile(
    r"\s(?:in|im|mit)\s+(?:[\w-]+\s+)?[\w-]*(?:teig|sauce|soße|sosse|panade|kruste|mantel)\b",
    re.IGNORECASE,
)


# a group of products before the comma: ALDI's "Backzutaten, Backpulver 160 g"
_GROUP_HEADS = ("backzutaten", "zutaten", "sortiment", "spezialitaeten", "vorrat")


def product_head(product: str) -> str:
    """The product itself of an offer name, without its variant or what it comes in
    ('' for a ready meal)."""
    text = str(product or "")
    if _READY_MEAL_RE.search(text):
        return ""
    parts = _HEAD_CUT_RE.split(text, maxsplit=1)
    head = parts[0].strip()
    if len(parts) > 1 and fold(head) in _GROUP_HEADS:
        head = product_head(parts[1])  # "Backzutaten, Backpulver 160 g": Backpulver
    return head or text


# first parts of compounds that make the head another product: "Granatapfel" is no Apfel,
# "Kondensmilch" no Milch, "Erdnussbutter" no Butter, "Auftausalz" no Salz
_OTHER_COMPOUND_PARTS = frozenset(
    {
        "granat",
        "kondens",
        "auftau",
        "streu",
        "regenerier",
        "spuelmaschine",
        "erdnuss",
        "kakao",
        "shea",
        "kokos",
        "kokosnuss",
        "mandel",
        "hafer",
        "soja",
        "schoko",
        "schokolade",
        "bade",
        "dusch",
        "koerper",
        "sonnen",
        "reinigung",
        "gesicht",
    }
)


def other_compound(text: str, key: str) -> bool:
    """True if a key word is only named as the head of a compound of another product
    ('Granatäpfel' / 'Granatapfel' for "apfel", 'Kondensmilch' for "milch")."""
    tokens = [_singular(t) for t in fold(text).split()]
    for word in (w for w in key.split() if len(w) >= 3):
        if word in tokens:
            continue
        heads = [t for t in tokens if t.endswith(word) and t != word]
        if not heads and word.startswith("a"):
            # "Granatäpfel": the umlaut plural of "apfel"
            umlaut = f"ae{word[1:]}"
            heads = [t for t in tokens if t.endswith(umlaut) and t != umlaut]
            word = umlaut
        if heads and all(_compound_part(t[: -len(word)]) in _OTHER_COMPOUND_PARTS for t in heads):
            return True
    return False


def _compound_part(modifier: str) -> str:
    """The first part of a compound without its linking letters ('schokoladen' ->
    'schokolade', 'reinigungs' -> 'reinigung')."""
    if modifier in _OTHER_COMPOUND_PARTS:
        return modifier
    for link in ("s", "n", "es", "en"):
        if modifier.endswith(link) and modifier[: -len(link)] in _OTHER_COMPOUND_PARTS:
            return modifier[: -len(link)]
    return modifier


# kinds of products that a food word only flavours or fills: "Skyr Drink Erdbeere
# Himbeere", "Almighurt Erdbeere", "Ingwer Shots", "Alioli Knoblauch Dip", "Mikado Milch
# Schokolade", "Limonaden" + "Zitrone", "Petz Gefüllte Paprika" (a ready meal)
_CARRIER_HEADS = (
    "drink",
    "shot",
    "dip",
    "schokolade",
    "riegel",
    "limonade",
    "ghurt",
    "jogurt",
    "yogurt",
    "skyr",
    "quark",
    "pudding",
    "saft",
    "schorle",
    "nektar",
    "sirup",
    "smoothie",
    "shake",
    "likoer",
    "bonbon",
    "chip",
    "keks",
    "kuchen",
    "torte",
    "aufstrich",
    "creme",
    "sauce",
    "sosse",
    "dressing",
    "tee",
)
_CARRIER_PREFIXES = ("gefuellt",)


def _word_forms(token: str) -> set[str]:
    forms = {token, _singular(token)}
    for ending in ("s", "e", "n", "en"):
        if token.endswith(ending) and len(token) > len(ending) + 2:
            forms.add(token[: -len(ending)])
    return forms


def flavour_only(text: str, key: str) -> bool:
    """True if a text names a product of another kind that the key's food only flavours
    or fills ('Skyr Drink Erdbeere' for "erdbeere", 'Ingwer Shots' for "ingwer"); False
    when the key is that kind itself ('Naturjoghurt' for "joghurt")."""
    words = [w for w in key.split() if len(w) >= 3]
    if not words:
        return False
    for token in fold(text).split():
        forms = _word_forms(token)
        carrier = (
            token == "eis"
            or token.startswith(_CARRIER_PREFIXES)
            or any(f.endswith(_CARRIER_HEADS) for f in forms)
        )
        if carrier and not any(
            f == w or f.endswith(w) or w.endswith(f) for w in words for f in forms
        ):
            return True
    return False


def _brand_name(raw: dict[str, Any]) -> str:
    """The offer's brand; marktguru's placeholder of unbranded offers becomes ''."""
    brand_info = raw.get("brand") or {}
    brand = str(brand_info.get("name") or "")
    if _NO_BRAND in (brand.strip().lower(), str(brand_info.get("uniqueName") or "")):
        return ""
    return brand


def _reference_price(raw: dict[str, Any]) -> tuple[float | None, str | None]:
    """(price per g / ml / Stück, base unit) from referencePrice and unit.shortName."""
    unit = ((raw.get("unit") or {}).get("shortName") or "").lower()
    reference = raw.get("referencePrice")
    if not reference:
        return None, None
    value = float(reference)
    if unit in ("kg", "kilogramm"):
        return value / 1000, "g"
    if unit in ("l", "liter"):
        return value / 1000, "ml"
    if unit in ("100g", "100 g"):
        return value / 100, "g"
    if unit in ("stück", "stk", "st", "stk."):
        return value, "Stück"
    return None, None


def _title(brand: str, product: str) -> str:
    return (
        f"{brand} {product}".strip() if brand and brand.lower() not in product.lower() else product
    )


def normalize_marktguru(raw: dict[str, Any], query: str = "") -> dict[str, Any] | None:
    """Convert a marktguru offer of the search (detailed format) into the internal format."""
    try:
        offer_id = raw.get("id")
        product = (raw.get("product") or {}).get("name") or ""
        brand = _brand_name(raw)
        advertisers = raw.get("advertisers") or []
        advertiser = advertisers[0] if advertisers else {}
        price = raw.get("price")
        if price is None or not product:
            return None
        validity = (raw.get("validityDates") or [{}])[0]
        description = raw.get("description") or ""
        unit_price, base_unit = _reference_price(raw)
        pack = parse_pack(description) or parse_pack(product)
        if pack is None and base_unit in (None, "Stück"):
            # sold by count ("Eier Größe M (53-63 g), 10 Stück", "10er-Packung")
            pack = _parse_count(description) or _parse_count(product)
        title = _title(brand, product)
        return {
            "id": f"mg_{offer_id}",
            "title": title,
            "product": product,
            "brand": brand,
            "description": description[:200],
            "store": advertiser.get("name") or "",
            "store_id": advertiser.get("uniqueName") or "",
            "retailer": retailer_for_store_id(advertiser.get("uniqueName")),
            "price": round(float(price), 2),
            "old_price": round(float(raw["oldPrice"]), 2) if raw.get("oldPrice") else None,
            "unit_price": unit_price,
            "base_unit": base_unit,
            "pack_amount": pack[0] if pack else None,
            "pack_unit": pack[1] if pack else None,
            "valid_from": _date(validity.get("from")),
            "valid_to": _date(validity.get("to")),
            "image": IMAGE_URL.format(id=offer_id) if offer_id else None,
            "loyalty": bool(raw.get("requiresLoyalityMembership")),
            "source": "marktguru",
            "query": query,
        }
    except (TypeError, ValueError, AttributeError, IndexError) as err:
        _LOGGER.debug("Could not parse offer %s: %s", raw, err)
        return None


# notes of the catalog descriptions (11/2026): "HINWEIS: MIT LIDL PLUS APP 1.59 € 190g",
# "MIT ROSSMANN APP COUPON 1.- €", "MIT APP 0,10 € REWE BONUS", "NUR ONLINE VERFÜGBAR",
# "Normalpreis: 1.35", "Ohne Penny App 1.79", "Einzelpreis: 0.25", "zzgl. 3.10 Pfand"
_PRICE = r"(\d+[.,](?:\d{1,2}|-))"
_HINT_RE = re.compile(r"\bhinweis\s*:\s*", re.IGNORECASE)
_BONUS_RE = re.compile(
    rf"\bmit\s+app\s+{_PRICE}\s*€\s*((?:[a-zäöü]+\s+){{0,2}}?)bonus\b", re.IGNORECASE
)
_APP_PRICE_RE = re.compile(
    rf"\bmit\s+((?:[a-zäöü]+\s+){{0,2}}?)app(?:[\s-]+coupon)?\s*:?\s*{_PRICE}\s*€", re.IGNORECASE
)
_APP_HINT_RE = re.compile(r"\bmit\s+((?:[a-zäöü]+\s+){0,2}?)app(?:[\s-]+coupon)?\b", re.IGNORECASE)
_WITHOUT_APP_RE = re.compile(
    rf"\bohne\s+(?:[a-zäöü]+\s+){{0,2}}?app\s*:?\s*{_PRICE}\s*€?", re.IGNORECASE
)
_NORMAL_PRICE_RE = re.compile(rf"\bnormalpreis\s*:?\s*{_PRICE}\s*€?", re.IGNORECASE)
_SINGLE_PRICE_RE = re.compile(rf"[,;]?\s*\beinzelpreis\s*:?\s*{_PRICE}\s*€?", re.IGNORECASE)
_ONLINE_RE = re.compile(r"\bnur\s+online\s+verf(?:ü|ue)gbar\b", re.IGNORECASE)
_DEPOSIT_RE = re.compile(rf"(?:\bzzgl\.?|\+)\s*(?:€\s*)?{_PRICE}\s*(?:€\s*)?pfand\b", re.IGNORECASE)
_PROSPEKT_RE = re.compile(r"\bdetails\s+im\s+prospekt\b", re.IGNORECASE)


def _price_value(text: str) -> float | None:
    """'1.59' / '1,59' / '1.-' -> 1.59 / 1.0 (None outside 0,01–1000 €)."""
    try:
        value = float(text.replace(",", ".").replace(".-", ".0").rstrip("-"))
    except ValueError:
        return None
    return round(value, 2) if 0.01 <= value <= 1000 else None


def parse_offer_notes(description: str | None) -> dict[str, Any]:
    """The notes in a catalog description and the description without them.

    {text (description without the notes), regular_price ("Normalpreis: 1.35"; never a
    "UVP" or Netto's "Einzelpreis" of one piece of a multipack), app_price ("MIT LIDL PLUS
    APP 1.59 €": the main price applies to everyone), app_only (an app hint without an
    amount, or "Ohne Penny App 1.79": the main price needs the app), without_app (the
    price without the app), bonus ("MIT APP 0,10 € REWE BONUS"), online_only ("NUR
    ONLINE VERFÜGBAR"), deposit (EUR)}.
    """
    text = str(description or "")
    notes: dict[str, Any] = {
        "regular_price": None,
        "app_price": None,
        "app_only": False,
        "without_app": None,
        "bonus": None,
        "online_only": False,
        "deposit": None,
    }

    if match := _BONUS_RE.search(text):
        notes["bonus"] = _price_value(match.group(1))
        text = _BONUS_RE.sub(" ", text, count=1)
    if match := _APP_PRICE_RE.search(text):
        notes["app_price"] = _price_value(match.group(2))
        text = _APP_PRICE_RE.sub(" ", text, count=1)
    if match := _WITHOUT_APP_RE.search(text):
        notes["without_app"] = _price_value(match.group(1))
        notes["app_only"] = True
        text = _WITHOUT_APP_RE.sub(" ", text, count=1)
    if _APP_HINT_RE.search(text):
        notes["app_only"] = notes["app_only"] or notes["app_price"] is None
        text = _APP_HINT_RE.sub(" ", text)
    if match := _NORMAL_PRICE_RE.search(text):
        notes["regular_price"] = _price_value(match.group(1))
        text = _NORMAL_PRICE_RE.sub(" ", text)
    if match := _DEPOSIT_RE.search(text):
        notes["deposit"] = _price_value(match.group(1))
        text = _DEPOSIT_RE.sub(" ", text)
    if _ONLINE_RE.search(text):
        notes["online_only"] = True
        text = _ONLINE_RE.sub(" ", text)
    text = _SINGLE_PRICE_RE.sub(" ", text)
    text = _PROSPEKT_RE.sub(" ", _HINT_RE.sub(" ", text))
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*([.,;])(?:\s*[.,;])+", r"\1", text).strip(" ,.;")
    notes["text"] = text
    return notes


def _loyalty_note(notes: dict[str, Any]) -> str | None:
    """German note of the app price / bonus ('mit App 1,59 €')."""
    parts: list[str] = []
    if notes.get("app_price"):
        parts.append(f"mit App {format_eur(notes['app_price'])}")
    if notes.get("app_only"):
        text = "Preis nur mit App"
        if notes.get("without_app"):
            text += f", ohne App {format_eur(notes['without_app'])}"
        parts.append(text)
    if notes.get("bonus"):
        parts.append(f"mit App {format_eur(notes['bonus'])} Bonus")
    return " · ".join(parts) or None


_SHORT_UNITS = {"kg": (1000.0, "g"), "l": (1000.0, "ml"), "stk": (1.0, "Stück")}


def _short_pack(
    raw: dict[str, Any], price: float, text: str, product: str
) -> tuple[float, str] | None:
    """Pack size of a catalog offer: the description ('Je 500 g'), the product name, the
    stated volume x quantity when it fits price / referencePrice (marktguru stores whole
    numbers only: 1.5 kg is volume 1), else price / referencePrice, else a count."""
    pack = parse_pack(text) or parse_pack(product)
    if pack is not None:
        return pack
    unit = str((raw.get("unit") or {}).get("shortName") or "").lower()
    factor, base = _SHORT_UNITS.get(unit, (0.0, ""))
    try:
        reference = float(raw.get("referencePrice") or 0)
        volume = float(raw.get("volume") or 0) * float(raw.get("quantity") or 1)
    except (TypeError, ValueError):
        reference, volume = 0.0, 0.0
    derived = price / reference if reference > 0 else None
    if factor and volume > 0 and (derived is None or abs(volume - derived) <= 0.08 * volume):
        pack = (round(volume * factor, 3), base)
    elif factor and derived and (base != "Stück" or reference >= 0.1):
        amount = derived * factor
        pack = (float(max(1, round(amount))) if base == "Stück" else float(round(amount)), base)
    if pack is None:
        pack = _parse_count(text) or _parse_count(product)
    if pack is not None and pack[1] in ("g", "ml", "Stück") and not plausible_pack(*pack):
        return None
    return pack


def normalize_marktguru_short(raw: dict[str, Any], query: str = "") -> dict[str, Any] | None:
    """Convert an offer of a marktguru chain catalog (short format) into the offer format.

    Short format: {id, description, product: {name}, retailer: {id, name, uniqueName},
    brand: {name, uniqueName}, unit: {shortName}, price, oldPrice (0.0 = none),
    referencePrice, volume, quantity, validFrom, validTo}. The description notes become
    regular_price ("Normalpreis"), app_price / loyalty / loyalty_note (app prices, REWE
    Bonus), online_only and deposit; valid_from / valid_to are local dates. The detailed
    format of the search (advertisers, validityDates) is read as well.
    """
    try:
        offer_id = raw.get("id")
        product = re.sub(r"\s+", " ", str((raw.get("product") or {}).get("name") or "")).strip()
        price = raw.get("price")
        if price is None or not product or offer_id is None:
            return None
        price = round(float(price), 2)
        if price <= 0:
            return None
        retailer_info = raw.get("retailer") or ((raw.get("advertisers") or [{}])[0]) or {}
        unique = str(retailer_info.get("uniqueName") or "")
        brand = _brand_name(raw)
        notes = parse_offer_notes(raw.get("description"))
        text = notes["text"]
        unit_price, base_unit = _reference_price(raw)
        pack = _short_pack(raw, price, text, product)
        validity = (raw.get("validityDates") or [{}])[0] if "validFrom" not in raw else {}
        old_price = raw.get("oldPrice")
        old = round(float(old_price), 2) if old_price else None
        regular = notes["regular_price"]
        return {
            "id": f"mg_{offer_id}",
            "title": _title(brand, product),
            "product": product,
            "brand": brand,
            "description": text[:200],
            "store": str(retailer_info.get("name") or ""),
            "store_id": unique,
            "retailer": retailer_for_store_id(unique),
            "price": price,
            "old_price": old if old and old > price else None,
            "regular_price": regular if regular and regular > price else None,
            "app_price": notes["app_price"]
            if notes["app_price"] and notes["app_price"] < price
            else None,
            "loyalty": bool(notes["app_only"] or raw.get("requiresLoyalityMembership")),
            "loyalty_note": _loyalty_note(notes),
            "online_only": notes["online_only"],
            "deposit": notes["deposit"],
            "unit_price": unit_price,
            "base_unit": base_unit,
            "pack_amount": pack[0] if pack else None,
            "pack_unit": pack[1] if pack else None,
            "valid_from": _date(raw.get("validFrom") or validity.get("from")),
            "valid_to": _date(raw.get("validTo") or validity.get("to")),
            "image": IMAGE_URL.format(id=offer_id),
            "source": "marktguru",
            "query": query,
        }
    except (TypeError, ValueError, AttributeError, IndexError) as err:
        _LOGGER.debug("Could not parse catalog offer %s: %s", raw, err)
        return None


def store_allowed(store_id: str, allowed: list[str]) -> bool:
    """Store filter (also matches regional variants like 'edeka-suedwest')."""
    if not allowed:
        return True
    return any(store_id == s or store_id.startswith(f"{s}-") for s in allowed)


class MarktguruClient:
    """Minimal client for the marktguru.de offer search."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize."""
        self._session = async_get_clientsession(hass)
        self._keys: tuple[str, str] | None = None

    async def _async_keys(self, force: bool = False) -> tuple[str, str]:
        if self._keys and not force:
            return self._keys
        try:
            async with self._session.get(
                MARKTGURU_HOME,
                headers={"User-Agent": _USER_AGENT, "Accept-Language": "de-DE,de;q=0.9"},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status in (401, 403, 429):
                    raise OfferBlocked(f"marktguru.de lehnt ab (HTTP {resp.status})")
                if resp.status >= 400:
                    raise OfferError(f"marktguru.de antwortet mit HTTP {resp.status}")
                page = await resp.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise OfferError(f"marktguru.de nicht erreichbar: {err}") from err
        for block in _CONFIG_RE.findall(page):
            try:
                data = json.loads(block)
            except ValueError:
                continue
            config = data.get("config") if isinstance(data, dict) else None
            if isinstance(config, dict) and config.get("apiKey") and config.get("clientKey"):
                self._keys = (config["apiKey"], config["clientKey"])
                return self._keys
        raise OfferError("Zugangsdaten auf marktguru.de nicht gefunden (Seite geändert?)")

    async def async_search(
        self, query: str, zip_code: str, limit: int = 60, retailers: list[int] | None = None
    ) -> list[dict[str, Any]]:
        """Search offers near a zip code (retailers: numeric marktguru ids of the chain
        variants to search, from the catalog's discovery; None = all)."""
        params: dict[str, Any] = {
            "as": "web",
            "q": query,
            "zipCode": zip_code,
            "limit": limit,
            "offset": 0,
        }
        if retailers:
            params["retailers"] = ",".join(str(r) for r in retailers)
        for attempt in range(2):
            api_key, client_key = await self._async_keys(force=attempt > 0)
            try:
                async with self._session.get(
                    f"{MARKTGURU_API}/offers/search",
                    params=params,
                    headers={
                        "x-apikey": api_key,
                        "x-clientkey": client_key,
                        "User-Agent": _USER_AGENT,
                        "Accept": "application/json",
                    },
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status in (401, 403) and attempt == 0:
                        continue  # the keys changed: read them again once
                    if resp.status in (401, 403, 429):
                        raise OfferBlocked(
                            f"Angebotssuche: marktguru lehnt ab (HTTP {resp.status})"
                        )
                    if resp.status >= 400:
                        raise OfferError(f"Angebotssuche: HTTP {resp.status}")
                    if "html" in str(resp.headers.get("Content-Type") or "").lower():
                        raise OfferBlocked("Angebotssuche: marktguru antwortet mit einer Webseite")
                    data = await resp.json(content_type=None)
            except (aiohttp.ClientError, TimeoutError, ValueError) as err:
                raise OfferError(f"Angebotssuche fehlgeschlagen: {err}") from err
            results = data.get("results") if isinstance(data, dict) else None
            return results if isinstance(results, list) else []
        raise OfferBlocked("Angebotssuche: Zugriff verweigert")


async def async_fetch_offers(
    hass: HomeAssistant,
    terms: list[tuple[str, str]],
    zip_code: str,
    stores: list[str],
    delay: float | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch offers for (search term, ingredient key) pairs near one zip code (1.2 API)."""
    return await async_fetch_target_offers(hass, terms, [(zip_code, stores)], delay)


async def async_fetch_target_offers(
    hass: HomeAssistant,
    terms: list[tuple[str, str]],
    targets: list[tuple[str, list[str]]],
    delay: float | None = None,
    extra_limit: int | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch offers for several (zip code, [retailers]) targets. Returns (offers, errors).

    The first target (main branch) is searched with all terms (up to MAX_QUERIES), further
    targets with the first EXTRA_TARGET_QUERIES terms. Offers found at several zip codes
    are merged (keys and "zip_codes" collected). Every offer has "retailer" and
    "zip_codes". Stops early when the source is unavailable.
    """
    client = MarktguruClient(hass)
    offers: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    delay = REQUEST_DELAY if delay is None else delay
    extra_limit = EXTRA_TARGET_QUERIES if extra_limit is None else extra_limit
    several = len(targets) > 1
    requests = 0
    succeeded = False
    for position, (zip_code, stores) in enumerate(targets):
        target_terms = terms if position == 0 else terms[:extra_limit]
        target_errors = 0
        unavailable = False
        for index, (term, key) in enumerate(target_terms):
            if requests and delay > 0:
                await asyncio.sleep(delay)  # be polite to the web site
            requests += 1
            try:
                raw_offers = await client.async_search(term, zip_code)
            except OfferError as err:
                errors.append(f"{term} ({zip_code}): {err}" if several else f"{term}: {err}")
                target_errors += 1
                if index == 0 or target_errors >= 3:
                    unavailable = not succeeded  # nothing worked so far: stop completely
                    break
                continue
            succeeded = True
            for raw in raw_offers:
                offer = normalize_marktguru(raw, term)
                if offer is None or not store_allowed(offer["store_id"], stores):
                    continue
                if not offer_matches(f"{offer['product']} {offer['description']}", key):
                    continue
                _merge_offer(offers, offer, key, zip_code)
        if unavailable:
            break
    return list(offers.values()), errors


def _merge_offer(
    offers: dict[str, dict[str, Any]], offer: dict[str, Any], key: str | None, zip_code: str
) -> None:
    existing = offers.get(offer["id"])
    if existing is None:
        existing = offers[offer["id"]] = {**offer, "keys": [], "zip_codes": []}
    if key and key not in existing["keys"]:
        existing["keys"].append(key)
    if zip_code not in existing["zip_codes"]:
        existing["zip_codes"].append(zip_code)


async def async_search_target_offers(
    hass: HomeAssistant,
    query: str,
    targets: list[tuple[str, list[str]]],
    delay: float | None = None,
    retailer_ids: dict[str, list[int]] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Live search of one product at every target (no ingredient matching).

    retailer_ids: {zip code: numeric marktguru ids of the chain variants there} (only these
    chains are searched; a postcode without ids searches all and filters afterwards).
    Raises OfferBlocked when marktguru refuses (nothing more is asked).
    """
    client = MarktguruClient(hass)
    offers: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    delay = REQUEST_DELAY if delay is None else delay
    for position, (zip_code, stores) in enumerate(targets):
        if position and delay > 0:
            await asyncio.sleep(delay)
        try:
            raw_offers = await client.async_search(
                query, zip_code, retailers=(retailer_ids or {}).get(zip_code) or None
            )
        except OfferBlocked:
            raise
        except OfferError as err:
            errors.append(str(err))
            if not offers:
                break  # source unavailable
            continue
        for raw in raw_offers:
            offer = normalize_marktguru(raw, query)
            if offer is not None and store_allowed(offer["store_id"], stores):
                _merge_offer(offers, offer, None, zip_code)
    for offer in offers.values():
        if not offer["keys"]:
            del offer["keys"]
    return list(offers.values()), errors


def leaflet_week_end(day: date) -> date:
    """End of the leaflet week of a day: the coming Saturday (the day itself on a Saturday).

    Offers entered without an end date end then, they never count forever.
    """
    return day + timedelta(days=(5 - day.weekday()) % 7)


def manual_offer(
    product: str,
    store: str,
    price: float,
    pack_text: str | None = None,
    valid_from: date | None = None,
    valid_to: date | None = None,
    old_price: float | None = None,
) -> dict[str, Any]:
    """Create an offer entered by the user."""
    pack = parse_pack_text(pack_text) or parse_pack(product)
    key = ingredient_key(product)
    stamp = int(datetime.now().timestamp() * 1000)
    return {
        "id": f"man_{stamp}",
        "title": product.strip(),
        "product": product.strip(),
        "brand": "",
        "description": pack_text or "",
        "store": store.strip(),
        "store_id": fold(store).replace(" ", "-"),
        "price": round(float(price), 2),
        "old_price": round(float(old_price), 2) if old_price else None,
        "unit_price": None,
        "base_unit": None,
        "pack_amount": pack[0] if pack else None,
        "pack_unit": pack[1] if pack else None,
        "valid_from": valid_from.isoformat() if valid_from else None,
        "valid_to": valid_to.isoformat() if valid_to else None,
        "image": None,
        "loyalty": False,
        "source": "manual",
        "query": product,
        "keys": [key] if key else [],
    }


async def async_refresh_offers(
    hass: HomeAssistant, manager: Any, force: bool = True
) -> dict[str, Any]:
    """Refresh the offers (1.4: the offer catalog of the saved stores, catalog.py).

    The 1.3 search per ingredient is replaced by the catalog of every saved store (EDEKA /
    ALDI SÜD directly, marktguru when enabled) matched locally with the ingredients.
    force=True (service, button) at most once per hour unless the stores changed;
    force=False only when the catalog is stale. Only one refresh runs at a time (tied to
    the config entry). Returns the offers meta (status, errors, count, targets, learned,
    catalog).
    """
    from .catalog import async_refresh_catalog  # the catalog imports this module

    return await async_refresh_catalog(hass, manager, force=force)
