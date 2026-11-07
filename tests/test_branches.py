"""Branch search with OpenStreetMap (Overpass): areas, query, parsing, cache, errors (1.3)."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.essensplaner import branches
from custom_components.essensplaner.branches import (
    ATTRIBUTION,
    OVERPASS_URL,
    build_query,
    configured_zones,
    default_areas,
    default_zones,
    find_zone,
    haversine,
    parse_elements,
    route_pairs,
    search_areas,
    search_key,
    segment_distance,
)
from custom_components.essensplaner.const import (
    CONF_BRANCH_RADIUS,
    CONF_BRANCH_ROUTE,
    CONF_BRANCH_ZONES,
    DOMAIN,
    HTTP_USER_AGENT,
    STORAGE_KEY,
)
from custom_components.essensplaner.manager import error_message
from custom_components.essensplaner.retailers import retailer_for_osm

HOME = (48.137154, 11.576124)  # Marienplatz
WORK = (48.177, 11.592)  # Schwabing, ~4.6 km north
WORK_2 = (48.100, 11.520)  # ~5.8 km south west


def _zones(hass: HomeAssistant, gym: bool = True) -> None:
    """zone.home, zone.arbeit, zone.arbeit_2 (like the user's HA) and an unrelated zone."""
    for entity_id, name, (lat, lon) in (
        ("zone.home", "Zuhause", HOME),
        ("zone.arbeit", "Arbeit", WORK),
        ("zone.arbeit_2", "Arbeit 2", WORK_2),
    ):
        hass.states.async_set(
            entity_id,
            "0",
            {"latitude": lat, "longitude": lon, "radius": 100, "friendly_name": name},
        )
    if gym:
        hass.states.async_set(
            "zone.fitness",
            "0",
            {"latitude": 48.2, "longitude": 11.4, "radius": 50, "friendly_name": "Fitnessstudio"},
        )
    hass.states.async_set("zone.kaputt", "0", {"friendly_name": "Ohne Koordinaten"})


def _elements() -> dict:
    """An Overpass answer: nodes, ways and relations with center, noise and duplicates."""
    return {
        "version": 0.6,
        "elements": [
            {
                "type": "node",
                "id": 1,
                "lat": 48.1380,
                "lon": 11.5770,
                "tags": {
                    "shop": "supermarket",
                    "name": "Lidl",
                    "brand": "Lidl",
                    "addr:street": "Sendlinger Straße",
                    "addr:housenumber": "5",
                    "addr:postcode": "80331",
                    "addr:city": "München",
                    "opening_hours": "Mo-Sa 07:00-21:00",
                },
            },
            {  # plain "Aldi" without postcode, next to the Lidl -> 80331 -> Aldi Süd
                "type": "way",
                "id": 2,
                "center": {"lat": 48.1395, "lon": 11.5790},
                "tags": {"shop": "supermarket", "name": "ALDI"},
            },
            {  # the Lidl building mapped a second time (no address) -> duplicate
                "type": "way",
                "id": 3,
                "center": {"lat": 48.13805, "lon": 11.57705},
                "tags": {"shop": "supermarket", "name": "Lidl"},
            },
            {  # on the way to work
                "type": "relation",
                "id": 4,
                "center": {"lat": 48.160, "lon": 11.585},
                "tags": {
                    "shop": "supermarket",
                    "name": "Kaufland",
                    "brand": "Kaufland",
                    "addr:street": "Leopoldstraße",
                    "addr:housenumber": "100",
                    "addr:postcode": "D-80804",
                },
            },
            {  # not a known chain
                "type": "node",
                "id": 5,
                "lat": 48.1372,
                "lon": 11.5762,
                "tags": {"shop": "supermarket", "name": "Bio Markt Müller"},
            },
            {  # plain "Aldi" far away from any postcode -> undecidable, skipped
                "type": "node",
                "id": 6,
                "lat": 48.300,
                "lon": 11.900,
                "tags": {"shop": "supermarket", "name": "Aldi"},
            },
            {  # closed for good
                "type": "node",
                "id": 7,
                "lat": 48.1375,
                "lon": 11.5765,
                "tags": {"shop": "supermarket", "name": "REWE", "opening_hours": "closed"},
            },
            {"type": "node", "id": 8, "tags": {"shop": "supermarket", "name": "Penny"}},
            {
                "type": "node",
                "id": 9,
                "lat": 48.1775,
                "lon": 11.5925,
                "tags": {
                    "shop": "supermarket",
                    "name": "REWE City",
                    "brand:wikidata": "Q16968817",
                    "addr:postcode": "80803",
                },
            },
        ],
    }


async def _setup(
    hass: HomeAssistant, entry: MockConfigEntry, freezer, **options
) -> MockConfigEntry:
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(datetime.fromisoformat("2026-11-04T10:00:00+01:00"))
    assert await async_setup_component(hass, "homeassistant", {})
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _call(hass: HomeAssistant, service: str, **data):
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


def _overpass_calls(aioclient_mock: AiohttpClientMocker) -> list:
    return [c for c in aioclient_mock.mock_calls if str(c[1]) == OVERPASS_URL]


# ----------------------------------------------------------------------
# Pure helpers
# ----------------------------------------------------------------------


def test_osm_tags_to_retailer() -> None:
    """Chains from brand:wikidata, brand/name text and the Aldi postcode heuristic."""
    assert retailer_for_osm({"brand": "Lidl", "name": "Lidl"}) == ("lidl", False)
    assert retailer_for_osm({"name": "ALDI SÜD"}) == ("aldi-sued", False)
    assert retailer_for_osm({"name": "Aldi", "brand:wikidata": "Q41171373"}) == (
        "aldi-nord",
        False,
    )
    # plain "Aldi": the postcode decides (and the result is marked as guessed)
    assert retailer_for_osm({"name": "Aldi", "addr:postcode": "45127"}) == ("aldi-nord", True)
    assert retailer_for_osm({"name": "Aldi", "addr:postcode": "50667"}) == ("aldi-sued", True)
    assert retailer_for_osm({"name": "Aldi"}, "80331") == ("aldi-sued", True)
    assert retailer_for_osm({"name": "Aldi"}) == (None, True)
    assert retailer_for_osm({"name": "REWE Center"}) == ("rewe", False)
    assert retailer_for_osm({"name": "E center"}) == ("edeka", False)
    assert retailer_for_osm({"name": "Netto", "brand:wikidata": "Q552652"}) == (None, False)
    assert retailer_for_osm({"name": "Netto Marken-Discount"}) == ("netto-marken-discount", False)
    assert retailer_for_osm({"name": "Bio Markt Müller"}) == (None, False)


def test_distances() -> None:
    """Haversine and point-to-segment distances in meters."""
    assert haversine(48.0, 11.0, 48.0, 11.0) == 0
    assert haversine(48.0, 11.0, 49.0, 11.0) == pytest.approx(111195, rel=1e-3)
    # perpendicular to the segment
    assert segment_distance(48.01, 11.5, 48.0, 11.0, 48.0, 12.0) == pytest.approx(1112, rel=1e-2)
    # beyond the end: distance to the end point
    beyond = segment_distance(48.0, 12.5, 48.0, 11.0, 48.0, 12.0)
    assert beyond == pytest.approx(haversine(48.0, 12.5, 48.0, 12.0), rel=5e-3)
    # on the segment
    assert segment_distance(48.0, 11.3, 48.0, 11.0, 48.0, 12.0) < 1
    # a zero length segment is a point
    assert segment_distance(48.01, 11.0, 48.0, 11.0, 48.0, 11.0) == pytest.approx(1112, rel=1e-2)


async def test_search_areas_from_zones(hass: HomeAssistant) -> None:
    """Default areas: zone.home + 'arbeit'/'work' zones; zones by id, object id or name."""
    assert search_areas(hass, None) == []
    _zones(hass)
    hass.states.async_set(
        "zone.office",
        "0",
        {"latitude": 48.15, "longitude": 11.55, "friendly_name": "Work Office"},
    )
    assert default_zones(hass) == ["zone.home", "zone.arbeit", "zone.arbeit_2", "zone.office"]
    areas = search_areas(hass, None)
    assert [(a["zone"], a["name"], a["home"]) for a in areas] == [
        ("zone.home", "Zuhause", True),
        ("zone.arbeit", "Arbeit", False),
        ("zone.arbeit_2", "Arbeit 2", False),
        ("zone.office", "Work Office", False),
    ]
    assert (areas[0]["lat"], areas[0]["lon"]) == HOME

    assert find_zone(hass, "zone.arbeit_2").entity_id == "zone.arbeit_2"
    assert find_zone(hass, "arbeit_2").entity_id == "zone.arbeit_2"
    assert find_zone(hass, "Arbeit 2").entity_id == "zone.arbeit_2"
    assert find_zone(hass, "Fitnessstudio").entity_id == "zone.fitness"
    assert find_zone(hass, "zuhause").entity_id == "zone.home"
    assert find_zone(hass, "zone.kaputt") is None  # no coordinates
    assert find_zone(hass, "Büro") is None
    explicit = search_areas(hass, ["Fitnessstudio", "zone.home", "zone.home", "zone.nope"])
    assert [a["zone"] for a in explicit] == ["zone.fitness", "zone.home"]
    # option zones: missing ones are reported; none left -> automatic
    configured, missing = default_areas(hass, ["zone.fitness", "zone.weg"])
    assert ([a["zone"] for a in configured], missing) == (["zone.fitness"], ["zone.weg"])
    configured, missing = default_areas(hass, ["zone.weg"])
    assert [a["zone"] for a in configured] == [a["zone"] for a in areas]
    assert missing == ["zone.weg"]
    assert configured_zones("zone.home, zone.arbeit") == ["zone.home", "zone.arbeit"]
    assert configured_zones([]) is None
    assert configured_zones(None) is None

    # corridors from home to every other area, not longer than 100 km
    pairs = route_pairs(areas)
    assert [(h["zone"], o["zone"]) for h, o in pairs] == [
        ("zone.home", "zone.arbeit"),
        ("zone.home", "zone.arbeit_2"),
        ("zone.home", "zone.office"),
    ]
    far = {"zone": "zone.urlaub", "name": "Urlaub", "lat": 53.55, "lon": 9.99, "home": False}
    assert route_pairs([areas[0], far]) == []
    assert route_pairs(areas[1:]) == []  # no home zone


def test_build_query() -> None:
    """Around every area, the commute corridor as polyline, out center tags 500 (one cheap
    statement each: small timeout and memory limit, chains are recognized locally)."""
    areas = [
        {"zone": "zone.home", "name": "Zuhause", "lat": HOME[0], "lon": HOME[1], "home": True},
        {"zone": "zone.arbeit", "name": "Arbeit", "lat": WORK[0], "lon": WORK[1], "home": False},
    ]
    query = build_query(areas, 3000, True, 800)
    assert query.startswith("[out:json][timeout:25][maxsize:134217728];")
    assert query.rstrip().endswith("out center tags 500;")
    # coordinates rounded to ~100 m
    assert "(around:3000,48.137,11.576);" in query
    assert "(around:3000,48.177,11.592);" in query
    assert "(around:800,48.137,11.576,48.177,11.592);" in query
    assert "48.137154" not in query
    assert 'nwr["shop"~"^(supermarket|discount)$"](around:3000,48.137,11.576);' in query
    assert ",i]" not in query  # no costly case-insensitive regex on the server
    assert query.count("nwr[") == 3  # 2 areas + 1 corridor

    without_route = build_query(areas, 1500, False, 800)
    assert "around:800" not in without_route
    assert "(around:1500,48.137,11.576);" in without_route
    # the cache key changes with the parameters
    pairs = route_pairs(areas)
    assert search_key(areas, 3000, pairs, 800) == search_key(
        list(reversed(areas)), 3000, pairs, 800
    )
    assert search_key(areas, 3000, pairs, 800) != search_key(areas, 3000, [], 800)
    assert search_key(areas, 3000, pairs, 800) != search_key(areas, 2000, pairs, 800)


def test_parse_elements() -> None:
    """Known chains only, ways/relations via center, postcode guess, duplicates, distances."""
    areas = [
        {"zone": "zone.home", "name": "Zuhause", "lat": HOME[0], "lon": HOME[1], "home": True},
        {"zone": "zone.arbeit", "name": "Arbeit", "lat": WORK[0], "lon": WORK[1], "home": False},
    ]
    pairs = route_pairs(areas)
    stats: dict[str, int] = {}
    results = parse_elements(
        _elements(), areas, pairs, radius_m=3000, route_radius_m=800, stats=stats
    )
    by_id = {r["id"]: r for r in results}
    assert set(by_id) == {"osm_node_1", "osm_way_2", "osm_relation_4", "osm_node_9"}
    assert stats == {"elements": 8, "unknown": 1, "aldi_undecided": 1, "duplicates": 1}
    distances = [r["distance"] for r in results]
    assert distances == sorted(distances)

    lidl = by_id["osm_node_1"]
    assert lidl == {
        "id": "osm_node_1",
        "source": "osm",
        "retailer": "lidl",
        "retailer_name": "Lidl",
        "retailer_guessed": False,
        "name": "Lidl",
        "label": "Lidl Sendlinger Straße 5",
        "street": "Sendlinger Straße 5",
        "postcode": "80331",
        "postcode_guessed": False,
        "city": "München",
        "lat": 48.138,
        "lon": 11.577,
        "near": {"zone.home": round(haversine(*HOME, 48.138, 11.577))},
        "route": {"zone.arbeit": lidl["route"]["zone.arbeit"]},
        "distance": lidl["distance"],
        "opening_hours": "Mo-Sa 07:00-21:00",
    }
    assert lidl["route"]["zone.arbeit"] < lidl["near"]["zone.home"] < 150

    aldi = by_id["osm_way_2"]  # postcode of the Lidl next door -> Aldi Süd
    assert (aldi["retailer"], aldi["retailer_guessed"]) == ("aldi-sued", True)
    assert (aldi["postcode"], aldi["postcode_guessed"]) == ("80331", True)
    assert (aldi["name"], aldi["label"], aldi["street"]) == ("ALDI", "Aldi Süd", "")
    assert (aldi["lat"], aldi["lon"]) == (48.1395, 11.579)

    kaufland = by_id["osm_relation_4"]  # on the way to work, near home as well
    assert kaufland["postcode"] == "80804"
    assert kaufland["route"]["zone.arbeit"] < 800
    assert kaufland["near"] == {
        "zone.home": round(haversine(*HOME, 48.160, 11.585)),
        "zone.arbeit": round(haversine(*WORK, 48.160, 11.585)),
    }

    rewe = by_id["osm_node_9"]  # next to work: not "near" home (4.5 km)
    assert rewe["retailer"] == "rewe"
    assert set(rewe["near"]) == {"zone.arbeit"}
    assert rewe["near"]["zone.arbeit"] < 100
    assert rewe["distance"] == min(rewe["near"]["zone.arbeit"], rewe["route"]["zone.arbeit"])

    # without limits every zone is listed; a known branch helps with the postcode
    known = [{"lat": 48.300, "lon": 11.901, "postcode": "85748"}]
    all_zones = parse_elements(_elements(), areas, [], known=known)
    far_aldi = next(r for r in all_zones if r["id"] == "osm_node_6")
    assert (far_aldi["retailer"], far_aldi["postcode"], far_aldi["postcode_guessed"]) == (
        "aldi-sued",
        "85748",
        True,
    )
    assert set(far_aldi["near"]) == {"zone.home", "zone.arbeit"}
    assert far_aldi["route"] == {}
    assert parse_elements({}, areas, pairs) == []
    assert parse_elements({"elements": [None, {"type": "area", "id": 1}]}, areas, pairs) == []


# ----------------------------------------------------------------------
# Service, cache, throttle and errors
# ----------------------------------------------------------------------


async def test_find_branches_cache_and_throttle(
    hass: HomeAssistant,
    setup_integration,
    aioclient_mock: AiohttpClientMocker,
    freezer,
    hass_storage,
) -> None:
    """One request per search; cached for 30 days; at most one query every 2 minutes."""
    manager = setup_integration.runtime_data
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "find_branches")
    assert err.value.translation_key == "no_search_area"
    _zones(hass)
    aioclient_mock.post(OVERPASS_URL, json=_elements())

    result = await _call(hass, "find_branches")
    calls = _overpass_calls(aioclient_mock)
    assert len(calls) == 1
    method, _url, data, headers = calls[0]
    assert method.lower() == "post"
    assert headers["User-Agent"] == HTTP_USER_AGENT
    query = data["data"]
    assert "(around:3000,48.137,11.576);" in query
    assert "(around:3000,48.100,11.520);" in query
    assert "(around:800,48.137,11.576,48.177,11.592);" in query
    assert "(around:800,48.137,11.576,48.100,11.520);" in query
    assert "48.2" not in query  # the unrelated zone is not searched

    assert result["cached"] is False
    assert result["attribution"] == ATTRIBUTION == "© OpenStreetMap-Mitwirkende (ODbL)"
    assert result["areas"] == [
        {"zone": "zone.home", "name": "Zuhause"},
        {"zone": "zone.arbeit", "name": "Arbeit"},
        {"zone": "zone.arbeit_2", "name": "Arbeit 2"},
    ]
    assert (result["radius_km"], result["route"], result["route_radius_m"]) == (3.0, True, 800)
    assert [z["zone"] for z in result["zones"] if z["default"]] == [
        "zone.home",
        "zone.arbeit",
        "zone.arbeit_2",
    ]
    assert {r["id"] for r in result["results"]} == {
        "osm_node_1",
        "osm_way_2",
        "osm_relation_4",
        "osm_node_9",
    }
    assert result["count"] == 4
    assert all(r["saved"] is False and r["branch_id"] is None for r in result["results"])
    assert any("Aldi-Filiale" in w for w in result["warnings"])
    assert manager.branch_search["time"] == result["time"]

    # same search again: from the cache, no request
    again = await _call(hass, "find_branches")
    assert again["cached"] is True
    assert again["results"] == result["results"]
    assert len(_overpass_calls(aioclient_mock)) == 1

    # forced refresh within 2 minutes: cached result with a hint
    refreshed = await _call(hass, "find_branches", refresh=True)
    assert refreshed["cached"] is True
    assert any("Neue Suche in" in w for w in refreshed["warnings"])
    assert len(_overpass_calls(aioclient_mock)) == 1

    # another search within 2 minutes is refused
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "find_branches", radius_km=1.5)
    assert err.value.translation_key == "branch_search_wait"
    assert "Sekunden" in error_message(err.value)

    freezer.tick(timedelta(seconds=121))
    small = await _call(hass, "find_branches", radius_km=1.5, route=False, zones=["zone.home"])
    calls = _overpass_calls(aioclient_mock)
    assert len(calls) == 2
    assert "(around:1500,48.137,11.576);" in calls[1][2]["data"]
    assert "around:800" not in calls[1][2]["data"]
    assert small["cached"] is False
    assert small["areas"] == [{"zone": "zone.home", "name": "Zuhause"}]
    assert (small["radius_km"], small["route"], small["route_radius_m"]) == (1.5, False, None)

    # stored for the next start (results stay local)
    await manager.async_save_now()
    stored = hass_storage[f"{STORAGE_KEY}.{setup_integration.entry_id}"]["data"]["branch_search"]
    assert stored["key"] == manager.branch_search["key"]
    assert {r["id"] for r in stored["results"]} == {r["id"] for r in small["results"]}

    # after 30 days the cache is stale and the search runs again
    freezer.tick(timedelta(days=31))
    await _call(hass, "find_branches", radius_km=1.5, route=False, zones=["zone.home"])
    assert len(_overpass_calls(aioclient_mock)) == 3


