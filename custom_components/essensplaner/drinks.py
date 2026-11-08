"""Drink suggestions (1.5): what to drink with dishes and occasions.

Rules first: DRINK_RULES match recipe tags, names, ingredients and proteins, the occasion
(template), the season (Advent, summer) and courses; every suggestion has at least two
alcohol-free drinks (also when alcohol is allowed), children get drinks for children, and
the option drinks_alcohol (panel ⚙️ → Budget & Planung) switches alcoholic suggestions off.
Drinks on offer (offers of the user's stores) rank a little higher. Quantities follow the
number of guests, children and hours. The AI (feature "drinks", optional) only adds to and
reorders the rule result; its drinks are checked for alcohol by name.
"""

from __future__ import annotations

from datetime import date
import logging
import math
import re
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant

from .const import AI_FEATURE_DRINKS, CONF_DRINKS_ALCOHOL, DEFAULT_DRINKS_ALCOHOL
from .dates import advent_start
from .ingredients import fold, ingredient_key
from .pricing import format_eur

if TYPE_CHECKING:
    from .manager import EssensplanerManager

_LOGGER = logging.getLogger(__name__)

KIND_WINE = "wine"
KIND_SPARKLING = "sparkling"
KIND_BEER = "beer"
KIND_MIXED = "mixed"
KIND_SOFT = "soft"
KIND_JUICE = "juice"
KIND_HOT = "hot"
KIND_WATER = "water"
KINDS = (
    KIND_WINE,
    KIND_SPARKLING,
    KIND_BEER,
    KIND_MIXED,
    KIND_SOFT,
    KIND_JUICE,
    KIND_HOT,
    KIND_WATER,
)

