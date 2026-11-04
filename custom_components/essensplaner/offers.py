"""Supermarket offers (Aldi, Lidl, Rewe, Edeka, Penny, Netto, Kaufland …).

Sources:
- manual offers (panel, service, voice)
- optional: marktguru.de (aggregates the weekly leaflets of German supermarkets).
  This uses the *unofficial* web API that marktguru.de itself uses; it is not documented
  and may change at any time. Only enabled when the user opts in.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
import json
import logging
import re
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .ingredients import _singular, fold, ingredient_key, to_base

_LOGGER = logging.getLogger(__name__)

MARKTGURU_HOME = "https://www.marktguru.de/"
MARKTGURU_API = "https://api.marktguru.de/api/v1"
IMAGE_URL = "https://mg2de.b-cdn.net/api/v1/offers/{id}/images/default/0/medium.jpg"

STORES: dict[str, str] = {
    "aldi-sued": "Aldi Süd",
    "aldi-nord": "Aldi Nord",
    "lidl": "Lidl",
    "rewe": "REWE",
    "edeka": "EDEKA",
    "penny": "Penny",
    "netto-marken-discount": "Netto",
    "kaufland": "Kaufland",
    "norma": "Norma",
    "globus": "Globus",
    "marktkauf": "Marktkauf",
}
DEFAULT_STORES = [
    "aldi-sued",
    "aldi-nord",
    "lidl",
    "rewe",
    "edeka",
    "penny",
    "netto-marken-discount",
    "kaufland",
]

REQUEST_DELAY = 0.4

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
_CONFIG_RE = re.compile(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', re.DOTALL)
_PACK_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*-?\s*(kg|g|ml|l|liter)\b", re.IGNORECASE)
_MULTI_RE = re.compile(r"(\d+)\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*-?\s*(kg|g|ml|l)\b", re.IGNORECASE)


class OfferError(Exception):
    """Raised when offers could not be fetched."""


def parse_pack(text: str | None) -> tuple[float, str] | None:
    """Package size from texts like 'je 500-g-Packung', '2 x 125 g', '1,5-l-Flasche'."""
    if not text:
        return None
    if match := _MULTI_RE.search(text):
        count = float(match.group(1))
        value = float(match.group(2).replace(",", "."))
        amount, unit = to_base(count * value, match.group(3).lower())
        return (amount or 0, unit) if amount else None
    if match := _PACK_RE.search(text):
        value = float(match.group(1).replace(",", "."))
        unit = match.group(2).lower().replace("liter", "l")
        amount, base = to_base(value, unit)
        return (amount or 0, base) if amount else None
    return None


def _date(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10] if re.match(r"\d{4}-\d{2}-\d{2}", text) else None


def offer_matches(offer_text: str, key: str) -> bool:
    """True if an offer title fits an ingredient key ('haehnchenbrust' ~ 'Hähnchenbrustfilet')."""
    if not key:
        return False
    tokens = [_singular(w) for w in fold(offer_text).split()]
    words = [w for w in key.split() if len(w) >= 3]
    if not words:
        return False
    return all(any(_token_match(t, w) for t in tokens) for w in words)


# what may follow an ingredient word inside a compound ("Hähnchenbrust|filet")
_ALLOWED_REST = (
    "filet",
    "fleisch",
    "stueck",
    "scheibe",
    "wuerfel",
    "streifen",
    "mix",
    "sorte",
    "schnitzel",
    "steak",
    "brust",
    "keule",
    "schenkel",
    "packung",
    "spiess",
    "ragout",
)
_PLURAL_REST = {"n", "e", "en", "s", "er", "nen"}


def _token_match(token: str, word: str) -> bool:
    """German compounds: the head is at the end ('Vollmilch' ~ 'milch', not 'Milchschokolade')."""
    if token == word or token.endswith(word):
        return True
    if token.startswith(word):
        rest = token[len(word) :]
        return rest in _PLURAL_REST or rest.startswith(_ALLOWED_REST)
    return False


def normalize_marktguru(raw: dict[str, Any], query: str = "") -> dict[str, Any] | None:
    """Convert a marktguru offer into the internal format."""
    try:
        offer_id = raw.get("id")
        product = (raw.get("product") or {}).get("name") or ""
        brand = (raw.get("brand") or {}).get("name") or ""
        advertisers = raw.get("advertisers") or []
        advertiser = advertisers[0] if advertisers else {}
        price = raw.get("price")
        if price is None or not product:
            return None
        validity = (raw.get("validityDates") or [{}])[0]
        description = raw.get("description") or ""
        unit = ((raw.get("unit") or {}).get("shortName") or "").lower()
        reference = raw.get("referencePrice")
        unit_price = None
        base_unit = None
        if reference:
            if unit in ("kg", "kilogramm"):
                unit_price, base_unit = float(reference) / 1000, "g"
            elif unit in ("l", "liter"):
                unit_price, base_unit = float(reference) / 1000, "ml"
            elif unit in ("100g", "100 g"):
                unit_price, base_unit = float(reference) / 100, "g"
            elif unit in ("stück", "stk", "st", "stk."):
                unit_price, base_unit = float(reference), "Stück"
        pack = parse_pack(description) or parse_pack(product)
        title = (
            f"{brand} {product}".strip()
            if brand and brand.lower() not in product.lower()
            else product
        )
        return {
            "id": f"mg_{offer_id}",
            "title": title,
            "product": product,
            "brand": brand,
            "description": description[:200],
            "store": advertiser.get("name") or "",
            "store_id": advertiser.get("uniqueName") or "",
            "price": round(float(price), 2),
            "old_price": round(float(raw["oldPrice"]), 2) if raw.get("oldPrice") else None,
            "unit_price": unit_price,
            "base_unit": base_unit,
            "pack_amount": pack[0] if pack else None,
            "pack_unit": pack[1] if pack else None,
            "valid_from": _date(validity.get("from")),
            "valid_to": _date(validity.get("to")),
            "image": IMAGE_URL.format(id=offer_id) if offer_id else None,
            "loyalty": bool(raw.get("requiresLoyalityMembership")),
            "source": "marktguru",
            "query": query,
        }
    except (TypeError, ValueError, AttributeError, IndexError) as err:
        _LOGGER.debug("Could not parse offer %s: %s", raw, err)
        return None


def store_allowed(store_id: str, allowed: list[str]) -> bool:
    """Store filter (also matches regional variants like 'edeka-suedwest')."""
    if not allowed:
        return True
    return any(store_id == s or store_id.startswith(f"{s}-") for s in allowed)


class MarktguruClient:
    """Minimal client for the marktguru.de offer search."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize."""
        self._session = async_get_clientsession(hass)
        self._keys: tuple[str, str] | None = None

    async def _async_keys(self, force: bool = False) -> tuple[str, str]:
        if self._keys and not force:
            return self._keys
        try:
            async with self._session.get(
                MARKTGURU_HOME,
                headers={"User-Agent": _USER_AGENT, "Accept-Language": "de-DE,de;q=0.9"},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status >= 400:
                    raise OfferError(f"marktguru.de antwortet mit HTTP {resp.status}")
                page = await resp.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise OfferError(f"marktguru.de nicht erreichbar: {err}") from err
        for block in _CONFIG_RE.findall(page):
            try:
                data = json.loads(block)
            except ValueError:
                continue
            config = data.get("config") if isinstance(data, dict) else None
            if isinstance(config, dict) and config.get("apiKey") and config.get("clientKey"):
                self._keys = (config["apiKey"], config["clientKey"])
                return self._keys
        raise OfferError("Zugangsdaten auf marktguru.de nicht gefunden (Seite geändert?)")

    async def async_search(
        self, query: str, zip_code: str, limit: int = 60
    ) -> list[dict[str, Any]]:
        """Search offers near a zip code."""
        for attempt in range(2):
            api_key, client_key = await self._async_keys(force=attempt > 0)
            try:
                async with self._session.get(
                    f"{MARKTGURU_API}/offers/search",
                    params={
                        "as": "web",
                        "q": query,
                        "zipCode": zip_code,
                        "limit": limit,
                        "offset": 0,
                    },
                    headers={
                        "x-apikey": api_key,
                        "x-clientkey": client_key,
                        "User-Agent": _USER_AGENT,
                        "Accept": "application/json",
                    },
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status in (401, 403) and attempt == 0:
                        continue
                    if resp.status >= 400:
                        raise OfferError(f"Angebotssuche: HTTP {resp.status}")
                    data = await resp.json(content_type=None)
            except (aiohttp.ClientError, TimeoutError, ValueError) as err:
                raise OfferError(f"Angebotssuche fehlgeschlagen: {err}") from err
            results = data.get("results") if isinstance(data, dict) else None
            return results if isinstance(results, list) else []
        raise OfferError("Angebotssuche: Zugriff verweigert")


async def async_fetch_offers(
    hass: HomeAssistant,
    terms: list[tuple[str, str]],
    zip_code: str,
    stores: list[str],
    delay: float | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch offers for (search term, ingredient key) pairs. Returns (offers, errors)."""
    client = MarktguruClient(hass)
    offers: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    delay = REQUEST_DELAY if delay is None else delay
    for index, (term, key) in enumerate(terms):
        if index and delay > 0:
            await asyncio.sleep(delay)  # be polite to the web site
        try:
            raw_offers = await client.async_search(term, zip_code)
        except OfferError as err:
            errors.append(f"{term}: {err}")
            if index == 0 or len(errors) >= 3:
                break  # source unavailable – stop early
            continue
        for raw in raw_offers:
            offer = normalize_marktguru(raw, term)
            if offer is None or not store_allowed(offer["store_id"], stores):
                continue
            if not offer_matches(f"{offer['product']} {offer['description']}", key):
                continue
            existing = offers.setdefault(offer["id"], {**offer, "keys": []})
            if key not in existing["keys"]:
                existing["keys"].append(key)
    return list(offers.values()), errors


def manual_offer(
    product: str,
    store: str,
    price: float,
    pack_text: str | None = None,
    valid_from: date | None = None,
    valid_to: date | None = None,
    old_price: float | None = None,
) -> dict[str, Any]:
    """Create an offer entered by the user."""
    pack = parse_pack(pack_text) or parse_pack(product)
    key = ingredient_key(product)
    stamp = int(datetime.now().timestamp() * 1000)
    return {
        "id": f"man_{stamp}",
        "title": product.strip(),
        "product": product.strip(),
        "brand": "",
        "description": pack_text or "",
        "store": store.strip(),
        "store_id": fold(store).replace(" ", "-"),
        "price": round(float(price), 2),
        "old_price": round(float(old_price), 2) if old_price else None,
        "unit_price": None,
        "base_unit": None,
        "pack_amount": pack[0] if pack else None,
        "pack_unit": pack[1] if pack else None,
        "valid_from": valid_from.isoformat() if valid_from else None,
        "valid_to": valid_to.isoformat() if valid_to else None,
        "image": None,
        "loyalty": False,
        "source": "manual",
        "query": product,
        "keys": [key] if key else [],
    }


MAX_QUERIES = 40


async def async_refresh_offers(hass: HomeAssistant, manager: Any) -> dict[str, Any]:
    """Fetch offers from marktguru for the manager's ingredients and store them."""
    terms = manager.offer_search_terms(limit=MAX_QUERIES)
    offers, errors = await async_fetch_offers(hass, terms, manager.zip_code, manager.offer_stores)
    meta = {
        "source": "marktguru",
        "last_update": dt_util.utcnow().isoformat(),
        "searched": len(terms),
        "count": len(offers),
        "errors": errors[:5],
        "status": "error" if errors and not offers else "ok",
    }
    if meta["status"] == "error":
        # keep the previous offers, only report the problem
        manager.offers_meta = {**manager.offers_meta, **meta}
        manager.async_refresh_listeners()
    else:
        manager.replace_source_offers("marktguru", offers, meta)
    return meta
