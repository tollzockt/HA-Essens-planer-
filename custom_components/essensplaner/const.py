"""Constants for the Essensplaner integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "essensplaner"
NAME: Final = "Essensplaner"

STORAGE_VERSION: Final = 1
STORAGE_KEY: Final = DOMAIN

EVENT_UPDATED: Final = f"{DOMAIN}_updated"

# Meal slots -----------------------------------------------------------------
MEAL_BREAKFAST: Final = "fruehstueck"
MEAL_LUNCH: Final = "mittagessen"
MEAL_SNACK: Final = "snack"
MEAL_DINNER: Final = "abendessen"

ALL_MEALS: Final = [MEAL_BREAKFAST, MEAL_LUNCH, MEAL_SNACK, MEAL_DINNER]

MEAL_LABELS: Final = {
    MEAL_BREAKFAST: "Frühstück",
    MEAL_LUNCH: "Mittagessen",
    MEAL_SNACK: "Snack",
    MEAL_DINNER: "Abendessen",
}

DEFAULT_MEAL_TIMES: Final = {
    MEAL_BREAKFAST: "07:30",
    MEAL_LUNCH: "12:30",
    MEAL_SNACK: "15:30",
    MEAL_DINNER: "18:30",
}

# Config / options -----------------------------------------------------------
CONF_IMPORT_STARTER: Final = "import_starter_recipes"
CONF_DEFAULT_SERVINGS: Final = "default_servings"
CONF_DEFAULT_MEAL: Final = "default_meal"
CONF_ENABLED_MEALS: Final = "enabled_meals"
CONF_PANTRY: Final = "pantry_staples"
CONF_SYNC_TODO: Final = "shopping_sync_entity"
CONF_REGISTER_INTENTS: Final = "register_intents"
CONF_SHOW_PANEL: Final = "show_panel"
CONF_MEAL_TIME_PREFIX: Final = "time_"
CONF_EXCLUDED: Final = "excluded"
CONF_AUTO_COOKED: Final = "auto_mark_cooked"

DEFAULT_SERVINGS: Final = 2
DEFAULT_MEAL: Final = MEAL_DINNER
DEFAULT_ENABLED_MEALS: Final = [MEAL_BREAKFAST, MEAL_LUNCH, MEAL_DINNER]
DEFAULT_PANTRY: Final = "Salz, Pfeffer, Wasser"

# Services -------------------------------------------------------------------
SERVICE_ADD_RECIPE: Final = "add_recipe"
SERVICE_UPDATE_RECIPE: Final = "update_recipe"
SERVICE_DELETE_RECIPE: Final = "delete_recipe"
SERVICE_IMPORT_RECIPE: Final = "import_recipe"
SERVICE_GET_RECIPES: Final = "get_recipes"
SERVICE_GET_RECIPE: Final = "get_recipe"
SERVICE_PLAN_MEAL: Final = "plan_meal"
SERVICE_REMOVE_MEAL: Final = "remove_meal"
SERVICE_GET_PLAN: Final = "get_plan"
SERVICE_SUGGEST: Final = "suggest_recipes"
SERVICE_AUTO_PLAN: Final = "auto_plan"
SERVICE_SHOPPING_LIST: Final = "generate_shopping_list"
SERVICE_MARK_COOKED: Final = "mark_cooked"
SERVICE_MOVE_MEAL: Final = "move_meal"
SERVICE_COPY_PLAN: Final = "copy_plan"
SERVICE_FIND_BY_INGREDIENTS: Final = "find_by_ingredients"
SERVICE_GET_SHOPPING_LIST: Final = "get_shopping_list"
SERVICE_EXPORT_RECIPES: Final = "export_recipes"
SERVICE_IMPORT_RECIPES: Final = "import_recipes"

# Attributes / service fields --------------------------------------------------
ATTR_RECIPE: Final = "recipe"
ATTR_RECIPE_ID: Final = "recipe_id"
ATTR_NAME: Final = "name"
ATTR_SERVINGS: Final = "servings"
ATTR_INGREDIENTS: Final = "ingredients"
ATTR_STEPS: Final = "steps"
ATTR_TAGS: Final = "tags"
ATTR_PREP_TIME: Final = "prep_time"
ATTR_COOK_TIME: Final = "cook_time"
ATTR_TOTAL_TIME: Final = "total_time"
ATTR_NOTES: Final = "notes"
ATTR_SOURCE_URL: Final = "source_url"
ATTR_IMAGE: Final = "image"
ATTR_FAVORITE: Final = "favorite"
ATTR_RATING: Final = "rating"
ATTR_URL: Final = "url"
ATTR_QUERY: Final = "query"
ATTR_TAG: Final = "tag"
ATTR_MAX_TIME: Final = "max_time"
ATTR_FAVORITES_ONLY: Final = "favorites_only"
ATTR_DATE: Final = "date"
ATTR_MEAL: Final = "meal"
ATTR_TITLE: Final = "title"
ATTR_NOTE: Final = "note"
ATTR_START_DATE: Final = "start_date"
ATTR_DAYS: Final = "days"
ATTR_COUNT: Final = "count"
ATTR_OVERWRITE: Final = "overwrite"
ATTR_SYNC: Final = "sync"

PANEL_URL_PATH: Final = DOMAIN
PANEL_STATIC_URL: Final = f"/{DOMAIN}_static"
PANEL_COMPONENT: Final = "essensplaner-panel"
CARD_FILE: Final = "essensplaner-card.js"
