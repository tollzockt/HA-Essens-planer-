"""Sidebar panel and websocket API for the Essensplaner frontend."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from homeassistant.components import websocket_api
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
import voluptuous as vol

from .const import (
    CARD_FILE,
    DOMAIN,
    EVENT_UPDATED,
    NAME,
    PANEL_COMPONENT,
    PANEL_STATIC_URL,
    PANEL_URL_PATH,
)
from .ingredients import CATEGORY_ORDER

_LOGGER = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).parent / "frontend"
_STATIC_REGISTERED = f"{DOMAIN}_static_registered"
_CARD_REGISTERED = f"{DOMAIN}_card_registered"
# {"module_url": registered module, "removal": task removing the panel after a reload}
_PANEL_STATE = f"{DOMAIN}_panel"


def _version() -> str:
    try:
        manifest = json.loads((Path(__file__).parent / "manifest.json").read_text())
        return str(manifest.get("version", "0"))
    except (OSError, ValueError):
        return "0"


async def _async_register_static(hass: HomeAssistant) -> bool:
    """Serve the frontend folder. Returns False if the frontend is unavailable."""
    if "frontend" not in hass.config.components or hass.http is None:
        _LOGGER.debug("Frontend not loaded, skipping panel and card")
        return False
    # Imported lazily so the integration also works without the frontend (tests).
    from homeassistant.components.http import StaticPathConfig

    if not hass.data.get(_STATIC_REGISTERED):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(PANEL_STATIC_URL, str(FRONTEND_DIR), cache_headers=False)]
        )
        hass.data[_STATIC_REGISTERED] = True
    return True


async def async_register_card(hass: HomeAssistant) -> None:
    """Load the dashboard card on every frontend page (no manual resource needed)."""
    if hass.data.get(_CARD_REGISTERED) or not await _async_register_static(hass):
        return
    from homeassistant.components.frontend import add_extra_js_url

    version = await hass.async_add_executor_job(_version)
    add_extra_js_url(hass, f"{PANEL_STATIC_URL}/{CARD_FILE}?v={version}")
    hass.data[_CARD_REGISTERED] = True


async def async_register_panel(hass: HomeAssistant) -> bool:
    """Register the sidebar panel. Returns False if the frontend is unavailable.

    A panel still registered from before a reload of the entry stays as it is (see
    async_remove_panel): registering it again would tell the frontend twice that the
    panel list changed."""
    if not await _async_register_static(hass):
        return False
    from homeassistant.components import frontend, panel_custom

    state = hass.data.setdefault(_PANEL_STATE, {})
    if (removal := state.pop("removal", None)) is not None:
        removal.cancel()  # set up again (reload): the panel stays
    version = await hass.async_add_executor_job(_version)
    module_url = f"{PANEL_STATIC_URL}/essensplaner-panel.js?v={version}"
    registered = PANEL_URL_PATH in hass.data.get(frontend.DATA_PANELS, {})
    if registered and state.get("module_url") == module_url:
        return True
    if registered:  # new files without a restart: the new module needs a new registration
        frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_COMPONENT,
        sidebar_title=NAME,
        sidebar_icon="mdi:silverware-fork-knife",
        module_url=module_url,
        require_admin=False,
        config={},
    )
    state["module_url"] = module_url
    return True


@callback
def async_remove_panel(hass: HomeAssistant) -> None:
    """Remove the sidebar panel when the entry is unloaded – during a reload (e.g. after
    saving the settings in the panel) only once the reload is over and only if it did not
    register the panel again (panel switched off, entry disabled or deleted).

    The frontend asks for the panel list as soon as it changes; a list without the open
    panel sends the user to the default dashboard, and the panel would be gone."""
    from homeassistant.components import frontend

    state = hass.data.setdefault(_PANEL_STATE, {})
    if (old := state.pop("removal", None)) is not None:
        old.cancel()
    # a reload, a removal or a disabling holds the entry's setup lock until it is over
    locks = [
        lock
        for entry in hass.config_entries.async_entries(DOMAIN)
        if (lock := getattr(entry, "setup_lock", None)) is not None and lock.locked()
    ]

    @callback
    def _remove() -> None:
        frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
        state.pop("module_url", None)

    if not locks:
        _remove()
        return

    async def _remove_after_reload() -> None:
        for lock in locks:
            async with lock:
                pass
        if state.get("removal") is task:
            state.pop("removal")
            _remove()

    task = hass.async_create_background_task(
        _remove_after_reload(), f"{DOMAIN}_panel_removal", eager_start=False
    )
    state["removal"] = task


def _entity_ids(hass: HomeAssistant, entry_id: str) -> dict[str, str | None]:
    registry = er.async_get(hass)
    return {
        "shopping_list": registry.async_get_entity_id("todo", DOMAIN, f"{entry_id}_shopping_list"),
        "calendar": registry.async_get_entity_id("calendar", DOMAIN, f"{entry_id}_meal_plan"),
        "next_meal": registry.async_get_entity_id("sensor", DOMAIN, f"{entry_id}_next_meal"),
    }


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/data"})
@callback
def ws_get_data(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return all data for the panel."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], "not_loaded", "Essensplaner ist nicht eingerichtet")
        return
    entry = entries[0]
    manager = entry.runtime_data
    data = manager.export()
    data["entities"] = _entity_ids(hass, entry.entry_id)
    # readable names of the "immer hier kaufen" products (also ones not on the list)
    data["store_preference_names"] = {
        key: manager._preference_name(key) for key in data.get("store_preferences") or {}
    }
    connection.send_result(msg["id"], data)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/subscribe"})
@callback
def ws_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Notify the panel whenever data changes."""

    @callback
    def forward(event: Event) -> None:
        connection.send_message(websocket_api.event_message(msg["id"], dict(event.data)))

    connection.subscriptions[msg["id"]] = hass.bus.async_listen(EVENT_UPDATED, forward)
    connection.send_result(msg["id"])


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/prices"})
@callback
def ws_get_prices(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """All known ingredient prices (estimates, learned, own)."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], "not_loaded", "Essensplaner ist nicht eingerichtet")
        return
    connection.send_result(msg["id"], {"prices": entries[0].runtime_data.prices_view()})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/store_prices",
        vol.Optional("query"): str,
        vol.Optional("limit", default=400): vol.All(int, vol.Range(min=1, max=2000)),
    }
)
@callback
def ws_store_prices(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Price list per store (estimate + each retailer's prices)."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], "not_loaded", "Essensplaner ist nicht eingerichtet")
        return
    connection.send_result(
        msg["id"], entries[0].runtime_data.store_price_matrix(msg.get("query"), msg["limit"])
    )


def _loaded_manager(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> Any:
    """The manager of the loaded entry (sends an error and returns None if not loaded)."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], "not_loaded", "Essensplaner ist nicht eingerichtet")
        return None
    return entries[0].runtime_data


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/branches"})
@callback
def ws_branches(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """The user's branches, the main branch and the postcodes offers are searched at."""
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    connection.send_result(msg["id"], manager.branches_export())


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/reorder_branches", vol.Required("ids"): [str]}
)
@callback
def ws_reorder_branches(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Change the order (priority) of the branches."""
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    manager.reorder_branches(msg["ids"])
    connection.send_result(msg["id"], manager.branches_export())


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/forget_store_preference", vol.Required("key"): str}
)
@callback
def ws_forget_store_preference(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """✕ at a product of "Immer hier gekauft": forget exactly this remembered product key.

    The panel has the stored key; the set_shopping_store service would parse it as a
    spoken name again ("bio milch" is "Milch") and might find another list item
    ("Vollmilch" for "milch"). Open items of this product are assigned automatically
    again: a store choice at the forgotten chain came with "immer" (set_shopping_store
    always=True sets both) and is dropped, one at another store is the item's own choice
    and stays. Result {key, retailer (None if nothing was remembered), items: [uid]}.
    """
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    key = msg["key"]
    retailer = manager.store_preferences.pop(key, None)
    manager.store_preference_aliases.pop(key, None)
    if retailer is None:
        connection.send_result(msg["id"], {"key": key, "retailer": None, "items": []})
        return
    items = [i for i in manager.shopping if i.get("key") == key]
    for item in items:
        override = manager.get_branch(item.get("store_override"))
        if override is not None and override.get("retailer") != retailer:
            continue  # the item's own choice of another store
        item.pop("store_override", None)
        if isinstance(item.get("chosen"), dict):
            item["chosen"].pop("pins_store", None)
    open_items = [i for i in items if i.get("status") != "completed"]
    if manager.store_split_active:
        manager.assign_stores(open_items)
        for item in open_items:
            manager.update_shopping_description(item)
    manager._changed("shopping")
    connection.send_result(
        msg["id"],
        {"key": key, "retailer": retailer, "items": [i["uid"] for i in open_items]},
    )


def merge_article_results(
    manager: Any,
    query: str,
    local: list[dict[str, Any]],
    live: list[dict[str, Any]],
    limit: int,
    scope: str = "main",
) -> list[dict[str, Any]]:
    """Local and live article hits in one order: offers and exact matches first, at most limit.

    Both lists come ranked from the manager (match quality); this only merges them. Live
    offers that are also saved offers (local hits) are left out. When the query names an
    article (a hit matches it exactly, e.g. "Butter"), an offer that is another product
    ("Butterkekse", "Erdnussbutter", "Gehackte Tomaten" for "Tomaten" – the manager's
    _is_article rule, as for the shopping list) ranks like a substring match, so it never
    comes before the article itself. A match is only ever lowered here, never raised.

    scope "all" (1.5): the hits of every store, cheapest first within the match tier
    (articles.sort_all); a live hit of a product that is already a local hit (same product
    of the product database or the same offer) is left out.
    """
    from .articles import MATCH_EXACT, MATCH_SUBSTRING, SCOPE_ALL, _sort_key, sort_all
    from .ingredients import ingredient_key

    known = {(r.get("offer") or {}).get("id") for r in local if r.get("offer")}
    if scope == SCOPE_ALL:
        products = {r.get("product_id") for r in local if r.get("product_id")}
        merged = [
            *local,
            *(
                r
                for r in live
                if (r.get("offer") or {}).get("id") not in known
                and (not r.get("product_id") or r["product_id"] not in products)
            ),
        ]
        return sort_all(merged)[: max(1, limit)]
    merged = [*local, *(r for r in live if (r.get("offer") or {}).get("id") not in known)]
    key = ingredient_key(query)
    if key and any(r["match"] == MATCH_EXACT for r in merged):

        def other_product(result: dict[str, Any]) -> bool:
            if result["source"] not in ("offer", "live"):
                return False
            if not MATCH_EXACT < result["match"] < MATCH_SUBSTRING:
                return False
            texts = (result.get("title") or "", result.get("key") or "")
            return not any(manager._is_article(t, key) for t in texts if t)

        merged = [{**r, "match": MATCH_SUBSTRING} if other_product(r) else r for r in merged]
    merged.sort(key=lambda r: (_sort_key(r), r.get("unit_price") or 9e9, r.get("price") or 0))
    return merged[: max(1, limit)]


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/article_search",
        vol.Required("query"): str,
        vol.Optional("store"): vol.Any(str, None),
        vol.Optional("live", default=False): bool,
        vol.Optional("limit"): vol.All(int, vol.Range(min=1, max=50)),
        vol.Optional("scope", default="main"): vol.In(["main", "all"]),
    }
)
@websocket_api.async_response
async def ws_article_search(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Articles for the "Artikel hinzufügen" field (local; live=True also online sources).

    scope "main" (default): the given store, else the main branch; "all" (1.5): every
    selected store, cheapest first within the match tier (only the given store's chain
    with store). limit default 10 (main) / 20 (all), at most 50.

    Result {query, scope, store: {branch_id, retailer, retailer_name, label, postcode,
    main} | None, results: [...], live: bool, error: str | None, superseded: bool}.
    """
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .articles import ALL_LIMIT, MAIN_LIMIT, SCOPE_ALL
    from .manager import error_message  # avoid loading the manager for the panel only

    query = msg["query"]
    scope = msg["scope"]
    limit = msg.get("limit") or (ALL_LIMIT if scope == SCOPE_ALL else MAIN_LIMIT)
    try:
        branch, retailer = manager.article_target(msg.get("store"))
        if scope == SCOPE_ALL and not msg.get("store"):
            branch, retailer = None, None  # every store
        results = manager.search_articles(query, msg.get("store"), limit, scope)
        response = {"results": [], "live": False, "error": None}
        if msg["live"]:
            response = await manager.async_search_articles_live(
                query, msg.get("store"), limit, scope
            )
    except ServiceValidationError as err:
        connection.send_error(msg["id"], "invalid_store", error_message(err))
        return
    connection.send_result(
        msg["id"],
        {
            "query": query,
            "scope": scope,
            "store": manager.article_store_info(branch, retailer),
            "results": merge_article_results(
                manager, query, results, response["results"], limit, scope
            ),
            "live": response["live"],
            "error": response["error"],
            "superseded": bool(response.get("superseded")),
        },
    )


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/compare_prices", vol.Required("item"): str}
)
@callback
def ws_compare_prices(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Price of a product at every selected store (store picker of the shopping list)."""
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .manager import error_message

    try:
        result = manager.compare_prices(msg["item"])
    except ServiceValidationError as err:
        connection.send_error(msg["id"], "invalid_item", error_message(err))
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/find_branches",
        vol.Optional("zones"): [str],
        vol.Optional("radius_km"): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=25)),
        vol.Optional("route"): bool,
        vol.Optional("route_radius_m"): vol.All(vol.Coerce(int), vol.Range(min=100, max=5000)),
        vol.Optional("retailers"): [str],
        vol.Optional("refresh", default=False): bool,
        vol.Optional("cached_only", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_find_branches(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Supermarkets near the zones and on the way to work (OpenStreetMap).

    Same parameters and result as the find_branches service (plus "defaults": the radius
    and commute settings from the options); cached_only=True returns the last stored search
    without any request. Error codes are the translation keys
    (overpass_busy, overpass_timeout, overpass_failed, branch_search_wait,
    zone_not_found, no_search_area, unknown_store) with a German message.
    """
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .branches import async_find_branches, search_defaults
    from .manager import error_message

    try:
        result = await async_find_branches(
            hass,
            manager,
            zones=msg.get("zones") or None,
            radius_km=msg.get("radius_km"),
            route=msg.get("route"),
            route_radius_m=msg.get("route_radius_m"),
            retailers=msg.get("retailers") or None,
            refresh=msg["refresh"],
            cached_only=msg["cached_only"],
        )
    except HomeAssistantError as err:
        code = getattr(err, "translation_key", None) or "search_failed"
        connection.send_error(msg["id"], code, error_message(err))
        return
    # preset of the panel's search form (radius / commute from the options)
    connection.send_result(msg["id"], {**result, "defaults": search_defaults(manager.options)})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/rewe_markets", vol.Optional("zip"): vol.Any(str, None)}
)
@websocket_api.async_response
async def ws_rewe_markets(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """REWE markets near a postcode ("Markt suchen" of a REWE branch, experimental).

    Same result as the find_rewe_markets service: {zip_code, markets: [{id, name, street,
    postcode, city, label, lat, lon, branch_id}]}. Error codes are the translation keys
    (invalid_postcode, rewe_postcode_required, rewe_blocked, rewe_failed) with a German
    message.
    """
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .manager import error_message
    from .rewe import async_find_rewe_markets

    try:
        result = await async_find_rewe_markets(hass, manager, msg.get("zip"))
    except HomeAssistantError as err:
        code = getattr(err, "translation_key", None) or "search_failed"
        connection.send_error(msg["id"], code, error_message(err))
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/edeka_markets", vol.Optional("zip"): vol.Any(str, None)}
)
@websocket_api.async_response
async def ws_edeka_markets(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """EDEKA markets near a postcode ("Markt suchen" of an EDEKA branch).

    Same result as the find_edeka_markets service: {zip_code, markets: [{id, name, channel,
    street, postcode, city, label, lat, lon, branch_id}]}. Error codes are the translation
    keys (invalid_postcode, edeka_postcode_required, edeka_blocked, edeka_failed) with a
    German message.
    """
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .edeka import async_find_edeka_markets
    from .manager import error_message

    try:
        result = await async_find_edeka_markets(hass, manager, msg.get("zip"))
    except HomeAssistantError as err:
        code = getattr(err, "translation_key", None) or "search_failed"
        connection.send_error(msg["id"], code, error_message(err))
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/aldi_stores",
        vol.Optional("zip"): vol.Any(str, None),
        vol.Inclusive("lat", "location"): vol.All(vol.Coerce(float), vol.Range(min=-90, max=90)),
        vol.Inclusive("lon", "location"): vol.All(vol.Coerce(float), vol.Range(min=-180, max=180)),
    }
)
@websocket_api.async_response
async def ws_aldi_stores(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """ALDI SÜD stores near a location ("Filiale suchen" of an ALDI SÜD branch).

    Same result as the find_aldi_stores service: {location: {lat, lon, source, zip_code},
    stores: [{id, name, street, postcode, city, label, lat, lon, distance_km, branch_id}]}.
    Error codes are the translation keys (invalid_postcode, aldi_postcode_unknown,
    aldi_location_required, aldi_blocked, aldi_failed) with a German message.
    """
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .aldi import async_find_aldi_stores
    from .manager import error_message

    try:
        result = await async_find_aldi_stores(
            hass, manager, msg.get("zip"), msg.get("lat"), msg.get("lon")
        )
    except HomeAssistantError as err:
        code = getattr(err, "translation_key", None) or "search_failed"
        connection.send_error(msg["id"], code, error_message(err))
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/store_offers",
        vol.Optional("branch_ids"): vol.Any(None, [str]),
        vol.Optional("when", default="current"): vol.In(["current", "upcoming", "all"]),
        vol.Optional("kind", default="all"): vol.In(
            ["food", "drugstore", "household", "nonfood", "all"]
        ),
        vol.Optional("query"): vol.Any(None, str),
        vol.Optional("mine", default=False): bool,
        vol.Optional("sort", default="saving"): vol.In(
            ["saving", "price", "unit_price", "name", "store"]
        ),
        vol.Optional("offset", default=0): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional("limit", default=60): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
        vol.Optional("include_online", default=False): bool,
    }
)
@callback
def ws_store_offers(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """All current offers of the saved stores (offer catalog), per store selectable.

    branch_ids: only these branches (default all selected ones); when: current | upcoming |
    all; kind: food | drugstore | household | nonfood (drugstore + household) | all; query: text or ingredient; mine: only
    offers of planned / favourite / listed ingredients; sort: saving | price | unit_price |
    name | store; offset / limit (≤ 100) page the offers. Result {total, offset, limit,
    offers: [{id, title, brand, description, price, old_price, regular_price, app_price,
    loyalty, loyalty_note, online_only, unit_price, base_unit, pack_amount, pack_unit,
    valid_from, valid_to, current, image, kind, retailer, store, branch_ids, keys, source,
    saving, discount}], stores: [{branch_id, label, retailer, store, main, count_current,
    count_upcoming, sources, leaflet_only, leaflets, status, error}], meta: {updated,
    last_run, status, errors, marktguru, sources, count, blocked_until}}. Nothing is
    fetched (refresh_offers fetches).
    """
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .catalog import store_offers_view

    connection.send_result(
        msg["id"],
        store_offers_view(
            manager,
            branch_ids=msg.get("branch_ids") or None,
            when=msg["when"],
            kind=msg["kind"],
            query=msg.get("query"),
            mine=msg["mine"],
            sort=msg["sort"],
            offset=msg["offset"],
            limit=msg["limit"],
            include_online=msg["include_online"],
        ),
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/leaflets",
        vol.Optional("when", default="all"): vol.In(["current", "upcoming", "all"]),
        vol.Optional("branch_ids"): vol.Any(None, [str]),
    }
)
@callback
def ws_leaflets(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """The leaflets of the saved branches ("📰 Prospekte", 1.5): marktguru leaflets (every
    branch with the option all_leaflets, else the chains without single offers), ALDI SÜD's
    own list and the chains' own leaflet pages as links. when: current | upcoming | all;
    branch_ids: only leaflets of these branches. Result {leaflets: [{id, leaflet_id, source,
    retailer, store, name, valid_from, valid_to, current, page_count, page_base, cover,
    pages, page_url_template, zoom_url_template, thumb_url_template, url, offer_count,
    branch_ids, labels}], branches: [{branch_id, label, retailer, store, main,
    count_current, count_upcoming, link}], links: [{retailer, store, url, branch_ids,
    labels, has_leaflets}], meta: {marktguru, all_leaflets, aldi_direct, updated, errors,
    blocked_until, count}}. Nothing is fetched (refresh_offers fetches)."""
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .catalog import leaflets_view

    connection.send_result(
        msg["id"],
        leaflets_view(manager, when=msg["when"], branch_ids=msg.get("branch_ids") or None),
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/season",
        vol.Optional("date"): vol.Any(None, str),
        vol.Optional("limit", default=12): vol.All(vol.Coerce(int), vol.Range(min=1, max=50)),
    }
)
@callback
def ws_season(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """What is in season (1.5, season.py) on a day (date: "morgen", "24.12." or ISO;
    default today): {date, month, month_name, season {id, label, emoji}, windows [{id, label,
    emoji, start, end}], upcoming [...], produce [{id, label, strict, new, ending}], coming
    [labels], text, recipes [{id, name, image, score, items, windows, hints}] (the best
    fitting, at most limit), out_of_season [{id, name, items}], season_aware}."""
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .dates import DateParseError, parse_date
    from .season import season_view

    day = manager.today()
    if msg.get("date"):
        try:
            day, _ = parse_date(msg["date"], manager.today())
        except DateParseError:
            from .manager import ERROR_MESSAGES_DE

            connection.send_error(
                msg["id"],
                "invalid_date",
                ERROR_MESSAGES_DE["invalid_date"].format(date=msg["date"]),
            )
            return
    connection.send_result(msg["id"], season_view(manager, day, msg["limit"]))


def _receipt_signer(hass: HomeAssistant, connection: websocket_api.ActiveConnection) -> Any:
    """Signed image links for this connection (an <img> cannot send the token)."""
    from .receipts import image_link

    def sign(receipt_id: str) -> str:
        return image_link(hass, receipt_id, connection.refresh_token_id)

    return sign


def _receipt_error(
    connection: websocket_api.ActiveConnection, msg: dict[str, Any], err: HomeAssistantError
) -> None:
    from .manager import error_message

    code = getattr(err, "translation_key", None) or "receipt_failed"
    connection.send_error(msg["id"], code, error_message(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/receipts",
        vol.Optional("limit", default=50): vol.All(vol.Coerce(int), vol.Range(min=1, max=200)),
    }
)
@websocket_api.require_admin
@callback
def ws_receipts(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Stored receipts, newest first (admins).

    Result {count, last_date, prices, ai_entity, ai_available, receipts: [{id, branch_id,
    retailer, retailer_name, store_label, date, total, sum, items, source, image,
    media_content_id, image_url (signed, 24 h), prices, created, updated}]}.
    """
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .receipts import receipts_view

    connection.send_result(
        msg["id"], receipts_view(manager, msg["limit"], _receipt_signer(hass, connection))
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/receipt_parse",
        vol.Exclusive("text", "receipt"): str,
        vol.Exclusive("upload_id", "receipt"): str,
        vol.Optional("branch"): vol.Any(None, str),
        vol.Optional("ai", default=True): bool,
        vol.Optional("entity_id"): vol.Any(None, str),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_receipt_parse(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Proposal of a receipt: pasted text (parsed locally) or an uploaded photo / PDF
    (upload_id from /api/essensplaner/receipt_upload, read by the AI Task entity; ai=False
    refuses to send it). Same result as the receipt_parse_text / receipt_scan services plus
    image_url. Error codes are the translation keys (receipt_no_items,
    receipt_ai_not_configured, receipt_ai_unavailable, receipt_ai_failed,
    receipt_ai_invalid, receipt_upload_not_found, branch_not_found) with a German message.
    """
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .manager import _error
    from .receipts import async_parse_receipt_text, async_scan_receipt

    try:
        if msg.get("text") is not None:
            result = await async_parse_receipt_text(manager, msg["text"], msg.get("branch"))
        elif msg.get("upload_id"):
            if not msg["ai"]:
                raise _error("receipt_ai_not_configured")
            result = await async_scan_receipt(
                hass,
                manager,
                upload_id=msg["upload_id"],
                entity_id=msg.get("entity_id") or None,
                branch=msg.get("branch"),
            )
        else:
            raise _error("receipt_no_items")
    except HomeAssistantError as err:
        _receipt_error(connection, msg, err)
        return
    sign = _receipt_signer(hass, connection)
    result["image_url"] = sign(result["upload_id"]) if result.get("upload_id") else None
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/receipt_save", vol.Required("receipt"): dict}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_receipt_save(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Store a reviewed receipt and set its prices (as the receipt_save service)."""
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .receipts import async_save_receipt, receipt_view

    try:
        result = await async_save_receipt(manager, dict(msg["receipt"]))
    except HomeAssistantError as err:
        _receipt_error(connection, msg, err)
        return
    stored = manager.receipts.get(result["receipt"]["id"])
    if stored is not None:
        result["receipt"] = receipt_view(manager, stored, _receipt_signer(hass, connection))
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/receipt_delete",
        # "id" is the websocket message id
        vol.Required("receipt_id"): str,
        vol.Optional("remove_prices", default=False): bool,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_receipt_delete(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Delete a receipt and its image (as the delete_receipt service with id = receipt_id)."""
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .receipts import async_delete_receipt

    try:
        result = await async_delete_receipt(manager, msg["receipt_id"], msg["remove_prices"])
    except HomeAssistantError as err:
        _receipt_error(connection, msg, err)
        return
    connection.send_result(msg["id"], result)


def _settings_entry(hass: HomeAssistant) -> Any:
    """The config entry the settings belong to (loaded first; also a not loaded one, so
    broken settings can be fixed)."""
    loaded = hass.config_entries.async_loaded_entries(DOMAIN)
    if loaded:
        return loaded[0]
    entries = hass.config_entries.async_entries(DOMAIN)
    return entries[0] if entries else None


def _entity_choices(
    hass: HomeAssistant, domain: str, current: Any, exclude: set[str] | None = None
) -> list[dict[str, Any]]:
    """[{value, label, available}] of the entities of a domain (current values that do not
    exist any more are listed too, so they can be seen and removed)."""
    from homeassistant.const import STATE_UNAVAILABLE

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for state in hass.states.async_all(domain):
        if exclude and state.entity_id in exclude:
            continue
        seen.add(state.entity_id)
        result.append(
            {
                "value": state.entity_id,
                "label": str(state.attributes.get("friendly_name") or state.entity_id),
                "available": state.state != STATE_UNAVAILABLE,
            }
        )
    result.sort(key=lambda c: c["label"].casefold())
    for value in current if isinstance(current, list) else [current]:
        if value and value not in seen:
            result.append({"value": value, "label": value, "available": False, "missing": True})
    return result


def _settings_warnings(
    hass: HomeAssistant, manager: Any, values: dict[str, Any]
) -> list[dict[str, str]]:
    """Hints for the current settings: the marktguru AGB, an unavailable AI Task or AI
    entity, chain sources that are on but have no linked branch yet."""
    from .ai import ai_available
    from .const import (
        CONF_AI_ENTITY,
        CONF_ALDI_ONLINE,
        CONF_EDEKA_OFFERS,
        CONF_OFFERS_SOURCE,
        CONF_RECEIPT_AI,
        CONF_REWE_ONLINE,
        CONF_SPLIT_MODE,
        OFFERS_MARKTGURU,
        SPLIT_OFF,
    )
    from .options_schema import MARKTGURU_WARNING_DE

    warnings: list[dict[str, str]] = []
    if values.get(CONF_OFFERS_SOURCE) == OFFERS_MARKTGURU:
        warnings.append({"key": CONF_OFFERS_SOURCE, "message": MARKTGURU_WARNING_DE})
    entity = values.get(CONF_RECEIPT_AI)
    if entity:
        state = hass.states.get(entity)
        if state is None or state.state == "unavailable":
            warnings.append(
                {
                    "key": CONF_RECEIPT_AI,
                    "message": f"Die KI-Aufgabe {entity} ist gerade nicht erreichbar – Fotos "
                    "werden erst gelesen, wenn sie wieder verfügbar ist. Text einfügen geht "
                    "immer.",
                }
            )
    ai_entity = values.get(CONF_AI_ENTITY)
    if ai_entity and not ai_available(hass, ai_entity):
        warnings.append(
            {
                "key": CONF_AI_ENTITY,
                "message": f"Die KI {ai_entity} ist gerade nicht erreichbar – die "
                "KI-Funktionen warten, bis sie wieder verfügbar ist; alles andere funktioniert "
                "ohne KI.",
            }
        )
    branches = list(getattr(manager, "branches", None) or [])

    def linked(retailer: str, field: str | None = None) -> bool:
        return any(
            b.get("retailer") == retailer
            and b.get("selected", True)
            and (not field or b.get(field))
            for b in branches
        )

    if manager is not None:
        if values.get(CONF_REWE_ONLINE) and not linked("rewe", "rewe_market_id"):
            warnings.append(
                {
                    "key": CONF_REWE_ONLINE,
                    "message": "REWE-Onlinepreise brauchen eine REWE-Filiale mit Markt-ID "
                    "(🏪 Läden & Preise → „Markt suchen“).",
                }
            )
        if values.get(CONF_ALDI_ONLINE) and not linked("aldi-sued"):
            warnings.append(
                {
                    "key": CONF_ALDI_ONLINE,
                    "message": "ALDI-SÜD-Preise brauchen eine gespeicherte ALDI-SÜD-Filiale "
                    "(🏪 Läden & Preise).",
                }
            )
        if values.get(CONF_EDEKA_OFFERS) and not linked("edeka", "edeka_market_id"):
            warnings.append(
                {
                    "key": CONF_EDEKA_OFFERS,
                    "message": "EDEKA-Angebote brauchen eine EDEKA-Filiale mit Markt-ID "
                    "(🏪 Läden & Preise → „EDEKA-Markt suchen“).",
                }
            )
        if values.get(CONF_SPLIT_MODE) != SPLIT_OFF and manager.get_main_branch() is None:
            warnings.append(
                {
                    "key": CONF_SPLIT_MODE,
                    "message": "Die Aufteilung nach Läden wirkt, sobald du in „🏪 Läden & "
                    "Preise“ einen Hauptladen gewählt hast.",
                }
            )
    return warnings


def settings_view(hass: HomeAssistant, entry: Any) -> dict[str, Any]:
    """Everything the panel's settings view needs (websocket essensplaner/get_settings)."""
    from .ai import entity_choices
    from .const import (
        AI_FEATURES,
        ALL_MEALS,
        CONF_AI_ENTITY,
        CONF_BRANCH_ZONES,
        CONF_RECEIPT_AI,
        CONF_SYNC_TODO,
        SPLIT_MODES,
        STRATEGIES,
    )
    from .options_schema import (
        OFFERS_SOURCES,
        SECTIONS,
        choice_list,
        current_values,
        default_values,
        describe_fields,
        store_choices,
    )

    manager = getattr(entry, "runtime_data", None)
    if not hasattr(manager, "branch_postcodes"):
        manager = None
    values = current_values({**entry.data, **entry.options})
    own_list = _entity_ids(hass, entry.entry_id)["shopping_list"]
    main = manager.get_main_branch() if manager is not None else None
    return {
        "values": values,
        "defaults": default_values(),
        "fields": describe_fields(),
        "sections": SECTIONS,
        "choices": {
            "meals": choice_list("meal", ALL_MEALS),
            "strategies": choice_list("strategy", STRATEGIES),
            "split_modes": choice_list("split_mode", SPLIT_MODES),
            "offers_sources": choice_list("offers_source", OFFERS_SOURCES),
            "stores": store_choices(),
            "zones": _entity_choices(hass, "zone", values[CONF_BRANCH_ZONES]),
            "todo_entities": _entity_choices(
                hass, "todo", values[CONF_SYNC_TODO], {own_list} if own_list else None
            ),
            "ai_task_entities": _entity_choices(hass, "ai_task", values[CONF_RECEIPT_AI]),
            "ai_entities": entity_choices(hass, values[CONF_AI_ENTITY]),
            "ai_features": choice_list("ai_feature", AI_FEATURES),
        },
        "warnings": _settings_warnings(hass, manager, values),
        "branch_postcodes": manager.branch_postcodes() if manager is not None else [],
        "branches": len(manager.branches) if manager is not None else 0,
        "main_branch": manager.branch_label(main) if main else None,
        "loaded": manager is not None,
    }


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/get_settings"})
@websocket_api.require_admin
@callback
def ws_get_settings(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """The settings of the panel's ⚙️ view (admins): {values, defaults, fields, sections,
    choices: {meals, strategies, split_modes, offers_sources, stores, zones, todo_entities,
    ai_task_entities, ai_entities: [{value, label, available, kind (ai_task |
    conversation), missing?}], ai_features: [{value, label}]}, warnings: [{key, message}],
    branch_postcodes, branches, main_branch, loaded}."""
    entry = _settings_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_loaded", "Essensplaner ist nicht eingerichtet")
        return
    connection.send_result(msg["id"], settings_view(hass, entry))


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/save_settings", vol.Required("values"): dict}
)
@websocket_api.require_admin
@callback
def ws_save_settings(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Check and store settings of the panel (admins), with the rules of options_schema.py.

    values: some or all settings (missing ones keep their value; unknown keys are ignored).
    Invalid: {saved: false, errors: {key: German message}} and nothing is stored. Valid: the
    entry's options are updated (other option keys are kept) and the update listener reloads
    the integration: {saved: true, reload: true} – {saved: true, reload: false} when nothing
    changed.
    """
    from .options_schema import current_values, error_messages, merge_options, validate

    entry = _settings_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_loaded", "Essensplaner ist nicht eingerichtet")
        return
    manager = getattr(entry, "runtime_data", None)
    postcodes = manager.branch_postcodes() if hasattr(manager, "branch_postcodes") else []
    options = {**entry.data, **entry.options}
    merged = {**current_values(options), **msg["values"]}
    cleaned, errors = validate(merged, postcodes)
    if errors:
        connection.send_result(msg["id"], {"saved": False, "errors": error_messages(errors)})
        return
    new_options = merge_options(entry.options, cleaned)
    changed = hass.config_entries.async_update_entry(entry, options=new_options)
    connection.send_result(msg["id"], {"saved": True, "reload": bool(changed)})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/ai_status"})
@websocket_api.require_admin
@callback
def ws_ai_status(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """The AI via Home Assistant (admins, 1.5): {entity, mode (ai_task | conversation),
    label, configured, available, features: [feature], ready: {feature: bool},
    receipts_entity, receipts_available, busy, last: {ok, seconds, mode, feature, code, at}}."""
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .ai import ai_status

    connection.send_result(msg["id"], ai_status(hass, manager))


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/ai_test", vol.Optional("entity_id"): vol.Any(None, str)}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_ai_test(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """ "Verbindung testen" (admins, 1.5): a tiny request to the given AI entity (also one
    not saved yet) or the configured one. {ok, entity, mode, seconds, code, error} – code
    and German error when it failed (ai_not_configured, ai_unavailable, ai_busy,
    ai_failed, ai_invalid); never a websocket error for a failing AI."""
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .ai import async_ai_test

    connection.send_result(
        msg["id"], await async_ai_test(hass, manager, msg.get("entity_id") or None)
    )


# ----------------------------------------------------------------------
# Product database (1.5, products.py)
# ----------------------------------------------------------------------


def _product_error(
    connection: websocket_api.ActiveConnection, msg: dict[str, Any], err: HomeAssistantError
) -> None:
    from .manager import error_message

    code = getattr(err, "translation_key", None) or "product_failed"
    connection.send_error(msg["id"], code, error_message(err))


def _products_changed(hass: HomeAssistant) -> None:
    """Tell open panels that products changed (their list, ⭐) – nothing else is saved."""
    hass.bus.async_fire(EVENT_UPDATED, {"change": "products"})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/products",
        vol.Optional("query"): vol.Any(None, str),
        vol.Optional("retailers"): vol.Any(None, [str]),
        vol.Optional("branch_ids"): vol.Any(None, [str]),
        vol.Optional("category"): vol.Any(None, str),
        vol.Optional("kind", default="all"): vol.In(
            ["food", "drugstore", "household", "nonfood", "all"]
        ),
        vol.Optional("only"): vol.Any(
            None, vol.In(["favorites", "offers", "bought", "manual", "unsorted"])
        ),
        vol.Optional("sort", default="price"): vol.In(
            ["price", "unit_price", "saving", "name", "recent"]
        ),
        vol.Optional("offset", default=0): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional("limit", default=60): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
    }
)
@callback
def ws_products(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """The product database ("📦 Artikel"), page by page.

    query: brand, name or ingredient; retailers / branch_ids: only these chains /
    branches; category: an aisle; kind: food | drugstore | household | nonfood | all; only:
    favorites | offers | bought | manual | unsorted (1.5.1: nobody sorted it yet); sort: price | unit_price | saving | name | recent;
    offset / limit (≤ 100). Result {total, offset, limit, products: [{id, title, product,
    brand, description, image, price, regular_price, regular_source, regular_seen,
    old_price, stale, unit_price, base_unit, pack_amount, pack_unit, pack, on_offer,
    current, offer_price, valid_from, valid_to, offer_source, loyalty, loyalty_note,
    app_price, deposit, saving, discount, kind, category, retailer, store, branch_ids,
    keys, source, sources, favorite, favorite_keys, bought, manual, first_seen,
    last_seen, checked (rule | ai | user | None), checked_at, unsorted, ai_fix}], stores: [{branch_id, label, retailer, store, main, count}], categories:
    [{name, count}], counts}. Nothing is fetched.
    """
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .products import products_view

    connection.send_result(
        msg["id"],
        products_view(
            manager,
            query=msg.get("query"),
            retailers=msg.get("retailers") or None,
            branch_ids=msg.get("branch_ids") or None,
            category=msg.get("category") or None,
            kind=msg["kind"],
            only=msg.get("only"),
            sort=msg["sort"],
            offset=msg["offset"],
            limit=msg["limit"],
        ),
    )


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/product_detail", vol.Required("product_id"): str}
)
@callback
def ws_product_detail(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """One product: {product (card), history: [{date, price, kind: regular | offer}], twins
    (the same branded product at other chains), keys: [{key, name}], favorite_for,
    picks: [{key, count, last, kind}]}. Error product_not_found."""
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .products import product_detail

    try:
        connection.send_result(msg["id"], product_detail(manager, msg["product_id"]))
    except HomeAssistantError as err:
        _product_error(connection, msg, err)


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/product_save", vol.Required("product"): dict}
)
@callback
def ws_product_save(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Create or change an own product ("＋ Eigener Artikel"): product {id?, store, name,
    brand?, pack?, price?, image? (https URL), ingredient?, category?, favorite?}. Result
    {product (card)}. Errors name_required, store_required, unknown_store, invalid_price,
    invalid_url, product_not_found."""
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .products import product_card, save_manual

    try:
        product = save_manual(manager, dict(msg["product"]))
    except HomeAssistantError as err:
        _product_error(connection, msg, err)
        return
    _products_changed(hass)
    connection.send_result(msg["id"], {"product": product_card(manager, product)})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/product_classify",
        vol.Required("product_id"): str,
        vol.Optional("category"): vol.Any(None, vol.In(CATEGORY_ORDER)),
        vol.Optional("kind"): vol.Any(
            None, vol.In(["food", "drinks", "drugstore", "household", "nonfood"])
        ),
        vol.Optional("keys"): vol.Any(None, [str]),
    }
)
@callback
def ws_product_classify(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """The user sorts a product (1.5.1, "🗂️ Einordnung" in the product detail): category
    (an aisle), kind (food | drinks | drugstore | household | nonfood), keys (ingredient
    names, [] = none). From then on checked by "user": the AI and the rules never change
    it. Result {product (card)}. Error product_not_found."""
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .products import classify_product, product_card

    try:
        product = classify_product(
            manager,
            msg["product_id"],
            category=msg.get("category"),
            kind=msg.get("kind"),
            keys=msg.get("keys"),
        )
    except HomeAssistantError as err:
        _product_error(connection, msg, err)
        return
    _products_changed(hass)
    connection.send_result(msg["id"], {"product": product_card(manager, product)})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/ai_sort",
        vol.Optional("target", default="all"): vol.In(["products", "recipes", "all"]),
    }
)
@websocket_api.async_response
async def ws_ai_sort(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """ "🤖 Artikel sortieren" / "🤖 Rezepte sortieren" (1.5.1): the AI checks what the rules
    sorted (target products | recipes | all) – a running sort is joined. Result {targets,
    ok, checked, changed, removed, skipped, errors: [German messages], products, recipes,
    status}; progress meanwhile in ai_status / the panel data (ai.sort.running). A failing
    AI is reported in the result (the rules stay), never as a websocket error."""
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .ai_sort import async_sort

    connection.send_result(msg["id"], await async_sort(hass, manager, msg["target"]))


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/product_delete", vol.Required("product_id"): str}
)
@callback
def ws_product_delete(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Delete a product (also its ⭐ and picks): {deleted: id}. Error product_not_found."""
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .products import delete_product

    try:
        product = delete_product(manager, msg["product_id"])
    except HomeAssistantError as err:
        _product_error(connection, msg, err)
        return
    _products_changed(hass)
    connection.send_result(msg["id"], {"deleted": product["id"]})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/product_favorite",
        vol.Required("product_id"): str,
        vol.Optional("key"): vol.Any(None, str),
        vol.Optional("favorite", default=True): bool,
    }
)
@callback
def ws_product_favorite(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """⭐ a product for an ingredient (key; default its first ingredient) or take the ⭐
    away (favorite false; without key from every ingredient). Result {key, product_id,
    favorites: {key: product id}}. Error product_not_found."""
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .products import set_favorite

    try:
        result = set_favorite(manager, msg["product_id"], msg.get("key"), msg["favorite"])
    except HomeAssistantError as err:
        _product_error(connection, msg, err)
        return
    _products_changed(hass)
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/product_alternatives",
        vol.Exclusive("key", "what"): str,
        vol.Exclusive("uid", "what"): str,
        vol.Exclusive("product_id", "what"): str,
        vol.Optional("limit", default=20): vol.All(vol.Coerce(int), vol.Range(min=1, max=50)),
    }
)
@callback
def ws_product_alternatives(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Products for an ingredient at all saved chains ("Produkt wechseln"): of a shopping
    item (uid), a product (product_id) or an ingredient (key), cheapest for the needed
    amount first. Result {key, name, item_uid, amounts, current, favorite, alternatives:
    [card + {cost, packs, needed, cost_text}]}. Errors shopping_item_not_found,
    product_not_found."""
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .products import product_alternatives

    try:
        result = product_alternatives(
            manager,
            key=msg.get("key"),
            uid=msg.get("uid"),
            product_id=msg.get("product_id"),
            limit=msg["limit"],
        )
    except HomeAssistantError as err:
        _product_error(connection, msg, err)
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/shopping_set_product",
        vol.Required("uid"): str,
        vol.Optional("product_id"): vol.Any(None, str),
        vol.Optional("remember", default="none"): vol.In(["none", "pick", "favorite"]),
    }
)
@callback
def ws_shopping_set_product(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """ "Produkt wechseln" on the shopping list: buy the item (uid) as this product
    (product_id; None / "" = the list chooses again), priced with its offer or regular price
    at its store; remember none | pick | favorite (⭐ for the ingredient). Result {item,
    stores}. Errors shopping_item_not_found, product_not_found, invalid_remember."""
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    try:
        item = manager.shopping_set_product(msg["uid"], msg.get("product_id"), msg["remember"])
    except HomeAssistantError as err:
        _product_error(connection, msg, err)
        return
    if msg["remember"] == "favorite":
        _products_changed(hass)
    connection.send_result(msg["id"], {"item": item, "stores": manager.stores_summary()})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/product_to_recipe",
        vol.Required("product_id"): str,
        vol.Optional("tags"): vol.Any(None, str, [str]),
    }
)
@callback
def ws_product_to_recipe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """ "Als Rezept speichern" (a ready meal): a recipe with the product as its one
    ingredient, "Nach Packungsanleitung zubereiten." and the product's image; tags default
    ["Fertiggericht"]. Result {recipe: summary}. Errors product_not_found, recipe_exists."""
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .products import product_to_recipe

    try:
        recipe = product_to_recipe(manager, msg["product_id"], msg.get("tags"))
    except HomeAssistantError as err:
        _product_error(connection, msg, err)
        return
    connection.send_result(msg["id"], {"recipe": manager.recipe_summary(recipe)})


