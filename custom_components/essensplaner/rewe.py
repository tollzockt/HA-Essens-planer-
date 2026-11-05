"""EXPERIMENTAL: regular prices from the REWE online shop and the REWE market search.

Off by default (option rewe_online_prices). Uses the JSON endpoints the REWE web shop uses
in a browser:
- product search: SEARCH_URL?search=<term>&market=<market id>&objectsPerPage=20&page=1
- market search: MARKETS_URL?searchTerm=<postcode> (also without the price option, it is
  an explicit user action)
Neither is documented; both may change or refuse automated requests at any time. This
module sends an honest User-Agent, uses no app certificates and does not try to get around
any bot protection: HTTP 401/403/429 or an HTML page instead of JSON mark the source as
"blocked", an answer without the expected structure as "error" – both stop all requests
for BLOCK_DAYS days. Prices learned before are kept.

Status in manager.price_sources_meta["rewe"]: {status (ok|error|blocked), last_run,
last_success, count, learned, searched, errors (<= 5), blocked_until, market_id,
branch_id}; rewe_status() adds "off" (option off) and "pending" (never run).

Learned prices go to the REWE price list (learn_store_price("rewe", key, ...,
source "rewe_online")): the cheapest matching article per ingredient (price per kg / l /
piece), refreshed weekly (daily check at 04:xx in __init__.py).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import json
import logging
import re
from typing import TYPE_CHECKING, Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .articles import cached_live_fetch, parse_pack_text
from .const import CONF_REWE_ONLINE, DEFAULT_REWE_ONLINE, DOMAIN, HTTP_USER_AGENT
from .ingredients import fold, ingredient_key, parse_ingredient, to_base
from .offers import OfferError, offer_matches
from .pricing import offer_pack, plausible_pack, unit_price
from .stores import valid_postcode

if TYPE_CHECKING:
    from .manager import EssensplanerManager

_LOGGER = logging.getLogger(__name__)

SEARCH_URL = "https://shop.rewe.de/api/products"
MARKETS_URL = "https://www.rewe.de/api/marketsearch"

RETAILER = "rewe"
SOURCE = "rewe_online"
META_KEY = "rewe"

STATUS_OFF = "off"
STATUS_PENDING = "pending"
STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_BLOCKED = "blocked"

# seconds between two product searches of a refresh (tests set 0)
REQUEST_DELAY = 2.0
REQUEST_TIMEOUT = 20
OBJECTS_PER_PAGE = 20
# search terms per refresh: like the offers (watchlist, plan, favourites) + open shopping items
MAX_TERMS = 40
MAX_SHOPPING_TERMS = 20
# prices are refreshed when the last success is older than this
REFRESH_DAYS = 7
# no requests for this long after the shop refused them / answered unexpectedly
BLOCK_DAYS = 7
MAX_ERRORS = 5
# a refresh stops after this many failed searches in a row
MAX_FAILURES = 3
MAX_MARKETS = 25
_MAX_BYTES = 4 * 1024 * 1024
# a REWE price outside this range is not a price
_PRICE_RANGE = (0.01, 1000.0)

HEADERS = {
    "User-Agent": HTTP_USER_AGENT,
    "Accept": "application/json",
    "Accept-Language": "de-DE,de;q=0.9",
}

MSG_NO_MARKET = (
    "Für REWE ist keine Markt-ID hinterlegt – bei der REWE-Filiale „Markt suchen“ und "
    "den Markt auswählen."
)

_MARKET_ID_RE = re.compile(r"^[0-9A-Za-z-]{1,20}$")
# base price in a grammage text: "(1 kg = 3,98 €)", "(100 g = 0,92 €)", "(1 Stück = 0,25 €)"
_BASE_PRICE_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)?\s*(kg|g|ml|l|liter|stück|stk\.?|st\.?)\s*=\s*(\d+(?:[.,]\d+)?)\s*(?:€|eur)",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
# UN/ECE unit codes of "baseUnit" ({"KGM": 1})
_UNIT_CODES = {
    "KGM": (1000.0, "g"),
    "GRM": (1.0, "g"),
    "LTR": (1000.0, "ml"),
    "MLT": (1.0, "ml"),
    "H87": (1.0, "Stück"),
    "PCE": (1.0, "Stück"),
    "STK": (1.0, "Stück"),
}

# refreshes running at the moment (config entry ids)
_RUNNING: set[str] = set()


class ReweError(HomeAssistantError):
    """A REWE request failed (translation key + German message)."""

    def __init__(self, key: str, message: str, **placeholders: str) -> None:
        """Error with a translation key and a German message (for status and warnings)."""
        super().__init__(
            translation_domain=DOMAIN,
            translation_key=key,
            translation_placeholders=placeholders,
        )
        self.message = message


class ReweBlocked(ReweError):
    """REWE refused automated requests (HTTP 401/403/429, HTML page instead of data)."""


class ReweUnexpected(ReweError):
    """The answer did not have the expected structure (interface changed?)."""


def _blocked(detail: str) -> ReweBlocked:
    return ReweBlocked(
        "rewe_blocked",
        f"Der REWE-Onlineshop lässt gerade keine automatischen Abfragen zu ({detail}).",
        error=detail,
    )


def _failed(detail: str, unexpected: bool = False) -> ReweError:
    cls = ReweUnexpected if unexpected else ReweError
    return cls(
        "rewe_failed",
        f"Die Abfrage beim REWE-Onlineshop ist fehlgeschlagen ({detail}).",
        error=detail,
    )


# ----------------------------------------------------------------------
# Parsers (tolerant: nested shop answers and flat shapes)
# ----------------------------------------------------------------------


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and (match := _NUMBER_RE.search(value)):
        return float(match.group().replace(",", "."))
    return None


def _in_range(price: float | None) -> float | None:
    if price is None or not _PRICE_RANGE[0] <= price <= _PRICE_RANGE[1]:
        return None
    return round(price, 2)


def cents_to_eur(value: Any) -> float | None:
    """REWE prices are cents: 199 -> 1.99 (None if not a plausible price)."""
    number = _number(value)
    return _in_range(number / 100) if number is not None else None


def flat_price(value: Any) -> float | None:
    """Price of a flat shape: an integer is cents (REWE style), a decimal number EUR.

    199 -> 1.99, 1.99 -> 1.99, "1,99 €" -> 1.99, "199 ct" -> 1.99.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return cents_to_eur(value)
    if isinstance(value, float):
        return _in_range(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text.endswith(("ct", "cent")):
            return cents_to_eur(text)
        return _in_range(_number(text))
    if isinstance(value, dict):
        for key in ("value", "amount", "price"):
            if key in value:
                return flat_price(value[key])
    return None


def parse_grammage(
    text: str | None, price: float | None = None
) -> tuple[tuple[float, str] | None, tuple[float, str] | None]:
    """'500g (1 kg = 3,98 €)' -> ((500.0, 'g'), (0.00398, 'g')): (pack, price per base unit).

    The pack is read before the brackets ('6x1,5l', '10 Stück', 'ca. 400g'); the base price
    from '(<amount> <unit> = <price> €)'. Without a base price but with pack and price the
    price per unit is computed.
    """
    if not text:
        return None, None
    text = str(text)
    head = text.split("(", 1)[0]
    pack = parse_pack_text(head) or (parse_pack_text(text) if "=" not in text else None)
    per: tuple[float, str] | None = None
    if match := _BASE_PRICE_RE.search(text):
        amount = float((match.group(1) or "1").replace(",", "."))
        unit = match.group(2).lower().rstrip(".")
        unit = {"liter": "l", "stück": "Stück", "stk": "Stück", "st": "Stück"}.get(unit, unit)
        base_price = float(match.group(3).replace(",", "."))
        base_amount, base = to_base(amount, unit)
        if base_amount and base_price > 0:
            per = (base_price / base_amount, base or "Stück")
    if per is None and pack and price:
        per = (price / pack[0], pack[1])
    return pack, per


def _base_price(pricing: dict[str, Any]) -> tuple[float, str] | None:
    """Price per base unit from basePrice (cents) and baseUnit ({"KGM": 1})."""
    base_price = cents_to_eur(pricing.get("basePrice"))
    unit = pricing.get("baseUnit")
    if base_price is None or not isinstance(unit, dict) or not unit:
        return None
    code, count = next(iter(unit.items()))
    factor = _UNIT_CODES.get(str(code).upper())
    amount = _number(count) or 1.0
    if factor is None or amount <= 0:
        return None
    return base_price / (factor[0] * amount), factor[1]


def _listing(raw: dict[str, Any]) -> dict[str, Any]:
    """The listing (price data) of the first article of a nested product."""
    articles = _dict(raw.get("_embedded")).get("articles")
    if isinstance(articles, list):
        for article in articles:
            if not isinstance(article, dict):
                continue
            listing = _dict(article.get("_embedded")).get("listing") or article.get("listing")
            if isinstance(listing, dict):
                return listing
    return {}


def _image(raw: dict[str, Any]) -> str | None:
    images = _dict(raw.get("media")).get("images")
    candidates: list[Any] = []
    if isinstance(images, list) and images:
        first = _dict(images[0])
        candidates.append(_dict(_dict(first.get("_links")).get("self")).get("href"))
        candidates.append(first.get("url"))
    candidates.extend(raw.get(k) for k in ("imageURL", "imageUrl", "image"))
    for url in candidates:
        if isinstance(url, str) and url.startswith("https://"):
            return url
    return None


def parse_product(raw: Any, query: str = "") -> dict[str, Any] | None:
    """One REWE product in the offer format (like offers.normalize_marktguru()).

    Nested: {id, productName, brand: {name}, _embedded: {articles: [{_embedded: {listing:
    {pricing: {currentRetailPrice (cents), grammage, basePrice, baseUnit, discount?}}}}]}}.
    Flat: {id, name | productName, price (int = cents, decimal = EUR) | currentRetailPrice,
    grammage}. Extra keys: product_id, regular_price (if the current price is reduced).
    """
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("productName") or raw.get("name") or raw.get("title") or "").strip()
    if not name:
        return None
    listing = _listing(raw)
    pricing = _dict(listing.get("pricing")) or _dict(raw.get("pricing"))
    price: float | None = None
    regular: float | None = None
    if "currentRetailPrice" in pricing:
        price = cents_to_eur(pricing.get("currentRetailPrice"))
        regular = cents_to_eur(
            pricing.get("regularRetailPrice")
            or _dict(pricing.get("discount")).get("regularPrice")
            or pricing.get("regularPrice")
        )
    elif "currentRetailPrice" in raw:
        price = cents_to_eur(raw.get("currentRetailPrice"))
        regular = cents_to_eur(raw.get("regularRetailPrice") or raw.get("regularPrice"))
    else:
        price = flat_price(raw.get("price"))
        regular = flat_price(raw.get("regular_price") or raw.get("regularPrice"))
    if price is None:
        return None
    grammage = str(
        pricing.get("grammage") or listing.get("grammage") or raw.get("grammage") or ""
    ).strip()
    pack, per = parse_grammage(grammage, price)
    if per is None:
        per = _base_price(pricing)
    if pack is None and (name_pack := parse_pack_text(name)):
        pack = name_pack
        per = per or (price / pack[0], pack[1])
    if pack is not None and not plausible_pack(*pack):
        pack = None
    brand = raw.get("brand")
    brand_name = str(_dict(brand).get("name") or (brand if isinstance(brand, str) else ""))
    product_id = str(
        raw.get("id")
        or raw.get("productId")
        or listing.get("id")
        or fold(name).replace(" ", "-")[:60]
    )
    return {
        "id": f"rewe_{product_id}",
        "product_id": product_id,
        "title": name,
        "product": name,
        "brand": brand_name.strip(),
        "description": grammage[:200],
        "store": "REWE",
        "store_id": RETAILER,
        "retailer": RETAILER,
        "price": price,
        "regular_price": regular if regular is not None and regular > price else None,
        "old_price": None,
        "unit_price": round(per[0], 6) if per else None,
        "base_unit": per[1] if per else None,
        "pack_amount": pack[0] if pack else None,
        "pack_unit": pack[1] if pack else None,
        "valid_from": None,
        "valid_to": None,
        "image": _image(raw),
        "loyalty": False,
        "source": SOURCE,
        "query": query,
    }


