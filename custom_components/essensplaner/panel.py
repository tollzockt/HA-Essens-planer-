"""Sidebar panel and websocket API for the Essensplaner frontend."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from homeassistant.components import websocket_api
from homeassistant.core import Event, HomeAssistant, callback
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


@callback
def async_setup_websocket(hass: HomeAssistant) -> None:
    """Register websocket commands."""
    websocket_api.async_register_command(hass, ws_get_data)
    websocket_api.async_register_command(hass, ws_subscribe)
