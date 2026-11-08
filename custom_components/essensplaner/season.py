"""Season (1.5): what is in season in Germany, times of the year and seasonal planning.

- SEASON_CALENDAR: fresh produce, fish and game with the months they are in season
  (Spargel April–June, Kürbis September–December, Grünkohl November–February …). A recipe
  line counts when its product is fresh: "Kirschtomaten" is a tomato, "Tomatenmark",
  "gehackte Tomaten", "Kürbiskerne", "Apfelmus" or anything from a can, a jar or the
  freezer is not.
- WINDOWS: times of the year with their dishes – Fasching, Ostern (computed with easter()),
  Grillzeit (May–August), Oktoberfest, Martinstag, Advent (advent_start()), Weihnachten and
  Silvester.
- recipe_season(): how well a recipe fits a day (score 0..1, the produce in season, the
  produce out of season, the times it fits and short hints such as "🍂 Saison: Kürbis"),
  cached per recipe, recipe version, month and active times.
- season_factor(): the factor of the suggestion weights (manager._suggest_weight()):
  × (1 + weight·score), × 0.4 when a typical seasonal product (Spargel, Erdbeeren …) is out
  of season. The weight comes from the planning strategy (economy._STRATEGY_WEIGHTS;
  "seasonal" weighs it most); the option "season_aware" switches it off for the other
  strategies.
- The optional AI plan (feature "season"): the AI only orders the 40 candidates the rules
  ranked best; unknown ids are dropped and the rules fill the rest (async_auto_plan()).
"""

from __future__ import annotations

from collections.abc import Callable
import copy
from dataclasses import dataclass
from datetime import date, timedelta
import functools
import logging
from typing import TYPE_CHECKING, Any

from .const import AI_FEATURE_SEASON, CONF_SEASON_AWARE, DEFAULT_SEASON_AWARE, STRATEGY_SEASONAL
from .dates import WEEKDAY_NAMES, advent_start, easter
from .ingredients import fold

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .manager import EssensplanerManager

_LOGGER = logging.getLogger(__name__)

MONTH_NAMES = [
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
]
# folded month words -> month ("jaenner" and "feber" are Austrian)
_MONTH_WORDS = {
    **{fold(name): number for number, name in enumerate(MONTH_NAMES, 1)},
    "jan": 1,
    "jaenner": 1,
    "feb": 2,
    "feber": 2,
    "maerz": 3,
    "mrz": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "okt": 10,
    "nov": 11,
    "dez": 12,
}

# meteorological seasons: id -> (label, emoji, months)
SEASONS: dict[str, tuple[str, str, tuple[int, ...]]] = {
    "spring": ("Frühling", "🌱", (3, 4, 5)),
    "summer": ("Sommer", "☀️", (6, 7, 8)),
    "autumn": ("Herbst", "🍂", (9, 10, 11)),
    "winter": ("Winter", "❄️", (12, 1, 2)),
}
# folded recipe tags naming a season
SEASON_TAGS = {
    "spring": frozenset({"fruehling", "fruehjahr"}),
    "summer": frozenset({"sommer", "sommerlich"}),
    "autumn": frozenset({"herbst", "herbstlich"}),
    "winter": frozenset({"winter", "winterlich"}),
}


def _months(first: int, last: int) -> tuple[int, ...]:
    """Months from first to last, across the turn of the year (11, 2 -> 11, 12, 1, 2)."""
    months = [first]
    while months[-1] != last:
        months.append(months[-1] % 12 + 1)
    return tuple(months)


@dataclass(frozen=True)
class Produce:
    """A seasonal product: words of its (folded) name, the months it is in season; strict
    products (Spargel, Erdbeeren, Kürbis …) are typical seasonal dishes – a recipe with
    them out of season is suggested less."""

    id: str
    label: str
    months: tuple[int, ...]
    words: tuple[str, ...]
    strict: bool = False
    prefixes: tuple[str, ...] = ()
    # words of other products that end with a word of this one ("Knoblauch", "Kichererbsen")
    exclude: tuple[str, ...] = ()


