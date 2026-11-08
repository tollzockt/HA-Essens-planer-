"""Shared machinery of the experimental online price sources (REWE online shop, ALDI SÜD)
and of the EDEKA market offers.

An adapter module (rewe.py, aldi.py, edeka.py) defines an OnlinePriceSource subclass that
only knows how to find its store, ask for products and read them. Everything else works the
same for every source:

- status in manager.price_sources_meta[key]: {status (ok|error|blocked), last_run,
  last_success, count, learned, searched, errors (<= MAX_ERRORS), blocked_until, client
  (the adapter's CLIENT_VERSION: a stored error or pause of an older client does not count),
  no_articles, <store field> (market_id / service_point), branch_id}; status() adds "off"
  (option off), "pending" (never run) and a German message;
- politeness: REQUEST_DELAY s between two requests of a refresh, at most MAX_TERMS search
  terms (offers) + MAX_SHOPPING_TERMS open shopping items, a scheduled refresh only when
  the last success is REFRESH_DAYS old, a manual one at most once per MANUAL_MIN_HOURS after
  a success, one refresh per config entry at a time;
- backoff: HTTP 401/403/429 or a web page instead of JSON mark the source as "blocked", an
  answer without the expected structure as "error"; both stop all requests for BLOCK_DAYS
  days (a store that returns no articles at all: NO_ARTICLES_DAYS). Prices learned before
  are kept. Nothing tries to get around a refusal (honest User-Agent, no browser headers).

The tunables are module constants of the adapter (rewe.REQUEST_DELAY, aldi.MAX_TERMS …)
read at run time, so the defaults below are only used when an adapter does not set one.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
import json
import logging
import re
from types import ModuleType
from typing import TYPE_CHECKING, Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .articles import cached_live_fetch
from .const import DOMAIN, HTTP_USER_AGENT
from .ingredients import fold, ingredient_key, parse_ingredient
from .netio import BodyTooLarge, async_read_body
from .offers import OfferError, leaflet_week_end, offer_matches
from .pricing import offer_pack, piece_weight_known, plausible_pack, unit_price

if TYPE_CHECKING:
    from .manager import EssensplanerManager

_LOGGER = logging.getLogger(__name__)

STATUS_OFF = "off"
STATUS_PENDING = "pending"
STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_BLOCKED = "blocked"

# defaults of the tunables (each adapter module may set its own)
DEFAULTS: dict[str, float] = {
    "REQUEST_DELAY": 2.0,
    "REQUEST_TIMEOUT": 20,
    "MAX_TERMS": 40,
    "MAX_SHOPPING_TERMS": 20,
    "REFRESH_DAYS": 7,
    "BLOCK_DAYS": 7,
    "NO_ARTICLES_DAYS": 1,
    "NO_ARTICLE_SEARCHES": 5,
    "MANUAL_MIN_HOURS": 6,
    "MAX_ERRORS": 5,
    "MAX_FAILURES": 3,
    "MAX_BYTES": 4 * 1024 * 1024,
}

HEADERS = {
    "User-Agent": HTTP_USER_AGENT,
    "Accept": "application/json",
    "Accept-Language": "de-DE,de;q=0.9",
}

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
# a price outside this range is not a price
_PRICE_RANGE = (0.01, 1000.0)


# ----------------------------------------------------------------------
# Errors
# ----------------------------------------------------------------------


class SourceError(HomeAssistantError):
    """A request of an online source failed (translation key + German message)."""

    def __init__(self, key: str, message: str, **placeholders: str) -> None:
        """Error with a translation key and a German message (for status and warnings)."""
        super().__init__(
            translation_domain=DOMAIN,
            translation_key=key,
            translation_placeholders=placeholders,
        )
        self.message = message


class SourceBlocked(SourceError):
    """The source refused automated requests (HTTP 401/403/429, web page instead of data)."""


class SourceUnexpected(SourceError):
    """The answer did not have the expected structure (interface changed?)."""


# blocked(detail) -> SourceBlocked, failed(detail, unexpected) -> SourceError
BlockedFactory = Callable[[str], SourceError]
FailedFactory = Callable[..., SourceError]


# ----------------------------------------------------------------------
# Numbers and products
# ----------------------------------------------------------------------


def dict_of(value: Any) -> dict[str, Any]:
    """value if it is a dict, else {}."""
    return value if isinstance(value, dict) else {}


def number(value: Any) -> float | None:
    """A number from a number or text ('1,19 €' -> 1.19); None for booleans / nothing."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and (match := _NUMBER_RE.search(value)):
        return float(match.group().replace(",", "."))
    return None