# id -> title (shown), name (what is bought), hint, alcohol, kind, kids (fine for
# children), pack (litres per bottle; None = sold by the litre)
DRINKS: dict[str, dict[str, Any]] = {
    "rotwein_kraeftig": {
        "title": "Rotwein, kräftig",
        "name": "Rotwein",
        "hint": "z. B. Dornfelder oder Lemberger",
        "alcohol": True,
        "kind": KIND_WINE,
        "pack": 0.75,
    },
    "rotwein_leicht": {
        "title": "Rotwein, leicht",
        "name": "Rotwein",
        "hint": "z. B. Spätburgunder oder Chianti",
        "alcohol": True,
        "kind": KIND_WINE,
        "pack": 0.75,
    },
    "weisswein": {
        "title": "Weißwein, trocken",
        "name": "Weißwein",
        "hint": "z. B. Grauburgunder oder Riesling",
        "alcohol": True,
        "kind": KIND_WINE,
        "pack": 0.75,
    },
    "silvaner": {
        "title": "Silvaner",
        "name": "Weißwein",
        "hint": "der Klassiker zu Spargel",
        "alcohol": True,
        "kind": KIND_WINE,
        "pack": 0.75,
    },
    "riesling_feinherb": {
        "title": "Riesling, feinherb",
        "name": "Weißwein",
        "hint": "fruchtig, mildert die Schärfe",
        "alcohol": True,
        "kind": KIND_WINE,
        "pack": 0.75,
    },
    "bier": {
        "title": "Bier",
        "name": "Bier",
        "hint": "Pils oder Helles",
        "alcohol": True,
        "kind": KIND_BEER,
        "pack": 0.5,
    },
    "sekt": {
        "title": "Sekt",
        "name": "Sekt",
        "hint": "oder Prosecco",
        "alcohol": True,
        "kind": KIND_SPARKLING,
        "pack": 0.75,
    },
    "gluehwein": {
        "title": "Glühwein",
        "name": "Glühwein",
        "hint": "heiß serviert",
        "alcohol": True,
        "kind": KIND_HOT,
        "pack": 1.0,
    },
    "hugo": {
        "title": "Hugo",
        "name": "Prosecco",
        "hint": "Prosecco mit Holunderblütensirup, Minze und Limette",
        "alcohol": True,
        "kind": KIND_MIXED,
        "pack": 0.75,
    },
    "bowle": {
        "title": "Erdbeerbowle",
        "name": "Erdbeerbowle",
        "hint": "Weißwein, Sekt und Erdbeeren",
        "alcohol": True,
        "kind": KIND_MIXED,
        "pack": None,
    },
    "traubensaft_rot": {
        "title": "Roter Traubensaft",
        "name": "Traubensaft",
        "hint": "pur oder als Schorle",
        "alcohol": False,
        "kind": KIND_JUICE,
        "kids": True,
        "pack": None,
    },
    "johannisbeerschorle": {
        "title": "Johannisbeerschorle",
        "name": "Johannisbeerschorle",
        "hint": "herb-fruchtig",
        "alcohol": False,
        "kind": KIND_JUICE,
        "kids": True,
        "pack": None,
    },
    "apfelschorle": {
        "title": "Apfelschorle",
        "name": "Apfelschorle",
        "hint": "",
        "alcohol": False,
        "kind": KIND_JUICE,
        "kids": True,
        "pack": None,
    },
    "weisswein_af": {
        "title": "Alkoholfreier Weißwein",
        "name": "alkoholfreier Weißwein",
        "hint": "",
        "alcohol": False,
        "kind": KIND_WINE,
        "pack": 0.75,
    },
    "bier_af": {
        "title": "Alkoholfreies Bier",
        "name": "alkoholfreies Bier",
        "hint": "",
        "alcohol": False,
        "kind": KIND_BEER,
        "pack": 0.5,
    },
    "radler_af": {
        "title": "Radler 0,0 %",
        "name": "alkoholfreies Radler",
        "hint": "",
        "alcohol": False,
        "kind": KIND_BEER,
        "pack": 0.5,
    },
    "fassbrause": {
        "title": "Fassbrause",
        "name": "Fassbrause",
        "hint": "",
        "alcohol": False,
        "kind": KIND_SOFT,
        "kids": True,
        "pack": 0.5,
    },
    "ingwer_limo": {
        "title": "Ingwer-Limonade",
        "name": "Ingwerlimonade",
        "hint": "",
        "alcohol": False,
        "kind": KIND_SOFT,
        "pack": None,
    },
    "mango_lassi": {
        "title": "Mango-Lassi",
        "name": "Mango-Lassi",
        "hint": "Joghurt, Mango und Milch",
        "alcohol": False,
        "kind": KIND_JUICE,
        "kids": True,
        "pack": None,
    },
    "kindersekt": {
        "title": "Kindersekt",
        "name": "Kindersekt",
        "hint": "",
        "alcohol": False,
        "kind": KIND_SPARKLING,
        "kids": True,
        "pack": 0.75,
    },
    "traubensecco": {
        "title": "Traubensecco",
        "name": "alkoholfreier Secco",
        "hint": "prickelnd ohne Alkohol",
        "alcohol": False,
        "kind": KIND_SPARKLING,
        "pack": 0.75,
    },
    "kaffee": {
        "title": "Kaffee",
        "name": "Kaffee",
        "hint": "oder Espresso",
        "alcohol": False,
        "kind": KIND_HOT,
        "pack": None,
        "per_cup": True,
    },
    "kakao": {
        "title": "Kakao",
        "name": "Kakao",
        "hint": "",
        "alcohol": False,
        "kind": KIND_HOT,
        "kids": True,
        "pack": None,
        "per_cup": True,
    },
    "tee": {
        "title": "Tee",
        "name": "Tee",
        "hint": "Schwarztee oder Kräutertee",
        "alcohol": False,
        "kind": KIND_HOT,
        "kids": True,
        "pack": None,
        "per_cup": True,
    },
    "kinderpunsch": {
        "title": "Kinderpunsch",
        "name": "Kinderpunsch",
        "hint": "heiß serviert",
        "alcohol": False,
        "kind": KIND_HOT,
        "kids": True,
        "pack": 1.0,
    },
    "hugo_af": {
        "title": "Hugo alkoholfrei",
        "name": "alkoholfreier Secco",
        "hint": "mit Holunderblütensirup, Minze und Limette",
        "alcohol": False,
        "kind": KIND_MIXED,
        "pack": 0.75,
    },
    "bowle_af": {
        "title": "Alkoholfreie Bowle",
        "name": "alkoholfreie Bowle",
        "hint": "mit Erdbeeren und Kindersekt",
        "alcohol": False,
        "kind": KIND_MIXED,
        "kids": True,
        "pack": None,
    },
    "cola": {
        "title": "Cola",
        "name": "Cola",
        "hint": "",
        "alcohol": False,
        "kind": KIND_SOFT,
        "pack": None,
    },
    "limonade": {
        "title": "Limonade",
        "name": "Limonade",
        "hint": "",
        "alcohol": False,
        "kind": KIND_SOFT,
        "kids": True,
        "pack": None,
    },
    "eistee": {
        "title": "Eistee",
        "name": "Eistee",
        "hint": "",
        "alcohol": False,
        "kind": KIND_SOFT,
        "kids": True,
        "pack": None,
    },
    "orangensaft": {
        "title": "Orangensaft",
        "name": "Orangensaft",
        "hint": "",
        "alcohol": False,
        "kind": KIND_JUICE,
        "kids": True,
        "pack": None,
    },
    "mineralwasser": {
        "title": "Mineralwasser",
        "name": "Mineralwasser",
        "hint": "still und sprudelnd",
        "alcohol": False,
        "kind": KIND_WATER,
        "kids": True,
        "pack": None,
    },
}

