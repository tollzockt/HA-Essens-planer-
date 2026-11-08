"""AI via Home Assistant (1.5): an AI Task entity or a conversation agent answers in JSON.

Rules first, AI optional: every feature works without AI; the AI only reorders or extends
proposals the rules made, and the callers validate its answers. The Essensplaner keeps no
API keys – it calls Home Assistant's ai_task.generate_data (AI Task entities, e.g. of the
Anthropic, OpenAI, Google Gemini or Ollama integrations) or conversation.process
(conversation agents such as an LLM voice assistant; every request is a new conversation).

Safety and size:
- one request at a time per manager: a different request meanwhile gets ai_busy, the same
  one waits for the running answer; answers are cached for 10 minutes (feature, entity and
  prompt);
- payloads are compact JSON of at most PAYLOAD_MAX characters (the longest lists are
  shortened until it fits);
- AI_ACTIVE is set while a request runs: the Essensplaner intents refuse tool calls in that
  context, so an agent cannot call the Essensplaner (and so itself) again; every prompt
  ends with NO_TOOLS;
- privacy: callers send only recipe ids/names/tags, ingredient keys, chain names (no
  branch labels, addresses or postcodes), offer products and prices, month/season, guest
  counts and dietary exclusions – never notes, receipts or user names. Prompts and answers
  are never logged above debug level and never put into the diagnostics.

Receipt photos need attachments, which only AI Tasks take: receipts.py uses ai_entity(…,
"receipts") (its own option, else the AI entity when that is an AI Task).
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
import copy
from dataclasses import dataclass, field
import hashlib
import json
import logging
import re
import time
from typing import TYPE_CHECKING, Any

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .const import (
    AI_FEATURE_RECEIPTS,
    AI_FEATURES,
    CONF_AI_ENTITY,
    CONF_AI_FEATURES,
    CONF_RECEIPT_AI,
    DEFAULT_AI_FEATURES,
)
from .options_schema import CHOICE_LABELS_DE

if TYPE_CHECKING:
    from .manager import EssensplanerManager

_LOGGER = logging.getLogger(__name__)

MODE_AI_TASK = "ai_task"
MODE_CONVERSATION = "conversation"
AI_MODES = (MODE_AI_TASK, MODE_CONVERSATION)
# Home Assistant's own agent only matches sentences to intents – it cannot answer in JSON
BUILTIN_AGENT = "conversation.home_assistant"

AI_TIMEOUT = 120  # seconds per request (a local model on a small machine is slow)
TEST_TIMEOUT = 60
CACHE_TTL = 600  # seconds an answer is reused
CACHE_MAX = 32
PAYLOAD_MAX = 12000  # characters of the JSON payload
ERROR_TEXT_MAX = 160
NO_TOOLS = "Benutze keine Werkzeuge. Antworte nur mit JSON."
# the answer of an Essensplaner intent called by an agent during an Essensplaner AI request
AI_REFUSED_DE = (
    "Während einer Essensplaner-KI-Anfrage nicht möglich – bitte ohne Werkzeuge nur mit "
    "JSON antworten."
)
TEST_TASK_NAME = "Essensplaner Verbindungstest"
TEST_INSTRUCTIONS = (
    "Verbindungstest des Essensplaners. Antworte genau mit diesem JSON-Objekt und sonst "
    'nichts: {"ok": true}'
)
FEATURE_LABELS_DE: dict[str, str] = CHOICE_LABELS_DE["ai_feature"]

# True while an Essensplaner AI request runs in this context (tasks started from it, such
# as the tool calls of a conversation agent, inherit it)
AI_ACTIVE: ContextVar[bool] = ContextVar("essensplaner_ai_active", default=False)


@dataclass
class AiState:
    """Lock, cache and last result of the AI requests of one manager."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    cache: dict[str, tuple[float, Any]] = field(default_factory=dict)
    inflight: tuple[str, asyncio.Future[Any]] | None = None
    last: dict[str, Any] | None = None


def _state(manager: EssensplanerManager) -> AiState:
    """The AI state of a manager (created on first use; a reload starts empty)."""
    state = manager.__dict__.get("_ai_state")
    if state is None:
        state = AiState()
        manager.__dict__["_ai_state"] = state
    return state


