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
CONF_BUDGET: Final = "weekly_budget"
CONF_OFFERS_SOURCE: Final = "offers_source"
CONF_ZIP: Final = "zip_code"
CONF_STORES: Final = "offer_stores"
CONF_WATCHLIST: Final = "offers_watchlist"
CONF_STRATEGY: Final = "plan_strategy"

OFFERS_OFF: Final = "off"
OFFERS_MARKTGURU: Final = "marktguru"

# Stores (1.3): shopping list split "Hauptladen + Ausnahmen" ---------------------
CONF_SPLIT_MODE: Final = "store_split_mode"
SPLIT_OFF: Final = "off"
SPLIT_MAIN_ONLY: Final = "main_only"
SPLIT_MAIN_EXCEPTIONS: Final = "main_exceptions"
SPLIT_MODES: Final = [SPLIT_OFF, SPLIT_MAIN_ONLY, SPLIT_MAIN_EXCEPTIONS]
DEFAULT_SPLIT_MODE: Final = SPLIT_MAIN_EXCEPTIONS
# another store gets an item if its offer saves >= offer_min, or its real price is
# >= min_saving EUR or >= min_percent % cheaper (never less than SPLIT_FLOOR EUR)
CONF_SPLIT_MIN_SAVING: Final = "store_split_min_saving"
DEFAULT_SPLIT_MIN_SAVING: Final = 1.0
CONF_SPLIT_MIN_PERCENT: Final = "store_split_min_percent"
DEFAULT_SPLIT_MIN_PERCENT: Final = 20
CONF_SPLIT_OFFER_MIN: Final = "store_split_offer_min"
DEFAULT_SPLIT_OFFER_MIN: Final = 0.30
# minimum total saving per extra store (is the trip worth it?), 0 = off
CONF_SPLIT_TRIP_MIN: Final = "store_split_trip_min"
DEFAULT_SPLIT_TRIP_MIN: Final = 0
SPLIT_FLOOR: Final = 0.20
# branch search (OpenStreetMap): zones (None = zone.home + "arbeit"/"work" zones),
# radius around the zones, corridor along the way to work
CONF_BRANCH_ZONES: Final = "branch_zones"
DEFAULT_BRANCH_ZONES: Final = None
CONF_BRANCH_RADIUS: Final = "branch_radius_km"
DEFAULT_BRANCH_RADIUS: Final = 3
CONF_BRANCH_ROUTE: Final = "branch_route"
DEFAULT_BRANCH_ROUTE: Final = True
CONF_BRANCH_ROUTE_RADIUS: Final = "branch_route_radius_m"
DEFAULT_BRANCH_ROUTE_RADIUS: Final = 800
# experimental REWE online shop prices (opt-in)
CONF_REWE_ONLINE: Final = "rewe_online_prices"
DEFAULT_REWE_ONLINE: Final = False
# experimental ALDI SÜD prices and reduced articles (opt-in, 1.4)
CONF_ALDI_ONLINE: Final = "aldi_online_prices"
DEFAULT_ALDI_ONLINE: Final = False
# offers of the linked EDEKA market from edeka.de (opt-in, 1.4)
CONF_EDEKA_OFFERS: Final = "edeka_offers"
DEFAULT_EDEKA_OFFERS: Final = False
# receipts (Kassenzettel, 1.4): AI Task entity that reads receipt photos (None = only
# pasted receipt text, parsed locally)
CONF_RECEIPT_AI: Final = "receipt_ai_task_entity"
DEFAULT_RECEIPT_AI: Final = None
# AI via Home Assistant (1.5): an AI Task entity (ai_task.*) or a conversation agent
# (conversation.*) for menus, drinks, the seasonal plan and product matching – no API keys
# in the Essensplaner; receipt photos keep their own AI Task option (CONF_RECEIPT_AI) and
# fall back to this entity when it is an AI Task
CONF_AI_ENTITY: Final = "ai_entity"
DEFAULT_AI_ENTITY: Final = None
CONF_AI_FEATURES: Final = "ai_features"
AI_FEATURE_OCCASIONS: Final = "occasions"
AI_FEATURE_DRINKS: Final = "drinks"
AI_FEATURE_SEASON: Final = "season"
# 1.5.1: "products" sorts the articles of the product database, "recipes" the recipe kinds
# (both with a button and a weekly check of what is new; on by default)
AI_FEATURE_PRODUCTS: Final = "products"
AI_FEATURE_RECIPES: Final = "recipes"
AI_FEATURE_RECEIPTS: Final = "receipts"
AI_FEATURES: Final = [
    AI_FEATURE_OCCASIONS,
    AI_FEATURE_DRINKS,
    AI_FEATURE_SEASON,
    AI_FEATURE_PRODUCTS,
    AI_FEATURE_RECIPES,
    AI_FEATURE_RECEIPTS,
]
DEFAULT_AI_FEATURES: Final = [
    AI_FEATURE_OCCASIONS,
    AI_FEATURE_DRINKS,
    AI_FEATURE_SEASON,
    AI_FEATURE_PRODUCTS,
    AI_FEATURE_RECIPES,
    AI_FEATURE_RECEIPTS,
]
# planning (1.5): season in suggestions and the auto plan, occasions in the weekly budget,
# drink suggestions with alcohol (alcohol-free ones are always included)
CONF_SEASON_AWARE: Final = "season_aware"
DEFAULT_SEASON_AWARE: Final = True
CONF_OCCASIONS_IN_BUDGET: Final = "occasions_in_budget"
DEFAULT_OCCASIONS_IN_BUDGET: Final = True
CONF_DRINKS_ALCOHOL: Final = "drinks_alcohol"
DEFAULT_DRINKS_ALCOHOL: Final = True
# leaflets of all saved branches (1.5, only with marktguru)
CONF_ALL_LEAFLETS: Final = "all_leaflets"
DEFAULT_ALL_LEAFLETS: Final = True
# honest User-Agent of all HTTP clients (OpenStreetMap, REWE, ALDI SÜD, EDEKA, marktguru)
HTTP_USER_AGENT: Final = "HA-Essensplaner/1.5 (+https://github.com/tollzockt/HA-Essens-planer-)"

