"""Data management for the Essensplaner integration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
import difflib
import json
import logging
from pathlib import Path
import random
from typing import Any
import uuid

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .articles import ArticlesMixin, parse_pack_text
from .const import (
    ALL_MEALS,
    CONF_AUTO_COOKED,
    CONF_DEFAULT_MEAL,
    CONF_DEFAULT_SERVINGS,
    CONF_ENABLED_MEALS,
    CONF_EXCLUDED,
    CONF_MEAL_TIME_PREFIX,
    CONF_PANTRY,
    CONF_SYNC_TODO,
    DEFAULT_ENABLED_MEALS,
    DEFAULT_MEAL,
    DEFAULT_MEAL_TIMES,
    DEFAULT_PANTRY,
    DEFAULT_SERVINGS,
    DOMAIN,
    EVENT_UPDATED,
    MEAL_BREAKFAST,
    MEAL_LABELS,
    MEAL_SNACK,
    STORAGE_KEY,
    STORAGE_VERSION,
    STRATEGY_CHEAP,
)
from .dates import WEEKDAY_NAMES
from .economy import EconomyMixin, load_default_prices
from .ingredients import (
    aggregate,
    category_rank,
    fold,
    format_ingredient,
    guess_category,
    ingredient_key,
    is_pantry_item,
    normalize_ingredient,
    normalize_spoken_quantity,
    parse_ingredient,
    scale_ingredient,
    strip_article,
    to_base,
)
from .pricing import COUNT_UNITS, offer_pack, unit_price
from .stores import StoresMixin

_LOGGER = logging.getLogger(__name__)

SAVE_DELAY = 1

BREAKFAST_TAGS = {"fruehstueck", "breakfast", "brunch", "morgens"}
SNACK_TAGS = {
    "snack",
    "snacks",
    "dessert",
    "nachtisch",
    "kuchen",
    "gebaeck",
    "zwischenmahlzeit",
    "suessspeise",
}

MAIN_TAGS = {"hauptgericht", "hauptspeise", "mittagessen", "abendessen", "dinner", "lunch"}

# bundled recipes of version 1.0/1.1 (used to find the new ones on upgrade)
ORIGINAL_STARTER_NAMES = [
    "Spaghetti Bolognese",
    "Chili con Carne",
    "Gemüsecurry mit Kichererbsen",
    "Pfannkuchen",
    "Linsensuppe",
    "Ofengemüse mit Feta",
    "Hähnchen-Reis-Pfanne",
    "Kartoffelsuppe",
    "Lasagne",
    "Overnight Oats",
    "Shakshuka",
    "Hähnchen-Wraps",
    "Spaghetti Aglio e Olio",
    "Lachs mit Ofenkartoffeln und Brokkoli",
    "Bananenbrot",
]

# fields of a live offer kept with a shopping item that was added from it
_OFFER_COPY_FIELDS = (
    "id",
    "title",
    "product",
    "store",
    "store_id",
    "retailer",
    "price",
    "old_price",
    "unit_price",
    "base_unit",
    "pack_amount",
    "pack_unit",
    "valid_from",
    "valid_to",
    "source",
)

# German messages for errors (used by intents / voice answers)
ERROR_MESSAGES_DE = {
    "recipe_not_found": "Ich habe kein Rezept „{name}“ gefunden.",
    "recipe_exists": "Es gibt bereits ein Rezept „{name}“.",
    "name_required": "Bitte gib einen Namen an.",
    "invalid_date": "Ich habe das Datum „{date}“ nicht verstanden.",
    "invalid_meal": "Die Mahlzeit „{meal}“ kenne ich nicht.",
    "not_loaded": "Der Essensplaner ist nicht eingerichtet.",
    "no_recipe_found": "Auf der Seite {url} habe ich kein Rezept gefunden.",
    "download_failed": "Die Seite {url} konnte nicht geladen werden ({error}).",
    "invalid_url": "„{url}“ ist keine gültige Internetadresse.",
    "shopping_item_not_found": "Den Eintrag habe ich auf der Einkaufsliste nicht gefunden.",
    "meal_not_planned": "Am {date} ist zu dieser Mahlzeit nichts geplant.",
    "dish_not_planned": "„{name}“ ist in den nächsten Tagen nicht geplant.",
    "invalid_json": "Die Rezeptdaten konnten nicht gelesen werden.",
    "offers_disabled": "Online-Angebote sind nicht aktiviert (Essensplaner → Konfigurieren).",
    "invalid_zip": (
        "Bitte in den Optionen eine gültige Postleitzahl für Angebote eintragen "
        "oder eine Filiale mit Postleitzahl hinzufügen."
    ),
    "invalid_strategy": "Die Planungsart „{strategy}“ kenne ich nicht.",
    "invalid_price": "Den Preis „{price}“ habe ich nicht verstanden.",
    "unknown_store": "Den Laden „{store}“ kenne ich nicht.",
    "store_required": "Bitte gib den Laden an, z. B. Aldi Süd, Lidl oder REWE.",
    "invalid_postcode": "Die Postleitzahl „{postcode}“ ist ungültig (5 Ziffern).",
    "branch_not_found": "Die Filiale „{branch}“ habe ich nicht gefunden.",
    "branch_ambiguous": (
        "Es gibt mehrere Filialen zu „{branch}“ – bitte genauer angeben, z. B. mit der Straße."
    ),
    "overpass_busy": (
        "OpenStreetMap ist gerade ausgelastet – bitte in ein paar Minuten erneut versuchen."
    ),
    "overpass_timeout": (
        "OpenStreetMap hat nicht rechtzeitig geantwortet – bitte später erneut versuchen "
        "oder den Radius verkleinern."
    ),
    "overpass_failed": "Die Filialsuche bei OpenStreetMap ist fehlgeschlagen ({error}).",
    "branch_search_wait": (
        "Bitte warte noch {seconds} Sekunden bis zur nächsten Filialsuche – so wird "
        "OpenStreetMap nicht überlastet."
    ),
    "zone_not_found": "Die Zone „{zone}“ habe ich nicht gefunden.",
    "no_search_area": (
        "Keine Zone mit Koordinaten gefunden – lege in Home Assistant die Zone „Zuhause“ "
        "fest oder wähle Zonen aus."
    ),
    "store_split_off": (
        "Die Einkaufsliste wird gerade nicht nach Läden aufgeteilt. Dafür brauchst du einen "
        "Hauptladen (im Essensplaner-Panel unter „Läden und Preise“), und die Aufteilung nach "
        "Läden muss in den Optionen eingeschaltet sein."
    ),
    "rewe_disabled": (
        "REWE-Onlinepreise sind nicht aktiviert (experimentell, Essensplaner → Konfigurieren)."
    ),
    "rewe_no_market": (
        "Keine REWE-Filiale mit Markt-ID – füge eine REWE-Filiale hinzu und trage ihre "
        "Markt-ID ein (zu finden mit „REWE-Märkte suchen“)."
    ),
    "rewe_blocked": "Der REWE-Onlineshop lässt gerade keine automatischen Abfragen zu ({error}).",
    "rewe_failed": "Die Abfrage beim REWE-Onlineshop ist fehlgeschlagen ({error}).",
    "rewe_postcode_required": "Bitte gib eine Postleitzahl an (5 Ziffern).",
    "aldi_disabled": (
        "ALDI-SÜD-Onlinepreise sind nicht aktiviert (experimentell, Essensplaner → Konfigurieren)."
    ),
    "aldi_no_store": (
        "Keine ALDI-SÜD-Filiale – füge im Panel eine ALDI-SÜD-Filiale hinzu (am besten aus "
        "der Kartensuche) oder wähle sie mit „ALDI-SÜD-Filiale suchen“."
    ),
    "aldi_blocked": "Die ALDI-SÜD-Website lässt gerade keine automatischen Abfragen zu ({error}).",
    "aldi_failed": "Die Abfrage bei ALDI SÜD ist fehlgeschlagen ({error}).",
    "aldi_location_required": (
        "Für die Suche nach ALDI-SÜD-Filialen brauche ich einen Ort: gib Breiten- und "
        "Längengrad an, eine Postleitzahl einer deiner Filialen oder lege die Zone "
        "„Zuhause“ fest."
    ),
    "aldi_postcode_unknown": (
        "Die Postleitzahl {postcode} kenne ich von keiner deiner Filialen – ALDI SÜD sucht "
        "nur nach Koordinaten. Füge die Filiale aus der Kartensuche hinzu oder gib Breiten- "
        "und Längengrad an."
    ),
    "invalid_aldi_store": "„{value}“ ist keine gültige ALDI-SÜD-Filialnummer (z. B. B402).",
    "edeka_disabled": "EDEKA-Angebote sind nicht aktiviert (Essensplaner → Konfigurieren).",
    "edeka_no_market": (
        "Keine EDEKA-Filiale mit Markt-ID – füge eine EDEKA-Filiale hinzu und wähle ihren "
        "Markt (zu finden mit „EDEKA-Märkte suchen“)."
    ),
    "edeka_blocked": "Die EDEKA-Website lässt gerade keine automatischen Abfragen zu ({error}).",
    "edeka_failed": "Die Abfrage bei EDEKA ist fehlgeschlagen ({error}).",
    "edeka_postcode_required": "Bitte gib eine Postleitzahl an (5 Ziffern).",
    "invalid_edeka_market": "„{value}“ ist keine gültige EDEKA-Markt-ID (nur Ziffern).",
    "marktguru_blocked": "marktguru.de lässt gerade keine automatischen Abfragen zu ({error}).",
    "marktguru_failed": "Die Abfrage bei marktguru ist fehlgeschlagen ({error}).",
    "receipt_not_found": "Den Kassenzettel „{id}“ habe ich nicht gefunden.",
    "receipt_upload_not_found": (
        "Das hochgeladene Foto „{upload_id}“ gibt es nicht mehr – bitte den Kassenzettel "
        "nochmal hochladen."
    ),
    "receipt_no_items": "Auf dem Kassenzettel habe ich keine Artikel mit Preis gefunden.",
    "receipt_ai_not_configured": (
        "Für Fotos von Kassenzetteln brauche ich eine KI-Aufgabe (AI Task): wähle sie in den "
        "Optionen (Essensplaner → Konfigurieren → Läden & Einkauf) – oder füge den Text des "
        "Kassenzettels ein."
    ),
    "receipt_ai_unavailable": (
        "Die KI-Aufgabe {entity} ist gerade nicht verfügbar – bitte später erneut versuchen "
        "oder den Text des Kassenzettels einfügen."
    ),
    "receipt_ai_failed": "Die KI-Aufgabe konnte den Kassenzettel nicht lesen ({error}).",
    "receipt_ai_invalid": (
        "Die KI hat keinen lesbaren Kassenzettel zurückgegeben – bitte ein schärferes Foto "
        "versuchen oder den Text des Kassenzettels einfügen."
    ),
    "receipt_media_invalid": (
        "„{media}“ ist kein Kassenzettel-Bild aus dem Medienordner (JPG, PNG, WebP oder PDF)."
    ),
}


def error_message(err: HomeAssistantError) -> str:
    """Return a German message for an error raised by the manager."""
    key = getattr(err, "translation_key", None)
    if key in ERROR_MESSAGES_DE:
        try:
            return ERROR_MESSAGES_DE[key].format(**(err.translation_placeholders or {}))
        except (KeyError, IndexError):
            pass
    return str(err)


def _error(key: str, **placeholders: Any) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders={k: str(v) for k, v in placeholders.items()},
    )


def _split_lines(value: Any, separators: tuple[str, ...] = ("\n",)) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        result: list[str] = []
        for item in value:
            if isinstance(item, dict):
                continue
            result.extend(_split_lines(item, separators))
        return result
    text = str(value)
    for sep in separators[1:]:
        text = text.replace(sep, separators[0])
    return [line.strip(" \t-•*") for line in text.split(separators[0]) if line.strip(" \t-•*")]


def _to_int(value: Any, minimum: int | None = None) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    if minimum is not None and number < minimum:
        return None
    return number


class EssensplanerManager(ArticlesMixin, StoresMixin, EconomyMixin):
    """Holds recipes, the meal plan, the shopping list, prices and offers."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the manager."""
        self.hass = hass
        self.entry = entry
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry.entry_id}"
        )
        self.recipes: dict[str, dict[str, Any]] = {}
        self.plan: dict[str, dict[str, dict[str, Any]]] = {}
        self.shopping: list[dict[str, Any]] = []
        self._listeners: list[Callable[[], None]] = []
        self.starter_names: list[str] = []
        self.prices_user: dict[str, dict[str, Any]] = {}
        self.prices_learned: dict[str, dict[str, Any]] = {}
        self.offers: list[dict[str, Any]] = []
        self.offers_meta: dict[str, Any] = {}
        self.default_prices: list[dict[str, Any]] = []
        self._price_book = None
        self._offer_index = None
        self._cost_cache: dict[tuple, dict[str, Any]] = {}
        self._offer_name_cache: dict[tuple[str, str | None], list[dict[str, Any]]] = {}
        self._offer_day_cache: dict[date, Any] = {}
        self._recipes_using_cache: dict[tuple[str, ...], list[str]] = {}
        # set when the config entry is unloaded: late results of long refreshes are dropped
        # instead of overwriting the data of the new manager (options change = reload)
        self.unloaded = False
        self._offers_task: asyncio.Task[dict[str, Any]] | None = None  # running offer refresh
        from .catalog import OfferCatalog  # the catalog imports the mixins

        # all current offers of the saved stores (own file, 1.4)
        self.catalog = OfferCatalog(hass, entry.entry_id)
        from .receipts import ReceiptStore

        # stored receipts (Kassenzettel) and their images (own file, 1.4)
        self.receipts = ReceiptStore(hass, entry.entry_id)
        self._init_store_data()
        self._init_article_data()

    # ------------------------------------------------------------------
    # Options
    # ------------------------------------------------------------------

    @property
    def options(self) -> dict[str, Any]:
        """Return the merged config entry data/options."""
        return {**self.entry.data, **self.entry.options}

    @property
    def default_servings(self) -> int:
        """Default number of servings."""
        return _to_int(self.options.get(CONF_DEFAULT_SERVINGS), 1) or DEFAULT_SERVINGS

    @property
    def default_meal(self) -> str:
        """Default meal slot."""
        meal = self.options.get(CONF_DEFAULT_MEAL, DEFAULT_MEAL)
        return meal if meal in ALL_MEALS else DEFAULT_MEAL

    @property
    def enabled_meals(self) -> list[str]:
        """Meal slots in use, sorted by time."""
        meals = self.options.get(CONF_ENABLED_MEALS) or DEFAULT_ENABLED_MEALS
        meals = [m for m in meals if m in ALL_MEALS] or list(DEFAULT_ENABLED_MEALS)
        return sorted(meals, key=self.meal_time)

    @property
    def pantry(self) -> list[str]:
        """Pantry staples that never land on the shopping list."""
        text = self.options.get(CONF_PANTRY, DEFAULT_PANTRY) or ""
        return [p.strip() for p in str(text).replace(";", ",").split(",") if p.strip()]

    @property
    def excluded(self) -> list[str]:
        """Tags or ingredients that should never be suggested."""
        text = self.options.get(CONF_EXCLUDED) or ""
        return [p.strip() for p in str(text).replace(";", ",").split(",") if p.strip()]

    @property
    def auto_mark_cooked(self) -> bool:
        """Count planned meals as cooked once the day is over."""
        return bool(self.options.get(CONF_AUTO_COOKED, True))

    @property
    def sync_entity(self) -> str | None:
        """External todo list the shopping list is copied to."""
        return self.options.get(CONF_SYNC_TODO) or None

    def meal_time(self, meal: str) -> time:
        """Return the configured time of a meal slot."""
        value = self.options.get(f"{CONF_MEAL_TIME_PREFIX}{meal}") or DEFAULT_MEAL_TIMES.get(
            meal, "12:00"
        )
        parsed = dt_util.parse_time(str(value))
        return parsed or time(12, 0)

    def today(self) -> date:
        """Return today's local date."""
        return dt_util.now().date()

    # ------------------------------------------------------------------
    # Persistence & listeners
    # ------------------------------------------------------------------

    async def async_load(self, import_starter: bool = False) -> None:
        """Load data from storage."""
        data = await self._store.async_load()
        new_install = data is None
        if data is None:
            data = {"recipes": {}, "plan": {}, "shopping": [], "starter_names": []}
        self.recipes = data.get("recipes", {})
        # names of bundled recipes that were offered before (1.0/1.1 shipped 15 recipes)
        self.starter_names = list(
            data.get("starter_names", [] if new_install else ORIGINAL_STARTER_NAMES)
        )
        if import_starter:
            added = await self._async_add_new_starter_recipes()
            if added:
                _LOGGER.info("Added %d new bundled recipes", added)
        if new_install or import_starter:
            data["recipes"] = self.recipes
            data["starter_names"] = self.starter_names
            await self._store.async_save({**data})
        self.plan = data.get("plan", {})
        self.shopping = data.get("shopping", [])
        self.prices_user = data.get("prices", {})
        self.prices_learned = data.get("prices_learned", {})
        self.offers = data.get("offers", [])
        self.offers_meta = data.get("offers_meta", {})
        self._load_store_data(data)
        await self.catalog.async_load()
        self.catalog.prune(self.today())
        await self.receipts.async_load()
        self.default_prices = await self.hass.async_add_executor_job(load_default_prices)
        migrated = self._migrate_v2()
        expired = self.cleanup_offers()
        self.tag_offer_branches()
        # the store options (mode, thresholds) may have changed with this reload and offers
        # may have ended overnight: assign the open items again (no-op for 1.2 lists)
        before = [dict(i) for i in self.shopping]
        self._reassign_open_items()
        if migrated:
            await self.async_save_now()
        elif expired or self.shopping != before:
            self._save_later()

    async def async_save_now(self) -> None:
        """Write data to disk immediately."""
        await self._store.async_save(self._data_to_store())

    async def _async_add_new_starter_recipes(self) -> int:
        """Add bundled recipes that are new in this version (deleted ones stay deleted)."""
        pack = await self.hass.async_add_executor_job(_load_starter_recipes)
        seen = {fold(n) for n in self.starter_names}
        added = 0
        for recipe in pack:
            name = recipe.get("name", "")
            if fold(name) in seen:
                continue
            seen.add(fold(name))
            self.starter_names.append(name)
            if self.get_recipe_by_name(name):
                continue
            built = self._build_recipe(recipe)
            self.recipes[built["id"]] = built
            added += 1
        return added

    def _data_to_store(self) -> dict[str, Any]:
        return {
            "starter_names": self.starter_names,
            "recipes": self.recipes,
            "plan": self.plan,
            "shopping": self.shopping,
            "prices": self.prices_user,
            "prices_learned": self.prices_learned,
            "offers": self.offers,
            "offers_meta": self.offers_meta,
            **self._store_data(),
        }

    async def async_import_starter_recipes(self) -> dict[str, list[str]]:
        """Add all bundled recipes that are not in the collection yet."""
        recipes = await self.hass.async_add_executor_job(_load_starter_recipes)
        return self.import_recipes(recipes, overwrite=False)

    @callback
    def async_add_listener(self, update_callback: Callable[[], None]) -> Callable[[], None]:
        """Listen for data updates."""
        self._listeners.append(update_callback)

        @callback
        def remove_listener() -> None:
            if update_callback in self._listeners:
                self._listeners.remove(update_callback)

        return remove_listener

    @callback
    def _changed(self, change: str) -> None:
        if self.unloaded:
            return  # a refresh finished after a reload: never overwrite the new data
        if change.startswith("recipe"):
            self._recipes_using_cache = {}  # which recipes use an offer
        self._store.async_delay_save(self._data_to_store, SAVE_DELAY)
        for update_callback in list(self._listeners):
            update_callback()
        self.hass.bus.async_fire(EVENT_UPDATED, {"change": change})

    @callback
    def _save_later(self) -> None:
        """Save soon without notifying entities or the panel (e.g. caches)."""
        if self.unloaded:
            return
        self._store.async_delay_save(self._data_to_store, SAVE_DELAY)

    @callback
    def async_refresh_listeners(self) -> None:
        """Ask entities to refresh (e.g. at midnight)."""
        if self.unloaded:
            return
        for update_callback in list(self._listeners):
            update_callback()

    # ------------------------------------------------------------------
    # Recipes
    # ------------------------------------------------------------------

    def _build_recipe(
        self, data: dict[str, Any], existing: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        recipe = dict(existing or {})
        now = dt_util.utcnow().isoformat()
        if not existing:
            recipe.update(
                {
                    "id": uuid.uuid4().hex[:12],
                    "created": now,
                    "last_cooked": None,
                    "cooked_count": 0,
                    "favorite": False,
                    "rating": 0,
                    "tags": [],
                    "ingredients": [],
                    "steps": [],
                    "notes": "",
                    "source_url": "",
                    "image": "",
                    "prep_time": None,
                    "cook_time": None,
                    "total_time": None,
                    "servings": self.default_servings,
                }
            )
        if "name" in data:
            name = str(data["name"] or "").strip()
            if not name:
                raise _error("name_required")
            recipe["name"] = name
        if not recipe.get("name"):
            raise _error("name_required")
        if "servings" in data and data["servings"] not in (None, ""):
            recipe["servings"] = _to_int(data["servings"], 1) or recipe.get(
                "servings", self.default_servings
            )
        if "ingredients" in data and data["ingredients"] is not None:
            raw = data["ingredients"]
            items: list[Any]
            if isinstance(raw, str):
                items = _split_lines(raw, ("\n", ";"))
            elif isinstance(raw, list):
                items = [i for i in raw if i not in (None, "")]
            else:
                items = [raw]
            recipe["ingredients"] = [normalize_ingredient(i) for i in items]
        if "steps" in data and data["steps"] is not None:
            recipe["steps"] = _split_lines(data["steps"])
        if "tags" in data and data["tags"] is not None:
            tags = data["tags"]
            if isinstance(tags, str):
                tags = tags.split(",")
            seen: set[str] = set()
            clean: list[str] = []
            for tag in tags:
                tag = str(tag).strip()
                if tag and fold(tag) not in seen:
                    seen.add(fold(tag))
                    clean.append(tag)
            recipe["tags"] = clean
        for key in ("prep_time", "cook_time", "total_time"):
            if key in data:
                recipe[key] = _to_int(data[key], 0)
        if recipe.get("total_time") is None and (
            recipe.get("prep_time") or recipe.get("cook_time")
        ):
            recipe["total_time"] = (recipe.get("prep_time") or 0) + (recipe.get("cook_time") or 0)
        for key in ("notes", "source_url", "image"):
            if key in data and data[key] is not None:
                recipe[key] = str(data[key]).strip()
        if "favorite" in data and data["favorite"] is not None:
            recipe["favorite"] = bool(data["favorite"])
        if "rating" in data and data["rating"] is not None:
            recipe["rating"] = max(0, min(5, _to_int(data["rating"]) or 0))
        recipe["updated"] = now
        return recipe

    def add_recipe(self, data: dict[str, Any], allow_duplicate: bool = False) -> dict[str, Any]:
        """Add a recipe."""
        name = str(data.get("name") or "").strip()
        if not name:
            raise _error("name_required")
        if not allow_duplicate and (existing := self.get_recipe_by_name(name)):
            raise _error("recipe_exists", name=existing["name"])
        recipe = self._build_recipe(data)
        self.recipes[recipe["id"]] = recipe
        self._changed("recipe_added")
        return recipe

    def upsert_imported_recipe(self, data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Add or update an imported recipe (matched by source URL)."""
        url = data.get("source_url")
        for recipe in self.recipes.values():
            if url and recipe.get("source_url") == url:
                updated = self._build_recipe(data, recipe)
                self.recipes[updated["id"]] = updated
                self._changed("recipe_updated")
                return updated, False
        name = data.get("name") or ""
        if self.get_recipe_by_name(name):
            data = {**data, "name": f"{name} (Import)"}
        recipe = self._build_recipe(data)
        self.recipes[recipe["id"]] = recipe
        self._changed("recipe_added")
        return recipe, True

    def update_recipe(self, recipe_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update an existing recipe."""
        recipe = self.recipes.get(recipe_id)
        if recipe is None:
            raise _error("recipe_not_found", name=recipe_id)
        updated = self._build_recipe(data, recipe)
        self.recipes[recipe_id] = updated
        # keep plan titles in sync
        for meals in self.plan.values():
            for entry in meals.values():
                if entry.get("recipe_id") == recipe_id:
                    entry["title"] = updated["name"]
        self._changed("recipe_updated")
        return updated

    def delete_recipe(self, recipe_id: str) -> dict[str, Any]:
        """Delete a recipe. Planned meals keep their title."""
        recipe = self.recipes.pop(recipe_id, None)
        if recipe is None:
            raise _error("recipe_not_found", name=recipe_id)
        for meals in self.plan.values():
            for entry in meals.values():
                if entry.get("recipe_id") == recipe_id:
                    entry["recipe_id"] = None
        self._changed("recipe_deleted")
        return recipe

    def get_recipe_by_name(self, name: str) -> dict[str, Any] | None:
        """Exact (case/umlaut-insensitive) name match."""
        key = fold(name)
        for recipe in self.recipes.values():
            if fold(recipe["name"]) == key:
                return recipe
        return None

    def find_recipe(self, query: str | None) -> dict[str, Any] | None:
        """Find the best matching recipe for a (spoken) name."""
        if not query:
            return None
        if query in self.recipes:
            return self.recipes[query]
        key = fold(query)
        if not key:
            return None
        by_key = {fold(r["name"]): r for r in self.recipes.values()}
        if key in by_key:
            return by_key[key]
        contains = [r for k, r in by_key.items() if key in k]
        if contains:
            # ambiguous ("Bolognese"): favourites, often cooked, classics, then the shortest name
            return min(
                contains,
                key=lambda r: (
                    not r.get("favorite"),
                    -(r.get("cooked_count") or 0),
                    -(r.get("rating") or 0),
                    "klassiker" not in self.recipe_tags_folded(r),
                    len(r["name"]),
                ),
            )
        contained = [r for k, r in by_key.items() if k and k in key]
        if contained:
            return max(contained, key=lambda r: len(r["name"]))
        close = difflib.get_close_matches(key, list(by_key), n=1, cutoff=0.72)
        if close:
            return by_key[close[0]]
        # token overlap ("Bolognese" -> "Spaghetti Bolognese")
        words = {w for w in key.split() if len(w) > 3}
        best: tuple[float, dict[str, Any] | None] = (0.0, None)
        for name_key, recipe in by_key.items():
            name_words = set(name_key.split())
            if not words or not name_words:
                continue
            score = 0.0
            for word in words:
                for name_word in name_words:
                    ratio = difflib.SequenceMatcher(None, word, name_word).ratio()
                    if ratio > 0.8:
                        score += ratio
            if score > best[0]:
                best = (score, recipe)
        return best[1]

    def resolve_recipe(
        self, recipe_id: str | None = None, name: str | None = None
    ) -> dict[str, Any]:
        """Return a recipe by id or name or raise."""
        if recipe_id and recipe_id in self.recipes:
            return self.recipes[recipe_id]
        if recipe := self.find_recipe(name or recipe_id):
            return recipe
        raise _error("recipe_not_found", name=name or recipe_id or "")

    @staticmethod
    def recipe_tags_folded(recipe: dict[str, Any]) -> set[str]:
        """Folded tags of a recipe."""
        return {fold(t) for t in recipe.get("tags", [])}

    def search_recipes(
        self,
        query: str | None = None,
        tag: str | None = None,
        max_time: int | None = None,
        favorites_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Search recipes by text (name, tags, ingredients), tag and time."""
        result = []
        qkey = fold(query) if query else ""
        tkey = fold(tag) if tag else ""
        for recipe in self.recipes.values():
            if favorites_only and not recipe.get("favorite"):
                continue
            if tkey and not any(tkey == t or tkey in t for t in self.recipe_tags_folded(recipe)):
                continue
            if max_time and (recipe.get("total_time") or 0) > max_time:
                continue
            if qkey:
                haystack = " ".join(
                    [
                        fold(recipe["name"]),
                        " ".join(self.recipe_tags_folded(recipe)),
                        " ".join(fold(i.get("name", "")) for i in recipe.get("ingredients", [])),
                    ]
                )
                if not all(word in haystack for word in qkey.split()):
                    continue
            result.append(recipe)
        result.sort(key=lambda r: (not r.get("favorite"), fold(r["name"])))
        return result

    def recipe_summary(self, recipe: dict[str, Any]) -> dict[str, Any]:
        """Short representation of a recipe."""
        return {
            "id": recipe["id"],
            "name": recipe["name"],
            "servings": recipe.get("servings"),
            "total_time": recipe.get("total_time"),
            "tags": recipe.get("tags", []),
            "favorite": recipe.get("favorite", False),
            "rating": recipe.get("rating", 0),
            "last_cooked": recipe.get("last_cooked"),
            "cooked_count": recipe.get("cooked_count", 0),
            "image": recipe.get("image") or None,
        }

    def recipe_view(self, recipe: dict[str, Any], servings: int | None = None) -> dict[str, Any]:
        """Full recipe, scaled to the given servings."""
        base = recipe.get("servings") or self.default_servings
        target = servings or base
        factor = target / base if base else 1
        ingredients = [scale_ingredient(i, factor) for i in recipe.get("ingredients", [])]
        return {
            **recipe,
            "servings": target,
            "original_servings": base,
            "ingredients": ingredients,
            "ingredient_lines": [format_ingredient(i) for i in ingredients],
            "cost": self.recipe_cost(recipe, target),
        }

    def mark_cooked(
        self, recipe: dict[str, Any] | None, day: date | None = None, meal: str | None = None
    ) -> dict[str, Any] | None:
        """Mark a recipe (and the planned meal) as cooked."""
        day = day or self.today()
        meals = self.plan.get(day.isoformat(), {})
        entry = None
        if meal and meal in meals:
            entry = meals[meal]
        elif recipe is None and meals:
            entry = next(iter(meals.values()))
        elif recipe is not None:
            entry = next((e for e in meals.values() if e.get("recipe_id") == recipe["id"]), None)
        already = False
        if entry is not None:
            already = bool(entry.get("cooked"))
            entry["cooked"] = True
            entry.pop("auto_cooked", None)
            if recipe is None and entry.get("recipe_id"):
                recipe = self.recipes.get(entry["recipe_id"])
        if recipe is not None and not already:
            self._count_cooked(recipe, day)
        self._changed("cooked")
        return recipe

    @staticmethod
    def _count_cooked(recipe: dict[str, Any], day: date) -> None:
        last = recipe.get("last_cooked")
        if not last or last < day.isoformat():
            recipe["last_cooked"] = day.isoformat()
        recipe["cooked_count"] = int(recipe.get("cooked_count") or 0) + 1

    @callback
    def async_auto_mark_cooked(self) -> int:
        """Count past planned meals (last 7 days) as cooked."""
        if not self.auto_mark_cooked:
            return 0
        today = self.today()
        start = (today - timedelta(days=7)).isoformat()
        count = 0
        for key in sorted(self.plan):
            if not start <= key < today.isoformat():
                continue
            for entry in self.plan[key].values():
                recipe = self.recipes.get(entry.get("recipe_id") or "")
                if recipe is None or entry.get("cooked"):
                    continue
                entry["cooked"] = True
                entry["auto_cooked"] = True
                self._count_cooked(recipe, date.fromisoformat(key))
                count += 1
        if count:
            self._changed("cooked")
        return count

    # ------------------------------------------------------------------
    # Meal plan
    # ------------------------------------------------------------------

    def plan_meal(
        self,
        day: date,
        meal: str,
        recipe: dict[str, Any] | None = None,
        title: str | None = None,
        servings: int | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Put a recipe (or free text) into the meal plan."""
        if meal not in ALL_MEALS:
            raise _error("invalid_meal", meal=meal)
        if recipe is None and not (title or "").strip():
            raise _error("name_required")
        entry = {
            "recipe_id": recipe["id"] if recipe else None,
            "title": recipe["name"] if recipe else str(title).strip(),
            "servings": servings or self.default_servings,
            "note": (note or "").strip(),
            "cooked": False,
            "added": dt_util.utcnow().isoformat(),
        }
        self.plan.setdefault(day.isoformat(), {})[meal] = entry
        self._cleanup_plan()
        self._changed("plan")
        return self.entry_view(day, meal, entry)

    def remove_meal(self, day: date, meal: str | None = None) -> list[dict[str, Any]]:
        """Remove one meal or a whole day from the plan."""
        key = day.isoformat()
        meals = self.plan.get(key, {})
        removed: list[dict[str, Any]] = []
        for slot in list(meals):
            if meal is None or slot == meal:
                removed.append(self.entry_view(day, slot, meals.pop(slot)))
        if not meals:
            self.plan.pop(key, None)
        if removed:
            self._changed("plan")
        return removed

    def move_meal(
        self, from_day: date, from_meal: str, to_day: date, to_meal: str
    ) -> dict[str, Any]:
        """Move a planned meal. An occupied target is swapped."""
        for meal in (from_meal, to_meal):
            if meal not in ALL_MEALS:
                raise _error("invalid_meal", meal=meal)
        source = self.plan.get(from_day.isoformat(), {})
        if from_meal not in source:
            raise _error("meal_not_planned", date=from_day.isoformat())
        entry = source.pop(from_meal)
        target = self.plan.setdefault(to_day.isoformat(), {})
        swapped = target.pop(to_meal, None)
        target[to_meal] = entry
        if swapped is not None:
            self.plan.setdefault(from_day.isoformat(), {})[from_meal] = swapped
        for key in (from_day.isoformat(), to_day.isoformat()):
            if not self.plan.get(key):
                self.plan.pop(key, None)
        self._changed("plan")
        return {
            "moved": self.entry_view(to_day, to_meal, entry),
            "swapped": self.entry_view(from_day, from_meal, swapped) if swapped else None,
        }

    def copy_plan(
        self, source: date, target: date, days: int = 7, overwrite: bool = False
    ) -> list[dict[str, Any]]:
        """Copy the plan of a range of days (e.g. last week) to another start date."""
        copied: list[dict[str, Any]] = []
        for offset in range(max(1, days)):
            src_day = source + timedelta(days=offset)
            dst_day = target + timedelta(days=offset)
            for meal, entry in self.plan.get(src_day.isoformat(), {}).items():
                existing = self.plan.get(dst_day.isoformat(), {})
                if meal in existing and not overwrite:
                    continue
                new_entry = {
                    **entry,
                    "cooked": False,
                    "added": dt_util.utcnow().isoformat(),
                }
                new_entry.pop("auto_cooked", None)
                self.plan.setdefault(dst_day.isoformat(), {})[meal] = new_entry
                copied.append(self.entry_view(dst_day, meal, new_entry))
        if copied:
            self._changed("plan")
        return copied

    def find_planned(
        self, dish: str, around: date | None = None, days: int = 14
    ) -> tuple[date, str] | None:
        """Find the closest planned meal (today or later first) matching a dish name."""
        around = around or self.today()
        dish = strip_article(dish)
        key = fold(dish)
        recipe = self.find_recipe(dish)
        for offset in sorted(range(-3, days), key=lambda o: (o < 0, abs(o))):
            day = around + timedelta(days=offset)
            for view in self.day_meals(day):
                if (recipe and view.get("recipe_id") == recipe["id"]) or (
                    key and key in fold(view["title"])
                ):
                    return day, view["meal"]
        return None

    def _cleanup_plan(self) -> None:
        """Drop plan entries older than one year."""
        limit = (self.today() - timedelta(days=365)).isoformat()
        for key in [k for k in self.plan if k < limit]:
            self.plan.pop(key, None)

    def entry_view(self, day: date, meal: str, entry: dict[str, Any]) -> dict[str, Any]:
        """Return a plan entry enriched with labels and recipe info."""
        recipe = self.recipes.get(entry.get("recipe_id") or "")
        meal_time = self.meal_time(meal)
        return {
            "date": day.isoformat(),
            "weekday": WEEKDAY_NAMES[day.weekday()],
            "meal": meal,
            "meal_label": MEAL_LABELS.get(meal, meal),
            "time": meal_time.strftime("%H:%M"),
            "title": entry.get("title") or (recipe["name"] if recipe else ""),
            "recipe_id": recipe["id"] if recipe else None,
            "servings": entry.get("servings"),
            "note": entry.get("note", ""),
            "cooked": entry.get("cooked", False),
            "total_time": recipe.get("total_time") if recipe else None,
            "image": (recipe.get("image") or None) if recipe else None,
        }

    def day_meals(self, day: date) -> list[dict[str, Any]]:
        """All planned meals of a day, sorted by time."""
        meals = self.plan.get(day.isoformat(), {})
        views = [self.entry_view(day, meal, entry) for meal, entry in meals.items()]
        views.sort(key=lambda v: (v["time"], ALL_MEALS.index(v["meal"])))
        return views

    def plan_range(self, start: date, days: int) -> list[dict[str, Any]]:
        """Plan for a range of days."""
        return [
            {
                "date": (start + timedelta(days=offset)).isoformat(),
                "weekday": WEEKDAY_NAMES[(start + timedelta(days=offset)).weekday()],
                "meals": self.day_meals(start + timedelta(days=offset)),
            }
            for offset in range(max(1, days))
        ]

    def meal_datetime(self, day: date, meal: str) -> datetime:
        """Local datetime of a meal."""
        return datetime.combine(day, self.meal_time(meal), tzinfo=dt_util.get_default_time_zone())

    def next_meal(self, now: datetime | None = None) -> dict[str, Any] | None:
        """Return the next upcoming (or currently running) meal."""
        now = now or dt_util.now()
        today = now.date()
        for offset in range(0, 15):
            day = today + timedelta(days=offset)
            for view in self.day_meals(day):
                start = self.meal_datetime(day, view["meal"])
                if start + timedelta(minutes=45) >= now:
                    return view
        return None

    # ------------------------------------------------------------------
    # Suggestions & auto planning
    # ------------------------------------------------------------------

    def _fits_meal(self, recipe: dict[str, Any], meal: str | None) -> bool:
        tags = self.recipe_tags_folded(recipe)
        is_breakfast = bool(tags & BREAKFAST_TAGS)
        is_snack = bool(tags & SNACK_TAGS)
        if meal == MEAL_BREAKFAST:
            return is_breakfast
        if meal == MEAL_SNACK:
            return is_snack
        if meal is None:
            return True
        return bool(tags & MAIN_TAGS) or not (is_breakfast or is_snack)

    def is_excluded(self, recipe: dict[str, Any]) -> bool:
        """True if the recipe has an excluded tag or ingredient."""
        excluded = self.excluded
        if not excluded:
            return False
        tags = self.recipe_tags_folded(recipe)
        names = [i.get("name", "") for i in recipe.get("ingredients", [])]
        for item in excluded:
            key = fold(item)
            if key in tags:
                return True
            if any(is_pantry_item(name, [item]) or key in fold(name) for name in names):
                return True
        return False

    def find_by_ingredients(
        self, available: list[str], count: int = 5, meal: str | None = None
    ) -> list[dict[str, Any]]:
        """Rank recipes by how well they use the given ingredients."""
        wanted = [(a.strip(), ingredient_key(a)) for a in available if a and a.strip()]
        wanted = [(a, k) for a, k in wanted if k]
        if not wanted:
            return []
        results = []
        for recipe in self.recipes.values():
            if meal and not self._fits_meal(recipe, meal):
                continue
            relevant = [
                i
                for i in recipe.get("ingredients", [])
                if i.get("name") and not is_pantry_item(i["name"], self.pantry)
            ]
            if not relevant:
                continue
            used: set[str] = set()
            matched_ingredients: set[int] = set()
            for label, key in wanted:
                for index, ingredient in enumerate(relevant):
                    ikey = ingredient_key(ingredient["name"])
                    if key == ikey or key in ikey or (len(ikey) > 3 and ikey in key):
                        used.add(label)
                        matched_ingredients.add(index)
            if not used:
                continue
            missing = [
                format_ingredient(i) for n, i in enumerate(relevant) if n not in matched_ingredients
            ]
            results.append(
                {
                    **self.recipe_summary(recipe),
                    "uses": sorted(used),
                    "missing": missing,
                    "coverage": round(len(matched_ingredients) / len(relevant), 2),
                }
            )
        results.sort(
            key=lambda r: (-len(r["uses"]), -r["coverage"], len(r["missing"]), fold(r["name"]))
        )
        return results[: max(1, count)]

    def suggest(
        self,
        count: int = 3,
        tag: str | None = None,
        max_time: int | None = None,
        meal: str | None = None,
        around: date | None = None,
        exclude: set[str] | None = None,
        rng: random.Random | None = None,
        strategy: str | None = None,
        target_cost: float | None = None,
        servings: int | None = None,
    ) -> list[dict[str, Any]]:
        """Suggest recipes.

        Prefers favourites, things not cooked lately, recipes with ingredients on offer,
        recipes that fit the remaining budget and dishes that differ from the
        neighbouring days.
        """
        rng = rng or random.Random()
        exclude = exclude or set()
        around = around or self.today()
        candidates = [
            r
            for r in self.search_recipes(tag=tag, max_time=max_time)
            if r["id"] not in exclude and self._fits_meal(r, meal) and not self.is_excluded(r)
        ]
        recently_planned: set[str] = set()
        for offset in range(-6, 7):
            for entry in self.plan.get((around + timedelta(days=offset)).isoformat(), {}).values():
                if entry.get("recipe_id"):
                    recently_planned.add(entry["recipe_id"])

        if target_cost is None and self.weekly_budget:
            target_cost = self.budget_target(around)
        median = self.median_cost(around, servings) if strategy == STRATEGY_CHEAP else None
        neighbours = self._neighbour_signatures(around)
        weights = []
        for recipe in candidates:
            weight = 1.0
            last = recipe.get("last_cooked")
            if not last:
                weight += 1.5
            else:
                try:
                    days_ago = (around - date.fromisoformat(last)).days
                    weight += min(max(days_ago, 0), 60) / 15
                    if days_ago < 5:
                        weight *= 0.2
                except ValueError:
                    pass
            if recipe.get("favorite"):
                weight += 2
            weight += (recipe.get("rating") or 0) * 0.4
            if recipe["id"] in recently_planned:
                weight *= 0.1
            weight *= self.economy_weight(
                recipe,
                around,
                strategy=strategy,
                target_cost=target_cost,
                median_cost=median,
                servings=servings,
                neighbours=neighbours,
            )
            weights.append(weight)

        chosen: list[dict[str, Any]] = []
        pool = list(zip(candidates, weights, strict=True))
        while pool and len(chosen) < max(1, count):
            total = sum(w for _, w in pool)
            pick = rng.uniform(0, total)
            upto = 0.0
            for index, (recipe, weight) in enumerate(pool):
                upto += weight
                if upto >= pick:
                    chosen.append(recipe)
                    pool.pop(index)
                    break
            else:  # pragma: no cover - floating point safety
                chosen.append(pool.pop()[0])
        return chosen

    def auto_plan(
        self,
        start: date,
        days: int,
        meals: list[str] | None = None,
        tag: str | None = None,
        max_time: int | None = None,
        overwrite: bool = False,
        servings: int | None = None,
        strategy: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fill empty slots of the plan with suggestions (budget, offers and variety aware)."""
        meals = meals or [self.default_meal]
        planned: list[dict[str, Any]] = []
        used: set[str] = set()
        # dishes already planned around these days are not planned a second time
        nearby: set[str] = set()
        for offset in range(-6, max(1, days) + 6):
            day = start + timedelta(days=offset)
            for meal, entry in self.plan.get(day.isoformat(), {}).items():
                replaced = overwrite and 0 <= offset < max(1, days) and meal in meals
                if entry.get("recipe_id") and not replaced:
                    nearby.add(entry["recipe_id"])
        for offset in range(max(1, days)):
            day = start + timedelta(days=offset)
            existing = self.plan.get(day.isoformat(), {})
            for meal in meals:
                if meal in existing and not overwrite:
                    continue
                target = self.budget_target(day, len(meals)) if self.weekly_budget else None
                options = {
                    "tag": tag,
                    "max_time": max_time,
                    "meal": meal,
                    "around": day,
                    "strategy": strategy,
                    "target_cost": target,
                    "servings": servings or self.default_servings,
                }
                suggestion = self.suggest(1, exclude=used | nearby, **options)
                if not suggestion and nearby:
                    suggestion = self.suggest(1, exclude=used, **options)  # few recipes
                if not suggestion:
                    continue
                recipe = suggestion[0]
                used.add(recipe["id"])
                entry = {
                    "recipe_id": recipe["id"],
                    "title": recipe["name"],
                    "servings": servings or self.default_servings,
                    "note": "",
                    "cooked": False,
                    "added": dt_util.utcnow().isoformat(),
                }
                self.plan.setdefault(day.isoformat(), {})[meal] = entry
                planned.append(self.entry_view(day, meal, entry))
        if planned:
            self._changed("plan")
        return planned

    # ------------------------------------------------------------------
    # Shopping list
    # ------------------------------------------------------------------

    def generate_shopping_list(
        self, start: date, days: int, replace: bool = True
    ) -> dict[str, Any]:
        """Create shopping list items from the planned recipes."""
        entries: list[tuple[dict[str, Any], str]] = []
        meal_count = 0
        free_text: list[str] = []
        for offset in range(max(1, days)):
            day = start + timedelta(days=offset)
            for entry in self.plan.get(day.isoformat(), {}).values():
                recipe = self.recipes.get(entry.get("recipe_id") or "")
                if recipe is None:
                    if entry.get("title"):
                        free_text.append(entry["title"])
                    continue
                meal_count += 1
                base = recipe.get("servings") or self.default_servings
                factor = (entry.get("servings") or base) / base
                entries.extend(
                    (scale_ingredient(i, factor), recipe["name"])
                    for i in recipe.get("ingredients", [])
                )

        aggregated = aggregate(entries, self.pantry)
        total_price = self.price_shopping_items(aggregated, start)
        previous = {i.get("key"): i for i in self.shopping if i.get("source") == "plan"}
        if replace:
            self.shopping = [i for i in self.shopping if i.get("source") != "plan"]

        new_items: list[dict[str, Any]] = []
        for item in aggregated:
            old = previous.get(item["key"])
            status = (
                "completed"
                if old
                and old.get("status") == "completed"
                and old.get("summary") == item["summary"]
                else "needs_action"
            )
            shopping_item = {
                "uid": uuid.uuid4().hex,
                "summary": item["summary"],
                "status": status,
                "description": "",
                "source": "plan",
                "key": item["key"],
                "category": item["category"],
                "price": item.get("price"),
                "offer": item.get("offer"),
                # 1.3: amounts/packs for store prices, recipes for the description
                "name": item["name"],
                "amounts": dict(item["amounts"]),
                "packs": item.get("packs") if item.get("price") is not None else None,
                "recipes": list(item["recipes"]),
            }
            if old and old.get("store_override"):
                shopping_item["store_override"] = old["store_override"]
            new_items.append(shopping_item)
        if self.assign_stores(new_items, start):
            total_price = round(sum(i["price"] for i in new_items if i.get("price") is not None), 2)
        for shopping_item in new_items:
            self.update_shopping_description(shopping_item)
        self.shopping.extend(new_items)
        self._changed("shopping")
        return {
            "start_date": start.isoformat(),
            "days": days,
            "meals": meal_count,
            "meals_without_recipe": free_text,
            "total_price": total_price,
            "items": [
                {
                    "summary": i["summary"],
                    "category": i["category"],
                    "description": i["description"],
                    "status": i["status"],
                    "price": i.get("price"),
                    "offer": i.get("offer"),
                    **{
                        field: i.get(field)
                        for field in ("branch_id", "retailer", "store_label", "store_reason")
                        if field in i
                    },
                }
                for i in new_items
            ],
            "stores": self.stores_summary(),
        }

    def shopping_clear(self, mode: str = "all") -> int:
        """Empty the shopping list. mode: all | completed | plan (generated items)."""
        before = len(self.shopping)
        if mode == "completed":
            self.shopping = [i for i in self.shopping if i.get("status") != "completed"]
        elif mode == "plan":
            self.shopping = [i for i in self.shopping if i.get("source") != "plan"]
        else:
            self.shopping = []
        removed = before - len(self.shopping)
        if removed:
            self._changed("shopping")
        return removed

    def shopping_add(
        self,
        summary: str,
        description: str | None = None,
        status: str = "needs_action",
        store: str | None = None,
        price: float | None = None,
        pack: str | None = None,
        offer_id: str | None = None,
    ) -> dict[str, Any]:
        """Add a manual shopping item.

        store: branch (id, label, store name) to buy it at (a manual store choice).
        price/pack: price of one pack and its size as chosen by the user (e.g. from the
        article search); offer_id: a saved offer (its store, price and pack).
        Without them the price is estimated at the main store (or the given store).
        Spoken amounts become digits ("zwei Liter Milch" -> "2 Liter Milch").
        """
        summary = normalize_spoken_quantity(str(summary or "").strip())
        parsed = parse_ingredient(summary)
        name = parsed["name"] or summary
        amounts: dict[str, float] = {}
        if parsed["amount"] is not None:
            amount, unit = to_base(parsed["amount"], parsed["unit"])
            if amount:
                amounts[unit] = amount
        item: dict[str, Any] = {
            "uid": uuid.uuid4().hex,
            "summary": summary,
            "status": status,
            "description": description or "",
            "source": "manual",
            "key": ingredient_key(name),
            "category": guess_category(name),
            "name": name,
            "amounts": amounts,
        }
        offer = self._picked_offer(offer_id) if offer_id else None
        branch = self.resolve_branch(store) if store else None
        retailer = branch.get("retailer") if branch else None
        if store and branch is None:
            if self.store_split_active:
                raise _error("branch_not_found", branch=store)
            retailer = self.require_retailer(store)  # no branches: that retailer's prices
        if offer is not None and not store:
            # the branch the offer was found for (main branch first), also a further branch
            # of a chain ("Lidl Arbeit" for an offer found only at the work postcode)
            retailer = self.offer_retailer(offer)
            branch = next(
                (
                    b
                    for b in self.selected_branches()
                    if b.get("retailer") == retailer
                    and b.get("id")
                    and ("branches" not in offer or b["id"] in offer["branches"])
                ),
                None,
            )
        chosen = self._chosen_pick(name, price, pack, offer, retailer, amounts)
        if chosen is not None:
            chosen["retailer"] = retailer or self.main_retailer
            item["chosen"] = chosen
        if branch is not None and (store or branch["id"] != self.main_branch):
            # an offer of the main store is no store choice: the item stays automatic
            item["store_override"] = branch["id"]
            if not store and chosen is not None:
                chosen["pins_store"] = True  # until the offer ends (see assign_stores)
        self._price_shopping_item(item, retailer, branch["id"] if branch else None)
        self.remember_article(summary, item["key"], item.get("retailer") or retailer)
        self.shopping.append(item)
        if self.trip_depends_on_items():
            # an own store choice or one more offer there: other offers of that store may
            # now be worth the trip
            self._reassign_open_items()
        self._changed("shopping")
        return item

    def _price_shopping_item(
        self, item: dict[str, Any], retailer: str | None = None, branch_id: str | None = None
    ) -> None:
        """Store, price and description of one item (store split, else that retailer).

        Without a store split a picked price counts at its retailer (e.g. the main store's
        500 g pack from the article search while "Aus" is set), as in _reassign_open_items().
        """
        if not self.assign_stores([item]):
            if retailer is None and isinstance(item.get("chosen"), dict):
                retailer = item["chosen"].get("retailer")
            cost = self.price_at(item, retailer, branch_id)
            item["price"] = cost["price"] if cost else None
            item["packs"] = cost["packs"] if cost else None
            item["offer"] = cost["offer"] if cost else None
        self.update_shopping_description(item)

    def _picked_offer(self, offer_id: str) -> dict[str, Any] | None:
        """A saved offer, an offer of the offer catalog (all offers of the saved stores) or
        a leaflet offer of the live article search (still in its cache)."""
        offer = next((o for o in self.offers if o.get("id") == offer_id), None)
        if offer is not None:
            return offer
        if (found := self.catalog_offer(offer_id)) is not None:
            return found
        for _, results in self._live_cache.values():
            for found in results:
                if found.get("id") == offer_id and found.get("source") == "marktguru":
                    return found
        _LOGGER.debug("Offer %s not found (not saved?)", offer_id)
        return None

    def catalog_offer(self, offer_id: str) -> dict[str, Any] | None:
        """A current offer of the catalog as a copy with "branches" (the selected branches
        it applies to), e.g. picked in "Alle Angebote meiner Läden"."""
        from .catalog import offer_branches  # avoid an import cycle

        offer = self.catalog.get_offer(offer_id, self.today())
        if offer is None:
            return None
        return {**offer, "branches": offer_branches(self, offer)}

    def _chosen_pick(
        self,
        name: str,
        price: float | None,
        pack: str | None,
        offer: dict[str, Any] | None,
        retailer: str | None = None,
        amounts: dict[str, float] | None = None,
    ) -> dict[str, Any] | None:
        """The price/pack the user picked ({name, price, amount, unit, offer_id[, offer]}).

        A pack without price is priced by the unit price of the store (or the estimate). A
        price without pack is the price of the store's usual pack of the product (else of
        the amount on the list). A picked offer only counts while it is valid.
        """
        if price is None and not pack and offer is None:
            return None
        size = parse_pack_text(pack) if pack else None
        if size is None and offer is not None:
            size = offer_pack(offer)
        if price is None and offer is not None:
            price = offer.get("price")
        if price is None:
            entry = self.regular_book(retailer).lookup(name)
            if entry is None:
                return None
            per = unit_price(entry)
            if (
                size is not None
                and per is not None
                and (per[1] == size[1] or {per[1], size[1]} <= {"g", "ml"})
            ):
                price = per[0] * size[0]  # e.g. a 500-g pack at the price of 250 g
            if price is None:
                price, size = entry.price, (entry.amount, entry.unit)
        if size is None:
            # e.g. an offer said by voice: the usual pack, never "1 Stück" of 500 g mince
            if (regular := self.regular_book(retailer).lookup(name)) is not None:
                size = (regular.amount, regular.unit)
            elif amounts and len(amounts) == 1:
                unit, amount = next(iter(amounts.items()))
                if unit in ("g", "ml") or unit in COUNT_UNITS:
                    size = (amount, "Stück" if unit in COUNT_UNITS else unit)
        try:
            value = round(float(price), 2)
        except (TypeError, ValueError) as err:
            raise _error("invalid_price", price=price) from err
        if value < 0:
            raise _error("invalid_price", price=price)
        chosen: dict[str, Any] = {
            "name": name,
            "price": value,
            "amount": size[0] if size else 1,
            "unit": size[1] if size else "Stück",
        }
        if offer is not None:
            chosen["offer_id"] = offer.get("id")
            if not any(o is offer for o in self.offers):
                # a live leaflet offer (not saved): keep what is needed while it is valid
                chosen["offer"] = {k: offer.get(k) for k in _OFFER_COPY_FIELDS}
        return chosen

    def shopping_update(
        self,
        uid: str,
        summary: str | None = None,
        status: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Update a shopping item.

        A changed text is parsed again ("Butter" -> "2 Butter": amount, price, store).
        """
        for item in self.shopping:
            if item["uid"] == uid:
                renamed = summary is not None and summary.strip() != item.get("summary")
                if summary is not None:
                    item["summary"] = summary
                if status is not None:
                    item["status"] = status
                if description is not None:
                    item["description"] = description
                if renamed and "amounts" in item:
                    self._reparse_shopping_item(item)
                self._changed("shopping")
                return item
        raise _error("shopping_item_not_found")

    def _reparse_shopping_item(self, item: dict[str, Any]) -> None:
        """Amount, product and price after the text of an item (1.3 item) was changed."""
        parsed = parse_ingredient(normalize_spoken_quantity(item["summary"]))
        amounts: dict[str, float] = {}
        if parsed["amount"] is not None:
            amount, unit = to_base(parsed["amount"], parsed["unit"])
            if amount:
                amounts[unit] = amount
        if item.get("source") == "plan" and not amounts:
            return  # e.g. "Spaghetti (500 g + 1 Pck.)": keep the planned amounts
        item["amounts"] = amounts
        name = parsed["name"] or item["summary"]
        key = ingredient_key(name)
        if item.get("source") != "plan" and key and key != item.get("key"):
            item.update({"name": name, "key": key, "category": guess_category(name)})
            item.pop("chosen", None)  # the picked price was for another product
        chosen = item.get("chosen") or {}
        self._price_shopping_item(item, chosen.get("retailer"))

    def shopping_delete(self, uids: list[str]) -> None:
        """Delete shopping items."""
        remove = set(uids)
        removed = [i for i in self.shopping if i["uid"] in remove]
        self.shopping = [i for i in self.shopping if i["uid"] not in remove]
        if self.trip_depends_on_items() and any(
            i.get("branch_id") not in (None, self.main_branch) and i.get("status") != "completed"
            for i in removed
        ):
            self._reassign_open_items()  # one store less on the list: is the trip still worth it?
        self._changed("shopping")

    def shopping_move(self, uid: str, previous_uid: str | None) -> None:
        """Re-order shopping items."""
        item = next((i for i in self.shopping if i["uid"] == uid), None)
        if item is None:
            raise _error("shopping_item_not_found")
        self.shopping.remove(item)
        if previous_uid is None:
            self.shopping.insert(0, item)
        else:
            index = next((n for n, i in enumerate(self.shopping) if i["uid"] == previous_uid), None)
            if index is None:
                self.shopping.append(item)
            else:
                self.shopping.insert(index + 1, item)
        self._changed("shopping")

    # ------------------------------------------------------------------
    # Backup / sharing
    # ------------------------------------------------------------------

    _EXPORT_FIELDS = (
        "name",
        "servings",
        "prep_time",
        "cook_time",
        "total_time",
        "tags",
        "ingredients",
        "steps",
        "notes",
        "source_url",
        "image",
        "favorite",
        "rating",
    )

    def export_recipes(self, recipe_ids: list[str] | None = None) -> list[dict[str, Any]]:
        """Recipes in a portable format."""
        recipes = [r for r in self.recipes.values() if recipe_ids is None or r["id"] in recipe_ids]
        recipes.sort(key=lambda r: fold(r["name"]))
        return [{k: r.get(k) for k in self._EXPORT_FIELDS} for r in recipes]

    def import_recipes(
        self, recipes: list[dict[str, Any]], overwrite: bool = False
    ) -> dict[str, list[str]]:
        """Import recipes (e.g. from export_recipes). Existing names are skipped or updated."""
        result: dict[str, list[str]] = {"added": [], "updated": [], "skipped": []}
        for data in recipes:
            if not isinstance(data, dict) or not str(data.get("name") or "").strip():
                continue
            data = {k: v for k, v in data.items() if k in self._EXPORT_FIELDS}
            existing = self.get_recipe_by_name(str(data["name"]))
            if existing and not overwrite:
                result["skipped"].append(existing["name"])
                continue
            if existing:
                updated = self._build_recipe(data, existing)
                self.recipes[updated["id"]] = updated
                result["updated"].append(updated["name"])
            else:
                recipe = self._build_recipe(data)
                self.recipes[recipe["id"]] = recipe
                result["added"].append(recipe["name"])
        if result["added"] or result["updated"]:
            self._changed("recipes_imported")
        return result

    def shopping_overview(self, store: str | None = None) -> dict[str, Any]:
        """Open shopping items grouped by aisle (and by store with an active split).

        store: also return "selection" – the open items of that store (None while the
        split is inactive).
        """
        groups: dict[str, list[str]] = {}
        done = 0
        total = 0.0
        priced = 0
        offers = []
        for item in self.shopping:
            if item.get("status") == "completed":
                done += 1
                continue
            groups.setdefault(item.get("category") or "Sonstiges", []).append(item["summary"])
            if item.get("price") is not None:
                total += item["price"]
                priced += 1
            if item.get("offer"):
                offers.append({"item": item["summary"], **item["offer"]})
        ordered = dict(sorted(groups.items(), key=lambda g: category_rank(g[0])))
        result: dict[str, Any] = {
            "open": sum(len(v) for v in ordered.values()),
            "completed": done,
            "groups": ordered,
            "estimated_total": round(total, 2),
            "priced_items": priced,
            "offers": offers,
            "split_active": self.store_split_active,
            "stores": self.stores_summary(),
        }
        if store:
            result["selection"] = self.store_selection(store) if self.store_split_active else None
        return result

    # ------------------------------------------------------------------
    # Export for the panel / websocket
    # ------------------------------------------------------------------

    def export(self) -> dict[str, Any]:
        """All data for the frontend panel."""
        return {
            "recipes": sorted(self.recipes.values(), key=lambda r: fold(r["name"])),
            "plan": self.plan,
            "shopping": self.shopping,
            "meals": [
                {
                    "id": meal,
                    "label": MEAL_LABELS[meal],
                    "time": self.meal_time(meal).strftime("%H:%M"),
                }
                for meal in self.enabled_meals
            ],
            "all_meals": [
                {
                    "id": meal,
                    "label": MEAL_LABELS[meal],
                    "time": self.meal_time(meal).strftime("%H:%M"),
                }
                for meal in ALL_MEALS
            ],
            "default_meal": self.default_meal,
            "default_servings": self.default_servings,
            "pantry": self.pantry,
            "excluded": self.excluded,
            "today": self.today().isoformat(),
            "economy": self.economy_export(),
            **self.branches_export(),
            "store_split": self.split_settings(),
            "shopping_stores": self.stores_summary(),
            # "immer hier kaufen": product key -> retailer (store picker of the panel)
            "store_preferences": dict(self.store_preferences),
            # ... at a further branch of the chain ("Lidl Arbeit"): product key -> branch id
            "store_preference_branches": dict(self.store_preference_branches),
            "offers": self.offers_view("all", limit=300),
            "recipe_costs": {
                rid: self.recipe_cost(recipe)["per_serving"] for rid, recipe in self.recipes.items()
            },
        }


def _load_starter_recipes() -> list[dict[str, Any]]:
    path = Path(__file__).parent / "starter_recipes.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        _LOGGER.warning("Could not load starter recipes: %s", err)
        return []
