"""1.5 phase P6: the season – calendar, times of the year, the season of a recipe, the
suggestion weights of every strategy, the strategy "seasonal", reasons, the auto plan with
AI, the websocket, the data export and the intent.

The setup has the starter recipes (conftest: Wednesday 2026-11-04); the AI is faked."""

from __future__ import annotations

from datetime import date
import random
import time
from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import intent
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.essensplaner import season as sea
from custom_components.essensplaner.const import (
    CONF_AI_ENTITY,
    CONF_AI_FEATURES,
    CONF_SEASON_AWARE,
    CONF_STRATEGY,
    DOMAIN,
    STRATEGIES,
    STRATEGY_SEASONAL,
)
from custom_components.essensplaner.economy import _STRATEGY_WEIGHTS, strategy_weights
from custom_components.essensplaner.options_schema import CHOICE_LABELS_DE
from custom_components.essensplaner.services import resolve_strategy

TODAY = date(2026, 11, 4)
TASK = "ai_task.koch"


def _recipe(name: str, ingredients: list[Any], tags: list[str] | None = None, **extra: Any):
    return {
        "id": f"r_{name}",
        "name": name,
        "updated": "1",
        "tags": tags or ["Hauptgericht"],
        "ingredients": [
            {"name": i, "unit": "", "note": ""} if isinstance(i, str) else i for i in ingredients
        ],
        **extra,
    }


class _Manager:
    """Enough of a manager for recipe_season() (cache in __dict__)."""

    options: dict[str, Any] = {}

    def today(self) -> date:
        return TODAY


async def _call(hass: HomeAssistant, service: str, **data: Any) -> Any:
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


async def _use(hass: HomeAssistant, entry: MockConfigEntry, **options: Any) -> Any:
    hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
    await hass.async_block_till_done()
    return entry.runtime_data


async def _speech(hass: HomeAssistant, intent_type: str, **slots: Any) -> intent.IntentResponse:
    return await intent.async_handle(
        hass,
        "test",
        intent_type,
        {key: {"value": value} for key, value in slots.items()},
        language="de",
    )


def _fake_task(hass: HomeAssistant, answer: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def handler(call: ServiceCall) -> Any:
        calls.append(dict(call.data))
        if isinstance(answer, BaseException):
            raise answer
        return answer

    hass.services.async_register(
        "ai_task", "generate_data", handler, supports_response=SupportsResponse.ONLY
    )
    hass.states.async_set(TASK, "unknown", {"friendly_name": "Koch-KI"})
    return calls


# ----------------------------------------------------------------------
# Calendar and times of the year
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "produce"),
    [
        ("Hokkaido-Kürbis", "kuerbis"),
        ("Kirschtomaten", "tomate"),
        ("Äpfel", "apfel"),
        ("Bratäpfel", "apfel"),
        ("grüner Spargel", "spargel"),
        ("Erdbeeren", "erdbeere"),
        ("Pfifferlinge", "pfifferling"),
        ("grüne Bohnen", "bohne"),
        ("Rote Bete", "rote_bete"),
        ("Gänsekeulen", "gans"),
        ("Rehrücken", "wild"),
        ("Miesmuscheln", "muschel"),
        ("Matjesfilets", "matjes"),
        ("Grünkohl", "gruenkohl"),
        ("Lauch", "lauch"),
        # processed or another product: not fresh produce
        ("Kürbiskerne", None),
        ("Tomatenmark", None),
        ("gehackte Tomaten", None),
        ("getrocknete Tomaten", None),
        ("Apfelmus", None),
        ("Apfelsaft", None),
        ("Granatapfel", None),
        ("Erdbeerkonfitüre", None),
        ("Kichererbsen", None),
        ("Kidneybohnen", None),
        ("Gewürzgurken", None),
        ("Knoblauch", None),
        ("Schnittlauch", None),
        ("Rahmspinat", None),
        ("Muschelnudeln", None),
        ("Wildreis", None),
        ("Champignons", None),
        ("Zwiebeln", None),
    ],
)
def test_produce_of(name: str, produce: str | None) -> None:
    """Fresh produce by the last part of its name; processed products are no produce."""
    assert sea.produce_of(name) == produce