STRATEGY_BALANCED: Final = "balanced"
STRATEGY_CHEAP: Final = "cheap"
STRATEGY_OFFERS: Final = "offers"
STRATEGY_VARIETY: Final = "variety"
# 1.5: what is in season (season.py) – and the offers
STRATEGY_SEASONAL: Final = "seasonal"
STRATEGIES: Final = [
    STRATEGY_BALANCED,
    STRATEGY_CHEAP,
    STRATEGY_OFFERS,
    STRATEGY_VARIETY,
    STRATEGY_SEASONAL,
]

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
SERVICE_PLAN_LEFTOVER: Final = "plan_leftover"
SERVICE_REMOVE_MEAL: Final = "remove_meal"
SERVICE_GET_PLAN: Final = "get_plan"
SERVICE_SUGGEST: Final = "suggest_recipes"
SERVICE_AUTO_PLAN: Final = "auto_plan"
SERVICE_REPLAN_MEAL: Final = "replan_meal"
SERVICE_SHOPPING_LIST: Final = "generate_shopping_list"
SERVICE_MARK_COOKED: Final = "mark_cooked"
SERVICE_MOVE_MEAL: Final = "move_meal"
SERVICE_COPY_PLAN: Final = "copy_plan"
SERVICE_FIND_BY_INGREDIENTS: Final = "find_by_ingredients"
SERVICE_GET_SHOPPING_LIST: Final = "get_shopping_list"
SERVICE_EXPORT_RECIPES: Final = "export_recipes"
SERVICE_IMPORT_RECIPES: Final = "import_recipes"
SERVICE_CLEAR_SHOPPING: Final = "clear_shopping_list"
SERVICE_IMPORT_STARTER: Final = "import_starter_recipes"
SERVICE_REFRESH_OFFERS: Final = "refresh_offers"
SERVICE_SEARCH_OFFERS: Final = "search_offers"
SERVICE_GET_OFFERS: Final = "get_offers"
SERVICE_ADD_OFFER: Final = "add_offer"
SERVICE_REMOVE_OFFER: Final = "remove_offer"
SERVICE_SET_PRICE: Final = "set_price"
SERVICE_GET_COSTS: Final = "get_costs"
SERVICE_GET_STORE_PRICES: Final = "get_store_prices"
SERVICE_SAVE_BRANCH: Final = "save_branch"
SERVICE_REMOVE_BRANCH: Final = "remove_branch"
SERVICE_GET_BRANCHES: Final = "get_branches"
SERVICE_SET_SHOPPING_STORE: Final = "set_shopping_store"
SERVICE_ASSIGN_SHOPPING_STORES: Final = "assign_shopping_stores"
SERVICE_COMPARE_PRICES: Final = "compare_prices"
SERVICE_ADD_SHOPPING_ITEM: Final = "add_shopping_item"
SERVICE_FIND_BRANCHES: Final = "find_branches"
SERVICE_REFRESH_PRICES: Final = "refresh_prices"
SERVICE_FIND_REWE_MARKETS: Final = "find_rewe_markets"
SERVICE_FIND_ALDI_STORES: Final = "find_aldi_stores"
SERVICE_FIND_EDEKA_MARKETS: Final = "find_edeka_markets"
SERVICE_RECEIPT_PARSE_TEXT: Final = "receipt_parse_text"
SERVICE_RECEIPT_SCAN: Final = "receipt_scan"
SERVICE_RECEIPT_SAVE: Final = "receipt_save"
SERVICE_GET_RECEIPTS: Final = "get_receipts"
SERVICE_DELETE_RECEIPT: Final = "delete_receipt"
# product database (1.5)
SERVICE_SEARCH_PRODUCTS: Final = "search_products"
SERVICE_SAVE_PRODUCT: Final = "save_product"
SERVICE_SET_SHOPPING_PRODUCT: Final = "set_shopping_product"
SERVICE_GET_LEAFLETS: Final = "get_leaflets"
SERVICE_SORT_WITH_AI: Final = "sort_with_ai"
# occasions and drinks (1.5)
SERVICE_SAVE_OCCASION: Final = "save_occasion"
SERVICE_DELETE_OCCASION: Final = "delete_occasion"
SERVICE_GET_OCCASIONS: Final = "get_occasions"
SERVICE_SUGGEST_OCCASION_MENU: Final = "suggest_occasion_menu"
SERVICE_SUGGEST_DRINKS: Final = "suggest_drinks"
# sources of refresh_prices
PRICE_SOURCE_OFFERS: Final = "offers"
PRICE_SOURCE_REWE: Final = "rewe"
PRICE_SOURCE_ALDI: Final = "aldi"
PRICE_SOURCE_EDEKA: Final = "edeka"
PRICE_SOURCES: Final = [
    PRICE_SOURCE_OFFERS,
    PRICE_SOURCE_REWE,
    PRICE_SOURCE_ALDI,
    PRICE_SOURCE_EDEKA,
]

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
