"""Intents for voice assistants and LLM agents (e.g. "Jarvis").

Every intent registered here is automatically offered as a tool to LLM based
conversation agents that use the Home Assistant "Assist" LLM API – including
the Model Context Protocol server integration. The intent type therefore is a
valid tool name (lower case snake case).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, intent
import voluptuous as vol

from .const import DOMAIN, MEAL_LABELS, MEAL_SNACK
from .dates import describe_date
from .ingredients import strip_article
from .manager import EssensplanerManager, error_message
from .recipe_import import async_fetch_recipe
from .services import (
    async_sync_shopping,
    resolve_day,
    resolve_meal,
    resolve_meals,
    resolve_move,
    split_list,
)

_LOGGER = logging.getLogger(__name__)

INTENT_GET_MEALS = "essensplaner_get_meals"
INTENT_GET_WEEK = "essensplaner_get_week_plan"
INTENT_PLAN_MEAL = "essensplaner_plan_meal"
INTENT_REMOVE_MEAL = "essensplaner_remove_meal"
INTENT_SUGGEST = "essensplaner_suggest_recipes"
INTENT_GET_RECIPE = "essensplaner_get_recipe"
INTENT_SEARCH = "essensplaner_search_recipes"
INTENT_SHOPPING = "essensplaner_create_shopping_list"
INTENT_AUTO_PLAN = "essensplaner_auto_plan"
INTENT_ADD_RECIPE = "essensplaner_add_recipe"
INTENT_IMPORT_RECIPE = "essensplaner_import_recipe"
INTENT_MARK_COOKED = "essensplaner_mark_cooked"
INTENT_COOK_WITH = "essensplaner_cook_with"
INTENT_GET_SHOPPING = "essensplaner_get_shopping_list"
INTENT_MOVE_MEAL = "essensplaner_move_meal"

_DATE_DESC = (
    "Tag/day: 'heute', 'morgen', 'übermorgen', Wochentag wie 'Freitag', "
    "'nächsten Montag', '24.12.' oder ISO 'YYYY-MM-DD'. Standard: heute."
)
_MEAL_DESC = "Mahlzeit/meal: 'Frühstück', 'Mittagessen', 'Abendessen' oder 'Snack'."
_INT_1_14 = vol.All(vol.Coerce(int), vol.Range(min=1, max=14))
_INT_1_30 = vol.All(vol.Coerce(int), vol.Range(min=1, max=30))
_INT_MIN = vol.All(vol.Coerce(int), vol.Range(min=1, max=1440))

_PREPOSITION = {meal: f"zum {label}" for meal, label in MEAL_LABELS.items()}
_PREPOSITION[MEAL_SNACK] = "als Snack"


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _join(items: list[str], last: str = "und") -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} {last} {items[-1]}"


def _get_manager(hass: HomeAssistant) -> EssensplanerManager | None:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    return entries[0].runtime_data if entries else None


class _EssensplanerIntent(intent.IntentHandler):
    """Base class: validates slots, converts errors into spoken answers."""

    platforms = None
    response_type = intent.IntentResponseType.QUERY_ANSWER

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent."""
        hass = intent_obj.hass
        response = intent_obj.create_response()
        manager = _get_manager(hass)
        if manager is None:
            response.async_set_error(
                intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                "Der Essensplaner ist nicht eingerichtet.",
            )
            return response
        slots = self.async_validate_slots(intent_obj.slots)
        values = {
            key: value.get("value")
            for key, value in slots.items()
            if isinstance(value, dict) and value.get("value") not in (None, "")
        }
        try:
            speech, data = await self._async_handle(hass, manager, values)
        except ServiceValidationError as err:
            response.async_set_error(
                intent.IntentResponseErrorCode.FAILED_TO_HANDLE, error_message(err)
            )
            return response
        except HomeAssistantError as err:
            _LOGGER.warning("Essensplaner intent %s failed: %s", self.intent_type, err)
            response.async_set_error(
                intent.IntentResponseErrorCode.FAILED_TO_HANDLE, error_message(err)
            )
            return response
        response.response_type = self.response_type
        response.async_set_speech(speech)
        if data:
            response.async_set_speech_slots(data)
        return response

    async def _async_handle(
        self, hass: HomeAssistant, manager: EssensplanerManager, values: dict[str, Any]
    ) -> tuple[str, dict[str, Any] | None]:
        raise NotImplementedError


