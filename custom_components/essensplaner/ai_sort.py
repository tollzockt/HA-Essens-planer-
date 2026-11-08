"""AI sorting of articles and recipes (1.5.1, features "products" and "recipes").

Rules first: every product is classified by the rules when it is stored (catalog.
classify_offer(), ingredients.guess_category(); a product of unknown kind is stored
"unsorted") and every recipe gets its kind by kinds.classify_kind(). The AI checks what the
rules decided – started with "🤖 Artikel sortieren" / "🤖 Rezepte sortieren" (websocket
essensplaner/ai_sort, service sort_with_ai) and weekly on Sunday at 03:xx for what is new.

Articles: the products nobody but the rules checked (unsorted first, then those with a
current offer, newest first), ≤ BATCH_SIZE per request, ≤ MAX_REQUESTS per run. The AI gets
only name, brand, pack and the rules' category / kind / keys plus the known ingredient keys
that fit the names – no prices, stores, branches or addresses – and answers
[{id, category, kind, keys, confidence}]. Strict checks: the id must be one that was sent,
the category one of CATEGORY_ORDER, the kind one of products.SORT_KINDS and consistent with
the aisle, keys only from the keys sent; low confidence keeps the rules. A product sorted
as non-food goes (and is not stored again) unless it is protected (⭐, picks, bought, own,
used by the shopping list, a recipe or an occasion). What the user set (checked by "user")
is never sent or changed.

Recipes: those whose kind the rules set (kind_source "rule"; never "user"); the AI gets
name, tags and ingredient names (no notes, no source) and answers [{id, kind, tags,
confidence}]: the kind (kinds.KINDS, applied with kinds.set_kind(…, "ai")) and at most
MAX_AI_TAGS tags of ALLOWED_TAGS ("vegetarisch" / "vegan" only without meat, fish or – vegan
– animal products among the ingredients).

The weekly check (only with an AI entity and the feature on) sends only what is new since
its last complete run (products first seen since then, unsorted ones, recipes of the
rules the AI did not answer yet); a failed check (AI unavailable, busy) is tried again the
next night. One run per manager at a time (a second call joins it); each request goes
through ai.async_ai_json() (single flight, timeout, cache, recursion guard). Without an
answer everything stays as the rules decided and the summary says why.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date, datetime, timedelta
import json
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from .ai import PAYLOAD_MAX, ai_enabled, ai_entity, async_ai_json
from .const import (
    AI_FEATURE_PRODUCTS,
    AI_FEATURE_RECIPES,
    AI_FEATURES,
    CONF_AI_FEATURES,
    EVENT_UPDATED,
)
from .ingredients import CATEGORY_ORDER, fold, guess_category, ingredient_key, is_pantry_item
from .kinds import KINDS, SOURCE_AI, SOURCE_RULE, SOURCE_USER, set_kind

if TYPE_CHECKING:
    from .manager import EssensplanerManager

_LOGGER = logging.getLogger(__name__)

TARGET_PRODUCTS = "products"
TARGET_RECIPES = "recipes"
TARGET_ALL = "all"
SORT_TARGETS = (TARGET_PRODUCTS, TARGET_RECIPES)
TARGETS = (*SORT_TARGETS, TARGET_ALL)
FEATURES = {TARGET_PRODUCTS: AI_FEATURE_PRODUCTS, TARGET_RECIPES: AI_FEATURE_RECIPES}

BATCH_SIZE = 60
MAX_REQUESTS = 5  # articles per run (the button continues with the rest)
RECIPE_MAX_REQUESTS = 3
# the JSON of one request stays below the cap of ai.py (nothing is cut off)
PAYLOAD_LIMIT = PAYLOAD_MAX - 500
MIN_CONFIDENCE = 0.5
REMOVE_CONFIDENCE = 0.7
ITEM_KEYS = 8  # known keys per article
RECIPE_INGREDIENTS = 12
MAX_AI_TAGS = 3
MAX_ERRORS = 3
# the weekly check: Sunday 03:xx (the minute spread per installation)
WEEKLY_WEEKDAY = 6
WEEKLY_HOUR = 3
# the first weekly check (no earlier one): articles first seen this many days ago
FIRST_WEEK_DAYS = 7
# errors after which a run stops (nothing more would be answered)
STOP_CODES = frozenset(
    {"ai_feature_off", "ai_not_configured", "ai_unavailable", "ai_busy", "ai_failed"}
)

# tags the AI may add to a recipe
ALLOWED_TAGS = (
    "vegetarisch",
    "vegan",
    "schnell",
    "günstig",
    "Kinder",
    "Party",
    "Grillen",
    "Weihnachten",
    "Ostern",
    "Sommer",
    "Herbst",
    "Winter",
    "Frühling",
    "Fertiggericht",
    "Suppe",
    "Salat",
    "Pasta",
    "Auflauf",
    "Eintopf",
)
_ALLOWED_TAGS = {fold(t): t for t in ALLOWED_TAGS}
_MEAT_AISLES = frozenset({"Fleisch & Fisch"})
_ANIMAL_AISLES = frozenset({"Fleisch & Fisch", "Milchprodukte & Eier", "Käse & Aufschnitt"})
_ANIMAL_WORDS = ("honig", "gelatine", "butter", "sahne", "milch", "ei", "eier", "quark")

PRODUCT_KINDS_TEXT = (
    "food (Lebensmittel), drinks (Getränke), drugstore (Drogerie, Körperpflege, Kosmetik, "
    "Baby, Gesundheit), household (Haushalt, Reinigung, Waschmittel, Küchenrolle) oder "
    "nonfood (alles andere: Kleidung, Technik, Möbel, Deko, Pflanzen, Spielzeug, Werkzeug, "
    "Tierfutter)"
)
PRODUCT_TASK = "Essensplaner Artikel sortieren"
PRODUCT_INSTRUCTIONS = (
    "Du sortierst die Artikel einer Artikel-Datenbank von Supermärkten und Drogerien. Die "
    'Daten enthalten "products" (id, name, brand, pack und die bisherige Einordnung nach '
    'Regeln: category, kind, keys) und "known_keys" (bekannte Zutaten-Schlüssel). Gib für '
    'JEDEN Artikel zurück: {"products": [{"id": "…", "category": "…", "kind": "…", '
    '"keys": ["…"], "confidence": 0.9}]}. category genau eine von: '
    + ", ".join(CATEGORY_ORDER)
    + ". kind genau eins von: "
    + PRODUCT_KINDS_TEXT
    + '. keys: nur Schlüssel aus "known_keys", die der Artikel selbst ist (Butter → '
    '"butter", Butterkekse nicht "butter"), sonst []. confidence: 0 bis 1, wie sicher du '
    "bist. Lass keinen Artikel aus und erfinde keine ids."
)
RECIPE_TASK = "Essensplaner Rezepte sortieren"
RECIPE_INSTRUCTIONS = (
    'Du sortierst Rezepte. Die Daten enthalten "recipes" (id, name, tags, ingredients und '
    "die bisherige Art nach Regeln: kind). Gib für JEDES Rezept zurück: "
    '{"recipes": [{"id": "…", "kind": "…", "tags": ["…"], "confidence": 0.9}]}. kind '
    "genau eins von: meal (Mittag- oder Abendessen), breakfast (Frühstück), snack (Snack, "
    "Kuchen, Gebäck), dessert (Nachtisch), drink (Getränk), side (Beilage, Vorspeise) oder "
    "component (Sauce, Dip, Dressing, Aufstrich, Kräuterbutter). tags: höchstens "
    f"{MAX_AI_TAGS} passende zusätzliche Tags, nur aus: "
    + ", ".join(ALLOWED_TAGS)
    + " (sonst []). confidence: 0 bis 1. Lass kein Rezept aus und erfinde keine ids."
)


# ----------------------------------------------------------------------
# State
# ----------------------------------------------------------------------


def _persisted(manager: EssensplanerManager) -> dict[str, Any]:
    """The stored state (main file "ai_sort"): {products: {...}, recipes: {...},
    features_151}."""
    state = getattr(manager, "ai_sort_state", None)
    if not isinstance(state, dict):
        state = {}
        manager.ai_sort_state = state
    return state


def _target_state(manager: EssensplanerManager, target: str) -> dict[str, Any]:
    state = _persisted(manager)
    entry = state.get(target)
    if not isinstance(entry, dict):
        entry = {}
        state[target] = entry
    return entry


def _runtime(manager: EssensplanerManager) -> dict[str, Any]:
    """The running sort of a manager (not stored): {task, targets, progress}."""
    runtime = manager.__dict__.get("_ai_sort_runtime")
    if runtime is None:
        runtime = {"task": None, "targets": (), "progress": None}
        manager.__dict__["_ai_sort_runtime"] = runtime
    return runtime


def weekly_minute(entry_id: str) -> int:
    """The minute of the weekly check (stable per installation, like the daily requests)."""
    return sum(ord(c) for c in entry_id) % 50 + 5


def next_weekly_run(manager: EssensplanerManager, now: datetime | None = None) -> datetime:
    """The next Sunday 03:xx (local time)."""
    local = dt_util.as_local(now or dt_util.utcnow())
    minute = weekly_minute(manager.entry.entry_id)
    candidate = local.replace(hour=WEEKLY_HOUR, minute=minute, second=0, microsecond=0)
    candidate += timedelta(days=(WEEKLY_WEEKDAY - local.weekday()) % 7)
    if candidate <= local:
        candidate += timedelta(days=7)
    return candidate


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def sort_status(manager: EssensplanerManager, now: datetime | None = None) -> dict[str, Any]:
    """The AI sorting for the panel (⚙️ KI, "📦 Artikel", recipes): {products: {enabled,
    last_run, last_ok, last_auto, result: {checked, changed, removed, skipped, errors,
    code, remaining}, pending}, recipes: {…}, running: {target, request, requests} | None,
    next_run (the next weekly check, None when no feature is on)}. No prompts, no answers."""
    runtime = _runtime(manager)
    task = runtime.get("task")
    running = runtime.get("progress") if task is not None and not task.done() else None
    result: dict[str, Any] = {}
    for target in SORT_TARGETS:
        state = _target_state(manager, target)
        info: dict[str, Any] = {
            "enabled": ai_enabled(manager, FEATURES[target]),
            "last_run": state.get("last_run"),
            "last_ok": state.get("last_ok"),
            "last_auto": state.get("last_auto"),
            "result": state.get("last_result"),
        }
        if target == TARGET_RECIPES:
            info["pending"] = sum(
                1
                for r in manager.recipes.values()
                if (r.get("kind_source") or SOURCE_RULE) == SOURCE_RULE
            )
        result[target] = info
    weekly = any(result[t]["enabled"] for t in SORT_TARGETS)
    result["running"] = dict(running) if running else None
    result["next_run"] = next_weekly_run(manager, now).isoformat() if weekly else None
    return result


def migrate_features(hass: HomeAssistant, manager: EssensplanerManager) -> bool:
    """Once (1.5.1): a saved AI feature selection that uses the AI gets the new features
    "products" (was only prepared in 1.5) and "recipes" – the default for new installs.
    Returns True if the options changed."""
    state = _persisted(manager)
    if state.get("features_151"):
        return False
    state["features_151"] = True
    manager._save_later()
    entry = manager.entry
    raw = entry.options.get(CONF_AI_FEATURES)
    if not isinstance(raw, list) or not raw:
        return False
    wanted = set(raw) | {AI_FEATURE_PRODUCTS, AI_FEATURE_RECIPES}
    features = [f for f in AI_FEATURES if f in wanted]
    if features == list(raw):
        return False
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_AI_FEATURES: features}
    )
    return True


# ----------------------------------------------------------------------
# Answers
# ----------------------------------------------------------------------


def _dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _items(answer: Any, names: tuple[str, ...]) -> list[Any]:
    """The list of an answer: the answer itself or its first list under one of names."""
    if isinstance(answer, list):
        return answer
    if isinstance(answer, dict):
        for name in names:
            if isinstance(answer.get(name), list):
                return answer[name]
    return []


def _confidence(value: Any) -> float:
    """0..1 (a percentage is divided by 100; missing: MIN_CONFIDENCE)."""
    if value is None or isinstance(value, bool):
        return MIN_CONFIDENCE
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if 1 < number <= 100:
        number /= 100
    return max(0.0, min(1.0, number))


def _texts(value: Any) -> list[str]:
    """A list of texts ("a, b", ["a", "b"], "" -> [])."""
    if value is None:
        return []
    if isinstance(value, str):
        return [t.strip() for t in value.split(",") if t.strip()]
    if isinstance(value, (list, tuple)):
        return [str(t).strip() for t in value if isinstance(t, str) and str(t).strip()]
    return []


def _category(value: Any) -> str | None:
    text = str(value or "").strip()
    if text in CATEGORY_ORDER:
        return text
    folded = fold(text)
    return next((c for c in CATEGORY_ORDER if fold(c) == folded), None) if folded else None


def _part() -> dict[str, Any]:
    return {
        "ok": True,
        "checked": 0,
        "changed": 0,
        "removed": 0,
        "skipped": 0,
        "errors": [],
        "code": None,
        "requests": 0,
        "remaining": 0,
    }


def _fail(part: dict[str, Any], err: ServiceValidationError) -> str:
    from .manager import error_message

    code = str(err.translation_key or "ai_failed")
    message = error_message(err)
    part["code"] = code
    if message not in part["errors"] and len(part["errors"]) < MAX_ERRORS:
        part["errors"].append(message)
    return code


# ----------------------------------------------------------------------
# Articles
# ----------------------------------------------------------------------


def _protected_products(manager: EssensplanerManager) -> set[str]:
    """Products that are never removed (⭐, picks, bought, own, in use)."""
    from .products import _store_of, protected_ids

    store = _store_of(manager)
    if store is None:
        return set()
    found = protected_ids(manager) | store.favorite_ids() | store.pick_ids() | store.bought_ids()
    found |= {pid for pid, p in store.products.items() if p.get("manual")}
    return found


def product_candidates(
    manager: EssensplanerManager, auto: bool = False, since: str | None = None
) -> list[dict[str, Any]]:
    """The products the AI should check: not sorted by the AI or the user, no own product;
    unsorted ones first, then those with a current offer, newest first. auto (the weekly
    check): only unsorted ones and those first seen since `since` (the first check: the
    last FIRST_WEEK_DAYS days) the AI did not answer yet."""
    from .products import CHECK_AI, CHECK_USER, _offer_now, _store_of, checked_by

    store = _store_of(manager)
    if store is None:
        return []
    today = manager.today()
    iso = today.isoformat()
    first = since[:10] if since else (today - timedelta(days=FIRST_WEEK_DAYS)).isoformat()
    found: list[dict[str, Any]] = []
    for product in store.products.values():
        by = checked_by(product)
        if by in (CHECK_AI, CHECK_USER) or product.get("manual"):
            continue
        if auto and (
            product.get("ai_seen") or (by is not None and (product.get("first_seen") or "") < first)
        ):
            continue
        found.append(product)

    def order(product: dict[str, Any]) -> tuple[Any, ...]:
        seen = _day(product.get("first_seen"))
        return (
            checked_by(product) is not None,
            not _offer_now(product.get("offer"), iso),
            -(seen.toordinal() if seen else 0),
            product["id"],
        )

    found.sort(key=order)
    return found


def _product_keys(product: dict[str, Any], matcher: Any) -> list[str]:
    """Known keys that fit a product's name (and its own keys), ≤ ITEM_KEYS."""
    from .offers import product_head

    name = str(product.get("name") or "")
    head = product_head(name)
    keys = list(product.get("keys") or [])
    keys += matcher.match(head, head)
    own = ingredient_key(head)
    if own in matcher._key_set:
        keys.append(own)
    keys += [k for k in matcher.candidates(name) if len(k) >= 3]
    return list(dict.fromkeys(keys))[:ITEM_KEYS]


