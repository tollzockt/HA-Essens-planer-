"""Weekly offers of the user's EDEKA market from www.edeka.de (optional).

Off by default (option edeka_offers). Every EDEKA merchant has his own leaflet; the EDEKA
web site shows it per market from two JSON endpoints (checked 11/2026 with the honest
User-Agent, no login):
- market search: MARKETS_URL?searchstring=<postcode>&size=.. -> {totalCount, markets: [{id,
  name, contact: {address: {street, city: {name, zipCode}}}, coordinates, ...}]}
- offers of one market: OFFERS_URL?marketId=<id>&limit=500 -> {docs: [...], anzahl,
  gueltig_von, gueltig_bis (epoch ms), national}; an offer has angebotid, titel, preis
  (EUR), beschreibung ("je 200 g Beutel", "je Packung = 6 x 1,5 l zzgl. € 1.50 Pfand"),
  basicPrice ("1 kg = € 9.95" with non-breaking spaces, may be missing), warengruppe,
  bild_app, kriterien ([{name: "PAYBACK" | "App-Preis" | "Superknüller"}]),
  punkte_deutschlandcard, gueltig_bis.
The market is linked to the EDEKA branch with save_branch (edeka_market_id, found with
find_edeka_markets). Offers come as normalized offers (source "edeka", retailer "edeka",
for that branch); the ones matching the planned / frequent ingredients and open shopping
items are kept with the other offers (planning, budget, shopping list stores).

Not documented; may change or refuse automated requests at any time: HTTP 401/403/429 or a
web page = blocked, an unexpected answer = error, both pause the source for BLOCK_DAYS
days; the offers fetched before are kept. Refreshed daily at 06:xx when the last success is
REFRESH_HOURS old or the stored leaflet week has ended (and on demand, at most once per
MANUAL_MIN_HOURS).
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
import logging
import re
import sys
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .catalog import KeyMatcher
from .const import CONF_EDEKA_OFFERS, DEFAULT_EDEKA_OFFERS
from .ingredients import fold
from .offers import _parse_count, parse_pack, parse_pack_text
from .online_prices import (
    STATUS_ERROR,
    STATUS_OK,
    OnlinePriceSource,
    SourceBlocked,
    SourceError,
    SourceUnexpected,
    async_get_json,
    dict_of,
    in_range,
    number,
    parse_time,
    refresh_terms,
)
from .pricing import plausible_pack
from .stores import valid_postcode

if TYPE_CHECKING:
    from .manager import EssensplanerManager

_LOGGER = logging.getLogger(__name__)

MARKETS_URL = "https://www.edeka.de/api/marketsearch/markets"
OFFERS_URL = "https://www.edeka.de/eh/service/eh/offers"
CLIENT_VERSION = 1

RETAILER = "edeka"
SOURCE = "edeka"
META_KEY = "edeka"
STORE_NAME = "EDEKA"

# seconds between the requests of a refresh (one per linked market; tests set 0)
REQUEST_DELAY = 1.5
REQUEST_TIMEOUT = 20
OFFER_LIMIT = 500
MARKET_PAGE_SIZE = 20
MAX_MARKETS = 25
# the offers are fetched again when the last success is this old (or the week has ended)
REFRESH_HOURS = 20
BLOCK_DAYS = 7
MANUAL_MIN_HOURS = 1
MAX_ERRORS = 5
MAX_BYTES = 4 * 1024 * 1024
# offers are matched with this many ingredients (plan, favourites, watchlist) + open items
MAX_MATCH_TERMS = 200
MAX_SHOPPING_TERMS = 40

MSG_NO_MARKET = (
    "Für EDEKA ist kein Markt verknüpft – bei deiner EDEKA-Filiale „Markt suchen“ und den "
    "Markt auswählen."
)

_MARKET_ID_RE = re.compile(r"^\d{1,12}$")
# "1 kg = € 9.95", "1 kg = ab € 11.10", "1 l = € 1.20 / € 1.51", "1 WA = € 0.05"
_BASIC_PRICE_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)?\s*(kg|g|ml|l|wa|wl|stück|stk|st)\.?\s*=\s*(ab\s*)?€\s*(\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)
# "zzgl. € 0.15 Pfand", "zzgl. € 3.10 / € 3.42 Pfand"
_DEPOSIT_RE = re.compile(
    r",?\s*zzgl\.?\s*€\s*(\d+[.,]\d{1,2})(?:\s*/\s*€\s*\d+[.,]\d{1,2})*\s*Pfand", re.IGNORECASE
)
# a range of pieces ("je 16 - 36 Stück") is no pack size
_PIECE_RANGE_RE = re.compile(r"\d+\s*[-–]\s*\d+\s*(?:stück|stueck|stk)", re.IGNORECASE)
_SINGLE_PIECE_RE = re.compile(r"(?:^|[\s,])(?:je\s+)?st(?:ü|ue)ck\b", re.IGNORECASE)
# origin in front of fruit, vegetables, meat and wine ("Spanien - Bio Orangen")
_COUNTRIES = {
    fold(c)
    for c in (
        "Deutschland",
        "Spanien",
        "Italien",
        "Frankreich",
        "Niederlande",
        "Belgien",
        "Österreich",
        "Schweiz",
        "Polen",
        "Ungarn",
        "Portugal",
        "Griechenland",
        "Türkei",
        "Marokko",
        "Ägypten",
        "Israel",
        "Südafrika",
        "Chile",
        "Argentinien",
        "Brasilien",
        "Peru",
        "Ecuador",
        "Kolumbien",
        "Costa Rica",
        "Mexiko",
        "Neuseeland",
        "Australien",
        "Irland",
        "Dänemark",
        "Norwegen",
        "Schottland",
        "Tschechien",
        "Kenia",
        "Indien",
        "China",
        "Vietnam",
        "Thailand",
        "USA",
    )
}


class EdekaError(SourceError):
    """An EDEKA request failed (translation key + German message)."""


class EdekaBlocked(EdekaError, SourceBlocked):
    """EDEKA refused automated requests (HTTP 401/403/429, web page instead of data)."""


class EdekaUnexpected(EdekaError, SourceUnexpected):
    """The answer did not have the expected structure (interface changed?)."""


def _blocked(detail: str) -> EdekaBlocked:
    return EdekaBlocked(
        "edeka_blocked",
        f"Die EDEKA-Website lässt gerade keine automatischen Abfragen zu ({detail}).",
        error=detail,
    )


def _failed(detail: str, unexpected: bool = False) -> EdekaError:
    cls = EdekaUnexpected if unexpected else EdekaError
    return cls(
        "edeka_failed",
        f"Die Abfrage bei EDEKA ist fehlgeschlagen ({detail}).",
        error=detail,
    )


# ----------------------------------------------------------------------
# Parsers
# ----------------------------------------------------------------------


def _clean(value: Any) -> str:
    """Text with non-breaking spaces and runs of white space as one space."""
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def local_date(value: Any) -> str | None:
    """Epoch milliseconds -> local ISO date (EDEKA's 1794009600000 = 07.11.2026)."""
    millis = number(value)
    if millis is None or millis <= 0:
        return None
    try:
        moment = datetime.fromtimestamp(millis / 1000, tz=dt_util.UTC)
    except (OverflowError, OSError, ValueError):
        return None
    return dt_util.as_local(moment).date().isoformat()


def basic_price(text: Any) -> tuple[float, str, bool] | None:
    """'1 kg = € 9.95' -> (0.00995, 'g', False): price per g / ml / piece / washing load,
    True for a minimum ('ab €'). The first of several values counts."""
    match = _BASIC_PRICE_RE.search(_clean(text))
    if match is None:
        return None
    amount = number(match.group(1)) or 1.0
    unit = match.group(2).lower()
    value = number(match.group(4))
    if not value or amount <= 0:
        return None
    factor, base = {
        "kg": (1000.0, "g"),
        "g": (1.0, "g"),
        "l": (1000.0, "ml"),
        "ml": (1.0, "ml"),
        "wa": (1.0, "WL"),
        "wl": (1.0, "WL"),
    }.get(unit, (1.0, "Stück"))
    return value / (amount * factor), base, bool(match.group(3))


def deposit(text: str) -> tuple[float | None, str]:
    """(deposit EUR, text without it): 'je 0,5 l Flasche zzgl. € 0.15 Pfand' ->
    (0.15, 'je 0,5 l Flasche')."""
    match = _DEPOSIT_RE.search(text)
    if match is None:
        return None, text
    return number(match.group(1)), _clean(text[: match.start()] + text[match.end() :])


def pack_of(text: str, title: str = "") -> tuple[float, str] | None:
    """Pack size from the description ('je 200 g Beutel', 'je Packung = 6 x 1,5 l',
    'je 38 WA Flasche', '8 x 150 Blatt', 'Klasse I, Stück'), else from the title."""
    pack = parse_pack(text) or parse_pack(title)
    counted = _PIECE_RANGE_RE.sub(" ", text)
    if pack is None:
        pack = parse_pack_text(counted) or _parse_count(counted)
    if pack is None and _SINGLE_PIECE_RE.search(counted):
        pack = (1.0, "Stück")
    if pack is None:
        return None
    # weights, volumes and counts within the sanity limits; washing loads and rolls as given
    return pack if pack[1] not in ("g", "ml", "Stück") or plausible_pack(*pack) else None


def _split_title(title: str) -> tuple[str, str, str]:
    """'Spanien - Bio Orangen' -> (product 'Bio Orangen', brand '', origin 'Spanien');
    'EDEKA - Butter-Spekulatius' -> ('Butter-Spekulatius', 'EDEKA', '')."""
    parts = [p.strip() for p in title.split(" - ") if p.strip()]
    if len(parts) < 2:
        return title, "", ""
    origin = [
        p
        for p in parts[:-1]
        if all(fold(c) in _COUNTRIES for c in re.split(r"\s*/\s*", p) if c.strip())
    ]
    brand = [p for p in parts[:-1] if p not in origin]
    return parts[-1], " - ".join(brand), " / ".join(origin)


def _notes(raw: dict[str, Any]) -> tuple[bool, str | None, bool]:
    """(price needs the EDEKA app, loyalty note, Superknüller) from kriterien / points."""
    names = {
        fold(str(dict_of(c).get("name") or ""))
        for c in raw.get("kriterien") or []
        if isinstance(c, dict)
    }
    notes: list[str] = []
    app = "app-preis" in names or "app preis" in names
    if app:
        notes.append("Preis mit der EDEKA-App")
    if "payback" in names:
        notes.append("PAYBACK-Punkte")
    points = number(raw.get("punkte_deutschlandcard"))
    if points:
        notes.append(f"{int(points)} DeutschlandCard-Punkte")
    elif "deutschlandcard" in names:
        notes.append("DeutschlandCard-Punkte")
    return app, " · ".join(notes) or None, "superknueller" in names


def parse_offer(
    raw: Any,
    valid_from: str | None = None,
    valid_to: str | None = None,
    market_id: str | None = None,
) -> dict[str, Any] | None:
    """One EDEKA offer in the offer format (like offers.normalize_marktguru()).

    valid_from / valid_to: the leaflet week (local dates); an offer's own gueltig_bis wins.
    Extra keys: market_id, origin, category (warengruppe), loyalty_note (PAYBACK,
    DeutschlandCard, app price), highlight (Superknüller), deposit (EUR), unit_price_from
    (the base price is a minimum, "ab").
    """
    if not isinstance(raw, dict):
        return None
    offer_id = str(raw.get("angebotid") or "").strip()
    title = _clean(raw.get("titel"))
    price = in_range(number(raw.get("preis")))
    if not offer_id or not title or price is None:
        return None
    description = _clean(raw.get("beschreibung"))
    pfand, rest = deposit(description)
    product, brand, origin = _split_title(title)
    pack = pack_of(rest, product)
    per = basic_price(raw.get("basicPrice"))
    unit_price = (per[0], per[1]) if per else None
    if unit_price is None and pack:
        unit_price = (price / pack[0], pack[1])
    app, note, highlight = _notes(raw)
    image = next(
        (
            url
            for url in (raw.get("bild_app"), raw.get("bild_web130"), raw.get("bild_web90"))
            if isinstance(url, str) and url.startswith("https://")
        ),
        None,
    )
    shown = description
    if origin:
        shown = f"Herkunft: {origin} · {shown}" if shown else f"Herkunft: {origin}"
    return {
        "id": f"edeka_{offer_id}",
        "title": title,
        "product": product,
        "brand": brand,
        "description": shown[:200],
        "store": STORE_NAME,
        "store_id": RETAILER,
        "retailer": RETAILER,
        "price": price,
        "old_price": None,
        "unit_price": round(unit_price[0], 6) if unit_price else None,
        "base_unit": unit_price[1] if unit_price else None,
        "unit_price_from": bool(per and per[2]),
        "pack_amount": pack[0] if pack else None,
        "pack_unit": pack[1] if pack else None,
        "valid_from": valid_from,
        "valid_to": local_date(raw.get("gueltig_bis")) or valid_to,
        "image": image,
        "loyalty": app,
        "loyalty_note": note,
        "highlight": "Superknüller" if highlight else None,
        "deposit": pfand,
        "category": _clean(raw.get("warengruppe")) or None,
        "origin": origin or None,
        "market_id": market_id,
        "source": SOURCE,
        "query": "",
    }


def parse_offers(data: Any, market_id: str | None = None) -> dict[str, Any]:
    """{offers, valid_from, valid_to, count} of an offers answer. Raises EdekaUnexpected
    for another structure."""
    docs = data.get("docs") if isinstance(data, dict) else None
    if not isinstance(docs, list):
        raise _failed("unerwartete Antwort", unexpected=True)
    valid_from = local_date(data.get("gueltig_von"))
    valid_to = local_date(data.get("gueltig_bis"))
    offers: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in docs:
        offer = parse_offer(raw, valid_from, valid_to, market_id)
        if offer is not None and offer["id"] not in seen:
            seen.add(offer["id"])
            offers.append(offer)
    if len(docs) >= 3 and not offers:
        raise _failed("keine Preise in der Antwort", unexpected=True)
    return {
        "offers": offers,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "count": len(offers),
    }


def parse_market(raw: Any) -> dict[str, Any] | None:
    """One EDEKA market: {id, name, channel, street, postcode, city, label, lat, lon}."""
    if not isinstance(raw, dict):
        return None
    market_id = str(raw.get("id") or "").strip()
    if not _MARKET_ID_RE.fullmatch(market_id):
        return None
    address = dict_of(dict_of(raw.get("contact")).get("address"))
    city_info = dict_of(address.get("city"))
    postcode = str(city_info.get("zipCode") or raw.get("zipCode_keyword") or "").strip()
    city = _clean(city_info.get("name"))
    if postcode and city.startswith(f"{postcode} "):
        city = city[len(postcode) + 1 :]  # "55501 Musterheim"
    street = _clean(address.get("street"))
    name = _clean(raw.get("name")) or STORE_NAME
    coordinates = dict_of(raw.get("coordinates"))
    lat, lon = number(coordinates.get("lat")), number(coordinates.get("lon"))
    place = " ".join(p for p in (postcode, city) if p)
    channel = _clean(dict_of(raw.get("distributionChannel")).get("name")) or None
    return {
        "id": market_id,
        "name": name,
        "channel": channel,
        "street": street,
        "postcode": postcode,
        "city": city,
        "label": ", ".join(p for p in (name, street, place) if p),
        "lat": round(lat, 6) if lat is not None and -90 <= lat <= 90 else None,
        "lon": round(lon, 6) if lon is not None and -180 <= lon <= 180 else None,
    }


def parse_markets(data: Any) -> list[dict[str, Any]]:
    """Markets of a market search answer ({totalCount, markets: [...]})."""
    raw = data.get("markets") if isinstance(data, dict) else None
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
# Matching
# ----------------------------------------------------------------------


def match_offers(
    manager: EssensplanerManager, offers: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The offers that fit a planned / frequent ingredient or an open shopping item, with
    their keys (copies; the others are left out like a leaflet page nobody needs).

    The same matcher as the offer catalog: the product itself decides ("Granatäpfel" are
    no Äpfel, "Ingwer Shot" no Ingwer); the description only names the kind of product
    ("französischer Hartkäse" for "Gruyère"), not what is in it ("mit Röstzwiebeln"),
    and the short words of keys ("tiefgefroren" for "tk erbse")."""
    keys = list(
        dict.fromkeys(k for _, k in refresh_terms(manager, MAX_MATCH_TERMS, MAX_SHOPPING_TERMS))
    )
    matcher = KeyMatcher(keys)
    matched: list[dict[str, Any]] = []
    for offer in offers:
        found = matcher.offer_keys(offer)
        if found:
            matched.append({**offer, "keys": found})
    return matched


# what follows in a description is an ingredient, a flavour or another variant
_KIND_CUT_RE = re.compile(
    r"(?:^|\s)(?:mit|ohne|weniger|auch|zero|oder|und|in|aus|z\.\s*b\.)(?:\s|$)", re.IGNORECASE
)


def _kind_text(offer: dict[str, Any]) -> str:
    """The kind of product named by the start of the EDEKA description: 'französischer
    Hartkäse' of 'französischer Hartkäse, 50% Fett i. Tr., je 100 g am Stück'; nothing for
    'mit Röstzwiebeln und Käse, je 100 g' or 'versch. Sorten, ohne Zucker'."""
    description = str(offer.get("description") or "")
    if description.startswith("Herkunft:"):
        description = description.split("·", 1)[-1]
    first = description.split(",", 1)[0].strip()
    if first.lower().startswith(("versch", "je ")):
        return ""
    cut = _KIND_CUT_RE.search(first)
    return first[: cut.start()] if cut else first


# ----------------------------------------------------------------------
# HTTP client
# ----------------------------------------------------------------------


class EdekaClient:
    """Minimal client for the EDEKA web site interfaces (honest User-Agent, JSON only)."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize."""
        self._session = async_get_clientsession(hass)

    async def async_get_json(self, url: str, params: dict[str, Any]) -> Any:
        """GET a JSON answer. Raises EdekaBlocked, EdekaUnexpected or EdekaError."""
        return await async_get_json(
            self._session,
            url,
            params,
            _blocked,
            _failed,
            timeout=REQUEST_TIMEOUT,
            max_bytes=MAX_BYTES,
        )

    async def async_search_markets(self, zip_code: str) -> list[dict[str, Any]]:
        """EDEKA markets near a postcode (the order of the EDEKA market search)."""
        return parse_markets(
            await self.async_get_json(
                MARKETS_URL, {"searchstring": zip_code, "size": MARKET_PAGE_SIZE}
            )
        )

    async def async_market_offers(self, market_id: str) -> dict[str, Any]:
        """The current offers of one market (see parse_offers())."""
        data = await self.async_get_json(OFFERS_URL, {"marketId": market_id, "limit": OFFER_LIMIT})
        return parse_offers(data, market_id)


# ----------------------------------------------------------------------
# The source
# ----------------------------------------------------------------------


def edeka_markets(
    manager: EssensplanerManager, branch: dict[str, Any] | None = None
) -> list[tuple[dict[str, Any], str]]:
    """(branch, market id) of the given / the selected EDEKA branches with a market id."""
    candidates = [branch] if branch is not None else manager.selected_branches()
    result: list[tuple[dict[str, Any], str]] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate.get("retailer") != RETAILER:
            continue
        market_id = str(candidate.get("edeka_market_id") or "").strip()
        if _MARKET_ID_RE.fullmatch(market_id) and market_id not in seen:
            seen.add(market_id)
            result.append((candidate, market_id))
    return result


class EdekaSource(OnlinePriceSource):
    """The leaflet offers of the linked EDEKA markets."""

    key = META_KEY
    retailer = RETAILER
    source = SOURCE
    option = CONF_EDEKA_OFFERS
    option_default = DEFAULT_EDEKA_OFFERS
    store_field = "market_id"
    title = "EDEKA-Angebote"
    site = "Die EDEKA-Website"
    site_from = "von der EDEKA-Website"
    log_name = "EDEKA offers"
    experimental = False
    kept_text = "Bisherige Angebote bleiben bis zu ihrem Ende erhalten."
    schedule_text = "morgens"

    def target(
        self, manager: EssensplanerManager, branch: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str | None]:
        """The first linked EDEKA branch and all linked market ids ("2600001,12553")."""
        markets = edeka_markets(manager, branch)
        if not markets:
            return None, None
        return markets[0][0], ",".join(m for _, m in markets)

    def no_target_message(self, manager: EssensplanerManager) -> str:
        """No EDEKA branch with a market id."""
        return MSG_NO_MARKET

    def stale(self, manager: EssensplanerManager, now: datetime) -> bool:
        """REFRESH_HOURS after the last success, when the leaflet week has ended or the
        linked markets changed."""
        meta = self.meta(manager)
        last = parse_time(meta.get("last_success"))
        if last is None or now - last >= timedelta(hours=REFRESH_HOURS):
            return True
        if str(meta.get("market_id") or "") != str(self.target(manager)[1] or ""):
            return True
        try:
            valid_to = date.fromisoformat(str(meta.get("valid_to") or "")[:10])
        except ValueError:
            return False
        return valid_to < manager.today()

    def learned_count(self, manager: EssensplanerManager) -> int:
        """EDEKA offers kept with the other offers right now."""
        return sum(1 for o in manager.offers if o.get("source") == SOURCE)

    def ok_message(self, meta: dict[str, Any], when: str) -> str:
        """Offers of the week and how many fit the plan."""
        count = int(meta.get("count") or 0)
        matched = int(meta.get("matched") or 0)
        text = f"Zuletzt am {when} aktualisiert: {count} Angebote"
        try:
            until = date.fromisoformat(str(meta.get("valid_to") or "")[:10])
            text += f" bis {until.strftime('%d.%m.')}"
        except ValueError:
            pass
        return f"{text}, {matched} passen zu deinen Rezepten und der Einkaufsliste."

    def status_extra(self, manager: EssensplanerManager, meta: dict[str, Any]) -> dict[str, Any]:
        """Leaflet week, matched offers and the markets."""
        return {
            "matched": int(meta.get("matched") or 0),
            "valid_from": meta.get("valid_from"),
            "valid_to": meta.get("valid_to"),
            "markets": [dict(m) for m in meta.get("markets") or [] if isinstance(m, dict)],
        }

    async def _async_run(
        self,
        hass: HomeAssistant,
        manager: EssensplanerManager,
        branch: dict[str, Any] | None,
        store_id: str,
        now: datetime,
    ) -> bool:
        """Fetch the offers of every linked market and keep the matching ones (True if
        they were stored, open items were assigned again then)."""
        previous = dict(self.meta(manager))
        offers, results, stop = await _async_fetch(hass, edeka_markets(manager))
        failed = {r["market_id"] for r in results if not r["ok"]}
        errors = [r["error"] for r in results if r.get("error")]
        succeeded = any(r["ok"] for r in results)
        meta = {
            **previous,
            "status": STATUS_OK if succeeded and not failed else STATUS_ERROR,
            "last_run": now.isoformat(),
            "searched": len(results),
            "errors": errors[:MAX_ERRORS],
            "blocked_until": None,
            "market_id": store_id,
            "branch_id": branch.get("id") if branch else None,
            "client": CLIENT_VERSION,
            "no_articles": False,
            "markets": [
                {k: r.get(k) for k in ("branch_id", "market_id", "count", "valid_to", "ok")}
                for r in results
            ],
        }
        if succeeded and stop is None:
            today = manager.today().isoformat()
            current = [o for o in offers if (o.get("valid_to") or "9999") >= today]
            matched = match_offers(manager, current)
            # a market that failed this time keeps its offers until they end
            kept = [
                o
                for o in manager.offers
                if o.get("source") == SOURCE and o.get("market_id") in failed
            ]
            ends = [o["valid_to"] for o in current if o.get("valid_to")]
            starts = [o["valid_from"] for o in current if o.get("valid_from")]
            meta.update(
                {
                    "status": STATUS_OK,
                    "last_success": now.isoformat(),
                    "count": len(current),
                    "matched": len(matched),
                    "learned": 0,
                    "valid_from": min(starts) if starts else None,
                    "valid_to": max(ends) if ends else None,
                }
            )
            manager.price_sources_meta[self.key] = meta
            # the whole leaflet for "Alle Angebote meiner Läden" (offer catalog, 1.4); a
            # market that failed this time keeps its offers there too
            catalog = getattr(manager, "catalog", None)
            if catalog is not None:
                previous_offers = (catalog.bucket(SOURCE, RETAILER, None) or {}).get("offers")
                kept_all = [o for o in previous_offers or [] if o.get("market_id") in failed]
                catalog.put_source(manager, SOURCE, RETAILER, [*current, *kept_all])
            manager.replace_source_offers(SOURCE, [*matched, *kept], None)
            return True
        manager.price_sources_meta[self.key] = meta
        if stop is not None:
            self.record_block(manager, stop, now)  # the offers fetched before are kept
        elif errors and not succeeded:
            _LOGGER.debug("EDEKA offers: %s", "; ".join(errors))
        return False


SOURCE_EDEKA = EdekaSource(sys.modules[__name__])


async def _async_fetch(
    hass: HomeAssistant, markets: list[tuple[dict[str, Any], str]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], SourceError | None]:
    """(offers, results per market, refusal) of the linked markets (REQUEST_DELAY apart).

    An offer of several linked markets is one offer for all their branches (branch_ids).
    A refusal / unexpected answer stops; another error only skips that market.
    """
    client = EdekaClient(hass)
    offers: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    stop: SourceError | None = None
    for position, (branch, market_id) in enumerate(markets):
        if position and REQUEST_DELAY > 0:
            await asyncio.sleep(REQUEST_DELAY)  # be polite to the web site
        result: dict[str, Any] = {"branch_id": branch.get("id"), "market_id": market_id}
        try:
            answer = await client.async_market_offers(market_id)
        except (SourceBlocked, SourceUnexpected) as err:
            stop = err
            results.append({**result, "ok": False, "error": err.message})
            break
        except SourceError as err:
            results.append({**result, "ok": False, "error": err.message})
            continue
        for offer in answer["offers"]:
            existing = offers.get(offer["id"])
            if existing is None:
                offers[offer["id"]] = {
                    **offer,
                    "branch_id": branch.get("id"),
                    "branch_ids": [branch.get("id")],
                    "branches": [branch.get("id")],
                }
            elif branch.get("id") not in existing["branch_ids"]:
                existing["branch_ids"].append(branch.get("id"))
                existing["branches"].append(branch.get("id"))
        results.append(
            {**result, "ok": True, "count": answer["count"], "valid_to": answer["valid_to"]}
        )
    return list(offers.values()), results, stop


def edeka_enabled(manager: EssensplanerManager) -> bool:
    """True if the user enabled the EDEKA offers."""
    return SOURCE_EDEKA.enabled(manager)


def edeka_status(manager: EssensplanerManager) -> dict[str, Any]:
    """EDEKA offers for the panel / services (status like rewe_status())."""
    return SOURCE_EDEKA.status(manager)


async def async_refresh_edeka_offers(
    hass: HomeAssistant, manager: EssensplanerManager, force: bool = False
) -> dict[str, Any]:
    """Fetch the offers of the linked EDEKA markets and keep the matching ones.

    Needs the option edeka_offers and a selected EDEKA branch with edeka_market_id.
    force=False runs when stale (REFRESH_HOURS, a new leaflet week, other markets);
    force=True (button, service) at most once per MANUAL_MIN_HOURS. Returns edeka_status().
    """
    return await SOURCE_EDEKA.async_refresh(hass, manager, force)


async def async_fetch_edeka_offers(
    hass: HomeAssistant, manager: EssensplanerManager
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """All current offers of the linked EDEKA markets (for the offer catalog), unmatched.

    Nothing is stored. Needs the option; nothing is sent while the source is paused (a
    refusal pauses it). Returns (offers, meta {status (ok|error|blocked|off), count,
    valid_from, valid_to, markets: [{branch_id, market_id, count, valid_to, ok}], errors}).
    """
    meta: dict[str, Any] = {"status": "off", "count": 0, "markets": [], "errors": []}
    if not edeka_enabled(manager):
        return [], meta
    now = dt_util.utcnow()
    if SOURCE_EDEKA.blocked_until(manager, now) is not None:
        return [], {**meta, "status": "blocked"}
    markets = edeka_markets(manager)
    if not markets:
        return [], {**meta, "status": "error", "errors": [MSG_NO_MARKET]}
    offers, results, stop = await _async_fetch(hass, markets)
    if stop is not None:
        SOURCE_EDEKA.record_block(manager, stop, now)
        manager._changed("price_sources")
    today = manager.today().isoformat()
    current = [o for o in offers if (o.get("valid_to") or "9999") >= today]
    ends = [o["valid_to"] for o in current if o.get("valid_to")]
    starts = [o["valid_from"] for o in current if o.get("valid_from")]
    ok = any(r["ok"] for r in results) and stop is None
    return current, {
        "status": "ok" if ok else "blocked" if isinstance(stop, SourceBlocked) else "error",
        "count": len(current),
        "valid_from": min(starts) if starts else None,
        "valid_to": max(ends) if ends else None,
        "markets": results,
        "errors": [r["error"] for r in results if r.get("error")],
        "updated": now.isoformat(),
    }


# ----------------------------------------------------------------------
# Market search (explicit user action, also with the option off)
# ----------------------------------------------------------------------


async def async_find_edeka_markets(
    hass: HomeAssistant, manager: EssensplanerManager, zip_code: str | None = None
) -> dict[str, Any]:
    """EDEKA markets near a postcode (find_edeka_markets, the panel's "Markt suchen").

    zip_code default: the postcode of the first EDEKA branch, else the zip_code option.
    Returns {zip_code, markets: [{id, name, channel, street, postcode, city, label, lat,
    lon, branch_id (EDEKA branch already linked to this market) | None}]}.
    """
    from .manager import _error  # avoid an import cycle

    text = str(zip_code or "").strip()
    if text:
        postcode = valid_postcode(text)
        if postcode is None:
            raise _error("invalid_postcode", postcode=text)
    else:
        branches = [b for b in manager.selected_branches() if b.get("retailer") == RETAILER] + [
            b for b in manager.branches if b.get("retailer") == RETAILER
        ]
        postcode = next(
            (p for b in branches if (p := valid_postcode(b.get("postcode")))), None
        ) or valid_postcode(manager.zip_code)
        if postcode is None:
            raise _error("edeka_postcode_required")
    markets = await EdekaClient(hass).async_search_markets(postcode)
    linked = {
        str(b.get("edeka_market_id") or ""): b.get("id")
        for b in manager.branches
        if b.get("retailer") == RETAILER and b.get("edeka_market_id")
    }
    for market in markets:
        market["branch_id"] = linked.get(market["id"])
    # the market search sorts by distance; the postcode's own markets first
    markets.sort(key=lambda m: m["postcode"] != postcode)
    return {"zip_code": postcode, "markets": markets[:MAX_MARKETS]}
