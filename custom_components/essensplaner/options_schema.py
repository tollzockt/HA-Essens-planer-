"""Option keys, defaults, ranges and validation of the Essensplaner settings (1.4, 1.5).

The settings are changed in the panel's own settings view (⚙️, websockets
essensplaner/get_settings and essensplaner/save_settings). This module holds their rules:
what a value may be, how it is stored and which German message an invalid value gets.
Home Assistant's options flow (Einstellungen → Geräte & Dienste → Essensplaner →
Konfigurieren) only toggles the sidebar panel (show_panel) since 1.4; the setup flow takes
the servings range from here. 1.5 adds the section "ai" (AI entity and features via Home
Assistant) and the planning / offers switches of season, occasions, drinks and leaflets.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any

from .branches import RADIUS_KM_RANGE, ROUTE_RADIUS_RANGE
from .const import (
    AI_FEATURES,
    ALL_MEALS,
    CONF_AI_ENTITY,
    CONF_AI_FEATURES,
    CONF_ALDI_ONLINE,
    CONF_ALL_LEAFLETS,
    CONF_AUTO_COOKED,
    CONF_BRANCH_RADIUS,
    CONF_BRANCH_ROUTE,
    CONF_BRANCH_ROUTE_RADIUS,
    CONF_BRANCH_ZONES,
    CONF_BUDGET,
    CONF_DEFAULT_MEAL,
    CONF_DEFAULT_SERVINGS,
    CONF_DRINKS_ALCOHOL,
    CONF_EDEKA_OFFERS,
    CONF_ENABLED_MEALS,
    CONF_EXCLUDED,
    CONF_MEAL_TIME_PREFIX,
    CONF_OCCASIONS_IN_BUDGET,
    CONF_OFFERS_SOURCE,
    CONF_PANTRY,
    CONF_RECEIPT_AI,
    CONF_REGISTER_INTENTS,
    CONF_REWE_ONLINE,
    CONF_SEASON_AWARE,
    CONF_SHOW_PANEL,
    CONF_SPLIT_MIN_PERCENT,
    CONF_SPLIT_MIN_SAVING,
    CONF_SPLIT_MODE,
    CONF_SPLIT_OFFER_MIN,
    CONF_SPLIT_TRIP_MIN,
    CONF_STORES,
    CONF_STRATEGY,
    CONF_SYNC_TODO,
    CONF_WATCHLIST,
    CONF_ZIP,
    DEFAULT_AI_FEATURES,
    DEFAULT_ALDI_ONLINE,
    DEFAULT_ALL_LEAFLETS,
    DEFAULT_BRANCH_RADIUS,
    DEFAULT_BRANCH_ROUTE,
    DEFAULT_BRANCH_ROUTE_RADIUS,
    DEFAULT_DRINKS_ALCOHOL,
    DEFAULT_EDEKA_OFFERS,
    DEFAULT_ENABLED_MEALS,
    DEFAULT_MEAL,
    DEFAULT_MEAL_TIMES,
    DEFAULT_OCCASIONS_IN_BUDGET,
    DEFAULT_PANTRY,
    DEFAULT_REWE_ONLINE,
    DEFAULT_SEASON_AWARE,
    DEFAULT_SERVINGS,
    DEFAULT_SPLIT_MIN_PERCENT,
    DEFAULT_SPLIT_MIN_SAVING,
    DEFAULT_SPLIT_MODE,
    DEFAULT_SPLIT_OFFER_MIN,
    DEFAULT_SPLIT_TRIP_MIN,
    MEAL_LABELS,
    OFFERS_MARKTGURU,
    OFFERS_OFF,
    SPLIT_MODES,
    STRATEGIES,
    STRATEGY_BALANCED,
)
from .retailers import DEFAULT_STORES, STORES, retailer_kind

# ----------------------------------------------------------------------------------
# Ranges (the setup flow's servings selector uses the same numbers)
# ----------------------------------------------------------------------------------
SERVINGS_RANGE = (1, 20)
BUDGET_RANGE = (0, 2000)
EUR_MAX = 20  # store_split_min_saving / store_split_offer_min
TRIP_MAX = 50  # store_split_trip_min
PERCENT_MAX = 90  # store_split_min_percent
RADIUS_KM = RADIUS_KM_RANGE
ROUTE_RADIUS_M = ROUTE_RADIUS_RANGE
TEXT_MAX = 2000  # pantry, excluded ingredients, watchlist

OFFERS_SOURCES = [OFFERS_OFF, OFFERS_MARKTGURU]

# sections of the panel's settings view (in this order)
SECTION_GENERAL = "general"
SECTION_PLANNING = "planning"
SECTION_OFFERS = "offers"
SECTION_STORES = "stores"
SECTION_RECEIPTS = "receipts"
SECTION_AI = "ai"
SECTIONS = [
    SECTION_GENERAL,
    SECTION_PLANNING,
    SECTION_OFFERS,
    SECTION_STORES,
    SECTION_RECEIPTS,
    SECTION_AI,
]

# entity domains of the AI picker (an AI Task or a conversation agent, 1.5)
AI_DOMAINS = ("ai_task", "conversation")

# value kinds
INT = "int"
FLOAT = "float"
BOOL = "bool"
SELECT = "select"
MULTI = "multi"
TEXT = "text"
TEXTAREA = "textarea"
TIME = "time"
ENTITY = "entity"
ENTITIES = "entities"


@dataclass(frozen=True)
class Field:
    """One option: where the panel shows it, its kind, default and limits."""

    key: str
    section: str
    kind: str
    default: Any
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    choices: tuple[str, ...] | None = None
    domain: str | None = None  # entity / entities: one domain (1.4 style)
    optional: bool = False  # removed from the options when empty (entity pickers)
    domains: tuple[str, ...] | None = None  # entity / entities: several domains (1.5)
    empty_ok: bool = False  # multi: an empty selection is a value (not "the default")

    @property
    def entity_domains(self) -> tuple[str, ...]:
        """The domains an entity of this field may have (domains, else domain)."""
        if self.domains:
            return tuple(self.domains)
        return (self.domain,) if self.domain else ()

    def describe(self) -> dict[str, Any]:
        """The field for the panel (type, limits, section; entity fields: domain = the first
        allowed domain as in 1.4, domains = all of them)."""
        info: dict[str, Any] = {"section": self.section, "type": self.kind}
        for name, value in (("min", self.minimum), ("max", self.maximum), ("step", self.step)):
            if value is not None:
                info[name] = value
        if domains := self.entity_domains:
            info["domain"] = domains[0]
            info["domains"] = list(domains)
        if self.optional:
            info["optional"] = True
        return info


def _time_key(meal: str) -> str:
    return f"{CONF_MEAL_TIME_PREFIX}{meal}"


FIELDS: tuple[Field, ...] = (
    # Allgemein
    Field(CONF_DEFAULT_SERVINGS, SECTION_GENERAL, INT, DEFAULT_SERVINGS, *SERVINGS_RANGE, 1),
    Field(CONF_DEFAULT_MEAL, SECTION_GENERAL, SELECT, DEFAULT_MEAL, choices=tuple(ALL_MEALS)),
    Field(
        CONF_ENABLED_MEALS,
        SECTION_GENERAL,
        MULTI,
        list(DEFAULT_ENABLED_MEALS),
        choices=tuple(ALL_MEALS),
    ),
    *(
        Field(_time_key(meal), SECTION_GENERAL, TIME, DEFAULT_MEAL_TIMES[meal])
        for meal in ALL_MEALS
    ),
    Field(CONF_PANTRY, SECTION_GENERAL, TEXTAREA, DEFAULT_PANTRY, maximum=TEXT_MAX),
    Field(CONF_EXCLUDED, SECTION_GENERAL, TEXT, "", maximum=TEXT_MAX),
    Field(CONF_AUTO_COOKED, SECTION_GENERAL, BOOL, True),
    Field(CONF_SYNC_TODO, SECTION_GENERAL, ENTITY, None, domain="todo", optional=True),
    Field(CONF_REGISTER_INTENTS, SECTION_GENERAL, BOOL, True),
    Field(CONF_SHOW_PANEL, SECTION_GENERAL, BOOL, True),
    # Budget & Planung
    Field(CONF_BUDGET, SECTION_PLANNING, FLOAT, 0.0, *BUDGET_RANGE, 5),
    Field(CONF_STRATEGY, SECTION_PLANNING, SELECT, STRATEGY_BALANCED, choices=tuple(STRATEGIES)),
    Field(CONF_SEASON_AWARE, SECTION_PLANNING, BOOL, DEFAULT_SEASON_AWARE),
    Field(CONF_OCCASIONS_IN_BUDGET, SECTION_PLANNING, BOOL, DEFAULT_OCCASIONS_IN_BUDGET),
    Field(CONF_DRINKS_ALCOHOL, SECTION_PLANNING, BOOL, DEFAULT_DRINKS_ALCOHOL),
    # Angebote & Preisquellen
    Field(CONF_OFFERS_SOURCE, SECTION_OFFERS, SELECT, OFFERS_OFF, choices=tuple(OFFERS_SOURCES)),
    Field(CONF_ZIP, SECTION_OFFERS, TEXT, ""),
    Field(CONF_STORES, SECTION_OFFERS, MULTI, list(DEFAULT_STORES), choices=tuple(STORES)),
    Field(CONF_WATCHLIST, SECTION_OFFERS, TEXT, "", maximum=TEXT_MAX),
    Field(CONF_REWE_ONLINE, SECTION_OFFERS, BOOL, DEFAULT_REWE_ONLINE),
    Field(CONF_ALDI_ONLINE, SECTION_OFFERS, BOOL, DEFAULT_ALDI_ONLINE),
    Field(CONF_EDEKA_OFFERS, SECTION_OFFERS, BOOL, DEFAULT_EDEKA_OFFERS),
    Field(CONF_ALL_LEAFLETS, SECTION_OFFERS, BOOL, DEFAULT_ALL_LEAFLETS),
    # Läden & Einkauf
    Field(CONF_SPLIT_MODE, SECTION_STORES, SELECT, DEFAULT_SPLIT_MODE, choices=tuple(SPLIT_MODES)),
    Field(CONF_SPLIT_MIN_SAVING, SECTION_STORES, FLOAT, DEFAULT_SPLIT_MIN_SAVING, 0, EUR_MAX, 0.1),
    Field(
        CONF_SPLIT_MIN_PERCENT, SECTION_STORES, INT, DEFAULT_SPLIT_MIN_PERCENT, 0, PERCENT_MAX, 1
    ),
    Field(CONF_SPLIT_OFFER_MIN, SECTION_STORES, FLOAT, DEFAULT_SPLIT_OFFER_MIN, 0, EUR_MAX, 0.05),
    Field(CONF_SPLIT_TRIP_MIN, SECTION_STORES, FLOAT, DEFAULT_SPLIT_TRIP_MIN, 0, TRIP_MAX, 0.5),
    Field(CONF_BRANCH_ZONES, SECTION_STORES, ENTITIES, [], domain="zone"),
    Field(CONF_BRANCH_RADIUS, SECTION_STORES, FLOAT, DEFAULT_BRANCH_RADIUS, *RADIUS_KM, 0.5),
    Field(CONF_BRANCH_ROUTE, SECTION_STORES, BOOL, DEFAULT_BRANCH_ROUTE),
    Field(
        CONF_BRANCH_ROUTE_RADIUS,
        SECTION_STORES,
        INT,
        DEFAULT_BRANCH_ROUTE_RADIUS,
        *ROUTE_RADIUS_M,
        50,
    ),
    # Kassenzettel (photos: an AI Task; empty = the AI entity of "KI" if it is an AI Task)
    Field(CONF_RECEIPT_AI, SECTION_RECEIPTS, ENTITY, None, domain="ai_task", optional=True),
    # KI (1.5): an AI Task or a conversation agent of Home Assistant, and what it is used for
    Field(CONF_AI_ENTITY, SECTION_AI, ENTITY, None, domains=AI_DOMAINS, optional=True),
    Field(
        CONF_AI_FEATURES,
        SECTION_AI,
        MULTI,
        list(DEFAULT_AI_FEATURES),
        choices=tuple(AI_FEATURES),
        empty_ok=True,
    ),
)
FIELD_MAP: dict[str, Field] = {f.key: f for f in FIELDS}

# German labels of the choices (meal and strategy: the same texts as the selectors in
# translations/de.json, which services.yaml uses)
CHOICE_LABELS_DE: dict[str, dict[str, str]] = {
    "meal": dict(MEAL_LABELS),
    "strategy": {
        "balanced": "Ausgewogen",
        "cheap": "Günstig (Budget)",
        "offers": "Angebote nutzen",
        "variety": "Abwechslung",
        "seasonal": "Saisonal",
    },
    "split_mode": {
        "off": "Aus – eine Liste wie bisher",
        "main_only": "Alles im Hauptladen",
        "main_exceptions": "Hauptladen + Ausnahmen (empfohlen)",
    },
    "offers_source": {
        "off": "Aus (nur eigene Angebote)",
        "marktguru": "marktguru.de (inoffiziell, eigenes Risiko)",
    },
    "ai_feature": {
        "occasions": "Anlässe (Menü-Vorschläge)",
        "drinks": "Getränke",
        "season": "Saisonplan (Auto-Plan „mit KI“)",
        "products": "Artikel sortieren (Knopf + wöchentlich)",
        "recipes": "Rezepte sortieren (Knopf + wöchentlich)",
        "receipts": "Kassenzettel-Fotos",
    },
}

# The marktguru warning (user decision 2026-11-07: shown wherever it can be switched on)
MARKTGURU_WARNING_DE = (
    "marktguru untersagt laut AGB das automatische Auslesen – Nutzung auf eigenes Risiko, "
    "nur privat."
)

# German messages of the validation (shown at the field in the panel's settings view)
ERROR_TEXTS_DE: dict[str, str] = {
    "no_meals": "Bitte mindestens eine Mahlzeit auswählen.",
    "invalid_zip": (
        "Bitte eine 5-stellige Postleitzahl eingeben oder im Essensplaner-Panel eine Filiale "
        "mit Postleitzahl hinzufügen."
    ),
    "required": "Bitte einen Wert angeben.",
    "invalid_number": "Bitte eine Zahl eingeben.",
    "out_of_range": "Bitte einen Wert von {min} bis {max} eingeben.",
    "invalid_choice": "Bitte einen der angebotenen Werte wählen.",
    "invalid_time": "Bitte eine Uhrzeit wie 18:30 eingeben.",
    "invalid_entity": "Bitte eine Entität der Art „{domain}“ wählen.",
    "invalid_ai_entity": "Bitte eine KI-Aufgabe (ai_task) oder einen Gesprächsagenten wählen.",
    "too_long": "Höchstens {max} Zeichen.",
    "invalid_type": "Ungültiger Wert.",
}

_ZIP_RE = re.compile(r"\d{5}")
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?$")
_ENTITY_RE = re.compile(r"^(?P<domain>[a-z0-9_]+)\.[a-z0-9_]+$")


# ----------------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------------


def normalize_time(value: Any) -> str:
    """ "07:30:00" -> "07:30" (the stored form); shorter text stays as it is."""
    text = str(value or "")
    return text[:5] if len(text) >= 5 else text


def number(value: Any, default: float) -> float:
    """An option as a number (the default for missing or broken values)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def whole(value: float) -> float | int:
    """3.0 -> 3 (nicer in the stored options), 2.5 stays 2.5."""
    return int(value) if float(value).is_integer() else round(float(value), 2)


