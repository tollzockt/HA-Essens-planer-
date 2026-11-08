"""Service actions for the Essensplaner integration."""

from __future__ import annotations

from datetime import date, timedelta
import json
import logging
import re
from typing import TYPE_CHECKING, Any

from homeassistant.components.todo import TodoListEntityFeature
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.service import async_register_admin_service
import voluptuous as vol

from .aldi import SOURCE_ALDI, async_find_aldi_stores, async_refresh_aldi_prices
from .branches import RADIUS_KM_RANGE, ROUTE_RADIUS_RANGE, async_find_branches
from .catalog import catalog_plan, leaflets_view, marktguru_paused, pause_marktguru, paused_message
from .const import (
    ALL_MEALS,
    ATTR_COOK_TIME,
    ATTR_COUNT,
    ATTR_DATE,
    ATTR_DAYS,
    ATTR_FAVORITE,
    ATTR_FAVORITES_ONLY,
    ATTR_IMAGE,
    ATTR_INGREDIENTS,
    ATTR_MAX_TIME,
    ATTR_MEAL,
    ATTR_NAME,
    ATTR_NOTE,
    ATTR_NOTES,
    ATTR_OVERWRITE,
    ATTR_PREP_TIME,
    ATTR_QUERY,
    ATTR_RATING,
    ATTR_RECIPE,
    ATTR_SERVINGS,
    ATTR_SOURCE_URL,
    ATTR_START_DATE,
    ATTR_STEPS,
    ATTR_SYNC,
    ATTR_TAG,
    ATTR_TAGS,
    ATTR_TITLE,
    ATTR_TOTAL_TIME,
    ATTR_URL,
    DOMAIN,
    EVENT_UPDATED,
    OFFERS_MARKTGURU,
    PRICE_SOURCE_ALDI,
    PRICE_SOURCE_EDEKA,
    PRICE_SOURCE_REWE,
    PRICE_SOURCES,
    SERVICE_ADD_OFFER,
    SERVICE_ADD_RECIPE,
    SERVICE_ADD_SHOPPING_ITEM,
    SERVICE_ASSIGN_SHOPPING_STORES,
    SERVICE_AUTO_PLAN,
    SERVICE_CLEAR_SHOPPING,
    SERVICE_COMPARE_PRICES,
    SERVICE_COPY_PLAN,
    SERVICE_DELETE_OCCASION,
    SERVICE_DELETE_RECEIPT,
    SERVICE_DELETE_RECIPE,
    SERVICE_EXPORT_RECIPES,
    SERVICE_FIND_ALDI_STORES,
    SERVICE_FIND_BRANCHES,
    SERVICE_FIND_BY_INGREDIENTS,
    SERVICE_FIND_EDEKA_MARKETS,
    SERVICE_FIND_REWE_MARKETS,
    SERVICE_GET_BRANCHES,
    SERVICE_GET_COSTS,
    SERVICE_GET_LEAFLETS,
    SERVICE_GET_OCCASIONS,
    SERVICE_GET_OFFERS,
    SERVICE_GET_PLAN,
    SERVICE_GET_RECEIPTS,
    SERVICE_GET_RECIPE,
    SERVICE_GET_RECIPES,
    SERVICE_GET_SHOPPING_LIST,
    SERVICE_GET_STORE_PRICES,
    SERVICE_IMPORT_RECIPE,
    SERVICE_IMPORT_RECIPES,
    SERVICE_IMPORT_STARTER,
    SERVICE_MARK_COOKED,
    SERVICE_MOVE_MEAL,
    SERVICE_PLAN_LEFTOVER,
    SERVICE_PLAN_MEAL,
    SERVICE_RECEIPT_PARSE_TEXT,
    SERVICE_RECEIPT_SAVE,
    SERVICE_RECEIPT_SCAN,
    SERVICE_REFRESH_OFFERS,
    SERVICE_REFRESH_PRICES,
    SERVICE_REMOVE_BRANCH,
    SERVICE_REMOVE_MEAL,
    SERVICE_REMOVE_OFFER,
    SERVICE_SAVE_BRANCH,
    SERVICE_SAVE_OCCASION,
    SERVICE_SAVE_PRODUCT,
    SERVICE_SEARCH_OFFERS,
    SERVICE_SEARCH_PRODUCTS,
    SERVICE_SET_PRICE,
    SERVICE_SET_SHOPPING_PRODUCT,
    SERVICE_SET_SHOPPING_STORE,
    SERVICE_SHOPPING_LIST,
    SERVICE_SORT_WITH_AI,
    SERVICE_SUGGEST,
    SERVICE_SUGGEST_DRINKS,
    SERVICE_SUGGEST_OCCASION_MENU,
    SERVICE_UPDATE_RECIPE,
    STRATEGIES,
)
from .dates import DateParseError, parse_date, parse_meal, week_start
from .edeka import SOURCE_EDEKA, async_find_edeka_markets, async_refresh_edeka_offers
from .ingredients import fold
from .occasions import (
    COURSES,
    TEMPLATES,
    async_suggest_drinks,
    async_suggest_menu,
    delete_occasion,
    items_from_text,
    occasion_view,
    occasions_between,
    resolve_course,
    resolve_occasion,
    save_occasion,
)
from .offers import OfferBlocked, async_refresh_offers, async_search_target_offers
from .products import product_card, products_view, save_manual
from .receipts import (
    async_delete_receipt,
    async_parse_receipt_text,
    async_save_receipt,
    async_scan_receipt,
    receipts_view,
)
from .recipe_import import async_fetch_recipe
from .rewe import async_find_rewe_markets, async_refresh_rewe_prices, rewe_enabled, rewe_market
from .season import async_auto_plan, season_weight, suggest_reasons

if TYPE_CHECKING:
    from .manager import EssensplanerManager

_LOGGER = logging.getLogger(__name__)

_TEXT_OR_LIST = vol.Any(cv.string, [vol.Any(cv.string, dict)])
_POSITIVE = vol.All(vol.Coerce(int), vol.Range(min=1, max=100))
_MINUTES = vol.All(vol.Coerce(int), vol.Range(min=0, max=10000))
_DAYS = vol.All(vol.Coerce(int), vol.Range(min=1, max=62))

_RECIPE_FIELDS = {
    vol.Optional(ATTR_SERVINGS): _POSITIVE,
    vol.Optional(ATTR_INGREDIENTS): _TEXT_OR_LIST,
    vol.Optional(ATTR_STEPS): vol.Any(cv.string, [cv.string]),
    vol.Optional(ATTR_TAGS): vol.Any(cv.string, [cv.string]),
    vol.Optional(ATTR_PREP_TIME): _MINUTES,
    vol.Optional(ATTR_COOK_TIME): _MINUTES,
    vol.Optional(ATTR_TOTAL_TIME): _MINUTES,
    vol.Optional(ATTR_NOTES): cv.string,
    vol.Optional(ATTR_SOURCE_URL): cv.string,
    vol.Optional(ATTR_IMAGE): cv.string,
    vol.Optional(ATTR_FAVORITE): cv.boolean,
    vol.Optional(ATTR_RATING): vol.All(vol.Coerce(int), vol.Range(min=0, max=5)),
    # 1.5.1: meal, breakfast, snack, dessert, drink, side, component or auto
    vol.Optional("kind"): cv.string,
}

