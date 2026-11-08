"""Sensors of the Essensplaner integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .dates import WEEKDAY_NAMES
from .entity import EssensplanerEntity
from .manager import EssensplanerManager
from .occasions import (
    COURSE_LABELS,
    COURSES,
    next_occasion,
    occasion_cost,
    occasion_date,
    occasions_on,
    template_info,
)

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
            NextOccasionSensor(manager),
            WeekPlanSensor(manager),
            RecipesSensor(manager),
            WeekCostSensor(manager),
            BudgetRemainingSensor(manager),
            OffersSensor(manager),
            ShoppingStoresSensor(manager),
            ShoppingTotalSensor(manager),
        ]
    )


class DaySensor(EssensplanerEntity, SensorEntity):
    """Meals planned for today / tomorrow."""

    _attr_icon = "mdi:silverware-fork-knife"
    _unrecorded_attributes = frozenset({"meals", "occasions"})

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
    def entity_picture(self) -> str | None:
        """Image of the main meal (dinner first)."""
        meals = sorted(self._meals, key=lambda m: m["meal"] != self.manager.default_meal)
        return next((m["image"] for m in meals if m.get("image")), None)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Per meal details."""
        day = self.manager.today() + timedelta(days=self._offset)
        meals = self._meals
        attrs: dict[str, Any] = {
            "date": day.isoformat(),
            "weekday": WEEKDAY_NAMES[day.weekday()],
            "meals": meals,
            # 1.5: occasions of the day ("🎬 Filmabend")
            "occasions": [
                {
                    "id": o["id"],
                    "title": o["title"],
                    "emoji": template_info(o.get("template"))["emoji"],
                    "time": o.get("time"),
                    "guests": o.get("guests"),
                    "children": o.get("children"),
                }
                for o in occasions_on(self.manager, day)
            ],
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
            # 1.5.1: what is cooked (with the leftovers for another day)
            servings = upcoming.get("cook_servings") or upcoming.get("servings")
            view = self.manager.recipe_view(recipe, servings)
            attrs["ingredients"] = view["ingredient_lines"]
            attrs["steps"] = view.get("steps", [])
            attrs["source_url"] = recipe.get("source_url") or None
        return attrs


class NextOccasionSensor(EssensplanerEntity, SensorEntity):
    """The next (or running) occasion ("Nächster Anlass", 1.5)."""

    _attr_icon = "mdi:party-popper"
    _unrecorded_attributes = frozenset({"courses", "notes"})

    def __init__(self, manager: EssensplanerManager) -> None:
        """Initialize the sensor."""
        super().__init__(manager, "next_occasion")

    @property
    def native_value(self) -> str | None:
        """Title of the next occasion (None without one)."""
        occasion = next_occasion(self.manager)
        return _truncate(occasion["title"]) if occasion else None

    @property
    def entity_picture(self) -> str | None:
        """Image of its main dish."""
        occasion = next_occasion(self.manager)
        for item in (occasion or {}).get("items") or []:
            recipe = self.manager.recipes.get(item.get("recipe_id") or "")
            if recipe and recipe.get("image") and item.get("course") == "main":
                return str(recipe["image"])
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Date, time, guests, courses and the estimated cost."""
        occasion = next_occasion(self.manager)
        if occasion is None:
            return {}
        day = occasion_date(occasion)
        info = template_info(occasion.get("template"))
        courses = {
            COURSE_LABELS[course]: [
                str(i.get("title"))
                for i in occasion.get("items") or []
                if i.get("course") == course and i.get("title")
            ]
            for course in COURSES
        }
        return {
            "id": occasion["id"],
            "date": day.isoformat(),
            "weekday": WEEKDAY_NAMES[day.weekday()],
            "time": occasion.get("time"),
            "days_until": (day - self.manager.today()).days,
            "template": occasion.get("template"),
            "emoji": info["emoji"],
            "guests": occasion.get("guests"),
            "children": occasion.get("children"),
            "courses": {label: titles for label, titles in courses.items() if titles},
            "cost": occasion_cost(self.manager, occasion)["total"],
            "notes": occasion.get("notes") or None,
            "estimate": True,
        }


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


class WeekCostSensor(EssensplanerEntity, SensorEntity):
    """Estimated cost of this week's meal plan (Mon–Sun)."""

    _attr_icon = "mdi:cash-multiple"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "EUR"
    _attr_suggested_display_precision = 2
    _unrecorded_attributes = frozenset({"days", "next_week"})

    def __init__(self, manager: EssensplanerManager) -> None:
        """Initialize the sensor."""
        super().__init__(manager, "week_cost")

    @property
    def native_value(self) -> float:
        """Estimated cost in EUR."""
        return self.manager.week_overview()["total"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Budget and per-day costs."""
        week = self.manager.week_overview()
        next_week = self.manager.week_overview(self.manager.today() + timedelta(days=7))
        return {
            "budget": week["budget"],
            "remaining": week["remaining"],
            "over_budget": week["over_budget"],
            "savings_by_offers": week["savings"],
            "week_start": week["start"],
            "days": {d["date"]: d["total"] for d in week["days"]},
            "next_week": next_week["total"],
            "estimate": True,
        }


class BudgetRemainingSensor(EssensplanerEntity, SensorEntity):
    """Remaining weekly budget."""

    _attr_icon = "mdi:piggy-bank-outline"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "EUR"
    _attr_suggested_display_precision = 2

    def __init__(self, manager: EssensplanerManager) -> None:
        """Initialize the sensor."""
        super().__init__(manager, "budget_remaining")

    @property
    def native_value(self) -> float | None:
        """Budget minus planned costs (None without budget)."""
        return self.manager.week_overview()["remaining"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The budget."""
        return {"budget": self.manager.weekly_budget}


class OffersSensor(EssensplanerEntity, SensorEntity):
    """Current supermarket offers that fit the recipes."""

    _attr_icon = "mdi:sale"
    _attr_native_unit_of_measurement = "Angebote"
    _unrecorded_attributes = frozenset({"offers", "upcoming"})

    def __init__(self, manager: EssensplanerManager) -> None:
        """Initialize the sensor."""
        super().__init__(manager, "offers")

    @property
    def native_value(self) -> int:
        """Number of current offers that are used in recipes."""
        return sum(1 for o in self.manager.offers_view("current") if o["recipe_count"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Top offers."""

        def compact(offer: dict[str, Any]) -> dict[str, Any]:
            return {
                "title": offer.get("title"),
                "store": offer.get("store"),
                "price": offer.get("price"),
                "old_price": offer.get("old_price"),
                "discount": offer.get("discount"),
                "valid_to": offer.get("valid_to"),
                "recipes": offer.get("recipes", [])[:3],
            }

        current = [o for o in self.manager.offers_view("current") if o["recipe_count"]]
        upcoming = [o for o in self.manager.offers_view("upcoming") if o["recipe_count"]]
        meta = self.manager.offers_meta
        return {
            "offers": [compact(o) for o in current[:25]],
            "upcoming": [compact(o) for o in upcoming[:15]],
            "upcoming_count": len(upcoming),
            "source": self.manager.offers_source,
            "last_update": meta.get("last_update"),
            "status": meta.get("status"),
        }


class ShoppingStoresSensor(EssensplanerEntity, SensorEntity):
    """Number of stores with open shopping items ("Hauptladen + Ausnahmen")."""

    _attr_icon = "mdi:store-outline"
    _attr_native_unit_of_measurement = "Läden"
    _unrecorded_attributes = frozenset({"stores"})

    def __init__(self, manager: EssensplanerManager) -> None:
        """Initialize the sensor."""
        super().__init__(manager, "shopping_stores")

    @property
    def native_value(self) -> int:
        """Stores with open items (0 while the list is not split by store)."""
        return sum(1 for group in self.manager.stores_summary() if group["branch_id"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Open items, subtotal and saving per store."""
        groups = self.manager.stores_summary()
        main = self.manager.get_main_branch()
        return {
            "split_active": self.manager.store_split_active,
            "main_store": self.manager.branch_label(main) if main else None,
            "without_store": sum(g["open"] for g in groups if not g["branch_id"]),
            "stores": [
                {
                    "label": g["label"],
                    "retailer": g["retailer"],
                    "branch_id": g["branch_id"],
                    "main": g["main"],
                    "open": g["open"],
                    "subtotal": g["subtotal"],
                    "saving": g["saving"],
                    "items": g["items"][:50],
                }
                for g in groups
            ],
        }


class ShoppingTotalSensor(EssensplanerEntity, SensorEntity):
    """Estimated total of the open shopping items."""

    _attr_icon = "mdi:cart-variant"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "EUR"
    _attr_suggested_display_precision = 2

    def __init__(self, manager: EssensplanerManager) -> None:
        """Initialize the sensor."""
        super().__init__(manager, "shopping_total")

    @property
    def native_value(self) -> float:
        """Sum of the estimated prices of the open items in EUR."""
        return self.manager.shopping_overview()["estimated_total"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Item counts and savings."""
        overview = self.manager.shopping_overview()
        return {
            "open": overview["open"],
            "priced_items": overview["priced_items"],
            "unpriced_items": overview["open"] - overview["priced_items"],
            "offers": len(overview["offers"]),
            "saving_by_stores": round(sum(g["saving"] for g in overview["stores"]), 2),
            "estimate": True,
        }
