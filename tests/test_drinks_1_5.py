"""1.5 phase P5: drink suggestions (drinks.py) – rules by dish, occasion and season,
always alcohol-free ones, children, the alcohol option, quantities, offers, the AI, drinks
of a planned meal and the intent "Welcher Wein passt zur Lasagne?".

Only made-up test recipes; the AI is a fake conversation agent."""

from __future__ import annotations

from datetime import date
from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import intent
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.essensplaner import drinks as drk, occasions as occ
from custom_components.essensplaner.const import (
    CONF_AI_ENTITY,
    CONF_DEFAULT_MEAL,
    CONF_DEFAULT_SERVINGS,
    CONF_DRINKS_ALCOHOL,
    CONF_ENABLED_MEALS,
    CONF_IMPORT_STARTER,
    CONF_PANTRY,
    CONF_REGISTER_INTENTS,
    CONF_SHOW_PANEL,
    DOMAIN,
)

AGENT = "conversation.jarvis"
NOVEMBER = date(2026, 11, 4)
ADVENT = date(2026, 12, 10)
SUMMER = date(2027, 7, 10)

RECIPES: list[dict[str, Any]] = [
    {
        "name": "Rinderbraten",
        "tags": ["Hauptgericht", "Rind", "Sonntagsessen"],
        "ingredients": ["1 kg Rinderbraten", "2 Zwiebeln"],
    },
    {
        "name": "Lasagne",
        "tags": ["Hauptgericht", "Pasta", "Italienisch"],
        "ingredients": ["500 g Hackfleisch", "400 g gehackte Tomaten", "250 g Lasagneplatten"],
    },
    {
        "name": "Lachs mit Kartoffeln",
        "tags": ["Hauptgericht", "Fisch"],
        "ingredients": ["400 g Lachsfilet", "800 g Kartoffeln"],
    },
    {
        "name": "Spargel mit Sauce Hollandaise",
        "tags": ["Hauptgericht", "Frühling"],
        "ingredients": ["1 kg Spargel", "200 g Butter"],
    },
    {
        "name": "Rotes Thai-Curry",
        "tags": ["Hauptgericht", "Asiatisch", "scharf"],
        "ingredients": ["400 ml Kokosmilch", "2 EL rote Currypaste"],
    },
    {
        "name": "Tiramisu",
        "tags": ["Dessert"],
        "ingredients": ["500 g Mascarpone"],
    },
    {
        "name": "Glühwein",
        "tags": ["Getränk"],
        "ingredients": ["1 l Rotwein", "1 Orange"],
    },
]


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """No starter recipes: only the test recipes."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Essensplaner",
        data={CONF_IMPORT_STARTER: False},
        options={
            CONF_DEFAULT_SERVINGS: 2,
            CONF_DEFAULT_MEAL: "abendessen",
            CONF_ENABLED_MEALS: ["fruehstueck", "mittagessen", "abendessen"],
            CONF_PANTRY: "Salz, Pfeffer, Wasser",
            CONF_REGISTER_INTENTS: True,
            CONF_SHOW_PANEL: True,
        },
    )


@pytest.fixture
async def manager(hass: HomeAssistant, setup_integration: MockConfigEntry) -> Any:
    """The manager with the test recipes."""
    manager = setup_integration.runtime_data
    for recipe in RECIPES:
        manager.add_recipe(recipe)
    return manager


async def _use(hass: HomeAssistant, entry: MockConfigEntry, **options: Any) -> Any:
    hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
    await hass.async_block_till_done()
    return entry.runtime_data


async def _speech(hass: HomeAssistant, intent_type: str, **slots: Any) -> str:
    response = await intent.async_handle(
        hass,
        "test",
        intent_type,
        {key: {"value": value} for key, value in slots.items()},
        language="de",
    )
    return response.speech["plain"]["speech"]


def _suggest(manager: Any, *names: str, **kw: Any) -> dict[str, Any]:
    recipes = [manager.get_recipe_by_name(n) for n in names]
    kw.setdefault("day", NOVEMBER)
    return drk.suggest_drinks(manager, recipes=recipes, **kw)


def _ids(result: dict[str, Any]) -> list[str]:
    return [d["id"] for d in result["drinks"]]


@pytest.mark.parametrize(
    ("title", "alcohol"),
    [
        ("Rotwein", True),
        ("Weißwein, trocken", True),
        ("Weizenbier", True),
        ("Hugo", True),
        ("Aperol Spritz", True),
        ("Gin Tonic", True),
        ("Erdbeerbowle", True),
        ("Glühwein", True),
        ("Alkoholfreies Bier", False),
        ("Radler 0,0 %", False),
        ("Kinderpunsch", False),
        ("Kindersekt", False),
        ("Virgin Mojito", False),
        ("Traubensaft", False),
        ("Traubensecco", False),
        ("Ingwer-Limonade", False),
        ("Limettenlimonade", False),
        ("Silvaner", True),
        ("Chianti Classico", True),
        ("Grauburgunder", True),
        ("Kölsch", True),
        ("Apfelschorle", False),
        ("Mineralwasser", False),
        ("", False),
    ],
)
def test_is_alcoholic(title: str, alcohol: bool) -> None:
    """Alcohol by name; short words only as whole words ("Gin" is no "Ingwer")."""
    assert drk.is_alcoholic(title) is alcohol


def test_drink_table() -> None:
    """Every drink of the rules exists; the alcohol flag matches the name check."""
    for drink_id, info in drk.DRINKS.items():
        assert info["kind"] in drk.KINDS, drink_id
        if drink_id not in ("bowle_af", "hugo_af"):
            assert drk.is_alcoholic(info["title"]) is info["alcohol"], drink_id
    for rule in drk.DRINK_RULES:
        for drink_id in (*rule.get("alcohol", ()), *rule.get("free", ())):
            assert drink_id in drk.DRINKS, (rule["id"], drink_id)
            assert drk.DRINKS[drink_id]["alcohol"] is (drink_id in rule.get("alcohol", ()))
    for drink_id in (*drk.FALLBACK_FREE, *drk.KIDS_FALLBACK):
        assert not drk.DRINKS[drink_id]["alcohol"]


async def test_rules_by_dish(hass: HomeAssistant, manager: Any) -> None:
    """Red wine to roasts, a light red to pasta with tomato, white wine to fish, Silvaner to
    asparagus, Riesling to Thai curry, coffee to dessert – always ≥ 2 alcohol-free."""
    cases = {
        "Rinderbraten": "rotwein_kraeftig",
        "Lasagne": "rotwein_leicht",
        "Lachs mit Kartoffeln": "weisswein",
        "Spargel mit Sauce Hollandaise": "silvaner",
        "Rotes Thai-Curry": "riesling_feinherb",
    }
    for name, first in cases.items():
        result = _suggest(manager, name)
        assert result["alcohol"] is True
        assert _ids(result)[0] == first, name
        assert sum(1 for d in result["drinks"] if not d["alcohol"]) >= 2, name
        assert len([d for d in result["drinks"] if d["alcohol"]]) <= drk.MAX_ALCOHOL
    roast = _suggest(manager, "Rinderbraten")
    assert {"traubensaft_rot", "johannisbeerschorle"} <= set(_ids(roast))
    assert roast["drinks"][0]["reason"].startswith("kräftiges Fleisch")
    dessert = _suggest(manager, "Tiramisu")
    assert {"kaffee", "kakao"} <= set(_ids(dessert))
    # no dish fits: water and apple spritzer
    nothing = drk.suggest_drinks(manager, titles=["Gemüsepfanne"], day=date(2026, 10, 1))
    assert _ids(nothing) == ["mineralwasser", "apfelschorle"]
    assert nothing["drinks"][0]["reason"] == "geht immer"


async def test_occasion_season_and_children(hass: HomeAssistant, manager: Any) -> None:
    """Barbecue → beer and alcohol-free beer; film night → cola; Advent → mulled wine and
    children's punch (the recipe "Glühwein" is linked); summer → Hugo; children get a
    drink for children."""
    grill = drk.suggest_drinks(manager, template="grillen", day=NOVEMBER)
    assert _ids(grill)[0] == "bier" and "bier_af" in _ids(grill)
    film = drk.suggest_drinks(manager, template="filmabend", day=NOVEMBER)
    assert "cola" in _ids(film)
    advent = drk.suggest_drinks(manager, template="weihnachten", day=ADVENT)
    assert {"gluehwein", "kinderpunsch"} <= set(_ids(advent))
    mulled = next(d for d in advent["drinks"] if d["id"] == "gluehwein")
    assert mulled["recipe_id"] == manager.get_recipe_by_name("Glühwein")["id"]
    summer = drk.suggest_drinks(manager, titles=["Salat"], day=SUMMER)
    assert "hugo" in _ids(summer) and "hugo_af" in _ids(summer)
    assert drk.season_windows(ADVENT) == {"advent"} and drk.season_windows(NOVEMBER) == set()
    kids = drk.suggest_drinks(manager, template="filmabend", day=NOVEMBER, children=2)
    assert any(d["kids"] and not d["alcohol"] for d in kids["drinks"])
    wine = _suggest(manager, "Lachs mit Kartoffeln", kind="wine")
    assert wine["drinks"][0]["kind"] == "wine"
    free = _suggest(manager, "Rinderbraten", kind="free")
    assert free["alcohol"] is False and not any(d["alcohol"] for d in free["drinks"])


async def test_alcohol_option(
    hass: HomeAssistant, manager: Any, setup_integration: MockConfigEntry
) -> None:
    """With "Getränkevorschläge mit Alkohol" off only alcohol-free drinks (still ≥ 2); an
    explicit alcohol=True overrides it."""
    manager = await _use(hass, setup_integration, **{CONF_DRINKS_ALCOHOL: False})
    result = _suggest(manager, "Rinderbraten")
    assert result["alcohol"] is False
    assert result["drinks"] and not any(d["alcohol"] for d in result["drinks"])
    assert len(result["drinks"]) >= 2
    assert _suggest(manager, "Rinderbraten", alcohol=True)["drinks"][0]["id"] == "rotwein_kraeftig"
    assert manager.export()["occasion_meta"]["alcohol"] is False


def test_quantities() -> None:
    """Litres for guests, children and hours; wine and beer in bottles, cups for coffee."""
    drinks = [
        drk.drink_view("bier"),
        drk.drink_view("rotwein_kraeftig"),
        drk.drink_view("apfelschorle"),
        drk.drink_view("mineralwasser"),
        drk.drink_view("kaffee"),
    ]
    summary = drk.drink_quantities(drinks, guests=6, children=2, hours=4)
    by_id = {d["id"]: d for d in drinks}
    # adults 6 × (0,45 + 4 × 0,25) = 8,7 l: 45 % alcohol = 3,9 l for beer and wine
    assert by_id["bier"]["bottles"] == 4  # 1,96 l in 0,5-l bottles
    assert by_id["bier"]["liters"] == 2.0 and by_id["bier"]["unit"] == "l"
    assert by_id["rotwein_kraeftig"]["bottles"] == 3 and by_id["rotwein_kraeftig"]["liters"] == 2.25
    assert by_id["kaffee"]["liters"] == 1.5  # 6 cups of 0,2 l, rounded up to 0,5 l
    # 4,8 l alcohol-free for adults and 2 × (0,3 + 4 × 0,2) = 2,2 l for children, halved
    assert by_id["apfelschorle"]["liters"] == 3.5 and "bottles" not in by_id["apfelschorle"]
    assert by_id["mineralwasser"]["liters"] == 3.5
    assert summary["guests"] == 6 and summary["children"] == 2 and summary["hours"] == 4
    assert summary["liters"] == pytest.approx(sum(d["liters"] for d in drinks))
    # without alcohol all litres go to the alcohol-free drinks
    free_only = [drk.drink_view("apfelschorle"), drk.drink_view("mineralwasser")]
    drk.drink_quantities(free_only, guests=4)
    assert sum(d["liters"] for d in free_only) >= 4 * (drk.ADULT_BASE_L + 3 * drk.ADULT_HOUR_L)


async def test_drink_offers(hass: HomeAssistant, manager: Any) -> None:
    """A drink on offer at the user's stores ranks higher and names the offer."""
    manager.add_offer("Bier", "Lidl", 0.79, "0,5 l", NOVEMBER, date(2026, 11, 7))
    result = drk.suggest_drinks(manager, template="filmabend", day=NOVEMBER)
    beer = next(d for d in result["drinks"] if d["id"] == "bier")
    assert beer["offer"]["store"] == "Lidl" and beer["offer"]["price"] == 0.79
    assert beer["offer"]["text"] == "Lidl 0,79 €"


