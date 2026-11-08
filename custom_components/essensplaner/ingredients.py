"""Ingredient parsing, scaling, unit handling and shopping categories.

Pure Python, no Home Assistant imports, so it can be unit tested easily.
"""

from __future__ import annotations

import functools
import math
import re
from typing import Any
import unicodedata

# --------------------------------------------------------------------------
# Units
# --------------------------------------------------------------------------

# canonical unit -> aliases (lower case, without trailing dot)
_UNIT_ALIASES: dict[str, tuple[str, ...]] = {
    "g": ("g", "gr", "gramm", "gram", "grams"),
    "kg": ("kg", "kilo", "kilogramm"),
    "mg": ("mg", "milligramm"),
    "ml": ("ml", "milliliter"),
    "l": ("l", "liter", "ltr"),
    "cl": ("cl", "zentiliter"),
    "dl": ("dl", "deziliter"),
    "EL": ("el", "essl", "esslöffel", "eßlöffel", "tbsp", "tablespoon", "tablespoons"),
    "TL": ("tl", "teel", "teelöffel", "tsp", "teaspoon", "teaspoons"),
    "Prise": ("prise", "prisen", "pr", "pinch"),
    "Msp.": ("msp", "messerspitze", "messerspitzen"),
    "Bund": ("bund", "bd", "bunch"),
    "Dose": ("dose", "dosen", "ds", "can", "cans"),
    "Pck.": ("pck", "päckchen", "packung", "packungen", "pk", "pkg", "pkt", "paket", "pack"),
    "Stück": ("stück", "stk", "st", "stck", "piece", "pieces"),
    "Zehe": ("zehe", "zehen", "clove", "cloves"),
    "Scheibe": ("scheibe", "scheiben", "slice", "slices"),
    "Becher": ("becher",),
    "Glas": ("glas", "gläser", "jar"),
    "Tasse": ("tasse", "tassen", "cup", "cups"),
    "Handvoll": ("handvoll",),
    "Würfel": ("würfel",),
    "Zweig": ("zweig", "zweige", "sprig", "sprigs"),
    "Blatt": ("blatt", "blätter"),
    "Spritzer": ("spritzer", "schuss"),
    "Stange": ("stange", "stangen"),
    "Kopf": ("kopf", "köpfe"),
    "Knolle": ("knolle", "knollen"),
    "Tafel": ("tafel", "tafeln"),
    "Flasche": ("flasche", "flaschen"),
    "Tüte": ("tüte", "tüten", "beutel"),
    "Schale": ("schale", "schalen"),
    "Netz": ("netz",),
    # drugstore / household packs (1.4): "8 Rollen", "20 WL" (Waschladungen)
    "Rolle": ("rolle", "rollen"),
    "WL": ("wl", "waschladung", "waschladungen"),
    "oz": ("oz", "ounce", "ounces"),
    "lb": ("lb", "lbs", "pound", "pounds"),
}

UNIT_LOOKUP: dict[str, str] = {
    alias: canonical for canonical, aliases in _UNIT_ALIASES.items() for alias in aliases
}

# unit -> (base unit, factor)
_CONVERSIONS: dict[str, tuple[str, float]] = {
    "g": ("g", 1.0),
    "kg": ("g", 1000.0),
    "mg": ("g", 0.001),
    "oz": ("g", 28.3495),
    "lb": ("g", 453.592),
    "ml": ("ml", 1.0),
    "l": ("ml", 1000.0),
    "cl": ("ml", 10.0),
    "dl": ("ml", 100.0),
    "Stück": ("", 1.0),
}

# Units you buy as a whole package – shopping amounts are rounded up.
_WHOLE_UNITS = {
    "",
    "Bund",
    "Dose",
    "Pck.",
    "Zehe",
    "Becher",
    "Glas",
    "Würfel",
    "Stange",
    "Kopf",
    "Knolle",
    "Tafel",
    "Flasche",
    "Tüte",
    "Schale",
    "Netz",
    "Rolle",
    "WL",
}

_FRACTIONS = {
    "½": "1/2",
    "⅓": "1/3",
    "⅔": "2/3",
    "¼": "1/4",
    "¾": "3/4",
    "⅕": "1/5",
    "⅖": "2/5",
    "⅗": "3/5",
    "⅘": "4/5",
    "⅙": "1/6",
    "⅚": "5/6",
    "⅛": "1/8",
    "⅜": "3/8",
    "⅝": "5/8",
    "⅞": "7/8",
}

