"""Supermarket and drugstore offers (Aldi, Lidl, Rewe, Edeka, Penny, Netto, Kaufland, Rossmann …).

Sources:
- manual offers (panel, service, voice)
- optional: marktguru.de (aggregates the weekly leaflets of German supermarkets).
  This uses the *unofficial* web API that marktguru.de itself uses; it is not documented
  and may change at any time. Only enabled when the user opts in.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
import json
import logging
import re
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .const import HTTP_USER_AGENT
from .ingredients import _singular, fold, ingredient_key, to_base

# STORES / DEFAULT_STORES moved to retailers.py in 1.3, re-exported here
from .retailers import DEFAULT_STORES as DEFAULT_STORES, STORES as STORES, retailer_for_store_id

_LOGGER = logging.getLogger(__name__)

MARKTGURU_HOME = "https://www.marktguru.de/"
MARKTGURU_API = "https://api.marktguru.de/api/v1"
IMAGE_URL = "https://mg2de.b-cdn.net/api/v1/offers/{id}/images/default/0/medium.jpg"

REQUEST_DELAY = 0.4
# search terms per refresh: main postcode / each further postcode
MAX_QUERIES = 40
EXTRA_TARGET_QUERIES = 25

# the integration's honest User-Agent (1.4; no browser impersonation)
_USER_AGENT = HTTP_USER_AGENT
# marktguru's placeholder brand of unbranded offers
_NO_BRAND = "thisisnobrand123"
_CONFIG_RE = re.compile(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', re.DOTALL)
_PACK_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*-?\s*(kg|g|ml|l|liter)\b", re.IGNORECASE)
_MULTI_RE = re.compile(r"(\d+)\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*-?\s*(kg|g|ml|l)\b", re.IGNORECASE)
# a weight class or range ("Größe M (53-63 g)", "500-600 g") is no package size
_RANGE_RE = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:kg|g|ml|l)?\s*[-–]\s*\d+(?:[.,]\d+)?\s*-?\s*(?:kg|g|ml|l|liter)\b",
    re.IGNORECASE,
)
# the same written out: egg weight classes "(53 g bis unter 63 g)", "(ab 63 g)", "über 73 g"
_WEIGHT_CLASS_RE = re.compile(
    r"\d+(?:[.,]\d+)?\s*g\s+bis\s+(?:unter\s+)?\d+(?:[.,]\d+)?\s*g\b"
    r"|\b(?:ab|über|ueber|unter|bis(?:\s+unter)?)\s+\d+(?:[.,]\d+)?\s*g\b",
    re.IGNORECASE,
)
# drugstore / household packs (1.4): detergent by washing loads ("39 WL", "20
# Waschladungen", EDEKA's "38 WA" Waschanwendungen), paper by rolls ("8 Rollen",
# "3 x 100 Blatt" = 3 rolls)
_LOADS_RE = re.compile(
    r"(\d+)\s*-?\s*(?:wl|wa|waschladung(?:en)?|waschanwendung(?:en)?)\b", re.IGNORECASE
)
_ROLLS_RE = re.compile(r"(\d+)\s*-?\s*rollen?\b|(\d+)\s*[x×]\s*\d+\s*blatt\b", re.IGNORECASE)


class OfferError(Exception):
    """Raised when offers could not be fetched."""


def parse_pack(text: str | None) -> tuple[float, str] | None:
    """Package size from texts like 'je 500-g-Packung', '2 x 125 g', '1,5-l-Flasche'.

    Ranges and weight classes are skipped: 'Eier Größe M (53-63 g), 10 Stück' or 'Größe L
    (ab 63 g)' has no size in grams. Detergents are sized by washing loads ('1,1 l = 20 WL'
    -> (20, 'WL'), EDEKA's '38 WA' too), toilet paper and kitchen rolls by rolls ('8 Rollen', '3 x 100 Blatt'
    -> (3, 'Rolle')) when no weight or volume is given.
    """
    if not text:
        return None
    text = _WEIGHT_CLASS_RE.sub(" ", _RANGE_RE.sub(" ", text))
    if (match := _LOADS_RE.search(text)) and (loads := float(match.group(1))) > 0:
        return loads, "WL"
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
    if (match := _ROLLS_RE.search(text)) and (rolls := float(match.group(1) or match.group(2))):
        return rolls, "Rolle"
    return None


_STUECK_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:stück|stueck|stk\b|st\b)", re.IGNORECASE)


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


def _date(value: Any) -> str | None:
    """Local date of a timestamp: marktguru's '2026-11-08T23:00:00Z' starts on 09.11. in
    Germany (UTC timestamps become the local date; a plain date stays as it is)."""
    if not value:
        return None
    text = str(value).strip()
    try:
        parsed = dt_util.parse_datetime(text)
    except ValueError:
        parsed = None
    if parsed is not None:
        return dt_util.as_local(parsed).date().isoformat()
    return text[:10] if re.match(r"\d{4}-\d{2}-\d{2}", text) else None


def short_key(key: str) -> bool:
    """Keys without a word of 3+ letters ("ei" for Eier): matched by whole words only."""
    return bool(key) and all(len(w) < 3 for w in key.split())


# words that make an "Eier" offer another product (chocolate eggs, egg liqueur, noodles)
_SHORT_KEY_OTHER = (
    "schoko",
    "ueberraschung",
    "kinder",
    "likoer",
    "nudel",
    "spaetzle",
    "zartbitter",
    "vollmilch",
    "oster",
    "marzipan",
    "nougat",
    "praline",
    "trueffel",
    "milka",
    "lindt",
    "ferrero",
    "salat",
    "creme",
    "waffel",
    "gummi",
    "zucker",
    "hohl",
    "fondant",
    "keks",
    "plaetzchen",
)
_COUNT_RE = re.compile(r"(\d+)\s*(?:stück|stueck|stk\b|st\.|st\b|er\b)", re.IGNORECASE)


def _parse_count(text: str | None) -> tuple[float, str] | None:
    """'10 Stück', '10er-Packung', '6 St.' -> (10, 'Stück') (1–100 pieces)."""
    match = _COUNT_RE.search(text or "")
    if match is None:
        return None
    count = float(match.group(1))
    return (count, "Stück") if 1 <= count <= 100 else None


def _short_key_matches(offer_text: str, key: str) -> bool:
    """'Frische Eier', 'Bio-Eier, 10 Stück' fit "ei"; 'Eierlikör', 'Eier-Nudeln',
    'Schoko-Eier', 'Kinder Überraschung Eier' or a 100-g bag do not (eggs are sold by count).
    """
    heads: set[str] = set()
    for word in offer_text.split():
        parts = fold(word).split()
        if parts:
            heads.add(_singular(parts[-1]))  # the head of "Bio-Eier" is "Eier"
    if not all(w in heads for w in key.split()):
        return False
    tokens = fold(offer_text).split()
    if any(t.startswith(_SHORT_KEY_OTHER) for t in tokens):
        return False
    pack = parse_pack(offer_text)
    return not (pack and pack[1] in ("g", "ml") and not _COUNT_RE.search(offer_text))


def offer_matches(offer_text: str, key: str) -> bool:
    """True if an offer title fits an ingredient key ('haehnchenbrust' ~ 'Hähnchenbrustfilet')."""
    if not key:
        return False
    if short_key(key):
        return _short_key_matches(offer_text, key)
    tokens = [_singular(w) for w in fold(offer_text).split()]
    words = [w for w in key.split() if len(w) >= 3]
    return all(any(_token_match(t, w) for t in tokens) for w in words)


def key_only_as_modifier(text: str, key: str) -> bool:
    """True if every mention of a key word in a product name is the first part of a
    hyphenated compound naming another product: 'Butter-Spekulatius' or
    'Butter-Mandel-Spekulatius' for "butter", 'Kartoffel-Gratin' for "kartoffel" (fold()
    splits them into words that offer_matches() accepts), also a shortened compound
    ('Butter-, Krusten- oder Kochschinken'). Not 'Bio-Butter', 'Kräuter-/Knoblauchbutter'
    or 'H-Milch' (the key is the head)."""
    words = [w for w in key.split() if len(w) >= 3]
    for word in words:
        head_found = modifier_found = False
        for raw in re.split(r"[\s,;()]+", text or ""):
            parts = [fold(p).replace(" ", "") for p in re.split(r"[-/]+", raw) if p.strip()]
            parts = [p for p in parts if p]
            if not parts:
                continue
            if raw.endswith("-"):
                # "Butter-" of "Butter-, Krusten- oder Kochschinken": only a first part
                modifier_found = modifier_found or any(word in part for part in parts)
            elif _token_match(_singular(parts[-1]), word):
                head_found = True
            elif any(word in part for part in parts[:-1]):
                modifier_found = True
        if modifier_found and not head_found:
            return True
    return False


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


# the first part of a compound that makes it another product ("Eis|kaffee", "Milch|kaffee",
# "Malz|kaffee"); other compounds are the same product ("Röst|kaffee", "Filter|kaffee")
_OTHER_PRODUCT_MODIFIERS = (
    "eis",
    "milch",
    "malz",
    "getreide",
    "gerste",
    "zichorie",
    "lupine",
    "dinkel",
    "kinder",
    "kokos",
    "mandel",
    "hafer",
    "soja",
    "reis",
    "butter",
    "schoko",
    "kakao",
)
# what may follow the key inside a compound of the same product ("Kaffee|bohnen",
# "Kaffee|pads"); else the compound is another product ("Kaffee|sahne", "Kaffee|filter")
_SAME_PRODUCT_REST = (*_ALLOWED_REST, "bohne", "pad", "kapsel", "pulver")


def _key_product_verdict(text: str, key: str) -> bool | None:
    """How a text names the key's product: True (the product: whole words or a compound of
    the same product), False (a compound naming another product), None (not mentioned)."""
    tokens = [_singular(w) for w in fold(text).split()]
    words = key.split()
    if all(w in tokens for w in words):
        return True
    mentioned = 0
    for word in [w for w in words if len(w) >= 3]:
        found = word in tokens
        for token in tokens:
            if token == word or word not in token:
                continue
            if token.endswith(word):
                modifier = token[: -len(word)]
                forms = {modifier, modifier[:-1] if modifier.endswith("s") else modifier}
                if any(
                    form.startswith(_OTHER_PRODUCT_MODIFIERS)
                    or form.endswith(_OTHER_PRODUCT_MODIFIERS)
                    for form in forms
                ):
                    return False  # "Eiskaffee", "Vollmilchkaffee"
                found = True  # "Röstkaffee", "Bohnenkaffee"
            elif token.startswith(word):
                rest = token[len(word) :]
                if rest not in _PLURAL_REST and not rest.startswith(_SAME_PRODUCT_REST):
                    return False  # "Kaffeesahne"
                found = True  # "Kaffeebohnen"
        mentioned += found
    if mentioned and mentioned == len([w for w in words if len(w) >= 3]):
        return True
    return None


def names_other_compound(text: str, key: str) -> bool:
    """True if a text names another product in a compound with the key ('Eiskaffee',
    'Kaffeesahne' for "kaffee"); False for the product itself or a text without the key."""
    return bool(key) and _key_product_verdict(text, key) is False


def names_key_product(product: str, key: str, description: str = "") -> bool:
    """True if an offer is of the key's product itself, not of a compound that
    offer_matches() accepts but that is another product.

    The product name decides when it names the key: 'Kaffee Crema, ganze Bohne',
    'Bio-Kaffee' or 'Röstkaffee' for "kaffee", not 'Eiskaffee', 'Milchkaffee' or
    'Kaffeesahne'. A brand name without it ('Krönung', 'Prodomo') is decided by the
    description the offer was matched with ('Röstkaffee, gemahlen').
    """
    if not key:
        return False
    if ingredient_key(product) == key:
        return True
    for text in (product, description, f"{product} {description}"):
        verdict = _key_product_verdict(text, key)
        if verdict is not None:
            return verdict
    return False


def normalize_marktguru(raw: dict[str, Any], query: str = "") -> dict[str, Any] | None:
    """Convert a marktguru offer into the internal format."""
    try:
        offer_id = raw.get("id")
        product = (raw.get("product") or {}).get("name") or ""
        brand_info = raw.get("brand") or {}
        brand = brand_info.get("name") or ""
        if _NO_BRAND in (brand.strip().lower(), str(brand_info.get("uniqueName") or "")):
            brand = ""  # marktguru's placeholder of unbranded offers
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
        if pack is None and base_unit in (None, "Stück"):
            # sold by count ("Eier Größe M (53-63 g), 10 Stück", "10er-Packung")
            pack = _parse_count(description) or _parse_count(product)
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
            "retailer": retailer_for_store_id(advertiser.get("uniqueName")),
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
    """Fetch offers for (search term, ingredient key) pairs near one zip code (1.2 API)."""
    return await async_fetch_target_offers(hass, terms, [(zip_code, stores)], delay)


async def async_fetch_target_offers(
    hass: HomeAssistant,
    terms: list[tuple[str, str]],
    targets: list[tuple[str, list[str]]],
    delay: float | None = None,
    extra_limit: int | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch offers for several (zip code, [retailers]) targets. Returns (offers, errors).

    The first target (main branch) is searched with all terms (up to MAX_QUERIES), further
    targets with the first EXTRA_TARGET_QUERIES terms. Offers found at several zip codes
    are merged (keys and "zip_codes" collected). Every offer has "retailer" and
    "zip_codes". Stops early when the source is unavailable.
    """
    client = MarktguruClient(hass)
    offers: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    delay = REQUEST_DELAY if delay is None else delay
    extra_limit = EXTRA_TARGET_QUERIES if extra_limit is None else extra_limit
    several = len(targets) > 1
    requests = 0
    succeeded = False
    for position, (zip_code, stores) in enumerate(targets):
        target_terms = terms if position == 0 else terms[:extra_limit]
        target_errors = 0
        unavailable = False
        for index, (term, key) in enumerate(target_terms):
            if requests and delay > 0:
                await asyncio.sleep(delay)  # be polite to the web site
            requests += 1
            try:
                raw_offers = await client.async_search(term, zip_code)
            except OfferError as err:
                errors.append(f"{term} ({zip_code}): {err}" if several else f"{term}: {err}")
                target_errors += 1
                if index == 0 or target_errors >= 3:
                    unavailable = not succeeded  # nothing worked so far: stop completely
                    break
                continue
            succeeded = True
            for raw in raw_offers:
                offer = normalize_marktguru(raw, term)
                if offer is None or not store_allowed(offer["store_id"], stores):
                    continue
                if not offer_matches(f"{offer['product']} {offer['description']}", key):
                    continue
                _merge_offer(offers, offer, key, zip_code)
        if unavailable:
            break
    return list(offers.values()), errors