class GetMealsIntent(_EssensplanerIntent):
    """What is planned for a day?"""

    intent_type = INTENT_GET_MEALS
    description = (
        "Essensplaner: sagt, welche Mahlzeiten für einen Tag geplant sind "
        "(z. B. 'Was gibt es heute zu essen?', 'Was kochen wir morgen Abend?'). "
        "Returns the planned meals (meal plan) for one day."
    )
    slot_schema = {
        vol.Optional("date", description=_DATE_DESC): cv.string,
        vol.Optional("meal", description=_MEAL_DESC): cv.string,
    }

    async def _async_handle(self, hass, manager, values):
        day, hint = resolve_day(manager, values.get("date"))
        meal = resolve_meal(manager, values.get("meal"), hint, default=False)
        meals = manager.day_meals(day)
        if meal:
            meals = [m for m in meals if m["meal"] == meal]
        when = describe_date(day, manager.today())
        data = {"date": day.isoformat(), "meals": meals}
        if not meals:
            if meal:
                return f"Für {when} {_PREPOSITION[meal]} ist noch nichts geplant.", data
            return f"Für {when} ist noch nichts geplant.", data
        parts = [f"{_PREPOSITION[m['meal']]} {m['title']}" for m in meals]
        return f"{_cap(when)} gibt es {_join(parts)}.", data


class GetWeekPlanIntent(_EssensplanerIntent):
    """Plan for several days."""

    intent_type = INTENT_GET_WEEK
    description = (
        "Essensplaner: liefert den Wochenplan / Essensplan für mehrere Tage "
        "(z. B. 'Was gibt es diese Woche?'). Returns the meal plan for several days."
    )
    slot_schema = {
        vol.Optional("start_date", description=_DATE_DESC): cv.string,
        vol.Optional(
            "days", description="Anzahl Tage/number of days (1-14), Standard 7"
        ): _INT_1_14,
    }

    async def _async_handle(self, hass, manager, values):
        start, _ = resolve_day(manager, values.get("start_date"))
        days = manager.plan_range(start, int(values.get("days", 7)))
        lines = []
        empty = 0
        for day in days:
            if not day["meals"]:
                empty += 1
                continue
            meals = ", ".join(f"{m['meal_label']} {m['title']}" for m in day["meals"])
            lines.append(f"{day['weekday']}: {meals}")
        if not lines:
            return "In diesem Zeitraum ist noch nichts geplant.", {"days": days}
        speech = ". ".join(lines) + "."
        if empty:
            speech += f" An {empty} {'Tag' if empty == 1 else 'Tagen'} ist noch nichts geplant."
        return speech, {"days": days}


class PlanMealIntent(_EssensplanerIntent):
    """Add a dish to the plan."""

    intent_type = INTENT_PLAN_MEAL
    response_type = intent.IntentResponseType.ACTION_DONE
    description = (
        "Essensplaner: plant ein Gericht für einen Tag/eine Mahlzeit ein "
        "(z. B. 'Plane Lasagne für Freitag Abend'). Existiert kein Rezept, wird der "
        "Text als Notiz eingetragen. Adds a dish to the meal plan."
    )
    slot_schema = {
        vol.Required("dish", description="Gericht/Rezeptname, z. B. 'Lasagne'"): cv.string,
        vol.Optional("date", description=_DATE_DESC): cv.string,
        vol.Optional("meal", description=_MEAL_DESC + " Standard: Abendessen"): cv.string,
        vol.Optional("servings", description="Portionen/servings"): _INT_1_30,
    }

    async def _async_handle(self, hass, manager, values):
        day, hint = resolve_day(manager, values.get("date"))
        meal = resolve_meal(manager, values.get("meal"), hint)
        assert meal is not None
        dish = strip_article(str(values["dish"]))
        recipe = manager.find_recipe(dish)
        previous = manager.plan.get(day.isoformat(), {}).get(meal)
        entry = manager.plan_meal(
            day,
            meal,
            recipe=recipe,
            title=None if recipe else dish,
            servings=values.get("servings"),
        )
        when = describe_date(day, manager.today())
        speech = f"Ich habe {entry['title']} für {when} {_PREPOSITION[meal]} eingeplant"
        if previous and previous.get("title") and previous.get("title") != entry["title"]:
            speech += f" (statt {previous['title']})"
        speech += "."
        if recipe is None:
            speech += " Ein passendes Rezept habe ich nicht, deshalb steht es als Notiz im Plan."
        return speech, {"entry": entry, "recipe_found": recipe is not None}