# fresh produce, fish and game in Germany (regional season, open-air or stored)
SEASON_CALENDAR: dict[str, Produce] = {
    p.id: p
    for p in (
        Produce("baerlauch", "Bärlauch", _months(3, 5), ("baerlauch",), True),
        Produce("spargel", "Spargel", _months(4, 6), ("spargel",), True),
        Produce("rhabarber", "Rhabarber", _months(4, 6), ("rhabarber",), True),
        Produce("radieschen", "Radieschen", _months(4, 9), ("radieschen",)),
        Produce("kohlrabi", "Kohlrabi", _months(5, 10), ("kohlrabi",)),
        Produce("erdbeere", "Erdbeeren", _months(5, 7), ("erdbeere",), True),
        Produce("spinat", "Spinat", (3, 4, 5, 9, 10, 11), ("spinat",), exclude=("rahmspinat",)),
        Produce(
            "erbse", "Erbsen", _months(6, 8), ("zuckerschote", "erbse"), exclude=("kichererbse",)
        ),
        Produce("matjes", "Matjes", _months(6, 7), ("matjes",), prefixes=("matjes",)),
        Produce(
            "kirsche",
            "Kirschen",
            _months(6, 8),
            ("kirsche",),
            True,
            exclude=("cocktailkirsche", "sauerkirsche"),
        ),
        Produce("heidelbeere", "Heidelbeeren", _months(7, 9), ("heidelbeere", "blaubeere")),
        Produce("himbeere", "Himbeeren", _months(6, 9), ("himbeere",)),
        Produce("johannisbeere", "Johannisbeeren", _months(6, 8), ("johannisbeere",)),
        Produce(
            "gurke",
            "Gurken",
            _months(6, 9),
            ("salatgurke", "gurke"),
            exclude=("gewuerzgurke", "essiggurke", "salzgurke", "cornichon"),
        ),
        Produce("zucchini", "Zucchini", _months(6, 10), ("zucchini",)),
        Produce("fenchel", "Fenchel", _months(6, 11), ("fenchel",)),
        Produce(
            "tomate",
            "Tomaten",
            _months(7, 10),
            ("tomate",),
            exclude=("pizzatomate", "dosentomate", "tomatenmark"),
        ),
        Produce("paprika", "Paprika", _months(7, 10), ("paprika", "paprikaschote")),
        Produce("aubergine", "Auberginen", _months(7, 10), ("aubergine",)),
        Produce(
            "bohne",
            "grüne Bohnen",
            _months(7, 10),
            ("gruene bohne", "brechbohne", "buschbohne", "stangenbohne", "schnippelbohne"),
        ),
        Produce("mais", "Mais", _months(8, 10), ("maiskolben",)),
        Produce(
            "zwetschge",
            "Zwetschgen",
            _months(7, 9),
            ("zwetschge", "pflaume"),
            True,
            exclude=("trockenpflaume", "backpflaume"),
        ),
        Produce("mirabelle", "Mirabellen", _months(7, 9), ("mirabelle",), True),
        Produce("pfifferling", "Pfifferlinge", _months(7, 10), ("pfifferling",), True),
        Produce("steinpilz", "Steinpilze", _months(8, 10), ("steinpilz",), True),
        Produce("pilz", "Waldpilze", _months(7, 10), ("waldpilz", "pilz", "schwammerl")),
        Produce("apfel", "Äpfel", _months(8, 11), ("apfel", "aepfel"), exclude=("granatapfel",)),
        Produce("birne", "Birnen", _months(8, 11), ("birne",)),
        Produce(
            "trauben",
            "Weintrauben",
            _months(8, 10),
            ("weintraube", "traube"),
            exclude=("trockentraube",),
        ),
        Produce("federweisser", "Federweißer", _months(9, 10), ("federweisser",), True),
        Produce("quitte", "Quitten", _months(9, 11), ("quitte",), True),
        Produce("kuerbis", "Kürbis", _months(9, 12), ("kuerbis",), True),
        Produce("rote_bete", "Rote Bete", _months(9, 3), ("rote bete", "rote beete")),
        Produce(
            "lauch",
            "Lauch",
            _months(9, 3),
            ("lauch", "porree"),
            exclude=("schnittlauch", "knoblauch", "baerlauch"),
        ),
        Produce("rotkohl", "Rotkohl", _months(9, 3), ("rotkohl", "blaukraut", "rotkraut")),
        Produce("wirsing", "Wirsing", _months(9, 3), ("wirsing",)),
        Produce("weisskohl", "Weißkohl", _months(9, 3), ("weisskohl", "spitzkohl")),
        Produce("knollensellerie", "Sellerie", _months(9, 3), ("knollensellerie",)),
        Produce("muschel", "Muscheln", _months(9, 4), ("miesmuschel", "muschel")),
        Produce("rosenkohl", "Rosenkohl", _months(10, 2), ("rosenkohl",)),
        Produce("feldsalat", "Feldsalat", _months(10, 3), ("feldsalat",)),
        Produce("pastinake", "Pastinaken", _months(10, 3), ("pastinake",)),
        Produce("schwarzwurzel", "Schwarzwurzeln", _months(10, 3), ("schwarzwurzel",), True),
        Produce(
            "wild",
            "Wild",
            _months(10, 1),
            ("wildschwein", "wildgulasch", "wildbraten", "wildragout"),
            prefixes=("reh", "hirsch", "wildschwein"),
        ),
        Produce("gans", "Gans", _months(11, 12), ("gans",), True, prefixes=("gaense",)),
        Produce("gruenkohl", "Grünkohl", _months(11, 2), ("gruenkohl",), True),
        Produce("chicoree", "Chicorée", _months(10, 3), ("chicoree",)),
    )
}

# a recipe line with one of these words is processed, not fresh ("Tomatenmark",
# "Apfelmus", "Kürbiskerne", "getrocknete Tomaten", "Erdbeerkonfitüre")
_PROCESSED_WORDS = (
    "mark",
    "mus",
    "saft",
    "schorle",
    "nektar",
    "marmelade",
    "konfituere",
    "gelee",
    "kern",
    "kerne",
    "chips",
    "pulver",
    "sirup",
    "getrocknet",
    "getrocknete",
    "passiert",
    "passierte",
    "gehackt",
    "gehackte",
    "dose",
    "konserve",
    "glas",
    "tk",
    "tiefkuehl",
    "tiefgekuehlt",
    "ketchup",
    "pesto",
    "essig",
    "likoer",
    "aroma",
)
_PROCESSED_PARTS = ("tiefkuehl", "konserve", "getrocknet", "dosen")
# units of canned or jarred products
_PROCESSED_UNITS = {"Dose", "Glas"}

OUT_OF_SEASON_FACTOR = 0.4  # suggestion weight with a typical product out of season
CANDIDATES = 40  # rule candidates the AI may order (auto plan "mit KI")
MAX_HINT_ITEMS = 2
_CACHE_MAX = 5000


@dataclass(frozen=True)
class Window:
    """A time of the year: its dates in a year and the dishes that fit it (folded tags,
    words of recipe names, words of ingredient names)."""

    id: str
    label: str
    emoji: str
    dates: Callable[[int], tuple[date, date]]
    tags: frozenset[str] = frozenset()
    names: tuple[str, ...] = ()
    ingredients: tuple[str, ...] = ()


def _oktoberfest(year: int) -> tuple[date, date]:
    """From the Saturday after 15 September to the first Sunday in October (at least
    3 October)."""
    start = date(year, 9, 16)
    start += timedelta(days=(5 - start.weekday()) % 7)
    end = date(year, 10, 1)
    end += timedelta(days=(6 - end.weekday()) % 7)
    return start, max(end, date(year, 10, 3))


