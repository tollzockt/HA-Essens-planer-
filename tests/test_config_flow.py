"""Config flow tests: the setup step and the one options step (1.4: only the sidebar panel;
all other settings live in the panel's ⚙️ view, see test_settings_1_4.py)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
import pytest

from custom_components.essensplaner.const import DOMAIN

# options of an installation that went through the 1.3 options flow and the 1.4 settings
# (plus a key the integration does not know and the 1.3 text form of the zones)
FULL_OPTIONS: dict[str, Any] = {
    "default_servings": 3,
    "default_meal": "mittagessen",
    "enabled_meals": ["mittagessen", "abendessen"],
    "time_fruehstueck": "07:00",
    "time_mittagessen": "12:00",
    "time_snack": "15:00",
    "time_abendessen": "19:00",
    "pantry_staples": "Salz, Pfeffer, Öl",
    "excluded": "Fisch",
    "auto_mark_cooked": False,
    "shopping_sync_entity": "todo.bring",
    "register_intents": True,
    "show_panel": True,
    "weekly_budget": 70.0,
    "plan_strategy": "cheap",
    "offers_source": "marktguru",
    "zip_code": "57601",
    "offer_stores": ["lidl", "rewe", "rossmann"],
    "offers_watchlist": "Kaffee, Butter",
    "rewe_online_prices": True,
    "aldi_online_prices": True,
    "edeka_offers": True,
    "store_split_mode": "main_only",
    "store_split_min_saving": 1.5,
    "store_split_min_percent": 25,
    "store_split_offer_min": 0.5,
    "store_split_trip_min": 3,
    "branch_zones": "zone.arbeit, zone.arbeit_2",
    "branch_radius_km": 2.5,
    "branch_route": False,
    "branch_route_radius_m": 600,
    "receipt_ai_task_entity": "ai_task.ollama_ai_task",
    "custom_key": "bleibt",
}


def _defaults(result: dict[str, Any]) -> dict[str, Any]:
    """Defaults (or suggested values) of a form."""
    values = {}
    for marker in result["data_schema"].schema:
        default = getattr(marker, "default", None)
        if callable(default):
            values[str(marker)] = default()
        elif marker.description and "suggested_value" in marker.description:
            values[str(marker)] = marker.description["suggested_value"]
    return values


async def _set_options(hass: HomeAssistant, entry, options: dict[str, Any]) -> None:
    hass.config_entries.async_update_entry(entry, options=options)
    await hass.async_block_till_done()


async def test_user_flow(hass: HomeAssistant, mock_setup_entry) -> None:
    """The user step creates an entry (unchanged in 1.4)."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert sorted(_defaults(result)) == ["default_servings", "import_starter_recipes"]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"import_starter_recipes": False, "default_servings": 3}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"import_starter_recipes": False}
    assert result["options"]["default_servings"] == 3
    assert result["options"]["time_abendessen"] == "18:30"
    assert result["options"]["show_panel"] is True
    # the online sources are off for a new installation (nothing stored = default off)
    for key in ("offers_source", "rewe_online_prices", "aldi_online_prices", "edeka_offers"):
        assert key not in result["options"], key


async def test_user_flow_single_instance(hass: HomeAssistant, setup_integration) -> None:
    """A second setup is refused."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_options_flow_only_the_panel(hass: HomeAssistant, setup_integration) -> None:
    """The options dialog has one step with one field: the sidebar panel."""
    entry = setup_integration
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert _defaults(result) == {"show_panel": True}
    assert not result.get("errors")
    assert not result.get("description_placeholders")
    # nothing else can be sent through this dialog any more
    for extra in ({"weekly_budget": 50}, {"offers_source": "marktguru"}, {"zip_code": "1"}):
        with pytest.raises(InvalidData):
            await hass.config_entries.options.async_configure(
                result["flow_id"], {"show_panel": True, **extra}
            )
    # the flow is still open; an empty form keeps the shown value
    before = dict(entry.options)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert dict(entry.options) == before


async def test_options_flow_keeps_every_other_option(
    hass: HomeAssistant, setup_integration
) -> None:
    """Saving the step changes show_panel and nothing else – also not the values that only
    the panel's settings can change (marktguru, chain sources, AI Task) or unknown keys."""
    entry = setup_integration
    await _set_options(hass, entry, dict(FULL_OPTIONS))
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert _defaults(result) == {"show_panel": True}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"show_panel": False}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert dict(entry.options) == {**FULL_OPTIONS, "show_panel": False}
    # the next dialog shows the stored value; switching back restores the exact options
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert _defaults(result) == {"show_panel": False}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"show_panel": True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert dict(entry.options) == FULL_OPTIONS
    manager = entry.runtime_data
    assert manager.offers_source == "marktguru"
    assert manager.weekly_budget == 70
    assert manager.offer_stores == ["lidl", "rewe", "rossmann"]


async def test_options_flow_old_entry_without_panel_key(
    hass: HomeAssistant, setup_integration
) -> None:
    """An entry without show_panel (very old setup) shows the panel switch on; saving it
    unchanged only adds the key."""
    entry = setup_integration
    options = {k: v for k, v in entry.options.items() if k != "show_panel"}
    await _set_options(hass, entry, options)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert _defaults(result) == {"show_panel": True}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"show_panel": True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert dict(entry.options) == {**options, "show_panel": True}


async def test_options_flow_toggles_the_sidebar_panel(
    hass: HomeAssistant, setup_integration
) -> None:
    """Off removes the panel (reload without registering it), on brings it back; saving
    the same value again does not reload."""
    entry = setup_integration
    register = AsyncMock(return_value=True)
    remove = MagicMock()
    with (
        patch("custom_components.essensplaner.async_register_panel", register),
        patch("custom_components.essensplaner.async_remove_panel", remove),
    ):
        # a reload with the panel on registers it (and its removal on unload)
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert register.await_count == 1
        before = dict(entry.options)

        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"show_panel": False}
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        assert remove.call_count == 1  # unloaded with the old options
        assert register.await_count == 1  # not registered again
        assert entry.options["show_panel"] is False
        assert {k: v for k, v in entry.options.items() if k != "show_panel"} == {
            k: v for k, v in before.items() if k != "show_panel"
        }

        manager = entry.runtime_data
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"show_panel": False}
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        assert entry.runtime_data is manager  # nothing changed: no reload

        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"show_panel": True}
        )
        await hass.async_block_till_done()
        assert register.await_count == 2
        assert remove.call_count == 1
        assert dict(entry.options) == before