def _error(key: str, **placeholders: Any) -> ServiceValidationError:
    from .manager import _error as error  # the manager imports the mixins that import this

    return error(key, **placeholders)


# ----------------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------------


def ai_mode(entity_id: str | None) -> str | None:
    """ "ai_task" or "conversation" for an AI entity id, else None."""
    domain, dot, name = str(entity_id or "").partition(".")
    return domain if dot and name and domain in AI_MODES else None


def ai_features(manager: EssensplanerManager) -> list[str]:
    """The AI features switched on in the settings (default: all except products)."""
    raw = manager.options.get(CONF_AI_FEATURES)
    chosen = raw if isinstance(raw, (list, tuple)) else DEFAULT_AI_FEATURES
    return [f for f in AI_FEATURES if f in chosen]


def ai_entity(manager: EssensplanerManager, feature: str | None = None) -> str | None:
    """The configured AI entity of a feature (switched on or not).

    Receipt photos: the receipt option (an AI Task), else the AI entity when it is an AI
    Task – a conversation agent cannot read images. Everything else: the AI entity."""
    options = manager.options
    general = options.get(CONF_AI_ENTITY) or None
    if ai_mode(general) is None:
        general = None
    if feature == AI_FEATURE_RECEIPTS:
        if own := options.get(CONF_RECEIPT_AI) or None:
            return str(own)
        return general if ai_mode(general) == MODE_AI_TASK else None
    return general


def ai_enabled(manager: EssensplanerManager, feature: str) -> bool:
    """True if the feature is switched on and has an AI entity (available or not)."""
    return feature in ai_features(manager) and ai_entity(manager, feature) is not None


def ai_available(hass: HomeAssistant, entity_id: str | None) -> bool:
    """True if the entity exists, is not unavailable and its service is registered."""
    mode = ai_mode(entity_id)
    if mode is None:
        return False
    service = "generate_data" if mode == MODE_AI_TASK else "process"
    if not hass.services.has_service(mode, service):
        return False
    state = hass.states.get(str(entity_id))
    return state is not None and state.state != STATE_UNAVAILABLE


def _label(hass: HomeAssistant, entity_id: str | None) -> str | None:
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    return str(state.attributes.get("friendly_name") or entity_id) if state else entity_id


def entity_choices(hass: HomeAssistant, current: str | None = None) -> list[dict[str, Any]]:
    """[{value, label, available, kind}] of the AI Tasks and conversation agents (AI Tasks
    first; not Home Assistant's own agent). A chosen entity that does not exist any more is
    listed too (missing), so it can be seen and removed."""
    result: list[dict[str, Any]] = []
    for kind in AI_MODES:
        found = [
            {
                "value": state.entity_id,
                "label": str(state.attributes.get("friendly_name") or state.entity_id),
                "available": state.state != STATE_UNAVAILABLE,
                "kind": kind,
            }
            for state in hass.states.async_all(kind)
            if state.entity_id != BUILTIN_AGENT
        ]
        result.extend(sorted(found, key=lambda c: c["label"].casefold()))
    if current and current not in {c["value"] for c in result}:
        result.append(
            {
                "value": current,
                "label": current,
                "available": False,
                "kind": ai_mode(current) or "",
                "missing": True,
            }
        )
    return result


def ai_status(hass: HomeAssistant, manager: EssensplanerManager) -> dict[str, Any]:
    """{entity, mode, label, configured, available, features, ready: {feature: bool},
    receipts_entity, receipts_available, busy, last} – ready = switched on, configured and
    available; last = {ok, seconds, mode, feature, code, at} of the last request (no
    prompts, no answers)."""
    entity = ai_entity(manager)
    available = ai_available(hass, entity)
    features = ai_features(manager)
    receipts = ai_entity(manager, AI_FEATURE_RECEIPTS)
    receipts_available = ai_available(hass, receipts)
    ready = {
        f: f in features
        and (receipts_available if f == AI_FEATURE_RECEIPTS else entity is not None and available)
        for f in AI_FEATURES
    }
    state = _state(manager)
    return {
        "entity": entity,
        "mode": ai_mode(entity),
        "label": _label(hass, entity),
        "configured": entity is not None,
        "available": available,
        "features": features,
        "ready": ready,
        "receipts_entity": receipts,
        "receipts_available": receipts_available,
        "busy": state.lock.locked(),
        "last": dict(state.last) if state.last else None,
    }


