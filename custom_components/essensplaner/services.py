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
import voluptuous as vol

from .const import (
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
    OFFERS_MARKTGURU,
    SERVICE_ADD_OFFER,
    SERVICE_ADD_RECIPE,
    SERVICE_AUTO_PLAN,
    SERVICE_CLEAR_SHOPPING,
    SERVICE_COPY_PLAN,
    SERVICE_DELETE_RECIPE,
    SERVICE_EXPORT_RECIPES,
    SERVICE_FIND_BY_INGREDIENTS,
    SERVICE_GET_BRANCHES,
    SERVICE_GET_COSTS,
    SERVICE_GET_OFFERS,
    SERVICE_GET_PLAN,
    SERVICE_GET_RECIPE,
    SERVICE_GET_RECIPES,
    SERVICE_GET_SHOPPING_LIST,
    SERVICE_GET_STORE_PRICES,
    SERVICE_IMPORT_RECIPE,
    SERVICE_IMPORT_RECIPES,
    SERVICE_IMPORT_STARTER,
    SERVICE_MARK_COOKED,
    SERVICE_MOVE_MEAL,
    SERVICE_PLAN_MEAL,
    SERVICE_REFRESH_OFFERS,
    SERVICE_REMOVE_BRANCH,
    SERVICE_REMOVE_MEAL,
    SERVICE_REMOVE_OFFER,
    SERVICE_SAVE_BRANCH,
    SERVICE_SEARCH_OFFERS,
    SERVICE_SET_PRICE,
    SERVICE_SHOPPING_LIST,
    SERVICE_SUGGEST,
    SERVICE_UPDATE_RECIPE,
    STRATEGIES,
)
from .dates import DateParseError, parse_date, parse_meal, week_start
from .ingredients import fold
from .offers import async_refresh_offers, async_search_target_offers
from .recipe_import import async_fetch_recipe

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
    }
)
SHOPPING_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_START_DATE): cv.string,
        vol.Optional(ATTR_DAYS, default=7): _DAYS,
        vol.Optional("replace", default=True): cv.boolean,
        vol.Optional(ATTR_SYNC, default=True): cv.boolean,
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
    }
)
REMOVE_BRANCH_SCHEMA = vol.Schema({vol.Required("branch"): cv.string})
GET_COSTS_SCHEMA = vol.Schema(
    {vol.Optional(ATTR_START_DATE): cv.string, vol.Optional(ATTR_DAYS): _DAYS}
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
    """Raise unless online offers are configured (zip code option or branches with postcode)."""
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
        entry = manager.plan_meal(
            day,
            meal,
            recipe=recipe,
            title=title,
            servings=call.data.get(ATTR_SERVINGS),
            note=call.data.get(ATTR_NOTE),
        )
        return {"entry": entry, "recipe_found": recipe is not None}

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
        recipes = manager.suggest(
            call.data[ATTR_COUNT],
            tag=call.data.get(ATTR_TAG),
            max_time=call.data.get(ATTR_MAX_TIME),
            meal=meal,
            around=around,
            strategy=resolve_strategy(call.data.get("strategy")),
        )
        return {
            "recipes": [
                {**manager.recipe_summary(r), "cost": manager.recipe_cost(r, None, around)["total"]}
                for r in recipes
            ]
        }

    async def auto_plan(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        start, _ = resolve_day(manager, call.data.get(ATTR_START_DATE))
        planned = manager.auto_plan(
            start,
            call.data[ATTR_DAYS],
            meals=resolve_meals(manager, call.data.get("meals")),
            tag=call.data.get(ATTR_TAG),
            max_time=call.data.get(ATTR_MAX_TIME),
            overwrite=call.data[ATTR_OVERWRITE],
            servings=call.data.get(ATTR_SERVINGS),
            strategy=resolve_strategy(call.data.get("strategy")),
        )
        return {"planned": planned, "week": manager.week_overview(start)}

    async def shopping_list(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        start, _ = resolve_day(manager, call.data.get(ATTR_START_DATE))
        result = manager.generate_shopping_list(
            start, call.data[ATTR_DAYS], replace=call.data["replace"]
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
        return get_manager(hass).shopping_overview()

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
        if targets:
            live, errors = await async_search_target_offers(hass, query, targets)
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
        return {"count": len(offers), "offers": offers, "meta": manager.offers_meta}

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
        (SERVICE_REMOVE_MEAL, remove_meal, REMOVE_MEAL_SCHEMA),
        (SERVICE_GET_PLAN, get_plan, GET_PLAN_SCHEMA),
        (SERVICE_SUGGEST, suggest, SUGGEST_SCHEMA),
        (SERVICE_AUTO_PLAN, auto_plan, AUTO_PLAN_SCHEMA),
        (SERVICE_SHOPPING_LIST, shopping_list, SHOPPING_SCHEMA),
        (SERVICE_MARK_COOKED, mark_cooked, MARK_COOKED_SCHEMA),
        (SERVICE_MOVE_MEAL, move_meal, MOVE_MEAL_SCHEMA),
        (SERVICE_COPY_PLAN, copy_plan, COPY_PLAN_SCHEMA),
        (SERVICE_FIND_BY_INGREDIENTS, find_by_ingredients, FIND_BY_INGREDIENTS_SCHEMA),
        (SERVICE_GET_SHOPPING_LIST, get_shopping_list, EMPTY_SCHEMA),
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
    ]
    for name, handler, schema in services:
        hass.services.async_register(
            DOMAIN, name, handler, schema=schema, supports_response=SupportsResponse.OPTIONAL
        )
