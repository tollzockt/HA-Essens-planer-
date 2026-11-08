"""Price estimates for ingredients, recipes and shopping lists.

Pure Python (no Home Assistant imports). Prices are always in EUR.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
import math
import re
from typing import Any

from .ingredients import _singular, fold, guess_category, ingredient_key, to_base
from .retailers import retailer_for_store_id

# spoon sizes
_SPOON_LIQUID = {"EL": 15.0, "TL": 5.0}
_SPOON_SOLID = {"EL": 10.0, "TL": 3.0}
_SPOON_SPICE = {"EL": 6.0, "TL": 2.0}

# rough sizes of small units (base unit, amount)
_SMALL_UNITS: dict[str, tuple[str, float]] = {
    "Prise": ("g", 0.5),
    "Msp.": ("g", 0.3),
    "Spritzer": ("ml", 5.0),
    "Tasse": ("ml", 200.0),
    "Becher": ("g", 200.0),
    "Scheibe": ("g", 25.0),
    "Handvoll": ("g", 30.0),
    "Zweig": ("g", 2.0),
    "Blatt": ("g", 2.0),
    "Glas": ("g", 350.0),
    "Dose": ("g", 400.0),
    "Zehe": ("g", 5.0),
}
_PACKAGE_UNITS = {
    "Dose",
    "Glas",
    "Becher",
    "Pck.",
    "Flasche",
    "Tüte",
    "Schale",
    "Netz",
    "Tafel",
    "Rolle",  # "1 Rolle Blätterteig (275 g)"; toilet paper is priced per Rolle
}
COUNT_UNITS = {"", "Stück", "Stange", "Kopf", "Knolle"}

# average weight of one piece (g), keyed by the last word of the ingredient key
_PIECE_WEIGHTS = {
    "zwiebel": 80,
    "gemuesezwiebel": 250,
    "schalotte": 30,
    "karotte": 80,
    "moehre": 80,
    "kartoffel": 100,
    "suesskartoffel": 300,
    "tomate": 100,
    "apfel": 150,
    "banane": 120,
    "zitrone": 100,
    "limette": 60,
    "brokkoli": 400,
    "champignon": 20,
    "kuerbi": 1200,
    "kuerbis": 1200,
    "ingwer": 30,
    "knoblauch": 50,
    "knoblauchzehe": 5,
    "paprika": 160,
    "zucchini": 250,
    "aubergine": 300,
    "gurke": 400,
    "salatgurke": 400,
    "avocado": 200,
    "mango": 350,
    "ei": 60,
    "spargel": 25,
    "radieschen": 15,
    "kohlrabi": 300,
    "lauch": 250,
    "cocktailkirsche": 5,
    "aepfel": 150,
    "roulade": 150,
    "rinderroulade": 150,
    "schnitzel": 150,
    "schweineschnitzel": 150,
    "steak": 200,
    "haehnchenbrust": 150,
    "haehnchenbrustfilet": 150,
    "haehnchenschenkel": 250,
    "haehnchenkeule": 250,
    "bratwurst": 100,
    "bratwuerste": 100,
    "wuerstchen": 50,
    "wiener": 50,
    "lachsfilet": 125,
    "seelachsfilet": 125,
    "fischstaebchen": 30,
    "matjesfilet": 50,
    "lorbeerblatt": 0.2,
    "lorbeerblaetter": 0.2,
    "nelke": 0.1,
    "gewuerznelke": 0.1,
    "wacholderbeere": 0.2,
    "pimentkoerner": 0.1,
    "gewuerzgurke": 40,
    "olive": 4,
    "cornichon": 8,
    "chilischote": 10,
    "peperoni": 10,
    "kirschtomate": 15,
    "datteltomate": 15,
    "fruehlingszwiebel": 20,
    "orange": 200,
    "birne": 170,
    "pfirsich": 150,
    "kiwi": 80,
}

_NOTE_AMOUNT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l)\b", re.IGNORECASE)
_NOTE_COUNT_RE = re.compile(r"(\d+)\s*(?:Stück|Stk\.?|St\.)", re.IGNORECASE)
_BUND_WEIGHTS = {"fruehlingszwiebel": 120.0, "lauchzwiebel": 120.0, "radieschen": 200.0}
_PCK_WEIGHTS = {"vanillezucker": 8.0, "trockenhefe": 7.0, "backpulver": 15.0, "gelatine": 9.0}
_PER_PIECE_RE = re.compile(r"(?:^|\s)(?:à|a|je|pro|jeweils|ca\.? à)\s", re.IGNORECASE)

# fallback weight of one piece (g) by aisle when nothing better is known
_CATEGORY_PIECE = {
    "Fleisch & Fisch": 150.0,
    "Obst & Gemüse": 120.0,
    "Käse & Aufschnitt": 25.0,
    "Brot & Backwaren": 60.0,
    "Milchprodukte & Eier": 60.0,
    "Gewürze, Öle & Saucen": 0.5,
}


def _full_key(name: str) -> str:
    return " ".join(_singular(w) for w in fold(name).split())


def _last_word(key: str) -> str:
    return key.split()[-1] if key else key


@dataclass
class PriceEntry:
    """A price for a package of a product."""

    name: str
    amount: float
    unit: str
    price: float
    # default | user | offer_regular | offer | leaflet | rewe_online
    source: str = "default"
    store: str | None = None
    spice: bool = False
    offer: dict[str, Any] | None = None
    aliases: list[str] = field(default_factory=list)
    store_id: str | None = None  # retailer id ("aldi-sued") of store specific prices
    updated: str | None = None

    @property
    def real(self) -> bool:
        """True for a real price (own, learned, offer) – False for a rough estimate."""
        return self.source != "default"

    def as_dict(self) -> dict[str, Any]:
        """Serialize."""
        data = {
            "name": self.name,
            "amount": self.amount,
            "unit": self.unit,
            "price": round(self.price, 2),
            "source": self.source,
        }
        if self.store:
            data["store"] = self.store
        if self.store_id:
            data["store_id"] = self.store_id
        if self.updated:
            data["updated"] = self.updated
        return data


def to_pricing_base(
    amount: float | None, unit: str, note: str = "", key: str = ""
) -> tuple[float | None, str]:
    """Convert an ingredient amount into g / ml / Stück (or keep a special unit)."""
    if amount is None:
        return None, unit
    if unit in _PACKAGE_UNITS and (count := _NOTE_COUNT_RE.search(note or "")):
        return amount * float(count.group(1)), "Stück"  # "1 Pck. Wraps (8 Stück)"
    match = _NOTE_AMOUNT_RE.search(note or "")
    if match and (unit in _PACKAGE_UNITS or unit in COUNT_UNITS):
        value = float(match.group(1).replace(",", "."))
        sub_amount, sub_unit = to_base(value, match.group(2).lower())
        if unit in _PACKAGE_UNITS or _PER_PIECE_RE.search(note or ""):
            return amount * (sub_amount or 0), sub_unit  # "1 Dose (400 g)", "4 Rouladen (à 150 g)"
        return sub_amount or 0, sub_unit  # "2 Hähnchenbrustfilets (400 g)" = total
    if unit in COUNT_UNITS:
        return amount, "Stück"
    base_amount, base_unit = to_base(amount, unit)
    if base_unit == "":
        return base_amount, "Stück"
    return base_amount, base_unit


def convert(
    amount: float,
    unit: str,
    target: str,
    key: str = "",
    spice: bool = False,
    category: str | None = None,
) -> float | None:
    """Convert an amount in a pricing base unit into the target unit."""
    if unit == target:
        return amount
    if unit in ("g", "ml") and target in ("g", "ml"):
        return amount  # 1 g ≈ 1 ml is good enough for estimates
    if unit in ("EL", "TL"):
        if target == "ml":
            return amount * _SPOON_LIQUID[unit]
        table = _SPOON_SPICE if spice or category == "Gewürze, Öle & Saucen" else _SPOON_SOLID
        if target == "g":
            return amount * table[unit]
        return convert(amount * table[unit], "g", target, key, spice, category)
    if unit in _SMALL_UNITS:
        base, size = _SMALL_UNITS[unit]
        return convert(amount * size, base, target, key, spice, category)
    last = _last_word(key)
    if unit == "Bund":
        return convert(amount * _BUND_WEIGHTS.get(last, 30.0), "g", target, key, spice, category)
    if unit == "Pck.":
        return convert(amount * _PCK_WEIGHTS.get(last, 15.0), "g", target, key, spice, category)
    if target in ("Bund", "Pck.") and unit != target:
        grams = convert(amount, unit, "g", key, spice, category)
        if grams is None:
            return None
        size = _BUND_WEIGHTS.get(last, 30.0) if target == "Bund" else _PCK_WEIGHTS.get(last, 15.0)
        return grams / size
    weight = _PIECE_WEIGHTS.get(key.replace(" ", "")) or _PIECE_WEIGHTS.get(_last_word(key))
    if not weight and (unit == "Stück" or target == "Stück"):
        weight = 0.5 if spice else _CATEGORY_PIECE.get(category or "", 60.0)
    if unit == "Stück" and target in ("g", "ml") and weight:
        return amount * weight
    if unit in ("g", "ml") and target == "Stück" and weight:
        return amount / weight
    return None


def lookup_keys(name: str) -> tuple[str, str]:
    """(full key, short key) used to look up a name in a price index."""
    return _full_key(name), ingredient_key(name)


def _fuzzy_hit(candidate: str, key: str) -> bool:
    """Compound words: 'Rinderhackfleisch' ~ 'hackfleisch', 'Hähnchenbrustfilet' ~ 'haehnchenbrust'."""
    words = candidate.split()
    return any(w == key or w.endswith(key) or w.startswith(key) for w in words) or (
        " " in key and key in candidate
    )


def make_entry(item: dict[str, Any], source: str, store_id: str | None = None) -> PriceEntry | None:
    """PriceEntry from a stored price dict (None if invalid)."""
    try:
        return PriceEntry(
            name=str(item["name"]),
            amount=float(item.get("amount") or 1),
            unit=str(item.get("unit") or "Stück"),
            price=float(item["price"]),
            source=source,
            store=item.get("store"),
            spice=bool(item.get("spice")),
            aliases=list(item.get("aliases") or []),
            store_id=store_id,
            updated=item.get("updated"),
        )
    except (KeyError, TypeError, ValueError):
        return None


class PriceIndex:
    """Price entries indexed by name keys (one layer of a price book)."""

    def __init__(self) -> None:
        """Create an empty index."""
        self._index: dict[str, PriceEntry] = {}
        # keys that are the own (full) name/alias key of an entry ("tomate" of "Tomaten")
        self._full: set[str] = set()
        self._sorted: list[str] | None = None

    def __len__(self) -> int:
        """Number of keys."""
        return len(self._index)

    def __contains__(self, key: object) -> bool:
        """True if the exact key is indexed."""
        return key in self._index

    def add(
        self,
        item: dict[str, Any] | PriceEntry,
        source: str = "default",
        keys: list[str] | tuple[str, ...] = (),
        weak_keys: list[str] | tuple[str, ...] = (),
        store_id: str | None = None,
    ) -> PriceEntry | None:
        """Add an entry under its name/alias keys (later entries win).

        The short key of a name with an adjective ("gehackte Tomaten" -> "tomate") never
        replaces a product that is really called that ("Tomaten"), so canned tomatoes do
        not take over the price of fresh ones.
        keys: extra keys that also win; weak_keys: extra name keys (e.g. the aliases of the
        matching estimate) only used if still free.
        """
        entry = item if isinstance(item, PriceEntry) else make_entry(item, source, store_id)
        if entry is None:
            return None
        for name in [entry.name, *entry.aliases]:
            full, short = _full_key(name), ingredient_key(name)
            if full:
                self._index[full] = entry
                self._full.add(full)
            if short and short != full and short not in self._full:
                self._index[short] = entry
        for key in keys:
            if key:
                self._index[key] = entry
                self._full.add(key)
        for key in weak_keys:
            if key and key not in self._index:
                self._index[key] = entry
                self._full.add(key)
        self._sorted = None
        return entry

    def get(self, key: str) -> PriceEntry | None:
        """Entry stored under an exact key."""
        return self._index.get(key)

    def is_full_key(self, key: str) -> bool:
        """True if the key is an entry's own name/alias key (or a forced key), not a short key."""
        return key in self._full

    def keys_by_length(self) -> list[str]:
        """All keys, longest first (insertion order for equal lengths)."""
        if self._sorted is None:
            self._sorted = sorted(self._index, key=len, reverse=True)
        return self._sorted

    def exact(self, name: str) -> PriceEntry | None:
        """Entry for the full or short key of a name."""
        for key in lookup_keys(name):
            if key in self._index:
                return self._index[key]
        return None

    def fuzzy(self, name: str) -> PriceEntry | None:
        """Entry whose key is part of a compound word of the name (longest key first)."""
        for candidate in lookup_keys(name):
            for key in self.keys_by_length():
                if len(key) >= 4 and _fuzzy_hit(candidate, key):
                    return self._index[key]
        return None

    def lookup(self, name: str) -> PriceEntry | None:
        """Exact match, else fuzzy match."""
        return self.exact(name) or self.fuzzy(name)

    def entries(self) -> list[PriceEntry]:
        """All distinct entries."""
        seen: dict[int, PriceEntry] = {}
        for entry in self._index.values():
            seen[id(entry)] = entry
        return sorted(seen.values(), key=lambda e: fold(e.name))