ADD_RECIPE_SCHEMA = vol.Schema({vol.Required(ATTR_NAME): cv.string, **_RECIPE_FIELDS})
UPDATE_RECIPE_SCHEMA = vol.Schema(
    {vol.Required(ATTR_RECIPE): cv.string, vol.Optional(ATTR_NAME): cv.string, **_RECIPE_FIELDS}
)
RECIPE_SCHEMA = vol.Schema({vol.Required(ATTR_RECIPE): cv.string})
GET_RECIPE_SCHEMA = vol.Schema(
    {vol.Required(ATTR_RECIPE): cv.string, vol.Optional(ATTR_SERVINGS): _POSITIVE}
)
IMPORT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_URL): cv.string,
        vol.Optional(ATTR_TAGS): vol.Any(cv.string, [cv.string]),
        vol.Optional(ATTR_FAVORITE): cv.boolean,
    }
)
GET_RECIPES_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_QUERY): cv.string,
        vol.Optional(ATTR_TAG): cv.string,
        vol.Optional(ATTR_MAX_TIME): _MINUTES,
        vol.Optional(ATTR_FAVORITES_ONLY, default=False): cv.boolean,
    }
)
PLAN_MEAL_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DATE): cv.string,
        vol.Optional(ATTR_MEAL): cv.string,
        vol.Optional(ATTR_RECIPE): cv.string,
        vol.Optional(ATTR_TITLE): cv.string,
        vol.Optional(ATTR_SERVINGS): _POSITIVE,
        vol.Optional(ATTR_NOTE): cv.string,
        vol.Optional("drinks"): vol.Any(cv.string, [vol.Any(cv.string, dict)]),
        # 1.5.1: components with the meal (recipes or free text)
        vol.Optional("extras"): vol.Any(cv.string, [vol.Any(cv.string, dict)]),
    }
)
PLAN_LEFTOVER_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DATE): cv.string,
        vol.Optional(ATTR_MEAL): cv.string,
        vol.Optional("from_date"): cv.string,
        vol.Optional("from_meal"): cv.string,
        vol.Optional(ATTR_SERVINGS): _POSITIVE,
    }
)
REMOVE_MEAL_SCHEMA = vol.Schema(
    {vol.Optional(ATTR_DATE): cv.string, vol.Optional(ATTR_MEAL): cv.string}
)
GET_PLAN_SCHEMA = vol.Schema(
    {vol.Optional(ATTR_START_DATE): cv.string, vol.Optional(ATTR_DAYS, default=7): _DAYS}
)
SUGGEST_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_COUNT, default=3): vol.All(vol.Coerce(int), vol.Range(min=1, max=20)),
        vol.Optional(ATTR_TAG): cv.string,
        vol.Optional(ATTR_MAX_TIME): _MINUTES,
        vol.Optional(ATTR_MEAL): cv.string,
        vol.Optional(ATTR_DATE): cv.string,
        vol.Optional("strategy"): cv.string,
    }
)
AUTO_PLAN_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_START_DATE): cv.string,
        vol.Optional(ATTR_DAYS, default=7): _DAYS,
        vol.Optional("meals"): vol.Any(cv.string, [cv.string]),
        vol.Optional(ATTR_TAG): cv.string,
        vol.Optional(ATTR_MAX_TIME): _MINUTES,
        vol.Optional(ATTR_SERVINGS): _POSITIVE,
        vol.Optional(ATTR_OVERWRITE, default=False): cv.boolean,
        vol.Optional("strategy"): cv.string,
        # 1.5: the AI orders the rules' best candidates (feature "season")
        vol.Optional("ai", default=False): cv.boolean,
    }
)
SHOPPING_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_START_DATE): cv.string,
        vol.Optional(ATTR_DAYS, default=7): _DAYS,
        vol.Optional("replace", default=True): cv.boolean,
        vol.Optional(ATTR_SYNC, default=True): cv.boolean,
        vol.Optional("include_occasions", default=True): cv.boolean,
        vol.Optional("occasion"): cv.string,
    }
)
MARK_COOKED_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_RECIPE): cv.string,
        vol.Optional(ATTR_DATE): cv.string,
        vol.Optional(ATTR_MEAL): cv.string,
    }
)
MOVE_MEAL_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_RECIPE): cv.string,
        vol.Optional("from_date"): cv.string,
        vol.Optional("from_meal"): cv.string,
        vol.Required("to_date"): cv.string,
        vol.Optional("to_meal"): cv.string,
    }
)
COPY_PLAN_SCHEMA = vol.Schema(
    {
        vol.Optional("source_start"): cv.string,
        vol.Optional("target_start"): cv.string,
        vol.Optional(ATTR_DAYS, default=7): _DAYS,
        vol.Optional(ATTR_OVERWRITE, default=False): cv.boolean,
    }
)
FIND_BY_INGREDIENTS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_INGREDIENTS): vol.Any(cv.string, [cv.string]),
        vol.Optional(ATTR_COUNT, default=5): vol.All(vol.Coerce(int), vol.Range(min=1, max=50)),
        vol.Optional(ATTR_MEAL): cv.string,
    }
)
EMPTY_SCHEMA = vol.Schema({})
EXPORT_SCHEMA = vol.Schema({vol.Optional("recipes"): vol.All(cv.ensure_list, [cv.string])})
CLEAR_SHOPPING_SCHEMA = vol.Schema(
    {vol.Optional("mode", default="all"): vol.In(["all", "completed", "plan"])}
)
GET_OFFERS_SCHEMA = vol.Schema(
    {
        vol.Optional("when", default="all"): vol.In(["all", "current", "upcoming"]),
        vol.Optional(ATTR_QUERY): cv.string,
        vol.Optional("store"): cv.string,
        vol.Optional(ATTR_COUNT, default=50): vol.All(vol.Coerce(int), vol.Range(min=1, max=500)),
    }
)
SEARCH_OFFERS_SCHEMA = vol.Schema({vol.Required(ATTR_QUERY): cv.string})
ADD_OFFER_SCHEMA = vol.Schema(
    {
        vol.Required("product"): cv.string,
        vol.Required("store"): cv.string,
        vol.Required("price"): vol.Coerce(float),
        vol.Optional("old_price"): vol.Coerce(float),
        vol.Optional("pack"): cv.string,
        vol.Optional("valid_from"): cv.string,
        vol.Optional("valid_to"): cv.string,
    }
)
REMOVE_OFFER_SCHEMA = vol.Schema({vol.Required("id"): cv.string})
SET_PRICE_SCHEMA = vol.Schema(
    {
        vol.Required("ingredient"): cv.string,
        vol.Optional("price"): vol.Coerce(float),
        vol.Optional("amount", default=1): vol.Coerce(float),
        vol.Optional("unit", default="Stück"): cv.string,
        vol.Optional("store"): cv.string,
        vol.Optional("remove", default=False): cv.boolean,
    }
)
GET_STORE_PRICES_SCHEMA = vol.Schema(
    {vol.Optional("store"): cv.string, vol.Optional(ATTR_QUERY): cv.string}
)
SAVE_BRANCH_SCHEMA = vol.Schema(
    {
        vol.Optional("id"): cv.string,
        vol.Optional("store"): cv.string,
        vol.Optional(ATTR_NAME): cv.string,
        vol.Optional("label"): cv.string,
        vol.Optional("street"): cv.string,
        vol.Optional("postcode"): cv.string,
        vol.Optional("city"): cv.string,
        vol.Optional("lat"): vol.All(vol.Coerce(float), vol.Range(min=-90, max=90)),
        vol.Optional("lon"): vol.All(vol.Coerce(float), vol.Range(min=-180, max=180)),
        vol.Optional("selected"): cv.boolean,
        vol.Optional("main"): cv.boolean,
        vol.Optional("priority"): vol.All(vol.Coerce(float), vol.Range(min=0, max=1000)),
        vol.Optional("rewe_market_id"): cv.string,
        vol.Optional("edeka_market_id"): cv.string,
        vol.Optional("aldi_service_point"): cv.string,
    }
)
REMOVE_BRANCH_SCHEMA = vol.Schema({vol.Required("branch"): cv.string})
FIND_BRANCHES_SCHEMA = vol.Schema(
    {
        vol.Optional("zones"): vol.Any(cv.string, [cv.string]),
        vol.Optional("radius_km"): vol.All(
            vol.Coerce(float), vol.Range(min=RADIUS_KM_RANGE[0], max=RADIUS_KM_RANGE[1])
        ),
        vol.Optional("route"): cv.boolean,
        vol.Optional("route_radius_m"): vol.All(
            vol.Coerce(int), vol.Range(min=ROUTE_RADIUS_RANGE[0], max=ROUTE_RADIUS_RANGE[1])
        ),
        vol.Optional("retailers"): vol.Any(cv.string, [cv.string]),
        vol.Optional("refresh", default=False): cv.boolean,
    }
)
REFRESH_PRICES_SCHEMA = vol.Schema({vol.Required("source"): vol.In(PRICE_SOURCES)})
FIND_REWE_MARKETS_SCHEMA = vol.Schema({vol.Optional("zip"): cv.string})
FIND_EDEKA_MARKETS_SCHEMA = vol.Schema({vol.Optional("zip"): cv.string})
FIND_ALDI_STORES_SCHEMA = vol.Schema(
    {
        vol.Optional("zip"): cv.string,
        vol.Inclusive("lat", "location"): vol.All(vol.Coerce(float), vol.Range(min=-90, max=90)),
        vol.Inclusive("lon", "location"): vol.All(vol.Coerce(float), vol.Range(min=-180, max=180)),
    }
)
GET_SHOPPING_LIST_SCHEMA = vol.Schema({vol.Optional("store"): cv.string})
SET_SHOPPING_STORE_SCHEMA = vol.Schema(
    {
        vol.Required("item"): cv.string,
        vol.Required("store"): cv.string,
        vol.Optional("always", default=False): cv.boolean,
    }
)
ASSIGN_SHOPPING_STORES_SCHEMA = vol.Schema({vol.Optional("reset", default=False): cv.boolean})
COMPARE_PRICES_SCHEMA = vol.Schema({vol.Required("item"): cv.string})
ADD_SHOPPING_ITEM_SCHEMA = vol.Schema(
    {
        vol.Required("item"): cv.string,
        vol.Optional("store"): cv.string,
        vol.Optional("price"): vol.All(vol.Coerce(float), vol.Range(min=0, max=10000)),
        vol.Optional("pack"): cv.string,
        vol.Optional("offer_id"): cv.string,
        vol.Optional("product_id"): cv.string,
    }
)
SET_SHOPPING_PRODUCT_SCHEMA = vol.Schema(
    {
        vol.Required("item"): cv.string,
        vol.Optional("product_id"): vol.Any(None, cv.string),
        vol.Optional("remember", default="none"): vol.In(["none", "pick", "favorite"]),
    }
)
GET_COSTS_SCHEMA = vol.Schema(
    {vol.Optional(ATTR_START_DATE): cv.string, vol.Optional(ATTR_DAYS): _DAYS}
)
RECEIPT_PARSE_TEXT_SCHEMA = vol.Schema(
    {vol.Required("text"): cv.string, vol.Optional("branch"): cv.string}
)
RECEIPT_SCAN_SCHEMA = vol.Schema(
    {
        vol.Exclusive("upload_id", "receipt"): cv.string,
        vol.Exclusive("media_content_id", "receipt"): cv.string,
        vol.Optional("entity_id"): cv.entity_id,
        vol.Optional("branch"): cv.string,
    }
)
RECEIPT_SAVE_SCHEMA = vol.Schema({vol.Required("receipt"): dict})
GET_RECEIPTS_SCHEMA = vol.Schema(
    {vol.Optional("limit", default=50): vol.All(vol.Coerce(int), vol.Range(min=1, max=200))}
)
DELETE_RECEIPT_SCHEMA = vol.Schema(
    {vol.Required("id"): cv.string, vol.Optional("remove_prices", default=False): cv.boolean}
)
SEARCH_PRODUCTS_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_QUERY): cv.string,
        vol.Optional("store"): cv.string,
        vol.Optional("only"): vol.In(["favorites", "offers", "bought", "manual"]),
        vol.Optional("sort", default="price"): vol.In(
            ["price", "unit_price", "saving", "name", "recent"]
        ),
        vol.Optional(ATTR_COUNT, default=20): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
    }
)
GET_LEAFLETS_SCHEMA = vol.Schema(
    {
        vol.Optional("store"): cv.string,
        vol.Optional("when", default="all"): vol.In(["current", "upcoming", "all"]),
    }
)
SORT_WITH_AI_SCHEMA = vol.Schema(
    {vol.Optional("target", default="all"): vol.In(["all", "products", "recipes"])}
)
SAVE_PRODUCT_SCHEMA = vol.Schema(
    {
        vol.Optional("id"): cv.string,
        vol.Optional("store"): cv.string,
        vol.Optional(ATTR_NAME): cv.string,
        vol.Optional("brand"): cv.string,
        vol.Optional("pack"): cv.string,
        vol.Optional("price"): vol.All(vol.Coerce(float), vol.Range(min=0.01, max=10000)),
        vol.Optional(ATTR_IMAGE): cv.string,
        vol.Optional("ingredient"): cv.string,
        vol.Optional(ATTR_FAVORITE): cv.boolean,
    }
)
_GUESTS = vol.All(vol.Coerce(int), vol.Range(min=1, max=200))
_CHILDREN = vol.All(vol.Coerce(int), vol.Range(min=0, max=100))
SAVE_OCCASION_SCHEMA = vol.Schema(
    {
        vol.Optional("occasion"): cv.string,
        vol.Optional(ATTR_TITLE): cv.string,
        vol.Optional("template"): vol.In(list(TEMPLATES)),
        vol.Optional(ATTR_DATE): cv.string,
        vol.Optional("time"): cv.string,
        vol.Optional("duration"): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=48)),
        vol.Optional("guests"): _GUESTS,
        vol.Optional("children"): _CHILDREN,
        vol.Optional("items"): vol.Any(cv.string, [vol.Any(cv.string, dict)]),
        vol.Optional("course"): vol.In(list(COURSES)),
        vol.Optional("remove"): vol.Any(cv.string, [cv.string]),
        vol.Optional(ATTR_NOTES): cv.string,
        vol.Optional("auto_fill", default=False): cv.boolean,
    }
)
OCCASION_SCHEMA = vol.Schema({vol.Required("occasion"): cv.string})
GET_OCCASIONS_SCHEMA = vol.Schema(
    {
        vol.Optional("occasion"): cv.string,
        vol.Optional(ATTR_START_DATE): cv.string,
        vol.Optional(ATTR_DAYS, default=365): vol.All(vol.Coerce(int), vol.Range(min=1, max=400)),
    }
)
SUGGEST_OCCASION_MENU_SCHEMA = vol.Schema(
    {
        vol.Required("occasion"): cv.string,
        vol.Optional("course"): vol.In(list(COURSES)),
        vol.Optional(ATTR_COUNT, default=5): vol.All(vol.Coerce(int), vol.Range(min=1, max=20)),
        vol.Optional("ai", default=False): cv.boolean,
        vol.Optional("apply", default=False): cv.boolean,
    }
)
SUGGEST_DRINKS_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_RECIPE): cv.string,
        vol.Optional("occasion"): cv.string,
        vol.Optional(ATTR_DATE): cv.string,
        vol.Optional("guests"): _GUESTS,
        vol.Optional("children"): _CHILDREN,
        vol.Optional("alcohol"): cv.boolean,
        vol.Optional("ai", default=False): cv.boolean,
    }
)
IMPORT_RECIPES_SCHEMA = vol.Schema(
    {
        vol.Required("recipes"): vol.Any(cv.string, [dict]),
        vol.Optional(ATTR_OVERWRITE, default=False): cv.boolean,
    }
)


