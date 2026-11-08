"""Article search for the "Artikel hinzufügen" field (mixin for the manager).

Local results (instant, no network): the store's price list (own and learned store prices),
own general prices, the bundled estimates (names and aliases), valid offers of the store's
retailer and recently added articles (article_history). The default store is the main
branch; without one the general prices are searched.

Optional live results (async_search_articles_live): providers per retailer can be
registered in LIVE_PROVIDERS with an optional "enabled" check (the experimental REWE
online shop for "rewe" and ALDI SÜD for "aldi-sued", only asked while their option is on); the
marktguru offer search for the branch postcode is used for every retailer when the user
enabled marktguru (offers_source). Live requests are throttled (LIVE_MIN_INTERVAL, newest
query wins) and cached in memory for an hour per (query, postcode / market), see
cached_live_fetch().

1.5 – search across all saved stores (scope "all", the panel's "Artikel hinzufügen"): the
products of the product database of every selected chain, own offers, the stores' own and
learned prices where the product database knows no product of that ingredient there,
recently added articles and, last, the estimates (no store). The article itself ranks before
other products ("Butter" before "Butterkekse"); within that, the comparable price (per kg /
l, per piece separately), the pack price and offers decide – cheapest first. Live providers
of every enabled chain and marktguru are asked in parallel (one lock and one request per
second per provider host). Scope "main" (voice, services) is the 1.4 search of one store.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
import logging
import re
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from .const import OFFERS_MARKTGURU
from .economy import _offer_short
from .ingredients import fold, ingredient_key, parse_ingredient
from .offers import (
    MarktguruClient,
    OfferBlocked,
    OfferError,
    normalize_marktguru,
    offer_matches,
    parse_pack_text as parse_pack_text,  # moved to offers.py (re-exported)
    store_allowed,
)
from .pricing import (
    PriceEntry,
    format_eur,
    make_entry,
    offer_as_entry,
    offer_pack,
    offer_valid_on,
    pack_text,
    unit_price,
)
from .retailers import retailer_for_store_id, retailer_name
from .stores import valid_postcode

if TYPE_CHECKING:
    from .manager import EssensplanerManager

_LOGGER = logging.getLogger(__name__)

ARTICLE_HISTORY_MAX = 200
# live search: cache lifetime, minimum seconds between requests, minimum query length
LIVE_CACHE_SECONDS = 3600
LIVE_MIN_INTERVAL = 1.0
LIVE_MIN_QUERY = 3
LIVE_CACHE_MAX = 100
LIVE_RESULTS = 40

# match quality (lower = better)
MATCH_EXACT = 0
MATCH_PREFIX = 1
MATCH_WORD = 2
MATCH_SUBSTRING = 3
# result order within the same match quality
SOURCE_RANK = {
    "offer": 0,
    "product": 0,
    "store": 1,
    "learned": 2,
    "history": 3,
    "default": 4,
    "live": 5,
}
_LEARNED = {"leaflet", "rewe_online", "aldi_online", "offer_regular"}

# 1.5: which stores are searched – the main store (or the given one) or every saved store
SCOPE_MAIN = "main"
SCOPE_ALL = "all"
SCOPES = (SCOPE_MAIN, SCOPE_ALL)
MAIN_LIMIT = 10  # default number of hits (scope main)
ALL_LIMIT = 20  # default number of hits (scope all)
MAX_LIMIT = 50
# match tiers of scope "all" (lower = better): the article itself (or an exact / prefix
# match), another product with the word, a substring
TIER_ARTICLE = 0
TIER_WORD = 1
TIER_OTHER = 2
# the provider host of a live source (one lock and one request per interval each)
HOST_MARKTGURU = "marktguru"

# async provider(manager, query, branch or None, retailer or None) -> [offer dicts]
# (normalized like normalize_marktguru(); may raise OfferError)
LiveProvider = Callable[
    ["EssensplanerManager", str, dict[str, Any] | None, str | None],
    Awaitable[list[dict[str, Any]]],
]
LIVE_PROVIDERS: dict[str, LiveProvider] = {}
# sequence number of the live search running in this task (all its providers share it)
_SEARCH_SEQUENCE: ContextVar[int | None] = ContextVar("essensplaner_live_search", default=None)
# optional check per retailer: the provider is only asked while it returns True
LiveProviderCheck = Callable[["EssensplanerManager"], bool]
LIVE_PROVIDER_CHECKS: dict[str, LiveProviderCheck] = {}


def register_live_provider(
    retailer: str, provider: LiveProvider, enabled: LiveProviderCheck | None = None
) -> None:
    """Add a live article source for one retailer (e.g. the REWE online shop).

    enabled(manager) -> bool: the provider is only asked (and the search only counts as
    live) while it returns True, e.g. while an opt-in option is on.
    """
    LIVE_PROVIDERS[retailer] = provider
    if enabled is None:
        LIVE_PROVIDER_CHECKS.pop(retailer, None)
    else:
        LIVE_PROVIDER_CHECKS[retailer] = enabled


def live_provider_for(manager: EssensplanerManager, retailer: str | None) -> LiveProvider | None:
    """The enabled live provider of a retailer (None if there is none or it is off)."""
    provider = LIVE_PROVIDERS.get(retailer or "")
    if provider is None:
        return None
    check = LIVE_PROVIDER_CHECKS.get(retailer or "")
    return provider if check is None or check(manager) else None


def _match(query: str, key: str, names: list[str]) -> int | None:
    """Best match quality of a query (folded) against names (None = no match)."""
    best: int | None = None
    for name in names:
        folded = fold(name or "")
        if not folded:
            continue
        if folded == query or (key and ingredient_key(name) == key):
            rank = MATCH_EXACT
        elif folded.startswith(query):
            rank = MATCH_PREFIX
        elif any(word.startswith(query) for word in re.split(r"[\s\-/]+", folded)):
            rank = MATCH_WORD
        elif query in folded:
            rank = MATCH_SUBSTRING
        else:
            continue
        best = rank if best is None else min(best, rank)
    return best


def _source_of(entry: PriceEntry) -> str:
    if entry.source == "default":
        return "default"
    if entry.source in _LEARNED:
        return "learned"
    return "store"


def _base_group(base: str | None) -> str | None:
    """Comparable unit prices: per g and per ml together, per piece (and others) alone."""
    if base in ("g", "ml"):
        return "g"
    return base or None


def all_sort_key(result: dict[str, Any], dominant: dict[int, str | None]) -> tuple[Any, ...]:
    """Order of scope "all": the match tier (the article itself first), real prices before
    estimates, then the comparable price (the tier's most common unit first: per kg / l or
    per piece), the pack price and offers first."""
    tier = result.get("tier", TIER_OTHER)
    group = _base_group(result.get("base")) if not result.get("stale") else None
    per = result.get("unit_price") if group is not None else None
    bucket = 2 if per is None else 0 if group == dominant.get(tier) else 1
    return (
        tier,
        result.get("source") == "default",
        result.get("price") is None,
        bucket,
        group or "",
        per if per is not None else 0.0,
        result.get("price") or 0.0,
        not result.get("offer"),
        -(result.get("count") or 0),
        fold(result.get("title") or ""),
        result.get("retailer") or "",
    )


def dominant_bases(results: list[dict[str, Any]]) -> dict[int, str | None]:
    """{tier: the most common comparable unit of its priced hits} (all_sort_key())."""
    counts: dict[int, dict[str, int]] = {}
    for result in results:
        group = _base_group(result.get("base"))
        if group is None or result.get("unit_price") is None or result.get("stale"):
            continue
        tier = counts.setdefault(result.get("tier", TIER_OTHER), {})
        tier[group] = tier.get(group, 0) + 1
    return {tier: max(sorted(groups), key=lambda g: groups[g]) for tier, groups in counts.items()}


def sort_all(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Hits of scope "all" in their order (see all_sort_key())."""
    dominant = dominant_bases(results)
    return sorted(results, key=lambda r: all_sort_key(r, dominant))