def clamp(value: Any, default: float, minimum: float, maximum: float) -> float:
    """A stored number inside its range (a broken value gives the default)."""
    return min(max(number(value, default), minimum), maximum)


def zone_list(value: Any) -> list[str]:
    """The branch zones as a list (1.3 also stored a comma separated text)."""
    if isinstance(value, str):
        return [z.strip() for z in value.split(",") if z.strip()]
    if isinstance(value, (list, tuple)):
        return [str(z) for z in value if z]
    return []


def meals_error(meals: Any) -> str | None:
    """ "no_meals" when no meal is enabled."""
    return None if meals else "no_meals"


def zip_error(offers_source: Any, zip_code: Any, branch_postcodes: Sequence[str]) -> str | None:
    """ "invalid_zip" when marktguru is on and the postcode is wrong, or missing without a
    selected branch that has one."""
    if offers_source != OFFERS_MARKTGURU:
        return None
    text = str(zip_code or "").strip()
    if text and not _ZIP_RE.fullmatch(text):
        return "invalid_zip"
    if not text and not branch_postcodes:
        return "invalid_zip"
    return None


def error_text(code: str, field: Field | None = None) -> str:
    """The German message of a validation code for a field."""
    text = ERROR_TEXTS_DE.get(code) or ERROR_TEXTS_DE["invalid_type"]
    if field is None:
        return text
    return text.format(
        min=_fmt(field.minimum),
        max=_fmt(field.maximum),
        domain=" / ".join(field.entity_domains),
    )