# what the rules look at: tags (folded recipe tags), names (parts of folded dish names),
# keys (ingredient keys containing the word), proteins (from _variety_signature),
# occasions (template ids), courses, months, windows ("advent"); weight per match
DRINK_RULES: list[dict[str, Any]] = [
    {
        "id": "braten",
        "reason": "kräftiges Fleisch",
        "tags": {"rind", "wild", "braten", "lamm", "ente", "gans", "festlich"},
        "names": (
            "braten",
            "gulasch",
            "roulade",
            "wild",
            "reh",
            "hirsch",
            "gans",
            "ente",
            "lamm",
            "steak",
            "rinder",
            "ochsen",
            "schmor",
        ),
        "proteins": {
            "rind",
            "rindfleisch",
            "rinderhackfleisch",
            "lamm",
            "wild",
            "ente",
            "gans",
            "rinderbraten",
            "rinderroulade",
        },
        "alcohol": ("rotwein_kraeftig",),
        "free": ("traubensaft_rot", "johannisbeerschorle"),
    },
    {
        "id": "tomate",
        "reason": "Pasta oder Pizza mit Tomate",
        "tags": {"pizza"},
        "names": ("pizza", "lasagne", "bolognese", "arrabbiata", "napoli", "pomodoro"),
        "need_tomato": ("pasta", "italienisch"),
        "alcohol": ("rotwein_leicht",),
        "free": ("traubensaft_rot", "apfelschorle"),
    },
    {
        "id": "fisch",
        "reason": "Fisch oder Geflügel",
        "tags": {"fisch", "haehnchen", "gefluegel", "pute", "huhn", "meeresfruechte"},
        "names": (
            "fisch",
            "lachs",
            "forelle",
            "kabeljau",
            "seelachs",
            "garnele",
            "scampi",
            "zander",
            "dorade",
            "haehnchen",
            "huhn",
            "pute",
            "gefluegel",
        ),
        "proteins": {
            "lachs",
            "fisch",
            "forelle",
            "kabeljau",
            "seelachs",
            "garnele",
            "haehnchen",
            "haehnchenbrust",
            "haehnchenbrustfilet",
            "pute",
            "putenbrust",
        },
        "alcohol": ("weisswein",),
        "free": ("apfelschorle", "weisswein_af"),
    },
    {
        "id": "spargel",
        "reason": "Spargel",
        "names": ("spargel",),
        "keys": ("spargel",),
        "weight": 3.0,
        "alcohol": ("silvaner",),
        "free": ("apfelschorle", "weisswein_af"),
    },
    {
        "id": "grill",
        "reason": "Gegrilltes und Deftiges",
        "tags": {"grillen", "grill", "bbq", "deftig"},
        "names": (
            "grill",
            "bratwurst",
            "wuerstchen",
            "currywurst",
            "haxe",
            "leberkaese",
            "burger",
            "schnitzel",
            "spiess",
        ),
        "occasions": {"grillen"},
        "alcohol": ("bier",),
        "free": ("bier_af", "radler_af", "fassbrause"),
    },
    {
        "id": "asiatisch",
        "reason": "asiatisch und scharf",
        "tags": {
            "asiatisch",
            "scharf",
            "indisch",
            "thailaendisch",
            "chinesisch",
            "vietnamesisch",
            "japanisch",
            "curry",
            "orientalisch",
        },
        "names": ("curry", "thai", "wok", "pad ", "sushi", "teriyaki", "chili"),
        "alcohol": ("riesling_feinherb",),
        "free": ("ingwer_limo", "mango_lassi"),
    },
    {
        "id": "mexikanisch",
        "reason": "mexikanisch",
        "tags": {"mexikanisch", "tex mex"},
        "names": ("taco", "burrito", "nachos", "quesadilla", "enchilada", "chili con carne"),
        "alcohol": ("bier",),
        "free": ("limonade", "eistee"),
    },
    {
        "id": "kaese",
        "reason": "Käse und Raclette",
        "names": ("raclette", "fondue", "kaesespaetzle", "flammkuchen", "tartiflette"),
        "occasions": {"raclette", "fondue"},
        "alcohol": ("weisswein",),
        "free": ("tee", "apfelschorle"),
    },
    {
        "id": "fest",
        "reason": "zum Anstoßen",
        "tags": {"festlich"},
        "occasions": {"weihnachten", "silvester", "geburtstag", "ostern"},
        "alcohol": ("sekt",),
        "free": ("kindersekt", "traubensecco"),
    },
    {
        "id": "party",
        "reason": "Party",
        "tags": {"party", "fingerfood"},
        "occasions": {"party", "silvester", "geburtstag"},
        "alcohol": ("bier", "sekt"),
        "free": ("cola", "limonade"),
    },
    {
        "id": "film",
        "reason": "Filmabend",
        "occasions": {"filmabend"},
        "weight": 3.0,
        "alcohol": ("bier",),
        "free": ("cola", "eistee"),
    },
    {
        "id": "brunch",
        "reason": "Brunch",
        "tags": {"fruehstueck", "brunch"},
        "occasions": {"brunch"},
        "alcohol": ("sekt",),
        "free": ("orangensaft", "kaffee"),
    },
    {
        "id": "dessert",
        "reason": "zum Dessert",
        "tags": {"dessert", "nachtisch", "kuchen", "suess", "suessspeise", "torte"},
        "courses": {"dessert"},
        "free": ("kaffee", "kakao"),
    },
    {
        "id": "advent",
        "reason": "Adventszeit",
        "windows": {"advent"},
        "alcohol": ("gluehwein",),
        "free": ("kinderpunsch",),
    },
    {
        "id": "sommer",
        "reason": "Sommer",
        "months": {6, 7, 8},
        "alcohol": ("hugo", "bowle"),
        "free": ("hugo_af", "bowle_af"),
    },
    {
        "id": "familie",
        "reason": "Familienessen",
        "occasions": {"familienessen"},
        "free": ("apfelschorle", "johannisbeerschorle"),
    },
]
FALLBACK_FREE = ("mineralwasser", "apfelschorle")
KIDS_FALLBACK = ("apfelschorle", "limonade")
DEFAULT_COUNT = 5
MAX_COUNT = 10
MAX_ALCOHOL = 2
MIN_FREE = 2
# litres per adult / child: base + per hour (an evening of 3 hours: ~1.2 l per adult)
ADULT_BASE_L = 0.45
ADULT_HOUR_L = 0.25
CHILD_BASE_L = 0.3
CHILD_HOUR_L = 0.2
ALCOHOL_SHARE = 0.45
CUP_L = 0.2
DEFAULT_HOURS = 3.0
TITLE_MAX = 60
REASON_MAX = 140
AI_MAX = 4

