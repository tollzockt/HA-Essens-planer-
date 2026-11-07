"""Translation and documentation audit: de/en/strings, services, icons, errors, entities, flows.

Keeps translations/de.json, translations/en.json, strings.json, services.yaml, icons.json,
the Python code, README.md and CHANGELOG.md consistent (no generator script needed).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
import re
from typing import Any
import unicodedata

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import SelectSelector
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import yaml

from custom_components.essensplaner.const import DOMAIN
from custom_components.essensplaner.intents import INTENT_HANDLERS
from custom_components.essensplaner.manager import ERROR_MESSAGES_DE
from custom_components.essensplaner.retailers import RETAILERS

ROOT = Path(__file__).parent.parent
PKG = ROOT / "custom_components" / DOMAIN
LANGUAGES = ("de", "en")
PLACEHOLDER = re.compile(r"{(\w+)}")
# constructors that take (translation_key, ...) as first argument; "cls" is the
# error/unexpected switch in rewe._failed, aldi._failed, edeka._failed and catalog._failed
ERROR_FACTORIES = {
    "_error",
    "BranchSearchError",
    "ReweError",
    "ReweBlocked",
    "ReweUnexpected",
    "AldiError",
    "AldiBlocked",
    "AldiUnexpected",
    "EdekaError",
    "EdekaBlocked",
    "EdekaUnexpected",
    "MarktguruError",
    "MarktguruBlocked",
    "MarktguruUnexpected",
    "MarktguruUnavailable",
    "cls",
}


def _load(name: str) -> dict[str, Any]:
    return json.loads((PKG / name).read_text(encoding="utf-8"))


TRANSLATIONS = {lang: _load(f"translations/{lang}.json") for lang in LANGUAGES}
SERVICES_YAML: dict[str, Any] = yaml.safe_load((PKG / "services.yaml").read_text("utf-8"))
ICONS = _load("icons.json")


def _leaves(data: Any, path: tuple[str, ...] = ()) -> dict[tuple[str, ...], str]:
    """All string values by key path."""
    if isinstance(data, dict):
        result: dict[tuple[str, ...], str] = {}
        for key, value in data.items():
            result.update(_leaves(value, (*path, key)))
        return result
    return {path: data}


def _keys(data: Any, path: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    if not isinstance(data, dict):
        return set()
    result = set()
    for key, value in data.items():
        result.add((*path, key))
        result |= _keys(value, (*path, key))
    return result


def _placeholders(text: str) -> set[str]:
    return set(PLACEHOLDER.findall(text))


def _fields(service: str) -> dict[str, Any]:
    return (SERVICES_YAML.get(service) or {}).get("fields") or {}


# ----------------------------------------------------------------------
# Files
# ----------------------------------------------------------------------


def test_de_en_same_structure_and_placeholders() -> None:
    """de.json and en.json have the same keys and the same placeholders in every string."""
    de, en = TRANSLATIONS["de"], TRANSLATIONS["en"]
    assert sorted(_keys(de) - _keys(en)) == [], "only in de.json"
    assert sorted(_keys(en) - _keys(de)) == [], "only in en.json"
    en_leaves = _leaves(en)
    for path, text in _leaves(de).items():
        assert isinstance(text, str) and text.strip(), path
        assert isinstance(en_leaves[path], str) and en_leaves[path].strip(), path
        assert _placeholders(text) == _placeholders(en_leaves[path]), path


def test_strings_json_equals_en() -> None:
    """strings.json is the English source and must equal translations/en.json."""
    assert _load("strings.json") == TRANSLATIONS["en"]


@pytest.mark.parametrize("lang", LANGUAGES)
def test_strings_follow_hassfest_rules(lang: str) -> None:
    """No HTML, no surrounding spaces, no single-quoted placeholders, no URLs."""
    for path, text in _leaves(TRANSLATIONS[lang]).items():
        assert text == text.strip(), path
        assert not re.search(r"<[a-zA-Z/][^>]*>", text), path
        assert not re.search(r"'{\w+}'", text), path
        assert "http://" not in text and "https://" not in text, path
        assert not re.search(r"\[%key:[^\]]+\]\S", text), path


# ----------------------------------------------------------------------
# Services
# ----------------------------------------------------------------------


@pytest.mark.parametrize("lang", LANGUAGES)
def test_services_translated(lang: str) -> None:
    """Every service and field in services.yaml has a name and description, nothing extra."""
    services = TRANSLATIONS[lang]["services"]
    assert sorted(services) == sorted(SERVICES_YAML)
    for service in SERVICES_YAML:
        texts = services[service]
        assert texts.get("name") and texts.get("description"), service
        translated = texts.get("fields") or {}
        assert sorted(translated) == sorted(_fields(service)), service
        for field, field_texts in translated.items():
            assert field_texts.get("name"), f"{service}.{field}"
            assert field_texts.get("description"), f"{service}.{field}"


def test_services_yaml_fields_complete() -> None:
    """Every field has a selector; text fields have an example."""
    for service, spec in SERVICES_YAML.items():
        for field, field_spec in _fields(service).items():
            assert isinstance(field_spec.get("selector"), dict), f"{service}.{field}"
            assert "name" not in field_spec and "description" not in field_spec, (
                f"{service}.{field}: texts belong into the translations"
            )
            selector = field_spec["selector"]
            if "text" in selector and field_spec.get("required"):
                assert "example" in field_spec, f"{service}.{field}"
        assert spec is None or set(spec) <= {"fields", "target"}, service


async def test_registered_services_documented(hass: HomeAssistant, setup_integration) -> None:
    """Registered services == services.yaml == icons.json; schema keys == fields."""
    registered = hass.services.async_services_for_domain(DOMAIN)
    assert sorted(registered) == sorted(SERVICES_YAML)
    assert sorted(ICONS["services"]) == sorted(SERVICES_YAML)
    for service, icon in ICONS["services"].items():
        assert icon["service"].startswith("mdi:"), service
    for name, service in registered.items():
        schema = getattr(service.schema, "schema", {}) or {}
        keys = {str(key) for key in schema}
        assert keys == set(_fields(name)), name


def _yaml_selects(data: Any) -> list[dict[str, Any]]:
    """All select selectors with a translation key in services.yaml."""
    found: list[dict[str, Any]] = []
    if isinstance(data, dict):
        select = data.get("select")
        if isinstance(select, dict) and select.get("translation_key"):
            found.append(select)
        for value in data.values():
            found.extend(_yaml_selects(value))
    return found


@pytest.mark.parametrize("lang", LANGUAGES)
def test_service_selectors_translated(lang: str) -> None:
    """select selectors of services.yaml with translation_key have all options translated."""
    selectors = TRANSLATIONS[lang]["selector"]
    found = _yaml_selects(SERVICES_YAML)
    assert found
    for select in found:
        options = selectors[select["translation_key"]]["options"]
        for option in select["options"]:
            value = option["value"] if isinstance(option, dict) else option
            assert value in options, f"{select['translation_key']}.{value}"


@pytest.mark.parametrize("lang", LANGUAGES)
def test_retailer_selector_matches_retailers(lang: str) -> None:
    """The retailer selector lists exactly the known retailers."""
    assert sorted(TRANSLATIONS[lang]["selector"]["retailer"]["options"]) == sorted(RETAILERS)


# ----------------------------------------------------------------------
# Errors (exceptions)
# ----------------------------------------------------------------------


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _exception_uses() -> dict[str, list[tuple[str, set[str] | None]]]:
    """translation key -> [(place, placeholders given or None if unknown)] from the code."""
    uses: dict[str, list[tuple[str, set[str] | None]]] = {}
    for path in sorted(PKG.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            place = f"{path.name}:{node.lineno}"
            keywords = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            key: str | None = None
            given: set[str] | None = None
            if (
                _call_name(node) in ERROR_FACTORIES
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                key = node.args[0].value
                given = set(keywords)
                if any(kw.arg is None for kw in node.keywords):
                    given = None  # **placeholders
            elif "translation_domain" in keywords and isinstance(
                keywords.get("translation_key"), ast.Constant
            ):
                key = keywords["translation_key"].value
                value = keywords.get("translation_placeholders")
                if value is None:
                    given = set()
                elif isinstance(value, ast.Dict) and all(
                    isinstance(k, ast.Constant) for k in value.keys
                ):
                    given = {k.value for k in value.keys}  # type: ignore[union-attr]
            if key is not None:
                uses.setdefault(key, []).append((place, given))
    return uses


def test_exception_keys_translated() -> None:
    """Every error raised in the code exists in de/en with placeholders the code provides."""
    uses = _exception_uses()
    # the scan has to find the keys of all error styles
    for key in ("recipe_not_found", "invalid_strategy", "no_recipe_found", "overpass_failed"):
        assert key in uses, key
    assert "rewe_failed" in uses and "rewe_blocked" in uses
    for lang in LANGUAGES:
        exceptions = TRANSLATIONS[lang]["exceptions"]
        for key, places in uses.items():
            assert key in exceptions, f"{lang}: {key} ({places[0][0]})"
            needed = _placeholders(exceptions[key]["message"])
            for place, given in places:
                if given is not None:
                    assert needed <= given, f"{lang}: {key} at {place} misses {needed - given}"
    # no stale messages: every translated error is raised somewhere
    assert sorted(set(TRANSLATIONS["de"]["exceptions"]) - set(uses)) == []


def test_german_error_messages_consistent() -> None:
    """manager.ERROR_MESSAGES_DE (used for Jarvis/panel answers) matches the translations."""
    exceptions = TRANSLATIONS["de"]["exceptions"]
    uses = _exception_uses()
    for key, text in ERROR_MESSAGES_DE.items():
        assert key in exceptions, key
        assert _placeholders(text) == _placeholders(exceptions[key]["message"]), key
        for place, given in uses.get(key, []):
            if given is not None:
                assert _placeholders(text) <= given, f"{key} at {place}"
    # every error a voice/panel answer can hit has a German text
    assert sorted(set(uses) - set(ERROR_MESSAGES_DE)) == []


# ----------------------------------------------------------------------
# Entities
# ----------------------------------------------------------------------


async def test_entity_translation_keys(hass: HomeAssistant, setup_integration) -> None:
    """Every entity has a translated name and an icon; no stale entity texts."""
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, setup_integration.entry_id)
    used: dict[str, set[str]] = {}
    for entry in entries:
        assert entry.translation_key, entry.entity_id
        used.setdefault(entry.domain, set()).add(entry.translation_key)
    assert {"sensor", "button", "calendar", "todo"} <= set(used)
    assert {"shopping_stores", "shopping_total"} <= used["sensor"]
    for lang in LANGUAGES:
        entity = TRANSLATIONS[lang]["entity"]
        assert sorted(entity) == sorted(used), lang
        for domain, keys in used.items():
            assert sorted(entity[domain]) == sorted(keys), f"{lang}: {domain}"
            for key in keys:
                assert entity[domain][key]["name"], f"{lang}: {domain}.{key}"
    for domain, keys in used.items():
        assert sorted(ICONS["entity"][domain]) == sorted(keys), domain


# ----------------------------------------------------------------------
# Config and options flow
# ----------------------------------------------------------------------


def _schema_info(result: dict[str, Any]) -> tuple[list[str], list[SelectSelector]]:
    keys: list[str] = []
    selects: list[SelectSelector] = []
    for marker, validator in result["data_schema"].schema.items():
        keys.append(str(marker))
        if isinstance(validator, SelectSelector):
            selects.append(validator)
    return keys, selects


def _check_step(section: str, result: dict[str, Any]) -> None:
    """Title, description placeholders, data and data_description of a form step."""
    keys, selects = _schema_info(result)
    placeholders = set(result.get("description_placeholders") or {})
    for lang in LANGUAGES:
        step = TRANSLATIONS[lang][section]["step"][result["step_id"]]
        where = f"{lang}: {section}.{result['step_id']}"
        assert step.get("title"), where
        for text_key in ("title", "description"):
            if text_key in step:
                assert _placeholders(step[text_key]) <= placeholders, where
        if placeholders:
            assert placeholders <= _placeholders(step.get("description", "")), where
        assert sorted(step["data"]) == sorted(keys), where
        assert sorted(step.get("data_description", {})) == sorted(keys), where
        for select in selects:
            translation_key = select.config.get("translation_key")
            if not translation_key:
                continue
            options = TRANSLATIONS[lang]["selector"][translation_key]["options"]
            for option in select.config["options"]:
                value = option["value"] if isinstance(option, dict) else option
                assert value in options, f"{where}: {translation_key}.{value}"


def _flow_texts() -> tuple[set[str], set[str]]:
    """Error and abort keys used in config_flow.py."""
    source = (PKG / "config_flow.py").read_text(encoding="utf-8")
    errors = set(re.findall(r'errors\[[^\]]+\]\s*=\s*"(\w+)"', source))
    aborts = set(re.findall(r'async_abort\(reason="(\w+)"\)', source))
    return errors, aborts


def test_flow_errors_translated() -> None:
    """All form errors and abort reasons of config_flow.py are translated."""
    errors, aborts = _flow_texts()
    assert {"no_meals", "invalid_zip"} <= errors
    for lang in LANGUAGES:
        assert sorted(TRANSLATIONS[lang]["options"]["error"]) == sorted(errors), lang
        assert sorted(TRANSLATIONS[lang]["config"]["abort"]) == sorted(aborts), lang


async def test_config_flow_translated(hass: HomeAssistant) -> None:
    """The user step is fully translated."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    _check_step("config", result)
    for lang in LANGUAGES:
        assert sorted(TRANSLATIONS[lang]["config"]["step"]) == ["user"]


