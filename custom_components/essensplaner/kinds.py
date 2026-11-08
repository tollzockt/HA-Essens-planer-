"""Recipe kinds (1.5.1): what a recipe is – a meal, breakfast, a snack, a dessert, a drink,
a side or a component (sauce, dip, herb butter, dressing).

Only meals, breakfasts and snacks fill a slot of the meal plan on their own (manager.
_fits_meal()); drinks, sides, components and desserts can be part of a meal (the extras of
a plan entry, the courses of an occasion) but never end up as one. The kind is stored with
the recipe ("kind", "kind_source"): the rules below classify every recipe from its tags,
its name and its ingredients ("rule"); what the user chose ("user") is never overwritten,
not by the rules and not by a later AI sorting ("ai").
"""

from __future__ import annotations

import re
from typing import Any

from .ingredients import fold, guess_category, is_pantry_item
from .occasions import DRINK_TAGS, MAIN_TAGS, is_drink_name

KIND_MEAL = "meal"
KIND_BREAKFAST = "breakfast"
KIND_SNACK = "snack"
KIND_DESSERT = "dessert"
KIND_DRINK = "drink"
KIND_SIDE = "side"
KIND_COMPONENT = "component"
KINDS = (
    KIND_MEAL,
    KIND_BREAKFAST,
    KIND_SNACK,
    KIND_DESSERT,
    KIND_DRINK,
    KIND_SIDE,
    KIND_COMPONENT,
)
# kinds that fill a meal slot on their own (meal: lunch / dinner, breakfast, snack)
SLOT_KINDS = frozenset({KIND_MEAL, KIND_BREAKFAST, KIND_SNACK})
# kinds that are only ever part of a meal ("Dazu" in the panel's picker)
PART_KINDS = frozenset({KIND_DESSERT, KIND_DRINK, KIND_SIDE, KIND_COMPONENT})
KIND_LABELS = {
    KIND_MEAL: "Mahlzeit",
    KIND_BREAKFAST: "Frühstück",
    KIND_SNACK: "Snack",
    KIND_DESSERT: "Dessert",
    KIND_DRINK: "Getränk",
    KIND_SIDE: "Beilage",
    KIND_COMPONENT: "Bestandteil",
}
KIND_EMOJI = {
    KIND_MEAL: "🍽️",
    KIND_BREAKFAST: "☕",
    KIND_SNACK: "🥪",
    KIND_DESSERT: "🍰",
    KIND_DRINK: "🥤",
    KIND_SIDE: "🥔",
    KIND_COMPONENT: "🧈",
}
SOURCE_RULE = "rule"
SOURCE_USER = "user"
SOURCE_AI = "ai"
KIND_SOURCES = (SOURCE_RULE, SOURCE_USER, SOURCE_AI)
# who may overwrite whom: the user always, the AI the rules, the rules only themselves
_RANK = {SOURCE_RULE: 0, SOURCE_AI: 1, SOURCE_USER: 2}
# "automatisch" in the recipe editor / the services: the rules decide again
KIND_AUTO = "auto"

# typed / spoken words (folded) -> kind
KIND_WORDS = {
    "meal": KIND_MEAL,
    "mahlzeit": KIND_MEAL,
    "mahlzeiten": KIND_MEAL,
    "hauptgericht": KIND_MEAL,
    "hauptspeise": KIND_MEAL,
    "gericht": KIND_MEAL,
    "breakfast": KIND_BREAKFAST,
    "fruehstueck": KIND_BREAKFAST,
    "snack": KIND_SNACK,
    "snacks": KIND_SNACK,
    "dessert": KIND_DESSERT,
    "desserts": KIND_DESSERT,
    "nachtisch": KIND_DESSERT,
    "suesses": KIND_DESSERT,
    "drink": KIND_DRINK,
    "getraenk": KIND_DRINK,
    "getraenke": KIND_DRINK,
    "side": KIND_SIDE,
    "beilage": KIND_SIDE,
    "beilagen": KIND_SIDE,
    "component": KIND_COMPONENT,
    "bestandteil": KIND_COMPONENT,
    "bestandteile": KIND_COMPONENT,
    "sauce": KIND_COMPONENT,
    "dip": KIND_COMPONENT,
}