WINDOWS: tuple[Window, ...] = (
    Window(
        "fasching",
        "Fasching",
        "🎭",
        lambda y: (easter(y) - timedelta(days=52), easter(y) - timedelta(days=47)),
        frozenset({"fasching", "karneval", "fastnacht"}),
        ("krapfen", "berliner", "kreppel", "kraeppel", "mutzen"),
    ),
    Window(
        "ostern",
        "Ostern",
        "🐣",
        lambda y: (easter(y) - timedelta(days=7), easter(y) + timedelta(days=1)),
        frozenset({"ostern", "osteressen"}),
        ("lamm", "osterlamm", "hefezopf", "osterbrunch"),
        ("lamm",),
    ),
    Window(
        "grillzeit",
        "Grillzeit",
        "🔥",
        lambda y: (date(y, 5, 1), date(y, 8, 31)),
        frozenset({"grillen", "grill", "bbq", "barbecue"}),
        ("grill", "bratwurst", "bratwuerst", "spiess", "maiskolben", "folienkartoffel", "steak"),
    ),
    Window(
        "oktoberfest",
        "Oktoberfest",
        "🥨",
        _oktoberfest,
        frozenset({"bayerisch", "oktoberfest"}),
        ("brezel", "obatzda", "weisswurst", "haxe", "hendl", "schweinsbraten", "leberkaese"),
        ("weisswurst", "brezel"),
    ),
    Window(
        "martinstag",
        "Martinstag",
        "🏮",
        lambda y: (date(y, 11, 1), date(y, 11, 11)),
        frozenset({"martinsgans", "martinstag"}),
        ("gans", "gaense", "weckmann", "stutenkerl"),
        ("gans", "gaense"),
    ),
    Window(
        "advent",
        "Adventszeit",
        "🕯️",
        lambda y: (advent_start(y), date(y, 12, 23)),
        frozenset({"advent", "weihnachten", "plaetzchen", "weihnachtsbaeckerei"}),
        (
            "gluehwein",
            "punsch",
            "lebkuchen",
            "plaetzchen",
            "stollen",
            "bratapfel",
            "brataepfel",
            "spekulatius",
            "zimtstern",
            "vanillekipferl",
            "maronen",
        ),
        ("lebkuchen", "spekulatius", "marone"),
    ),
    Window(
        "weihnachten",
        "Weihnachten",
        "🎄",
        lambda y: (date(y, 12, 24), date(y, 12, 26)),
        frozenset({"weihnachten", "festlich", "festessen", "festtag"}),
        (
            "gans",
            "gaense",
            "ente",
            "braten",
            "roulade",
            "kloesse",
            "knoedel",
            "rotkohl",
            "fondue",
            "raclette",
            "rehruecken",
            "hirsch",
            "kartoffelsalat mit wuerstchen",
        ),
        ("gans", "gaense", "ente"),
    ),
    Window(
        "silvester",
        "Silvester",
        "🎆",
        lambda y: (date(y, 12, 31), date(y + 1, 1, 1)),
        frozenset({"silvester", "neujahr", "party", "fingerfood"}),
        ("raclette", "fondue", "berliner", "bowle", "sekt"),
    ),
)
WINDOW_MAP = {w.id: w for w in WINDOWS}
WINDOW_HINT_DAYS = 21  # "bald: Adventszeit" this many days before a time starts


# ----------------------------------------------------------------------
# Calendar
# ----------------------------------------------------------------------


def season_of(day: date) -> str:
    """The meteorological season of a day (spring, summer, autumn, winter)."""
    for season, (_, _, months) in SEASONS.items():
        if day.month in months:
            return season
    return "winter"  # pragma: no cover - every month is in a season


def _window_dates(window: Window, day: date) -> tuple[date, date] | None:
    """The dates of a window that contain a day (the year before for Silvester)."""
    for year in (day.year, day.year - 1):
        start, end = window.dates(year)
        if start <= day <= end:
            return start, end
    return None


@functools.lru_cache(maxsize=512)
def active_windows(day: date) -> tuple[str, ...]:
    """Ids of the times of the year a day is in ("advent", "grillzeit" …)."""
    return tuple(w.id for w in WINDOWS if _window_dates(w, day) is not None)


def upcoming_windows(day: date, days: int = WINDOW_HINT_DAYS) -> list[dict[str, Any]]:
    """Times of the year that start within the next days (not running yet)."""
    found: list[dict[str, Any]] = []
    for window in WINDOWS:
        if _window_dates(window, day) is not None:
            continue
        for year in (day.year, day.year + 1):
            start, end = window.dates(year)
            if day < start <= day + timedelta(days=days):
                found.append(_window_view(window, start, end))
                break
    found.sort(key=lambda w: w["start"])
    return found


def _window_view(window: Window, start: date, end: date) -> dict[str, Any]:
    return {
        "id": window.id,
        "label": window.label,
        "emoji": window.emoji,
        "start": start.isoformat(),
        "end": end.isoformat(),
    }


def produce_in_season(month: int) -> list[Produce]:
    """The produce in season in a month (calendar order)."""
    return [p for p in SEASON_CALENDAR.values() if month in p.months]


def resolve_month(text: Any) -> int | None:
    """'Dezember', 'im Mai', '12' -> month number (None if none is named)."""
    if isinstance(text, int):
        return text if 1 <= text <= 12 else None
    words = fold(str(text or "")).split()
    for word in words:
        if word in _MONTH_WORDS:
            return _MONTH_WORDS[word]
        if word.isdigit() and 1 <= int(word) <= 12:
            return int(word)
    return None