class RemoveMealIntent(_EssensplanerIntent):
    """Remove planned meals."""

    intent_type = INTENT_REMOVE_MEAL
    response_type = intent.IntentResponseType.ACTION_DONE
    description = (
        "Essensplaner: entfernt eine geplante Mahlzeit (oder alle eines Tages, "
        "wenn keine Mahlzeit angegeben ist). Removes meals from the meal plan."
    )
    slot_schema = {
        vol.Optional("date", description=_DATE_DESC): cv.string,
        vol.Optional("meal", description=_MEAL_DESC + " Leer = ganzer Tag"): cv.string,
    }

    async def _async_handle(self, hass, manager, values):
        day, hint = resolve_day(manager, values.get("date"))
        meal = resolve_meal(manager, values.get("meal"), hint, default=False)
        removed = manager.remove_meal(day, meal)
        when = describe_date(day, manager.today())
        if not removed:
            return f"Für {when} war nichts geplant.", {"removed": []}
        titles = _join([r["title"] for r in removed])
        return f"Ich habe {titles} für {when} aus dem Plan entfernt.", {"removed": removed}


class SuggestIntent(_EssensplanerIntent):
    """Suggest recipes."""

    intent_type = INTENT_SUGGEST
    description = (
        "Essensplaner: schlägt Rezepte aus der eigenen Rezeptsammlung vor "
        "('Was soll ich heute kochen?', 'Schlag mir was Vegetarisches vor'). "
        "Bevorzugt Favoriten und lange nicht gekochte Gerichte. Suggests recipes."
    )
    slot_schema = {
        vol.Optional(
            "tag", description="Kategorie/Tag, z. B. 'vegetarisch', 'schnell', 'Pasta'"
        ): cv.string,
        vol.Optional("max_time", description="Maximale Zubereitungszeit in Minuten"): _INT_MIN,
        vol.Optional("meal", description=_MEAL_DESC): cv.string,
        vol.Optional("count", description="Anzahl Vorschläge (Standard 3)"): _INT_1_14,
    }

    async def _async_handle(self, hass, manager, values):
        meal = resolve_meal(manager, values.get("meal"), None, default=False)
        recipes = manager.suggest(
            int(values.get("count", 3)),
            tag=values.get("tag"),
            max_time=values.get("max_time"),
            meal=meal,
        )
        data = {"recipes": [manager.recipe_summary(r) for r in recipes]}
        if not recipes:
            return "Dazu habe ich leider kein passendes Rezept gefunden.", data
        names = [r["name"] for r in recipes]
        if len(names) == 1:
            return f"Wie wäre es mit {names[0]}?", data
        return f"Wie wäre es mit {_join(names, 'oder')}?", data


