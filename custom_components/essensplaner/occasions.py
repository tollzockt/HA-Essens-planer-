"""Occasions (1.5): a film night, a barbecue, Christmas dinner … as their own "Anlass".

An occasion has a date, an optional time, guests and children and items per course
(starter, main, side, dessert, snack, drink, extra): recipes of the collection, products of
the product database or free text (with an optional quantity, e.g. "2,5 kg Grillkohle").
TEMPLATES give the courses, the time and extras per number of persons ("Popcorn 100 g per 2
persons"). Suggestions per course follow the planning rules (favourites, not cooked lately,
offers – manager._suggest_weight()) plus the template's tags; the AI (feature "occasions",
optional) only reorders and extends them and is checked against the recipes.

Occasions are stored in the main file (key "occasions", pruned 365 days after their date),
count in the week's costs (and in the budget with the option occasions_in_budget), show in
the calendar (uid "<date>_occasion-<id>"), the sensor "Nächster Anlass" and the shopping
list (with the week or as a list of their own).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
import logging
import math
import re
from typing import TYPE_CHECKING, Any
import uuid

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from .const import AI_FEATURE_OCCASIONS, DOMAIN
from .dates import WEEKDAY_NAMES, parse_date
from .drinks import DRINKS, alcohol_allowed, drink_quantities, is_alcoholic, suggest_drinks
from .ingredients import (
    fold,
    guess_category,
    ingredient_key,
    is_nonfood_category,
    normalize_unit,
    scale_ingredient,
    to_base,
)
from .pricing import item_cost
from .season import recipe_season

if TYPE_CHECKING:
    from .manager import EssensplanerManager

_LOGGER = logging.getLogger(__name__)

COURSE_STARTER = "starter"
COURSE_MAIN = "main"
COURSE_SIDE = "side"
COURSE_DESSERT = "dessert"
COURSE_SNACK = "snack"
COURSE_DRINK = "drink"
COURSE_EXTRA = "extra"
COURSES = (
    COURSE_STARTER,
    COURSE_MAIN,
    COURSE_SIDE,
    COURSE_DESSERT,
    COURSE_SNACK,
    COURSE_DRINK,
    COURSE_EXTRA,
)
DISH_COURSES = (COURSE_STARTER, COURSE_MAIN, COURSE_SIDE, COURSE_DESSERT, COURSE_SNACK)
COURSE_LABELS = {
    COURSE_STARTER: "Vorspeise",
    COURSE_MAIN: "Hauptgang",
    COURSE_SIDE: "Beilagen",
    COURSE_DESSERT: "Dessert",
    COURSE_SNACK: "Snacks",
    COURSE_DRINK: "Getränke",
    COURSE_EXTRA: "Zubehör",
}
COURSE_EMOJI = {
    COURSE_STARTER: "🥗",
    COURSE_MAIN: "🍽️",
    COURSE_SIDE: "🥔",
    COURSE_DESSERT: "🍰",
    COURSE_SNACK: "🍿",
    COURSE_DRINK: "🥤",
    COURSE_EXTRA: "🧺",
}
# spoken / typed course words (folded) -> course
COURSE_WORDS = {
    "vorspeise": COURSE_STARTER,
    "vorspeisen": COURSE_STARTER,
    "starter": COURSE_STARTER,
    "hauptgang": COURSE_MAIN,
    "hauptgericht": COURSE_MAIN,
    "hauptspeise": COURSE_MAIN,
    "main": COURSE_MAIN,
    "beilage": COURSE_SIDE,
    "beilagen": COURSE_SIDE,
    "side": COURSE_SIDE,
    "nachtisch": COURSE_DESSERT,
    "nachspeise": COURSE_DESSERT,
    "dessert": COURSE_DESSERT,
    "snack": COURSE_SNACK,
    "snacks": COURSE_SNACK,
    "knabberei": COURSE_SNACK,
    "getraenk": COURSE_DRINK,
    "getraenke": COURSE_DRINK,
    "drink": COURSE_DRINK,
    "drinks": COURSE_DRINK,
    "zubehoer": COURSE_EXTRA,
    "extra": COURSE_EXTRA,
    "extras": COURSE_EXTRA,
}

# recipe tags (folded) per course; drinks and side components never fill a meal slot of
# the week plan (manager._fits_meal) unless they are also a main dish
DRINK_TAGS = frozenset(
    {
        "getraenk",
        "getraenke",
        "drink",
        "drinks",
        "cocktail",
        "cocktails",
        "mocktail",
        "mocktails",
        "bowle",
        "punsch",
        "heissgetraenk",
    }
)
COMPONENT_TAGS = frozenset(
    DRINK_TAGS
    | {"beilage", "beilagen", "vorspeise", "vorspeisen", "dip", "dips", "sauce", "saucen"}
)
MAIN_TAGS = frozenset(
    {"hauptgericht", "hauptspeise", "hauptgang", "mittagessen", "abendessen", "dinner", "lunch"}
)
STARTER_TAGS = frozenset({"vorspeise", "vorspeisen", "starter", "antipasti", "antipasto"})
SIDE_TAGS = frozenset({"beilage", "beilagen", "side", "dip", "dips", "sauce", "saucen"})
DESSERT_TAGS = frozenset(
    {"dessert", "desserts", "nachtisch", "nachspeise", "suessspeise", "kuchen", "torte"}
)
SNACK_COURSE_TAGS = frozenset({"snack", "snacks", "fingerfood", "party", "knabbern", "gebaeck"})
# second choices: a soup can be a starter, a salad a side
SECONDARY = {COURSE_STARTER: frozenset({"suppe", "salat"}), COURSE_SIDE: frozenset({"salat"})}

# words of dish names (folded) when a recipe or a free item has no course tag
_NAME_COURSES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        COURSE_DESSERT,
        (
            "mousse",
            "tiramisu",
            "pudding",
            "panna cotta",
            "creme brulee",
            "parfait",
            "kompott",
            "crumble",
            "eis ",
            "sorbet",
            "bratapfel",
            "dessert",
            "nachtisch",
            "torte",
            "kuchen",
            "muffin",
            "brownie",
            "waffel",
            "rote gruetze",
        ),
    ),
    (
        COURSE_SIDE,
        (
            "salat",
            "rotkohl",
            "kloesse",
            "knoedel",
            "spaetzle",
            "pommes",
            "kroketten",
            "baguette",
            "kraeuterbutter",
            "tzatziki",
            "dip",
            "sauce",
            "sosse",
            "folienkartoffel",
            "maiskolben",
            "grillgemuese",
            "reis",
            "kartoffelpueree",
            "bratkartoffeln",
        ),
    ),
    (
        COURSE_SNACK,
        (
            "chips",
            "popcorn",
            "nachos",
            "salzstangen",
            "erdnuesse",
            "cracker",
            "brezel",
            "fingerfood",
            "spiesse",
            "pizzaschnecken",
            "knabber",
        ),
    ),
)

GENERIC_TEMPLATE = "anlass"
# extras rule: (title, amount, unit, per persons[, course]); amount × ceil(persons / per);
# food (a course other than extra) counts children as half a person
TEMPLATES: dict[str, dict[str, Any]] = {
    "filmabend": {
        "title": "Filmabend",
        "to": "zum Filmabend",
        "emoji": "🎬",
        "time": "20:00",
        "duration_h": 3.0,
        "courses": {COURSE_MAIN: 1, COURSE_SNACK: 1},
        "tags": {
            COURSE_MAIN: ("pizza", "burger", "fingerfood", "party", "amerikanisch", "mexikanisch"),
            COURSE_SNACK: ("snack", "party", "fingerfood", "dip"),
        },
        "names": {
            COURSE_MAIN: ("pizza", "burger", "nachos", "wrap", "quesadilla", "hot dog"),
            COURSE_SNACK: ("nachos", "dip", "popcorn", "chips", "muffin", "brownie"),
        },
        "extras": (
            ("Popcorn", 100, "g", 2, COURSE_SNACK),
            ("Chips", 1, "Tüte", 3, COURSE_SNACK),
            ("Servietten", 1, "Pck.", 20),
        ),
    },
    "grillen": {
        "title": "Grillabend",
        "to": "zum Grillabend",
        "emoji": "🔥",
        "time": "18:00",
        "duration_h": 4.0,
        "courses": {COURSE_MAIN: 2, COURSE_SIDE: 2, COURSE_DESSERT: 1},
        "tags": {
            COURSE_MAIN: ("grillen", "grill", "bbq"),
            COURSE_SIDE: ("salat", "beilage", "dip", "grillen"),
            COURSE_DESSERT: ("dessert", "sommer"),
        },
        "names": {
            COURSE_MAIN: (
                "grill",
                "bratwurst",
                "steak",
                "spiess",
                "burger",
                "wuerstchen",
                "halloumi",
            ),
            COURSE_SIDE: (
                "salat",
                "baguette",
                "kraeuterbutter",
                "tzatziki",
                "dip",
                "maiskolben",
                "grillgemuese",
                "folienkartoffel",
            ),
        },
        "extras": (
            ("Grillkohle", 2.5, "kg", 6),
            ("Grillanzünder", 1, "Pck.", 12),
            ("Grillsoße", 1, "Flasche", 6, COURSE_SIDE),
            ("Servietten", 1, "Pck.", 20),
        ),
    },
    "familienessen": {
        "title": "Familienessen",
        "to": "zum Familienessen",
        "emoji": "👨‍👩‍👧‍👦",
        "time": "12:30",
        "duration_h": 3.0,
        "courses": {COURSE_MAIN: 1, COURSE_SIDE: 1, COURSE_DESSERT: 1},
        "tags": {
            COURSE_MAIN: ("sonntagsessen", "klassiker", "braten", "festlich", "kinder"),
            COURSE_SIDE: ("beilage", "salat", "gemuese"),
            COURSE_DESSERT: ("dessert", "nachtisch", "kuchen", "suess"),
        },
        "names": {COURSE_MAIN: ("braten", "roulade", "schnitzel", "gulasch", "auflauf")},
        "extras": (("Servietten", 1, "Pck.", 20),),
    },
    "weihnachten": {
        "title": "Weihnachtsessen",
        "to": "zum Weihnachtsessen",
        "emoji": "🎄",
        "time": "18:00",
        "duration_h": 4.0,
        "courses": {COURSE_STARTER: 1, COURSE_MAIN: 1, COURSE_SIDE: 2, COURSE_DESSERT: 1},
        "tags": {
            COURSE_STARTER: ("vorspeise", "suppe", "festlich", "weihnachten"),
            COURSE_MAIN: (
                "festlich",
                "weihnachten",
                "braten",
                "gans",
                "ente",
                "wild",
                "sonntagsessen",
            ),
            COURSE_SIDE: ("beilage", "kloesse", "rotkohl"),
            COURSE_DESSERT: ("dessert", "festlich", "weihnachten"),
        },
        "names": {
            COURSE_STARTER: ("suppe", "carpaccio", "lachs", "feldsalat"),
            COURSE_MAIN: (
                "gans",
                "ente",
                "braten",
                "roulade",
                "wild",
                "reh",
                "hirsch",
                "filet",
                "fondue",
                "raclette",
            ),
            COURSE_SIDE: (
                "rotkohl",
                "kloesse",
                "knoedel",
                "kartoffelsalat",
                "rosenkohl",
                "spaetzle",
            ),
            COURSE_DESSERT: (
                "mousse",
                "tiramisu",
                "bratapfel",
                "parfait",
                "creme",
                "panna cotta",
                "lebkuchen",
            ),
        },
        "extras": (("Servietten", 1, "Pck.", 12), ("Kerzen", 1, "Pck.", 12)),
    },
    "silvester": {
        "title": "Silvester",
        "to": "zu Silvester",
        "emoji": "🎆",
        "time": "19:00",
        "duration_h": 6.0,
        "courses": {COURSE_MAIN: 1, COURSE_SNACK: 2},
        "tags": {
            COURSE_MAIN: ("raclette", "fondue", "party", "festlich"),
            COURSE_SNACK: ("party", "fingerfood", "snack", "dip"),
        },
        "names": {
            COURSE_MAIN: ("raclette", "fondue", "buffet"),
            COURSE_SNACK: ("dip", "spiess", "blaetterteig", "muffin"),
        },
        "extras": (
            ("Berliner", 1, "Stück", 1, COURSE_DESSERT),
            ("Wunderkerzen", 1, "Pck.", 6),
            ("Servietten", 1, "Pck.", 20),
        ),
    },
    "geburtstag": {
        "title": "Geburtstag",
        "to": "zum Geburtstag",
        "emoji": "🎂",
        "time": "15:00",
        "duration_h": 4.0,
        "courses": {COURSE_MAIN: 1, COURSE_DESSERT: 1, COURSE_SNACK: 1},
        "tags": {
            COURSE_MAIN: ("party", "kinder", "fingerfood"),
            COURSE_DESSERT: ("kuchen", "backen", "torte", "suess"),
            COURSE_SNACK: ("party", "snack", "fingerfood"),
        },
        "names": {COURSE_DESSERT: ("kuchen", "torte", "muffin", "brownie")},
        "extras": (
            ("Geburtstagskerzen", 1, "Pck.", 30),
            ("Servietten", 1, "Pck.", 20),
            ("Pappteller", 1, "Pck.", 10),
        ),
    },
    "brunch": {
        "title": "Brunch",
        "to": "zum Brunch",
        "emoji": "🥐",
        "time": "10:30",
        "duration_h": 3.0,
        "courses": {COURSE_MAIN: 2, COURSE_SNACK: 1},
        "tags": {
            COURSE_MAIN: ("fruehstueck", "brunch", "eier"),
            COURSE_SNACK: ("fruehstueck", "backen", "suess", "snack"),
        },
        "names": {
            COURSE_MAIN: (
                "ruehrei",
                "omelett",
                "shakshuka",
                "pfannkuchen",
                "pancake",
                "french toast",
                "porridge",
                "overnight oats",
                "quiche",
            ),
            COURSE_SNACK: ("muffin", "brot", "croissant"),
        },
        "extras": (
            ("Brötchen", 2, "Stück", 1, COURSE_SIDE),
            ("Servietten", 1, "Pck.", 20),
        ),
    },
    "raclette": {
        "title": "Raclette-Abend",
        "to": "zum Raclette-Abend",
        "emoji": "🧀",
        "time": "19:00",
        "duration_h": 4.0,
        "courses": {COURSE_SIDE: 1, COURSE_DESSERT: 1},
        "tags": {
            COURSE_SIDE: ("salat", "beilage", "dip"),
            COURSE_DESSERT: ("dessert", "nachtisch"),
        },
        "names": {COURSE_SIDE: ("salat", "dip", "baguette")},
        "extras": (
            ("Raclettekäse", 200, "g", 1, COURSE_MAIN),
            ("Kartoffeln", 250, "g", 1, COURSE_MAIN),
            ("Kochschinken", 80, "g", 1, COURSE_MAIN),
            ("Champignons", 100, "g", 1, COURSE_MAIN),
            ("Gewürzgurken", 1, "Glas", 6, COURSE_SIDE),
            ("Silberzwiebeln", 1, "Glas", 8, COURSE_SIDE),
        ),
    },
    "fondue": {
        "title": "Fondue",
        "to": "zum Fondue",
        "emoji": "🫕",
        "time": "19:00",
        "duration_h": 4.0,
        "courses": {COURSE_SIDE: 2, COURSE_DESSERT: 1},
        "tags": {COURSE_SIDE: ("dip", "sauce", "salat", "beilage")},
        "names": {COURSE_SIDE: ("dip", "sauce", "aioli", "baguette", "salat")},
        "extras": (
            ("Fondue-Fleisch", 200, "g", 1, COURSE_MAIN),
            ("Baguette", 1, "Stück", 3, COURSE_SIDE),
            ("Brennpaste", 1, "Pck.", 8),
        ),
    },
    "party": {
        "title": "Party",
        "to": "zur Party",
        "emoji": "🎉",
        "time": "19:00",
        "duration_h": 5.0,
        "courses": {COURSE_MAIN: 1, COURSE_SNACK: 3},
        "tags": {
            COURSE_MAIN: ("party", "fingerfood", "auflauf"),
            COURSE_SNACK: ("party", "fingerfood", "snack", "dip"),
        },
        "names": {
            COURSE_MAIN: ("chili", "pizza", "wrap", "nudelsalat"),
            COURSE_SNACK: ("dip", "nachos", "spiess", "muffin", "pizzaschnecken"),
        },
        "extras": (
            ("Chips", 1, "Tüte", 4, COURSE_SNACK),
            ("Salzstangen", 1, "Tüte", 6, COURSE_SNACK),
            ("Servietten", 1, "Pck.", 20),
            ("Eiswürfel", 1, "Tüte", 8),
        ),
    },
    "ostern": {
        "title": "Osteressen",
        "to": "zum Osteressen",
        "emoji": "🐣",
        "time": "12:30",
        "duration_h": 4.0,
        "courses": {COURSE_STARTER: 1, COURSE_MAIN: 1, COURSE_SIDE: 1, COURSE_DESSERT: 1},
        "tags": {
            COURSE_STARTER: ("vorspeise", "suppe", "fruehling"),
            COURSE_MAIN: ("lamm", "ostern", "festlich", "fruehling", "braten", "sonntagsessen"),
            COURSE_DESSERT: ("dessert", "kuchen", "ostern"),
        },
        "names": {
            COURSE_STARTER: ("baerlauch", "suppe", "salat"),
            COURSE_MAIN: ("lamm", "braten", "spargel"),
            COURSE_SIDE: ("spargel", "kartoffel", "salat"),
            COURSE_DESSERT: ("osterlamm", "moehrenkuchen", "karottenkuchen", "rhabarber"),
        },
        "extras": (("Eier zum Färben", 2, "Stück", 1), ("Servietten", 1, "Pck.", 20)),
    },
    GENERIC_TEMPLATE: {
        "title": "Anlass",
        "to": "zum Anlass",
        "emoji": "🎉",
        "time": "18:00",
        "duration_h": 3.0,
        "courses": {COURSE_MAIN: 1},
        "tags": {},
        "names": {},
        "extras": (),
    },
}
# spoken / typed words (folded) -> template, longest first when matching
TEMPLATE_WORDS = {
    "filmabend": "filmabend",
    "kinoabend": "filmabend",
    "film abend": "filmabend",
    "serienabend": "filmabend",
    "film": "filmabend",
    "grillabend": "grillen",
    "grillen": "grillen",
    "grillparty": "grillen",
    "grillfest": "grillen",
    "barbecue": "grillen",
    "bbq": "grillen",
    "familienessen": "familienessen",
    "sonntagsessen": "familienessen",
    "familienfeier": "familienessen",
    "weihnachtsessen": "weihnachten",
    "weihnachtsmenue": "weihnachten",
    "weihnachten": "weihnachten",
    "heiligabend": "weihnachten",
    "weihnachtsfeier": "weihnachten",
    "festessen": "weihnachten",
    "silvesterparty": "silvester",
    "silvesteressen": "silvester",
    "silvester": "silvester",
    "geburtstagsfeier": "geburtstag",
    "geburtstagsparty": "geburtstag",
    "kindergeburtstag": "geburtstag",
    "geburtstag": "geburtstag",
    "brunch": "brunch",
    "sonntagsbrunch": "brunch",
    "raclette abend": "raclette",
    "racletteabend": "raclette",
    "raclette": "raclette",
    "fondue abend": "fondue",
    "fondueabend": "fondue",
    "fondue": "fondue",
    "party": "party",
    "feier": "party",
    "fete": "party",
    "osteressen": "ostern",
    "osterbrunch": "ostern",
    "ostern": "ostern",
    "anlass": GENERIC_TEMPLATE,
}
_TEMPLATE_ORDER = sorted(TEMPLATE_WORDS, key=lambda w: (-len(w.split()), -len(w)))

KEEP_DAYS = 365  # occasions are kept this long after their date
EXPORT_PAST_DAYS = 30  # the panel gets occasions from this many days back
MAX_OCCASIONS = 200
MAX_ITEMS = 60
TITLE_MAX = 80
NOTE_MAX = 500
REASON_MAX = 140
MAX_GUESTS = 200
MAX_CHILDREN = 100
DEFAULT_SUGGESTIONS = 5
MAX_SUGGESTIONS = 20
AI_CANDIDATES = 12  # recipes per course the AI may choose from
AI_PER_COURSE = 4
AUTO_EXTRA = "extra"
AUTO_DRINK = "drink"
_TIME_RE = re.compile(r"^\s*(\d{1,2})(?:\s*[:.]\s*(\d{2}))?\s*(?:uhr)?\s*$", re.IGNORECASE)
_ITEM_FIELDS = (
    "uid",
    "course",
    "recipe_id",
    "product_id",
    "title",
    "name",
    "servings",
    "quantity",
    "unit",
    "alcohol",
    "note",
    "ai",
    "auto",
    "drink",
    "hint",
)


def _error(key: str, **placeholders: Any) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders={k: str(v) for k, v in placeholders.items()},
    )


def _text(value: Any, limit: int = TITLE_MAX) -> str:
    return " ".join(str(value or "").split())[:limit]


# ----------------------------------------------------------------------
# Templates and courses
# ----------------------------------------------------------------------


def resolve_template(text: str | None) -> str | None:
    """'Grillabend' / 'grillen' / 'Weihnachtsessen bei Oma' -> template id (None if no
    template is named)."""
    folded = fold(str(text or ""))
    if not folded:
        return None
    if folded in TEMPLATES:
        return folded
    padded = f" {folded} "
    for word in _TEMPLATE_ORDER:
        if f" {word} " in padded or (len(word) > 5 and word in folded.replace(" ", "")):
            return TEMPLATE_WORDS[word]
    return None


def _template_word(text: str) -> bool:
    """True for a plain template word ('grillen', 'Grillabend', 'Weihnachtsessen') – no
    own title like 'Omas Geburtstag'."""
    folded = fold(text)
    return (
        folded in TEMPLATES
        or folded in TEMPLATE_WORDS
        or any(folded == fold(info["title"]) for info in TEMPLATES.values())
    )


def resolve_course(text: str | None) -> str | None:
    """'Nachtisch' / 'dessert' -> course id (None if unknown)."""
    folded = fold(str(text or ""))
    if folded in COURSES:
        return folded
    return COURSE_WORDS.get(folded)


def template_info(template: str | None) -> dict[str, Any]:
    """The template (the generic one for unknown ids)."""
    return TEMPLATES.get(template or "", TEMPLATES[GENERIC_TEMPLATE])


def templates_view() -> list[dict[str, Any]]:
    """Templates for the panel: [{id, title, emoji, time, duration_h, courses, counts}]
    (counts: how many dishes per course the template wants – the panel's "✓ Fehlendes
    übernehmen" fills up to them like apply_menu())."""
    return [
        {
            "id": key,
            "title": info["title"],
            "emoji": info["emoji"],
            "time": info["time"],
            "duration_h": info["duration_h"],
            "courses": list(info["courses"]),
            "counts": dict(info["courses"]),
        }
        for key, info in TEMPLATES.items()
    ]


def courses_view() -> list[dict[str, Any]]:
    """Courses for the panel: [{id, label, emoji}]."""
    return [{"id": c, "label": COURSE_LABELS[c], "emoji": COURSE_EMOJI[c]} for c in COURSES]


def _folded_tags(recipe: dict[str, Any]) -> set[str]:
    return {fold(str(t)) for t in recipe.get("tags") or []}


def _name_course(folded_name: str) -> str | None:
    padded = f" {folded_name} "
    for course, words in _NAME_COURSES:
        if any(word in padded for word in words):
            return course
    return None


def recipe_courses(recipe: dict[str, Any]) -> set[str]:
    """Every course a recipe can be served as (tags first, then its name): a drink is only
    a drink; a main dish tagged "Salat" is also a side, a soup also a starter. 1.5.1: by
    the recipe's kind (kinds.py) – only a meal or a breakfast is a main course, a side or
    component is a side, a dessert a dessert, a snack a snack."""
    from .kinds import (  # the kinds import this module
        KIND_BREAKFAST,
        KIND_COMPONENT,
        KIND_DESSERT,
        KIND_DRINK,
        KIND_MEAL,
        KIND_SIDE,
        KIND_SNACK,
        recipe_kind,
    )

    kind = recipe_kind(recipe)
    if kind == KIND_DRINK:
        return {COURSE_DRINK}
    courses = _tag_courses(recipe)
    courses.discard(COURSE_DRINK)
    if kind == KIND_MEAL:
        courses.add(COURSE_MAIN)
    elif kind != KIND_BREAKFAST:
        courses.discard(COURSE_MAIN)
        if not courses:
            courses.add(
                {
                    KIND_SIDE: COURSE_SIDE,
                    KIND_COMPONENT: COURSE_SIDE,
                    KIND_DESSERT: COURSE_DESSERT,
                    KIND_SNACK: COURSE_SNACK,
                }.get(kind, COURSE_SIDE)
            )
    return courses


def _tag_courses(recipe: dict[str, Any]) -> set[str]:
    """The courses of a recipe by its tags and name (1.5)."""
    tags = _folded_tags(recipe)
    if tags & DRINK_TAGS or (not tags & MAIN_TAGS and is_drink_name(str(recipe.get("name") or ""))):
        return {COURSE_DRINK}
    courses: set[str] = set()
    if tags & MAIN_TAGS:
        courses.add(COURSE_MAIN)
    if tags & STARTER_TAGS:
        courses.add(COURSE_STARTER)
    if tags & SIDE_TAGS:
        courses.add(COURSE_SIDE)
    if tags & DESSERT_TAGS:
        courses.add(COURSE_DESSERT)
    if tags & SNACK_COURSE_TAGS:
        courses.add(COURSE_SNACK)
    if not courses and (by_name := _name_course(fold(str(recipe.get("name") or "")))):
        courses.add(by_name)
    if not courses:
        courses.add(COURSE_MAIN)
    for course, secondary in SECONDARY.items():
        if tags & secondary:
            courses.add(course)
    return courses


def recipe_course(recipe: dict[str, Any]) -> str:
    """The main course of a recipe: drink, main, dessert, starter, side or snack."""
    courses = recipe_courses(recipe)
    tags = _folded_tags(recipe)
    for course in (COURSE_DRINK, COURSE_MAIN):
        if course in courses:
            return course
    for course, tagset in (
        (COURSE_DESSERT, DESSERT_TAGS),
        (COURSE_STARTER, STARTER_TAGS),
        (COURSE_SIDE, SIDE_TAGS),
        (COURSE_SNACK, SNACK_COURSE_TAGS),
    ):
        if course in courses and tags & tagset:
            return course
    return next(c for c in COURSES if c in courses)


def is_drink_name(name: str) -> bool:
    """True for names of drinks ('Apfelschorle', 'Glühwein', 'Kinderpunsch', 'Cola')."""
    folded = fold(name)
    if not folded:
        return False
    if any(fold(d["title"]) == folded or fold(d["name"]) == folded for d in DRINKS.values()):
        return True
    words = (
        "schorle",
        "limonade",
        "limo",
        "saft",
        "punsch",
        "bowle",
        "cocktail",
        "mocktail",
        "lassi",
        "smoothie",
        "eistee",
        "kakao",
        "heisse schokolade",
        "mineralwasser",
        "cola",
        "spritz",
    )
    if any(food in folded for food in _FOOD_WORDS):
        return False
    padded = f" {folded} "
    if any(f" {word} " in padded or folded.endswith(word) for word in words):
        return True
    return is_alcoholic(name)


# a dish named after a drink is still a dish ("Kakao-Bananenbrot", "Rotweinkuchen")
_FOOD_WORDS = (
    "kuchen",
    "brot",
    "muffin",
    "torte",
    "pudding",
    "creme",
    "sauce",
    "sosse",
    "gelee",
    "porridge",
    "oats",
    "pancake",
    "waffel",
    "braten",
    "gulasch",
    "risotto",
    "suppe",
    "eis",
    "huhn",
    "haehnchen",
    "fleisch",
    "fisch",
    "kekse",
    "plaetzchen",
)


def guess_course(title: str) -> str:
    """The course of a free item: drink, a non-food extra, else by its name, else main."""
    if is_drink_name(title):
        return COURSE_DRINK
    if is_nonfood_category(guess_category(title)) or fold(title) in _EXTRA_WORDS:
        return COURSE_EXTRA
    return _name_course(fold(title)) or COURSE_MAIN


_EXTRA_WORDS = {
    fold(rule[0])
    for info in TEMPLATES.values()
    for rule in info["extras"]
    if len(rule) < 5 or rule[4] == COURSE_EXTRA
}


# ----------------------------------------------------------------------
# Occasions
# ----------------------------------------------------------------------


def servings_of(occasion: dict[str, Any]) -> int:
    """Default servings of the dishes: guests + half a serving per child."""
    guests = int(occasion.get("guests") or 0)
    children = int(occasion.get("children") or 0)
    return max(1, math.ceil(guests + children / 2 - 1e-9))


def persons_of(occasion: dict[str, Any]) -> int:
    """Guests and children (extras like napkins count everybody)."""
    return max(1, int(occasion.get("guests") or 0) + int(occasion.get("children") or 0))


def occasion_date(occasion: dict[str, Any]) -> date:
    """The occasion's date."""
    return date.fromisoformat(str(occasion["date"])[:10])


def occasion_start(occasion: dict[str, Any]) -> datetime:
    """Local start (an occasion without time: the template's time)."""
    parsed = dt_util.parse_time(
        str(occasion.get("time") or template_info(occasion.get("template"))["time"])
    )
    return datetime.combine(
        occasion_date(occasion), parsed or time(18, 0), tzinfo=dt_util.get_default_time_zone()
    )


def occasion_end(occasion: dict[str, Any]) -> datetime:
    """Local end (start + duration; an occasion without time lasts the whole day)."""
    if not occasion.get("time"):
        return datetime.combine(
            occasion_date(occasion) + timedelta(days=1),
            time(0, 0),
            tzinfo=dt_util.get_default_time_zone(),
        )
    hours = float(
        occasion.get("duration_h") or template_info(occasion.get("template"))["duration_h"]
    )
    return occasion_start(occasion) + timedelta(hours=hours)


def occasion_label(occasion: dict[str, Any]) -> str:
    """'🎬 Filmabend' (shopping items name it as their "recipe")."""
    emoji = template_info(occasion.get("template"))["emoji"]
    return f"{emoji} {occasion.get('title') or ''}".strip()


def parse_time_text(value: Any) -> str | None:
    """'20:00', '20 Uhr', '19.30' -> 'HH:MM'; '' / None -> None; else invalid_time."""
    if value in (None, ""):
        return None
    if isinstance(value, time):
        return value.strftime("%H:%M")
    match = _TIME_RE.match(str(value))
    if match:
        hour, minute = int(match.group(1)), int(match.group(2) or 0)
        if hour < 24 and minute < 60:
            return f"{hour:02d}:{minute:02d}"
    raise _error("invalid_time", time=value)


def _int(value: Any, low: int, high: int, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _date(manager: EssensplanerManager, value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return parse_date(str(value or ""), manager.today())[0]
    except ValueError as err:
        raise _error("invalid_date", date=value) from err


def require_occasion(manager: EssensplanerManager, occasion_id: str) -> dict[str, Any]:
    """An occasion by id or occasion_not_found."""
    found = manager.occasions.get(str(occasion_id or ""))
    if found is None:
        raise _error("occasion_not_found", occasion=occasion_id)
    return found


def resolve_occasion(
    manager: EssensplanerManager, text: str | None = None, day: date | None = None
) -> dict[str, Any]:
    """An occasion by id, title, template word ('Grillabend') and/or date – the next one
    from today first, else the latest. occasion_not_found."""
    raw = str(text or "").strip()
    if raw and raw in manager.occasions:
        return manager.occasions[raw]
    today = manager.today().isoformat()
    candidates = list(manager.occasions.values())
    if day is not None:
        same_day = [o for o in candidates if o.get("date") == day.isoformat()]
        near = [
            o for o in candidates if abs((occasion_date(o) - day).days) <= 1 and o not in same_day
        ]
        candidates = same_day or near
    if raw:
        folded = fold(raw)
        template = resolve_template(raw)
        exact = [o for o in candidates if fold(o.get("title") or "") == folded]
        by_template = [o for o in candidates if template and o.get("template") == template]
        contains = [
            o
            for o in candidates
            if folded
            and (folded in fold(o.get("title") or "") or fold(o.get("title") or "") in folded)
        ]
        candidates = exact or by_template or contains
    if not candidates:
        raise _error("occasion_not_found", occasion=raw or (day.isoformat() if day else ""))
    upcoming = sorted((o for o in candidates if o["date"] >= today), key=lambda o: o["date"])
    if upcoming:
        return upcoming[0]
    return max(candidates, key=lambda o: o["date"])


def occasions_between(manager: EssensplanerManager, start: date, end: date) -> list[dict[str, Any]]:
    """Occasions from start to end (inclusive), sorted by date and time."""
    first, last = start.isoformat(), end.isoformat()
    found = [o for o in manager.occasions.values() if first <= str(o.get("date")) <= last]
    found.sort(key=lambda o: (o["date"], o.get("time") or ""))
    return found


def occasions_on(manager: EssensplanerManager, day: date) -> list[dict[str, Any]]:
    """Occasions of one day."""
    return occasions_between(manager, day, day)


def next_occasion(
    manager: EssensplanerManager, now: datetime | None = None
) -> dict[str, Any] | None:
    """The running or next occasion (within a year)."""
    now = now or dt_util.now()
    upcoming = occasions_between(
        manager, now.date() - timedelta(days=2), now.date() + timedelta(days=366)
    )
    running = [o for o in upcoming if occasion_end(o) >= now]
    return min(running, key=occasion_start) if running else None


def _new_id(manager: EssensplanerManager) -> str:
    while True:
        new = uuid.uuid4().hex[:8]
        if new not in manager.occasions:
            return new


def _match_recipe(manager: EssensplanerManager, text: str) -> dict[str, Any] | None:
    """A recipe named like a dish ('Kartoffelsalat'): the exact name, else the shortest
    recipe whose name contains all its words (no fuzzy guess – a free item is better than
    the wrong recipe)."""
    if not text:
        return None
    if (recipe := manager.recipes.get(text)) is not None:
        return recipe
    if (recipe := manager.get_recipe_by_name(text)) is not None:
        return recipe
    words = fold(text).split()
    if not words:
        return None
    found = [
        r for r in manager.recipes.values() if all(f" {w}" in f" {fold(r['name'])}" for w in words)
    ]
    return min(found, key=lambda r: len(r["name"])) if found else None


def normalize_item(
    manager: EssensplanerManager,
    raw: Any,
    course: str | None = None,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """An occasion item from a text or dict {uid?, course?, recipe_id? | recipe? |
    product_id?, title?, servings?, quantity?, unit?, alcohol?, note?}: a recipe (title =
    recipe name), a product (title = product title, quantity = packs) or free text.
    Errors recipe_not_found, product_not_found, invalid_course, name_required."""
    if isinstance(raw, str):
        raw = {"title": raw}
    if not isinstance(raw, dict):
        raise _error("name_required")
    title = _text(raw.get("title") or raw.get("name"))
    recipe = None
    product = None
    if raw.get("recipe_id"):
        recipe = manager.recipes.get(str(raw["recipe_id"]))
        if recipe is None:
            raise _error("recipe_not_found", name=raw["recipe_id"])
    elif raw.get("recipe"):
        recipe = manager.resolve_recipe(name=str(raw["recipe"]))
    if raw.get("product_id"):
        from .products import product_title, require_product  # imports the manager

        product = require_product(manager, str(raw["product_id"]))
        title = title or product_title(product)
    if recipe is not None:
        title = recipe["name"]
    if not title:
        raise _error("name_required")
    wanted = raw.get("course") or course
    if wanted:
        resolved = resolve_course(str(wanted))
        if resolved is None:
            raise _error("invalid_course", course=wanted)
        wanted = resolved
    else:
        wanted = recipe_course(recipe) if recipe is not None else guess_course(title)
    old = existing or {}
    item: dict[str, Any] = {
        "uid": str(raw.get("uid") or old.get("uid") or uuid.uuid4().hex[:12]),
        "course": wanted,
        "title": title,
    }
    if recipe is not None:
        item["recipe_id"] = recipe["id"]
        servings = _int(raw.get("servings"), 1, 500, 0)
        if servings:
            item["servings"] = servings
    if product is not None:
        item["product_id"] = product["id"]
    quantity = _float(raw.get("quantity"))
    if recipe is None and quantity is not None:
        item["quantity"] = round(quantity, 3)
        unit = normalize_unit(str(raw.get("unit") or "").strip())
        if product is None and unit:
            item["unit"] = unit[:12]
    if recipe is None and product is None and raw.get("name") and raw.get("title"):
        name = _text(raw.get("name"))
        if name and name != title:
            item["name"] = name  # what is bought ("Rotwein" for "Rotwein, leicht")
    if wanted == COURSE_DRINK:
        said = raw.get("alcohol")
        item["alcohol"] = bool(said) if isinstance(said, bool) else is_alcoholic(title)
    if note := _text(raw.get("note"), NOTE_MAX):
        item["note"] = note
    if raw.get("ai") is True:
        item["ai"] = True
    if hint := _text(raw.get("hint"), REASON_MAX):
        item["hint"] = hint
    drink = raw.get("drink") or old.get("drink")
    if isinstance(drink, str) and drink in DRINKS:
        item["drink"] = drink
    auto = raw.get("auto") if "auto" in raw else old.get("auto")
    if auto in (AUTO_EXTRA, AUTO_DRINK):
        changed = old and "quantity" in raw and _float(raw.get("quantity")) != old.get("quantity")
        if not changed:
            item["auto"] = auto  # recomputed when the number of guests changes
    return item


def _items(
    manager: EssensplanerManager,
    raws: Any,
    existing: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if raws is None:
        return []
    if isinstance(raws, (str, dict)):
        raws = [raws]
    by_uid = {i.get("uid"): i for i in existing or []}
    items: list[dict[str, Any]] = []
    for raw in list(raws)[:MAX_ITEMS]:
        uid = raw.get("uid") if isinstance(raw, dict) else None
        items.append(normalize_item(manager, raw, existing=by_uid.get(uid)))
    return items


def _touch(manager: EssensplanerManager, occasion: dict[str, Any]) -> None:
    occasion["updated"] = dt_util.utcnow().isoformat()
    prune_occasions(manager)
    manager.occasions_changed()


def create_occasion(
    manager: EssensplanerManager,
    template: str | None = None,
    day: date | str | None = None,
    time_text: str | None = None,
    guests: int | None = None,
    children: int | None = None,
    title: str | None = None,
    auto_fill: bool = False,
    duration_h: float | None = None,
    notes: str | None = None,
    items: Any = None,
    save: bool = True,
) -> dict[str, Any]:
    """A new occasion. template: id or word ('Grillabend'; else the title names it, else
    the generic "Anlass"); title default: the template's title; time default: the
    template's; guests default: the default servings. auto_fill: dishes per course (rule
    suggestions), drinks and the template's extras. Errors name_required,
    invalid_template, invalid_date, invalid_time."""
    if template:
        found = resolve_template(template)
        if found is None:
            if title:
                raise _error("invalid_template", template=template)
            title = str(template)
        elif not title and not _template_word(str(template)):
            title = str(template)  # "Omas Geburtstag": the template and the title
        template = found
    title = _text(title)
    template = template or resolve_template(title) or GENERIC_TEMPLATE
    info = TEMPLATES[template]
    title = title or info["title"]
    if not title:
        raise _error("name_required")
    now = dt_util.utcnow().isoformat()
    duration = _float(duration_h) or info["duration_h"]
    occasion: dict[str, Any] = {
        "id": _new_id(manager),
        "title": title,
        "template": template,
        "date": _date(manager, day if day is not None else manager.today()).isoformat(),
        "time": parse_time_text(time_text) if time_text not in (None, "") else info["time"],
        "duration_h": round(min(max(duration, 0.5), 48.0), 2),
        "guests": _int(guests, 1, MAX_GUESTS, manager.default_servings),
        "children": _int(children, 0, MAX_CHILDREN, 0),
        "items": _items(manager, items),
        "notes": _text(notes, NOTE_MAX),
        "created": now,
        "updated": now,
    }
    manager.occasions[occasion["id"]] = occasion
    if auto_fill:
        fill_occasion(manager, occasion)
    if save:
        _touch(manager, occasion)
    return occasion


def update_occasion(
    manager: EssensplanerManager, occasion_id: str, data: dict[str, Any]
) -> dict[str, Any]:
    """Change an occasion: title, template, date, time ("" = all day), duration_h, guests,
    children, notes, items (replaces all), add_items, remove_items (uids or titles).
    Quantities of automatic drinks and extras follow the number of guests."""
    occasion = require_occasion(manager, occasion_id)
    before = (occasion.get("guests"), occasion.get("children"), occasion.get("duration_h"))
    if "title" in data and data["title"] is not None:
        title = _text(data["title"])
        if not title:
            raise _error("name_required")
        occasion["title"] = title
    if data.get("template"):
        template = resolve_template(str(data["template"]))
        if template is None:
            raise _error("invalid_template", template=data["template"])
        occasion["template"] = template
    if data.get("date") not in (None, ""):
        occasion["date"] = _date(manager, data["date"]).isoformat()
    if "time" in data:
        occasion["time"] = parse_time_text(data["time"])
    if data.get("duration_h") not in (None, ""):
        duration = _float(data["duration_h"])
        if duration:
            occasion["duration_h"] = round(min(max(duration, 0.5), 48.0), 2)
    if data.get("guests") not in (None, ""):
        occasion["guests"] = _int(data["guests"], 1, MAX_GUESTS, occasion["guests"])
    if data.get("children") not in (None, ""):
        occasion["children"] = _int(data["children"], 0, MAX_CHILDREN, occasion["children"])
    if "notes" in data and data["notes"] is not None:
        occasion["notes"] = _text(data["notes"], NOTE_MAX)
    if data.get("items") is not None:
        occasion["items"] = _items(manager, data["items"], occasion.get("items"))
    if data.get("remove_items"):
        remove = data["remove_items"]
        for value in [remove] if isinstance(remove, str) else list(remove):
            _remove(occasion, str(value))
    if data.get("add_items"):
        added = _items(manager, data["add_items"])
        occasion["items"] = (occasion.get("items") or []) + added
        del occasion["items"][MAX_ITEMS:]
    after = (occasion.get("guests"), occasion.get("children"), occasion.get("duration_h"))
    if after != before:
        rescale_auto_items(manager, occasion)
    _touch(manager, occasion)
    return occasion


def save_occasion(manager: EssensplanerManager, data: dict[str, Any]) -> dict[str, Any]:
    """Create (no id) or change (id) an occasion from a dict (websocket / service)."""
    if data.get("id"):
        return update_occasion(manager, str(data["id"]), data)
    return create_occasion(
        manager,
        template=data.get("template"),
        day=data.get("date"),
        time_text=data.get("time"),
        guests=data.get("guests"),
        children=data.get("children"),
        title=data.get("title"),
        auto_fill=bool(data.get("auto_fill", False)),
        duration_h=data.get("duration_h"),
        notes=data.get("notes"),
        items=[*(data.get("items") or []), *(data.get("add_items") or [])] or None,
    )


def delete_occasion(manager: EssensplanerManager, occasion_id: str) -> dict[str, Any]:
    """Remove an occasion (its shopping items stay)."""
    occasion = require_occasion(manager, occasion_id)
    del manager.occasions[occasion["id"]]
    manager.occasions_changed()
    return occasion


def _remove(occasion: dict[str, Any], value: str) -> dict[str, Any] | None:
    items = occasion.get("items") or []
    found = next((i for i in items if i.get("uid") == value), None)
    if found is None:
        folded = fold(value)
        found = next((i for i in items if fold(i.get("title") or "") == folded), None)
    if found is None and value:
        folded = fold(value)
        found = next((i for i in items if folded and folded in fold(i.get("title") or "")), None)
    if found is not None:
        items.remove(found)
    return found


def add_item(
    manager: EssensplanerManager, occasion_id: str, raw: Any, course: str | None = None
) -> dict[str, Any]:
    """Add a dish, drink or extra ('Kartoffelsalat': the recipe of that name, else free
    text; the course from the recipe or the name)."""
    occasion = require_occasion(manager, occasion_id)
    if isinstance(raw, str):
        recipe = _match_recipe(manager, raw)
        raw = {"recipe_id": recipe["id"]} if recipe is not None else {"title": raw}
    item = normalize_item(manager, raw, course)
    occasion.setdefault("items", []).append(item)
    del occasion["items"][MAX_ITEMS:]
    _touch(manager, occasion)
    return item


def remove_item(manager: EssensplanerManager, occasion_id: str, value: str) -> dict[str, Any]:
    """Remove an item by uid or title; occasion_item_not_found."""
    occasion = require_occasion(manager, occasion_id)
    found = _remove(occasion, value)
    if found is None:
        raise _error("occasion_item_not_found", item=value, occasion=occasion["title"])
    _touch(manager, occasion)
    return found


def prune_occasions(manager: EssensplanerManager) -> int:
    """Drop occasions more than KEEP_DAYS in the past (and the oldest above
    MAX_OCCASIONS). Returns the number removed."""
    limit = (manager.today() - timedelta(days=KEEP_DAYS)).isoformat()
    old = [k for k, o in manager.occasions.items() if str(o.get("date") or "") < limit]
    for key in old:
        del manager.occasions[key]
    extra = len(manager.occasions) - MAX_OCCASIONS
    if extra > 0:
        for key in sorted(manager.occasions, key=lambda k: manager.occasions[k]["date"])[:extra]:
            del manager.occasions[key]
        return len(old) + extra
    return len(old)


def load_occasions(value: Any) -> dict[str, dict[str, Any]]:
    """Stored occasions (missing in data before 1.5: none)."""
    if not isinstance(value, dict):
        return {}
    found: dict[str, dict[str, Any]] = {}
    for key, occasion in value.items():
        if not isinstance(occasion, dict) or not occasion.get("date"):
            continue
        try:
            date.fromisoformat(str(occasion["date"])[:10])
        except ValueError:
            continue
        occasion.setdefault("id", str(key))
        occasion["items"] = [i for i in occasion.get("items") or [] if isinstance(i, dict)]
        found[str(occasion["id"])] = occasion
    return found


# ----------------------------------------------------------------------
# Extras, drinks and suggestions
# ----------------------------------------------------------------------


def _round_quantity(amount: float, unit: str) -> float:
    if unit == "g":
        return float(math.ceil(amount / 50 - 1e-9) * 50)
    if unit in ("kg", "l"):
        return math.ceil(amount * 2 - 1e-9) / 2
    return float(math.ceil(amount - 1e-9))


def extra_quantity(rule: tuple[Any, ...], occasion: dict[str, Any]) -> float:
    """Quantity of a template extra for the occasion's guests."""
    _title, amount, unit, per, *rest = rule
    course = rest[0] if rest else COURSE_EXTRA
    people = persons_of(occasion) if course == COURSE_EXTRA else servings_of(occasion)
    return _round_quantity(float(amount) * math.ceil(people / per - 1e-9), unit)


def template_extras(occasion: dict[str, Any]) -> list[dict[str, Any]]:
    """The template's extras for the occasion (items with auto "extra")."""
    found = []
    for rule in template_info(occasion.get("template"))["extras"]:
        title, _amount, unit, _per, *rest = rule
        found.append(
            {
                "course": rest[0] if rest else COURSE_EXTRA,
                "title": title,
                "quantity": extra_quantity(rule, occasion),
                "unit": unit,
                "auto": AUTO_EXTRA,
            }
        )
    return found


def _occasion_dishes(
    manager: EssensplanerManager, occasion: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str], set[str]]:
    recipes: list[dict[str, Any]] = []
    titles: list[str] = []
    courses: set[str] = set()
    for item in occasion.get("items") or []:
        if item.get("course") in (COURSE_DRINK, COURSE_EXTRA):
            continue
        courses.add(item.get("course") or COURSE_MAIN)
        recipe = manager.recipes.get(item.get("recipe_id") or "")
        if recipe is not None:
            recipes.append(recipe)
        elif item.get("title"):
            titles.append(str(item["title"]))
    return recipes, titles, courses


def occasion_drinks(
    manager: EssensplanerManager,
    occasion: dict[str, Any],
    alcohol: bool | None = None,
    count: int | None = None,
) -> dict[str, Any]:
    """Drink suggestions for the occasion's dishes, template, season and guests."""
    recipes, titles, courses = _occasion_dishes(manager, occasion)
    return suggest_drinks(
        manager,
        recipes=recipes,
        titles=titles,
        template=occasion.get("template"),
        day=occasion_date(occasion),
        alcohol=alcohol,
        guests=int(occasion.get("guests") or 0),
        children=int(occasion.get("children") or 0),
        hours=float(occasion.get("duration_h") or 0) or None,
        count=count or 5,
        courses=courses,
    )


def drink_item(drink: dict[str, Any]) -> dict[str, Any]:
    """An occasion item of a suggested drink."""
    item: dict[str, Any] = {
        "course": COURSE_DRINK,
        "title": drink["title"],
        "alcohol": bool(drink.get("alcohol")),
    }
    if drink.get("name") and drink["name"] != drink["title"]:
        item["name"] = drink["name"]
    if drink.get("recipe_id"):
        item["recipe_id"] = drink["recipe_id"]
    elif drink.get("quantity"):
        item["quantity"] = drink["quantity"]
        item["unit"] = drink.get("unit") or "l"
    if drink.get("id"):
        item["drink"] = drink["id"]
        item["auto"] = AUTO_DRINK
    if drink.get("hint"):
        item["hint"] = drink["hint"]
    if drink.get("ai"):
        item["ai"] = True
    return item


def rescale_auto_items(manager: EssensplanerManager, occasion: dict[str, Any]) -> None:
    """Quantities of automatic extras and drinks after guests, children or duration
    changed (items the user changed keep theirs)."""
    rules = {fold(r[0]): r for r in template_info(occasion.get("template"))["extras"]}
    drinks = []
    for item in occasion.get("items") or []:
        if item.get("auto") == AUTO_EXTRA and (rule := rules.get(fold(item.get("title") or ""))):
            item["quantity"] = extra_quantity(rule, occasion)
        elif item.get("auto") == AUTO_DRINK and item.get("drink") in DRINKS and "quantity" in item:
            info = DRINKS[item["drink"]]
            drinks.append(
                {
                    "id": item["drink"],
                    "alcohol": info["alcohol"],
                    "kids": info.get("kids"),
                    "_item": item,
                }
            )
    if drinks:
        drink_quantities(
            drinks,
            int(occasion.get("guests") or 0),
            int(occasion.get("children") or 0),
            float(occasion.get("duration_h") or 0) or None,
        )
        for drink in drinks:
            if drink.get("quantity"):
                drink["_item"]["quantity"] = drink["quantity"]


def _template_hits(template: str | None, course: str, recipe: dict[str, Any]) -> int:
    info = template_info(template)
    tags = set(info["tags"].get(course, ()))
    names = info["names"].get(course, ())
    hits = len(_folded_tags(recipe) & tags)
    name = f" {fold(recipe.get('name') or '')} "
    hits += sum(1 for word in names if word in name)
    return hits


def _wants_template(template: str | None, course: str) -> bool:
    info = template_info(template)
    return bool(info["tags"].get(course) or info["names"].get(course))


def suggest_course(
    manager: EssensplanerManager,
    occasion: dict[str, Any],
    course: str,
    count: int = DEFAULT_SUGGESTIONS,
    exclude: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Recipes for one course of an occasion, best first: the planning weights (favourite,
    rating, not cooked lately, offers – manager._suggest_weight()) × how well the course
    fits × the template (a barbecue prefers grill dishes). Recipes already in the occasion,
    excluded ones and drinks (see occasion_drinks()) are left out.
    [{recipe summary, recipe_id, title, course, cost, servings, reasons, score}]."""
    if course not in DISH_COURSES:
        return []
    day = occasion_date(occasion)
    servings = servings_of(occasion)
    used = {i.get("recipe_id") for i in occasion.get("items") or []} | set(exclude or ())
    template = occasion.get("template")
    ctx = manager._suggest_context(day, servings=servings, budget=False, variety=False)
    info = template_info(template)
    scored: list[tuple[float, dict[str, Any], int]] = []
    for recipe in manager.recipes.values():
        if recipe["id"] in used or manager.is_excluded(recipe):
            continue
        courses = recipe_courses(recipe)
        if course not in courses:
            continue
        weight = manager._suggest_weight(recipe, ctx)
        weight *= 1.0 if recipe_course(recipe) == course else 0.6
        hits = _template_hits(template, course, recipe)
        if hits:
            weight *= 1 + min(hits, 4)
        elif _wants_template(template, course):
            weight *= 0.5
        scored.append((weight, recipe, hits))
    scored.sort(key=lambda s: (-s[0], fold(s[1]["name"])))
    result = []
    for weight, recipe, hits in scored[: max(1, min(int(count), MAX_SUGGESTIONS))]:
        cost = manager.recipe_cost(recipe, servings, day)
        reasons = []
        if recipe.get("favorite"):
            reasons.append("⭐ Favorit")
        if hits:
            reasons.append(f"{info['emoji']} passt zu {info['title']}")
        if ctx.get("season"):  # 1.5: "🍂 Saison: Kürbis", "🕯️ Adventszeit"
            reasons.extend(recipe_season(manager, recipe, day)["hints"])
        if cost["on_offer"]:
            offers = ", ".join(o["ingredient"] for o in cost["on_offer"][:2])
            reasons.append(f"🏷️ Angebot: {offers}")
        result.append(
            {
                **manager.recipe_summary(recipe),
                "recipe_id": recipe["id"],
                "title": recipe["name"],
                "course": course,
                "cost": cost["total"],
                "servings": servings,
                "reasons": reasons,
                "score": round(weight, 3),
            }
        )
    return result


def suggest_menu(
    manager: EssensplanerManager,
    occasion: dict[str, Any],
    courses: list[str] | None = None,
    count: int = DEFAULT_SUGGESTIONS,
    exclude: set[str] | None = None,
    alcohol: bool | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Rule suggestions per course: dishes (suggest_course()), drinks (occasion_drinks())
    and the template's extras that are missing. courses default: the template's dish
    courses, drinks and extras."""
    wanted = courses or [
        *template_info(occasion.get("template"))["courses"],
        COURSE_DRINK,
        COURSE_EXTRA,
    ]
    menu: dict[str, list[dict[str, Any]]] = {}
    for course in wanted:
        if course == COURSE_DRINK:
            drinks = occasion_drinks(manager, occasion, alcohol=alcohol)["drinks"]
            menu[course] = [
                {
                    **drink_item(d),
                    **{k: d[k] for k in ("reason", "kids", "offer", "bottles") if k in d},
                }
                for d in drinks
            ]
        elif course == COURSE_EXTRA:
            have = {fold(i.get("title") or "") for i in occasion.get("items") or []}
            menu[course] = [e for e in template_extras(occasion) if fold(e["title"]) not in have]
        elif course in DISH_COURSES:
            menu[course] = suggest_course(manager, occasion, course, count, exclude)
    return menu


def apply_menu(
    manager: EssensplanerManager,
    occasion: dict[str, Any],
    menu: dict[str, list[dict[str, Any]]],
    course: str | None = None,
) -> list[dict[str, Any]]:
    """Put suggestions into the occasion: per dish course as many as the template wants
    that are still missing (one with an explicit course), the drinks when it has none yet,
    the missing extras. Returns the added items (the caller saves)."""
    counts = template_info(occasion.get("template"))["courses"]
    items = occasion.setdefault("items", [])
    added: list[dict[str, Any]] = []
    for name, suggestions in menu.items():
        if course and name != course:
            continue
        present = [i for i in items if i.get("course") == name]
        if name == COURSE_DRINK:
            if present and not course:
                continue
            have = {fold(i.get("title") or "") for i in present}
            chosen = [s for s in suggestions if fold(s["title"]) not in have]
        elif name == COURSE_EXTRA:
            chosen = list(suggestions)
        else:
            need = 1 if course else max(0, int(counts.get(name, 1)) - len(present))
            chosen = suggestions[:need]
        for suggestion in chosen:
            # the occasion's servings (a recipe summary carries the recipe's own)
            raw = {
                k: v
                for k, v in suggestion.items()
                if k in _ITEM_FIELDS and k not in ("uid", "servings")
            }
            raw["course"] = suggestion.get("course") or name
            item = normalize_item(manager, raw)
            items.append(item)
            added.append(item)
    del items[MAX_ITEMS:]
    return added


def fill_occasion(manager: EssensplanerManager, occasion: dict[str, Any]) -> list[dict[str, Any]]:
    """Auto fill (a new occasion, "Plane einen Filmabend"): the dishes the template wants,
    then drinks for them and the extras."""
    dishes = [c for c in template_info(occasion.get("template"))["courses"]]
    added = apply_menu(manager, occasion, suggest_menu(manager, occasion, dishes))
    added += apply_menu(
        manager, occasion, suggest_menu(manager, occasion, [COURSE_DRINK, COURSE_EXTRA])
    )
    return added


# ----------------------------------------------------------------------
# Costs and shopping
# ----------------------------------------------------------------------


def _item_name(item: dict[str, Any]) -> str:
    return str(item.get("name") or item.get("title") or "")


def _free_cost(
    manager: EssensplanerManager,
    name: str,
    quantity: float | None,
    unit: str,
    day: date,
) -> float | None:
    key = ingredient_key(name)
    if not key:
        return None
    best, regular = manager.best_price(name, day)
    amounts: dict[str, float] = {}
    if quantity:
        amount, base = to_base(quantity, normalize_unit(unit))
        if amount:
            amounts[base] = amount
    category = guess_category(name)
    for entry in (best, regular):
        if entry is None:
            continue
        result = item_cost(amounts, key, entry, category, count_as_packs=True)
        if result is not None:
            return result[0]
    return None


def item_costs(
    manager: EssensplanerManager, occasion: dict[str, Any], day: date | None = None
) -> dict[str, Any]:
    """Cost per item {uid: cost | None}, offers used and unknown items."""
    day = day or occasion_date(occasion)
    servings = servings_of(occasion)
    costs: dict[str, float | None] = {}
    on_offer: list[str] = []
    unknown: list[str] = []
    from .products import _store_of, product_entry  # imports the manager

    store = None
    for item in occasion.get("items") or []:
        cost: float | None = None
        recipe = manager.recipes.get(item.get("recipe_id") or "")
        if recipe is not None:
            result = manager.recipe_cost(recipe, item.get("servings") or servings, day)
            cost = result["total"] if result["items"] else None
            on_offer += [o["ingredient"] for o in result["on_offer"]]
        elif item.get("product_id"):
            store = store or _store_of(manager)
            product = store.get(item["product_id"]) if store is not None else None
            entry = product_entry(product, day) if product else None
            if entry is not None:
                cost = round(entry.price * max(1.0, float(item.get("quantity") or 1)), 2)
                if entry.offer:
                    on_offer.append(str(item.get("title")))
        else:
            cost = _free_cost(
                manager, _item_name(item), item.get("quantity"), str(item.get("unit") or ""), day
            )
        costs[str(item.get("uid"))] = round(cost, 2) if cost is not None else None
        if cost is None:
            unknown.append(str(item.get("title")))
    return {"items": costs, "on_offer": list(dict.fromkeys(on_offer)), "unknown": unknown}


def occasion_cost(
    manager: EssensplanerManager, occasion: dict[str, Any], day: date | None = None
) -> dict[str, Any]:
    """Estimated cost: recipes for their servings (default guests + children/2), products
    with their price, free items and extras with the store's or estimated price.
    {total, per_person, items: {uid: cost}, courses: {course: total}, on_offer, unknown,
    estimate}."""
    found = item_costs(manager, occasion, day)
    courses: dict[str, float] = {}
    for item in occasion.get("items") or []:
        cost = found["items"].get(str(item.get("uid")))
        if cost is not None:
            course = item.get("course") or COURSE_MAIN
            courses[course] = round(courses.get(course, 0.0) + cost, 2)
    total = round(sum(courses.values()), 2)
    return {
        "total": total,
        "per_person": round(total / persons_of(occasion), 2),
        "items": found["items"],
        "courses": courses,
        "on_offer": found["on_offer"],
        "unknown": found["unknown"],
        "estimate": True,
    }


def occasion_entries(
    manager: EssensplanerManager, occasion: dict[str, Any]
) -> tuple[list[tuple[dict[str, Any], str]], list[str], int]:
    """Shopping entries ((ingredient, label) like the plan's) of an occasion: the scaled
    ingredients of its recipes, its products (packs), free items with a quantity, drinks,
    snacks and extras; dishes without a recipe and quantity are returned as text (like a
    plan entry without recipe). Returns (entries, without_recipe, dishes)."""
    label = occasion_label(occasion)
    servings = servings_of(occasion)
    entries: list[tuple[dict[str, Any], str]] = []
    without: list[str] = []
    dishes = 0
    from .products import _store_of  # imports the manager

    store = None
    for item in occasion.get("items") or []:
        recipe = manager.recipes.get(item.get("recipe_id") or "")
        if recipe is not None:
            dishes += 1
            base = recipe.get("servings") or manager.default_servings
            factor = (item.get("servings") or servings) / base
            entries.extend(
                (scale_ingredient(i, factor), label) for i in recipe.get("ingredients", [])
            )
            continue
        if item.get("product_id"):
            store = store or _store_of(manager)
            product = store.get(item["product_id"]) if store is not None else None
            if product is not None:
                entries.append(
                    (
                        {
                            "name": str(item.get("title") or product.get("name")),
                            "amount": max(1.0, float(item.get("quantity") or 1)),
                            "unit": "Pck.",
                            "product_id": product["id"],
                        },
                        label,
                    )
                )
                continue
        name = _item_name(item)
        if not name:
            continue
        if item.get("quantity"):
            entries.append(
                (
                    {
                        "name": name,
                        "amount": float(item["quantity"]),
                        "unit": normalize_unit(str(item.get("unit") or "")),
                    },
                    label,
                )
            )
        elif item.get("course") in (COURSE_DRINK, COURSE_SNACK, COURSE_EXTRA):
            entries.append(({"name": name, "amount": None, "unit": ""}, label))
        else:
            without.append(name)
    return entries, without, dishes


def occasion_meals(manager: EssensplanerManager, day: date) -> set[str]:
    """Meal slots of the plan an occasion with dishes covers on a day (the enabled meal
    nearest to its time) – the auto plan leaves them free."""
    covered: set[str] = set()
    meals = manager.enabled_meals
    if not meals:
        return covered
    for occasion in occasions_on(manager, day):
        if not any(
            i.get("course") in (COURSE_MAIN, COURSE_STARTER) for i in occasion.get("items") or []
        ):
            continue
        start = occasion_start(occasion)
        minutes = start.hour * 60 + start.minute
        covered.add(
            min(
                meals,
                key=lambda m: abs(
                    manager.meal_time(m).hour * 60 + manager.meal_time(m).minute - minutes
                ),
            )
        )
    return covered


# ----------------------------------------------------------------------
# Views
# ----------------------------------------------------------------------


def quantity_text(item: dict[str, Any]) -> str:
    """'200 g', '2,5 kg', '3 l', '2 Pck.' (empty without quantity)."""
    quantity = item.get("quantity")
    if not quantity:
        return ""
    number = f"{float(quantity):g}".replace(".", ",")
    unit = str(item.get("unit") or ("Pck." if item.get("product_id") else ""))
    return f"{number} {unit}".strip()


def item_view(
    manager: EssensplanerManager,
    item: dict[str, Any],
    servings: int,
    cost: float | None,
    product_store: Any = None,
) -> dict[str, Any]:
    """An item with labels, the recipe's image and time, the product, its cost."""
    view: dict[str, Any] = {
        **item,
        "course_label": COURSE_LABELS.get(item.get("course") or "", ""),
        "quantity_text": quantity_text(item),
        "cost": cost,
        "image": None,
    }
    if item.get("recipe_id"):
        recipe = manager.recipes.get(item["recipe_id"])
        if recipe is None:
            view["missing"] = True
        else:
            view["image"] = recipe.get("image") or None
            view["total_time"] = recipe.get("total_time")
            view["servings"] = item.get("servings") or servings
    if item.get("product_id") and product_store is not None:
        from .products import slim_product  # imports the manager

        product = product_store.get(item["product_id"])
        if product is None:
            view["missing"] = True
        else:
            view["product"] = slim_product(product, day=manager.today())
            view["image"] = product.get("image")
    return view


def occasion_summary(occasion: dict[str, Any]) -> str:
    """'Pizza Margherita, Nachos · Cola, Bier' (dishes, then drinks)."""
    dishes = [
        str(i.get("title"))
        for i in occasion.get("items") or []
        if i.get("course") in DISH_COURSES and i.get("title")
    ]
    drinks = [
        str(i.get("title"))
        for i in occasion.get("items") or []
        if i.get("course") == COURSE_DRINK and i.get("title")
    ]
    return " · ".join(part for part in (", ".join(dishes), ", ".join(drinks)) if part)


def occasion_view(
    manager: EssensplanerManager, occasion: dict[str, Any], with_cost: bool = True
) -> dict[str, Any]:
    """The occasion for the panel and services: labels, weekday, servings, persons, the
    items (with their cost), the courses (uids of their items, cost) and the cost (without
    the per-item costs – they are at the items)."""
    from .products import _store_of  # imports the manager

    info = template_info(occasion.get("template"))
    day = occasion_date(occasion)
    servings = servings_of(occasion)
    cost = occasion_cost(manager, occasion) if with_cost else None
    store = _store_of(manager)
    items = [
        item_view(manager, i, servings, (cost or {}).get("items", {}).get(str(i.get("uid"))), store)
        for i in occasion.get("items") or []
    ]
    courses = []
    for course in COURSES:
        uids = [i["uid"] for i in items if i.get("course") == course]
        if uids or course in info["courses"]:
            courses.append(
                {
                    "id": course,
                    "label": COURSE_LABELS[course],
                    "emoji": COURSE_EMOJI[course],
                    "uids": uids,
                    "cost": (cost or {}).get("courses", {}).get(course),
                }
            )
    today = manager.today()
    return {
        **{k: v for k, v in occasion.items() if k != "items"},
        "template_title": info["title"],
        "emoji": info["emoji"],
        "label": occasion_label(occasion),
        "weekday": WEEKDAY_NAMES[day.weekday()],
        "servings": servings,
        "persons": persons_of(occasion),
        "items": items,
        "courses": courses,
        "summary": occasion_summary(occasion),
        "cost": {k: v for k, v in cost.items() if k != "items"} if cost else None,
        "past": day < today,
        "days_until": (day - today).days,
        "uid": calendar_uid(occasion),
    }


def calendar_uid(occasion: dict[str, Any]) -> str:
    """The calendar event uid: '<date>_occasion-<id>' (the meal uids are '<date>_<meal>')."""
    return f"{occasion['date']}_occasion-{occasion['id']}"


def occasions_export(manager: EssensplanerManager) -> list[dict[str, Any]]:
    """Occasions for the panel (from EXPORT_PAST_DAYS back), by date."""
    start = manager.today() - timedelta(days=EXPORT_PAST_DAYS)
    end = manager.today() + timedelta(days=KEEP_DAYS + 366)
    return [occasion_view(manager, o) for o in occasions_between(manager, start, end)]


def occasion_meta() -> dict[str, Any]:
    """Templates and courses for the panel."""
    return {"templates": templates_view(), "courses": courses_view()}


# ----------------------------------------------------------------------
# AI menu (optional, feature "occasions")
# ----------------------------------------------------------------------

AI_TASK_NAME = "Essensplaner Anlass-Menü"
AI_INSTRUCTIONS = (
    "Du planst das Essen für einen Anlass. Stelle ein stimmiges Menü zusammen: je Gang "
    "aus 'gaenge' ein bis zwei Gerichte. Nimm bevorzugt Rezepte aus 'rezepte' (mit ihrer "
    "id); fehlt etwas Passendes, schlage ein bekanntes Gericht mit deutschem Namen vor "
    "(ohne id). Getränke mit Alkohol nur, wenn 'alkohol_erlaubt' true ist; immer auch "
    "alkoholfreie. Vermeide Zutaten aus 'ausgeschlossen'. Antworte als JSON: "
    '{"menu": [{"gang": "main", "rezept_id": "…", "titel": "…", "grund": "…"}]}'
)


def ai_payload(
    manager: EssensplanerManager,
    occasion: dict[str, Any],
    candidates: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """What the AI gets: the kind of occasion (not its title – it may name people), month,
    guests, courses, candidate recipes (id, name, tags), what is planned already and the
    excluded ingredients."""
    info = template_info(occasion.get("template"))
    return {
        "anlass": info["title"],
        "monat": occasion_date(occasion).month,
        "gaeste": occasion.get("guests"),
        "kinder": occasion.get("children"),
        "alkohol_erlaubt": alcohol_allowed(manager),
        "ausgeschlossen": manager.excluded,
        "gaenge": [{"id": c, "name": COURSE_LABELS[c]} for c in candidates],
        "rezepte": [
            {
                "id": s["recipe_id"],
                "name": s["title"],
                "gang": course,
                "tags": s.get("tags", [])[:6],
            }
            for course, found in candidates.items()
            for s in found
            if s.get("recipe_id")
        ],
        "schon_geplant": [str(i.get("title")) for i in occasion.get("items") or []],
    }


def parse_ai_menu(
    manager: EssensplanerManager,
    answer: Any,
    courses: list[str],
    occasion: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Checked AI menu: courses of the request only; a recipe id must exist (and not be
    excluded), a name is matched to a recipe of that name, else it becomes a free item
    (ai: true); drinks with alcohol only when allowed; at most AI_PER_COURSE per course."""
    items: Any = answer
    if isinstance(answer, dict):
        items = next((answer[k] for k in ("menu", "gerichte", "items") if k in answer), None)
    if not isinstance(items, list):
        return {}
    allowed = alcohol_allowed(manager)
    used = {i.get("recipe_id") for i in occasion.get("items") or []}
    seen: set[str] = set()
    menu: dict[str, list[dict[str, Any]]] = {}
    for raw in items:
        if not isinstance(raw, dict):
            continue
        course = resolve_course(str(raw.get("gang") or raw.get("course") or ""))
        if course is None or course not in courses:
            continue
        if len(menu.get(course, [])) >= AI_PER_COURSE:
            continue
        recipe = manager.recipes.get(str(raw.get("rezept_id") or raw.get("recipe_id") or ""))
        title = _text(raw.get("titel") or raw.get("title"))
        if recipe is None and title:
            recipe = manager.get_recipe_by_name(title)
        reason = _text(raw.get("grund") or raw.get("reason"), REASON_MAX)
        if recipe is not None:
            if recipe["id"] in used or manager.is_excluded(recipe) or recipe["id"] in seen:
                continue
            seen.add(recipe["id"])
            suggestion = {
                **manager.recipe_summary(recipe),
                "recipe_id": recipe["id"],
                "title": recipe["name"],
                "course": course,
                "reasons": [f"🤖 {reason}" if reason else "🤖 KI"],
                "ai": True,
            }
        else:
            if not title or fold(title) in seen:
                continue
            alcohol = is_alcoholic(title)
            if course == COURSE_DRINK and alcohol and not allowed:
                continue
            seen.add(fold(title))
            suggestion = {
                "recipe_id": None,
                "title": title,
                "course": course,
                "reasons": [f"🤖 {reason}" if reason else "🤖 KI"],
                "ai": True,
            }
            if course == COURSE_DRINK:
                suggestion["alcohol"] = alcohol
        menu.setdefault(course, []).append(suggestion)
    return menu


def merge_menus(
    ai_menu: dict[str, list[dict[str, Any]]], rules: dict[str, list[dict[str, Any]]]
) -> dict[str, list[dict[str, Any]]]:
    """AI suggestions first, then the rule suggestions (each dish once)."""
    merged: dict[str, list[dict[str, Any]]] = {}
    for course in list(rules) + [c for c in ai_menu if c not in rules]:
        seen: set[str] = set()
        merged[course] = []
        for suggestion in [*ai_menu.get(course, []), *rules.get(course, [])]:
            key = suggestion.get("recipe_id") or fold(suggestion.get("title") or "")
            if key in seen:
                continue
            seen.add(key)
            merged[course].append(suggestion)
    return merged


async def async_ai_menu(
    hass: HomeAssistant,
    manager: EssensplanerManager,
    occasion: dict[str, Any],
    courses: list[str] | None = None,
    rules: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """The AI's menu for the occasion (feature "occasions"), checked and merged with the
    rule suggestions (AI first). Raises the ai_* errors."""
    from .ai import async_ai_json  # imports the manager

    wanted = courses or [*template_info(occasion.get("template"))["courses"], COURSE_DRINK]
    rules = rules if rules is not None else suggest_menu(manager, occasion, wanted)
    candidates = {
        course: suggest_course(manager, occasion, course, AI_CANDIDATES)
        for course in wanted
        if course in DISH_COURSES
    }
    for course in wanted:
        candidates.setdefault(course, [])
    answer = await async_ai_json(
        hass,
        manager,
        AI_FEATURE_OCCASIONS,
        AI_TASK_NAME,
        AI_INSTRUCTIONS,
        ai_payload(manager, occasion, candidates),
    )
    return merge_menus(parse_ai_menu(manager, answer, wanted, occasion), rules)


# ----------------------------------------------------------------------
# Suggestions with optional AI (services, websockets)
# ----------------------------------------------------------------------


def _ai_failure(err: Exception) -> dict[str, Any]:
    from .manager import error_message  # imports this module

    return {
        "ok": False,
        "code": getattr(err, "translation_key", None) or "ai_failed",
        "error": error_message(err) if hasattr(err, "translation_key") else str(err),
    }


async def async_suggest_menu(
    hass: HomeAssistant,
    manager: EssensplanerManager,
    occasion: dict[str, Any],
    course: str | None = None,
    count: int = DEFAULT_SUGGESTIONS,
    ai: bool = False,
    apply: bool = False,
    exclude: set[str] | None = None,
) -> dict[str, Any]:
    """Suggestions for an occasion (one course or all), with ai the AI's menu first (a
    failing AI leaves the rule suggestions: ai {ok: false, code, error}); apply puts them
    into the occasion (apply_menu()). {occasion, suggestions: {course: [...]}, applied:
    [titles], ai: None | {ok, code?, error?}}."""
    from homeassistant.exceptions import HomeAssistantError

    courses = [course] if course else None
    menu = suggest_menu(manager, occasion, courses, count, exclude)
    ai_result: dict[str, Any] | None = None
    if ai:
        try:
            menu = await async_ai_menu(hass, manager, occasion, courses, menu)
            ai_result = {"ok": True}
        except HomeAssistantError as err:
            ai_result = _ai_failure(err)
    applied: list[str] = []
    if apply:
        if course:
            added = apply_menu(manager, occasion, menu, course)
        else:
            # dishes and extras first, then the drinks for them (the AI's when it answered)
            dishes = {k: v for k, v in menu.items() if k != COURSE_DRINK}
            added = apply_menu(manager, occasion, dishes)
            drinks = (
                {COURSE_DRINK: menu.get(COURSE_DRINK, [])}
                if ai_result and ai_result.get("ok")
                else suggest_menu(manager, occasion, [COURSE_DRINK])
            )
            added += apply_menu(manager, occasion, drinks)
        applied = [str(i["title"]) for i in added]
        if added:
            _touch(manager, occasion)
    return {
        "occasion": occasion_view(manager, occasion),
        "suggestions": menu,
        "applied": applied,
        "ai": ai_result,
    }


async def async_suggest_drinks(
    hass: HomeAssistant,
    manager: EssensplanerManager,
    recipes: list[dict[str, Any]] | None = None,
    titles: list[str] | None = None,
    occasion: dict[str, Any] | None = None,
    day: date | None = None,
    alcohol: bool | None = None,
    guests: int | None = None,
    children: int | None = None,
    hours: float | None = None,
    ai: bool = False,
    kind: str | None = None,
) -> dict[str, Any]:
    """Drinks for recipes / dish titles and/or an occasion (its dishes, template, date and
    guests), with ai the AI's drinks first (a failing AI leaves the rule result).
    suggest_drinks() result + ai: None | {ok, code?, error?}."""
    from homeassistant.exceptions import HomeAssistantError

    from .drinks import async_ai_drinks

    recipes = list(recipes or [])
    titles = list(titles or [])
    template = None
    courses: set[str] = set()
    if occasion is not None:
        found, free, courses = _occasion_dishes(manager, occasion)
        recipes += [r for r in found if r not in recipes]
        titles += free
        template = occasion.get("template")
        day = day or occasion_date(occasion)
        guests = guests if guests is not None else int(occasion.get("guests") or 0)
        children = children if children is not None else int(occasion.get("children") or 0)
        hours = hours or float(occasion.get("duration_h") or 0) or None
    rules = suggest_drinks(
        manager,
        recipes=recipes,
        titles=titles,
        template=template,
        day=day,
        alcohol=alcohol,
        guests=guests,
        children=children or 0,
        hours=hours,
        courses=courses,
        kind=kind,
    )
    result = {**rules, "ai": None}
    if ai:
        try:
            result = {
                **await async_ai_drinks(
                    hass,
                    manager,
                    rules,
                    recipes=recipes,
                    titles=titles,
                    template=template,
                    day=day,
                    guests=guests,
                    children=children or 0,
                    hours=hours,
                ),
                "ai": {"ok": True},
            }
        except HomeAssistantError as err:
            result["ai"] = _ai_failure(err)
    return result


def items_from_text(
    manager: EssensplanerManager, values: Any, course: str | None = None
) -> list[dict[str, Any]]:
    """Items said or typed ('Kartoffelsalat, Würstchen'): a recipe of that name, else
    free text; course for all of them (else from the recipe or the name)."""
    if isinstance(values, str):
        values = [values]
    found: list[dict[str, Any]] = []
    for value in values or []:
        if isinstance(value, dict):
            found.append({**value, **({"course": course} if course else {})})
            continue
        text = _text(value)
        if not text:
            continue
        recipe = _match_recipe(manager, text)
        raw: dict[str, Any] = {"recipe_id": recipe["id"]} if recipe else {"title": text}
        if course:
            raw["course"] = course
        found.append(raw)
    return found
