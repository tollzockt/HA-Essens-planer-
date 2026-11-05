"""Branches, store specific prices and the price matrix (mixin for the manager).

Price order for a retailer r (first match wins, see store_book()):
own store price of r -> learned store price of r (<= 180 days, REWE online before leaflet)
-> own general price -> learned general price -> default estimate.
General prices that carry a store label of another retailer are that retailer's prices
and are skipped for r.
"""

from __future__ import annotations

from datetime import date, timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from .ingredients import fold, guess_category, ingredient_key
from .pricing import LayeredPriceBook, PriceEntry, PriceIndex, lookup_keys, make_entry, unit_price
from .retailers import RETAILERS, resolve_retailer, retailer_for_store_id, retailer_name

if TYPE_CHECKING:
    from .manager import EssensplanerManager

_LOGGER = logging.getLogger(__name__)

DATA_VERSION = 2
# learned store prices older than this are ignored for lookups (kept in storage)
STALE_DAYS = 180
# learned store price sources, most trusted first
LEARNED_SOURCES = ("rewe_online", "leaflet")
SOURCE_USER = "user"


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
