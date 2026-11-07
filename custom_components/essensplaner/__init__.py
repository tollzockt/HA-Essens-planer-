"""Essensplaner – meal planner, recipes and shopping list for Home Assistant."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_call_later, async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .aldi import (
    RETAILER as ALDI_SUED,
    SOURCE_ALDI,
    aldi_enabled,
    async_aldi_live,
    async_refresh_aldi_prices,
)
from .articles import register_live_provider
from .catalog import OfferCatalog, async_refresh_catalog, marktguru_enabled
from .const import (
    CONF_IMPORT_STARTER,
    CONF_REGISTER_INTENTS,
    CONF_SHOW_PANEL,
    DOMAIN,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .edeka import SOURCE_EDEKA, async_refresh_edeka_offers, edeka_enabled
from .intents import async_register_intents, async_remove_intents
from .manager import EssensplanerManager
from .online_prices import STATUS_BLOCKED, STATUS_ERROR, OnlinePriceSource
from .panel import (
    async_register_card,
    async_register_panel,
    async_remove_panel,
    async_setup_websocket,
)
from .receipts import ReceiptStore, async_register_views
from .rewe import (
    RETAILER as REWE,
    SOURCE_REWE,
    async_refresh_rewe_prices,
    async_rewe_live,
    rewe_enabled,
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
    # receipt photos: upload and (signed) image links of the panel
    async_register_views(hass)
    # article search: REWE online shop and ALDI SÜD (experimental, only while their option
    # is on)
    register_live_provider(REWE, async_rewe_live, rewe_enabled)
    register_live_provider(ALDI_SUED, async_aldi_live, aldi_enabled)
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

    @callback
    def _new_day(now: datetime) -> None:
        """Expired offers go; items bought on an offer that ended are assigned again."""
        manager.new_day()

    entry.async_on_unload(async_track_time_change(hass, _new_day, hour=0, minute=1, second=0))

    if marktguru_enabled(manager) or aldi_enabled(manager):
        # the offer catalog of the saved stores (marktguru, ALDI SÜD weekly offers; EDEKA
        # stores its own refresh there); postcodes come from the options or the branches
        _setup_offer_refresh(hass, entry, manager)
    if rewe_enabled(manager):
        # experimental REWE online prices (opt-in; options changes reload the entry)
        _setup_rewe_refresh(hass, entry, manager)
    if aldi_enabled(manager):
        # experimental ALDI SÜD prices: weekly like REWE, half an hour later
        _setup_source_refresh(
            hass,
            entry,
            manager,
            SOURCE_ALDI,
            async_refresh_aldi_prices,
            ALDI_START_DELAY,
            4,
            (_daily_minute(entry) + 30) % 60,
        )
    if edeka_enabled(manager):
        # offers of the linked EDEKA market: daily at 06:xx (after the marktguru offers)
        _setup_source_refresh(
            hass,
            entry,
            manager,
            SOURCE_EDEKA,
            async_refresh_edeka_offers,
            EDEKA_START_DELAY,
            6,
            (_daily_minute(entry) + 5) % 60,
        )
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


# seconds after start until the first offers / REWE / ALDI SÜD / EDEKA check
OFFERS_START_DELAY = 90
REWE_START_DELAY = 150
ALDI_START_DELAY = 180
EDEKA_START_DELAY = 120


def _daily_minute(entry: EssensplanerConfigEntry) -> int:
    """Minute of the daily requests (stable per installation, spread over the hour)."""
    return sum(ord(c) for c in entry.entry_id) % 50 + 5


def _setup_offer_refresh(
    hass: HomeAssistant, entry: EssensplanerConfigEntry, manager: EssensplanerManager
) -> None:
    """Check the offer catalog shortly after start and daily at 06:xx (it only fetches when
    stale: 3 days, a new leaflet week, other stores) and a minute after a branch change
    that needs a postcode or chain not fetched yet."""

    async def _async_refresh() -> None:
        if marktguru_enabled(manager) and not manager.offer_targets() and not aldi_enabled(manager):
            return  # no zip code and no branch with a postcode yet
        before = manager.catalog.data.get("last_run")
        try:
            meta = await async_refresh_catalog(hass, manager, force=False)
        except Exception:
            _LOGGER.exception("Refreshing offers failed")
            return
        ran = manager.catalog.data.get("last_run") != before
        if ran and meta.get("status") in ("error", "blocked"):
            _LOGGER.warning("Essensplaner offers: %s", "; ".join(meta.get("errors") or []))
        # a branch saved while this (or the joined) refresh ran: its postcode was not
        # searched yet (the run's targets are in offers_meta, so this ends)
        manager.schedule_offer_refresh()

    @callback
    def _refresh(_now: datetime | None = None) -> None:
        # tied to the entry: cancelled on unload / reload, does not delay a restart
        entry.async_create_background_task(hass, _async_refresh(), "essensplaner_offers")

    # shortly after start (sends nothing while the catalog is fresh)
    entry.async_on_unload(async_call_later(hass, OFFERS_START_DELAY, _refresh))
    # a new branch at a postcode (or of a chain) not searched yet: search shortly after
    entry.async_on_unload(manager.enable_offer_refresh(_refresh))
    # spread the daily request over the morning (stable per installation)
    entry.async_on_unload(
        async_track_time_change(hass, _refresh, hour=6, minute=_daily_minute(entry), second=0)
    )


def _setup_rewe_refresh(
    hass: HomeAssistant, entry: EssensplanerConfigEntry, manager: EssensplanerManager
) -> None:
    """Check shortly after start and daily at 04:xx; prices are only fetched when the last
    success is a week old (or there was none)."""
    _setup_source_refresh(
        hass,
        entry,
        manager,
        SOURCE_REWE,
        async_refresh_rewe_prices,
        REWE_START_DELAY,
        4,
        _daily_minute(entry),
    )


def _setup_source_refresh(
    hass: HomeAssistant,
    entry: EssensplanerConfigEntry,
    manager: EssensplanerManager,
    source: OnlinePriceSource,
    refresh: Callable[[HomeAssistant, EssensplanerManager], Awaitable[dict[str, Any]]],
    start_delay: float,
    hour: int,
    minute: int,
) -> None:
    """Check an online source shortly after start and daily at hour:minute; the source
    only sends requests when its data is stale (REWE / ALDI SÜD: a week, EDEKA: a day or a
    new leaflet week) and never while it is paused."""

    async def _async_check() -> None:
        if not source.enabled(manager):
            return
        before = source.meta(manager).get("last_run")
        try:
            status = await refresh(hass, manager)
        except Exception:
            _LOGGER.exception("Refreshing %s failed", source.log_name)
            return
        if status.get("last_run") != before and status["status"] in (STATUS_ERROR, STATUS_BLOCKED):
            _LOGGER.warning(
                "Essensplaner %s%s: %s",
                source.log_name,
                " (experimental)" if source.experimental else "",
                "; ".join(status.get("errors") or []) or status["message"],
            )

    @callback
    def _check(_now: datetime | None = None) -> None:
        entry.async_create_background_task(
            hass, _async_check(), f"essensplaner_{source.key}_refresh"
        )

    # shortly after start too: data that was never fetched (or is stale) does not wait
    # for the next day (the check sends nothing while the data is fresh or paused)
    entry.async_on_unload(async_call_later(hass, start_delay, _check))
    entry.async_on_unload(async_track_time_change(hass, _check, hour=hour, minute=minute, second=0))


async def _async_update_listener(hass: HomeAssistant, entry: EssensplanerConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: EssensplanerConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        manager = entry.runtime_data
        await manager.async_save_now()
        await manager.catalog.async_save()
        await manager.receipts.async_save()
        # refreshes still running (services, panel) must not write over the new manager's data
        manager.unloaded = True
        manager.catalog.unloaded = True
        manager.receipts.unloaded = True
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove stored data when the integration is deleted (also the offer catalog, the
    receipts and their image files – nothing else of the media folder)."""
    await Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry.entry_id}").async_remove()
    await OfferCatalog(hass, entry.entry_id).async_remove()
    await ReceiptStore(hass, entry.entry_id).async_remove()