def _product_list(data: Any) -> list[Any] | None:
    """The raw products of an answer ([] = valid but empty, None = unknown structure)."""
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return None
    embedded = data.get("_embedded")
    if isinstance(embedded, dict) and isinstance(embedded.get("products"), list):
        return embedded["products"]
    for key in ("products", "items", "results"):
        if isinstance(data.get(key), list):
            return data[key]
    if isinstance(data.get("data"), dict):
        return _product_list(data["data"])
    if isinstance(embedded, dict) or "totalCount" in data or "pagination" in data:
        return []  # no hits
    return None


def parse_products(data: Any, query: str = "") -> list[dict[str, Any]]:
    """All products of a search answer. Raises ReweUnexpected for an unknown structure."""
    raw = _product_list(data)
    if raw is None:
        raise _failed("unerwartete Antwort", unexpected=True)
    products = [p for p in (parse_product(r, query) for r in raw) if p]
    if len(raw) >= 3 and not products:
        # several hits, none readable: the format changed (a single sold-out hit is fine)
        raise _failed("keine Preise in der Antwort", unexpected=True)
    return products


def _text(raw: dict[str, Any], *keys: str) -> str:
    address = _dict(raw.get("address"))
    for key in keys:
        for source in (raw, address):
            value = source.get(key)
            if isinstance(value, (str, int)) and str(value).strip():
                return str(value).strip()
    return ""