STRATEGY_WORDS = {
    "ausgewogen": "balanced",
    "normal": "balanced",
    "guenstig": "cheap",
    "billig": "cheap",
    "sparsam": "cheap",
    "preiswert": "cheap",
    "angebot": "offers",
    "abwechslung": "variety",
    "vielfalt": "variety",
    "saison": "seasonal",
    "regional": "seasonal",
}


def resolve_strategy(value: str | None) -> str | None:
    """Map 'günstig' / 'cheap' / 'Angebote' to a strategy id."""
    if not value:
        return None
    key = fold(value).strip()
    if key in STRATEGIES:
        return key
    for word, strategy in STRATEGY_WORDS.items():
        if word in key:
            return strategy
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="invalid_strategy",
        translation_placeholders={"strategy": value},
    )


def parse_price(value: Any) -> float:
    """'4,99 €' -> 4.99."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace("€", "").replace("Euro", "").replace("EUR", "").strip()
    match = re.search(r"\d+(?:[.,]\d{1,2})?", text)
    if not match:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_price",
            translation_placeholders={"price": str(value)},
        )
    return float(match.group().replace(",", "."))


def split_list(value: Any) -> list[str]:
    """Split 'Hähnchen, Reis und Paprika' into items."""
    if isinstance(value, list):
        items = [str(v) for v in value]
    else:
        text = str(value or "")
        for sep in (";", "\n", " und ", " and ", " sowie ", "&"):
            text = text.replace(sep, ",")
        items = text.split(",")
    return [i.strip() for i in items if i.strip()]


def require_offer_source(manager: EssensplanerManager) -> None:
    """Raise unless an offer source is on: marktguru (with a zip code option or branches
    with postcode), or the EDEKA / ALDI SÜD offers (1.4 offer catalog)."""
    plan = catalog_plan(manager)
    if plan["edeka"] or plan["aldi"]:
        return
    if manager.offers_source != OFFERS_MARKTGURU:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="offers_disabled")
    if not manager.offer_targets():
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="invalid_zip")


def resolve_move(
    manager: EssensplanerManager,
    dish: str | None,
    from_date: str | None,
    from_meal: str | None,
    to_date: str,
    to_meal: str | None,
) -> tuple[date, str, date, str]:
    """Work out source and target of a move."""
    if from_date or not dish:
        src_day, hint = resolve_day(manager, from_date)
        src_meal = resolve_meal(manager, from_meal, hint, default=False)
        if src_meal is None:
            planned = manager.plan.get(src_day.isoformat(), {})
            if dish and (found := manager.find_planned(dish, src_day, days=1)):
                src_meal = found[1]
            elif len(planned) == 1:
                src_meal = next(iter(planned))
            else:
                src_meal = manager.default_meal
    else:
        found = manager.find_planned(dish)
        if found is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="dish_not_planned",
                translation_placeholders={"name": dish},
            )
        src_day, src_meal = found
    dst_day, dst_hint = resolve_day(manager, to_date)
    dst_meal = resolve_meal(manager, to_meal, dst_hint, default=False) or src_meal
    return src_day, src_meal, dst_day, dst_meal


def resolve_leftover(
    manager: EssensplanerManager,
    to_date: str | None,
    to_meal: str | None,
    from_date: str | None,
    from_meal: str | None,
    dish: str | None = None,
) -> tuple[date, str, date, str]:
    """Cooking meal and leftovers slot (plan_leftover, the voice intent; 1.5.1).

    Without days the leftovers are tomorrow's of today; one day given, the other is the
    day before / after it. The cooking meal is the one given, else the planned meal of the
    cooking day (the one with the dish, else the default meal, the dinner, …); the
    leftovers' meal defaults to the cooking meal. Returns (from_day, from_meal, day, meal).
    """
    today = manager.today()
    src_hint = dst_hint = None
    if from_date:
        src_day, src_hint = resolve_day(manager, from_date)
    if to_date:
        dst_day, dst_hint = resolve_day(manager, to_date)
    if not from_date and not to_date:
        src_day, dst_day = today, today + timedelta(days=1)
    elif not to_date:
        dst_day = src_day + timedelta(days=1)
    elif not from_date:
        src_day = dst_day - timedelta(days=1)
    src_meal = resolve_meal(manager, from_meal, src_hint, default=False)
    if src_meal is None:
        planned = manager.plan.get(src_day.isoformat(), {})
        if dish and (found := manager.find_planned(dish, src_day, days=1)) and found[0] == src_day:
            src_meal = found[1]
        else:
            order = [manager.default_meal, *reversed(ALL_MEALS)]
            cooked = [m for m in order if m in planned and not planned[m].get("leftover_of")]
            src_meal = next(
                (m for m in cooked if planned[m].get("recipe_id")), cooked[0] if cooked else None
            )
    if src_meal is None:
        src_meal = resolve_meal(manager, to_meal, dst_hint) or manager.default_meal
    dst_meal = resolve_meal(manager, to_meal, dst_hint, default=False) or src_meal
    return src_day, src_meal, dst_day, dst_meal


def get_manager(hass: HomeAssistant) -> EssensplanerManager:
    """Return the manager of the loaded config entry."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")
    return entries[0].runtime_data