# tags (folded), checked in this order after the drink and main dish tags
_COMPONENT_TAGS = frozenset(
    {
        "dip",
        "dips",
        "sauce",
        "saucen",
        "sosse",
        "sossen",
        "dressing",
        "dressings",
        "pesto",
        "marinade",
        "aufstrich",
        "brotaufstrich",
        "bestandteil",
        "bestandteile",
        "component",
        "topping",
        "gewuerzmischung",
    }
)
_SIDE_TAGS = frozenset({"beilage", "beilagen", "side", "sides", "beilagensalat"})
_BREAKFAST_TAGS = frozenset({"fruehstueck", "breakfast", "brunch", "morgens"})
_SNACK_TAGS = frozenset({"snack", "snacks", "zwischenmahlzeit", "fingerfood", "knabbern"})
_DESSERT_TAGS = frozenset(
    {"dessert", "desserts", "nachtisch", "nachspeise", "suessspeise", "suessspeisen"}
)
# cake is eaten in the afternoon ("Kaffee und Kuchen"): a snack
_CAKE_TAGS = frozenset({"kuchen", "torte", "torten", "gebaeck", "kekse", "plaetzchen"})
_STARTER_TAGS = frozenset({"vorspeise", "vorspeisen", "starter", "antipasti", "antipasto"})

# words of the dish itself ("Kartoffelsalat mit Speck": "kartoffelsalat")
_HEAD_SPLIT = re.compile(r" (?:mit|an|auf|in|im|und|zu|zum|zur|nach|vom|von|aus) ")
_COMPONENT_SUFFIXES = (
    "butter",
    "aioli",
    "tzatziki",
    "zaziki",
    "dip",
    "dressing",
    "vinaigrette",
    "sauce",
    "sosse",
    "pesto",
    "remoulade",
    "mayonnaise",
    "mayo",
    "ketchup",
    "hollandaise",
    "bechamel",
    "marinade",
    "guacamole",
    "hummus",
    "salsa",
    "chutney",
    "aufstrich",
    "gewuerzmischung",
    "gewuerzsalz",
    "croutons",
    "gremolata",
    "relish",
)
_SIDE_WORDS = frozenset(
    {
        "reis",
        "basmatireis",
        "jasminreis",
        "duftreis",
        "naturreis",
        "wildreis",
        "langkornreis",
        "couscous",
        "bulgur",
        "polenta",
        "pommes",
        "ofenpommes",
        "kroketten",
        "baguette",
        "knoblauchbaguette",
        "kraeuterbaguette",
        "knoblauchbrot",
        "rotkohl",
        "apfelrotkohl",
        "blaukraut",
        "rotkraut",
        "sauerkraut",
        "rosenkohl",
        "maiskolben",
        "grillgemuese",
        "kartoffeln",
        "salzkartoffeln",
        "pellkartoffeln",
        "bratkartoffeln",
        "petersilienkartoffeln",
        "rosmarinkartoffeln",
        "ofenkartoffeln",
        "folienkartoffeln",
        "folienkartoffel",
        "kartoffelecken",
        "wedges",
        "kloesse",
        "kartoffelkloesse",
        "knoedel",
        "semmelknoedel",
        "kartoffelknoedel",
        "kartoffelsalat",
        "nudelsalat",
        "krautsalat",
        "gurkensalat",
        "tomatensalat",
        "blattsalat",
        "beilagensalat",
        "eisbergsalat",
        "karottensalat",
        "moehrensalat",
        "bohnensalat",
        "reissalat",
    }
)
_SIDE_SUFFIXES = ("pueree",)
_SIDE_PHRASES = ("gruener salat", "gemischter salat")
_BREAKFAST_WORDS = (
    "muesli",
    "porridge",
    "overnight oats",
    "oats",
    "granola",
    "ruehrei",
    "fruehstueck",
    "smoothie bowl",
    "smoothiebowl",
    "chia pudding",
    "chiapudding",
    "pancakes",
)
_SNACK_WORDS = (
    "chips",
    "popcorn",
    "nachos",
    "salzstangen",
    "erdnuesse",
    "cracker",
    "brezel",
    "brezeln",
    "fingerfood",
    "pizzaschnecken",
    "knabber",
    "riegel",
    "muesliriegel",
    "kekse",
    "plaetzchen",
    "cookies",
    "muffin",
    "muffins",
    "brownie",
    "brownies",
    "waffel",
    "waffeln",
)
_CAKE_SUFFIXES = ("kuchen", "torte")
# cakes that are a meal ("Pfannkuchen", "Zwiebelkuchen")
_NOT_CAKE = frozenset(
    {"pfannkuchen", "eierkuchen", "reibekuchen", "kartoffelkuchen", "zwiebelkuchen"}
)
# what (almost) every drink and dish has: not counted for the ingredient rule
_BASICS = ("Salz", "Pfeffer", "Wasser", "Zucker", "Eiswürfel")
# a dish named after a drink ("Bierteig") is no drink
_NOT_DRINK_SUFFIXES = ("teig", "marinade", "sauce", "sosse", "bowl", "bratensaft")
# words of the dish that name a drink ("Pfirsich-Eistee", "Weinschorle", "Milchshake")
_DRINK_SUFFIXES = (
    "eistee",
    "schorle",
    "limonade",
    "limo",
    "punsch",
    "bowle",
    "cocktail",
    "mocktail",
    "lassi",
    "smoothie",
    "kakao",
    "shake",
    "tee",
    "kaffee",
    "latte",
    "spritz",
    "sangria",
    "gluehwein",
    "saft",
)
_DESSERT_SUFFIXES = (
    "mousse",
    "tiramisu",
    "pudding",
    "parfait",
    "kompott",
    "crumble",
    "sorbet",
    "eiscreme",
    "gruetze",
    "milchreis",
    "griessbrei",
    "quarkspeise",
    "trifle",
    "dessert",
    "nachtisch",
    "bratapfel",
    "brataepfel",
)
_DESSERT_PHRASES = ("panna cotta", "creme brulee")
# a side with a main food is a meal ("Pellkartoffeln mit Quark", "Reis mit Hähnchen")
_MAIN_FOODS = (
    "haehnchen",
    "huhn",
    "fleisch",
    "wurst",
    "wuerstchen",
    "fisch",
    "lachs",
    "hack",
    "schnitzel",
    "steak",
    "frikadelle",
    "tofu",
    "quark",
    "spiegelei",
    "garnelen",
    "gulasch",
    "braten",
    "geschnetzeltes",
    "linsen",
    "kichererbsen",
    "halloumi",
)


