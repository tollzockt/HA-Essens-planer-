"""Diagnostics support."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_ZIP
from .manager import EssensplanerManager

# where the user lives / shops: coordinates, streets (also in labels), distances to zones
# and OpenStreetMap / REWE / EDEKA market ids and ALDI SÜD service points (which point to
# one exact shop)
TO_REDACT = {
    "market_id",
    "rewe_market_id",
    "edeka_market_id",
    "aldi_service_point",
    "service_point",
    "branch_id",
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
# branches and the branch search: also where they are (postcode, town, OSM name like
# "Lidl Sendlinger Tor", zone names) – retailer, main flag and counts are enough
BRANCH_REDACT = TO_REDACT | {"postcode", "city", "name", "zip_code"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    manager: EssensplanerManager = entry.runtime_data
    today = manager.today()
    return {
        "options": async_redact_data(dict(entry.options), {CONF_ZIP}),
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
        "offer_targets": [{"retailers": t["retailers"]} for t in manager.offer_targets_view()],
        "branches": async_redact_data(
            [{**b, "main": b.get("id") == manager.main_branch} for b in manager.branches],
            BRANCH_REDACT,
        ),
        "shopping_stores": [
            {k: g[k] for k in ("retailer", "main", "open", "priced", "subtotal", "saving")}
            for g in manager.stores_summary()
        ],
        "price_sources_meta": async_redact_data(manager.price_sources_meta, BRANCH_REDACT),
        # the offer catalog: counts only (no offers, postcodes or store ids)
        "offer_catalog": _catalog_counts(manager),
        # receipts: counts only (no articles, prices, stores or images)
        "receipts": _receipt_counts(manager),
        # AI via Home Assistant (1.5): mode and state only (never prompts or answers)
        "ai": _ai_info(hass, manager),
        "branch_search": async_redact_data(
            {k: v for k, v in manager.branch_search.items() if k not in ("results", "key")},
            BRANCH_REDACT,
        ),
    }


def _receipt_counts(manager: EssensplanerManager) -> dict[str, Any]:
    """How many receipts / uploads / learned names and receipt prices exist."""
    from .receipts import ai_available, ai_entity

    receipts = manager.receipts.receipts
    by_source: dict[str, int] = {}
    for receipt in receipts:
        source = str(receipt.get("source") or "?")
        by_source[source] = by_source.get(source, 0) + 1
    return {
        "receipts": len(receipts),
        "by_source": dict(sorted(by_source.items())),
        "with_image": sum(1 for r in receipts if r.get("image")),
        "pending_uploads": len(manager.receipts.data.get("uploads") or {}),
        "learned_names": len(manager.receipts.data.get("aliases") or {}),
        "receipt_prices": sum(
            1
            for bucket in manager.store_prices_user.values()
            for item in bucket.values()
            if isinstance(item, dict) and item.get("source") == "receipt"
        ),
        "ai_configured": ai_entity(manager) is not None,
        "ai_available": ai_available(manager.hass, ai_entity(manager)),
    }


def _ai_info(hass: HomeAssistant, manager: EssensplanerManager) -> dict[str, Any]:
    """Which AI kind is configured, whether it is available, the switched-on features and
    the result of the last request (ok, seconds, code) – no entity names, prompts or
    answers."""
    from .ai import ai_status

    status = ai_status(hass, manager)
    last = status["last"] or {}
    return {
        "configured": status["configured"],
        "mode": status["mode"],
        "available": status["available"],
        "features": status["features"],
        "receipts_configured": status["receipts_entity"] is not None,
        "busy": status["busy"],
        "last": {k: last.get(k) for k in ("ok", "seconds", "mode", "feature", "code")}
        if last
        else None,
    }


def _catalog_counts(manager: EssensplanerManager) -> dict[str, Any]:
    """Status and counts of the offer catalog (per source / retailer / kind)."""
    catalog = manager.catalog
    today = manager.today()
    offers = catalog.current_offers(today)

    def count(field: str) -> dict[str, int]:
        result: dict[str, int] = {}
        for offer in offers:
            value = str(offer.get(field) or "?")
            result[value] = result.get(value, 0) + 1
        return dict(sorted(result.items()))

    summary = catalog.summary(manager)
    return {
        "status": summary["status"],
        "updated": summary["updated"],
        "last_run": summary["last_run"],
        "errors": len(summary["errors"]),
        "requests_last_run": summary["requests"],
        "offers": len(offers),
        "with_keys": sum(1 for o in offers if o.get("keys")),
        "online_only": sum(1 for o in offers if o.get("online_only")),
        "by_source": count("source"),
        "by_retailer": count("retailer"),
        "by_kind": count("kind"),
        "leaflets": len(catalog.leaflets(today)),
        "discovery_postcodes": len(catalog.data.get("publishers") or {}),
        "buckets": len(catalog.buckets),
        "matched": summary["matched"],
        "learned": summary["learned"],
        "blocked": summary["blocked_until"] is not None,
    }
