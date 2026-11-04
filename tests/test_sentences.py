"""The custom sentences map to the right intents and slots."""

from __future__ import annotations

from pathlib import Path

from hassil import Intents, recognize
import pytest
import yaml

from custom_components.essensplaner.intents import INTENT_HANDLERS

SENTENCES = Path(__file__).parent.parent / "custom_sentences" / "de" / "essensplaner.yaml"


@pytest.fixture(scope="module")
def intents() -> Intents:
    """Load the sentence file."""
    return Intents.from_dict(yaml.safe_load(SENTENCES.read_text(encoding="utf-8")))


def test_all_intents_exist(intents: Intents) -> None:
    """Every intent in the file is registered by the integration."""
    registered = {h.intent_type for h in INTENT_HANDLERS}
    assert set(intents.intents) <= registered


@pytest.mark.parametrize(
    ("sentence", "intent_name", "slots"),
    [
        ("was gibt es heute zu essen", "essensplaner_get_meals", {"date": "heute"}),
        ("was gibt es morgen abend", "essensplaner_get_meals", {"date": "morgen abend"}),
        ("was essen wir am freitag", "essensplaner_get_meals", {"date": "am freitag"}),
        ("was gibt es zum abendessen", "essensplaner_get_meals", {"meal": "abendessen"}),
        ("wie sieht der essensplan aus", "essensplaner_get_week_plan", {}),
        (
            "plane lasagne für freitag",
            "essensplaner_plan_meal",
            {"dish": "lasagne", "date": "freitag"},
        ),
        (
            "plane spaghetti bolognese für morgen zum mittagessen",
            "essensplaner_plan_meal",
            {"dish": "spaghetti bolognese", "date": "morgen", "meal": "mittagessen"},
        ),
        (
            "plane pizza für heute abend",
            "essensplaner_plan_meal",
            {"dish": "pizza", "date": "heute abend"},
        ),
        ("lösche das essen von morgen", "essensplaner_remove_meal", {"date": "morgen"}),
        ("was soll ich heute kochen", "essensplaner_suggest_recipes", {}),
        (
            "schlag mir was vegetarisches vor",
            "essensplaner_suggest_recipes",
            {"tag": "vegetarisch"},
        ),
        ("was brauche ich für lasagne", "essensplaner_get_recipe", {"dish": "lasagne"}),
        ("wie koche ich chili con carne", "essensplaner_get_recipe", {"dish": "chili con carne"}),
        (
            "welche rezepte habe ich mit hähnchen",
            "essensplaner_search_recipes",
            {"query": "hähnchen"},
        ),
        ("erstelle die einkaufsliste", "essensplaner_create_shopping_list", {}),
        ("plane mir die nächste woche", "essensplaner_auto_plan", {"start_date": "nächste woche"}),
        (
            "wir haben heute linsensuppe gekocht",
            "essensplaner_mark_cooked",
            {"dish": "linsensuppe"},
        ),
        (
            "was kann ich mit hähnchen und reis kochen",
            "essensplaner_cook_with",
            {"ingredients": "hähnchen und reis"},
        ),
        ("was steht auf der einkaufsliste", "essensplaner_get_shopping_list", {}),
        ("was muss ich einkaufen", "essensplaner_get_shopping_list", {}),
        (
            "verschiebe die lasagne auf samstag",
            "essensplaner_move_meal",
            {"dish": "die lasagne", "to_date": "samstag"},
        ),
        (
            "tausche montag und dienstag",
            "essensplaner_move_meal",
            {"from_date": "montag", "to_date": "dienstag"},
        ),
        ("lösche die einkaufsliste", "essensplaner_clear_shopping_list", {}),
        (
            "lösche alle erledigten einträge",
            "essensplaner_clear_shopping_list",
            {"mode": "erledigte"},
        ),
        ("welche angebote gibt es diese woche", "essensplaner_get_offers", {}),
        ("wo ist butter im angebot", "essensplaner_get_offers", {"query": "butter"}),
        ("wie viel budget habe ich noch", "essensplaner_get_costs", {}),
        ("plane mir die woche günstig", "essensplaner_auto_plan", {"strategy": "günstig"}),
        ("plane die woche mit den angeboten", "essensplaner_auto_plan", {"strategy": "angebote"}),
    ],
)
def test_sentences(intents: Intents, sentence: str, intent_name: str, slots: dict) -> None:
    """Sentences are recognized."""
    result = recognize(sentence, intents)
    assert result is not None, sentence
    assert result.intent.name == intent_name
    assert {k: v.value for k, v in result.entities.items()} == slots
