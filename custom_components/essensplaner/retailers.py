"""Supermarket and drugstore chains (retailers) and how to recognize them.

Pure Python (no Home Assistant imports). Retailer ids are the marktguru advertiser ids
("aldi-sued", "lidl", "netto-marken-discount", "rossmann" …); regional marktguru variants
such as "edeka-suedwest" map to their chain by prefix. Every retailer has a kind:
"grocery" (supermarkets, discounters) or "drugstore" (Rossmann, dm, Müller, Budni).
"""

from __future__ import annotations

import re
from typing import Any

from .ingredients import fold

ALDI_SUED = "aldi-sued"
ALDI_NORD = "aldi-nord"

KIND_GROCERY = "grocery"
KIND_DRUGSTORE = "drugstore"
RETAILER_KINDS = (KIND_GROCERY, KIND_DRUGSTORE)
# OpenStreetMap shop types of each kind: a chain name only counts on a shop of its kind
# ("Müller" also names lighting shops, opticians, bakeries …)
SHOP_TYPES: dict[str, tuple[str, ...]] = {
    KIND_GROCERY: ("supermarket", "discount"),
    KIND_DRUGSTORE: ("chemist",),
}

RETAILERS: dict[str, dict[str, Any]] = {
    ALDI_SUED: {
        "name": "Aldi Süd",
        "kind": KIND_GROCERY,
        "aliases": ["aldi sued", "aldi sud", "aldi süd", "aldi-sued", "aldi-süd", "aldisued"],
        "osm": re.compile(r"\baldi ?(sued|sud)\b"),
        "wikidata": ["Q41171672"],
    },
    ALDI_NORD: {
        "name": "Aldi Nord",
        "kind": KIND_GROCERY,
        "aliases": ["aldi nord", "aldi-nord", "aldinord"],
        "osm": re.compile(r"\baldi ?nord\b"),
        "wikidata": ["Q41171373"],
    },
    "lidl": {
        "name": "Lidl",
        "kind": KIND_GROCERY,
        "aliases": ["lidl"],
        "osm": re.compile(r"\blidl\b"),
        "wikidata": ["Q151954"],
    },
    "rewe": {
        "name": "REWE",
        "kind": KIND_GROCERY,
        "aliases": ["rewe", "rewe markt", "rewe city", "rewe center", "rewe to go"],
        "osm": re.compile(r"\brewe\b"),
        "wikidata": ["Q16968817"],
    },
    "edeka": {
        "name": "EDEKA",
        "kind": KIND_GROCERY,
        "aliases": ["edeka", "edeka center", "e center", "e-center", "e aktiv markt", "e neukauf"],
        "osm": re.compile(r"\b(edeka|e ?center|e aktiv markt|e neukauf)\b"),
        "wikidata": ["Q701755"],
    },
    "penny": {
        "name": "Penny",
        "kind": KIND_GROCERY,
        "aliases": ["penny", "penny markt"],
        "osm": re.compile(r"\bpenny\b"),
        "wikidata": ["Q284688"],
    },
    "netto-marken-discount": {
        "name": "Netto",
        "kind": KIND_GROCERY,
        "aliases": ["netto", "netto marken discount", "netto marken-discount", "netto md"],
        "osm": re.compile(r"\bnetto\b"),
        "wikidata": ["Q879858"],
    },
    "kaufland": {
        "name": "Kaufland",
        "kind": KIND_GROCERY,
        "aliases": ["kaufland"],
        "osm": re.compile(r"\bkaufland\b"),
        "wikidata": ["Q685967"],
    },
    "norma": {
        "name": "Norma",
        "kind": KIND_GROCERY,
        "aliases": ["norma"],
        "osm": re.compile(r"\bnorma\b"),
        "wikidata": ["Q450180"],
    },
    "globus": {
        "name": "Globus",
        "kind": KIND_GROCERY,
        "aliases": ["globus", "globus sb warenhaus"],
        "osm": re.compile(r"\bglobus\b"),
        "wikidata": ["Q457503"],
    },
    "marktkauf": {
        "name": "Marktkauf",
        "kind": KIND_GROCERY,
        "aliases": ["marktkauf"],
        "osm": re.compile(r"\bmarktkauf\b"),
        "wikidata": ["Q1533254"],
    },
    # drugstores (shop=chemist in OpenStreetMap)
    "rossmann": {
        "name": "Rossmann",
        "kind": KIND_DRUGSTORE,
        "aliases": ["rossmann", "dirk rossmann", "rossmann drogerie", "rossmann drogeriemarkt"],
        "osm": re.compile(r"\brossmann\b"),
        "wikidata": ["Q316004"],
    },
    "dm-drogerie-markt": {
        "name": "dm",
        "kind": KIND_DRUGSTORE,
        "aliases": ["dm", "dm drogerie", "dm drogerie markt", "dm drogeriemarkt", "dm markt"],
        "osm": re.compile(r"\bdm\b"),
        "wikidata": ["Q266572"],
    },
    "mueller-drogeriemarkt": {
        "name": "Müller",
        "kind": KIND_DRUGSTORE,
        "aliases": [
            "müller",
            "mueller",
            "muller",
            "müller drogerie",
            "drogerie müller",
            "müller drogeriemarkt",
        ],
        "osm": re.compile(r"\bmue?ller\b"),
        "wikidata": ["Q1958759"],
    },
    "budnikowsky": {
        "name": "Budni",
        "kind": KIND_DRUGSTORE,
        "aliases": ["budni", "budnikowsky", "budni drogerie"],
        "osm": re.compile(r"\bbudni(kowsky)?\b"),
        "wikidata": ["Q1001516"],
    },
}