def _fmt(value: float | None) -> str:
    if value is None:
        return ""
    return str(whole(value)).replace(".", ",")


# ----------------------------------------------------------------------------------
# Current values, defaults, validation
# ----------------------------------------------------------------------------------


def default_values() -> dict[str, Any]:
    """The defaults of all settings (what a new installation uses)."""
    return {f.key: _copy(f.default) for f in FIELDS}


def _copy(value: Any) -> Any:
    return list(value) if isinstance(value, list) else value


def current_values(options: Mapping[str, Any]) -> dict[str, Any]:
    """The settings as the panel shows them: stored value, else the default; numbers
    inside their ranges, times as "HH:MM", zones as a list."""
    values: dict[str, Any] = {}
    for f in FIELDS:
        raw = options.get(f.key)
        if f.kind in (INT, FLOAT):
            if f.key == CONF_BUDGET:
                value: Any = number(raw or 0, 0)
            else:
                value = clamp(raw, f.default, f.minimum or 0, f.maximum or 0)
            value = whole(value) if f.kind == FLOAT else round(value)
        elif f.kind == BOOL:
            value = bool(raw) if raw is not None else bool(f.default)
        elif f.kind == SELECT:
            value = raw if raw in (f.choices or ()) else f.default
        elif f.kind == MULTI:
            # unknown ids (an old chain) are left out, so they never block saving; an empty
            # list is the default unless the field allows an empty selection (ai_features)
            chosen = raw if f.empty_ok and isinstance(raw, (list, tuple)) else (raw or f.default)
            value = [v for v in chosen if v in (f.choices or ())]
        elif f.kind == TIME:
            value = normalize_time(raw) or f.default
        elif f.kind == ENTITIES:
            value = zone_list(raw)
        elif f.kind == ENTITY:
            value = str(raw) if raw else None
        else:  # text
            value = str(raw if raw is not None else f.default)
        values[f.key] = value
    return values