_NUMBER = r"\d+\s+\d+/\d+|\d+/\d+|\d+(?:[.,]\d+)?"
_AMOUNT_RE = re.compile(
    rf"^(?P<a1>{_NUMBER})(?:\s*(?:-|–|—|bis)\s*(?P<a2>{_NUMBER}))?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
_PREFIX_RE = re.compile(r"^(?:ca\.?|circa|etwa|ungefähr|~)\s*", re.IGNORECASE)
_PLURAL_SUFFIX_RE = re.compile(r"\((?:n|en|e|s|er|nen)\)", re.IGNORECASE)
_PAREN_RE = re.compile(r"\s*\(([^)]*)\)\s*")
_UNIT_TOKEN_RE = re.compile(r"^(?P<unit>[^\W\d_]+\.?)(?=\s|$|[,(])\s*(?P<name>.*)$")


def _to_float(value: str) -> float:
    value = value.strip().replace(",", ".")
    total = 0.0
    for part in value.split():
        if "/" in part:
            num, den = part.split("/", 1)
            if float(den) == 0:
                continue
            total += float(num) / float(den)
        else:
            total += float(part)
    return total


def normalize_unit(unit: str | None) -> str:
    """Return the canonical spelling of a unit (or the input stripped)."""
    if not unit:
        return ""
    raw = unit.strip()
    key = raw.lower().rstrip(".")
    return UNIT_LOOKUP.get(key, raw)


def parse_ingredient(text: str) -> dict[str, Any]:
    """Parse a free text ingredient line like '1 1/2 EL Olivenöl, kalt gepresst'."""
    original = " ".join(str(text).split())
    line = original
    for frac, repl in _FRACTIONS.items():
        line = re.sub(rf"(\d)\s*{frac}", rf"\1 {repl}", line)
        line = line.replace(frac, f" {repl} ")
    line = " ".join(line.split())
    line = _PREFIX_RE.sub("", line)

    amount: float | None = None
    rest = line
    if match := _AMOUNT_RE.match(line):
        try:
            amount = _to_float(match.group("a1"))
            if match.group("a2"):
                # Ranges like "2-3": take the upper bound, better too much than too little.
                amount = max(amount, _to_float(match.group("a2")))
        except ValueError:
            amount = None
        rest = match.group("rest")

    unit = ""
    name = rest.strip()
    if amount is not None and (umatch := _UNIT_TOKEN_RE.match(name)):
        candidate = umatch.group("unit").lower().rstrip(".")
        if candidate in UNIT_LOOKUP and umatch.group("name").strip():
            unit = UNIT_LOOKUP[candidate]
            name = umatch.group("name").strip()
    elif amount is None and (umatch := _UNIT_TOKEN_RE.match(name)):
        # "Prise Salz" without a number
        candidate = umatch.group("unit").lower().rstrip(".")
        if (
            candidate in UNIT_LOOKUP
            and umatch.group("name").strip()
            and candidate
            in (
                "prise",
                "msp",
                "etwas",
            )
        ):
            unit = UNIT_LOOKUP[candidate]
            amount = 1
            name = umatch.group("name").strip()

    if name.lower().startswith("of "):
        name = name[3:]

    name = _PLURAL_SUFFIX_RE.sub("", name)
    notes: list[str] = []
    for note in _PAREN_RE.findall(name):
        if note.strip():
            notes.append(note.strip())
    name = _PAREN_RE.sub(" ", name).strip()
    if "," in name:
        name, extra = name.split(",", 1)
        if extra.strip():
            notes.append(extra.strip())
    name = name.strip(" ,;:-")

    if not name:
        name = original

    return {
        "name": name,
        "amount": round(amount, 4) if amount is not None else None,
        "unit": unit,
        "note": ", ".join(notes),
        "category": guess_category(name),
    }


def normalize_ingredient(data: Any) -> dict[str, Any]:
    """Normalize an ingredient given as string or dict."""
    if isinstance(data, str):
        return parse_ingredient(data)
    if not isinstance(data, dict):
        return parse_ingredient(str(data))
    name = str(data.get("name") or "").strip()
    amount = data.get("amount")
    if isinstance(amount, str):
        amount = amount.strip()
        try:
            amount = _to_float(amount) if amount else None
        except ValueError:
            amount = None
    if amount is not None:
        try:
            amount = round(float(amount), 4)
        except (TypeError, ValueError):
            amount = None
    if not name:
        return parse_ingredient(str(data.get("text", "")))
    return {
        "name": name,
        "amount": amount,
        "unit": normalize_unit(data.get("unit")),
        "note": str(data.get("note") or "").strip(),
        "category": str(data.get("category") or "").strip() or guess_category(name),
    }


# --------------------------------------------------------------------------
# Formatting & scaling
# --------------------------------------------------------------------------


def format_number(value: float) -> str:
    """Format a number the German way: 1.5 -> '1,5', 2.0 -> '2'."""
    if value >= 100:
        value = round(value)
    elif value >= 10:
        value = round(value, 1)
    else:
        value = round(value, 2)
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",")


_UNIT_PLURALS = {
    "Zehe": "Zehen",
    "Dose": "Dosen",
    "Stange": "Stangen",
    "Scheibe": "Scheiben",
    "Tasse": "Tassen",
    "Knolle": "Knollen",
    "Tafel": "Tafeln",
    "Flasche": "Flaschen",
    "Tüte": "Tüten",
    "Schale": "Schalen",
    "Prise": "Prisen",
    "Zweig": "Zweige",
    "Kopf": "Köpfe",
    "Glas": "Gläser",
    "Blatt": "Blätter",
    "Rolle": "Rollen",
}

_IRREGULAR_PLURALS = {"apfel": "Äpfel", "ei": "Eier"}
_NO_PLURAL_ENDINGS = ("n", "s", "er", "i", "a", "x")


