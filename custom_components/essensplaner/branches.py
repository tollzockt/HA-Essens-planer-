"""Branch search with OpenStreetMap (Overpass API), incl. the commute corridor.

Only runs when the user starts a search (service find_branches / panel button). The
coordinates of the chosen Home Assistant zones are sent to overpass-api.de, rounded to
three decimals (about 100 m). Results are cached in the store file (manager.branch_search)
for CACHE_DAYS days and live queries are throttled to one per MIN_INTERVAL seconds.

Search areas: zone.home plus the zones whose entity id or name contains "arbeit" / "work"
(or the zones of the branch_zones option / the service call). The commute corridor is the
straight line from zone.home to each other zone (Overpass "around" accepts a polyline).

Data © OpenStreetMap contributors, ODbL (ATTRIBUTION is part of every response).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
import hashlib
import json
import logging
import math
import re
from typing import TYPE_CHECKING, Any

import aiohttp
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util, slugify

from .const import (
    CONF_BRANCH_RADIUS,
    CONF_BRANCH_ROUTE,
    CONF_BRANCH_ROUTE_RADIUS,
    CONF_BRANCH_ZONES,
    DEFAULT_BRANCH_RADIUS,
    DEFAULT_BRANCH_ROUTE,
    DEFAULT_BRANCH_ROUTE_RADIUS,
    DOMAIN,
    HTTP_USER_AGENT,
)
from .ingredients import fold
from .netio import BodyTooLarge, async_read_body
from .retailers import ALDI_NORD, ALDI_SUED, resolve_retailer, retailer_for_osm, retailer_name

if TYPE_CHECKING:
    from .manager import EssensplanerManager

_LOGGER = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# tried when the main server stays busy (public instances listed on the OSM wiki)
OVERPASS_MIRRORS: tuple[str, ...] = ("https://overpass.kumi.systems/api/interpreter",)
ATTRIBUTION = "© OpenStreetMap-Mitwirkende (ODbL)"

# cache lifetime of a search, minimum seconds between two live queries
CACHE_DAYS = 30
MIN_INTERVAL = 120
# Overpass: server side timeout (s) and memory (small values are admitted first when the
# server is busy), HTTP timeout per attempt (s), maximum number of elements.
# The public server queues requests when it is full ("at capacity") and often answers only
# after a minute; a busy answer is retried after RETRY_DELAYS seconds (then the mirrors),
# all attempts together take at most TOTAL_TIMEOUT seconds.
QUERY_TIMEOUT = 25
QUERY_MAXSIZE = 128 * 1024 * 1024
REQUEST_TIMEOUT = 90
RETRY_DELAYS: tuple[float, ...] = (5, 15)
TOTAL_TIMEOUT = 240
MAX_ELEMENTS = 500
_MAX_BYTES = 4 * 1024 * 1024
# coordinates sent to Overpass are rounded to this many decimals (~100 m)
COORD_DECIMALS = 3
# search parameter limits (radius in km, corridor width in m)
RADIUS_KM_RANGE = (0.5, 25.0)
ROUTE_RADIUS_RANGE = (100, 5000)
# corridors longer than this are not searched (only the radius around the zone)
MAX_ROUTE_KM = 100
# a shop without postcode gets the postcode of the nearest shop / branch within this distance
POSTCODE_GUESS_M = 1500
# the same chain within this distance is one shop (mapped as node and building)
DUPLICATE_M = 50
# a manual branch of the same chain within this distance is the found shop
SAME_BRANCH_M = 100
# results slightly outside the radius still count as "near" (way centers, rounding)
_TOLERANCE = 1.15
_TOLERANCE_M = 150

HOME_ZONE = "zone.home"
WORK_WORDS = ("arbeit", "work")
_HOME_WORDS = {"home", "zuhause", "daheim", "heim", "zu hause"}
# shops tagged like supermarkets, prefiltered by chain name or brand on the server
SHOP_PATTERN = "^(supermarket|discount)$"
CHAIN_PATTERN = (
    "aldi|lidl|rewe|edeka|e.?center|e aktiv|neukauf|penny|netto|kaufland|norma|globus|marktkauf"
)
_POSTCODE_IN_TEXT = re.compile(r"(?<!\d)(\d{5})(?!\d)")
_CLOSED = {"closed", "off"}
EARTH_RADIUS_M = 6371000.0
_METERS_PER_DEGREE = EARTH_RADIUS_M * math.pi / 180

MSG_BUSY = "OpenStreetMap ist gerade ausgelastet – bitte in ein paar Minuten erneut versuchen."
MSG_TIMEOUT = (
    "OpenStreetMap hat nicht rechtzeitig geantwortet – bitte später erneut versuchen "
    "oder den Radius verkleinern."
)


class BranchSearchError(HomeAssistantError):
    """The Overpass query failed (translation keys overpass_busy/_timeout/_failed)."""

    def __init__(self, key: str, message: str, **placeholders: str) -> None:
        """Error with a translation key and a German message (for warnings)."""
        super().__init__(
            translation_domain=DOMAIN,
            translation_key=key,
            translation_placeholders=placeholders,
        )
        self.message = message


# ----------------------------------------------------------------------
# Distances
# ----------------------------------------------------------------------


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great circle distance in meters."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def segment_distance(
    lat: float, lon: float, lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Distance in meters from a point to the segment (lat1, lon1)-(lat2, lon2).

    Local equirectangular projection around the point (accurate for a few 100 km).
    """
    ky = EARTH_RADIUS_M * math.pi / 180
    kx = ky * math.cos(math.radians(lat))
    ax, ay = (lon1 - lon) * kx, (lat1 - lat) * ky
    bx, by = (lon2 - lon) * kx, (lat2 - lat) * ky
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    t = 0.0 if length == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / length))
    return math.hypot(ax + t * dx, ay + t * dy)