def _clean_number(f: Field, raw: Any) -> tuple[Any, str | None]:
    if isinstance(raw, bool) or raw is None or (isinstance(raw, str) and not raw.strip()):
        return None, "required" if f.key != CONF_BUDGET else None
    try:
        value = float(str(raw).replace(",", ".")) if isinstance(raw, str) else float(raw)
    except (TypeError, ValueError):
        return None, "invalid_number"
    if value != value or value in (float("inf"), float("-inf")):  # NaN / inf
        return None, "invalid_number"
    if f.minimum is not None and value < f.minimum:
        return None, "out_of_range"
    if f.maximum is not None and value > f.maximum:
        return None, "out_of_range"
    if f.kind == INT:
        return round(value), None
    return whole(value), None


def _clean_entity(f: Field, raw: Any) -> tuple[Any, str | None]:
    if raw in (None, ""):
        return None, None
    match = _ENTITY_RE.match(str(raw))
    if not isinstance(raw, str) or match is None or match["domain"] not in f.entity_domains:
        if f.entity_domains == AI_DOMAINS:
            return None, "invalid_ai_entity"
        return None, "invalid_entity"
    return raw, None


def clean_value(f: Field, raw: Any) -> tuple[Any, str | None]:
    """(stored value, error code) of one setting."""
    if f.kind in (INT, FLOAT):
        value, error = _clean_number(f, raw)
        if f.key == CONF_BUDGET and value is None and error is None:
            return 0.0, None  # empty budget = no budget
        if f.key == CONF_BUDGET and value is not None:
            return float(value), None  # the flow stores the budget as a float
        return value, error
    if f.kind == BOOL:
        return (raw, None) if isinstance(raw, bool) else (None, "invalid_type")
    if f.kind == SELECT:
        return (raw, None) if raw in (f.choices or ()) else (None, "invalid_choice")
    if f.kind == MULTI:
        if not isinstance(raw, (list, tuple)) or not all(isinstance(v, str) for v in raw):
            return None, "invalid_type"
        if any(v not in (f.choices or ()) for v in raw):
            return None, "invalid_choice"
        return list(dict.fromkeys(raw)), None
    if f.kind == TIME:
        match = _TIME_RE.match(str(raw or "").strip())
        if match is None:
            return None, "invalid_time"
        return f"{int(match[1]):02d}:{match[2]}", None
    if f.kind == ENTITY:
        return _clean_entity(f, raw)
    if f.kind == ENTITIES:
        if raw in (None, ""):
            return [], None
        if not isinstance(raw, (list, tuple)):
            return None, "invalid_type"
        cleaned = []
        for item in raw:
            value, error = _clean_entity(f, item)
            if error:
                return None, error
            if value and value not in cleaned:
                cleaned.append(value)
        return cleaned, None
    # text
    if raw is None:
        raw = ""
    if not isinstance(raw, str):
        return None, "invalid_type"
    text = raw.strip()
    if f.maximum is not None and len(text) > f.maximum:
        return None, "too_long"
    return text, None


