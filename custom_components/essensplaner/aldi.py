"""EXPERIMENTAL: regular prices and weekly offers of ALDI SÜD (api.aldi-sued.de).

Off by default (option aldi_online_prices). Uses the JSON interface the aldi-sued.de web
site uses in a browser (checked 11/2026 with the honest User-Agent, no login):
- service points (stores): SERVICE_POINTS_URL?latitude=..&longitude=..&radius=..&limit=..
  (the nearest one to the ALDI SÜD branch, else to the home zone; prices are the same in a
  region, one store is enough)
- product search: SEARCH_URL?currency=EUR&serviceType=walk-in&servicePoint=<id>&q=<term>
  &limit=<12|16|24|30|32|48|60>&offset=0&sort=relevance
- weekly offers: the same search with categoryKey=<"Wochenangebote" of the category tree>
Prices are cents (price.amountRelevant), the base price is price.comparison with
comparisonDisplay ("4,60 €/1 kg"), the bottle deposit (price.bottleDeposit) is never part of
the price. A product with price.wasPriceDisplay is reduced right now: its was-price is
learned as the regular price and the reduced price becomes a current offer of the searched
ingredient (source "aldi_online", until the end of the leaflet week).

Not documented; may change or refuse automated requests at any time. Same rules as the REWE
source (online_prices.py): HTTP 401/403/429 or a web page = blocked, an unexpected answer
(also {errors: [...]} with HTTP 200, or HTTP 400 for a rejected query) = error, both pause
the source for BLOCK_DAYS days; learned prices are kept.

Status in manager.price_sources_meta["aldi"] (like REWE, store field "service_point").
The service point is stored on the branch (aldi_service_point, like rewe_market_id).
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import sys
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .const import CONF_ALDI_ONLINE, DEFAULT_ALDI_ONLINE
from .ingredients import fold, to_base
from .offers import _parse_count, leaflet_week_end, parse_pack_text
from .online_prices import (
    OnlinePriceSource,
    SourceBlocked,
    SourceError,
    SourceUnexpected,
    async_get_json,
    cents_to_eur,
    dict_of,
    number,
)
from .pricing import format_eur, plausible_pack
from .retailers import ALDI_SUED
from .stores import valid_postcode

if TYPE_CHECKING:
    from .manager import EssensplanerManager

_LOGGER = logging.getLogger(__name__)

API = "https://api.aldi-sued.de"
SERVICE_POINTS_URL = f"{API}/v2/service-points"
SEARCH_URL = f"{API}/v3/product-search"
CATEGORY_TREE_URL = f"{API}/v2/product-category-tree"
SERVICE_TYPE = "walk-in"
# "Wochenangebote" in the category tree (11/2026); looked up again by its slug if it moves
WEEKLY_CATEGORY = "1588161426582123"
WEEKLY_SLUG = "wochenangebote"
CLIENT_VERSION = 1

RETAILER = ALDI_SUED
SOURCE = "aldi_online"
META_KEY = "aldi"
STORE_NAME = "ALDI SÜD"

# seconds between two requests of a refresh (tests set 0)
REQUEST_DELAY = 2.0
REQUEST_TIMEOUT = 20
# results per search: the interface only accepts 12, 16, 24, 30, 32, 48 or 60
SEARCH_LIMIT = 24
PAGE_LIMIT = 60
MAX_WEEKLY_PAGES = 4
MAX_TERMS = 40
MAX_SHOPPING_TERMS = 20
REFRESH_DAYS = 7
BLOCK_DAYS = 7
NO_ARTICLES_DAYS = 1
NO_ARTICLE_SEARCHES = 5
MANUAL_MIN_HOURS = 6
MAX_ERRORS = 5
MAX_FAILURES = 3
MAX_BYTES = 4 * 1024 * 1024
# service point search: radius (km) and number of stores
STORE_RADIUS_KM = 25
# decimals of the coordinates sent for the store lookup: about 1 km for the home location
# (a "nearest store" query needs no more), about 100 m for a store's own location
HOME_PRECISION = 2
STORE_PRECISION = 3
MAX_STORES = 10

MSG_NO_STORE = (
    "Für ALDI SÜD ist keine Filiale bekannt – füge im Panel unter „🏪 Läden & Preise“ deine "
    "ALDI-SÜD-Filiale hinzu (am besten aus der Kartensuche, dann wird die nächste Filiale "
    "automatisch bestimmt) oder wähle sie mit „ALDI-SÜD-Filiale suchen“."
)

_SERVICE_POINT_RE = re.compile(r"^[A-Za-z0-9_-]{2,16}$")
_DISPLAY_PRICE_RE = re.compile(r"(\d+(?:[.,]\d{1,2})?)\s*€")
# comparisonDisplay "4,60 €/1 kg", "0,95 €/1 l", "2,23 €/1 l" (not "0,02 €/1 M")
_COMPARISON_RE = re.compile(
    r"/\s*(\d+(?:[.,]\d+)?)?\s*(kg|g|ml|l|stück|stk|st)\b\.?", re.IGNORECASE
)
# "Kleine Schätze Zitronen, Stück", "je Stück", "Klasse I, Stück": one piece
_SINGLE_PIECE_RE = re.compile(r"(?:^|[\s,])(?:je\s+)?st(?:ü|ue)ck\b", re.IGNORECASE)


class AldiError(SourceError):
    """An ALDI SÜD request failed (translation key + German message)."""


class AldiBlocked(AldiError, SourceBlocked):
    """ALDI SÜD refused automated requests (HTTP 401/403/429, web page instead of data)."""


class AldiUnexpected(AldiError, SourceUnexpected):
    """The answer did not have the expected structure (interface changed?)."""


def _blocked(detail: str) -> AldiBlocked:
    return AldiBlocked(
        "aldi_blocked",
        f"Die ALDI-SÜD-Website lässt gerade keine automatischen Abfragen zu ({detail}).",
        error=detail,
    )


def _failed(detail: str, unexpected: bool = False) -> AldiError:
    cls = AldiUnexpected if unexpected else AldiError
    return cls(
        "aldi_failed",
        f"Die Abfrage bei ALDI SÜD ist fehlgeschlagen ({detail}).",
        error=detail,
    )


# ----------------------------------------------------------------------
# Parsers
# ----------------------------------------------------------------------


def _plausible(pack: tuple[float, str]) -> bool:
    """Weights, volumes and counts within the sanity limits; washing loads and rolls as
    given."""
    return pack[1] not in ("g", "ml", "Stück") or plausible_pack(*pack)


def single_piece(text: str | None) -> tuple[float, str] | None:
    """(1, 'Stück') for an article sold per piece without a count ('Zitronen, Stück')."""
    return (1.0, "Stück") if text and _SINGLE_PIECE_RE.search(text) else None


def display_price(text: Any) -> float | None:
    """'1,19 €' -> 1.19."""
    match = _DISPLAY_PRICE_RE.search(str(text or ""))
    return number(match.group(1)) if match else None


def _brand(value: Any) -> str:
    """'MILSANI' -> 'Milsani', '· FAIR&GUT ·' -> 'Fair&Gut', 'DR. OETKER' -> 'Dr. Oetker'."""
    text = re.sub(r"\s+", " ", str(value or "").replace("·", " ")).strip()
    if text.isupper():
        # every part of a word upper case first: "COCA-COLA" -> "Coca-Cola"
        text = re.sub(r"[^\W\d_]+", lambda m: m.group().capitalize(), text.lower())
        text = re.sub(r"(\w)'S\b", r"\1's", text)  # "Kellogg'S" -> "Kellogg's"
    return text


def _comparison(price: dict[str, Any]) -> tuple[float, str] | None:
    """Base price per g / ml / piece from comparison (cents) and comparisonDisplay."""
    value = cents_to_eur(price.get("comparison"))
    match = _COMPARISON_RE.search(str(price.get("comparisonDisplay") or ""))
    if value is None or match is None:
        return None
    amount = number(match.group(1)) or 1.0
    unit = match.group(2).lower()
    unit = {"stück": "Stück", "stk": "Stück", "st": "Stück"}.get(unit, unit)
    base_amount, base = to_base(amount, unit)
    if not base_amount:
        return None
    return value / base_amount, base or "Stück"


def _image(raw: dict[str, Any]) -> str | None:
    for asset in raw.get("assets") or []:
        url = dict_of(asset).get("url")
        if isinstance(url, str) and url.startswith("https://"):
            slug = str(raw.get("urlSlugText") or "produkt")
            return url.replace("{width}", "300").replace("{slug}", slug)
    return None


def parse_product(raw: Any, query: str = "") -> dict[str, Any] | None:
    """One ALDI SÜD product in the offer format (like rewe.parse_product()).

    {sku, name ("Deutsche Markenbutter 250 g"), brandName, sellingSize ("250 g" | None),
    price: {amount, amountRelevant (cents), comparison (cents), comparisonDisplay,
    wasPriceDisplay ("1,19 €" while reduced), bottleDeposit (cents)}, categories, assets}.
    Extra keys: product_id (sku), regular_price (was-price while reduced), deposit (EUR),
    categories (names). The deposit is never part of the price.
    """
    if not isinstance(raw, dict) or raw.get("discontinued"):
        return None
    name = re.sub(r"\s+", " ", str(raw.get("name") or "")).strip()
    if not name:
        return None
    pricing = dict_of(raw.get("price"))
    price = cents_to_eur(pricing.get("amountRelevant") or pricing.get("amount"))
    if price is None:
        return None
    was = display_price(pricing.get("wasPriceDisplay"))
    size = str(raw.get("sellingSize") or "").strip()
    pack = (
        parse_pack_text(size) or parse_pack_text(name) or _parse_count(name) or single_piece(name)
    )
    if pack is not None and not _plausible(pack):
        pack = None
    per = _comparison(pricing)
    if per is None and pack:
        per = (price / pack[0], pack[1])
    deposit = cents_to_eur(pricing.get("bottleDeposit"))
    brand = _brand(raw.get("brandName"))
    title = f"{brand} {name}" if brand and fold(brand) not in fold(name) else name
    description = size
    if deposit:
        note = f"zzgl. {format_eur(deposit)} Pfand"
        description = f"{description} · {note}" if description else note
    sku = str(raw.get("sku") or "").strip() or fold(name).replace(" ", "-")[:60]
    categories = [
        str(c["name"]) for c in raw.get("categories") or [] if isinstance(c, dict) and c.get("name")
    ]
    return {
        "id": f"aldi_{sku}",
        "product_id": sku,
        "title": title,
        "product": name,
        "brand": brand,
        "description": description[:200],
        "store": STORE_NAME,
        "store_id": RETAILER,
        "retailer": RETAILER,
        "price": price,
        "regular_price": was if was is not None and was > price else None,
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
        "deposit": deposit,
        "categories": categories[:3],
    }


def _raw_list(data: Any) -> list[Any]:
    """The raw products of a search answer. Raises AldiUnexpected for another structure."""
    raw = data.get("data") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        raise _failed("unerwartete Antwort", unexpected=True)
    return raw


def parse_products(data: Any, query: str = "") -> list[dict[str, Any]]:
    """All products of a search answer ({meta, data: [...]})."""
    raw = _raw_list(data)
    products = [p for p in (parse_product(r, query) for r in raw) if p]
    if len(raw) >= 3 and not products:
        raise _failed("keine Preise in der Antwort", unexpected=True)
    return products


def total_count(data: Any) -> int:
    """meta.pagination.totalCount of a search answer (0 if missing)."""
    pagination = dict_of(dict_of(dict_of(data).get("meta")).get("pagination"))
    try:
        return int(pagination.get("totalCount") or 0)
    except (TypeError, ValueError):
        return 0


def parse_service_point(raw: Any) -> dict[str, Any] | None:
    """One store: {id, name, street, postcode, city, label, lat, lon, distance_km}."""
    if not isinstance(raw, dict):
        return None
    store_id = str(raw.get("id") or "").strip()
    if not _SERVICE_POINT_RE.fullmatch(store_id):
        return None
    address = dict_of(raw.get("address"))
    street = str(address.get("address1") or raw.get("name") or "").strip()
    postcode = str(address.get("zipCode") or "").strip()
    city = str(address.get("city") or "").strip()
    lat = number(address.get("latitude"))
    lon = number(address.get("longitude"))
    place = " ".join(p for p in (postcode, city) if p)
    distance = number(raw.get("distance"))
    return {
        "id": store_id,
        "name": STORE_NAME,
        "street": street,
        "postcode": postcode,
        "city": city,
        "label": ", ".join(p for p in (STORE_NAME, street, place) if p),
        "lat": lat if lat is not None and -90 <= lat <= 90 else None,
        "lon": lon if lon is not None and -180 <= lon <= 180 else None,
        "distance_km": round(distance, 1) if distance is not None else None,
    }


def parse_service_points(data: Any) -> list[dict[str, Any]]:
    """Stores of a service point answer ({data: [...]}), duplicates dropped."""
    raw = _raw_list(data)
    stores: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        store = parse_service_point(item)
        if store is not None and store["id"] not in seen:
            seen.add(store["id"])
            stores.append(store)
    return stores


def weekly_category(data: Any) -> str | None:
    """Key of the "Wochenangebote" category in a category tree answer."""
    stack = list(dict_of(data).get("data") or [])
    while stack:
        node = dict_of(stack.pop(0))
        if str(node.get("urlSlugText") or "") == WEEKLY_SLUG or fold(
            str(node.get("name") or "")
        ) == fold("Wochenangebote"):
            return str(node.get("key") or "") or None
        stack.extend(node.get("children") or [])
    return None


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great circle distance."""
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((rlat2 - rlat1) / 2) ** 2
        + math.cos(rlat1) * math.cos(rlat2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 6371.0 * 2 * math.asin(math.sqrt(min(1.0, a)))


# ----------------------------------------------------------------------
# HTTP client
# ----------------------------------------------------------------------


class AldiClient:
    """Minimal client for the ALDI SÜD web site interface (honest User-Agent, JSON only)."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize."""
        self._session = async_get_clientsession(hass)

    async def async_get_json(self, url: str, params: dict[str, Any]) -> Any:
        """GET a JSON answer. Raises AldiBlocked, AldiUnexpected or AldiError.

        A rejected query (HTTP 400) and {errors: [...]} (also with HTTP 200) are
        unexpected: the interface changed, the source pauses.
        """
        data = await async_get_json(
            self._session,
            url,
            params,
            _blocked,
            _failed,
            timeout=REQUEST_TIMEOUT,
            max_bytes=MAX_BYTES,
            unexpected_status=(400, 404, 410),
        )
        if isinstance(data, dict) and data.get("errors"):
            first = dict_of((data["errors"] or [{}])[0])
            detail = str(first.get("code") or first.get("message") or "Fehler")
            raise _failed(f"Fehler {detail}", unexpected=True)
        return data

    async def async_service_points(
        self, lat: float, lon: float, precision: int = STORE_PRECISION
    ) -> list[dict[str, Any]]:
        """ALDI SÜD stores near a location, nearest first (the location is sent rounded to
        `precision` decimals; the distances are computed here with the exact one)."""
        stores = parse_service_points(
            await self.async_get_json(
                SERVICE_POINTS_URL,
                {
                    "latitude": round(lat, precision),
                    "longitude": round(lon, precision),
                    "radius": STORE_RADIUS_KM,
                    "limit": MAX_STORES,
                    "offset": 0,
                },
            )
        )
        for store in stores:
            if store["lat"] is not None and store["lon"] is not None:
                store["distance_km"] = round(_distance_km(lat, lon, store["lat"], store["lon"]), 1)
        stores.sort(key=lambda s: (s["distance_km"] is None, s["distance_km"] or 0))
        return stores

    def _search_params(self, service_point: str, **extra: Any) -> dict[str, Any]:
        return {
            "currency": "EUR",
            "serviceType": SERVICE_TYPE,
            "servicePoint": service_point,
            **extra,
            "sort": "relevance",
        }

    async def async_search_products(
        self, term: str, service_point: str, limit: int = SEARCH_LIMIT
    ) -> list[dict[str, Any]]:
        """Products for a search term (normalized, see parse_product())."""
        data = await self.async_get_json(
            SEARCH_URL,
            self._search_params(service_point, q=term, limit=limit, offset=0),
        )
        return parse_products(data, term)

    async def async_category_page(self, category: str, service_point: str, offset: int = 0) -> Any:
        """One page (PAGE_LIMIT products) of a category, the raw answer."""
        return await self.async_get_json(
            SEARCH_URL,
            self._search_params(
                service_point, categoryKey=category, limit=PAGE_LIMIT, offset=offset
            ),
        )

    async def async_weekly_category(self, service_point: str) -> str | None:
        """The key of "Wochenangebote" in the category tree."""
        return weekly_category(
            await self.async_get_json(
                CATEGORY_TREE_URL, {"serviceType": SERVICE_TYPE, "servicePoint": service_point}
            )
        )


# ----------------------------------------------------------------------
# The source
# ----------------------------------------------------------------------


def home_location(hass: HomeAssistant) -> tuple[float, float] | None:
    """Coordinates of zone.home (else the Home Assistant location)."""
    state = hass.states.get("zone.home")
    lat = number(state.attributes.get("latitude")) if state else None
    lon = number(state.attributes.get("longitude")) if state else None
    if lat is None or lon is None:
        lat, lon = number(hass.config.latitude), number(hass.config.longitude)
    if lat is None or lon is None or (lat == 0 and lon == 0):
        return None
    return lat, lon


def aldi_branch(
    manager: EssensplanerManager, branch: dict[str, Any] | None = None
) -> tuple[dict[str, Any] | None, str | None]:
    """(branch, service point): the given ALDI SÜD branch, else the first selected one
    (main branch first); the service point is None while none is stored."""
    candidates = [branch] if branch is not None else []
    candidates += manager.selected_branches()
    found = [c for c in candidates if c and c.get("retailer") == RETAILER]
    for candidate in found:
        point = str(candidate.get("aldi_service_point") or "").strip()
        if point and _SERVICE_POINT_RE.fullmatch(point):
            return candidate, point
    return (found[0] if found else None), None


def _location(hass: HomeAssistant, branch: dict[str, Any]) -> tuple[float, float, int] | None:
    """(lat, lon, decimals to send) of a branch: its own location, else the home's (sent
    rounded to about 1 km)."""
    lat, lon = number(branch.get("lat")), number(branch.get("lon"))
    if lat is not None and lon is not None:
        return lat, lon, STORE_PRECISION
    home = home_location(hass)
    return (*home, HOME_PRECISION) if home is not None else None


class AldiSource(OnlinePriceSource):
    """ALDI SÜD prices for the ALDI SÜD branch (nearest service point)."""

    key = META_KEY
    retailer = RETAILER
    source = SOURCE
    option = CONF_ALDI_ONLINE
    option_default = DEFAULT_ALDI_ONLINE
    store_field = "service_point"
    title = "ALDI-SÜD-Onlinepreise"
    site = "Die ALDI-SÜD-Website"
    site_from = "von der ALDI-SÜD-Website"
    log_name = "ALDI SÜD online prices"
    offer_source = SOURCE

    def target(
        self, manager: EssensplanerManager, branch: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str | None]:
        """The ALDI SÜD branch and its stored service point."""
        return aldi_branch(manager, branch)

    def has_target(self, manager: EssensplanerManager) -> bool:
        """An ALDI SÜD branch with a service point, or one that can be looked up."""
        branch, point = aldi_branch(manager)
        return point is not None or (
            branch is not None and _location(manager.hass, branch) is not None
        )

    async def async_target(
        self, hass: HomeAssistant, manager: EssensplanerManager, branch: dict[str, Any] | None
    ) -> tuple[dict[str, Any] | None, str | None]:
        """The stored service point, else the nearest one (stored on the branch)."""
        found, point = aldi_branch(manager, branch)
        if point is not None or found is None:
            return found, point
        location = _location(hass, found)
        if location is None:
            return found, None
        stores = await AldiClient(hass).async_service_points(
            location[0], location[1], precision=location[2]
        )
        if not stores:
            raise _failed("keine ALDI-SÜD-Filiale in der Nähe")
        nearest = stores[0]
        _LOGGER.debug("ALDI SÜD service point %s for branch %s", nearest["id"], found.get("id"))
        saved = manager.save_branch({"id": found["id"], "aldi_service_point": nearest["id"]})
        meta = dict(self.meta(manager))
        meta["store_label"] = nearest["label"]
        manager.price_sources_meta[self.key] = meta
        return manager.get_branch(saved["id"]) or found, nearest["id"]

    def no_target_message(self, manager: EssensplanerManager) -> str:
        """No ALDI SÜD branch (or none whose location is known)."""
        return MSG_NO_STORE

    def make_client(self, hass: HomeAssistant) -> AldiClient:
        """The ALDI SÜD client."""
        return AldiClient(hass)

    async def async_search(
        self, client: AldiClient, term: str, store_id: str
    ) -> list[dict[str, Any]]:
        """Products for a term at the service point."""
        return await client.async_search_products(term, store_id)

    def no_articles_error(self, store_id: str) -> SourceError:
        """Every search came back empty: the service point is wrong."""
        return AldiUnexpected(
            "aldi_failed",
            f"Die ALDI-SÜD-Filiale {store_id} liefert keine Artikel – bitte bei der "
            "ALDI-SÜD-Filiale „Filiale suchen“ und eine andere wählen",
            error=f"Filiale {store_id} liefert keine Artikel",
        )

    def ok_message(self, meta: dict[str, Any], when: str) -> str:
        """Learned prices and reduced articles."""
        text = super().ok_message(meta, when)
        offers = int(meta.get("offers") or 0)
        if offers:
            text = f"{text[:-1]}, {offers} reduzierte Artikel als Angebot."
        return text

    def status_extra(self, manager: EssensplanerManager, meta: dict[str, Any]) -> dict[str, Any]:
        """Reduced articles of the last refresh and the store label."""
        return {"offers": int(meta.get("offers") or 0), "store_label": meta.get("store_label")}


SOURCE_ALDI = AldiSource(sys.modules[__name__])


def aldi_enabled(manager: EssensplanerManager) -> bool:
    """True if the user enabled the (experimental) ALDI SÜD online prices."""
    return SOURCE_ALDI.enabled(manager)


def aldi_status(manager: EssensplanerManager) -> dict[str, Any]:
    """ALDI SÜD online prices for the panel / services (like rewe_status())."""
    return SOURCE_ALDI.status(manager)


async def async_refresh_aldi_prices(
    hass: HomeAssistant, manager: EssensplanerManager, force: bool = False
) -> dict[str, Any]:
    """Learn ALDI SÜD prices for the planned / frequent ingredients. Returns aldi_status().

    Like the REWE refresh: needs the option and a selected ALDI SÜD branch (its service
    point is looked up once from its coordinates, else the home zone); weekly, manual at
    most once per MANUAL_MIN_HOURS, never while paused. Reduced products become offers.
    """
    return await SOURCE_ALDI.async_refresh(hass, manager, force)


async def async_aldi_live(
    manager: EssensplanerManager,
    query: str,
    branch: dict[str, Any] | None,
    retailer: str | None,
) -> list[dict[str, Any]]:
    """ALDI SÜD articles for the "Artikel hinzufügen" field (cached 1 h, throttled)."""
    return await SOURCE_ALDI.async_live(manager, query, branch, retailer)


async def async_fetch_aldi_offers(
    hass: HomeAssistant, manager: EssensplanerManager
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """aldi_offers(): all current weekly offers ("Wochenangebote") of ALDI SÜD.

    For the offer catalog (one request per PAGE_LIMIT offers, at most MAX_WEEKLY_PAGES,
    REQUEST_DELAY s apart). Needs the option and an ALDI SÜD branch; nothing is sent while
    the source is paused. Returns (offers, meta): offers in the offer format with old_price
    (the was-price, if shown), valid_to = end of the leaflet week (ALDI publishes no end
    date), source "aldi_online", "weekly": True and no keys; meta {status (ok|error|
    blocked|off), count, errors, service_point, updated}.
    """
    meta: dict[str, Any] = {"status": "off", "count": 0, "errors": [], "service_point": None}
    if not aldi_enabled(manager):
        return [], meta
    now = dt_util.utcnow()
    if SOURCE_ALDI.blocked_until(manager, now) is not None:
        return [], {**meta, "status": "blocked"}
    try:
        _, point = await SOURCE_ALDI.async_target(hass, manager, None)
        if point is None:
            return [], {**meta, "status": "error", "errors": [MSG_NO_STORE]}
        meta["service_point"] = point
        raw = await _async_weekly_raw(AldiClient(hass), point)
    except SourceError as err:
        if isinstance(err, (SourceBlocked, SourceUnexpected)):
            SOURCE_ALDI.record_block(manager, err, now)
            manager._changed("price_sources")
        status = "blocked" if isinstance(err, SourceBlocked) else "error"
        return [], {**meta, "status": status, "errors": [err.message]}
    today = manager.today()
    end = leaflet_week_end(today).isoformat()
    offers: dict[str, dict[str, Any]] = {}
    for item in raw:
        product = parse_product(item)
        if product is None or product["id"] in offers:
            continue
        product.update(
            {
                "old_price": product["regular_price"],
                "valid_from": None,
                "valid_to": end,
                "weekly": True,
                "query": "",
            }
        )
        offers[product["id"]] = product
    return list(offers.values()), {
        **meta,
        "status": "ok",
        "count": len(offers),
        "updated": now.isoformat(),
    }


# the name the offer catalog (1.4 phase C) uses
aldi_offers = async_fetch_aldi_offers


async def _async_weekly_raw(client: AldiClient, point: str) -> list[Any]:
    """The raw products of all pages of the weekly offers (category looked up if empty)."""
    category = WEEKLY_CATEGORY
    raw: list[Any] = []
    for attempt in range(2):
        raw = []
        offset = 0
        total = 0
        for page in range(MAX_WEEKLY_PAGES):
            if (page or attempt) and REQUEST_DELAY > 0:
                await asyncio.sleep(REQUEST_DELAY)
            data = await client.async_category_page(category, point, offset)
            items = _raw_list(data)
            total = total_count(data)
            raw.extend(items)
            offset += len(items)
            if not items or offset >= total:
                break
        if raw or attempt:
            break
        # no offers at all: the category may have moved (one look at the category tree)
        if REQUEST_DELAY > 0:
            await asyncio.sleep(REQUEST_DELAY)
        found = await client.async_weekly_category(point)
        if not found or found == category:
            break
        category = found
    return raw


# ----------------------------------------------------------------------
# Store search (explicit user action, also with the option off)
# ----------------------------------------------------------------------


async def async_find_aldi_stores(
    hass: HomeAssistant,
    manager: EssensplanerManager,
    zip_code: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> dict[str, Any]:
    """ALDI SÜD stores near a location (find_aldi_stores, the panel's "Filiale suchen").

    The interface has no postcode search: lat/lon win; a postcode is located with a saved
    branch or a result of the last branch search at that postcode; without both the ALDI
    SÜD branch's coordinates, else the home zone. Returns {location: {lat, lon, source
    (coordinates|postcode|branch|home), zip_code}, stores: [{id, name, street, postcode,
    city, label, lat, lon, distance_km, branch_id (ALDI SÜD branch using this store)}]}.
    """
    from .manager import _error  # avoid an import cycle

    location: tuple[float, float] | None = None
    source = "coordinates"
    postcode: str | None = None
    if lat is not None and lon is not None:
        if not (-90 <= float(lat) <= 90 and -180 <= float(lon) <= 180):
            raise _error("aldi_location_required")
        location = (float(lat), float(lon))
    elif str(zip_code or "").strip():
        text = str(zip_code).strip()
        postcode = valid_postcode(text)
        if postcode is None:
            raise _error("invalid_postcode", postcode=text)
        location = _postcode_location(manager, postcode)
        source = "postcode"
        if location is None:
            raise _error("aldi_postcode_unknown", postcode=postcode)
    else:
        branch, _ = aldi_branch(manager)
        if branch is None:
            branch = next((b for b in manager.branches if b.get("retailer") == RETAILER), None)
        if (
            branch
            and (bl := number(branch.get("lat"))) is not None
            and (bo := number(branch.get("lon"))) is not None
        ):
            location, source = (bl, bo), "branch"
        else:
            location, source = home_location(hass), "home"
        if location is None:
            raise _error("aldi_location_required")
    stores = await AldiClient(hass).async_service_points(
        *location, precision=HOME_PRECISION if source == "home" else STORE_PRECISION
    )
    linked = {
        str(b.get("aldi_service_point") or ""): b.get("id")
        for b in manager.branches
        if b.get("retailer") == RETAILER and b.get("aldi_service_point")
    }
    for store in stores:
        store["branch_id"] = linked.get(store["id"])
    return {
        "location": {
            "lat": round(location[0], 3),
            "lon": round(location[1], 3),
            "source": source,
            "zip_code": postcode,
        },
        "stores": stores[:MAX_STORES],
    }


def _postcode_location(manager: EssensplanerManager, postcode: str) -> tuple[float, float] | None:
    """Coordinates of a saved branch or a branch search result at the postcode."""
    candidates = [*manager.branches]
    results = manager.branch_search.get("results")
    if isinstance(results, list):
        candidates += [r for r in results if isinstance(r, dict)]
    for item in candidates:
        if str(item.get("postcode") or "") != postcode:
            continue
        lat, lon = number(item.get("lat")), number(item.get("lon"))
        if lat is not None and lon is not None:
            return lat, lon
    return None