def _sort_key(result: dict[str, Any]) -> tuple[Any, ...]:
    """Offers and exact/prefix matches first."""
    offer = result["source"] in ("offer", "live")
    match = result["match"]
    tier = 0 if (offer and match <= MATCH_WORD) or match <= MATCH_PREFIX else 1
    return (
        tier,
        not offer,
        match,
        SOURCE_RANK.get(result["source"], 9),
        -(result.get("count") or 0),
        len(result["title"]),
        fold(result["title"]),
    )


class ArticlesMixin:
    """Mixed into EssensplanerManager (before StoresMixin)."""

    _live_cache: dict[tuple[str, str], tuple[float, list[dict[str, Any]]]]
    _live_last: dict[str, float]
    _live_seq: int
    _live_locks: dict[str, asyncio.Lock]
    _live_client: MarktguruClient | None
    _default_names: tuple[int, list[tuple[PriceEntry, list[str]]]] | None

    def _init_article_data(self: EssensplanerManager) -> None:
        """Empty caches (called from the manager's __init__)."""
        self._live_cache = {}
        self._live_last = {}  # provider host -> time of its last request
        self._live_seq = 0
        self._live_locks = {}  # provider host -> lock (one request at a time per host)
        self._live_client = None
        self._default_names = None

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def remember_article(
        self: EssensplanerManager, summary: str, key: str | None, retailer: str | None
    ) -> None:
        """Remember an added article (most recent first, max ARTICLE_HISTORY_MAX)."""
        summary = str(summary or "").strip()
        if not summary:
            return
        ident = key or fold(summary)
        existing = next(
            (
                a
                for a in self.article_history
                if (a.get("key") or fold(str(a.get("summary") or ""))) == ident
            ),
            None,
        )
        count = 1
        if existing is not None:
            count = int(existing.get("count") or 0) + 1
            self.article_history.remove(existing)
        self.article_history.insert(
            0,
            {
                "summary": summary,
                "key": key or "",
                "retailer": retailer,
                "count": count,
                "last": dt_util.utcnow().isoformat(),
            },
        )
        del self.article_history[ARTICLE_HISTORY_MAX:]

    # ------------------------------------------------------------------
    # Local search
    # ------------------------------------------------------------------

    def article_target(
        self: EssensplanerManager, store: str | None = None
    ) -> tuple[dict[str, Any] | None, str | None]:
        """(branch, retailer) searched: the given store, else the main branch, else none."""
        if store:
            branch = self.resolve_branch(store)
            if branch is not None and branch.get("retailer"):
                return branch, branch["retailer"]
            return None, self.require_retailer(store)
        main = self.get_main_branch()
        if main is not None and main.get("retailer"):
            return main, main["retailer"]
        return None, None

    def article_store_info(
        self: EssensplanerManager, branch: dict[str, Any] | None, retailer: str | None
    ) -> dict[str, Any] | None:
        """Short description of the searched store (None = general prices)."""
        if retailer is None:
            return None
        return {
            "branch_id": branch.get("id") if branch else None,
            "retailer": retailer,
            "retailer_name": retailer_name(retailer),
            "label": self.branch_label(branch) if branch else retailer_name(retailer),
            "postcode": (branch or {}).get("postcode") or None,
            "main": bool(branch) and branch.get("id") == self.main_branch,
        }

    def _default_name_list(self: EssensplanerManager) -> list[tuple[PriceEntry, list[str]]]:
        """Bundled estimates with their names (name first, then aliases)."""
        source = id(self.default_prices)
        if self._default_names is None or self._default_names[0] != source:
            entries = [
                (entry, [entry.name, *entry.aliases]) for entry in self.defaults_index().entries()
            ]
            self._default_names = (source, entries)
        return self._default_names[1]

    def _result(
        self: EssensplanerManager,
        title: str,
        entry: PriceEntry | None,
        source: str,
        match: int,
        retailer: str | None,
        branch_id: str | None,
        key: str | None = None,
        offer: dict[str, Any] | None = None,
        count: int = 0,
    ) -> dict[str, Any]:
        per = unit_price(entry) if entry else None
        regular = (
            round(entry.price, 2)
            if entry is not None and entry.offer is None and entry.real
            else None
        )
        return {
            "title": title,
            "key": key or ingredient_key(parse_ingredient(title)["name"] or title),
            "pack": (pack_text(entry.amount, entry.unit) or None) if entry else None,
            "amount": entry.amount if entry else None,
            "unit": entry.unit if entry else None,
            "price": round(entry.price, 2) if entry else None,
            "unit_price": round(per[0], 5) if per else None,
            "base": per[1] if per else None,
            "retailer": retailer or (entry.store_id if entry else None),
            "branch_id": branch_id,
            "source": source,
            "real": bool(entry and entry.real),
            "offer": offer,
            "count": count,
            "match": match,
            # 1.5: the product (product database) and the store of the hit
            "image": None,
            "brand": "",
            "product_id": None,
            "store_label": None,
            "regular_price": regular,
        }

    def _hit_label(
        self: EssensplanerManager, retailer: str | None, branch_id: str | None
    ) -> str | None:
        """The store of a hit: the branch's label, else the chain's name (None: no store)."""
        branch = self.get_branch(branch_id) if branch_id else None
        if branch is not None:
            return self.branch_label(branch)
        return retailer_name(retailer) if retailer else None

    def _decorate(self: EssensplanerManager, results: list[dict[str, Any]]) -> None:
        """Store label, product (image, brand, id) and regular price of hits (1.5)."""
        from .products import _store_of, product_for_hit

        store = _store_of(self)
        for result in results:
            if not result.get("store_label"):
                result["store_label"] = self._hit_label(result["retailer"], result["branch_id"])
            offer = result.get("offer") or {}
            if store is None or result.get("product_id"):
                continue
            product = (
                product_for_hit(self, offer, result["retailer"])
                if offer.get("id") or result["source"] == "live"
                else None
            )
            if product is None:
                continue
            result["product_id"] = product["id"]
            result["brand"] = result.get("brand") or product.get("brand") or ""
            result["image"] = result.get("image") or product.get("image")
            if result.get("regular_price") is None:
                regular = (product.get("regular") or {}).get("price")
                if regular is not None and regular > (result.get("price") or 0):
                    result["regular_price"] = regular

    def _offer_result(
        self: EssensplanerManager,
        offer: dict[str, Any],
        source: str,
        match: int,
        retailer: str | None,
        branch_id: str | None,
    ) -> dict[str, Any]:
        """Search result for an offer (pack only if known)."""
        result = self._result(
            offer.get("title") or offer.get("product") or "",
            offer_as_entry(offer),
            source,
            match,
            retailer,
            branch_id,
            ingredient_key(offer.get("product") or offer.get("title") or ""),
            _offer_short(offer),
        )
        result["real"] = True
        if result["price"] is None and offer.get("price") is not None:
            result["price"] = round(float(offer["price"]), 2)
        if offer_pack(offer) is None:
            result.update({"pack": None, "amount": None, "unit": None})
        image = str(offer.get("image") or "")
        result["image"] = image if image.startswith("https://") else None
        result["brand"] = str(offer.get("brand") or "")
        result["regular_price"] = _regular_of(offer)
        return result

    def search_articles(
        self: EssensplanerManager,
        query: str,
        store: str | None = None,
        limit: int | None = None,
        scope: str = SCOPE_MAIN,
    ) -> list[dict[str, Any]]:
        """Articles matching a query (local data only, fast).

        scope "main" (default; voice, services): the given store, else the main branch –
        offers and exact/prefix matches first, one per key + pack (1.4). scope "all" (the
        panel): every selected store (only the given store's chain with store), cheapest
        first within the match tier, see _search_all(). limit default MAIN_LIMIT /
        ALL_LIMIT.

        Result [{title, key, pack, amount, unit, price, unit_price, base, retailer,
        branch_id, store_label, source (product|offer|store|learned|history|default), real,
        offer (incl. valid_to), regular_price, image, brand, product_id, count, match,
        tier (scope all), stale (scope all)}].
        """
        if scope == SCOPE_ALL:
            return self._search_all(query, store, ALL_LIMIT if limit is None else limit)
        branch, retailer = self.article_target(store)
        results = self._search_local(
            query, branch, retailer, MAIN_LIMIT if limit is None else limit
        )
        self._decorate(results)
        return results

    def _all_targets(
        self: EssensplanerManager, store: str | None = None
    ) -> dict[str, dict[str, Any] | None]:
        """{retailer: its first selected branch | None} searched by scope "all": the selected
        chains (main first; without branches the offer_stores option), or only the given
        store's chain."""
        if store:
            branch, retailer = self.article_target(store)
            return {retailer: branch} if retailer else {}
        targets: dict[str, dict[str, Any] | None] = {}
        for branch in self.selected_branches():
            retailer = branch.get("retailer")
            if retailer and branch.get("id") and retailer not in targets:
                targets[retailer] = branch
        for retailer in self.active_retailers():
            targets.setdefault(retailer, None)
        return targets

    def _names_article(self: EssensplanerManager, query: str, key: str) -> bool:
        """True if the query names an article ("Butter"): its hits that are other products
        ("Butterkekse", "Erdnussbutter") rank after the article itself."""
        if not key:
            return False
        defaults = self.defaults_index()
        if defaults.get(key) is not None or defaults.exact(str(query)) is not None:
            return True
        from .products import _store_of

        store = _store_of(self)
        return store is not None and key in store._by_key

    def _tier(self: EssensplanerManager, title: str, match: int, key: str, article: bool) -> int:
        """Match tier of a hit (scope all): the article itself (or an exact / prefix match of
        a query that names no article), another product with the word, a substring."""
        if article:
            if self._is_article(title, key):
                return TIER_ARTICLE
            return TIER_WORD if match <= MATCH_WORD else TIER_OTHER
        if match <= MATCH_PREFIX:
            return TIER_ARTICLE
        return TIER_WORD if match == MATCH_WORD else TIER_OTHER

    def _search_all(
        self: EssensplanerManager, query: str, store: str | None = None, limit: int = ALL_LIMIT
    ) -> list[dict[str, Any]]:
        """Scope "all": the hits of every selected store, see search_articles().

        1. the product database (every product of the chains that can be bought today: a
           running offer or a known regular price; its offer's branches),
        2. own offers (typed from a leaflet; offers the product database does not know),
        3. the stores' own prices (always) and learned / receipt prices (only where the
           product database knows no product of that ingredient at that chain),
        4. own general prices (no store), recently added articles,
        5. the estimates ("Richtwert", no store) only for ingredients without a real hit.
        One hit per chain + product + pack.
        """
        from .catalog import _branch_index
        from .products import _branches_of, _store_of, product_title, search_hits

        folded = fold(str(query or "")).strip()
        if not folded:
            return []
        key = ingredient_key(str(query))
        article = self._names_article(str(query), key)
        today = self.today()
        targets = self._all_targets(store)
        retailers = list(targets)
        db = _store_of(self)
        by_retailer = _branch_index(self)[0]
        order = {b["id"]: n for n, b in enumerate(self.selected_branches()) if b.get("id")}
        found: list[dict[str, Any]] = []

        def add(result: dict[str, Any], title: str) -> None:
            result["tier"] = self._tier(title, result["match"], key, article)
            result.setdefault("stale", False)
            if not result.get("store_label"):
                result["store_label"] = self._hit_label(result["retailer"], result["branch_id"])
            found.append(result)

        def first_branch(retailer: str, branch_ids: list[str] | None) -> str | None:
            if branch_ids is not None:
                ordered = sorted((b for b in branch_ids if b in order), key=lambda b: order[b])
                if ordered:
                    return ordered[0]
            branch = targets.get(retailer)
            return branch.get("id") if branch else None

        # 1. the product database
        for product, prices in search_hits(self, folded, retailers, today):
            title = product_title(product)
            match = _match(folded, key, [title, str(product.get("name") or "")])
            if match is None:
                if (key and key in (product.get("keys") or [])) or folded in fold(
                    str(product.get("brand") or "")
                ):
                    match = MATCH_WORD
                else:
                    continue  # only its description names the query
            retailer = product["retailer"]
            branch_ids = _branches_of(product, prices, by_retailer)
            if by_retailer.get(retailer) and not branch_ids:
                continue  # an offer of a postcode none of the saved branches has
            add(
                self._product_hit(product, prices, match, key, first_branch(retailer, branch_ids)),
                title,
            )

        # 2. own offers (the product database has the catalog's and the shops' offers)
        active = self.active_retailers()
        for offer in self.offers:
            if not offer_valid_on(offer, today, 0) or offer.get("online_only"):
                continue
            retailer = self.offer_retailer(offer)
            if retailer not in targets or not self._offer_in_scope(offer, None, active):
                continue
            known = db.by_offer(offer.get("id")) if db is not None else None
            if known is not None and known["retailer"] in targets:
                continue  # a product of the product database (listed above)
            match = _match(folded, key, [offer.get("title") or "", offer.get("product") or ""])
            if key and key in (offer.get("keys") or []):
                match = MATCH_EXACT if match is None else min(match, MATCH_EXACT)
            if match is None:
                continue
            branches = offer.get("branches") if "branches" in offer else None
            if branches is not None and order and not any(b in order for b in branches):
                continue  # found for another postcode
            result = self._offer_result(
                offer, "offer", match, retailer, first_branch(retailer, branches)
            )
            add(result, str(offer.get("product") or offer.get("title") or ""))

        # 3. the stores' own and learned prices
        for retailer in retailers:
            branch = targets[retailer]
            branch_id = branch.get("id") if branch else None
            lists: list[tuple[dict[str, Any], str | None]] = [
                (self.store_prices_user.get(retailer, {}), None)
            ]
            lists.extend(
                (items, source) for source, items in self.fresh_store_prices(retailer).items()
            )
            for items, learned_source in lists:
                for item_key, item in items.items():
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or item_key)
                    match = _match(folded, key, [name])
                    if match is None:
                        continue
                    source = learned_source or str(item.get("source") or "user")
                    if source != "user" and db is not None and db.by_key(item_key, [retailer]):
                        continue  # the product database knows the products there
                    entry = make_entry(item, source, retailer)
                    if entry is None:
                        continue
                    result = self._result(
                        name,
                        entry,
                        "learned" if learned_source else "store",
                        match,
                        retailer,
                        branch_id,
                        item_key,
                    )
                    add(result, name)

        # 4. own general prices (no store) and recently added articles
        general = self._general_for(self.prices_user, None)
        for item_key, item in general.items():
            if not isinstance(item, dict) or item.get("store") or item.get("retailer"):
                continue
            name = str(item.get("name") or item_key)
            match = _match(folded, key, [name])
            entry = make_entry(item, "user") if match is not None else None
            if entry is not None and match is not None:
                add(self._result(name, entry, "store", match, None, None, item_key), name)
        for recent in self.article_history:
            summary = str(recent.get("summary") or "")
            match = _match(folded, key, [summary])
            if match is None:
                continue
            retailer = recent.get("retailer") if recent.get("retailer") in targets else None
            entry = self.regular_book(retailer).lookup(parse_ingredient(summary)["name"] or summary)
            # a price of a store names it (else the general price or the estimate)
            used = entry.store_id if entry is not None and entry.store_id in targets else None
            branch = targets.get(used) if used else None
            result = self._result(
                summary,
                entry,
                "history",
                match,
                used,
                branch.get("id") if branch else None,
                recent.get("key") or None,
                count=int(recent.get("count") or 0),
            )
            result["retailer"] = used
            add(result, summary)

        # 5. estimates (no store) for ingredients without a real hit
        real_keys = {r["key"] for r in found if r["real"] and r["price"] is not None}
        for entry, default_names in self._default_name_list():
            best: tuple[int, str] | None = None
            for name in default_names:
                match = _match(folded, key, [name])
                if match is not None and (best is None or match < best[0]):
                    best = (match, name)
            if best is None:
                continue
            result = self._result(best[1], entry, "default", best[0], None, None)
            if result["key"] in real_keys or ingredient_key(entry.name) in real_keys:
                continue
            add(result, best[1])

        self._decorate(found)
        result_list: list[dict[str, Any]] = []
        seen: set[tuple[Any, ...]] = set()
        for item in sort_all(found):
            ident = (
                item["retailer"],
                item.get("product_id")
                or (item["key"] if item["source"] != "history" else fold(item["title"])),
                item["pack"],
            )
            if ident in seen:
                continue
            seen.add(ident)
            result_list.append(item)
            if len(result_list) >= max(1, int(limit)):
                break
        return result_list

    def _product_hit(
        self: EssensplanerManager,
        product: dict[str, Any],
        prices: dict[str, Any],
        match: int,
        key: str,
        branch_id: str | None,
    ) -> dict[str, Any]:
        """A search hit of the product database (scope all)."""
        from .products import product_pack, product_title

        title = product_title(product)
        pack = product_pack(product)
        per = prices["per"]
        offer = product.get("offer") or {}
        price = prices["price"]
        retailer = product["retailer"]
        keys = list(product.get("keys") or [])
        hit_key = key if key in keys else (keys[0] if keys else ingredient_key(product["name"]))
        short = None
        if prices["offer_now"]:
            store = retailer_name(retailer)
            short = {
                "id": offer.get("id"),
                "title": title,
                "store": store,
                "price": price,
                "old_price": prices["reference"],
                "valid_from": offer.get("valid_from"),
                "valid_to": offer.get("valid_to"),
                "text": f"{store} {format_eur(price)}",
                "source": offer.get("source"),
                "product_id": product["id"],
            }
        return {
            "title": title,
            "key": hit_key,
            "pack": pack_text(*pack) if pack else None,
            "amount": pack[0] if pack else None,
            "unit": pack[1] if pack else None,
            "price": round(price, 2) if price is not None else None,
            "unit_price": round(per[0], 5) if per else None,
            "base": per[1] if per else None,
            "retailer": retailer,
            "branch_id": branch_id,
            "store_label": self._hit_label(retailer, branch_id),
            "source": "product",
            "real": True,
            "offer": short,
            "count": 0,
            "match": match,
            "image": product.get("image"),
            "brand": product.get("brand") or "",
            "product_id": product["id"],
            "regular_price": prices["regular_price"],
            "stale": not prices["offer_now"] and not prices["fresh"],
        }

    def _search_local(
        self: EssensplanerManager,
        query: str,
        branch: dict[str, Any] | None,
        retailer: str | None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        folded = fold(str(query or "")).strip()
        if not folded:
            return []
        key = ingredient_key(str(query))
        branch_id = branch.get("id") if branch else None
        book = self.store_book(retailer) if retailer else self.regular_book()
        today = self.today()
        found: list[dict[str, Any]] = []

        # valid offers of the store's retailer (without store: all selected stores)
        active = self.active_retailers()
        for offer in self.offers:
            if retailer is not None:
                if self.offer_retailer(offer) != retailer:
                    continue
                if branch_id and "branches" in offer and branch_id not in offer["branches"]:
                    continue
            elif not self._offer_in_scope(offer, None, active):
                continue
            if not offer_valid_on(offer, today, 0):
                continue
            match = _match(folded, key, [offer.get("title") or "", offer.get("product") or ""])
            if key and key in (offer.get("keys") or []):
                match = MATCH_EXACT  # an offer for exactly this article ("Deutsche Markenbutter")
            if match is None:
                continue
            found.append(
                self._offer_result(
                    offer,
                    "offer",
                    match,
                    retailer or self.offer_retailer(offer),
                    branch_id if retailer else None,
                )
            )

        # price lists: store prices, own/learned general prices, estimates
        names: list[tuple[str, int]] = []
        if retailer is not None:
            for items in (
                self.store_prices_user.get(retailer, {}),
                *self.fresh_store_prices(retailer).values(),
            ):
                names.extend(
                    (str(item.get("name") or k), m)
                    for k, item in items.items()
                    if (m := _match(folded, key, [str(item.get("name") or k)])) is not None
                )
        for items in (
            self._general_for(self.prices_user, retailer),
            self._general_for(self.prices_learned, retailer),
        ):
            names.extend(
                (str(item.get("name") or k), m)
                for k, item in items.items()
                if isinstance(item, dict)
                and (m := _match(folded, key, [str(item.get("name") or k)])) is not None
            )
        for _entry, default_names in self._default_name_list():
            best: tuple[int, str] | None = None
            for name in default_names:
                match = _match(folded, key, [name])
                if match is not None and (best is None or match < best[0]):
                    best = (match, name)
            if best is not None:
                names.append((best[1], best[0]))
        for name, match in names:
            entry = book.lookup(name)
            if entry is not None:
                found.append(
                    self._result(name, entry, _source_of(entry), match, retailer, branch_id)
                )

        # recently added articles
        for article in self.article_history:
            summary = str(article.get("summary") or "")
            match = _match(folded, key, [summary])
            if match is None:
                continue
            entry = book.lookup(parse_ingredient(summary)["name"] or summary)
            found.append(
                self._result(
                    summary,
                    entry,
                    "history",
                    match,
                    retailer,
                    branch_id,
                    article.get("key") or None,
                    count=int(article.get("count") or 0),
                )
            )

        if key and any(r["match"] == MATCH_EXACT for r in found):
            # the query names an article: its variants ("Süßrahmbutter") rank like prefix
            # matches, i.e. with the other products that start with it ("Butterkäse")
            # offers of another product ("Gehackte Tomaten" for "Tomaten") rank last, like
            # in the live search
            for item in found:
                if item["match"] == MATCH_EXACT:
                    continue
                if self._is_article(item["title"], key):
                    item["match"] = min(item["match"], MATCH_PREFIX)
                elif item["source"] == "offer":
                    item["match"] = MATCH_SUBSTRING
        found.sort(key=_sort_key)
        result: list[dict[str, Any]] = []
        seen: set[tuple[str, str | None]] = set()
        for item in found:
            ident = (item["key"], item["pack"])
            if ident in seen:
                continue
            seen.add(ident)
            result.append(item)
            if len(result) >= max(1, int(limit)):
                break
        return result

    def _is_article(self: EssensplanerManager, title: str, key: str) -> bool:
        """True if a hit is the article of the key or a variant of it (compound head:
        "Süßrahmbutter", "ja! Deutsche Markenbutter") – not "Butterkekse" or "Erdnussbutter"."""
        return offer_matches(title, key) and not self.names_other_product(title, key)

    # ------------------------------------------------------------------
    # Live search
    # ------------------------------------------------------------------

    def _live_postcode(self: EssensplanerManager, branch: dict[str, Any] | None) -> str | None:
        """Postcode for live offers: the branch's, else the main/zip option, else a target."""
        postcode = valid_postcode((branch or {}).get("postcode")) or valid_postcode(
            self.main_postcode
        )
        if postcode:
            return postcode
        targets = self.offer_targets()
        return targets[0][0] if targets else None

    async def async_search_articles_live(
        self: EssensplanerManager,
        query: str,
        store: str | None = None,
        limit: int | None = None,
        scope: str = SCOPE_MAIN,
    ) -> dict[str, Any]:
        """Online results for the article search (opt-in sources only).

        scope "main": the live provider of the store's chain (else the main branch's) and
        marktguru for that chain; scope "all": the providers of every selected chain and
        marktguru for all of them. The sources are asked in parallel (each provider host
        one request at a time, see cached_live_fetch()).

        Returns {results, live (a source was asked), error, superseded}. Results look like
        search_articles() results with source "live", the offer and provider.
        """
        everywhere = scope == SCOPE_ALL
        limit = (ALL_LIMIT if everywhere else MAIN_LIMIT) if limit is None else limit
        response: dict[str, Any] = {"results": [], "live": False, "error": None}
        if len(fold(str(query or "")).strip()) < LIVE_MIN_QUERY:
            return response
        if everywhere:
            targets = self._all_targets(store)
            branch, retailer = (None, None) if not store else self.article_target(store)
        else:
            branch, retailer = self.article_target(store)
            targets = {retailer: branch} if retailer else {}
        calls: list[tuple[LiveProvider, dict[str, Any] | None, str | None]] = []
        for chain, chain_branch in targets.items():
            if everywhere and chain_branch is None and not store:
                continue  # a chain without a saved branch has no shop to ask
            if (provider := live_provider_for(self, chain)) is not None:
                calls.append((provider, chain_branch, chain))
        if self.offers_source == OFFERS_MARKTGURU:
            calls.append((_marktguru_live, branch, retailer))
        if not calls:
            return response
        response["live"] = True
        text = str(query).strip()
        self._live_seq += 1  # a newer search replaces this one while it waits
        token = _SEARCH_SEQUENCE.set(self._live_seq)
        try:
            # every task copies the context (the search's sequence number)
            outcomes = await asyncio.gather(
                *(provider(self, text, at, chain) for provider, at, chain in calls),
                return_exceptions=True,
            )
        finally:
            _SEARCH_SEQUENCE.reset(token)
        offers: list[tuple[dict[str, Any], str | None, dict[str, Any] | None]] = []
        errors: list[str] = []
        for (_provider, at, chain), outcome in zip(calls, outcomes, strict=True):
            if isinstance(outcome, _Superseded):
                response["superseded"] = True
                return response
            if isinstance(outcome, OfferError):
                errors.append(str(outcome))
            elif isinstance(outcome, BaseException):
                raise outcome
            else:
                offers.extend((offer, chain, at) for offer in outcome)
        response["error"] = "; ".join(errors) or None
        folded = fold(text)
        key = ingredient_key(text)
        if key and offers:
            # the shop hits (REWE, ALDI SÜD) that fit go into the product database (1.5);
            # leaflet hits only when one is picked
            from .products import ingest_live_results

            try:
                ingest_live_results(self, [offer for offer, _, _ in offers], key)
            except Exception:
                _LOGGER.exception("Storing the products of the article search failed")
        defaults = self.defaults_index()
        # the query names an article: hits that are no such article are ranked last
        article = bool(key) and (defaults.get(key) is not None or defaults.exact(text) is not None)
        if everywhere:
            article = self._names_article(text, key)
        today = self.today()
        by_branch = self._live_branches() if everywhere else {}
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for offer, chain, at in offers:
            if offer.get("id") in seen or not offer_valid_on(offer, today, 0):
                continue
            seen.add(offer.get("id") or "")
            match = _match(folded, key, [offer.get("title") or "", offer.get("product") or ""])
            if article and not everywhere:
                # like the shopping list: offers of the article first, other products last
                title = str(offer.get("product") or offer.get("title") or "")
                if self._is_article(title, key):
                    match = MATCH_WORD if match is None else min(match, MATCH_WORD)
                else:
                    match = MATCH_SUBSTRING
            hit_retailer = offer.get("retailer") or chain or retailer
            if everywhere:
                if hit_retailer not in targets:
                    continue
                hit_branch = by_branch.get((hit_retailer, _offer_zip(offer)))
                if hit_branch is None:
                    first = at if at is not None and at.get("retailer") == hit_retailer else None
                    first = first or targets.get(hit_retailer)
                    hit_branch = first.get("id") if first else None
            else:
                hit_branch = branch.get("id") if branch else None
            result = self._offer_result(
                offer,
                "live",
                MATCH_SUBSTRING if match is None else match,
                hit_retailer,
                hit_branch,
            )
            result["offer"]["image"] = offer.get("image")
            # where the hit comes from: "marktguru" (leaflet offer), "rewe_online" /
            # "aldi_online" (shop price)
            result["provider"] = offer.get("source")
            if everywhere:
                title = str(offer.get("product") or offer.get("title") or "")
                result["tier"] = self._tier(title, result["match"], key, article)
                result["stale"] = False
            results.append(result)
        self._decorate(results)
        if everywhere:
            results = sort_all(results)
        else:
            results.sort(key=lambda r: (_sort_key(r), r["unit_price"] or 9e9, r["price"] or 0))
        response["results"] = results[: max(1, int(limit))]
        return response

    def _live_branches(self: EssensplanerManager) -> dict[tuple[str, str | None], str]:
        """{(retailer, postcode its offers are fetched at): first such branch}."""
        from .catalog import _branch_index

        result: dict[tuple[str, str | None], str] = {}
        for retailer, entries in _branch_index(self)[0].items():
            for branch_id, postcode in entries:
                result.setdefault((retailer, postcode), branch_id)
        return result


def _offer_zip(offer: dict[str, Any]) -> str | None:
    zips = offer.get("zip_codes") or []
    return str(zips[0]) if zips else None


def _regular_of(offer: dict[str, Any]) -> float | None:
    """The struck / regular price of an offer (old price, shop's regular price)."""
    for field in ("old_price", "regular_price"):
        try:
            value = float(offer.get(field) or 0)
            price = float(offer.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if value > price:
            return round(value, 2)
    return None


class _Superseded(Exception):
    """A newer live search replaced this one while it was waiting."""


async def cached_live_fetch(
    manager: EssensplanerManager,
    cache_key: tuple[Any, ...],
    fetch: Callable[[], Awaitable[list[dict[str, Any]]]],
    host: str = HOST_MARKTGURU,
) -> list[dict[str, Any]]:
    """Live results cached for LIVE_CACHE_SECONDS per key, one request per LIVE_MIN_INTERVAL
    and provider host (marktguru, the REWE shop, ALDI SÜD: the hosts are asked in parallel,
    each one request at a time).

    Shared by all live sources. A query that is replaced by a newer one while waiting for
    its turn raises _Superseded (the newest query wins). Errors of fetch() are passed on
    (nothing is cached then).
    """
    now = dt_util.utcnow().timestamp()
    cached = manager._live_cache.get(cache_key)
    if cached is not None and now - cached[0] < LIVE_CACHE_SECONDS:
        return cached[1]
    sequence = _SEARCH_SEQUENCE.get()
    if sequence is None:  # called outside async_search_articles_live
        manager._live_seq += 1
        sequence = manager._live_seq
    lock = manager._live_locks.get(host)
    if lock is None:
        lock = manager._live_locks[host] = asyncio.Lock()
    async with lock:
        cached = manager._live_cache.get(cache_key)
        now = dt_util.utcnow().timestamp()
        if cached is not None and now - cached[0] < LIVE_CACHE_SECONDS:
            return cached[1]
        wait = LIVE_MIN_INTERVAL - (now - manager._live_last.get(host, 0.0))
        if wait > 0:
            await asyncio.sleep(wait)  # be polite: one request per interval and host
        if sequence != manager._live_seq:
            raise _Superseded
        manager._live_last[host] = dt_util.utcnow().timestamp()
        results = await fetch()
        manager._live_cache[cache_key] = (dt_util.utcnow().timestamp(), results)
        if len(manager._live_cache) > LIVE_CACHE_MAX:
            oldest = min(manager._live_cache, key=lambda k: manager._live_cache[k][0])
            del manager._live_cache[oldest]
        return results


async def _marktguru_live(
    manager: EssensplanerManager,
    query: str,
    branch: dict[str, Any] | None,
    retailer: str | None,
) -> list[dict[str, Any]]:
    """marktguru offers for the query near the branch (cached 1 h, throttled; nothing is
    asked while marktguru is paused after it refused, and a refusal starts the pause)."""
    from .catalog import marktguru_paused, pause_marktguru, paused_message

    postcode = manager._live_postcode(branch)
    if postcode is None:
        return []
    if until := marktguru_paused(manager):
        raise OfferError(paused_message(until))

    # only the user's chains when the offer catalog knows their marktguru ids there
    catalog = getattr(manager, "catalog", None)
    ids = (
        catalog.publisher_ids(postcode, [retailer] if retailer else manager.active_retailers())
        if catalog is not None
        else []
    )

    async def fetch() -> list[dict[str, Any]]:
        if manager._live_client is None:
            manager._live_client = MarktguruClient(manager.hass)
        try:
            raw = await manager._live_client.async_search(
                query, postcode, LIVE_RESULTS, retailers=ids or None
            )
        except OfferBlocked as err:
            raise OfferError(paused_message(pause_marktguru(manager))) from err
        offers = [o for o in (normalize_marktguru(r, query) for r in raw) if o]
        for offer in offers:
            offer["zip_codes"] = [postcode]
        return offers

    cache_key = (fold(query).strip(), postcode, *([tuple(ids)] if ids else []))
    offers = await cached_live_fetch(manager, cache_key, fetch, HOST_MARKTGURU)
    if retailer is not None:
        return [
            o
            for o in offers
            if (o.get("retailer") or retailer_for_store_id(o.get("store_id"))) == retailer
        ]
    active = manager.active_retailers()
    return [o for o in offers if store_allowed(o.get("store_id") or "", active)]
