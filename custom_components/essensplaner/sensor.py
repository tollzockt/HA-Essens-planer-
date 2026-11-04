"""Sensors of the Essensplaner integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .dates import WEEKDAY_NAMES
from .entity import EssensplanerEntity
from .manager import EssensplanerManager

MAX_STATE = 255


def _truncate(text: str) -> str:
    return text if len(text) <= MAX_STATE else text[: MAX_STATE - 1] + "…"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    manager: EssensplanerManager = entry.runtime_data
    async_add_entities(
        [
            DaySensor(manager, "today", 0),
            DaySensor(manager, "tomorrow", 1),
            NextMealSensor(manager),
            WeekPlanSensor(manager),
            RecipesSensor(manager),
        ]
    )


class DaySensor(EssensplanerEntity, SensorEntity):
    """Meals planned for today / tomorrow."""

    _attr_icon = "mdi:silverware-fork-knife"
    _unrecorded_attributes = frozenset({"meals"})

    def __init__(self, manager: EssensplanerManager, key: str, offset: int) -> None:
        """Initialize the sensor."""
        super().__init__(manager, key)
        self._offset = offset

    @property
    def _meals(self) -> list[dict[str, Any]]:
        return self.manager.day_meals(self.manager.today() + timedelta(days=self._offset))

    @property
    def native_value(self) -> str:
        """Short text like 'Mittagessen: Linsensuppe · Abendessen: Lasagne'."""
        meals = self._meals
        if not meals:
            return "Nichts geplant"
        if len(meals) == 1:
            return _truncate(meals[0]["title"])
        return _truncate(" · ".join(f"{m['meal_label']}: {m['title']}" for m in meals))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Per meal details."""
        day = self.manager.today() + timedelta(days=self._offset)
        meals = self._meals
        attrs: dict[str, Any] = {
            "date": day.isoformat(),
            "weekday": WEEKDAY_NAMES[day.weekday()],
            "meals": meals,
        }
        for meal in self.manager.enabled_meals:
            attrs[meal] = next((m["title"] for m in meals if m["meal"] == meal), None)
        return attrs


class NextMealSensor(EssensplanerEntity, SensorEntity):
    """The next planned meal including the recipe."""

    _attr_icon = "mdi:food"
    _unrecorded_attributes = frozenset({"ingredients", "steps", "image"})

    def __init__(self, manager: EssensplanerManager) -> None:
        """Initialize the sensor."""
        super().__init__(manager, "next_meal")

    @property
    def native_value(self) -> str | None:
        """Title of the next meal."""
        upcoming = self.manager.next_meal()
        return _truncate(upcoming["title"]) if upcoming else None

    @property
    def entity_picture(self) -> str | None:
        """Recipe image."""
        upcoming = self.manager.next_meal()
        return upcoming.get("image") if upcoming else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Details incl. scaled ingredients and steps."""
        upcoming = self.manager.next_meal()
        if not upcoming:
            return {}
        attrs = dict(upcoming)
        recipe = self.manager.recipes.get(upcoming.get("recipe_id") or "")
        if recipe:
            view = self.manager.recipe_view(recipe, upcoming.get("servings"))
            attrs["ingredients"] = view["ingredient_lines"]
            attrs["steps"] = view.get("steps", [])
            attrs["source_url"] = recipe.get("source_url") or None
        return attrs


class WeekPlanSensor(EssensplanerEntity, SensorEntity):
    """Number of planned meals in the next 7 days, plan as attributes."""

    _attr_icon = "mdi:calendar-week"
    _attr_native_unit_of_measurement = "Mahlzeiten"
    _unrecorded_attributes = frozenset({"days", "summary"})

    def __init__(self, manager: EssensplanerManager) -> None:
        """Initialize the sensor."""
        super().__init__(manager, "week_plan")

    @property
    def native_value(self) -> int:
        """Number of planned meals."""
        days = self.manager.plan_range(self.manager.today(), 7)
        return sum(len(d["meals"]) for d in days)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The plan of the next 7 days."""
        days = self.manager.plan_range(self.manager.today(), 7)
        compact = [
            {
                "date": d["date"],
                "weekday": d["weekday"],
                "meals": {m["meal_label"]: m["title"] for m in d["meals"]},
            }
            for d in days
        ]
        summary = "\n".join(
            f"{d['weekday']}: "
            + (", ".join(f"{label} {title}" for label, title in d["meals"].items()) or "–")
            for d in compact
        )
        return {"days": compact, "summary": summary}


class RecipesSensor(EssensplanerEntity, SensorEntity):
    """Number of recipes, names as attribute."""

    _attr_icon = "mdi:book-open-variant"
    _attr_native_unit_of_measurement = "Rezepte"
    _unrecorded_attributes = frozenset({"recipes", "tags", "favorites"})

    def __init__(self, manager: EssensplanerManager) -> None:
        """Initialize the sensor."""
        super().__init__(manager, "recipes")

    @property
    def native_value(self) -> int:
        """Number of recipes."""
        return len(self.manager.recipes)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Recipe names and tags."""
        recipes = sorted(self.manager.recipes.values(), key=lambda r: r["name"].lower())
        tags = sorted({t for r in recipes for t in r.get("tags", [])}, key=str.lower)
        return {
            "recipes": [r["name"] for r in recipes][:300],
            "favorites": [r["name"] for r in recipes if r.get("favorite")],
            "tags": tags,
        }