# display names (marktguru ids), also used by the panel's settings (offer_stores)
STORES: dict[str, str] = {rid: info["name"] for rid, info in RETAILERS.items()}
# offer_stores default of new installs (no drugstores: they are added as branches)
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

# aliases that are also common surnames: inside a longer text they only count at its start
# ("Müller Hauptstraße" is Müller, "EDEKA Müller" an EDEKA, "Bäckerei Müller" no chain)
_START_ONLY_ALIASES = {"mueller", "muller"}

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


def retailer_kind(retailer: str | None) -> str | None:
    """'grocery' or 'drugstore' for a retailer id (regional variants included), else None."""
    rid = retailer_for_store_id(retailer)
    return RETAILERS[rid]["kind"] if rid else None


def is_drugstore(retailer: str | None) -> bool:
    """True for a drugstore chain ('rossmann', 'dm-drogerie-markt' …)."""
    return retailer_kind(retailer) == KIND_DRUGSTORE


def drugstore_ids() -> list[str]:
    """Ids of the drugstore chains."""
    return [rid for rid, info in RETAILERS.items() if info["kind"] == KIND_DRUGSTORE]


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
        if alias in _START_ONLY_ALIASES:
            if padded.startswith(f" {alias} "):
                return _ALIASES[alias]
        elif f" {alias} " in padded:
            return _ALIASES[alias]
    return None


def retailers_named(text: str | None) -> set[str]:
    """Every chain a text names as a whole word ('REWE neben Rossmann' -> {rewe, rossmann};
    a plain 'Aldi' names both Aldi variants). Surname aliases ('Müller') only count at the
    start of the text."""
    folded = fold(str(text or ""))
    if not folded:
        return set()
    padded = f" {folded} "
    found: set[str] = set()
    for alias, rid in _ALIASES.items():
        if alias in _START_ONLY_ALIASES:
            if padded.startswith(f" {alias} "):
                found.add(rid)
        elif f" {alias} " in padded:
            found.add(rid)
    if re.search(rf"\b{_GENERIC_ALDI}\b", folded) and not found & {ALDI_SUED, ALDI_NORD}:
        found |= {ALDI_SUED, ALDI_NORD}
    return found