def product_batch(
    candidates: list[dict[str, Any]], matcher: Any
) -> tuple[dict[str, Any], dict[str, str]]:
    """(payload, {sent id: product id}) of the next request: ≤ BATCH_SIZE products whose
    JSON stays below PAYLOAD_LIMIT – name, brand, pack, the rules' category / kind / keys
    and the known keys that fit them; nothing else (no prices, stores, branches)."""
    from .pricing import pack_text
    from .products import product_pack

    entries: list[dict[str, Any]] = []
    known: set[str] = set()
    ids: dict[str, str] = {}
    for product in candidates:
        if len(entries) >= BATCH_SIZE:
            break
        pack = product_pack(product)
        sid = f"p{len(entries) + 1}"
        entry = {
            "id": sid,
            "name": str(product.get("name") or ""),
            "brand": str(product.get("brand") or ""),
            "pack": pack_text(*pack) if pack else "",
            "category": str(product.get("category") or "Sonstiges"),
            "kind": str(product.get("kind") or "unknown"),
            "keys": list(product.get("keys") or []),
        }
        keys = known | set(_product_keys(product, matcher))
        size = len(_dumps({"products": [*entries, entry], "known_keys": sorted(keys)}))
        if size > PAYLOAD_LIMIT and entries:
            break
        entries.append(entry)
        known = keys
        ids[sid] = product["id"]
    return {"products": entries, "known_keys": sorted(known)}, ids