async def test_options_flow_translated(hass: HomeAssistant, setup_integration) -> None:
    """All options steps (init, economy, stores) are fully translated."""
    entry: MockConfigEntry = setup_integration
    result = await hass.config_entries.options.async_init(entry.entry_id)
    steps = []
    while result["type"] == "form":
        steps.append(result["step_id"])
        _check_step("options", result)
        # submit the defaults of the form
        data = {
            str(marker): marker.default()
            for marker in result["data_schema"].schema
            if callable(getattr(marker, "default", None)) and marker.default() is not None
        }
        if result["step_id"] == "init":
            data["enabled_meals"] = data.get("enabled_meals") or ["abendessen"]
        result = await hass.config_entries.options.async_configure(result["flow_id"], data)
        assert not result.get("errors"), result
    assert result["type"] == "create_entry"
    assert steps == ["init", "economy", "stores"]
    for lang in LANGUAGES:
        assert sorted(TRANSLATIONS[lang]["options"]["step"]) == sorted(steps), lang


# ----------------------------------------------------------------------
# Documentation
# ----------------------------------------------------------------------


def test_version_and_changelog() -> None:
    """manifest version == newest CHANGELOG entry; the panel reads the manifest version."""
    version = _load("manifest.json")["version"]
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    newest = re.search(r"^## (\d+\.\d+\.\d+)", changelog, re.MULTILINE)
    assert newest and newest.group(1) == version
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    assert "manifest.json" in (PKG / "panel.py").read_text(encoding="utf-8")