def season_info(day: date) -> dict[str, Any]:
    """What is in season on a day: {date, month, month_name, season {id, label, emoji},
    windows [{id, label, emoji, start, end}] (running), upcoming [...] (starting within
    three weeks), produce [{id, label, strict, new, ending}], coming [labels starting next
    month], text ("Jetzt Saison: Kürbis, Grünkohl …")}. Cached per day (a copy is
    returned)."""
    return copy.deepcopy(_season_info(day))


@functools.lru_cache(maxsize=64)
def _season_info(day: date) -> dict[str, Any]:
    season = season_of(day)
    label, emoji, _ = SEASONS[season]
    windows = []
    for window_id in active_windows(day):
        window = WINDOW_MAP[window_id]
        start, end = _window_dates(window, day) or (day, day)
        windows.append(_window_view(window, start, end))
    month = day.month
    previous = (month - 2) % 12 + 1
    following = month % 12 + 1
    produce = [
        {
            "id": p.id,
            "label": p.label,
            "strict": p.strict,
            "new": previous not in p.months,
            "ending": following not in p.months,
        }
        for p in produce_in_season(month)
    ]
    # the typical seasonal products first, then those that are new this month
    produce.sort(key=lambda p: (not p["strict"], not p["new"]))
    coming = [
        p.label for p in SEASON_CALENDAR.values() if following in p.months and month not in p.months
    ]
    labels = [p["label"] for p in produce]
    return {
        "date": day.isoformat(),
        "month": month,
        "month_name": MONTH_NAMES[month - 1],
        "season": {"id": season, "label": label, "emoji": emoji},
        "windows": windows,
        "upcoming": upcoming_windows(day),
        "produce": produce,
        "coming": coming,
        "text": f"Jetzt Saison: {', '.join(labels[:8])}" if labels else "",
    }


# ----------------------------------------------------------------------
# Recipes
# ----------------------------------------------------------------------


def _forms(word: str) -> tuple[str, ...]:
    """A word and its forms without plural endings ('erdbeeren' -> 'erdbeere')."""
    forms = [word]
    for ending in ("n", "en", "e", "s", "se", "er", "es"):
        if word.endswith(ending) and len(word) > len(ending) + 3:
            forms.append(word[: -len(ending)])
    return tuple(forms)


@functools.lru_cache(maxsize=4096)
def produce_of(name: str) -> str | None:
    """The calendar id of a fresh product named by an ingredient name ('Hokkaido-Kürbis'
    -> 'kuerbis', 'Kirschtomaten' -> 'tomate'); None for processed products ('Tomatenmark',
    'gehackte Tomaten', 'Kürbiskerne', 'Apfelmus') and everything else."""
    folded = fold(name)
    if not folded:
        return None
    words = folded.split()
    if any(word in _PROCESSED_WORDS for word in words) or any(
        part in folded for part in _PROCESSED_PARTS
    ):
        return None
    padded = f" {folded} "
    for produce in SEASON_CALENDAR.values():
        if produce.exclude and any(ex in folded for ex in produce.exclude):
            continue
        for phrase in produce.words:
            if " " in phrase:
                if f" {phrase} " in padded or f" {phrase}n " in padded:
                    return produce.id
                continue
            # the last part of a compound ("Kirschtomaten"), never its first part
            # ("Tomatenmark", "Erdbeerjoghurt")
            if any(form.endswith(phrase) for word in words for form in _forms(word)):
                return produce.id
        if produce.prefixes and any(word.startswith(produce.prefixes) for word in words):
            return produce.id
    return None


def _line_produce(line: dict[str, Any]) -> str | None:
    """The calendar id of a fresh recipe line (canned, jarred and frozen lines: None)."""
    if not isinstance(line, dict):
        return None
    if line.get("unit") in _PROCESSED_UNITS:
        return None
    note = fold(str(line.get("note") or ""))
    if note and any(word in _PROCESSED_WORDS for word in note.split()):
        return None
    return produce_of(str(line.get("name") or ""))


def _names(text: str, tokens: tuple[str, ...]) -> bool:
    """True if a folded text names one of the tokens: a word starting or ending with it
    ("Entenbrust", "Osterlamm"; not "Studentenfutter", "Flammkuchen") or a phrase in it."""
    padded = f" {text} "
    words = text.split()
    for token in tokens:
        if " " in token:
            if f" {token} " in padded:
                return True
        elif any(word.startswith(token) or word.endswith(token) for word in words):
            return True
    return False


def _window_fits(window: Window, tags: set[str], name: str, lines: list[str]) -> bool:
    if tags & window.tags:
        return True
    if _names(name, window.names):
        return True
    return bool(window.ingredients) and any(_names(line, window.ingredients) for line in lines)


def _cache(manager: EssensplanerManager) -> dict[tuple, dict[str, Any]]:
    cache = manager.__dict__.get("_season_cache")
    if cache is None or len(cache) > _CACHE_MAX:
        cache = {}
        manager.__dict__["_season_cache"] = cache
    return cache


def recipe_season(
    manager: EssensplanerManager, recipe: dict[str, Any], day: date | None = None
) -> dict[str, Any]:
    """How well a recipe fits the season of a day: {score 0..1, items [produce in season],
    out_of_season [typical seasonal products out of season], windows [ids of the times it
    fits], hints ["🍂 Saison: Kürbis", "🕯️ Adventszeit"]}. Cached per recipe version, month
    and the running times of the year (a copy is returned)."""
    day = day or manager.today()
    windows = active_windows(day)
    key = (recipe.get("id"), recipe.get("updated"), day.month, windows)
    cache = _cache(manager)
    found = cache.get(key)
    if found is None:
        found = _recipe_season(recipe, day, windows)
        cache[key] = found
    return {
        "score": found["score"],
        "items": list(found["items"]),
        "out_of_season": list(found["out_of_season"]),
        "windows": list(found["windows"]),
        "hints": list(found["hints"]),
    }


