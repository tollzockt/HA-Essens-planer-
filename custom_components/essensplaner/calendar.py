"""Calendar showing the meal plan."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEntityFeature, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import ALL_MEALS
from .dates import parse_meal
from .entity import EssensplanerEntity
from .manager import EssensplanerManager

MEAL_DURATION = timedelta(minutes=45)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the calendar."""
    async_add_entities([MealPlanCalendar(entry.runtime_data)])


class MealPlanCalendar(EssensplanerEntity, CalendarEntity):
    """All planned meals as calendar events."""

    _attr_icon = "mdi:calendar-heart"
    _attr_supported_features = (
        CalendarEntityFeature.CREATE_EVENT | CalendarEntityFeature.DELETE_EVENT
    )

    def __init__(self, manager: EssensplanerManager) -> None:
        """Initialize the calendar."""
        super().__init__(manager, "meal_plan")

    def _event(self, view: dict[str, Any]) -> CalendarEvent:
        day = date.fromisoformat(view["date"])
        start = self.manager.meal_datetime(day, view["meal"])
        description_parts = []
        if view.get("servings"):
            description_parts.append(f"{view['servings']} Portionen")
        if view.get("total_time"):
            description_parts.append(f"ca. {view['total_time']} Minuten")
        if view.get("note"):
            description_parts.append(view["note"])
        recipe = self.manager.recipes.get(view.get("recipe_id") or "")
        if recipe:
            lines = self.manager.recipe_view(recipe, view.get("servings"))["ingredient_lines"]
            if lines:
                description_parts.append("Zutaten: " + ", ".join(lines))
        return CalendarEvent(
            start=start,
            end=start + MEAL_DURATION,
            summary=f"{view['meal_label']}: {view['title']}",
            description="\n".join(description_parts) or None,
            uid=f"{view['date']}_{view['meal']}",
        )

    @property
    def event(self) -> CalendarEvent | None:
        """The next meal."""
        upcoming = self.manager.next_meal()
        return self._event(upcoming) if upcoming else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return meals between two datetimes."""
        start_local = dt_util.as_local(start_date).date() - timedelta(days=1)
        end_local = dt_util.as_local(end_date).date()
        events: list[CalendarEvent] = []
        day = start_local
        while day <= end_local:
            for view in self.manager.day_meals(day):
                event = self._event(view)
                if event.end > start_date and event.start < end_date:
                    events.append(event)
            day += timedelta(days=1)
        return events

    async def async_create_event(self, **kwargs: Any) -> None:
        """Plan a meal from a calendar event."""
        summary = str(kwargs.get("summary") or "").strip()
        start = kwargs.get("dtstart")
        meal: str | None = None
        if ":" in summary:
            prefix, rest = summary.split(":", 1)
            if (parsed := parse_meal(prefix)) is not None:
                meal, summary = parsed, rest.strip()
        if isinstance(start, datetime):
            local = dt_util.as_local(start)
            day = local.date()
            if meal is None:
                candidates = self.manager.enabled_meals or ALL_MEALS
                minutes = local.hour * 60 + local.minute
                meal = min(
                    candidates,
                    key=lambda m: abs(
                        self.manager.meal_time(m).hour * 60
                        + self.manager.meal_time(m).minute
                        - minutes
                    ),
                )
        elif isinstance(start, date):
            day = start
        else:
            day = self.manager.today()
        meal = meal or self.manager.default_meal
        recipe = self.manager.find_recipe(summary)
        self.manager.plan_meal(
            day,
            meal,
            recipe=recipe,
            title=None if recipe else summary,
            note=kwargs.get("description"),
        )

    async def async_delete_event(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Remove a meal."""
        day_text, _, meal = uid.partition("_")
        self.manager.remove_meal(date.fromisoformat(day_text), meal or None)