def pluralize(name: str) -> str:
    """Very small German pluralizer for counted ingredients ('Zwiebel' -> 'Zwiebeln')."""
    words = name.split()
    if not words:
        return name
    last = words[-1]
    lower = last.lower()
    if lower in _IRREGULAR_PLURALS:
        plural = _IRREGULAR_PLURALS[lower]
    elif lower.endswith(_NO_PLURAL_ENDINGS) or not last[:1].isupper():
        return name
    elif lower.endswith(("e", "el")):
        plural = f"{last}n"
    elif lower.endswith("o"):
        plural = f"{last}s"
    else:
        return name
    return " ".join([*words[:-1], plural])


_IRREGULAR_SINGULARS = {"eier": "Ei", "äpfel": "Apfel"}


def singularize(name: str) -> str:
    """Inverse of pluralize for '1 Karotten' -> '1 Karotte'."""
    words = name.split()
    if not words:
        return name
    last = words[-1]
    lower = last.lower()
    if lower in _IRREGULAR_SINGULARS:
        singular = _IRREGULAR_SINGULARS[lower]
    elif not last[:1].isupper() or lower.endswith("chen") or len(lower) < 5:
        return name
    elif lower.endswith(("eln", "en")):
        singular = last[:-1]
    else:
        return name
    return " ".join([*words[:-1], singular])


def _pretty_amount(amount: float, unit: str) -> tuple[float, str]:
    if unit == "g" and amount >= 1000:
        return amount / 1000, "kg"
    if unit == "ml" and amount >= 1000:
        return amount / 1000, "l"
    return amount, unit


def format_amount(amount: float | None, unit: str) -> str:
    """Format amount + unit, e.g. '1,5 kg'."""
    if amount is None:
        return unit
    amount, unit = _pretty_amount(amount, unit)
    text = format_number(amount)
    if amount > 1 and unit in _UNIT_PLURALS:
        unit = _UNIT_PLURALS[unit]
    return f"{text} {unit}".strip()


def format_ingredient(ingredient: dict[str, Any]) -> str:
    """Return a human readable ingredient line."""
    parts = []
    amount = ingredient.get("amount")
    unit = ingredient.get("unit") or ""
    amount_text = format_amount(amount, unit)
    if amount_text:
        parts.append(amount_text)
    name = ingredient.get("name", "")
    if unit in ("", "Stück") and amount is not None:
        name = pluralize(name) if amount > 1 else singularize(name)
    parts.append(name)
    text = " ".join(p for p in parts if p)
    if ingredient.get("note"):
        text += f" ({ingredient['note']})"
    return text


def scale_ingredient(ingredient: dict[str, Any], factor: float) -> dict[str, Any]:
    """Return a scaled copy of an ingredient."""
    scaled = dict(ingredient)
    if scaled.get("amount") is not None:
        scaled["amount"] = round(float(scaled["amount"]) * factor, 4)
    return scaled


# --------------------------------------------------------------------------
# Name normalisation (for merging shopping items)
# --------------------------------------------------------------------------

_ADJECTIVES = {
    "groß",
    "große",
    "großer",
    "großes",
    "gross",
    "grosse",
    "klein",
    "kleine",
    "kleiner",
    "kleines",
    "mittelgroß",
    "mittelgroße",
    "mittelgroßer",
    "mittelgroßes",
    "frisch",
    "frische",
    "frischer",
    "frisches",
    "reif",
    "reife",
    "reifer",
    "reifes",
    "gehackt",
    "gehackte",
    "gehackter",
    "gewürfelt",
    "gewürfelte",
    "fein",
    "grob",
    "optional",
    "bio",
    "etwas",
    "evtl",
    "evtl.",
    "mittelscharf",
    "mittelscharfer",
    "scharf",
    "scharfer",
    "lauwarm",
    "lauwarmes",
    "lauwarme",
    "kalt",
    "kaltes",
    "kalte",
    "warmes",
    "warme",
    "grobe",
    "grober",
    "saeuerlich",
    "säuerliche",
    "säuerlicher",
}

_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def fold(text: str) -> str:
    """Lower case + umlaut folding + whitespace cleanup ('Crème fraîche' -> 'creme fraiche')."""
    text = text.lower().translate(_UMLAUTS)
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return " ".join(text.split())


def _singular(word: str) -> str:
    if word == "eier":
        return "ei"
    if len(word) > 4 and (word.endswith("eln") or word.endswith("ern")):
        return word[:-1]
    if len(word) > 4 and word.endswith("en") and not word.endswith("chen"):
        return word[:-1]
    if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


_ARTICLES = ("der ", "die ", "das ", "den ", "dem ", "ein ", "eine ", "einen ", "einem ")

