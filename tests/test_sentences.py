"""The custom sentences map to the right intents and slots."""

from __future__ import annotations

from pathlib import Path

from hassil import Intents, recognize_best
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
        # 1.3: shopping list per store, prices, adding items
        (
            "was muss ich bei aldi süd kaufen",
            "essensplaner_get_shopping_list",
            {"store": "aldi süd"},
        ),
        ("was kaufe ich bei lidl", "essensplaner_get_shopping_list", {"store": "lidl"}),
        # 1.4: drugstores
        ("was kaufe ich bei rossmann", "essensplaner_get_shopping_list", {"store": "rossmann"}),
        ("was muss ich beim dm kaufen", "essensplaner_get_shopping_list", {"store": "dm"}),
        ("was hat müller im angebot", "essensplaner_get_offers", {"store": "müller"}),
        # the drugstore (voice-docs-r1-2)
        ("was kaufe ich in der drogerie", "essensplaner_get_shopping_list", {"store": "drogerie"}),
        (
            "was muss ich in der drogerie kaufen",
            "essensplaner_get_shopping_list",
            {"store": "drogerie"},
        ),
        ("was holen wir im drogeriemarkt", "essensplaner_get_shopping_list", {"store": "drogerie"}),
        (
            "was gibt es in der drogerie gerade im angebot",
            "essensplaner_get_offers",
            {"store": "drogerie"},
        ),
        ("welche angebote hat die drogerie", "essensplaner_get_offers", {"store": "drogerie"}),
        (
            "kauf zahnpasta immer bei budni",
            "essensplaner_set_shopping_store",
            {"item": "zahnpasta", "store": "budni", "always": True},
        ),
        (
            "was muss ich im hauptladen kaufen",
            "essensplaner_get_shopping_list",
            {"store": "hauptladen"},
        ),
        (
            "was müssen wir bei rewe besorgen",
            "essensplaner_get_shopping_list",
            {"store": "rewe"},
        ),
        (
            "was muss ich bei lidl arbeit kaufen",
            "essensplaner_get_shopping_list",
            {"store": "lidl arbeit"},
        ),
        ("wo ist butter am günstigsten", "essensplaner_compare_prices", {"item": "butter"}),
        (
            "wo bekomme ich hackfleisch am billigsten",
            "essensplaner_compare_prices",
            {"item": "hackfleisch"},
        ),
        ("vergleiche die preise für kaffee", "essensplaner_compare_prices", {"item": "kaffee"}),
        (
            "kauf die butter bei rewe",
            "essensplaner_set_shopping_store",
            {"item": "die butter", "store": "rewe"},
        ),
        (
            "kauf die milch bei lidl arbeit",
            "essensplaner_set_shopping_store",
            {"item": "die milch", "store": "lidl arbeit"},
        ),
        (
            "kauf butter immer bei aldi nord",
            "essensplaner_set_shopping_store",
            {"item": "butter", "store": "aldi nord", "always": True},
        ),
        (
            "milch kaufe ich immer bei lidl",
            "essensplaner_set_shopping_store",
            {"item": "milch", "store": "lidl", "always": True},
        ),
        (
            "setz butter auf die einkaufsliste",
            "essensplaner_add_shopping_item",
            {"item": "butter"},
        ),
        (
            "2 liter milch auf die einkaufsliste",
            "essensplaner_add_shopping_item",
            {"item": "2 liter milch"},
        ),
        ("füge eier zur einkaufsliste hinzu", "essensplaner_add_shopping_item", {"item": "eier"}),
        (
            "schreib kaffee für edeka auf die einkaufsliste",
            "essensplaner_add_shopping_item",
            {"item": "kaffee", "store": "edeka"},
        ),
        # the same wordings as HA's own shopping list (and speech recognition's "setzt")
        ("setzt milch auf die einkaufsliste", "essensplaner_add_shopping_item", {"item": "milch"}),
        ("nimm milch auf die einkaufsliste", "essensplaner_add_shopping_item", {"item": "milch"}),
        ("setz milch auf meine einkaufsliste", "essensplaner_add_shopping_item", {"item": "milch"}),
        ("schreib milch in die einkaufsliste", "essensplaner_add_shopping_item", {"item": "milch"}),
        (
            "füge milch zu meiner einkaufsliste hinzu",
            "essensplaner_add_shopping_item",
            {"item": "milch"},
        ),
        ("milch auf die einkaufsliste setzen", "essensplaner_add_shopping_item", {"item": "milch"}),
        ("milch zur einkaufsliste hinzufügen", "essensplaner_add_shopping_item", {"item": "milch"}),
        ("setz milch auf die liste", "essensplaner_add_shopping_item", {"item": "milch"}),
        (
            "ergänze milch auf der einkaufsliste",
            "essensplaner_add_shopping_item",
            {"item": "milch"},
        ),
        # own branch labels
        (
            "was müssen wir bei lidl arbeit kaufen",
            "essensplaner_get_shopping_list",
            {"store": "lidl arbeit"},
        ),
        (
            "was steht für lidl arbeit auf der einkaufsliste",
            "essensplaner_get_shopping_list",
            {"store": "lidl arbeit"},
        ),
        (
            "butter kaufe ich immer bei rewe arbeit",
            "essensplaner_set_shopping_store",
            {"item": "butter", "store": "rewe arbeit", "always": True},
        ),
        # offer questions with a store (review round 4)
        (
            "welche angebote gibt es bei lidl",
            "essensplaner_get_offers",
            {"store": "lidl"},
        ),
        (
            "was ist im hauptladen im angebot",
            "essensplaner_get_offers",
            {"store": "hauptladen"},
        ),
        (
            "welche angebote gibt es im hauptladen",
            "essensplaner_get_offers",
            {"store": "hauptladen"},
        ),
        (
            "wo ist butter bei lidl im angebot",
            "essensplaner_get_offers",
            {"query": "butter", "store": "lidl"},
        ),
        (
            "gibt es butter bei rewe im angebot",
            "essensplaner_get_offers",
            {"query": "butter", "store": "rewe"},
        ),
        (
            "was ist bei lidl arbeit im angebot",
            "essensplaner_get_offers",
            {"store": "lidl arbeit"},
        ),
        # one wildcard: the integration splits off the branch ("butter" at "lidl arbeit")
        (
            "wo ist butter bei lidl arbeit im angebot",
            "essensplaner_get_offers",
            {"query": "butter bei lidl arbeit"},
        ),
        # no conflicts with the older sentences
        ("setze die zutaten auf die einkaufsliste", "essensplaner_create_shopping_list", {}),
        ("schreib die zutaten auf die einkaufsliste", "essensplaner_create_shopping_list", {}),
        ("was muss ich kaufen", "essensplaner_get_shopping_list", {}),
        ("wo ist butter im angebot", "essensplaner_get_offers", {"query": "butter"}),
        ("was ist gerade im angebot", "essensplaner_get_offers", {}),
        (
            "welche angebote gibt es nächste woche",
            "essensplaner_get_offers",
            {"when": "nächste woche"},
        ),
        ("was kostet der essensplan", "essensplaner_get_costs", {}),
        # 1.5: occasions and drinks
        (
            "plane einen filmabend am samstag für 4",
            "essensplaner_plan_occasion",
            {"occasion": "filmabend", "date": "am samstag", "guests": 4},
        ),
        (
            "plane einen grillabend für samstag für 6 personen",
            "essensplaner_plan_occasion",
            {"occasion": "grillabend", "date": "samstag", "guests": 6},
        ),
        (
            "plane ein weihnachtsessen an heiligabend für 8 personen",
            "essensplaner_plan_occasion",
            {"occasion": "weihnachtsessen", "date": "heiligabend", "guests": 8},
        ),
        (
            "wir machen am samstag einen grillabend mit 8 leuten",
            "essensplaner_plan_occasion",
            {"date": "am samstag", "occasion": "grillabend", "guests": 8},
        ),
        ("plane eine party", "essensplaner_plan_occasion", {"occasion": "party"}),
        ("was gibt es weihnachten", "essensplaner_get_occasion", {"date": "weihnachten"}),
        (
            "was gibt es an heiligabend zu essen",
            "essensplaner_get_occasion",
            {"date": "heiligabend"},
        ),
        ("was essen wir an silvester", "essensplaner_get_occasion", {"date": "silvester"}),
        ("was gibt es beim grillabend", "essensplaner_get_occasion", {"occasion": "grillabend"}),
        ("wann ist der nächste anlass", "essensplaner_get_occasion", {}),
        (
            "füge kartoffelsalat zum grillabend hinzu",
            "essensplaner_edit_occasion",
            {"dish": "kartoffelsalat", "occasion": "grillabend"},
        ),
        (
            "streiche das tiramisu vom weihnachtsessen",
            "essensplaner_edit_occasion",
            {"dish": "das tiramisu", "occasion": "weihnachtsessen", "action": "entfernen"},
        ),
        (
            "zum grillabend kommen 8 personen",
            "essensplaner_edit_occasion",
            {"occasion": "grillabend", "guests": 8},
        ),
        (
            "welcher wein passt zur lasagne",
            "essensplaner_suggest_drinks",
            {"kind": "wein", "dish": "lasagne"},
        ),
        ("was trinken wir zum grillen", "essensplaner_suggest_drinks", {"occasion": "grillen"}),
        ("was trinken wir zur lasagne", "essensplaner_suggest_drinks", {"dish": "lasagne"}),
        (
            "welches bier passt zum filmabend",
            "essensplaner_suggest_drinks",
            {"kind": "bier", "occasion": "filmabend"},
        ),
        (
            "welche getränke passen zum raclette abend",
            "essensplaner_suggest_drinks",
            {"occasion": "Raclette-Abend"},
        ),
        # the meals of a day stay with get_meals / plan_meal
        (
            "plane lasagne für samstag",
            "essensplaner_plan_meal",
            {"dish": "lasagne", "date": "samstag"},
        ),
        ("was gibt es zum abendessen", "essensplaner_get_meals", {"meal": "abendessen"}),
    ],
)
def test_sentences(intents: Intents, sentence: str, intent_name: str, slots: dict) -> None:
    """Sentences are recognized (best match, like Home Assistant's default agent)."""
    result = recognize_best(sentence, intents)
    assert result is not None, sentence
    assert result.intent.name == intent_name
    assert {k: v.value for k, v in result.entities.items()} == slots


@pytest.mark.parametrize("sentence", ["hol die wäsche im keller", "hol die post beim nachbarn"])
def test_no_store_sentence(intents: Intents, sentence: str) -> None:
    """Everyday sentences with "holen … im/beim …" are left to other agents."""
    assert recognize_best(sentence, intents) is None


def test_store_list(intents: Intents) -> None:
    """Every store in the sentence list is understood by the integration."""
    from custom_components.essensplaner.retailers import resolve_retailer

    values = [v.value_out for v in intents.slot_lists["store"].values]
    assert "hauptladen" in values
    for value in values:
        if value != "hauptladen":
            assert resolve_retailer(value, zip_code="80331"), value


def test_occasion_and_holiday_lists(intents: Intents) -> None:
    """Every occasion word names a template, every holiday is a date (1.5)."""
    from datetime import date

    from custom_components.essensplaner.dates import parse_date
    from custom_components.essensplaner.occasions import TEMPLATES, resolve_template

    for value in intents.slot_lists["occasion"].values:
        assert resolve_template(value.value_out) in TEMPLATES, value.value_out
    for value in intents.slot_lists["holiday"].values:
        day, _ = parse_date(value.value_out, date(2026, 11, 4))
        assert day >= date(2026, 11, 4), value.value_out
