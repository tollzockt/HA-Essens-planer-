"""AI via Home Assistant (1.5, ai.py): AI Task entities (ai_task.generate_data) and
conversation agents (conversation.process), single flight, cache, payload cap, errors, the
recursion guard of the intents, the connection test, the settings and the receipt photo
fallback. The AI is always faked (registered services or a fake conversation entity)."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import json
from typing import Any

from homeassistant.components import conversation
from homeassistant.components.conversation.const import DATA_COMPONENT
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import intent
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.essensplaner import ai, receipts
from custom_components.essensplaner.const import DOMAIN
from custom_components.essensplaner.diagnostics import async_get_config_entry_diagnostics
from custom_components.essensplaner.intents import INTENT_GET_MEALS
from custom_components.essensplaner.manager import ERROR_MESSAGES_DE

TASK = "ai_task.koch"
AGENT = "conversation.jarvis"
DRINKS = {"drinks": [{"title": "Apfelschorle", "alcohol": False}]}
PAYLOAD = {"recipes": [{"id": "r1", "name": "Lasagne", "tags": ["Pasta"]}], "month": 11}


def _fake_task(hass: HomeAssistant, answer: Any, state: str = "unknown") -> list[dict[str, Any]]:
    """A fake ai_task.generate_data (answer: response, exception or coroutine function)."""
    calls: list[dict[str, Any]] = []

    async def handler(call: ServiceCall) -> Any:
        calls.append(dict(call.data))
        if isinstance(answer, BaseException):
            raise answer
        if callable(answer):
            return await answer(call)
        return answer

    hass.services.async_register(
        "ai_task", "generate_data", handler, supports_response=SupportsResponse.ONLY
    )
    hass.states.async_set(TASK, state, {"friendly_name": "Koch-KI"})
    return calls


def _speech(text: str, response_type: str = "action_done") -> dict[str, Any]:
    """What conversation.process returns (ConversationResult.as_dict())."""
    return {
        "response": {
            "speech": {"plain": {"speech": text, "extra_data": None}},
            "card": {},
            "language": "de",
            "response_type": response_type,
            "data": {"targets": [], "success": [], "failed": []},
        },
        "conversation_id": "01JTEST",
        "continue_conversation": False,
    }


def _fake_agent(hass: HomeAssistant, answer: Any) -> list[dict[str, Any]]:
    """A fake conversation.process service (the agent answers with speech text)."""
    calls: list[dict[str, Any]] = []

    async def handler(call: ServiceCall) -> Any:
        calls.append(dict(call.data))
        if isinstance(answer, BaseException):
            raise answer
        return answer

    hass.services.async_register(
        "conversation", "process", handler, supports_response=SupportsResponse.OPTIONAL
    )
    hass.states.async_set(AGENT, "unknown", {"friendly_name": "Jarvis"})
    return calls


async def _use(hass: HomeAssistant, entry: MockConfigEntry, **options: Any) -> Any:
    """Set options (reloads the entry) and return the new manager."""
    hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
    await hass.async_block_till_done()
    return entry.runtime_data


async def _ask(hass: HomeAssistant, manager: Any, feature: str = "drinks", **kw: Any) -> Any:
    return await ai.async_ai_json(
        hass,
        manager,
        feature,
        kw.pop("task_name", "Essensplaner Getränke"),
        kw.pop("instructions", 'Schlage Getränke vor: {"drinks": [{"title", "alcohol"}]}.'),
        kw.pop("payload", PAYLOAD),
        **kw,
    )


async def _code(coro: Any) -> str:
    with pytest.raises(ServiceValidationError) as err:
        await coro
    return str(err.value.translation_key)


# ----------------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------------


async def test_entities_and_features(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The AI entity serves every feature; receipt photos take their own option, else the
    AI entity only when it is an AI Task (a conversation agent cannot read images)."""
    entry = setup_integration
    manager = entry.runtime_data
    assert ai.ai_mode(TASK) == "ai_task" and ai.ai_mode(AGENT) == "conversation"
    assert ai.ai_mode("light.kueche") is None and ai.ai_mode("ai_task") is None
    assert ai.ai_mode(None) is None
    assert ai.ai_entity(manager) is None and not ai.ai_enabled(manager, "drinks")
    assert ai.ai_features(manager) == ["occasions", "drinks", "season", "receipts"]

    manager = await _use(hass, entry, ai_entity=AGENT)
    assert ai.ai_entity(manager, "occasions") == AGENT
    assert ai.ai_enabled(manager, "occasions")
    assert not ai.ai_enabled(manager, "products")  # off by default
    assert ai.ai_entity(manager, "receipts") is None
    assert receipts.ai_entity(manager) is None

    manager = await _use(hass, entry, ai_entity=TASK)
    assert ai.ai_entity(manager, "receipts") == TASK
    assert receipts.ai_entity(manager) == TASK  # 1.5: fallback for receipt photos
    manager = await _use(hass, entry, receipt_ai_task_entity="ai_task.bon_leser")
    assert receipts.ai_entity(manager) == "ai_task.bon_leser"  # the own option wins
    assert ai.ai_entity(manager, "drinks") == TASK

    # all features off: an empty selection stays empty
    manager = await _use(hass, entry, ai_features=[])
    assert ai.ai_features(manager) == []
    assert not ai.ai_enabled(manager, "drinks")
    assert receipts.ai_entity(manager) is None
    assert receipts.ai_entity(manager, "ai_task.anders") == "ai_task.anders"  # explicit