# spoken quantities ("zwei Liter Milch", "einen Liter Milch", "Packung Butter")
_DIGIT_WORDS = {
    "ein": 1,
    "eins": 1,
    "zwei": 2,
    "zwo": 2,
    "drei": 3,
    "vier": 4,
    "fuenf": 5,
    "sechs": 6,
    "sieben": 7,
    "acht": 8,
    "neun": 9,
}
_TEEN_WORDS = {
    "zehn": 10,
    "elf": 11,
    "zwoelf": 12,
    "dreizehn": 13,
    "vierzehn": 14,
    "fuenfzehn": 15,
    "sechzehn": 16,
    "siebzehn": 17,
    "achtzehn": 18,
    "neunzehn": 19,
}
_TEN_WORDS = {
    "zwanzig": 20,
    "dreissig": 30,
    "vierzig": 40,
    "fuenfzig": 50,
    "sechzig": 60,
    "siebzig": 70,
    "achtzig": 80,
    "neunzig": 90,
}
_FRACTION_WORDS = {
    "halb": 0.5,
    "halbe": 0.5,
    "halben": 0.5,
    "halber": 0.5,
    "halbes": 0.5,
    "anderthalb": 1.5,
    "eineinhalb": 1.5,
}
# articles count as "1" only in front of a unit ("einen Liter Milch", not "eine Gurke")
_ARTICLE_WORDS = {"ein", "eine", "einen", "einem", "einer"}
# units that may be said without a number ("Liter Milch" = 1 l)
_BARE_UNITS = {
    "liter",
    "kilo",
    "kilogramm",
    "gramm",
    "milliliter",
    "packung",
    "paeckchen",
    "paket",
    "dose",
    "flasche",
    "glas",
    "becher",
    "beutel",
    "tuete",
    "netz",
    "schale",
    "bund",
    "kopf",
    "stueck",
    "tafel",
    "stange",
    "knolle",
}
_POUND_WORDS = {"pfund"}


def _number_word(word: str) -> float | None:
    """German number words up to 999 ('drei', 'zweihundertfünfzig', 'halbe') -> number."""
    word = word.lower().translate(_UMLAUTS)
    if word in _FRACTION_WORDS:
        return _FRACTION_WORDS[word]
    if word in _DIGIT_WORDS:
        return float(_DIGIT_WORDS[word])
    if word in _TEEN_WORDS:
        return float(_TEEN_WORDS[word])
    if word in _TEN_WORDS:
        return float(_TEN_WORDS[word])
    if "hundert" in word:
        head, _, rest = word.partition("hundert")
        if head and head not in _DIGIT_WORDS:
            return None
        tail = _number_word(rest) if rest else 0.0
        if tail is None or tail != int(tail):
            return None
        return float(_DIGIT_WORDS.get(head, 1) * 100 + tail)
    if "und" in word:
        ones, _, tens = word.partition("und")
        if ones in _DIGIT_WORDS and tens in _TEN_WORDS:
            return float(_DIGIT_WORDS[ones] + _TEN_WORDS[tens])
    return None


def _number_text(value: float) -> str:
    return f"{value:g}".replace(".", ",")


def normalize_spoken_quantity(text: str) -> str:
    """Spoken amounts as digits, for items typed or said by the user (not for recipes).

    'zwei Liter Milch' -> '2 Liter Milch', 'drei Packungen Butter' -> '3 Packungen Butter',
    'einen Liter Milch' / 'Liter Milch' -> '1 Liter Milch', 'eine halbe Gurke' ->
    '0,5 Gurke', 'ein Pfund Hackfleisch' -> '500 g Hackfleisch'. Anything else is returned
    unchanged ('eine Gurke' stays, see strip_article()).
    """
    words = " ".join(str(text or "").split()).split(" ")
    if len(words) < 2:
        return " ".join(words)
    first = words[0].lower().translate(_UMLAUTS)
    amount: float | None = None
    rest = words[1:]
    if first in _ARTICLE_WORDS:
        second = rest[0].lower().translate(_UMLAUTS)
        if second in _FRACTION_WORDS and len(rest) > 1:
            amount, rest = _FRACTION_WORDS[second], rest[1:]  # "ein halbes Kilo"
        elif _unit_word(second) and len(rest) > 1:
            amount = 1.0
    elif re.fullmatch(r"\d+(?:[.,]\d+)?", first):
        if _unit_word(rest[0]) in _POUND_WORDS:
            amount = _to_float(first)
    elif (value := _number_word(first)) is not None:
        amount = value
    elif _unit_word(first) and len(words) > 1:
        amount, rest = 1.0, words  # "Liter Milch"
    if amount is None:
        return " ".join(words)
    if len(rest) > 1 and _unit_word(rest[0]) in _POUND_WORDS:
        return f"{_number_text(amount * 500)} g {' '.join(rest[1:])}"
    return f"{_number_text(amount)} {' '.join(rest)}"


def _unit_word(word: str) -> str | None:
    """Folded unit word that may stand without a number ('Packungen' -> 'packung')."""
    folded = word.lower().translate(_UMLAUTS).rstrip(".")
    for candidate in (folded, folded[:-1], folded[:-2]):
        if candidate in _BARE_UNITS or candidate in _POUND_WORDS:
            return candidate
    return None


def strip_article(text: str) -> str:
    """'die Lasagne' -> 'Lasagne' (for spoken dish names)."""
    cleaned = " ".join(str(text).split())
    lower = cleaned.lower()
    for article in _ARTICLES:
        if lower.startswith(article) and len(cleaned) > len(article):
            return cleaned[len(article) :]
    return cleaned


# adjectives that name a different product before these words ("gehackte Tomaten" are
# canned tomatoes, not fresh ones) and are therefore kept in the key
_PRODUCT_ADJECTIVES = {"gehackt": "tomate", "gehackte": "tomate", "gehackter": "tomate"}


def ingredient_key(name: str) -> str:
    """Return a key used to merge equal ingredients."""
    raw = name.lower().split()
    words = [
        w
        for n, w in enumerate(raw)
        if w.strip(".,") not in _ADJECTIVES
        or (
            (product := _PRODUCT_ADJECTIVES.get(w.strip(".,")))
            and n + 1 < len(raw)
            and fold(raw[n + 1]).startswith(product)
        )
    ]
    folded = fold(" ".join(words)) or fold(name)
    return " ".join(_singular(w) for w in folded.split())