def _words(text: str) -> list[str]:
    return [w for w in re.split(r"[\s\-/,()]+", text) if w]


def _head(folded_name: str) -> str:
    """The dish of a name without what comes with it ("kartoffelsalat mit speck")."""
    return _HEAD_SPLIT.split(f" {folded_name} ", maxsplit=1)[0].strip() or folded_name


def _is_ice_cream(word: str) -> bool:
    return word == "eis" or (word.endswith("eis") and not word.endswith("reis"))


def _name_kind(name: str) -> str | None:
    folded = fold(name)
    if not folded:
        return None
    spaced = " ".join(_words(folded))
    head = _head(spaced)
    words = _words(head)
    if not any(w.endswith(_NOT_DRINK_SUFFIXES) for w in _words(spaced)) and (
        any(w.endswith(_DRINK_SUFFIXES) for w in words) or is_drink_name(name)
    ):
        return KIND_DRINK
    if any(w.endswith(_COMPONENT_SUFFIXES) for w in words):
        return KIND_COMPONENT
    if any(w in _SIDE_WORDS or w.endswith(_SIDE_SUFFIXES) for w in words) or head in (
        _SIDE_PHRASES
    ):
        rest = _words(spaced[len(head) :])
        main = any(w in ("ei", "eier", "eiern") or any(f in w for f in _MAIN_FOODS) for w in rest)
        return KIND_MEAL if main else KIND_SIDE
    padded = f" {spaced} "
    if any(f" {w} " in padded for w in _BREAKFAST_WORDS):
        return KIND_BREAKFAST
    if any(w.endswith(_DESSERT_SUFFIXES) or _is_ice_cream(w) for w in words) or any(
        p in head for p in _DESSERT_PHRASES
    ):
        return KIND_DESSERT
    if any(w in _SNACK_WORDS for w in words) or "knabber" in head:
        return KIND_SNACK
    if any(w.endswith(_CAKE_SUFFIXES) and w not in _NOT_CAKE for w in words):
        return KIND_SNACK
    return None