def apply_products(
    manager: EssensplanerManager,
    answer: Any,
    ids: dict[str, str],
    allowed_keys: set[str],
    part: dict[str, Any],
) -> None:
    """Check and apply an answer (see the module doc); counts go into part."""
    from .products import (
        CHECK_AI,
        CHECK_USER,
        KIND_NONFOOD,
        SORT_KINDS,
        _store_of,
        checked_by,
        consistent_aisle,
        set_keys,
    )

    store = _store_of(manager)
    if store is None:
        return
    now = dt_util.utcnow().isoformat(timespec="seconds")
    day = manager.today()
    protected: set[str] | None = None
    answered: set[str] = set()
    for raw in _items(answer, ("products", "artikel", "items")):
        sid = str(raw.get("id") or "") if isinstance(raw, dict) else ""
        pid = ids.get(sid)
        if pid is None or sid in answered:
            continue  # an id that was not sent (or twice)
        answered.add(sid)
        product = store.get(pid)
        if product is None or checked_by(product) in (CHECK_AI, CHECK_USER):
            part["skipped"] += 1
            continue
        product["ai_seen"] = now
        category = _category(raw.get("category"))
        kind = str(raw.get("kind") or "").strip().lower()
        confidence = _confidence(raw.get("confidence"))
        aisle = consistent_aisle(kind, category) if category and kind in SORT_KINDS else None
        if aisle is None or confidence < MIN_CONFIDENCE:
            part["skipped"] += 1
            continue
        keys = [k for k in _texts(raw.get("keys")) if k in allowed_keys]
        if kind == KIND_NONFOOD and confidence >= REMOVE_CONFIDENCE:
            if protected is None:
                protected = _protected_products(manager)
            if product["id"] not in protected:
                store.drop(product, day)
                part["removed"] += 1
                part["checked"] += 1
                continue
        before = {
            "category": product.get("category"),
            "kind": product.get("kind"),
            "keys": list(product.get("keys") or []),
        }
        # the ingredients a ⭐ or a pick belongs to stay
        keep = {k for k, fav in store.favorites.items() if fav == product["id"]}
        keep |= {k for k, entries in store.picks.items() if any(e[0] == pid for e in entries)}
        store._unindex(product)
        product["category"] = aisle
        product["kind"] = kind
        set_keys(store, product, keys, keep)
        product["checked"] = {"by": CHECK_AI, "at": now}
        if before != {k: product.get(k) for k in before}:
            product["ai_fix"] = {"at": now, "confidence": round(confidence, 2), "before": before}
            part["changed"] += 1
        store._index(product)
        part["checked"] += 1
    part["skipped"] += len(set(ids) - answered)
    store._touch()