def ai_panel(hass: HomeAssistant, manager: EssensplanerManager) -> dict[str, Any]:
    """What the panel needs to show its AI buttons ("🤖 KI-Menü", "🤖 mit KI") – also for
    users who are not administrators (ai_status is admin-only): {configured, available,
    label, mode, enabled: {feature: bool}, ready: {feature: bool}}. enabled = switched on
    with an AI entity (the button shows); ready = also reachable right now. No last result,
    no prompts."""
    entity = ai_entity(manager)
    available = ai_available(hass, entity)
    receipts = ai_entity(manager, AI_FEATURE_RECEIPTS)
    receipts_available = ai_available(hass, receipts)
    enabled = {f: ai_enabled(manager, f) for f in AI_FEATURES}
    return {
        "configured": entity is not None,
        "available": available,
        "label": _label(hass, entity),
        "mode": ai_mode(entity),
        "enabled": enabled,
        "ready": {
            f: enabled[f] and (receipts_available if f == AI_FEATURE_RECEIPTS else available)
            for f in AI_FEATURES
        },
    }


# ----------------------------------------------------------------------------------
# JSON in and out
# ----------------------------------------------------------------------------------


def extract_json(text: str) -> Any:
    """The JSON value of an AI answer: code fences, text before/after and trailing commas
    are tolerated. Raises ValueError when there is none."""
    raw = str(text or "").strip()
    if fence := re.search(r"```(?:json|JSON)?\s*(.*?)```", raw, re.DOTALL):
        raw = fence.group(1).strip()
    raw = raw.replace("“", '"').replace("”", '"').replace("„", '"')
    start = min((i for i in (raw.find("{"), raw.find("[")) if i >= 0), default=-1)
    if start < 0:
        raise ValueError("no JSON")
    candidate = _balanced(raw, start)
    for attempt in (candidate, re.sub(r",\s*([}\]])", r"\1", candidate)):
        try:
            return json.loads(attempt)
        except ValueError:
            continue
    raise ValueError("invalid JSON")


def _balanced(text: str, start: int) -> str:
    """The text from start to its matching closing bracket (strings respected)."""
    depth = 0
    in_string = False
    escape = False
    for position in range(start, len(text)):
        char = text[position]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
            if depth == 0:
                return text[start : position + 1]
    return text[start:]


def _dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)


def _containers(data: Any) -> list[Any]:
    """All lists and dicts in data (data itself first)."""
    found: list[Any] = []
    stack = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, (list, dict)):
            found.append(item)
            stack.extend(item.values() if isinstance(item, dict) else item)
    return found