def _merge_offer(
    offers: dict[str, dict[str, Any]], offer: dict[str, Any], key: str | None, zip_code: str
) -> None:
    existing = offers.get(offer["id"])
    if existing is None:
        existing = offers[offer["id"]] = {**offer, "keys": [], "zip_codes": []}
    if key and key not in existing["keys"]:
        existing["keys"].append(key)
    if zip_code not in existing["zip_codes"]:
        existing["zip_codes"].append(zip_code)


async def async_search_target_offers(
    hass: HomeAssistant,
    query: str,
    targets: list[tuple[str, list[str]]],
    delay: float | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Live search of one product at every target (no ingredient matching)."""
    client = MarktguruClient(hass)
    offers: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    delay = REQUEST_DELAY if delay is None else delay
    for position, (zip_code, stores) in enumerate(targets):
        if position and delay > 0:
            await asyncio.sleep(delay)
        try:
            raw_offers = await client.async_search(query, zip_code)
        except OfferError as err:
            errors.append(str(err))
            if not offers:
                break  # source unavailable
            continue
        for raw in raw_offers:
            offer = normalize_marktguru(raw, query)
            if offer is not None and store_allowed(offer["store_id"], stores):
                _merge_offer(offers, offer, None, zip_code)
    for offer in offers.values():
        if not offer["keys"]:
            del offer["keys"]
    return list(offers.values()), errors


def leaflet_week_end(day: date) -> date:
    """End of the leaflet week of a day: the coming Saturday (the day itself on a Saturday).

    Offers entered without an end date end then, they never count forever.
    """
    return day + timedelta(days=(5 - day.weekday()) % 7)


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
    pack = parse_pack_text(pack_text) or parse_pack(product)
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


async def async_refresh_offers(hass: HomeAssistant, manager: Any) -> dict[str, Any]:
    """Fetch offers from marktguru for the manager's ingredients and store them.

    Searched at every postcode of manager.offer_targets() (branches, else the zip option).
    Only one refresh runs at a time (start-up / daily run, button, services): a second
    call waits for the running one and returns its result. The run is tied to the config
    entry (cancelled on unload).
    """
    task = getattr(manager, "_offers_task", None)
    if task is None or task.done():
        task = manager.entry.async_create_background_task(
            hass, _async_refresh_offers(hass, manager), "essensplaner_refresh_offers"
        )
        manager._offers_task = task
    return await asyncio.shield(task)


async def _async_refresh_offers(hass: HomeAssistant, manager: Any) -> dict[str, Any]:
    targets = manager.offer_targets()
    terms = manager.offer_search_terms(limit=MAX_QUERIES)
    if targets:
        offers, errors = await async_fetch_target_offers(hass, terms, targets)
    else:
        offers, errors = [], ["Keine gültige Postleitzahl (Optionen oder Filialen)"]
    meta = {
        "source": "marktguru",
        "last_update": dt_util.utcnow().isoformat(),
        "searched": len(terms),
        "count": len(offers),
        "errors": errors[:5],
        "status": "error" if errors and not offers else "ok",
        "targets": [{"zip_code": z, "retailers": list(r)} for z, r in targets],
    }
    if meta["status"] == "error":
        # keep the previous offers, only report the problem
        manager.offers_meta = {**manager.offers_meta, **meta}
        manager.async_refresh_listeners()
    else:
        manager.replace_source_offers("marktguru", offers, meta)
    return meta