# ----------------------------------------------------------------------
# Occasions and drinks (1.5, occasions.py, drinks.py)
# ----------------------------------------------------------------------


def _occasion_error(
    connection: websocket_api.ActiveConnection, msg: dict[str, Any], err: HomeAssistantError
) -> None:
    from .manager import error_message

    code = getattr(err, "translation_key", None) or "occasion_failed"
    connection.send_error(msg["id"], code, error_message(err))


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/occasion_save", vol.Required("occasion"): dict}
)
@callback
def ws_occasion_save(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Create (no id) or change an occasion: occasion {id?, title?, template?, date?
    (ISO or words), time? ("" = all day), duration_h?, guests?, children?, notes?, items?
    (replaces all: [{uid?, course, recipe_id? | product_id? | title, servings?, quantity?,
    unit?, alcohol?, note?}]), add_items?, remove_items? (uids), update_items? (1.5.1, one
    item changed in place: [{uid, servings? (None: the occasion's), quantity?, unit?,
    product_id? (None: no product)}]), auto_fill? (new: dishes, drinks and extras by the
    rules)}. Result {occasion (occasion_view)}. Errors
    occasion_not_found, name_required, invalid_template, invalid_date, invalid_time,
    invalid_course, recipe_not_found, product_not_found."""
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .occasions import occasion_view, save_occasion

    try:
        occasion = save_occasion(manager, dict(msg["occasion"]))
    except HomeAssistantError as err:
        _occasion_error(connection, msg, err)
        return
    connection.send_result(msg["id"], {"occasion": occasion_view(manager, occasion)})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/occasion_delete", vol.Required("occasion_id"): str}
)
@callback
def ws_occasion_delete(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Delete an occasion (its shopping items stay): {deleted: id}. Error
    occasion_not_found."""
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .occasions import delete_occasion

    try:
        occasion = delete_occasion(manager, msg["occasion_id"])
    except HomeAssistantError as err:
        _occasion_error(connection, msg, err)
        return
    connection.send_result(msg["id"], {"deleted": occasion["id"]})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/occasion_suggest",
        vol.Required("occasion_id"): str,
        vol.Optional("course"): vol.Any(
            None, vol.In(["starter", "main", "side", "dessert", "snack", "drink", "extra"])
        ),
        vol.Optional("count", default=5): vol.All(vol.Coerce(int), vol.Range(min=1, max=20)),
        vol.Optional("exclude"): vol.Any(None, [str]),
        vol.Optional("ai", default=False): bool,
        vol.Optional("apply", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_occasion_suggest(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Suggestions for an occasion ("＋ Gericht", "🤖 KI-Menü"): per course (or one course)
    recipes by the planning rules and the template, drinks and missing extras; ai: the AI's
    menu first (feature "occasions"; a failing AI keeps the rule suggestions and reports
    ai {ok: false, code, error}); apply: put the best ones into the occasion. Result
    {occasion, suggestions: {course: [{recipe_id, title, course, cost?, reasons?, …}]},
    applied: [titles], ai: None | {ok, code?, error?}}. Error occasion_not_found."""
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .occasions import async_suggest_menu, require_occasion

    try:
        occasion = require_occasion(manager, msg["occasion_id"])
        result = await async_suggest_menu(
            hass,
            manager,
            occasion,
            course=msg.get("course"),
            count=msg["count"],
            ai=msg["ai"],
            apply=msg["apply"],
            exclude=set(msg.get("exclude") or []),
        )
    except HomeAssistantError as err:
        _occasion_error(connection, msg, err)
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/occasion_products",
        vol.Required("occasion_id"): str,
        vol.Optional("uid"): vol.Any(None, str),
        vol.Optional("name"): vol.Any(None, str),
        vol.Optional("query"): vol.Any(None, str),
        vol.Optional("limit", default=30): vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
    }
)
@callback
def ws_occasion_products(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """ "📦 Artikel" of an occasion item (1.5.1): the products of the user's chains for
    the item (uid: its name and amount; else name) or a query, priced for the amount in
    whole packs, cheapest first. Result {name, quantity, unit, current (product id | None),
    products: [occasions.item_products() rows]}. Errors occasion_not_found,
    occasion_item_not_found."""
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .manager import _error
    from .occasions import _item_name, item_products, occasion_date, require_occasion

    try:
        occasion = require_occasion(manager, msg["occasion_id"])
        item: dict[str, Any] = {}
        if msg.get("uid"):
            item = next((i for i in occasion.get("items") or [] if i.get("uid") == msg["uid"]), {})
            if not item:
                raise _error("occasion_item_not_found", item=msg["uid"], occasion=occasion["title"])
    except HomeAssistantError as err:
        _occasion_error(connection, msg, err)
        return
    name = str(msg.get("name") or _item_name(item) or msg.get("query") or "")
    quantity = item.get("quantity") if not item.get("product_id") else None
    unit = str(item.get("unit") or "")
    if item.get("product_id"):
        from .occasions import _amount_of_packs
        from .products import _store_of

        store = _store_of(manager)
        product = store.get(item["product_id"]) if store is not None else None
        if product is not None and (amount := _amount_of_packs(item, product)):
            quantity, unit = amount
    products = item_products(
        manager,
        name,
        quantity,
        unit,
        occasion_date(occasion),
        query=msg.get("query"),
        limit=msg["limit"],
    )
    connection.send_result(
        msg["id"],
        {
            "name": name,
            "quantity": quantity,
            "unit": unit,
            "current": item.get("product_id"),
            "products": products,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/drinks_suggest",
        vol.Optional("recipe_ids"): vol.Any(None, [str]),
        vol.Optional("titles"): vol.Any(None, [str]),
        vol.Optional("occasion_id"): vol.Any(None, str),
        vol.Optional("date"): vol.Any(None, str),
        vol.Optional("alcohol"): vol.Any(None, bool),
        vol.Optional("guests"): vol.Any(None, vol.All(vol.Coerce(int), vol.Range(min=1, max=200))),
        vol.Optional("children"): vol.Any(
            None, vol.All(vol.Coerce(int), vol.Range(min=0, max=100))
        ),
        vol.Optional("hours"): vol.Any(
            None, vol.All(vol.Coerce(float), vol.Range(min=0.5, max=48))
        ),
        vol.Optional("kind"): vol.Any(
            None,
            vol.In(["wine", "sparkling", "beer", "mixed", "soft", "juice", "hot", "water", "free"]),
        ),
        vol.Optional("ai", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_drinks_suggest(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """ "🍷 Passt dazu": drinks for recipes (recipe_ids) / dish titles and/or an occasion,
    always at least two without alcohol, with alcohol only when allowed (alcohol, default
    the option drinks_alcohol), drinks for children, quantities for guests; ai: the AI's
    drinks first (feature "drinks"). Result {drinks: [{id, title, name, hint, alcohol,
    kids, kind, reason, score, offer?, recipe_id?, liters?, quantity?, unit?, bottles?,
    ai?}], alcohol, reasons, quantities, ai: None | {ok, code?, error?}}. Errors
    recipe_not_found, occasion_not_found, invalid_date."""
    if (manager := _loaded_manager(hass, connection, msg)) is None:
        return
    from .dates import DateParseError, parse_date
    from .manager import _error
    from .occasions import async_suggest_drinks, require_occasion

    try:
        recipes = []
        for recipe_id in msg.get("recipe_ids") or []:
            recipe = manager.recipes.get(recipe_id)
            if recipe is None:
                raise _error("recipe_not_found", name=recipe_id)
            recipes.append(recipe)
        occasion = require_occasion(manager, msg["occasion_id"]) if msg.get("occasion_id") else None
        day = None
        if msg.get("date"):
            try:
                day = parse_date(msg["date"], manager.today())[0]
            except DateParseError as err:
                raise _error("invalid_date", date=msg["date"]) from err
        result = await async_suggest_drinks(
            hass,
            manager,
            recipes=recipes,
            titles=[t for t in msg.get("titles") or [] if t],
            occasion=occasion,
            day=day,
            alcohol=msg.get("alcohol"),
            guests=msg.get("guests"),
            children=msg.get("children"),
            hours=msg.get("hours"),
            ai=msg["ai"],
            kind=msg.get("kind"),
        )
    except HomeAssistantError as err:
        _occasion_error(connection, msg, err)
        return
    connection.send_result(msg["id"], result)


@callback
def async_setup_websocket(hass: HomeAssistant) -> None:
    """Register websocket commands."""
    websocket_api.async_register_command(hass, ws_get_data)
    websocket_api.async_register_command(hass, ws_occasion_products)
    websocket_api.async_register_command(hass, ws_subscribe)
    websocket_api.async_register_command(hass, ws_get_prices)
    websocket_api.async_register_command(hass, ws_store_prices)
    websocket_api.async_register_command(hass, ws_branches)
    websocket_api.async_register_command(hass, ws_reorder_branches)
    websocket_api.async_register_command(hass, ws_forget_store_preference)
    websocket_api.async_register_command(hass, ws_article_search)
    websocket_api.async_register_command(hass, ws_compare_prices)
    websocket_api.async_register_command(hass, ws_find_branches)
    websocket_api.async_register_command(hass, ws_rewe_markets)
    websocket_api.async_register_command(hass, ws_edeka_markets)
    websocket_api.async_register_command(hass, ws_aldi_stores)
    websocket_api.async_register_command(hass, ws_store_offers)
    websocket_api.async_register_command(hass, ws_leaflets)
    websocket_api.async_register_command(hass, ws_season)
    websocket_api.async_register_command(hass, ws_receipts)
    websocket_api.async_register_command(hass, ws_receipt_parse)
    websocket_api.async_register_command(hass, ws_receipt_save)
    websocket_api.async_register_command(hass, ws_receipt_delete)
    websocket_api.async_register_command(hass, ws_get_settings)
    websocket_api.async_register_command(hass, ws_save_settings)
    websocket_api.async_register_command(hass, ws_ai_status)
    websocket_api.async_register_command(hass, ws_ai_test)
    websocket_api.async_register_command(hass, ws_products)
    websocket_api.async_register_command(hass, ws_product_detail)
    websocket_api.async_register_command(hass, ws_product_save)
    websocket_api.async_register_command(hass, ws_product_delete)
    websocket_api.async_register_command(hass, ws_product_classify)
    websocket_api.async_register_command(hass, ws_ai_sort)
    websocket_api.async_register_command(hass, ws_product_favorite)
    websocket_api.async_register_command(hass, ws_product_alternatives)
    websocket_api.async_register_command(hass, ws_product_to_recipe)
    websocket_api.async_register_command(hass, ws_shopping_set_product)
    websocket_api.async_register_command(hass, ws_occasion_save)
    websocket_api.async_register_command(hass, ws_occasion_delete)
    websocket_api.async_register_command(hass, ws_occasion_suggest)
    websocket_api.async_register_command(hass, ws_drinks_suggest)