def _recipe_season(recipe: dict[str, Any], day: date, windows: tuple[str, ...]) -> dict[str, Any]:
    month = day.month
    season = season_of(day)
    in_season: list[Produce] = []
    out: list[Produce] = []
    lines: list[str] = []
    for line in recipe.get("ingredients") or []:
        if not isinstance(line, dict):
            continue
        lines.append(fold(str(line.get("name") or "")))
        produce_id = _line_produce(line)
        if produce_id is None:
            continue
        produce = SEASON_CALENDAR[produce_id]
        target = in_season if month in produce.months else out
        if produce not in target:
            target.append(produce)
    tags = {fold(str(t)) for t in recipe.get("tags") or []}
    name = fold(str(recipe.get("name") or ""))
    fitting = [w for w in windows if _window_fits(WINDOW_MAP[w], tags, name, lines)]
    season_tag = bool(tags & SEASON_TAGS[season])
    strict = sum(1 for p in in_season if p.strict)
    score = 0.5 * strict + 0.25 * (len(in_season) - strict)
    score += 0.5 if fitting else 0.0
    score += 0.3 if season_tag else 0.0
    label, emoji, _ = SEASONS[season]
    # the typical products first ("Kürbis" before "Zwiebeln")
    in_season.sort(key=lambda p: not p.strict)
    hints: list[str] = []
    if in_season:
        hints.append(f"{emoji} Saison: {', '.join(p.label for p in in_season[:MAX_HINT_ITEMS])}")
    elif season_tag:
        hints.append(f"{emoji} {label}")
    hints.extend(f"{WINDOW_MAP[w].emoji} {WINDOW_MAP[w].label}" for w in fitting)
    return {
        "score": round(min(1.0, score), 2),
        "items": tuple(p.label for p in in_season),
        "out_of_season": tuple(p.label for p in out if p.strict),
        "windows": tuple(fitting),
        "hints": tuple(hints),
    }


def season_aware(manager: EssensplanerManager) -> bool:
    """The option "Saison berücksichtigen" (on by default)."""
    return bool(manager.options.get(CONF_SEASON_AWARE, DEFAULT_SEASON_AWARE))


def season_weight(manager: EssensplanerManager, strategy: str | None) -> float:
    """How much the season counts for a planning strategy (0 = not at all): the
    strategy's weight while the option is on; the strategy "seasonal" always counts it."""
    from .economy import strategy_weights

    resolved = strategy if strategy else manager.strategy
    weight = strategy_weights(resolved)[4]
    if resolved == STRATEGY_SEASONAL or season_aware(manager):
        return weight
    return 0.0


def season_factor(
    manager: EssensplanerManager, recipe: dict[str, Any], day: date, weight: float
) -> float:
    """Factor of a suggestion weight: × (1 + weight · score), × OUT_OF_SEASON_FACTOR when
    a typical seasonal product is out of season (1.0 with weight 0)."""
    if weight <= 0:
        return 1.0
    info = recipe_season(manager, recipe, day)
    factor = 1 + weight * info["score"]
    if info["out_of_season"]:
        factor *= OUT_OF_SEASON_FACTOR
    return factor


def suggest_reasons(
    manager: EssensplanerManager,
    recipe: dict[str, Any],
    day: date,
    servings: int | None = None,
    season: bool = True,
    meal: str | None = None,
) -> list[str]:
    """Why a recipe is suggested: ["⭐ Favorit", "🍂 Saison: Kürbis", "🏷️ Angebot: Hack"];
    1.5.1: a liked cuisine ("😋 Italienisch") and a recipe over the day's time limit ("⏱️
    45 min – länger als deine 30 min")."""
    from .profile import CUISINE_NAMES, CUISINES, recipe_cuisines

    reasons: list[str] = []
    if recipe.get("favorite"):
        reasons.append("⭐ Favorit")
    liked = recipe_cuisines(recipe) & manager.profile.cuisines
    if liked:
        first = next(c for c in CUISINES if c in liked)
        reasons.append(f"😋 {CUISINE_NAMES[first].split(' /')[0]}")
    if season:
        reasons.extend(recipe_season(manager, recipe, day)["hints"])
    cost = manager.recipe_cost(recipe, servings, day)
    if cost["on_offer"]:
        offers = ", ".join(o["ingredient"] for o in cost["on_offer"][:2])
        reasons.append(f"🏷️ Angebot: {offers}")
    if slow := manager.time_reason(recipe, day, meal):
        reasons.append(slow)
    return reasons


def recipe_season_export(manager: EssensplanerManager, day: date | None = None) -> dict[str, Any]:
    """The season of every recipe that has one, for the panel's 🍂 badges: {recipe id:
    {score, items, out, hints}} (recipes without a seasonal product, time or tag are left
    out)."""
    day = day or manager.today()
    result: dict[str, Any] = {}
    for recipe_id, recipe in manager.recipes.items():
        info = recipe_season(manager, recipe, day)
        if info["score"] <= 0 and not info["out_of_season"]:
            continue
        result[recipe_id] = {
            "score": info["score"],
            "items": info["items"][:3],
            "out": info["out_of_season"],
            "hints": info["hints"],
        }
    return result


def season_view(
    manager: EssensplanerManager, day: date | None = None, limit: int = 12
) -> dict[str, Any]:
    """season_info() plus the recipes that fit best (score > 0, not excluded, best first):
    recipes [{id, name, image, score, items, windows, hints}] and the recipes with a
    typical product out of season (out_of_season [{id, name, items}])."""
    day = day or manager.today()
    info = season_info(day)
    fitting: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    out: list[dict[str, Any]] = []
    for recipe in manager.recipes.values():
        if manager.is_excluded(recipe):
            continue
        season = recipe_season(manager, recipe, day)
        if season["out_of_season"]:
            out.append(
                {"id": recipe["id"], "name": recipe["name"], "items": season["out_of_season"]}
            )
        if season["score"] > 0 and not season["out_of_season"]:
            fitting.append((season["score"], recipe, season))
    fitting.sort(key=lambda f: (-f[0], fold(f[1]["name"])))
    info["recipes"] = [
        {
            "id": recipe["id"],
            "name": recipe["name"],
            "image": recipe.get("image") or None,
            "score": season["score"],
            "items": season["items"],
            "windows": season["windows"],
            "hints": season["hints"],
        }
        for _, recipe, season in fitting[: max(1, int(limit))]
    ]
    out.sort(key=lambda r: fold(r["name"]))
    info["out_of_season"] = out
    info["season_aware"] = season_aware(manager)
    return info