async def test_find_branches_options_and_filters(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, aioclient_mock
) -> None:
    """Zones/radius/route from the options; retailer filter; unknown zones and stores."""
    entry = await _setup(
        hass,
        config_entry,
        freezer,
        **{
            CONF_BRANCH_ZONES: ["zone.arbeit", "zone.weg"],
            CONF_BRANCH_RADIUS: 2,
            CONF_BRANCH_ROUTE: False,
        },
    )
    _zones(hass)
    aioclient_mock.post(OVERPASS_URL, json=_elements())
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "find_branches", zones="zone.home, zone.nope")
    assert err.value.translation_key == "zone_not_found"
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "find_branches", retailers=["Lidl", "Tante Emma"])
    assert err.value.translation_key == "unknown_store"
    assert aioclient_mock.call_count == 0

    result = await _call(hass, "find_branches", retailers="REWE")
    query = _overpass_calls(aioclient_mock)[0][2]["data"]
    assert "(around:2000,48.177,11.592);" in query
    assert "48.137" not in query  # only the configured zone
    assert result["areas"] == [{"zone": "zone.arbeit", "name": "Arbeit"}]
    assert result["route"] is False
    assert [r["retailer"] for r in result["results"]] == ["rewe"]
    assert any("zone.weg" in w for w in result["warnings"])
    assert [z["zone"] for z in result["zones"] if z["default"]] == ["zone.arbeit"]

    # the filter works on the cached result; "Aldi" means both variants
    aldi = await _call(hass, "find_branches", retailers=["Aldi"])
    assert aldi["cached"] is True
    assert [(r["id"], r["retailer"]) for r in aldi["results"]] == [("osm_way_2", "aldi-sued")]
    everything = await _call(hass, "find_branches")
    assert everything["count"] == 4
    assert {r["retailer"] for r in everything["results"]} == {
        "rewe",
        "kaufland",
        "lidl",
        "aldi-sued",
    }
    # shops outside the radius (the mock answers everything) list their nearest zone
    lidl = next(r for r in everything["results"] if r["retailer"] == "lidl")
    assert set(lidl["near"]) == {"zone.arbeit"}
    assert entry.runtime_data.branch_search["radius_m"] == 2000
    assert len(_overpass_calls(aioclient_mock)) == 1

    # route requested but only one zone: hint
    hint = await _call(hass, "find_branches", zones=["zone.arbeit"], route=True)
    assert any("Arbeitsweg" in w for w in hint["warnings"])


