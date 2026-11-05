"""Article search for the "Artikel hinzufügen" field (mixin for the manager).

Local results (instant, no network): the store's price list (own and learned store prices),
own general prices, the bundled estimates (names and aliases), valid offers of the store's
retailer and recently added articles (article_history). The default store is the main
branch; without one the general prices are searched.

Optional live results (async_search_articles_live): providers per retailer can be
registered in LIVE_PROVIDERS with an optional "enabled" check (rewe.py adds the
experimental REWE online shop for "rewe", only asked while its option is on); the
marktguru offer search for the branch postcode is used for every retailer when the user
enabled marktguru (offers_source). Live requests are throttled (LIVE_MIN_INTERVAL, newest
query wins) and cached in memory for an hour per (query, postcode / market), see
cached_live_fetch().
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
import re
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from .const import OFFERS_MARKTGURU
from .economy import _offer_short
from .ingredients import fold, ingredient_key, parse_ingredient
from .offers import MarktguruClient, OfferError, normalize_marktguru, parse_pack, store_allowed
from .pricing import PriceEntry, offer_as_entry, offer_pack, offer_valid_on, pack_text, unit_price
from .retailers import retailer_for_store_id, retailer_name
from .stores import valid_postcode

if TYPE_CHECKING:
    from .manager import EssensplanerManager

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
SOURCE_RANK = {"offer": 0, "store": 1, "learned": 2, "history": 3, "default": 4, "live": 5}
_LEARNED = {"leaflet", "rewe_online", "offer_regular"}
_STUECK_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:stück|stueck|stk\.?|st\.)", re.IGNORECASE)

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


def parse_pack_text(text: str | None) -> tuple[float, str] | None:
    """'250 g', '1,5 l', '2 x 125 g', '10 Stück' -> (amount, base unit)."""
    if not text:
        return None
    if size := parse_pack(str(text)):
        return size
    if match := _STUECK_RE.search(str(text)):
        amount = float(match.group(1).replace(",", "."))
        return (amount, "Stück") if amount > 0 else None
    return None


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
    _live_last: float
    _live_seq: int
    _live_lock: asyncio.Lock | None
    _live_client: MarktguruClient | None
    _default_names: tuple[int, list[tuple[PriceEntry, list[str]]]] | None

    def _init_article_data(self: EssensplanerManager) -> None:
        """Empty caches (called from the manager's __init__)."""
        self._live_cache = {}
        self._live_last = 0.0
        self._live_seq = 0
        self._live_lock = None
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
        }

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
        return result

    def search_articles(
        self: EssensplanerManager, query: str, store: str | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Articles matching a query at a store (local data only, fast).

        Result [{title, key, pack, amount, unit, price, unit_price, base, retailer,
        branch_id, source (store|learned|default|offer|history), real, offer, count,
        match}] – offers and exact/prefix matches first, one per key + pack.
        """
        branch, retailer = self.article_target(store)
        return self._search_local(query, branch, retailer, limit)

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
        self: EssensplanerManager, query: str, store: str | None = None, limit: int = 10
    ) -> dict[str, Any]:
        """Online results for the article search (opt-in sources only).

        Returns {results, live (a source was asked), error, superseded}. Results look like
        search_articles() results with source "live" and the offer.
        """
        branch, retailer = self.article_target(store)
        response: dict[str, Any] = {"results": [], "live": False, "error": None}
        if len(fold(str(query or "")).strip()) < LIVE_MIN_QUERY:
            return response
        providers: list[LiveProvider] = []
        if (provider := live_provider_for(self, retailer)) is not None:
            providers.append(provider)
        if self.offers_source == OFFERS_MARKTGURU:
            providers.append(_marktguru_live)
        if not providers:
            return response
        response["live"] = True
        offers: list[dict[str, Any]] = []
        errors: list[str] = []
        self._live_seq += 1  # a newer search replaces this one while it waits
        token = _SEARCH_SEQUENCE.set(self._live_seq)
        try:
            for provider in providers:
                try:
                    offers.extend(await provider(self, str(query).strip(), branch, retailer))
                except OfferError as err:
                    errors.append(str(err))
                except _Superseded:
                    response["superseded"] = True
                    return response
        finally:
            _SEARCH_SEQUENCE.reset(token)
        response["error"] = "; ".join(errors) or None
        folded = fold(str(query)).strip()
        key = ingredient_key(str(query))
        today = self.today()
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for offer in offers:
            if offer.get("id") in seen or not offer_valid_on(offer, today, 0):
                continue
            seen.add(offer.get("id") or "")
            match = _match(folded, key, [offer.get("title") or "", offer.get("product") or ""])
            result = self._offer_result(
                offer,
                "live",
                MATCH_SUBSTRING if match is None else match,
                offer.get("retailer") or retailer,
                branch.get("id") if branch else None,
            )
            result["offer"]["image"] = offer.get("image")
            # where the hit comes from: "marktguru" (leaflet offer), "rewe_online" (shop price)
            result["provider"] = offer.get("source")
            results.append(result)
        results.sort(key=lambda r: (_sort_key(r), r["unit_price"] or 9e9, r["price"] or 0))
        response["results"] = results[: max(1, int(limit))]
        return response


class _Superseded(Exception):
    """A newer live search replaced this one while it was waiting."""


async def cached_live_fetch(
    manager: EssensplanerManager,
    cache_key: tuple[str, str],
    fetch: Callable[[], Awaitable[list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    """Live results cached for LIVE_CACHE_SECONDS per key, one request per LIVE_MIN_INTERVAL.

    Shared by all live sources (marktguru, REWE). A query that is replaced by a newer one
    while waiting for its turn raises _Superseded (the newest query wins). Errors of fetch()
    are passed on (nothing is cached then).
    """
    now = dt_util.utcnow().timestamp()
    cached = manager._live_cache.get(cache_key)
    if cached is not None and now - cached[0] < LIVE_CACHE_SECONDS:
        return cached[1]
    sequence = _SEARCH_SEQUENCE.get()
    if sequence is None:  # called outside async_search_articles_live
        manager._live_seq += 1
        sequence = manager._live_seq
    if manager._live_lock is None:
        manager._live_lock = asyncio.Lock()
    async with manager._live_lock:
        cached = manager._live_cache.get(cache_key)
        now = dt_util.utcnow().timestamp()
        if cached is not None and now - cached[0] < LIVE_CACHE_SECONDS:
            return cached[1]
        wait = LIVE_MIN_INTERVAL - (now - manager._live_last)
        if wait > 0:
            await asyncio.sleep(wait)  # be polite: one request per interval
        if sequence != manager._live_seq:
            raise _Superseded
        manager._live_last = dt_util.utcnow().timestamp()
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
    """marktguru offers for the query near the branch (cached 1 h, throttled)."""
    postcode = manager._live_postcode(branch)
    if postcode is None:
        return []

    async def fetch() -> list[dict[str, Any]]:
        if manager._live_client is None:
            manager._live_client = MarktguruClient(manager.hass)
        raw = await manager._live_client.async_search(query, postcode, LIVE_RESULTS)
        offers = [o for o in (normalize_marktguru(r, query) for r in raw) if o]
        for offer in offers:
            offer["zip_codes"] = [postcode]
        return offers

    offers = await cached_live_fetch(manager, (fold(query).strip(), postcode), fetch)
    if retailer is not None:
        return [
            o
            for o in offers
            if (o.get("retailer") or retailer_for_store_id(o.get("store_id"))) == retailer
        ]
    active = manager.active_retailers()
    return [o for o in offers if store_allowed(o.get("store_id") or "", active)]