def test_line_produce_canned_and_frozen() -> None:
    """A line from a can, a jar or the freezer is no fresh produce."""
    assert sea._line_produce({"name": "Erbsen", "note": "TK"}) is None
    assert sea._line_produce({"name": "Sauerkirschen", "unit": "Glas"}) is None
    assert sea._line_produce({"name": "Rotkohl", "note": "Glas"}) is None
    assert sea._line_produce({"name": "Mais", "unit": "Dose"}) is None
    assert sea._line_produce({"name": "Erbsen", "unit": "g"}) == "erbse"


def test_times_of_the_year() -> None:
    """Advent, Christmas, New Year's Eve across the turn of the year, Easter, carnival,
    the barbecue season, Oktoberfest and St. Martin's Day."""
    assert sea.active_windows(date(2026, 11, 28)) == ()
    assert sea.active_windows(date(2026, 11, 29)) == ("advent",)  # first Advent 2026
    assert sea.active_windows(date(2026, 12, 23)) == ("advent",)
    assert sea.active_windows(date(2026, 12, 24)) == ("weihnachten",)
    assert sea.active_windows(date(2026, 12, 31)) == ("silvester",)
    assert sea.active_windows(date(2027, 1, 1)) == ("silvester",)
    assert sea.active_windows(date(2027, 1, 2)) == ()
    # Easter 2027 is on 28 March: from Palm Sunday to Easter Monday
    assert sea.active_windows(date(2027, 3, 21)) == ("ostern",)
    assert sea.active_windows(date(2027, 3, 29)) == ("ostern",)
    assert sea.active_windows(date(2027, 3, 30)) == ()
    assert sea.active_windows(date(2027, 2, 4)) == ("fasching",)  # Weiberfastnacht
    assert sea.active_windows(date(2027, 2, 9)) == ("fasching",)  # Shrove Tuesday
    assert sea.active_windows(date(2026, 6, 15)) == ("grillzeit",)
    assert sea._oktoberfest(2026) == (date(2026, 9, 19), date(2026, 10, 4))
    assert sea._oktoberfest(2027) == (date(2027, 9, 18), date(2027, 10, 3))
    assert sea.active_windows(TODAY) == ("martinstag",)
    assert [w["id"] for w in sea.upcoming_windows(date(2026, 11, 20))] == ["advent"]
    assert sea.upcoming_windows(TODAY) == []


def test_season_info() -> None:
    """What is in season in November and in May; the typical products first."""
    info = sea.season_info(TODAY)
    assert (info["month"], info["month_name"]) == (11, "November")
    assert info["season"] == {"id": "autumn", "label": "Herbst", "emoji": "🍂"}
    assert [w["id"] for w in info["windows"]] == ["martinstag"]
    labels = [p["label"] for p in info["produce"]]
    assert {"Kürbis", "Grünkohl", "Rosenkohl", "Feldsalat", "Gans"} <= set(labels)
    assert "Spargel" not in labels and "Erdbeeren" not in labels
    assert all(p["strict"] for p in info["produce"][:3])
    gruenkohl = next(p for p in info["produce"] if p["label"] == "Grünkohl")
    assert gruenkohl["new"] is True and gruenkohl["ending"] is False
    assert info["text"].startswith("Jetzt Saison: ")
    may = sea.season_info(date(2027, 5, 10))
    assert may["season"]["label"] == "Frühling"
    assert {"Spargel", "Rhabarber", "Erdbeeren", "Bärlauch"} <= {p["label"] for p in may["produce"]}
    assert "Kürbis" not in {p["label"] for p in may["produce"]}
    assert "Kirschen" in may["coming"]
    # a copy: changing it changes nothing
    info["produce"].clear()
    assert sea.season_info(TODAY)["produce"]


def test_resolve_month() -> None:
    """Month names and numbers."""
    assert sea.resolve_month("im Dezember") == 12
    assert sea.resolve_month("März") == 3
    assert sea.resolve_month("Maerz") == 3
    assert sea.resolve_month("5") == 5
    assert sea.resolve_month(7) == 7
    assert sea.resolve_month("Montag") is None
    assert sea.resolve_month(None) is None


# ----------------------------------------------------------------------
# The season of a recipe
# ----------------------------------------------------------------------


