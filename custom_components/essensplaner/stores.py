"""Branches, store specific prices and the price matrix (mixin for the manager).

Price order for a retailer r (first match wins, see store_book()):
own store price of r -> learned store price of r (<= 180 days, REWE online before leaflet)
-> own general price -> learned general price -> default estimate.
General prices that carry a store label of another retailer are that retailer's prices
and are skipped for r.

Branches (Filialen) are the user's shops: {id ("man_<ms>" | "osm_node_123" | "osm_way_…"),
retailer, name, label, street, postcode, city, postcode_guessed, lat, lon, source (osm|manual),
selected, priority, near, route, rewe_market_id, retailer_guessed, added, updated}.
Offers are fetched per postcode of the selected branches (offer_targets()).
"""

from __future__ import annotations

from datetime import date, timedelta
import logging
import re
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from .ingredients import fold, guess_category, ingredient_key
from .pricing import (
    LayeredPriceBook,
    PriceEntry,
    PriceIndex,
    lookup_keys,
    make_entry,
    offer_pack,
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

DATA_VERSION = 2
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
    """All lookup keys of an entry's name and aliases."""
    if entry is None:
        return []
    keys: list[str] = []
    for name in [entry.name, *entry.aliases]:
        for key in lookup_keys(name):
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
        """Upgrade 1.2 data (idempotent). Returns True if something changed.

        - own prices with a store label are also stored as store prices of that retailer
          (only once, when upgrading; the general price is kept)
        - offers get a "retailer"
        """
        changed = False
        if self.data_version < DATA_VERSION:
            for key, entry in self.prices_user.items():
                if not isinstance(entry, dict) or not entry.get("store"):
                    continue
                retailer = entry.get("retailer") or self.resolve_store(entry["store"])
                if not retailer:
                    continue
                entry["retailer"] = retailer
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
            self.data_version = DATA_VERSION
            changed = True
        for offer in self.offers:
            if "retailer" not in offer:
                offer["retailer"] = self.offer_retailer(offer)
                changed = True
        if changed:
            self._invalidate_prices()
        return changed

    # ------------------------------------------------------------------
    # Branches (minimal accessors; management follows in a later phase)
    # ------------------------------------------------------------------

    def selected_branches(self: EssensplanerManager) -> list[dict[str, Any]]:
        """Selected branches: main branch first, then by priority (ascending)."""
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
        """Retailer of an offer (stored, from the marktguru id or from the store name)."""
        if "retailer" in offer:
            return offer["retailer"]
        return retailer_for_store_id(offer.get("store_id")) or self.resolve_store(
            offer.get("store")
        )

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
        self.tag_offer_branches()
        self._invalidate_prices()
        self._ensure_price_context()
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

        Clears the main branch and shopping list store choices pointing to it.
        """
        found = self.require_branch(branch, unique=True)
        view = self.branch_view(found)
        branch_id = found["id"]
        self.branches = [b for b in self.branches if b.get("id") != branch_id]
        if self.main_branch == branch_id:
            self.main_branch = None
        for item in self.shopping:
            if branch_id in (item.get("branch_id"), item.get("store_override")):
                for field in SHOPPING_STORE_FIELDS:
                    item.pop(field, None)
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
        return self._default_index

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
            entry = index.add(
                item,
                source or item.get("source") or SOURCE_USER,
                keys=[key],
                store_id=retailer,
            )
            if entry is None:
                continue
            if retailer and not entry.store:
                entry.store = retailer_name(retailer)
            default = defaults.get(key) or defaults.exact(entry.name)
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
        self._changed("prices")
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
        removed = self._pop_store_price(retailer_id, ingredient_key(name or ""))
        if removed:
            self._invalidate_prices()
            self._changed("prices")
        return removed

    def _pop_store_price(self: EssensplanerManager, retailer: str, key: str) -> bool:
        removed = False
        bucket = self.store_prices_user.get(retailer)
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
        """Price per base unit within PLAUSIBLE_MIN..MAX x the estimate (if comparable)."""
        per = unit_price(entry)
        if per is None or per[0] <= 0:
            return False
        default = self.defaults_index().lookup(key)
        reference = unit_price(default) if default else None
        if reference is None or reference[0] <= 0 or not _comparable(per[1], reference[1]):
            return True  # nothing to compare with
        return PLAUSIBLE_MIN <= per[0] / reference[0] <= PLAUSIBLE_MAX

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

        def row_for(key: str, name: str) -> dict[str, Any]:
            default = defaults.get(key) or defaults.exact(name)
            row_key = ingredient_key(default.name) if default else key
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
                row = row_for(key, str(item.get("name") or key))
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