def _within(lat1: float, lon1: float, lat2: float, lon2: float, meters: float) -> float | None:
    """The distance if it is at most meters, else None (cheap latitude check first)."""
    if abs(lat1 - lat2) * _METERS_PER_DEGREE > meters:
        return None
    distance = haversine(lat1, lon1, lat2, lon2)
    return distance if distance <= meters else None


# ----------------------------------------------------------------------
# Search areas (Home Assistant zones)
# ----------------------------------------------------------------------


def _coords(state: State | None) -> tuple[float, float] | None:
    if state is None:
        return None
    try:
        lat = float(state.attributes["latitude"])
        lon = float(state.attributes["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def _zone_name(state: State) -> str:
    return str(state.attributes.get("friendly_name") or state.object_id)


def zone_states(hass: HomeAssistant) -> list[State]:
    """All zones with coordinates, zone.home first."""
    zones = [s for s in hass.states.async_all("zone") if _coords(s)]
    return sorted(zones, key=lambda s: (s.entity_id != HOME_ZONE, s.entity_id))


def find_zone(hass: HomeAssistant, text: str | None) -> State | None:
    """A zone by entity id ('zone.arbeit'), object id ('arbeit_2') or name ('Arbeit 2')."""
    raw = str(text or "").strip()
    if not raw:
        return None
    lowered = raw.lower()
    if lowered.startswith("zone."):
        state = hass.states.get(lowered)
        return state if _coords(state) else None
    folded = fold(raw)
    if folded in _HOME_WORDS:
        state = hass.states.get(HOME_ZONE)
        if _coords(state):
            return state
    state = hass.states.get(f"zone.{slugify(raw)}")
    if _coords(state):
        return state
    return next((s for s in zone_states(hass) if fold(_zone_name(s)) == folded), None)


def _area(state: State) -> dict[str, Any]:
    lat, lon = _coords(state) or (0.0, 0.0)
    return {
        "zone": state.entity_id,
        "name": _zone_name(state),
        "lat": lat,
        "lon": lon,
        "home": state.entity_id == HOME_ZONE,
    }


def _is_work_zone(state: State) -> bool:
    text = f"{fold(state.entity_id)} {fold(_zone_name(state))}"
    return any(word in text for word in WORK_WORDS)


def default_zones(hass: HomeAssistant) -> list[str]:
    """zone.home plus the zones with "arbeit"/"work" in their entity id or name."""
    return [s.entity_id for s in zone_states(hass) if s.entity_id == HOME_ZONE or _is_work_zone(s)]


def search_areas(hass: HomeAssistant, zones: list[str] | None = None) -> list[dict[str, Any]]:
    """Search areas [{zone, name, lat, lon, home}] (unknown zones are skipped).

    zones None or empty: zone.home + "arbeit"/"work" zones (see default_zones()).
    """
    states: list[State] = []
    if zones:
        for text in zones:
            state = find_zone(hass, text)
            if state is not None and state not in states:
                states.append(state)
    else:
        states = [s for s in (hass.states.get(z) for z in default_zones(hass)) if s]
    return [_area(s) for s in states]


def route_pairs(
    areas: list[dict[str, Any]], max_km: float = MAX_ROUTE_KM
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Commute segments: zone.home -> every other area (at most max_km long, not 0 m)."""
    home = next((a for a in areas if a["zone"] == HOME_ZONE), None)
    if home is None:
        return []
    pairs = []
    for other in areas:
        if other is home:
            continue
        length = haversine(home["lat"], home["lon"], other["lat"], other["lon"])
        if 100 <= length <= max_km * 1000:
            pairs.append((home, other))
    return pairs


# ----------------------------------------------------------------------
# Query and parsing
# ----------------------------------------------------------------------


def _coord_text(value: float) -> str:
    return f"{round(value, COORD_DECIMALS):.{COORD_DECIMALS}f}"


def build_query(
    areas: list[dict[str, Any]], radius_m: int, route: bool, route_radius_m: int
) -> str:
    """Overpass QL: supermarket chains around each area and along the commute corridors."""
    # one cheap statement per area: the public server rejects or drops costly queries
    # (case-insensitive name/brand regexes, a big memory limit) when it is busy; the chains
    # are recognized locally (retailer_for_osm)
    filters = [f'["shop"~"{SHOP_PATTERN}"]']
    spatial = [
        f"(around:{int(radius_m)},{_coord_text(a['lat'])},{_coord_text(a['lon'])})" for a in areas
    ]
    if route:
        spatial += [
            f"(around:{int(route_radius_m)},{_coord_text(home['lat'])},"
            f"{_coord_text(home['lon'])},{_coord_text(other['lat'])},{_coord_text(other['lon'])})"
            for home, other in route_pairs(areas)
        ]
    lines = [f"  nwr{tag_filter}{around};" for around in spatial for tag_filter in filters]
    return (
        f"[out:json][timeout:{QUERY_TIMEOUT}][maxsize:{QUERY_MAXSIZE}];\n(\n"
        + "\n".join(lines)
        + f"\n);\nout center tags {MAX_ELEMENTS};"
    )


def _element_coords(element: dict[str, Any]) -> tuple[float, float] | None:
    source = element if element.get("type") == "node" else element.get("center") or {}
    try:
        lat, lon = float(source["lat"]), float(source["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    return lat, lon


def _postcode(tags: dict[str, Any]) -> str | None:
    match = _POSTCODE_IN_TEXT.search(str(tags.get("addr:postcode") or ""))
    return match.group(1) if match else None


def _street(tags: dict[str, Any]) -> str:
    street = str(tags.get("addr:street") or tags.get("addr:place") or "").strip()
    number = str(tags.get("addr:housenumber") or "").strip()
    return f"{street} {number}".strip() if street else ""


def _label(retailer: str, street: str, city: str) -> str:
    return f"{retailer_name(retailer)} {street or city}".strip()


def _completeness(result: dict[str, Any]) -> tuple[int, int]:
    return (
        bool(result["street"]) + bool(result["postcode"] and not result["postcode_guessed"]),
        result["id"].startswith("osm_node_"),
    )


def parse_elements(
    data: dict[str, Any],
    areas: list[dict[str, Any]],
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    *,
    radius_m: float | None = None,
    route_radius_m: float | None = None,
    known: list[dict[str, Any]] | None = None,
    stats: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Overpass elements -> branch candidates of known chains, nearest first.

    Each result: {id ("osm_node_1" | "osm_way_2" | "osm_relation_3"), source "osm", retailer,
    retailer_name, retailer_guessed, name, label, street, postcode, postcode_guessed, city,
    lat, lon, near {zone: m}, route {zone: m (to the zone.home -> zone segment)}, distance,
    opening_hours?}.

    near/route only list zones within radius_m / route_radius_m (with a small tolerance; all
    zones if not given; the nearest zone if none). A shop without addr:postcode gets the
    postcode of the nearest shop or known branch (dicts with lat/lon/postcode) within
    POSTCODE_GUESS_M (postcode_guessed True), else None. A plain "Aldi" is decided by
    brand:wikidata, else by its (guessed) postcode; without one it is skipped. The same chain
    within DUPLICATE_M is one shop (the better tagged element wins). stats (if given)
    receives counts: elements, unknown, aldi_undecided, duplicates.
    """
    counts = {"elements": 0, "unknown": 0, "aldi_undecided": 0, "duplicates": 0}
    raw: list[dict[str, Any]] = []
    for element in (data or {}).get("elements") or []:
        if not isinstance(element, dict):
            continue
        kind, osm_id = element.get("type"), element.get("id")
        if kind not in ("node", "way", "relation") or osm_id is None:
            continue
        coords = _element_coords(element)
        if coords is None:
            continue
        counts["elements"] += 1
        tags = element.get("tags") or {}
        if str(tags.get("opening_hours") or "").strip().lower() in _CLOSED:
            continue
        raw.append({"id": f"osm_{kind}_{osm_id}", "tags": tags, "lat": coords[0], "lon": coords[1]})

    # postcodes: own tag, else the nearest shop / known branch with one
    sources = [(r["lat"], r["lon"], code) for r in raw if (code := _postcode(r["tags"]))]
    for branch in known or []:
        code = branch.get("postcode")
        if code and not branch.get("postcode_guessed") and branch.get("lat") is not None:
            try:
                sources.append((float(branch["lat"]), float(branch["lon"]), str(code)))
            except (TypeError, ValueError, KeyError):
                continue

    results: list[dict[str, Any]] = []
    for item in raw:
        tags = item["tags"]
        postcode = _postcode(tags)
        guessed_postcode = False
        if postcode is None:
            close = [
                (distance, code)
                for lat, lon, code in sources
                if (distance := _within(item["lat"], item["lon"], lat, lon, POSTCODE_GUESS_M))
                is not None
            ]
            if close:
                postcode, guessed_postcode = min(close)[1], True
        retailer, guessed = retailer_for_osm(tags, postcode)
        if retailer is None:
            counts["aldi_undecided" if guessed else "unknown"] += 1
            continue
        lat, lon = item["lat"], item["lon"]
        all_near = {a["zone"]: haversine(lat, lon, a["lat"], a["lon"]) for a in areas}
        route = {
            other["zone"]: segment_distance(
                lat, lon, home["lat"], home["lon"], other["lat"], other["lon"]
            )
            for home, other in pairs
        }
        near = dict(all_near)
        if radius_m is not None:
            near = {z: d for z, d in near.items() if d <= radius_m * _TOLERANCE + _TOLERANCE_M}
        if route_radius_m is not None:
            limit = route_radius_m * _TOLERANCE + _TOLERANCE_M
            route = {z: d for z, d in route.items() if d <= limit}
        if not near and not route and all_near:
            zone = min(all_near, key=lambda z: all_near[z])
            near = {zone: all_near[zone]}
        street = _street(tags)
        city = str(tags.get("addr:city") or "").strip()
        result = {
            "id": item["id"],
            "source": "osm",
            "retailer": retailer,
            "retailer_name": retailer_name(retailer),
            "retailer_guessed": guessed,
            "name": str(tags.get("name") or tags.get("brand") or retailer_name(retailer)).strip(),
            "label": _label(retailer, street, city),
            "street": street,
            "postcode": postcode,
            "postcode_guessed": guessed_postcode,
            "city": city,
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "near": {z: round(d) for z, d in near.items()},
            "route": {z: round(d) for z, d in route.items()},
        }
        result["distance"] = min([*result["near"].values(), *result["route"].values()], default=0)
        if tags.get("opening_hours"):
            result["opening_hours"] = str(tags["opening_hours"])
        results.append(result)

    # one shop mapped twice (node + building): keep the better tagged element
    results.sort(key=_completeness, reverse=True)
    unique: list[dict[str, Any]] = []
    for result in results:
        if any(
            other["retailer"] == result["retailer"]
            and _within(other["lat"], other["lon"], result["lat"], result["lon"], DUPLICATE_M)
            is not None
            for other in unique
        ):
            counts["duplicates"] += 1
            continue
        unique.append(result)
    unique.sort(key=lambda r: (r["distance"], fold(r["label"]), r["id"]))
    if stats is not None:
        stats.update(counts)
    return unique


def search_key(
    areas: list[dict[str, Any]],
    radius_m: int,
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    route_radius_m: int,
) -> str:
    """Cache key of a search (hash, so the coordinates are not readable from it)."""
    payload = {
        "v": 2,
        "areas": sorted([a["zone"], round(a["lat"], 4), round(a["lon"], 4)] for a in areas),
        "radius": int(radius_m),
        "route": sorted([home["zone"], other["zone"]] for home, other in pairs),
        "route_radius": int(route_radius_m) if pairs else 0,
        "chains": CHAIN_PATTERN,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:20]


# ----------------------------------------------------------------------
# Overpass client
# ----------------------------------------------------------------------


async def async_overpass_query(hass: HomeAssistant, query: str) -> dict[str, Any]:
    """POST a query to the Overpass API, retrying a busy / slow server and then the mirrors.

    Raises BranchSearchError (the last error when every attempt failed).
    """
    session = async_get_clientsession(hass)
    attempts = [(OVERPASS_URL, 0.0)]
    attempts += [(OVERPASS_URL, float(delay)) for delay in RETRY_DELAYS]
    attempts += [(url, 0.0) for url in OVERPASS_MIRRORS]
    loop_time = asyncio.get_running_loop().time
    started = loop_time()
    last: BranchSearchError | None = None
    for url, delay in attempts:
        left = TOTAL_TIMEOUT - (loop_time() - started) - delay
        if last is not None and left < 10:
            break
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            return await _async_post(session, url, query, min(REQUEST_TIMEOUT, max(left, 10)))
        except BranchSearchError as err:
            if err.translation_key not in ("overpass_busy", "overpass_timeout"):
                raise
            _LOGGER.debug("Overpass %s: %s – retrying", url, err.message)
            last = err
    raise last or _failed("keine Antwort")


async def _async_post(
    session: aiohttp.ClientSession, url: str, query: str, timeout: float
) -> dict[str, Any]:
    """One Overpass request. Raises BranchSearchError."""
    try:
        async with session.post(
            url,
            data={"data": query},
            headers={"User-Agent": HTTP_USER_AGENT, "Accept": "application/json"},
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            # 502/503 "at capacity" / 429 "too many requests": busy, try again later
            if resp.status in (429, 502, 503):
                raise BranchSearchError("overpass_busy", MSG_BUSY)
            if resp.status == 504:
                raise BranchSearchError("overpass_timeout", MSG_TIMEOUT)
            if resp.status != 200:
                raise _failed(f"HTTP {resp.status}")
            body = await async_read_body(resp, _MAX_BYTES)
    except BodyTooLarge as err:
        raise _failed("Antwort zu groß") from err
    except TimeoutError as err:
        raise BranchSearchError("overpass_timeout", MSG_TIMEOUT) from err
    except aiohttp.ClientError as err:
        if isinstance(err, aiohttp.ClientConnectionError):
            # connection reset / refused: an overloaded server, worth another attempt
            raise BranchSearchError("overpass_busy", MSG_BUSY) from err
        raise _failed(str(err) or type(err).__name__) from err
    try:
        data = json.loads(body.decode("utf-8", errors="replace"))
    except ValueError as err:
        raise _failed("unerwartete Antwort") from err
    if not isinstance(data, dict):
        raise _failed("unerwartete Antwort")
    remark = str(data.get("remark") or "")
    if remark and not data.get("elements"):
        _LOGGER.debug("Overpass remark: %s", remark)
        if "timed out" in remark or "timeout" in remark.lower():
            raise BranchSearchError("overpass_timeout", MSG_TIMEOUT)
        if "runtime error" in remark:
            raise _failed(remark[:120])
    return data


def _failed(error: str) -> BranchSearchError:
    return BranchSearchError(
        "overpass_failed",
        f"Die Filialsuche bei OpenStreetMap ist fehlgeschlagen ({error}).",
        error=error,
    )


# ----------------------------------------------------------------------
# Search (service find_branches / websocket essensplaner/find_branches)
# ----------------------------------------------------------------------


def _number(value: Any, default: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float(default)
    return max(low, min(high, number))


def search_defaults(options: dict[str, Any]) -> dict[str, Any]:
    """Default search parameters from the options (preset of the panel's search form)."""
    return {
        "radius_km": _number(
            options.get(CONF_BRANCH_RADIUS, DEFAULT_BRANCH_RADIUS),
            DEFAULT_BRANCH_RADIUS,
            *RADIUS_KM_RANGE,
        ),
        "route": bool(options.get(CONF_BRANCH_ROUTE, DEFAULT_BRANCH_ROUTE)),
        "route_radius_m": round(
            _number(
                options.get(CONF_BRANCH_ROUTE_RADIUS, DEFAULT_BRANCH_ROUTE_RADIUS),
                DEFAULT_BRANCH_ROUTE_RADIUS,
                *ROUTE_RADIUS_RANGE,
            )
        ),
    }


def _resolve_retailers(manager: EssensplanerManager, texts: list[str] | None) -> set[str] | None:
    """Retailer ids for a filter; a plain 'Aldi' means both variants."""
    if not texts:
        return None
    from .manager import _error

    found: set[str] = set()
    for text in texts:
        retailer = resolve_retailer(text)
        if retailer is None and fold(str(text)) == "aldi":
            found |= {ALDI_SUED, ALDI_NORD}
            continue
        if retailer is None:
            raise _error("unknown_store", store=text)
        found.add(retailer)
    return found


def _saved_branch(manager: EssensplanerManager, result: dict[str, Any]) -> str | None:
    """Id of the user's branch for a search result (same OSM id, or same chain nearby).

    A branch with coordinates counts within SAME_BRANCH_M; one without coordinates if
    street (and postcode, where both have one) are the same.
    """
    if manager.get_branch(result["id"]):
        return result["id"]
    for branch in manager.branches:
        if branch.get("retailer") != result["retailer"]:
            continue
        try:
            lat, lon = float(branch["lat"]), float(branch["lon"])
        except (KeyError, TypeError, ValueError):
            lat = lon = None
        if lat is not None and lon is not None:
            if haversine(lat, lon, result["lat"], result["lon"]) <= SAME_BRANCH_M:
                return branch.get("id")
            continue
        street = fold(str(branch.get("street") or ""))
        postcodes = {branch.get("postcode") or None, result.get("postcode") or None} - {None}
        if street and street == fold(result.get("street") or "") and len(postcodes) <= 1:
            return branch.get("id")
    return None


def _view(
    manager: EssensplanerManager,
    search: dict[str, Any],
    *,
    cached: bool,
    warnings: list[str],
    retailers: set[str] | None,
    zones: list[dict[str, Any]],
) -> dict[str, Any]:
    results = []
    for result in search.get("results") or []:
        if not isinstance(result, dict) or not result.get("id"):
            continue
        if retailers is not None and result.get("retailer") not in retailers:
            continue
        branch_id = _saved_branch(manager, result)
        results.append({**result, "saved": branch_id is not None, "branch_id": branch_id})
    all_warnings: list[str] = []
    for warning in [*(search.get("warnings") or []), *warnings]:
        if warning not in all_warnings:
            all_warnings.append(warning)
    return {
        "results": results,
        "count": len(results),
        "areas": [{"zone": a["zone"], "name": a["name"]} for a in search.get("areas") or []],
        "radius_km": round((search.get("radius_m") or 0) / 1000, 2),
        "route": bool(search.get("route")),
        "route_radius_m": search.get("route_radius_m"),
        "cached": cached,
        "time": search.get("time"),
        "attribution": ATTRIBUTION,
        "warnings": all_warnings,
        "error": search.get("error"),
        "zones": zones,
    }


def configured_zones(value: Any) -> list[str] | None:
    """The branch_zones option as a list (None or empty = automatic)."""
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, (list, tuple)):
        return None
    return [str(z).strip() for z in value if str(z or "").strip()] or None


def default_areas(
    hass: HomeAssistant, configured: list[str] | None
) -> tuple[list[dict[str, Any]], list[str]]:
    """(areas, missing zones) of the branch_zones option; automatic if none of them exists."""
    missing = [z for z in configured or [] if find_zone(hass, z) is None]
    areas = search_areas(hass, configured) if configured else []
    return areas or search_areas(hass, None), missing


def zones_view(hass: HomeAssistant, configured: list[str] | None) -> list[dict[str, Any]]:
    """All zones for the panel's zone chips; default = searched without a zone choice."""
    defaults = {a["zone"] for a in default_areas(hass, configured)[0]}
    return [
        {"zone": s.entity_id, "name": _zone_name(s), "default": s.entity_id in defaults}
        for s in zone_states(hass)
    ]


async def async_find_branches(
    hass: HomeAssistant,
    manager: EssensplanerManager,
    zones: list[str] | None = None,
    radius_km: float | None = None,
    route: bool | None = None,
    route_radius_m: int | None = None,
    retailers: list[str] | None = None,
    refresh: bool = False,
    cached_only: bool = False,
) -> dict[str, Any]:
    """Find supermarkets near the zones and along the way to work (OpenStreetMap).

    Defaults come from the options branch_zones (None = zone.home + work zones),
    branch_radius_km, branch_route and branch_route_radius_m. A search with the same areas
    and parameters is answered from the cache for CACHE_DAYS days (refresh=True forces a
    new query). Live queries are at least MIN_INTERVAL seconds apart: within that time the
    cached result of the same search is returned with a warning, another search raises
    branch_search_wait. If the query fails, a cached result of the same search is returned
    with the error as warning, else the error (overpass_busy / overpass_timeout /
    overpass_failed) is raised. cached_only returns the last stored search without any
    request (parameters ignored).

    Returns {results: [... + saved, branch_id], count, areas: [{zone, name}], radius_km,
    route, route_radius_m, cached, time, attribution, warnings, error (of the last query
    attempt), zones: [{zone, name, default}]}.
    """
    from .manager import _error

    options = manager.options
    configured = configured_zones(options.get(CONF_BRANCH_ZONES))
    zone_list = zones_view(hass, configured)
    retailer_filter = _resolve_retailers(manager, retailers)
    search = manager.branch_search
    if cached_only:
        has_results = isinstance(search.get("results"), list) and bool(search.get("time"))
        return _view(
            manager,
            search,
            cached=has_results,
            warnings=[],
            retailers=retailer_filter,
            zones=zone_list,
        )

    warnings: list[str] = []
    if zones:
        missing = [z for z in zones if find_zone(hass, z) is None]
        if missing:
            raise _error("zone_not_found", zone=", ".join(missing))
        areas = search_areas(hass, zones)
    else:
        areas, missing = default_areas(hass, configured)
        warnings += [f"Die Zone „{z}“ gibt es nicht – sie wurde übersprungen." for z in missing]
    if not areas:
        raise _error("no_search_area")

    radius_m = round(
        _number(
            options.get(CONF_BRANCH_RADIUS, DEFAULT_BRANCH_RADIUS)
            if radius_km is None
            else radius_km,
            DEFAULT_BRANCH_RADIUS,
            *RADIUS_KM_RANGE,
        )
        * 1000
    )
    use_route = bool(
        options.get(CONF_BRANCH_ROUTE, DEFAULT_BRANCH_ROUTE) if route is None else route
    )
    corridor_m = round(
        _number(
            options.get(CONF_BRANCH_ROUTE_RADIUS, DEFAULT_BRANCH_ROUTE_RADIUS)
            if route_radius_m is None
            else route_radius_m,
            DEFAULT_BRANCH_ROUTE_RADIUS,
            *ROUTE_RADIUS_RANGE,
        )
    )
    pairs = route_pairs(areas) if use_route else []
    if use_route:
        home = next((a for a in areas if a["zone"] == HOME_ZONE), None)
        if home is None or len(areas) < 2:
            warnings.append(
                "Für den Arbeitsweg werden die Zone „Zuhause“ und mindestens eine weitere "
                "Zone benötigt – es wurde nur im Umkreis gesucht."
            )
        else:
            linked = {other["zone"] for _, other in pairs}
            warnings += [
                f"Der Weg zu „{a['name']}“ ist länger als {MAX_ROUTE_KM} km – dort wird nur "
                "im Umkreis gesucht."
                for a in areas
                if a is not home
                and a["zone"] not in linked
                and haversine(home["lat"], home["lon"], a["lat"], a["lon"]) > MAX_ROUTE_KM * 1000
            ]
    key = search_key(areas, radius_m, pairs, corridor_m)

    if manager._branch_lock is None:
        manager._branch_lock = asyncio.Lock()
    async with manager._branch_lock:
        search = manager.branch_search
        now = dt_util.utcnow()
        same = search.get("key") == key and isinstance(search.get("results"), list)
        found_at = dt_util.parse_datetime(str(search.get("time") or "")) if same else None
        fresh = found_at is not None and now - found_at < timedelta(days=CACHE_DAYS)
        view = {"retailers": retailer_filter, "zones": zone_list}
        if fresh and not refresh:
            return _view(manager, search, cached=True, warnings=warnings, **view)

        last = dt_util.parse_datetime(str(search.get("last_query") or ""))
        elapsed = (now - last).total_seconds() if last else None
        if elapsed is not None and 0 <= elapsed < MIN_INTERVAL:
            wait = math.ceil(MIN_INTERVAL - elapsed)
            if found_at is not None:
                warnings.append(
                    f"Die letzte Suche ist erst {int(elapsed)} Sekunden her – gezeigt wird "
                    f"das gespeicherte Ergebnis. Neue Suche in {wait} Sekunden möglich."
                )
                return _view(manager, search, cached=True, warnings=warnings, **view)
            raise _error("branch_search_wait", seconds=wait)

        query = build_query(areas, radius_m, bool(pairs), corridor_m)
        search["last_query"] = now.isoformat()
        try:
            data = await async_overpass_query(hass, query)
        except BranchSearchError as err:
            search["error"] = err.message
            manager._save_later()
            if found_at is not None:
                stamp = dt_util.as_local(found_at).strftime("%d.%m.%Y")
                warnings.append(
                    f"{err.message} Gezeigt wird das gespeicherte Ergebnis vom {stamp}."
                )
                return _view(manager, search, cached=True, warnings=warnings, **view)
            raise

        stats: dict[str, int] = {}
        results = parse_elements(
            data,
            areas,
            pairs,
            radius_m=radius_m,
            route_radius_m=corridor_m if pairs else None,
            known=manager.branches,
            stats=stats,
        )
        stored_warnings: list[str] = []
        if stats.get("elements", 0) >= MAX_ELEMENTS:
            stored_warnings.append(
                f"Sehr viele Treffer – es wurden nur die ersten {MAX_ELEMENTS} ausgewertet. "
                "Bitte den Radius verkleinern."
            )
        if data.get("remark"):
            stored_warnings.append(
                "OpenStreetMap hat nur einen Teil der Ergebnisse geliefert – bitte später "
                "erneut suchen."
            )
        if undecided := stats.get("aldi_undecided"):
            stored_warnings.append(
                f"{undecided} Aldi-Filiale(n) ohne Postleitzahl: Süd oder Nord ist unklar – "
                "bitte manuell hinzufügen."
            )
        manager.branch_search = {
            "key": key,
            "time": now.isoformat(),
            "last_query": now.isoformat(),
            "results": results,
            "warnings": stored_warnings,
            "error": None,
            "areas": [{"zone": a["zone"], "name": a["name"]} for a in areas],
            "radius_m": radius_m,
            "route": bool(pairs),
            "route_radius_m": corridor_m if pairs else None,
            "elements": stats.get("elements", 0),
        }
        manager._save_later()
        _LOGGER.debug(
            "Branch search: %d shops (%d elements) in %d areas, %d corridors",
            len(results),
            stats.get("elements", 0),
            len(areas),
            len(pairs),
        )
        return _view(manager, manager.branch_search, cached=False, warnings=warnings, **view)