def _fake_agent(hass: HomeAssistant, text: str) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def handler(call: ServiceCall) -> Any:
        calls.append(dict(call.data))
        return {
            "response": {
                "speech": {"plain": {"speech": text, "extra_data": None}},
                "card": {},
                "language": "de",
                "response_type": "action_done",
                "data": {"targets": [], "success": [], "failed": []},
            },
            "conversation_id": "01JTEST",
            "continue_conversation": False,
        }

    hass.services.async_register(
        "conversation", "process", handler, supports_response=SupportsResponse.OPTIONAL
    )
    hass.states.async_set(AGENT, "unknown", {"friendly_name": "Jarvis"})
    return calls


async def test_ai_drinks_merged(
    hass: HomeAssistant, manager: Any, setup_integration: MockConfigEntry, hass_ws_client
) -> None:
    """The AI's drinks come first, checked by name (no alcohol when switched off – even if
    the AI says otherwise), merged with the rules; the payload has the dishes, not the
    occasion's title."""
    manager = await _use(
        hass, setup_integration, **{CONF_AI_ENTITY: AGENT, CONF_DRINKS_ALCOHOL: False}
    )
    calls = _fake_agent(
        hass,
        'Gerne! {"getraenke": [{"titel": "Barolo", "alkohol": false}, '
        '{"titel": "Rotwein", "alkohol": false}, {"titel": "Virgin Mojito", "alkohol": false, '
        '"grund": "frisch"}, {"titel": "Apfelschorle"}, "Holunderschorle"]}',
    )
    occasion = occ.create_occasion(manager, "familienessen", "Sonntag", title="Tante Ernas 70.")
    occ.add_item(manager, occasion["id"], "Rinderbraten")
    result = await occ.async_suggest_drinks(hass, manager, occasion=occasion, ai=True)
    assert result["ai"] == {"ok": True}
    titles = [d["title"] for d in result["drinks"]]
    assert titles[:2] == ["Virgin Mojito", "Apfelschorle"]
    assert "Holunderschorle" in titles and "Barolo" not in titles and "Rotwein" not in titles
    assert titles.count("Apfelschorle") == 1
    assert not any(d["alcohol"] for d in result["drinks"])
    assert result["drinks"][0]["ai"] is True and result["drinks"][0]["reason"] == "frisch"
    assert result["quantities"]["guests"] == 2 and result["drinks"][0]["liters"]
    prompt = calls[0]["text"]
    assert "Rinderbraten" in prompt and "Tante Erna" not in prompt
    assert '"alkohol_erlaubt":false' in prompt
    # a broken answer keeps the rules (another dish: no cached answer)
    _fake_agent(hass, "Dazu passt Wasser.")
    occ.add_item(manager, occasion["id"], "Tiramisu")
    client = await hass_ws_client(hass)
    await client.send_json(
        {"id": 1, "type": f"{DOMAIN}/drinks_suggest", "occasion_id": occasion["id"], "ai": True}
    )
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"]["ai"]["ok"] is False and msg["result"]["ai"]["code"] == "ai_invalid"
    assert len(msg["result"]["drinks"]) >= 2