def test_readme_mentions_services_and_intents() -> None:
    """Every service and Jarvis intent is documented in the README."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    words = set(re.findall(r"[a-z_]+", readme))
    assert sorted(set(SERVICES_YAML) - words) == []
    assert sorted({h.intent_type for h in INTENT_HANDLERS} - words) == []


def _github_anchor(heading: str) -> str:
    """Anchor GitHub creates for a heading (letters, marks, numbers, '_', ' ', '-')."""
    kept = "".join(
        c for c in heading.strip().lower() if unicodedata.category(c)[0] in "LMN" or c in "_ -"
    )
    return kept.replace(" ", "-")


def test_readme_links_and_screenshots() -> None:
    """Links to sections of the README exist; screenshot placeholders are named .png files."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    anchors = {_github_anchor(h) for h in re.findall(r"^#{1,6} (.+)$", readme, re.MULTILINE)}
    links = re.findall(r"\]\(#([^)]+)\)", readme)
    assert links
    assert sorted(set(links) - anchors) == []
    for name in re.findall(r"<!-- screenshot: (\S+) -->", readme):
        assert re.fullmatch(r"[a-z0-9-]+\.png", name), name
    for image in re.findall(r"\]\((docs/images/[^)]+)\)", readme):
        assert (ROOT / image).is_file(), image