async def test_status(hass: HomeAssistant, setup_integration: MockConfigEntry) -> None:
    """ai_status: entity, kind, availability, features and readiness per feature."""
    manager = setup_integration.runtime_data
    status = ai.ai_status(hass, manager)
    assert status["configured"] is False and status["available"] is False
    assert status["ready"] == {
        f: False for f in ("occasions", "drinks", "season", "products", "receipts")
    }
    _fake_agent(hass, _speech("{}"))
    manager = await _use(hass, setup_integration, ai_entity=AGENT, ai_features=["drinks"])
    status = ai.ai_status(hass, manager)
    assert status["entity"] == AGENT and status["mode"] == "conversation"
    assert status["label"] == "Jarvis" and status["available"] is True
    assert status["features"] == ["drinks"]
    assert status["ready"]["drinks"] is True and status["ready"]["occasions"] is False
    assert status["ready"]["receipts"] is False and status["receipts_entity"] is None
    assert status["busy"] is False and status["last"] is None
    hass.states.async_set(AGENT, "unavailable")
    assert ai.ai_status(hass, manager)["ready"]["drinks"] is False


# ----------------------------------------------------------------------------------
# Both modes
# ----------------------------------------------------------------------------------


async def test_ai_task_mode_and_cache(
    hass: HomeAssistant, setup_integration: MockConfigEntry, freezer
) -> None:
    """An AI Task gets task name, entity and the prompt (instructions, compact JSON data,
    "no tools, JSON only"); the JSON answer comes back and is reused for 10 minutes."""
    calls = _fake_task(
        hass, {"conversation_id": "1", "data": f"```json\n{json.dumps(DRINKS)}\n```"}
    )
    manager = await _use(hass, setup_integration, ai_entity=TASK)
    assert await _ask(hass, manager) == DRINKS
    assert len(calls) == 1
    call = calls[0]
    assert sorted(call) == ["entity_id", "instructions", "task_name"]  # no attachments
    assert call["task_name"] == "Essensplaner Getränke" and call["entity_id"] == TASK
    prompt = call["instructions"]
    assert prompt.startswith("Schlage Getränke vor")
    assert json.dumps(PAYLOAD, ensure_ascii=False, separators=(",", ":")) in prompt
    assert prompt.endswith("Benutze keine Werkzeuge. Antworte nur mit JSON.")
    # cached: the same request does not ask again; the answer is a copy
    answer = await _ask(hass, manager)
    answer["drinks"].clear()
    assert await _ask(hass, manager) == DRINKS
    assert len(calls) == 1
    # other data or another feature ask again
    await _ask(hass, manager, payload={**PAYLOAD, "month": 12})
    await _ask(hass, manager, feature="occasions")
    assert len(calls) == 3
    # after 10 minutes the answer is fetched again
    freezer.tick(timedelta(minutes=10, seconds=1))
    await _ask(hass, manager)
    assert len(calls) == 4
    # a structured answer (object instead of text) is taken as it is
    _fake_task(hass, {"data": {"menu": ["Gulasch"]}})
    assert await _ask(hass, manager, payload={"x": 1}) == {"menu": ["Gulasch"]}
    last = ai.ai_status(hass, manager)["last"]
    assert last["ok"] is True and last["mode"] == "ai_task" and last["feature"] == "drinks"
    assert "prompt" not in last and "answer" not in last


