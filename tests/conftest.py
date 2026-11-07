"""Fixtures for Essensplaner tests."""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.essensplaner.const import (
    CONF_DEFAULT_MEAL,
    CONF_DEFAULT_SERVINGS,
    CONF_ENABLED_MEALS,
    CONF_IMPORT_STARTER,
    CONF_PANTRY,
    CONF_REGISTER_INTENTS,
    CONF_SHOW_PANEL,
    DOMAIN,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations in all tests."""


@pytest.fixture(autouse=True)
def no_overpass_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """One Overpass attempt per query (the clock is frozen; retries have their own tests)."""
    from custom_components.essensplaner import branches

    monkeypatch.setattr(branches, "RETRY_DELAYS", ())
    monkeypatch.setattr(branches, "OVERPASS_MIRRORS", ())


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """A config entry with starter recipes."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Essensplaner",
        data={CONF_IMPORT_STARTER: True},
        options={
            CONF_DEFAULT_SERVINGS: 2,
            CONF_DEFAULT_MEAL: "abendessen",
            CONF_ENABLED_MEALS: ["fruehstueck", "mittagessen", "abendessen"],
            CONF_PANTRY: "Salz, Pfeffer, Wasser",
            CONF_REGISTER_INTENTS: True,
            CONF_SHOW_PANEL: True,
        },
    )


@pytest.fixture
async def setup_integration(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer
) -> MockConfigEntry:
    """Set up the integration on a fixed date (Wednesday 2026-11-04, 10:00)."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(datetime.fromisoformat("2026-11-04T10:00:00+01:00"))
    assert await async_setup_component(hass, "homeassistant", {})
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


@pytest.fixture
def mock_setup_entry() -> Generator[None]:
    """Skip setup in config flow tests."""
    with patch("custom_components.essensplaner.async_setup_entry", return_value=True):
        yield