def parse_market(raw: Any) -> dict[str, Any] | None:
    """One REWE market: {id, name, street, postcode, city, label, lat, lon}."""
    if not isinstance(raw, dict):
        return None
    market_id = _text(raw, "wwIdent", "id", "marketId")
    if not market_id or not _MARKET_ID_RE.fullmatch(market_id):
        return None
    name = _text(raw, "companyName", "name", "marketHeadline") or "REWE"
    street = _text(raw, "contactStreet", "street")
    postcode = _text(raw, "contactZipCode", "zipCode", "postalCode", "zip")
    city = _text(raw, "contactCity", "city")
    location = _dict(raw.get("location")) or _dict(raw.get("geoLocation"))
    lat = _number(location.get("latitude", location.get("lat")))
    lon = _number(location.get("longitude", location.get("lon")))
    place = " ".join(p for p in (postcode, city) if p)
    return {
        "id": market_id,
        "name": name,
        "street": street,
        "postcode": postcode,
        "city": city,
        "label": ", ".join(p for p in (name, street, place) if p),
        "lat": lat if lat is not None and -90 <= lat <= 90 else None,
        "lon": lon if lon is not None and -180 <= lon <= 180 else None,
    }


def parse_markets(data: Any) -> list[dict[str, Any]]:
    """Markets of a market search answer (a list or {"markets": [...]}).

    Raises ReweUnexpected for an unknown structure.
    """
    raw: Any = data
    if isinstance(data, dict):
        raw = next(
            (data[k] for k in ("markets", "items", "results") if isinstance(data.get(k), list)),
            _dict(data.get("_embedded")).get("markets"),
        )
    if not isinstance(raw, list):
        raise _failed("unerwartete Antwort", unexpected=True)
    markets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        market = parse_market(item)
        if market is not None and market["id"] not in seen:
            seen.add(market["id"])
            markets.append(market)
    return markets


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
    are sold in is used.
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
        units = [c[4] for c in candidates]
        common = max(("g", "ml", "Stück"), key=units.count)
        preferred = [c for c in candidates if c[4] == common] or candidates
    best = min(preferred, key=lambda c: (c[0], c[1], len(c[2])))
    return best[3]


