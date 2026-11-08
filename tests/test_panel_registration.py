"""The sidebar panel across reloads (1.4 review): saving the settings in the panel reloads
the entry, and the panel must stay registered meanwhile – the frontend asks for the panel
list on every change and leaves a page whose panel is missing for the default dashboard."""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
from typing import Any
from unittest.mock import patch

from homeassistant.components.frontend import DATA_PANELS, EVENT_PANELS_UPDATED
from homeassistant.config_entries import ConfigEntryDisabler
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.essensplaner.const import CONF_SHOW_PANEL, DOMAIN, PANEL_URL_PATH


async def _ws(client: Any, msg_id: int, msg_type: str, **data: Any) -> dict[str, Any]:
    await client.send_json({"id": msg_id, "type": f"{DOMAIN}/{msg_type}", **data})
    return await client.receive_json()


@pytest.fixture
def frontend_panels(hass: HomeAssistant) -> Generator[list[bool]]:
    """The panel registry of the frontend (without setting up the whole frontend) and the
    changes of the Essensplaner panel the frontend saw (True: in the list of a panels_updated
    event, False: missing; other integrations, e.g. todo and calendar, add panels too)."""
    hass.data[DATA_PANELS] = {}
    seen: list[bool] = []

    @callback
    def _updated(_event: Event) -> None:
        present = PANEL_URL_PATH in hass.data[DATA_PANELS]
        if present != (seen[-1] if seen else False):
            seen.append(present)

    hass.bus.async_listen(EVENT_PANELS_UPDATED, _updated)
    with (
        patch("custom_components.essensplaner.panel._async_register_static", return_value=True),
        patch("custom_components.essensplaner.async_register_card"),
    ):
        yield seen


@pytest.fixture
async def panel_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry, frontend_panels: list[bool], freezer
) -> MockConfigEntry:
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(datetime.fromisoformat("2026-11-04T10:00:00+01:00"))
    assert await async_setup_component(hass, "homeassistant", {})
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert PANEL_URL_PATH in hass.data[DATA_PANELS]
    assert frontend_panels == [True]
    return config_entry


async def test_saving_settings_keeps_the_panel(
    hass: HomeAssistant, panel_entry: MockConfigEntry, frontend_panels: list[bool], hass_ws_client
) -> None:
    """A reload after saving settings neither removes nor re-registers the panel: the
    frontend gets no panels_updated event, so the open panel stays open."""
    entry = panel_entry
    manager = entry.runtime_data
    panel = hass.data[DATA_PANELS][PANEL_URL_PATH]
    client = await hass_ws_client(hass)
    msg = await _ws(client, 1, "save_settings", values={"default_servings": 4})
    assert msg["result"] == {"saved": True, "reload": True}
    await hass.async_block_till_done()
    assert entry.runtime_data is not manager  # reloaded
    assert hass.data[DATA_PANELS][PANEL_URL_PATH] is panel
    assert frontend_panels == [True]

    # also a reload from Home Assistant's integration page
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.data[DATA_PANELS][PANEL_URL_PATH] is panel
    assert frontend_panels == [True]


async def test_panel_switched_off_in_the_panel_is_removed(
    hass: HomeAssistant, panel_entry: MockConfigEntry, frontend_panels: list[bool], hass_ws_client
) -> None:
    """show_panel off: removed once the reload is over (once); on again (Home Assistant's
    options dialog): registered again."""
    entry = panel_entry
    client = await hass_ws_client(hass)
    msg = await _ws(client, 1, "save_settings", values={CONF_SHOW_PANEL: False})
    assert msg["result"] == {"saved": True, "reload": True}
    await hass.async_block_till_done()
    assert PANEL_URL_PATH not in hass.data[DATA_PANELS]
    assert frontend_panels == [True, False]

    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(result["flow_id"], {CONF_SHOW_PANEL: True})
    await hass.async_block_till_done()
    assert PANEL_URL_PATH in hass.data[DATA_PANELS]
    assert frontend_panels == [True, False, True]


async def test_panel_removed_with_the_entry(
    hass: HomeAssistant, panel_entry: MockConfigEntry, frontend_panels: list[bool]
) -> None:
    """Unloading, disabling or deleting the entry removes the panel; setting it up again
    brings it back."""
    entry = panel_entry
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert PANEL_URL_PATH not in hass.data[DATA_PANELS]
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert PANEL_URL_PATH in hass.data[DATA_PANELS]

    await hass.config_entries.async_set_disabled_by(entry.entry_id, ConfigEntryDisabler.USER)
    await hass.async_block_till_done()
    assert PANEL_URL_PATH not in hass.data[DATA_PANELS]
    await hass.config_entries.async_set_disabled_by(entry.entry_id, None)
    await hass.async_block_till_done()
    assert PANEL_URL_PATH in hass.data[DATA_PANELS]

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert PANEL_URL_PATH not in hass.data[DATA_PANELS]
    assert frontend_panels == [True, False, True, False, True, False]


async def test_new_panel_module_is_registered_again(
    hass: HomeAssistant, panel_entry: MockConfigEntry, frontend_panels: list[bool]
) -> None:
    """New files without a restart (another version): the reload registers the new module."""
    with patch("custom_components.essensplaner.panel._version", return_value="9.9.9"):
        await hass.config_entries.async_reload(panel_entry.entry_id)
        await hass.async_block_till_done()
    panel = hass.data[DATA_PANELS][PANEL_URL_PATH]
    assert panel.config["_panel_custom"]["module_url"].endswith("essensplaner-panel.js?v=9.9.9")
