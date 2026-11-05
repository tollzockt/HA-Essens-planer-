"""Import recipes from websites (schema.org/Recipe JSON-LD)."""

from __future__ import annotations

import html
import json
import logging
import re
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN
from .netio import async_read_body

_LOGGER = logging.getLogger(__name__)

_LD_JSON_RE = re.compile(
    r"<script[^>]*type\s*=\s*[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+(?:\.\d+)?)D)?(?:T(?:(?P<hours>\d+(?:\.\d+)?)H)?"
    r"(?:(?P<minutes>\d+(?:\.\d+)?)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$",
    re.IGNORECASE,
)
_MAX_BYTES = 5 * 1024 * 1024


class RecipeImportError(HomeAssistantError):
    """Raised when a recipe could not be imported."""


def _clean(text: Any) -> str:
    if text is None:
        return ""
    if isinstance(text, (list, tuple)):
        text = " ".join(_clean(t) for t in text)
    text = html.unescape(str(text))
    text = _TAG_RE.sub(" ", text)
    return " ".join(text.split())


def parse_duration(value: Any) -> int | None:
    """Parse an ISO 8601 duration (PT1H30M) into minutes."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    match = _DURATION_RE.match(text)
    if not match or not any(match.groupdict().values()):
        return None
    days = float(match.group("days") or 0)
    hours = float(match.group("hours") or 0)
    minutes = float(match.group("minutes") or 0)
    seconds = float(match.group("seconds") or 0)
    total = round(days * 1440 + hours * 60 + minutes + seconds / 60)
    return total or None


def _parse_yield(value: Any) -> int | None:
    if isinstance(value, list):
        for item in value:
            if (parsed := _parse_yield(item)) is not None:
                return parsed
        return None
    if isinstance(value, (int, float)):
        return int(value) or None
    if value is None:
        return None
    match = re.search(r"\d+", str(value))
    return int(match.group()) if match else None


def _parse_image(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value:
        return _parse_image(value[0])
    if isinstance(value, dict):
        return str(value.get("url") or value.get("contentUrl") or "")
    return ""


def _parse_instructions(value: Any) -> list[str]:
    steps: list[str] = []
    if value is None:
        return steps
    if isinstance(value, str):
        text = html.unescape(value)
        text = re.sub(r"<\s*(br|/p|/li)\s*/?>", "\n", text, flags=re.IGNORECASE)
        for line in text.split("\n"):
            if cleaned := _clean(line):
                steps.append(cleaned)
        return steps
    if isinstance(value, dict):
        kind = value.get("@type")
        if isinstance(kind, list):
            kind = kind[0] if kind else None
        if kind == "HowToSection" or "itemListElement" in value:
            section_steps = _parse_instructions(value.get("itemListElement"))
            if (name := _clean(value.get("name"))) and section_steps:
                section_steps[0] = f"{name}: {section_steps[0]}"
            return section_steps
        text = value.get("text") or value.get("name") or value.get("description")
        return _parse_instructions(text)
    if isinstance(value, list):
        for item in value:
            steps.extend(_parse_instructions(item))
    return steps


def _collect_tags(recipe: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    for key in ("recipeCategory", "recipeCuisine", "keywords"):
        value = recipe.get(key)
        if not value:
            continue
        items = value if isinstance(value, list) else str(value).split(",")
        for item in items:
            tag = _clean(item)
            if tag and len(tag) <= 30 and tag.lower() not in {t.lower() for t in tags}:
                tags.append(tag)
    return tags[:10]


def _is_recipe(node: dict[str, Any]) -> bool:
    kind = node.get("@type")
    if isinstance(kind, list):
        return "Recipe" in kind
    return kind == "Recipe"


def _find_recipe(data: Any) -> dict[str, Any] | None:
    if isinstance(data, list):
        for item in data:
            if found := _find_recipe(item):
                return found
        return None
    if not isinstance(data, dict):
        return None
    if _is_recipe(data):
        return data
    for key in ("@graph", "mainEntity", "mainEntityOfPage", "itemListElement"):
        if key in data and (found := _find_recipe(data[key])):
            return found
    return None


def extract_recipe(page: str, url: str = "") -> dict[str, Any]:
    """Extract a recipe dict from an HTML page."""
    for block in _LD_JSON_RE.findall(page):
        raw = block.strip()
        raw = raw.removeprefix("<!--").removesuffix("-->")
        raw = raw.replace("<![CDATA[", "").replace("]]>", "").strip()
        try:
            data = json.loads(raw)
        except ValueError:
            try:
                data = json.loads(raw, strict=False)
            except ValueError:
                continue
        if not (recipe := _find_recipe(data)):
            continue
        name = _clean(recipe.get("name"))
        if not name:
            continue
        ingredients = recipe.get("recipeIngredient") or recipe.get("ingredients") or []
        if isinstance(ingredients, str):
            ingredients = [ingredients]
        prep = parse_duration(recipe.get("prepTime"))
        cook = parse_duration(recipe.get("cookTime"))
        total = parse_duration(recipe.get("totalTime"))
        if total is None and (prep or cook):
            total = (prep or 0) + (cook or 0)
        return {
            "name": name,
            "servings": _parse_yield(recipe.get("recipeYield")),
            "ingredients": [_clean(i) for i in ingredients if _clean(i)],
            "steps": _parse_instructions(recipe.get("recipeInstructions")),
            "prep_time": prep,
            "cook_time": cook,
            "total_time": total,
            "tags": _collect_tags(recipe),
            "image": _parse_image(recipe.get("image")),
            "notes": _clean(recipe.get("description"))[:1000],
            "source_url": url,
        }
    raise RecipeImportError(
        translation_domain=DOMAIN,
        translation_key="no_recipe_found",
        translation_placeholders={"url": url},
    )


async def async_fetch_recipe(hass: HomeAssistant, url: str) -> dict[str, Any]:
    """Download a page and extract the recipe."""
    if not re.match(r"^https?://", url, re.IGNORECASE):
        raise RecipeImportError(
            translation_domain=DOMAIN,
            translation_key="invalid_url",
            translation_placeholders={"url": url},
        )
    session = async_get_clientsession(hass)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 HomeAssistant-Essensplaner"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    }
    try:
        async with session.get(
            url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)
        ) as resp:
            if resp.status >= 400:
                raise RecipeImportError(
                    translation_domain=DOMAIN,
                    translation_key="download_failed",
                    translation_placeholders={"url": url, "error": f"HTTP {resp.status}"},
                )
            body = await async_read_body(resp, _MAX_BYTES, truncate=True)
            page = body.decode(resp.charset or "utf-8", errors="replace")
    except (aiohttp.ClientError, TimeoutError) as err:
        raise RecipeImportError(
            translation_domain=DOMAIN,
            translation_key="download_failed",
            translation_placeholders={"url": url, "error": str(err) or type(err).__name__},
        ) from err
    return extract_recipe(page, url)
