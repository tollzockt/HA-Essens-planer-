"""Sidebar panel and websocket API for the Essensplaner frontend."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from homeassistant.components import websocket_api
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
import voluptuous as vol

from .const import (
    CARD_FILE,
    DOMAIN,
    EVENT_UPDATED,
    NAME,
    PANEL_COMPONENT,
    PANEL_STATIC_URL,
    PANEL_URL_PATH,
)

_LOGGER = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).parent / "frontend"
_STATIC_REGISTERED = f"{DOMAIN}_static_registered"
_CARD_REGISTERED = f"{DOMAIN}_card_registered"


def _version() -> str:
    try:
        manifest = json.loads((Path(__file__).parent / "manifest.json").read_text())
        return str(manifest.get("version", "0"))
    except (OSError, ValueError):
        return "0"


async def _async_register_static(hass: HomeAssistant) -> bool:
    """Serve the frontend folder. Returns False if the frontend is unavailable."""
    if "frontend" not in hass.config.components or hass.http is None:
        _LOGGER.debug("Frontend not loaded, skipping panel and card")
        return False
    # Imported lazily so the integration also works without the frontend (tests).
    from homeassistant.components.http import StaticPathConfig

    if not hass.data.get(_STATIC_REGISTERED):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(PANEL_STATIC_URL, str(FRONTEND_DIR), cache_headers=False)]
        )
        hass.data[_STATIC_REGISTERED] = True
    return True


async def async_register_card(hass: HomeAssistant) -> None:
    """Load the dashboard card on every frontend page (no manual resource needed)."""
    if hass.data.get(_CARD_REGISTERED) or not await _async_register_static(hass):
        return
    from homeassistant.components.frontend import add_extra_js_url

    version = await hass.async_add_executor_job(_version)
    add_extra_js_url(hass, f"{PANEL_STATIC_URL}/{CARD_FILE}?v={version}")
    hass.data[_CARD_REGISTERED] = True


async def async_register_panel(hass: HomeAssistant) -> bool:
    """Register the sidebar panel. Returns False if the frontend is unavailable."""
    if not await _async_register_static(hass):
        return False
    from homeassistant.components import panel_custom

    version = await hass.async_add_executor_job(_version)
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_COMPONENT,
        sidebar_title=NAME,
        sidebar_icon="mdi:silverware-fork-knife",
        module_url=f"{PANEL_STATIC_URL}/essensplaner-panel.js?v={version}",
        require_admin=False,
        config={},
    )
    return True


@callback
def async_remove_panel(hass: HomeAssistant) -> None:
    """Remove the sidebar panel."""
    from homeassistant.components import frontend

    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)


def _entity_ids(hass: HomeAssistant, entry_id: str) -> dict[str, str | None]:
    registry = er.async_get(hass)
    return {
        "shopping_list": registry.async_get_entity_id("todo", DOMAIN, f"{entry_id}_shopping_list"),
        "calendar": registry.async_get_entity_id("calendar", DOMAIN, f"{entry_id}_meal_plan"),
        "next_meal": registry.async_get_entity_id("sensor", DOMAIN, f"{entry_id}_next_meal"),
    }


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/data"})
@callback
def ws_get_data(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return all data for the panel."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], "not_loaded", "Essensplaner ist nicht eingerichtet")
        return
    entry = entries[0]
    manager = entry.runtime_data
    data = manager.export()
    data["entities"] = _entity_ids(hass, entry.entry_id)
    # readable names of the "immer hier kaufen" products (also ones not on the list)
    data["store_preference_names"] = {
        key: manager._preference_name(key) for key in data.get("store_preferences") or {}
    }
    connection.send_result(msg["id"], data)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/subscribe"})
@callback
def ws_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Notify the panel whenever data changes."""

    @callback
    def forward(event: Event) -> None:
        connection.send_message(websocket_api.event_message(msg["id"], dict(event.data)))

    connection.subscriptions[msg["id"]] = hass.bus.async_listen(EVENT_UPDATED, forward)
    connection.send_result(msg["id"])


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/prices"})
@callback
def ws_get_prices(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """All known ingredient prices (estimates, learned, own)."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], "not_loaded", "Essensplaner ist nicht eingerichtet")
        return
    connection.send_result(msg["id"], {"prices": entries[0].runtime_data.prices_view()})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/store_prices",
        vol.Optional("query"): str,
        vol.Optional("limit", default=400): vol.All(int, vol.Range(min=1, max=2000)),
    }
)
@callback
def ws_store_prices(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Price list per store (estimate + each retailer's prices)."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], "not_loaded", "Essensplaner ist nicht eingerichtet")
        return
    connection.send_result(
        msg["id"], entries[0].runtime_data.store_price_matrix(msg.get("query"), msg["limit"])
    )


def _loaded_manager(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> Any:
    """The manager of the loaded entry (sends an error and returns None if not loaded)."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], "not_loaded", "Essensplaner ist nicht eingerichtet")
        return None
    return entries[0].runtime_data


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/branches"})
@callback
def ws_branches(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """The user's branches, the main branch and the postcodes offers are searched at."""
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    connection.send_result(msg["id"], manager.branches_export())


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/reorder_branches", vol.Required("ids"): [str]}
)
@callback
def ws_reorder_branches(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Change the order (priority) of the branches."""
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    manager.reorder_branches(msg["ids"])
    connection.send_result(msg["id"], manager.branches_export())


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/forget_store_preference", vol.Required("key"): str}
)
@callback
def ws_forget_store_preference(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """✕ at a product of "Immer hier gekauft": forget exactly this remembered product key.

    The panel has the stored key; the set_shopping_store service would parse it as a
    spoken name again ("bio milch" is "Milch") and might find another list item
    ("Vollmilch" for "milch"). Open items of this product are assigned automatically
    again: a store choice at the forgotten chain came with "immer" (set_shopping_store
    always=True sets both) and is dropped, one at another store is the item's own choice
    and stays. Result {key, retailer (None if nothing was remembered), items: [uid]}.
    """
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    key = msg["key"]
    retailer = manager.store_preferences.pop(key, None)
    manager.store_preference_aliases.pop(key, None)
    if retailer is None:
        connection.send_result(msg["id"], {"key": key, "retailer": None, "items": []})
        return
    items = [i for i in manager.shopping if i.get("key") == key]
    for item in items:
        override = manager.get_branch(item.get("store_override"))
        if override is not None and override.get("retailer") != retailer:
            continue  # the item's own choice of another store
        item.pop("store_override", None)
        if isinstance(item.get("chosen"), dict):
            item["chosen"].pop("pins_store", None)
    open_items = [i for i in items if i.get("status") != "completed"]
    if manager.store_split_active:
        manager.assign_stores(open_items)
        for item in open_items:
            manager.update_shopping_description(item)
    manager._changed("shopping")
    connection.send_result(
        msg["id"],
        {"key": key, "retailer": retailer, "items": [i["uid"] for i in open_items]},
    )


def merge_article_results(
    manager: Any,
    query: str,
    local: list[dict[str, Any]],
    live: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    """Local and live article hits in one order: offers and exact matches first, at most limit.

    Both lists come ranked from the manager (match quality); this only merges them. Live
    offers that are also saved offers (local hits) are left out. When the query names an
    article (a hit matches it exactly, e.g. "Butter"), an offer that is another product
    ("Butterkekse", "Erdnussbutter", "Gehackte Tomaten" for "Tomaten" – the manager's
    _is_article rule, as for the shopping list) ranks like a substring match, so it never
    comes before the article itself. A match is only ever lowered here, never raised.
    """
    from .articles import MATCH_EXACT, MATCH_SUBSTRING, _sort_key
    from .ingredients import ingredient_key

    known = {(r.get("offer") or {}).get("id") for r in local if r.get("offer")}
    merged = [*local, *(r for r in live if (r.get("offer") or {}).get("id") not in known)]
    key = ingredient_key(query)
    if key and any(r["match"] == MATCH_EXACT for r in merged):

        def other_product(result: dict[str, Any]) -> bool:
            if result["source"] not in ("offer", "live"):
                return False
            if not MATCH_EXACT < result["match"] < MATCH_SUBSTRING:
                return False
            texts = (result.get("title") or "", result.get("key") or "")
            return not any(manager._is_article(t, key) for t in texts if t)

        merged = [{**r, "match": MATCH_SUBSTRING} if other_product(r) else r for r in merged]
    merged.sort(key=lambda r: (_sort_key(r), r.get("unit_price") or 9e9, r.get("price") or 0))
    return merged[: max(1, limit)]


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/article_search",
        vol.Required("query"): str,
        vol.Optional("store"): vol.Any(str, None),
        vol.Optional("live", default=False): bool,
        vol.Optional("limit", default=10): vol.All(int, vol.Range(min=1, max=50)),
    }
)
@websocket_api.async_response
async def ws_article_search(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Articles for the "Artikel hinzufügen" field (local; live=True also online sources).

    Result {query, store: {branch_id, retailer, retailer_name, label, postcode, main} | None,
    results: [...], live: bool, error: str | None}.
    """
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .manager import error_message  # avoid loading the manager for the panel only

    query = msg["query"]
    try:
        branch, retailer = manager.article_target(msg.get("store"))
        results = manager.search_articles(query, msg.get("store"), msg["limit"])
        response = {"results": [], "live": False, "error": None}
        if msg["live"]:
            response = await manager.async_search_articles_live(
                query, msg.get("store"), msg["limit"]
            )
    except ServiceValidationError as err:
        connection.send_error(msg["id"], "invalid_store", error_message(err))
        return
    connection.send_result(
        msg["id"],
        {
            "query": query,
            "store": manager.article_store_info(branch, retailer),
            "results": merge_article_results(
                manager, query, results, response["results"], msg["limit"]
            ),
            "live": response["live"],
            "error": response["error"],
            "superseded": bool(response.get("superseded")),
        },
    )


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/compare_prices", vol.Required("item"): str}
)
@callback
def ws_compare_prices(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Price of a product at every selected store (store picker of the shopping list)."""
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .manager import error_message

    try:
        result = manager.compare_prices(msg["item"])
    except ServiceValidationError as err:
        connection.send_error(msg["id"], "invalid_item", error_message(err))
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/find_branches",
        vol.Optional("zones"): [str],
        vol.Optional("radius_km"): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=25)),
        vol.Optional("route"): bool,
        vol.Optional("route_radius_m"): vol.All(vol.Coerce(int), vol.Range(min=100, max=5000)),
        vol.Optional("retailers"): [str],
        vol.Optional("refresh", default=False): bool,
        vol.Optional("cached_only", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_find_branches(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Supermarkets near the zones and on the way to work (OpenStreetMap).

    Same parameters and result as the find_branches service (plus "defaults": the radius
    and commute settings from the options); cached_only=True returns the last stored search
    without any request. Error codes are the translation keys
    (overpass_busy, overpass_timeout, overpass_failed, branch_search_wait,
    zone_not_found, no_search_area, unknown_store) with a German message.
    """
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .branches import async_find_branches, search_defaults
    from .manager import error_message

    try:
        result = await async_find_branches(
            hass,
            manager,
            zones=msg.get("zones") or None,
            radius_km=msg.get("radius_km"),
            route=msg.get("route"),
            route_radius_m=msg.get("route_radius_m"),
            retailers=msg.get("retailers") or None,
            refresh=msg["refresh"],
            cached_only=msg["cached_only"],
        )
    except HomeAssistantError as err:
        code = getattr(err, "translation_key", None) or "search_failed"
        connection.send_error(msg["id"], code, error_message(err))
        return
    # preset of the panel's search form (radius / commute from the options)
    connection.send_result(msg["id"], {**result, "defaults": search_defaults(manager.options)})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/rewe_markets", vol.Optional("zip"): vol.Any(str, None)}
)
@websocket_api.async_response
async def ws_rewe_markets(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """REWE markets near a postcode ("Markt suchen" of a REWE branch, experimental).

    Same result as the find_rewe_markets service: {zip_code, markets: [{id, name, street,
    postcode, city, label, lat, lon, branch_id}]}. Error codes are the translation keys
    (invalid_postcode, rewe_postcode_required, rewe_blocked, rewe_failed) with a German
    message.
    """
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .manager import error_message
    from .rewe import async_find_rewe_markets

    try:
        result = await async_find_rewe_markets(hass, manager, msg.get("zip"))
    except HomeAssistantError as err:
        code = getattr(err, "translation_key", None) or "search_failed"
        connection.send_error(msg["id"], code, error_message(err))
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/edeka_markets", vol.Optional("zip"): vol.Any(str, None)}
)
@websocket_api.async_response
async def ws_edeka_markets(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """EDEKA markets near a postcode ("Markt suchen" of an EDEKA branch).

    Same result as the find_edeka_markets service: {zip_code, markets: [{id, name, channel,
    street, postcode, city, label, lat, lon, branch_id}]}. Error codes are the translation
    keys (invalid_postcode, edeka_postcode_required, edeka_blocked, edeka_failed) with a
    German message.
    """
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .edeka import async_find_edeka_markets
    from .manager import error_message

    try:
        result = await async_find_edeka_markets(hass, manager, msg.get("zip"))
    except HomeAssistantError as err:
        code = getattr(err, "translation_key", None) or "search_failed"
        connection.send_error(msg["id"], code, error_message(err))
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/aldi_stores",
        vol.Optional("zip"): vol.Any(str, None),
        vol.Inclusive("lat", "location"): vol.All(vol.Coerce(float), vol.Range(min=-90, max=90)),
        vol.Inclusive("lon", "location"): vol.All(vol.Coerce(float), vol.Range(min=-180, max=180)),
    }
)
@websocket_api.async_response
async def ws_aldi_stores(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """ALDI SÜD stores near a location ("Filiale suchen" of an ALDI SÜD branch).

    Same result as the find_aldi_stores service: {location: {lat, lon, source, zip_code},
    stores: [{id, name, street, postcode, city, label, lat, lon, distance_km, branch_id}]}.
    Error codes are the translation keys (invalid_postcode, aldi_postcode_unknown,
    aldi_location_required, aldi_blocked, aldi_failed) with a German message.
    """
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .aldi import async_find_aldi_stores
    from .manager import error_message

    try:
        result = await async_find_aldi_stores(
            hass, manager, msg.get("zip"), msg.get("lat"), msg.get("lon")
        )
    except HomeAssistantError as err:
        code = getattr(err, "translation_key", None) or "search_failed"
        connection.send_error(msg["id"], code, error_message(err))
        return
    connection.send_result(msg["id"], result)


@callback
def async_setup_websocket(hass: HomeAssistant) -> None:
    """Register websocket commands."""
    websocket_api.async_register_command(hass, ws_get_data)
    websocket_api.async_register_command(hass, ws_subscribe)
    websocket_api.async_register_command(hass, ws_get_prices)
    websocket_api.async_register_command(hass, ws_store_prices)
    websocket_api.async_register_command(hass, ws_branches)
    websocket_api.async_register_command(hass, ws_reorder_branches)
    websocket_api.async_register_command(hass, ws_forget_store_preference)
    websocket_api.async_register_command(hass, ws_article_search)
    websocket_api.async_register_command(hass, ws_compare_prices)
    websocket_api.async_register_command(hass, ws_find_branches)
    websocket_api.async_register_command(hass, ws_rewe_markets)
    websocket_api.async_register_command(hass, ws_edeka_markets)
    websocket_api.async_register_command(hass, ws_aldi_stores)
