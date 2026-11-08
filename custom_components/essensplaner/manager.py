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
    CONF_OCCASIONS_IN_BUDGET,
    CONF_PANTRY,
    CONF_SYNC_TODO,
    DEFAULT_ENABLED_MEALS,
    DEFAULT_MEAL,
    DEFAULT_MEAL_TIMES,
    DEFAULT_OCCASIONS_IN_BUDGET,
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
from .kinds import (
    KIND_AUTO,
    KIND_BREAKFAST,
    KIND_MEAL,
    KIND_SNACK,
    KIND_SOURCES,
    KINDS,
    PART_KINDS,
    SLOT_KINDS,
    SOURCE_RULE,
    SOURCE_USER,
    kinds_view,
    recipe_kind,
    resolve_kind,
    set_kind,
)
from .pricing import (
    COUNT_UNITS,
    offer_pack,
    pack_text,
    package_cost,
    package_need,
    to_pricing_base,
    unit_price,
)
from .products import product_counts
from .stores import REMATCH_CHANGES, StoresMixin

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

# leftovers ("Reste", 1.5.1): eaten at most this many days after the cooking day
LEFTOVER_MAX_DAYS = 7
LEFTOVER_EMOJI = "🍲"
# extra components of a plan entry (a sauce, a side, a drink with its recipe)
MAX_EXTRAS = 8
# a bought pack leaves a remainder worth a hint ("↪ 200 g übrig – z. B. für …"): at least
# this share of the pack and this much (g / ml, pieces) of a perishable aisle
PACK_LEFTOVER_SHARE = 0.25
PACK_LEFTOVER_MIN = {"g": 100.0, "ml": 100.0, "Stück": 2.0}
PACK_LEFTOVER_CATEGORIES = frozenset(
    {
        "Fleisch & Fisch",
        "Milchprodukte & Eier",
        "Käse & Aufschnitt",
        "Obst & Gemüse",
        "Brot & Backwaren",
    }
)
PACK_LEFTOVER_RECIPES = 2
# keeps for weeks: no hint
PACK_LEFTOVER_SKIP = frozenset({"butter", "margarine", "schmalz", "ei", "eier"})

