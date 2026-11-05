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
    data = entry.runtime_data.export()
    data["entities"] = _entity_ids(hass, entry.entry_id)
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
    known = {(r["offer"] or {}).get("id") for r in results if r.get("offer")}
    results += [r for r in response["results"] if (r["offer"] or {}).get("id") not in known]
    connection.send_result(
        msg["id"],
        {
            "query": query,
            "store": manager.article_store_info(branch, retailer),
            "results": results,
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

    Same parameters and result as the find_branches service; cached_only=True returns the
    last stored search without any request. Error codes are the translation keys
    (overpass_busy, overpass_timeout, overpass_failed, branch_search_wait,
    zone_not_found, no_search_area, unknown_store) with a German message.
    """
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .branches import async_find_branches
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
    connection.send_result(msg["id"], result)


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


@callback
def async_setup_websocket(hass: HomeAssistant) -> None:
    """Register websocket commands."""
    websocket_api.async_register_command(hass, ws_get_data)
    websocket_api.async_register_command(hass, ws_subscribe)
    websocket_api.async_register_command(hass, ws_get_prices)
    websocket_api.async_register_command(hass, ws_store_prices)
    websocket_api.async_register_command(hass, ws_branches)
    websocket_api.async_register_command(hass, ws_reorder_branches)
    websocket_api.async_register_command(hass, ws_article_search)
    websocket_api.async_register_command(hass, ws_compare_prices)
    websocket_api.async_register_command(hass, ws_find_branches)
    websocket_api.async_register_command(hass, ws_rewe_markets)
