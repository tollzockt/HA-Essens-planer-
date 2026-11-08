"""Intents for voice assistants and LLM agents (e.g. "Jarvis").

Every intent registered here is automatically offered as a tool to LLM based
conversation agents that use the Home Assistant "Assist" LLM API – including
the Model Context Protocol server integration. The intent type therefore is a
valid tool name (lower case snake case).
"""

from __future__ import annotations

import contextlib
from datetime import date, timedelta
import logging
import re
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, intent
import voluptuous as vol

from .ai import AI_ACTIVE, AI_REFUSED_DE
from .const import DOMAIN, MEAL_LABELS, MEAL_SNACK, SPLIT_OFF
from .dates import describe_date
from .ingredients import fold, strip_article
from .manager import EssensplanerManager, error_message
from .offers import parse_pack_text, split_pack
from .pricing import format_eur, pack_text
from .recipe_import import async_fetch_recipe
from .retailers import retailer_name
from .services import (
    async_sync_shopping,
    parse_price,
    resolve_day,
    resolve_leftover,
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
INTENT_SET_PRICE = "essensplaner_set_price"
INTENT_PLAN_OCCASION = "essensplaner_plan_occasion"
INTENT_GET_OCCASION = "essensplaner_get_occasion"
INTENT_EDIT_OCCASION = "essensplaner_edit_occasion"
INTENT_SUGGEST_DRINKS = "essensplaner_suggest_drinks"
INTENT_GET_SEASON = "essensplaner_get_season"
INTENT_PLAN_LEFTOVER = "essensplaner_plan_leftover"

_DATE_DESC = (
    "Tag/day: 'heute', 'morgen', 'übermorgen', Wochentag wie 'Freitag', "
    "'nächsten Montag', '24.12.' oder ISO 'YYYY-MM-DD'. Standard: heute."
)
_MEAL_DESC = "Mahlzeit/meal: 'Frühstück', 'Mittagessen', 'Abendessen' oder 'Snack'."
_INT_1_14 = vol.All(vol.Coerce(int), vol.Range(min=1, max=14))
_INT_1_30 = vol.All(vol.Coerce(int), vol.Range(min=1, max=30))
_INT_MIN = vol.All(vol.Coerce(int), vol.Range(min=1, max=1440))
_OCCASION_DESC = (
    "Anlass/occasion: Vorlage wie 'Filmabend', 'Grillabend', 'Familienessen', "
    "'Weihnachtsessen', 'Silvester', 'Geburtstag', 'Brunch', 'Raclette', 'Fondue', 'Party', "
    "'Osteressen' oder der Name eines geplanten Anlasses."
)
_HOLIDAY_DATE_DESC = (
    _DATE_DESC + " Auch Feiertage: 'Heiligabend', 'Weihnachten', 'Silvester', 'Ostern'."
)
_STORE_DESC = (
    "Laden/Filiale/store: Supermarkt wie 'Aldi Süd', 'Lidl', 'REWE', Drogerie wie "
    "'Rossmann' oder 'dm', eine eigene "
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


class _NotThisIntent(_SpokenError):
    """A sentence of the built-in agent that is no command of this intent after all (a
    question caught by a wildcard): with "prefer handling commands locally" the
    conversation agent (LLM) answers it; a tool call gets the spoken error."""


def _split_off_reason(manager: EssensplanerManager) -> str:
    """Why the shopping list is not split by store right now."""
    if manager.split_mode == SPLIT_OFF:
        return (
            "Die Aufteilung nach Läden ist ausgeschaltet (im Essensplaner-Panel unter "
            "Einstellungen, Läden und Einkauf)."
        )
    return (
        "Die Einkaufsliste ist nicht nach Läden aufgeteilt – dafür brauche ich einen "
        "Hauptladen (im Essensplaner-Panel unter „Läden und Preise“)."
    )


def _spoken_title(view: dict[str, Any]) -> str:
    """A plan entry for speech: 'Reste von Dienstag (Lasagne)' without the emoji."""
    return str(view.get("title") or "").removeprefix("🍲 ")


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
        if AI_ACTIVE.get():
            # a conversation agent answering an Essensplaner AI request calls a tool: it
            # would ask the Essensplaner (and so itself) again – refuse (1.5)
            response.async_set_error(intent.IntentResponseErrorCode.FAILED_TO_HANDLE, AI_REFUSED_DE)
            return response
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
        except _NotThisIntent as err:
            if intent_obj.platform == "conversation":  # a sentence of the built-in agent
                raise intent.MatchFailedError(
                    result=intent.MatchTargetsResult(False, intent.MatchFailedReason.NAME),
                    constraints=intent.MatchTargetsConstraints(),
                ) from err
            response.async_set_error(
                intent.IntentResponseErrorCode.FAILED_TO_HANDLE, _speakable(str(err))
            )
            return response
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
        parts = [f"{_PREPOSITION[m['meal']]} {_spoken_title(m)}" for m in meals]
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
            meals = ", ".join(f"{m['meal_label']} {_spoken_title(m)}" for m in day["meals"])
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
        if added := entry.get("added_as_extra"):
            # 1.5.1: a side, sauce, drink or dessert joins the planned meal
            speech = (
                f"Ich habe {added} zu {_spoken_title(entry)} für {when} "
                f"{_PREPOSITION[meal]} dazugeplant."
            )
            return speech, {"entry": entry, "recipe_found": True}
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
        titles = _join([_spoken_title(r) for r in removed])
        speech = f"Ich habe {titles} für {when} aus dem Plan entfernt."
        for view in (v for r in removed for v in r.get("leftovers_unlinked") or []):
            # 1.5.1: its leftovers are a meal of their own day now
            other = describe_date(date.fromisoformat(view["date"]), manager.today())
            speech += f" {_cap(other)} wird {view['dish']} jetzt frisch gekocht."
        return speech, {"removed": removed}


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
        groups = result.get("stores") or []
        stores = [{k: g.get(k) for k in ("label", "open", "subtotal", "saving")} for g in groups]
        if result["items"] and len(groups) > 1:
            # "Hauptladen + Ausnahmen": where to shop (the whole open list)
            per_store = [
                f"{g['open']} bei {g['label']}" if g["branch_id"] else f"{g['open']} ohne Laden"
                for g in groups
            ]
            speech += f" Nach Laden: {_join(per_store)}"
            saving = round(sum(g["saving"] or 0 for g in stores), 2)
            if saving > 0:
                speech += f" – das spart etwa {format_eur(saving)}"
            speech += "."
        if result["meals_without_recipe"]:
            speech += " Ohne Rezept: " + _join(result["meals_without_recipe"]) + "."
        data: dict[str, Any] = {
            "items": [i["summary"] for i in result["items"]],
            "meals": result["meals"],
        }
        if stores:
            data["stores"] = stores
        return speech, data


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
            "'abwechslung', 'saisonal' (was gerade Saison hat) oder 'ausgewogen' (Standard)",
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
            f"Ich habe {_spoken_title(moved)} auf "
            f"{describe_date(dst_day, today).removeprefix('am ')} "
            f"{_PREPOSITION[dst_meal]} verschoben."
        )
        if swapped := result["swapped"]:
            speech += (
                f" {_spoken_title(swapped)} gibt es dafür {describe_date(src_day, today)} "
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
        "Essensplaner: nennt aktuelle oder kommende Angebote der eigenen Läden – Supermärkte "
        "und Drogerien (Aldi, Lidl, Rewe, Rossmann, dm …): ohne Laden und Produkt die zu den "
        "eigenen Rezepten passenden, mit Laden oder Produkt alle Angebote des Prospekts "
        "('Welche Angebote gibt es diese Woche?', 'Was hat Rossmann im Angebot?', 'Wo ist "
        "Butter im Angebot?', 'Was gibt es in der Drogerie im Angebot?'). Returns offers."
    )
    slot_schema = {
        vol.Optional("query", description="Produkt/Zutat, z. B. 'Hähnchen'"): cv.string,
        vol.Optional(
            "when", description="'aktuell' (Standard), 'nächste Woche' oder 'alle'"
        ): cv.string,
        vol.Optional("store", description=_STORE_DESC): cv.string,
    }

    async def _async_handle(self, hass, manager, values):
        when_text = fold(values.get("when") or "")
        when = (
            "upcoming"
            if "naechst" in when_text or "kommend" in when_text
            else ("all" if "alle" in when_text else "current")
        )
        query, store = values.get("query"), values.get("store")
        # "Butter bei Lidl Arbeit" (one wildcard of the sentence file): the store at the end
        if (
            query
            and not store
            and (match := _AT_BRANCH_RE.match(str(query)))
            and not manager.is_generic_store(match[2])
            and (manager.resolve_branch(match[2]) or manager.resolve_store(match[2]))
        ):
            query, store = match[1].strip(), match[2].strip()
        offers = manager.offers_view(when, query, store, 50)
        if store or query or not offers:
            # 1.4: every offer of the saved stores' leaflets (also drugstores and products
            # not planned), after the offers matching the recipes
            offers = _merge_offers(offers, _catalog_offers(manager, when, query, store))
        prefix = ""
        if not offers and when == "current":
            # nothing yet, the new week starts soon ("Was hat Rossmann im Angebot?" on Sunday)
            offers = _merge_offers(
                manager.offers_view("upcoming", query, store, 50),
                _catalog_offers(manager, "upcoming", query, store),
            )
            if offers:
                start = min(str(o.get("valid_from") or "")[:10] for o in offers)
                with contextlib.suppress(ValueError):
                    prefix = (
                        "Gerade nicht, aber "
                        f"{describe_date(date.fromisoformat(start), manager.today())} "
                    )
        if not offers:
            return (
                f"Ich habe keine passenden Angebote gefunden.{_offers_hint(manager, store)}",
                {"offers": []},
            )
        top = offers[:5]
        parts = []
        for offer in top:
            until = ""
            if offer.get("valid_to"):
                until = f" bis {describe_date(date.fromisoformat(offer['valid_to'][:10]), manager.today()).removeprefix('am ')}"
            title = offer.get("title") or offer.get("product") or ""
            parts.append(
                f"{title} bei {offer.get('store') or ''} für {format_eur(offer['price'])}{until}"
            )
        count = "ein Angebot" if len(offers) == 1 else f"{len(offers)} Angebote"
        head = f"{prefix}gibt es {count}" if prefix else f"Ich habe {count} gefunden"
        listed = _join(parts)
        end = "" if listed.endswith(".") else "."  # "bis Freitag, 13.11."
        speech = f"{head}{':' if len(offers) == 1 else ', zum Beispiel'} {listed}{end}"
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


def _catalog_offers(
    manager: EssensplanerManager, when: str, query: str | None, store: str | None
) -> list[dict[str, Any]]:
    """Offers of the offer catalog (all offers of the saved stores) for a store and / or
    product question; a store that names no saved branch: its chain's offers."""
    from .catalog import store_offers_view  # the catalog imports the manager

    branch_ids: list[str] | None = None
    retailer: str | None = None
    if store and not manager.is_generic_store(store):
        branches = manager._match_branches(store)
        branch_ids = [b["id"] for b in branches if b.get("id")]
        if not branch_ids:
            retailer = manager.resolve_store(store)
            if retailer is None:
                return []
            branch_ids = None
    # a product question asks for the product itself, not for any text containing it
    view = store_offers_view(
        manager,
        branch_ids=branch_ids,
        when=when,
        query=query,
        limit=200,
        sort="saving",
        match="key",
    )
    return [
        o
        for o in view["offers"]
        if not o.get("online_only") and (retailer is None or o.get("retailer") == retailer)
    ]


def _merge_offers(
    first: list[dict[str, Any]], second: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """first, then the offers of second that are not in it (same id)."""
    ids = {o.get("id") for o in first if o.get("id")}
    return [*first, *(o for o in second if not o.get("id") or o["id"] not in ids)]


def _store_hints(manager: EssensplanerManager, store: str | None) -> list[str]:
    """Hints for an asked store without offers: only leaflet pages as images (NORMA, EDEKA
    via marktguru), EDEKA's own offers switched off."""
    from .catalog import store_offers_view  # the catalog imports the manager
    from .edeka import edeka_enabled

    if not store or manager.is_generic_store(store):
        return []
    branches = manager._match_branches(store)
    if not branches and (retailer := manager.resolve_store(store)):
        branches = [b for b in manager.selected_branches() if b.get("retailer") == retailer]
    ids = {b.get("id") for b in branches if b.get("id")}
    if not ids:
        return []
    hints = []
    stores = [s for s in store_offers_view(manager, limit=1)["stores"] if s["branch_id"] in ids]
    leaflets = list(dict.fromkeys(s["store"] for s in stores if s.get("leaflet_only")))
    if leaflets:
        names = _join(leaflets)
        hints.append(
            f"Für {names} gibt es nur den Prospekt als Bilder – im Essensplaner-Panel unter "
            "Angebote, Alle Angebote meiner Läden."
        )
    if any(b.get("retailer") == "edeka" for b in branches) and not edeka_enabled(manager):
        hints.append(
            "Mit „EDEKA-Angebote“ in den Einstellungen bekomme ich die einzelnen Angebote "
            "deines Markts."
        )
    return hints


def _offers_hint(manager: EssensplanerManager, store: str | None = None) -> str:
    """Why no offer may be known: no source on, the EDEKA market not linked, nothing
    fetched yet; for an asked store: only leaflet images, EDEKA's offers off."""
    from .catalog import catalog_enabled, catalog_status  # the catalog imports the manager
    from .edeka import edeka_enabled, edeka_markets

    if not catalog_enabled(manager):
        if manager.offers:
            return ""
        return (
            " Online-Angebote sind nicht eingeschaltet (im Essensplaner-Panel unter "
            "Einstellungen, Angebote und Preisquellen)."
        )
    hints = []
    if (
        edeka_enabled(manager)
        and any(b.get("retailer") == "edeka" for b in manager.selected_branches())
        and not edeka_markets(manager)
    ):
        hints.append(
            "Für EDEKA-Angebote fehlt noch die Markt-ID (im Essensplaner-Panel unter Läden "
            "und Preise, EDEKA-Markt suchen)."
        )
    if catalog_status(manager) == "pending":
        hints.append("Die Angebote wurden noch nicht abgerufen.")
    else:
        hints.extend(h for h in _store_hints(manager, store) if h not in hints)
    return "".join(f" {h}" for h in hints)


class AddOfferIntent(_EssensplanerIntent):
    """Remember an offer seen in a leaflet."""

    intent_type = INTENT_ADD_OFFER
    response_type = intent.IntentResponseType.ACTION_DONE
    description = (
        "Essensplaner: merkt sich ein befristetes Supermarkt-Angebot (Prospekt, gilt bis zum "
        "angegebenen Tag, sonst bis Samstag), damit es bei Planung und Einkaufsliste "
        "berücksichtigt wird ('Bei Lidl gibt es Hähnchenbrust für 4,99 Euro das Kilo bis Samstag'). "
        "Für den normalen (dauerhaften) Preis eines Ladens essensplaner_set_price verwenden. "
        "Saves a limited-time offer."
    )
    slot_schema = {
        vol.Required("product", description="Produkt, z. B. 'Hähnchenbrust'"): cv.string,
        vol.Required("store", description=_STORE_DESC): cv.string,
        vol.Required("price", description="Preis in Euro, z. B. '4,99'"): cv.string,
        vol.Optional("pack", description="Packungsgröße, z. B. '1 kg' oder '500 g'"): cv.string,
        vol.Optional(
            "valid_to",
            description="Gültig bis (ohne Angabe: bis zum kommenden Samstag). " + _DATE_DESC,
        ): cv.string,
    }

    async def _async_handle(self, hass, manager, values):
        price = parse_price(values["price"])
        valid_to = resolve_day(manager, values["valid_to"])[0] if values.get("valid_to") else None
        offer = manager.add_offer(
            values["product"], values["store"], price, values.get("pack"), None, valid_to
        )
        recipes = manager._recipes_using(offer["keys"])
        # an offer of one branch ("Hauptladen", "Lidl Arbeit"): named like the branch
        store = manager.branch_label(manager.get_branch(offer.get("branch_id"))) or offer["store"]
        speech = f"Ich habe mir {offer['title']} bei {store} für {format_eur(price)} gemerkt"
        if offer.get("valid_to"):
            # without "bis …" it ends with the leaflet week (the coming Saturday): say so
            end = date.fromisoformat(offer["valid_to"][:10])
            speech += f", gültig bis {describe_date(end, manager.today()).removeprefix('am ')}"
        speech += "."
        if recipes:
            speech += f" Passt zum Beispiel zu {_join(recipes[:3])}."
        return speech, {"offer": offer, "recipes": recipes[:10]}


# "1 Euro 79", "1 € 79" (speech recognition) -> "1,79"; "99 Cent" -> "0,99"
_EURO_CENT_RE = re.compile(r"^\s*(\d+)\s*(?:euro|€|eur)\s*(\d{1,2})\s*(?:cent)?\s*$", re.I)
_CENT_RE = re.compile(r"^\s*(\d{1,2})\s*cent\s*$", re.I)


def _spoken_price(text: str) -> str:
    """A price as spoken ("1 Euro 79", "99 Cent") in the form parse_price() reads."""
    if match := _EURO_CENT_RE.match(text):
        return f"{match[1]},{int(match[2]):02d}"
    if match := _CENT_RE.match(text):
        return f"0,{int(match[1]):02d}"
    return text


# a price ("1,79", "1.79 €", "2 Euro", "1,79 € für 250 g"), not an amount ("1 kg
# Hackfleisch", "500 g Paket Kaffee") or a product ("die Butter")
_PRICE_TEXT_RE = re.compile(
    r"^\s*(?:€\s*)?\d+(?:[.,]\d{1,2})?(?!\d)(?!\s*(?:-\s*)?(?:kg|g|mg|ml|l|cl|liter|stück|stueck"
    r"|stk|st|x|er|prozent|%)(?:\b|$))",
    re.IGNORECASE,
)
# a question that the sentence "{product} kostet bei {store} {price}" may catch: "Was kostet
# bei Lidl 1 kg Hackfleisch?", "Wie viel kostet beim Lidl …"
_QUESTION_WORDS = frozenset(
    {"was", "wie", "wieviel", "welche", "welcher", "welches", "wo", "wer", "warum", "wann"}
)


class SetPriceIntent(_EssensplanerIntent):
    """Remember the regular price of a product at a store (an own store price)."""

    intent_type = INTENT_SET_PRICE
    response_type = intent.IntentResponseType.ACTION_DONE
    description = (
        "Essensplaner: merkt sich den Normalpreis (dauerhaft) eines Produkts in einem Laden "
        "als eigenen Preis dieses Ladens ('Butter kostet bei Netto 1,79 Euro', 'Merk dir: "
        "Milch kostet bei Lidl 99 Cent'). Für befristete Prospekt-Angebote "
        "essensplaner_add_offer verwenden. Saves a store's regular price."
    )
    slot_schema = {
        vol.Required("product", description="Produkt, z. B. 'Butter'"): cv.string,
        vol.Required("store", description=_STORE_DESC): cv.string,
        vol.Required("price", description="Preis in Euro, z. B. '1,79'"): cv.string,
        vol.Optional(
            "pack",
            description="Packungsgröße, z. B. '250 g' oder '1 l' (ohne Angabe: die übliche)",
        ): cv.string,
    }

    async def _async_handle(self, hass, manager, values):
        text = str(values["price"]).strip()
        if values.get("price_cent") is not None:  # sentence "… 1 Euro 79"
            text = f"{text} Euro {int(float(values['price_cent']))}"
        elif values.get("price_unit") == "cent":  # sentence "… 99 Cent"
            text = f"{text} Cent"
        text = _spoken_price(text)
        words = fold(str(values["product"])).split()
        if not words or words[0] in _QUESTION_WORDS:
            raise _NotThisIntent(f"„{values['product']}“ ist kein Produkt.")
        if not _PRICE_TEXT_RE.match(text):
            raise _NotThisIntent(
                f"„{values['price']}“ ist kein Preis – bitte den Preis in Euro sagen, "
                "zum Beispiel 1,79 Euro."
            )
        price = parse_price(text)
        # a pack named with the product ("Butter 250 g"): the price of Butter in that pack
        product, named_pack = split_pack(strip_article(str(values["product"])))
        product = _cap(product.strip())
        store = str(values["store"]).strip()
        retailer = manager.require_retailer(manager.store_text(store))
        pack = parse_pack_text(values.get("pack")) or named_pack
        if pack is None:
            # the pack of the price there or of the estimate ("Butter": 250 g)
            known = manager.store_book(retailer).lookup(product)
            pack = (known.amount, known.unit) if known is not None else (1.0, "Stück")
        entry = manager.set_price(product, price, pack[0], pack[1], store)
        branch = manager.named_branch(store)
        label = manager.branch_label(branch) if branch else retailer_name(retailer)
        shown = pack_text(entry["amount"], entry["unit"])
        speech = (
            f"Okay, {product} kostet bei {label} {format_eur(entry['price'])}"
            f"{f' ({shown})' if shown else ''}. Das ist jetzt der Normalpreis dort."
        )
        return speech, {"price": entry}


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
        occasions = [o for d in week["days"] for o in d.get("occasions") or []]
        meals_total = round(week["total"] - week.get("occasions_total", 0.0), 2)
        if not meals:
            speech = f"Für {label} sind noch keine Rezepte geplant."
        else:
            speech = (
                f"Die {meals} geplanten Mahlzeiten kosten {label} etwa {format_eur(meals_total)}."
            )
            if week.get("savings"):
                speech += f" Durch Angebote sparst du ungefähr {format_eur(week['savings'])}."
        if occasions:
            # 1.5: occasions of the week ("Dazu kommt der Filmabend mit etwa 23 €")
            names = _join([o["title"] for o in occasions])
            speech += f" Dazu {'kommt' if len(occasions) == 1 else 'kommen'} {names} mit etwa "
            speech += format_eur(week.get("occasions_total"))
            speech += "." if week.get("occasions_in_budget", True) else " (nicht im Budget)."
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
        "(eigene Ladenpreise, gelernte Normalpreise, gültige Angebote) und nennt das Produkt "
        "dahinter ('Wo ist Butter am günstigsten?'). Compares the price of a product across "
        "stores."
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
        item = str(result["item"])
        results = result["results"]
        if not results:
            return f"Für {name} habe ich keinen Preis.", result
        # only the stores' own prices are named; an estimate is said to be one
        real = [r for r in results if r["real"]]
        if not real:
            estimate = result.get("estimate") or results[0]
            return (
                f"Für {name} kenne ich noch keinen Ladenpreis"
                f"{_pack_hint(estimate, estimate=True, price=True)}.",
                result,
            )
        cheapest = result["cheapest"]
        # without an amount stores are compared per kilo / litre: say it when packs differ
        per_unit = result["compared_by"] == "unit_price" and len({r["pack"] for r in real}) > 1
        if cheapest is None:
            first = real[0]
            offer = " im Angebot" if first.get("offer") else ""
            if len(real) == 1:
                if len(results) > 1:
                    return (
                        f"Ich kenne nur den Preis bei {first['label']}: "
                        f"{format_eur(first['price'])}{_pack_hint(first, item=item)}{offer}.",
                        result,
                    )
                return (
                    f"{name} gibt es bei {first['label']} für {format_eur(first['price'])}"
                    f"{_pack_hint(first, item=item)}{offer}.",
                    result,
                )
            tied = result.get("tied") or []
            if not tied:
                # prices that cannot be compared (no unit price): each store with its own
                prices = [
                    f"bei {r['label']} {format_eur(r['price'])}{_pack_hint(r)}"
                    f"{' im Angebot' if r.get('offer') else ''}"
                    for r in real[:4]
                ]
                return f"{name} kostet {_join(prices)}.", result
            others = [
                f"bei {r['label']} {format_eur(r['price'])}{_pack_hint(r, per_unit=per_unit)}"
                for r in real
                if not any(r is t for t in tied)
            ][:3]
            if len({(r["price"], r["pack"], r.get("packs")) for r in tied}) == 1:
                # "gibt es" works for "Butter" and "Eier" alike; "überall" only when every
                # store has this price
                where = (
                    "überall"
                    if len(tied) == len(results)
                    else _join([f"bei {r['label']}" for r in tied])
                )
                offer = " im Angebot" if all(r.get("offer") for r in tied) else ""
                speech = (
                    f"{name} gibt es {where} für {format_eur(first['price'])}"
                    f"{_pack_hint(first)}{offer}."
                )
            else:
                # the same price per kilo / litre in different packs
                same = [
                    f"bei {r['label']} für {format_eur(r['price'])}{_pack_hint(r, per_unit=True)}"
                    for r in tied
                ]
                speech = f"Gleich günstig gibt es {name} {_join(same)}."
            if others:
                speech += f" {_cap(_join(others))}."
            return speech, result
        speech = (
            f"Am günstigsten gibt es {name} bei {cheapest['label']}: "
            f"{format_eur(cheapest['price'])}"
            f"{_pack_hint(cheapest, per_unit=per_unit, item=item)}"
        )
        if cheapest.get("offer"):
            speech += " im Angebot"
        others = [
            f"bei {r['label']} {format_eur(r['price'])}{_pack_hint(r, per_unit=per_unit)}"
            for r in real
            if r is not cheapest
        ][:3]
        speech += "."
        if others:
            speech += f" {_cap(_join(others))}."
        return speech, result


def _pack_hint(
    result: dict[str, Any],
    estimate: bool = False,
    per_unit: bool = False,
    price: bool = False,
    item: str | None = None,
) -> str:
    """' (250 g)', ' (2 mal 250 g)', ' (250 g, Richtwert)', ' (500 g, 6,98 € pro Kilo)';
    with price the estimate itself: ' (Richtwert 1,99 € für 250 g)'. With item (1.5) the
    product of the product database behind the price when it says more than the item's
    name: ' (Bergland Butter, 250 g)'."""
    parts = []
    if item is not None and (named := _product_name(result, item)):
        parts.append(named)
    pack = ""
    if result.get("pack"):
        packs = result.get("packs") or 1
        pack = f"{packs} mal {result['pack']}" if packs > 1 else result["pack"]
    if price:
        text = f"Richtwert {format_eur(result['price'])}"
        return f" ({text} für {pack})" if pack else f" ({text})"
    if pack:
        parts.append(pack)
    if per_unit and (base_price := _base_price(result)):
        parts.append(base_price)
    if estimate:
        parts.append("Richtwert")
    return f" ({', '.join(parts)})" if parts else ""


def _product_name(result: dict[str, Any], item: str) -> str | None:
    """'Bergland Butter' – the product of a price comparison result (None when it is just
    the item's name)."""
    product = result.get("product") if isinstance(result.get("product"), dict) else None
    title = str((product or {}).get("title") or "").strip()
    if not title or fold(title) == fold(item):
        return None
    return title


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
        if always and not manager.names_product(strip_article(str(values["item"]))):
            # "Was kaufe ich immer bei Lidl?" is a question, no product
            found = manager.preferred_products(str(values["store"]))
            if not found["items"]:
                return f"Für {found['label']} habe ich mir noch keine Produkte gemerkt.", found
            return f"Bei {found['label']} kaufst du immer {_join(found['items'])}.", found
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
        "bzw. dem genannten Laden und dem Lieblingsprodukt, falls eins gemerkt ist ('Setz "
        "Butter auf die Einkaufsliste', '2 Liter Milch auf die Einkaufsliste'). Adds an item "
        "to the shopping list with store, price and the favourite product."
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
        # 1.5: the product of the product database (the ⭐ favourite, a pick, the cheapest)
        product = ""
        if what := manager._product_text(item):
            favorite = item.get("product_reason") == "favorite"
            product = f"{'dein Lieblingsprodukt ' if favorite else ''}{what} "
        if item.get("store_label") and price is not None:
            speech += f" – {product}bei {item['store_label']} etwa {format_eur(price)}"
        elif item.get("store_label"):
            speech += f" – {product}zu kaufen bei {item['store_label']}"
        elif price is not None and product:
            speech += f" – {product}für etwa {format_eur(price)}"
        elif price is not None:
            speech += f" (etwa {format_eur(price)})"
        elif product:
            speech += f" – {product.strip()}"
        speech += "."
        if offer := item.get("offer"):
            speech += (
                f" Gerade im Angebot bei {offer.get('store')} für {format_eur(offer.get('price'))}."
            )
        return speech, {"item": item}


# ----------------------------------------------------------------------
# Occasions and drinks (1.5)
# ----------------------------------------------------------------------

_GUESTS = vol.All(vol.Coerce(int), vol.Range(min=1, max=200))
_CHILDREN = vol.All(vol.Coerce(int), vol.Range(min=0, max=100))
_KIND_WORDS = (
    ("alkoholfrei", "free"),
    ("ohne alkohol", "free"),
    ("kinder", "free"),
    ("rotwein", "wine"),
    ("weisswein", "wine"),
    ("wein", "wine"),
    ("sekt", "sparkling"),
    ("prosecco", "sparkling"),
    ("bier", "beer"),
    ("cocktail", "mixed"),
    ("saft", "juice"),
    ("heiss", "hot"),
    ("kaffee", "hot"),
)


def _to_occasion(occasion: dict[str, Any]) -> str:
    """'zum Filmabend', 'zur Party', 'zu Silvester', 'zu Omas Geburtstag'."""
    from .occasions import template_info

    info = template_info(occasion.get("template"))
    title = str(occasion.get("title") or info["title"])
    if title == info["title"]:
        return str(info["to"])
    return f"zu {title}"


def _people(occasion: dict[str, Any]) -> str:
    """'4 Personen', '2 Erwachsene und 2 Kinder'."""
    guests = int(occasion.get("guests") or 0)
    children = int(occasion.get("children") or 0)
    if not children:
        return f"{guests} {'Person' if guests == 1 else 'Personen'}"
    adults = f"{guests} {'Erwachsenen' if guests == 1 else 'Erwachsene'}"
    return f"{adults} und {children} {'Kind' if children == 1 else 'Kinder'}"


def _menu_speech(occasion: dict[str, Any], extras: bool = False) -> str:
    """'Hauptgang: Pizza Margherita; Snacks: Popcorn und Chips; Getränke: Cola, Bier und
    Apfelschorle' (without the extras unless asked)."""
    from .occasions import COURSE_EXTRA, COURSE_LABELS, COURSES

    parts = []
    for course in COURSES:
        if course == COURSE_EXTRA and not extras:
            continue
        titles = [
            str(i["title"])
            for i in occasion.get("items") or []
            if i.get("course") == course and i.get("title")
        ]
        if titles:
            parts.append(f"{COURSE_LABELS[course]}: {_join(titles)}")
    return "; ".join(parts)


def _occasion_when(manager: EssensplanerManager, occasion: dict[str, Any]) -> str:
    from .occasions import occasion_date

    when = describe_date(occasion_date(occasion), manager.today())
    if occasion.get("time"):
        when += f" um {occasion['time']} Uhr"
    return when


def _guest_numbers(values: dict[str, Any]) -> tuple[int | None, int | None]:
    guests = values.get("guests")
    children = values.get("children")
    return (
        int(guests) if guests is not None else None,
        int(children) if children is not None else None,
    )


class PlanOccasionIntent(_EssensplanerIntent):
    """Plan an occasion with menu, drinks and extras."""

    intent_type = INTENT_PLAN_OCCASION
    response_type = intent.IntentResponseType.ACTION_DONE
    description = (
        "Essensplaner: plant einen Anlass wie Filmabend, Grillabend, Familienessen, "
        "Weihnachtsessen oder Geburtstag mit Menü, Getränken (immer auch alkoholfrei) und "
        "Zubehör nach Regeln ('Plane einen Filmabend am Samstag für 4'). Plans an occasion."
    )
    slot_schema = {
        vol.Required("occasion", description=_OCCASION_DESC): cv.string,
        vol.Optional("date", description=_HOLIDAY_DATE_DESC): cv.string,
        vol.Optional("guests", description="Anzahl Gäste/Erwachsene (1-200)"): _GUESTS,
        vol.Optional("children", description="Anzahl Kinder (0-100)"): _CHILDREN,
        vol.Optional("time", description="Uhrzeit, z. B. '19:30' oder '20 Uhr'"): cv.string,
    }

    async def _async_handle(self, hass, manager, values):
        from .occasions import (
            create_occasion,
            occasion_cost,
            occasions_on,
            resolve_template,
            template_info,
            update_occasion,
        )

        text = strip_article(str(values["occasion"]))
        day, _ = resolve_day(manager, values.get("date"))
        template = resolve_template(text)
        guests, children = _guest_numbers(values)
        info = template_info(template)
        # "Filmabend" / "grillen": the template's title; "Omas Geburtstag": as said
        plain = {template or "", fold(info["title"]), "grillen", "bbq", "film", "anlass"}
        title = info["title"] if template and fold(text) in plain else _cap(text)
        existing = next(
            (
                o
                for o in occasions_on(manager, day)
                if (template and o.get("template") == template)
                or fold(o.get("title") or "") == fold(title)
            ),
            None,
        )
        if existing is not None:
            changes: dict[str, Any] = {}
            if guests:
                changes["guests"] = guests
            if children is not None:
                changes["children"] = children
            if values.get("time"):
                changes["time"] = values["time"]
            if changes:
                update_occasion(manager, existing["id"], changes)
            speech = (
                f"{_cap(existing['title'])} ist {_occasion_when(manager, existing)} schon geplant"
            )
            speech += f" – jetzt für {_people(existing)}." if changes else "."
            if menu := _menu_speech(existing):
                speech += f" {menu}."
            return speech, {"occasion": existing}
        occasion = create_occasion(
            manager,
            template=template,
            day=day,
            time_text=values.get("time"),
            guests=guests,
            children=children,
            title=title,
            auto_fill=True,
        )
        speech = (
            f"Ich habe {occasion['title']} {_occasion_when(manager, occasion)} für "
            f"{_people(occasion)} geplant."
        )
        if menu := _menu_speech(occasion):
            speech += f" {menu}."
        if cost := occasion_cost(manager, occasion)["total"]:
            speech += f" Das kostet ungefähr {format_eur(cost)}."
        return speech, {"occasion": occasion}


class GetOccasionIntent(_EssensplanerIntent):
    """What is planned for an occasion or a holiday?"""

    intent_type = INTENT_GET_OCCASION
    description = (
        "Essensplaner: sagt, was für einen Anlass oder Feiertag geplant ist – Menü, "
        "Getränke, Gäste, Kosten ('Was gibt es Weihnachten?', 'Was gibt es beim "
        "Grillabend?'); ohne Angabe den nächsten Anlass. Returns a planned occasion."
    )
    slot_schema = {
        vol.Optional("occasion", description=_OCCASION_DESC): cv.string,
        vol.Optional("date", description=_HOLIDAY_DATE_DESC): cv.string,
    }

    async def _async_handle(self, hass, manager, values):
        from .occasions import next_occasion, occasion_cost, resolve_occasion

        text = strip_article(str(values.get("occasion") or "")) or None
        day = resolve_day(manager, values["date"])[0] if values.get("date") else None
        if text is None and day is None:
            occasion = next_occasion(manager)
            if occasion is None:
                return "Es ist gerade kein Anlass geplant.", {"occasion": None}
        else:
            try:
                occasion = resolve_occasion(manager, text, day)
            except ServiceValidationError:
                if day is None:
                    raise
                when = describe_date(day, manager.today()).removeprefix("am ")
                meals = manager.day_meals(day)
                if not meals:
                    return f"Für {when} ist noch nichts geplant.", {"occasion": None}
                parts = [f"{_PREPOSITION[m['meal']]} {_spoken_title(m)}" for m in meals]
                return (
                    f"Für {when} ist kein Anlass geplant, aber es gibt {_join(parts)}.",
                    {"occasion": None, "meals": meals},
                )
        speech = (
            f"{_cap(occasion['title'])} {_occasion_when(manager, occasion)} für {_people(occasion)}"
        )
        menu = _menu_speech(occasion)
        speech += f": {menu}." if menu else " – das Menü ist noch leer."
        if cost := occasion_cost(manager, occasion)["total"]:
            speech += f" Geschätzt etwa {format_eur(cost)}."
        return speech, {"occasion": occasion}


class EditOccasionIntent(_EssensplanerIntent):
    """Add or remove a dish, drink or extra of an occasion; change the guests."""

    intent_type = INTENT_EDIT_OCCASION
    response_type = intent.IntentResponseType.ACTION_DONE
    description = (
        "Essensplaner: ändert einen geplanten Anlass – Gericht, Getränk oder Zubehör "
        "hinzufügen oder entfernen, Gästezahl ändern ('Füge Kartoffelsalat zum Grillabend "
        "hinzu', 'Streiche das Tiramisu vom Weihnachtsessen'). Edits an occasion."
    )
    slot_schema = {
        vol.Optional(
            "dish", description="Gericht, Getränk oder Zubehör, z. B. 'Kartoffelsalat'"
        ): cv.string,
        vol.Optional(
            "occasion", description=_OCCASION_DESC + " Leer = nächster Anlass."
        ): cv.string,
        vol.Optional("action", description="'hinzufügen' (Standard) oder 'entfernen'"): cv.string,
        vol.Optional(
            "course",
            description=(
                "Gang: 'Vorspeise', 'Hauptgang', 'Beilagen', 'Dessert', 'Snacks', "
                "'Getränke' oder 'Zubehör'. Leer = automatisch."
            ),
        ): cv.string,
        vol.Optional("guests", description="Neue Anzahl Gäste/Erwachsene"): _GUESTS,
        vol.Optional("children", description="Neue Anzahl Kinder"): _CHILDREN,
    }

    async def _async_handle(self, hass, manager, values):
        from .occasions import (
            COURSE_LABELS,
            add_item,
            items_from_text,
            next_occasion,
            remove_item,
            resolve_course,
            resolve_occasion,
            update_occasion,
        )

        text = strip_article(str(values.get("occasion") or "")) or None
        occasion = resolve_occasion(manager, text) if text else next_occasion(manager)
        if occasion is None:
            raise _SpokenError(
                "Es ist kein Anlass geplant – plane zuerst einen, z. B. einen Filmabend."
            )
        guests, children = _guest_numbers(values)
        dish = strip_article(str(values.get("dish") or "")).strip()
        if not dish and guests is None and children is None:
            raise _SpokenError(f"Was soll ich {_to_occasion(occasion)} ändern?")
        parts: list[str] = []
        data: dict[str, Any] = {}
        if dish:
            action = fold(str(values.get("action") or ""))
            course = None
            if values.get("course"):
                course = resolve_course(str(values["course"]))
                if course is None:
                    raise _SpokenError(f"Den Gang „{values['course']}“ kenne ich nicht.")
            if any(word in action for word in ("entfern", "streich", "loesch", "weg", "remove")):
                removed = remove_item(manager, occasion["id"], dish)
                parts.append(f"Ich habe {removed['title']} {_from_occasion(occasion)} gestrichen")
                data["removed"] = removed
            else:
                raw = items_from_text(manager, [dish], course)[0]
                item = add_item(manager, occasion["id"], raw)
                parts.append(
                    f"Ich habe {item['title']} {_to_occasion(occasion)} hinzugefügt "
                    f"({COURSE_LABELS[item['course']]})"
                )
                data["item"] = item
        if guests is not None or children is not None:
            changes = {}
            if guests is not None:
                changes["guests"] = guests
            if children is not None:
                changes["children"] = children
            occasion = update_occasion(manager, occasion["id"], changes)
            parts.append(f"{_cap(_to_occasion(occasion))} kommen jetzt {_people(occasion)}")
        data["occasion"] = occasion
        return ". ".join(_cap(p) for p in parts) + ".", data


def _from_occasion(occasion: dict[str, Any]) -> str:
    """'vom Filmabend', 'von der Party', 'von Silvester'."""
    to = _to_occasion(occasion)
    for old, new in (("zum ", "vom "), ("zur ", "von der "), ("zu ", "von ")):
        if to.startswith(old):
            return new + to[len(old) :]
    return to


class SuggestDrinksIntent(_EssensplanerIntent):
    """Which drinks go with a dish or an occasion?"""

    intent_type = INTENT_SUGGEST_DRINKS
    description = (
        "Essensplaner: schlägt passende Getränke zu einem Gericht oder Anlass vor – Wein, "
        "Bier, Sekt und immer auch alkoholfreie ('Welcher Wein passt zur Lasagne?', 'Was "
        "trinken wir zum Grillen?'); ohne Angabe zur nächsten Mahlzeit. Suggests drinks."
    )
    slot_schema = {
        vol.Optional("dish", description="Gericht/Rezept, z. B. 'Lasagne'"): cv.string,
        vol.Optional("occasion", description=_OCCASION_DESC): cv.string,
        vol.Optional(
            "kind",
            description="Art: 'Wein', 'Bier', 'Sekt', 'Cocktail' oder 'alkoholfrei'",
        ): cv.string,
    }

    async def _async_handle(self, hass, manager, values):
        from .drinks import drink_text, suggest_drinks
        from .occasions import (
            _occasion_dishes,
            occasion_date,
            resolve_occasion,
            resolve_template,
            template_info,
        )

        dish = strip_article(str(values.get("dish") or "")).strip()
        occasion_text = strip_article(str(values.get("occasion") or "")).strip()
        if (
            dish
            and not occasion_text
            and resolve_template(dish)
            and not manager.get_recipe_by_name(dish)
        ):
            occasion_text, dish = dish, ""  # "Was trinken wir zum Grillen?"
        kind_text = fold(str(values.get("kind") or ""))
        kind = next((k for word, k in _KIND_WORDS if word in kind_text), None)
        recipes: list[dict[str, Any]] = []
        titles: list[str] = []
        template = None
        day = None
        guests = None
        children = 0
        target = ""
        if occasion_text:
            try:
                occasion = resolve_occasion(manager, occasion_text)
            except ServiceValidationError:
                occasion = None
            if occasion is not None:
                found, free, _courses = _occasion_dishes(manager, occasion)
                recipes, titles = found, free
                template = occasion.get("template")
                day = occasion_date(occasion)
                guests = int(occasion.get("guests") or 0) or None
                children = int(occasion.get("children") or 0)
                target = _to_occasion(occasion)
            else:
                template = resolve_template(occasion_text)
                if template is None:
                    raise _SpokenError(f"Den Anlass „{occasion_text}“ kenne ich nicht.")
                target = str(template_info(template)["to"])
        if dish:
            recipe = manager.find_recipe(dish)
            if recipe is not None:
                recipes = [recipe]
                target = f"zu {recipe['name']}"
            else:
                titles = [dish]
                target = f"zu {dish}"
        if not recipes and not titles and template is None:
            upcoming = manager.next_meal()
            recipe = manager.recipes.get((upcoming or {}).get("recipe_id") or "")
            if recipe is None:
                raise _SpokenError("Zu welchem Gericht oder Anlass suchst du ein Getränk?")
            recipes = [recipe]
            target = f"zu {recipe['name']}"
        result = suggest_drinks(
            manager,
            recipes=recipes,
            titles=titles,
            template=template,
            day=day,
            guests=guests,
            children=children,
            kind=kind,
        )
        drinks = result["drinks"]
        alcoholic = [d for d in drinks if d["alcohol"]]
        free = [d for d in drinks if not d["alcohol"]]
        if alcoholic:
            speech = f"{_cap(target)} passt {_join([drink_text(d) for d in alcoholic], 'oder')}."
            speech += f" Ohne Alkohol: {_join([d['title'] for d in free[:3]], 'oder')}."
        else:
            speech = f"{_cap(target)} passt {_join([d['title'] for d in free[:3]], 'oder')}."
            if kind not in (None, "free") and not result["alcohol"]:
                speech += " Getränke mit Alkohol schlage ich nicht vor – das ist in den Einstellungen ausgeschaltet."
        return speech, result


class GetSeasonIntent(_EssensplanerIntent):
    """What is in season (now or in a month) and which recipes fit?"""

    intent_type = INTENT_GET_SEASON
    description = (
        "Essensplaner: sagt, welches Obst und Gemüse gerade (oder in einem Monat) Saison hat, "
        "welche Zeit des Jahres ist (Advent, Grillzeit …) und welche eigenen Rezepte dazu "
        "passen ('Was hat gerade Saison?', 'Was hat im Mai Saison?'). Seasonal produce."
    )
    slot_schema = {
        vol.Optional("month", description="Monat/month, z. B. 'Mai' oder 'Dezember'"): cv.string,
        vol.Optional("date", description=_HOLIDAY_DATE_DESC): cv.string,
    }

    async def _async_handle(self, hass, manager, values):
        from .season import MONTH_NAMES, resolve_month, season_view

        today = manager.today()
        day = today
        when = "Gerade"
        if values.get("month"):
            month = resolve_month(values["month"])
            if month is None:
                raise _SpokenError(f"Den Monat „{values['month']}“ kenne ich nicht.")
            if month != today.month:
                year = today.year + (1 if month < today.month else 0)
                day = date(year, month, 15)
                when = f"Im {MONTH_NAMES[month - 1]}"
        elif values.get("date"):
            day, _ = resolve_day(manager, values["date"])
            if day != today:
                when = _cap(describe_date(day, today))
        view = season_view(manager, day, 3)
        produce = [p["label"] for p in view["produce"]]
        speech = (
            f"{when} hat Saison: {_join(produce[:6])}."
            if produce
            else f"{when} hat kaum etwas aus der Region Saison."
        )
        if view["windows"]:
            speech += f" Es ist {_join([w['label'] for w in view['windows']])}."
        elif view["upcoming"] and day == today:
            speech += f" Bald beginnt: {_join([w['label'] for w in view['upcoming']])}."
        recipes = [r["name"] for r in view["recipes"]]
        if recipes:
            speech += f" Dazu passt aus deinen Rezepten {_join(recipes, 'oder')}."
        return speech, {
            "date": view["date"],
            "month": view["month_name"],
            "season": view["season"]["label"],
            "produce": produce,
            "windows": [w["label"] for w in view["windows"]],
            "recipes": view["recipes"],
        }


class PlanLeftoverIntent(_EssensplanerIntent):
    """Cook a planned meal for another day too (leftovers, 1.5.1)."""

    intent_type = INTENT_PLAN_LEFTOVER
    response_type = intent.IntentResponseType.ACTION_DONE
    description = (
        "Essensplaner: kocht eine geplante Mahlzeit für einen weiteren Tag mit – die Reste "
        "werden für eine spätere Mahlzeit eingeplant ('Koch am Dienstag für Mittwoch mit', "
        "'Plane die Reste vom Dienstag für Mittwoch'); eingekauft wird am Kochtag für beide, "
        "die Reste kosten nichts. Plans the leftovers of a planned meal for a later meal."
    )
    slot_schema = {
        vol.Optional("from_date", description="Kochtag/cooking day. " + _DATE_DESC): cv.string,
        vol.Optional(
            "to_date", description="Tag der Reste/day of the leftovers (Standard: Tag danach)."
        ): cv.string,
        vol.Optional("from_meal", description="Gekocht zum/cooked for. " + _MEAL_DESC): cv.string,
        vol.Optional(
            "to_meal", description="Mahlzeit der Reste (Standard: wie beim Kochen)."
        ): cv.string,
        vol.Optional("dish", description="Geplantes Gericht, z. B. 'Lasagne'"): cv.string,
        vol.Optional("servings", description="Portionen der Reste/servings"): _INT_1_30,
    }

    async def _async_handle(self, hass, manager, values):
        dish = strip_article(str(values["dish"])) if values.get("dish") else None
        src_day, src_meal, day, meal = resolve_leftover(
            manager,
            values.get("to_date"),
            values.get("to_meal"),
            values.get("from_date"),
            values.get("from_meal"),
            dish=dish,
        )
        view = manager.plan_leftover(day, meal, src_day, src_meal, servings=values.get("servings"))
        link = view["leftover_of"]
        cooking_day = date.fromisoformat(link["date"])
        cooking = manager.entry_view(
            cooking_day, link["meal"], manager.plan[link["date"]][link["meal"]]
        )
        today = manager.today()
        speech = (
            f"Alles klar: {view['dish']} wird {describe_date(cooking_day, today)} für "
            f"{cooking['cook_servings']} Portionen gekocht, "
            f"{describe_date(day, today)} {_PREPOSITION[meal]} gibt es die Reste."
        )
        if view.get("replaced") and view["replaced"] != view["dish"]:
            speech += f" {view['replaced']} habe ich dafür aus dem Plan genommen."
        return speech, {"entry": view, "cooking": cooking}


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
    SetPriceIntent,
    PlanOccasionIntent,
    GetOccasionIntent,
    EditOccasionIntent,
    SuggestDrinksIntent,
    GetSeasonIntent,
    PlanLeftoverIntent,
]


def async_register_intents(hass: HomeAssistant) -> None:
    """Register all intents."""
    for handler in INTENT_HANDLERS:
        intent.async_register(hass, handler())


def async_remove_intents(hass: HomeAssistant) -> None:
    """Remove all intents."""
    for handler in INTENT_HANDLERS:
        intent.async_remove(hass, handler.intent_type)