def test_recipe_season() -> None:
    """Score, produce in and out of season, times and hints; cached per recipe version and
    month."""
    manager = _Manager()
    soup = _recipe("Kürbissuppe", ["Hokkaido-Kürbis", "Zwiebeln", "Kürbiskerne"], ["Suppe"])
    found = sea.recipe_season(manager, soup, TODAY)
    assert found == {
        "score": 0.5,
        "items": ["Kürbis"],
        "out_of_season": [],
        "windows": [],
        "hints": ["🍂 Saison: Kürbis"],
    }
    tagged = _recipe("Kürbissuppe", ["Hokkaido-Kürbis"], ["Suppe", "Herbst"], id="r2")
    assert sea.recipe_season(manager, tagged, TODAY)["score"] == 0.8
    in_may = sea.recipe_season(manager, soup, date(2027, 5, 10))
    assert in_may["score"] == 0 and in_may["out_of_season"] == ["Kürbis"]
    asparagus = _recipe("Spargel mit Hollandaise", ["weißer Spargel", "Kartoffeln"])
    assert sea.recipe_season(manager, asparagus, TODAY)["out_of_season"] == ["Spargel"]
    assert sea.recipe_season(manager, asparagus, date(2027, 5, 10))["items"] == ["Spargel"]
    canned = _recipe("Tomatensuppe", ["gehackte Tomaten", "Tomatenmark"])
    assert sea.recipe_season(manager, canned, date(2026, 8, 10))["score"] == 0
    goose = _recipe("Gänsebraten", ["Gänsekeulen", "Rotkohl", "Äpfel"], ["Festlich"])
    martin = sea.recipe_season(manager, goose, TODAY)
    assert martin["windows"] == ["martinstag"] and martin["score"] == 1.0
    assert martin["hints"][-1] == "🏮 Martinstag"
    christmas = sea.recipe_season(manager, goose, date(2026, 12, 25))
    assert christmas["windows"] == ["weihnachten"]
    punch = _recipe("Glühwein", ["Rotwein", "Orangen"], ["Getränk", "Advent"])
    assert sea.recipe_season(manager, punch, date(2026, 12, 2))["hints"] == ["🕯️ Adventszeit"]
    # "Flammkuchen" is no lamb, "Studentenfutter" no duck
    tart = _recipe("Flammkuchen", ["Flammkuchenteig", "Speck"])
    assert sea.recipe_season(manager, tart, date(2027, 3, 25))["windows"] == []
    # the cache: a copy per call, a new version is computed again
    first = sea.recipe_season(manager, soup, TODAY)
    first["items"].append("x")
    assert sea.recipe_season(manager, soup, TODAY)["items"] == ["Kürbis"]
    changed = {**soup, "updated": "2", "ingredients": soup["ingredients"][1:]}
    assert sea.recipe_season(manager, changed, TODAY)["score"] == 0


def test_season_factor_and_strategy_weights() -> None:
    """× (1 + weight · score), × 0.4 for a typical product out of season; every strategy
    has a season weight, "seasonal" the highest."""
    assert set(_STRATEGY_WEIGHTS) == set(STRATEGIES)
    assert all(len(w) == 5 for w in _STRATEGY_WEIGHTS.values())
    assert strategy_weights(STRATEGY_SEASONAL)[4] == 2.5
    assert strategy_weights("unknown") == _STRATEGY_WEIGHTS["balanced"]
    assert max(_STRATEGY_WEIGHTS, key=lambda s: _STRATEGY_WEIGHTS[s][4]) == STRATEGY_SEASONAL
    manager = _Manager()
    soup = _recipe("Kürbissuppe", ["Hokkaido-Kürbis"], ["Suppe", "Herbst"])
    asparagus = _recipe("Spargel", ["weißer Spargel"])
    assert sea.season_factor(manager, soup, TODAY, 0.8) == pytest.approx(1.64)
    assert sea.season_factor(manager, soup, TODAY, 2.5) == pytest.approx(3.0)
    assert sea.season_factor(manager, asparagus, TODAY, 0.8) == pytest.approx(0.4)
    assert sea.season_factor(manager, asparagus, TODAY, 0) == 1.0
    assert STRATEGY_SEASONAL in CHOICE_LABELS_DE["strategy"]
    assert resolve_strategy("saisonal") == STRATEGY_SEASONAL
    assert resolve_strategy("nach Saison") == STRATEGY_SEASONAL
    assert resolve_strategy("seasonal") == STRATEGY_SEASONAL


