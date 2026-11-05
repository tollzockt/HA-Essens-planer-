"""Supermarket chains (retailers) and how to recognize them.

Pure Python (no Home Assistant imports). Retailer ids are the marktguru advertiser ids
("aldi-sued", "lidl", "netto-marken-discount" …); regional marktguru variants such as
"edeka-suedwest" map to their chain by prefix.
"""

from __future__ import annotations

import re
from typing import Any

from .ingredients import fold

ALDI_SUED = "aldi-sued"
ALDI_NORD = "aldi-nord"

RETAILERS: dict[str, dict[str, Any]] = {
    ALDI_SUED: {
        "name": "Aldi Süd",
        "aliases": ["aldi sued", "aldi sud", "aldi süd", "aldi-sued", "aldi-süd", "aldisued"],
        "osm": re.compile(r"\baldi ?(sued|sud)\b"),
        "wikidata": ["Q41171672"],
    },
    ALDI_NORD: {
        "name": "Aldi Nord",
        "aliases": ["aldi nord", "aldi-nord", "aldinord"],
        "osm": re.compile(r"\baldi ?nord\b"),
        "wikidata": ["Q41171373"],
    },
    "lidl": {
        "name": "Lidl",
        "aliases": ["lidl"],
        "osm": re.compile(r"\blidl\b"),
        "wikidata": ["Q151954"],
    },
    "rewe": {
        "name": "REWE",
        "aliases": ["rewe", "rewe markt", "rewe city", "rewe center", "rewe to go"],
        "osm": re.compile(r"\brewe\b"),
        "wikidata": ["Q16968817"],
    },
    "edeka": {
        "name": "EDEKA",
        "aliases": ["edeka", "edeka center", "e center", "e-center", "e aktiv markt", "e neukauf"],
        "osm": re.compile(r"\b(edeka|e ?center|e aktiv markt|e neukauf)\b"),
        "wikidata": ["Q701755"],
    },
    "penny": {
        "name": "Penny",
        "aliases": ["penny", "penny markt"],
        "osm": re.compile(r"\bpenny\b"),
        "wikidata": ["Q284688"],
    },
    "netto-marken-discount": {
        "name": "Netto",
        "aliases": ["netto", "netto marken discount", "netto marken-discount", "netto md"],
        "osm": re.compile(r"\bnetto\b"),
        "wikidata": ["Q879858"],
    },
    "kaufland": {
        "name": "Kaufland",
        "aliases": ["kaufland"],
        "osm": re.compile(r"\bkaufland\b"),
        "wikidata": ["Q685967"],
    },
    "norma": {
        "name": "Norma",
        "aliases": ["norma"],
        "osm": re.compile(r"\bnorma\b"),
        "wikidata": ["Q450180"],
    },
    "globus": {
        "name": "Globus",
        "aliases": ["globus", "globus sb warenhaus"],
        "osm": re.compile(r"\bglobus\b"),
        "wikidata": ["Q457503"],
    },
    "marktkauf": {
        "name": "Marktkauf",
        "aliases": ["marktkauf"],
        "osm": re.compile(r"\bmarktkauf\b"),
        "wikidata": ["Q1533254"],
    },
}

# display names (marktguru ids), also used by the options flow
STORES: dict[str, str] = {rid: info["name"] for rid, info in RETAILERS.items()}
DEFAULT_STORES: list[str] = [
    "aldi-sued",
    "aldi-nord",
    "lidl",
    "rewe",
    "edeka",
    "penny",
    "netto-marken-discount",
    "kaufland",
]

# chains that look like a known one but are a different company
# (Netto ApS "mit dem Scottie" is not Netto Marken-Discount)
_OTHER_WIKIDATA = {"Q552652"}

_GENERIC_ALDI = "aldi"
_ALDI_SUED_PREFIXES = {"40", "41", "42", "46", "47", *(str(n) for n in range(50, 58))}
_ALDI_NORD_PREFIXES = {"44", "45", "48", "49", "58", "59"}
_OSM_TEXT_TAGS = ("brand", "name", "operator", "brand:de", "name:de")


def _build_aliases() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for rid, info in RETAILERS.items():
        for text in [rid, info["name"], *info["aliases"]]:
            key = fold(text)
            if key:
                aliases.setdefault(key, rid)
    return aliases


_ALIASES = _build_aliases()
# longest first so "aldi sued" wins over "aldi" and "netto marken discount" over "netto"
_ALIASES_BY_LENGTH = sorted(_ALIASES, key=len, reverse=True)
_WIKIDATA = {qid: rid for rid, info in RETAILERS.items() for qid in info["wikidata"]}