# parts of drink names with alcohol ("Rotwein", "Weizenbier", "Aperol Spritz") and whole
# words that are too short to look for inside other words ("Gin" is no "Ingwer")
_ALCOHOL_PARTS = (
    "wein",
    "bier",
    "pils",
    "sekt",
    "prosecco",
    "champagner",
    "cremant",
    "spritz",
    "aperol",
    "hugo",
    "bowle",
    "punsch",
    "likoer",
    "schnaps",
    "wodka",
    "vodka",
    "whisky",
    "whiskey",
    "cognac",
    "brandy",
    "grappa",
    "cocktail",
    "mojito",
    "caipirinha",
    "margarita",
    "radler",
    "sangria",
    "amaretto",
    "tequila",
    "ouzo",
    # wines by grape or region ("Silvaner", "Chianti" – an AI answers like that)
    "silvaner",
    "riesling",
    "burgunder",
    "dornfelder",
    "lemberger",
    "trollinger",
    "mueller thurgau",
    "chianti",
    "barolo",
    "rioja",
    "primitivo",
    "montepulciano",
    "lambrusco",
    "merlot",
    "cabernet",
    "chardonnay",
    "sauvignon",
    "shiraz",
    "syrah",
    "pinot",
    "grauburgunder",
    "sherry",
    "lillet",
    "campari",
    "koelsch",
)
_ALCOHOL_WORDS = frozenset(
    {"rum", "gin", "met", "cidre", "cider", "helles", "weizen", "secco", "alt", "ipa", "porto"}
)
_ALCOHOL_FREE = re.compile(
    r"(alkoholfrei|ohne alkohol|0 0|0 prozent|kinder|virgin|mocktail|traubensaft|"
    r"traubensecco|ingwerbier)"
)