class GetRecipeIntent(_EssensplanerIntent):
    """Read a recipe."""

    intent_type = INTENT_GET_RECIPE
    description = (
        "Essensplaner: liefert ein Rezept mit Zutaten (auf Portionen umgerechnet) und "
        "Zubereitungsschritten ('Was brauche ich für Lasagne?', 'Wie koche ich ...?'). "
        "Ohne Gericht wird die nächste geplante Mahlzeit genommen. Returns a recipe."
    )
    slot_schema = {
        vol.Optional(
            "dish", description="Gericht/Rezeptname. Leer = nächste geplante Mahlzeit"
        ): cv.string,
        vol.Optional("servings", description="Portionen/servings"): _INT_1_30,
    }

    async def _async_handle(self, hass, manager, values):
        servings = values.get("servings")
        if dish := values.get("dish"):
            recipe = manager.resolve_recipe(name=dish)
        else:
            upcoming = manager.next_meal()
            if not upcoming or not upcoming.get("recipe_id"):
                return "Es ist keine Mahlzeit mit Rezept geplant. Welches Rezept meinst du?", None
            recipe = manager.recipes[upcoming["recipe_id"]]
            servings = servings or upcoming.get("servings")
        view = manager.recipe_view(recipe, servings)
        speech = f"{view['name']} für {view['servings']} Portionen"
        if view.get("total_time"):
            speech += f", etwa {view['total_time']} Minuten"
        speech += ". "
        if view["ingredient_lines"]:
            speech += "Zutaten: " + ", ".join(view["ingredient_lines"]) + ". "
        if view.get("steps"):
            speech += "Zubereitung: " + " ".join(
                f"{n}. {step}" for n, step in enumerate(view["steps"], 1)
            )
        data = {
            key: view.get(key)
            for key in (
                "id",
                "name",
                "servings",
                "ingredient_lines",
                "steps",
                "prep_time",
                "cook_time",
                "total_time",
                "tags",
                "notes",
                "source_url",
            )
        }
        return speech.strip(), data


class SearchRecipesIntent(_EssensplanerIntent):
    """Search the recipe collection."""

    intent_type = INTENT_SEARCH
    description = (
        "Essensplaner: durchsucht die Rezeptsammlung nach Name, Zutat oder Kategorie "
        "('Welche Rezepte mit Hähnchen habe ich?'). Leer = alle Rezepte. Searches recipes."
    )
    slot_schema = {
        vol.Optional("query", description="Suchbegriff (Name oder Zutat)"): cv.string,
        vol.Optional("tag", description="Kategorie/Tag"): cv.string,
        vol.Optional("max_time", description="Maximale Zeit in Minuten"): _INT_MIN,
    }

    async def _async_handle(self, hass, manager, values):
        recipes = manager.search_recipes(
            query=values.get("query"), tag=values.get("tag"), max_time=values.get("max_time")
        )
        data = {
            "count": len(recipes),
            "recipes": [manager.recipe_summary(r) for r in recipes[:50]],
        }
        if not recipes:
            return "Ich habe keine passenden Rezepte gefunden.", data
        names = [r["name"] for r in recipes[:10]]
        speech = f"Ich habe {len(recipes)} {'Rezept' if len(recipes) == 1 else 'Rezepte'} gefunden: {_join(names)}"
        if len(recipes) > 10:
            speech += f" und {len(recipes) - 10} weitere"
        return speech + ".", data


class ShoppingListIntent(_EssensplanerIntent):
    """Generate the shopping list."""

    intent_type = INTENT_SHOPPING
    response_type = intent.IntentResponseType.ACTION_DONE
    description = (
        "Essensplaner: erstellt die Einkaufsliste aus den geplanten Rezepten "
        "(Zutaten werden zusammengefasst und nach Supermarkt-Abteilung sortiert). "
        "Creates the shopping list from the meal plan."
    )
    slot_schema = {
        vol.Optional("start_date", description=_DATE_DESC): cv.string,
        vol.Optional("days", description="Anzahl Tage (Standard 7)"): _INT_1_14,
    }

    async def _async_handle(self, hass, manager, values):
        start, _ = resolve_day(manager, values.get("start_date"))
        days = int(values.get("days", 7))
        result = manager.generate_shopping_list(start, days)
        if manager.sync_entity:
            result["synced_items"] = await async_sync_shopping(
                hass, manager.sync_entity, result["items"]
            )
        if not result["items"]:
            speech = "In diesem Zeitraum sind keine Rezepte mit Zutaten geplant."
        else:
            speech = (
                f"Die Einkaufsliste ist fertig: {len(result['items'])} Artikel "
                f"für {result['meals']} {'Mahlzeit' if result['meals'] == 1 else 'Mahlzeiten'}."
            )
        if result["meals_without_recipe"]:
            speech += " Ohne Rezept: " + _join(result["meals_without_recipe"]) + "."
        return speech, {
            "items": [i["summary"] for i in result["items"]],
            "meals": result["meals"],
        }