async def test_suggestion_weights(hass: HomeAssistant, setup_integration: MockConfigEntry) -> None:
    """Every strategy prefers what is in season; "seasonal" most; the option switches it
    off for the other strategies; offers still count."""
    manager = setup_integration.runtime_data
    soup = manager.get_recipe_by_name("Kürbissuppe")
    asparagus = manager.get_recipe_by_name("Spargel mit Sauce Hollandaise und Kartoffeln")
    bolognese = manager.get_recipe_by_name("Spaghetti Bolognese")

    def weights(strategy: str | None = None) -> dict[str, float]:
        ctx = manager._suggest_context(TODAY, strategy=strategy)
        return {r["name"]: manager._suggest_weight(r, ctx) for r in (soup, asparagus, bolognese)}

    balanced = weights()
    seasonal = weights(STRATEGY_SEASONAL)
    assert balanced[soup["name"]] > balanced[bolognese["name"]] > balanced[asparagus["name"]]
    assert seasonal[soup["name"]] > 1.5 * balanced[soup["name"]]
    assert seasonal[bolognese["name"]] == pytest.approx(balanced[bolognese["name"]])
    for strategy in STRATEGIES:
        ctx = manager._suggest_context(TODAY, strategy=strategy)
        assert ctx["season"] > 0, strategy
        assert manager._suggest_weight(soup, ctx) > manager._suggest_weight(asparagus, ctx)

    manager = await _use(hass, setup_integration, **{CONF_SEASON_AWARE: False})
    soup = manager.get_recipe_by_name("Kürbissuppe")
    asparagus = manager.get_recipe_by_name("Spargel mit Sauce Hollandaise und Kartoffeln")
    ctx = manager._suggest_context(TODAY)
    assert ctx["season"] == 0
    assert manager._suggest_weight(asparagus, ctx) == pytest.approx(
        manager._suggest_weight(bolognese, ctx)
    )
    # the strategy "seasonal" counts the season anyway
    assert manager._suggest_context(TODAY, strategy=STRATEGY_SEASONAL)["season"] == 2.5
    assert sea.season_weight(manager, None) == 0
    manager = await _use(
        hass, setup_integration, **{CONF_SEASON_AWARE: True, CONF_STRATEGY: STRATEGY_SEASONAL}
    )
    assert manager.strategy == STRATEGY_SEASONAL
    assert sea.season_weight(manager, None) == 2.5