# ----------------------------------------------------------------------
# Auto plan with AI (feature "season")
# ----------------------------------------------------------------------

AI_TASK_NAME = "Essensplaner Saisonplan"
AI_INSTRUCTIONS = (
    "Du planst die Mahlzeiten einer Woche für einen Haushalt in Deutschland. Denke gründlich "
    "und Schritt für Schritt nach, bevor du antwortest – gib aber nur das JSON aus.\n"
    "1. Für jeden Tag aus 'days' und jede Mahlzeit aus 'meals' wählst du genau ein Rezept "
    "aus 'candidates' – bevorzugt aus den 'candidates' des Tages (die Regeln halten sie an "
    "dem Tag für am besten: Angebote, Budget, Abwechslung, Saison).\n"
    "2. Achte auf Saison ('in_season', 'times', 'season' der Rezepte, 'out_of_season' "
    "meiden), Angebote ('offers'), Kosten ('cost_per_serving', 'budget'), die Planungsart "
    "('strategy'), Favoriten und auf Abwechslung: keine ähnlichen Gerichte (gleiche "
    "Hauptzutat, gleiche Art) an aufeinanderfolgenden Tagen, kein Rezept zweimal.\n"
    "3. Was schon geplant ist ('planned'), nicht noch einmal.\n"
    "4. Verwende nur ids aus 'candidates' und erfinde keine Rezepte.\n"
    "5. Beachte 'profile' (Ernährung, Allergien, Geräte, Lieblingsküchen und -aromen) und "
    "je Tag 'max_minutes' (höchstens so lange Zubereitungszeit 'minutes'); an Tagen mit "
    "'no_cooking' nur Frühstück und Snacks planen.\n"
    'Antworte nur mit JSON: {"plan": [{"date": "JJJJ-MM-TT", "meal": "<id aus meals>", '
    '"id": "<rezept-id>", "reason": "höchstens 10 Wörter"}], "order": ["<id>", …], '
    '"notes": "ein Satz zur Woche"} – "order" sind die übrigen passenden Rezepte, das '
    "passendste zuerst (höchstens 40)."
)
AI_DAY_CANDIDATES = 8  # per day the ids the rules rank best that day
AI_TIMEOUT = 180  # 1.5.1: a whole week (a local model is slow)
AI_PAYLOAD_MAX = 16000
REASON_MAX = 140
NOTES_MAX = 300