class LayeredPriceBook:
    """Look up prices in several indexes, the first layer has the highest priority.

    Exact keys are tried across all layers first (full key, then short key, each in
    layer order); a key that is only the short key of a name with an adjective
    ("gewürfelte Tomaten" -> "tomate") counts after all layers' own name keys, so it never
    replaces a product that is really called that ("Tomaten" in a lower layer), like in the
    1.2 price book. Then compound-word matching: the most specific (longest) key across
    all layers wins, equal lengths go to the higher priority layer – the same rule as
    the single 1.2 index, so a short own price ("Milch") never captures "Kokosmilch".
    """

    def __init__(self, layers: list[PriceIndex]) -> None:
        """Build the book."""
        self.layers = [layer for layer in layers if layer is not None]
        self._cache: dict[str, PriceEntry | None] = {}
        self._fuzzy_keys: list[tuple[str, PriceIndex]] | None = None

    def lookup(self, name: str) -> PriceEntry | None:
        """Best matching price entry for an ingredient name (cached)."""
        if name in self._cache:
            return self._cache[name]
        result = self._lookup(name)
        self._cache[name] = result
        return result

    def _merged_keys(self) -> list[tuple[str, PriceIndex]]:
        if self._fuzzy_keys is None:
            merged = [
                (len(key), position, order, key, layer)
                for position, layer in enumerate(self.layers)
                for order, key in enumerate(layer.keys_by_length())
                if len(key) >= 4
            ]
            merged.sort(key=lambda m: (-m[0], m[1], m[2]))
            self._fuzzy_keys = [(m[3], m[4]) for m in merged]
        return self._fuzzy_keys

    def _lookup(self, name: str) -> PriceEntry | None:
        keys = lookup_keys(name)
        for key in keys:
            for layer in self.layers:
                if layer.is_full_key(key) and (entry := layer.get(key)) is not None:
                    return entry
        for key in keys:
            for layer in self.layers:
                if (entry := layer.get(key)) is not None:
                    return entry
        for candidate in keys:
            for key, layer in self._merged_keys():
                if _fuzzy_hit(candidate, key):
                    return layer.get(key)
        return None

    def entries(self) -> list[PriceEntry]:
        """Distinct entries of all layers (higher priority first for equal names)."""
        seen: dict[int, PriceEntry] = {}
        for layer in self.layers:
            for entry in layer._index.values():
                seen.setdefault(id(entry), entry)
        return list(seen.values())