def _shrink(data: Any) -> bool:
    """Make data smaller: halve its biggest list, else halve its longest text. False if
    nothing can be shortened."""
    containers = _containers(data)
    lists = [c for c in containers if isinstance(c, list) and len(c) > 1]
    if lists:
        biggest = max(lists, key=lambda c: len(_dumps(c)))
        del biggest[max(1, len(biggest) // 2) :]
        return True
    texts = [
        (len(value), container, key)
        for container in containers
        for key, value in (
            container.items() if isinstance(container, dict) else enumerate(container)
        )
        if isinstance(value, str) and len(value) > 20
    ]
    if not texts:
        return False
    _, container, key = max(texts, key=lambda t: t[0])
    container[key] = container[key][: len(container[key]) // 2]
    return True


def payload_json(payload: Any, limit: int = PAYLOAD_MAX) -> str:
    """The payload as compact JSON of at most limit characters (lists and texts are
    shortened until it fits; the payload itself is not changed)."""
    text = _dumps(payload)
    if len(text) <= limit:
        return text
    data = json.loads(text)
    for _ in range(200):
        if not _shrink(data):
            break
        text = _dumps(data)
        if len(text) <= limit:
            return text
    return "{}"


def build_prompt(instructions: str, payload_text: str) -> str:
    """Instructions, the data and the closing rule (no tools, JSON only)."""
    return f"{instructions.strip()}\n\nDaten (JSON):\n{payload_text}\n\n{NO_TOOLS}"


def _short(text: Any) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value if len(value) <= ERROR_TEXT_MAX else f"{value[: ERROR_TEXT_MAX - 1]}…"


def parse_answer(mode: str, response: Any, entity: str) -> Any:
    """The JSON value of an AI answer (ai_task: response["data"]; conversation:
    response.speech.plain.speech). An error answer of an agent raises ai_failed, an answer
    without JSON ai_invalid."""
    if mode == MODE_AI_TASK:
        value = response.get("data") if isinstance(response, dict) else None
        if isinstance(value, (dict, list)):
            return value
        text = str(value or "")
    else:
        inner = response.get("response") if isinstance(response, dict) else None
        inner = inner if isinstance(inner, dict) else {}
        speech = inner.get("speech") if isinstance(inner.get("speech"), dict) else {}
        plain = speech.get("plain") if isinstance(speech.get("plain"), dict) else {}
        text = str(plain.get("speech") or "")
        if inner.get("response_type") == "error":
            raise _error("ai_failed", entity=entity, error=_short(text) or "Fehlerantwort")
    try:
        return extract_json(text)
    except ValueError as err:
        _LOGGER.debug("AI answer of %s without JSON (%d characters)", entity, len(text))
        raise _error("ai_invalid", entity=entity) from err


# ----------------------------------------------------------------------------------
# Requests
# ----------------------------------------------------------------------------------


async def _async_request(
    hass: HomeAssistant, entity: str, task_name: str, prompt: str, timeout: float
) -> Any:
    """One request to the AI entity (AI_ACTIVE set meanwhile); the parsed JSON answer."""
    mode = ai_mode(entity)
    token = AI_ACTIVE.set(True)
    try:
        async with asyncio.timeout(timeout):
            if mode == MODE_AI_TASK:
                response = await hass.services.async_call(
                    "ai_task",
                    "generate_data",
                    {"task_name": task_name, "entity_id": entity, "instructions": prompt},
                    blocking=True,
                    return_response=True,
                )
            else:
                # a new conversation per request (no conversation_id): no history of the
                # user's chats goes in, none of this request stays in them
                response = await hass.services.async_call(
                    "conversation",
                    "process",
                    {"text": prompt, "agent_id": entity, "language": "de"},
                    blocking=True,
                    return_response=True,
                )
    except TimeoutError as err:
        raise _error(
            "ai_failed", entity=entity, error=f"keine Antwort nach {round(timeout)} s"
        ) from err
    except (HomeAssistantError, vol.Invalid, ValueError, KeyError) as err:
        raise _error("ai_failed", entity=entity, error=_short(err) or type(err).__name__) from err
    finally:
        AI_ACTIVE.reset(token)
    return parse_answer(str(mode), response, entity)


def _remember(state: AiState, ok: bool, started: float, **info: Any) -> None:
    state.last = {
        "ok": ok,
        "seconds": round(max(0.0, time.monotonic() - started), 1),
        "at": dt_util.utcnow().isoformat(timespec="seconds"),
        **info,
    }


def _cache_get(state: AiState, key: str) -> tuple[bool, Any]:
    now = time.monotonic()
    for old in [k for k, (at, _) in state.cache.items() if now - at >= CACHE_TTL]:
        del state.cache[old]
    if key in state.cache:
        return True, copy.deepcopy(state.cache[key][1])
    return False, None


def _cache_put(state: AiState, key: str, value: Any) -> None:
    state.cache.pop(key, None)
    state.cache[key] = (time.monotonic(), copy.deepcopy(value))
    while len(state.cache) > CACHE_MAX:
        del state.cache[next(iter(state.cache))]


async def async_ai_json(
    hass: HomeAssistant,
    manager: EssensplanerManager,
    feature: str,
    task_name: str,
    instructions: str,
    payload: Any,
    timeout: float = AI_TIMEOUT,
) -> Any:
    """Ask the AI entity of a feature and return its JSON answer (dict or list).

    instructions: the German task (what to return); payload: the data (see the privacy
    rules in the module docstring), sent as compact JSON of at most PAYLOAD_MAX characters.
    Errors (ServiceValidationError with a German message): ai_feature_off, ai_not_configured,
    ai_unavailable, ai_busy, ai_failed (error answer, exception, timeout), ai_invalid (no
    JSON). The caller validates the answer against its own data."""
    if feature not in AI_FEATURES:
        raise ValueError(f"unknown AI feature {feature}")
    if feature not in ai_features(manager):
        raise _error("ai_feature_off", feature=FEATURE_LABELS_DE.get(feature, feature))
    entity = ai_entity(manager, feature)
    if entity is None:
        raise _error("ai_not_configured")
    prompt = build_prompt(instructions, payload_json(payload))
    key = hashlib.sha1(
        "\x1f".join((feature, entity, task_name, prompt)).encode("utf-8"), usedforsecurity=False
    ).hexdigest()
    state = _state(manager)
    hit, value = _cache_get(state, key)
    if hit:
        return value
    if state.inflight is not None and state.inflight[0] == key:
        future = state.inflight[1]
        try:
            return copy.deepcopy(await asyncio.shield(future))
        except asyncio.CancelledError:
            if future.cancelled():
                raise _error("ai_failed", entity=entity, error="abgebrochen") from None
            raise
    if not ai_available(hass, entity):
        raise _error("ai_unavailable", entity=entity)
    if state.lock.locked():
        raise _error("ai_busy")
    async with state.lock:
        future = asyncio.get_running_loop().create_future()
        state.inflight = (key, future)
        started = time.monotonic()
        try:
            result = await _async_request(hass, entity, task_name, prompt, timeout)
        except asyncio.CancelledError:
            future.cancel()
            raise
        except Exception as err:
            future.set_exception(err)
            future.exception()  # waiters re-raise it; nobody else has to retrieve it
            code = getattr(err, "translation_key", None) or "ai_failed"
            _remember(state, False, started, mode=ai_mode(entity), feature=feature, code=code)
            raise
        finally:
            state.inflight = None
        future.set_result(result)
        _remember(state, True, started, mode=ai_mode(entity), feature=feature, code=None)
        _cache_put(state, key, result)
    return copy.deepcopy(result)


async def async_ai_test(
    hass: HomeAssistant, manager: EssensplanerManager, entity_id: str | None = None
) -> dict[str, Any]:
    """Test an AI entity (the given one – e.g. just picked in the panel – else the
    configured one) with a tiny request: {ok, entity, mode, seconds, code, error} – error is
    the German message of the code (ai_not_configured, ai_unavailable, ai_busy, ai_failed,
    ai_invalid). Not cached; works whatever features are switched on."""
    from .manager import error_message

    entity = entity_id or ai_entity(manager)
    mode = ai_mode(entity)
    state = _state(manager)
    started = time.monotonic()
    result: dict[str, Any] = {
        "ok": False,
        "entity": entity,
        "mode": mode,
        "seconds": None,
        "code": None,
        "error": None,
    }
    try:
        if entity is None or mode is None:
            raise _error("ai_not_configured")
        if not ai_available(hass, entity):
            raise _error("ai_unavailable", entity=entity)
        if state.lock.locked():
            raise _error("ai_busy")
        async with state.lock:
            started = time.monotonic()
            await _async_request(
                hass,
                entity,
                TEST_TASK_NAME,
                f"{TEST_INSTRUCTIONS}\n\n{NO_TOOLS}",
                TEST_TIMEOUT,
            )
    except ServiceValidationError as err:
        code = err.translation_key or "ai_failed"
        result.update(code=code, error=error_message(err))
        if code in ("ai_failed", "ai_invalid"):  # the request was sent
            result["seconds"] = round(max(0.0, time.monotonic() - started), 1)
            _remember(state, False, started, mode=mode, feature="test", code=code)
        return result
    result.update(ok=True, seconds=round(max(0.0, time.monotonic() - started), 1))
    _remember(state, True, started, mode=mode, feature="test", code=None)
    return result


__all__ = [
    "AI_ACTIVE",
    "AI_MODES",
    "AI_REFUSED_DE",
    "BUILTIN_AGENT",
    "NO_TOOLS",
    "PAYLOAD_MAX",
    "ai_available",
    "ai_enabled",
    "ai_entity",
    "ai_features",
    "ai_mode",
    "ai_status",
    "async_ai_json",
    "async_ai_test",
    "build_prompt",
    "entity_choices",
    "extract_json",
    "payload_json",
]
