"""Branches, store specific prices and the price matrix (mixin for the manager).

Price order for a retailer r (first match wins, see store_book()):
own store price of r -> learned store price of r (<= 180 days, REWE online before leaflet)
-> own general price -> learned general price -> default estimate.
General prices that carry a store label of another retailer are that retailer's prices
and are skipped for r.

Branches (Filialen) are the user's shops: {id ("man_<ms>" | "osm_node_123" | "osm_way_…"),
retailer, name, label, street, postcode, city, postcode_guessed, lat, lon, source (osm|manual),
selected, priority, near, route, rewe_market_id, retailer_guessed, added, updated}.
Offers are fetched per postcode of the selected branches (offer_targets()). Branches are
added manually or from the OpenStreetMap search (branches.py, cached in branch_search).
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
import logging
import re
from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from .const import (
    CONF_SPLIT_MIN_PERCENT,
    CONF_SPLIT_MIN_SAVING,
    CONF_SPLIT_MODE,
    CONF_SPLIT_OFFER_MIN,
    CONF_SPLIT_TRIP_MIN,
    DEFAULT_SPLIT_MIN_PERCENT,
    DEFAULT_SPLIT_MIN_SAVING,
    DEFAULT_SPLIT_MODE,
    DEFAULT_SPLIT_OFFER_MIN,
    DEFAULT_SPLIT_TRIP_MIN,
    SPLIT_FLOOR,
    SPLIT_MAIN_EXCEPTIONS,
    SPLIT_MODES,
    SPLIT_OFF,
)
from .economy import _key_by_name, _offer_short
from .ingredients import (
    _singular,
    fold,
    guess_category,
    ingredient_key,
    normalize_spoken_quantity,
    parse_ingredient,
    to_base,
)
from .offers import offer_matches, short_key
from .pricing import (
    LayeredPriceBook,
    PriceEntry,
    PriceIndex,
    convert,
    format_eur,
    item_cost,
    lookup_keys,
    make_entry,
    offer_pack,
    pack_text,
    piece_weight_known,
    unit_price,
)
from .retailers import (
    ALDI_NORD,
    ALDI_SUED,
    RETAILERS,
    aldi_for_postcode,
    resolve_retailer,
    retailer_for_store_id,
    retailer_name,
)

if TYPE_CHECKING:
    from .manager import EssensplanerManager

_LOGGER = logging.getLogger(__name__)

DATA_VERSION = 3
# learned store prices older than this are ignored for lookups (kept in storage)
STALE_DAYS = 180
# learned store price sources, most trusted first
LEARNED_SOURCES = ("rewe_online", "leaflet")
SOURCE_USER = "user"
SOURCE_LEAFLET = "leaflet"

# offers are searched for at most this many postcodes (main branch first)
MAX_OFFER_TARGETS = 4
# learned store prices: price history length and minimum distance of unchanged entries
HISTORY_MAX = 12
HISTORY_INTERVAL_DAYS = 7
# a learned price per base unit must be within this factor range of the estimate
PLAUSIBLE_MIN = 0.3
PLAUSIBLE_MAX = 3.0

BRANCH_SOURCES = ("osm", "manual")
_OSM_ID_RE = re.compile(r"^osm_(node|way|relation)_\d+$")
_POSTCODE_RE = re.compile(r"^\d{5}$")
_BRANCH_TEXT_FIELDS = ("name", "street", "city", "rewe_market_id")
# words for "the main branch" (after fold(), filler words removed)
_MAIN_WORDS = {
    "main",
    "hauptladen",
    "hauptfiliale",
    "hauptmarkt",
    "hauptgeschaeft",
    "hauptsupermarkt",
    "stammladen",
    "stammfiliale",
    "stammmarkt",
    "standardladen",
    "laden",
}
# store words that name no store ("Was muss ich im Supermarkt kaufen?" = the whole list);
# "mein Laden" is the main branch, "im Laden" any store
_GENERIC_STORE_WORDS = {
    "laden",
    "supermarkt",
    "markt",
    "geschaeft",
    "einkauf",
    "einkaufen",
    "discounter",
    "lebensmittelladen",
    "lebensmittelgeschaeft",
}
_FILLER_WORDS = {
    "bei",
    "beim",
    "im",
    "in",
    "am",
    "zum",
    "zur",
    "vom",
    "von",
    "der",
    "die",
    "das",
    "dem",
    "den",
    "mein",
    "meine",
    "meinem",
    "meinen",
    "meiner",
    "unser",
    "unserem",
    "unseren",
    "filiale",
}
_PREPOSITION_WORDS = {
    "bei",
    "beim",
    "im",
    "in",
    "am",
    "zum",
    "zur",
    "der",
    "die",
    "das",
    "dem",
    "den",
}
# shopping item fields that point to a branch (cleared when the branch is removed)
SHOPPING_STORE_FIELDS = (
    "branch_id",
    "retailer",
    "store_label",
    "store_reason",
    "store_override",
    "saving",
    "alternatives",
)
# fields of the automatic store assignment (cleared while the split is inactive)
ASSIGNED_FIELDS = ("branch_id", "retailer", "store_label", "store_reason", "saving", "alternatives")
# why an item is bought at its store
REASON_MAIN = "main"
REASON_OFFER = "offer"
REASON_CHEAPER = "cheaper"
REASON_MANUAL = "manual"
REASON_PREFERRED = "preferred"
MAX_ALTERNATIVES = 4
NO_STORE_LABEL = "Ohne Laden"
# store texts that reset a manual store choice
_AUTO_WORDS = {"auto", "automatisch", "automatic", "standard", "zuruecksetzen"}
# words that name no product ("Was kaufe ich immer bei Lidl?" is a question)
_NO_PRODUCT_WORDS = {
    "was",
    "wer",
    "wie",
    "wo",
    "wann",
    "warum",
    "welche",
    "welcher",
    "welches",
    "welchen",
    "das",
    "dies",
    "diese",
    "dieses",
    "es",
    "alles",
    "nichts",
    "etwas",
    "sachen",
    "dinge",
    "zeug",
    "artikel",
    "produkte",
    "denn",
    "eigentlich",
    "sonst",
    "noch",
}
# description parts written by the integration (rebuilt on every change)
_DESCRIPTION_PREFIXES = ("🏪", "≈ ", "🏷️")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _nested(value: Any) -> dict[str, dict[str, dict[str, Any]]]:
    """{retailer: {key: entry}} with invalid parts dropped."""
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for retailer, entries in _dict(value).items():
        if isinstance(entries, dict):
            result[str(retailer)] = {str(k): v for k, v in entries.items() if isinstance(v, dict)}
    return result


def _source_rank(source: str) -> int:
    return LEARNED_SOURCES.index(source) if source in LEARNED_SOURCES else len(LEARNED_SOURCES)


def _last_seen(item: dict[str, Any]) -> date | None:
    stamps = [str(s) for s in (item.get("seen"), item.get("updated")) if s]
    if not stamps:
        return None
    try:
        return date.fromisoformat(max(stamps)[:10])
    except ValueError:
        return None


def _alias_keys(entry: PriceEntry | None) -> list[str]:
    """The full lookup keys of an entry's name and aliases.

    Only full keys: the short key of an alias with an adjective ("stückige Tomaten" ->
    "tomate") would make a canned-tomato price the price of fresh tomatoes.
    """
    if entry is None:
        return []
    keys: list[str] = []
    for name in [entry.name, *entry.aliases]:
        key = lookup_keys(name)[0]
        if key and key not in keys:
            keys.append(key)
    return keys


def valid_postcode(value: Any) -> str | None:
    """A German postcode ('80331') or None."""
    text = re.sub(r"\s", "", str(value or ""))
    return text if _POSTCODE_RE.fullmatch(text) else None


def _coordinate(value: Any, limit: float) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 6) if -limit <= number <= limit else None


def _number(value: Any) -> int | float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0
    return int(number) if number.is_integer() else number


def _distances(value: Any) -> dict[str, int]:
    """{zone: meters} with invalid parts dropped."""
    result: dict[str, int] = {}
    for zone, meters in _dict(value).items():
        try:
            result[str(zone)] = round(float(meters))
        except (TypeError, ValueError):
            continue
    return result


def _priority(branch: dict[str, Any]) -> float:
    try:
        return float(branch.get("priority") or 0)
    except (TypeError, ValueError):
        return 0.0


def _comparable(base: str, other: str) -> bool:
    return base == other or {base, other} <= {"g", "ml"}


def _price_info(entry: PriceEntry) -> dict[str, Any]:
    per = unit_price(entry)
    return {
        "price": round(entry.price, 2),
        "amount": entry.amount,
        "unit": entry.unit,
        "unit_price": round(per[0], 5) if per else None,
        "base": per[1] if per else None,
    }


class StoresMixin:
    """Mixed into EssensplanerManager (before EconomyMixin)."""

    # storage (top-level keys of the store file)
    data_version: int
    branches: list[dict[str, Any]]
    main_branch: str | None
    store_prices_user: dict[str, dict[str, dict[str, Any]]]
    store_prices_learned: dict[str, dict[str, dict[str, Any]]]
    store_preferences: dict[str, str]
    price_sources_meta: dict[str, Any]
    branch_search: dict[str, Any]
    article_history: list[dict[str, Any]]
    # caches
    _store_books: dict[str, LayeredPriceBook]
    _store_books_day: date | None
    _default_index: PriceIndex | None
    _default_index_source: int | None
    _price_ctx: tuple[Any, ...] | None
    _selected_memo: tuple[Any, list[dict[str, Any]]] | None
    _branch_lock: asyncio.Lock | None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _init_store_data(self: EssensplanerManager) -> None:
        """Empty store data (called from the manager's __init__)."""
        self.data_version = 1
        self.branches = []
        self.main_branch = None
        self.store_prices_user = {}
        self.store_prices_learned = {}
        self.store_preferences = {}
        self.price_sources_meta = {}
        self.branch_search = {}
        self.article_history = []
        self._store_books = {}
        self._store_books_day = None
        self._default_index = None
        self._default_index_source = None
        self._price_ctx = None
        self._selected_memo = None
        self._branch_lock = None  # one OpenStreetMap search at a time (branches.py)
        self._other_product_cache: dict[tuple[str, str], bool] = {}

    def _load_store_data(self: EssensplanerManager, data: dict[str, Any]) -> None:
        """Read the 1.3 keys (missing in 1.2 data)."""
        try:
            self.data_version = int(data.get("data_version") or 1)
        except (TypeError, ValueError):
            self.data_version = 1
        self.branches = [b for b in _list(data.get("branches")) if isinstance(b, dict)]
        main = data.get("main_branch")
        self.main_branch = str(main) if main else None
        self.store_prices_user = _nested(data.get("store_prices_user"))
        self.store_prices_learned = _nested(data.get("store_prices_learned"))
        self.store_preferences = {
            str(k): str(v) for k, v in _dict(data.get("store_preferences")).items() if v
        }
        self.price_sources_meta = _dict(data.get("price_sources_meta"))
        self.branch_search = _dict(data.get("branch_search"))
        self.article_history = [
            a for a in _list(data.get("article_history")) if isinstance(a, dict)
        ]
        self._store_books = {}

    def _store_data(self: EssensplanerManager) -> dict[str, Any]:
        """The 1.3 keys for saving."""
        return {
            "data_version": self.data_version,
            "branches": self.branches,
            "main_branch": self.main_branch,
            "store_prices_user": self.store_prices_user,
            "store_prices_learned": self.store_prices_learned,
            "store_preferences": self.store_preferences,
            "price_sources_meta": self.price_sources_meta,
            "branch_search": self.branch_search,
            "article_history": self.article_history,
        }

    def _migrate_v2(self: EssensplanerManager) -> bool:
        """Upgrade 1.2 / 1.3.0 data (idempotent). Returns True if something changed.

        - v2 (1.2 -> 1.3): own prices with a store label are also stored as store prices of
          that retailer (only once, when upgrading; the general price is kept). A plain
          "Aldi" that only the postcode decided is kept as a label (no "retailer") and its
          store price is marked "guessed" (moved to the Aldi of your branch later).
        - v3: prices and plan items stored under the 1.2 key of another product
          ("Gehackte Tomaten" under "tomate") get that product's key.
        - every load: offers of a known retailer get a "retailer"; offer keys that name
          another product are corrected (canned tomato offers never price fresh ones).
        """
        changed = False
        if self.data_version < 2:
            for key, entry in self.prices_user.items():
                if not isinstance(entry, dict) or not entry.get("store"):
                    continue
                certain = entry.get("retailer") or resolve_retailer(
                    entry["store"], self._branch_retailers()
                )
                retailer = certain or self.resolve_store(entry["store"])
                if not retailer:
                    continue
                if certain:
                    entry["retailer"] = certain
                bucket = self.store_prices_user.setdefault(retailer, {})
                if key not in bucket:
                    bucket[key] = {
                        "name": entry.get("name") or key,
                        "price": entry.get("price"),
                        "amount": entry.get("amount") or 1,
                        "unit": entry.get("unit") or "Stück",
                        "source": SOURCE_USER,
                        "updated": entry.get("updated") or dt_util.utcnow().isoformat(),
                        "migrated": True,
                    }
                    if not certain:
                        bucket[key]["guessed"] = True
        if self.data_version < 3:
            self._rekey_variants()
        if self.data_version < DATA_VERSION:
            self.data_version = DATA_VERSION
            changed = True
        for offer in self.offers:
            if not offer.get("retailer") and (retailer := self._certain_offer_retailer(offer)):
                offer["retailer"] = retailer
                changed = True
            keys = self.offer_keys(offer)
            if keys != (offer.get("keys") or []):
                offer["keys"] = keys
                changed = True
        if changed:
            self._invalidate_prices()
        return changed

    def _rekey_variants(self: EssensplanerManager) -> None:
        """Move prices / plan items stored under the key of another product (1.2 keys)."""

        def rekey(bucket: dict[str, Any]) -> None:
            for key in list(bucket):
                item = bucket[key]
                name = str(item.get("name") or "") if isinstance(item, dict) else ""
                if not self.names_other_product(name, key):
                    continue
                new = self.variant_key(name)
                if new and new != key:
                    del bucket[key]
                    bucket.setdefault(new, item)

        rekey(self.prices_user)
        rekey(self.prices_learned)
        for buckets in (self.store_prices_user, self.store_prices_learned):
            for bucket in buckets.values():
                rekey(bucket)
        for item in self.shopping:
            if item.get("source") != "plan" or not item.get("key"):
                continue
            name = self._item_name(item)
            if self.names_other_product(name, item["key"]):
                item["key"] = self.variant_key(name)

    def offer_keys(self: EssensplanerManager, offer: dict[str, Any]) -> list[str]:
        """The offer's ingredient keys without keys of another product.

        A canned-tomato offer found for "Tomaten" ("Oro di Parma Gehackte Tomaten", key
        "tomate") gets the key of its own product ("gehackte tomate") instead. Short keys
        ("ei") need an offer sold by count: a 100-g bag of "Schoko-Eier" is no egg offer.
        """
        product = str(offer.get("product") or offer.get("title") or "")
        pack = offer_pack(offer)
        keys: list[str] = []
        for key in offer.get("keys") or []:
            if self.names_other_product(product, key):
                key = self.variant_key(product)
            if short_key(key) and pack is not None and pack[1] != "Stück":
                continue
            if key and key not in keys:
                keys.append(key)
        return keys

    @staticmethod
    def _certain_offer_retailer(offer: dict[str, Any]) -> str | None:
        """Retailer of an offer without guessing (a plain 'Aldi' stays open)."""
        return retailer_for_store_id(offer.get("store_id")) or resolve_retailer(offer.get("store"))

    def _adopt_guessed_aldi(self: EssensplanerManager) -> None:
        """Store prices of a plain 'Aldi' guessed from the postcode follow the Aldi branch."""
        aldis = {b.get("retailer") for b in self.selected_branches()} & {ALDI_SUED, ALDI_NORD}
        if len(aldis) != 1:
            return
        target = aldis.pop()
        other = ALDI_NORD if target == ALDI_SUED else ALDI_SUED
        bucket = self.store_prices_user.get(other) or {}
        for key in [k for k, v in bucket.items() if v.get("guessed")]:
            item = bucket.pop(key)
            item.pop("guessed", None)
            self.store_prices_user.setdefault(target, {}).setdefault(key, item)
        if other in self.store_prices_user and not bucket:
            del self.store_prices_user[other]

    # ------------------------------------------------------------------
    # Branches (minimal accessors; management follows in a later phase)
    # ------------------------------------------------------------------

    def selected_branches(self: EssensplanerManager) -> list[dict[str, Any]]:
        """Selected branches: main branch first, then by priority (ascending).

        Memoized (called for every price lookup); the key covers everything that matters.
        """
        memo_key = (
            self.main_branch,
            tuple(
                (id(b), b.get("id"), b.get("selected", True), b.get("priority"), b.get("name"))
                for b in self.branches
            ),
        )
        memo = self._selected_memo
        if memo is not None and memo[0] == memo_key:
            return list(memo[1])
        result = self._sorted_selected()
        self._selected_memo = (memo_key, result)
        return list(result)

    def _sorted_selected(self: EssensplanerManager) -> list[dict[str, Any]]:
        selected = [
            b for b in self.branches if b.get("selected", True) or b.get("id") == self.main_branch
        ]

        def order(branch: dict[str, Any]) -> tuple[int, float, str]:
            try:
                priority = float(branch.get("priority") or 0)
            except (TypeError, ValueError):
                priority = 0.0
            return (branch.get("id") != self.main_branch, priority, fold(branch.get("name") or ""))

        return sorted(selected, key=order)

    def get_main_branch(self: EssensplanerManager) -> dict[str, Any] | None:
        """The main branch (None without one)."""
        if not self.main_branch:
            return None
        return next((b for b in self.branches if b.get("id") == self.main_branch), None)

    @property
    def main_retailer(self: EssensplanerManager) -> str | None:
        """Retailer of the main branch (None without main branch)."""
        branch = self.get_main_branch()
        if branch is None:
            return None
        return branch.get("retailer") or None

    @property
    def main_postcode(self: EssensplanerManager) -> str:
        """Postcode of the main branch, else the zip code option."""
        branch = self.get_main_branch()
        if branch and branch.get("postcode"):
            return str(branch["postcode"])
        return self.zip_code

    def active_retailers(self: EssensplanerManager) -> list[str]:
        """Retailers of the selected branches (main first), else the offer_stores option."""
        result: list[str] = []
        for branch in self.selected_branches():
            retailer = branch.get("retailer")
            if retailer and retailer not in result:
                result.append(retailer)
        return result or self.offer_stores

    def resolve_store(self: EssensplanerManager, text: str | None) -> str | None:
        """Retailer id for a store text ('Aldi' -> the selected Aldi variant)."""
        return resolve_retailer(text, self.active_retailers(), self.main_postcode)

    def require_retailer(self: EssensplanerManager, text: str | None) -> str:
        """Retailer id for a store text or a clear error."""
        retailer = self.resolve_store(text)
        if retailer is None:
            from .manager import _error  # avoid an import cycle

            raise _error("unknown_store", store=text or "")
        return retailer

    def offer_retailer(self: EssensplanerManager, offer: dict[str, Any]) -> str | None:
        """Retailer of an offer (stored, from the marktguru id or from the store name).

        A plain 'Aldi' is resolved with the current branches each time (not stored).
        """
        if offer.get("retailer"):
            return offer["retailer"]
        return retailer_for_store_id(offer.get("store_id")) or self.resolve_store(
            offer.get("store")
        )

    def _branch_retailers(self: EssensplanerManager) -> list[str]:
        """Retailers of the selected branches (no fallback to the options)."""
        return [b["retailer"] for b in self.selected_branches() if b.get("retailer")]

    def _price_context(self: EssensplanerManager) -> tuple[Any, ...]:
        return (self.main_retailer, tuple(self.active_retailers()))

    def _ensure_price_context(self: EssensplanerManager) -> None:
        """Drop cached costs when the main branch or the selected retailers changed."""
        context = self._price_context()
        if context != self._price_ctx:
            self._invalidate_prices()
            self._price_ctx = context

    # ------------------------------------------------------------------
    # Branch management
    # ------------------------------------------------------------------

    def get_branch(self: EssensplanerManager, branch_id: str | None) -> dict[str, Any] | None:
        """The branch with this id (None if unknown)."""
        if not branch_id:
            return None
        return next((b for b in self.branches if b.get("id") == branch_id), None)

    @staticmethod
    def _default_label(branch: dict[str, Any]) -> str:
        """'<Retailer> <street or city>' ('Aldi Süd Hauptstraße 5')."""
        retailer = retailer_name(branch.get("retailer")) or str(branch.get("name") or "")
        place = str(branch.get("street") or "").strip() or str(branch.get("city") or "").strip()
        return f"{retailer} {place}".strip()

    def branch_label(self: EssensplanerManager, branch: dict[str, Any] | None) -> str:
        """Display name of a branch (own label, else '<Retailer> <street or city>')."""
        if not branch:
            return ""
        return str(branch.get("label") or "").strip() or self._default_label(branch)

    def branch_postcodes(self: EssensplanerManager) -> list[str]:
        """Valid postcodes of the selected branches (main branch first)."""
        result: list[str] = []
        for branch in self.selected_branches():
            postcode = valid_postcode(branch.get("postcode"))
            if postcode and postcode not in result:
                result.append(postcode)
        return result

    def branch_view(
        self: EssensplanerManager,
        branch: dict[str, Any],
        offer_zips: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """A branch for the panel / service responses."""
        if offer_zips is None:
            offer_zips = self._offer_plan()[1]
        main = branch.get("id") == self.main_branch
        return {
            **branch,
            "label": self.branch_label(branch),
            "retailer_name": retailer_name(branch.get("retailer")),
            "selected": bool(branch.get("selected", True)) or main,
            "main": main,
            "offer_zip": offer_zips.get(branch.get("id") or ""),
        }

    def branches_view(self: EssensplanerManager) -> list[dict[str, Any]]:
        """All branches sorted by priority."""
        offer_zips = self._offer_plan()[1]
        ordered = sorted(self.branches, key=lambda b: (_priority(b), fold(self.branch_label(b))))
        return [self.branch_view(b, offer_zips) for b in ordered]

    def branches_export(self: EssensplanerManager) -> dict[str, Any]:
        """Branches, main branch and offer postcodes (service, websocket, panel)."""
        return {
            "branches": self.branches_view(),
            "main_branch": self.main_branch if self.get_main_branch() else None,
            "offer_targets": self.offer_targets_view(),
        }

    def _new_branch_id(self: EssensplanerManager) -> str:
        stamp = int(dt_util.utcnow().timestamp() * 1000)
        while self.get_branch(f"man_{stamp}"):
            stamp += 1
        return f"man_{stamp}"

    def _branch_retailer(self: EssensplanerManager, text: str, postcode: str | None) -> str | None:
        """Retailer of a branch; a plain 'Aldi' is decided by the branch's own postcode first."""
        if postcode and (found := resolve_retailer(text, None, postcode)):
            return found
        return self.resolve_store(text)

    def _duplicate_branch(
        self: EssensplanerManager,
        retailer: str | None,
        street: str,
        postcode: str,
        city: str,
    ) -> dict[str, Any] | None:
        """A manual branch with the same retailer and address (needs street or postcode)."""
        if not retailer or not (street or postcode):
            return None
        for branch in self.branches:
            if (
                branch.get("retailer") == retailer
                and fold(branch.get("street") or "") == fold(street)
                and (branch.get("postcode") or "") == postcode
                and fold(branch.get("city") or "") == fold(city)
            ):
                return branch
        return None

    def save_branch(self: EssensplanerManager, data: dict[str, Any]) -> dict[str, Any]:
        """Create or update a branch. Returns the branch view.

        data: id (update; OpenStreetMap ids like "osm_node_123" are created as given),
        store or retailer (required for new branches), name, label, street, postcode, city,
        lat, lon, selected, main, priority, rewe_market_id, and from the map search
        source, near, route, postcode_guessed, retailer_guessed.

        A new OpenStreetMap id from the last branch search (find_branches) takes the
        missing fields from that search result (address, coordinates, near/route).

        Without an id a manual branch is created ("man_<ms>"); a branch with the same
        retailer and address is updated instead. Main branch: main=True makes it the main
        branch, main=False or deselecting it removes that; if no main branch is set the
        only selected branch becomes the main branch.
        """
        from .manager import _error  # avoid an import cycle

        data = {k: v for k, v in data.items() if v is not None}
        branch_id = str(data.get("id") or "").strip()
        existing = self.get_branch(branch_id) if branch_id else None
        if branch_id and existing is None and not _OSM_ID_RE.fullmatch(branch_id):
            raise _error("branch_not_found", branch=branch_id)
        if branch_id and existing is None:
            data = self._with_search_result(branch_id, data)

        postcode = (existing or {}).get("postcode") or ""
        if "postcode" in data:
            raw = str(data["postcode"]).strip()
            postcode = valid_postcode(raw) or ""
            if raw and not postcode:
                raise _error("invalid_postcode", postcode=raw)
        store = str(data.get("retailer") or data.get("store") or "").strip()
        retailer = None
        if store:
            retailer = self._branch_retailer(store, postcode or None)
            if retailer is None:
                raise _error("unknown_store", store=store)
        elif existing is None or not existing.get("retailer"):
            raise _error("store_required")
        if existing is None and not branch_id:
            existing = self._duplicate_branch(
                retailer,
                str(data.get("street") or "").strip(),
                postcode,
                str(data.get("city") or "").strip(),
            )

        now = dt_util.utcnow().isoformat()
        if existing is not None:
            branch = dict(existing)
            auto_label = branch.get("label") in (None, "", self._default_label(existing))
        else:
            new_id = branch_id or self._new_branch_id()
            branch = {
                "id": new_id,
                "retailer": None,
                "name": "",
                "label": "",
                "street": "",
                "postcode": "",
                "city": "",
                "postcode_guessed": False,
                "lat": None,
                "lon": None,
                "source": "osm" if _OSM_ID_RE.fullmatch(new_id) else "manual",
                "selected": True,
                "priority": max((_number(b.get("priority")) for b in self.branches), default=-1)
                + 1,
                "near": {},
                "route": {},
                "rewe_market_id": "",
                "retailer_guessed": False,
                "added": now,
            }
            auto_label = True

        for field in _BRANCH_TEXT_FIELDS:
            if field in data:
                branch[field] = str(data[field]).strip()
        if "postcode" in data:
            branch["postcode"] = postcode
            branch["postcode_guessed"] = bool(data.get("postcode_guessed", False))
        elif "postcode_guessed" in data:
            branch["postcode_guessed"] = bool(data["postcode_guessed"])
        for field, limit in (("lat", 90.0), ("lon", 180.0)):
            if field in data:
                branch[field] = _coordinate(data[field], limit)
        for field in ("near", "route"):
            if field in data:
                branch[field] = _distances(data[field])
        if data.get("source") in BRANCH_SOURCES:
            branch["source"] = data["source"]
        if retailer is not None:
            guessed = data.get("retailer_guessed")
            branch["retailer"] = retailer
            # guessed: "Aldi" needed the postcode / selection to pick Süd or Nord
            branch["retailer_guessed"] = bool(
                resolve_retailer(store) != retailer if guessed is None else guessed
            )
        elif (
            "postcode" in data
            and branch.get("retailer_guessed")
            and branch.get("retailer") in (ALDI_SUED, ALDI_NORD)
            and (guess := aldi_for_postcode(postcode))
        ):
            branch["retailer"] = guess  # guessed Aldi variant follows a corrected postcode
        if "selected" in data:
            branch["selected"] = bool(data["selected"])
        if "priority" in data:
            branch["priority"] = _number(data["priority"])
        if str(data.get("label") or "").strip():
            branch["label"] = str(data["label"]).strip()
        elif "label" in data or auto_label:
            branch["label"] = self._default_label(branch)
        if not branch.get("name"):
            branch["name"] = retailer_name(branch.get("retailer"))
        branch["updated"] = now

        if existing is not None:
            self.branches = [branch if b is existing else b for b in self.branches]
        else:
            self.branches.append(branch)
        main = data.get("main")
        if main is True:
            branch["selected"] = True
            self.main_branch = branch["id"]
        elif self.main_branch == branch["id"] and (
            main is False or not branch.get("selected", True)
        ):
            self.main_branch = None
        if main is not False:
            self._auto_main()
        self._branches_changed()
        return self.branch_view(branch)

    def branch_search_result(self: EssensplanerManager, branch_id: str) -> dict[str, Any] | None:
        """A shop of the last OpenStreetMap search (branch_search results) by its id."""
        return next(
            (
                r
                for r in _list(self.branch_search.get("results"))
                if isinstance(r, dict) and r.get("id") == branch_id
            ),
            None,
        )

    def _with_search_result(
        self: EssensplanerManager, branch_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Fill a new OpenStreetMap branch from the last search (given fields win).

        Keeps name, address, coordinates and the distances to the zones (near/route), so
        the panel only needs to send the id of a search result.
        """
        result = self.branch_search_result(branch_id)
        if result is None:
            return data
        found: dict[str, Any] = {"source": "osm"}
        for field in ("name", "street", "city", "lat", "lon"):
            if result.get(field) not in (None, ""):
                found[field] = result[field]
        for field in ("near", "route"):
            if isinstance(result.get(field), dict):
                found[field] = result[field]
        if result.get("postcode") and "postcode" not in data:
            found["postcode"] = result["postcode"]
            found["postcode_guessed"] = bool(result.get("postcode_guessed"))
        if result.get("retailer") and not (data.get("store") or data.get("retailer")):
            found["store"] = result["retailer"]
            found["retailer_guessed"] = bool(result.get("retailer_guessed"))
        return {**found, **data}

    def _auto_main(self: EssensplanerManager) -> None:
        """Without a (valid) main branch the only selected branch becomes the main branch."""
        if self.get_main_branch() is not None:
            return
        self.main_branch = None
        selected = [b for b in self.branches if b.get("selected", True)]
        if len(selected) == 1:
            self.main_branch = selected[0].get("id")

    def _branches_changed(self: EssensplanerManager) -> None:
        """Branches changed: keep them ordered, retag offers, drop cached prices, save."""
        self.branches.sort(key=lambda b: (_priority(b), fold(self.branch_label(b))))
        self._adopt_guessed_aldi()
        self.tag_offer_branches()
        self._invalidate_prices()
        self._ensure_price_context()
        self._reassign_open_items()
        self._changed("branches")

    def set_main_branch(self: EssensplanerManager, branch: str | None) -> dict[str, Any] | None:
        """Make a branch (id, label, store name) the main branch; None removes the main branch."""
        if not branch:
            self.main_branch = None
            self._branches_changed()
            return None
        found = self.require_branch(branch)
        found["selected"] = True
        self.main_branch = found["id"]
        self._branches_changed()
        return self.branch_view(found)

    def remove_branch(self: EssensplanerManager, branch: str) -> dict[str, Any]:
        """Remove a branch (id, label or unambiguous store name). Returns the removed branch.

        Clears the main branch and shopping list store choices pointing to it; open items
        are assigned again.
        """
        found = self.require_branch(branch, unique=True)
        view = self.branch_view(found)
        branch_id = found["id"]
        self.branches = [b for b in self.branches if b.get("id") != branch_id]
        if self.main_branch == branch_id:
            self.main_branch = None
        for item in self.shopping:
            if item.get("store_override") == branch_id:
                item.pop("store_override", None)
            if item.get("status") == "completed" and item.get("branch_id") == branch_id:
                for field in SHOPPING_STORE_FIELDS:
                    item.pop(field, None)
                if "description" in item:
                    self.update_shopping_description(item)
        # open items are assigned again (to the main branch or the next best store)
        self._auto_main()
        self._branches_changed()
        return view

    def reorder_branches(self: EssensplanerManager, ids: list[str]) -> list[dict[str, Any]]:
        """New order (priority) of the branches; unknown ids are ignored, missing ones follow."""
        order: list[str] = []
        for branch_id in ids:
            if self.get_branch(branch_id) and branch_id not in order:
                order.append(branch_id)
        current = sorted(self.branches, key=lambda b: (_priority(b), fold(self.branch_label(b))))
        order += [b["id"] for b in current if b.get("id") not in order]
        for position, branch_id in enumerate(order):
            if found := self.get_branch(branch_id):
                found["priority"] = position
        self._branches_changed()
        return self.branches_view()

    def _match_branches(self: EssensplanerManager, text: str | None) -> list[dict[str, Any]]:
        """Best matching branches for an id, label, 'Hauptladen' or a store name."""
        raw = str(text or "").strip()
        if not raw:
            return []
        if found := self.get_branch(raw):
            return [found]
        words = fold(raw).split()
        while words and words[0] in _FILLER_WORDS:
            words.pop(0)
        folded = " ".join(words)
        if not folded:
            return []
        if folded in _MAIN_WORDS:
            main = self.get_main_branch()
            return [main] if main else []
        selected = self.selected_branches()
        ordered = selected + [b for b in self.branches if b not in selected]
        exact = [
            b for b in ordered if folded in (fold(self.branch_label(b)), fold(b.get("name") or ""))
        ]
        if exact:
            return exact
        retailer = resolve_retailer(folded, self.active_retailers(), self.main_postcode)
        candidates = [b for b in ordered if not retailer or b.get("retailer") == retailer]
        if not candidates:
            return []
        name_words = set(fold(retailer_name(retailer)).split()) if retailer else set()
        tokens = [w for w in words if len(w) >= 3 and w not in name_words]

        def score(branch: dict[str, Any]) -> int:
            hay = fold(
                " ".join(
                    str(branch.get(f) or "")
                    for f in ("label", "name", "street", "city", "postcode")
                )
            )
            return sum(1 for token in tokens if token in hay)

        scores = [score(b) for b in candidates]
        best = max(scores)
        if retailer is None and best == 0:
            return []
        return [b for b, s in zip(candidates, scores, strict=True) if s == best]

    @staticmethod
    def is_generic_store(text: str | None) -> bool:
        """True for words that name no store ('im Supermarkt', 'beim Einkaufen', 'Laden')."""
        words = [w for w in fold(str(text or "")).split() if w not in _PREPOSITION_WORDS]
        return bool(words) and " ".join(words) in _GENERIC_STORE_WORDS

    def resolve_branch(self: EssensplanerManager, text: str | None) -> dict[str, Any] | None:
        """Branch for an id, a label, 'Hauptladen' / 'main' or a store name (best match)."""
        found = self._match_branches(text)
        return found[0] if found else None

    def require_branch(
        self: EssensplanerManager, text: str | None, unique: bool = False
    ) -> dict[str, Any]:
        """Like resolve_branch, but raises a clear error (unique: no ambiguous store name)."""
        from .manager import _error  # avoid an import cycle

        found = self._match_branches(text)
        if not found:
            raise _error("branch_not_found", branch=text or "")
        if unique and len(found) > 1:
            raise _error("branch_ambiguous", branch=text or "")
        return found[0]

    # ------------------------------------------------------------------
    # Offers per branch postcode
    # ------------------------------------------------------------------

    def _offer_plan(
        self: EssensplanerManager,
    ) -> tuple[list[tuple[str, list[str]]], dict[str, str]]:
        """([(postcode, [retailers])], {branch id: postcode its offers are searched at}).

        Selected branches with a postcode decide (main branch first, at most
        MAX_OFFER_TARGETS postcodes); a branch without postcode counts as being at the zip
        code option. Branches beyond the limit or without any postcode are searched at
        the first postcode. Without selected branches: the 1.2 options (zip code + stores).
        """
        zip_option = valid_postcode(self.zip_code)
        targets: dict[str, list[str]] = {}
        branch_zip: dict[str, str] = {}
        overflow: list[dict[str, Any]] = []
        for branch in self.selected_branches():
            retailer = branch.get("retailer")
            if not retailer:
                continue
            postcode = valid_postcode(branch.get("postcode")) or zip_option
            if postcode is None or (postcode not in targets and len(targets) >= MAX_OFFER_TARGETS):
                overflow.append(branch)
                continue
            retailers = targets.setdefault(postcode, [])
            if retailer not in retailers:
                retailers.append(retailer)
            branch_zip[branch["id"]] = postcode
        if not targets:
            if zip_option is None:
                return [], {}
            return [(zip_option, list(self.active_retailers()))], {}
        first = next(iter(targets))
        for branch in overflow:
            if branch["retailer"] not in targets[first]:
                targets[first].append(branch["retailer"])
            branch_zip[branch["id"]] = first
        return list(targets.items()), branch_zip

    def offer_targets(self: EssensplanerManager) -> list[tuple[str, list[str]]]:
        """Where offers are searched: [(postcode, [retailer ids])], main branch first."""
        return self._offer_plan()[0]

    def offer_targets_view(self: EssensplanerManager) -> list[dict[str, Any]]:
        """offer_targets() for JSON responses."""
        return [
            {
                "zip_code": postcode,
                "retailers": list(retailers),
                "stores": [retailer_name(r) for r in retailers],
            }
            for postcode, retailers in self.offer_targets()
        ]

    def tag_offer_branches(
        self: EssensplanerManager, offers: list[dict[str, Any]] | None = None
    ) -> None:
        """offer["branches"] = selected branches of the offer's retailer it applies to.

        An offer found for certain postcodes ("zip_codes") applies to the branches searched
        at these postcodes; offers without postcode info (manual ones) to all branches of
        the retailer.
        """
        branch_zip = self._offer_plan()[1]
        by_retailer: dict[str, list[tuple[str, str | None]]] = {}
        for branch in self.selected_branches():
            if branch.get("retailer") and branch.get("id"):
                by_retailer.setdefault(branch["retailer"], []).append(
                    (branch["id"], branch_zip.get(branch["id"]))
                )
        for offer in self.offers if offers is None else offers:
            candidates = by_retailer.get(self.offer_retailer(offer) or "", [])
            zips = offer.get("zip_codes")
            offer["branches"] = [
                bid for bid, zip_code in candidates if not zips or zip_code in zips
            ]

    # ------------------------------------------------------------------
    # Store price books
    # ------------------------------------------------------------------

    def defaults_index(self: EssensplanerManager) -> PriceIndex:
        """Index of the bundled estimates (built once)."""
        if self._default_index is None or self._default_index_source != id(self.default_prices):
            index = PriceIndex()
            for item in self.default_prices:
                index.add(item, "default")
            self._default_index = index
            self._default_index_source = id(self.default_prices)
            self._other_product_cache = {}
        return self._default_index

    def names_other_product(self: EssensplanerManager, name: str, key: str) -> bool:
        """True if `name` is a different, more specific product than the key `key`.

        Decided with the bundled estimates: "Oro di Parma Gehackte Tomaten" is the product
        "Gehackte Tomaten", not "Tomaten" ("tomate"); "Kokosmilch" is not "Milch". Used
        wherever an offer or a stored price is matched to an ingredient key, so canned
        tomatoes never price (or move) fresh ones. Unknown products: False.
        """
        if not name or not key:
            return False
        cache = self._other_product_cache
        if (name, key) in cache:
            return cache[(name, key)]
        defaults = self.defaults_index()
        product = defaults.lookup(name)
        result = False
        if product is not None and product is not (defaults.get(key) or defaults.lookup(key)):
            result = any(k != key and k.endswith(key) for k in _alias_keys(product))
        if len(cache) > 5000:
            cache.clear()
        cache[(name, key)] = result
        return result

    def variant_key(self: EssensplanerManager, name: str) -> str:
        """Key of the bundled product a name stands for ('Oro di Parma Gehackte Tomaten' ->
        'gehackte tomate'), else the name's own key."""
        product = self.defaults_index().lookup(name)
        return ingredient_key(product.name) if product is not None else ingredient_key(name)

    def _key_applies(self: EssensplanerManager, key: str, name: str, learned: bool) -> bool:
        """A price stored under `key` with this product name counts as the price of `key`.

        Not for another product ("Gehackte Tomaten" under the 1.2 key "tomate") and, like
        the 1.2 price book, not for own prices whose key is just the name without its
        adjective when a product is really called that ("gewürfelte Tomaten" -> "tomate").
        Learned prices are stored under the search term's key and count for it.
        """
        full, short = lookup_keys(name)
        if not key or key == full:
            return True
        if self.names_other_product(name, key):
            return False
        return learned or key != short or not self.defaults_index().is_full_key(key)

    def _layer(
        self: EssensplanerManager,
        items: dict[str, dict[str, Any]],
        source: str | None,
        retailer: str | None,
    ) -> PriceIndex:
        """Index of stored prices; also reachable via the aliases of the matching estimate."""
        defaults = self.defaults_index()
        index = PriceIndex()
        for key, item in items.items():
            item_source = source or item.get("source") or SOURCE_USER
            applies = self._key_applies(key, str(item.get("name") or key), item_source != "user")
            entry = index.add(
                item,
                item_source,
                keys=[key] if applies else [],
                store_id=retailer,
            )
            if entry is None:
                continue
            if retailer and not entry.store:
                entry.store = retailer_name(retailer)
            if applies:
                default = defaults.get(key) or defaults.exact(entry.name)
            else:
                default = defaults.get(lookup_keys(entry.name)[0])
            index.add(entry, weak_keys=_alias_keys(default))
        return index

    def fresh_store_prices(
        self: EssensplanerManager, retailer: str
    ) -> dict[str, dict[str, dict[str, Any]]]:
        """Learned prices of a retailer that are not older than STALE_DAYS, by source."""
        cutoff = self.today() - timedelta(days=STALE_DAYS)
        by_source: dict[str, dict[str, dict[str, Any]]] = {}
        for key, item in self.store_prices_learned.get(retailer, {}).items():
            seen = _last_seen(item)
            if seen is not None and seen < cutoff:
                continue
            by_source.setdefault(item.get("source") or "leaflet", {})[key] = item
        return by_source

    def _general_for(
        self: EssensplanerManager, items: dict[str, dict[str, Any]], retailer: str | None
    ) -> dict[str, dict[str, Any]]:
        """General prices without a store label of another retailer."""
        if not retailer:
            return items
        selected = self.active_retailers()
        postcode = self.main_postcode
        result = {}
        for key, item in items.items():
            label = item.get("retailer") or (
                resolve_retailer(item["store"], selected, postcode) if item.get("store") else None
            )
            if label in (None, retailer):
                result[key] = item
        return result

    def store_book(self: EssensplanerManager, retailer: str | None) -> LayeredPriceBook:
        """Price book of one retailer (cached until prices change or the day changes)."""
        today = self.today()
        if self._store_books_day != today:
            self._store_books = {}
            self._store_books_day = today
        cache_key = retailer or ""
        book = self._store_books.get(cache_key)
        if book is not None:
            return book
        layers: list[PriceIndex] = []
        if retailer:
            layers.append(
                self._layer(self.store_prices_user.get(retailer, {}), SOURCE_USER, retailer)
            )
            learned = self.fresh_store_prices(retailer)
            for source in sorted(learned, key=_source_rank):
                layers.append(self._layer(learned[source], source, retailer))
        layers.append(self._layer(self._general_for(self.prices_user, retailer), "user", None))
        layers.append(
            self._layer(self._general_for(self.prices_learned, retailer), "offer_regular", None)
        )
        layers.append(self.defaults_index())
        book = LayeredPriceBook(layers)
        self._store_books[cache_key] = book
        return book

    def set_store_price(
        self: EssensplanerManager,
        retailer: str,
        name: str,
        price: float,
        amount: float = 1,
        unit: str = "Stück",
    ) -> dict[str, Any]:
        """Store an own price of one retailer ('Butter at Aldi Süd costs 1,69 €')."""
        retailer_id = self.require_retailer(retailer)
        entry = self._put_store_price(retailer_id, name, price, amount, unit)
        self._invalidate_prices()
        self._after_price_change("prices")
        return {**entry, "retailer": retailer_id, "store": retailer_name(retailer_id)}

    def _put_store_price(
        self: EssensplanerManager,
        retailer: str,
        name: str,
        price: float,
        amount: float = 1,
        unit: str = "Stück",
    ) -> dict[str, Any]:
        from .manager import _error  # avoid an import cycle

        key = ingredient_key(name or "")
        if not key:
            raise _error("name_required")
        try:
            value = round(float(price), 2)
        except (TypeError, ValueError) as err:
            raise _error("invalid_price", price=price) from err
        if value < 0:
            raise _error("invalid_price", price=price)
        try:
            size = float(amount or 1)
        except (TypeError, ValueError):
            size = 1.0
        entry = {
            "name": name.strip(),
            "price": value,
            "amount": size if size > 0 else 1.0,
            "unit": unit or "Stück",
            "source": SOURCE_USER,
            "updated": dt_util.utcnow().isoformat(),
        }
        self.store_prices_user.setdefault(retailer, {})[key] = entry
        return entry

    def remove_store_price(self: EssensplanerManager, retailer: str, name: str) -> bool:
        """Remove an own store price (and the general own price labelled with that store)."""
        retailer_id = self.require_retailer(retailer)
        removed = self._pop_store_price(retailer_id, ingredient_key(name or ""), name)
        if removed:
            self._invalidate_prices()
            self._after_price_change("prices")
        return removed

    def _pop_store_price(
        self: EssensplanerManager, retailer: str, key: str, name: str | None = None
    ) -> bool:
        removed = False
        bucket = self.store_prices_user.get(retailer)
        if bucket and key not in bucket and name:
            key = _key_by_name(bucket, name) or key  # stored under another (1.2) key
        if bucket and bucket.pop(key, None) is not None:
            removed = True
            if not bucket:
                del self.store_prices_user[retailer]
        general = self.prices_user.get(key)
        if general and general.get("store"):
            label = general.get("retailer") or self.resolve_store(general["store"])
            if label == retailer:
                del self.prices_user[key]
                removed = True
        return removed

    # ------------------------------------------------------------------
    # Learned regular prices per store (leaflets, REWE online shop)
    # ------------------------------------------------------------------

    def _plausible_price(self: EssensplanerManager, key: str, entry: PriceEntry) -> bool:
        """Price per base unit within PLAUSIBLE_MIN..MAX x the estimate.

        Without an estimate any price counts. Units that cannot be compared (100 g vs. the
        estimate per piece) are converted with a known piece weight ("Paprika 500 g"),
        else the price is not learned: it may be another product ("Schoko-Eier").
        """
        per = unit_price(entry)
        if per is None or per[0] <= 0:
            return False
        default = self.defaults_index().lookup(key)
        reference = unit_price(default) if default else None
        if reference is None or reference[0] <= 0:
            return True  # nothing to compare with
        value = per[0]
        if not _comparable(per[1], reference[1]):
            units = {per[1], reference[1]}
            if "Stück" not in units or not units - {"Stück"} <= {"g", "ml"}:
                return False
            if not piece_weight_known(key):
                return False
            size = convert(1.0, reference[1], per[1], key)  # one estimate unit in entry units
            if not size:
                return False
            value = per[0] * size
        return PLAUSIBLE_MIN <= value / reference[0] <= PLAUSIBLE_MAX

    def learn_store_price(
        self: EssensplanerManager,
        retailer: str,
        key: str,
        name: str,
        price: float,
        amount: float,
        unit: str,
        source: str,
        ref: str | None = None,
        day: date | None = None,
    ) -> bool:
        """Remember a regular price seen at a retailer (e.g. the old price of a leaflet offer).

        Stored in store_prices_learned[retailer][key] as {name, price, amount, unit, source,
        updated, seen, ref, history}; history holds up to HISTORY_MAX {date, price, source}
        and gets a new entry when the price changed or HISTORY_INTERVAL_DAYS passed.
        Implausible prices (far off the estimate) are dropped, a fresh price of a more
        trusted source (REWE online before leaflet) is kept. Returns True if stored.
        The caller saves (self._changed(...)).
        """
        key = str(key or "").strip()
        if not retailer or not key:
            return False
        try:
            value = round(float(price), 2)
            size = float(amount)
        except (TypeError, ValueError):
            return False
        if value <= 0 or size <= 0:
            return False
        unit = unit or "Stück"
        entry = make_entry(
            {"name": name or key, "price": value, "amount": size, "unit": unit}, source, retailer
        )
        if entry is None or not self._plausible_price(key, entry):
            _LOGGER.debug(
                "Ignoring implausible price %s € / %s %s for %s at %s",
                value,
                size,
                unit,
                key,
                retailer,
            )
            return False
        day = day or self.today()
        bucket = self.store_prices_learned.setdefault(retailer, {})
        current = bucket.get(key)
        if current and _source_rank(source) > _source_rank(current.get("source") or ""):
            seen = _last_seen(current)
            if seen is not None and seen >= day - timedelta(days=STALE_DAYS):
                return False  # keep the fresher price of the more trusted source
        history = [h for h in _list((current or {}).get("history")) if isinstance(h, dict)]
        last = history[-1] if history else None
        last_day = None
        if last:
            try:
                last_day = date.fromisoformat(str(last.get("date"))[:10])
            except ValueError:
                last_day = None
        if (
            last is None
            or last.get("price") != value
            or last_day is None
            or (day - last_day).days >= HISTORY_INTERVAL_DAYS
        ):
            history.append({"date": day.isoformat(), "price": value, "source": source})
        changed = current is None or (
            current.get("price"),
            current.get("amount"),
            current.get("unit"),
            current.get("source"),
        ) != (value, size, unit, source)
        now = dt_util.utcnow().isoformat()
        bucket[key] = {
            "name": entry.name,
            "price": value,
            "amount": size,
            "unit": unit,
            "source": source,
            "updated": now if changed else (current or {}).get("updated") or now,
            "seen": day.isoformat(),
            "ref": ref,
            "history": history[-HISTORY_MAX:],
        }
        self._invalidate_prices()
        return True

    def learn_from_offers(self: EssensplanerManager, offers: list[dict[str, Any]]) -> int:
        """Learn the regular store prices (old prices) of leaflet offers. Returns the count.

        Several offers for the same retailer and ingredient: the lowest regular price per
        unit wins (the store brand is what most people buy).
        """
        best: dict[
            tuple[str, str], tuple[float | None, str | None, dict[str, Any], float, str]
        ] = {}
        for offer in offers:
            retailer = offer.get("retailer") or self.offer_retailer(offer)
            pack = offer_pack(offer)
            old_price = offer.get("old_price")
            keys = offer.get("keys") or []
            if not (old_price and pack and retailer and keys):
                continue
            entry = make_entry(
                {
                    "name": offer.get("product") or "x",
                    "price": old_price,
                    "amount": pack[0],
                    "unit": pack[1],
                },
                SOURCE_LEAFLET,
            )
            per = unit_price(entry) if entry else None
            for key in keys:
                current = best.get((retailer, key))
                if current is None or (
                    per is not None
                    and current[0] is not None
                    and per[1] == current[1]
                    and per[0] < current[0]
                ):
                    best[(retailer, key)] = (
                        per[0] if per else None,
                        per[1] if per else None,
                        offer,
                        pack[0],
                        pack[1],
                    )
        learned = 0
        for (retailer, key), (_, _, offer, amount, unit) in best.items():
            if self.learn_store_price(
                retailer,
                key,
                offer.get("product") or offer.get("title") or key,
                offer["old_price"],
                amount,
                unit,
                SOURCE_LEAFLET,
                ref=offer.get("id"),
            ):
                learned += 1
        return learned

    # ------------------------------------------------------------------
    # Price matrix (panel "Preisliste je Laden")
    # ------------------------------------------------------------------

    def _matrix_columns(self: EssensplanerManager) -> list[str]:
        columns = list(self.active_retailers())
        extra = [
            r
            for r in [*self.store_prices_user, *self.store_prices_learned]
            if r not in columns
            and (self.store_prices_user.get(r) or self.store_prices_learned.get(r))
        ]
        order = list(RETAILERS)
        for retailer in sorted(
            set(extra), key=lambda r: (order.index(r) if r in order else len(order), r)
        ):
            columns.append(retailer)
        return columns

    def _store_cells(
        self: EssensplanerManager, retailer: str
    ) -> dict[str, tuple[int, dict[str, Any], dict[str, Any]]]:
        """key -> (rank, stored item, cell) of the store specific prices of a retailer."""
        cutoff = self.today() - timedelta(days=STALE_DAYS)
        cells: dict[str, tuple[int, dict[str, Any], dict[str, Any]]] = {}
        candidates: list[tuple[int, str, dict[str, Any], str]] = [
            (0, key, item, SOURCE_USER)
            for key, item in self.store_prices_user.get(retailer, {}).items()
        ]
        for key, item in self.store_prices_learned.get(retailer, {}).items():
            source = item.get("source") or "leaflet"
            seen = _last_seen(item)
            stale = seen is not None and seen < cutoff
            candidates.append((1 + _source_rank(source) + (10 if stale else 0), key, item, source))
        for rank, key, item, source in candidates:
            if key in cells and cells[key][0] <= rank:
                continue
            entry = make_entry(item, source, retailer)
            if entry is None:
                continue
            cell = {
                **_price_info(entry),
                "name": entry.name,
                "source": source,
                "updated": item.get("seen") or item.get("updated"),
            }
            if item.get("history"):
                cell["history"] = list(item["history"])
            if rank >= 10:
                cell["stale"] = True
            cells[key] = (rank, item, cell)
        return cells

    def store_price_matrix(
        self: EssensplanerManager,
        query: str | None = None,
        limit: int = 400,
        retailer: str | None = None,
    ) -> dict[str, Any]:
        """Estimates and store prices side by side (rows = products, columns = retailers)."""
        defaults = self.defaults_index()
        columns = [retailer] if retailer else self._matrix_columns()
        rows: dict[str, dict[str, Any]] = {}
        ranks: dict[tuple[str, str], tuple[int, bool]] = {}

        def row_for(key: str, name: str, learned: bool = False) -> dict[str, Any]:
            if self._key_applies(key, name, learned):
                default = defaults.get(key) or defaults.exact(name)
                row_key = ingredient_key(default.name) if default else key
            else:  # e.g. "Gehackte Tomaten" stored under "tomate": its own row
                full = lookup_keys(name)[0]
                default = defaults.get(full) or (
                    defaults.lookup(name) if self.names_other_product(name, key) else None
                )
                row_key = ingredient_key(default.name) if default else full
            row = rows.get(row_key)
            if row is None:
                row = rows[row_key] = {
                    "key": row_key,
                    "name": default.name if default else name,
                    "category": guess_category(default.name if default else name),
                    "default": _price_info(default) if default else None,
                    "aliases": list(default.aliases) if default else [],
                    "stores": {},
                    "cheapest": None,
                }
            return row

        for entry in defaults.entries():
            row_for(ingredient_key(entry.name), entry.name)
        for key, item in self.prices_user.items():
            if isinstance(item, dict) and item.get("name"):
                general = make_entry(item, "user")
                if general is not None:
                    row = row_for(key, general.name)
                    row["general"] = {
                        **_price_info(general),
                        "source": "user",
                        "store": item.get("store"),
                    }
        for column in columns:
            for key, (rank, item, cell) in self._store_cells(column).items():
                row = row_for(key, str(item.get("name") or key), cell["source"] != SOURCE_USER)
                exact = key == row["key"]
                previous = ranks.get((row["key"], column))
                if previous is not None and (previous[0], not previous[1]) <= (rank, not exact):
                    continue
                ranks[(row["key"], column)] = (rank, exact)
                row["stores"][column] = cell

        folded = fold(query or "")
        result = []
        for row in rows.values():
            if folded and not (
                folded in fold(row["name"])
                or folded in row["key"]
                or any(folded in fold(a) for a in row["aliases"])
                or any(folded in fold(c["name"]) for c in row["stores"].values())
            ):
                continue
            row["cheapest"] = _cheapest(row)
            result.append(row)
        result.sort(key=lambda r: (not r["stores"], fold(r["name"])))
        return {
            "retailers": [{"id": r, "name": retailer_name(r)} for r in columns],
            "main_retailer": self.main_retailer,
            "stale_days": STALE_DAYS,
            "total": len(result),
            "rows": result[: max(1, int(limit))],
        }

    # ------------------------------------------------------------------
    # Shopping list per store ("Hauptladen + Ausnahmen")
    # ------------------------------------------------------------------

    @property
    def split_mode(self: EssensplanerManager) -> str:
        """off | main_only | main_exceptions (option store_split_mode)."""
        mode = self.options.get(CONF_SPLIT_MODE) or DEFAULT_SPLIT_MODE
        return mode if mode in SPLIT_MODES else DEFAULT_SPLIT_MODE

    def split_settings(self: EssensplanerManager) -> dict[str, Any]:
        """Mode and thresholds of the store split (options with defaults)."""

        def number(key: str, default: float) -> float:
            try:
                value = float(self.options.get(key, default))
            except (TypeError, ValueError):
                return float(default)
            return value if value >= 0 else float(default)

        return {
            "mode": self.split_mode,
            "active": self.store_split_active,
            "min_saving": number(CONF_SPLIT_MIN_SAVING, DEFAULT_SPLIT_MIN_SAVING),
            "min_percent": number(CONF_SPLIT_MIN_PERCENT, DEFAULT_SPLIT_MIN_PERCENT),
            "offer_min": number(CONF_SPLIT_OFFER_MIN, DEFAULT_SPLIT_OFFER_MIN),
            "trip_min": number(CONF_SPLIT_TRIP_MIN, DEFAULT_SPLIT_TRIP_MIN),
            "floor": SPLIT_FLOOR,
        }

    @property
    def store_split_active(self: EssensplanerManager) -> bool:
        """True with a main branch (with retailer) and store_split_mode != off."""
        return self.split_mode != SPLIT_OFF and bool(self.main_retailer)

    def store_candidates(self: EssensplanerManager) -> list[dict[str, Any]]:
        """First selected branch per retailer (main branch first)."""
        seen: set[str] = set()
        result: list[dict[str, Any]] = []
        for branch in self.selected_branches():
            retailer = branch.get("retailer")
            if retailer and retailer not in seen and branch.get("id"):
                seen.add(retailer)
                result.append(branch)
        return result

    @staticmethod
    def _item_name(item: dict[str, Any]) -> str:
        """Product name of a shopping item ('250 g Butter' -> 'Butter')."""
        if item.get("name"):
            return str(item["name"])
        summary = str(item.get("summary") or "")
        return parse_ingredient(summary)["name"] or summary or str(item.get("key") or "")

    @staticmethod
    def _item_amounts(item: dict[str, Any]) -> dict[str, float]:
        """Amounts of a shopping item (stored, else parsed from the summary)."""
        if isinstance(item.get("amounts"), dict):
            return item["amounts"]
        parsed = parse_ingredient(str(item.get("summary") or ""))
        if parsed["amount"] is None:
            # 1.2 list items with several units: "Butter (2 EL + 25 g)"
            parts = [p.strip() for p in str(parsed.get("note") or "").split(" + ")]
            amounts: dict[str, float] = {}
            for part in parts if len(parts) > 1 else []:
                sub = parse_ingredient(f"{part} x")
                if sub["amount"] is None or sub["name"] != "x":
                    return {}
                amount, unit = to_base(sub["amount"], sub["unit"])
                if amount:
                    amounts[unit] = amounts.get(unit, 0.0) + amount
            return amounts
        amount, unit = to_base(parsed["amount"], parsed["unit"])
        return {unit: amount} if amount else {}

    def _chosen_entry(
        self: EssensplanerManager, item: dict[str, Any], retailer: str | None
    ) -> PriceEntry | None:
        """Price the user picked when adding the item (applies to its retailer only)."""
        chosen = item.get("chosen")
        if not isinstance(chosen, dict) or chosen.get("price") is None:
            return None
        if chosen.get("retailer") and chosen["retailer"] != retailer:
            return None
        if chosen.get("offer_id"):
            # a picked offer counts while it is valid (and unchanged), then the store's prices
            offer = next((o for o in self.offers if o.get("id") == chosen["offer_id"]), None)
            if offer is None and isinstance(chosen.get("offer"), dict):
                offer = chosen["offer"]  # a live leaflet offer
            try:
                same = offer is not None and float(offer.get("price")) == float(chosen["price"])
            except (TypeError, ValueError):
                same = False
            if not same or (offer.get("valid_to") or "9999")[:10] < self.today().isoformat():
                return None
            entry = self.offer_entry(offer, self._item_name(item))
            if entry is not None:
                return entry
        return make_entry(
            {
                "name": chosen.get("name") or self._item_name(item),
                "price": chosen["price"],
                "amount": chosen.get("amount") or 1,
                "unit": chosen.get("unit") or "Stück",
            },
            SOURCE_USER,
            chosen.get("retailer") or retailer,
        )

    def price_at(
        self: EssensplanerManager,
        item: dict[str, Any],
        retailer: str | None,
        branch_id: str | None = None,
        day: date | None = None,
        lead_days: int = 3,
        by_unit: bool = False,
    ) -> dict[str, Any] | None:
        """Cheapest way to buy a shopping item at one retailer (whole packs).

        Compares the retailer's price (store price book) with its valid offers (that apply
        to branch_id). Returns {price, packs, entry, offer, real, specific, regular} or None.
        specific: a price of this retailer (store price, offer, own choice) – not a general
        price or estimate. retailer None: like best_price() without retailer.
        by_unit: the option with the lowest price per kg / l / piece wins (comparing
        products without an amount: a bigger pack on offer can be the better buy).
        """
        day = day or self.today()
        today = self.today().isoformat()
        name = self._item_name(item)
        key = item.get("key") or ingredient_key(name)
        category = item.get("category") or guess_category(name)
        amounts = self._item_amounts(item)
        as_packs = item.get("source") != "plan"
        best: dict[str, Any] | None = None

        def consider(entry: PriceEntry | None) -> dict[str, Any] | None:
            nonlocal best
            if entry is None:
                return None
            cost = item_cost(amounts, key, entry, category, as_packs)
            if cost is None:
                return None
            option = {
                "price": cost[0],
                "packs": cost[1],
                "entry": entry,
                "offer": _offer_short(entry.offer) if entry.offer else None,
                "real": entry.real,
                "specific": entry.offer is not None
                or (retailer is not None and entry.real and entry.store_id == retailer),
            }
            if best is None or _better(option, best, by_unit):
                best = option
            return option

        regular_entry = self._chosen_entry(item, retailer)
        if regular_entry is None:
            regular_entry = self.regular_book(retailer).lookup(name)
        regular = consider(regular_entry)
        for offer in self.offers_for(name, day, lead_days, retailer=retailer):
            if (offer.get("valid_to") or "9999")[:10] < today:
                continue  # no longer buyable
            if branch_id and "branches" in offer and branch_id not in offer["branches"]:
                continue  # found for another postcode
            consider(self.offer_entry(offer, name))
        if best is None:
            return None
        return {**best, "regular": regular}

    def assign_stores(
        self: EssensplanerManager, items: list[dict[str, Any]], day: date | None = None
    ) -> bool:
        """Assign shopping items to branches ("Hauptladen + Ausnahmen"). Returns True if active.

        Order: manual store_override -> store_preferences[key] ("immer hier") -> main branch,
        unless another selected store (first branch per retailer) has an offer that saves
        >= offer_min or a real store price that is >= min_saving EUR or >= min_percent %
        cheaper (and at least SPLIT_FLOOR EUR) -> the cheapest such store (another branch of
        a chain counts with offers found only there, e.g. REWE near work). Without any price
        at the main branch (no estimate, e.g. Kaffee) an offer elsewhere moves the item
        (saving unknown: counts 0 for trip_min). With trip_min, stores whose items save
        less in total go back to the main branch. main_only: all at the main branch,
        alternatives are still computed.

        Sets branch_id, retailer, store_label, store_reason (main|offer|cheaper|manual|
        preferred), saving, price/packs/offer at that store and up to 4 alternatives.
        Without an active split the assignment fields are removed (1.2 behaviour).
        Descriptions are not touched (see update_shopping_description()).
        """
        if not self.store_split_active:
            for item in items:
                for field in ASSIGNED_FIELDS:
                    item.pop(field, None)
            return False
        day = day or self.today()
        settings = self.split_settings()
        candidates = self.store_candidates()
        main = self.get_main_branch()
        if main is None:  # cannot happen while the split is active
            return False
        if not candidates or candidates[0].get("id") != main.get("id"):
            candidates = [main, *[c for c in candidates if c.get("id") != main.get("id")]]
        by_retailer = {c["retailer"]: c for c in candidates}
        # further branches of a chain (e.g. REWE near work): only for offers found there
        first_ids = {c["id"] for c in candidates}
        extras = [
            b
            for b in self.selected_branches()
            if b.get("id") not in first_ids and b.get("retailer") in by_retailer
        ]
        moved: dict[str, list[tuple[dict[str, Any], dict[str, Any] | None]]] = {}
        for item in items:
            costs: dict[str, dict[str, Any] | None] = {
                c["id"]: self.price_at(item, c["retailer"], c["id"], day) for c in candidates
            }
            for extra in extras:
                cost = self.price_at(item, extra["retailer"], extra["id"], day)
                first = costs.get(by_retailer[extra["retailer"]]["id"])
                if (
                    cost
                    and cost["offer"]
                    and (first is None or cost["price"] < first["price"] - 1e-9)
                ):
                    costs[extra["id"]] = cost
            main_cost = costs[main["id"]]
            target, reason = main, REASON_MAIN
            chosen = item.get("chosen") if isinstance(item.get("chosen"), dict) else {}
            if (
                chosen.get("pins_store")
                and self._chosen_entry(item, chosen.get("retailer")) is None
            ):
                # the store came from a picked offer that ended: automatic again
                item.pop("store_override", None)
                chosen.pop("pins_store", None)
            override = self.get_branch(item.get("store_override"))
            if override is not None and not (
                override.get("selected", True) or override.get("id") == main.get("id")
            ):
                override = None  # a paused branch: chosen again when it is active
            preferred = by_retailer.get(self.store_preferences.get(item.get("key") or "") or "")
            if override is not None and override.get("retailer"):
                target, reason = override, REASON_MANUAL
                if override["id"] not in costs:
                    costs[override["id"]] = self.price_at(
                        item, override["retailer"], override["id"], day
                    )
            elif preferred is not None:
                target, reason = preferred, REASON_PREFERRED
            elif settings["mode"] == SPLIT_MAIN_EXCEPTIONS:
                best: tuple[dict[str, Any], dict[str, Any]] | None = None
                movable = candidates[1:] + [b for b in extras if b["id"] in costs]
                for branch in movable:
                    cost = costs[branch["id"]]
                    if cost is None:
                        continue
                    if main_cost is None:
                        # no price at the main store (e.g. Kaffee): an offer elsewhere wins
                        if not cost["offer"]:
                            continue
                    elif not self._worth_moving(main_cost, cost, settings):
                        continue
                    if best is None or cost["price"] < best[1]["price"]:
                        best = (branch, cost)
                if best is not None:
                    target = best[0]
                    reason = REASON_OFFER if best[1]["offer"] else REASON_CHEAPER
            self._set_store(item, target, reason, costs, main_cost)
            if reason in (REASON_OFFER, REASON_CHEAPER):
                moved.setdefault(target["id"], []).append((item, main_cost))
        if settings["trip_min"] > 0:
            batch = {id(i) for i in items}
            for branch_id, entries in moved.items():
                total = sum(i.get("saving") or 0 for i, _ in entries) + sum(
                    i.get("saving") or 0
                    for i in self.shopping
                    if id(i) not in batch
                    and i.get("status") != "completed"
                    and i.get("branch_id") == branch_id
                    and i.get("store_reason") in (REASON_OFFER, REASON_CHEAPER)
                )
                if round(total, 2) >= settings["trip_min"]:
                    continue
                for item, main_cost in entries:
                    self._set_store(item, main, REASON_MAIN, None, main_cost)
        return True

    @staticmethod
    def _worth_moving(
        main_cost: dict[str, Any], cost: dict[str, Any], settings: dict[str, Any]
    ) -> bool:
        """Offer saving >= offer_min, or a real store price clearly cheaper."""
        if cost["offer"]:
            saving = round(main_cost["price"] - cost["price"], 2)
            if saving > 0 and saving >= settings["offer_min"]:
                return True
        regular = cost.get("regular")
        if regular is None or not regular["specific"]:
            return False
        saving = round(main_cost["price"] - regular["price"], 2)
        if saving < settings["floor"] or saving <= 0:
            return False
        percent = saving / main_cost["price"] * 100 if main_cost["price"] > 0 else 0.0
        return saving >= settings["min_saving"] or percent >= settings["min_percent"]

    def _set_store(
        self: EssensplanerManager,
        item: dict[str, Any],
        branch: dict[str, Any],
        reason: str,
        costs: dict[str, dict[str, Any] | None] | None,
        main_cost: dict[str, Any] | None,
    ) -> None:
        """Write the assignment of one item (costs None: keep the alternatives)."""
        main_id = self.main_branch
        if costs is None:
            # moved back to the main branch (trip not worth it): previous store -> alternative
            previous = {
                "branch_id": item.get("branch_id"),
                "retailer": item.get("retailer"),
                "label": item.get("store_label"),
                "price": item.get("price"),
            }
            if item.get("offer"):
                previous["offer"] = item["offer"]
            alternatives = [
                a for a in item.get("alternatives") or [] if a.get("branch_id") != branch["id"]
            ]
            alternatives = sorted([previous, *alternatives], key=lambda a: a["price"] or 0)
            cost = main_cost
        else:
            cost = costs.get(branch["id"])
            alternatives = []
            for other_id, other in costs.items():
                other_branch = self.get_branch(other_id)
                if other_id == branch["id"] or other is None or other_branch is None:
                    continue
                alternative = {
                    "branch_id": other_id,
                    "retailer": other_branch.get("retailer"),
                    "label": self.branch_label(other_branch),
                    "price": other["price"],
                    "real": other["specific"],
                }
                if other["offer"]:
                    alternative["offer"] = other["offer"]
                alternatives.append(alternative)
            alternatives.sort(key=lambda a: (a["price"], a["branch_id"] != main_id))
        item["branch_id"] = branch["id"]
        item["retailer"] = branch.get("retailer")
        item["store_label"] = self.branch_label(branch)
        item["store_reason"] = reason
        item["price"] = cost["price"] if cost else None
        item["packs"] = cost["packs"] if cost else None
        item["offer"] = cost["offer"] if cost else None
        if branch["id"] == main_id:
            item["saving"] = 0.0
        elif cost and main_cost:
            item["saving"] = round(main_cost["price"] - cost["price"], 2)
        else:
            item["saving"] = None
        item["alternatives"] = alternatives[:MAX_ALTERNATIVES]

    def update_shopping_description(self: EssensplanerManager, item: dict[str, Any]) -> None:
        """Rebuild the description: '🏪 store · aisle · ≈ price · 🏷️ offer · recipes/note'.

        Without a store (split inactive) it is exactly the 1.2 description: plan items
        'aisle · ≈ price · 🏷️ offer · recipes', manual items the user's text.
        """
        plan = item.get("source") == "plan"
        if plan and isinstance(item.get("recipes"), list):
            extra = [", ".join(item["recipes"])] if item["recipes"] else []
        else:
            extra = [
                part.strip()
                for part in str(item.get("description") or "").split(" · ")
                if part.strip()
                and not part.strip().startswith(_DESCRIPTION_PREFIXES)
                and not (plan and part.strip() == item.get("category"))
            ]
        store = item.get("store_label") if item.get("branch_id") else None
        parts: list[str] = []
        if store:
            parts.append(f"🏪 {store}")
        if plan:
            parts.append(item.get("category") or "Sonstiges")
        if item.get("price") is not None and (plan or store):
            parts.append(f"≈ {format_eur(item['price'])}")
        if (plan or store) and (offer := item.get("offer")):
            parts.append(offer_label(offer))
        parts.extend(extra)
        item["description"] = " · ".join(parts)

    def find_shopping_item(self: EssensplanerManager, text: str) -> dict[str, Any]:
        """Shopping item by uid or name (open items first) or a clear error.

        Whole words first: "Milch" finds "1 l Milch" or "frische Milch", then a compound
        with the product at the end that is the same product ("Hähnchenbrustfilet" for
        "Hähnchen"). Last, the only open item of the same kind with the product at the end
        of its name ("Rinderhackfleisch" for "Hackfleisch"); "Kokosmilch" is no "Milch".
        """
        from .manager import _error  # avoid an import cycle

        raw = str(text or "").strip()
        for item in self.shopping:
            if item.get("uid") == raw:
                return item
        raw = normalize_spoken_quantity(raw)  # "zwei Liter Milch" like "2 Liter Milch"
        name = parse_ingredient(raw)["name"] or raw
        key = ingredient_key(name)
        folded = fold(raw)
        ordered = sorted(self.shopping, key=lambda i: i.get("status") == "completed")
        if key:
            for item in ordered:
                if item.get("key") == key or fold(item.get("summary") or "") == folded:
                    return item
            words = set(key.split())
            for item in ordered:
                summary = {_singular(w) for w in fold(item.get("summary") or "").split()}
                item_key = set(str(item.get("key") or "").split())
                if words <= summary or words <= item_key or (item_key and item_key <= words):
                    return item
            for item in ordered:
                item_name = self._item_name(item)
                if offer_matches(item_name, key) and not self.names_other_product(item_name, key):
                    return item
            loose = self._loose_shopping_matches(name)
            if len(loose) == 1:
                return loose[0]
        raise _error("shopping_item_not_found")

    def _loose_shopping_matches(self: EssensplanerManager, name: str) -> list[dict[str, Any]]:
        """Open items of the same kind whose name ends with the product: "Rinderhackfleisch"
        or "Cherrytomaten" for "Hackfleisch" / "Tomaten" (same aisle), not "Kokosmilch"
        for "Milch" or "Gehackte Tomaten" for "Tomaten" (another aisle)."""
        key = ingredient_key(name)
        if not key:
            return []
        category = guess_category(name)
        result = []
        for item in self.shopping:
            if item.get("status") == "completed":
                continue
            item_name = self._item_name(item)
            if offer_matches(item_name, key) and guess_category(item_name) == category:
                result.append(item)
        return result

    def set_shopping_store(
        self: EssensplanerManager, item_text: str, store: str | None, always: bool = False
    ) -> dict[str, Any]:
        """Buy an item at a branch (id, label, store name, 'Hauptladen').

        store None / 'auto' resets the manual choice; always=True also remembers the store
        for this product ("immer hier kaufen", store_preferences) or forgets it with 'auto'
        – also for a product that is not on the list right now (then the result is
        {name, key, store_label, preference_only: True}).
        """
        from .manager import _error  # avoid an import cycle

        if not self.store_split_active:
            raise _error("store_split_off")
        text = normalize_spoken_quantity(str(item_text or "").strip())
        spoken = parse_ingredient(text)["name"] or text
        try:
            item = self.find_shopping_item(item_text)
        except ServiceValidationError:
            # "immer" for a product that is not on the list (not even as "Rinderhackfleisch")
            if not always or self._loose_shopping_matches(spoken):
                raise
            return self._remember_store(item_text, store)
        key = item.get("key") or ingredient_key(self._item_name(item))
        # "Hackfleisch kaufe ich immer bei Lidl" found "Rinderhackfleisch": remember both
        spoken_key = "" if item.get("uid") == str(item_text or "").strip() else spoken
        keys = [k for k in dict.fromkeys([key, ingredient_key(spoken_key)]) if k]
        if isinstance(item.get("chosen"), dict):
            item["chosen"].pop("pins_store", None)  # now the user's own store choice
        words = fold(store or "").split()
        if not words or " ".join(words) in _AUTO_WORDS:
            item.pop("store_override", None)
            if always:
                for k in keys:
                    self.store_preferences.pop(k, None)
        else:
            branch = self.require_branch(store)
            item["store_override"] = branch["id"]
            if always and branch.get("retailer"):
                for k in keys:
                    self.store_preferences[k] = branch["retailer"]
        self.assign_stores([item])
        self.update_shopping_description(item)
        self._changed("shopping")
        return item

    def _remember_store(
        self: EssensplanerManager, item_text: str, store: str | None
    ) -> dict[str, Any]:
        """ "Kaffee kaufe ich immer bei Lidl" for a product that is not on the list."""
        from .manager import _error  # avoid an import cycle

        text = normalize_spoken_quantity(str(item_text or "").strip())
        name = parse_ingredient(text)["name"] or text
        key = ingredient_key(name)
        if not key:
            raise _error("name_required")
        if not self.names_product(name):
            raise _error("shopping_item_not_found")
        label = None
        words = fold(store or "").split()
        if not words or " ".join(words) in _AUTO_WORDS:
            self.store_preferences.pop(key, None)
        else:
            branch = self.require_branch(store)
            if branch.get("retailer"):
                self.store_preferences[key] = branch["retailer"]
            label = self.branch_label(branch)
        self._changed("shopping")
        return {"name": name, "key": key, "store_label": label, "preference_only": True}

    @staticmethod
    def names_product(text: str | None) -> bool:
        """False for question words and pronouns ("was", "welche Sachen", "das")."""
        words = fold(str(text or "")).split()
        return bool(words) and not set(words) <= _NO_PRODUCT_WORDS

    def preferred_products(self: EssensplanerManager, store: str) -> dict[str, Any]:
        """Products bought "immer" at a store: {label, retailer, items: [names]}."""
        branch = self.require_branch(store)
        retailer = branch.get("retailer")
        keys = [k for k, v in self.store_preferences.items() if retailer and v == retailer]
        # "Tomaten" also stands for "Cherrytomaten" (set_shopping_store() stores both keys)
        names = [
            self._preference_name(key)
            for key in keys
            if " " in key or not any(o != key and key.endswith(o) for o in keys)
        ]
        return {
            "label": retailer_name(retailer) if retailer else self.branch_label(branch),
            "retailer": retailer,
            "items": sorted(names, key=fold),
        }

    def _preference_name(self: EssensplanerManager, key: str) -> str:
        """Readable name of a product key (list item, added article, estimate, the key)."""
        for item in self.shopping:
            if item.get("key") == key:
                return self._item_name(item)
        for article in self.article_history:
            if article.get("key") == key and article.get("summary"):
                return parse_ingredient(str(article["summary"]))["name"] or article["summary"]
        default = self.defaults_index().get(key)
        if default is not None:
            return default.name
        return key[:1].upper() + key[1:]

    def assign_shopping_stores(
        self: EssensplanerManager, reset_overrides: bool = False
    ) -> dict[str, Any]:
        """Assign all open items again (e.g. after prices or branches changed).

        reset_overrides: forget the manual store choices of the items first.
        """
        items = [i for i in self.shopping if i.get("status") != "completed"]
        if reset_overrides:
            for item in self.shopping:
                item.pop("store_override", None)
        active = self.assign_stores(items)
        for item in items:
            self.update_shopping_description(item)
        if items or reset_overrides:
            self._changed("shopping")
        return {"active": active, "assigned": len(items) if active else 0}

    def _reassign_open_items(self: EssensplanerManager) -> bool:
        """Assign the open shopping items again after branches, prices or offers changed.

        Manual store choices and "immer hier" are kept. While the split is inactive only
        items with an old assignment are touched (back to the 1.2 price). The caller saves
        (_changed). Returns True if items were updated.
        """
        items = [i for i in self.shopping if i.get("status") != "completed"]
        if not self.store_split_active:
            items = [i for i in items if any(f in i for f in ASSIGNED_FIELDS)]
            for item in items:
                for field in ASSIGNED_FIELDS:
                    item.pop(field, None)
                chosen = item.get("chosen") if isinstance(item.get("chosen"), dict) else {}
                cost = self.price_at(item, chosen.get("retailer"))
                item["price"] = cost["price"] if cost else None
                item["packs"] = cost["packs"] if cost else None
                item["offer"] = cost["offer"] if cost else None
        elif items:
            self.assign_stores(items)
        for item in items:
            self.update_shopping_description(item)
        return bool(items)

    def _after_price_change(self: EssensplanerManager, change: str) -> None:
        """Prices or offers changed: assign the open items again, save and notify."""
        self._reassign_open_items()
        self._changed(change)

    def new_day(self: EssensplanerManager) -> None:
        """After midnight: drop expired offers and move items off offers that ended."""
        today = self.today().isoformat()
        removed = self.cleanup_offers()
        expired = any(
            (i.get("offer") or {}).get("valid_to") and str(i["offer"]["valid_to"])[:10] < today
            for i in self.shopping
            if i.get("status") != "completed"
        )
        if removed or expired:
            self._after_price_change("offers")

    def stores_summary(self: EssensplanerManager) -> list[dict[str, Any]]:
        """Open items per store (main branch first, then the selected order, "Ohne Laden").

        [{branch_id, retailer, label, main, open, priced, subtotal, saving, items: [summary]}].
        Empty while the split is inactive (no main branch or store_split_mode off).
        """
        if not self.store_split_active:
            return []
        order = {b["id"]: n for n, b in enumerate(self.selected_branches())}
        groups: dict[str | None, dict[str, Any]] = {}
        for item in self.shopping:
            if item.get("status") == "completed":
                continue
            branch = self.get_branch(item.get("branch_id"))
            branch_id = branch["id"] if branch else None
            group = groups.get(branch_id)
            if group is None:
                group = groups[branch_id] = {
                    "branch_id": branch_id,
                    "retailer": branch.get("retailer") if branch else None,
                    "label": self.branch_label(branch) if branch else NO_STORE_LABEL,
                    "main": branch_id is not None and branch_id == self.main_branch,
                    "open": 0,
                    "priced": 0,
                    "subtotal": 0.0,
                    "saving": 0.0,
                    "items": [],
                }
            group["open"] += 1
            group["items"].append(item.get("summary") or "")
            if item.get("price") is not None:
                group["subtotal"] += item["price"]
                group["priced"] += 1
            if (item.get("saving") or 0) > 0:
                group["saving"] += item["saving"]
        result = list(groups.values())
        for group in result:
            group["subtotal"] = round(group["subtotal"], 2)
            group["saving"] = round(group["saving"], 2)
        result.sort(
            key=lambda g: (
                g["branch_id"] is None,
                not g["main"],
                order.get(g["branch_id"] or "", len(order)),
                fold(g["label"]),
            )
        )
        return result

    def store_selection(self: EssensplanerManager, store: str) -> dict[str, Any]:
        """Open items of one store (branch id, label, store name, 'Hauptladen')."""
        from .manager import _error  # avoid an import cycle

        matches = self._match_branches(store)
        if not matches:
            raise _error("branch_not_found", branch=store)
        ids = {b["id"] for b in matches}
        retailers = {b.get("retailer") for b in matches}
        label = (
            self.branch_label(matches[0])
            if len(matches) == 1
            else retailer_name(next(iter(retailers)))
            if len(retailers) == 1
            else store
        )
        items = [
            i for i in self.shopping if i.get("status") != "completed" and i.get("branch_id") in ids
        ]
        subtotal = sum(i["price"] for i in items if i.get("price") is not None)
        return {
            "branch_id": matches[0]["id"] if len(matches) == 1 else None,
            "branch_ids": sorted(ids),
            "retailer": matches[0].get("retailer") if len(retailers) == 1 else None,
            "label": label,
            "open": len(items),
            "priced": sum(1 for i in items if i.get("price") is not None),
            "subtotal": round(subtotal, 2),
            "saving": round(
                sum(i.get("saving") or 0 for i in items if (i.get("saving") or 0) > 0), 2
            ),
            "items": [i.get("summary") or "" for i in items],
            "offers": [{"item": i.get("summary"), **i["offer"]} for i in items if i.get("offer")],
        }

    def compare_prices(
        self: EssensplanerManager, name: str, amount_text: str | None = None
    ) -> dict[str, Any]:
        """Price of a product at every selected store (first branch per retailer).

        Without branches the active retailers (offer_stores option) are compared. With an
        amount ('500 g Hackfleisch') the cost in whole packs is compared, else the price
        per unit (pack prices differ in size). cheapest: the best result (None with less
        than two stores or when all cost the same).
        """
        from .manager import _error  # avoid an import cycle

        text = normalize_spoken_quantity(str(name or "").strip())
        parsed = parse_ingredient(text)
        product = parsed["name"] or text
        if not ingredient_key(product):
            raise _error("name_required")
        amount, unit = parsed["amount"], parsed["unit"]
        if amount_text:
            extra = parse_ingredient(normalize_spoken_quantity(f"{amount_text} {product}"))
            amount, unit = extra["amount"], extra["unit"]
        amounts: dict[str, float] = {}
        if amount is not None:
            base_amount, base_unit = to_base(amount, unit)
            if base_amount:
                amounts[base_unit] = base_amount
        item = {
            "name": product,
            "key": ingredient_key(product),
            "category": guess_category(product),
            "amounts": amounts,
            "source": "compare",
        }
        targets: list[tuple[dict[str, Any] | None, str]] = [
            (b, b["retailer"]) for b in self.store_candidates()
        ] or [(None, r) for r in self.active_retailers()]
        today = self.today()
        results: list[dict[str, Any]] = []
        for branch, retailer in targets:
            cost = self.price_at(
                item, retailer, branch["id"] if branch else None, today, 0, by_unit=not amounts
            )
            if cost is None:
                continue
            entry: PriceEntry = cost["entry"]
            per = unit_price(entry)
            result = {
                "branch_id": branch["id"] if branch else None,
                "retailer": retailer,
                "label": self.branch_label(branch) if branch else retailer_name(retailer),
                "price": cost["price"],
                "packs": cost["packs"],
                "pack": pack_text(entry.amount, entry.unit),
                "unit_price": round(per[0], 5) if per else None,
                "base": per[1] if per else None,
                "source": entry.source,
                "real": cost["specific"],
                "main": branch is not None and branch["id"] == self.main_branch,
                "offer": cost["offer"],
            }
            results.append(result)
        by_price = bool(amounts)
        bases = [r["base"] for r in results if r["unit_price"] is not None]
        base = max(set(bases), key=bases.count) if bases else None

        def rank(result: dict[str, Any]) -> tuple[Any, ...]:
            if by_price or result["unit_price"] is None or result["base"] != base:
                value = result["price"] if by_price else float("inf")
            else:
                value = result["unit_price"]
            return (value, result["price"], not result["main"])

        results.sort(key=rank)
        cheapest = None
        if (
            len(results) >= 2
            and rank(results[0])[0] != float("inf")
            and rank(results[0])[0] < rank(results[1])[0] - 1e-9
        ):
            cheapest = results[0]
        return {
            "item": product,
            "amount": " + ".join(f"{a:g} {u}".strip() for u, a in amounts.items()) or None,
            "compared_by": "price" if by_price else "unit_price",
            "results": results,
            "cheapest": cheapest,
        }


def _better(option: dict[str, Any], best: dict[str, Any], by_unit: bool) -> bool:
    """option is cheaper than best (per pack, or per base unit with by_unit)."""
    if by_unit:
        mine, theirs = unit_price(option["entry"]), unit_price(best["entry"])
        if mine and theirs and _comparable(mine[1], theirs[1]):
            return mine[0] < theirs[0] - 1e-12
    return option["price"] < best["price"] - 1e-9


def offer_label(offer: dict[str, Any]) -> str:
    """'🏷️ Lidl 4,99 € bis 07.11.' (shopping item descriptions)."""
    valid_to = str(offer.get("valid_to") or "")
    until = f" bis {valid_to[8:10]}.{valid_to[5:7]}." if valid_to else ""
    return f"🏷️ {offer.get('store')} {format_eur(offer.get('price'))}{until}"


def _cheapest(row: dict[str, Any]) -> str | None:
    """Retailer with the lowest unit price (needs two comparable store prices)."""
    cells = {
        r: c
        for r, c in row["stores"].items()
        if not c.get("stale") and c.get("unit_price") is not None
    }
    if len(cells) < 2:
        return None
    bases = [c["base"] for c in cells.values()]
    base = (row.get("default") or {}).get("base")
    if base not in bases:
        base = max(set(bases), key=bases.count)
    comparable = {r: c["unit_price"] for r, c in cells.items() if c["base"] == base}
    if len(comparable) < 2 or len(set(comparable.values())) == 1:
        return None
    return min(comparable, key=lambda r: comparable[r])