def in_range(price: float | None) -> float | None:
    """A plausible price rounded to cents (None outside 0,01–1000 €)."""
    if price is None or not _PRICE_RANGE[0] <= price <= _PRICE_RANGE[1]:
        return None
    return round(price, 2)


def cents_to_eur(value: Any) -> float | None:
    """Prices in cents: 199 -> 1.99 (None if not a plausible price)."""
    value = number(value)
    return in_range(value / 100) if value is not None else None


def learn_price(product: dict[str, Any]) -> float:
    """The regular price of a product (not a temporary reduction)."""
    return product.get("regular_price") or product["price"]


def product_matches(name: str, key: str) -> bool:
    """True if a product name fits an ingredient key (like offers.offer_matches()).

    Keys without a word of 3+ letters ('ei' for Eier) match a word of the name with the
    same key ('Eier 10 Stück', not 'Eierlikör').
    """
    if offer_matches(name, key):
        return True
    words = key.split()
    if not words or any(len(w) >= 3 for w in words):
        return False
    return key in {ingredient_key(word) for word in re.split(r"[\s,;/()]+", name) if word}


def best_product(
    products: list[dict[str, Any]], key: str, base: str | None = None
) -> dict[str, Any] | None:
    """The cheapest product (regular price per kg / l / piece) matching an ingredient key.

    Only products with a plausible pack size count. base (g / ml / Stück, e.g. of the
    estimate) prefers products sold in a comparable unit; otherwise the unit most matches
    are sold in is used – not for an estimate per Bund / Kopf / piece without a known
    piece weight: the cheapest per g would be another product ("Pesto" for Basilikum).
    """
    candidates: list[tuple[float, float, str, dict[str, Any], str]] = []
    for product in products:
        if not product or product.get("price") is None:
            continue
        if not product_matches(str(product.get("product") or product.get("title") or ""), key):
            continue
        pack = offer_pack(product)
        if pack is None or not plausible_pack(*pack):
            continue
        price = learn_price(product)
        candidates.append(
            (price / pack[0], price, str(product.get("title") or ""), product, pack[1])
        )
    if not candidates:
        return None
    # g and ml are compared 1:1 (like the plausibility check against the estimates)
    wanted = {"g", "ml"} if base in ("g", "ml") else {base} if base else set()
    preferred = [c for c in candidates if c[4] in wanted]
    if not preferred:
        if base and base not in ("g", "ml") and not piece_weight_known(key):
            return None  # nothing to compare a price by weight with
        units = [c[4] for c in candidates]
        common = max(("g", "ml", "Stück"), key=units.count)
        preferred = [c for c in candidates if c[4] == common] or candidates
    best = min(preferred, key=lambda c: (c[0], c[1], len(c[2])))
    return best[3]


def reduced_products(
    products: list[dict[str, Any]], key: str, limit: int = 2
) -> list[dict[str, Any]]:
    """Products of a search that are reduced right now (regular_price > price) and match
    the key, cheapest per unit first (at most `limit`)."""
    found: list[tuple[float, dict[str, Any]]] = []
    for product in products:
        regular = product.get("regular_price")
        if not regular or product.get("price") is None or regular <= product["price"]:
            continue
        if not product_matches(str(product.get("product") or product.get("title") or ""), key):
            continue
        pack = offer_pack(product)
        if pack is None or not plausible_pack(*pack):
            continue
        found.append((product["price"] / pack[0], product))
    found.sort(key=lambda f: f[0])
    return [p for _, p in found[:limit]]


# ----------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------


