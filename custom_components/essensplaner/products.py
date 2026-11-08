"""Product database (Artikel-Datenbank, 1.5).

Every real product with a real price the Essensplaner sees is kept here, per chain: the
offers of the offer catalog (EDEKA, ALDI SÜD weekly offers, marktguru), the products of the
REWE / ALDI SÜD online price refresh and of the live article search (the hits that fit the
searched ingredient), the lines of saved receipts and products the user typed. Nothing is
fetched for it – it only keeps what the other sources fetched anyway. Only real prices:
shop prices, leaflet prices (and the regular price printed in a leaflet), receipt prices
and typed prices; no estimates and never a price of another chain.

Stored in its own file (Store "essensplaner.products.<entry_id>"), removed with the entry:
{version, seeded, updated, products: {pid: product}, favorites: {ingredient key: pid},
picks: {ingredient key: [[pid, count, last date, "picked" | "bought"], … ≤ MAX_PICKS]},
aliases: {old pid: pid}}.

A product: {id, retailer, name, brand, pack_amount, pack_unit, image, category, kind,
keys (ingredient keys), sig, stable_id?, deposit?, description?, sources (≤ MAX_SOURCES),
regular: {price, source (rewe_online | aldi_online | leaflet | receipt | user), seen}?,
offer: {price, id, source, valid_from, valid_to, zip_codes?, branch_ids?, loyalty?,
loyalty_note?, app_price?}?, unit_price?, base_unit?, history: [[date, price, "r" | "o"],
… ≤ HISTORY_MAX], first_seen, last_seen, manual?}.

Identity: a stable id of the chain (REWE product id, ALDI SÜD sku) gives pid
"<retailer>:<id>"; otherwise the signature sig = folded brand | core name (the folded name
without the brand, the pack size and filler words) | pack gives pid "<retailer>:s<hash>".
The same signature at one chain is the same product (marktguru's and EDEKA's weekly offer
ids change every week); a signature product becomes the stable product when the chain's
own id shows up. The same signature at another chain is a twin ("auch bei Lidl 1,19 €"),
but only for brands that are not a chain's own brand (retailers.STORE_BRANDS).

Caps (small on a Raspberry Pi): MAX_PRODUCTS, history ≤ HISTORY_MAX, images only as
URLs, saved SAVE_DELAY s after a change, offers ingested in chunks of INGEST_CHUNK. Never
pruned: own products, favourites, picks and products used by open shopping items,
recipes or occasions; a product with a valid offer stays; others go KEEP_DAYS after they
were last seen; above MAX_PRODUCTS the oldest unprotected go first. Non-food is never
stored.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import date, timedelta
from functools import lru_cache
import hashlib
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .catalog import (
    KIND_DRINKS,
    KIND_DRUG,
    KIND_FOOD,
    KIND_HOUSEHOLD,
    KIND_NONFOOD,
    KIND_UNKNOWN,
    _branch_ids,
    _branch_index,
    _reference,
    classify_offer,
    kind_matches,
)
from .const import STORAGE_KEY
from .ingredients import (
    CATEGORY_DRUGSTORE,
    CATEGORY_HOUSEHOLD,
    CATEGORY_ORDER,
    NONFOOD_CATEGORIES,
    category_rank,
    fold,
    guess_category,
    ingredient_key,
)
from .offers import leaflet_week_end, names_key_product, parse_pack_text, split_pack
from .online_prices import learn_price, product_matches
from .pricing import (
    PriceEntry,
    format_eur,
    item_cost,
    offer_pack,
    pack_text,
    plausible_pack,
    to_pricing_base,
)
from .retailers import ALDI_SUED, RETAILERS, is_store_brand, retailer_for_store_id, retailer_name

if TYPE_CHECKING:
    from .manager import EssensplanerManager

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
SAVE_DELAY = 30
MAX_PRODUCTS = 3000
KEEP_DAYS = 120
REGULAR_STALE_DAYS = 90
HISTORY_MAX = 8
HISTORY_INTERVAL_DAYS = 7
MAX_KEYS = 6
MAX_SOURCES = 4
MAX_PICKS = 3
MAX_ALIASES = 500
PICK_RECENT_DAYS = 60
INGEST_CHUNK = 200
SHOP_LIMIT = 6
LIVE_LIMIT = 10
SEED_RECEIPT_DAYS = 90
RECEIPT_TOLERANCE = 0.15
DESCRIPTION_MAX = 120
NAME_MAX = 120
MAX_VIEW_LIMIT = 100
ALTERNATIVES_LIMIT = 20

# kinds of products that are stored (an unknown kind only with an ingredient key)
STORED_KINDS = frozenset({KIND_FOOD, KIND_DRINKS, KIND_DRUG, KIND_HOUSEHOLD})

PICK_PICKED = "picked"
PICK_BOUGHT = "bought"
PICK_KINDS = (PICK_PICKED, PICK_BOUGHT)

# why a product was chosen for a shopping item (choose_for_item)
REASON_MANUAL = "manual"
REASON_FAVORITE = "favorite"
REASON_PICKED = PICK_PICKED
REASON_BOUGHT = PICK_BOUGHT
REASON_CHEAPEST = "cheapest"
REASON_OFFER = "offer"
REASONS = (
    REASON_FAVORITE,
    REASON_PICKED,
    REASON_BOUGHT,
    REASON_CHEAPEST,
    REASON_MANUAL,
    REASON_OFFER,
)

# filters / sorting of products_view()
ONLY_FAVORITES = "favorites"
ONLY_OFFERS = "offers"
ONLY_BOUGHT = "bought"
ONLY_MANUAL = "manual"
ONLY_VALUES = (ONLY_FAVORITES, ONLY_OFFERS, ONLY_BOUGHT, ONLY_MANUAL)
SORTS = ("price", "unit_price", "saving", "name", "recent")
KIND_FILTERS = ("food", "drugstore", "household", "nonfood", "all")

# sources of a regular price (higher rank wins while the price is fresh)
SOURCE_USER = "user"
SOURCE_RECEIPT = "receipt"
SOURCE_LEAFLET = "leaflet"
REWE_ONLINE = "rewe_online"
ALDI_ONLINE = "aldi_online"
REGULAR_SOURCES = (REWE_ONLINE, ALDI_ONLINE, SOURCE_LEAFLET, SOURCE_RECEIPT, SOURCE_USER)
_REGULAR_RANK = {
    SOURCE_LEAFLET: 1,
    REWE_ONLINE: 2,
    ALDI_ONLINE: 2,
    SOURCE_RECEIPT: 3,
    SOURCE_USER: 4,
}
# shop sources: the chain whose own price (and stable product id) they are
SHOP_SOURCES = {REWE_ONLINE: "rewe", ALDI_ONLINE: ALDI_SUED}
# offer ids that carry the chain's stable product id ("rewe_<id>", "aldi_<sku>")
_STABLE_ID_PREFIXES = {"rewe": "rewe_", ALDI_SUED: "aldi_"}
# words of an offer name that do not tell which product it is
_FILLER_WORDS = frozenset(
    {"je", "versch", "verschiedene", "verschiedener", "sorten", "sorte", "ca"}
)
# pack units besides g / ml / Stück (washing loads, rolls)
_OTHER_PACK_UNITS = ("WL", "Rolle")

# the aisle of a kind (a product's category follows its kind)
_KIND_AISLES = {
    KIND_DRUG: CATEGORY_DRUGSTORE,
    KIND_HOUSEHOLD: CATEGORY_HOUSEHOLD,
    KIND_DRINKS: "Getränke",
}

RECIPE_STEP = "Nach Packungsanleitung zubereiten."
RECIPE_TAG = "Fertiggericht"


# ----------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------


def _price(value: Any) -> float | None:
    """A price in EUR (None unless 0 < price ≤ 10000)."""
    if isinstance(value, bool):
        return None
    try:
        price = round(float(value), 2)
    except (TypeError, ValueError):
        return None
    return price if 0 < price <= 10000 else None


def _parse_day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _valid_pack(pack: tuple[float, str] | None) -> tuple[float, str] | None:
    """A pack size that can be priced (plausible g / ml / Stück, washing loads, rolls)."""
    if not pack:
        return None
    try:
        amount, unit = float(pack[0]), str(pack[1])
    except (TypeError, ValueError, IndexError):
        return None
    if amount <= 0:
        return None
    if unit in _OTHER_PACK_UNITS or plausible_pack(amount, unit):
        return amount, unit
    return None


def pack_key(pack: tuple[float, str] | None) -> str:
    """'250g', '1000ml', '10Stück' ('' without a pack)."""
    if not pack:
        return ""
    return f"{float(pack[0]):g}{pack[1]}"


def core_name(name: str, brand: str = "") -> str:
    """The folded product name without the brand, the pack size and filler words."""
    text, _ = split_pack(name)
    words = fold(text).split()
    brand_words = set(fold(brand).split())
    plain = [w for w in words if w not in _FILLER_WORDS]
    core = [w for w in plain if w not in brand_words]
    return " ".join(core or plain or words)


def signature(name: str, brand: str = "", pack: tuple[float, str] | None = None) -> str:
    """brand | core name | pack – the same product at a chain (and its twins elsewhere)."""
    return f"{fold(brand)}|{core_name(name, brand)}|{pack_key(pack)}"


def stable_id(item: dict[str, Any], retailer: str | None) -> str | None:
    """The chain's own product id (REWE product id, ALDI SÜD sku) of a product or offer."""
    value = item.get("product_id")
    if value not in (None, ""):
        return str(value)[:64]
    prefix = _STABLE_ID_PREFIXES.get(retailer or "")
    offer_id = str(item.get("id") or "")
    if prefix and offer_id.startswith(prefix) and len(offer_id) > len(prefix):
        return offer_id[len(prefix) :][:64]
    return None


def product_title(product: dict[str, Any]) -> str:
    """Brand and name ('Kerrygold Irische Butter'); the name when it names the brand."""
    return _title(str(product.get("brand") or ""), str(product.get("name") or ""))


@lru_cache(maxsize=4096)
def _title(brand: str, name: str) -> str:
    if brand and fold(brand) not in fold(name):
        return f"{brand} {name}"
    return name


def product_pack(product: dict[str, Any]) -> tuple[float, str] | None:
    """(amount, unit) of a product (None if unknown)."""
    return _valid_pack((product.get("pack_amount"), product.get("pack_unit")))  # type: ignore[arg-type]


def _regular_fresh(regular: dict[str, Any] | None, day: date) -> bool:
    if not regular or regular.get("price") is None:
        return False
    seen = _parse_day(regular.get("seen"))
    return seen is not None and (day - seen).days <= REGULAR_STALE_DAYS