class PriceBook:
    """Look up prices by ingredient name (user prices > learned > defaults).

    The 1.2 price book: one index where later sources overwrite earlier ones.
    """

    def __init__(
        self,
        defaults: list[dict[str, Any]],
        user: dict[str, dict[str, Any]] | None = None,
        learned: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """Build the index."""
        self.index = PriceIndex()
        self._cache: dict[str, PriceEntry | None] = {}
        for item in defaults:
            self.index.add(item, "default")
        for item in (learned or {}).values():
            self.index.add(item, "offer_regular")
        for item in (user or {}).values():
            self.index.add(item, "user")

    def lookup(self, name: str) -> PriceEntry | None:
        """Best matching price entry for an ingredient name (cached)."""
        if name in self._cache:
            return self._cache[name]
        result = self.index.lookup(name)
        self._cache[name] = result
        return result

    def entries(self) -> list[PriceEntry]:
        """All distinct entries."""
        return self.index.entries()


# plausible package sizes when deriving them from price / unit price
_DERIVED_PACK_LIMITS = {"g": (10.0, 50000.0), "ml": (10.0, 50000.0), "Stück": (1.0, 100.0)}


def plausible_pack(amount: Any, unit: str | None) -> bool:
    """Package size within the sanity limits (0.01–50 kg/l, 1–100 Stück)."""
    limits = _DERIVED_PACK_LIMITS.get(str(unit or ""))
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return False
    return limits is not None and limits[0] * 0.95 <= value <= limits[1]


def _derived_pack(price: Any, per_unit: float, base: str) -> float | None:
    """Package size = price / unit price, if plausible (0.01–50 kg/l, 1–100 Stück)."""
    try:
        amount = float(price) / per_unit
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    limits = _DERIVED_PACK_LIMITS.get(base)
    if limits is None or not limits[0] * 0.95 <= amount <= limits[1]:
        return None
    return float(max(1, round(amount))) if base == "Stück" else float(round(amount))


def offer_as_entry(offer: dict[str, Any]) -> PriceEntry | None:
    """Turn a normalized offer into a price entry."""
    store_id = offer.get("retailer") or retailer_for_store_id(offer.get("store_id"))
    name = offer.get("product") or offer.get("title") or ""
    try:
        if offer.get("pack_amount") and offer.get("pack_unit"):
            return PriceEntry(
                name=name,
                amount=float(offer["pack_amount"]),
                unit=str(offer["pack_unit"]),
                price=float(offer["price"]),
                source="offer",
                store=offer.get("store"),
                offer=offer,
                store_id=store_id,
            )
        if offer.get("unit_price") and offer.get("base_unit"):
            base = offer["base_unit"]
            per_unit = float(offer["unit_price"])
            derived = (
                _derived_pack(offer["price"], per_unit, base)
                if offer.get("price") is not None
                else None
            )
            if derived:
                return PriceEntry(
                    name=name,
                    amount=derived,
                    unit=base,
                    price=float(offer["price"]),
                    source="offer",
                    store=offer.get("store"),
                    offer=offer,
                    store_id=store_id,
                )
            amount = 1000.0 if base in ("g", "ml") else 1.0
            return PriceEntry(
                name=name,
                amount=amount,
                unit=base,
                price=per_unit * amount,
                source="offer",
                store=offer.get("store"),
                offer=offer,
                store_id=store_id,
            )
    except (TypeError, ValueError):
        return None
    return None


def offer_pack(offer: dict[str, Any]) -> tuple[float, str] | None:
    """Package size of an offer: stated pack, else derived from price / unit price."""
    try:
        if offer.get("pack_amount") and offer.get("pack_unit"):
            return float(offer["pack_amount"]), str(offer["pack_unit"])
        if offer.get("unit_price") and offer.get("base_unit") and offer.get("price") is not None:
            base = str(offer["base_unit"])
            derived = _derived_pack(offer["price"], float(offer["unit_price"]), base)
            if derived:
                return derived, base
    except (TypeError, ValueError):
        return None
    return None


def cheaper_by(a: float, b: float) -> tuple[float, float]:
    """How much cheaper a is than b: (absolute EUR, percent of b). Negative = more expensive."""
    absolute = round(b - a, 2)
    percent = round((b - a) / b * 100, 1) if b > 0 else 0.0
    return absolute, percent


def unit_price(entry: PriceEntry) -> tuple[float, str] | None:
    """Price per pricing base unit (g / ml / Stück / special)."""
    amount, unit = to_pricing_base(entry.amount, entry.unit)
    if not amount:
        return None
    return entry.price / amount, unit


def ingredient_cost(ingredient: dict[str, Any], entry: PriceEntry) -> float | None:
    """Proportional cost of an ingredient (what is actually used)."""
    key = ingredient_key(ingredient.get("name", ""))
    need, need_unit = to_pricing_base(
        ingredient.get("amount"), ingredient.get("unit") or "", ingredient.get("note", ""), key
    )
    if need is None:
        return None
    per = unit_price(entry)
    if per is None:
        return None
    price_per_unit, pack_unit = per
    category = ingredient.get("category") or guess_category(ingredient.get("name", ""))
    if need_unit in _PACKAGE_UNITS and need_unit != pack_unit and pack_unit in ("g", "ml"):
        # "1 Dose Mais" without size: one can as sold
        pack_amount, _ = to_pricing_base(entry.amount, entry.unit)
        return need * (pack_amount or 0) * price_per_unit
    converted = convert(need, need_unit, pack_unit, key, entry.spice, category)
    if converted is None:
        return None
    return converted * price_per_unit


def package_need(
    amounts: dict[str, float],
    key: str,
    pack_amount: float,
    pack_unit: str,
    spice: bool = False,
    category: str | None = None,
) -> float:
    """How much of a pack's unit the amounts need (amounts: base unit -> amount from
    aggregate(); a can / jar / cup counts as one pack, an unknown conversion as one)."""
    total = 0.0
    for unit, amount in amounts.items():
        pricing_unit = "Stück" if unit in COUNT_UNITS else unit
        if (
            pricing_unit in _PACKAGE_UNITS
            and pricing_unit != pack_unit
            and pack_unit in ("g", "ml")
        ):
            total += amount * pack_amount  # one can/jar/cup = one pack
            continue
        converted = convert(amount, pricing_unit, pack_unit, key, spice, category)
        if converted is None:
            # unknown conversion (e.g. "4 Cocktailkirschen" vs. 200-g-Glas): assume one pack
            converted = pack_amount
        total += converted
    return total


def package_cost(
    amounts: dict[str, float], key: str, entry: PriceEntry, category: str | None = None
) -> tuple[float, int] | None:
    """Cost when buying whole packages. amounts: base unit -> amount (from aggregate())."""
    pack_amount, pack_unit = to_pricing_base(entry.amount, entry.unit)
    if not pack_amount:
        return None
    total = package_need(amounts, key, pack_amount, pack_unit, entry.spice, category)
    if total <= 0:
        return None
    packs = max(1, math.ceil(total / pack_amount - 1e-6))
    return round(packs * entry.price, 2), packs


def piece_weight_known(key: str) -> bool:
    """True if the weight of one piece of this product is known ('zwiebel', 'ei')."""
    return bool(_PIECE_WEIGHTS.get(key.replace(" ", "")) or _PIECE_WEIGHTS.get(_last_word(key)))


def item_cost(
    amounts: dict[str, float] | None,
    key: str,
    entry: PriceEntry,
    category: str | None = None,
    count_as_packs: bool = False,
) -> tuple[float, int] | None:
    """Cost of a shopping item in whole packs: (price, packs).

    amounts as in aggregate() (base unit -> amount). Without amounts: None, or one pack
    with count_as_packs (manually added items like 'Butter'). With count_as_packs a plain
    count of a product sold by weight/volume ('2 Butter', '2 Milch') means packs.
    """
    if not amounts:
        if not count_as_packs or entry.price is None:
            return None
        return round(entry.price, 2), 1
    if count_as_packs and set(amounts) <= COUNT_UNITS:
        _, pack_unit = to_pricing_base(entry.amount, entry.unit)
        if pack_unit != "Stück" and not piece_weight_known(key):
            packs = max(1, math.ceil(sum(amounts.values()) - 1e-6))
            return round(packs * entry.price, 2), packs
    return package_cost(amounts, key, entry, category)


def pack_text(amount: float | None, unit: str | None) -> str:
    """'250 g', '1 l', '10 Stück', '8 Rollen', '20 WL' (empty without a size)."""
    if not amount or not unit:
        return ""
    if unit in ("g", "ml") and amount >= 1000 and amount % 100 == 0:
        value, unit = amount / 1000, "kg" if unit == "g" else "l"
    else:
        value = amount
    number = f"{value:g}".replace(".", ",")
    if unit == "Rolle" and value != 1:
        unit = "Rollen"
    return f"{number} {unit}"


def format_eur(value: float | None) -> str:
    """1.5 -> '1,50 €'."""
    if value is None:
        return "–"
    return f"{value:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def offer_valid_on(offer: dict[str, Any], day: date, lead_days: int = 3) -> bool:
    """True if the offer can be used for a meal on `day` (bought up to lead_days before)."""
    try:
        start = date.fromisoformat(str(offer.get("valid_from") or "")[:10])
    except ValueError:
        start = date.min
    try:
        end = date.fromisoformat(str(offer.get("valid_to") or "")[:10])
    except ValueError:
        end = date.max
    return start <= day and end >= day - timedelta(days=lead_days)
