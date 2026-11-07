"""Config flow tests (setup and the options steps init -> economy -> stores)."""

from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
import pytest

from custom_components.essensplaner.const import (
    DEFAULT_ALDI_ONLINE,
    DEFAULT_BRANCH_RADIUS,
    DEFAULT_BRANCH_ROUTE,
    DEFAULT_BRANCH_ROUTE_RADIUS,
    DEFAULT_EDEKA_OFFERS,
    DEFAULT_REWE_ONLINE,
    DEFAULT_SPLIT_MIN_PERCENT,
    DEFAULT_SPLIT_MIN_SAVING,
    DEFAULT_SPLIT_MODE,
    DEFAULT_SPLIT_OFFER_MIN,
    DEFAULT_SPLIT_TRIP_MIN,
    DOMAIN,
)

GENERAL = {
    "default_servings": 2,
    "enabled_meals": ["mittagessen", "abendessen"],
    "default_meal": "abendessen",
    "time_fruehstueck": "07:30:00",
    "time_mittagessen": "12:30:00",
    "time_snack": "15:30:00",
    "time_abendessen": "18:30:00",
    "register_intents": True,
    "show_panel": True,
}
ECONOMY = {
    "weekly_budget": 0,
    "plan_strategy": "balanced",
    "offers_source": "off",
    "zip_code": "",
    "offer_stores": ["lidl"],
}
STORES = {
    "store_split_mode": "main_exceptions",
    "store_split_min_saving": 1.5,
    "store_split_min_percent": 25,
    "store_split_offer_min": 0.5,
    "store_split_trip_min": 3,
    "branch_zones": ["zone.home", "zone.arbeit"],
    "branch_radius_km": 2.5,
    "branch_route": False,
    "branch_route_radius_m": 600,
    "rewe_online_prices": True,
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


async def _stores_form(
    hass: HomeAssistant, entry, general: dict | None = None, economy: dict | None = None
) -> dict[str, Any]:
    """Run init and economy, return the stores form."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], general or GENERAL
    )
    assert result["step_id"] == "economy"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], economy or ECONOMY
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "stores"
    assert not result.get("errors")
    return result


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
    """Options can be changed in all three steps."""
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
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "economy"
    # marktguru needs a valid zip code
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "weekly_budget": 70,
            "plan_strategy": "cheap",
            "offers_source": "marktguru",
            "zip_code": "12",
            "offer_stores": ["lidl", "aldi-sued"],
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"zip_code": "invalid_zip"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "weekly_budget": 70,
            "plan_strategy": "cheap",
            "offers_source": "off",
            "zip_code": "",
            "offer_stores": ["lidl", "aldi-sued"],
            "offers_watchlist": "Butter, Kaffee",
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "stores"
    assert result["description_placeholders"] == {"branches": "0", "main_branch": "–"}
    assert entry.options.get("weekly_budget") is None  # nothing saved before the last step
    result = await hass.config_entries.options.async_configure(result["flow_id"], STORES)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["time_abendessen"] == "19:00"
    assert entry.options["default_servings"] == 4
    assert entry.options["store_split_min_saving"] == 1.5
    assert entry.options["store_split_trip_min"] == 3
    assert entry.options["branch_zones"] == ["zone.home", "zone.arbeit"]
    assert entry.options["branch_route_radius_m"] == 600
    await hass.async_block_till_done()
    manager = entry.runtime_data
    assert manager.default_meal == "mittagessen"
    assert manager.pantry == ["Salz", "Pfeffer", "Öl"]
    assert manager.weekly_budget == 70
    assert manager.strategy == "cheap"
    assert manager.offer_stores == ["lidl", "aldi-sued"]
    assert manager.watchlist == ["Butter", "Kaffee"]
    settings = manager.split_settings()
    assert (settings["mode"], settings["min_saving"], settings["min_percent"]) == (
        "main_exceptions",
        1.5,
        25,
    )
    assert (settings["offer_min"], settings["trip_min"]) == (0.5, 3)


async def test_options_stores_defaults(hass: HomeAssistant, setup_integration) -> None:
    """The stores step offers the const.py defaults and saves them unchanged."""
    entry = setup_integration
    result = await _stores_form(hass, entry)
    assert _defaults(result) == {
        "store_split_mode": DEFAULT_SPLIT_MODE,
        "store_split_min_saving": DEFAULT_SPLIT_MIN_SAVING,
        "store_split_min_percent": DEFAULT_SPLIT_MIN_PERCENT,
        "store_split_offer_min": DEFAULT_SPLIT_OFFER_MIN,
        "store_split_trip_min": DEFAULT_SPLIT_TRIP_MIN,
        "branch_zones": [],
        "branch_radius_km": DEFAULT_BRANCH_RADIUS,
        "branch_route": DEFAULT_BRANCH_ROUTE,
        "branch_route_radius_m": DEFAULT_BRANCH_ROUTE_RADIUS,
        "rewe_online_prices": DEFAULT_REWE_ONLINE,
        # 1.4: the chain sources ALDI SÜD (prices) and EDEKA (offers), off by default
        "aldi_online_prices": DEFAULT_ALDI_ONLINE,
        "edeka_offers": DEFAULT_EDEKA_OFFERS,
    }
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    options = entry.options
    assert options["store_split_mode"] == "main_exceptions"
    assert options["store_split_min_saving"] == 1
    assert options["store_split_min_percent"] == 20
    assert options["store_split_offer_min"] == 0.3
    assert options["store_split_trip_min"] == 0
    assert options["branch_zones"] == []  # automatic: home + work zones
    assert options["branch_radius_km"] == 3
    assert options["branch_route"] is True
    assert options["branch_route_radius_m"] == 800
    assert options["rewe_online_prices"] is False
    assert options["aldi_online_prices"] is False
    assert options["edeka_offers"] is False
    await hass.async_block_till_done()
    manager = entry.runtime_data
    assert manager.split_settings() == {
        "mode": "main_exceptions",
        "active": False,  # no main branch yet
        "min_saving": 1.0,
        "min_percent": 20.0,
        "offer_min": 0.3,
        "trip_min": 0.0,
        "floor": 0.2,
    }


async def test_options_stores_validation(hass: HomeAssistant, setup_integration) -> None:
    """Values outside the ranges, unknown modes and non-zone entities are refused."""
    entry = setup_integration
    result = await _stores_form(hass, entry)
    flow_id = result["flow_id"]
    for bad in (
        {"store_split_mode": "sometimes"},
        {"store_split_min_saving": -1},
        {"store_split_min_saving": 25},
        {"store_split_min_percent": 95},
        {"store_split_offer_min": -0.1},
        {"store_split_trip_min": 60},
        {"branch_radius_km": 0.2},
        {"branch_radius_km": 30},
        {"branch_route_radius_m": 50},
        {"branch_route_radius_m": 6000},
        {"branch_zones": ["sensor.essensplaner_today"]},
    ):
        with pytest.raises(InvalidData):
            await hass.config_entries.options.async_configure(flow_id, {**STORES, **bad})
    # the flow is still open and accepts valid values
    result = await hass.config_entries.options.async_configure(
        flow_id, {**STORES, "store_split_mode": "off", "store_split_min_percent": 0}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["store_split_mode"] == "off"
    assert entry.options["store_split_min_percent"] == 0


async def test_options_existing_values_kept(hass: HomeAssistant, setup_integration) -> None:
    """Saved values are shown again; other options survive; cleared selectors are removed."""
    entry = setup_integration
    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            **STORES,
            "store_split_mode": "main_only",
            "branch_zones": "zone.arbeit, zone.arbeit_2",  # 1.3 also accepts text
            "shopping_sync_entity": "todo.einkauf",
            "weekly_budget": 55.0,
            "custom_key": "bleibt",
        },
    )
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    init_defaults = _defaults(result)
    assert init_defaults["shopping_sync_entity"] == "todo.einkauf"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**GENERAL, "shopping_sync_entity": "todo.einkauf"}
    )
    assert _defaults(result)["weekly_budget"] == 55.0
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**ECONOMY, "weekly_budget": 55}
    )
    defaults = _defaults(result)
    assert defaults["store_split_mode"] == "main_only"
    assert defaults["store_split_min_saving"] == 1.5
    assert defaults["branch_zones"] == ["zone.arbeit", "zone.arbeit_2"]
    assert defaults["branch_radius_km"] == 2.5
    assert defaults["branch_route"] is False
    assert defaults["rewe_online_prices"] is True
    # the zones were cleared in the form: the key is missing -> automatic
    stores = {k: v for k, v in defaults.items() if k != "branch_zones"}
    result = await hass.config_entries.options.async_configure(result["flow_id"], stores)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    options = entry.options
    assert options["custom_key"] == "bleibt"
    assert options["shopping_sync_entity"] == "todo.einkauf"
    assert options["weekly_budget"] == 55
    assert options["store_split_mode"] == "main_only"
    assert options["store_split_offer_min"] == 0.5
    assert options["branch_zones"] == []
    assert options["rewe_online_prices"] is True
    assert options["time_abendessen"] == "18:30"
    await hass.async_block_till_done()

    # clearing the optional todo list in step 1 removes it
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], GENERAL)
    result = await hass.config_entries.options.async_configure(result["flow_id"], ECONOMY)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert "shopping_sync_entity" not in entry.options
    assert entry.options["custom_key"] == "bleibt"
    assert entry.options["store_split_mode"] == "main_only"


async def test_options_with_branches(hass: HomeAssistant, setup_integration) -> None:
    """marktguru works with branches that have a postcode; the step shows the main store."""
    entry = setup_integration
    manager = entry.runtime_data
    manager.save_branch({"store": "Aldi Süd", "street": "Hauptstraße 5", "postcode": "80331"})
    manager.save_branch({"store": "REWE", "postcode": "80333", "rewe_market_id": "1940156"})
    economy = {**ECONOMY, "offers_source": "marktguru", "zip_code": ""}
    result = await _stores_form(hass, entry, economy=economy)
    assert result["description_placeholders"] == {
        "branches": "2",
        "main_branch": "Aldi Süd Hauptstraße 5",
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**STORES, "branch_zones": []}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    manager = entry.runtime_data
    assert manager.offers_source == "marktguru"
    assert manager.zip_code == ""
    assert [zip_code for zip_code, _ in manager.offer_targets()] == ["80331", "80333"]
    # the branches survive the reload; the split is active with the main branch
    assert manager.get_main_branch()["retailer"] == "aldi-sued"
    assert manager.store_split_active
    from custom_components.essensplaner.rewe import rewe_status

    status = rewe_status(manager)
    assert (status["enabled"], status["status"], status["market_id"]) == (
        True,
        "pending",
        "1940156",
    )


async def test_options_invalid_zip_stays_on_economy(hass: HomeAssistant, setup_integration) -> None:
    """A wrong zip code keeps the economy step open (the stores step is not shown)."""
    entry = setup_integration
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], GENERAL)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**ECONOMY, "offers_source": "marktguru", "zip_code": "8033"}
    )
    assert result["step_id"] == "economy"
    assert result["errors"] == {"zip_code": "invalid_zip"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**ECONOMY, "offers_source": "marktguru", "zip_code": " 80331 "}
    )
    assert result["step_id"] == "stores"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["zip_code"] == "80331"
    assert entry.options["offers_source"] == "marktguru"
