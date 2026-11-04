"""Essensplaner – meal planner, recipes and shopping list for Home Assistant."""

from __future__ import annotations

from datetime import datetime
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_IMPORT_STARTER,
    CONF_REGISTER_INTENTS,
    CONF_SHOW_PANEL,
    DOMAIN,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .intents import async_register_intents, async_remove_intents
from .manager import EssensplanerManager
from .panel import (
    async_register_card,
    async_register_panel,
    async_remove_panel,
    async_setup_websocket,
)
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BUTTON, Platform.CALENDAR, Platform.SENSOR, Platform.TODO]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type EssensplanerConfigEntry = ConfigEntry[EssensplanerManager]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up services and websocket commands."""
    async_setup_services(hass)
    async_setup_websocket(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: EssensplanerConfigEntry) -> bool:
    """Set up the Essensplaner from a config entry."""
    manager = EssensplanerManager(hass, entry)
    await manager.async_load(import_starter=entry.data.get(CONF_IMPORT_STARTER, True))
    entry.runtime_data = manager

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    options = manager.options
    if options.get(CONF_REGISTER_INTENTS, True):
        async_register_intents(hass)

        @callback
        def _remove_intents() -> None:
            async_remove_intents(hass)

        entry.async_on_unload(_remove_intents)

    await async_register_card(hass)  # dashboard card, loaded on every frontend page
    if options.get(CONF_SHOW_PANEL, True) and await async_register_panel(hass):

        @callback
        def _remove_panel() -> None:
            async_remove_panel(hass)

        entry.async_on_unload(_remove_panel)

    @callback
    def _refresh(now: datetime) -> None:
        """Day changes / next meal changes over time."""
        manager.async_refresh_listeners()

    entry.async_on_unload(async_track_time_change(hass, _refresh, minute="/15", second=0))

    @callback
    def _auto_cooked(now: datetime | None = None) -> None:
        """Count yesterday's planned meals as cooked."""
        manager.async_auto_mark_cooked()

    _auto_cooked()
    entry.async_on_unload(async_track_time_change(hass, _auto_cooked, hour=0, minute=5, second=0))
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: EssensplanerConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: EssensplanerConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_save_now()
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove stored data when the integration is deleted."""
    await Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry.entry_id}").async_remove()
