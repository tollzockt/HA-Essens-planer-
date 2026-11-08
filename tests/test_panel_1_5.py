"""1.5 phase P7a: the panel's "📦 Artikel" tab, "Produkt wechseln", the search over all
stores and "📰 Prospekte" use the backend as it is (static checks of the panel file; the
UI itself is checked in the browser harness)."""

from __future__ import annotations

from pathlib import Path
import re

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.essensplaner import catalog, products
from custom_components.essensplaner.const import DOMAIN

FRONTEND = Path(__file__).parent.parent / "custom_components" / DOMAIN / "frontend"
PANEL = (FRONTEND / "essensplaner-panel.js").read_text(encoding="utf-8")
COMMON = (FRONTEND / "essensplaner-common.js").read_text(encoding="utf-8")


def _const_keys(name: str) -> list[str]:
    """Keys of a `const NAME = {…};` object or ids of a `const NAME = [[id, …], …];` list."""
    found = re.search(rf"^const {name} = ([\[{{].*?)^[\]}}];$", PANEL, re.M | re.S)
    if found is None:
        found = re.search(rf"^const {name} = ([\[{{].*?[\]}}]);$", PANEL, re.M)
    assert found, name
    body = found.group(1)
    if body.lstrip().startswith("["):
        return re.findall(r'\["(\w+)",', body)
    return re.findall(r'(?:^|[{,\s])"?(\w+)"?: ', body)


async def test_panel_websockets_exist(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Every websocket command the panel sends is registered by the integration (a typo
    would only show as an error in the browser)."""
    used = set(re.findall(r"type: `\$\{DOMAIN\}/(\w+)`", PANEL))
    registered = {
        command.removeprefix(f"{DOMAIN}/")
        for command in hass.data[websocket_api.DOMAIN]
        if command.startswith(f"{DOMAIN}/")
    }
    # 1.5 phase P7a
    for name in (
        "products",
        "product_detail",
        "product_save",
        "product_delete",
        "product_favorite",
        "product_alternatives",
        "product_to_recipe",
        "shopping_set_product",
        "leaflets",
        "article_search",
    ):
        assert name in used, name
    assert used <= registered, sorted(used - registered)


def test_panel_choices_match_the_backend() -> None:
    """Sort, filter, product reasons and leaflet times of the panel are the backend's."""
    assert set(_const_keys("PRODUCT_SORTS")) == set(products.SORTS)
    assert _const_keys("PRODUCT_ONLY") == list(products.ONLY_VALUES)
    assert set(_const_keys("LEAFLET_WHEN")) == set(catalog.LEAFLET_WHEN)
    reasons = {
        products.REASON_MANUAL,
        products.REASON_FAVORITE,
        products.REASON_PICKED,
        products.REASON_BOUGHT,
        products.REASON_CHEAPEST,
        products.REASON_OFFER,
    }
    assert set(_const_keys("PRODUCT_REASON")) == reasons
    assert 'const OFFERS_MODES = ["recipes", "stores", "leaflets"];' in PANEL


def test_panel_tabs_and_search_scope() -> None:
    """ "📦 Artikel" sits between the shopping list and the offers; "Artikel hinzufügen"
    searches every saved store (scope all) and adds database hits with their product_id."""
    tabs = re.findall(r'<button class="tab" data-tab="(\w+)"', PANEL)
    assert tabs == ["plan", "recipes", "shopping", "products", "offers", "stores"]
    searches = re.findall(r"type: `\$\{DOMAIN\}/article_search`[^}]*\}", PANEL)
    assert len(searches) == 2 and all('scope: "all"' in s for s in searches)
    assert "data.product_id = productId" in PANEL
    assert "product_id: p.id }, true)" in PANEL  # "➕" of a product card


def test_panel_needs_no_new_common_exports() -> None:
    """A cached old essensplaner-common.js (it is loaded without a version) must not break
    the panel: the panel imports only names the shared module has had since 1.4."""
    imported = re.search(
        r"^import \{\n(.*?)\} from \"\./essensplaner-common\.js\";", PANEL, re.M | re.S
    )
    assert imported
    names = re.findall(r"(\w+),", imported.group(1))
    exported = set(re.findall(r"^export (?:const|function) (\w+)", COMMON, re.M))
    assert set(names) <= exported
    assert set(names) <= {
        "CATEGORY_ICONS",
        "CATEGORY_ORDER",
        "DOMAIN",
        "MEAL_STYLE",
        "MONTHS",
        "WEEKDAYS",
        "addDays",
        "beep",
        "dishEmoji",
        "esc",
        "eur",
        "shortDate",
        "findTimers",
        "fold",
        "formatClock",
        "fromIso",
        "greeting",
        "isoWeek",
        "mondayOf",
        "relativeDay",
        "stars",
        "toIso",
        "upcomingMeal",
        "weekdayIndex",
    }


def test_panel_images_have_placeholders() -> None:
    """Product and leaflet pictures go through one helper with an emoji placeholder, and a
    picture that fails to load is replaced by it (onerror for the whole panel)."""
    assert (
        'this.shadowRoot.addEventListener("error", (ev) => this._brokenImage(ev.target), true);'
        in PANEL
    )
    assert 'data-ph="${esc(ph)}"' in PANEL
    assert 'data-ph="📄"' in PANEL  # leaflet pages