def _offer_now(offer: dict[str, Any] | None, iso: str) -> bool:
    return bool(
        offer
        and offer.get("price") is not None
        and (offer.get("valid_from") or "") <= iso <= (offer.get("valid_to") or "9999")
    )


def _per_unit(product: dict[str, Any], price: float | None) -> tuple[float, str] | None:
    """(price per g / ml / Stück …, base unit) of a price of the product."""
    if price is None:
        return None
    pack = product_pack(product)
    if pack is not None:
        amount, unit = to_pricing_base(pack[0], pack[1])
        if amount:
            return price / amount, unit
    if product.get("unit_price") and product.get("base_unit"):
        return float(product["unit_price"]), str(product["base_unit"])
    return None


@lru_cache(maxsize=2048)
def _key_category(key: str) -> str:
    """The aisle of an ingredient key (guess_category is slow for thousands of offers)."""
    return guess_category(key)


@lru_cache(maxsize=1024)
def _store_brand(brand: str, retailer: str) -> bool:
    return is_store_brand(brand, retailer)


def _image(value: Any) -> str | None:
    text = str(value or "").strip()
    return text[:500] if text.startswith("https://") else None


# ----------------------------------------------------------------------
# The store
# ----------------------------------------------------------------------


def _empty() -> dict[str, Any]:
    return {
        "version": STORE_VERSION,
        "seeded": False,
        "updated": None,
        "products": {},
        "favorites": {},
        "picks": {},
        "aliases": {},
    }


def _clean_picks(value: Any) -> dict[str, list[list[Any]]]:
    picks: dict[str, list[list[Any]]] = {}
    if not isinstance(value, dict):
        return picks
    for key, entries in value.items():
        clean: list[list[Any]] = []
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, list) or len(entry) != 4:
                continue
            pid, count, last, kind = entry
            try:
                count = max(1, int(count))
            except (TypeError, ValueError):
                continue
            if pid and isinstance(last, str) and kind in PICK_KINDS:
                clean.append([str(pid), count, last[:10], kind])
        if clean:
            picks[str(key)] = clean[:MAX_PICKS]
    return picks