async def test_seasonal_suggestions_and_reasons(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The seasonal strategy mostly suggests what is in season; the service says why."""
    manager = setup_integration.runtime_data
    rng = random.Random(4)
    picks = [
        manager.suggest(1, meal="abendessen", strategy=STRATEGY_SEASONAL, rng=rng)[0]
        for _ in range(60)
    ]
    seasonal = sum(1 for r in picks if sea.recipe_season(manager, r, TODAY)["score"] > 0)
    out = sum(1 for r in picks if sea.recipe_season(manager, r, TODAY)["out_of_season"])
    assert seasonal > out

    manager.add_offer("Hokkaido-Kürbis", "Aldi Süd", 0.99, "1 kg")
    result = await _call(hass, "suggest_recipes", count=20, tag="Herbst", strategy="saisonal")
    soup = next(r for r in result["recipes"] if r["name"] == "Kürbissuppe")
    assert soup["reasons"][0] == "🍂 Saison: Kürbis"
    assert any(r.startswith("🏷️ Angebot: ") for r in soup["reasons"])
    # without the season: no season reason
    await _use(hass, setup_integration, **{CONF_SEASON_AWARE: False})
    result = await _call(hass, "suggest_recipes", count=20, tag="Herbst")
    soup = next(r for r in result["recipes"] if r["name"] == "Kürbissuppe")
    assert not any("Saison" in r for r in soup["reasons"])


async def test_auto_plan_seasonal(hass: HomeAssistant, setup_integration: MockConfigEntry) -> None:
    """auto_plan takes the strategy "saisonal" and returns reasons; without AI it reports
    no AI result."""
    result = await _call(hass, "auto_plan", days=3, strategy="saisonal")
    assert len(result["planned"]) == 3 and result["ai"] is None
    assert all("reasons" in p for p in result["planned"])


# ----------------------------------------------------------------------
# Auto plan with AI (feature "season")
# ----------------------------------------------------------------------


async def test_auto_plan_with_ai(hass: HomeAssistant, setup_integration: MockConfigEntry) -> None:
    """The AI orders the rules' best 40 candidates: its order fills the days, unknown ids
    are dropped; the payload has recipe names and the season, no notes."""
    manager = setup_integration.runtime_data
    candidates = sea.rank_candidates(manager, TODAY, 3, ["abendessen"])
    assert len(candidates) == sea.CANDIDATES
    # three of the last candidates of different kinds (no variety rule in the way)
    chosen: list[dict[str, Any]] = []
    for recipe in reversed(candidates):
        kind = manager._variety_signature(recipe)
        if all(not kind & manager._variety_signature(c) for c in chosen):
            chosen.append(recipe)
        if len(chosen) == 3:
            break
    chosen[0]["notes"] = "Geheimrezept von Oma, Lindenweg 1"
    answer = {"data": {"order": ["erfunden", chosen[0]["id"], chosen[1]["name"], chosen[2]["id"]]}}
    calls = _fake_task(hass, answer)
    manager = await _use(hass, setup_integration, **{CONF_AI_ENTITY: TASK})
    result = await _call(hass, "auto_plan", days=3, ai=True)
    assert result["ai"] == {"ok": True}
    assert [p["recipe_id"] for p in result["planned"]] == [r["id"] for r in chosen]
    prompt = calls[0]["instructions"]
    assert "Oma" not in prompt and "Lindenweg" not in prompt
    assert "Herbst" in prompt and "November" in prompt and chosen[0]["name"] in prompt
    assert "Benutze keine Werkzeuge" in prompt

    # an answer without a known recipe: the rules plan, the AI result says why
    _fake_task(hass, {"data": {"order": ["erfunden"]}})
    result = await _call(hass, "auto_plan", start_date="2026-11-10", days=2, ai=True)
    assert result["ai"]["ok"] is False and result["ai"]["code"] == "ai_invalid"
    assert len(result["planned"]) == 2
    # the AI fails
    _fake_task(hass, HomeAssistantError("kaputt"))
    result = await _call(hass, "auto_plan", start_date="2026-11-12", days=1, ai=True)
    assert result["ai"]["code"] == "ai_failed" and len(result["planned"]) == 1
    # the feature is off
    await _use(hass, setup_integration, **{CONF_AI_FEATURES: ["occasions"]})
    result = await _call(hass, "auto_plan", start_date="2026-11-13", days=1, ai=True)
    assert result["ai"]["code"] == "ai_feature_off" and len(result["planned"]) == 1


async def test_auto_plan_ai_not_configured(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Without an AI entity the rules plan alone."""
    result = await _call(hass, "auto_plan", days=1, ai=True)
    assert result["ai"]["code"] == "ai_not_configured"
    assert len(result["planned"]) == 1


async def test_ordered_pick_avoids_the_same_kind(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """With an order, a slot gets the first fitting recipe – of another kind than the day
    before when the order has one; drinks and excluded recipes never."""
    manager = setup_integration.runtime_data
    names = [
        "Glühwein",
        "Spaghetti Bolognese",
        "Penne all'arrabbiata",
        "Kürbissuppe",
        "Linsensuppe",
    ]
    order = [manager.get_recipe_by_name(n)["id"] for n in names]
    planned = manager.auto_plan(TODAY, 3, order=order)
    assert [p["title"] for p in planned] == [
        "Spaghetti Bolognese",
        "Kürbissuppe",  # no pasta two days in a row
        "Penne all'arrabbiata",
    ]


def test_parse_ai_order() -> None:
    """Ids or names, in order, each once; other answers give nothing."""
    candidates = [{"id": "a", "name": "Kürbissuppe"}, {"id": "b", "name": "Linsensuppe"}]
    assert sea.parse_ai_order({"order": ["b", "kürbissuppe", "b", "x"]}, candidates) == ["b", "a"]
    assert sea.parse_ai_order([{"id": "a"}, {"name": "Linsensuppe"}], candidates) == ["a", "b"]
    assert sea.parse_ai_order({"plan": [{"recipe_id": "b"}]}, candidates) == ["b"]
    assert sea.parse_ai_order({"foo": 1}, candidates) == []
    assert sea.parse_ai_order("text", candidates) == []


# ----------------------------------------------------------------------
# Websocket, data export, occasions and the intent
# ----------------------------------------------------------------------


async def test_ws_season_and_data(
    hass: HomeAssistant, setup_integration: MockConfigEntry, hass_ws_client
) -> None:
    """essensplaner/season: the season of a day with the best fitting recipes;
    essensplaner/data: season and recipe_season."""
    manager = setup_integration.runtime_data
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/season"})
    result = (await client.receive_json())["result"]
    assert result["date"] == TODAY.isoformat() and result["season_aware"] is True
    assert result["recipes"][0]["name"] == "Gänsekeulen mit Rotkohl und Klößen"
    scores = [r["score"] for r in result["recipes"]]
    assert scores == sorted(scores, reverse=True) and len(scores) == 12
    assert "Spargel mit Sauce Hollandaise und Kartoffeln" in {
        r["name"] for r in result["out_of_season"]
    }
    await client.send_json({"id": 2, "type": f"{DOMAIN}/season", "date": "24.12.", "limit": 3})
    christmas = (await client.receive_json())["result"]
    assert [w["id"] for w in christmas["windows"]] == ["weihnachten"]
    assert len(christmas["recipes"]) == 3
    assert "weihnachten" in christmas["recipes"][0]["windows"]
    await client.send_json({"id": 3, "type": f"{DOMAIN}/season", "date": "Blumenkohltag"})
    error = await client.receive_json()
    assert not error["success"] and error["error"]["code"] == "invalid_date"

    data = manager.export()
    assert data["season"]["season"]["label"] == "Herbst" and data["season"]["season_aware"]
    soup = manager.get_recipe_by_name("Kürbissuppe")
    assert data["recipe_season"][soup["id"]]["items"] == ["Kürbis"]
    bolognese = manager.get_recipe_by_name("Spaghetti Bolognese")
    assert bolognese["id"] not in data["recipe_season"]
    asparagus = manager.get_recipe_by_name("Spargel mit Sauce Hollandaise und Kartoffeln")
    assert data["recipe_season"][asparagus["id"]]["out"] == ["Spargel"]


async def test_recipe_season_is_fast(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The season of all starter recipes takes little CPU time (a Raspberry Pi), the
    second time it comes from the cache."""
    manager = setup_integration.runtime_data
    manager.__dict__.pop("_season_cache", None)
    start = time.process_time()
    sea.recipe_season_export(manager)
    cold = time.process_time() - start
    start = time.process_time()
    for _ in range(10):
        sea.recipe_season_export(manager)
    assert cold < 0.5
    assert (time.process_time() - start) / 10 < 0.05


async def test_occasion_suggestions_name_the_season(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Occasion suggestions get the season weight and its reasons ("🎄 Weihnachten")."""
    from custom_components.essensplaner import occasions as occ

    manager = setup_integration.runtime_data
    occasion = occ.create_occasion(manager, "weihnachten", "Heiligabend", guests=4)
    mains = occ.suggest_course(manager, occasion, "main", 5)
    goose = next(s for s in mains if s["title"] == "Gänsekeulen mit Rotkohl und Klößen")
    assert "🎄 Weihnachten" in goose["reasons"]


async def test_get_season_intent(hass: HomeAssistant, setup_integration: MockConfigEntry) -> None:
    """ "Was hat gerade Saison?" – produce, the time of the year and fitting recipes."""
    response = await _speech(hass, "essensplaner_get_season")
    speech = response.speech["plain"]["speech"]
    assert speech.startswith("Gerade hat Saison: ")
    assert "Kürbis" in speech and "Es ist Martinstag." in speech
    assert "Gänsekeulen mit Rotkohl und Klößen" in speech
    assert response.speech_slots["season"] == "Herbst"
    may = (await _speech(hass, "essensplaner_get_season", month="Mai")).speech["plain"]["speech"]
    assert may.startswith("Im Mai hat Saison: ") and "Spargel" in may
    christmas = await _speech(hass, "essensplaner_get_season", date="Heiligabend")
    assert "Es ist Weihnachten." in christmas.speech["plain"]["speech"]
    unknown = await _speech(hass, "essensplaner_get_season", month="Brumaire")
    assert unknown.response_type == intent.IntentResponseType.ERROR
    assert "Brumaire" in unknown.speech["plain"]["speech"]
    # a month that has passed this year: next year's
    march = await _speech(hass, "essensplaner_get_season", month="März")
    assert march.speech_slots["date"] == "2027-03-15"