def validate(
    values: Mapping[str, Any], branch_postcodes: Sequence[str] = ()
) -> tuple[dict[str, Any], dict[str, str]]:
    """(cleaned values, {key: error code}) of a full set of settings (the rules of the
    1.3 options flow): every value in its range, at least one meal, and marktguru needs a
    5-digit postcode or selected branches with a postcode. Unknown keys are ignored."""
    cleaned: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for f in FIELDS:
        if f.key not in values:
            continue
        value, error = clean_value(f, values[f.key])
        if error:
            errors[f.key] = error
        else:
            cleaned[f.key] = value
    if CONF_ENABLED_MEALS in cleaned and (error := meals_error(cleaned[CONF_ENABLED_MEALS])):
        errors[CONF_ENABLED_MEALS] = error
    if (
        CONF_ZIP not in errors
        and CONF_OFFERS_SOURCE in cleaned
        and (
            error := zip_error(
                cleaned[CONF_OFFERS_SOURCE], cleaned.get(CONF_ZIP, ""), branch_postcodes
            )
        )
    ):
        errors[CONF_ZIP] = error
    return cleaned, errors


def error_messages(errors: Mapping[str, str]) -> dict[str, str]:
    """{key: German message} of validation codes."""
    return {key: error_text(code, FIELD_MAP.get(key)) for key, code in errors.items()}