def rank_candidates(
    manager: EssensplanerManager,
    start: date,
    days: int,
    meals: list[str],
    tag: str | None = None,
    max_time: int | None = None,
    strategy: str | None = None,
    servings: int | None = None,
    exclude: set[str] | None = None,
    limit: int = CANDIDATES,
) -> list[dict[str, Any]]:
    """The recipes the rules rank best for the days (the weights of the middle day; only
    recipes fitting one of the meals, not excluded): best first, at most limit."""
    around = start + timedelta(days=max(1, days) // 2)
    exclude = exclude or set()
    ctx = manager._suggest_context(around, strategy=strategy, servings=servings)
    scored = []
    for recipe in manager.search_recipes(tag=tag, max_time=max_time):
        if recipe["id"] in exclude or manager.is_excluded(recipe):
            continue
        if not any(manager._fits_meal(recipe, meal) for meal in meals):
            continue
        scored.append((manager._suggest_weight(recipe, ctx), recipe))
    scored.sort(key=lambda s: (-s[0], fold(s[1]["name"])))
    return [recipe for _, recipe in scored[: max(1, limit)]]


def day_candidates(
    manager: EssensplanerManager,
    day: date,
    meals: list[str],
    candidates: list[dict[str, Any]],
    strategy: str | None,
    servings: int | None,
    limit: int = AI_DAY_CANDIDATES,
) -> list[str]:
    """The ids of the candidates the rules rank best on one day (its own weights: budget,
    offers valid that day, the neighbouring days, the season)."""
    ctx = manager._suggest_context(day, strategy=strategy, servings=servings)
    scored = [
        (manager._suggest_weight(r, ctx), r)
        for r in candidates
        if any(manager._fits_meal(r, m) for m in meals)
    ]
    scored.sort(key=lambda s: (-s[0], fold(s[1]["name"])))
    return [r["id"] for _, r in scored[: max(1, limit)]]


def ai_payload(
    manager: EssensplanerManager,
    start: date,
    days: int,
    meals: list[str],
    candidates: list[dict[str, Any]],
    strategy: str | None,
    servings: int | None,
) -> dict[str, Any]:
    """What the AI gets (privacy: recipe ids, names, kinds and tags, products in season,
    offers of the recipes' ingredients, costs, the month, the budget and the strategy – no
    notes). 1.5.1: per day the candidates the rules rank best that day, per candidate why
    (favourite, rating, last cooked, meals it fits) and what is planned around."""
    from .const import MEAL_LABELS
    from .kinds import KIND_LABELS, recipe_kind
    from .options_schema import CHOICE_LABELS_DE
    from .profile import summary_texts

    around = start + timedelta(days=max(1, days) // 2)
    info = season_info(around)
    servings = servings or manager.default_servings
    days_view = []
    for offset in range(max(1, days)):
        day = start + timedelta(days=offset)
        times = [WINDOW_MAP[w].label for w in active_windows(day)]
        entry: dict[str, Any] = {
            "date": day.isoformat(),
            "weekday": WEEKDAY_NAMES[day.weekday()],
            "meals": list(meals),
            "candidates": day_candidates(manager, day, meals, candidates, strategy, servings),
        }
        if times:
            entry["times"] = times
        if day == manager.today():
            entry["today"] = True
        # 1.5.1: the profile's time limit and cooking days
        if limit := manager.time_limit(day):
            entry["max_minutes"] = limit
        if not manager.profile.cooks_on(day):
            entry["no_cooking"] = True
        days_view.append(entry)
    rows = []
    today = manager.today()
    for recipe in candidates:
        cost = manager.recipe_cost(recipe, servings, around)
        season = recipe_season(manager, recipe, around)
        row: dict[str, Any] = {
            "id": recipe["id"],
            "name": recipe["name"],
            "kind": str(KIND_LABELS.get(recipe_kind(recipe), "")),
            "tags": [str(t) for t in (recipe.get("tags") or [])][:6],
            "meals": [m for m in meals if manager._fits_meal(recipe, m)],
        }
        if season["items"] or season["windows"]:
            row["season"] = [
                *season["items"][:3],
                *(WINDOW_MAP[w].label for w in season["windows"]),
            ]
        if season["out_of_season"]:
            row["out_of_season"] = season["out_of_season"]
        if cost["on_offer"]:
            row["offers"] = [o["ingredient"] for o in cost["on_offer"][:3]]
        if cost.get("per_serving"):
            row["cost_per_serving"] = cost["per_serving"]
        if recipe.get("total_time"):
            row["minutes"] = recipe["total_time"]
        if recipe.get("favorite"):
            row["favorite"] = True
        if recipe.get("rating"):
            row["rating"] = recipe["rating"]
        if (ago := _days_ago(today, recipe.get("last_cooked"))) is not None:
            row["cooked_days_ago"] = ago
        rows.append(row)
    planned = []
    for offset in range(-3, max(1, days) + 3):
        day = start + timedelta(days=offset)
        for meal, entry in manager.plan.get(day.isoformat(), {}).items():
            if entry.get("title"):
                planned.append({"date": day.isoformat(), "meal": meal, "name": entry["title"]})
    resolved = strategy or manager.strategy
    payload: dict[str, Any] = {
        "month": info["month_name"],
        "season": info["season"]["label"],
        "in_season": [p["label"] for p in info["produce"]][:15],
        "times": [w["label"] for w in info["windows"]],
        "strategy": CHOICE_LABELS_DE["strategy"].get(resolved, resolved),
        "servings": servings,
        "meals": [{"id": m, "name": MEAL_LABELS.get(m, m)} for m in meals],
        "days": days_view,
        "planned": planned[:30],
        "candidates": rows,
        # 1.5.1: preferences only (no personal data)
        "profile": summary_texts(manager.profile),
    }
    if manager.weekly_budget:
        week = manager.week_overview(around)
        payload["budget"] = {
            "week": manager.weekly_budget,
            "left": week.get("remaining"),
            "per_meal": round(manager.budget_target(around, len(meals)) or 0, 2) or None,
        }
    return payload


def _days_ago(today: date, value: Any) -> int | None:
    if not value:
        return None
    try:
        return (today - date.fromisoformat(str(value)[:10])).days
    except ValueError:
        return None


def parse_ai_order(answer: Any, candidates: list[dict[str, Any]]) -> list[str]:
    """The candidate ids in the AI's order (ids or names; unknown ones are dropped):
    {"order": [...]}, {"plan": [{"id": …}]} or a plain list."""
    by_id = {r["id"]: r["id"] for r in candidates}
    by_name = {fold(r["name"]): r["id"] for r in candidates}
    if isinstance(answer, dict):
        for key in ("order", "plan", "recipes", "ids", "ranking"):
            if isinstance(answer.get(key), list):
                answer = answer[key]
                break
        else:
            answer = []
    if not isinstance(answer, list):
        return []
    order: list[str] = []
    for value in answer:
        if isinstance(value, dict):
            value = value.get("id") or value.get("recipe_id") or value.get("name")
        if not isinstance(value, (str, int)):
            continue
        text = str(value).strip()
        found = by_id.get(text) or by_name.get(fold(text))
        if found and found not in order:
            order.append(found)
    return order


def parse_ai_plan(
    manager: EssensplanerManager,
    answer: Any,
    candidates: list[dict[str, Any]],
    start: date,
    days: int,
    meals: list[str],
) -> dict[tuple[str, str], dict[str, str]]:
    """The AI's picks per slot (1.5.1), checked: a day of the request, one of its meals
    (id or name), a candidate (id or name) that fits the meal, each recipe once.
    {(date, meal): {id, reason}}."""
    from .const import MEAL_LABELS

    rows = answer.get("plan") if isinstance(answer, dict) else None
    if not isinstance(rows, list):
        return {}
    by_id = {r["id"]: r for r in candidates}
    by_name = {fold(r["name"]): r for r in candidates}
    meal_of = {fold(m): m for m in meals} | {fold(MEAL_LABELS.get(m, m)): m for m in meals}
    first, last = start.isoformat(), (start + timedelta(days=max(1, days) - 1)).isoformat()
    picks: dict[tuple[str, str], dict[str, str]] = {}
    used: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        day = str(row.get("date") or "")[:10]
        meal = meal_of.get(fold(str(row.get("meal") or "")))
        if len(meals) == 1 and meal is None and not row.get("meal"):
            meal = meals[0]
        value = str(row.get("id") or row.get("recipe_id") or row.get("name") or "").strip()
        recipe = by_id.get(value) or by_name.get(fold(value))
        if (
            not first <= day <= last
            or meal is None
            or recipe is None
            or recipe["id"] in used
            or (day, meal) in picks
            or not manager._fits_meal(recipe, meal)
        ):
            continue
        used.add(recipe["id"])
        reason = " ".join(str(row.get("reason") or row.get("grund") or "").split())
        picks[(day, meal)] = {"id": recipe["id"], "reason": reason[:REASON_MAX]}
    return picks


async def async_ai_plan(
    hass: HomeAssistant,
    manager: EssensplanerManager,
    start: date,
    days: int,
    meals: list[str],
    tag: str | None = None,
    max_time: int | None = None,
    strategy: str | None = None,
    servings: int | None = None,
    exclude: set[str] | None = None,
) -> tuple[list[str], dict[tuple[str, str], dict[str, str]], str]:
    """The AI's plan (feature "season", AI_TIMEOUT seconds): (the candidate order –
    completed with the remaining candidates in the rules' order –, its picks per slot
    (parse_ai_plan()), its note). Raises the ai_* errors (ai_invalid without one known
    id)."""
    from .ai import _error, async_ai_json  # the AI module imports the manager

    candidates = rank_candidates(
        manager, start, days, meals, tag, max_time, strategy, servings, exclude
    )
    if not candidates:
        return [], {}, ""
    answer = await async_ai_json(
        hass,
        manager,
        AI_FEATURE_SEASON,
        AI_TASK_NAME,
        AI_INSTRUCTIONS,
        ai_payload(manager, start, days, meals, candidates, strategy, servings),
        timeout=AI_TIMEOUT,
        limit=AI_PAYLOAD_MAX,
    )
    picks = parse_ai_plan(manager, answer, candidates, start, days, meals)
    order = parse_ai_order(answer, candidates)
    for pick in picks.values():
        if pick["id"] not in order:
            order.append(pick["id"])
    if not order:
        from .ai import ai_entity

        raise _error("ai_invalid", entity=ai_entity(manager, AI_FEATURE_SEASON) or "")
    note = ""
    if isinstance(answer, dict):
        note = " ".join(str(answer.get("notes") or answer.get("notiz") or "").split())
    return (
        [*order, *(r["id"] for r in candidates if r["id"] not in order)],
        picks,
        note[:NOTES_MAX],
    )


async def async_auto_plan(
    hass: HomeAssistant,
    manager: EssensplanerManager,
    start: date,
    days: int,
    meals: list[str] | None = None,
    tag: str | None = None,
    max_time: int | None = None,
    overwrite: bool = False,
    servings: int | None = None,
    strategy: str | None = None,
    ai: bool = False,
) -> dict[str, Any]:
    """Fill the free slots (manager.auto_plan()); with ai the AI plans the days from the
    rules' best candidates (its picks per slot, then its order) – a failing AI plans with
    the rules alone (ai {ok: false, code, error}). {planned [plan entries + reasons and
    cost], ai: None | {ok, code?, error?, notes?}}."""
    from homeassistant.exceptions import HomeAssistantError

    meals = meals or [manager.default_meal]
    order: list[str] | None = None
    picks: dict[tuple[str, str], dict[str, str]] = {}
    ai_result: dict[str, Any] | None = None
    if ai:
        try:
            nearby = _nearby(manager, start, days, meals, overwrite)
            order, picks, note = await async_ai_plan(
                hass, manager, start, days, meals, tag, max_time, strategy, servings, nearby
            )
            ai_result = {"ok": True}
            if note:
                ai_result["notes"] = note
        except HomeAssistantError as err:
            from .occasions import _ai_failure

            ai_result = _ai_failure(err)
    planned = manager.auto_plan(
        start,
        days,
        meals=meals,
        tag=tag,
        max_time=max_time,
        overwrite=overwrite,
        servings=servings,
        strategy=strategy,
        order=order,
        picks={slot: pick["id"] for slot, pick in picks.items()} or None,
    )
    for entry in planned:
        add_reasons(manager, entry, servings, strategy)
        pick = picks.get((entry["date"], entry["meal"]))
        if pick and pick["id"] == entry.get("recipe_id"):
            entry["reasons"].insert(0, f"🤖 {pick['reason']}" if pick["reason"] else "🤖 KI")
    return {"planned": planned, "ai": ai_result}


def add_reasons(
    manager: EssensplanerManager,
    entry: dict[str, Any],
    servings: int | None = None,
    strategy: str | None = None,
) -> dict[str, Any]:
    """Why a planned entry (favourite, season, offers) and its cost (1.5.1: the auto plan's
    rows show it and the week's total)."""
    day = date.fromisoformat(entry["date"])
    recipe = manager.recipes.get(entry.get("recipe_id") or "")
    entry["reasons"] = []
    if isinstance(entry.get("leftover_of"), dict):
        # 1.5.1: a day without cooking gets the leftovers of the cooking day before
        entry["reasons"] = ["🍲 Kein Kochtag – Reste mitkochen"]
    elif recipe is not None:
        entry["reasons"] = suggest_reasons(
            manager,
            recipe,
            day,
            servings or entry.get("servings") or manager.default_servings,
            season=season_weight(manager, strategy) > 0,
            meal=entry.get("meal"),
        )
    stored = manager.plan.get(entry["date"], {}).get(entry["meal"])
    cost = manager.entry_cost(day, entry["meal"], stored) if stored else None
    entry["cost"] = cost["total"] if cost else None
    return entry


def _nearby(
    manager: EssensplanerManager, start: date, days: int, meals: list[str], overwrite: bool
) -> set[str]:
    """Recipes planned around the days (not offered to the AI a second time)."""
    nearby: set[str] = set()
    for offset in range(-6, max(1, days) + 6):
        day = start + timedelta(days=offset)
        for meal, entry in manager.plan.get(day.isoformat(), {}).items():
            replaced = overwrite and 0 <= offset < max(1, days) and meal in meals
            if entry.get("recipe_id") and not replaced:
                nearby.add(entry["recipe_id"])
    return nearby
