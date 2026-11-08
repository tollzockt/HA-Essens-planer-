"""1.5 phase P7b: the panel's occasions (week plan cards and editor), drinks ("🍷 Passt
dazu", meal entry), season (row, view, badges, reasons), "🤖 mit KI" and the dashboard
card's occasions – the backend pieces they need and static checks of the panel file (the
UI itself is checked in the browser harness)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import re
from typing import Any

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.essensplaner import drinks, occasions
from custom_components.essensplaner.const import AI_FEATURES, DOMAIN

FRONTEND = Path(__file__).parent.parent / "custom_components" / DOMAIN / "frontend"
PANEL = (FRONTEND / "essensplaner-panel.js").read_text(encoding="utf-8")
CARD = (FRONTEND / "essensplaner-card.js").read_text(encoding="utf-8")
AGENT = "conversation.jarvis"


def _js_list(name: str) -> list[str]:
    """Strings of `const NAME = [...]` or `const NAME = new Set([...])` (one line)."""
    found = re.search(rf"^const {name} = (?:new Set\()?\[(.*?)\]\)?;$", PANEL, re.M)
    assert found, name
    return re.findall(r'"([^"]+)"', found.group(1))


def _js_keys(name: str) -> list[str]:
    found = re.search(rf"^const {name} = \{{(.*?)\}};$", PANEL, re.M)
    assert found, name
    return re.findall(r'(?:^|[{,\s])"?(\w+)"?: ', found.group(1))


async def test_panel_occasion_websockets(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The occasion editor, drinks and the season view use registered websockets."""
    used = set(re.findall(r"type: `\$\{DOMAIN\}/(\w+)`", PANEL))
    registered = {
        command.removeprefix(f"{DOMAIN}/")
        for command in hass.data[websocket_api.DOMAIN]
        if command.startswith(f"{DOMAIN}/")
    }
    for name in (
        "occasion_save",
        "occasion_delete",
        "occasion_suggest",
        "drinks_suggest",
        "season",
    ):
        assert name in used, name
    assert used <= registered, sorted(used - registered)


def test_panel_constants_match_the_backend() -> None:
    """Courses, drink tags, drink kinds and the item fields of the panel are the backend's."""
    assert _js_list("OCC_COURSES") == list(occasions.COURSES)
    assert set(_js_list("DISH_COURSES")) == set(occasions.DISH_COURSES)
    assert set(_js_keys("COURSE_ADD")) == set(occasions.COURSES)
    assert set(_js_list("DRINK_TAGS")) == set(occasions.DRINK_TAGS)
    assert set(_js_keys("DRINK_EMOJI")) == set(drinks.KINDS)
    fields = set(_js_list("OCC_ITEM_FIELDS"))
    assert fields == set(occasions._ITEM_FIELDS) - {"uid", "course", "servings"}
    # the AI buttons follow the features of the data export
    for feature in ('_aiOn("occasions")', '_aiOn("drinks")', '_aiOn("season")'):
        assert feature in PANEL, feature


def test_templates_carry_their_counts() -> None:
    """ "✓ Fehlendes übernehmen" fills each course up to the template's count."""
    for view in occasions.templates_view():
        info = occasions.TEMPLATES[view["id"]]
        assert view["counts"] == dict(info["courses"])
        assert view["courses"] == list(info["courses"])


def _fake_agent(hass: HomeAssistant, state: str = "unknown") -> None:
    async def handler(call: ServiceCall) -> dict[str, Any]:
        return {"response": {"speech": {"plain": {"speech": "{}"}}, "response_type": "action_done"}}

    hass.services.async_register(
        "conversation", "process", handler, supports_response=SupportsResponse.OPTIONAL
    )
    hass.states.async_set(AGENT, state, {"friendly_name": "Jarvis"})


async def test_data_export_ai_block(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """essensplaner/data says which AI buttons to show (also for non-admins), without the
    entity id, prompts or answers."""
    manager = setup_integration.runtime_data
    block = manager.export()["ai"]
    assert block == {
        "configured": False,
        "available": False,
        "label": None,
        "mode": None,
        "enabled": dict.fromkeys(AI_FEATURES, False),
        "ready": dict.fromkeys(AI_FEATURES, False),
    }

    _fake_agent(hass)
    hass.config_entries.async_update_entry(
        setup_integration, options={**setup_integration.options, "ai_entity": AGENT}
    )
    await hass.async_block_till_done()
    manager = setup_integration.runtime_data
    block = manager.export()["ai"]
    assert block["configured"] is True and block["available"] is True
    assert block["label"] == "Jarvis" and block["mode"] == "conversation"
    assert block["enabled"] == {
        "occasions": True,
        "drinks": True,
        "season": True,
        "products": False,  # not switched on by default
        "receipts": False,  # photos need an AI Task, not a conversation agent
    }
    assert block["ready"]["occasions"] and block["ready"]["season"]
    assert AGENT not in repr(block)

    # switched on but not reachable: the button shows, "ready" says it will fail
    hass.states.async_set(AGENT, "unavailable", {"friendly_name": "Jarvis"})
    block = manager.export()["ai"]
    assert block["enabled"]["occasions"] is True
    assert block["ready"]["occasions"] is False and block["available"] is False


async def test_plan_meal_same_dish_keeps_cooked(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """ "Getränk hinzufügen" plans the same dish again with its drinks: it stays cooked and
    keeps when it was planned; another dish in the slot starts uncooked."""
    manager = setup_integration.runtime_data
    day = date(2026, 11, 4)
    recipe = next(iter(manager.recipes.values()))
    first = manager.plan_meal(day, "abendessen", recipe=recipe, servings=2)
    assert first["cooked"] is False
    manager.plan[day.isoformat()]["abendessen"]["cooked"] = True
    added = manager.plan[day.isoformat()]["abendessen"]["added"]

    entry = manager.plan_meal(
        day,
        "abendessen",
        recipe=recipe,
        servings=2,
        drinks=[{"title": "Apfelschorle"}, {"title": "Rotwein, kräftig", "alcohol": True}],
    )
    stored = manager.plan[day.isoformat()]["abendessen"]
    assert entry["cooked"] is True and stored["added"] == added
    assert [d["title"] for d in entry["drinks"]] == ["Apfelschorle", "Rotwein, kräftig"]
    assert [d["alcohol"] for d in entry["drinks"]] == [False, True]

    other = next(r for r in manager.recipes.values() if r["id"] != recipe["id"])
    entry = manager.plan_meal(day, "abendessen", recipe=other)
    assert entry["cooked"] is False and entry["drinks"] == []


def test_dashboard_card_shows_occasions() -> None:
    """The card has an optional "Heute: 🎬 Filmabend" line and occasion chips in the week
    (option show_occasions, default on); it needs no new common.js names."""
    assert "show_occasions: true" in CARD
    assert "Heute: <b>" in CARD
    assert 'data-key="show_occasions"' in CARD
    assert "_occasions(iso)" in CARD