def is_pantry_item(name: str, pantry: list[str]) -> bool:
    """Return True if the ingredient is a pantry staple."""
    key = ingredient_key(name)
    for staple in pantry:
        skey = ingredient_key(staple)
        if not skey:
            continue
        if key == skey or key.startswith(f"{skey} ") or key.endswith(f" {skey}"):
            return True
    return False


# --------------------------------------------------------------------------
# Categories (aisles)
# --------------------------------------------------------------------------

# non-food aisles (1.4): bought at a drugstore branch (Rossmann, dm …) when there is one
CATEGORY_DRUGSTORE = "Drogerie & Körperpflege"
CATEGORY_HOUSEHOLD = "Haushalt & Reinigung"
NONFOOD_CATEGORIES = frozenset({CATEGORY_DRUGSTORE, CATEGORY_HOUSEHOLD})

CATEGORY_ORDER = [
    "Obst & Gemüse",
    "Brot & Backwaren",
    "Fleisch & Fisch",
    "Milchprodukte & Eier",
    "Käse & Aufschnitt",
    "Nudeln, Reis & Getreide",
    "Konserven & Gläser",
    "Gewürze, Öle & Saucen",
    "Backen & Süßes",
    "Nüsse & Trockenobst",
    "Tiefkühl",
    "Getränke",
    CATEGORY_DRUGSTORE,
    CATEGORY_HOUSEHOLD,
    "Sonstiges",
]