def is_chain_name(text: str | None) -> bool:
    """True if a text is just a chain's name or id ('Lidl', 'Aldi', 'rewe', 'Aldi Süd'),
    not a branch ('Lidl Arbeit') or another word."""
    folded = fold(str(text or ""))
    return bool(folded) and (
        folded == _GENERIC_ALDI or folded in _ALIASES or str(text).strip().lower() in RETAILERS
    )


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

    Order: brand:wikidata (always counts), then brand/name/operator text, then (for a plain
    "Aldi") the postcode heuristic. guessed is True whenever a heuristic decided; (None,
    True) means "an Aldi, but the variant could not be determined".

    A chain name in the text only counts on a shop of the chain's kind (SHOP_TYPES):
    drugstores on shop=chemist, groceries on shop=supermarket|discount – a "Müller" lighting
    shop or optician is no Müller drugstore, the "Rossmann" bakery no Rossmann. Without a
    shop tag only grocery names count (the behaviour before drugstores existed).
    """
    tags = tags or {}
    postcode = postcode or tags.get("addr:postcode")
    for qid in str(tags.get("brand:wikidata") or "").replace(",", ";").split(";"):
        qid = qid.strip()
        if qid in _OTHER_WIKIDATA:
            return None, False
        if qid in _WIKIDATA:
            return _WIKIDATA[qid], False
    shop = str(tags.get("shop") or "").strip().lower()
    kinds = {kind for kind, types in SHOP_TYPES.items() if shop in types} if shop else None
    if kinds is None:
        kinds = {KIND_GROCERY}
    texts = [fold(str(tags[t])) for t in _OSM_TEXT_TAGS if tags.get(t)]
    generic_aldi = False
    for text in texts:
        for rid, info in RETAILERS.items():
            if info["kind"] in kinds and info["osm"].search(text):
                # plain "Netto" could also be the Danish Netto
                guessed = rid == "netto-marken-discount" and "marken" not in text
                return rid, guessed
        if KIND_GROCERY in kinds and re.search(rf"\b{_GENERIC_ALDI}\b", text):
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


# own brands of the chains (1.5 product database): a product of such a brand is only sold
# by its chain, so the same name at another chain is another product – no "auch bei Lidl"
# twin. Folded spellings; a brand also counts when it starts with one of them ("ja! Bio",
# "K-Classic Bio").
STORE_BRANDS: frozenset[str] = frozenset(
    {
        # REWE / Penny
        "ja",
        "rewe",
        "rewe beste wahl",
        "rewe bio",
        "rewe feine welt",
        "rewe regional",
        "penny",
        "naturgut",
        "butchers",
        # EDEKA / Netto Marken-Discount / Marktkauf
        "edeka",
        "edeka bio",
        "edeka herzstuecke",
        "edeka mein bayern",
        "edeka zuhause",
        "gut guenstig",
        "gutguenstig",
        "gut und guenstig",
        "netto",
        "biobio",
        "muehlenhof",
        "marktkauf",
        # ALDI
        "aldi",
        "milsani",
        "gut bio",
        "moser roth",
        "choceur",
        "lacura",
        "tandil",
        "meine metzgerei",
        "golden seafood",
        "cucina nobile",
        "westminster",
        "rio d oro",
        "lyttos",
        "le gusto",
        "sweet valley",
        "happy harvest",
        "nur nur natur",
        "mamia",
        "ombra",
        "almare",
        # Lidl
        "lidl",
        "milbona",
        "pilos",
        "cien",
        "w5",
        "formil",
        "freeway",
        "solevita",
        "deluxe",
        "chef select",
        "bio organic",
        "crownfield",
        "fin carre",
        "snack day",
        "combino",
        "sondey",
        "vemondo",
        "kania",
        "alesto",
        "dulano",
        "nixe",
        "italiamo",
        "fairglobe",
        "pikok",
        "baresa",
        "mcennedy",
        "favorina",
        "perlenbacher",
        "freshona",
        "rivercote",
        "lord nelson",
        "belbake",
        "saskia",
        "eridanous",
        "realvalley",
        "trattoria alfredo",
        # Kaufland
        "k classic",
        "k bio",
        "k favourites",
        "k purland",
        "kaufland",
        # NORMA / Globus
        "norma",
        "globus",
        # drugstores
        "isana",
        "alterra",
        "babydream",
        "domol",
        "rival de loop",
        "enerbio",
        "sunozon",
        "rossmann",
        "balea",
        "dmbio",
        "dm bio",
        "alverde",
        "denkmit",
        "babylove",
        "sundance",
        "ebelin",
        "mivolis",
        "profissimo",
        "s quitofree",
        "dm",
    }
)
_STORE_BRAND_PREFIXES = tuple(sorted({f"{b} " for b in STORE_BRANDS}))


def is_store_brand(brand: str | None, retailer: str | None = None) -> bool:
    """True if a brand is a chain's own brand (STORE_BRANDS, or the name of the retailer
    itself): products of such a brand have no twins at other chains."""
    folded = fold(str(brand or ""))
    if not folded:
        return False
    if folded in STORE_BRANDS or folded.startswith(_STORE_BRAND_PREFIXES):
        return True
    if retailer and retailer in RETAILERS:
        names = {
            fold(RETAILERS[retailer]["name"]),
            *(fold(a) for a in RETAILERS[retailer]["aliases"]),
        }
        return folded in names or any(folded.startswith(f"{n} ") for n in names if n)
    return False