async def async_get_json(
    session: aiohttp.ClientSession,
    url: str,
    params: dict[str, Any] | None,
    blocked: BlockedFactory,
    failed: FailedFactory,
    *,
    timeout: float = 20,
    max_bytes: int = 4 * 1024 * 1024,
    unexpected_status: tuple[int, ...] = (404, 410),
    headers: dict[str, str] | None = None,
) -> Any:
    """GET a JSON answer with the honest User-Agent.

    HTTP 401/403/429 and a web page instead of data raise blocked(detail); HTTP statuses in
    unexpected_status (the interface moved) and unreadable data raise
    failed(detail, unexpected=True); other errors failed(detail) (retried next time).
    """
    try:
        async with session.get(
            url,
            params=params,
            headers=headers or HEADERS,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            status = resp.status
            content_type = str(resp.headers.get("Content-Type") or "").lower()
            if status in (401, 403, 429):
                raise blocked(f"HTTP {status}")
            if status in unexpected_status:
                raise failed(f"Schnittstelle nicht gefunden, HTTP {status}", unexpected=True)
            if status >= 400:
                raise failed(f"HTTP {status}")
            body = await async_read_body(resp, max_bytes)
    except BodyTooLarge as err:
        raise failed("Antwort zu groß") from err
    except TimeoutError as err:
        raise failed("keine Antwort") from err
    except aiohttp.ClientError as err:
        raise failed(str(err) or type(err).__name__) from err
    text = body.decode("utf-8", errors="replace").lstrip("﻿ \t\r\n")
    if "html" in content_type or text.startswith("<"):
        raise blocked("Webseite statt Daten")
    try:
        return json.loads(text)
    except ValueError as err:
        raise failed("keine lesbaren Daten", unexpected=True) from err


# ----------------------------------------------------------------------
# Search terms
# ----------------------------------------------------------------------


def refresh_terms(
    manager: EssensplanerManager, max_terms: int = 40, max_shopping: int = 20
) -> list[tuple[str, str]]:
    """(search term, ingredient key): the offer search terms plus open shopping items."""
    terms = list(manager.offer_search_terms(limit=max_terms))
    seen = {key for _, key in terms}
    extra = 0
    for item in manager.shopping:
        if item.get("status") == "completed" or extra >= max_shopping:
            continue
        summary = str(item.get("summary") or "")
        name = str(item.get("name") or parse_ingredient(summary)["name"] or summary).strip()
        key = str(item.get("key") or ingredient_key(name))
        if not name or not key or key in seen:
            continue
        seen.add(key)
        terms.append((name, key))
        extra += 1
    return terms


def default_base(manager: EssensplanerManager, key: str) -> str | None:
    """Base unit (g / ml / Stück) of the key's estimate."""
    default = manager.defaults_index().lookup(key)
    per = unit_price(default) if default else None
    return per[1] if per else None


def _ingest_products(
    manager: EssensplanerManager,
    retailer: str,
    products: list[dict[str, Any]],
    key: str,
    source: str,
) -> None:
    """Store a search's products in the product database (never fails the refresh)."""
    from .products import ingest_shop_products  # the product database imports this module

    try:
        ingest_shop_products(manager, retailer, products, key, source)
    except Exception:
        _LOGGER.exception("Storing the products of %s failed", source)


# ----------------------------------------------------------------------
# Time texts
# ----------------------------------------------------------------------


def parse_time(value: Any) -> datetime | None:
    """A stored ISO timestamp (None if missing)."""
    return dt_util.parse_datetime(value) if isinstance(value, str) and value else None


def date_text(value: datetime) -> str:
    """'11.11.2026' (local date)."""
    return dt_util.as_local(value).strftime("%d.%m.%Y")


def time_text(value: datetime, now: datetime) -> str:
    """'16:30 Uhr' (today) or '06.11. 02:00 Uhr'."""
    local = dt_util.as_local(value)
    if local.date() == dt_util.as_local(now).date():
        return local.strftime("%H:%M Uhr")
    return local.strftime("%d.%m. %H:%M Uhr")


# ----------------------------------------------------------------------
# The source
# ----------------------------------------------------------------------


class OnlinePriceSource:
    """One online price source; the adapter overrides the hooks marked below.

    Class attributes:
      key: meta key in price_sources_meta ("rewe"), also the refresh_prices source
      retailer: the retailer the learned prices belong to ("rewe")
      source: source of the learned prices ("rewe_online")
      option / option_default: the opt-in option
      store_field: status / meta key of the store id ("market_id")
      title: German plural name for messages ("REWE-Onlinepreise")
      site / site_from: "Der REWE-Onlineshop" / "vom REWE-Onlineshop"
      log_name: English name for the log ("REWE online prices")
      offer_source: offers of reduced products get this source (None: no offers)
      kept_text / schedule_text: German status parts (what is kept while paused, when the
        scheduled refresh runs)
    """

    key = ""
    retailer = ""
    source = ""
    option = ""
    option_default = False
    store_field = "market_id"
    title = ""
    site = ""
    site_from = ""
    log_name = ""
    offer_source: str | None = None
    experimental = True
    kept_text = "Bisherige Preise bleiben erhalten."
    schedule_text = "nachts"

    def __init__(self, module: ModuleType) -> None:
        """module: the adapter module whose constants are the tunables."""
        self.module = module
        self._running: set[str] = set()

    # -- tunables (module constants of the adapter, read at run time) -------------

    def setting(self, name: str) -> Any:
        """A tunable of the adapter module (rewe.REQUEST_DELAY …) or its default."""
        return getattr(self.module, name, DEFAULTS[name])

    @property
    def client_version(self) -> int:
        """Version of the adapter's client (stored errors of older ones do not count)."""
        return int(getattr(self.module, "CLIENT_VERSION", 1))

    # -- adapter hooks ------------------------------------------------------------

    def enabled(self, manager: EssensplanerManager) -> bool:
        """True if the user enabled the source."""
        return bool(manager.options.get(self.option, self.option_default))

    def target(
        self, manager: EssensplanerManager, branch: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str | None]:
        """(branch, store id) of the store to ask (None, None: no store known)."""
        raise NotImplementedError

    async def async_target(
        self, hass: HomeAssistant, manager: EssensplanerManager, branch: dict[str, Any] | None
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Like target(), may look the store up first (one request, e.g. ALDI SÜD)."""
        return self.target(manager, branch)

    def has_target(self, manager: EssensplanerManager) -> bool:
        """True if a refresh knows (or can find) its store."""
        return self.target(manager)[1] is not None

    def no_target_message(self, manager: EssensplanerManager) -> str:
        """German message while no store is known."""
        raise NotImplementedError

    def make_client(self, hass: HomeAssistant) -> Any:
        """The HTTP client of the source."""
        raise NotImplementedError

    async def async_search(self, client: Any, term: str, store_id: str) -> list[dict[str, Any]]:
        """Products for a search term (normalized like rewe.parse_product())."""
        raise NotImplementedError

    def no_articles_error(self, store_id: str) -> SourceError:
        """The error recorded when a store returns no articles at all."""
        raise NotImplementedError

    def ok_message(self, meta: dict[str, Any], when: str) -> str:
        """German message after a successful refresh."""
        return f"Zuletzt am {when} aktualisiert: {meta.get('learned') or 0} Preise gelernt."

    def status_extra(self, manager: EssensplanerManager, meta: dict[str, Any]) -> dict[str, Any]:
        """Further fields of the status (adapter specific)."""
        return {}

    def stale(self, manager: EssensplanerManager, now: datetime) -> bool:
        """True if a scheduled refresh should fetch again."""
        last = parse_time(self.meta(manager).get("last_success"))
        return last is None or now - last >= timedelta(days=self.setting("REFRESH_DAYS"))

    # -- meta and status ----------------------------------------------------------

    def meta(self, manager: EssensplanerManager) -> dict[str, Any]:
        """The stored meta of the source ({} if none)."""
        meta = manager.price_sources_meta.get(self.key)
        return meta if isinstance(meta, dict) else {}

    def current_client(self, meta: dict[str, Any]) -> bool:
        """True if the stored status comes from this client version (older errors and
        pauses were caused by an interface that moved and do not count)."""
        return meta.get("client") == self.client_version

    def blocked_until(
        self, manager: EssensplanerManager, now: datetime | None = None
    ) -> datetime | None:
        """End of the current backoff (None if requests are allowed)."""
        meta = self.meta(manager)
        until = parse_time(meta.get("blocked_until"))
        if until is None or until <= (now or dt_util.utcnow()) or not self.current_client(meta):
            return None
        return until

    def learned_count(self, manager: EssensplanerManager) -> int:
        """Prices of this source in the retailer's price list."""
        return sum(
            1
            for item in manager.store_prices_learned.get(self.retailer, {}).values()
            if item.get("source") == self.source
        )

    def status(self, manager: EssensplanerManager) -> dict[str, Any]:
        """Status for the panel / services: stored status plus a German message.

        status: off (option off) | pending (never run) | ok | error | blocked.
        """
        meta = self.meta(manager)
        enabled = self.enabled(manager)
        branch, store_id = self.target(manager)
        until = self.blocked_until(manager)
        status = str(meta.get("status") or STATUS_PENDING) if enabled else STATUS_OFF
        max_errors = int(self.setting("MAX_ERRORS"))
        errors = [str(e) for e in meta.get("errors") or []][:max_errors]
        if status in (STATUS_ERROR, STATUS_BLOCKED) and not self.current_client(meta):
            status, errors = STATUS_PENDING, []  # failed with an older interface
        last_success = parse_time(meta.get("last_success"))
        if not enabled:
            message = f"{self.title} sind aus (experimentell, in den Einstellungen einschaltbar)."
            if not self.experimental:
                message = f"{self.title} sind aus (in den Einstellungen einschaltbar)."
        elif not self.has_target(manager):
            message = self.no_target_message(manager)
        elif until is not None:
            reason = (
                f"{self.site} hat automatische Abfragen abgelehnt"
                if status == STATUS_BLOCKED
                else (errors[0] if meta.get("no_articles") and errors else None)
                or f"Unerwartete Antwort {self.site_from}"
            )
            message = f"{reason} – nächster Versuch ab {date_text(until)}. {self.kept_text}"
        elif status == STATUS_PENDING:
            message = (
                "Noch nicht abgerufen – das passiert automatisch kurz nach dem Start bzw. "
                f"{self.schedule_text} (oder jetzt mit „Preise aktualisieren“)."
            )
        elif status != STATUS_OK:
            message = f"Letzter Abruf fehlgeschlagen: {errors[0] if errors else 'unbekannt'}"
        else:
            when = date_text(last_success) if last_success else "?"
            message = self.ok_message(meta, when)
        return {
            "source": self.source,
            "experimental": self.experimental,
            "enabled": enabled,
            "status": status,
            "message": message,
            "last_run": meta.get("last_run"),
            "last_success": meta.get("last_success"),
            "count": int(meta.get("count") or 0),
            "learned": int(meta.get("learned") or 0),
            "searched": int(meta.get("searched") or 0),
            "errors": errors,
            "blocked_until": until.isoformat() if until else None,
            self.store_field: store_id,
            "branch_id": branch.get("id") if branch else None,
            "prices": self.learned_count(manager),
            **self.status_extra(manager, meta),
        }

    def manual_wait(
        self, manager: EssensplanerManager, store_id: str, now: datetime
    ) -> datetime | None:
        """End of the pause after a successful run for the same store (None = may run)."""
        meta = self.meta(manager)
        last = parse_time(meta.get("last_success"))
        if last is None or str(meta.get(self.store_field) or "") != store_id:
            return None
        until = last + timedelta(hours=self.setting("MANUAL_MIN_HOURS"))
        return until if until > now else None

    def record_block(
        self,
        manager: EssensplanerManager,
        err: SourceError,
        now: datetime,
        days: float | None = None,
        no_articles: bool = False,
    ) -> None:
        """Remember a refusal / unexpected answer: no requests for `days` days."""
        days = self.setting("BLOCK_DAYS") if days is None else days
        meta = dict(self.meta(manager))
        errors = [err.message, *[e for e in meta.get("errors") or [] if e != err.message]]
        if not self.current_client(meta):
            errors = [err.message]
        meta.update(
            {
                "status": STATUS_BLOCKED if isinstance(err, SourceBlocked) else STATUS_ERROR,
                "last_run": now.isoformat(),
                "errors": errors[: int(self.setting("MAX_ERRORS"))],
                "blocked_until": (now + timedelta(days=days)).isoformat(),
                "client": self.client_version,
                "no_articles": no_articles,
            }
        )
        manager.price_sources_meta[self.key] = meta
        _LOGGER.warning(
            "%s (experimental) paused for %s day(s): %s", self.log_name, days, err.message
        )

    def cooldown_status(
        self, manager: EssensplanerManager, until: datetime, now: datetime
    ) -> dict[str, Any]:
        """The status after a manual refresh within MANUAL_MIN_HOURS (nothing sent)."""
        status = self.status(manager)
        status["cooldown_until"] = until.isoformat()
        status["message"] = f"Gerade erst aktualisiert – wieder möglich ab {time_text(until, now)}."
        return status

    # -- refresh ------------------------------------------------------------------

    async def async_refresh(
        self, hass: HomeAssistant, manager: EssensplanerManager, force: bool = False
    ) -> dict[str, Any]:
        """Refresh the source. Returns status().

        force=False only runs when stale(); force=True (button, service) runs at most once
        per MANUAL_MIN_HOURS after a success for the same store (else the status with
        cooldown_until and a message). Never runs while blocked (also not with force) or
        while another refresh of the entry runs.
        """
        if not self.enabled(manager):
            return self.status(manager)
        now = dt_util.utcnow()
        entry_id = manager.entry.entry_id
        if (
            self.blocked_until(manager, now) is not None
            or (not force and not self.stale(manager, now))
            or entry_id in self._running
        ):
            return self.status(manager)
        self._running.add(entry_id)
        try:
            branch, store_id = await self.async_target(hass, manager, None)
            if store_id is None:
                return self.status(manager)
            if force and (until := self.manual_wait(manager, store_id, now)) is not None:
                # be polite: tapping "Preise aktualisieren" again sends nothing
                return self.cooldown_status(manager, until, now)
            notified = await self._async_run(hass, manager, branch, store_id, now)
        except SourceError as err:
            # the store lookup failed (ALDI SÜD service points)
            if isinstance(err, (SourceBlocked, SourceUnexpected)):
                self.record_block(manager, err, now)
            else:
                self._record_error(manager, err, now)
            manager._changed("price_sources")
            return self.status(manager)
        finally:
            self._running.discard(entry_id)
        if notified:
            manager._changed("price_sources")  # the new offers already moved open items
        else:
            manager._after_price_change("prices")  # learned prices can move open items
        return self.status(manager)

    def _record_error(self, manager: EssensplanerManager, err: SourceError, now: datetime) -> None:
        """A failed run without backoff (retried on the next check)."""
        meta = dict(self.meta(manager))
        meta.update(
            {
                "status": STATUS_ERROR,
                "last_run": now.isoformat(),
                "errors": [err.message][: int(self.setting("MAX_ERRORS"))],
                "blocked_until": None,
                "client": self.client_version,
                "no_articles": False,
            }
        )
        manager.price_sources_meta[self.key] = meta

    def learn(self, manager: EssensplanerManager, key: str, product: dict[str, Any]) -> bool:
        """Store the regular price of the best product of a term."""
        pack = offer_pack(product)
        return bool(
            pack
            and manager.learn_store_price(
                self.retailer,
                key,
                product["product"],
                learn_price(product),
                pack[0],
                pack[1],
                self.source,
                ref=product.get("product_id"),
            )
        )

    def as_offer(
        self, manager: EssensplanerManager, product: dict[str, Any], key: str
    ) -> dict[str, Any]:
        """A reduced product as a current offer (until the end of the leaflet week)."""
        return {
            **product,
            "old_price": product.get("regular_price"),
            "valid_from": manager.today().isoformat(),
            "valid_to": leaflet_week_end(manager.today()).isoformat(),
            "source": self.offer_source,
            "keys": [key],
        }

    async def _async_run(
        self,
        hass: HomeAssistant,
        manager: EssensplanerManager,
        branch: dict[str, Any] | None,
        store_id: str,
        now: datetime,
    ) -> bool:
        """Search every refresh term and learn the cheapest matching product.

        Returns True if new offers were stored (open items were assigned again already).
        """
        previous = dict(self.meta(manager))
        client = self.make_client(hass)
        errors: list[str] = []
        requests = succeeded = found = learned = failures = articles = 0
        stop: SourceError | None = None
        delay = float(self.setting("REQUEST_DELAY"))
        max_failures = int(self.setting("MAX_FAILURES"))
        no_article_searches = int(self.setting("NO_ARTICLE_SEARCHES"))
        offers: dict[str, dict[str, Any]] = {}
        terms = refresh_terms(
            manager, int(self.setting("MAX_TERMS")), int(self.setting("MAX_SHOPPING_TERMS"))
        )
        for term, key in terms:
            if requests and delay > 0:
                await asyncio.sleep(delay)  # be polite to the shop
            requests += 1
            try:
                products = await self.async_search(client, term, store_id)
            except (SourceBlocked, SourceUnexpected) as err:
                stop = err
                break
            except SourceError as err:
                errors.append(f"{term}: {err.message}")
                failures += 1
                if not succeeded or failures >= max_failures:
                    break  # the shop is not reachable: try again on the next check
                continue
            succeeded += 1
            failures = 0
            articles += len(products)
            if not articles and succeeded >= no_article_searches:
                break  # nothing priced at all: the store id is wrong (see below)
            if self.offer_source:
                for product in reduced_products(products, key):
                    offer = offers.get(product["id"])
                    if offer is None:
                        offers[product["id"]] = self.as_offer(manager, product, key)
                    elif key not in offer["keys"]:
                        offer["keys"].append(key)
            # the fitting products of the search go into the product database (1.5)
            _ingest_products(manager, self.retailer, products, key, self.source)
            product = best_product(products, key, default_base(manager, key))
            if product is None:
                continue
            found += 1
            if self.learn(manager, key, product):
                learned += 1
        meta = {
            **previous,
            "status": STATUS_OK if succeeded else STATUS_ERROR,
            "last_run": now.isoformat(),
            "searched": requests,
            "errors": errors[: int(self.setting("MAX_ERRORS"))],
            "blocked_until": None,
            self.store_field: store_id,
            "branch_id": branch.get("id") if branch else None,
            "client": self.client_version,
            "no_articles": False,
        }
        no_articles = (
            stop is None and succeeded >= min(no_article_searches, requests) and not articles
        )
        complete = bool(succeeded and stop is None and not no_articles)
        if complete:
            meta.update({"last_success": now.isoformat(), "count": found, "learned": learned})
            if self.offer_source:
                meta["offers"] = len(offers)
        manager.price_sources_meta[self.key] = meta
        notified = False
        if complete and self.offer_source:
            # reduced products are this week's offers of the store (old ones are replaced)
            manager.replace_source_offers(self.offer_source, list(offers.values()), None)
            notified = True
        if no_articles and requests >= 2:
            # every search came back without a single article: wrong / unknown store id
            self.record_block(
                manager,
                self.no_articles_error(store_id),
                now,
                days=self.setting("NO_ARTICLES_DAYS"),
                no_articles=True,
            )
        elif stop is not None:
            self.record_block(manager, stop, now)  # prices learned before the refusal stay
        elif errors and not succeeded:
            _LOGGER.debug("%s: %s", self.log_name, "; ".join(errors))
        return notified

    # -- live article search ------------------------------------------------------

    async def async_live(
        self,
        manager: EssensplanerManager,
        query: str,
        branch: dict[str, Any] | None,
        retailer: str | None,
    ) -> list[dict[str, Any]]:
        """Articles for the "Artikel hinzufügen" field (cached 1 h, throttled)."""
        if not self.enabled(manager):
            return []
        _, store_id = self.target(manager, branch)
        if store_id is None and self.has_target(manager):
            # look the store up once (ALDI SÜD); never while the source is paused
            if (until := self.blocked_until(manager)) is not None:
                raise OfferError(f"{self.title} pausiert bis {date_text(until)}.")
            try:
                _, store_id = await self.async_target(manager.hass, manager, branch)
            except SourceError as err:
                if isinstance(err, (SourceBlocked, SourceUnexpected)):
                    self.record_block(manager, err, dt_util.utcnow())
                    manager._changed("price_sources")
                raise OfferError(err.message) from err
        if store_id is None:
            raise OfferError(self.no_target_message(manager))

        async def fetch() -> list[dict[str, Any]]:
            if (until := self.blocked_until(manager)) is not None:
                raise OfferError(f"{self.title} pausiert bis {date_text(until)}.")
            try:
                return await self.async_search(self.make_client(manager.hass), query, store_id)
            except SourceError as err:
                if isinstance(err, (SourceBlocked, SourceUnexpected)):
                    self.record_block(manager, err, dt_util.utcnow())
                    manager._changed("price_sources")
                raise OfferError(err.message) from err

        return await cached_live_fetch(
            manager, (fold(query).strip(), f"{self.key}:{store_id}"), fetch
        )
