"""Tests for the pure parsing helpers."""

from __future__ import annotations

from datetime import date

import pytest

from custom_components.essensplaner.dates import DateParseError, parse_date, parse_meal
from custom_components.essensplaner.ingredients import (
    aggregate,
    format_ingredient,
    guess_category,
    parse_ingredient,
    scale_ingredient,
)
from custom_components.essensplaner.recipe_import import extract_recipe, parse_duration

TODAY = date(2026, 11, 4)  # Wednesday


@pytest.mark.parametrize(
    ("text", "amount", "unit", "name", "note"),
    [
        ("400 g Spaghetti", 400, "g", "Spaghetti", ""),
        ("1 1/2 EL Olivenöl, kalt gepresst", 1.5, "EL", "Olivenöl", "kalt gepresst"),
        ("½ Bund Petersilie", 0.5, "Bund", "Petersilie", ""),
        ("1½ TL Salz", 1.5, "TL", "Salz", ""),
        ("2-3 Zehen Knoblauch", 3, "Zehe", "Knoblauch", ""),
        ("1 Dose gehackte Tomaten (400 g)", 1, "Dose", "gehackte Tomaten", "400 g"),
        ("ca. 200g Mehl", 200, "g", "Mehl", ""),
        ("1,5 kg Kartoffeln", 1.5, "kg", "Kartoffeln", ""),
        ("Zwiebel(n), fein gewürfelt", None, "", "Zwiebel", "fein gewürfelt"),
        ("3 Eier", 3, "", "Eier", ""),
        ("Salz", None, "", "Salz", ""),
        ("1 Pck. Backpulver", 1, "Pck.", "Backpulver", ""),
    ],
)
def test_parse_ingredient(text, amount, unit, name, note) -> None:
    """Ingredient lines are split into amount, unit and name."""
    parsed = parse_ingredient(text)
    assert parsed["amount"] == amount
    assert parsed["unit"] == unit
    assert parsed["name"] == name
    assert parsed["note"] == note


@pytest.mark.parametrize(
    ("name", "category"),
    [
        ("Spaghetti", "Nudeln, Reis & Getreide"),
        ("Hähnchenbrust", "Fleisch & Fisch"),
        ("Tomatenmark", "Konserven & Gläser"),
        ("Kokosmilch", "Konserven & Gläser"),
        ("Gemüsebrühe", "Gewürze, Öle & Saucen"),
        ("Zwiebeln", "Obst & Gemüse"),
        ("Eier", "Milchprodukte & Eier"),
        ("Parmesan", "Käse & Aufschnitt"),
        ("TK-Erbsen", "Tiefkühl"),
        ("Weizenmehl", "Backen & Süßes"),
        ("Irgendwas", "Sonstiges"),
    ],
)
def test_guess_category(name, category) -> None:
    """Ingredients are sorted into supermarket aisles."""
    assert guess_category(name) == category


def test_scale_and_format() -> None:
    """Scaling keeps units and pluralizes counted items."""
    onion = scale_ingredient(parse_ingredient("1 Zwiebel"), 2)
    assert format_ingredient(onion) == "2 Zwiebeln"
    flour = scale_ingredient(parse_ingredient("750 g Mehl"), 2)
    assert format_ingredient(flour) == "1,5 kg Mehl"
    garlic = scale_ingredient(parse_ingredient("1 Zehe Knoblauch"), 3)
    assert format_ingredient(garlic) == "3 Zehen Knoblauch"


def test_aggregate() -> None:
    """Equal ingredients are merged, units converted, pantry skipped."""
    entries = [
        (parse_ingredient("1 Zwiebel"), "A"),
        (parse_ingredient("2 große Zwiebeln"), "B"),
        (parse_ingredient("500 g Kartoffeln"), "A"),
        (parse_ingredient("0,7 kg Kartoffeln"), "B"),
        (parse_ingredient("0,5 Dose Tomaten"), "A"),
        (parse_ingredient("Salz"), "A"),
        (parse_ingredient("1 Prise Pfeffer"), "A"),
    ]
    items = {i["key"]: i for i in aggregate(entries, ["Salz", "Pfeffer"])}
    assert items["zwiebel"]["summary"] == "3 Zwiebeln"
    assert items["zwiebel"]["recipes"] == ["A", "B"]
    assert items["kartoffel"]["summary"] == "1,2 kg Kartoffeln"
    assert items["tomate"]["summary"] == "1 Dose Tomaten"  # rounded up
    assert "salz" not in items
    assert "pfeffer" not in items