class AutoPlanIntent(_EssensplanerIntent):
    """Fill the plan automatically."""

    intent_type = INTENT_AUTO_PLAN
    response_type = intent.IntentResponseType.ACTION_DONE
    description = (
        "Essensplaner: füllt freie Tage im Wochenplan automatisch mit passenden Rezepten "
        "('Plane mir die nächste Woche'). Automatically fills empty slots of the meal plan."
    )
    slot_schema = {
        vol.Optional("start_date", description=_DATE_DESC): cv.string,
        vol.Optional("days", description="Anzahl Tage (Standard 7)"): _INT_1_14,
        vol.Optional(
            "meal", description=_MEAL_DESC + " Mehrere mit Komma, 'alle' = alle"
        ): cv.string,
        vol.Optional(
            "tag", description="Nur Rezepte mit dieser Kategorie, z. B. 'vegetarisch'"
        ): cv.string,
    }

    async def _async_handle(self, hass, manager, values):
        start, _ = resolve_day(manager, values.get("start_date"))
        planned = manager.auto_plan(
            start,
            int(values.get("days", 7)),
            meals=resolve_meals(manager, values.get("meal")),
            tag=values.get("tag"),
        )
        if not planned:
            return (
                "Ich habe nichts eingeplant – entweder ist schon alles geplant oder es "
                "fehlen passende Rezepte.",
                {"planned": []},
            )
        parts = [f"{p['weekday']} {p['title']}" for p in planned]
        return (
            f"Ich habe {len(planned)} {'Mahlzeit' if len(planned) == 1 else 'Mahlzeiten'} eingeplant: {_join(parts)}.",
            {"planned": planned},
        )


class AddRecipeIntent(_EssensplanerIntent):
    """Save a new recipe."""

    intent_type = INTENT_ADD_RECIPE
    response_type = intent.IntentResponseType.ACTION_DONE
    description = (
        "Essensplaner: speichert ein neues Rezept in der Rezeptsammlung. "
        "Zutaten mit Mengen kommasepariert/zeilenweise ('400 g Spaghetti; 1 Zwiebel'). "
        "Saves a new recipe."
    )
    slot_schema = {
        vol.Required("name", description="Name des Rezepts"): cv.string,
        vol.Optional(
            "ingredients", description="Zutaten, getrennt durch ';' oder Zeilenumbruch"
        ): cv.string,
        vol.Optional(
            "steps", description="Zubereitungsschritte, getrennt durch Zeilenumbruch"
        ): cv.string,
        vol.Optional("servings", description="Portionen"): _INT_1_30,
        vol.Optional(
            "tags", description="Kategorien, kommasepariert, z. B. 'vegetarisch, schnell'"
        ): cv.string,
        vol.Optional("total_time", description="Gesamtzeit in Minuten"): _INT_MIN,
    }

    async def _async_handle(self, hass, manager, values):
        data = dict(values)
        if (
            isinstance(data.get("ingredients"), str)
            and ";" not in data["ingredients"]
            and "\n" not in data["ingredients"]
        ):
            data["ingredients"] = data["ingredients"].replace(",", ";")
        recipe = manager.add_recipe(data)
        count = len(recipe["ingredients"])
        return (
            f"Ich habe das Rezept {recipe['name']} mit {count} {'Zutat' if count == 1 else 'Zutaten'} gespeichert.",
            {"recipe": manager.recipe_summary(recipe)},
        )


