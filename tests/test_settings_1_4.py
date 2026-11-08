"""Settings in the panel (1.4): options_schema.py and the websockets get_settings /
save_settings (admins), with the same rules as the options flow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.essensplaner import options_schema as schema
from custom_components.essensplaner.const import DOMAIN

from .test_config_flow import ECONOMY, GENERAL, _defaults

DE = json.loads(
    (
        Path(__file__).parent.parent / "custom_components" / DOMAIN / "translations" / "de.json"
    ).read_text(encoding="utf-8")
)


async def _ws(client: Any, msg_id: int, msg_type: str, **data: Any) -> dict[str, Any]:
    await client.send_json({"id": msg_id, "type": f"{DOMAIN}/{msg_type}", **data})
    return await client.receive_json()


# ----------------------------------------------------------------------------------
# options_schema (pure)
# ----------------------------------------------------------------------------------


def test_texts_match_translations() -> None:
    """The German messages and labels are the ones of the options flow (translations)."""
    for code in ("no_meals", "invalid_zip"):
        assert schema.ERROR_TEXTS_DE[code] == DE["options"]["error"][code]
    for kind, labels in schema.CHOICE_LABELS_DE.items():
        assert labels == DE["selector"][kind]["options"], kind


def test_every_flow_option_has_a_field() -> None:
    """The panel knows every option of the three flow steps (and nothing else)."""
    keys = set()
    for step in ("init", "economy", "stores"):
        keys |= set(DE["options"]["step"][step]["data"])
    assert keys == set(schema.FIELD_MAP)
    sections = {f.section for f in schema.FIELDS}
    assert sections == set(schema.SECTIONS)


def test_validate_rules() -> None:
    """Ranges, choices, times, entities, meals and the marktguru postcode rule."""
    base = schema.current_values({})
    cleaned, errors = schema.validate(base)
    assert errors == {}
    # stored values the panel cannot show are read leniently (never block saving)
    old = schema.current_values(
        {"offer_stores": ["lidl", "gibtsnicht"], "store_split_mode": "x", "branch_radius_km": 99}
    )
    assert old["offer_stores"] == ["lidl"]
    assert old["store_split_mode"] == "main_exceptions"
    assert old["branch_radius_km"] == 25
    assert schema.validate(old)[1] == {}
    assert cleaned["time_abendessen"] == "18:30"
    bad = {
        **base,
        "default_servings": 0,
        "enabled_meals": [],
        "default_meal": "brunch",
        "time_snack": "25:00",
        "shopping_sync_entity": "light.kueche",
        "store_split_min_percent": 95,
        "branch_radius_km": "kaputt",
        "branch_zones": ["sensor.x"],
        "rewe_online_prices": "ja",
        "offers_source": "marktguru",
        "zip_code": "",
        "pantry_staples": "x" * 2001,
    }
    cleaned, errors = schema.validate(bad, branch_postcodes=[])
    assert errors == {
        "default_servings": "out_of_range",
        "enabled_meals": "no_meals",
        "default_meal": "invalid_choice",
        "time_snack": "invalid_time",
        "shopping_sync_entity": "invalid_entity",
        "store_split_min_percent": "out_of_range",
        "branch_radius_km": "invalid_number",
        "branch_zones": "invalid_entity",
        "rewe_online_prices": "invalid_type",
        "zip_code": "invalid_zip",
        "pantry_staples": "too_long",
    }
    messages = schema.error_messages(errors)
    assert messages["default_servings"] == "Bitte einen Wert von 1 bis 20 eingeben."
    assert messages["store_split_min_percent"] == "Bitte einen Wert von 0 bis 90 eingeben."
    assert messages["zip_code"] == DE["options"]["error"]["invalid_zip"]
    assert messages["shopping_sync_entity"] == "Bitte eine Entität der Art „todo“ wählen."
    # marktguru: a postcode of a selected branch is enough; a wrong postcode never is
    assert schema.validate({**base, "offers_source": "marktguru"}, ["57610"])[1] == {}
    assert schema.validate({**base, "offers_source": "marktguru", "zip_code": "123"}, ["57610"])[
        1
    ] == {"zip_code": "invalid_zip"}
    # numbers as text with a comma (panel inputs), times with seconds (flow)
    cleaned, errors = schema.validate(
        {**base, "store_split_min_saving": "1,5", "time_snack": "15:05:00", "weekly_budget": ""}
    )
    assert errors == {}
    assert cleaned["store_split_min_saving"] == 1.5
    assert cleaned["time_snack"] == "15:05"
    assert cleaned["weekly_budget"] == 0.0


async def test_current_values_are_the_flow_defaults(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """What the panel shows for an option is what the options flow shows (same defaults)."""
    entry = setup_integration
    values = schema.current_values({**entry.data, **entry.options})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    for key, default in _defaults(result).items():
        if key.startswith("time_"):
            default = default[:5]
        assert values[key] == default, key
    result = await hass.config_entries.options.async_configure(result["flow_id"], GENERAL)
    for key, default in _defaults(result).items():
        assert values[key] == default, key
    result = await hass.config_entries.options.async_configure(result["flow_id"], ECONOMY)
    for key, default in _defaults(result).items():
        assert values[key] == default, key


# ----------------------------------------------------------------------------------
# Websockets
# ----------------------------------------------------------------------------------


async def test_get_settings(
    hass: HomeAssistant, setup_integration: MockConfigEntry, hass_ws_client
) -> None:
    """Values, defaults, field limits, choices (entities from the states) and hints."""
    entry = setup_integration
    hass.states.async_set("zone.home", "0", {"friendly_name": "Zuhause", "latitude": 50.6})
    hass.states.async_set("zone.arbeit", "0", {"friendly_name": "Arbeit", "latitude": 50.7})
    hass.states.async_set("todo.bring", "3", {"friendly_name": "Bring!"})
    hass.states.async_set("ai_task.ollama", "unavailable", {"friendly_name": "Ollama"})
    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            "offers_source": "marktguru",
            "zip_code": "57610",
            "rewe_online_prices": True,
            "receipt_ai_task_entity": "ai_task.ollama",
            "branch_zones": "zone.arbeit",
        },
    )
    await hass.async_block_till_done()
    client = await hass_ws_client(hass)
    msg = await _ws(client, 1, "get_settings")
    assert msg["success"], msg
    res = msg["result"]
    values = res["values"]
    assert values["offers_source"] == "marktguru"
    assert values["zip_code"] == "57610"
    assert values["branch_zones"] == ["zone.arbeit"]
    assert values["time_abendessen"] == "18:30"
    assert values["receipt_ai_task_entity"] == "ai_task.ollama"
    assert res["defaults"]["offers_source"] == "off"  # new installs: marktguru off
    assert res["defaults"]["edeka_offers"] is False
    assert res["fields"]["store_split_min_percent"] == {
        "section": "stores",
        "type": "int",
        "min": 0,
        "max": 90,
        "step": 1,
    }
    assert res["fields"]["receipt_ai_task_entity"]["optional"] is True
    assert res["sections"] == ["general", "planning", "offers", "stores", "receipts"]
    choices = res["choices"]
    assert [c["value"] for c in choices["meals"]] == [
        "fruehstueck",
        "mittagessen",
        "snack",
        "abendessen",
    ]
    assert choices["strategies"][0] == {"value": "balanced", "label": "Ausgewogen"}
    assert {"value": "rossmann", "label": "Rossmann", "kind": "drugstore"} in choices["stores"]
    assert [c["value"] for c in choices["zones"]] == ["zone.arbeit", "zone.home"]
    # the own shopping list is no target for the copy
    todo = [c["value"] for c in choices["todo_entities"]]
    assert "todo.bring" in todo and not any("essensplaner" in t for t in todo)
    assert choices["ai_task_entities"] == [
        {"value": "ai_task.ollama", "label": "Ollama", "available": False}
    ]
    keys = [w["key"] for w in res["warnings"]]
    assert keys == [
        "offers_source",
        "receipt_ai_task_entity",
        "rewe_online_prices",
        "store_split_mode",
    ]
    assert res["warnings"][0]["message"] == schema.MARKTGURU_WARNING_DE
    assert "untersagt laut AGB" in res["warnings"][0]["message"]
    assert res["loaded"] is True and res["branches"] == 0


async def test_settings_need_an_admin(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    hass_ws_client,
    hass_read_only_access_token,
) -> None:
    """Only admins read or change the settings."""
    client = await hass_ws_client(hass, hass_read_only_access_token)
    msg = await _ws(client, 1, "get_settings")
    assert not msg["success"] and msg["error"]["code"] == "unauthorized"
    msg = await _ws(client, 2, "save_settings", values={"default_servings": 4})
    assert not msg["success"] and msg["error"]["code"] == "unauthorized"
    assert setup_integration.options["default_servings"] == 2


async def test_save_settings_errors_store_nothing(
    hass: HomeAssistant, setup_integration: MockConfigEntry, hass_ws_client
) -> None:
    """Invalid values come back per field (German, like the options flow) and nothing is
    stored or reloaded."""
    entry = setup_integration
    manager = entry.runtime_data
    before = dict(entry.options)
    client = await hass_ws_client(hass)
    msg = await _ws(
        client,
        1,
        "save_settings",
        values={
            "offers_source": "marktguru",
            "zip_code": "",
            "enabled_meals": [],
            "store_split_trip_min": 99,
            "default_servings": 4,
        },
    )
    assert msg["success"], msg
    assert msg["result"] == {
        "saved": False,
        "errors": {
            "enabled_meals": "Bitte mindestens eine Mahlzeit auswählen.",
            "store_split_trip_min": "Bitte einen Wert von 0 bis 50 eingeben.",
            "zip_code": DE["options"]["error"]["invalid_zip"],
        },
    }
    await hass.async_block_till_done()
    assert dict(entry.options) == before
    assert entry.runtime_data is manager  # no reload


async def test_save_settings_stores_and_reloads(
    hass: HomeAssistant, setup_integration: MockConfigEntry, hass_ws_client
) -> None:
    """Valid settings are stored like the options flow stores them; other option keys stay,
    an emptied entity picker is removed, the entry reloads; saving again changes nothing."""
    entry = setup_integration
    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            "custom_key": "bleibt",
            "shopping_sync_entity": "todo.bring",
            "receipt_ai_task_entity": "ai_task.ollama",
        },
    )
    await hass.async_block_till_done()
    manager = entry.runtime_data
    client = await hass_ws_client(hass)
    msg = await _ws(
        client,
        1,
        "save_settings",
        values={
            "default_servings": "4",
            "time_abendessen": "19:15",
            "weekly_budget": "65,5",
            "plan_strategy": "cheap",
            "offer_stores": ["lidl", "rossmann"],
            "store_split_min_saving": 2.0,
            "branch_zones": ["zone.home"],
            "edeka_offers": True,
            "shopping_sync_entity": None,
            "receipt_ai_task_entity": "",
            "unknown_option": 1,
        },
    )
    assert msg["success"], msg
    assert msg["result"] == {"saved": True, "reload": True}
    await hass.async_block_till_done()
    options = entry.options
    assert options["custom_key"] == "bleibt"
    assert options["default_servings"] == 4
    assert options["time_abendessen"] == "19:15"
    assert options["time_fruehstueck"] == "07:30"
    assert options["weekly_budget"] == 65.5
    assert options["plan_strategy"] == "cheap"
    assert options["offer_stores"] == ["lidl", "rossmann"]
    assert options["store_split_min_saving"] == 2
    assert options["branch_zones"] == ["zone.home"]
    assert options["edeka_offers"] is True
    assert options["offers_source"] == "off"
    assert "shopping_sync_entity" not in options
    assert "receipt_ai_task_entity" not in options
    assert "unknown_option" not in options
    # the update listener reloaded the integration with the new options
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not manager
    assert entry.runtime_data.default_servings == 4
    assert entry.runtime_data.weekly_budget == 65.5
    # the same values again: nothing changes, no reload
    reloaded = entry.runtime_data
    msg = await _ws(client, 2, "save_settings", values={"default_servings": 4})
    assert msg["result"] == {"saved": True, "reload": False}
    await hass.async_block_till_done()
    assert entry.runtime_data is reloaded
    # the panel reads the new values back
    msg = await _ws(client, 3, "get_settings")
    assert msg["result"]["values"]["default_servings"] == 4
    assert msg["result"]["values"]["shopping_sync_entity"] is None


async def test_save_settings_marktguru_with_branch_postcodes(
    hass: HomeAssistant, setup_integration: MockConfigEntry, hass_ws_client
) -> None:
    """marktguru without a postcode in the settings works with branches that have one."""
    entry = setup_integration
    entry.runtime_data.save_branch({"store": "Lidl", "postcode": "56593"})
    client = await hass_ws_client(hass)
    msg = await _ws(client, 1, "save_settings", values={"offers_source": "marktguru"})
    assert msg["result"] == {"saved": True, "reload": True}
    await hass.async_block_till_done()
    assert entry.options["offers_source"] == "marktguru"
    assert entry.options["zip_code"] == ""
    # the branch survived the reload
    assert entry.runtime_data.branch_postcodes() == ["56593"]
    msg = await _ws(client, 2, "get_settings")
    assert msg["result"]["branch_postcodes"] == ["56593"]
    assert msg["result"]["main_branch"] == "Lidl"


def test_offer_filter_nonfood() -> None:
    """ "Drogerie & Haushalt" in the Angebote tab: drugstore and household offers."""
    from custom_components.essensplaner.catalog import kind_matches

    def offer(kind: str, retailer: str = "lidl") -> dict[str, Any]:
        return {"kind": kind, "retailer": retailer}

    assert kind_matches(offer("drugstore"), "nonfood")
    assert kind_matches(offer("household"), "nonfood")
    assert kind_matches(offer("unknown", "rossmann"), "nonfood")
    assert not kind_matches(offer("unknown"), "nonfood")
    assert not kind_matches(offer("food"), "nonfood")
    assert not kind_matches(offer("nonfood"), "nonfood")  # clothes, garden … only under "Alles"
