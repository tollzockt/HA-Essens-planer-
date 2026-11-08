"""Settings in the panel (1.4): options_schema.py and the websockets get_settings /
save_settings (admins), with the rules of the 1.3 options flow. Home Assistant's options
dialog only toggles the sidebar panel since 1.4 (test_config_flow.py)."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.essensplaner import const, options_schema as schema
from custom_components.essensplaner.const import DOMAIN

from .test_config_flow import _defaults

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
    """Choice labels used by services.yaml too (meals, strategies) are the translated
    ones; every choice and every validation code has a German text."""
    for kind in ("meal", "strategy"):
        assert schema.CHOICE_LABELS_DE[kind] == DE["selector"][kind]["options"], kind
    assert sorted(schema.CHOICE_LABELS_DE["split_mode"]) == sorted(const.SPLIT_MODES)
    assert sorted(schema.CHOICE_LABELS_DE["offers_source"]) == sorted(schema.OFFERS_SOURCES)
    assert "eigenes Risiko" in schema.CHOICE_LABELS_DE["offers_source"]["marktguru"]
    source = Path(schema.__file__).read_text(encoding="utf-8")
    codes = set(re.findall(r'return (?:\(?None, |None if \w+ else )?"(\w+)"', source))
    assert {"no_meals", "invalid_zip", "out_of_range", "invalid_entity"} <= codes
    assert codes <= set(schema.ERROR_TEXTS_DE)


def test_every_option_has_a_field() -> None:
    """The panel knows every option the integration reads (all CONF_* keys of const.py
    except the setup's starter-recipe import) – nothing is left to the options flow."""
    keys = {
        getattr(const, name)
        for name in dir(const)
        if name.startswith("CONF_") and name not in ("CONF_IMPORT_STARTER", "CONF_MEAL_TIME_PREFIX")
    }
    keys |= {f"{const.CONF_MEAL_TIME_PREFIX}{meal}" for meal in const.ALL_MEALS}
    assert keys == set(schema.FIELD_MAP)
    sections = {f.section for f in schema.FIELDS}
    assert sections == set(schema.SECTIONS)
    # the 1.4 sources are off for new installations
    defaults = schema.default_values()
    assert defaults["offers_source"] == "off"
    for key in ("rewe_online_prices", "aldi_online_prices", "edeka_offers"):
        assert defaults[key] is False, key
    assert defaults["receipt_ai_task_entity"] is None
    # 1.5: no AI until one is chosen; all features except the product matching; the new
    # planning / leaflet switches are on
    assert defaults["ai_entity"] is None
    assert defaults["ai_features"] == ["occasions", "drinks", "season", "receipts"]
    for key in ("season_aware", "occasions_in_budget", "drinks_alcohol", "all_leaflets"):
        assert defaults[key] is True, key
    assert schema.FIELD_MAP["ai_entity"].section == "ai"
    assert schema.FIELD_MAP["ai_features"].section == "ai"
    assert schema.FIELD_MAP["all_leaflets"].section == "offers"
    for key in ("season_aware", "occasions_in_budget", "drinks_alcohol"):
        assert schema.FIELD_MAP[key].section == "planning", key


def test_entity_fields_with_several_domains() -> None:
    """1.5: an entity field takes one domain (1.4) or several (the AI picker: AI Tasks and
    conversation agents); the panel gets domain (the first) and domains."""
    ai_field = schema.FIELD_MAP["ai_entity"]
    assert ai_field.entity_domains == ("ai_task", "conversation")
    assert ai_field.describe() == {
        "section": "ai",
        "type": "entity",
        "domain": "ai_task",
        "domains": ["ai_task", "conversation"],
        "optional": True,
    }
    todo = schema.FIELD_MAP["shopping_sync_entity"]
    assert todo.entity_domains == ("todo",)
    assert todo.describe()["domain"] == "todo" and todo.describe()["domains"] == ["todo"]
    assert schema.clean_value(ai_field, "ai_task.ollama") == ("ai_task.ollama", None)
    assert schema.clean_value(ai_field, "conversation.jarvis") == ("conversation.jarvis", None)
    assert schema.clean_value(ai_field, "") == (None, None)
    assert schema.clean_value(ai_field, "light.kueche") == (None, "invalid_ai_entity")
    assert schema.clean_value(todo, "ai_task.ollama") == (None, "invalid_entity")
    # the receipt photo picker stays AI Task only
    receipt = schema.FIELD_MAP["receipt_ai_task_entity"]
    assert schema.clean_value(receipt, "conversation.jarvis") == (None, "invalid_entity")
    assert schema.error_messages({"receipt_ai_task_entity": "invalid_entity"}) == {
        "receipt_ai_task_entity": "Bitte eine Entität der Art „ai_task“ wählen."
    }
    assert (
        "Gesprächsagent" in schema.error_messages({"ai_entity": "invalid_ai_entity"})["ai_entity"]
    )
    # ai_features: an empty selection is a value (all AI features off), unknown ones are
    # dropped when read and refused when saved
    assert schema.current_values({"ai_features": []})["ai_features"] == []
    assert schema.current_values({"ai_features": ["drinks", "alt"]})["ai_features"] == ["drinks"]
    assert schema.current_values({})["ai_features"] == ["occasions", "drinks", "season", "receipts"]
    assert schema.validate({"ai_features": []}) == ({"ai_features": []}, {})
    assert schema.validate({"ai_features": ["telepathie"]})[1] == {"ai_features": "invalid_choice"}
    # offer_stores keeps its 1.4 meaning: nothing chosen = the default chains
    assert schema.current_values({"offer_stores": []})["offer_stores"] == list(
        schema.FIELD_MAP["offer_stores"].default
    )
    assert set(schema.CHOICE_LABELS_DE["ai_feature"]) == set(const.AI_FEATURES)


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
    assert messages["zip_code"] == schema.ERROR_TEXTS_DE["invalid_zip"]
    assert messages["shopping_sync_entity"] == "Bitte eine Entität der Art „todo“ wählen."
    # marktguru: a postcode of a selected branch is enough; a wrong postcode never is
    assert schema.validate({**base, "offers_source": "marktguru"}, ["57601"])[1] == {}
    assert schema.validate({**base, "offers_source": "marktguru", "zip_code": "123"}, ["57601"])[
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


async def test_new_installation_shows_the_defaults(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """A fresh setup shows the defaults in the panel (with the servings chosen at setup);
    the options dialog shows the same panel switch."""
    entry = setup_integration
    values = schema.current_values({**entry.data, **entry.options})
    expected = {
        **schema.default_values(),
        "enabled_meals": ["fruehstueck", "mittagessen", "abendessen"],
    }
    assert values == expected
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert _defaults(result) == {"show_panel": values["show_panel"]}


# ----------------------------------------------------------------------------------
# Websockets
# ----------------------------------------------------------------------------------


async def test_get_settings(
    hass: HomeAssistant, setup_integration: MockConfigEntry, hass_ws_client
) -> None:
    """Values, defaults, field limits, choices (entities from the states) and hints."""
    entry = setup_integration
    hass.states.async_set("zone.home", "0", {"friendly_name": "Zuhause", "latitude": 48.1})
    hass.states.async_set("zone.arbeit", "0", {"friendly_name": "Arbeit", "latitude": 48.2})
    hass.states.async_set("todo.bring", "3", {"friendly_name": "Bring!"})
    hass.states.async_set("ai_task.ollama", "unavailable", {"friendly_name": "Ollama"})
    hass.states.async_set("conversation.jarvis", "unknown", {"friendly_name": "Jarvis"})
    hass.states.async_set("conversation.home_assistant", "unknown", {"friendly_name": "HA"})
    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            "offers_source": "marktguru",
            "zip_code": "57601",
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
    assert values["zip_code"] == "57601"
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
    assert res["fields"]["ai_entity"]["domains"] == ["ai_task", "conversation"]
    assert res["fields"]["ai_features"] == {"section": "ai", "type": "multi"}
    assert res["sections"] == ["general", "planning", "offers", "stores", "receipts", "ai"]
    assert values["ai_entity"] is None
    assert values["ai_features"] == ["occasions", "drinks", "season", "receipts"]
    assert values["season_aware"] is True and values["all_leaflets"] is True
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
    # 1.5: the AI picker lists AI Tasks and conversation agents (not Home Assistant's own
    # agent, it cannot answer in JSON) with their kind
    assert choices["ai_entities"] == [
        {"value": "ai_task.ollama", "label": "Ollama", "available": False, "kind": "ai_task"},
        {
            "value": "conversation.jarvis",
            "label": "Jarvis",
            "available": True,
            "kind": "conversation",
        },
    ]
    assert choices["ai_features"][0] == {"value": "occasions", "label": "Anlässe (Menü-Vorschläge)"}
    assert [c["value"] for c in choices["ai_features"]] == list(const.AI_FEATURES)
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
    """Invalid values come back per field (German, like the 1.3 options flow) and nothing is
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
            "zip_code": schema.ERROR_TEXTS_DE["invalid_zip"],
        },
    }
    await hass.async_block_till_done()
    assert dict(entry.options) == before
    assert entry.runtime_data is manager  # no reload


async def test_save_settings_stores_and_reloads(
    hass: HomeAssistant, setup_integration: MockConfigEntry, hass_ws_client
) -> None:
    """Valid settings are stored like the 1.3 options flow stored them; other option keys stay,
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
    entry.runtime_data.save_branch({"store": "Lidl", "postcode": "56501"})
    client = await hass_ws_client(hass)
    msg = await _ws(client, 1, "save_settings", values={"offers_source": "marktguru"})
    assert msg["result"] == {"saved": True, "reload": True}
    await hass.async_block_till_done()
    assert entry.options["offers_source"] == "marktguru"
    assert entry.options["zip_code"] == ""
    # the branch survived the reload
    assert entry.runtime_data.branch_postcodes() == ["56501"]
    msg = await _ws(client, 2, "get_settings")
    assert msg["result"]["branch_postcodes"] == ["56501"]
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


PANEL_JS = Path(__file__).parent.parent / "custom_components" / DOMAIN / "frontend"


async def test_panel_knows_every_setting(
    hass: HomeAssistant, setup_integration: MockConfigEntry, hass_ws_client
) -> None:
    """1.5: every setting has a label and help in the panel and is shown in its section; the
    panel's ENTITY_CHOICES / SELECT_CHOICES / MULTI_CHOICES maps name a choice list of
    get_settings for every entity, select and multi field (no hard-coded key checks)."""
    panel = (PANEL_JS / "essensplaner-panel.js").read_text(encoding="utf-8")
    info = re.search(r"^const SETTING_INFO = \{\n(.*?)^\};", panel, re.M | re.S)
    assert info
    labelled = set(re.findall(r"^  (\w+): \[", info.group(1), re.M))
    shown = set(re.findall(r'f\("(\w+)"\)', panel))
    shown |= {f"time_{meal}" for meal in const.ALL_MEALS}  # f(`time_${m}`)
    block = re.search(r"^const SETTINGS_SECTIONS = \[\n(.*?)^\];", panel, re.M | re.S)
    assert block
    assert re.findall(r'^  \["(\w+)", "', block.group(1), re.M) == schema.SECTIONS

    def choice_map(name: str) -> dict[str, str]:
        found = re.search(rf"^const {name} = \{{(.*?)\}};$", panel, re.M | re.S)
        assert found, name
        body = found.group(1)
        if name == "ENTITY_CHOICES":
            return dict(re.findall(r'(\w+): \{ list: "(\w+)"', body))
        return dict(re.findall(r'(\w+): "(\w+)"', body))

    maps = {
        "entity": choice_map("ENTITY_CHOICES"),
        "select": choice_map("SELECT_CHOICES"),
        "multi": choice_map("MULTI_CHOICES"),
    }
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/get_settings"})
    choices = (await client.receive_json())["result"]["choices"]
    for field in schema.FIELDS:
        assert field.key in labelled, field.key
        assert field.key in shown, field.key
        if field.kind in maps:
            assert maps[field.kind].get(field.key) in choices, field.key
    assert maps["entity"]["ai_entity"] == "ai_entities"
    assert maps["multi"]["ai_features"] == "ai_features"
    assert maps["select"]["default_meal"] == "meals"