class ImportRecipeIntent(_EssensplanerIntent):
    """Import a recipe from a website."""

    intent_type = INTENT_IMPORT_RECIPE
    response_type = intent.IntentResponseType.ACTION_DONE
    description = (
        "Essensplaner: importiert ein Rezept von einer Webseite (z. B. Chefkoch-Link) "
        "in die Rezeptsammlung. Imports a recipe from a URL."
    )
    slot_schema = {
        vol.Required("url", description="Internetadresse des Rezepts (https://...)"): cv.string,
    }

    async def _async_handle(self, hass, manager, values):
        data = await async_fetch_recipe(hass, str(values["url"]).strip())
        recipe, created = manager.upsert_imported_recipe(data)
        count = len(recipe["ingredients"])
        verb = "importiert" if created else "aktualisiert"
        return (
            f"Ich habe das Rezept {recipe['name']} mit {count} Zutaten {verb}.",
            {"recipe": manager.recipe_summary(recipe), "created": created},
        )


class MarkCookedIntent(_EssensplanerIntent):
    """Remember that something was cooked."""

    intent_type = INTENT_MARK_COOKED
    response_type = intent.IntentResponseType.ACTION_DONE
    description = (
        "Essensplaner: merkt sich, dass ein Gericht gekocht wurde (verbessert Vorschläge). "
        "Ohne Gericht wird die heutige geplante Mahlzeit genommen. Marks a meal as cooked."
    )
    slot_schema = {
        vol.Optional("dish", description="Gericht/Rezeptname"): cv.string,
        vol.Optional("date", description=_DATE_DESC): cv.string,
        vol.Optional("meal", description=_MEAL_DESC): cv.string,
    }

    async def _async_handle(self, hass, manager, values):
        day, hint = resolve_day(manager, values.get("date"))
        meal = resolve_meal(manager, values.get("meal"), hint, default=False)
        recipe = manager.resolve_recipe(name=values["dish"]) if values.get("dish") else None
        recipe = manager.mark_cooked(recipe, day, meal)
        if recipe is None:
            return "Alles klar, ich habe es als gekocht markiert.", None
        return f"Alles klar, {recipe['name']} ist als gekocht vermerkt.", {
            "recipe": manager.recipe_summary(recipe)
        }


class CookWithIntent(_EssensplanerIntent):
    """What can I cook with what I have?"""

    intent_type = INTENT_COOK_WITH
    description = (
        "Essensplaner: findet Rezepte aus der Sammlung, die vorhandene Zutaten verwenden "
        "('Was kann ich mit Hähnchen, Reis und Paprika kochen?', 'Ich habe noch Zucchini, "
        "was mache ich damit?'). Sagt auch, was noch fehlt. Finds recipes using given ingredients."
    )
    slot_schema = {
        vol.Required(
            "ingredients", description="Vorhandene Zutaten, kommagetrennt (z. B. 'Hähnchen, Reis')"
        ): cv.string,
        vol.Optional("meal", description=_MEAL_DESC): cv.string,
    }

    async def _async_handle(self, hass, manager, values):
        meal = resolve_meal(manager, values.get("meal"), None, default=False)
        wanted = split_list(values["ingredients"])
        results = manager.find_by_ingredients(wanted, 3, meal)
        data = {"recipes": results}
        if not results:
            return f"Mit {_join(wanted)} habe ich leider kein passendes Rezept.", data
        best = results[0]
        speech = f"Mit {_join(best['uses'])} kannst du {best['name']} kochen"
        missing = best["missing"]
        if not missing:
            speech += " – du hast alles da"
        elif len(missing) <= 4:
            speech += f". Dafür fehlt noch: {_join(missing)}"
        else:
            speech += f". Dafür fehlen noch {len(missing)} Zutaten, z. B. {_join(missing[:3])}"
        speech += "."
        if len(results) > 1:
            speech += f" Außerdem würden {_join([r['name'] for r in results[1:]])} passen."
        return speech, data