@pytest.mark.parametrize(
    ("text", "expected", "meal"),
    [
        (None, date(2026, 11, 4), None),
        ("heute", date(2026, 11, 4), None),
        ("heute Abend", date(2026, 11, 4), "abendessen"),
        ("heute morgen", date(2026, 11, 4), "fruehstueck"),
        ("morgen", date(2026, 11, 5), None),
        ("morgen früh", date(2026, 11, 5), "fruehstueck"),
        ("morgen Mittag", date(2026, 11, 5), "mittagessen"),
        ("übermorgen", date(2026, 11, 6), None),
        ("Freitag", date(2026, 11, 6), None),
        ("am Mittwoch", date(2026, 11, 4), None),
        ("nächsten Mittwoch", date(2026, 11, 11), None),
        ("nächste Woche Montag", date(2026, 11, 9), None),
        ("nächste Woche", date(2026, 11, 9), None),
        ("in 3 Tagen", date(2026, 11, 7), None),
        ("24.12.", date(2026, 12, 24), None),
        ("1.1.", date(2027, 1, 1), None),
        ("05.11.2026", date(2026, 11, 5), None),
        ("2026-11-20", date(2026, 11, 20), None),
        ("tomorrow", date(2026, 11, 5), None),
        ("Wochenende", date(2026, 11, 7), None),
    ],
)
def test_parse_date(text, expected, meal) -> None:
    """German date expressions are understood."""
    assert parse_date(text, TODAY) == (expected, meal)


def test_parse_date_invalid() -> None:
    """Gibberish raises."""
    with pytest.raises(DateParseError):
        parse_date("Blumenkohl", TODAY)


@pytest.mark.parametrize(
    ("text", "meal"),
    [
        ("Abendessen", "abendessen"),
        ("abends", "abendessen"),
        ("zum Mittagessen", "mittagessen"),
        ("Frühstück", "fruehstueck"),
        ("dinner", "abendessen"),
        ("Snack", "snack"),
        ("Quatsch", None),
    ],
)
def test_parse_meal(text, meal) -> None:
    """Meal names are mapped to slots."""
    assert parse_meal(text) == meal


PAGE = """
<html><head>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"WebSite","name":"x"}</script>
<script type="application/ld+json">
{"@context": "https://schema.org", "@graph": [{"@type": "BreadcrumbList"},
 {"@type": ["Recipe"], "name": "Omas K&auml;sesp&auml;tzle",
  "recipeYield": "4 Portionen",
  "prepTime": "PT20M", "cookTime": "PT1H",
  "recipeIngredient": ["500 g Mehl", "5 Eier", "200 g Bergkäse", "2 Zwiebeln"],
  "recipeInstructions": [
    {"@type": "HowToSection", "name": "Teig", "itemListElement": [
      {"@type": "HowToStep", "text": "Mehl und Eier verrühren."}]},
    {"@type": "HowToStep", "text": "Spätzle kochen.<br>Mit Käse schichten."}
  ],
  "keywords": "Hauptgericht, Käse, vegetarisch",
  "image": {"@type": "ImageObject", "url": "https://example.com/img.jpg"}}
]}
</script></head><body></body></html>
"""


def test_extract_recipe() -> None:
    """schema.org recipes are extracted from HTML."""
    recipe = extract_recipe(PAGE, "https://example.com/r")
    assert recipe["name"] == "Omas Käsespätzle"
    assert recipe["servings"] == 4
    assert recipe["prep_time"] == 20
    assert recipe["cook_time"] == 60
    assert recipe["total_time"] == 80
    assert recipe["ingredients"][0] == "500 g Mehl"
    assert recipe["steps"] == [
        "Teig: Mehl und Eier verrühren.",
        "Spätzle kochen.",
        "Mit Käse schichten.",
    ]
    assert recipe["tags"] == ["Hauptgericht", "Käse", "vegetarisch"]
    assert recipe["image"] == "https://example.com/img.jpg"


def test_parse_duration() -> None:
    """ISO 8601 durations."""
    assert parse_duration("PT1H30M") == 90
    assert parse_duration("P0DT0H45M") == 45
    assert parse_duration("45") == 45
    assert parse_duration("") is None
    assert parse_duration("bald") is None