async def _async_products(
    hass: HomeAssistant, manager: EssensplanerManager, auto: bool, report: Callable[..., None]
) -> dict[str, Any]:
    from .catalog import KeyMatcher, all_keys
    from .products import _store_of

    part = _part()
    store = _store_of(manager)
    if store is None:
        return part
    state = _target_state(manager, TARGET_PRODUCTS)
    candidates = product_candidates(manager, auto, state.get("since") if auto else None)
    matcher = KeyMatcher(all_keys(manager))
    position = 0
    while position < len(candidates) and part["requests"] < MAX_REQUESTS:
        if manager.unloaded or store.unloaded:
            break
        payload, ids = product_batch(candidates[position:], matcher)
        if not ids:
            break
        position += len(ids)
        part["requests"] += 1
        report(TARGET_PRODUCTS, part["requests"])
        try:
            answer = await async_ai_json(
                hass, manager, AI_FEATURE_PRODUCTS, PRODUCT_TASK, PRODUCT_INSTRUCTIONS, payload
            )
        except ServiceValidationError as err:
            part["skipped"] += len(ids)
            if _fail(part, err) in STOP_CODES:
                break
            continue
        if manager.unloaded or store.unloaded:
            break
        apply_products(manager, answer, ids, set(payload["known_keys"]), part)
        await asyncio.sleep(0)
    part["remaining"] = max(0, len(candidates) - position)
    part["ok"] = part["code"] is None or part["checked"] > 0
    if part["checked"] or part["skipped"]:
        store.save_later()
    return part