_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Obst & Gemüse": (
        "apfel",
        "aepfel",
        "banane",
        "birne",
        "orange",
        "zitrone",
        "limette",
        "mandarine",
        "beere",
        "erdbeere",
        "himbeere",
        "heidelbeere",
        "blaubeere",
        "traube",
        "kiwi",
        "mango",
        "ananas",
        "pfirsich",
        "nektarine",
        "melone",
        "avocado",
        "tomate",
        "kirschtomate",
        "gurke",
        "paprika",
        "zucchini",
        "aubergine",
        "zwiebel",
        "schalotte",
        "knoblauch",
        "ingwer",
        "karotte",
        "moehre",
        "kartoffel",
        "suesskartoffel",
        "kuerbis",
        "brokkoli",
        "blumenkohl",
        "kohl",
        "wirsing",
        "rotkohl",
        "weisskohl",
        "spinat",
        "salat",
        "rucola",
        "feldsalat",
        "lauch",
        "porree",
        "fruehlingszwiebel",
        "sellerie",
        "staudensellerie",
        "fenchel",
        "pilz",
        "champignon",
        "steinpilz",
        "pfifferling",
        "mais",
        "erbse",
        "bohne",
        "gruene bohne",
        "petersilie",
        "schnittlauch",
        "basilikum",
        "koriander",
        "dill",
        "minze",
        "rosmarin",
        "thymian",
        "salbei",
        "chili",
        "peperoni",
        "radieschen",
        "rote bete",
        "kohlrabi",
        "spargel",
        "pastinake",
        "rhabarber",
        "gemuese",
        "obst",
        "kraeuter",
        "lauchzwiebel",
        "mangold",
        "pak choi",
        "edamame",
        "schwammerl",  # mushrooms, not a sponge
    ),
    "Brot & Backwaren": (
        "brot",
        "broetchen",
        "toast",
        "toastbrot",
        "baguette",
        "ciabatta",
        "wrap",
        "tortilla",
        "fladenbrot",
        "pita",
        "brezel",
        "croissant",
        "burgerbroetchen",
        "knaeckebrot",
        "taco schale",
        "tacoschale",
        "naan",
    ),
    "Fleisch & Fisch": (
        "fleisch",
        "hackfleisch",
        "hack",
        "rinderhack",
        "gemischtes hack",
        "rind",
        "rinderhuefte",
        "steak",
        "schwein",
        "schnitzel",
        "kotelett",
        "huhn",
        "haehnchen",
        "haehnchenbrust",
        "haehnchenschenkel",
        "huehnchen",
        "pute",
        "putenbrust",
        "lamm",
        "speck",
        "bacon",
        "schinkenwuerfel",
        "wurst",
        "bratwurst",
        "chorizo",
        "lachs",
        "thunfischsteak",
        "fisch",
        "garnele",
        "shrimp",
        "scampi",
        "kabeljau",
        "seelachs",
        "forelle",
        "dorade",
        "muschel",
        "gyros",
        "bratwuerste",
        "wuerste",
        "pancetta",
        "matjes",
        "hering",
        "fleischwurst",
        "schweinenacken",
        "nackensteak",
        "geschnetzeltes",
        "wuerstchen",
        "wiener",
        "mett",
        "salsiccia",
        "ente",
        "frikadelle",
        "leberkaese",
        "rinderbrueh",
    ),
    "Milchprodukte & Eier": (
        "milch",
        "vollmilch",
        "butter",
        "sahne",
        "schlagsahne",
        "schmand",
        "saure sahne",
        "creme fraiche",
        "joghurt",
        "quark",
        "magerquark",
        "skyr",
        "buttermilch",
        "kefir",
        "ei",
        "eigelb",
        "eiweiss",
        "frischkaese",
        "mascarpone",
        "ricotta",
        "hafermilch",
        "sojamilch",
        "pflanzenmilch",
        "margarine",
        "kochsahne",
    ),
    "Käse & Aufschnitt": (
        "kaese",
        "gouda",
        "emmentaler",
        "parmesan",
        "pecorino",
        "mozzarella",
        "feta",
        "hirtenkaese",
        "cheddar",
        "bergkaese",
        "camembert",
        "brie",
        "halloumi",
        "reibekaese",
        "gratinkaese",
        "schinken",
        "salami",
        "kochschinken",
        "aufschnitt",
        "parmaschinken",
        "gorgonzola",
        "raclettekaese",
    ),
    "Nudeln, Reis & Getreide": (
        "nudel",
        "pasta",
        "spaghetti",
        "penne",
        "fusilli",
        "tagliatelle",
        "lasagneplatte",
        "lasagne platte",
        "makkaroni",
        "maccheroni",
        "farfalle",
        "rigatoni",
        "gnocchi",
        "spaetzle",
        "reis",
        "basmati",
        "jasminreis",
        "risottoreis",
        "milchreis",
        "couscous",
        "bulgur",
        "quinoa",
        "haferflocke",
        "muesli",
        "cornflake",
        "polenta",
        "griess",
        "hirse",
        "linse",
        "rote linse",
        "kichererbse",
        "glasnudel",
        "reisnudel",
        "mie nudel",
        "ramen",
        "graupe",
        "tortellini",
        "ravioli",
        "cannelloni",
        "sojagranulat",
        "paellareis",
        "orzo",
    ),
    "Konserven & Gläser": (
        "tomatenmark",
        "passierte tomate",
        "passata",
        "gehackte tomate",
        "dosentomate",
        "pizzatomate",
        "tomatensosse",
        "kokosmilch",
        "kidneybohne",
        "weisse bohne",
        "mais dose",
        "kichererbse",
        "thunfisch",
        "sardine",
        "oliven",
        "olive",
        "kapern",
        "gewuerzgurke",
        "essiggurke",
        "pesto",
        "senf",
        "ketchup",
        "mayonnaise",
        "mayo",
        "honig",
        "marmelade",
        "konfituere",
        "erdnussbutter",
        "nutella",
        "apfelmus",
        "sauerkraut",
        "rotkohl glas",
        "getrocknete tomate",
        "jalapeno",
        "antipasti",
        "kokoscreme",
        "tahini",
        "sauerkirsche",
        "kirsche",
        "cocktailkirsche",
        "sojasprosse",
        "schwarze bohne",
        "curry paste",
        "currypaste",
        "tahin",
        "hummus",
    ),
    "Gewürze, Öle & Saucen": (
        "salz",
        "pfeffer",
        "paprikapulver",
        "edelsuess",
        "rosenscharf",
        "curry",
        "currypulver",
        "kurkuma",
        "kreuzkuemmel",
        "kuemmel",
        "zimt",
        "muskat",
        "muskatnuss",
        "oregano",
        "majoran",
        "lorbeer",
        "lorbeerblatt",
        "nelke",
        "chiliflocke",
        "cayenne",
        "garam masala",
        "gewuerz",
        "kraeuter der provence",
        "italienische kraeuter",
        "oel",
        "olivenoel",
        "rapsoel",
        "sonnenblumenoel",
        "sesamoel",
        "essig",
        "balsamico",
        "weissweinessig",
        "sojasosse",
        "sojasauce",
        "worcestersosse",
        "fischsosse",
        "austernsosse",
        "teriyaki",
        "bruehe",
        "gemuesebruehe",
        "huehnerbruehe",
        "rinderbruehe",
        "fond",
        "bruehwuerfel",
        "sambal",
        "worcestersauce",
        "ketjap manis",
        "fischsauce",
        "safran",
        "safranfaeden",
        "sriracha",
        "tabasco",
        "vanilleextrakt",
        "senfkoerner",
        "gemuesebruehe pulver",
    ),
    "Backen & Süßes": (
        "mehl",
        "weizenmehl",
        "dinkelmehl",
        "speisestaerke",
        "staerke",
        "zucker",
        "puderzucker",
        "brauner zucker",
        "rohrzucker",
        "vanillezucker",
        "backpulver",
        "natron",
        "hefe",
        "trockenhefe",
        "kakao",
        "schokolade",
        "zartbitter",
        "kuvertuere",
        "schokotropfen",
        "gelatine",
        "paniermehl",
        "semmelbroesel",
        "ahornsirup",
        "agavendicksaft",
        "sirup",
        "streusel",
        "marzipan",
        "puddingpulver",
        "kekse",
        "biskuit",
        "loeffelbiskuit",
        "vanilleschote",
    ),
    "Nüsse & Trockenobst": (
        "nuss",
        "nuesse",
        "walnuss",
        "haselnuss",
        "mandel",
        "cashew",
        "erdnuss",
        "pinienkern",
        "sonnenblumenkern",
        "kuerbiskern",
        "sesam",
        "leinsamen",
        "chiasamen",
        "rosine",
        "cranberry",
        "dattel",
        "aprikose getrocknet",
        "kokosraspel",
        "pistazie",
    ),
    "Tiefkühl": (
        "tk",
        "tiefkuehl",
        "tiefgekuehlt",
        "gefroren",
        "pommes",
        "fischstaebchen",
        "blattspinat tk",
        "erbsen tk",
        "eis",
        "pizza",
        "rahmspinat",
    ),
    "Getränke": (
        "wasser",
        "mineralwasser",
        "saft",
        "orangensaft",
        "apfelsaft",
        "wein",
        "weisswein",
        "rotwein",
        "bier",
        "kaffee",
        "tee",
        "limonade",
        "cola",
        "sekt",
        "prosecco",
    ),
}