def _ingredient_kind(recipe: dict[str, Any]) -> str | None:
    """Mostly drinks (juice, wine, tea …) among the ingredients: a drink."""
    names = [
        str(i.get("name") or "")
        for i in recipe.get("ingredients") or []
        if isinstance(i, dict)
        and i.get("name")
        and not is_pantry_item(str(i["name"]), list(_BASICS))
    ]
    if len(names) < 2:
        return None
    drinks = sum(1 for n in names if guess_category(n) == "Getränke")
    if drinks >= 2 and drinks * 2 >= len(names):
        return KIND_DRINK
    return None


def classify_kind(recipe: dict[str, Any]) -> str:
    """The kind of a recipe by the rules: its tags first (drink, main dish, component,
    side, breakfast, snack, dessert, cake, starter), then the name of the dish
    ("Kräuterbutter", "Pfirsich-Eistee", "Kartoffelsalat mit Speck"), then its ingredients
    (mostly drinks: a drink), else a meal."""
    tags = {fold(str(t)) for t in recipe.get("tags") or []}
    if tags & DRINK_TAGS:
        return KIND_DRINK
    if tags & MAIN_TAGS:
        return KIND_MEAL
    for tagset, kind in (
        (_COMPONENT_TAGS, KIND_COMPONENT),
        (_SIDE_TAGS, KIND_SIDE),
        (_BREAKFAST_TAGS, KIND_BREAKFAST),
        (_SNACK_TAGS, KIND_SNACK),
        (_DESSERT_TAGS, KIND_DESSERT),
        (_CAKE_TAGS, KIND_SNACK),
        # a starter accompanies the meal (a soup, a salad, antipasti)
        (_STARTER_TAGS, KIND_SIDE),
    ):
        if tags & tagset:
            return kind
    return _name_kind(str(recipe.get("name") or "")) or _ingredient_kind(recipe) or KIND_MEAL


def recipe_kind(recipe: dict[str, Any]) -> str:
    """The stored kind of a recipe (the rules for one without, e.g. a bundled recipe that
    is not stored yet)."""
    kind = recipe.get("kind")
    return kind if kind in KINDS else classify_kind(recipe)


def resolve_kind(text: Any) -> str | None:
    """'Getränk' / 'drink' / 'Beilage' -> kind (None if unknown; 'auto' is KIND_AUTO)."""
    key = fold(str(text or "")).strip()
    if key in ("auto", "automatisch", "rule", "regel"):
        return KIND_AUTO
    if key in KINDS:
        return key
    return KIND_WORDS.get(key)


def set_kind(recipe: dict[str, Any], kind: str | None, source: str = SOURCE_USER) -> bool:
    """Set a recipe's kind (in place). source user: always; ai: unless the user chose one;
    rule (or kind None / auto): classify by the rules unless the user or the AI chose one
    – except source user with auto, which hands the kind back to the rules. Returns True
    when kind or source changed."""
    before = (recipe.get("kind"), recipe.get("kind_source"))
    current = recipe.get("kind_source") if recipe.get("kind") in KINDS else None
    if kind in (None, KIND_AUTO):
        if source == SOURCE_USER or current in (None, SOURCE_RULE):
            recipe["kind"] = classify_kind(recipe)
            recipe["kind_source"] = SOURCE_RULE
    elif kind in KINDS:
        if source not in _RANK:
            source = SOURCE_USER
        if current is None or _RANK[source] >= _RANK.get(current, 0):
            recipe["kind"] = kind
            recipe["kind_source"] = source
    return (recipe.get("kind"), recipe.get("kind_source")) != before


def fills_slot(recipe: dict[str, Any]) -> bool:
    """True for meals, breakfasts and snacks (they can fill a meal slot on their own)."""
    return recipe_kind(recipe) in SLOT_KINDS


def kinds_view() -> list[dict[str, str]]:
    """The kinds for the panel: [{id, label, emoji}]."""
    return [{"id": k, "label": KIND_LABELS[k], "emoji": KIND_EMOJI[k]} for k in KINDS]
