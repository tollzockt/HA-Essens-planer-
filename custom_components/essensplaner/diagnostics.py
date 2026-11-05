"""Diagnostics support."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .manager import EssensplanerManager

# where the user lives / shops: coordinates, streets (also in labels), distances to zones
# and OpenStreetMap ids (which point to one exact shop)
TO_REDACT = {
    "lat",
    "lon",
    "latitude",
    "longitude",
    "street",
    "label",
    "store_label",
    "near",
    "route",
    "id",
    "main_branch",
}


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
            "branches": len(manager.branches),
            "store_prices_user": {r: len(v) for r, v in manager.store_prices_user.items()},
            "store_prices_learned": {r: len(v) for r, v in manager.store_prices_learned.items()},
            "store_preferences": len(manager.store_preferences),
            "article_history": len(manager.article_history),
        },
        "enabled_meals": manager.enabled_meals,
        "meal_times": {m: manager.meal_time(m).strftime("%H:%M") for m in manager.enabled_meals},
        "today": today.isoformat(),
        "next_meal": manager.next_meal(),
        "recipe_names": sorted(r["name"] for r in manager.recipes.values()),
        "data_version": manager.data_version,
        "store_split": manager.split_settings(),
        "main_retailer": manager.main_retailer,
        "active_retailers": manager.active_retailers(),
        "offer_targets": manager.offer_targets_view(),
        "branches": async_redact_data(
            [{**b, "main": b.get("id") == manager.main_branch} for b in manager.branches],
            TO_REDACT,
        ),
        "shopping_stores": [
            {k: g[k] for k in ("retailer", "main", "open", "priced", "subtotal", "saving")}
            for g in manager.stores_summary()
        ],
        "price_sources_meta": async_redact_data(manager.price_sources_meta, TO_REDACT),
        "branch_search": async_redact_data(
            {k: v for k, v in manager.branch_search.items() if k != "results"}, TO_REDACT
        ),
    }