async def test_conversation_mode(hass: HomeAssistant, setup_integration: MockConfigEntry) -> None:
    """A conversation agent gets the prompt as text, in German, in a new conversation; the
    JSON is read from its spoken answer, also with text around it."""
    calls = _fake_agent(hass, _speech(f"Gern! Hier die Vorschläge:\n{json.dumps(DRINKS)}\nProst!"))
    manager = await _use(hass, setup_integration, ai_entity=AGENT)
    assert await _ask(hass, manager) == DRINKS
    assert len(calls) == 1
    assert sorted(calls[0]) == ["agent_id", "language", "text"]  # no conversation_id
    assert calls[0]["agent_id"] == AGENT and calls[0]["language"] == "de"
    assert calls[0]["text"].endswith(ai.NO_TOOLS)
    # an error answer of the agent
    _fake_agent(hass, _speech("Ich habe keine Verbindung zum Modell.", "error"))
    err = await _code(_ask(hass, manager, payload={"a": 1}))
    assert err == "ai_failed"
    # an answer without JSON
    _fake_agent(hass, _speech("Zur Lasagne passt ein Rotwein."))
    assert await _code(_ask(hass, manager, payload={"a": 2})) == "ai_invalid"


async def test_real_conversation_agent_and_recursion_guard(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """With Home Assistant's real conversation.process and a conversation entity: the agent
    gets the prompt in German, and an Essensplaner intent it calls as a tool meanwhile is
    refused (it would ask the Essensplaner, and so itself, again). Outside an AI request
    the intent works."""
    assert await async_setup_component(hass, "conversation", {})
    seen: dict[str, Any] = {}

    class FakeAgent(conversation.ConversationEntity):
        _attr_name = "Jarvis"
        _attr_unique_id = "jarvis"

        @property
        def supported_languages(self) -> str:
            return "*"

        async def async_process(
            self, user_input: conversation.ConversationInput
        ) -> conversation.ConversationResult:
            seen["language"] = user_input.language
            seen["conversation_id"] = user_input.conversation_id
            seen["active"] = ai.AI_ACTIVE.get()
            tool = await intent.async_handle(hass, "llm", INTENT_GET_MEALS, {})
            seen["tool"] = tool
            response = intent.IntentResponse(language=user_input.language)
            response.async_set_speech(json.dumps(DRINKS))
            return conversation.ConversationResult(response=response)

    await hass.data[DATA_COMPONENT].async_add_entities([FakeAgent()])
    await hass.async_block_till_done()
    assert hass.states.get(AGENT) is not None
    manager = await _use(hass, setup_integration, ai_entity=AGENT)
    assert ai.ai_available(hass, AGENT)
    assert await _ask(hass, manager) == DRINKS
    assert seen["language"] == "de" and seen["conversation_id"] is None
    assert seen["active"] is True
    tool = seen["tool"]
    assert tool.response_type == intent.IntentResponseType.ERROR
    assert tool.speech["plain"]["speech"] == ai.AI_REFUSED_DE
    assert ai.AI_ACTIVE.get() is False
    normal = await intent.async_handle(hass, "test", INTENT_GET_MEALS, {})
    assert normal.response_type != intent.IntentResponseType.ERROR


# ----------------------------------------------------------------------------------
# Errors, busy, timeout
# ----------------------------------------------------------------------------------


async def test_errors(hass: HomeAssistant, setup_integration: MockConfigEntry, freezer) -> None:
    """Clear German errors: not configured, feature off, unavailable, failing service,
    timeout, no JSON."""
    manager = setup_integration.runtime_data
    assert await _code(_ask(hass, manager)) == "ai_not_configured"
    manager = await _use(hass, setup_integration, ai_entity=TASK)
    assert await _code(_ask(hass, manager)) == "ai_unavailable"  # no AI Task service
    with pytest.raises(ServiceValidationError) as err:
        await _ask(hass, manager, feature="products")
    assert err.value.translation_key == "ai_feature_off"
    assert err.value.translation_placeholders == {"feature": "Produktzuordnung"}
    with pytest.raises(ValueError):
        await _ask(hass, manager, feature="telepathie")
    _fake_task(hass, {"data": "{}"}, state="unavailable")
    assert await _code(_ask(hass, manager)) == "ai_unavailable"
    _fake_task(hass, HomeAssistantError("Modell nicht geladen"))
    with pytest.raises(ServiceValidationError) as err:
        await _ask(hass, manager)
    assert err.value.translation_key == "ai_failed"
    assert err.value.translation_placeholders == {"entity": TASK, "error": "Modell nicht geladen"}
    _fake_task(hass, {"data": "Ich weiß es leider nicht."})
    assert await _code(_ask(hass, manager)) == "ai_invalid"
    status = ai.ai_status(hass, manager)
    assert status["last"]["ok"] is False and status["last"]["code"] == "ai_invalid"

    started = asyncio.Event()

    async def slow(call: ServiceCall) -> Any:
        started.set()
        await asyncio.Event().wait()

    _fake_task(hass, slow)
    pending = hass.async_create_task(_ask(hass, manager, timeout=30))
    await started.wait()
    freezer.tick(timedelta(seconds=31))  # the clock is frozen: move it past the limit
    with pytest.raises(ServiceValidationError) as err:
        await pending
    assert err.value.translation_key == "ai_failed"
    assert err.value.translation_placeholders["error"] == "keine Antwort nach 30 s"
    assert ai.AI_ACTIVE.get() is False
    # every error has a German text with the placeholders the code gives
    for key in ("ai_not_configured", "ai_unavailable", "ai_failed", "ai_invalid"):
        assert key in ERROR_MESSAGES_DE
    assert "Produktzuordnung" in ERROR_MESSAGES_DE["ai_feature_off"].format(
        feature="Produktzuordnung"
    )


async def test_single_flight(hass: HomeAssistant, setup_integration: MockConfigEntry) -> None:
    """One request at a time: the same request waits for the running answer (one call),
    another one gets ai_busy – also the connection test."""
    release = asyncio.Event()
    started = asyncio.Event()

    async def answer(call: ServiceCall) -> Any:
        started.set()
        await release.wait()
        return {"data": json.dumps(DRINKS)}

    calls = _fake_task(hass, answer)
    manager = await _use(hass, setup_integration, ai_entity=TASK)
    first = hass.async_create_task(_ask(hass, manager))
    await started.wait()
    same = hass.async_create_task(_ask(hass, manager))
    await asyncio.sleep(0)
    assert ai.ai_status(hass, manager)["busy"] is True
    assert await _code(_ask(hass, manager, payload={"other": True})) == "ai_busy"
    test = await ai.async_ai_test(hass, manager)
    assert test["ok"] is False and test["code"] == "ai_busy"
    release.set()
    assert await first == DRINKS
    assert await same == DRINKS
    assert len(calls) == 1
    assert ai.ai_status(hass, manager)["busy"] is False
    # a failing request fails the waiting one too, and frees the lock
    release.clear()
    started.clear()

    async def failing(call: ServiceCall) -> Any:
        started.set()
        await release.wait()
        raise HomeAssistantError("kaputt")

    _fake_task(hass, failing)
    first = hass.async_create_task(_ask(hass, manager, payload={"n": 1}))
    await started.wait()
    same = hass.async_create_task(_ask(hass, manager, payload={"n": 1}))
    await asyncio.sleep(0)
    release.set()
    assert await _code(first) == "ai_failed"
    assert await _code(same) == "ai_failed"
    assert not ai.ai_status(hass, manager)["busy"]


# ----------------------------------------------------------------------------------
# Payload and privacy
# ----------------------------------------------------------------------------------


def test_payload_cap() -> None:
    """Payloads are compact JSON of at most 12000 characters: long lists and texts are
    shortened, the caller's data stays as it is."""
    payload = {
        "recipes": [{"id": f"r{i}", "name": f"Rezept {i}", "tags": ["Pasta"]} for i in range(5000)],
        "month": 11,
    }
    text = ai.payload_json(payload)
    assert len(text) <= ai.PAYLOAD_MAX
    data = json.loads(text)
    assert data["month"] == 11 and 1 <= len(data["recipes"]) < 5000
    assert data["recipes"][0] == {"id": "r0", "name": "Rezept 0", "tags": ["Pasta"]}
    assert len(payload["recipes"]) == 5000
    assert ai.payload_json({"a": 1}) == '{"a":1}'
    long_text = ai.payload_json({"note": "x" * 50000})
    assert len(long_text) <= ai.PAYLOAD_MAX and json.loads(long_text)["note"].startswith("x")
    assert ai.payload_json({"a": "ä"}) == '{"a":"ä"}'


def test_extract_json() -> None:
    """The answer parser (moved from receipts.py; receipts imports it from ai.py)."""
    assert receipts.extract_json is ai.extract_json
    assert ai.extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert ai.extract_json('Gern: {"a": [1, 2,], "b": "x}"} – guten Appetit!') == {
        "a": [1, 2],
        "b": "x}",
    }
    assert ai.extract_json("[1, 2]") == [1, 2]
    with pytest.raises(ValueError):
        ai.extract_json("Ich kann das leider nicht.")
    with pytest.raises(ValueError):
        ai.extract_json('{"items": [')


async def test_privacy(hass: HomeAssistant, setup_integration: MockConfigEntry) -> None:
    """Only the given payload and instructions go to the AI – no stores, postcodes,
    options or notes of the user; the diagnostics show the AI kind and state, never the
    entity, prompts or answers."""
    manager = setup_integration.runtime_data
    manager.save_branch({"store": "Lidl", "street": "Lindenweg 1", "postcode": "12345"})
    calls = _fake_task(hass, {"data": json.dumps(DRINKS)})
    manager = await _use(hass, setup_integration, ai_entity=TASK, zip_code="12345")
    await _ask(hass, manager)
    sent = json.dumps(calls)
    for private in ("12345", "Lindenweg", "Musterstadt", "Salz, Pfeffer", "zip_code"):
        assert private not in sent, private
    diagnostics = await async_get_config_entry_diagnostics(hass, setup_integration)
    info = diagnostics["ai"]
    assert info["configured"] is True and info["mode"] == "ai_task"
    assert info["last"] == {
        "ok": True,
        "seconds": 0.0,
        "mode": "ai_task",
        "feature": "drinks",
        "code": None,
    }
    text = json.dumps(diagnostics["ai"])
    assert "Schlage" not in text and "Apfelschorle" not in text and TASK not in text


# ----------------------------------------------------------------------------------
# Connection test and websockets
# ----------------------------------------------------------------------------------


async def test_connection_test(hass: HomeAssistant, setup_integration: MockConfigEntry) -> None:
    """ "Verbindung testen": a tiny request to the given (or configured) entity; the
    result says ok, the kind and the seconds, or the German error."""
    manager = setup_integration.runtime_data
    result = await ai.async_ai_test(hass, manager)
    assert result["ok"] is False and result["code"] == "ai_not_configured"
    assert result["error"] == ERROR_MESSAGES_DE["ai_not_configured"]
    result = await ai.async_ai_test(hass, manager, "light.kueche")
    assert result["code"] == "ai_not_configured"
    result = await ai.async_ai_test(hass, manager, AGENT)
    assert result["code"] == "ai_unavailable" and AGENT in result["error"]
    calls = _fake_agent(hass, _speech('{"ok": true}'))
    result = await ai.async_ai_test(hass, manager, AGENT)  # not saved yet: works too
    assert result == {
        "ok": True,
        "entity": AGENT,
        "mode": "conversation",
        "seconds": 0.0,
        "code": None,
        "error": None,
    }
    assert calls[0]["text"].endswith(ai.NO_TOOLS)
    task_calls = _fake_task(hass, {"data": '{"ok": true}'})
    manager = await _use(hass, setup_integration, ai_entity=TASK, ai_features=[])
    result = await ai.async_ai_test(hass, manager)  # features do not matter
    assert result["ok"] is True and result["mode"] == "ai_task"
    assert task_calls[0]["task_name"] == "Essensplaner Verbindungstest"
    # not cached: every test asks
    await ai.async_ai_test(hass, manager)
    assert len(task_calls) == 2
    _fake_task(hass, {"data": "Hallo!"})
    result = await ai.async_ai_test(hass, manager)
    assert result["ok"] is False and result["code"] == "ai_invalid"
    assert result["error"] == ERROR_MESSAGES_DE["ai_invalid"].format(entity=TASK)


async def test_websockets(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    hass_ws_client,
    hass_read_only_access_token,
) -> None:
    """essensplaner/ai_status and essensplaner/ai_test (admins)."""
    _fake_agent(hass, _speech('{"ok": true}'))
    await _use(hass, setup_integration, ai_entity=AGENT)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/ai_status"})
    msg = await client.receive_json()
    assert msg["success"], msg
    assert msg["result"]["entity"] == AGENT and msg["result"]["available"] is True
    await client.send_json({"id": 2, "type": f"{DOMAIN}/ai_test"})
    msg = await client.receive_json()
    assert msg["success"] and msg["result"]["ok"] is True
    assert msg["result"]["mode"] == "conversation"
    await client.send_json({"id": 3, "type": f"{DOMAIN}/ai_test", "entity_id": TASK})
    msg = await client.receive_json()
    assert msg["success"] and msg["result"]["ok"] is False
    assert msg["result"]["code"] == "ai_unavailable"
    await client.send_json({"id": 4, "type": f"{DOMAIN}/ai_status"})
    msg = await client.receive_json()
    assert msg["result"]["last"]["ok"] is True  # unavailable entities are not "last"
    reader = await hass_ws_client(hass, hass_read_only_access_token)
    for number, kind in ((1, "ai_status"), (2, "ai_test")):
        await reader.send_json({"id": number, "type": f"{DOMAIN}/{kind}"})
        msg = await reader.receive_json()
        assert not msg["success"] and msg["error"]["code"] == "unauthorized"


async def test_settings_save_ai(
    hass: HomeAssistant, setup_integration: MockConfigEntry, hass_ws_client
) -> None:
    """The panel stores the AI entity (AI Task or conversation agent) and the features; an
    emptied picker removes the option; wrong entities get a German error; an unreachable
    AI entity gets a hint."""
    entry = setup_integration
    client = await hass_ws_client(hass)

    async def save(number: int, **values: Any) -> dict[str, Any]:
        await client.send_json({"id": number, "type": f"{DOMAIN}/save_settings", "values": values})
        msg = await client.receive_json()
        assert msg["success"], msg
        await hass.async_block_till_done()
        return msg["result"]

    result = await save(1, ai_entity=AGENT, ai_features=["drinks", "products"])
    assert result == {"saved": True, "reload": True}
    assert entry.options["ai_entity"] == AGENT
    assert entry.options["ai_features"] == ["drinks", "products"]
    await client.send_json({"id": 2, "type": f"{DOMAIN}/get_settings"})
    msg = await client.receive_json()
    assert msg["result"]["values"]["ai_entity"] == AGENT
    warning = next(w for w in msg["result"]["warnings"] if w["key"] == "ai_entity")
    assert "nicht erreichbar" in warning["message"]
    assert msg["result"]["choices"]["ai_entities"][-1] == {
        "value": AGENT,
        "label": AGENT,
        "available": False,
        "kind": "conversation",
        "missing": True,
    }
    result = await save(3, ai_entity="light.kueche")
    assert result["saved"] is False
    assert result["errors"] == {
        "ai_entity": "Bitte eine KI-Aufgabe (ai_task) oder einen Gesprächsagenten wählen."
    }
    result = await save(4, ai_entity="", ai_features=[])
    assert result == {"saved": True, "reload": True}
    assert "ai_entity" not in entry.options
    assert entry.options["ai_features"] == []


# ----------------------------------------------------------------------------------
# Receipt photos
# ----------------------------------------------------------------------------------


async def test_receipt_photo_fallback(
    hass: HomeAssistant, setup_integration: MockConfigEntry, tmp_path
) -> None:
    """Receipt photos use the AI entity when it is an AI Task and no receipt option is set;
    switched off in the features, a photo gets ai_feature_off; the AI Task call runs with
    the recursion guard."""
    hass.config.media_dirs = {"local": str(tmp_path / "media")}
    seen: dict[str, Any] = {}

    async def answer(call: ServiceCall) -> Any:
        seen["active"] = ai.AI_ACTIVE.get()
        seen["entity"] = call.data["entity_id"]
        return {"data": "kein Kassenzettel"}

    _fake_task(hass, answer)
    manager = await _use(hass, setup_integration, ai_entity=TASK)
    upload = await manager.receipts.async_add_upload(
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 200, "image/jpeg"
    )
    assert (
        await _code(
            hass.services.async_call(
                DOMAIN,
                "receipt_scan",
                {"upload_id": upload["id"]},
                blocking=True,
                return_response=True,
            )
        )
        == "receipt_ai_invalid"
    )
    assert seen == {"active": True, "entity": TASK}
    assert ai.AI_ACTIVE.get() is False
    manager = await _use(hass, setup_integration, ai_features=["drinks"])
    upload = await manager.receipts.async_add_upload(
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 200, "image/jpeg"
    )
    assert (
        await _code(
            hass.services.async_call(
                DOMAIN,
                "receipt_scan",
                {"upload_id": upload["id"]},
                blocking=True,
                return_response=True,
            )
        )
        == "ai_feature_off"
    )
    # a conversation agent cannot read photos
    manager = await _use(hass, setup_integration, ai_entity=AGENT, ai_features=["receipts"])
    assert (
        await _code(
            hass.services.async_call(
                DOMAIN,
                "receipt_scan",
                {"upload_id": upload["id"]},
                blocking=True,
                return_response=True,
            )
        )
        == "receipt_ai_not_configured"
    )