# ready meals (the bundled "Fertiggericht" recipes, recipes made from a product) are
# suggested half as often as cooked dishes – unless they are favourites (1.5)
READY_MEAL_TAG = "fertiggericht"
READY_MEAL_FACTOR = 0.5

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
    # 1.5: shown with the item's product
    "image",
    "brand",
)
# how a product picked with "Produkt wechseln" is remembered (shopping_set_product)
REMEMBER_NONE = "none"
REMEMBER_PICK = "pick"
REMEMBER_FAVORITE = "favorite"
REMEMBER_MODES = (REMEMBER_NONE, REMEMBER_PICK, REMEMBER_FAVORITE)

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
    "leftover_not_after": (
        "Reste kann ich nur für eine spätere Mahlzeit einplanen, höchstens {days} Tage nach "
        "dem Kochen."
    ),
    "invalid_kind": (
        "Die Art „{kind}“ kenne ich nicht – möglich sind Mahlzeit, Frühstück, Snack, "
        "Dessert, Getränk, Beilage und Bestandteil."
    ),
    "dish_not_planned": "„{name}“ ist in den nächsten Tagen nicht geplant.",
    "invalid_json": "Die Rezeptdaten konnten nicht gelesen werden.",
    "offers_disabled": (
        "Online-Angebote sind nicht aktiviert (Essensplaner-Panel → Einstellungen → "
        "Angebote & Preisquellen)."
    ),
    "invalid_zip": (
        "Bitte in den Einstellungen des Essensplaner-Panels eine gültige Postleitzahl für "
        "Angebote eintragen oder eine Filiale mit Postleitzahl hinzufügen."
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
        "Hauptladen (im Essensplaner-Panel unter „Läden und Preise“), und die Aufteilung "
        "nach Läden muss in den Einstellungen (Läden & Einkauf) eingeschaltet sein."
    ),
    "rewe_disabled": (
        "REWE-Onlinepreise sind nicht aktiviert (experimentell, Essensplaner-Panel → "
        "Einstellungen → Angebote & Preisquellen)."
    ),
    "rewe_no_market": (
        "Keine REWE-Filiale mit Markt-ID – füge eine REWE-Filiale hinzu und trage ihre "
        "Markt-ID ein (zu finden mit „REWE-Märkte suchen“)."
    ),
    "rewe_blocked": "Der REWE-Onlineshop lässt gerade keine automatischen Abfragen zu ({error}).",
    "rewe_failed": "Die Abfrage beim REWE-Onlineshop ist fehlgeschlagen ({error}).",
    "rewe_postcode_required": "Bitte gib eine Postleitzahl an (5 Ziffern).",
    "aldi_disabled": (
        "ALDI-SÜD-Onlinepreise sind nicht aktiviert (experimentell, Essensplaner-Panel → "
        "Einstellungen → Angebote & Preisquellen)."
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
    "edeka_disabled": (
        "EDEKA-Angebote sind nicht aktiviert (Essensplaner-Panel → Einstellungen → Angebote "
        "& Preisquellen)."
    ),
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
        "Für Fotos von Kassenzetteln brauche ich eine KI-Aufgabe (AI Task): wähle sie unter "
        "Essensplaner-Panel → Einstellungen → 🤖 KI oder → Kassenzettel – oder füge den "
        "Text des Kassenzettels ein."
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
    # product database (1.5, products.py)
    "product_not_found": "Den Artikel „{id}“ gibt es nicht in der Artikel-Datenbank.",
    "invalid_remember": (
        "„{remember}“ kenne ich nicht – möglich sind none (nicht merken), pick (als gewählt "
        "merken) und favorite (⭐ Lieblingsprodukt)."
    ),
    # occasions (1.5, occasions.py)
    "occasion_not_found": "Den Anlass „{occasion}“ habe ich nicht gefunden.",
    "occasion_item_not_found": "„{item}“ steht nicht auf dem Plan für „{occasion}“.",
    "invalid_course": (
        "Den Gang „{course}“ kenne ich nicht – möglich sind Vorspeise, Hauptgang, Beilagen, "
        "Dessert, Snacks, Getränke und Zubehör."
    ),
    "invalid_time": "Die Uhrzeit „{time}“ habe ich nicht verstanden (z. B. 19:30).",
    "invalid_template": (
        "Die Vorlage „{template}“ kenne ich nicht – z. B. Filmabend, Grillabend, "
        "Familienessen, Weihnachtsessen, Silvester, Geburtstag, Brunch, Raclette, Fondue, "
        "Party oder Osteressen."
    ),
    # AI via Home Assistant (1.5, ai.py)
    "ai_not_configured": (
        "Dafür brauche ich eine KI: wähle unter Essensplaner-Panel → Einstellungen → 🤖 KI "
        "eine KI-Aufgabe oder einen Gesprächsagenten aus Home Assistant (z. B. Claude, "
        "OpenAI oder Ollama). Ohne KI funktionieren die Vorschläge nach Regeln."
    ),
    "ai_unavailable": (
        "Die KI {entity} ist gerade nicht erreichbar – bitte später erneut versuchen. Die "
        "Vorschläge nach Regeln funktionieren weiter."
    ),
    "ai_failed": "Die Anfrage an die KI {entity} ist fehlgeschlagen ({error}).",
    "ai_invalid": (
        "Die KI {entity} hat keine verwertbare Antwort (JSON) geliefert – bitte erneut versuchen."
    ),
    "ai_feature_off": (
        "Die KI ist für „{feature}“ ausgeschaltet (Essensplaner-Panel → Einstellungen → 🤖 KI)."
    ),
    "ai_busy": (
        "Die KI arbeitet gerade an einer anderen Essensplaner-Anfrage – bitte gleich noch "
        "einmal versuchen."
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
        from .products import ProductStore

        # every real product with a real price that was seen (own file, 1.5)
        self.products = ProductStore(hass, entry.entry_id)
        # occasions ("Anlässe", 1.5, occasions.py): {id: occasion}, stored in the main file
        self.occasions: dict[str, dict[str, Any]] = {}
        # AI sorting of articles and recipes (1.5.1, ai_sort.py): last runs per target,
        # stored in the main file
        self.ai_sort_state: dict[str, Any] = {}
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
    def occasions_in_budget(self) -> bool:
        """Occasions count toward the weekly budget (their costs always show)."""
        return bool(self.options.get(CONF_OCCASIONS_IN_BUDGET, DEFAULT_OCCASIONS_IN_BUDGET))

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
        from .occasions import load_occasions, prune_occasions

        self.occasions = load_occasions(data.get("occasions"))
        self.ai_sort_state = dict(data["ai_sort"]) if isinstance(data.get("ai_sort"), dict) else {}
        pruned_occasions = prune_occasions(self)
        self._load_store_data(data)
        await self.catalog.async_load()
        self.catalog.prune(self.today())
        # offers of sources switched off (e.g. marktguru after reading its terms) go
        from .catalog import drop_disabled_sources  # the catalog imports the mixins

        dropped = drop_disabled_sources(self)
        await self.receipts.async_load()
        # after the catalog and the receipts (seeding reads them, see products.async_seed)
        await self.products.async_load()
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
        elif expired or dropped or pruned_occasions or self.shopping != before:
            self._save_later()
        if dropped:
            self.catalog.save_later()
        from .products import drop_disabled_products, prune_products

        # offers of sources switched off, ended offers and products nobody needs any more
        drop_disabled_products(self)
        prune_products(self)

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
            "occasions": self.occasions,
            "ai_sort": self.ai_sort_state,
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
        if change in ("plan", "recipe_updated", "recipe_deleted"):
            self._fix_leftovers()  # leftovers whose cooking meal changed (1.5.1)
        self._store.async_delay_save(self._data_to_store, SAVE_DELAY)
        if change in REMATCH_CHANGES:
            self.schedule_catalog_rematch()  # new keys: their offers from the catalog
        for update_callback in list(self._listeners):
            update_callback()
        self.hass.bus.async_fire(EVENT_UPDATED, {"change": change})

    @callback
    def occasions_changed(self) -> None:
        """Occasions changed: save, update entities and the panel (offers are matched again
        for their dishes and drinks)."""
        self._changed("occasions")

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
        self._apply_kind(recipe, data)
        recipe["updated"] = now
        return recipe

    @staticmethod
    def _apply_kind(recipe: dict[str, Any], data: dict[str, Any]) -> None:
        """The recipe's kind (1.5.1): the one given (the user's choice, "auto" / "" hands
        it back to the rules; an export's kind_source is kept), else the rules – which
        never overwrite what the user or the AI chose (kinds.set_kind())."""
        raw = data.get("kind")
        if raw is None:
            set_kind(recipe, None, SOURCE_RULE)
            return
        kind = resolve_kind(raw) if str(raw).strip() else KIND_AUTO
        if kind is None:
            raise _error("invalid_kind", kind=raw)
        source = data.get("kind_source")
        if source not in KIND_SOURCES:
            source = SOURCE_USER
        set_kind(recipe, None if source == SOURCE_RULE else kind, source)

    def _migrate_kinds(self) -> int:
        """v6 (1.5.1): every recipe without a (valid) kind gets one by the rules. Returns
        the count of changed recipes (0 on a second run)."""
        count = 0
        for recipe in self.recipes.values():
            if recipe.get("kind") in KINDS and recipe.get("kind_source") in KIND_SOURCES:
                continue
            set_kind(recipe, None, SOURCE_RULE)
            count += 1
        return count

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
            # 1.5.1: meal, breakfast, snack, dessert, drink, side or component
            "kind": recipe_kind(recipe),
            "kind_source": recipe.get("kind_source") or SOURCE_RULE,
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
        slot: str | None = None
        if meal and meal in meals:
            slot = meal
        elif recipe is None and meals:
            slot = next(iter(meals))
        elif recipe is not None:
            slot = next((m for m, e in meals.items() if e.get("recipe_id") == recipe["id"]), None)
        entry = meals.get(slot) if slot else None
        already = False
        count_day = day
        if entry is not None:
            already = bool(entry.get("cooked"))
            entry["cooked"] = True
            entry.pop("auto_cooked", None)
            if recipe is None and entry.get("recipe_id"):
                recipe = self.recipes.get(entry["recipe_id"])
            assert slot is not None
            if (source := self.leftover_source(day, slot, entry)) is not None:
                # leftovers (1.5.1): the cooking day counts (once), the leftovers never
                src_day, _src_meal, src_entry = source
                already = bool(src_entry.get("cooked"))
                src_entry["cooked"] = True
                src_entry.pop("auto_cooked", None)
                count_day = src_day
        if recipe is not None and not already:
            self._count_cooked(recipe, count_day)
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
        marked = False
        for key in sorted(self.plan):
            if not start <= key < today.isoformat():
                continue
            for slot, entry in self.plan[key].items():
                recipe = self.recipes.get(entry.get("recipe_id") or "")
                if recipe is None or entry.get("cooked"):
                    continue
                entry["cooked"] = True
                entry["auto_cooked"] = True
                marked = True
                if self.leftover_source(date.fromisoformat(key), slot, entry) is not None:
                    continue  # leftovers: their cooking day counted (1.5.1)
                self._count_cooked(recipe, date.fromisoformat(key))
                count += 1
        if marked:
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
        drinks: Any = None,
        extras: Any = None,
        as_extra: bool | None = None,
    ) -> dict[str, Any]:
        """Put a recipe (or free text) into the meal plan.

        drinks (1.5, optional): what is drunk with it ("🍷 Passt dazu") – texts or dicts
        {title, alcohol?, recipe_id?, product_id?}; None keeps the drinks of the meal that
        was planned in this slot with the same dish, [] removes them.
        extras (1.5.1, optional): what comes with the meal ("Dazu": a sauce, a side, a
        drink made from a recipe) – recipe names / ids or dicts {recipe_id | recipe |
        title, servings?}; they join the shopping list and the costs. None keeps the extras
        of the same dish, [] removes them.
        A recipe that is only ever part of a meal (a drink, side, component or dessert)
        planned into a slot that holds another dish is added to that dish as an extra
        (as_extra None; True: also any other recipe, False: never) – the view then has
        "added_as_extra". The same dish keeps "cooked" and its leftovers link.
        """
        if meal not in ALL_MEALS:
            raise _error("invalid_meal", meal=meal)
        if recipe is None and not (title or "").strip():
            raise _error("name_required")
        previous = self.plan.get(day.isoformat(), {}).get(meal) or {}
        if (
            recipe is not None
            and previous
            and as_extra is not False
            and previous.get("recipe_id") != recipe["id"]
            and (as_extra or recipe_kind(recipe) in PART_KINDS)
        ):
            return self.add_plan_extra(day, meal, recipe=recipe, servings=servings)
        entry = {
            "recipe_id": recipe["id"] if recipe else None,
            "title": recipe["name"] if recipe else str(title).strip(),
            "servings": servings or self.default_servings,
            "note": (note or "").strip(),
            "cooked": False,
            "added": dt_util.utcnow().isoformat(),
        }
        same_dish = bool(previous) and (
            previous.get("recipe_id") == entry["recipe_id"]
            and previous.get("title") == entry["title"]
        )
        if same_dish:
            # the same dish changed (servings, note, drinks – e.g. "Getränk hinzufügen" in
            # the panel, 1.5): it stays cooked and keeps when it was planned
            entry["cooked"] = bool(previous.get("cooked"))
            entry["added"] = previous.get("added") or entry["added"]
            if isinstance(previous.get("leftover_of"), dict):
                entry["leftover_of"] = dict(previous["leftover_of"])  # still the leftovers
        if drinks is not None:
            if cleaned := self._plan_drinks(drinks):
                entry["drinks"] = cleaned
        elif previous.get("drinks") and previous.get("title") == entry["title"]:
            entry["drinks"] = previous["drinks"]
        if extras is not None:
            if parts := self._plan_extras(extras, exclude=entry["recipe_id"]):
                entry["extras"] = parts
        elif previous.get("extras") and previous.get("title") == entry["title"]:
            entry["extras"] = previous["extras"]
        self.plan.setdefault(day.isoformat(), {})[meal] = entry
        self._cleanup_plan()
        self._changed("plan")
        return self.entry_view(day, meal, entry)

    def add_plan_extra(
        self,
        day: date,
        meal: str,
        recipe: dict[str, Any] | None = None,
        title: str | None = None,
        servings: int | None = None,
    ) -> dict[str, Any]:
        """Add a component to the planned meal of a slot ("Kräuterbutter" to the steak,
        1.5.1). Returns the entry's view with "added_as_extra" (the extra's title)."""
        entry = self.plan.get(day.isoformat(), {}).get(meal)
        if entry is None:
            raise _error("meal_not_planned", date=day.isoformat())
        new: dict[str, Any] = {"recipe_id": recipe["id"]} if recipe else {"title": title}
        if servings:
            new["servings"] = servings
        added = self._plan_extras([new])
        if not added:
            raise _error("name_required")
        entry["extras"] = self._plan_extras(
            [*(entry.get("extras") or []), *added], exclude=entry.get("recipe_id")
        )
        self._changed("plan")
        view = self.entry_view(day, meal, entry)
        view["added_as_extra"] = added[0]["title"]
        return view

    def _plan_extras(self, value: Any, exclude: str | None = None) -> list[dict[str, Any]]:
        """Extras of a plan entry: [{title, recipe_id?, servings?}] (≤ MAX_EXTRAS, no
        duplicates, not the dish itself). A text is a recipe name (else a free extra)."""
        items = value if isinstance(value, list) else [value]
        extras: list[dict[str, Any]] = []
        for raw in items:
            if isinstance(raw, str):
                raw = {"recipe": raw}
            if not isinstance(raw, dict):
                continue
            recipe = None
            if isinstance(raw.get("recipe_id"), str):
                recipe = self.recipes.get(raw["recipe_id"].strip())
            name = raw.get("recipe")
            if recipe is None and isinstance(name, str) and name.strip():
                recipe = self.recipes.get(name.strip()) or self.find_recipe(strip_article(name))
            title = (
                recipe["name"] if recipe else " ".join(str(raw.get("title") or name or "").split())
            )
            title = title[:80]
            if not title or (recipe is not None and recipe["id"] == exclude):
                continue
            if any(
                (recipe is not None and x.get("recipe_id") == recipe["id"])
                or fold(x["title"]) == fold(title)
                for x in extras
            ):
                continue
            extra: dict[str, Any] = {"title": title}
            if recipe is not None:
                extra["recipe_id"] = recipe["id"]
            if number := _to_int(raw.get("servings"), 1):
                extra["servings"] = min(number, 500)
            extras.append(extra)
            if len(extras) >= MAX_EXTRAS:
                break
        return extras

    def plan_leftover(
        self,
        day: date,
        meal: str,
        from_day: date,
        from_meal: str,
        servings: int | None = None,
    ) -> dict[str, Any]:
        """Eat the leftovers of a planned meal later ("Dienstag für Mittwoch mitkochen",
        1.5.1): the entry gets "leftover_of" {date, meal}; the cooking day is bought and
        priced for both (its servings plus the leftovers'), the leftovers cost nothing and
        add nothing to the shopping list. Leftovers of leftovers come from the cooking day.
        An entry in the target slot is replaced (the view has "replaced")."""
        for slot in (meal, from_meal):
            if slot not in ALL_MEALS:
                raise _error("invalid_meal", meal=slot)
        source = self.plan.get(from_day.isoformat(), {}).get(from_meal)
        if source is None:
            raise _error("meal_not_planned", date=from_day.isoformat())
        if found := self.leftover_source(from_day, from_meal, source):
            from_day, from_meal, source = found
        if (from_day, from_meal) == (day, meal) or not self._leftover_order_ok(
            from_day, from_meal, day, meal
        ):
            raise _error("leftover_not_after", days=LEFTOVER_MAX_DAYS)
        link = {"date": from_day.isoformat(), "meal": from_meal}
        previous = self.plan.get(day.isoformat(), {}).get(meal) or {}
        entry: dict[str, Any] = {
            "recipe_id": source.get("recipe_id"),
            "title": source.get("title") or "",
            "servings": servings or source.get("servings") or self.default_servings,
            "note": "",
            "cooked": False,
            "added": dt_util.utcnow().isoformat(),
            "leftover_of": link,
        }
        same = previous.get("leftover_of") == link
        if same:
            # the same leftovers, other servings: what was added to them stays
            entry["cooked"] = bool(previous.get("cooked"))
            entry["note"] = previous.get("note") or ""
            for key in ("drinks", "extras", "added"):
                if previous.get(key):
                    entry[key] = previous[key]
        self.plan.setdefault(day.isoformat(), {})[meal] = entry
        self._changed("plan")
        view = self.entry_view(day, meal, entry)
        if previous and not same:
            view["replaced"] = previous.get("title")
        return view

    def _meal_rank(self, meal: str) -> tuple[time, int]:
        return self.meal_time(meal), ALL_MEALS.index(meal) if meal in ALL_MEALS else 9

    def _leftover_order_ok(self, from_day: date, from_meal: str, day: date, meal: str) -> bool:
        """Leftovers are eaten after the cooking meal, at most LEFTOVER_MAX_DAYS later."""
        if (day, self._meal_rank(meal)) <= (from_day, self._meal_rank(from_meal)):
            return False
        return (day - from_day).days <= LEFTOVER_MAX_DAYS

    def leftover_source(
        self, day: date, meal: str, entry: dict[str, Any]
    ) -> tuple[date, str, dict[str, Any]] | None:
        """(day, meal, entry) of the meal an entry is the leftovers of – None for a normal
        entry or a link that no longer holds (the dish there changed, it was moved after
        the leftovers, it is leftovers itself)."""
        link = entry.get("leftover_of")
        if not isinstance(link, dict):
            return None
        try:
            src_day = date.fromisoformat(str(link.get("date")))
        except ValueError:
            return None
        src_meal = link.get("meal")
        if src_meal not in ALL_MEALS:
            return None
        source = self.plan.get(src_day.isoformat(), {}).get(src_meal)
        if source is None or source is entry or isinstance(source.get("leftover_of"), dict):
            return None
        if source.get("recipe_id") != entry.get("recipe_id") or (source.get("title") or "") != (
            entry.get("title") or ""
        ):
            return None
        if not self._leftover_order_ok(src_day, src_meal, day, meal):
            return None
        return src_day, src_meal, source

    def leftovers_of(self, day: date, meal: str) -> list[tuple[date, str, dict[str, Any]]]:
        """The entries that are the leftovers of a planned meal: [(day, meal, entry)]."""
        found: list[tuple[date, str, dict[str, Any]]] = []
        for offset in range(LEFTOVER_MAX_DAYS + 1):
            other = day + timedelta(days=offset)
            for slot, entry in self.plan.get(other.isoformat(), {}).items():
                link = entry.get("leftover_of")
                if (
                    isinstance(link, dict)
                    and link.get("date") == day.isoformat()
                    and link.get("meal") == meal
                    and self.leftover_source(other, slot, entry) is not None
                ):
                    found.append((other, slot, entry))
        return found

    def cook_servings(
        self, day: date, meal: str, entry: dict[str, Any], base: int | None = None
    ) -> int:
        """Servings cooked for a plan entry: its own plus those of its leftovers (base: the
        servings of an entry without any, default the default servings)."""
        own = entry.get("servings") or base or self.default_servings
        extra = sum(int(e.get("servings") or own) for _d, _m, e in self.leftovers_of(day, meal))
        return int(own) + extra

    def _links_to(self, day: date, meal: str) -> list[dict[str, Any]]:
        """Entries whose leftovers link names this slot (valid or not)."""
        return [
            entry
            for meals in self.plan.values()
            for entry in meals.values()
            if isinstance(link := entry.get("leftover_of"), dict)
            and link.get("date") == day.isoformat()
            and link.get("meal") == meal
        ]

    def _fix_leftovers(self) -> list[tuple[date, str, dict[str, Any], dict[str, Any]]]:
        """Leftovers whose cooking meal is gone, changed or after them become normal
        entries (cooked on their own day). Returns [(day, meal, entry, old link)]."""
        unlinked: list[tuple[date, str, dict[str, Any], dict[str, Any]]] = []
        for key, meals in self.plan.items():
            for slot, entry in meals.items():
                if "leftover_of" not in entry:
                    continue
                try:
                    day = date.fromisoformat(key)
                except ValueError:
                    continue
                if self.leftover_source(day, slot, entry) is None:
                    link = entry.pop("leftover_of")
                    unlinked.append((day, slot, entry, link if isinstance(link, dict) else {}))
        return unlinked

    @staticmethod
    def _plan_drinks(value: Any) -> list[dict[str, Any]]:
        """Drinks of a plan entry: [{title, alcohol, recipe_id?, product_id?}] (≤ 6)."""
        from .drinks import is_alcoholic

        items = value if isinstance(value, list) else [value]
        drinks: list[dict[str, Any]] = []
        for raw in items:
            if isinstance(raw, str):
                raw = {"title": raw}
            if not isinstance(raw, dict):
                continue
            title = " ".join(str(raw.get("title") or "").split())[:80]
            if not title or any(fold(d["title"]) == fold(title) for d in drinks):
                continue
            said = raw.get("alcohol")
            drink: dict[str, Any] = {
                "title": title,
                "alcohol": said if isinstance(said, bool) else is_alcoholic(title),
            }
            for key in ("recipe_id", "product_id"):
                if isinstance(raw.get(key), str) and raw[key].strip():
                    drink[key] = raw[key].strip()[:80]
            drinks.append(drink)
            if len(drinks) >= 6:
                break
        return drinks

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
            # leftovers of a removed meal are cooked on their own day now (1.5.1)
            unlinked = self._fix_leftovers()
            for view in removed:
                view["leftovers_unlinked"] = [
                    self.entry_view(d, m, e)
                    for d, m, e, link in unlinked
                    if link.get("date") == view["date"] and link.get("meal") == view["meal"]
                ]
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
        # leftovers follow their cooking meal (1.5.1)
        links_from = self._links_to(from_day, from_meal)
        links_to = self._links_to(to_day, to_meal)
        entry = source.pop(from_meal)
        target = self.plan.setdefault(to_day.isoformat(), {})
        swapped = target.pop(to_meal, None)
        target[to_meal] = entry
        if swapped is not None:
            self.plan.setdefault(from_day.isoformat(), {})[from_meal] = swapped
        for key in (from_day.isoformat(), to_day.isoformat()):
            if not self.plan.get(key):
                self.plan.pop(key, None)
        for linked in links_from:
            linked["leftover_of"] = {"date": to_day.isoformat(), "meal": to_meal}
        for linked in links_to:
            linked["leftover_of"] = {"date": from_day.isoformat(), "meal": from_meal}
        unlinked = self._fix_leftovers()
        self._changed("plan")
        result = {
            "moved": self.entry_view(to_day, to_meal, entry),
            "swapped": self.entry_view(from_day, from_meal, swapped) if swapped else None,
        }
        if unlinked:
            # moved after its leftovers: they are cooked on their own day now
            result["leftovers_unlinked"] = [self.entry_view(d, m, e) for d, m, e, _l in unlinked]
        return result

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
                self._copy_leftover_link(new_entry, source, target, days)
                self.plan.setdefault(dst_day.isoformat(), {})[meal] = new_entry
                copied.append(self.entry_view(dst_day, meal, new_entry))
        if copied:
            self._changed("plan")
        return copied

    @staticmethod
    def _copy_leftover_link(entry: dict[str, Any], source: date, target: date, days: int) -> None:
        """A copied leftovers entry points to the copy of its cooking meal (when that is
        copied too), else it is a normal entry."""
        link = entry.get("leftover_of")
        if not isinstance(link, dict):
            entry.pop("leftover_of", None)
            return
        try:
            src = date.fromisoformat(str(link.get("date")))
        except ValueError:
            src = None
        if src is None or not source <= src < source + timedelta(days=max(1, days)):
            entry.pop("leftover_of", None)
            return
        entry["leftover_of"] = {
            "date": (src + (target - source)).isoformat(),
            "meal": link.get("meal"),
        }

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
        """Return a plan entry enriched with labels and recipe info.

        1.5.1: "dish" is the dish's name; leftovers are titled "🍲 Reste von Dienstag
        (Lasagne)" ("leftover_of": {date, meal, weekday, meal_label}); a cooking meal lists
        its "leftovers" [{date, meal, weekday, servings}] and its "cook_servings"; "extras"
        are the components with the meal [{title, recipe_id, servings, kind}]."""
        recipe = self.recipes.get(entry.get("recipe_id") or "")
        meal_time = self.meal_time(meal)
        dish = entry.get("title") or (recipe["name"] if recipe else "")
        view: dict[str, Any] = {
            "date": day.isoformat(),
            "weekday": WEEKDAY_NAMES[day.weekday()],
            "meal": meal,
            "meal_label": MEAL_LABELS.get(meal, meal),
            "time": meal_time.strftime("%H:%M"),
            "title": dish,
            "dish": dish,
            "recipe_id": recipe["id"] if recipe else None,
            "servings": entry.get("servings"),
            "note": entry.get("note", ""),
            "cooked": entry.get("cooked", False),
            "total_time": recipe.get("total_time") if recipe else None,
            "image": (recipe.get("image") or None) if recipe else None,
            # 1.5: drinks with the meal (empty for older entries)
            "drinks": list(entry.get("drinks") or []),
            "extras": [self._extra_view(x, entry) for x in entry.get("extras") or []],
            "leftover_of": None,
            "leftovers": [],
            "cook_servings": entry.get("servings"),
        }
        if (source := self.leftover_source(day, meal, entry)) is not None:
            src_day, src_meal, _src = source
            view["leftover_of"] = {
                "date": src_day.isoformat(),
                "meal": src_meal,
                "weekday": WEEKDAY_NAMES[src_day.weekday()],
                "meal_label": MEAL_LABELS.get(src_meal, src_meal),
            }
            view["title"] = leftover_title(day, src_day, src_meal, dish)
        elif leftovers := self.leftovers_of(day, meal):
            view["leftovers"] = [
                {
                    "date": d.isoformat(),
                    "meal": m,
                    "weekday": WEEKDAY_NAMES[d.weekday()],
                    "servings": e.get("servings"),
                }
                for d, m, e in leftovers
            ]
            view["cook_servings"] = self.cook_servings(
                day, meal, entry, recipe.get("servings") if recipe else None
            )
        return view

    def _extra_view(self, extra: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
        recipe = self.recipes.get(extra.get("recipe_id") or "")
        return {
            "title": recipe["name"] if recipe else extra.get("title") or "",
            "recipe_id": recipe["id"] if recipe else None,
            "servings": extra.get("servings") or entry.get("servings"),
            "kind": recipe_kind(recipe) if recipe else None,
        }

    def entry_ingredients(
        self, day: date, meal: str, entry: dict[str, Any]
    ) -> tuple[list[tuple[dict[str, Any], str]], list[str], int]:
        """What a plan entry needs: ([(scaled ingredient, recipe name)], titles without a
        recipe, 1 if its dish is a recipe cooked that day). The cooking meal of leftovers
        is scaled to their servings too; leftovers need nothing (1.5.1); the extras need
        their recipes."""
        found: list[tuple[dict[str, Any], str]] = []
        without: list[str] = []
        counted = 0
        recipe = self.recipes.get(entry.get("recipe_id") or "")
        if self.leftover_source(day, meal, entry) is not None:
            pass  # bought and cooked on the cooking day
        elif recipe is None:
            if entry.get("title"):
                without.append(entry["title"])
        else:
            counted = 1
            servings = self.cook_servings(day, meal, entry, recipe.get("servings"))
            found.extend(self._scaled_ingredients(recipe, servings))
        for extra in entry.get("extras") or []:
            extra_recipe = self.recipes.get(extra.get("recipe_id") or "")
            if extra_recipe is None:
                if extra.get("title"):
                    without.append(extra["title"])
                continue
            servings = (
                extra.get("servings") or entry.get("servings") or extra_recipe.get("servings")
            )
            found.extend(self._scaled_ingredients(extra_recipe, servings))
        return found, without, counted

    def _scaled_ingredients(
        self, recipe: dict[str, Any], servings: int | None
    ) -> list[tuple[dict[str, Any], str]]:
        base = recipe.get("servings") or self.default_servings
        factor = (servings or base) / base
        return [
            (scale_ingredient(i, factor), recipe["name"]) for i in recipe.get("ingredients", [])
        ]

    def entry_cost(self, day: date, meal: str, entry: dict[str, Any]) -> dict[str, Any] | None:
        """Estimated cost of a plan entry {total, savings, on_offer (ingredients),
        leftover}: its recipe for the cooked servings (with its leftovers'), plus its
        extras; leftovers cost nothing (1.5.1). None without any recipe."""
        recipe = self.recipes.get(entry.get("recipe_id") or "")
        leftover = self.leftover_source(day, meal, entry) is not None
        parts: list[dict[str, Any]] = []
        if recipe is not None and not leftover:
            servings = self.cook_servings(day, meal, entry, recipe.get("servings"))
            parts.append(self.recipe_cost(recipe, servings, day))
        for extra in entry.get("extras") or []:
            extra_recipe = self.recipes.get(extra.get("recipe_id") or "")
            if extra_recipe is not None:
                servings = extra.get("servings") or entry.get("servings")
                parts.append(self.recipe_cost(extra_recipe, servings, day))
        if not parts and not leftover:
            return None
        return {
            "total": round(sum(p["total"] for p in parts), 2),
            "savings": round(sum(p["savings"] for p in parts), 2),
            "on_offer": [o["ingredient"] for p in parts for o in p["on_offer"]],
            "leftover": leftover,
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
        """True if the recipe can fill the meal slot on its own (1.5.1: by its kind – a
        drink, side, component or dessert never does; meal None: any slot). A meal tagged
        "Frühstück" / "Snack" also fits that slot (Pfannkuchen, Frühlingsrollen)."""
        kind = recipe_kind(recipe)
        if kind not in SLOT_KINDS:
            return False
        if meal is None:
            return True
        tags = self.recipe_tags_folded(recipe)
        if meal == MEAL_BREAKFAST:
            return kind == KIND_BREAKFAST or bool(tags & BREAKFAST_TAGS)
        if meal == MEAL_SNACK:
            return kind == KIND_SNACK or bool(tags & SNACK_TAGS)
        return kind == KIND_MEAL

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

    def _suggest_context(
        self,
        around: date,
        strategy: str | None = None,
        target_cost: float | None = None,
        servings: int | None = None,
        budget: bool = True,
        variety: bool = True,
    ) -> dict[str, Any]:
        """What the suggestion weights of one day depend on (computed once per day):
        recipes planned nearby, the budget target, the median cost (strategy cheap), the
        dishes of the neighbouring days and how much the season counts (1.5,
        season.season_weight()). budget / variety False: no budget target / no variety
        penalty (occasions: a party menu is no everyday meal)."""
        from .season import season_weight

        recently_planned: set[str] = set()
        for offset in range(-6, 7):
            for entry in self.plan.get((around + timedelta(days=offset)).isoformat(), {}).values():
                if entry.get("recipe_id"):
                    recently_planned.add(entry["recipe_id"])
        if target_cost is None and budget and self.weekly_budget:
            target_cost = self.budget_target(around)
        return {
            "around": around,
            "recent": recently_planned,
            "strategy": strategy,
            "target_cost": target_cost,
            "median": self.median_cost(around, servings) if strategy == STRATEGY_CHEAP else None,
            "servings": servings,
            "neighbours": self._neighbour_signatures(around) if variety else None,
            "season": season_weight(self, strategy),
        }

    def _suggest_weight(self, recipe: dict[str, Any], ctx: dict[str, Any]) -> float:
        """Weight of a recipe for suggestions (shared by suggest() and the occasions):
        favourites, rating, not cooked lately, not planned nearby, ready meals less often,
        offers, budget and variety (economy_weight()) and the season (1.5,
        season.season_factor())."""
        from .season import season_factor

        around: date = ctx["around"]
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
        elif READY_MEAL_TAG in self.recipe_tags_folded(recipe):
            weight *= READY_MEAL_FACTOR  # 1.5: a ready meal now and then, not every week
        weight += (recipe.get("rating") or 0) * 0.4
        if recipe["id"] in ctx["recent"]:
            weight *= 0.1
        weight *= self.economy_weight(
            recipe,
            around,
            strategy=ctx["strategy"],
            target_cost=ctx["target_cost"],
            median_cost=ctx["median"],
            servings=ctx["servings"],
            neighbours=ctx["neighbours"],
        )
        if ctx.get("season"):
            weight *= season_factor(self, recipe, around, ctx["season"])
        return weight

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
        recipes that fit the remaining budget, dishes that differ from the neighbouring
        days and (1.5) dishes of the season. Why: season.suggest_reasons().
        """
        rng = rng or random.Random()
        exclude = exclude or set()
        around = around or self.today()
        candidates = [
            r
            for r in self.search_recipes(tag=tag, max_time=max_time)
            if r["id"] not in exclude and self._fits_meal(r, meal) and not self.is_excluded(r)
        ]
        ctx = self._suggest_context(
            around, strategy=strategy, target_cost=target_cost, servings=servings
        )
        weights = [self._suggest_weight(recipe, ctx) for recipe in candidates]

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
        order: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fill empty slots of the plan with suggestions (budget, offers, variety and season
        aware). order (1.5, the AI's order of the rules' best candidates, see
        season.async_auto_plan()): each slot gets the first recipe of the order that fits
        the meal and is not planned yet – one of another kind than the day before when
        there is one –, else a suggestion."""
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
        from .occasions import occasion_meals

        for offset in range(max(1, days)):
            day = start + timedelta(days=offset)
            existing = self.plan.get(day.isoformat(), {})
            # an occasion with dishes that day (a barbecue at 18:00) is the dinner (1.5)
            covered = occasion_meals(self, day)
            for meal in meals:
                if (meal in existing and not overwrite) or meal in covered:
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
                suggestion = self._ordered_pick(order, day, meal, used | nearby) if order else []
                if not suggestion:
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

    def _ordered_pick(
        self, order: list[str], day: date, meal: str, taken: set[str]
    ) -> list[dict[str, Any]]:
        """The first recipe of an order that fits the meal and is not taken (one of
        another kind than the dishes of the day before, when the order has one)."""
        fitting = [
            recipe
            for rid in order
            if rid not in taken
            and (recipe := self.recipes.get(rid)) is not None
            and self._fits_meal(recipe, meal)
            and not self.is_excluded(recipe)
        ]
        if not fitting:
            return []
        before: set[str] = set()
        for entry in self.plan.get((day - timedelta(days=1)).isoformat(), {}).values():
            if recipe := self.recipes.get(entry.get("recipe_id") or ""):
                before |= self._variety_signature(recipe)
        for recipe in fitting:
            if not self._variety_signature(recipe) & before:
                return [recipe]
        return fitting[:1]

    # ------------------------------------------------------------------
    # Shopping list
    # ------------------------------------------------------------------

    def generate_shopping_list(
        self,
        start: date,
        days: int,
        replace: bool = True,
        include_occasions: bool = True,
        occasion_id: str | None = None,
    ) -> dict[str, Any]:
        """Create shopping list items from the planned recipes.

        include_occasions (1.5): the occasions of these days join the list (their dishes,
        drinks and extras are merged with the plan's items; a list of their own for such an
        occasion is taken over, unless shopping for it has begun – an item is ticked off –
        or replace is False). occasion_id: a list only for this occasion (its own items,
        source "plan" with occasion_id; replaces only them, and takes its share out of the
        week's items that included it).
        """
        if occasion_id:
            return self._occasion_shopping_list(occasion_id, replace)
        from .occasions import occasion_entries, occasions_between

        entries: list[tuple[dict[str, Any], str]] = []
        meal_count = 0
        free_text: list[str] = []
        for offset in range(max(1, days)):
            day = start + timedelta(days=offset)
            for slot, entry in self.plan.get(day.isoformat(), {}).items():
                found, without, counted = self.entry_ingredients(day, slot, entry)
                entries.extend(found)
                free_text.extend(without)
                meal_count += counted
        absorbed: list[dict[str, Any]] = []
        separate: list[dict[str, Any]] = []
        shares: dict[str, dict[str, dict[str, float]]] = {}
        if include_occasions:
            end = start + timedelta(days=max(1, days) - 1)
            for occasion in occasions_between(self, start, end):
                own = [i for i in self.shopping if i.get("occasion_id") == occasion["id"]]
                if own and (not replace or any(i.get("status") == "completed" for i in own)):
                    separate.append(occasion)  # its own list is in use: keep it apart
                    continue
                found, without, dishes = occasion_entries(self, occasion)
                absorbed.append(occasion)
                entries.extend(found)
                free_text.extend(without)
                meal_count += dishes
                for share in aggregate(found, self.pantry):
                    shares.setdefault(share["key"], {})[occasion["id"]] = dict(share["amounts"])

        aggregated = aggregate(entries, self.pantry)
        self.price_shopping_items(aggregated, start)
        weekly = [
            i for i in self.shopping if i.get("source") == "plan" and not i.get("occasion_id")
        ]
        previous = {i.get("key"): i for i in weekly}
        if replace:
            absorbed_ids = {o["id"] for o in absorbed}
            drop = {id(i) for i in weekly}
            self.shopping = [
                i
                for i in self.shopping
                if id(i) not in drop and i.get("occasion_id") not in absorbed_ids
            ]
        new_items, total_price = self._new_plan_items(aggregated, previous, start, shares=shares)
        leftovers = self._pack_leftovers(new_items, start)
        self.shopping.extend(new_items)
        self._changed("shopping")
        result = {
            "start_date": start.isoformat(),
            "days": days,
            "meals": meal_count,
            "meals_without_recipe": free_text,
            "total_price": total_price,
            "items": self._shopping_result_items(new_items),
            "stores": self.stores_summary(),
            # 1.5.1: what whole packs leave over ("↪ 200 g übrig – z. B. für …")
            "leftovers": leftovers,
        }
        if absorbed or separate:
            result["occasions"] = [
                {"id": o["id"], "title": o["title"], "date": o["date"]} for o in absorbed
            ]
            result["occasions_separate"] = [
                {"id": o["id"], "title": o["title"], "date": o["date"]} for o in separate
            ]
        return result

    def _new_plan_items(
        self,
        aggregated: list[dict[str, Any]],
        previous: dict[Any, dict[str, Any]],
        day: date,
        extra: dict[str, Any] | None = None,
        shares: dict[str, dict[str, dict[str, float]]] | None = None,
    ) -> tuple[list[dict[str, Any]], float]:
        """Shopping items of aggregated (and priced) ingredients: ticked off again when the
        same item was ticked off before, own store choices and picked products kept; store,
        product and description. extra: fields of every item (occasion_id); shares: the
        occasions' amounts per item key (occasion_amounts, to take an occasion out later).
        Returns (items, total price)."""
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
            # 1.5: the recipe's product, else the product picked for the item before
            # ("Produkt wechseln" on the previous list)
            product_id = item.get("product_id") or (old or {}).get("product_id")
            if product_id:
                shopping_item["product_id"] = product_id
            if extra:
                shopping_item.update(extra)
            if shares and (share := shares.get(item["key"])):
                shopping_item["occasion_amounts"] = share
            new_items.append(shopping_item)
        if not self.assign_stores(new_items, day):
            # no store split: the products of the main store (or of the priced offer)
            self.attach_products(new_items, day)
        total_price = round(sum(i["price"] for i in new_items if i.get("price") is not None), 2)
        for shopping_item in new_items:
            self.update_shopping_description(shopping_item)
        return new_items, total_price

    @staticmethod
    def _shopping_result_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The items of a generated list for service / intent answers."""
        return [
            {
                "summary": i["summary"],
                "category": i["category"],
                "description": i["description"],
                "status": i["status"],
                "price": i.get("price"),
                "offer": i.get("offer"),
                **{
                    field: i.get(field)
                    for field in (
                        "branch_id",
                        "retailer",
                        "store_label",
                        "store_reason",
                        "product",
                        "product_reason",
                        "occasion_id",
                        "leftover",
                    )
                    if field in i
                },
            }
            for i in items
        ]

    def _pack_leftovers(self, items: list[dict[str, Any]], day: date) -> list[dict[str, Any]]:
        """Hints for what whole packs leave over (1.5.1): items of a perishable aisle whose
        packs hold clearly more than the recipes need get "leftover" {amount, unit, text,
        recipes (≤ 2 meals that use it)} and "↪ 200 g übrig – z. B. für …" in their
        description; nothing is planned. Returns [{item, name, amount, unit, text,
        recipes}]."""
        found: list[dict[str, Any]] = []
        for item in items:
            info = self._pack_leftover(item, day)
            if info is None:
                item.pop("leftover", None)
                continue
            item["leftover"] = info
            self.update_shopping_description(item)
            found.append({"item": item["summary"], "name": item["name"], **info})
        return found

    def _pack_leftover(self, item: dict[str, Any], day: date) -> dict[str, Any] | None:
        packs = item.get("packs")
        amounts = item.get("amounts") or {}
        if not packs or item.get("price") is None or not amounts:
            return None
        if item.get("status") == "completed":
            return None
        name = str(item.get("name") or "")
        category = item.get("category") or guess_category(name)
        if category not in PACK_LEFTOVER_CATEGORIES:
            return None
        key = item.get("key") or ingredient_key(name)
        if not key or key.split()[-1] in PACK_LEFTOVER_SKIP:
            return None
        pack: tuple[float | None, str] | None = None
        spice = False
        product = item.get("product") if isinstance(item.get("product"), dict) else None
        if product and product.get("pack_amount") and product.get("pack_unit"):
            pack = to_pricing_base(float(product["pack_amount"]), str(product["pack_unit"]))
        if not pack or not pack[0]:
            pack = None
            for entry in self.best_price(name, day):
                if entry is None or (cost := package_cost(amounts, key, entry, category)) is None:
                    continue
                pack, spice = to_pricing_base(entry.amount, entry.unit), entry.spice
                if cost[1] == packs:
                    break
        if not pack or not pack[0] or pack[1] not in PACK_LEFTOVER_MIN:
            return None
        pack_amount, pack_unit = float(pack[0]), pack[1]
        left = packs * pack_amount - package_need(
            amounts, key, pack_amount, pack_unit, spice, category
        )
        if left < PACK_LEFTOVER_MIN[pack_unit] or left < PACK_LEFTOVER_SHARE * pack_amount:
            return None
        left = float(round(left / 10) * 10) if pack_unit in ("g", "ml") else float(int(left))
        return {
            "amount": left,
            "unit": pack_unit,
            "text": pack_text(left, pack_unit),
            "recipes": self._leftover_recipes(item),
        }

    def _leftover_recipes(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        """Up to PACK_LEFTOVER_RECIPES meals (kind meal) that use the item and are not
        the ones it was bought for."""
        planned = {fold(str(r)) for r in item.get("recipes") or []}
        result: list[dict[str, Any]] = []
        hits = self.find_by_ingredients([str(item.get("name") or "")], count=40)
        # favourites first, then as found (most of the recipe is the item); no ready meals
        hits.sort(key=lambda h: not h.get("favorite"))
        for hit in hits:
            recipe = self.recipes.get(hit["id"])
            if (
                recipe is None
                or recipe_kind(recipe) != KIND_MEAL
                or fold(recipe["name"]) in planned
                or READY_MEAL_TAG in self.recipe_tags_folded(recipe)
                or self.is_excluded(recipe)
            ):
                continue
            result.append({"id": recipe["id"], "name": recipe["name"]})
            if len(result) >= PACK_LEFTOVER_RECIPES:
                break
        return result

    def _occasion_shopping_list(self, occasion_id: str, replace: bool = True) -> dict[str, Any]:
        """generate_shopping_list() for one occasion ("🛒 Einkaufsliste für den Anlass")."""
        from .occasions import occasion_date, occasion_entries, require_occasion

        occasion = require_occasion(self, occasion_id)
        day = occasion_date(occasion)
        entries, without, dishes = occasion_entries(self, occasion)
        aggregated = aggregate(entries, self.pantry)
        self.price_shopping_items(aggregated, day)
        own = [i for i in self.shopping if i.get("occasion_id") == occasion["id"]]
        previous = {i.get("key"): i for i in own}
        if replace:
            self.shopping = [i for i in self.shopping if i.get("occasion_id") != occasion["id"]]
            changed = self._take_out_occasion(occasion)  # it was part of the week's list
        else:
            changed = []
        new_items, total_price = self._new_plan_items(
            aggregated, previous, day, extra={"occasion_id": occasion["id"]}
        )
        leftovers = self._pack_leftovers(new_items, day)
        self.shopping.extend(new_items)
        for item in changed:
            self._price_shopping_item(item)
        self._changed("shopping")
        return {
            "start_date": day.isoformat(),
            "days": 1,
            "meals": dishes,
            "meals_without_recipe": without,
            "total_price": total_price,
            "items": self._shopping_result_items(new_items),
            "stores": self.stores_summary(),
            "occasion": {"id": occasion["id"], "title": occasion["title"], "date": day.isoformat()},
            "leftovers": leftovers,
        }

    def _take_out_occasion(self, occasion: dict[str, Any]) -> list[dict[str, Any]]:
        """An occasion that joined the week's list gets a list of its own: its amounts go
        out of the open week items (items only it needed are removed). Returns the changed
        items (to be priced again)."""
        from .occasions import occasion_label

        label = occasion_label(occasion)
        changed: list[dict[str, Any]] = []
        for item in list(self.shopping):
            shares = item.get("occasion_amounts")
            if (
                not isinstance(shares, dict)
                or occasion["id"] not in shares
                or item.get("status") == "completed"
            ):
                continue
            share = shares.pop(occasion["id"]) or {}
            if not shares:
                item.pop("occasion_amounts", None)
            recipes = [r for r in item.get("recipes") or [] if r != label]
            if not recipes:
                self.shopping.remove(item)  # only the occasion needed it
                continue
            amounts = {
                unit: round(float(amount) - float(share.get(unit) or 0), 4)
                for unit, amount in (item.get("amounts") or {}).items()
            }
            amounts = {unit: amount for unit, amount in amounts.items() if amount > 1e-6}
            item["recipes"] = recipes
            item["amounts"] = amounts
            rebuilt = aggregate(
                [({"name": item["name"], "amount": a, "unit": u}, "") for u, a in amounts.items()]
                or [({"name": item["name"]}, "")]
            )
            if rebuilt:
                item["summary"] = rebuilt[0]["summary"]
            changed.append(item)
        return changed

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
        product_id: str | None = None,
    ) -> dict[str, Any]:
        """Add a manual shopping item.

        store: branch (id, label, store name) to buy it at (a manual store choice).
        price/pack: price of one pack and its size as chosen by the user (e.g. from the
        article search); offer_id: a saved offer (its store, price and pack).
        product_id (1.5): a product of the product database (search across all stores):
        the item is that product (product_id), priced with its offer or regular price at its
        chain (chosen; at the given store's chain its twin), bought at that chain like a
        picked offer, and remembered as picked for the ingredient.
        Without them the price is estimated at the main store (or the given store).
        Spoken amounts become digits ("zwei Liter Milch" -> "2 Liter Milch").
        """
        product = None
        if product_id:
            from .products import require_product

            product = require_product(self, product_id)
        summary = normalize_spoken_quantity(str(summary or "").strip())
        if not summary and product is not None:
            from .products import product_title

            summary = product_title(product)
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
        if product is not None:
            if offer is None and price is None and not pack:
                return self._add_product_item(item, product, store, branch, retailer)
            item["product_id"] = product["id"]
            self._product_key(item, product)
            if offer is None and not store:
                # an own price of the product: at its chain
                branch = self._product_branch(product, None)
                retailer = product["retailer"]
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
        if offer is not None:
            # the product of the picked offer (a live leaflet offer is stored now) is
            # remembered for this ingredient (product database, 1.5)
            from .products import PICK_PICKED, product_for_offer, record_pick

            product_id = product_for_offer(self, offer, item["key"])
            if product_id is not None:
                if chosen is not None:
                    chosen["product_id"] = product_id
                record_pick(self, item["key"], product_id, PICK_PICKED)
        if branch is not None and (store or branch["id"] != self.main_branch):
            # an offer of the main store is no store choice: the item stays automatic
            item["store_override"] = branch["id"]
            if not store and chosen is not None:
                chosen["pins_store"] = True  # until the offer ends (see assign_stores)
        if product is not None and offer is None:
            from .products import PICK_PICKED, record_pick

            if chosen is not None and chosen.get("retailer") == product["retailer"]:
                chosen["product_id"] = product["id"]
            record_pick(self, item["key"], product["id"], PICK_PICKED)
        return self._append_item(item, retailer, branch)

    def _append_item(
        self,
        item: dict[str, Any],
        retailer: str | None,
        branch: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Price, remember and append a new manual item (shopping_add())."""
        self._price_shopping_item(item, retailer, branch["id"] if branch else None)
        self.remember_article(item["summary"], item["key"], item.get("retailer") or retailer)
        self.shopping.append(item)
        if self.trip_depends_on_items():
            # an own store choice or one more offer there: other offers of that store may
            # now be worth the trip
            self._reassign_open_items()
        self._changed("shopping")
        return item

    def _product_key(self, item: dict[str, Any], product: dict[str, Any]) -> None:
        """The ingredient of an item that is a product of the product database: its own key
        when the product has it, else the product's ingredient its name names ("Bergland
        Butter" is "butter"), else the product's first ingredient when the item is named
        like the product."""
        from .offers import offer_matches
        from .products import product_title

        keys = [str(k) for k in product.get("keys") or [] if k]
        if not keys or item["key"] in keys:
            return
        name = str(item.get("name") or "")
        key = next((k for k in keys if offer_matches(name, k)), None)
        if key is None and fold(name) in (fold(product_title(product)), fold(product["name"])):
            key = keys[0]
        if key is not None:
            item["key"] = key
            if product.get("category"):
                item["category"] = product["category"]

    def _product_chosen(
        self,
        product: dict[str, Any],
        branch_id: str | None,
    ) -> dict[str, Any] | None:
        """The price picked with a product (chosen): its running offer (a copy, so the store
        choice ends with the offer like a picked offer) or its regular price; None without a
        price per pack."""
        from .products import product_entry, product_title

        entry = product_entry(product, self.today(), branch_id)
        if entry is None:
            return None
        chosen: dict[str, Any] = {
            "name": product_title(product),
            "price": round(entry.price, 2),
            "amount": entry.amount,
            "unit": entry.unit,
            "retailer": product["retailer"],
            "product_id": product["id"],
        }
        if entry.offer:
            offer = {
                **entry.offer,
                "store_id": product["retailer"],
                "image": product.get("image"),
                "brand": product.get("brand") or "",
            }
            chosen["offer_id"] = offer.get("id")
            chosen["offer"] = {k: offer.get(k) for k in _OFFER_COPY_FIELDS}
        return chosen

    def _product_branch(
        self, product: dict[str, Any], branch: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """The branch a product is bought at: the given branch of its chain, else the first
        selected branch of its chain its offer applies to (main branch first)."""
        if branch is not None and branch.get("retailer") == product["retailer"]:
            return branch
        offer = product.get("offer") or {}
        from .catalog import _branch_ids, _branch_index

        allowed = None
        if offer.get("zip_codes") or offer.get("branch_ids"):
            allowed = set(
                _branch_ids(
                    {
                        "retailer": product["retailer"],
                        "zip_codes": offer.get("zip_codes"),
                        "branch_ids": offer.get("branch_ids"),
                    },
                    _branch_index(self)[0],
                )
            )
        candidates = [
            b
            for b in self.selected_branches()
            if b.get("retailer") == product["retailer"] and b.get("id")
        ]
        return next(
            (b for b in candidates if allowed is None or not allowed or b["id"] in allowed),
            None,
        )

    def _add_product_item(
        self,
        item: dict[str, Any],
        product: dict[str, Any],
        store: str | None,
        branch: dict[str, Any] | None,
        retailer: str | None,
    ) -> dict[str, Any]:
        """shopping_add() of a product (product_id) without an own price or offer."""
        from .products import PICK_PICKED, _at_retailer, _store_of, record_pick

        item["product_id"] = product["id"]
        self._product_key(item, product)
        record_pick(self, item["key"], product["id"], PICK_PICKED)
        if store:
            # the user's store: the product there (a branded product's twin at another
            # chain; else that chain's product is chosen by the list)
            if retailer and retailer != product["retailer"]:
                db = _store_of(self)
                twin = _at_retailer(db, product["id"], retailer) if db is not None else None
                if twin is None:
                    if branch is not None:
                        item["store_override"] = branch["id"]
                    return self._append_item(item, retailer, branch)
                product = twin
            chosen = self._product_chosen(product, branch.get("id") if branch else None)
            if chosen is not None:
                item["chosen"] = chosen
            if branch is not None:
                item["store_override"] = branch["id"]
            return self._append_item(item, product["retailer"], branch)
        # like a picked offer: bought at the product's chain (the main branch stays
        # automatic), until its offer ends
        target = self._product_branch(product, None)
        chosen = self._product_chosen(product, target.get("id") if target else None)
        if chosen is not None:
            item["chosen"] = chosen
        if target is not None and target["id"] != self.main_branch:
            item["store_override"] = target["id"]
            if chosen is not None:
                chosen["pins_store"] = True
        return self._append_item(item, product["retailer"], target)

    def shopping_set_product(
        self, uid: str, product_id: str | None, remember: str = REMEMBER_NONE
    ) -> dict[str, Any]:
        """ "Produkt wechseln": buy a shopping item as this product of the product database.

        The item becomes the product (product_id; also when the list is created again),
        priced with its offer or regular price (chosen). With a store split the item moves to
        the product's chain when it is bought elsewhere (store_override; the same chain keeps
        the item's branch). remember: none | pick (counts as picked for the ingredient) |
        favorite (⭐ for the ingredient – binds the store from now on). product_id None / ""
        lets the list choose the product again. Errors shopping_item_not_found,
        product_not_found, invalid_remember.
        """
        from .products import PICK_PICKED, record_pick, require_product, set_favorite

        if remember not in REMEMBER_MODES:
            raise _error("invalid_remember", remember=remember)
        item = next((i for i in self.shopping if i.get("uid") == uid), None)
        if item is None:
            raise _error("shopping_item_not_found")
        chosen = item.get("chosen") if isinstance(item.get("chosen"), dict) else None
        if not product_id:
            # the store came with the product (its chain): automatic again, like the product
            from .products import _store_of

            db = _store_of(self)
            old = db.get(item.get("product_id")) if db is not None else None
            chains = {(old or {}).get("retailer"), (chosen or {}).get("retailer")} - {None}
            override = self.get_branch(item.get("store_override"))
            if override is not None and override.get("retailer") in chains:
                item.pop("store_override", None)
            item.pop("product_id", None)
            if chosen is not None and chosen.get("product_id"):
                item.pop("chosen", None)
            self._reprice_after_change(item)
            return item
        product = require_product(self, product_id)
        if not item.get("key"):
            item["key"] = ingredient_key(self._item_name(item))
        key = str(item["key"])
        item["product_id"] = product["id"]
        current = self.get_branch(item.get("branch_id")) if item.get("branch_id") else None
        branch = self._product_branch(product, current)
        new_chosen = self._product_chosen(product, branch.get("id") if branch else None)
        if new_chosen is not None:
            item["chosen"] = new_chosen
        else:
            item.pop("chosen", None)
        if (
            self.store_split_active
            and branch is not None
            and (current is None or current.get("id") != branch["id"])
        ):
            item["store_override"] = branch["id"]  # the user's choice of this product
        if remember == REMEMBER_FAVORITE:
            set_favorite(self, product["id"], key)
        elif remember == REMEMBER_PICK:
            record_pick(self, key, product["id"], PICK_PICKED)
        self._reprice_after_change(item)
        return item

    def _reprice_after_change(self, item: dict[str, Any]) -> None:
        """Store, price, product and description of an item after its product changed."""
        item.pop("leftover", None)  # another pack (1.5.1)
        if item.get("status") != "completed" and self.trip_depends_on_items():
            self._reassign_open_items()
        else:
            chosen = item.get("chosen") if isinstance(item.get("chosen"), dict) else {}
            self._price_shopping_item(item, chosen.get("retailer"))
        self._changed("shopping")

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
            self.attach_products([item], None, {id(item): cost})
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
                bought = status == "completed" and item.get("status") != "completed"
                if summary is not None:
                    item["summary"] = summary
                if status is not None:
                    item["status"] = status
                if bought:
                    self._product_bought(item)
                if description is not None:
                    item["description"] = description
                if renamed and "amounts" in item:
                    self._reparse_shopping_item(item)
                self._changed("shopping")
                return item
        raise _error("shopping_item_not_found")

    def _product_bought(self, item: dict[str, Any]) -> None:
        """A ticked-off item: its product counts as bought for the ingredient (1.5)."""
        from .products import PICK_BOUGHT, product_for_item, record_pick

        product_id = product_for_item(self, item)
        if product_id is not None and item.get("key"):
            record_pick(self, str(item["key"]), product_id, PICK_BOUGHT)

    def _reparse_shopping_item(self, item: dict[str, Any]) -> None:
        """Amount, product and price after the text of an item (1.3 item) was changed."""
        item.pop("leftover", None)  # other amounts (1.5.1)
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
            item.pop("product_id", None)  # and so was the picked product (1.5)
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
        # 1.5.1: the kind and who chose it (an import keeps the user's choice)
        "kind",
        "kind_source",
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
        from .ai import ai_panel
        from .drinks import alcohol_allowed
        from .occasions import occasion_meta, occasions_export
        from .season import recipe_season_export, season_aware, season_info

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
            # the product database (1.5): counts only, the products come page by page
            # (websocket essensplaner/products)
            "products": product_counts(self),
            # occasions (1.5) from 30 days back with items, costs and labels; templates,
            # courses and whether drink suggestions may have alcohol
            "occasions": occasions_export(self),
            "occasion_meta": {**occasion_meta(), "alcohol": alcohol_allowed(self)},
            # the season (1.5): what is in season today, the times of the year and the
            # recipes that fit (🍂 badges; recipes without a season are left out)
            "season": {**season_info(self.today()), "season_aware": season_aware(self)},
            "recipe_season": recipe_season_export(self),
            # the AI buttons of the panel (1.5): which features are switched on and whether
            # the AI is reachable – no entity settings, prompts or answers
            "ai": ai_panel(self.hass, self),
            # recipe kinds (1.5.1): [{id, label, emoji}] for the filters and the editor
            "kinds": kinds_view(),
            "leftover_max_days": LEFTOVER_MAX_DAYS,
        }


def leftover_title(day: date, src_day: date, src_meal: str, dish: str) -> str:
    """'🍲 Reste von Dienstag (Lasagne)' ('🍲 Reste vom Mittagessen (Lasagne)' the same
    day; without a dish only '🍲 Reste von Dienstag')."""
    if src_day == day:
        when = f"vom {MEAL_LABELS.get(src_meal, src_meal)}"
    else:
        when = f"von {WEEKDAY_NAMES[src_day.weekday()]}"
    text = f"{LEFTOVER_EMOJI} Reste {when}"
    return f"{text} ({dish})" if dish else text


def _load_starter_recipes() -> list[dict[str, Any]]:
    path = Path(__file__).parent / "starter_recipes.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        _LOGGER.warning("Could not load starter recipes: %s", err)
        return []
