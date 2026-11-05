"""Websocket API details used by the panel (1.3)."""

from __future__ import annotations

from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.essensplaner.branches import search_defaults
from custom_components.essensplaner.const import (
    CONF_BRANCH_RADIUS,
    CONF_BRANCH_ROUTE,
    CONF_BRANCH_ROUTE_RADIUS,
    DOMAIN,
)


def test_search_defaults() -> None:
    """Preset of the search form: option values, clamped, with the 1.3 defaults."""
    assert search_defaults({}) == {"radius_km": 3.0, "route": True, "route_radius_m": 800}
    assert search_defaults(
        {CONF_BRANCH_RADIUS: 99, CONF_BRANCH_ROUTE: False, CONF_BRANCH_ROUTE_RADIUS: 10}
    ) == {"radius_km": 25.0, "route": False, "route_radius_m": 100}
    assert search_defaults({CONF_BRANCH_RADIUS: "kaputt"})["radius_km"] == 3.0


@pytest.fixture
async def branch_options_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer
) -> MockConfigEntry:
    """Integration with branch search options (clock moved before the ws token)."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(datetime.fromisoformat("2026-11-04T10:00:00+01:00"))
    assert await async_setup_component(hass, "homeassistant", {})
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry,
        options={**config_entry.options, CONF_BRANCH_RADIUS: 5, CONF_BRANCH_ROUTE: False},
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


async def test_ws_find_branches_defaults(
    hass: HomeAssistant, branch_options_entry: MockConfigEntry, hass_ws_client
) -> None:
    """The cached-only answer (no request) carries the option defaults for the form."""
    hass.states.async_set(
        "zone.home", "0", {"latitude": 48.1, "longitude": 11.5, "friendly_name": "Zuhause"}
    )

    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/find_branches", "cached_only": True})
    msg = await client.receive_json()
    assert msg["success"]
    result = msg["result"]
    assert result["defaults"] == {"radius_km": 5.0, "route": False, "route_radius_m": 800}
    assert result["cached"] is False
    assert result["results"] == []
    assert result["zones"] == [{"zone": "zone.home", "name": "Zuhause", "default": True}]