# drugstore and household products. No bare "creme" (Crème fraîche, Kokoscreme), "tuch",
# "papier" (Reispapier), "spray" (Bratspray), "beutel" (Teebeutel), "watte" (Zuckerwatte),
# "binde" (Saucenbinder) or "tab" (Tabasco): only words that name no food.
_CATEGORY_KEYWORDS[CATEGORY_DRUGSTORE] = (
    "zahnpasta",
    "zahncreme",
    "zahnbuerste",
    "zahnseide",
    "zahnpflege",
    "mundspuelung",
    "mundwasser",
    "duschgel",
    "duschbad",
    "duschcreme",
    "duschoel",
    "schaumbad",
    "badesalz",
    "badezusatz",
    "shampoo",
    "spuelung",
    "haarspuelung",
    "conditioner",
    "haarkur",
    "haarmaske",
    "haargel",
    "haarspray",
    "haarfarbe",
    "haaroel",
    "haarwasser",
    "haarbuerste",
    "deo",
    "deos",
    "deospray",
    "deoroller",
    "deodorant",
    "antitranspirant",
    "rasier",
    "rasierer",
    "rasierschaum",
    "rasierklinge",
    "aftershave",
    "seife",
    "handseife",
    "fluessigseife",
    "handcreme",
    "sonnencreme",
    "sonnenmilch",
    "sonnenspray",
    "sonnenschutz",
    "gesichtscreme",
    "tagescreme",
    "nachtcreme",
    "koerpercreme",
    "fusscreme",
    "gesichtswasser",
    "mizellenwasser",
    "bodylotion",
    "koerperlotion",
    "lotion",
    "lippenpflege",
    "lippenbalsam",
    "labello",
    "lippenstift",
    "nagellack",
    "mascara",
    "wimperntusche",
    "parfum",
    "parfuem",
    "peeling",
    "babyoel",
    "koerperoel",
    "massageoel",
    "pflegeoel",
    "taschentuch",
    "taschentuecher",
    "feuchttuch",
    "feuchttuecher",
    "kosmetiktuch",
    "kosmetiktuecher",
    "abschminktuch",
    "abschminktuecher",
    "windel",
    "wattepad",
    "abschminkpad",
    "wattestaebchen",
    "wattebausch",
    "damenbinde",
    "slipeinlage",
    "tampon",
    "pflaster",
    "kondom",
)
_CATEGORY_KEYWORDS[CATEGORY_HOUSEHOLD] = (
    "waschmittel",
    "waschpulver",
    "weichspueler",
    "fleckentferner",
    "spuelmittel",
    "spuelmaschinentab",
    "spuelmaschinentabs",
    "geschirrspueltab",
    "geschirrspueltabs",
    "spuelmaschinensalz",
    "regeneriersalz",
    "klarspueler",
    "reiniger",
    "putzmittel",
    "scheuermilch",
    "entkalker",
    "desinfektionsmittel",
    "wc ente",
    "schwamm",
    "schwaemme",
    "schwammtuch",
    "spueltuch",
    "putztuch",
    "mikrofasertuch",
    "geschirrtuch",
    "spuelbuerste",
    "muellbeutel",
    "muellsack",
    "muellsaecke",
    "muelltuete",
    "gefrierbeutel",
    "frischhaltebeutel",
    "kuechenrolle",
    "kuechenpapier",
    "kuechentuch",
    "kuechentuecher",
    "haushaltsrolle",
    "toilettenpapier",
    "klopapier",
    "alufolie",
    "aluminiumfolie",
    "frischhaltefolie",
    "backpapier",
    "batterie",
    "gluehbirne",
    "leuchtmittel",
    "teelicht",
    "teelichter",
    "kerze",
    "streichholz",
    "streichhoelzer",
    "feuerzeug",
    "raumduft",
    "raumspray",
    "zahnstocher",
)

# brand names people use for the product ("Tempo", "Persil", "Zewa"): whole words only
# ("Froschschenkel" is no Frosch, "April" no Pril)
_BRAND_KEYWORDS = {
    CATEGORY_DRUGSTORE: (
        "tempo",
        "kleenex",
        "elmex",
        "aronal",
        "odol",
        "colgate",
        "oral b",
        "blend a med",
        "nivea",
        "penaten",
        "bepanthen",
        "hansaplast",
        "pampers",
        "always",
        "durex",
        "balea",
    ),
    CATEGORY_HOUSEHOLD: (
        "persil",
        "ariel",
        "somat",
        "frosch",
        "domestos",
        "sagrotan",
        "zewa",
        "pril",
        "lenor",
        "calgon",
        "finish",
        "meister proper",
        "vanish",
        "cillit",
    ),
}
_WHOLE_WORD_KEYWORDS = frozenset(kw for keywords in _BRAND_KEYWORDS.values() for kw in keywords)
for _category, _brands in _BRAND_KEYWORDS.items():
    _CATEGORY_KEYWORDS[_category] = (*_CATEGORY_KEYWORDS[_category], *_brands)