def resolve_day(manager: EssensplanerManager, value: str | None) -> tuple[date, str | None]:
    """Parse a date string or raise a validation error."""
    try:
        return parse_date(value, manager.today())
    except DateParseError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_date",
            translation_placeholders={"date": str(value)},
        ) from err


def resolve_meal(
    manager: EssensplanerManager, value: str | None, hint: str | None = None, default: bool = True
) -> str | None:
    """Parse a meal string or raise a validation error."""
    if value:
        meal = parse_meal(value)
        if meal is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_meal",
                translation_placeholders={"meal": value},
            )
        return meal
    if hint:
        return hint
    return manager.default_meal if default else None


def resolve_meals(manager: EssensplanerManager, value: Any) -> list[str] | None:
    """Parse a list of meals."""
    if not value:
        return None
    items = value if isinstance(value, list) else str(value).replace(";", ",").split(",")
    meals: list[str] = []
    for item in items:
        if str(item).strip() in ("all", "alle"):
            return list(manager.enabled_meals)
        meal = resolve_meal(manager, str(item).strip())
        if meal and meal not in meals:
            meals.append(meal)
    return meals or None


async def async_sync_shopping(
    hass: HomeAssistant, entity_id: str, items: list[dict[str, Any]]
) -> int:
    """Copy open shopping items to another todo list (skips duplicates)."""
    if (registry_entry := er.async_get(hass).async_get(entity_id)) and (
        registry_entry.platform == DOMAIN
    ):
        _LOGGER.warning("Shopping list sync target %s is the Essensplaner list itself", entity_id)
        return 0
    state = hass.states.get(entity_id)
    if state is None:
        _LOGGER.warning("Shopping list sync target %s not found", entity_id)
        return 0
    features = int(state.attributes.get("supported_features") or 0)
    supports_description = bool(features & TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM)
    existing: set[str] = set()
    try:
        response = await hass.services.async_call(
            "todo",
            "get_items",
            {"entity_id": entity_id, "status": ["needs_action"]},
            blocking=True,
            return_response=True,
        )
        if isinstance(response, dict):
            for item in response.get(entity_id, {}).get("items", []):
                existing.add(fold(item.get("summary", "")))
    except HomeAssistantError as err:
        _LOGGER.debug("Could not read items of %s: %s", entity_id, err)

    added = 0
    for item in items:
        if item.get("status") == "completed" or fold(item["summary"]) in existing:
            continue
        data: dict[str, Any] = {"entity_id": entity_id, "item": item["summary"]}
        if supports_description and item.get("description"):
            data["description"] = item["description"]
        try:
            await hass.services.async_call("todo", "add_item", data, blocking=True)
        except HomeAssistantError as err:
            _LOGGER.warning("Could not add %s to %s: %s", item["summary"], entity_id, err)
            continue
        existing.add(fold(item["summary"]))
        added += 1
    return added


