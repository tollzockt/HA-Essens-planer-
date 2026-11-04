"""Config flow tests."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.essensplaner.const import DOMAIN


async def test_user_flow(hass: HomeAssistant, mock_setup_entry) -> None:
    """The user step creates an entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"import_starter_recipes": False, "default_servings": 3}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"import_starter_recipes": False}
    assert result["options"]["default_servings"] == 3
    assert result["options"]["time_abendessen"] == "18:30"


async def test_options_flow(hass: HomeAssistant, setup_integration) -> None:
    """Options can be changed."""
    entry = setup_integration
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "default_servings": 4,
            "enabled_meals": ["mittagessen", "abendessen"],
            "default_meal": "mittagessen",
            "time_fruehstueck": "07:00:00",
            "time_mittagessen": "12:00:00",
            "time_snack": "15:00:00",
            "time_abendessen": "19:00:00",
            "pantry_staples": "Salz, Pfeffer, Öl",
            "register_intents": True,
            "show_panel": False,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["time_abendessen"] == "19:00"
    assert entry.options["default_servings"] == 4
    await hass.async_block_till_done()
    manager = entry.runtime_data
    assert manager.default_meal == "mittagessen"
    assert manager.pantry == ["Salz", "Pfeffer", "Öl"]