class GetShoppingListIntent(_EssensplanerIntent):
    """Read the shopping list."""

    intent_type = INTENT_GET_SHOPPING
    description = (
        "Essensplaner: liest die offene Einkaufsliste vor, sortiert nach Supermarkt-Abteilung "
        "('Was steht auf der Einkaufsliste?', 'Was muss ich einkaufen?'). Reads the shopping list."
    )

    async def _async_handle(self, hass, manager, values):
        overview = manager.shopping_overview()
        if not overview["open"]:
            return "Die Einkaufsliste ist leer.", overview
        parts = [
            f"{category.replace('&', 'und')}: {', '.join(items)}"
            for category, items in overview["groups"].items()
        ]
        count = overview["open"]
        speech = (
            f"Auf der Einkaufsliste {'steht' if count == 1 else 'stehen'} {count} "
            f"{'Eintrag' if count == 1 else 'Einträge'}. " + ". ".join(parts) + "."
        )
        return speech, overview


class MoveMealIntent(_EssensplanerIntent):
    """Move (or swap) a planned meal."""

    intent_type = INTENT_MOVE_MEAL
    response_type = intent.IntentResponseType.ACTION_DONE
    description = (
        "Essensplaner: verschiebt eine geplante Mahlzeit auf einen anderen Tag oder eine andere "
        "Mahlzeit; ist das Ziel belegt, werden beide getauscht ('Verschiebe die Lasagne auf "
        "Samstag', 'Leg das Essen von heute auf morgen'). Moves or swaps planned meals."
    )
    slot_schema = {
        vol.Optional("dish", description="Geplantes Gericht, das verschoben wird"): cv.string,
        vol.Optional("from_date", description="Bisheriger Tag. " + _DATE_DESC): cv.string,
        vol.Optional("from_meal", description="Bisherige Mahlzeit. " + _MEAL_DESC): cv.string,
        vol.Required("to_date", description="Neuer Tag. " + _DATE_DESC): cv.string,
        vol.Optional("to_meal", description="Neue Mahlzeit (Standard: wie bisher)"): cv.string,
    }

    async def _async_handle(self, hass, manager, values):
        dish = values.get("dish")
        from_date = values.get("from_date")
        if dish:
            # "das Essen von heute" -> from_date "heute"
            match = re.match(
                r"^(?:das |die )?(?:essen|mahlzeit|gericht)(?: von| vom| für)? (.+)$",
                strip_article(dish),
                re.IGNORECASE,
            )
            if match and not from_date:
                dish, from_date = None, match.group(1)
        src_day, src_meal, dst_day, dst_meal = resolve_move(
            manager,
            dish,
            from_date,
            values.get("from_meal"),
            values["to_date"],
            values.get("to_meal"),
        )
        result = manager.move_meal(src_day, src_meal, dst_day, dst_meal)
        today = manager.today()
        moved = result["moved"]
        speech = (
            f"Ich habe {moved['title']} auf {describe_date(dst_day, today).removeprefix('am ')} "
            f"{_PREPOSITION[dst_meal]} verschoben."
        )
        if swapped := result["swapped"]:
            speech += (
                f" {swapped['title']} gibt es dafür {describe_date(src_day, today)} "
                f"{_PREPOSITION[src_meal]}."
            )
        return speech, result


INTENT_HANDLERS: list[type[_EssensplanerIntent]] = [
    GetMealsIntent,
    GetWeekPlanIntent,
    PlanMealIntent,
    RemoveMealIntent,
    SuggestIntent,
    GetRecipeIntent,
    SearchRecipesIntent,
    ShoppingListIntent,
    AutoPlanIntent,
    AddRecipeIntent,
    ImportRecipeIntent,
    MarkCookedIntent,
    CookWithIntent,
    GetShoppingListIntent,
    MoveMealIntent,
]


def async_register_intents(hass: HomeAssistant) -> None:
    """Register all intents."""
    for handler in INTENT_HANDLERS:
        intent.async_register(hass, handler())


def async_remove_intents(hass: HomeAssistant) -> None:
    """Remove all intents."""
    for handler in INTENT_HANDLERS:
        intent.async_remove(hass, handler.intent_type)