# ----------------------------------------------------------------------
# HTTP client
# ----------------------------------------------------------------------


class ReweClient:
    """Minimal client for the REWE web shop (honest User-Agent, JSON only)."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize."""
        self._session = async_get_clientsession(hass)

    async def async_get_json(self, url: str, params: dict[str, Any]) -> Any:
        """GET a JSON answer. Raises ReweBlocked, ReweUnexpected or ReweError."""
        try:
            async with self._session.get(
                url,
                params=params,
                headers=HEADERS,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                status = resp.status
                content_type = str(resp.headers.get("Content-Type") or "").lower()
                if status in (401, 403, 429):
                    raise _blocked(f"HTTP {status}")
                if status in (404, 410):
                    raise _failed(f"Schnittstelle nicht gefunden, HTTP {status}", unexpected=True)
                if status >= 400:
                    raise _failed(f"HTTP {status}")
                body = await resp.content.read(_MAX_BYTES)
        except TimeoutError as err:
            raise _failed("keine Antwort") from err
        except aiohttp.ClientError as err:
            raise _failed(str(err) or type(err).__name__) from err
        text = body.decode("utf-8", errors="replace").lstrip("﻿ \t\r\n")
        if "html" in content_type or text.startswith("<"):
            raise _blocked("Webseite statt Daten")
        try:
            return json.loads(text)
        except ValueError as err:
            raise _failed("keine lesbaren Daten", unexpected=True) from err

    async def async_search_products(self, term: str, market_id: str) -> list[dict[str, Any]]:
        """Products for a search term in one market (normalized, see parse_product())."""
        data = await self.async_get_json(
            SEARCH_URL,
            {
                "search": term,
                "market": market_id,
                "objectsPerPage": OBJECTS_PER_PAGE,
                "page": 1,
            },
        )
        return parse_products(data, term)

    async def async_search_markets(self, zip_code: str) -> list[dict[str, Any]]:
        """REWE markets near a postcode."""
        return parse_markets(await self.async_get_json(MARKETS_URL, {"searchTerm": zip_code}))


# ----------------------------------------------------------------------
# Status
# ----------------------------------------------------------------------


def rewe_enabled(manager: EssensplanerManager) -> bool:
    """True if the user enabled the (experimental) REWE online prices."""
    return bool(manager.options.get(CONF_REWE_ONLINE, DEFAULT_REWE_ONLINE))


def rewe_market(
    manager: EssensplanerManager, branch: dict[str, Any] | None = None
) -> tuple[dict[str, Any] | None, str | None]:
    """(branch, market id): the given REWE branch, else the first selected REWE branch
    (main branch first) with a market id."""
    candidates = [branch] if branch is not None else []
    candidates += manager.selected_branches()
    for candidate in candidates:
        if not candidate or candidate.get("retailer") != RETAILER:
            continue
        market_id = str(candidate.get("rewe_market_id") or "").strip()
        if market_id and _MARKET_ID_RE.fullmatch(market_id):
            return candidate, market_id
    return None, None


def _meta(manager: EssensplanerManager) -> dict[str, Any]:
    meta = manager.price_sources_meta.get(META_KEY)
    return meta if isinstance(meta, dict) else {}


def _parse_time(value: Any) -> datetime | None:
    return dt_util.parse_datetime(value) if isinstance(value, str) and value else None


def blocked_until(manager: EssensplanerManager, now: datetime | None = None) -> datetime | None:
    """End of the current backoff (None if requests are allowed)."""
    until = _parse_time(_meta(manager).get("blocked_until"))
    if until is None or until <= (now or dt_util.utcnow()):
        return None
    return until


def _date_text(value: datetime) -> str:
    return dt_util.as_local(value).strftime("%d.%m.%Y")


def _rewe_price_count(manager: EssensplanerManager) -> int:
    return sum(
        1
        for item in manager.store_prices_learned.get(RETAILER, {}).values()
        if item.get("source") == SOURCE
    )


def rewe_status(manager: EssensplanerManager) -> dict[str, Any]:
    """REWE online prices for the panel / services: stored status plus a German message.

    status: off (option off) | pending (never run) | ok | error | blocked.
    """
    meta = _meta(manager)
    enabled = rewe_enabled(manager)
    branch, market_id = rewe_market(manager)
    until = blocked_until(manager)
    status = str(meta.get("status") or STATUS_PENDING) if enabled else STATUS_OFF
    errors = [str(e) for e in meta.get("errors") or []][:MAX_ERRORS]
    last_success = _parse_time(meta.get("last_success"))
    prices = _rewe_price_count(manager)
    if not enabled:
        message = "REWE-Onlinepreise sind aus (experimentell, in den Optionen einschaltbar)."
    elif market_id is None:
        message = MSG_NO_MARKET
    elif until is not None:
        reason = (
            "Der REWE-Onlineshop hat automatische Abfragen abgelehnt"
            if status == STATUS_BLOCKED
            else "Unerwartete Antwort vom REWE-Onlineshop"
        )
        message = (
            f"{reason} – nächster Versuch ab {_date_text(until)}. "
            "Bisherige Preise bleiben erhalten."
        )
    elif status == STATUS_PENDING:
        message = "Noch nicht abgerufen – das passiert automatisch nachts."
    elif status != STATUS_OK:
        message = f"Letzter Abruf fehlgeschlagen: {errors[0] if errors else 'unbekannt'}"
    else:
        when = _date_text(last_success) if last_success else "?"
        message = f"Zuletzt am {when} aktualisiert: {meta.get('learned') or 0} Preise gelernt."
    return {
        "source": SOURCE,
        "experimental": True,
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
        "market_id": market_id,
        "branch_id": branch.get("id") if branch else None,
        "prices": prices,
    }


def _stale(manager: EssensplanerManager, now: datetime) -> bool:
    last = _parse_time(_meta(manager).get("last_success"))
    return last is None or now - last >= timedelta(days=REFRESH_DAYS)


def _record_block(manager: EssensplanerManager, err: ReweError, now: datetime) -> None:
    """Remember a refusal / unexpected answer: no requests for BLOCK_DAYS days."""
    meta = dict(_meta(manager))
    errors = [err.message, *[e for e in meta.get("errors") or [] if e != err.message]]
    meta.update(
        {
            "status": STATUS_BLOCKED if isinstance(err, ReweBlocked) else STATUS_ERROR,
            "last_run": now.isoformat(),
            "errors": errors[:MAX_ERRORS],
            "blocked_until": (now + timedelta(days=BLOCK_DAYS)).isoformat(),
        }
    )
    manager.price_sources_meta[META_KEY] = meta
    _LOGGER.warning(
        "REWE online prices (experimental) paused for %d days: %s", BLOCK_DAYS, err.message
    )


# ----------------------------------------------------------------------
# Refresh (weekly) and market search
# ----------------------------------------------------------------------


def refresh_terms(manager: EssensplanerManager) -> list[tuple[str, str]]:
    """(search term, ingredient key): the offer search terms plus open shopping items."""
    terms = list(manager.offer_search_terms(limit=MAX_TERMS))
    seen = {key for _, key in terms}
    extra = 0
    for item in manager.shopping:
        if item.get("status") == "completed" or extra >= MAX_SHOPPING_TERMS:
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


def _default_base(manager: EssensplanerManager, key: str) -> str | None:
    default = manager.defaults_index().lookup(key)
    per = unit_price(default) if default else None
    return per[1] if per else None


async def async_refresh_rewe_prices(
    hass: HomeAssistant, manager: EssensplanerManager, force: bool = False
) -> dict[str, Any]:
    """Learn REWE online prices for the planned / frequent ingredients. Returns rewe_status().

    Needs the option rewe_online_prices and a selected REWE branch with a market id.
    force=False only runs when the last success is older than REFRESH_DAYS. Never runs
    while blocked (also not with force). For each term the cheapest matching product is
    stored with learn_store_price("rewe", key, ..., "rewe_online", ref=product id).
    """
    if not rewe_enabled(manager):
        return rewe_status(manager)
    branch, market_id = rewe_market(manager)
    now = dt_util.utcnow()
    entry_id = manager.entry.entry_id
    if (
        market_id is None
        or blocked_until(manager, now) is not None
        or (not force and not _stale(manager, now))
        or entry_id in _RUNNING
    ):
        return rewe_status(manager)
    _RUNNING.add(entry_id)
    try:
        await _async_run(hass, manager, branch, market_id, now)
    finally:
        _RUNNING.discard(entry_id)
    manager._changed("prices")
    return rewe_status(manager)


async def _async_run(
    hass: HomeAssistant,
    manager: EssensplanerManager,
    branch: dict[str, Any] | None,
    market_id: str,
    now: datetime,
) -> None:
    previous = dict(_meta(manager))
    client = ReweClient(hass)
    errors: list[str] = []
    requests = succeeded = found = learned = failures = 0
    stop: ReweError | None = None
    for term, key in refresh_terms(manager):
        if requests and REQUEST_DELAY > 0:
            await asyncio.sleep(REQUEST_DELAY)  # be polite to the shop
        requests += 1
        try:
            products = await client.async_search_products(term, market_id)
        except (ReweBlocked, ReweUnexpected) as err:
            stop = err
            break
        except ReweError as err:
            errors.append(f"{term}: {err.message}")
            failures += 1
            if not succeeded or failures >= MAX_FAILURES:
                break  # the shop is not reachable: try again on the next check
            continue
        succeeded += 1
        failures = 0
        product = best_product(products, key, _default_base(manager, key))
        if product is None:
            continue
        found += 1
        pack = offer_pack(product)
        if pack and manager.learn_store_price(
            RETAILER,
            key,
            product["product"],
            learn_price(product),
            pack[0],
            pack[1],
            SOURCE,
            ref=product["product_id"],
        ):
            learned += 1
    meta = {
        **previous,
        "status": STATUS_OK if succeeded else STATUS_ERROR,
        "last_run": now.isoformat(),
        "searched": requests,
        "errors": errors[:MAX_ERRORS],
        "blocked_until": None,
        "market_id": market_id,
        "branch_id": branch.get("id") if branch else None,
    }
    if succeeded and stop is None:
        meta.update({"last_success": now.isoformat(), "count": found, "learned": learned})
    manager.price_sources_meta[META_KEY] = meta
    if stop is not None:
        _record_block(manager, stop, now)  # prices learned before the refusal are kept
    elif errors and not succeeded:
        _LOGGER.debug("REWE online prices: %s", "; ".join(errors))


async def async_find_rewe_markets(
    hass: HomeAssistant, manager: EssensplanerManager, zip_code: str | None = None
) -> dict[str, Any]:
    """REWE markets near a postcode (explicit user action, also with the option off).

    zip_code default: the postcode of the first REWE branch, else the zip_code option.
    Returns {zip_code, markets: [{id, name, street, postcode, city, label, lat, lon,
    branch_id (REWE branch already using this market) | None}]}.
    """
    from .manager import _error  # avoid an import cycle

    text = str(zip_code or "").strip()
    if text:
        postcode = valid_postcode(text)
        if postcode is None:
            raise _error("invalid_postcode", postcode=text)
    else:
        rewe_branches = [
            b for b in manager.selected_branches() if b.get("retailer") == RETAILER
        ] + [b for b in manager.branches if b.get("retailer") == RETAILER]
        postcode = next(
            (p for b in rewe_branches if (p := valid_postcode(b.get("postcode")))), None
        ) or valid_postcode(manager.zip_code)
        if postcode is None:
            raise _error("rewe_postcode_required")
    markets = await ReweClient(hass).async_search_markets(postcode)
    linked = {
        str(b.get("rewe_market_id") or ""): b.get("id")
        for b in manager.branches
        if b.get("retailer") == RETAILER and b.get("rewe_market_id")
    }
    for market in markets:
        market["branch_id"] = linked.get(market["id"])
    markets.sort(key=lambda m: (m["postcode"] != postcode, m["branch_id"] is None))
    return {"zip_code": postcode, "markets": markets[:MAX_MARKETS]}


# ----------------------------------------------------------------------
# Live article search (articles.register_live_provider)
# ----------------------------------------------------------------------


async def async_rewe_live(
    manager: EssensplanerManager,
    query: str,
    branch: dict[str, Any] | None,
    retailer: str | None,
) -> list[dict[str, Any]]:
    """REWE online shop articles for the "Artikel hinzufügen" field (cached 1 h, throttled)."""
    if not rewe_enabled(manager):
        return []
    _, market_id = rewe_market(manager, branch)
    if market_id is None:
        raise OfferError(MSG_NO_MARKET)

    async def fetch() -> list[dict[str, Any]]:
        if (until := blocked_until(manager)) is not None:
            raise OfferError(f"REWE-Onlinepreise pausiert bis {_date_text(until)}.")
        try:
            return await ReweClient(manager.hass).async_search_products(query, market_id)
        except ReweError as err:
            if isinstance(err, (ReweBlocked, ReweUnexpected)):
                _record_block(manager, err, dt_util.utcnow())
                manager._changed("price_sources")
            raise OfferError(err.message) from err

    return await cached_live_fetch(manager, (fold(query).strip(), f"rewe:{market_id}"), fetch)
