"""Intents for voice assistants and LLM agents (e.g. "Jarvis").

Every intent registered here is automatically offered as a tool to LLM based
conversation agents that use the Home Assistant "Assist" LLM API – including
the Model Context Protocol server integration. The intent type therefore is a
valid tool name (lower case snake case).
"""

from __future__ import annotations

from datetime import date, timedelta
import logging
import re
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, intent
import voluptuous as vol

from .const import DOMAIN, MEAL_LABELS, MEAL_SNACK, SPLIT_OFF
from .dates import describe_date
from .ingredients import fold, strip_article
from .manager import EssensplanerManager, error_message
from .pricing import format_eur
from .recipe_import import async_fetch_recipe
from .services import (
    async_sync_shopping,
    parse_price,
    resolve_day,
    resolve_meal,
    resolve_meals,
    resolve_move,
    resolve_strategy,
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
INTENT_CLEAR_SHOPPING = "essensplaner_clear_shopping_list"
INTENT_GET_OFFERS = "essensplaner_get_offers"
INTENT_ADD_OFFER = "essensplaner_add_offer"
INTENT_GET_COSTS = "essensplaner_get_costs"
INTENT_COMPARE_PRICES = "essensplaner_compare_prices"
INTENT_SET_SHOPPING_STORE = "essensplaner_set_shopping_store"
INTENT_ADD_SHOPPING_ITEM = "essensplaner_add_shopping_item"

_DATE_DESC = (
    "Tag/day: 'heute', 'morgen', 'übermorgen', Wochentag wie 'Freitag', "
    "'nächsten Montag', '24.12.' oder ISO 'YYYY-MM-DD'. Standard: heute."
)
_MEAL_DESC = "Mahlzeit/meal: 'Frühstück', 'Mittagessen', 'Abendessen' oder 'Snack'."
_INT_1_14 = vol.All(vol.Coerce(int), vol.Range(min=1, max=14))
_INT_1_30 = vol.All(vol.Coerce(int), vol.Range(min=1, max=30))
_INT_MIN = vol.All(vol.Coerce(int), vol.Range(min=1, max=1440))
_STORE_DESC = (
    "Laden/Filiale/store: Supermarkt wie 'Aldi Süd', 'Lidl', 'REWE', eine eigene "
    "Filial-Bezeichnung wie 'Lidl Arbeit' oder 'Hauptladen'."
)

# "Butter bei Lidl Arbeit" -> ("Butter", "Lidl Arbeit")
_AT_BRANCH_RE = re.compile(r"^(.+?)\s+(?:bei|beim)\s+(.+)$", re.IGNORECASE)

_PREPOSITION = {meal: f"zum {label}" for meal, label in MEAL_LABELS.items()}
_PREPOSITION[MEAL_SNACK] = "als Snack"


# symbols that text-to-speech reads badly (error texts are shared with the panel)
_SPEAKABLE = (("≈ ", "ungefähr "), ("≈", "ungefähr "), (" → ", ", dort "), (" & ", " und "))


def _speakable(text: str) -> str:
    """'Essensplaner-Panel → Läden & Preise' -> 'Essensplaner-Panel, dort Läden und Preise'."""
    for symbol, words in _SPEAKABLE:
        text = text.replace(symbol, words)
    return text


class _SpokenError(HomeAssistantError):
    """An answer that is an error for the assistant (its text is spoken as is)."""


def _split_off_reason(manager: EssensplanerManager) -> str:
    """Why the shopping list is not split by store right now."""
    if manager.split_mode == SPLIT_OFF:
        return "Die Aufteilung nach Läden ist in den Optionen ausgeschaltet."
    return (
        "Die Einkaufsliste ist nicht nach Läden aufgeteilt – dafür brauche ich einen "
        "Hauptladen (im Essensplaner-Panel unter „Läden und Preise“)."
    )


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
        except (ServiceValidationError, _SpokenError) as err:
            response.async_set_error(
                intent.IntentResponseErrorCode.FAILED_TO_HANDLE, _speakable(error_message(err))
            )
            return response
        except HomeAssistantError as err:
            _LOGGER.warning("Essensplaner intent %s failed: %s", self.intent_type, err)
            response.async_set_error(
                intent.IntentResponseErrorCode.FAILED_TO_HANDLE, _speakable(error_message(err))
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
        vol.Optional(
            "strategy",
            description="'günstig' (Budget), 'angebote' (aktuelle Angebote nutzen), "
            "'abwechslung' oder 'ausgewogen' (Standard)",
        ): cv.string,
    }

    async def _async_handle(self, hass, manager, values):
        start, _ = resolve_day(manager, values.get("start_date"))
        planned = manager.auto_plan(
            start,
            int(values.get("days", 7)),
            meals=resolve_meals(manager, values.get("meal")),
            tag=values.get("tag"),
            strategy=resolve_strategy(values.get("strategy")),
        )
        if not planned:
            return (
                "Ich habe nichts eingeplant – entweder ist schon alles geplant oder es "
                "fehlen passende Rezepte.",
                {"planned": []},
            )
        parts = [f"{p['weekday']} {p['title']}" for p in planned]
        speech = (
            f"Ich habe {len(planned)} {'Mahlzeit' if len(planned) == 1 else 'Mahlzeiten'} "
            f"eingeplant: {_join(parts)}."
        )
        week = manager.week_overview(start)
        if week["total"]:
            speech += f" Die Woche kostet etwa {format_eur(week['total'])}"
            if week.get("budget"):
                speech += f" bei {format_eur(week['budget'])} Budget"
            speech += "."
        return speech, {"planned": planned, "week": week}


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
    """Read the shopping list (optionally only what to buy at one store)."""

    intent_type = INTENT_GET_SHOPPING
    description = (
        "Essensplaner: liest die offene Einkaufsliste vor, sortiert nach Supermarkt-Abteilung "
        "('Was steht auf der Einkaufsliste?', 'Was muss ich einkaufen?'). Mit Laden nur die "
        "Artikel, die dort gekauft werden ('Was muss ich bei Aldi kaufen?'). "
        "Reads the shopping list, optionally for one store."
    )
    slot_schema = {
        vol.Optional("store", description=_STORE_DESC + " Leer = ganze Liste."): cv.string,
    }

    async def _async_handle(self, hass, manager, values):
        store = values.get("store")
        if store and manager.is_generic_store(store):
            store = None  # "Was muss ich im Supermarkt kaufen?" = the whole list
        overview = manager.shopping_overview()
        if not store:
            return _shopping_speech(overview), overview
        if not manager.store_split_active:
            return f"{_split_off_reason(manager)} {_shopping_speech(overview)}", overview
        try:
            overview["selection"] = manager.store_selection(store)
        except ServiceValidationError as err:
            if err.translation_key != "branch_not_found":
                raise
            # an unknown store: the whole list instead of only an error
            return f"{error_message(err)} {_shopping_speech(overview)}", overview
        return _selection_speech(overview["selection"]), overview


def _shopping_speech(overview: dict[str, Any]) -> str:
    """'Auf der Einkaufsliste stehen 5 Einträge. Obst und Gemüse: …'."""
    if not overview["open"]:
        return "Die Einkaufsliste ist leer."
    parts = [
        f"{category.replace('&', 'und')}: {', '.join(items)}"
        for category, items in overview["groups"].items()
    ]
    count = overview["open"]
    speech = (
        f"Auf der Einkaufsliste {'steht' if count == 1 else 'stehen'} {count} "
        f"{'Eintrag' if count == 1 else 'Einträge'}."
    )
    stores = overview.get("stores") or []
    if stores:
        per_store = [
            f"{g['open']} bei {g['label']}" if g["branch_id"] else f"{g['open']} ohne Laden"
            for g in stores
        ]
        speech += f" Davon {_join(per_store)}."
    return speech + " " + ". ".join(parts) + "."


def _selection_speech(selection: dict[str, Any]) -> str:
    """'Bei Aldi Süd kaufst du 3 Artikel für ungefähr 7,47 €: …'."""
    label = selection["label"]
    count = selection["open"]
    if not count:
        return f"Bei {label} musst du gerade nichts kaufen."
    speech = f"Bei {label} kaufst du {count} Artikel"
    if selection.get("priced"):
        speech += f" für ungefähr {format_eur(selection['subtotal'])}"
    speech += f": {_join(selection['items'])}."
    if selection.get("saving"):
        speech += f" Dort sparst du etwa {format_eur(selection['saving'])}."
    return speech


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


class ClearShoppingListIntent(_EssensplanerIntent):
    """Empty the shopping list."""

    intent_type = INTENT_CLEAR_SHOPPING
    response_type = intent.IntentResponseType.ACTION_DONE
    description = (
        "Essensplaner: leert die Einkaufsliste ('Lösche die Einkaufsliste', 'Entferne die "
        "erledigten Einträge'). Clears the shopping list."
    )
    slot_schema = {
        vol.Optional(
            "mode",
            description="'alle' (Standard), 'erledigte' oder 'geplante' (aus dem Plan erzeugte)",
        ): cv.string,
    }

    async def _async_handle(self, hass, manager, values):
        text = (values.get("mode") or "alle").lower()
        mode = (
            "completed"
            if "erledig" in text or "abgehakt" in text or "completed" in text
            else ("plan" if "plan" in text or "geplant" in text else "all")
        )
        removed = manager.shopping_clear(mode)
        if not removed:
            return "Da gab es nichts zu löschen.", {"removed": 0}
        if mode == "completed":
            return f"Ich habe {removed} erledigte Einträge entfernt.", {"removed": removed}
        return f"Die Einkaufsliste ist jetzt leer ({removed} Einträge entfernt).", {
            "removed": removed
        }


class GetOffersIntent(_EssensplanerIntent):
    """Which supermarket offers are there?"""

    intent_type = INTENT_GET_OFFERS
    description = (
        "Essensplaner: nennt aktuelle oder kommende Supermarkt-Angebote (Aldi, Lidl, Rewe …), "
        "passend zu den eigenen Rezepten ('Welche Angebote gibt es diese Woche?', 'Wo ist "
        "Butter im Angebot?'). Returns supermarket offers."
    )
    slot_schema = {
        vol.Optional("query", description="Produkt/Zutat, z. B. 'Hähnchen'"): cv.string,
        vol.Optional(
            "when", description="'aktuell' (Standard), 'nächste Woche' oder 'alle'"
        ): cv.string,
        vol.Optional("store", description="Supermarkt, z. B. 'Lidl'"): cv.string,
    }

    async def _async_handle(self, hass, manager, values):
        when_text = fold(values.get("when") or "")
        when = (
            "upcoming"
            if "naechst" in when_text or "kommend" in when_text
            else ("all" if "alle" in when_text else "current")
        )
        offers = manager.offers_view(when, values.get("query"), values.get("store"), 50)
        if not offers:
            hint = ""
            if manager.offers_source == "off" and not manager.offers:
                hint = " Online-Angebote sind in den Optionen noch nicht aktiviert."
            return f"Ich habe keine passenden Angebote gefunden.{hint}", {"offers": []}
        top = offers[:5]
        parts = []
        for offer in top:
            until = ""
            if offer.get("valid_to"):
                until = f" bis {describe_date(date.fromisoformat(offer['valid_to'][:10]), manager.today()).removeprefix('am ')}"
            parts.append(
                f"{offer['title']} bei {offer['store']} für {format_eur(offer['price'])}{until}"
            )
        speech = f"Ich habe {len(offers)} Angebote gefunden, zum Beispiel {_join(parts)}."
        compact = [
            {
                k: o.get(k)
                for k in (
                    "title",
                    "store",
                    "price",
                    "old_price",
                    "valid_from",
                    "valid_to",
                    "recipes",
                )
            }
            for o in offers[:20]
        ]
        return speech, {"offers": compact}


class AddOfferIntent(_EssensplanerIntent):
    """Remember an offer seen in a leaflet."""

    intent_type = INTENT_ADD_OFFER
    response_type = intent.IntentResponseType.ACTION_DONE
    description = (
        "Essensplaner: merkt sich ein Supermarkt-Angebot, damit es bei Planung und Einkaufsliste "
        "berücksichtigt wird ('Bei Lidl gibt es Hähnchenbrust für 4,99 Euro das Kilo bis Samstag'). "
        "Saves an offer."
    )
    slot_schema = {
        vol.Required("product", description="Produkt, z. B. 'Hähnchenbrust'"): cv.string,
        vol.Required("store", description="Supermarkt, z. B. 'Lidl'"): cv.string,
        vol.Required("price", description="Preis in Euro, z. B. '4,99'"): cv.string,
        vol.Optional("pack", description="Packungsgröße, z. B. '1 kg' oder '500 g'"): cv.string,
        vol.Optional("valid_to", description="Gültig bis. " + _DATE_DESC): cv.string,
    }

    async def _async_handle(self, hass, manager, values):
        price = parse_price(values["price"])
        valid_to = resolve_day(manager, values["valid_to"])[0] if values.get("valid_to") else None
        offer = manager.add_offer(
            values["product"], values["store"], price, values.get("pack"), None, valid_to
        )
        recipes = manager._recipes_using(offer["keys"])
        speech = (
            f"Ich habe mir {offer['title']} bei {offer['store']} für {format_eur(price)} gemerkt."
        )
        if recipes:
            speech += f" Passt zum Beispiel zu {_join(recipes[:3])}."
        return speech, {"offer": offer, "recipes": recipes[:10]}


class GetCostsIntent(_EssensplanerIntent):
    """Costs of the plan and remaining budget."""

    intent_type = INTENT_GET_COSTS
    description = (
        "Essensplaner: geschätzte Kosten des Essensplans und Restbudget der Woche "
        "('Was kostet der Essensplan diese Woche?', 'Wie viel Budget habe ich noch?'). "
        "Returns plan costs and budget."
    )
    slot_schema = {
        vol.Optional("week", description="'diese' (Standard) oder 'nächste' Woche"): cv.string,
    }

    async def _async_handle(self, hass, manager, values):
        day = manager.today()
        if "naechst" in fold(values.get("week") or "") or "kommend" in fold(
            values.get("week") or ""
        ):
            day += timedelta(days=7)
        week = manager.week_overview(day)
        meals = sum(1 for d in week["days"] for m in d["meals"] if m.get("cost") is not None)
        label = "nächste Woche" if day != manager.today() else "diese Woche"
        if not meals:
            speech = f"Für {label} sind noch keine Rezepte geplant."
        else:
            speech = (
                f"Die {meals} geplanten Mahlzeiten kosten {label} etwa {format_eur(week['total'])}."
            )
            if week.get("savings"):
                speech += f" Durch Angebote sparst du ungefähr {format_eur(week['savings'])}."
        if week.get("budget"):
            remaining = week["remaining"]
            if remaining is not None and remaining < 0:
                speech += f" Das sind {format_eur(-remaining)} über dem Budget von {format_eur(week['budget'])}."
            else:
                speech += f" Vom Budget ({format_eur(week['budget'])}) sind noch {format_eur(remaining)} übrig."
        return speech, week


class ComparePricesIntent(_EssensplanerIntent):
    """Where is a product cheapest?"""

    intent_type = INTENT_COMPARE_PRICES
    description = (
        "Essensplaner: vergleicht den Preis eines Produkts in den gewählten Läden "
        "(eigene Ladenpreise, gelernte Normalpreise, gültige Angebote) "
        "('Wo ist Butter am günstigsten?'). Compares the price of a product across stores."
    )
    slot_schema = {
        vol.Required(
            "item",
            description="Produkt, optional mit Menge, z. B. 'Butter' oder '500 g Hackfleisch'",
        ): cv.string,
    }

    async def _async_handle(self, hass, manager, values):
        result = manager.compare_prices(strip_article(str(values["item"])))
        name = _cap(result["item"])
        results = result["results"]
        if not results:
            return f"Für {name} habe ich keinen Preis.", result
        cheapest = result["cheapest"]
        if cheapest is None:
            # "gibt es" works for "Butter" and "Eier" alike
            first = results[0]
            where = f"bei {first['label']}" if len(results) == 1 else "überall"
            estimate = not any(r["real"] for r in results)
            return (
                f"{name} gibt es {where} für etwa {format_eur(first['price'])}"
                f"{_pack_hint(first, estimate)}.",
                result,
            )
        # without an amount stores are compared per kilo / litre: say it when packs differ
        per_unit = result["compared_by"] == "unit_price" and len({r["pack"] for r in results}) > 1
        speech = (
            f"Am günstigsten gibt es {name} bei {cheapest['label']}: "
            f"{format_eur(cheapest['price'])}{_pack_hint(cheapest, per_unit=per_unit)}"
        )
        if cheapest.get("offer"):
            speech += " im Angebot"
        others = [
            f"bei {r['label']} {format_eur(r['price'])}{_pack_hint(r, per_unit=per_unit)}"
            for r in results
            if r is not cheapest
        ][:3]
        speech += "."
        if others:
            speech += f" {_cap(_join(others))}."
        return speech, result


def _pack_hint(result: dict[str, Any], estimate: bool = False, per_unit: bool = False) -> str:
    """' (250 g)', ' (2 mal 250 g)', ' (250 g, Richtwert)', ' (500 g, 6,98 € pro Kilo)'."""
    parts = []
    if result.get("pack"):
        packs = result.get("packs") or 1
        parts.append(f"{packs} mal {result['pack']}" if packs > 1 else result["pack"])
    if per_unit and (base_price := _base_price(result)):
        parts.append(base_price)
    if estimate:
        parts.append("Richtwert")
    return f" ({', '.join(parts)})" if parts else ""


def _base_price(result: dict[str, Any]) -> str:
    """'6,98 € pro Kilo' / 'pro Liter' / 'pro Stück' (empty without a unit price)."""
    per = result.get("unit_price")
    unit = {"g": "Kilo", "ml": "Liter", "Stück": "Stück"}.get(result.get("base") or "")
    if per is None or unit is None:
        return ""
    return f"{format_eur(per * (1 if unit == 'Stück' else 1000))} pro {unit}"


class SetShoppingStoreIntent(_EssensplanerIntent):
    """Buy an item of the shopping list at another store."""

    intent_type = INTENT_SET_SHOPPING_STORE
    response_type = intent.IntentResponseType.ACTION_DONE
    description = (
        "Essensplaner: legt fest, in welchem Laden ein Artikel der Einkaufsliste gekauft wird "
        "('Kauf die Butter bei REWE', 'Milch kaufe ich immer bei Lidl'). Laden 'automatisch' "
        "setzt die Wahl zurück. Sets the store for a shopping list item."
    )
    slot_schema = {
        vol.Required("item", description="Artikel der Einkaufsliste, z. B. 'Butter'"): cv.string,
        vol.Required(
            "store", description=_STORE_DESC + " 'automatisch' = wieder automatisch wählen."
        ): cv.string,
        vol.Optional(
            "always",
            description=(
                "true = für dieses Produkt immer diesen Laden nehmen (auch wenn es gerade "
                "nicht auf der Einkaufsliste steht)"
            ),
        ): cv.boolean,
    }

    async def _async_handle(self, hass, manager, values):
        always = bool(values.get("always", False))
        if not manager.store_split_active:
            raise _SpokenError(_split_off_reason(manager))
        item = manager.set_shopping_store(
            strip_article(str(values["item"])), str(values["store"]), always
        )
        name = _cap(manager._item_name(item))
        label = item.get("store_label") or ""
        if item.get("preference_only"):
            # "Kaffee kaufe ich immer bei Lidl" – not on the list right now
            if label:
                return f"Okay, {name} kaufst du ab jetzt immer bei {label}.", {"item": item}
            return f"Okay, für {name} merke ich mir keinen Laden mehr.", {"item": item}
        if item.get("store_override"):
            speech = f"Okay, {name} kaufst du bei {label}"
        else:
            speech = f"Okay, für {name} wähle ich den Laden wieder automatisch: {label}"
        if item.get("price") is not None:
            speech += f" (etwa {format_eur(item['price'])})"
        speech += "."
        if always and item.get("store_override"):
            speech += " Das merke ich mir auch für die nächsten Einkäufe."
        return speech, {"item": item}


class AddShoppingItemIntent(_EssensplanerIntent):
    """Put an article on the Essensplaner shopping list (with store and price)."""

    intent_type = INTENT_ADD_SHOPPING_ITEM
    response_type = intent.IntentResponseType.ACTION_DONE
    description = (
        "Essensplaner: setzt einen Artikel auf die Einkaufsliste – mit Preis aus dem Hauptladen "
        "bzw. dem genannten Laden ('Setz Butter auf die Einkaufsliste', '2 Liter Milch auf die "
        "Einkaufsliste'). Adds an item to the shopping list with store and price."
    )
    slot_schema = {
        vol.Required(
            "item", description="Artikel, optional mit Menge, z. B. 'Butter' oder '2 l Milch'"
        ): cv.string,
        vol.Optional("store", description=_STORE_DESC + " Leer = automatisch."): cv.string,
    }

    async def _async_handle(self, hass, manager, values):
        text, store = strip_article(str(values["item"])), values.get("store") or None
        # "Butter bei Lidl Arbeit": an own branch label at the end is the store
        if (
            store is None
            and (match := _AT_BRANCH_RE.match(text))
            and not manager.is_generic_store(match[2])
            and manager.resolve_branch(match[2])
        ):
            text, store = match[1].strip(), match[2].strip()
        item = manager.shopping_add(text, store=store)
        speech = f"Ich habe {item['summary']} auf die Einkaufsliste gesetzt"
        price = item.get("price")
        if item.get("store_label") and price is not None:
            speech += f" – bei {item['store_label']} etwa {format_eur(price)}"
        elif item.get("store_label"):
            speech += f" – zu kaufen bei {item['store_label']}"
        elif price is not None:
            speech += f" (etwa {format_eur(price)})"
        speech += "."
        if offer := item.get("offer"):
            speech += (
                f" Gerade im Angebot bei {offer.get('store')} für {format_eur(offer.get('price'))}."
            )
        return speech, {"item": item}


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
    ClearShoppingListIntent,
    GetOffersIntent,
    AddOfferIntent,
    GetCostsIntent,
    ComparePricesIntent,
    SetShoppingStoreIntent,
    AddShoppingItemIntent,
]


def async_register_intents(hass: HomeAssistant) -> None:
    """Register all intents."""
    for handler in INTENT_HANDLERS:
        intent.async_register(hass, handler())


def async_remove_intents(hass: HomeAssistant) -> None:
    """Remove all intents."""
    for handler in INTENT_HANDLERS:
        intent.async_remove(hass, handler.intent_type)