class ProductStore:
    """The product database of one config entry (kept in memory, saved after changes).

    Indexes (ingredient key, retailer, chain + signature, signature of twins, offer id) are
    kept up to date with every change; revision counts the changes (view caches)."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize (empty until async_load)."""
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(hass, STORE_VERSION, self.store_key(entry_id))
        self.data: dict[str, Any] = _empty()
        self.revision = 0
        self.unloaded = False
        self._dirty = False  # changed since the last write
        self._by_key: dict[str, set[str]] = {}
        self._by_retailer: dict[str, set[str]] = {}
        self._by_sig: dict[str, str] = {}
        self._by_twin: dict[str, set[str]] = {}
        self._by_offer: dict[str, str] = {}
        self._text_memo: tuple[int, dict[str, str]] | None = None
        # per revision and day: {("entry", pid, branch id): PriceEntry | None, ("key", key,
        # retailer): [fitting products]} – the shopping list asks the same products for many
        # items and stores (best_for())
        self._price_memo: tuple[tuple[int, str], dict[Any, Any]] | None = None
        self._lock: asyncio.Lock | None = None

    @staticmethod
    def store_key(entry_id: str) -> str:
        """Storage key of the product file of an entry."""
        return f"{STORAGE_KEY}.products.{entry_id}"

    @property
    def path(self) -> str:
        """Path of the product file."""
        return self._store.path

    # -- data ---------------------------------------------------------------------

    @property
    def products(self) -> dict[str, dict[str, Any]]:
        """{pid: product}."""
        return self.data["products"]

    @property
    def favorites(self) -> dict[str, str]:
        """{ingredient key: pid} – the ⭐ product of an ingredient."""
        return self.data["favorites"]

    @property
    def picks(self) -> dict[str, list[list[Any]]]:
        """{ingredient key: [[pid, count, last date, picked | bought]]}."""
        return self.data["picks"]

    @property
    def aliases(self) -> dict[str, str]:
        """{old pid: pid} of products that got their chain's stable id."""
        return self.data["aliases"]

    @property
    def lock(self) -> asyncio.Lock:
        """One ingest at a time."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    # -- persistence --------------------------------------------------------------

    async def async_load(self) -> None:
        """Read the file (missing or unreadable = an empty database)."""
        try:
            data = await self._store.async_load()
        except (OSError, ValueError) as err:  # pragma: no cover - defensive
            _LOGGER.warning("Could not read the product database: %s", err)
            data = None
        base = _empty()
        if isinstance(data, dict):
            base["seeded"] = bool(data.get("seeded"))
            if isinstance(data.get("updated"), str):
                base["updated"] = data["updated"]
            products = data.get("products")
            if isinstance(products, dict):
                for pid, product in products.items():
                    if (
                        isinstance(product, dict)
                        and product.get("retailer")
                        and product.get("name")
                    ):
                        product["id"] = str(pid)
                        base["products"][str(pid)] = product
            for key in ("favorites", "aliases"):
                value = data.get(key)
                if isinstance(value, dict):
                    base[key] = {str(k): str(v) for k, v in value.items() if k and v}
            base["picks"] = _clean_picks(data.get("picks"))
        self.data = base
        self._reindex()

    def _data_to_save(self) -> dict[str, Any]:
        self._dirty = False
        self.data["updated"] = dt_util.utcnow().isoformat()
        return self.data

    async def async_save(self, force: bool = False) -> None:
        """Write the file now if something changed (a pending delayed write is replaced)."""
        if not self.unloaded and (self._dirty or force):
            await self._store.async_save(self._data_to_save())

    def save_later(self) -> None:
        """Write the file in SAVE_DELAY seconds (changes in between are written together)."""
        if not self.unloaded:
            self._dirty = True
            self._store.async_delay_save(self._data_to_save, SAVE_DELAY)

    async def async_remove(self) -> None:
        """Delete the file."""
        await self._store.async_remove()

    # -- indexes ------------------------------------------------------------------

    def _touch(self) -> None:
        self.revision += 1

    def _reindex(self) -> None:
        self._by_key = {}
        self._by_retailer = {}
        self._by_sig = {}
        self._by_twin = {}
        self._by_offer = {}
        # stable products first: a signature points to the chain's own product
        for product in sorted(self.products.values(), key=lambda p: not p.get("stable_id")):
            self._index(product)
        self._touch()

    def _index(self, product: dict[str, Any]) -> None:
        pid = product["id"]
        retailer = product["retailer"]
        self._by_retailer.setdefault(retailer, set()).add(pid)
        for key in product.get("keys") or []:
            self._by_key.setdefault(key, set()).add(pid)
        sig = product.get("sig")
        if sig:
            self._by_sig.setdefault(f"{retailer}|{sig}", pid)
            if product.get("brand") and not _store_brand(product["brand"], retailer):
                self._by_twin.setdefault(sig, set()).add(pid)
        offer_id = (product.get("offer") or {}).get("id")
        if offer_id:
            self._by_offer[str(offer_id)] = pid

    def _unindex(self, product: dict[str, Any]) -> None:
        pid = product.get("id")
        retailer = product.get("retailer")
        if not pid or not retailer:
            return
        self._by_retailer.get(retailer, set()).discard(pid)
        for key in product.get("keys") or []:
            pids = self._by_key.get(key)
            if pids is not None:
                pids.discard(pid)
                if not pids:
                    del self._by_key[key]
        sig = product.get("sig")
        if sig:
            if self._by_sig.get(f"{retailer}|{sig}") == pid:
                del self._by_sig[f"{retailer}|{sig}"]
            twins = self._by_twin.get(sig)
            if twins is not None:
                twins.discard(pid)
                if not twins:
                    del self._by_twin[sig]
        offer_id = str((product.get("offer") or {}).get("id") or "")
        if offer_id and self._by_offer.get(offer_id) == pid:
            del self._by_offer[offer_id]

    # -- lookups ------------------------------------------------------------------

    def resolve(self, pid: Any) -> str | None:
        """The current id of a product id (also an old id before the stable id)."""
        if not pid:
            return None
        pid = str(pid)
        if pid in self.products:
            return pid
        alias = self.aliases.get(pid)
        return alias if alias in self.products else None

    def get(self, pid: Any) -> dict[str, Any] | None:
        """A product by id (None if unknown)."""
        resolved = self.resolve(pid)
        return self.products.get(resolved) if resolved else None

    def by_sig(self, retailer: str, sig: str) -> dict[str, Any] | None:
        """The product of a chain with this signature."""
        return self.get(self._by_sig.get(f"{retailer}|{sig}"))

    def by_offer(self, offer_id: Any) -> dict[str, Any] | None:
        """The product whose current offer has this id."""
        return self.get(self._by_offer.get(str(offer_id or "")))

    def by_key(self, key: str, retailers: Iterable[str] | None = None) -> list[dict[str, Any]]:
        """Products of an ingredient key (optionally only of these retailers)."""
        wanted = set(retailers) if retailers is not None else None
        return [
            product
            for pid in sorted(self._by_key.get(key) or ())
            if (product := self.products.get(pid)) is not None
            and (wanted is None or product["retailer"] in wanted)
        ]

    def memo(self, day: date) -> dict[Any, Any]:
        """A cache that lives until the products change or the day changes."""
        ident = (self.revision, day.isoformat())
        if self._price_memo is None or self._price_memo[0] != ident:
            self._price_memo = (ident, {})
        return self._price_memo[1]

    def by_retailer(self, retailer: str) -> list[dict[str, Any]]:
        """All products of a chain."""
        return [self.products[pid] for pid in sorted(self._by_retailer.get(retailer) or ())]

    def retailers(self) -> list[str]:
        """Chains with products."""
        return sorted(r for r, pids in self._by_retailer.items() if pids)

    def twins(self, pid: Any) -> list[dict[str, Any]]:
        """The same branded product at other chains (never for a chain's own brand)."""
        product = self.get(pid)
        if product is None or not product.get("sig") or not product.get("brand"):
            return []
        if is_store_brand(product["brand"], product["retailer"]):
            return []
        return [
            other
            for other_id in sorted(self._by_twin.get(product["sig"]) or ())
            if other_id != product["id"]
            and (other := self.products.get(other_id)) is not None
            and other["retailer"] != product["retailer"]
        ]

    def favorite_ids(self) -> set[str]:
        """Products that are someone's ⭐."""
        return {pid for pid in self.favorites.values() if pid in self.products}

    def pick_ids(self, kind: str | None = None) -> set[str]:
        """Products in the picks (of one kind)."""
        return {
            entry[0]
            for entries in self.picks.values()
            for entry in entries
            if kind is None or entry[3] == kind
        }

    def bought_ids(self) -> set[str]:
        """Products bought (a receipt or ticked off on the shopping list)."""
        found = self.pick_ids(PICK_BOUGHT)
        found |= {
            pid for pid, p in self.products.items() if SOURCE_RECEIPT in (p.get("sources") or [])
        }
        return found

    def search_text(self) -> dict[str, str]:
        """{pid: folded brand, name, description and keys} (cached per revision)."""
        if self._text_memo is not None and self._text_memo[0] == self.revision:
            return self._text_memo[1]
        texts = {
            pid: fold(
                " ".join(
                    (
                        str(p.get("brand") or ""),
                        str(p.get("name") or ""),
                        str(p.get("description") or ""),
                        " ".join(p.get("keys") or []),
                    )
                )
            )
            for pid, p in self.products.items()
        }
        self._text_memo = (self.revision, texts)
        return texts

    # -- changes ------------------------------------------------------------------

    def find_or_create(
        self, retailer: str, stable: str | None, sig: str
    ) -> tuple[dict[str, Any], bool]:
        """(product, created) for a chain's stable id or signature. A signature product
        becomes the stable product when the stable id shows up (not an own product)."""
        if stable:
            pid = f"{retailer}:{stable}"
            product = self.get(pid)
            if product is not None:
                return product, False
            other = self.by_sig(retailer, sig)
            if other is not None and not other.get("stable_id") and not other.get("manual"):
                self.rename(other["id"], pid)
                other["stable_id"] = stable
                return other, False
            return {"id": pid, "stable_id": stable}, True
        product = self.by_sig(retailer, sig)
        if product is not None:
            return product, False
        number = 0
        while True:
            text = sig if not number else f"{sig}#{number}"
            digest = hashlib.sha1(text.encode(), usedforsecurity=False).hexdigest()[:10]
            pid = f"{retailer}:s{digest}"
            if pid not in self.products and pid not in self.aliases:
                return {"id": pid}, True
            number += 1

    def upsert(self, product: dict[str, Any]) -> None:
        """Store a product as it is (indexes updated); products.ingest_*() and
        save_manual() merge new prices into a product instead."""
        old = self.products.get(product["id"])
        if old is not None:
            self._unindex(old)
        self.products[product["id"]] = product
        self._index(product)
        self._touch()

    def rename(self, old: str, new: str) -> None:
        """Give a product a new id (its favourites, picks and an alias follow)."""
        product = self.products.pop(old, None)
        if product is None or new in self.products:
            if product is not None:
                self.products[old] = product
            return
        self._unindex(product)
        product["id"] = new
        self.products[new] = product
        self._index(product)
        for alias, target in list(self.aliases.items()):
            if target == old:
                self.aliases[alias] = new
        self.aliases[old] = new
        while len(self.aliases) > MAX_ALIASES:
            del self.aliases[next(iter(self.aliases))]
        for key, pid in list(self.favorites.items()):
            if pid == old:
                self.favorites[key] = new
        for entries in self.picks.values():
            for entry in entries:
                if entry[0] == old:
                    entry[0] = new
        self._touch()

    def remove(self, pid: Any) -> dict[str, Any] | None:
        """Delete a product (its favourites, picks and aliases go too)."""
        resolved = self.resolve(pid)
        product = self.products.pop(resolved, None) if resolved else None
        if product is None:
            return None
        self._unindex(product)
        for key, fav in list(self.favorites.items()):
            if fav == resolved:
                del self.favorites[key]
        for key, entries in list(self.picks.items()):
            kept = [e for e in entries if e[0] != resolved]
            if kept:
                self.picks[key] = kept
            else:
                del self.picks[key]
        for alias, target in list(self.aliases.items()):
            if target == resolved:
                del self.aliases[alias]
        self._touch()
        return product

    def prune(self, today: date, protected: Iterable[str] = ()) -> int:
        """Drop ended offers and products nobody needs (see the module doc). Returns the
        number of products removed."""
        iso = today.isoformat()
        cutoff = (today - timedelta(days=KEEP_DAYS)).isoformat()
        keep = {self.resolve(p) for p in protected} | self.favorite_ids() | self.pick_ids()
        changed = False
        for product in self.products.values():
            offer = product.get("offer")
            if offer and (offer.get("valid_to") or "9999") < iso:
                self._unindex(product)
                del product["offer"]
                self._index(product)
                changed = True
        removed: list[str] = []
        for pid, product in self.products.items():
            if pid in keep or product.get("manual"):
                continue
            if product.get("offer"):
                continue  # a valid (or announced) offer
            if (product.get("last_seen") or "") < cutoff:
                removed.append(pid)
        for pid in removed:
            self.remove(pid)
        over = len(self.products) - MAX_PRODUCTS
        if over > 0:
            candidates = [
                p for pid, p in self.products.items() if pid not in keep and not p.get("manual")
            ]
            candidates.sort(
                key=lambda p: (
                    bool(p.get("offer")),
                    p.get("last_seen") or "",
                    p.get("first_seen") or "",
                    p["id"],
                )
            )
            for product in candidates[:over]:
                self.remove(product["id"])
                removed.append(product["id"])
        for key, pid in list(self.favorites.items()):
            if pid not in self.products:
                del self.favorites[key]
        if changed or removed:
            self._touch()
        return len(removed)


def _store_of(manager: Any) -> ProductStore | None:
    store = getattr(manager, "products", None)
    return store if isinstance(store, ProductStore) else None


# ----------------------------------------------------------------------
# Changing a product
# ----------------------------------------------------------------------


def _add_history(product: dict[str, Any], iso: str, price: float, kind: str) -> None:
    """A price in the history (≤ HISTORY_MAX): a new price, or the same price again after
    HISTORY_INTERVAL_DAYS; a new price of the same day replaces that day's."""
    history = [h for h in product.get("history") or [] if isinstance(h, list) and len(h) == 3]
    same = [h for h in history if h[2] == kind]
    last = same[-1] if same else None
    if last is not None:
        if last[0] == iso and last[1] == price:
            return
        last_day, this_day = _parse_day(last[0]), _parse_day(iso)
        if (
            last[1] == price
            and last_day is not None
            and this_day is not None
            and abs((this_day - last_day).days) < HISTORY_INTERVAL_DAYS
        ):
            return
        if last[0] == iso:
            history.remove(last)
    history.append([iso, price, kind])
    history.sort(key=lambda h: h[0])
    product["history"] = history[-HISTORY_MAX:]


def _set_regular(product: dict[str, Any], price: float, source: str, iso: str) -> bool:
    """Set the regular price unless a fresh one of a more trusted source or a newer one is
    known. Returns True if set."""
    current = product.get("regular")
    if current and current.get("price") is not None:
        day = _parse_day(iso) or dt_util.now().date()
        fresh = _regular_fresh(current, day)
        if fresh and iso < str(current.get("seen") or ""):
            return False  # older information
        if fresh and _REGULAR_RANK.get(source, 0) < _REGULAR_RANK.get(current.get("source"), 0):
            return False
    product["regular"] = {"price": price, "source": source, "seen": iso}
    _add_history(product, iso, price, "r")
    return True


def _offer_better(current: dict[str, Any] | None, new: dict[str, Any], iso: str) -> bool:
    if not current or current.get("price") is None:
        return True
    if (current.get("valid_to") or "9999") < iso:
        return True
    current_now = (current.get("valid_from") or "") <= iso
    new_now = _offer_now(new, iso)
    if new_now != current_now:
        return new_now
    return float(new["price"]) <= float(current["price"])


def _set_offer(product: dict[str, Any], offer: dict[str, Any], iso: str) -> None:
    current = product.get("offer")
    if current and offer.get("id") and current.get("id") == offer.get("id"):
        merged = {**current, **offer}
        for field in ("zip_codes", "branch_ids"):
            values = list(current.get(field) or [])
            values += [v for v in offer.get(field) or [] if v not in values]
            if values:
                merged[field] = values
        product["offer"] = merged
    elif _offer_better(current, offer, iso):
        product["offer"] = offer
    else:
        return
    _add_history(product, str(offer.get("valid_from") or iso)[:10], float(offer["price"]), "o")


def _merge_keys(product: dict[str, Any], keys: Iterable[str]) -> None:
    merged: list[str] = []
    for key in [*keys, *(product.get("keys") or [])]:
        key = str(key or "").strip()
        if key and key not in merged:
            merged.append(key)
    product["keys"] = merged[:MAX_KEYS]


def _add_source(product: dict[str, Any], source: str) -> None:
    sources = [s for s in product.get("sources") or [] if s != source]
    sources.append(source)
    product["sources"] = sources[-MAX_SOURCES:]


def _upsert(
    store: ProductStore,
    day: date,
    *,
    retailer: str,
    name: str,
    source: str,
    brand: str = "",
    pack: tuple[float, str] | None = None,
    stable: str | None = None,
    keys: Iterable[str] = (),
    kind: str | None = None,
    category: str | None = None,
    image: Any = None,
    description: str | None = None,
    deposit: Any = None,
    unit: tuple[float, str] | None = None,
    regular: tuple[float, str] | None = None,
    offer: dict[str, Any] | None = None,
    history: tuple[float, str] | None = None,
    manual: bool = False,
    own_name: bool = False,
    pid: str | None = None,
) -> dict[str, Any] | None:
    """Create or update a product (see the module doc for its identity).

    own_name: the name, brand and pack of this source win (the chain's online shop, an own
    product); otherwise they only fill gaps. manual: an own product (never pruned, its
    image and brand may be cleared). pid: update exactly this product."""
    name = " ".join(str(name or "").split())[:NAME_MAX]
    if not name or not retailer:
        return None
    brand = " ".join(str(brand or "").split())[:60]
    pack = _valid_pack(pack) or _valid_pack(split_pack(name)[1])
    keys = [k for k in keys if k]
    iso = day.isoformat()
    sig = signature(name, brand, pack)
    product: dict[str, Any] | None = store.get(pid) if pid else None
    created = False
    if product is None:
        product, created = store.find_or_create(retailer, stable, sig)
    store._unindex(product)
    if created:
        product.update(
            {
                "retailer": retailer,
                "name": name,
                "brand": brand,
                "keys": [],
                "sources": [],
                "history": [],
                "first_seen": iso,
                "last_seen": iso,
            }
        )
    elif own_name or manual:
        product["name"] = name
    if brand and (own_name or manual or not product.get("brand")):
        product["brand"] = brand
    elif manual and not brand:
        product["brand"] = ""
    if pack is not None and (own_name or manual or product_pack(product) is None):
        product["pack_amount"], product["pack_unit"] = pack
    if stable and not product.get("stable_id") and product["id"] == f"{retailer}:{stable}":
        product["stable_id"] = stable
    _merge_keys(product, keys)
    if kind and (manual or product.get("kind") in (None, KIND_UNKNOWN)):
        product["kind"] = kind
    elif not product.get("kind"):
        product["kind"] = (
            classify_offer(product["name"], description or "", retailer) or KIND_UNKNOWN
        )
    if category in CATEGORY_ORDER and (manual or not product.get("category")):
        product["category"] = category
    if not product.get("category") or product["category"] == "Sonstiges":
        # the aisle of its ingredient (cached) when the name ends with it ("Bergland
        # Butter", not "Butterkekse"), else of its name
        guessed = "Sonstiges"
        if product.get("keys"):
            last = str(product["keys"][0]).split()[-1]
            if any(word.endswith(last) for word in fold(product["name"]).split()):
                guessed = _key_category(product["keys"][0])
        if guessed == "Sonstiges":
            guessed = guess_category(product["name"])
        product["category"] = guessed
    if product.get("kind") in _KIND_AISLES and not (manual and category in CATEGORY_ORDER):
        # a drugstore / household product is in its aisle ("Kräuter-Shampoo" is no herb)
        drinks = product["kind"] == KIND_DRINKS
        if (drinks and product["category"] == "Sonstiges") or (
            not drinks and product["category"] not in NONFOOD_CATEGORIES
        ):
            product["category"] = _KIND_AISLES[product["kind"]]
    if (url := _image(image)) is not None:
        product["image"] = url
    elif manual and image is not None and not str(image).strip():
        product.pop("image", None)
    if description:
        product["description"] = " ".join(str(description).split())[:DESCRIPTION_MAX]
    if (deposit_value := _price(deposit)) is not None:
        product["deposit"] = deposit_value
    if unit is not None:
        try:
            product["unit_price"] = round(float(unit[0]), 6)
            product["base_unit"] = str(unit[1])
        except (TypeError, ValueError, IndexError):
            pass
    if regular is not None:
        _set_regular(product, regular[0], regular[1], iso)
    if offer is not None:
        _set_offer(product, offer, iso)
    if history is not None:
        _add_history(product, iso, history[0], history[1])
    if manual:
        product["manual"] = True
    _add_source(product, source)
    if iso > str(product.get("last_seen") or ""):
        product["last_seen"] = iso
    if iso < str(product.get("first_seen") or "9999"):
        product["first_seen"] = iso
    final_pack = product_pack(product)
    if product["name"] != name or (product.get("brand") or "") != brand or final_pack != pack:
        sig = signature(product["name"], product.get("brand") or "", final_pack)
    product["sig"] = sig
    store.products[product["id"]] = product
    store._index(product)
    store._touch()
    return product


# ----------------------------------------------------------------------
# Ingest (no requests: what the other sources fetched anyway)
# ----------------------------------------------------------------------


def _regular_source(source: str, retailer: str) -> str:
    """Source of the regular price an offer shows (its struck / normal price)."""
    if source in ("aldi_weekly", ALDI_ONLINE) and retailer == ALDI_SUED:
        return ALDI_ONLINE
    if source == REWE_ONLINE and retailer == "rewe":
        return REWE_ONLINE
    return SOURCE_LEAFLET


def ingest_offer(
    manager: EssensplanerManager, offer: dict[str, Any], day: date | None = None
) -> dict[str, Any] | None:
    """Store one offer (catalog, saved, live leaflet or reduced shop offer) as the offer
    of its product. Online-only, ended and non-food offers are left out. Returns the
    product (None if not stored)."""
    store = _store_of(manager)
    if store is None or not isinstance(offer, dict) or offer.get("online_only"):
        return None
    price = _price(offer.get("price"))
    name = str(offer.get("product") or offer.get("title") or "").strip()
    if price is None or not name:
        return None
    day = day or manager.today()
    iso = day.isoformat()
    valid_to = str(offer.get("valid_to") or "")[:10] or None
    if valid_to and valid_to < iso:
        return None
    retailer = (
        offer.get("retailer")
        or retailer_for_store_id(offer.get("store_id"))
        or manager.offer_retailer(offer)
    )
    if not retailer:
        return None
    keys = [str(k) for k in offer.get("keys") or [] if k]
    description = str(offer.get("description") or "")
    categories = offer.get("categories") or ([offer["category"]] if offer.get("category") else None)
    kind = offer.get("kind") or classify_offer(name, description, retailer, categories)
    if kind == KIND_NONFOOD or (kind not in STORED_KINDS and not keys):
        return None
    source = str(offer.get("source") or "offer")
    reference = _reference(offer)
    branch_ids = (
        offer.get("branch_ids")
        or offer.get("branches")
        or ([offer["branch_id"]] if offer.get("branch_id") else None)
    )
    info: dict[str, Any] = {
        "price": price,
        "id": str(offer.get("id") or f"{retailer}:{fold(name)}"),
        "source": source,
        "valid_from": str(offer.get("valid_from") or "")[:10] or None,
        "valid_to": valid_to,
        "zip_codes": list(offer.get("zip_codes") or []) or None,
        "branch_ids": list(branch_ids or []) or None,
        "loyalty": bool(offer.get("loyalty")) or None,
        "loyalty_note": offer.get("loyalty_note") or None,
        "app_price": _price(offer.get("app_price")),
    }
    unit = None
    if offer.get("unit_price") and offer.get("base_unit"):
        unit = (float(offer["unit_price"]), str(offer["base_unit"]))
    return _upsert(
        store,
        day,
        retailer=retailer,
        name=name,
        source=source,
        brand=str(offer.get("brand") or ""),
        pack=offer_pack(offer),
        stable=stable_id(offer, retailer),
        keys=keys,
        kind=kind,
        image=offer.get("image"),
        description=description,
        deposit=offer.get("deposit"),
        unit=unit,
        regular=(reference, _regular_source(source, retailer)) if reference else None,
        offer={k: v for k, v in info.items() if v is not None},
        own_name=source in SHOP_SOURCES,
    )


async def async_ingest_offers(
    manager: EssensplanerManager, offers: Iterable[dict[str, Any]], day: date | None = None
) -> int:
    """Store offers in chunks of INGEST_CHUNK (yielding to the event loop in between), then
    prune. Returns how many were stored."""
    store = _store_of(manager)
    offers = list(offers)
    if store is None or not offers:
        return 0
    day = day or manager.today()
    count = 0
    async with store.lock:
        for position, offer in enumerate(offers):
            if position and position % INGEST_CHUNK == 0:
                await asyncio.sleep(0)
                if manager.unloaded or store.unloaded:
                    return count
            if ingest_offer(manager, offer, day) is not None:
                count += 1
        if count:
            prune_products(manager, day)
            store.save_later()
    return count


async def async_ingest_safe(manager: EssensplanerManager, offers: list[dict[str, Any]]) -> int:
    """async_ingest_offers() that never fails the caller (a refresh)."""
    try:
        return await async_ingest_offers(manager, offers)
    except Exception:
        _LOGGER.exception("Storing products failed")
        return 0


def schedule_ingest(manager: EssensplanerManager, offers: list[dict[str, Any]]) -> None:
    """Store offers soon in the background (e.g. the EDEKA list stored by its refresh)."""
    store = _store_of(manager)
    if store is None or store.unloaded or manager.unloaded or not offers:
        return
    manager.entry.async_create_background_task(
        manager.hass, async_ingest_safe(manager, list(offers)), "essensplaner_products_ingest"
    )


def ingest_shop_products(
    manager: EssensplanerManager,
    retailer: str,
    products: list[dict[str, Any]],
    key: str,
    source: str,
    limit: int = SHOP_LIMIT,
) -> int:
    """Store the products of an online shop search (REWE online prices, ALDI SÜD) that fit
    the searched ingredient (online_prices.product_matches): their shop price as regular
    price, a reduction as offer until the end of the leaflet week. Returns the count."""
    store = _store_of(manager)
    if store is None or not key or not retailer:
        return 0
    day = manager.today()
    iso = day.isoformat()
    count = 0
    for product in products:
        if count >= limit:
            break
        if not isinstance(product, dict) or product.get("online_only"):
            continue
        name = str(product.get("product") or product.get("title") or "").strip()
        price = _price(product.get("price"))
        if not name or price is None or not product_matches(name, key):
            continue
        kind = classify_offer(name, "", retailer, product.get("categories"))
        if kind == KIND_NONFOOD:
            continue
        regular = _price(learn_price(product)) or price
        offer = None
        if regular > price:
            offer = {
                "price": price,
                "id": str(product.get("id") or f"{retailer}:{fold(name)}"),
                "source": source,
                "valid_from": iso,
                "valid_to": leaflet_week_end(day).isoformat(),
            }
        unit = None
        if product.get("unit_price") and product.get("base_unit"):
            unit = (float(product["unit_price"]), str(product["base_unit"]))
        stored = _upsert(
            store,
            day,
            retailer=retailer,
            name=name,
            source=source,
            brand=str(product.get("brand") or ""),
            pack=offer_pack(product),
            stable=stable_id(product, retailer),
            keys=[key],
            kind=kind,
            image=product.get("image"),
            description=None,
            deposit=product.get("deposit"),
            unit=unit,
            regular=(regular, source if source in REGULAR_SOURCES else SOURCE_LEAFLET),
            offer=offer,
            own_name=True,
        )
        if stored is not None:
            count += 1
    if count:
        if len(store.products) > MAX_PRODUCTS:
            prune_products(manager, day)
        store.save_later()
    return count


def ingest_live_results(
    manager: EssensplanerManager, offers: list[dict[str, Any]], key: str
) -> int:
    """The shop hits (REWE / ALDI SÜD) of a live article search, ≤ LIVE_LIMIT per chain;
    marktguru hits are only stored when one is picked (product_for_offer())."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for offer in offers:
        source = str(offer.get("source") or "")
        retailer = offer.get("retailer") or SHOP_SOURCES.get(source)
        if source in SHOP_SOURCES and retailer:
            groups.setdefault((retailer, source), []).append(offer)
    count = 0
    for (retailer, source), items in groups.items():
        count += ingest_shop_products(manager, retailer, items, key, source, LIVE_LIMIT)
    return count


def _receipt_match(
    store: ProductStore,
    retailer: str,
    key: str,
    price: float,
    pack: tuple[float, str] | None,
) -> dict[str, Any] | None:
    """The product of the chain with this key whose price is within RECEIPT_TOLERANCE of
    the receipt price (per g / ml / piece when both packs are known), closest first."""
    best: tuple[float, dict[str, Any]] | None = None
    for product in store.by_key(key, [retailer]):
        regular = product.get("regular") or {}
        offer = product.get("offer") or {}
        reference = _price(regular.get("price")) or _price(offer.get("price"))
        if reference is None:
            history = product.get("history") or []
            reference = _price(history[-1][1]) if history else None
        if reference is None:
            continue
        mine, theirs = price, reference
        other = product_pack(product)
        if pack is not None and other is not None:
            a_amount, a_unit = to_pricing_base(pack[0], pack[1])
            b_amount, b_unit = to_pricing_base(other[0], other[1])
            if a_amount and b_amount and (a_unit == b_unit or {a_unit, b_unit} <= {"g", "ml"}):
                mine, theirs = price / a_amount, reference / b_amount
        diff = abs(mine - theirs) / theirs if theirs else 1.0
        if diff <= RECEIPT_TOLERANCE and (best is None or diff < best[0]):
            best = (diff, product)
    return best[1] if best else None


def ingest_receipt(
    manager: EssensplanerManager, receipt: dict[str, Any], record: bool = True
) -> list[str]:
    """Link the saved lines of a receipt to products: a product of the chain with the same
    ingredient key and a price within ±15 % gets the receipt price (regular, or an offer
    price only into the history), else a receipt product is created. Each one gets a
    "bought" pick (record). Returns the product ids."""
    from .receipts import own_price  # the receipts call this module

    store = _store_of(manager)
    retailer = str(receipt.get("retailer") or "")
    if store is None or not retailer:
        return []
    day = _parse_day(receipt.get("date")) or manager.today()
    linked: list[str] = []
    for item in receipt.get("items") or []:
        if not isinstance(item, dict) or not item.get("key"):
            continue
        if item.get("status") not in ("saved", "kept", "offer"):
            continue
        price = own_price(item)
        if price is None:
            continue
        value, amount, unit = price
        key = str(item["key"])
        pack = _valid_pack((amount, unit))
        offer_line = item.get("status") == "offer"
        match = _receipt_match(store, retailer, key, value, pack)
        name = str(item.get("product") or item.get("name") or "")
        if match is None and classify_offer(name, "", retailer) == KIND_NONFOOD:
            continue
        product = _upsert(
            store,
            day,
            retailer=retailer,
            name=str(match["name"]) if match else name,
            source=SOURCE_RECEIPT,
            pack=None if match else pack,
            keys=[key],
            description=None if match else str(item.get("name") or ""),
            regular=None if offer_line else (value, SOURCE_RECEIPT),
            history=(value, "o") if offer_line else None,
            pid=match["id"] if match else None,
        )
        if product is None:
            continue
        linked.append(product["id"])
        if record:
            record_pick(manager, key, product["id"], PICK_BOUGHT, day, save=False)
    if linked:
        store.save_later()
    return linked


def _seed_learned(manager: EssensplanerManager, today: date) -> int:
    """The REWE / ALDI SÜD shop prices learned before 1.5 (with their product id)."""
    store = _store_of(manager)
    if store is None:
        return 0
    count = 0
    for retailer, bucket in manager.store_prices_learned.items():
        if retailer not in ("rewe", ALDI_SUED) or not isinstance(bucket, dict):
            continue
        for key, item in bucket.items():
            if not isinstance(item, dict) or not item.get("ref"):
                continue
            source = item.get("source")
            if source not in SHOP_SOURCES or SHOP_SOURCES[source] != retailer:
                continue
            seen = _parse_day(item.get("seen")) or today
            price = _price(item.get("price"))
            if price is None or (today - seen).days > REGULAR_STALE_DAYS:
                continue
            try:
                pack = (float(item.get("amount") or 0), str(item.get("unit") or ""))
            except (TypeError, ValueError):
                pack = None
            if _upsert(
                store,
                seen,
                retailer=retailer,
                name=str(item.get("name") or key),
                source=source,
                pack=pack,
                stable=str(item["ref"]),
                keys=[key],
                regular=(price, source),
            ):
                count += 1
    return count


async def async_seed(manager: EssensplanerManager) -> int:
    """Fill a new product database once (flag "seeded"): the current offers of the offer
    catalog and the own offers, the REWE / ALDI SÜD shop prices with their product id,
    the receipts of the last SEED_RECEIPT_DAYS days and the offers picked onto the open
    shopping list. Returns the number of products stored."""
    from .catalog import own_offers  # imports the mixins

    store = _store_of(manager)
    if store is None or store.data.get("seeded"):
        return 0
    today = manager.today()
    offers: list[dict[str, Any]] = [*manager.catalog.current_offers(today)]
    offers += own_offers(manager, today)
    count = await async_ingest_offers(manager, offers, today)
    if manager.unloaded or store.unloaded:
        return count
    # the offers picked onto the open shopping list (a live leaflet offer is only kept
    # there): the item remembers its product
    linked = False
    for item in manager.shopping:
        chosen = item.get("chosen") if item.get("status") != "completed" else None
        if not isinstance(chosen, dict) or chosen.get("product_id"):
            continue
        offer = chosen.get("offer") if isinstance(chosen.get("offer"), dict) else None
        if offer is None and chosen.get("offer_id"):
            offer = next((o for o in manager.offers if o.get("id") == chosen["offer_id"]), None)
        if offer is None:
            continue
        pid = product_for_offer(manager, offer, item.get("key"))
        if pid is not None:
            chosen["product_id"] = pid
            linked = True
            count += 1
    if linked:
        manager._save_later()
    count += _seed_learned(manager, today)
    since = (today - timedelta(days=SEED_RECEIPT_DAYS)).isoformat()
    for receipt in manager.receipts.receipts:
        if str(receipt.get("date") or "") >= since:
            count += len(ingest_receipt(manager, receipt))
    store.data["seeded"] = True
    prune_products(manager, today)
    store._touch()
    store.save_later()
    _LOGGER.debug("Product database seeded with %d products", len(store.products))
    return count


async def async_seed_safe(manager: EssensplanerManager) -> None:
    """async_seed() that only logs a failure (background task after the start)."""
    try:
        await async_seed(manager)
    except Exception:
        _LOGGER.exception("Filling the product database failed")


# ----------------------------------------------------------------------
# Pruning
# ----------------------------------------------------------------------


def protected_ids(manager: EssensplanerManager) -> set[str]:
    """Products used by open shopping items, recipes and occasions."""
    store = _store_of(manager)
    found: set[str] = set()
    for item in manager.shopping:
        if item.get("status") == "completed":
            continue
        if (pid := product_for_item(manager, item)) is not None:
            found.add(pid)
    for recipe in manager.recipes.values():
        for ingredient in recipe.get("ingredients") or []:
            if isinstance(ingredient, dict) and ingredient.get("product_id"):
                found.add(str(ingredient["product_id"]))
    occasions = getattr(manager, "occasions", None)
    if isinstance(occasions, dict):
        for occasion in occasions.values():
            for entry in (occasion or {}).get("items") or []:
                if isinstance(entry, dict) and entry.get("product_id"):
                    found.add(str(entry["product_id"]))
    if store is not None:
        found = {resolved for pid in found if (resolved := store.resolve(pid))}
    return found


def drop_disabled_products(manager: EssensplanerManager) -> int:
    """Forget the offers of sources the user switched off (marktguru, ALDI SÜD, EDEKA –
    like catalog.drop_disabled_sources()); a product that then has no price left and is
    no own product, ⭐, pick or in use goes. Returns the number of products removed."""
    from .catalog import disabled_sources  # imports the mixins

    store = _store_of(manager)
    if store is None:
        return 0
    off = disabled_sources(manager)
    keep = protected_ids(manager) | store.favorite_ids() | store.pick_ids()
    changed = False
    removed: list[str] = []
    for pid, product in store.products.items():
        offer = product.get("offer")
        if offer and offer.get("source") in off:
            store._unindex(product)
            del product["offer"]
            store._index(product)
            changed = True
            if (
                pid not in keep
                and not product.get("manual")
                and not product.get("regular")
                and all(s in off for s in product.get("sources") or [])
            ):
                removed.append(pid)
    for pid in removed:
        store.remove(pid)
    if changed:
        store._touch()
        store.save_later()
    return len(removed)


def prune_products(manager: EssensplanerManager, day: date | None = None) -> int:
    """Prune the product database (daily and after an ingest); saved soon if it changed."""
    store = _store_of(manager)
    if store is None:
        return 0
    before = store.revision
    removed = store.prune(day or manager.today(), protected_ids(manager))
    if store.revision != before:
        store.save_later()
    return removed


# ----------------------------------------------------------------------
# Picks and favourites
# ----------------------------------------------------------------------


def record_pick(
    manager: EssensplanerManager,
    key: str | None,
    pid: str | None,
    kind: str = PICK_PICKED,
    day: date | None = None,
    save: bool = True,
) -> bool:
    """Remember that a product was picked (search, offer) or bought (receipt, ticked off)
    for an ingredient (≤ MAX_PICKS per ingredient, most used first)."""
    store = _store_of(manager)
    product = store.get(pid) if store is not None else None
    if store is None or product is None or not key or kind not in PICK_KINDS:
        return False
    pid = product["id"]
    iso = (day or manager.today()).isoformat()
    entries = [list(e) for e in store.picks.get(key) or []]
    entry = next((e for e in entries if e[0] == pid), None)
    if entry is None:
        entries.append([pid, 1, iso, kind])
    else:
        entry[1] = int(entry[1]) + 1
        entry[2] = max(str(entry[2]), iso)
        entry[3] = PICK_BOUGHT if PICK_BOUGHT in (entry[3], kind) else kind
    entries.sort(key=lambda e: (e[1], e[2]), reverse=True)
    store.picks[key] = entries[:MAX_PICKS]
    store._touch()
    if save:
        store.save_later()
    return True


def _error(key: str, **placeholders: Any) -> Exception:
    from .manager import _error as manager_error  # avoid an import cycle

    return manager_error(key, **placeholders)


def require_product(manager: EssensplanerManager, pid: Any) -> dict[str, Any]:
    """A product by id or the error product_not_found."""
    store = _store_of(manager)
    product = store.get(pid) if store is not None else None
    if product is None:
        raise _error("product_not_found", id=str(pid or ""))
    return product


def _favorite_key(product: dict[str, Any], key: str | None) -> str:
    if key:
        text = str(key).strip()
        if text in (product.get("keys") or []):
            return text
        return ingredient_key(text) or text
    if product.get("keys"):
        return str(product["keys"][0])
    return ingredient_key(split_pack(product["name"])[0])


def set_favorite(
    manager: EssensplanerManager, pid: Any, key: str | None = None, favorite: bool = True
) -> dict[str, Any]:
    """⭐ a product for an ingredient (its first key unless given) or take the ⭐ away
    (favorite False; without a key from every ingredient). Returns {key, product_id
    (None after removing), favorites: {key: pid}}."""
    store = _store_of(manager)
    product = require_product(manager, pid)
    assert store is not None
    pid = product["id"]
    target = _favorite_key(product, key)
    if favorite:
        store.favorites[target] = pid
        if target not in (product.get("keys") or []):
            store._unindex(product)
            _merge_keys(product, [*(product.get("keys") or []), target])
            store._index(product)
    elif key:
        if store.favorites.get(target) == pid:
            del store.favorites[target]
    else:
        for fav_key, fav in list(store.favorites.items()):
            if fav == pid:
                del store.favorites[fav_key]
    store._touch()
    store.save_later()
    return {
        "key": target,
        "product_id": pid if favorite else None,
        "favorites": dict(store.favorites),
    }


def product_for_offer(
    manager: EssensplanerManager, offer: dict[str, Any], key: str | None = None
) -> str | None:
    """The product of an offer picked for the shopping list (a live leaflet offer is
    stored now); None if it is no product to keep (online-only, non-food)."""
    store = _store_of(manager)
    if store is None or not isinstance(offer, dict):
        return None
    found = store.by_offer(offer.get("id"))
    if found is not None:
        return found["id"]
    keys = list(offer.get("keys") or []) or ([key] if key else [])
    product = ingest_offer(manager, {**offer, "keys": keys})
    if product is None:
        return None
    store.save_later()
    return product["id"]


def product_for_item(manager: EssensplanerManager, item: dict[str, Any]) -> str | None:
    """The product of a shopping item: its product, the product of its picked price or
    offer, else of the offer it is priced with."""
    store = _store_of(manager)
    if store is None:
        return None
    product = item.get("product") if isinstance(item.get("product"), dict) else {}
    chosen = item.get("chosen") if isinstance(item.get("chosen"), dict) else {}
    for pid in (item.get("product_id"), product.get("id"), chosen.get("product_id")):
        if (resolved := store.resolve(pid)) is not None:
            return resolved
    offer = item.get("offer") if isinstance(item.get("offer"), dict) else {}
    for offer_id in (chosen.get("offer_id"), offer.get("id")):
        if offer_id and (found := store.by_offer(offer_id)) is not None:
            return found["id"]
    return None


def product_for_hit(
    manager: EssensplanerManager, offer: dict[str, Any], retailer: str | None = None
) -> dict[str, Any] | None:
    """The stored product of a search hit / offer: by its offer id, the chain's stable id
    (REWE product id, ALDI SÜD sku) or its signature at the chain (None if not stored)."""
    store = _store_of(manager)
    if store is None or not isinstance(offer, dict):
        return None
    if offer.get("id") and (found := store.by_offer(offer["id"])) is not None:
        return found
    retailer = (
        offer.get("retailer")
        or retailer_for_store_id(offer.get("store_id"))
        or SHOP_SOURCES.get(str(offer.get("source") or ""))
        or retailer
    )
    if not retailer:
        return None
    stable = stable_id(offer, retailer)
    if stable and (found := store.get(f"{retailer}:{stable}")) is not None:
        return found
    name = str(offer.get("product") or offer.get("title") or "").strip()
    if not name:
        return None
    pack = _valid_pack(offer_pack(offer)) or _valid_pack(split_pack(name)[1])
    return store.by_sig(retailer, signature(name, str(offer.get("brand") or ""), pack))


def slim_product(
    product: dict[str, Any], entry: PriceEntry | None = None, day: date | None = None
) -> dict[str, Any]:
    """The product as kept with a shopping item / a price comparison: {id, name, brand,
    title, image, retailer, pack_amount, pack_unit, price (its pack price: the running
    offer or the regular price), on_offer}."""
    pack = product_pack(product)
    if entry is None and day is not None:
        entry = product_entry(product, day)
    price = entry.price if entry is not None else None
    if price is None:
        price = _price((product.get("regular") or {}).get("price"))
    return {
        "id": product["id"],
        "name": product.get("name") or "",
        "brand": product.get("brand") or "",
        "title": product_title(product),
        "image": product.get("image"),
        "retailer": product["retailer"],
        "pack_amount": pack[0] if pack else None,
        "pack_unit": pack[1] if pack else None,
        "price": round(price, 2) if price is not None else None,
        "on_offer": bool(entry is not None and entry.offer),
    }


def search_hits(
    manager: EssensplanerManager, folded: str, retailers: Iterable[str], day: date
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """(product, prices) of the products of these chains whose brand, name, description or
    ingredient contains the folded query and that can be bought on the day (a running
    offer or a regular price; an only announced offer is no hit) – the article search
    across all stores."""
    store = _store_of(manager)
    if store is None or not folded:
        return []
    wanted = set(retailers)
    found: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for pid, text in store.search_text().items():
        if folded not in text:
            continue
        product = store.products.get(pid)
        if product is None or product["retailer"] not in wanted:
            continue
        prices = _prices(product, day)
        if prices["price"] is None or (not prices["offer_now"] and prices["regular_price"] is None):
            continue
        found.append((product, prices))
    return found


# ----------------------------------------------------------------------
# Prices
# ----------------------------------------------------------------------


def product_entry(
    product: dict[str, Any], day: date, branch_id: str | None = None
) -> PriceEntry | None:
    """The price of a product on a day: its valid offer (for the branch, if the offer
    names branches), else its fresh regular price (≤ REGULAR_STALE_DAYS old), else None.
    Without a known pack size there is no price per amount (None)."""
    iso = day.isoformat()
    offer = product.get("offer")
    use_offer = _offer_now(offer, iso) and (
        not branch_id or not (offer or {}).get("branch_ids") or branch_id in offer["branch_ids"]
    )
    regular = product.get("regular")
    if use_offer:
        assert offer is not None
        price = float(offer["price"])
        source = "offer"
    elif _regular_fresh(regular, day):
        assert regular is not None
        price = float(regular["price"])
        source = str(regular.get("source") or SOURCE_LEAFLET)
    else:
        return None
    pack = product_pack(product)
    if pack is None and product.get("unit_price") and product.get("base_unit"):
        pack = offer_pack(
            {"price": price, "unit_price": product["unit_price"], "base_unit": product["base_unit"]}
        )
    if pack is None:
        return None
    title = product_title(product)
    offer_view = None
    if use_offer:
        assert offer is not None
        old = _price((regular or {}).get("price"))
        offer_view = {
            "id": offer.get("id"),
            "title": title,
            "product": product.get("name"),
            "store": retailer_name(product["retailer"]),
            "retailer": product["retailer"],
            "price": price,
            "old_price": old if old and old > price else None,
            "valid_from": offer.get("valid_from"),
            "valid_to": offer.get("valid_to"),
            "pack_amount": pack[0],
            "pack_unit": pack[1],
            "source": offer.get("source"),
            "product_id": product["id"],
        }
    return PriceEntry(
        name=title,
        amount=pack[0],
        unit=pack[1],
        price=price,
        source=source,
        store=retailer_name(product["retailer"]),
        offer=offer_view,
        store_id=product["retailer"],
        updated=(regular or {}).get("seen") if not use_offer else None,
    )


def _fits_key(product: dict[str, Any], key: str) -> bool:
    return _fits(
        str(product.get("name") or ""),
        str(product.get("description") or ""),
        product_title(product),
        key,
    )


@lru_cache(maxsize=8192)
def _fits(name: str, description: str, title: str, key: str) -> bool:
    """names_key_product() of a product's name (with its description) or title (cached:
    the shopping list asks it for every product of an ingredient at every store)."""
    return names_key_product(name, key, description) or names_key_product(title, key)


def best_for(
    manager: EssensplanerManager,
    key: str,
    retailer: str,
    amounts: dict[str, float] | None,
    day: date | None = None,
    branch_id: str | None = None,
    category: str | None = None,
    as_packs: bool = True,
) -> dict[str, Any] | None:
    """The cheapest product of a chain for an ingredient: only products of the key's
    product itself (names_key_product), priced on the day; cheapest for the needed amount
    (item_cost), then per g / ml / piece, then an offer first. Returns {product, entry,
    price, packs, unit_price} or None."""
    store = _store_of(manager)
    if store is None or not key:
        return None
    day = day or manager.today()
    memo = store.memo(day)
    candidates = memo.get(("key", key, retailer))
    if candidates is None:
        candidates = memo[("key", key, retailer)] = [
            product for product in store.by_key(key, [retailer]) if _fits_key(product, key)
        ]
    best: tuple[tuple[Any, ...], dict[str, Any]] | None = None
    for product in candidates:
        entry_key = ("entry", product["id"], branch_id)
        if entry_key in memo:
            entry = memo[entry_key]
        else:
            entry = memo[entry_key] = product_entry(product, day, branch_id)
        if entry is None:
            continue
        cost = item_cost(amounts or {}, key, entry, category or product.get("category"), as_packs)
        per = _per_unit(product, entry.price)
        rank = (
            cost is None,
            cost[0] if cost else 0.0,
            per[0] if per else 9e9,
            entry.offer is None,
            entry.price,
            product["id"],
        )
        if best is None or rank < best[0]:
            best = (
                rank,
                {
                    "product": product,
                    "entry": entry,
                    "price": cost[0] if cost else None,
                    "packs": cost[1] if cost else None,
                    "unit_price": per[0] if per else None,
                },
            )
    return best[1] if best else None


def _at_retailer(store: ProductStore, pid: Any, retailer: str) -> dict[str, Any] | None:
    """The product at this chain: itself, or its twin there (a branded product)."""
    product = store.get(pid)
    if product is None:
        return None
    if product["retailer"] == retailer:
        return product
    return next((t for t in store.twins(product["id"]) if t["retailer"] == retailer), None)


def choose_for_item(
    manager: EssensplanerManager,
    item: dict[str, Any],
    retailer: str | None,
    branch_id: str | None = None,
    day: date | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """(product, reason) for a shopping item at a chain: the recipe's product (manual) →
    the ⭐ favourite → a pick (picked ≥ 2× or within PICK_RECENT_DAYS days; picked |
    bought) → the cheapest fitting product (offer | cheapest); (None, None) without one."""
    store = _store_of(manager)
    if store is None or not retailer:
        return None, None
    day = day or manager.today()
    key = str(item.get("key") or ingredient_key(str(item.get("name") or item.get("summary") or "")))
    if not key:
        return None, None
    if item.get("product_id") and (found := _at_retailer(store, item["product_id"], retailer)):
        return found, REASON_MANUAL
    if (fav := store.favorites.get(key)) and (found := _at_retailer(store, fav, retailer)):
        return found, REASON_FAVORITE
    recent = (day - timedelta(days=PICK_RECENT_DAYS)).isoformat()
    for pid, count, last, kind in store.picks.get(key) or []:
        product = store.get(pid)
        if product is None or product["retailer"] != retailer:
            continue
        if int(count) >= 2 or str(last) >= recent:
            return product, kind
    amounts = item.get("amounts") if isinstance(item.get("amounts"), dict) else {}
    best = best_for(
        manager,
        key,
        retailer,
        amounts,
        day,
        branch_id,
        item.get("category"),
        item.get("source") != "plan",
    )
    if best is None:
        return None, None
    return best["product"], REASON_OFFER if best["entry"].offer else REASON_CHEAPEST


# ----------------------------------------------------------------------
# Own products
# ----------------------------------------------------------------------


def save_manual(manager: EssensplanerManager, data: dict[str, Any]) -> dict[str, Any]:
    """Create or change an own product ("＋ Eigener Artikel", service save_product).

    data: {id? (change this product), store | retailer (the chain), name, brand?, pack?
    ("350 g") | pack_amount + pack_unit, price? (regular price), image? (https URL, "" clears
    it), ingredient? | key? (its ingredient), category?, favorite?}. Own products are never
    pruned. Returns the product."""
    store = _store_of(manager)
    if store is None:
        raise _error("not_loaded")
    existing = None
    if data.get("id"):
        existing = require_product(manager, data["id"])
    name = " ".join(str(data.get("name") or (existing or {}).get("name") or "").split())
    if not name:
        raise _error("name_required")
    store_text = str(data.get("store") or data.get("retailer") or "").strip()
    if store_text:
        retailer = store_text if store_text in RETAILERS else manager.require_retailer(store_text)
    elif existing is not None:
        retailer = existing["retailer"]
    else:
        raise _error("store_required")
    if existing is not None and existing["retailer"] != retailer:
        existing = None  # another chain: a new product there
    price = None
    if data.get("price") not in (None, ""):
        price = _price(data["price"])
        if price is None:
            raise _error("invalid_price", price=data["price"])
    pack = None
    if data.get("pack"):
        pack = _valid_pack(parse_pack_text(str(data["pack"])))
    elif data.get("pack_amount") and data.get("pack_unit"):
        pack = _valid_pack((data["pack_amount"], data["pack_unit"]))
    if pack is None and existing is None and not _valid_pack(split_pack(name)[1]):
        pack = (1.0, "Stück")
    image = data.get("image")
    if image not in (None, "") and _image(image) is None:
        raise _error("invalid_url", url=str(image))
    ingredient = str(data.get("ingredient") or data.get("key") or "").strip()
    key = ingredient_key(ingredient) if ingredient else ""
    if not key and not (existing or {}).get("keys"):
        key = ingredient_key(split_pack(name)[0])  # a new product: the ingredient of its name
    product = _upsert(
        store,
        manager.today(),
        retailer=retailer,
        name=name,
        source=SOURCE_USER,
        brand=str(
            data.get("brand")
            if data.get("brand") is not None
            else (existing or {}).get("brand") or ""
        ),
        pack=pack,
        keys=[key] if key else [],
        category=str(data.get("category") or "") or None,
        image=image if image is not None else (existing or {}).get("image"),
        regular=(price, SOURCE_USER) if price is not None else None,
        manual=True,
        own_name=True,
        pid=existing["id"] if existing else None,
    )
    if product is None:
        raise _error("name_required")
    if data.get("favorite") is True:
        set_favorite(manager, product["id"], key or None, True)
    elif data.get("favorite") is False:
        set_favorite(manager, product["id"], None, False)
    store.save_later()
    return product


def delete_product(manager: EssensplanerManager, pid: Any) -> dict[str, Any]:
    """Delete a product (also its ⭐ and picks). Returns the deleted product."""
    store = _store_of(manager)
    product = require_product(manager, pid)
    assert store is not None
    store.remove(product["id"])
    store.save_later()
    return product


def product_to_recipe(
    manager: EssensplanerManager, pid: Any, tags: list[str] | str | None = None
) -> dict[str, Any]:
    """A recipe from a ready meal ("Als Rezept speichern"): one ingredient with the
    product's id, the step "Nach Packungsanleitung zubereiten." and the product's image.
    Returns the recipe."""
    product = require_product(manager, pid)
    pack = product_pack(product)
    ingredient: dict[str, Any] = {
        "name": product["name"],
        "amount": 1,
        "unit": "Pck.",
        "note": pack_text(*pack) if pack else "",
        "product_id": product["id"],
    }
    if pack is not None and pack[1] == "Stück":
        ingredient.update({"amount": pack[0], "unit": "", "note": ""})
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    data = {
        "name": product_title(product),
        "ingredients": [ingredient],
        "steps": [RECIPE_STEP],
        "tags": list(tags) if tags else [RECIPE_TAG],
        "image": product.get("image") or "",
        "notes": f"{product_title(product)} von {retailer_name(product['retailer'])}",
    }
    return manager.add_recipe(data)


# ----------------------------------------------------------------------
# Views (websockets / services)
# ----------------------------------------------------------------------


def _prices(product: dict[str, Any], day: date) -> dict[str, Any]:
    """The prices a card shows on a day: the offer's while it runs (or an announced one
    without a regular price), else the regular price; the regular price as struck price
    of a running offer; per g / ml / piece."""
    iso = day.isoformat()
    offer = product.get("offer") or None
    regular = product.get("regular") or None
    offer_now = _offer_now(offer, iso)
    offer_next = bool(offer and (offer.get("valid_from") or "") > iso)
    regular_price = _price((regular or {}).get("price"))
    price = regular_price
    if offer is not None and (offer_now or (offer_next and regular_price is None)):
        price = _price(offer.get("price"))
    reference = (
        regular_price if offer_now and regular_price and price and regular_price > price else None
    )
    return {
        "price": price,
        "regular_price": regular_price,
        "reference": reference,
        "saving": round(reference - price, 2) if reference and price else None,
        "per": _per_unit(product, price),
        "offer_now": offer_now,
        "offer_next": offer_next,
        "fresh": _regular_fresh(regular, day),
    }


def _branches_of(
    product: dict[str, Any],
    prices: dict[str, Any],
    by_retailer: dict[str, list[tuple[str, str | None]]],
) -> list[str]:
    """The selected branches a product is sold at: every branch of its chain; only the
    branches of its offer's postcodes while nothing but that offer prices it."""
    offer = product.get("offer") or {}
    if (
        prices["offer_now"]
        and not prices["fresh"]
        and (offer.get("zip_codes") or offer.get("branch_ids"))
    ):
        return _branch_ids(
            {
                "retailer": product["retailer"],
                "zip_codes": offer.get("zip_codes"),
                "branch_ids": offer.get("branch_ids"),
            },
            by_retailer,
        )
    return [bid for bid, _ in by_retailer.get(product["retailer"], [])]