async def test_overpass_errors(
    hass: HomeAssistant, setup_integration, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    """429 / 504 / timeouts / other errors give German messages; the cache is a fallback."""
    _zones(hass, gym=False)
    manager = setup_integration.runtime_data

    async def expect(key: str, **mock) -> str:
        aioclient_mock.clear_requests()
        aioclient_mock.post(OVERPASS_URL, **mock)
        freezer.tick(timedelta(seconds=121))
        with pytest.raises(HomeAssistantError) as err:
            await _call(hass, "find_branches", refresh=True)
        assert err.value.translation_key == key
        return error_message(err.value)

    busy = await expect("overpass_busy", status=429)
    assert busy == (
        "OpenStreetMap ist gerade ausgelastet – bitte in ein paar Minuten erneut versuchen."
    )
    assert manager.branch_search["error"] == busy
    assert "nicht rechtzeitig" in await expect("overpass_timeout", status=504)
    assert "nicht rechtzeitig" in await expect("overpass_timeout", exc=TimeoutError())
    assert "nicht rechtzeitig" in await expect(
        "overpass_timeout",
        json={"elements": [], "remark": 'runtime error: Query timed out in "query" at line 3'},
    )
    assert "HTTP 500" in await expect("overpass_failed", status=500)
    assert "unerwartete Antwort" in await expect("overpass_failed", text="<html>Fehler</html>")
    # a failed query also counts for the throttle
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "find_branches", radius_km=1)
    assert err.value.translation_key == "branch_search_wait"

    # with a cached result of the same search, errors become a warning
    aioclient_mock.clear_requests()
    aioclient_mock.post(OVERPASS_URL, json=_elements())
    freezer.tick(timedelta(seconds=121))
    ok = await _call(hass, "find_branches")
    assert ok["cached"] is False
    assert manager.branch_search["error"] is None
    aioclient_mock.clear_requests()
    aioclient_mock.post(OVERPASS_URL, status=429)
    freezer.tick(timedelta(seconds=121))
    fallback = await _call(hass, "find_branches", refresh=True)
    assert fallback["cached"] is True
    assert fallback["results"] == ok["results"]
    assert any(w.startswith(busy) and "04.11.2026" in w for w in fallback["warnings"])

    # partial results are kept with a hint
    aioclient_mock.clear_requests()
    aioclient_mock.post(
        OVERPASS_URL, json={**_elements(), "remark": "runtime error: Query ran out of memory"}
    )
    freezer.tick(timedelta(seconds=121))
    partial = await _call(hass, "find_branches", refresh=True)
    assert partial["count"] == 4
    assert any("nur einen Teil" in w for w in partial["warnings"])