def _recipe_payload(call: ServiceCall) -> dict[str, Any]:
    return {k: v for k, v in call.data.items() if k != ATTR_RECIPE}


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the service actions."""

    async def add_recipe(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        recipe = manager.add_recipe(dict(call.data))
        return {"recipe": manager.recipe_view(recipe)}

    async def update_recipe(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        recipe = manager.resolve_recipe(name=call.data[ATTR_RECIPE])
        updated = manager.update_recipe(recipe["id"], _recipe_payload(call))
        return {"recipe": manager.recipe_view(updated)}

    async def delete_recipe(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        recipe = manager.resolve_recipe(name=call.data[ATTR_RECIPE])
        manager.delete_recipe(recipe["id"])
        return {"deleted": manager.recipe_summary(recipe)}

    async def import_recipe(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        data = await async_fetch_recipe(hass, call.data[ATTR_URL])
        if ATTR_TAGS in call.data:
            extra = call.data[ATTR_TAGS]
            extra = extra.split(",") if isinstance(extra, str) else extra
            data["tags"] = [*data.get("tags", []), *extra]
        if ATTR_FAVORITE in call.data:
            data["favorite"] = call.data[ATTR_FAVORITE]
        recipe, created = manager.upsert_imported_recipe(data)
        return {"recipe": manager.recipe_view(recipe), "created": created}

    async def get_recipes(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        recipes = manager.search_recipes(
            query=call.data.get(ATTR_QUERY),
            tag=call.data.get(ATTR_TAG),
            max_time=call.data.get(ATTR_MAX_TIME),
            favorites_only=call.data[ATTR_FAVORITES_ONLY],
        )
        return {
            "count": len(recipes),
            "recipes": [manager.recipe_summary(r) for r in recipes],
        }

    async def get_recipe(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        recipe = manager.resolve_recipe(name=call.data[ATTR_RECIPE])
        return {"recipe": manager.recipe_view(recipe, call.data.get(ATTR_SERVINGS))}

    async def plan_meal(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        day, hint = resolve_day(manager, call.data.get(ATTR_DATE))
        meal = resolve_meal(manager, call.data.get(ATTR_MEAL), hint)
        assert meal is not None
        recipe = None
        title = call.data.get(ATTR_TITLE)
        if name := call.data.get(ATTR_RECIPE):
            recipe = manager.find_recipe(name)
            if recipe is None and not title:
                title = name
        drinks = call.data.get("drinks")
        extras = call.data.get("extras")
        entry = manager.plan_meal(
            day,
            meal,
            recipe=recipe,
            title=title,
            servings=call.data.get(ATTR_SERVINGS),
            note=call.data.get(ATTR_NOTE),
            drinks=split_list(drinks) if isinstance(drinks, str) else drinks,
            extras=split_list(extras) if isinstance(extras, str) else extras,
        )
        return {"entry": entry, "recipe_found": recipe is not None}

    async def plan_leftover(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        src_day, src_meal, day, meal = resolve_leftover(
            manager,
            call.data.get(ATTR_DATE),
            call.data.get(ATTR_MEAL),
            call.data.get("from_date"),
            call.data.get("from_meal"),
        )
        entry = manager.plan_leftover(
            day, meal, src_day, src_meal, servings=call.data.get(ATTR_SERVINGS)
        )
        link = entry["leftover_of"] or {"date": src_day.isoformat(), "meal": src_meal}
        cooking_day = date.fromisoformat(link["date"])
        cooking = manager.plan.get(link["date"], {}).get(link["meal"])
        return {
            "entry": entry,
            "cooking": manager.entry_view(cooking_day, link["meal"], cooking) if cooking else None,
        }

    async def remove_meal(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        day, hint = resolve_day(manager, call.data.get(ATTR_DATE))
        meal = resolve_meal(manager, call.data.get(ATTR_MEAL), hint, default=False)
        return {"removed": manager.remove_meal(day, meal)}

    async def get_plan(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        start, _ = resolve_day(manager, call.data.get(ATTR_START_DATE))
        return {"days": manager.plan_range(start, call.data[ATTR_DAYS])}

    async def suggest(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        around, hint = resolve_day(manager, call.data.get(ATTR_DATE))
        meal = resolve_meal(manager, call.data.get(ATTR_MEAL), hint, default=False)
        strategy = resolve_strategy(call.data.get("strategy"))
        recipes = manager.suggest(
            call.data[ATTR_COUNT],
            tag=call.data.get(ATTR_TAG),
            max_time=call.data.get(ATTR_MAX_TIME),
            meal=meal,
            around=around,
            strategy=strategy,
        )
        # 1.5: why each recipe (favourite, season, offers)
        season = season_weight(manager, strategy) > 0
        return {
            "recipes": [
                {
                    **manager.recipe_summary(r),
                    "cost": manager.recipe_cost(r, None, around)["total"],
                    "reasons": suggest_reasons(manager, r, around, season=season),
                }
                for r in recipes
            ]
        }

    async def auto_plan(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        start, _ = resolve_day(manager, call.data.get(ATTR_START_DATE))
        result = await async_auto_plan(
            hass,
            manager,
            start,
            call.data[ATTR_DAYS],
            meals=resolve_meals(manager, call.data.get("meals")),
            tag=call.data.get(ATTR_TAG),
            max_time=call.data.get(ATTR_MAX_TIME),
            overwrite=call.data[ATTR_OVERWRITE],
            servings=call.data.get(ATTR_SERVINGS),
            strategy=resolve_strategy(call.data.get("strategy")),
            ai=call.data["ai"],
        )
        return {
            "planned": result["planned"],
            "week": manager.week_overview(start),
            "ai": result["ai"],
        }

    async def shopping_list(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        start, _ = resolve_day(manager, call.data.get(ATTR_START_DATE))
        occasion_id = None
        if call.data.get("occasion"):
            occasion_id = resolve_occasion(manager, call.data["occasion"])["id"]
        result = manager.generate_shopping_list(
            start,
            call.data[ATTR_DAYS],
            replace=call.data["replace"],
            include_occasions=call.data["include_occasions"],
            occasion_id=occasion_id,
        )
        result["synced_to"] = None
        result["synced_items"] = 0
        if call.data[ATTR_SYNC] and (target := manager.sync_entity):
            result["synced_to"] = target
            result["synced_items"] = await async_sync_shopping(hass, target, result["items"])
        return result

    async def mark_cooked(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        day, hint = resolve_day(manager, call.data.get(ATTR_DATE))
        meal = resolve_meal(manager, call.data.get(ATTR_MEAL), hint, default=False)
        recipe = None
        if name := call.data.get(ATTR_RECIPE):
            recipe = manager.resolve_recipe(name=name)
        recipe = manager.mark_cooked(recipe, day, meal)
        return {"recipe": manager.recipe_summary(recipe) if recipe else None}

    async def move_meal(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        src_day, src_meal, dst_day, dst_meal = resolve_move(
            manager,
            call.data.get(ATTR_RECIPE),
            call.data.get("from_date"),
            call.data.get("from_meal"),
            call.data["to_date"],
            call.data.get("to_meal"),
        )
        return manager.move_meal(src_day, src_meal, dst_day, dst_meal)

    async def copy_plan(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        if call.data.get("target_start"):
            target, _ = resolve_day(manager, call.data["target_start"])
        else:
            target = week_start(manager.today())
        if call.data.get("source_start"):
            source, _ = resolve_day(manager, call.data["source_start"])
        else:
            source = target - timedelta(days=7)
        copied = manager.copy_plan(
            source, target, call.data[ATTR_DAYS], overwrite=call.data[ATTR_OVERWRITE]
        )
        return {"copied": copied}

    async def find_by_ingredients(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        meal = resolve_meal(manager, call.data.get(ATTR_MEAL), None, default=False)
        return {
            "recipes": manager.find_by_ingredients(
                split_list(call.data[ATTR_INGREDIENTS]), call.data[ATTR_COUNT], meal
            )
        }

    async def get_shopping_list(call: ServiceCall) -> ServiceResponse:
        return get_manager(hass).shopping_overview(call.data.get("store"))

    async def set_shopping_store(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        item = manager.set_shopping_store(
            call.data["item"], call.data["store"], call.data["always"]
        )
        return {"item": item, "stores": manager.stores_summary()}

    async def assign_shopping_stores(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        result = manager.assign_shopping_stores(call.data["reset"])
        return {**result, "stores": manager.stores_summary()}

    async def compare_prices(call: ServiceCall) -> ServiceResponse:
        return get_manager(hass).compare_prices(call.data["item"])

    async def add_shopping_item(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        item = manager.shopping_add(
            call.data["item"],
            store=call.data.get("store"),
            price=call.data.get("price"),
            pack=call.data.get("pack"),
            offer_id=call.data.get("offer_id"),
            product_id=call.data.get("product_id"),
        )
        return {"item": item}

    async def set_shopping_product(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        item = manager.find_shopping_item(call.data["item"])
        item = manager.shopping_set_product(
            item["uid"], call.data.get("product_id"), call.data["remember"]
        )
        return {"item": item, "stores": manager.stores_summary()}

    async def export_recipes(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        ids = None
        if names := call.data.get("recipes"):
            ids = [manager.resolve_recipe(name=n)["id"] for n in names]
        return {"version": 1, "recipes": manager.export_recipes(ids)}

    async def import_recipes(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        recipes = call.data["recipes"]
        if isinstance(recipes, str):
            try:
                parsed = json.loads(recipes)
            except ValueError as err:
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="invalid_json"
                ) from err
            recipes = parsed.get("recipes", []) if isinstance(parsed, dict) else parsed
        if not isinstance(recipes, list):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="invalid_json")
        return manager.import_recipes(recipes, overwrite=call.data[ATTR_OVERWRITE])

    async def clear_shopping_list(call: ServiceCall) -> ServiceResponse:
        return {"removed": get_manager(hass).shopping_clear(call.data["mode"])}

    async def import_starter_recipes(call: ServiceCall) -> ServiceResponse:
        return await get_manager(hass).async_import_starter_recipes()

    async def refresh_offers(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        require_offer_source(manager)
        return await async_refresh_offers(hass, manager)

    async def search_offers(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        query = call.data[ATTR_QUERY]
        live: list[dict[str, Any]] = []
        error = None
        targets = manager.offer_targets() if manager.offers_source == OFFERS_MARKTGURU else []
        if targets and (until := marktguru_paused(manager)):
            error = paused_message(until)  # it refused: nothing is asked meanwhile
        elif targets:
            # only the user's chains (numeric ids from the catalog's discovery)
            ids = {z: manager.catalog.publisher_ids(z, r) for z, r in targets}
            try:
                live, errors = await async_search_target_offers(
                    hass, query, targets, retailer_ids=ids
                )
            except OfferBlocked:
                live, errors = [], [paused_message(pause_marktguru(manager))]
            error = "; ".join(errors) if errors else None
        live.sort(key=lambda o: (o.get("unit_price") or 9e9, o["price"]))
        return {
            "query": query,
            "live": live[:50],
            "saved": manager.offers_view(query=query),
            "error": error,
        }

    async def get_offers(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        offers = manager.offers_view(
            call.data["when"],
            call.data.get(ATTR_QUERY),
            call.data.get("store"),
            call.data[ATTR_COUNT],
        )
        return {
            "count": len(offers),
            "offers": offers,
            "meta": manager.offers_meta,
            "price_sources": manager.price_sources_view(),
        }

    async def add_offer(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        valid_from = (
            resolve_day(manager, call.data["valid_from"])[0]
            if call.data.get("valid_from")
            else None
        )
        valid_to = (
            resolve_day(manager, call.data["valid_to"])[0] if call.data.get("valid_to") else None
        )
        offer = manager.add_offer(
            call.data["product"],
            call.data["store"],
            call.data["price"],
            call.data.get("pack"),
            valid_from,
            valid_to,
            call.data.get("old_price"),
        )
        return {"offer": offer}

    async def remove_offer(call: ServiceCall) -> ServiceResponse:
        return {"removed": get_manager(hass).remove_offer(call.data["id"])}

    async def set_price(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        if call.data["remove"] or call.data.get("price") is None:
            return {
                "removed": manager.remove_price(call.data["ingredient"], call.data.get("store"))
            }
        return {
            "price": manager.set_price(
                call.data["ingredient"],
                call.data["price"],
                call.data["amount"],
                call.data["unit"],
                call.data.get("store"),
            )
        }

    async def get_store_prices(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        retailer = manager.require_retailer(call.data["store"]) if call.data.get("store") else None
        return manager.store_price_matrix(call.data.get(ATTR_QUERY), retailer=retailer)

    async def save_branch(call: ServiceCall) -> ServiceResponse:
        return {"branch": get_manager(hass).save_branch(dict(call.data))}

    async def remove_branch(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        removed = manager.remove_branch(call.data["branch"])
        return {"removed": removed, "main_branch": manager.branches_export()["main_branch"]}

    async def get_branches(call: ServiceCall) -> ServiceResponse:
        return get_manager(hass).branches_export()

    async def find_branches(call: ServiceCall) -> ServiceResponse:
        return await async_find_branches(
            hass,
            get_manager(hass),
            zones=split_list(call.data.get("zones")) or None,
            radius_km=call.data.get("radius_km"),
            route=call.data.get("route"),
            route_radius_m=call.data.get("route_radius_m"),
            retailers=split_list(call.data.get("retailers")) or None,
            refresh=call.data["refresh"],
        )

    async def refresh_prices(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        source = call.data["source"]
        if source == PRICE_SOURCE_ALDI:
            if not SOURCE_ALDI.enabled(manager):
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="aldi_disabled"
                )
            if not SOURCE_ALDI.has_target(manager):
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="aldi_no_store"
                )
            return await async_refresh_aldi_prices(hass, manager, force=True)
        if source == PRICE_SOURCE_EDEKA:
            if not SOURCE_EDEKA.enabled(manager):
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="edeka_disabled"
                )
            if not SOURCE_EDEKA.has_target(manager):
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="edeka_no_market"
                )
            return await async_refresh_edeka_offers(hass, manager, force=True)
        if source != PRICE_SOURCE_REWE:
            require_offer_source(manager)
            return await async_refresh_offers(hass, manager)
        if not rewe_enabled(manager):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="rewe_disabled")
        if rewe_market(manager)[1] is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="rewe_no_market"
            )
        return await async_refresh_rewe_prices(hass, manager, force=True)

    async def find_rewe_markets(call: ServiceCall) -> ServiceResponse:
        return await async_find_rewe_markets(hass, get_manager(hass), call.data.get("zip"))

    async def find_edeka_markets(call: ServiceCall) -> ServiceResponse:
        return await async_find_edeka_markets(hass, get_manager(hass), call.data.get("zip"))

    async def find_aldi_stores(call: ServiceCall) -> ServiceResponse:
        return await async_find_aldi_stores(
            hass,
            get_manager(hass),
            call.data.get("zip"),
            call.data.get("lat"),
            call.data.get("lon"),
        )

    async def receipt_parse_text(call: ServiceCall) -> ServiceResponse:
        return await async_parse_receipt_text(
            get_manager(hass), call.data["text"], call.data.get("branch")
        )

    async def receipt_scan(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        if not call.data.get("upload_id") and not call.data.get("media_content_id"):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="receipt_media_invalid",
                translation_placeholders={"media": ""},
            )
        return await async_scan_receipt(
            hass,
            manager,
            upload_id=call.data.get("upload_id"),
            media_content_id=call.data.get("media_content_id"),
            entity_id=call.data.get("entity_id"),
            branch=call.data.get("branch"),
        )

    async def receipt_save(call: ServiceCall) -> ServiceResponse:
        return await async_save_receipt(get_manager(hass), dict(call.data["receipt"]))

    async def get_receipts(call: ServiceCall) -> ServiceResponse:
        return receipts_view(get_manager(hass), call.data["limit"])

    async def delete_receipt(call: ServiceCall) -> ServiceResponse:
        return await async_delete_receipt(
            get_manager(hass), call.data["id"], call.data["remove_prices"]
        )

    async def search_products(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        retailers = None
        if store := call.data.get("store"):
            branch = manager.resolve_branch(store)
            retailers = [branch["retailer"] if branch else manager.require_retailer(store)]
        result = products_view(
            manager,
            query=call.data.get(ATTR_QUERY),
            retailers=retailers,
            only=call.data.get("only"),
            sort=call.data["sort"],
            limit=call.data[ATTR_COUNT],
        )
        return {
            "total": result["total"],
            "products": result["products"],
            "counts": result["counts"],
        }

    async def get_leaflets(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        branch_ids: list[str] | None = None
        if store := call.data.get("store"):
            # one branch ("Lidl Arbeit", "Hauptladen") or every branch of a chain ("Lidl")
            if (branch := manager.named_branch(store)) is not None:
                branch_ids = [branch["id"]]
            else:
                retailer = manager.require_retailer(store)
                branch_ids = [
                    b["id"] for b in manager.selected_branches() if b.get("retailer") == retailer
                ] or ["-"]  # a chain without a saved branch: no leaflets
        return leaflets_view(manager, when=call.data["when"], branch_ids=branch_ids)

    async def sort_with_ai(call: ServiceCall) -> ServiceResponse:
        from .ai_sort import async_sort  # imports the manager

        manager = get_manager(hass)
        result = await async_sort(hass, manager, call.data["target"])
        return {k: v for k, v in result.items() if k != "status"}

    async def save_product(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        product = save_manual(manager, dict(call.data))
        hass.bus.async_fire(EVENT_UPDATED, {"change": "products"})
        return {"product": product_card(manager, product)}

    async def save_occasion_service(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        data: dict[str, Any] = {}
        for key in (ATTR_TITLE, "template", "time", "guests", "children", ATTR_NOTES):
            if key in call.data:
                data[key] = call.data[key]
        if "duration" in call.data:
            data["duration_h"] = call.data["duration"]
        if call.data.get(ATTR_DATE):
            data["date"] = resolve_day(manager, call.data[ATTR_DATE])[0]
        if "items" in call.data:
            values = call.data["items"]
            data["add_items"] = items_from_text(
                manager,
                split_list(values) if isinstance(values, str) else values,
                call.data.get("course"),
            )
        if call.data.get("remove"):
            remove = call.data["remove"]
            data["remove_items"] = split_list(remove) if isinstance(remove, str) else remove
        if call.data.get("occasion"):
            data["id"] = resolve_occasion(manager, call.data["occasion"])["id"]
        else:
            data["auto_fill"] = call.data["auto_fill"]
        occasion = save_occasion(manager, data)
        return {"occasion": occasion_view(manager, occasion)}

    async def delete_occasion_service(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        occasion = delete_occasion(manager, resolve_occasion(manager, call.data["occasion"])["id"])
        return {
            "deleted": {"id": occasion["id"], "title": occasion["title"], "date": occasion["date"]}
        }

    async def get_occasions(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        if call.data.get("occasion"):
            found = [resolve_occasion(manager, call.data["occasion"])]
        else:
            start, _ = resolve_day(manager, call.data.get(ATTR_START_DATE))
            end = start + timedelta(days=call.data[ATTR_DAYS] - 1)
            found = occasions_between(manager, start, end)
        return {"occasions": [occasion_view(manager, o) for o in found]}

    async def suggest_occasion_menu(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        occasion = resolve_occasion(manager, call.data["occasion"])
        return await async_suggest_menu(
            hass,
            manager,
            occasion,
            course=resolve_course(call.data.get("course")),
            count=call.data[ATTR_COUNT],
            ai=call.data["ai"],
            apply=call.data["apply"],
        )

    async def suggest_drinks_service(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        recipes = []
        titles = []
        if dish := call.data.get(ATTR_RECIPE):
            recipe = manager.find_recipe(dish)
            if recipe is not None:
                recipes.append(recipe)
            else:
                titles.append(dish)
        occasion = None
        if call.data.get("occasion"):
            occasion = resolve_occasion(manager, call.data["occasion"])
        day = resolve_day(manager, call.data[ATTR_DATE])[0] if call.data.get(ATTR_DATE) else None
        return await async_suggest_drinks(
            hass,
            manager,
            recipes=recipes,
            titles=titles,
            occasion=occasion,
            day=day,
            alcohol=call.data.get("alcohol"),
            guests=call.data.get("guests"),
            children=call.data.get("children"),
            ai=call.data["ai"],
        )

    async def get_costs(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        if call.data.get(ATTR_START_DATE) or call.data.get(ATTR_DAYS):
            start, _ = resolve_day(manager, call.data.get(ATTR_START_DATE))
            result = manager.plan_costs(start, call.data.get(ATTR_DAYS) or 7)
            result["budget"] = manager.weekly_budget
            return result
        return manager.week_overview()

    services: list[tuple[str, Any, vol.Schema]] = [
        (SERVICE_ADD_RECIPE, add_recipe, ADD_RECIPE_SCHEMA),
        (SERVICE_UPDATE_RECIPE, update_recipe, UPDATE_RECIPE_SCHEMA),
        (SERVICE_DELETE_RECIPE, delete_recipe, RECIPE_SCHEMA),
        (SERVICE_IMPORT_RECIPE, import_recipe, IMPORT_SCHEMA),
        (SERVICE_GET_RECIPES, get_recipes, GET_RECIPES_SCHEMA),
        (SERVICE_GET_RECIPE, get_recipe, GET_RECIPE_SCHEMA),
        (SERVICE_PLAN_MEAL, plan_meal, PLAN_MEAL_SCHEMA),
        (SERVICE_PLAN_LEFTOVER, plan_leftover, PLAN_LEFTOVER_SCHEMA),
        (SERVICE_REMOVE_MEAL, remove_meal, REMOVE_MEAL_SCHEMA),
        (SERVICE_GET_PLAN, get_plan, GET_PLAN_SCHEMA),
        (SERVICE_SUGGEST, suggest, SUGGEST_SCHEMA),
        (SERVICE_AUTO_PLAN, auto_plan, AUTO_PLAN_SCHEMA),
        (SERVICE_SHOPPING_LIST, shopping_list, SHOPPING_SCHEMA),
        (SERVICE_MARK_COOKED, mark_cooked, MARK_COOKED_SCHEMA),
        (SERVICE_MOVE_MEAL, move_meal, MOVE_MEAL_SCHEMA),
        (SERVICE_COPY_PLAN, copy_plan, COPY_PLAN_SCHEMA),
        (SERVICE_FIND_BY_INGREDIENTS, find_by_ingredients, FIND_BY_INGREDIENTS_SCHEMA),
        (SERVICE_GET_SHOPPING_LIST, get_shopping_list, GET_SHOPPING_LIST_SCHEMA),
        (SERVICE_EXPORT_RECIPES, export_recipes, EXPORT_SCHEMA),
        (SERVICE_IMPORT_RECIPES, import_recipes, IMPORT_RECIPES_SCHEMA),
        (SERVICE_CLEAR_SHOPPING, clear_shopping_list, CLEAR_SHOPPING_SCHEMA),
        (SERVICE_IMPORT_STARTER, import_starter_recipes, EMPTY_SCHEMA),
        (SERVICE_REFRESH_OFFERS, refresh_offers, EMPTY_SCHEMA),
        (SERVICE_SEARCH_OFFERS, search_offers, SEARCH_OFFERS_SCHEMA),
        (SERVICE_GET_OFFERS, get_offers, GET_OFFERS_SCHEMA),
        (SERVICE_ADD_OFFER, add_offer, ADD_OFFER_SCHEMA),
        (SERVICE_REMOVE_OFFER, remove_offer, REMOVE_OFFER_SCHEMA),
        (SERVICE_SET_PRICE, set_price, SET_PRICE_SCHEMA),
        (SERVICE_GET_COSTS, get_costs, GET_COSTS_SCHEMA),
        (SERVICE_GET_STORE_PRICES, get_store_prices, GET_STORE_PRICES_SCHEMA),
        (SERVICE_SAVE_BRANCH, save_branch, SAVE_BRANCH_SCHEMA),
        (SERVICE_REMOVE_BRANCH, remove_branch, REMOVE_BRANCH_SCHEMA),
        (SERVICE_GET_BRANCHES, get_branches, EMPTY_SCHEMA),
        (SERVICE_FIND_BRANCHES, find_branches, FIND_BRANCHES_SCHEMA),
        (SERVICE_SET_SHOPPING_STORE, set_shopping_store, SET_SHOPPING_STORE_SCHEMA),
        (SERVICE_ASSIGN_SHOPPING_STORES, assign_shopping_stores, ASSIGN_SHOPPING_STORES_SCHEMA),
        (SERVICE_COMPARE_PRICES, compare_prices, COMPARE_PRICES_SCHEMA),
        (SERVICE_ADD_SHOPPING_ITEM, add_shopping_item, ADD_SHOPPING_ITEM_SCHEMA),
        (SERVICE_REFRESH_PRICES, refresh_prices, REFRESH_PRICES_SCHEMA),
        (SERVICE_FIND_REWE_MARKETS, find_rewe_markets, FIND_REWE_MARKETS_SCHEMA),
        (SERVICE_FIND_EDEKA_MARKETS, find_edeka_markets, FIND_EDEKA_MARKETS_SCHEMA),
        (SERVICE_FIND_ALDI_STORES, find_aldi_stores, FIND_ALDI_STORES_SCHEMA),
        (SERVICE_SEARCH_PRODUCTS, search_products, SEARCH_PRODUCTS_SCHEMA),
        (SERVICE_SAVE_PRODUCT, save_product, SAVE_PRODUCT_SCHEMA),
        (SERVICE_SET_SHOPPING_PRODUCT, set_shopping_product, SET_SHOPPING_PRODUCT_SCHEMA),
        (SERVICE_GET_LEAFLETS, get_leaflets, GET_LEAFLETS_SCHEMA),
        (SERVICE_SORT_WITH_AI, sort_with_ai, SORT_WITH_AI_SCHEMA),
        (SERVICE_SAVE_OCCASION, save_occasion_service, SAVE_OCCASION_SCHEMA),
        (SERVICE_DELETE_OCCASION, delete_occasion_service, OCCASION_SCHEMA),
        (SERVICE_GET_OCCASIONS, get_occasions, GET_OCCASIONS_SCHEMA),
        (SERVICE_SUGGEST_OCCASION_MENU, suggest_occasion_menu, SUGGEST_OCCASION_MENU_SCHEMA),
        (SERVICE_SUGGEST_DRINKS, suggest_drinks_service, SUGGEST_DRINKS_SCHEMA),
    ]
    for name, handler, schema in services:
        hass.services.async_register(
            DOMAIN, name, handler, schema=schema, supports_response=SupportsResponse.OPTIONAL
        )
    # receipts are for admins (like their websockets, the upload and the image view);
    # calls without a user (automations, scripts) are allowed
    for name, handler, schema in (
        (SERVICE_RECEIPT_PARSE_TEXT, receipt_parse_text, RECEIPT_PARSE_TEXT_SCHEMA),
        (SERVICE_RECEIPT_SCAN, receipt_scan, RECEIPT_SCAN_SCHEMA),
        (SERVICE_RECEIPT_SAVE, receipt_save, RECEIPT_SAVE_SCHEMA),
        (SERVICE_GET_RECEIPTS, get_receipts, GET_RECEIPTS_SCHEMA),
        (SERVICE_DELETE_RECEIPT, delete_receipt, DELETE_RECEIPT_SCHEMA),
    ):
        async_register_admin_service(
            hass, DOMAIN, name, handler, schema=schema, supports_response=SupportsResponse.OPTIONAL
        )