# (keyword, category) sorted by keyword length, longest first
_KEYWORDS: list[tuple[str, str]] = sorted(
    ((kw, category) for category, keywords in _CATEGORY_KEYWORDS.items() for kw in keywords),
    key=lambda item: len(item[0]),
    reverse=True,
)


@functools.lru_cache(maxsize=8192)
def guess_category(name: str) -> str:
    """Guess the supermarket aisle for an ingredient (cached: offers ask it often)."""
    folded = fold(name)
    if not folded:
        return "Sonstiges"
    if re.search(r"(^| )(tk|tiefkuehl\w*|tiefgekuehlt\w*)( |$)", folded):
        return "Tiefkühl"
    singular = " ".join(_singular(w) for w in folded.split())
    candidates = (folded, singular)
    # 1. whole word / compound head (word ends with keyword)
    for keyword, category in _KEYWORDS:
        for text in candidates:
            if text == keyword or text.endswith(keyword) or f"{keyword} " in f"{text} ":
                if keyword in _WHOLE_WORD_KEYWORDS and f" {keyword} " not in f" {text} ":
                    continue
                if keyword in ("ei",) and not re.search(r"(^| )ei(er)?( |$)", folded):
                    continue
                if keyword == "deo" and not re.search(r"(^| )deo", text):
                    continue  # "Deo", "Deo-Roller", not "Video"
                if (
                    keyword in ("tk", "eis", "hack", "tee", "oel")
                    and not re.search(rf"(^| ){keyword}", text)
                    and not text.endswith(keyword)
                ):
                    continue
                return category
    # 2. keyword anywhere (e.g. "Hähnchenbrustfilet")
    for keyword, category in _KEYWORDS:
        if len(keyword) < 4 or keyword in _WHOLE_WORD_KEYWORDS:
            continue
        for text in candidates:
            if keyword in text:
                return category
    return "Sonstiges"


def is_nonfood_category(category: str | None) -> bool:
    """True for the drugstore and household aisles (no food)."""
    return category in NONFOOD_CATEGORIES


def category_rank(category: str) -> int:
    """Sort index of a category."""
    try:
        return CATEGORY_ORDER.index(category)
    except ValueError:
        return len(CATEGORY_ORDER)


# --------------------------------------------------------------------------
# Shopping list aggregation
# --------------------------------------------------------------------------


def to_base(amount: float | None, unit: str) -> tuple[float | None, str]:
    """Convert to base units (g / ml / count)."""
    if amount is None:
        return None, unit
    if unit in _CONVERSIONS:
        base, factor = _CONVERSIONS[unit]
        return amount * factor, base
    return amount, unit


def aggregate(
    entries: list[tuple[dict[str, Any], str]],
    pantry: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Merge ingredient entries into shopping items.

    entries: list of (ingredient, recipe_title) – ingredients already scaled.
    """
    pantry = pantry or []
    merged: dict[str, dict[str, Any]] = {}
    for ingredient, recipe_title in entries:
        name = ingredient.get("name", "").strip()
        if not name or is_pantry_item(name, pantry):
            continue
        key = ingredient_key(name)
        item = merged.setdefault(
            key,
            {
                "key": key,
                "name": name,
                "names": [],
                "category": ingredient.get("category") or guess_category(name),
                "amounts": {},
                "unquantified": False,
                "recipes": [],
            },
        )
        if name not in item["names"]:
            item["names"].append(name)
        amount, unit = to_base(ingredient.get("amount"), ingredient.get("unit") or "")
        if amount is None:
            item["unquantified"] = True
        else:
            item["amounts"][unit] = item["amounts"].get(unit, 0.0) + amount
        if recipe_title and recipe_title not in item["recipes"]:
            item["recipes"].append(recipe_title)

    result = []
    for item in merged.values():
        # Prefer the plain name ("Zwiebeln" over "große Zwiebeln")
        fewest_words = min(len(n.split()) for n in item["names"])
        plain = [n for n in item["names"] if len(n.split()) == fewest_words]
        item["name"] = min(plain, key=len)
        parts = []
        counted: float | None = None
        for unit, amount in item["amounts"].items():
            if unit in _WHOLE_UNITS:
                amount = math.ceil(amount - 1e-9)
            if unit == "":
                counted = amount
            parts.append(format_amount(amount, unit))
        if counted is not None and counted > 1:
            plural = [n for n in plain if pluralize(n) == n and n != item["name"]]
            item["name"] = plural[0] if plural else pluralize(item["name"])
        elif counted is not None and len(item["amounts"]) == 1:
            item["name"] = singularize(item["name"])
        del item["names"]
        if len(parts) == 1:
            summary = f"{parts[0]} {item['name']}"
        elif parts:
            summary = f"{item['name']} ({' + '.join(parts)})"
        else:
            summary = item["name"]
        item["summary"] = summary
        item["amount_text"] = " + ".join(parts)
        result.append(item)

    result.sort(key=lambda i: (category_rank(i["category"]), fold(i["name"])))
    return result