def is_alcoholic(title: str) -> bool:
    """True when a drink's name says it has alcohol ('Rotwein', 'Hugo', 'Gin Tonic');
    'alkoholfreies Bier', 'Kinderpunsch', 'Virgin Mojito', 'Traubensaft' or
    'Limettenlimonade' have none."""
    folded = fold(title)
    if not folded or _ALCOHOL_FREE.search(folded):
        return False
    if any(word in _ALCOHOL_WORDS for word in folded.split()):
        return True
    return any(part in folded for part in _ALCOHOL_PARTS)


def alcohol_allowed(manager: EssensplanerManager) -> bool:
    """The option "Getränkevorschläge mit Alkohol" (alcohol-free ones are always there)."""
    return bool(manager.options.get(CONF_DRINKS_ALCOHOL, DEFAULT_DRINKS_ALCOHOL))


def season_windows(day: date) -> set[str]:
    """Windows of the year for drinks: 'advent' (first Sunday of Advent until the 24th)."""
    windows: set[str] = set()
    if advent_start(day.year) <= day <= date(day.year, 12, 24):
        windows.add("advent")
    return windows


def _features(
    manager: EssensplanerManager,
    recipes: list[dict[str, Any]],
    titles: list[str],
    template: str | None,
    day: date,
    courses: set[str],
) -> dict[str, Any]:
    from .occasions import recipe_course  # occasions imports this module

    tags: set[str] = set()
    names: list[str] = [fold(t) for t in titles if t]
    keys: set[str] = set()
    proteins: set[str] = set()
    for recipe in recipes:
        tags |= manager.recipe_tags_folded(recipe)
        names.append(fold(recipe.get("name", "")))
        for ingredient in recipe.get("ingredients") or []:
            if key := ingredient_key(ingredient.get("name", "")):
                keys.add(key)
        for part in manager._variety_signature(recipe):
            if part.startswith("protein:"):
                proteins.add(part.split(":", 1)[1])
        courses.add(recipe_course(recipe))
    return {
        "tags": tags,
        "names": names,
        "keys": keys,
        "proteins": proteins,
        "template": template,
        "courses": courses,
        "month": day.month,
        "windows": season_windows(day),
    }


def _rule_weight(rule: dict[str, Any], feat: dict[str, Any]) -> float:
    """How well a rule matches (0 = not at all)."""
    score = 0.0
    if rule.get("tags") and feat["tags"] & rule["tags"]:
        score += 2.0
    if rule.get("names") and any(word in name for name in feat["names"] for word in rule["names"]):
        score += 2.0
    if rule.get("keys") and any(word in key for key in feat["keys"] for word in rule["keys"]):
        score += 1.5
    if rule.get("proteins") and feat["proteins"] & rule["proteins"]:
        score += 1.5
    if (
        rule.get("need_tomato")
        and feat["tags"] & set(rule["need_tomato"])
        and any("tomate" in key or "passata" in key for key in feat["keys"])
    ):
        score += 2.0
    if rule.get("occasions") and feat["template"] in rule["occasions"]:
        score += 3.0
    if rule.get("courses") and feat["courses"] & rule["courses"]:
        score += 1.5
    if rule.get("months") and feat["month"] in rule["months"]:
        score += 1.0
    if rule.get("windows") and feat["windows"] & rule["windows"]:
        score += 2.0
    return score * float(rule.get("weight", 1.0)) if score else 0.0


def drink_view(drink_id: str, reason: str | None = None, score: float = 0.0) -> dict[str, Any]:
    """A drink for display and for occasion items."""
    info = DRINKS[drink_id]
    return {
        "id": drink_id,
        "title": info["title"],
        "name": info["name"],
        "hint": info.get("hint") or "",
        "alcohol": bool(info["alcohol"]),
        "kids": bool(info.get("kids")),
        "kind": info["kind"],
        "reason": reason or "",
        "score": round(score, 2),
    }


def _drink_recipe(manager: EssensplanerManager, title: str) -> dict[str, Any] | None:
    """A recipe of the collection that makes this drink ('Glühwein', 'Kinderpunsch')."""
    return manager.get_recipe_by_name(title)


