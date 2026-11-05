"""Essensplaner – meal planner, recipes and shopping list for Home Assistant."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_call_later, async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .const import (
    CONF_IMPORT_STARTER,
    CONF_REGISTER_INTENTS,
    CONF_SHOW_PANEL,
    DOMAIN,
    OFFERS_MARKTGURU,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .intents import async_register_intents, async_remove_intents
from .manager import EssensplanerManager
from .offers import async_refresh_offers
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

    if manager.offers_source == OFFERS_MARKTGURU:
        # postcodes come from the options or the branches (can change without a reload)
        _setup_offer_refresh(hass, entry, manager)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


def _setup_offer_refresh(
    hass: HomeAssistant, entry: EssensplanerConfigEntry, manager: EssensplanerManager
) -> None:
    """Refresh offers once a day and shortly after start if they are stale."""

    async def _refresh(_now: datetime | None = None) -> None:
        if not manager.offer_targets():
            return  # no zip code and no branch with a postcode yet
        try:
            meta = await async_refresh_offers(hass, manager)
        except Exception:
            _LOGGER.exception("Refreshing offers failed")
            return
        if meta.get("status") == "error":
            _LOGGER.warning("Essensplaner offers: %s", "; ".join(meta.get("errors") or []))

    last = manager.offers_meta.get("last_update")
    stale = True
    if last and (parsed := dt_util.parse_datetime(last)):
        stale = dt_util.utcnow() - parsed > timedelta(hours=20)
    if stale:
        entry.async_on_unload(async_call_later(hass, 90, _refresh))
    # spread the daily request over the morning (stable per installation)
    minute = sum(ord(c) for c in entry.entry_id) % 50 + 5
    entry.async_on_unload(async_track_time_change(hass, _refresh, hour=6, minute=minute, second=0))


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
