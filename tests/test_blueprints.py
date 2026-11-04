"""The blueprints are valid Home Assistant automation blueprints."""

from __future__ import annotations

import inspect
from pathlib import Path

from homeassistant.components.automation.config import (
    AUTOMATION_BLUEPRINT_SCHEMA,
    async_validate_config_item,
)
from homeassistant.components.blueprint import models
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import load_yaml_dict
import pytest

BLUEPRINTS = Path(__file__).parent.parent / "blueprints" / "automation" / "essensplaner"


@pytest.mark.parametrize("name", ["erinnerung.yaml", "wochenroutine.yaml"])
async def test_blueprint_valid(hass: HomeAssistant, name: str) -> None:
    """Blueprint metadata is valid and the substituted automation validates."""
    assert await async_setup_component(hass, "homeassistant", {})
    data = load_yaml_dict(str(BLUEPRINTS / name))
    kwargs = {"expected_domain": "automation", "path": name}
    if "schema" in inspect.signature(models.Blueprint).parameters:
        kwargs["schema"] = AUTOMATION_BLUEPRINT_SCHEMA
    blueprint = models.Blueprint(data, **kwargs)
    inputs = models.BlueprintInputs(blueprint, {"use_blueprint": {"path": name, "input": {}}})
    inputs.validate()
    config = inputs.async_substitute()
    config["id"] = "test"
    config["alias"] = "Test"
    validated = await async_validate_config_item(hass, "automation.test", config)
    assert validated is not None
    assert not getattr(validated, "validation_error", None), getattr(
        validated, "validation_error", None
    )