def _card(
    manager: EssensplanerManager,
    product: dict[str, Any],
    day: date,
    by_retailer: dict[str, list[tuple[str, str | None]]],
    favorites: dict[str, list[str]],
    bought: set[str],
    prices: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A product like an offer card of the offer catalog (catalog._view) plus its own
    fields."""
    prices = prices or _prices(product, day)
    price, reference, per = prices["price"], prices["reference"], prices["per"]
    regular = product.get("regular") or {}
    pack = product_pack(product)
    shown = (product.get("offer") or {}) if prices["offer_now"] or prices["offer_next"] else {}
    return {
        "id": product["id"],
        "title": product_title(product),
        "product": product["name"],
        "brand": product.get("brand") or "",
        "description": product.get("description") or "",
        "image": product.get("image"),
        "price": price,
        "regular_price": prices["regular_price"],
        "regular_source": regular.get("source"),
        "regular_seen": regular.get("seen"),
        "old_price": reference,
        "stale": not prices["offer_now"] and not prices["fresh"],
        "unit_price": round(per[0], 6) if per else None,
        "base_unit": per[1] if per else None,
        "pack_amount": pack[0] if pack else None,
        "pack_unit": pack[1] if pack else None,
        "pack": pack_text(*pack) if pack else "",
        "on_offer": prices["offer_now"],
        "current": not prices["offer_next"] or prices["regular_price"] is not None,
        "offer_price": _price(shown.get("price")),
        "valid_from": shown.get("valid_from"),
        "valid_to": shown.get("valid_to"),
        "offer_source": shown.get("source"),
        "loyalty": bool(shown.get("loyalty")),
        "loyalty_note": shown.get("loyalty_note"),
        "app_price": shown.get("app_price"),
        "deposit": product.get("deposit"),
        "saving": prices["saving"],
        "discount": round((1 - price / reference) * 100) if reference and price else None,
        "kind": product.get("kind") or KIND_UNKNOWN,
        "category": product.get("category") or "Sonstiges",
        "retailer": product["retailer"],
        "store": retailer_name(product["retailer"]),
        "branch_ids": _branches_of(product, prices, by_retailer),
        "keys": list(product.get("keys") or []),
        "source": (product.get("sources") or [None])[-1],
        "sources": list(product.get("sources") or []),
        "favorite": product["id"] in favorites,
        "favorite_keys": list(favorites.get(product["id"], [])),
        "bought": product["id"] in bought,
        "manual": bool(product.get("manual")),
        "first_seen": product.get("first_seen"),
        "last_seen": product.get("last_seen"),
    }


def _favorites_by_product(store: ProductStore) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for key, pid in store.favorites.items():
        result.setdefault(pid, []).append(key)
    return result


def product_card(manager: EssensplanerManager, product: dict[str, Any]) -> dict[str, Any]:
    """The card of one product (as in products_view)."""
    store = _store_of(manager)
    assert store is not None
    return _card(
        manager,
        product,
        manager.today(),
        _branch_index(manager)[0],
        _favorites_by_product(store),
        store.bought_ids(),
    )


_SORT_KEYS = {
    "price": lambda c: (c["price"] is None, c["price"] or 0, fold(c["title"])),
    "unit_price": lambda c: (
        c["unit_price"] is None,
        c["base_unit"] or "",
        c["unit_price"] or 0,
        c["price"] or 0,
    ),
    "saving": lambda c: (-(c["saving"] or 0), -(c["discount"] or 0), c["price"] or 0),
    "name": lambda c: (fold(c["title"]), c["price"] or 0),
    "recent": lambda c: (_neg_iso(c["last_seen"]), fold(c["title"])),
}


def _sort_fields(product: dict[str, Any], prices: dict[str, Any]) -> dict[str, Any]:
    """The fields of a card the sorting needs (full cards are only built for the page)."""
    price, reference, per = prices["price"], prices["reference"], prices["per"]
    return {
        "price": price,
        "unit_price": per[0] if per else None,
        "base_unit": per[1] if per else None,
        "saving": prices["saving"],
        "discount": round((1 - price / reference) * 100) if reference and price else None,
        "title": product_title(product),
        "last_seen": product.get("last_seen"),
    }


def _neg_iso(value: Any) -> tuple[int, ...]:
    day = _parse_day(value)
    return (-day.toordinal(),) if day else (0,)


def products_view(
    manager: EssensplanerManager,
    query: str | None = None,
    retailers: list[str] | None = None,
    branch_ids: list[str] | None = None,
    category: str | None = None,
    kind: str | None = None,
    only: str | None = None,
    sort: str = "price",
    offset: int = 0,
    limit: int = 60,
) -> dict[str, Any]:
    """The products of the database (websocket essensplaner/products, service
    search_products): filtered by text (brand, name, ingredient), chains or branches,
    aisle, kind (food | drugstore | household | nonfood | all), only (favorites | offers |
    bought | manual) and sorted (price | unit_price | saving | name | recent); offset /
    limit (≤ MAX_VIEW_LIMIT) page the products.

    Result {total, offset, limit, products: [card], stores: [{branch_id, label, retailer,
    store, main, count}], categories: [{name, count}], counts: {products, favorites, offers,
    manual}}. The store and category counts follow the other filters (not their own)."""
    store = _store_of(manager)
    day = manager.today()
    iso = day.isoformat()
    empty = {
        "total": 0,
        "offset": 0,
        "limit": limit,
        "products": [],
        "stores": [],
        "categories": [],
        "counts": product_counts(manager),
    }
    if store is None:
        return empty
    by_retailer, _ = _branch_index(manager)
    favorites = _favorites_by_product(store)
    bought = store.bought_ids()
    texts = store.search_text() if query and query.strip() else {}
    words = fold(query or "").split()
    query_key = ingredient_key(query or "") if words else ""
    wanted_retailers = {r for r in retailers or [] if r}
    wanted_branches = set(branch_ids or [])
    branch_retailers: dict[str, str] = {
        bid: retailer for retailer, items in by_retailer.items() for bid, _ in items
    }
    if wanted_branches:
        wanted_retailers |= {branch_retailers[b] for b in wanted_branches if b in branch_retailers}

    candidates: list[dict[str, Any]] = []
    for pid, product in store.products.items():
        if kind and kind != "all" and not kind_matches(product, kind):
            continue
        if only == ONLY_FAVORITES and pid not in favorites:
            continue
        if only == ONLY_OFFERS and not _offer_now(product.get("offer"), iso):
            continue
        if only == ONLY_BOUGHT and pid not in bought:
            continue
        if only == ONLY_MANUAL and not product.get("manual"):
            continue
        if words:
            text = texts.get(pid, "")
            if not all(w in text for w in words) and query_key not in (product.get("keys") or []):
                continue
        candidates.append(product)

    store_counts: dict[str, int] = {}
    retailer_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    selected: list[dict[str, Any]] = []
    for product in candidates:
        retailer = product["retailer"]
        retailer_counts[retailer] = retailer_counts.get(retailer, 0) + 1
        in_store = not wanted_retailers or retailer in wanted_retailers
        if in_store:
            name = product.get("category") or "Sonstiges"
            category_counts[name] = category_counts.get(name, 0) + 1
        if not in_store or (category and (product.get("category") or "Sonstiges") != category):
            continue
        selected.append(product)
    for retailer, items in by_retailer.items():
        for bid, _ in items:
            store_counts[bid] = retailer_counts.get(retailer, 0)

    rows: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for product in selected:
        prices = _prices(product, day)
        if wanted_branches:
            branches = _branches_of(product, prices, by_retailer)
            if branches and not wanted_branches & set(branches):
                continue
        rows.append((product, prices, _sort_fields(product, prices)))
    order = _SORT_KEYS.get(sort, _SORT_KEYS["price"])
    rows.sort(key=lambda row: order(row[2]))
    limit = max(1, min(int(limit), MAX_VIEW_LIMIT))
    offset = max(0, int(offset))
    cards = [
        _card(manager, product, day, by_retailer, favorites, bought, prices)
        for product, prices, _ in rows[offset : offset + limit]
    ]
    stores: list[dict[str, Any]] = []
    listed: set[str] = set()
    for branch in manager.selected_branches():
        if not branch.get("retailer") or not branch.get("id"):
            continue
        listed.add(branch["retailer"])
        stores.append(
            {
                "branch_id": branch["id"],
                "label": manager.branch_label(branch),
                "retailer": branch["retailer"],
                "store": retailer_name(branch["retailer"]),
                "main": branch["id"] == manager.main_branch,
                "count": store_counts.get(branch["id"], 0),
            }
        )
    for retailer in sorted(retailer_counts):
        if retailer not in listed:
            stores.append(
                {
                    "branch_id": None,
                    "label": retailer_name(retailer),
                    "retailer": retailer,
                    "store": retailer_name(retailer),
                    "main": False,
                    "count": retailer_counts[retailer],
                }
            )
    return {
        "total": len(rows),
        "offset": offset,
        "limit": limit,
        "products": cards,
        "stores": stores,
        "categories": [
            {"name": name, "count": count}
            for name, count in sorted(category_counts.items(), key=lambda c: category_rank(c[0]))
        ],
        "counts": product_counts(manager),
    }


def _key_name(manager: EssensplanerManager, key: str) -> str:
    entry = manager.defaults_index().get(key)
    return entry.name if entry is not None else key[:1].upper() + key[1:]


def product_detail(manager: EssensplanerManager, pid: Any) -> dict[str, Any]:
    """One product (websocket product_detail): {product: card, history: [{date, price,
    kind: regular | offer}], twins: [card] (the same branded product at other chains),
    keys: [{key, name}], favorite_for: [key], picks: [{key, count, last, kind}]}."""
    store = _store_of(manager)
    product = require_product(manager, pid)
    assert store is not None
    card = product_card(manager, product)
    twins = [product_card(manager, twin) for twin in store.twins(product["id"])]
    twins.sort(key=_SORT_KEYS["price"])
    picks = [
        {"key": key, "count": entry[1], "last": entry[2], "kind": entry[3]}
        for key, entries in store.picks.items()
        for entry in entries
        if entry[0] == product["id"]
    ]
    return {
        "product": card,
        "history": [
            {"date": h[0], "price": h[1], "kind": "offer" if h[2] == "o" else "regular"}
            for h in product.get("history") or []
        ],
        "twins": twins,
        "keys": [
            {"key": key, "name": _key_name(manager, key)} for key in product.get("keys") or []
        ],
        "favorite_for": card["favorite_keys"],
        "picks": picks,
    }


def product_alternatives(
    manager: EssensplanerManager,
    key: str | None = None,
    uid: str | None = None,
    product_id: str | None = None,
    limit: int = ALTERNATIVES_LIMIT,
) -> dict[str, Any]:
    """Products to buy for an ingredient at every saved chain ("Produkt wechseln"): of a
    shopping item (uid: its amount), a product (its first ingredient) or an ingredient
    (key or name). Sorted by the cost for the needed amount (one pack without an amount),
    then per g / ml / piece. Result {key, name, item_uid, amounts, current (product id),
    favorite (⭐ product id), alternatives: [card + {cost, packs, needed}]}."""
    store = _store_of(manager)
    day = manager.today()
    item: dict[str, Any] | None = None
    current: str | None = None
    amounts: dict[str, float] = {}
    as_packs = True
    category: str | None = None
    if uid:
        item = next((i for i in manager.shopping if i.get("uid") == uid), None)
        if item is None:
            raise _error("shopping_item_not_found")
        key = str(item.get("key") or "")
        amounts = dict(manager._item_amounts(item))
        as_packs = item.get("source") != "plan"
        category = item.get("category")
        current = product_for_item(manager, item)
        name = manager._item_name(item)
    elif product_id:
        product = require_product(manager, product_id)
        current = product["id"]
        key = str((product.get("keys") or [ingredient_key(split_pack(product["name"])[0])])[0])
        name = _key_name(manager, key)
    else:
        text = str(key or "").strip()
        key = text if store is not None and text in store._by_key else ingredient_key(text)
        name = _key_name(manager, key) if key else text
    result: dict[str, Any] = {
        "key": key,
        "name": name,
        "item_uid": item.get("uid") if item else None,
        "amounts": amounts,
        "current": current,
        "favorite": store.favorites.get(key or "") if store is not None else None,
        "alternatives": [],
    }
    if store is None or not key:
        return result
    retailers = set(manager.active_retailers()) or set(store.retailers())
    if current and (product := store.get(current)) is not None:
        retailers.add(product["retailer"])
    favorites = _favorites_by_product(store)
    bought = store.bought_ids()
    by_retailer, _ = _branch_index(manager)
    found: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    for product in store.by_key(key, retailers):
        if not _fits_key(product, key) and product["id"] != current:
            continue
        entry = product_entry(product, day)
        cost = (
            item_cost(amounts, key, entry, category or product.get("category"), as_packs)
            if entry is not None
            else None
        )
        card = _card(manager, product, day, by_retailer, favorites, bought)
        card.update(
            {
                "cost": cost[0] if cost else None,
                "packs": cost[1] if cost else None,
                "needed": bool(amounts),
                "cost_text": format_eur(cost[0]) if cost else None,
            }
        )
        found.append(
            (
                (
                    cost is None,
                    cost[0] if cost else 0.0,
                    card["unit_price"] if card["unit_price"] is not None else 9e9,
                    not card["on_offer"],
                    card["title"],
                ),
                card,
            )
        )
    found.sort(key=lambda f: f[0])
    result["alternatives"] = [card for _, card in found[: max(1, int(limit))]]
    return result


def product_counts(manager: EssensplanerManager) -> dict[str, Any]:
    """Counts for the panel's data (no products): {products, favorites, offers, manual,
    bought, retailers: {retailer: count}, seeded}."""
    store = _store_of(manager)
    if store is None:
        return {
            "products": 0,
            "favorites": 0,
            "offers": 0,
            "manual": 0,
            "bought": 0,
            "seeded": False,
        }
    iso = manager.today().isoformat()
    return {
        "products": len(store.products),
        "favorites": len(store.favorite_ids()),
        "offers": sum(1 for p in store.products.values() if _offer_now(p.get("offer"), iso)),
        "manual": sum(1 for p in store.products.values() if p.get("manual")),
        "bought": len(store.bought_ids() & set(store.products)),
        "retailers": {r: len(store._by_retailer.get(r) or ()) for r in store.retailers()},
        "seeded": bool(store.data.get("seeded")),
    }