# ----------------------------------------------------------------------
# Recipes
# ----------------------------------------------------------------------


def recipe_candidates(manager: EssensplanerManager, auto: bool = False) -> list[dict[str, Any]]:
    """Recipes whose kind the rules set (never the user's or the AI's), newest first; auto:
    only those the AI did not answer yet."""
    found = [
        r
        for r in manager.recipes.values()
        if (r.get("kind_source") or SOURCE_RULE) == SOURCE_RULE
        and not (auto and r.get("ai_sorted"))
    ]
    found.sort(key=lambda r: (str(r.get("created") or ""), r["id"]), reverse=True)
    return found


def recipe_batch(candidates: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, str]]:
    """(payload, {sent id: recipe id}): name, tags, ingredient names (≤ RECIPE_INGREDIENTS)
    and the rules' kind – no notes, no source, no amounts."""
    entries: list[dict[str, Any]] = []
    ids: dict[str, str] = {}
    for recipe in candidates:
        if len(entries) >= BATCH_SIZE:
            break
        sid = f"r{len(entries) + 1}"
        names = [
            str(i.get("name") or "")
            for i in recipe.get("ingredients") or []
            if isinstance(i, dict) and i.get("name")
        ]
        entry = {
            "id": sid,
            "name": str(recipe.get("name") or ""),
            "tags": [str(t) for t in recipe.get("tags") or []][:8],
            "ingredients": names[:RECIPE_INGREDIENTS],
            "kind": str(recipe.get("kind") or ""),
        }
        if len(_dumps({"recipes": [*entries, entry]})) > PAYLOAD_LIMIT and entries:
            break
        entries.append(entry)
        ids[sid] = recipe["id"]
    return {"recipes": entries}, ids