def _offer_for(manager: EssensplanerManager, name: str, day: date) -> dict[str, Any] | None:
    """A current offer of the user's stores for a drink (cheapest), as {title, store,
    price, valid_to}."""
    if not ingredient_key(name):
        return None
    best = None
    for offer in manager.offers_for(name, day):
        price = offer.get("price")
        if not isinstance(price, (int, float)):
            continue
        if best is None or price < best["price"]:
            best = offer
    if best is None:
        return None
    return {
        "id": best.get("id"),
        "title": best.get("title"),
        "store": best.get("store"),
        "price": best.get("price"),
        "valid_to": best.get("valid_to"),
        "text": f"{best.get('store')} {format_eur(best.get('price'))}",
    }


def suggest_drinks(
    manager: EssensplanerManager,
    recipes: list[dict[str, Any]] | None = None,
    titles: list[str] | None = None,
    template: str | None = None,
    day: date | None = None,
    alcohol: bool | None = None,
    guests: int | None = None,
    children: int = 0,
    hours: float | None = None,
    count: int = DEFAULT_COUNT,
    courses: set[str] | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    """Drinks for dishes (recipes or free titles) and/or an occasion template.

    Always at least MIN_FREE alcohol-free drinks; alcoholic ones (at most MAX_ALCOHOL) only
    when allowed (alcohol, default: the option drinks_alcohol); with children at least one
    drink for children. kind: only drinks of this kind first ("wine" also takes sparkling
    wine; "free" = only alcohol-free). Quantities when guests are given.
    Result {drinks: [{id, title, name, hint, alcohol, kids, kind, reason, score, offer?,
    recipe_id?, liters?, quantity?, unit?, bottles?}], alcohol, reasons, quantities}.
    """
    day = day or manager.today()
    allowed = alcohol_allowed(manager) if alcohol is None else bool(alcohol)
    if kind == "free":
        allowed = False
    count = max(MIN_FREE, min(int(count or DEFAULT_COUNT), MAX_COUNT))
    feat = _features(manager, recipes or [], titles or [], template, day, set(courses or ()))
    scores: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}
    matched: list[str] = []
    for rule in DRINK_RULES:
        weight = _rule_weight(rule, feat)
        if not weight:
            continue
        matched.append(rule["reason"])
        for position, drink_id in enumerate((*rule.get("alcohol", ()), *rule.get("free", ()))):
            # the first drink of a rule fits best
            scores[drink_id] = scores.get(drink_id, 0.0) + weight * (1 - 0.1 * position)
            reasons.setdefault(drink_id, [])
            if rule["reason"] not in reasons[drink_id]:
                reasons[drink_id].append(rule["reason"])
    offers: dict[str, dict[str, Any]] = {}
    for drink_id in list(scores) + list(FALLBACK_FREE):
        name = DRINKS[drink_id]["name"]
        if drink_id not in offers and (offer := _offer_for(manager, name, day)) is not None:
            offers[drink_id] = offer
            if drink_id in scores:
                scores[drink_id] += 0.5  # on offer at the user's stores
    order = sorted(scores, key=lambda d: (-scores[d], DRINKS[d]["title"]))
    if kind and kind != "free":
        wanted = {KIND_WINE, KIND_SPARKLING} if kind == KIND_WINE else {kind}
        order.sort(key=lambda d: DRINKS[d]["kind"] not in wanted)
    chosen: list[str] = []
    if allowed:
        chosen += [d for d in order if DRINKS[d]["alcohol"]][:MAX_ALCOHOL]
    free_slots = max(MIN_FREE, count - len(chosen))
    free = [d for d in order if not DRINKS[d]["alcohol"]]
    if children and not any(DRINKS[d].get("kids") for d in free[:free_slots]):
        kids = next(
            (d for d in free if DRINKS[d].get("kids")),
            next(d for d in KIDS_FALLBACK if DRINKS[d].get("kids")),
        )
        free = [kids] + [d for d in free if d != kids]
    for fallback in FALLBACK_FREE:
        if len(free) >= free_slots:
            break
        if fallback not in free:
            free.append(fallback)
    chosen += free[:free_slots]
    drinks = []
    for drink_id in chosen:
        reason = ", ".join(reasons.get(drink_id, [])) or (
            "für Kinder" if children and DRINKS[drink_id].get("kids") else "geht immer"
        )
        view = drink_view(drink_id, reason, scores.get(drink_id, 0.0))
        if drink_id in offers:
            view["offer"] = offers[drink_id]
        if (recipe := _drink_recipe(manager, view["title"])) is not None:
            view["recipe_id"] = recipe["id"]
        drinks.append(view)
    quantities = None
    if guests:
        quantities = drink_quantities(drinks, guests, children, hours)
    return {
        "drinks": drinks,
        "alcohol": allowed,
        "reasons": matched,
        "quantities": quantities,
    }


