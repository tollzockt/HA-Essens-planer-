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
from .ingredients import fold
from .manager import EssensplanerManager
from .occasions import (
    COURSE_LABELS,
    COURSES,
    calendar_uid,
    create_occasion,
    delete_occasion,
    next_occasion,
    occasion_cost,
    occasion_date,
    occasion_end,
    occasion_label,
    occasion_start,
    occasions_between,
    quantity_text,
)
from .pricing import format_eur

MEAL_DURATION = timedelta(minutes=45)
# "Anlass: Omas Geburtstag" as a new event plans an occasion (1.5)
OCCASION_PREFIXES = ("anlass", "feier", "event")
OCCASION_UID = "occasion-"


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
        if leftover := view.get("leftover_of"):
            # 1.5.1: cooked on another day
            description_parts.append(
                f"Vorgekocht am {leftover['weekday']} ({leftover['meal_label']})"
            )
        elif recipe:
            servings = view.get("cook_servings") or view.get("servings")
            lines = self.manager.recipe_view(recipe, servings)["ingredient_lines"]
            if lines:
                description_parts.append("Zutaten: " + ", ".join(lines))
            if view.get("leftovers"):
                description_parts.append(
                    "Mitkochen für "
                    + ", ".join(
                        f"{x['weekday']} ({x['servings']} Portionen)"
                        if x.get("servings")
                        else x["weekday"]
                        for x in view["leftovers"]
                    )
                )
        if extras := [x["title"] for x in view.get("extras") or [] if x.get("title")]:
            description_parts.append("Dazu: " + ", ".join(extras))
        if drinks := [d.get("title") for d in view.get("drinks") or [] if d.get("title")]:
            description_parts.append("Getränke: " + ", ".join(drinks))
        return CalendarEvent(
            start=start,
            end=start + MEAL_DURATION,
            summary=f"{view['meal_label']}: {view['title']}",
            description="\n".join(description_parts) or None,
            uid=f"{view['date']}_{view['meal']}",
        )

    def _occasion_event(self, occasion: dict[str, Any]) -> CalendarEvent:
        """An occasion ("🎬 Filmabend") with guests, courses, cost and notes."""
        lines = []
        guests = int(occasion.get("guests") or 0)
        children = int(occasion.get("children") or 0)
        people = f"👥 {guests} {'Gast' if guests == 1 else 'Gäste'}"
        if children:
            people += f" + {children} {'Kind' if children == 1 else 'Kinder'}"
        lines.append(people)
        for course in COURSES:
            titles = [
                " ".join(filter(None, (quantity_text(i), str(i.get("title") or ""))))
                for i in occasion.get("items") or []
                if i.get("course") == course and i.get("title")
            ]
            if titles:
                lines.append(f"{COURSE_LABELS[course]}: {', '.join(titles)}")
        cost = occasion_cost(self.manager, occasion)["total"]
        if cost:
            lines.append(f"≈ {format_eur(cost)}")
        if occasion.get("notes"):
            lines.append(str(occasion["notes"]))
        if occasion.get("time"):
            start: date | datetime = occasion_start(occasion)
            end: date | datetime = occasion_end(occasion)
        else:
            start = occasion_date(occasion)
            end = start + timedelta(days=1)
        return CalendarEvent(
            start=start,
            end=end,
            summary=occasion_label(occasion),
            description="\n".join(lines),
            uid=calendar_uid(occasion),
        )

    @property
    def event(self) -> CalendarEvent | None:
        """The next meal or occasion (whatever starts first, a running one included)."""
        upcoming = self.manager.next_meal()
        events = [self._event(upcoming)] if upcoming else []
        if (occasion := next_occasion(self.manager)) is not None:
            events.append(self._occasion_event(occasion))
        if not events:
            return None
        return min(events, key=lambda e: e.start_datetime_local)

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
        for occasion in occasions_between(self.manager, start_local, end_local):
            event = self._occasion_event(occasion)
            if event.end_datetime_local > start_date and event.start_datetime_local < end_date:
                events.append(event)
        return events

    async def async_create_event(self, **kwargs: Any) -> None:
        """Plan a meal from a calendar event ("Abendessen: Lasagne"); "Anlass: Grillabend"
        plans an occasion (1.5)."""
        summary = str(kwargs.get("summary") or "").strip()
        start = kwargs.get("dtstart")
        meal: str | None = None
        if ":" in summary:
            prefix, rest = summary.split(":", 1)
            if fold(prefix) in OCCASION_PREFIXES and rest.strip():
                self._create_occasion(rest.strip(), start, kwargs.get("dtend"), kwargs)
                return
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

    def _create_occasion(self, title: str, start: Any, end: Any, kwargs: dict[str, Any]) -> None:
        """An occasion from an event "Anlass: …" (template from the title, e.g. "Anlass:
        Grillabend"; date and time of the event; its description as notes)."""
        day = self.manager.today()
        time_text = None
        duration = None
        if isinstance(start, datetime):
            local = dt_util.as_local(start)
            day, time_text = local.date(), local.strftime("%H:%M")
            if isinstance(end, datetime) and end > start:
                duration = (end - start).total_seconds() / 3600
        elif isinstance(start, date):
            day = start
        create_occasion(
            self.manager,
            day=day,
            time_text=time_text,
            title=title,
            duration_h=duration,
            notes=kwargs.get("description"),
        )

    async def async_delete_event(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Remove a meal (uid "<date>_<meal>") or an occasion ("<date>_occasion-<id>")."""
        day_text, _, meal = uid.partition("_")
        if meal.startswith(OCCASION_UID):
            delete_occasion(self.manager, meal[len(OCCASION_UID) :])
            return
        self.manager.remove_meal(date.fromisoformat(day_text), meal or None)