def _tag_allowed(tag: str, recipe: dict[str, Any]) -> bool:
    """vegetarisch / vegan only without meat or fish (vegan: without animal products)."""
    if tag not in ("vegetarisch", "vegan"):
        return True
    aisles = _MEAT_AISLES if tag == "vegetarisch" else _ANIMAL_AISLES
    for ingredient in recipe.get("ingredients") or []:
        name = str((ingredient or {}).get("name") or "") if isinstance(ingredient, dict) else ""
        if not name or is_pantry_item(name, ["Salz", "Pfeffer", "Wasser"]):
            continue
        if guess_category(name) in aisles:
            return False
        if tag == "vegan" and any(w in fold(name).split() for w in _ANIMAL_WORDS):
            return False
    return True


def apply_recipes(
    manager: EssensplanerManager, answer: Any, ids: dict[str, str], part: dict[str, Any]
) -> bool:
    """Check and apply an answer for recipes; True if a recipe changed."""
    now = dt_util.utcnow().isoformat(timespec="seconds")
    answered: set[str] = set()
    changed_any = False
    for raw in _items(answer, ("recipes", "rezepte", "items")):
        sid = str(raw.get("id") or "") if isinstance(raw, dict) else ""
        rid = ids.get(sid)
        if rid is None or sid in answered:
            continue
        answered.add(sid)
        recipe = manager.recipes.get(rid)
        if recipe is None or recipe.get("kind_source") in (SOURCE_USER, SOURCE_AI):
            part["skipped"] += 1
            continue
        kind = str(raw.get("kind") or "").strip().lower()
        confidence = _confidence(raw.get("confidence"))
        if kind not in KINDS or confidence < MIN_CONFIDENCE:
            recipe["ai_sorted"] = {"at": now, "skipped": True}
            part["skipped"] += 1
            changed_any = True
            continue
        before = recipe.get("kind")
        set_kind(recipe, kind, SOURCE_AI)
        present = {fold(t) for t in recipe.get("tags") or []}
        added: list[str] = []
        for text in _texts(raw.get("tags")):
            tag = _ALLOWED_TAGS.get(fold(text))
            if tag is None or fold(tag) in present or len(added) >= MAX_AI_TAGS:
                continue
            if _tag_allowed(tag, recipe):
                added.append(tag)
                present.add(fold(tag))
        if added:
            recipe["tags"] = [*(recipe.get("tags") or []), *added]
        info: dict[str, Any] = {"at": now, "confidence": round(confidence, 2)}
        if added:
            info["tags"] = added
        if before != recipe.get("kind"):
            info["before"] = before
        recipe["ai_sorted"] = info
        if added or before != recipe.get("kind"):
            part["changed"] += 1
        part["checked"] += 1
        changed_any = True
    part["skipped"] += len(set(ids) - answered)
    return changed_any


