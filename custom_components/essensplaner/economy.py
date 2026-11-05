"""Prices, offers, budget and cost aware planning (mixin for the manager)."""

from __future__ import annotations

from datetime import date, timedelta
import json
import logging
from pathlib import Path
import statistics
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from .const import (
    CONF_BUDGET,
    CONF_OFFERS_SOURCE,
    CONF_STORES,
    CONF_STRATEGY,
    CONF_WATCHLIST,
    CONF_ZIP,
    OFFERS_OFF,
    STRATEGIES,
    STRATEGY_BALANCED,
    STRATEGY_CHEAP,
    STRATEGY_OFFERS,
    STRATEGY_VARIETY,
)
from .ingredients import (
    aggregate,
    category_rank,
    fold,
    format_ingredient,
    guess_category,
    ingredient_key,
    is_pantry_item,
    scale_ingredient,
)
from .offers import manual_offer, offer_matches, store_allowed
from .pricing import (
    LayeredPriceBook,
    PriceBook,
    PriceEntry,
    format_eur,
    ingredient_cost,
    offer_as_entry,
    offer_valid_on,
    package_cost,
    unit_price,
)
from .retailers import DEFAULT_STORES, RETAILERS, STORES, retailer_for_store_id, retailer_name

if TYPE_CHECKING:
    from .manager import EssensplanerManager

_LOGGER = logging.getLogger(__name__)

# tags/ingredient groups used to avoid the same kind of dish on consecutive days
VARIETY_TAGS = {
    "pasta",
    "reis",
    "suppe",
    "eintopf",
    "auflauf",
    "curry",
    "salat",
    "haehnchen",
    "rind",
    "schwein",
    "hackfleisch",
    "fisch",
    "pute",
    "pfanne",
    "ofen",
    "asiatisch",
    "italienisch",
    "mexikanisch",
}

# relevant aisles when searching offers (spices etc. are cheap anyway)
_OFFER_CATEGORIES = {
    "Fleisch & Fisch",
    "Milchprodukte & Eier",
    "Käse & Aufschnitt",
    "Obst & Gemüse",
    "Nudeln, Reis & Getreide",
    "Konserven & Gläser",
    "Tiefkühl",
    "Brot & Backwaren",
    "Backen & Süßes",
    "Nüsse & Trockenobst",
}

# strategy -> (offer factor, over-budget penalty, cheapness exponent, variety penalty)
_STRATEGY_WEIGHTS = {
    STRATEGY_BALANCED: (1.2, 2.0, 0.4, 0.35),
    STRATEGY_CHEAP: (1.5, 4.0, 1.2, 0.6),
    STRATEGY_OFFERS: (3.5, 2.0, 0.4, 0.6),
    STRATEGY_VARIETY: (0.6, 1.0, 0.2, 0.12),
}


def load_default_prices() -> list[dict[str, Any]]:
    """Read the bundled price estimates (executor)."""
    path = Path(__file__).parent / "default_prices.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        _LOGGER.warning("Could not load default prices: %s", err)
        return []


