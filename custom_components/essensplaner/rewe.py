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

The refresh, status, backoff and live search are shared with the other online sources
(online_prices.OnlinePriceSource); this module is the REWE adapter (market id, product
search, parsers) and keeps its 1.3 functions.

Status in manager.price_sources_meta["rewe"]: {status (ok|error|blocked), last_run,
last_success, count, learned, searched, errors (<= 5), blocked_until, market_id,
branch_id}; rewe_status() adds "off" (option off) and "pending" (never run).

Learned prices go to the REWE price list (learn_store_price("rewe", key, ...,
source "rewe_online")): the cheapest matching article per ingredient (price per kg / l /
piece), refreshed weekly (daily check at 04:xx in __init__.py). There is no public list of
all offers of a REWE market (checked 11/2026: the offers pages answer automated requests
with a bot check, stationary-app-offers is gone) – REWE offers come from marktguru.
"""

from __future__ import annotations

from datetime import datetime
import logging
import re
import sys
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .articles import parse_pack_text
from .const import CONF_REWE_ONLINE, DEFAULT_REWE_ONLINE
from .ingredients import fold, to_base
from .online_prices import (
    HEADERS as HEADERS,
    STATUS_BLOCKED as STATUS_BLOCKED,
    STATUS_ERROR as STATUS_ERROR,
    STATUS_OFF as STATUS_OFF,
    STATUS_OK as STATUS_OK,
    STATUS_PENDING as STATUS_PENDING,
    OnlinePriceSource,
    SourceBlocked,
    SourceError,
    SourceUnexpected,
    async_get_json,
    best_product as best_product,
    cents_to_eur as cents_to_eur,
    dict_of,
    in_range,
    learn_price as learn_price,
    number,
    product_matches as product_matches,
    refresh_terms as _refresh_terms,
)
from .pricing import plausible_pack
from .stores import valid_postcode

if TYPE_CHECKING:
    from .manager import EssensplanerManager

_LOGGER = logging.getLogger(__name__)

# the web shop's own JSON interfaces (checked 11/2026: shop.rewe.de/api redirects here,
# prices only come with a market *and* a service type; the old marketsearch is gone)
SEARCH_URL = "https://www.rewe.de/shop/api/products"
SERVICE_TYPE = "PICKUP"
MARKETS_URL = "https://www.rewe.de/api/wksmarketsearch"
PICKUP_MARKETS_URL = "https://www.rewe.de/shop/api/marketselection/zipcodes/{zip}/services/pickup"
# a stored error / pause of an older client version does not count (the interface moved)
CLIENT_VERSION = 2

RETAILER = "rewe"
SOURCE = "rewe_online"
META_KEY = "rewe"

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
# a market that returns no articles at all (wrong market id): try again after a day
NO_ARTICLES_DAYS = 1
# searches without any article in a row after which the market id is considered wrong
NO_ARTICLE_SEARCHES = 5
# a manual refresh (button, service) runs at most once in this many hours after a success
MANUAL_MIN_HOURS = 6
MAX_ERRORS = 5
# a refresh stops after this many failed searches in a row
MAX_FAILURES = 3
MAX_MARKETS = 25
MAX_BYTES = 4 * 1024 * 1024

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


class ReweError(SourceError):
    """A REWE request failed (translation key + German message)."""


class ReweBlocked(ReweError, SourceBlocked):
    """REWE refused automated requests (HTTP 401/403/429, HTML page instead of data)."""


class ReweUnexpected(ReweError, SourceUnexpected):
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


_dict = dict_of
_number = number
_in_range = in_range


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
    location = _dict(raw.get("location")) or _dict(raw.get("geoLocation")) or raw
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
        return await async_get_json(
            self._session,
            url,
            params,
            _blocked,
            _failed,
            timeout=REQUEST_TIMEOUT,
            max_bytes=MAX_BYTES,
        )

    async def async_search_products(self, term: str, market_id: str) -> list[dict[str, Any]]:
        """Products for a search term in one market (normalized, see parse_product())."""
        data = await self.async_get_json(
            SEARCH_URL,
            {
                "search": term,
                "market": market_id,
                "serviceTypes": SERVICE_TYPE,
                "objectsPerPage": OBJECTS_PER_PAGE,
                "page": 1,
            },
        )
        return parse_products(data, term)

    async def async_search_markets(self, zip_code: str) -> list[dict[str, Any]]:
        """REWE markets near a postcode (market search, else the pickup market list)."""
        try:
            markets = parse_markets(
                await self.async_get_json(MARKETS_URL, {"searchTerm": zip_code})
            )
        except ReweBlocked:
            raise
        except ReweError as err:
            _LOGGER.debug("REWE market search failed (%s), trying the pickup list", err.message)
            markets = []
        if markets:
            return markets
        return parse_markets(await self.async_get_json(PICKUP_MARKETS_URL.format(zip=zip_code), {}))


# ----------------------------------------------------------------------
# The source (status, weekly refresh, live search: online_prices.OnlinePriceSource)
# ----------------------------------------------------------------------


class ReweSource(OnlinePriceSource):
    """The REWE online shop for the REWE branch with a market id."""

    key = META_KEY
    retailer = RETAILER
    source = SOURCE
    option = CONF_REWE_ONLINE
    option_default = DEFAULT_REWE_ONLINE
    store_field = "market_id"
    title = "REWE-Onlinepreise"
    site = "Der REWE-Onlineshop"
    site_from = "vom REWE-Onlineshop"
    log_name = "REWE online prices"

    def target(
        self, manager: EssensplanerManager, branch: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str | None]:
        """The given REWE branch, else the first selected one (main first) with a market id."""
        return rewe_market(manager, branch)

    def no_target_message(self, manager: EssensplanerManager) -> str:
        """No REWE branch with a market id."""
        return MSG_NO_MARKET

    def make_client(self, hass: HomeAssistant) -> ReweClient:
        """The REWE web shop client."""
        return ReweClient(hass)

    async def async_search(
        self, client: ReweClient, term: str, store_id: str
    ) -> list[dict[str, Any]]:
        """Products for a term in the market."""
        return await client.async_search_products(term, store_id)

    def no_articles_error(self, store_id: str) -> SourceError:
        """Every search of the market came back empty: the market id is wrong."""
        return ReweUnexpected(
            "rewe_failed",
            f"Der REWE-Markt {store_id} liefert keine Artikel – bitte bei der "
            "REWE-Filiale „Markt suchen“ und den Markt neu wählen",
            error=f"Markt {store_id} liefert keine Artikel",
        )


SOURCE_REWE = ReweSource(sys.modules[__name__])


def rewe_enabled(manager: EssensplanerManager) -> bool:
    """True if the user enabled the (experimental) REWE online prices."""
    return SOURCE_REWE.enabled(manager)


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


def blocked_until(manager: EssensplanerManager, now: datetime | None = None) -> datetime | None:
    """End of the current backoff (None if requests are allowed)."""
    return SOURCE_REWE.blocked_until(manager, now)


def rewe_status(manager: EssensplanerManager) -> dict[str, Any]:
    """REWE online prices for the panel / services: stored status plus a German message.

    status: off (option off) | pending (never run) | ok | error | blocked.
    """
    return SOURCE_REWE.status(manager)


def refresh_terms(manager: EssensplanerManager) -> list[tuple[str, str]]:
    """(search term, ingredient key): the offer search terms plus open shopping items."""
    return _refresh_terms(manager, MAX_TERMS, MAX_SHOPPING_TERMS)


async def async_refresh_rewe_prices(
    hass: HomeAssistant, manager: EssensplanerManager, force: bool = False
) -> dict[str, Any]:
    """Learn REWE online prices for the planned / frequent ingredients. Returns rewe_status().

    Needs the option rewe_online_prices and a selected REWE branch with a market id.
    force=False only runs when the last success is older than REFRESH_DAYS; force=True
    (button, service) runs at most once per MANUAL_MIN_HOURS after a success for the same
    market (else the status with cooldown_until and a message). Never runs while blocked
    (also not with force). For each term the cheapest matching product is
    stored with learn_store_price("rewe", key, ..., "rewe_online", ref=product id).
    """
    return await SOURCE_REWE.async_refresh(hass, manager, force)


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
    return await SOURCE_REWE.async_live(manager, query, branch, retailer)