async def test_plan_entry_drinks(hass: HomeAssistant, manager: Any) -> None:
    """A planned meal keeps its drinks (re-planning the same dish keeps them, [] removes
    them); older entries have none."""
    lasagne = manager.get_recipe_by_name("Lasagne")
    view = manager.plan_meal(
        NOVEMBER,
        "abendessen",
        lasagne,
        drinks=["Rotwein", {"title": "Wasser", "alcohol": False}, "rotwein"],
    )
    assert view["drinks"] == [
        {"title": "Rotwein", "alcohol": True},
        {"title": "Wasser", "alcohol": False},
    ]
    view = manager.plan_meal(NOVEMBER, "abendessen", lasagne, servings=4)
    assert [d["title"] for d in view["drinks"]] == ["Rotwein", "Wasser"]
    view = manager.plan_meal(NOVEMBER, "abendessen", manager.get_recipe_by_name("Tiramisu"))
    assert view["drinks"] == []
    view = manager.plan_meal(NOVEMBER, "abendessen", lasagne, drinks=["Rotwein"])
    view = manager.plan_meal(NOVEMBER, "abendessen", lasagne, drinks=[])
    assert view["drinks"] == [] and "drinks" not in manager.plan[NOVEMBER.isoformat()]["abendessen"]


async def test_intent_suggest_drinks(
    hass: HomeAssistant, manager: Any, setup_integration: MockConfigEntry
) -> None:
    """ "Welcher Wein passt zur Lasagne?", "Was trinken wir zum Grillen?", the next meal."""
    speech = await _speech(hass, "essensplaner_suggest_drinks", dish="Lasagne", kind="wein")
    assert speech.startswith("Zu Lasagne passt Rotwein, leicht (z. B. Spätburgunder oder Chianti)")
    assert speech.endswith("Ohne Alkohol: Roter Traubensaft, Apfelschorle oder Mineralwasser."), (
        speech
    )
    speech = await _speech(hass, "essensplaner_suggest_drinks", occasion="grillen")
    assert speech.startswith("Zum Grillabend passt Bier (Pils oder Helles)")
    assert "Alkoholfreies Bier" in speech
    speech = await _speech(hass, "essensplaner_suggest_drinks", dish="grillen")
    assert speech.startswith("Zum Grillabend passt Bier")
    speech = await _speech(hass, "essensplaner_suggest_drinks")
    assert speech == "Zu welchem Gericht oder Anlass suchst du ein Getränk?"
    manager.plan_meal(NOVEMBER, "abendessen", manager.get_recipe_by_name("Rinderbraten"))
    speech = await _speech(hass, "essensplaner_suggest_drinks")
    assert speech.startswith("Zu Rinderbraten passt Rotwein, kräftig")
    speech = await _speech(hass, "essensplaner_suggest_drinks", dish="Lasagne", kind="alkoholfrei")
    assert speech == "Zu Lasagne passt Roter Traubensaft, Apfelschorle oder Mineralwasser."
    manager = await _use(hass, setup_integration, **{CONF_DRINKS_ALCOHOL: False})
    speech = await _speech(hass, "essensplaner_suggest_drinks", dish="Lasagne", kind="wein")
    assert "Rotwein" not in speech
    assert speech.endswith("das ist in den Einstellungen ausgeschaltet.")