def merge_options(options: Mapping[str, Any], cleaned: Mapping[str, Any]) -> dict[str, Any]:
    """New options: the existing ones (also keys this module does not know) updated with
    the cleaned settings; an emptied entity picker (todo copy, AI Task) is removed."""
    result = dict(options)
    for key, value in cleaned.items():
        f = FIELD_MAP.get(key)
        if f is not None and f.optional and value in (None, "", []):
            result.pop(key, None)
        else:
            result[key] = _copy(value)
    return result


def describe_fields() -> dict[str, dict[str, Any]]:
    """{key: {section, type, min, max, step, domain, domains, optional}} for the panel."""
    return {f.key: f.describe() for f in FIELDS}


def choice_list(kind: str, values: Iterable[str]) -> list[dict[str, str]]:
    """[{value, label}] with the German labels of a choice list."""
    labels = CHOICE_LABELS_DE.get(kind, {})
    return [{"value": v, "label": labels.get(v, v)} for v in values]


def store_choices() -> list[dict[str, Any]]:
    """The chains of "Supermärkte" (offer_stores) with their kind (grocery / drugstore)."""
    return [
        {"value": rid, "label": name, "kind": retailer_kind(rid) or "grocery"}
        for rid, name in STORES.items()
    ]


__all__ = [
    "AI_DOMAINS",
    "CHOICE_LABELS_DE",
    "ERROR_TEXTS_DE",
    "FIELDS",
    "FIELD_MAP",
    "MARKTGURU_WARNING_DE",
    "SECTIONS",
    "SECTION_AI",
    "Field",
    "choice_list",
    "clamp",
    "clean_value",
    "current_values",
    "default_values",
    "describe_fields",
    "error_messages",
    "error_text",
    "meals_error",
    "merge_options",
    "normalize_time",
    "number",
    "store_choices",
    "validate",
    "whole",
    "zip_error",
    "zone_list",
]
