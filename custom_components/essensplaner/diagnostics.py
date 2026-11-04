"""Diagnostics support."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .manager import EssensplanerManager


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    manager: EssensplanerManager = entry.runtime_data
    today = manager.today()
    return {
        "options": dict(entry.options),
        "counts": {
            "recipes": len(manager.recipes),
            "plan_days": len(manager.plan),
            "planned_next_7_days": sum(len(d["meals"]) for d in manager.plan_range(today, 7)),
            "shopping_items": len(manager.shopping),
            "shopping_open": sum(1 for i in manager.shopping if i.get("status") != "completed"),
        },
        "enabled_meals": manager.enabled_meals,
        "meal_times": {m: manager.meal_time(m).strftime("%H:%M") for m in manager.enabled_meals},
        "today": today.isoformat(),
        "next_meal": manager.next_meal(),
        "recipe_names": sorted(r["name"] for r in manager.recipes.values()),
    }