async def _async_recipes(
    hass: HomeAssistant, manager: EssensplanerManager, auto: bool, report: Callable[..., None]
) -> dict[str, Any]:
    part = _part()
    candidates = recipe_candidates(manager, auto)
    position = 0
    changed = False
    while position < len(candidates) and part["requests"] < RECIPE_MAX_REQUESTS:
        if manager.unloaded:
            break
        payload, ids = recipe_batch(candidates[position:])
        if not ids:
            break
        position += len(ids)
        part["requests"] += 1
        report(TARGET_RECIPES, part["requests"])
        try:
            answer = await async_ai_json(
                hass, manager, AI_FEATURE_RECIPES, RECIPE_TASK, RECIPE_INSTRUCTIONS, payload
            )
        except ServiceValidationError as err:
            part["skipped"] += len(ids)
            if _fail(part, err) in STOP_CODES:
                break
            continue
        if manager.unloaded:
            break
        changed = apply_recipes(manager, answer, ids, part) or changed
        await asyncio.sleep(0)
    part["remaining"] = max(0, len(candidates) - position)
    part["ok"] = part["code"] is None or part["checked"] > 0
    if changed and not manager.unloaded:
        manager._changed("recipe_sorted")
    return part


# ----------------------------------------------------------------------
# Runs
# ----------------------------------------------------------------------


def _remember(
    manager: EssensplanerManager, target: str, part: dict[str, Any], auto: bool, started: str
) -> None:
    state = _target_state(manager, target)
    now = dt_util.utcnow().isoformat(timespec="seconds")
    state["last_run"] = now
    state["last_ok"] = bool(part["ok"])
    state["last_result"] = {
        k: part[k]
        for k in ("checked", "changed", "removed", "skipped", "errors", "code", "remaining")
    }
    if auto:
        state["auto_tried"] = now
        state["auto_ok"] = bool(part["ok"] and part["code"] is None)
        if state["auto_ok"]:
            state["last_auto"] = now
            if not part["remaining"]:
                state["since"] = started  # what was new is done: next time only newer
    if not manager.unloaded:
        manager._save_later()


def _off_part(code: str, **placeholders: Any) -> dict[str, Any]:
    from .manager import _error

    part = _part()
    _fail(part, _error(code, **placeholders))
    part["ok"] = False
    return part


async def _async_run(
    hass: HomeAssistant, manager: EssensplanerManager, targets: tuple[str, ...], auto: bool
) -> dict[str, Any]:
    from .ai import FEATURE_LABELS_DE

    runtime = _runtime(manager)
    started = dt_util.utcnow().isoformat(timespec="seconds")
    result: dict[str, Any] = {
        "targets": list(targets),
        "auto": auto,
        "ok": True,
        "checked": 0,
        "changed": 0,
        "removed": 0,
        "skipped": 0,
        "errors": [],
        TARGET_PRODUCTS: None,
        TARGET_RECIPES: None,
    }

    def report(target: str, request: int) -> None:
        runtime["progress"] = {
            "target": target,
            "request": request,
            "requests": MAX_REQUESTS if target == TARGET_PRODUCTS else RECIPE_MAX_REQUESTS,
            "started": started,
        }
        if not manager.unloaded:
            hass.bus.async_fire(EVENT_UPDATED, {"change": "ai_sort"})

    for target in targets:
        feature = FEATURES[target]
        if ai_entity(manager, feature) is None:
            part = _off_part("ai_not_configured")
        elif not ai_enabled(manager, feature):
            part = _off_part("ai_feature_off", feature=FEATURE_LABELS_DE.get(feature, feature))
        elif target == TARGET_PRODUCTS:
            part = await _async_products(hass, manager, auto, report)
        else:
            part = await _async_recipes(hass, manager, auto, report)
        if manager.unloaded:
            break
        result[target] = part
        _remember(manager, target, part, auto, started)
        for key in ("checked", "changed", "removed", "skipped"):
            result[key] += part[key]
        result["errors"] += [e for e in part["errors"] if e not in result["errors"]]
        result["ok"] = result["ok"] and part["ok"]
    runtime["progress"] = None
    if not manager.unloaded:
        hass.bus.async_fire(EVENT_UPDATED, {"change": "products"})
        hass.bus.async_fire(EVENT_UPDATED, {"change": "ai_sort"})
        manager.async_refresh_listeners()
    _LOGGER.debug(
        "AI sorting %s: %d checked, %d changed, %d removed, %d skipped",
        "/".join(targets),
        result["checked"],
        result["changed"],
        result["removed"],
        result["skipped"],
    )
    return result