def retailer_name(retailer: str | None) -> str:
    """Display name of a retailer id ('aldi-sued' -> 'Aldi Süd'); unknown ids unchanged."""
    if not retailer:
        return ""
    info = RETAILERS.get(retailer)
    return info["name"] if info else retailer


def aldi_for_postcode(postcode: str | None) -> str | None:
    """Guess Aldi Süd / Aldi Nord from a German postcode (None if undecidable)."""
    digits = re.sub(r"\D", "", str(postcode or ""))
    if len(digits) < 2:
        return None
    prefix = digits[:2]
    if prefix in _ALDI_SUED_PREFIXES:
        return ALDI_SUED
    if prefix in _ALDI_NORD_PREFIXES:
        return ALDI_NORD
    if digits[0] in "0123":
        return ALDI_NORD
    if digits[0] in "6789":
        return ALDI_SUED
    return None


def _resolve_aldi(selected: list[str] | None, zip_code: str | None) -> str | None:
    variants = [r for r in (selected or []) if r in (ALDI_SUED, ALDI_NORD)]
    if len(set(variants)) == 1:
        return variants[0]
    return aldi_for_postcode(zip_code)


def _alias_match(folded: str) -> str | None:
    """Alias id for a folded text: exact, else the longest alias contained as whole words."""
    if folded in _ALIASES:
        return _ALIASES[folded]
    padded = f" {folded} "
    for alias in _ALIASES_BY_LENGTH:
        if f" {alias} " in padded:
            return _ALIASES[alias]
    return None


def resolve_retailer(
    text: str | None, selected: list[str] | None = None, zip_code: str | None = None
) -> str | None:
    """Retailer id for a store name or id ('Aldi Süd', 'aldi-sued', 'Netto', 'rewe city').

    A plain 'Aldi' becomes the selected Aldi variant (if exactly one is selected), else the
    variant guessed from the zip code, else None.
    """
    if not text:
        return None
    raw = str(text).strip().lower()
    if raw in RETAILERS:
        return raw
    if by_id := retailer_for_store_id(raw):
        return by_id
    folded = fold(str(text))
    if not folded:
        return None
    if folded == _GENERIC_ALDI:
        return _resolve_aldi(selected, zip_code)
    found = _alias_match(folded)
    if found:
        return found
    if re.search(rf"\b{_GENERIC_ALDI}\b", folded):
        return _resolve_aldi(selected, zip_code)
    return None


def retailer_for_store_id(store_id: str | None) -> str | None:
    """Retailer of a marktguru advertiser id (incl. regional variants like 'edeka-suedwest')."""
    if not store_id:
        return None
    value = str(store_id).strip().lower()
    if value in RETAILERS:
        return value
    for rid in sorted(RETAILERS, key=len, reverse=True):
        if value.startswith(f"{rid}-"):
            return rid
    return None


def retailer_for_osm(tags: dict[str, Any], postcode: str | None = None) -> tuple[str | None, bool]:
    """Retailer of an OpenStreetMap shop. Returns (retailer id | None, guessed).

    Order: brand:wikidata, then brand/name/operator text, then (for a plain "Aldi") the
    postcode heuristic. guessed is True whenever a heuristic decided; (None, True) means
    "an Aldi, but the variant could not be determined".
    """
    tags = tags or {}
    postcode = postcode or tags.get("addr:postcode")
    for qid in str(tags.get("brand:wikidata") or "").replace(",", ";").split(";"):
        qid = qid.strip()
        if qid in _OTHER_WIKIDATA:
            return None, False
        if qid in _WIKIDATA:
            return _WIKIDATA[qid], False
    texts = [fold(str(tags[t])) for t in _OSM_TEXT_TAGS if tags.get(t)]
    generic_aldi = False
    for text in texts:
        for rid, info in RETAILERS.items():
            if info["osm"].search(text):
                # plain "Netto" could also be the Danish Netto
                guessed = rid == "netto-marken-discount" and "marken" not in text
                return rid, guessed
        if re.search(rf"\b{_GENERIC_ALDI}\b", text):
            generic_aldi = True
    if generic_aldi:
        return aldi_for_postcode(postcode), True
    return None, False


def _candidates(value: str | None) -> set[str]:
    if not value:
        return set()
    if found := resolve_retailer(value):
        return {found}
    folded = fold(str(value))
    if folded == _GENERIC_ALDI or re.search(rf"\b{_GENERIC_ALDI}\b", folded):
        return {ALDI_SUED, ALDI_NORD}
    return set()


def retailer_matches(a: str | None, b: str | None) -> bool:
    """True if two store texts/ids mean the same retailer (a plain 'Aldi' matches both)."""
    return bool(_candidates(a) & _candidates(b))
