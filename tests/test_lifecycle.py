"""Long refreshes and reloads of the config entry (options change = reload)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.essensplaner import offers, rewe
from custom_components.essensplaner.const import (
    CONF_OFFERS_SOURCE,
    CONF_REWE_ONLINE,
    CONF_WATCHLIST,
    CONF_ZIP,
    DOMAIN,
    STORAGE_KEY,
)

NOW = datetime.fromisoformat("2026-11-04T10:00:00+01:00")
BUTTER = {
    "id": "B1",
    "productName": "ja! Deutsche Markenbutter",
    "price": 199,
    "grammage": "250g (1 kg = 7,96 €)",
}


@pytest.fixture(autouse=True)
def no_delays(monkeypatch) -> None:
    """No pauses between requests."""
    monkeypatch.setattr(rewe, "REQUEST_DELAY", 0)
    monkeypatch.setattr(rewe, "MAX_TERMS", 3)


async def _setup(hass: HomeAssistant, entry: MockConfigEntry, freezer, **options) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(NOW)
    assert await async_setup_component(hass, "homeassistant", {})
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _stored(hass_storage, entry: MockConfigEntry) -> dict:
    return hass_storage[f"{STORAGE_KEY}.{entry.entry_id}"]["data"]


async def _flush(hass: HomeAssistant, freezer) -> None:
    """Let delayed saves run."""
    freezer.tick(timedelta(seconds=5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_refresh_after_reload_does_not_overwrite(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer, hass_storage, monkeypatch
) -> None:
    """A REWE refresh that finishes after a reload keeps its hands off the new data."""
    await _setup(hass, config_entry, freezer, **{CONF_REWE_ONLINE: True, CONF_WATCHLIST: "Butter"})
    old = config_entry.runtime_data
    old.save_branch({"store": "REWE", "postcode": "80331", "rewe_market_id": "1940178"})
    gate = asyncio.Event()
    started = asyncio.Event()

    async def slow_search(self, term: str, market_id: str) -> list[dict]:
        started.set()
        await gate.wait()
        return [rewe.parse_product(BUTTER, term)]

    monkeypatch.setattr(rewe.ReweClient, "async_search_products", slow_search)
    task = hass.async_create_background_task(
        hass.services.async_call(
            DOMAIN, "refresh_prices", {"source": "rewe"}, blocking=True, return_response=True
        ),
        "test refresh",
    )
    await started.wait()

    # options change -> reload while the refresh is still waiting for REWE
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    new = config_entry.runtime_data
    assert new is not old and old.unloaded and not new.unloaded
    new.shopping_add("Zucker")
    await _flush(hass, freezer)
    assert [i["summary"] for i in _stored(hass_storage, config_entry)["shopping"]] == ["Zucker"]

    gate.set()
    await task
    await _flush(hass, freezer)
    stored = _stored(hass_storage, config_entry)
    assert [i["summary"] for i in stored["shopping"]] == ["Zucker"]  # not overwritten
    assert "rewe" not in stored["store_prices_learned"]


async def test_scheduled_refresh_is_cancelled_on_unload(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer
) -> None:
    """The daily offer refresh runs as a task of the entry (cancelled on unload)."""
    await _setup(
        hass, config_entry, freezer, **{CONF_OFFERS_SOURCE: "marktguru", CONF_ZIP: "80331"}
    )
    manager = config_entry.runtime_data
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def fetch(*args, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    with patch.object(offers, "async_fetch_target_offers", fetch):
        freezer.tick(timedelta(seconds=91))  # stale offers: refresh 90 s after the start
        async_fire_time_changed(hass)
        await started.wait()
        assert manager._offers_task is not None and not manager._offers_task.done()
        assert await hass.config_entries.async_unload(config_entry.entry_id)
        await asyncio.wait_for(cancelled.wait(), 1)
    assert manager.unloaded


async def test_one_offer_refresh_at_a_time(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer
) -> None:
    """Button and service while a refresh runs: no second run, both get its result."""
    await _setup(
        hass, config_entry, freezer, **{CONF_OFFERS_SOURCE: "marktguru", CONF_ZIP: "80331"}
    )
    manager = config_entry.runtime_data
    gate = asyncio.Event()
    calls = 0

    async def fetch(*args, **kwargs):
        nonlocal calls
        calls += 1
        await gate.wait()
        return [], []

    with patch.object(offers, "async_fetch_target_offers", fetch):
        first = hass.async_create_task(offers.async_refresh_offers(hass, manager))
        second = hass.async_create_task(
            hass.services.async_call(
                DOMAIN, "refresh_offers", {}, blocking=True, return_response=True
            )
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        gate.set()
        meta = await first
        response = await second
    assert calls == 1
    assert meta["status"] == "ok"
    assert response["last_update"] == meta["last_update"] == dt_util.utcnow().isoformat()
    # afterwards a new refresh runs again
    with patch.object(offers, "async_fetch_target_offers", fetch):
        await offers.async_refresh_offers(hass, manager)
    assert calls == 2