def drink_quantities(
    drinks: list[dict[str, Any]],
    guests: int,
    children: int = 0,
    hours: float | None = None,
) -> dict[str, Any]:
    """Litres per drink for the guests (set on each drink: liters, quantity, unit and for
    bottled drinks bottles). Adults drink ADULT_BASE_L + ADULT_HOUR_L per hour, children
    CHILD_BASE_L + CHILD_HOUR_L; alcoholic drinks get ALCOHOL_SHARE of the adults' litres,
    hot drinks one cup per person. Returns {guests, children, hours, liters}."""
    hours = float(hours or DEFAULT_HOURS)
    guests = max(0, int(guests or 0))
    children = max(0, int(children or 0))
    adult_l = guests * (ADULT_BASE_L + ADULT_HOUR_L * hours)
    child_l = children * (CHILD_BASE_L + CHILD_HOUR_L * hours)
    cups = [d for d in drinks if DRINKS.get(d.get("id") or "", {}).get("per_cup")]
    cold = [d for d in drinks if d not in cups]
    alcoholic = [d for d in cold if d.get("alcohol")]
    free = [d for d in cold if not d.get("alcohol")]
    kids = [d for d in free if d.get("kids")]
    alcohol_l = adult_l * ALCOHOL_SHARE if alcoholic else 0.0
    free_adult_l = adult_l - alcohol_l
    liters: dict[int, float] = {}
    for drink in alcoholic:
        liters[id(drink)] = alcohol_l / len(alcoholic)
    for drink in free:
        liters[id(drink)] = liters.get(id(drink), 0.0) + free_adult_l / max(len(free), 1)
    for drink in kids or free:
        liters[id(drink)] = liters.get(id(drink), 0.0) + child_l / max(len(kids or free), 1)
    for drink in cups:
        drinkers = children if drink.get("kids") and drink.get("id") == "kakao" else guests
        liters[id(drink)] = max(1, drinkers) * CUP_L
    total = 0.0
    for drink in drinks:
        amount = liters.get(id(drink), 0.0)
        if amount <= 0:
            continue
        pack = DRINKS.get(drink.get("id") or "", {}).get("pack")
        if pack and pack != 1.0:
            bottles = max(1, math.ceil(amount / pack - 1e-9))
            amount = bottles * pack
            drink["bottles"] = bottles
        else:
            amount = max(0.5, math.ceil(amount * 2 - 1e-9) / 2)
        drink["liters"] = round(amount, 2)
        drink["quantity"] = round(amount, 2)
        drink["unit"] = "l"
        total += amount
    return {"guests": guests, "children": children, "hours": hours, "liters": round(total, 2)}


def drink_text(drink: dict[str, Any]) -> str:
    """'Rotwein, leicht (z. B. Spätburgunder oder Chianti)'."""
    hint = drink.get("hint")
    return f"{drink['title']} ({hint})" if hint else str(drink["title"])


# ----------------------------------------------------------------------
# AI (optional, feature "drinks")
# ----------------------------------------------------------------------

AI_TASK_NAME = "Essensplaner Getränke"
AI_INSTRUCTIONS = (
    "Du bist Sommelier und Gastgeber. Schlage passende Getränke zu den Gerichten bzw. zum "
    "Anlass vor (deutsche Namen, kurz). Immer mindestens zwei alkoholfreie Getränke; "
    "Getränke mit Alkohol nur, wenn 'alkohol_erlaubt' true ist; bei Kindern auch ein "
    "Getränk für Kinder. 'regel_vorschlaege' sind bereits geprüfte Vorschläge – übernimm "
    "gute davon und ergänze höchstens vier eigene. Antworte als JSON: "
    '{"getraenke": [{"titel": "…", "alkohol": true/false, "grund": "…"}]}'
)


