"""Natural language (German/English) date and meal parsing."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import re

from .const import ALL_MEALS, MEAL_BREAKFAST, MEAL_DINNER, MEAL_LABELS, MEAL_LUNCH, MEAL_SNACK
from .ingredients import fold

WEEKDAYS = {
    "montag": 0,
    "mo": 0,
    "monday": 0,
    "dienstag": 1,
    "di": 1,
    "tuesday": 1,
    "mittwoch": 2,
    "mi": 2,
    "wednesday": 2,
    "donnerstag": 3,
    "do": 3,
    "thursday": 3,
    "freitag": 4,
    "fr": 4,
    "friday": 4,
    "samstag": 5,
    "sa": 5,
    "sonnabend": 5,
    "saturday": 5,
    "sonntag": 6,
    "so": 6,
    "sunday": 6,
}

WEEKDAY_NAMES = [
    "Montag",
    "Dienstag",
    "Mittwoch",
    "Donnerstag",
    "Freitag",
    "Samstag",
    "Sonntag",
]

# folded alias -> meal
MEAL_ALIASES: dict[str, str] = {
    "fruehstueck": MEAL_BREAKFAST,
    "frueh": MEAL_BREAKFAST,
    "morgens": MEAL_BREAKFAST,
    "breakfast": MEAL_BREAKFAST,
    "brunch": MEAL_BREAKFAST,
    "mittag": MEAL_LUNCH,
    "mittags": MEAL_LUNCH,
    "mittagessen": MEAL_LUNCH,
    "lunch": MEAL_LUNCH,
    "abend": MEAL_DINNER,
    "abends": MEAL_DINNER,
    "abendessen": MEAL_DINNER,
    "abendbrot": MEAL_DINNER,
    "nachtessen": MEAL_DINNER,
    "dinner": MEAL_DINNER,
    "supper": MEAL_DINNER,
    "heute abend": MEAL_DINNER,
    "snack": MEAL_SNACK,
    "snacks": MEAL_SNACK,
    "zwischenmahlzeit": MEAL_SNACK,
    "nachmittag": MEAL_SNACK,
    "nachmittags": MEAL_SNACK,
    "kaffee": MEAL_SNACK,
    "kaffee und kuchen": MEAL_SNACK,
    "vesper": MEAL_SNACK,
    "jause": MEAL_SNACK,
}
for _meal in ALL_MEALS:
    MEAL_ALIASES[_meal] = _meal
    MEAL_ALIASES[fold(MEAL_LABELS[_meal])] = _meal

_FILLER = {
    "am",
    "an",
    "den",
    "dem",
    "der",
    "die",
    "das",
    "zum",
    "zur",
    "zu",
    "fuer",
    "for",
    "on",
    "the",
    "this",
    "diesen",
    "diese",
    "dieses",
    "diesem",
    "essen",
    "es",
    "gibt",
    "um",
    "im",
    "in",
}

_ISO_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_DE_RE = re.compile(r"(\d{1,2})\.\s*(\d{1,2})\.?(?:\s*(\d{2,4}))?")
_IN_DAYS_RE = re.compile(r"in (\d+|einem|zwei|drei|vier|fuenf|sechs|sieben) tag(?:en)?")
_NUMBER_WORDS = {
    "einem": 1,
    "zwei": 2,
    "drei": 3,
    "vier": 4,
    "fuenf": 5,
    "sechs": 6,
    "sieben": 7,
}


class DateParseError(ValueError):
    """Raised when a date could not be understood."""


def parse_meal(text: str | None) -> str | None:
    """Return the meal slot for a text like 'Abendessen' / 'mittags'."""
    if not text:
        return None
    folded = fold(str(text))
    if folded in MEAL_ALIASES:
        return MEAL_ALIASES[folded]
    for token in reversed(folded.split()):
        if token in MEAL_ALIASES:
            return MEAL_ALIASES[token]
    return None


def parse_date(text: str | date | datetime | None, today: date) -> tuple[date, str | None]:
    """Parse a date expression. Returns (date, meal hint)."""
    if text is None:
        return today, None
    if isinstance(text, datetime):
        return text.date(), None
    if isinstance(text, date):
        return text, None

    raw = str(text).strip()
    if not raw:
        return today, None

    if match := _ISO_RE.search(raw):
        try:
            return (
                date(int(match.group(1)), int(match.group(2)), int(match.group(3))),
                parse_meal(raw[match.end() :]),
            )
        except ValueError as err:
            raise DateParseError(raw) from err

    if match := _DE_RE.search(raw):
        day, month = int(match.group(1)), int(match.group(2))
        year_text = match.group(3)
        try:
            if year_text:
                year = int(year_text)
                if year < 100:
                    year += 2000
                result = date(year, month, day)
            else:
                result = date(today.year, month, day)
                if result < today - timedelta(days=60):
                    result = date(today.year + 1, month, day)
        except ValueError as err:
            raise DateParseError(raw) from err
        return result, parse_meal(raw[match.end() :])

    folded = fold(raw)
    tokens = folded.split()
    meal_hint: str | None = None

    # "morgen früh" -> tomorrow breakfast, "heute abend" -> today dinner
    for token in tokens:
        if token in ("frueh", "morgens"):
            meal_hint = MEAL_BREAKFAST
        elif token in MEAL_ALIASES and token not in ("kaffee",):
            meal_hint = MEAL_ALIASES[token]

    if match := _IN_DAYS_RE.search(folded):
        value = match.group(1)
        days = int(value) if value.isdigit() else _NUMBER_WORDS[value]
        return today + timedelta(days=days), meal_hint

    is_today = any(t in ("heute", "heut", "today", "tonight") for t in tokens)
    if "uebermorgen" in tokens:
        return today + timedelta(days=2), meal_hint
    if "vorgestern" in tokens:
        return today - timedelta(days=2), meal_hint
    if "gestern" in tokens or "yesterday" in tokens:
        if "morgen" in tokens:  # "gestern morgen" = yesterday morning
            meal_hint = meal_hint or MEAL_BREAKFAST
        return today - timedelta(days=1), meal_hint
    if is_today:
        if "morgen" in tokens:  # "heute morgen" = this morning
            meal_hint = meal_hint or MEAL_BREAKFAST
        return today, meal_hint or (MEAL_DINNER if "tonight" in tokens else None)
    if "morgen" in tokens or "tomorrow" in tokens:
        return today + timedelta(days=1), meal_hint

    next_week = any(
        t in ("naechsten", "naechste", "naechster", "kommenden", "kommende", "next") for t in tokens
    )
    for token in tokens:
        if token not in WEEKDAYS:
            continue
        if len(token) == 2 and len(tokens) > 2:
            # Abbreviations like "do"/"so" are only accepted on their own.
            continue
        target = WEEKDAYS[token]
        delta = (target - today.weekday()) % 7
        if next_week:
            if "woche" in tokens:
                # "nächste Woche Mittwoch" -> Wednesday of next calendar week
                delta = (week_start(today) + timedelta(days=7 + target) - today).days
            elif delta == 0:
                delta = 7
        return today + timedelta(days=delta), meal_hint
    if next_week and ("woche" in tokens or "week" in tokens):
        return week_start(today) + timedelta(days=7), meal_hint
    if "woche" in tokens or "week" in tokens:
        return today, meal_hint
    if "wochenende" in tokens or "weekend" in tokens:
        delta = (5 - today.weekday()) % 7
        return today + timedelta(days=delta), meal_hint

    meaningful = [t for t in tokens if t not in _FILLER and t not in MEAL_ALIASES]
    if not meaningful:
        return today, meal_hint
    raise DateParseError(raw)


def week_start(day: date) -> date:
    """Return the Monday of the week of the given day."""
    return day - timedelta(days=day.weekday())


def describe_date(day: date, today: date) -> str:
    """Return a German description of a date relative to today."""
    delta = (day - today).days
    if delta == 0:
        return "heute"
    if delta == 1:
        return "morgen"
    if delta == 2:
        return "übermorgen"
    if delta == -1:
        return "gestern"
    weekday = WEEKDAY_NAMES[day.weekday()]
    if 0 < delta < 7:
        return f"am {weekday}"
    return f"am {weekday}, {day.day}.{day.month}."