async def async_sort(
    hass: HomeAssistant, manager: EssensplanerManager, target: str = TARGET_ALL, auto: bool = False
) -> dict[str, Any]:
    """Sort articles and/or recipes with the AI (target products | recipes | all; "all"
    leaves out a target whose feature is off). One run per manager: a call for targets the
    running one covers joins it, another waits for it. Returns the summary {targets, auto,
    ok, checked, changed, removed, skipped, errors: [German messages], products: part |
    None, recipes: part | None} – part {ok, checked, changed, removed, skipped, errors,
    code, requests, remaining} – plus status (sort_status())."""
    if target == TARGET_ALL:
        targets = tuple(t for t in SORT_TARGETS if ai_enabled(manager, FEATURES[t]))
        targets = targets or (SORT_TARGETS if auto else (TARGET_PRODUCTS,))
    else:
        targets = (target,)
    runtime = _runtime(manager)
    while (task := runtime.get("task")) is not None and not task.done():
        if set(targets) <= set(runtime.get("targets") or ()):
            result = dict(await asyncio.shield(task))
            return {**result, "status": sort_status(manager)}
        try:
            await asyncio.shield(task)
        except Exception:  # the other run reported its own failure
            _LOGGER.debug("The previous AI sorting failed")
    task = manager.entry.async_create_background_task(
        hass, _async_run(hass, manager, targets, auto), "essensplaner_ai_sort"
    )
    runtime["task"] = task
    runtime["targets"] = targets
    result = dict(await asyncio.shield(task))
    return {**result, "status": sort_status(manager)}


def weekly_due(manager: EssensplanerManager, target: str, now: datetime) -> bool:
    """True if the weekly check of a target is due: its feature is on and it is Sunday (not
    tried today), or the last check failed and was tried before today (again every night
    until it works)."""
    if not ai_enabled(manager, FEATURES[target]):
        return False
    state = _target_state(manager, target)
    today = dt_util.as_local(now).date()
    tried = _day(_local_iso(state.get("auto_tried")))
    if tried == today:
        return False
    if today.weekday() == WEEKLY_WEEKDAY:
        return True
    return state.get("auto_ok") is False and tried is not None and (today - tried).days < 7


def _local_iso(value: Any) -> str | None:
    moment = dt_util.parse_datetime(str(value)) if value else None
    return dt_util.as_local(moment).date().isoformat() if moment else None


async def async_weekly_check(
    hass: HomeAssistant, manager: EssensplanerManager, now: datetime | None = None
) -> dict[str, Any] | None:
    """The nightly check at 03:xx: the weekly sorting of what is new (see weekly_due()).
    Returns the summary (None if nothing was due)."""
    now = now or dt_util.utcnow()
    if manager.unloaded:
        return None
    targets = [t for t in SORT_TARGETS if weekly_due(manager, t, now)]
    if not targets:
        return None
    result = await async_sort(
        hass, manager, targets[0] if len(targets) == 1 else TARGET_ALL, auto=True
    )
    if not result.get("ok"):
        _LOGGER.info("Essensplaner AI sorting (weekly): %s", "; ".join(result.get("errors") or []))
    return result


__all__ = [
    "ALLOWED_TAGS",
    "TARGETS",
    "async_sort",
    "async_weekly_check",
    "migrate_features",
    "next_weekly_run",
    "sort_status",
]