class EconomyMixin:
    """Mixed into EssensplanerManager."""

    # set by the manager
    prices_user: dict[str, dict[str, Any]]
    prices_learned: dict[str, dict[str, Any]]
    offers: list[dict[str, Any]]
    offers_meta: dict[str, Any]
    default_prices: list[dict[str, Any]]
    _price_book: PriceBook | None
    _offer_index: dict[str, list[dict[str, Any]]] | None
    _cost_cache: dict[tuple, dict[str, Any]]
    _offer_name_cache: dict[tuple[str, str | None], list[dict[str, Any]]]
    _offer_day_cache: dict[date, Any]
    _recipes_using_cache: dict[tuple[str, ...], list[str]]

    # ------------------------------------------------------------------
    # Options
    # ------------------------------------------------------------------

    @property
    def weekly_budget(self: EssensplanerManager) -> float | None:
        """Weekly food budget in EUR (None = no budget)."""
        try:
            value = float(self.options.get(CONF_BUDGET) or 0)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    @property
    def offers_source(self: EssensplanerManager) -> str:
        """Where offers come from (off / marktguru)."""
        return self.options.get(CONF_OFFERS_SOURCE) or OFFERS_OFF

    @property
    def zip_code(self: EssensplanerManager) -> str:
        """Zip code for offers."""
        return str(self.options.get(CONF_ZIP) or "").strip()

    @property
    def offer_stores(self: EssensplanerManager) -> list[str]:
        """Selected supermarkets."""
        return list(self.options.get(CONF_STORES) or DEFAULT_STORES)

    @property
    def watchlist(self: EssensplanerManager) -> list[str]:
        """Extra search terms for offers."""
        text = self.options.get(CONF_WATCHLIST) or ""
        return [w.strip() for w in str(text).replace(";", ",").split(",") if w.strip()]

    @property
    def strategy(self: EssensplanerManager) -> str:
        """Default planning strategy."""
        value = self.options.get(CONF_STRATEGY) or STRATEGY_BALANCED
        return value if value in STRATEGIES else STRATEGY_BALANCED

    # ------------------------------------------------------------------
    # Price book & offers index
    # ------------------------------------------------------------------

    def _invalidate_prices(self: EssensplanerManager) -> None:
        self._price_book = None
        self._offer_index = None
        self._cost_cache = {}
        self._offer_name_cache = {}
        self._offer_day_cache = {}
        self._store_books = {}

    @property
    def price_book(self: EssensplanerManager) -> PriceBook:
        """Lazily built price lookup."""
        if self._price_book is None:
            self._price_book = PriceBook(self.default_prices, self.prices_user, self.prices_learned)
        return self._price_book

    def _offers_index(self: EssensplanerManager) -> dict[str, list[dict[str, Any]]]:
        """All offers by ingredient key (store filters are applied in offers_for)."""
        if self._offer_index is None:
            index: dict[str, list[dict[str, Any]]] = {}
            for offer in self.offers:
                for key in offer.get("keys") or []:
                    index.setdefault(key, []).append(offer)
            self._offer_index = index
        return self._offer_index

    def _offer_in_scope(
        self: EssensplanerManager,
        offer: dict[str, Any],
        retailer: str | None,
        active: list[str],
    ) -> bool:
        """retailer given: only offers of that retailer; else manual + active retailers."""
        if retailer is not None:
            return self.offer_retailer(offer) == retailer
        return offer.get("source") != "marktguru" or store_allowed(
            offer.get("store_id", ""), active
        )

    def offers_for(
        self: EssensplanerManager,
        name: str,
        day: date | None = None,
        lead_days: int = 3,
        retailer: str | None = None,
    ) -> list[dict[str, Any]]:
        """Offers usable for an ingredient (on a given day, optionally of one retailer)."""
        self._ensure_price_context()
        index = self._offers_index()
        if not index:
            return []
        cache = self._offer_name_cache
        cache_key = (name, retailer)
        if cache_key not in cache:
            # matching offers of every store (shared by all retailers, "*" = unfiltered)
            found = cache.get((name, "*"))
            if found is None:
                key = ingredient_key(name)
                found = list(index.get(key, []))
                if not found:
                    for other_key, offers in index.items():
                        if other_key and (
                            other_key in key.split() or offer_matches(name, other_key)
                        ):
                            found.extend(offers)
                cache[(name, "*")] = found
            active = self.active_retailers()
            cache[cache_key] = [o for o in found if self._offer_in_scope(o, retailer, active)]
        found = list(cache[cache_key])
        if day is not None:
            found = [o for o in found if offer_valid_on(o, day, lead_days)]
        return found

    def regular_book(
        self: EssensplanerManager, retailer: str | None = None
    ) -> PriceBook | LayeredPriceBook:
        """Price book used for regular prices.

        retailer given: that retailer's book; else the main branch's retailer book, or the
        general 1.2 book without a main branch.
        """
        if retailer is None:
            retailer = self.main_retailer
            if retailer is None:
                return self.price_book
        return self.store_book(retailer)

    def best_price(
        self: EssensplanerManager,
        name: str,
        day: date | None = None,
        retailer: str | None = None,
    ) -> tuple[PriceEntry | None, PriceEntry | None]:
        """(cheapest usable entry, regular entry) for an ingredient.

        retailer: compare with that retailer's prices and offers only. Without it the main
        branch's prices (or the general prices) and the offers of all selected stores.
        """
        regular = self.regular_book(retailer).lookup(name)
        best = regular
        best_unit = unit_price(regular) if regular else None
        for offer in self.offers_for(name, day or self.today(), retailer=retailer):
            entry = offer_as_entry(offer)
            if entry is None:
                continue
            per = unit_price(entry)
            if per is None:
                continue
            if (
                best_unit is None
                or (per[1] == best_unit[1] and per[0] < best_unit[0])
                or (best is regular and regular is None)
            ):
                best, best_unit = entry, per
            elif (
                per[1] != best_unit[1]
                and best is regular
                and regular is not None
                and regular.source == "default"
            ):
                # different units (e.g. Stück vs g): trust the offer over a rough estimate
                best, best_unit = entry, per
        return best, regular

    # ------------------------------------------------------------------
    # Costs
    # ------------------------------------------------------------------

    def _offer_day_key(self: EssensplanerManager, day: date) -> Any:
        """Days with the same usable offers share cached costs."""
        if not self.offers:
            return "-"
        cache = self._offer_day_cache
        if day not in cache:
            cache[day] = frozenset(o.get("id") for o in self.offers if offer_valid_on(o, day))
        return cache[day]

    def recipe_cost(
        self: EssensplanerManager,
        recipe: dict[str, Any],
        servings: int | None = None,
        day: date | None = None,
    ) -> dict[str, Any]:
        """Estimated cost of a recipe (proportional to the used amounts)."""
        self._ensure_price_context()
        base = recipe.get("servings") or self.default_servings
        target = servings or base
        day = day or self.today()
        cache_key = (recipe["id"], recipe.get("updated"), target, self._offer_day_key(day))
        if cache_key in self._cost_cache:
            return self._cost_cache[cache_key]
        factor = target / base if base else 1
        total = 0.0
        regular_total = 0.0
        unknown: list[str] = []
        on_offer: list[dict[str, Any]] = []
        items: list[dict[str, Any]] = []
        for raw in recipe.get("ingredients", []):
            ingredient = scale_ingredient(raw, factor)
            name = ingredient.get("name", "")
            if not name or ingredient.get("amount") is None or is_pantry_item(name, self.pantry):
                continue
            best, regular = self.best_price(name, day)
            if best is None:
                unknown.append(name)
                continue
            cost = ingredient_cost(ingredient, best)
            if cost is None and regular is not None and best is not regular:
                best = regular
                cost = ingredient_cost(ingredient, regular)
            if cost is None:
                unknown.append(name)
                continue
            regular_cost = ingredient_cost(ingredient, regular) if regular else None
            total += cost
            regular_total += regular_cost if regular_cost is not None else cost
            item = {
                "name": name,
                "cost": round(cost, 2),
                "source": best.source,
            }
            if best.offer:
                item["offer"] = _offer_short(best.offer)
                on_offer.append({"ingredient": name, **_offer_short(best.offer)})
            items.append(item)
        result = {
            "total": round(total, 2),
            "per_serving": round(total / target, 2) if target else None,
            "servings": target,
            "regular_total": round(regular_total, 2),
            "savings": round(max(0.0, regular_total - total), 2),
            "on_offer": on_offer,
            "unknown": unknown,
            "items": sorted(items, key=lambda i: -i["cost"]),
            "estimate": True,
        }
        self._cost_cache[cache_key] = result
        return result

    def plan_costs(self: EssensplanerManager, start: date, days: int) -> dict[str, Any]:
        """Cost of the planned meals in a date range."""
        out_days = []
        total = 0.0
        savings = 0.0
        for offset in range(max(1, days)):
            day = start + timedelta(days=offset)
            day_total = 0.0
            meals = []
            for view in self.day_meals(day):
                recipe = self.recipes.get(view.get("recipe_id") or "")
                if recipe is None:
                    meals.append({**_meal_short(view), "cost": None})
                    continue
                cost = self.recipe_cost(recipe, view.get("servings"), day)
                day_total += cost["total"]
                savings += cost["savings"]
                meals.append(
                    {
                        **_meal_short(view),
                        "cost": cost["total"],
                        "on_offer": [o["ingredient"] for o in cost["on_offer"]],
                    }
                )
            total += day_total
            out_days.append({"date": day.isoformat(), "total": round(day_total, 2), "meals": meals})
        return {
            "start": start.isoformat(),
            "days": out_days,
            "total": round(total, 2),
            "savings": round(savings, 2),
        }

    def week_overview(self: EssensplanerManager, day: date | None = None) -> dict[str, Any]:
        """Costs of the calendar week (Mon–Sun) containing `day`, incl. budget."""
        day = day or self.today()
        start = day - timedelta(days=day.weekday())
        costs = self.plan_costs(start, 7)
        budget = self.weekly_budget
        costs["end"] = (start + timedelta(days=6)).isoformat()
        costs["budget"] = budget
        costs["remaining"] = round(budget - costs["total"], 2) if budget else None
        costs["over_budget"] = bool(budget and costs["total"] > budget)
        return costs

    # ------------------------------------------------------------------
    # Planning helpers
    # ------------------------------------------------------------------

    def _variety_signature(self: EssensplanerManager, recipe: dict[str, Any]) -> set[str]:
        signature = self.recipe_tags_folded(recipe) & VARIETY_TAGS
        for ingredient in recipe.get("ingredients", []):
            if (ingredient.get("category") or guess_category(ingredient.get("name", ""))) == (
                "Fleisch & Fisch"
            ):
                key = ingredient_key(ingredient.get("name", ""))
                if key:
                    signature.add(f"protein:{key.split()[-1]}")
                break
        return signature

    def _neighbour_signatures(
        self: EssensplanerManager, day: date, extra: dict[str, set[str]] | None = None
    ) -> list[tuple[int, set[str]]]:
        found: list[tuple[int, set[str]]] = []
        for offset in (-2, -1, 1, 2):
            other = (day + timedelta(days=offset)).isoformat()
            for entry in self.plan.get(other, {}).values():
                recipe = self.recipes.get(entry.get("recipe_id") or "")
                if recipe:
                    found.append((abs(offset), self._variety_signature(recipe)))
            if extra and other in extra:
                found.append((abs(offset), extra[other]))
        return found

    def economy_weight(
        self: EssensplanerManager,
        recipe: dict[str, Any],
        day: date,
        strategy: str | None = None,
        target_cost: float | None = None,
        median_cost: float | None = None,
        servings: int | None = None,
        neighbours: list[tuple[int, set[str]]] | None = None,
    ) -> float:
        """Multiplier for suggestion weights: offers, budget and variety."""
        strategy = strategy if strategy in _STRATEGY_WEIGHTS else self.strategy
        offer_factor, budget_penalty, cheap_exp, variety_penalty = _STRATEGY_WEIGHTS[strategy]
        weight = 1.0
        cost = self.recipe_cost(recipe, servings or self.default_servings, day)
        if cost["total"] > 0:
            share = sum(i["cost"] for i in cost["items"] if i.get("offer")) / cost["total"]
            if cost["on_offer"]:
                weight *= 1 + offer_factor * min(1.0, share + 0.15 * len(cost["on_offer"]))
            if target_cost:
                ratio = cost["total"] / target_cost
                if ratio > 1:
                    weight /= 1 + (ratio - 1) * budget_penalty
                else:
                    weight *= 1 + (1 - ratio) * (0.6 if strategy == STRATEGY_CHEAP else 0.25)
            if median_cost and cheap_exp:
                weight *= (median_cost / max(cost["total"], 0.5)) ** cheap_exp
        if neighbours:
            signature = self._variety_signature(recipe)
            for distance, other in neighbours:
                overlap = signature & other
                if overlap:
                    weight *= variety_penalty if distance == 1 else (1 + variety_penalty) / 2
        return max(weight, 0.001)

    def median_cost(
        self: EssensplanerManager, day: date, servings: int | None = None
    ) -> float | None:
        """Median recipe cost (for 'cheap' weighting)."""
        values = [
            self.recipe_cost(r, servings or self.default_servings, day)["total"]
            for r in self.recipes.values()
        ]
        values = [v for v in values if v > 0]
        return statistics.median(values) if values else None

    def budget_target(self: EssensplanerManager, day: date, meals_per_day: int = 1) -> float | None:
        """Target cost for one more meal in the week of `day`, given the budget."""
        budget = self.weekly_budget
        if not budget:
            return None
        week = self.week_overview(day)
        free = 0
        start = date.fromisoformat(week["start"])
        for offset in range(7):
            current = start + timedelta(days=offset)
            if current < self.today():
                continue
            planned = len(self.plan.get(current.isoformat(), {}))
            free += max(0, meals_per_day - planned)
        remaining = budget - week["total"]
        return max(remaining, 0.5) / max(free, 1)

    # ------------------------------------------------------------------
    # Shopping list prices
    # ------------------------------------------------------------------

    def price_shopping_items(
        self: EssensplanerManager, items: list[dict[str, Any]], day: date
    ) -> float:
        """Add price/offer info to aggregated shopping items. Returns the total."""
        total = 0.0
        for item in items:
            best, regular = self.best_price(item["name"], day)
            item["price"] = None
            item["offer"] = None
            for entry in (best, regular):
                if entry is None:
                    continue
                result = package_cost(item["amounts"], item["key"], entry, item.get("category"))
                if result is None:
                    continue
                item["price"], item["packs"] = result
                if entry.offer:
                    item["offer"] = _offer_short(entry.offer)
                break
            if item["price"] is not None:
                total += item["price"]
        return round(total, 2)

    # ------------------------------------------------------------------
    # Prices & offers management
    # ------------------------------------------------------------------

    def set_price(
        self: EssensplanerManager,
        name: str,
        price: float,
        amount: float = 1,
        unit: str = "Stück",
        store: str | None = None,
    ) -> dict[str, Any]:
        """Store an own price for an ingredient.

        Like 1.2 the price is stored as own price with the store as label (used while no
        main branch is set). If the store is a known retailer it is also stored as that
        retailer's store price; for other retailers a price labelled with another store
        is ignored.
        """
        key = ingredient_key(name)
        retailer = self.resolve_store(store) if store else None
        entry: dict[str, Any] = {
            "name": name.strip(),
            "price": round(float(price), 2),
            "amount": float(amount or 1),
            "unit": unit or "Stück",
            "store": store or None,
            "updated": dt_util.utcnow().isoformat(),
        }
        if retailer:
            self._put_store_price(retailer, name, price, amount, unit)
            entry["retailer"] = retailer
        self.prices_user[key] = entry
        self._invalidate_prices()
        self._changed("prices")
        return entry

    def remove_price(self: EssensplanerManager, name: str, store: str | None = None) -> bool:
        """Remove an own price (falls back to the estimate).

        With a known store: remove that store's price (and the own price labelled with it).
        """
        key = ingredient_key(name)
        retailer = self.resolve_store(store) if store else None
        if retailer:
            removed = self._pop_store_price(retailer, key)
        else:
            removed = self.prices_user.pop(key, None) is not None
        if removed:
            self._invalidate_prices()
            self._changed("prices")
        return removed

    def add_offer(
        self: EssensplanerManager,
        product: str,
        store: str,
        price: float,
        pack_text: str | None = None,
        valid_from: date | None = None,
        valid_to: date | None = None,
        old_price: float | None = None,
    ) -> dict[str, Any]:
        """Add an offer by hand (or by voice)."""
        offer = manual_offer(product, store, price, pack_text, valid_from, valid_to, old_price)
        # ids come from the clock: keep them unique (offers added in the same millisecond)
        known = {o.get("id") for o in self.offers}
        while offer["id"] in known:
            offer["id"] = f"man_{int(offer['id'][4:]) + 1}"
        offer["retailer"] = retailer_for_store_id(offer["store_id"]) or self.resolve_store(store)
        # also match recipe ingredients (e.g. offer "Hähnchenbrustfilet" -> "Hähnchenbrust")
        keys = set(offer["keys"])
        for recipe in self.recipes.values():
            for ingredient in recipe.get("ingredients", []):
                ikey = ingredient_key(ingredient.get("name", ""))
                if ikey and offer_matches(product, ikey):
                    keys.add(ikey)
        offer["keys"] = sorted(keys)
        self.tag_offer_branches([offer])
        self.offers.append(offer)
        self._invalidate_prices()
        self._changed("offers")
        return offer

    def remove_offer(self: EssensplanerManager, offer_id: str) -> bool:
        """Delete an offer."""
        before = len(self.offers)
        self.offers = [o for o in self.offers if o.get("id") != offer_id]
        if len(self.offers) != before:
            self._invalidate_prices()
            self._changed("offers")
            return True
        return False

    def replace_source_offers(
        self: EssensplanerManager, source: str, offers: list[dict[str, Any]], meta: dict[str, Any]
    ) -> None:
        """Replace all offers of one source (e.g. after a marktguru refresh).

        Tags the offers with the branches they apply to and learns regular prices from
        old prices: like 1.2 as general learned prices, and per retailer (with history).
        """
        today = self.today().isoformat()
        kept = [
            o
            for o in self.offers
            if o.get("source") != source and (o.get("valid_to") or "9999") >= today
        ]
        for offer in offers:
            if "retailer" not in offer:
                offer["retailer"] = self.offer_retailer(offer)
        self.offers = kept + offers
        self.tag_offer_branches()
        # learn regular prices from offers with an old price (1.2: general learned prices)
        for offer in offers:
            if offer.get("old_price") and offer.get("pack_amount") and offer.get("keys"):
                for key in offer["keys"]:
                    self.prices_learned[key] = {
                        "name": offer.get("product") or key,
                        "price": offer["old_price"],
                        "amount": offer["pack_amount"],
                        "unit": offer["pack_unit"],
                        "store": offer.get("store"),
                        "updated": dt_util.utcnow().isoformat(),
                    }
        meta["learned"] = self.learn_from_offers(offers)
        self.offers_meta = meta
        self._invalidate_prices()
        self._changed("offers")

    def cleanup_offers(self: EssensplanerManager) -> None:
        """Drop expired offers."""
        today = self.today().isoformat()
        before = len(self.offers)
        self.offers = [o for o in self.offers if (o.get("valid_to") or "9999") >= today]
        if len(self.offers) != before:
            self._invalidate_prices()

    def offer_search_terms(self: EssensplanerManager, limit: int = 40) -> list[tuple[str, str]]:
        """Ingredients worth looking up: watchlist, planned, favourites, frequent."""
        scores: dict[str, float] = {}
        names: dict[str, str] = {}

        def add(name: str, score: float) -> None:
            key = ingredient_key(name)
            if not key or is_pantry_item(name, self.pantry):
                return
            if guess_category(name) not in _OFFER_CATEGORIES:
                return
            scores[key] = scores.get(key, 0) + score
            names.setdefault(key, name)

        today = self.today()
        for offset in range(14):
            for entry in self.plan.get((today + timedelta(days=offset)).isoformat(), {}).values():
                recipe = self.recipes.get(entry.get("recipe_id") or "")
                for ingredient in (recipe or {}).get("ingredients", []):
                    add(ingredient.get("name", ""), 5)
        for recipe in self.recipes.values():
            bonus = 2 if recipe.get("favorite") else 0
            for ingredient in recipe.get("ingredients", []):
                add(ingredient.get("name", ""), 1 + bonus)
        terms = [(w, ingredient_key(w)) for w in self.watchlist if ingredient_key(w)]
        seen = {k for _, k in terms}
        for key in sorted(scores, key=lambda k: -scores[k]):
            if key in seen:
                continue
            terms.append((names[key], key))
            seen.add(key)
            if len(terms) >= limit:
                break
        return terms[:limit]

    def offers_view(
        self: EssensplanerManager,
        when: str = "all",
        query: str | None = None,
        store: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Offers for display: when = current | upcoming | all."""
        today = self.today()
        active = self.active_retailers()
        result = []
        for offer in self.offers:
            if not self._offer_in_scope(offer, None, active):
                continue
            start = (offer.get("valid_from") or "")[:10]
            end = (offer.get("valid_to") or "9999-12-31")[:10]
            if end < today.isoformat():
                continue
            is_current = not start or start <= today.isoformat()
            if when == "current" and not is_current:
                continue
            if when == "upcoming" and is_current:
                continue
            if (
                query
                and not offer_matches(
                    f"{offer.get('title')} {offer.get('description')}", ingredient_key(query)
                )
                and fold(query) not in fold(offer.get("title", ""))
            ):
                continue
            if store and fold(store) not in fold(offer.get("store", "")):
                continue
            discount = None
            if offer.get("old_price") and offer["old_price"] > offer["price"]:
                discount = round((1 - offer["price"] / offer["old_price"]) * 100)
            recipes = self._recipes_using(offer.get("keys") or [])
            result.append(
                {
                    **offer,
                    "current": is_current,
                    "discount": discount,
                    "recipes": recipes[:5],
                    "recipe_count": len(recipes),
                }
            )
        result.sort(
            key=lambda o: (
                not o["current"],
                -(o["recipe_count"] > 0),
                -(o["discount"] or 0),
                o.get("valid_to") or "",
            )
        )
        return result[:limit]

    def _recipes_using(self: EssensplanerManager, keys: list[str]) -> list[str]:
        """Names of the recipes using one of these ingredient keys (cached until recipes change)."""
        if not keys:
            return []
        cache_key = tuple(keys)
        cached = self._recipes_using_cache.get(cache_key)
        if cached is not None:
            return list(cached)
        names = []
        for recipe in self.recipes.values():
            for ingredient in recipe.get("ingredients", []):
                ikey = ingredient_key(ingredient.get("name", ""))
                if ikey and any(
                    ikey == k or offer_matches(ingredient.get("name", ""), k) for k in keys
                ):
                    names.append(recipe["name"])
                    break
        result = sorted(names, key=fold)
        self._recipes_using_cache[cache_key] = result
        return list(result)

    def prices_view(self: EssensplanerManager) -> list[dict[str, Any]]:
        """All known prices (own, learned, estimates)."""
        result = []
        for entry in self.price_book.entries():
            per = unit_price(entry)
            result.append(
                {
                    **entry.as_dict(),
                    "key": ingredient_key(entry.name),
                    "unit_price": round(per[0], 5) if per else None,
                    "base_unit": per[1] if per else None,
                }
            )
        return result

    def economy_export(self: EssensplanerManager) -> dict[str, Any]:
        """Data for the panel."""
        return {
            "budget": self.weekly_budget,
            "week": self.week_overview(),
            "next_week": self.week_overview(self.today() + timedelta(days=7)),
            "offers_source": self.offers_source,
            "offers_meta": self.offers_meta,
            "zip_code": self.zip_code,
            "stores": [{"id": s, "name": STORES.get(s, s)} for s in self.offer_stores],
            "strategy": self.strategy,
            "user_prices": self.prices_user,
            "retailers": [{"id": r, "name": retailer_name(r)} for r in RETAILERS],
            "active_retailers": self.active_retailers(),
            "main_branch": self.main_branch,
            "main_retailer": self.main_retailer,
            "price_sources": self.price_sources_view(),
        }

    def price_sources_view(self: EssensplanerManager) -> dict[str, Any]:
        """Status of the online price sources besides the offers (REWE online shop)."""
        from .rewe import rewe_status  # rewe.py imports the mixins

        return {"rewe": rewe_status(self)}

    def shopping_from_items(
        self: EssensplanerManager, entries: list[tuple[dict[str, Any], str]]
    ) -> list[dict[str, Any]]:
        """Aggregate + price (helper used by generate_shopping_list)."""
        return aggregate(entries, self.pantry)


def _offer_short(offer: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": offer.get("id"),
        "title": offer.get("title"),
        "store": offer.get("store"),
        "price": offer.get("price"),
        "old_price": offer.get("old_price"),
        "valid_to": offer.get("valid_to"),
        "valid_from": offer.get("valid_from"),
        "text": f"{offer.get('store')} {format_eur(offer.get('price'))}",
    }


def _meal_short(view: dict[str, Any]) -> dict[str, Any]:
    return {
        "meal": view["meal"],
        "meal_label": view["meal_label"],
        "title": view["title"],
        "recipe_id": view.get("recipe_id"),
    }


__all__ = ["EconomyMixin", "category_rank", "format_ingredient", "load_default_prices"]