async def test_websocket_save_and_saved_flag(
    hass: HomeAssistant,
    setup_integration,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client,
) -> None:
    """The panel searches via websocket, saves a result by id; saved results are marked."""
    from custom_components.essensplaner.diagnostics import async_get_config_entry_diagnostics

    manager = setup_integration.runtime_data
    _zones(hass)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/find_branches", "cached_only": True})
    msg = await client.receive_json()
    assert msg["success"]
    assert (msg["result"]["results"], msg["result"]["cached"]) == ([], False)
    assert aioclient_mock.call_count == 0

    await client.send_json({"id": 2, "type": f"{DOMAIN}/find_branches", "zones": ["zone.nope"]})
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "zone_not_found"
    assert msg["error"]["message"] == "Die Zone „zone.nope“ habe ich nicht gefunden."

    aioclient_mock.post(OVERPASS_URL, json=_elements())
    await client.send_json(
        {"id": 3, "type": f"{DOMAIN}/find_branches", "radius_km": 3, "route_radius_m": 800}
    )
    msg = await client.receive_json()
    assert msg["success"]
    result = msg["result"]
    assert result["cached"] is False
    assert result["count"] == 4

    # a manual branch at the same street counts as saved
    manual = manager.save_branch(
        {"store": "Lidl", "street": "Sendlinger Straße 5", "postcode": "80331"}
    )
    # saving a result by its id keeps address, coordinates and the zone distances
    kaufland = next(r for r in result["results"] if r["id"] == "osm_relation_4")
    saved = (await _call(hass, "save_branch", id="osm_relation_4"))["branch"]
    assert saved["id"] == "osm_relation_4"
    assert saved["source"] == "osm"
    assert (saved["retailer"], saved["retailer_guessed"]) == ("kaufland", False)
    assert (saved["street"], saved["postcode"], saved["postcode_guessed"]) == (
        "Leopoldstraße 100",
        "80804",
        False,
    )
    assert (saved["lat"], saved["lon"]) == (48.16, 11.585)
    assert saved["near"] == kaufland["near"]
    assert saved["route"] == kaufland["route"]
    assert saved["label"] == "Kaufland Leopoldstraße 100"
    # given fields win over the search result
    aldi = (await _call(hass, "save_branch", id="osm_way_2", store="Aldi Nord", label="Aldi Ecke"))[
        "branch"
    ]
    assert (aldi["retailer"], aldi["label"], aldi["postcode"]) == (
        "aldi-nord",
        "Aldi Ecke",
        "80331",
    )
    assert aldi["postcode_guessed"] is True
    assert aldi["near"] == next(r for r in result["results"] if r["id"] == "osm_way_2")["near"]

    await client.send_json({"id": 4, "type": f"{DOMAIN}/find_branches"})
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"]["cached"] is True
    flags = {r["id"]: (r["saved"], r["branch_id"]) for r in msg["result"]["results"]}
    assert flags == {
        "osm_node_1": (True, manual["id"]),
        "osm_way_2": (True, "osm_way_2"),
        "osm_relation_4": (True, "osm_relation_4"),
        "osm_node_9": (False, None),
    }
    assert aioclient_mock.call_count == 1

    # cached_only: the last search without a request
    await client.send_json(
        {"id": 5, "type": f"{DOMAIN}/find_branches", "cached_only": True, "retailers": ["rewe"]}
    )
    msg = await client.receive_json()
    assert [r["id"] for r in msg["result"]["results"]] == ["osm_node_9"]
    assert msg["result"]["cached"] is True

    # an OSM id that is not in the last search needs the store
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "save_branch", id="osm_node_12345")
    assert err.value.translation_key == "store_required"

    # diagnostics: no search results, no cache key, no coordinates
    diagnostics = await async_get_config_entry_diagnostics(hass, setup_integration)
    assert "results" not in diagnostics["branch_search"]
    assert "key" not in diagnostics["branch_search"]
    assert "Leopoldstraße" not in str(diagnostics)
    assert "48.16" not in str(diagnostics)


async def test_no_request_without_user_action(
    hass: HomeAssistant, setup_integration, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    """Nothing is sent to OpenStreetMap on start, on branch changes or over time."""
    _zones(hass)
    manager = setup_integration.runtime_data
    manager.save_branch({"store": "Lidl", "postcode": "80331"})
    freezer.tick(timedelta(days=2))
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == 0
    assert branches.MIN_INTERVAL == 120
    assert branches.CACHE_DAYS == 30