def ai_payload(
    manager: EssensplanerManager,
    recipes: list[dict[str, Any]],
    titles: list[str],
    template: str | None,
    day: date,
    allowed: bool,
    guests: int | None,
    children: int,
    rule_drinks: list[dict[str, Any]],
) -> dict[str, Any]:
    """What the AI gets: dish names and tags, the occasion kind, month, guests, the rule
    drinks (no notes, names or places)."""
    from .occasions import TEMPLATES  # occasions imports this module

    return {
        "gerichte": [
            {"name": r.get("name"), "tags": list(r.get("tags") or [])[:8]} for r in recipes
        ]
        + [{"name": t} for t in titles],
        "anlass": TEMPLATES[template]["title"] if template in TEMPLATES else None,
        "monat": day.month,
        "alkohol_erlaubt": allowed,
        "gaeste": guests,
        "kinder": children,
        "regel_vorschlaege": [{"titel": d["title"], "alkohol": d["alcohol"]} for d in rule_drinks],
    }


def parse_ai_drinks(answer: Any, allowed: bool) -> list[dict[str, Any]]:
    """Checked drinks of an AI answer ({"getraenke": [...]} or a list): a title (≤ 60
    characters), alcohol by name and by the answer (a drink with alcohol is dropped when
    not allowed), a short reason; at most AI_MAX."""
    items: Any = answer
    if isinstance(answer, dict):
        items = next((answer[k] for k in ("getraenke", "drinks", "getränke") if k in answer), None)
    if not isinstance(items, list):
        return []
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in items:
        if isinstance(raw, str):
            raw = {"titel": raw}
        if not isinstance(raw, dict):
            continue
        title = " ".join(str(raw.get("titel") or raw.get("title") or "").split())[:TITLE_MAX]
        if not title or fold(title) in seen:
            continue
        said = raw.get("alkohol", raw.get("alcohol"))
        alcohol = is_alcoholic(title) or said is True
        if alcohol and not allowed:
            continue
        seen.add(fold(title))
        reason = " ".join(str(raw.get("grund") or raw.get("reason") or "").split())
        found.append(
            {
                "id": None,
                "title": title,
                "name": title,
                "hint": "",
                "alcohol": alcohol,
                "kids": False,
                "kind": None,
                "reason": reason[:REASON_MAX],
                "score": 0.0,
                "ai": True,
            }
        )
        if len(found) >= AI_MAX:
            break
    return found


def merge_drinks(
    ai_drinks: list[dict[str, Any]], rule_drinks: list[dict[str, Any]], count: int
) -> list[dict[str, Any]]:
    """AI drinks first, then the rule drinks (same name once), at most count + AI_MAX; at
    least MIN_FREE alcohol-free ones stay."""
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for drink in [*ai_drinks, *rule_drinks]:
        key = fold(drink["title"])
        if key in seen:
            continue
        seen.add(key)
        merged.append(drink)
    limit = max(count, MIN_FREE) + AI_MAX
    result = merged[:limit]
    free = [d for d in result if not d["alcohol"]]
    for drink in merged[limit:]:
        if len(free) >= MIN_FREE:
            break
        if not drink["alcohol"]:
            result.append(drink)
            free.append(drink)
    return result


async def async_ai_drinks(
    hass: HomeAssistant,
    manager: EssensplanerManager,
    rules: dict[str, Any],
    recipes: list[dict[str, Any]] | None = None,
    titles: list[str] | None = None,
    template: str | None = None,
    day: date | None = None,
    guests: int | None = None,
    children: int = 0,
    hours: float | None = None,
) -> dict[str, Any]:
    """The rule result (suggest_drinks()) extended by the AI: its drinks first, checked
    (alcohol only when allowed), quantities again for all. Raises the ai_* errors."""
    from .ai import async_ai_json  # imports the manager

    day = day or manager.today()
    allowed = bool(rules["alcohol"])
    payload = ai_payload(
        manager,
        recipes or [],
        titles or [],
        template,
        day,
        allowed,
        guests,
        children,
        rules["drinks"],
    )
    answer = await async_ai_json(
        hass, manager, AI_FEATURE_DRINKS, AI_TASK_NAME, AI_INSTRUCTIONS, payload
    )
    ai_drinks = parse_ai_drinks(answer, allowed)
    for drink in ai_drinks:
        if (recipe := _drink_recipe(manager, drink["title"])) is not None:
            drink["recipe_id"] = recipe["id"]
    drinks = merge_drinks(ai_drinks, rules["drinks"], len(rules["drinks"]))
    quantities = None
    if guests:
        for drink in drinks:
            for key in ("liters", "quantity", "unit", "bottles"):
                drink.pop(key, None)
        quantities = drink_quantities(drinks, guests, children, hours)
    return {**rules, "drinks": drinks, "quantities": quantities, "ai": True}
