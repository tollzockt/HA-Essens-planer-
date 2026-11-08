"""All current offers of the saved stores (offer catalog, 1.4).

The catalog holds every current (and announced) offer of the selected branches, per source:
- EDEKA: the leaflet of the linked market (edeka.py, option edeka_offers). The EDEKA refresh
  stores its whole list here (put_source); a catalog refresh only asks it to refresh when
  its own rules say so (daily / new leaflet week / other markets).
- ALDI SÜD: the weekly offers ("Wochenangebote", aldi.py, option aldi_online_prices; 1–2
  requests per refresh).
- marktguru.de, only with the option offers_source = marktguru (an unofficial interface;
  marktguru's terms forbid automated reading – the user enables it at his own risk):
  - discovery: which chain variants have single offers at a postcode
    (PUBLISHERS_PATH?as=mobile&limit=50&offerLimit=1&zipCode=.., cached DISCOVERY_DAYS);
  - catalog of one variant (RETAILER_OFFERS_PATH?as=web&zipCode=..&limit=PAGE_LIMIT
    &offset=..): current offers first, then up to ~15 expired "filler" offers; paging stops
    at the first expired offer or a short page (totalResults is not trusted), at most
    MAX_PAGES pages;
  - leaflet images of chains without single offers (NORMA, EDEKA without the direct
    source): LEAFLETS_PATH?as=mobile&zipCode=..&limit=LEAFLET_LIMIT per industry.
- REWE: there is no public list of all offers of a market (1.4 probe), so REWE offers come
  from marktguru only.

Refresh (async_refresh_catalog): daily check at 06:xx; it fetches when the last success is
REFRESH_DAYS old, on Saturday/Sunday when the last success was before that Saturday, on
Monday when it was before Monday (a new leaflet week), or when the stores changed. A manual
refresh runs at most once per MANUAL_MIN_HOURS (unless the stores changed). REQUEST_DELAY s
between two requests, at most MAX_REQUESTS per run (about 10–15 for six stores); a refusal
(HTTP 401/403 after reading the keys again, 429, a web page) pauses marktguru for
BLOCK_DAYS days. After each run the catalog is matched locally with the ingredients of the
plan, the favourites, the watchlist, the shopping list and the price list; matching offers
go to manager.offers (planning, budget, shopping list stores), and regular prices printed in
the leaflets (old price, "Normalpreis", ALDI's was-price) are learned for the price list.

Stored in its own file (Store "essensplaner.catalog.<entry_id>"), removed with the entry.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta
import hashlib
import json
import logging
import re
from typing import TYPE_CHECKING, Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import HTTP_USER_AGENT, OFFERS_MARKTGURU, STORAGE_KEY
from .ingredients import (
    CATEGORY_DRUGSTORE,
    CATEGORY_HOUSEHOLD,
    _singular,
    fold,
    guess_category,
    ingredient_key,
)
from .netio import BodyTooLarge, async_read_body
from .offers import (
    _CONFIG_RE,
    LEAFLET_LINK,
    LEAFLET_PAGE_URL,
    MARKTGURU_API,
    MARKTGURU_HOME,
    _date,
    enumeration,
    flavour_only,
    key_only_as_modifier,
    normalize_marktguru_short,
    offer_matches,
    other_compound,
    product_head,
    short_key,
)
from .online_prices import (
    SourceBlocked,
    SourceError,
    SourceUnexpected,
    async_get_json,
    dict_of,
    parse_time,
    refresh_terms,
    time_text,
)
from .retailers import (
    ALDI_SUED,
    KIND_DRUGSTORE,
    retailer_for_store_id,
    retailer_kind,
    retailer_name,
)

if TYPE_CHECKING:
    from .manager import EssensplanerManager

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
CLIENT_VERSION = 1

PUBLISHERS_PATH = "/offers/publishers"
RETAILER_OFFERS_PATH = "/publishers/retailer/{name}/offers"
LEAFLETS_PATH = "/industries/{industry}/leaflets"

SOURCE_MARKTGURU = "marktguru"
SOURCE_EDEKA = "edeka"
SOURCE_ALDI = "aldi_weekly"
SOURCES = (SOURCE_EDEKA, SOURCE_ALDI, SOURCE_MARKTGURU)

# seconds between two requests of a refresh (tests set 0)
REQUEST_DELAY = 1.5
REQUEST_TIMEOUT = 20
MAX_BYTES = 4 * 1024 * 1024
HOME_MAX_BYTES = 2 * 1024 * 1024
PAGE_LIMIT = 500
MAX_PAGES = 4
LEAFLET_LIMIT = 30
DISCOVERY_LIMIT = 50
DISCOVERY_DAYS = 7
REFRESH_DAYS = 3
MANUAL_MIN_HOURS = 1
BLOCK_DAYS = 7
# safety net: never more requests per run (six stores need about 10–15)
MAX_REQUESTS = 30
MAX_ERRORS = 5
# keys of the plan, favourites, watchlist and frequent ingredients + open shopping items
MAX_MATCH_TERMS = 200
MAX_SHOPPING_TERMS = 40
LEAFLET_PREVIEW_PAGES = 4
# matching yields to the event loop every this many offers
MATCH_CHUNK = 200
MAX_VIEW_LIMIT = 100

# offer kinds (local heuristic)
KIND_FOOD = "food"
KIND_DRINKS = "drinks"
KIND_DRUG = "drugstore"
KIND_HOUSEHOLD = "household"
KIND_NONFOOD = "nonfood"
KIND_UNKNOWN = "unknown"
OFFER_KINDS = (KIND_FOOD, KIND_DRINKS, KIND_DRUG, KIND_HOUSEHOLD, KIND_NONFOOD, KIND_UNKNOWN)
# filters of the store_offers websocket
FILTER_KINDS = ("food", "drugstore", "household", "nonfood", "all")
WHEN_VALUES = ("current", "upcoming", "all")
SORTS = ("saving", "price", "unit_price", "name", "store")

STATUS_OFF = "off"
STATUS_PENDING = "pending"
STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_BLOCKED = "blocked"

# marktguru industries of the chains (leaflet lists of chains without single offers)
INDUSTRIES: dict[str, str] = {
    "rewe": "supermaerkte",
    "edeka": "supermaerkte",
    "kaufland": "supermaerkte",
    "globus": "supermaerkte",
    "marktkauf": "supermaerkte",
    "aldi-sued": "discounter",
    "aldi-nord": "discounter",
    "lidl": "discounter",
    "penny": "discounter",
    "netto-marken-discount": "discounter",
    "norma": "discounter",
    "rossmann": "drogerie-gesundheit",
    "dm-drogerie-markt": "drogerie-gesundheit",
    "mueller-drogeriemarkt": "drogerie-gesundheit",
    "budnikowsky": "drogerie-gesundheit",
}

MSG_OFF = (
    "Keine Angebotsquelle eingeschaltet (marktguru, EDEKA oder ALDI SÜD in den Einstellungen)."
)
MSG_NO_TARGETS = "Keine gültige Postleitzahl (Einstellungen oder Filialen)"
MSG_NO_BRANCH = (
    "Für die eingeschalteten Quellen fehlt noch die Filiale (EDEKA: Markt verknüpfen, "
    "ALDI SÜD: Filiale speichern)."
)

# fields kept per offer in the catalog file
_OFFER_FIELDS = (
    "id",
    "title",
    "product",
    "brand",
    "description",
    "store",
    "store_id",
    "retailer",
    "price",
    "old_price",
    "regular_price",
    "app_price",
    "loyalty",
    "loyalty_note",
    "online_only",
    "deposit",
    "unit_price",
    "base_unit",
    "unit_price_from",
    "pack_amount",
    "pack_unit",
    "valid_from",
    "valid_to",
    "image",
    "category",
    "highlight",
    "market_id",
    "branch_id",
    "branch_ids",
    "zip_codes",
    "kind",
    "keys",
    "source",
)


# ----------------------------------------------------------------------
# Errors
# ----------------------------------------------------------------------


class MarktguruError(SourceError):
    """A marktguru request failed (translation key + German message)."""


class MarktguruBlocked(MarktguruError, SourceBlocked):
    """marktguru refused automated requests (HTTP 401/403/429, web page instead of data)."""

    status: int | None = None


class MarktguruUnexpected(MarktguruError, SourceUnexpected):
    """The answer did not have the expected structure (interface changed?)."""


class MarktguruUnavailable(MarktguruError):
    """The web site (its keys) cannot be reached: nothing more is asked this run."""


# errors that end the whole marktguru part of a run
_STOP_ERRORS = (SourceBlocked, SourceUnexpected, MarktguruUnavailable)


def _blocked(detail: str) -> MarktguruBlocked:
    err = MarktguruBlocked(
        "marktguru_blocked",
        f"marktguru.de lässt gerade keine automatischen Abfragen zu ({detail}).",
        error=detail,
    )
    if match := re.search(r"HTTP (\d+)", detail):
        err.status = int(match.group(1))
    return err


def _failed(detail: str, unexpected: bool = False) -> MarktguruError:
    cls = MarktguruUnexpected if unexpected else MarktguruError
    return cls(
        "marktguru_failed",
        f"Die Abfrage bei marktguru ist fehlgeschlagen ({detail}).",
        error=detail,
    )


def _unavailable(detail: str) -> MarktguruUnavailable:
    return MarktguruUnavailable(
        "marktguru_failed",
        f"Die Abfrage bei marktguru ist fehlgeschlagen ({detail}).",
        error=detail,
    )


class _BudgetExceeded(Exception):
    """MAX_REQUESTS reached (nothing more is sent this run)."""


# ----------------------------------------------------------------------
# Kind of an offer (food / drinks / drugstore / household / nonfood)
# ----------------------------------------------------------------------

# heads of non-food products: a word of the product name ending with one of these
# ("LED-Lampe", "Funktionsshirt", "Kaffeevollautomat"); container words (Glas, Becher,
# Topf) and words of dishes (Pfanne, Tasche, Figur, Grill) are left out on purpose
_NONFOOD_HEADS = (
    "jacke",
    "shirt",
    "hose",
    "schuh",
    "socke",
    "strumpf",
    "pullover",
    "pulli",
    "mantel",
    "kleid",
    "bluse",
    "weste",
    "muetze",
    "schal",
    "pyjama",
    "schlafanzug",
    "legging",
    "tight",
    "waermer",
    "lampe",
    "leuchte",
    "lichterkette",
    "laterne",
    "akku",
    "batterie",
    "werkzeug",
    "bohrer",
    "schrauber",
    "saege",
    "sauger",
    "blaeser",
    "bettwaesche",
    "bettdecke",
    "kissen",
    "handtuch",
    "teppich",
    "matratze",
    "spielzeug",
    "spielware",
    "spiel",
    "puzzle",
    "puppe",
    "buch",
    "sticker",
    "kerze",
    "vase",
    "deko",
    "dekoration",
    "gesteck",
    "regal",
    "stuhl",
    "koffer",
    "rucksack",
    "kabel",
    "ladegeraet",
    "kopfhoerer",
    "lautsprecher",
    "fernseher",
    "uhr",
    "kontaktgrill",
    "elektrogrill",
    "gasgrill",
    "schlauch",
    "erde",
    "duenger",
    "pflanze",
    "bratpfanne",
    "kochtopf",
    "messer",
    "geschirr",
    "teller",
    "schuessel",
    "brett",
    "form",
    "toaster",
    "kocher",
    "sprudler",
    "karaffe",
    "kartusche",
    "automat",
    "maschine",
    "halter",
    "staender",
    "zubehoer",
    "isolierbecher",
    "karte",
    "planer",
    "marker",
    "auto",
    "hundefutter",
    "katzenfutter",
    "vogelfutter",
    "fischfutter",
    "nassfutter",
    "trockenfutter",
    "streu",
    "katzennahrung",
    "hundenahrung",
)
# a word starting with one of these makes the product non-food (pet food, toys)
_NONFOOD_PREFIXES = ("katze", "hunde", "tierfutter", "alleinfutter", "spielzeug", "deko")
# drugstore products whatever the chain ("Kräuter-Shampoo" is no herb)
_DRUGSTORE_HEADS = (
    "shampoo",
    "duschgel",
    "zahnpasta",
    "zahncreme",
    "deo",
    "deospray",
    "lotion",
    "pflege",
    "spuelung",
    "parfum",
    "parfuem",
    "edp",
    "edt",
    "edc",
    "serum",
    "rasierer",
    "windel",
)
# more drugstore words, only at a drugstore chain ("Creme" at REWE may be a dessert)
_DRUGSTORE_CHAIN_HEADS = ("creme", "maske", "duft", "geschenkset", "gel", "pad", "tab")
# food a drugstore sells that guess_category() does not know ("Krüger Cappuccino",
# "Proteinriegel", "Bio Dinkel Eierwaffeln", "Milka Choco Mini Stars"): without these the
# drugstore chain would make it a drugstore product (hidden from "Lebensmittel")
_DRUGSTORE_FOOD_HEADS = (
    "cappuccino",
    "espresso",
    "kaffee",
    "kakao",
    "riegel",
    "waffel",
    "waffeln",
    "keks",
    "kekse",
    "cookie",
    "cookies",
    "schokolade",
    "praline",
    "pralinen",
    "chips",
    "gummies",
    "fruchtgummi",
    "kaugummi",
    "bonbon",
    "bonbons",
    "pastille",
    "pastillen",
    "muesli",
    "flohsamen",
    "cracker",
    "zwieback",
)
_DRUGSTORE_FOOD_TOKENS = {"choco", "schoko", "snack", "snacks", "mints"}
_DRUGSTORE_DRINK_HEADS = ("drink",)  # "Haferdrink Natur"
# drinks guess_category() does not know
_DRINK_TOKENS = {
    "rum",
    "gin",
    "wodka",
    "vodka",
    "whisky",
    "whiskey",
    "likoer",
    "sekt",
    "prosecco",
    "champagner",
    "bier",
    "wein",
    "tee",
}
_CATEGORY_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("drogerie", "kosmetik", "koerperpflege", "hygiene", "baby", "gesundheit"), KIND_DRUG),
    (("haushalt", "reinigung", "wasch", "putz"), KIND_HOUSEHOLD),
    (
        (
            "tier",
            "non food",
            "nonfood",
            "aktionsartikel",
            "technik",
            "textil",
            "bekleidung",
            "garten",
            "spielwaren",
            "spielzeug",
            "elektro",
            "deko",
            "freizeit",
        ),
        KIND_NONFOOD,
    ),
    (("getraenk", "wein", "bier", "spirituose", "cola", "saft"), KIND_DRINKS),
    (
        (
            "molkerei",
            "kaese",
            "fleisch",
            "wurst",
            "obst",
            "gemuese",
            "brot",
            "back",
            "knabber",
            "nasch",
            "suess",
            "tiefkuehl",
            "konserve",
            "frische",
            "milch",
            "fisch",
            "fertiggericht",
        ),
        KIND_FOOD,
    ),
)
# the start of a description that only names a variant / an ingredient
_KIND_CUT_RE = re.compile(
    r"(?:^|\s)(?:mit|ohne|weniger|auch|zero|oder|und|in|aus|z\.\s*b\.)(?:\s|$)", re.IGNORECASE
)
_AISLE_KINDS = {
    CATEGORY_DRUGSTORE: KIND_DRUG,
    CATEGORY_HOUSEHOLD: KIND_HOUSEHOLD,
    "Getränke": KIND_DRINKS,
}


def kind_text(description: str | None) -> str:
    """The kind of product named by the start of a description: 'frz. Schnittkäse' of
    'frz. Schnittkäse, je 150-g-Pckg.', 'französischer Hartkäse' of EDEKA's 'französischer
    Hartkäse, 50% Fett i. Tr., je 100 g'; nothing for 'oder Mayonnaise je 400-ml-Fl.',
    'mit Röstzwiebeln …' or 'versch. Sorten …' (a variant or an ingredient)."""
    text = str(description or "")
    if text.startswith("Herkunft:"):
        text = text.split("·", 1)[-1]
    # the first part up to a comma or the end of a sentence (not an abbreviation: "frz.")
    first = re.split(r",|(?<=[a-zäöüß]{5})\.\s", text, maxsplit=1)[0].strip()
    if first.lower().startswith(("versch", "je ", "hinweis")) or re.match(r"\d", first):
        return ""
    cut = _KIND_CUT_RE.search(first)
    return first[: cut.start()].strip() if cut else first


def _category_kind(names: Iterable[str]) -> str | None:
    for name in names:
        folded = fold(str(name or ""))
        if not folded:
            continue
        for hints, kind in _CATEGORY_HINTS:
            if any(h in folded for h in hints):
                return kind
    return None


def _words(text: str) -> list[str]:
    """Folded words of a text, each also in its singular form."""
    words: list[str] = []
    for token in fold(text).split():
        words.append(token)
        singular = _singular(token)
        if singular != token:
            words.append(singular)
    return words


def _has_head(words: list[str], heads: tuple[str, ...]) -> bool:
    return any(w.endswith(heads) for w in words)


def classify_offer(
    product: str,
    description: str = "",
    retailer: str | None = None,
    categories: Iterable[str] | None = None,
) -> str:
    """food | drinks | drugstore | household | nonfood | unknown (local heuristic, no
    request).

    Order: the shopping aisle of the product name (guess_category) for drugstore and
    household products, a category of the source (EDEKA's warengruppe, ALDI's
    categories), non-food words ("LED-Lampe", "Funktionsshirt", pet food), drugstore words
    ("Kräuter-Shampoo"; "Creme" only at a drugstore chain), drinks, the food aisles, the
    kind named by the description ("Classic" + "frz. Schnittkäse") and last the kind of
    chain (Rossmann: drugstore).
    """
    category_kind = _category_kind(categories or ())
    words = _words(product)
    drugstore_chain = retailer_kind(retailer) == KIND_DRUGSTORE
    aisle = guess_category(product) if product.strip() else "Sonstiges"
    if aisle in (CATEGORY_DRUGSTORE, CATEGORY_HOUSEHOLD):
        return _AISLE_KINDS[aisle]
    if category_kind in (KIND_DRUG, KIND_HOUSEHOLD):
        return category_kind
    if _has_head(words, _NONFOOD_HEADS) or any(w.startswith(_NONFOOD_PREFIXES) for w in words):
        return KIND_NONFOOD
    if _has_head(words, _DRUGSTORE_HEADS) or (
        drugstore_chain
        # "Proteinriegel" ends with "gel" but is no gel
        and _has_head([w for w in words if not w.endswith("riegel")], _DRUGSTORE_CHAIN_HEADS)
    ):
        return KIND_DRUG
    if category_kind == KIND_NONFOOD:
        return KIND_NONFOOD
    if aisle == "Getränke" or any(w in _DRINK_TOKENS for w in words):
        return KIND_DRINKS
    if aisle != "Sonstiges":
        return KIND_FOOD
    if category_kind is not None:
        return category_kind
    kind = kind_text(description)
    if kind:
        aisle = guess_category(kind)
        if aisle in _AISLE_KINDS:
            return _AISLE_KINDS[aisle]
        if aisle != "Sonstiges":
            return KIND_FOOD
    if drugstore_chain:
        # food and drinks of a drugstore: the name, else the other products of the offer
        # ("Favourites" + "oder Ritter Sport Schokowürfel")
        for text in (product, description):
            found = _words(text)
            if _has_head(found, _DRUGSTORE_DRINK_HEADS):
                return KIND_DRINKS
            if _has_head(found, _DRUGSTORE_FOOD_HEADS) or any(
                w in _DRUGSTORE_FOOD_TOKENS or w.startswith(("schoko", "choco")) for w in found
            ):
                return KIND_FOOD
        return KIND_DRUG
    return KIND_UNKNOWN


def kind_matches(offer: dict[str, Any], kind: str) -> bool:
    """The panel filter: food = food, drinks or an unknown product of a grocery chain;
    drugstore = drugstore products (and unknown ones of a drugstore); household; nonfood =
    drugstore or household ("Drogerie & Haushalt", 1.4 panel)."""
    value = offer.get("kind") or KIND_UNKNOWN
    if kind == "all":
        return True
    drugstore_chain = retailer_kind(offer.get("retailer")) == KIND_DRUGSTORE
    if kind == "food":
        return value in (KIND_FOOD, KIND_DRINKS) or (value == KIND_UNKNOWN and not drugstore_chain)
    if kind == "drugstore":
        return value == KIND_DRUG or (value == KIND_UNKNOWN and drugstore_chain)
    if kind == "household":
        return value == KIND_HOUSEHOLD
    if kind == "nonfood":
        return kind_matches(offer, "drugstore") or value == KIND_HOUSEHOLD
    return False


# ----------------------------------------------------------------------
# Local matching
# ----------------------------------------------------------------------


class KeyMatcher:
    """Ingredient keys of offer texts with a token index (no test of every offer against
    every key): an offer token is looked up by its prefixes and suffixes (German compounds:
    "Vollmilch" ends with "milch", "Hähnchenbrustfilet" starts with "haehnchenbrust"), then
    offer_matches() decides with its rules; a key only named as the first part of a
    hyphenated compound of another product ("Butter-Spekulatius") does not count."""

    def __init__(self, keys: Iterable[str]) -> None:
        """Index the keys."""
        self.keys = list(dict.fromkeys(k for k in keys if k))
        self._key_set = set(self.keys)
        self._words: dict[str, list[str]] = {}
        self._short: dict[str, list[str]] = {}
        for key in self.keys:
            if short_key(key):
                for word in key.split():
                    self._short.setdefault(word, []).append(key)
                continue
            for word in key.split():
                if len(word) >= 3:
                    self._words.setdefault(word, []).append(key)

    def candidates(self, text: str) -> list[str]:
        """Keys sharing a word part with the text (to be checked with offer_matches())."""
        found: dict[str, None] = {}
        words = self._words
        for token in {_singular(t) for t in fold(text).split()}:
            for key in self._short.get(token, ()):
                found[key] = None
            size = len(token)
            for end in range(3, size + 1):
                for key in words.get(token[:end], ()):
                    found[key] = None
            for start in range(1, size - 2):
                for key in words.get(token[start:], ()):
                    found[key] = None
        return list(found)

    def match(self, text: str, product: str, short_context: str = "") -> list[str]:
        """Keys a text fits ("Butter-Spekulatius" is no butter, "Granatapfel" no Apfel,
        "Skyr Drink Erdbeere" or "Limonaden" of the kind "Zitrone" no Erdbeere / Zitrone).
        The short words of a key ("tk" of "tk erbse") may also be named by short_context
        (the description: "tiefgefroren, je 750-g-Beutel")."""
        if not text.strip():
            return []
        context = text if text == product else f"{product} {text}"
        return [
            key
            for key in self.candidates(text)
            if offer_matches(text, key, short_context)
            and not key_only_as_modifier(product, key)
            and not other_compound(text, key)
            and not flavour_only(context, key)
        ]

    def offer_keys(self, offer: dict[str, Any]) -> list[str]:
        """Keys of an offer: the product itself decides (the name up to a comma or "in" /
        "mit": ALDI's "Apfelmus 360 g, Apfel" is no Apfel); the description only names the
        kind of product ("Classic" + "frz. Schnittkäse"), not what is in it ("mit Gurken"),
        and the short words of keys ("tiefgefroren" for "tk erbse")."""
        name = str(offer.get("product") or offer.get("title") or "")
        description = str(offer.get("description") or "")
        product = product_head(name)
        short_context = f"{name} {description}"
        found = self.match(product, product, short_context)
        if not found:
            kind = kind_text(description)
            if kind:
                found = self.match(kind, product, short_context)
        listed = enumeration(name)
        if listed and listed[0] == product:
            found = self._enumerated_keys(listed[0], listed[1], found, short_context)
        return found

    def _enumerated_keys(
        self, head: str, parts: list[str], found: list[str], short_context: str
    ) -> list[str]:
        """Keys of a name listing alternatives after its comma: a list of products
        ("Tomaten, Gurken oder Paprika": every part is a product of its own) or one noun
        after the alternatives ("Birkel's No. 1, 7-Hühnchen oder 3 Glocken Nudeln"); the
        variants of a product are no products ("Buitoni Pizza, Salami oder Schinken",
        "Knorr Fix, Spaghetti Bolognese oder Lasagne", "Pringles, Original oder Paprika")."""

        def own_product(part: str) -> list[str]:
            keys = self.match(part, part, short_context)
            return keys if ingredient_key(part) in keys else []

        if found and own_product(head):
            listed = [own_product(part) for part in parts]
            if all(listed):
                return list(dict.fromkeys([*found, *(k for keys in listed for k in keys)]))
            return found
        last = parts[-1].split()
        if found or len(last) < 2 or self.match(parts[0], parts[0], short_context):
            return found
        return self.match(last[-1], last[-1], short_context)


def planning_keys(manager: EssensplanerManager) -> list[str]:
    """Keys whose offers count for planning and the shopping list: plan, favourites,
    watchlist, frequent ingredients, open shopping items and the own prices of the price
    list."""
    keys = [k for _, k in refresh_terms(manager, MAX_MATCH_TERMS, MAX_SHOPPING_TERMS)]
    keys += [k for k in manager.prices_user if isinstance(k, str)]
    for bucket in manager.store_prices_user.values():
        if isinstance(bucket, dict):
            keys += [k for k in bucket if isinstance(k, str)]
    return list(dict.fromkeys(k for k in keys if k))


def all_keys(manager: EssensplanerManager, planning: list[str] | None = None) -> list[str]:
    """Every key the catalog is matched with: planning keys, the bundled estimates and the
    learned store prices (the price list rows)."""
    keys = list(planning if planning is not None else planning_keys(manager))
    keys += [ingredient_key(entry.name) for entry in manager.defaults_index().entries()]
    for bucket in manager.store_prices_learned.values():
        if isinstance(bucket, dict):
            keys += [k for k in bucket if isinstance(k, str)]
    return list(dict.fromkeys(k for k in keys if k))


async def async_match_offers(
    manager: EssensplanerManager, offers: list[dict[str, Any]], keys: list[str]
) -> None:
    """Set offer["keys"] (with manager.offer_keys() rules: canned tomatoes get their own key,
    a drugstore product keeps no food key) of every offer; online-only offers get none."""
    matcher = KeyMatcher(keys)
    for position, offer in enumerate(offers):
        if position and position % MATCH_CHUNK == 0:
            await asyncio.sleep(0)  # keep the event loop responsive
        if offer.get("online_only"):
            offer["keys"] = []
            continue
        found = matcher.offer_keys(offer)
        offer["keys"] = manager.offer_keys({**offer, "keys": found}) if found else []


# ----------------------------------------------------------------------
# marktguru answers
# ----------------------------------------------------------------------


def _numeric_id(value: Any) -> int | None:
    """'retailers/128150' / 128150 -> 128150."""
    match = re.search(r"(\d+)$", str(value or ""))
    return int(match.group(1)) if match else None


def parse_publishers(data: Any) -> list[dict[str, Any]]:
    """Chain variants with single offers at a postcode: [{id (numeric), unique_name, name,
    retailer}] (variants of unknown chains are left out)."""
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        raise _failed("unerwartete Antwort", unexpected=True)
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in results:
        if not isinstance(raw, dict):
            continue
        unique = str(raw.get("uniqueName") or "").strip().lower()
        retailer = retailer_for_store_id(unique)
        if not unique or retailer is None or unique in seen:
            continue
        seen.add(unique)
        found.append(
            {
                "id": _numeric_id(raw.get("id")),
                "unique_name": unique,
                "name": str(raw.get("name") or retailer_name(retailer)),
                "retailer": retailer,
            }
        )
    return found


def parse_leaflet(raw: Any) -> dict[str, Any] | None:
    """One leaflet of a leaflet list: {id (flight), leaflet_id, unique_name, retailer, name,
    valid_from, valid_to (local dates), page_count, pages (first page images), url}."""
    if not isinstance(raw, dict):
        return None
    advertiser = dict_of(raw.get("advertiser"))
    unique = str(advertiser.get("uniqueName") or "").strip().lower()
    retailer = retailer_for_store_id(unique)
    leaflet_id = _numeric_id(raw.get("mainLeafletId"))
    if retailer is None or leaflet_id is None:
        return None
    try:
        pages = max(0, int(raw.get("pageCount") or 0))
    except (TypeError, ValueError):
        pages = 0
    return {
        "id": _numeric_id(raw.get("id")),
        "leaflet_id": leaflet_id,
        "unique_name": unique,
        "retailer": retailer,
        "name": str(advertiser.get("name") or retailer_name(retailer)),
        "valid_from": _date(raw.get("validFrom")),
        "valid_to": _date(raw.get("validTo")),
        "valid_until": raw.get("validTo"),
        "page_count": pages,
        "offer_count": raw.get("offerCount"),
        "pages": [
            LEAFLET_PAGE_URL.format(id=leaflet_id, page=i)
            for i in range(min(pages or 1, LEAFLET_PREVIEW_PAGES))
        ],
        "url": LEAFLET_LINK.format(id=leaflet_id),
    }


def _expired(raw: dict[str, Any], now: datetime) -> bool:
    """True if a catalog offer ended before now (validTo is a UTC timestamp)."""
    value = raw.get("validTo")
    if not value:
        return False
    try:
        end = dt_util.parse_datetime(str(value))
    except ValueError:
        end = None
    if end is None:
        day = _date(value)
        return bool(day) and day < dt_util.as_local(now).date().isoformat()
    if end.tzinfo is None:
        end = end.replace(tzinfo=dt_util.UTC)
    return end < now


class CatalogClient:
    """marktguru client of the catalog: honest User-Agent, the public keys of the web
    site's configuration, REQUEST_DELAY s between requests, at most MAX_REQUESTS."""

    def __init__(self, hass: HomeAssistant, delay: float | None = None) -> None:
        """Initialize."""
        self._session = async_get_clientsession(hass)
        self._keys: tuple[str, str] | None = None
        self._delay = REQUEST_DELAY if delay is None else delay
        self.requests = 0

    async def _async_wait(self) -> None:
        if self.requests >= MAX_REQUESTS:
            raise _BudgetExceeded
        if self.requests and self._delay > 0:
            await asyncio.sleep(self._delay)  # be polite to the web site
        self.requests += 1

    async def _async_keys(self, force: bool = False) -> tuple[str, str]:
        if self._keys and not force:
            return self._keys
        await self._async_wait()
        try:
            async with self._session.get(
                MARKTGURU_HOME,
                headers={"User-Agent": HTTP_USER_AGENT, "Accept-Language": "de-DE,de;q=0.9"},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status in (401, 403, 429):
                    raise _blocked(f"HTTP {resp.status}")
                if resp.status >= 400:
                    raise _unavailable(f"marktguru.de antwortet mit HTTP {resp.status}")
                body = await async_read_body(resp, HOME_MAX_BYTES, truncate=True)
        except BodyTooLarge as err:  # pragma: no cover - truncate=True
            raise _unavailable("Antwort zu groß") from err
        except TimeoutError as err:
            raise _unavailable("marktguru.de nicht erreichbar: keine Antwort") from err
        except aiohttp.ClientError as err:
            raise _unavailable(f"marktguru.de nicht erreichbar: {err}") from err
        page = body.decode("utf-8", errors="replace")
        for block in _CONFIG_RE.findall(page):
            try:
                data = json.loads(block)
            except ValueError:
                continue
            config = data.get("config") if isinstance(data, dict) else None
            if isinstance(config, dict) and config.get("apiKey") and config.get("clientKey"):
                self._keys = (str(config["apiKey"]), str(config["clientKey"]))
                return self._keys
        raise _failed("Zugangsdaten auf marktguru.de nicht gefunden – Seite geändert?", True)

    async def async_get(self, path: str, params: dict[str, Any]) -> Any:
        """GET an API answer (keys read again once on HTTP 401/403)."""
        for attempt in range(2):
            api_key, client_key = await self._async_keys(force=attempt > 0)
            await self._async_wait()
            try:
                return await async_get_json(
                    self._session,
                    f"{MARKTGURU_API}{path}",
                    params,
                    _blocked,
                    _failed,
                    timeout=REQUEST_TIMEOUT,
                    max_bytes=MAX_BYTES,
                    headers={
                        "x-apikey": api_key,
                        "x-clientkey": client_key,
                        "User-Agent": HTTP_USER_AGENT,
                        "Accept": "application/json",
                    },
                )
            except MarktguruBlocked as err:
                if attempt == 0 and err.status in (401, 403):
                    continue  # the keys may have changed
                raise
        raise _blocked("HTTP 403")  # pragma: no cover - the loop returns or raises

    async def async_publishers(self, zip_code: str) -> list[dict[str, Any]]:
        """Chain variants with single offers at a postcode (see parse_publishers())."""
        data = await self.async_get(
            PUBLISHERS_PATH,
            {"as": "mobile", "limit": DISCOVERY_LIMIT, "offerLimit": 1, "zipCode": zip_code},
        )
        return parse_publishers(data)

    async def async_retailer_page(
        self, unique_name: str, zip_code: str, offset: int = 0
    ) -> list[dict[str, Any]]:
        """One page of a chain variant's catalog (raw offers)."""
        data = await self.async_get(
            RETAILER_OFFERS_PATH.format(name=unique_name),
            {"as": "web", "zipCode": zip_code, "limit": PAGE_LIMIT, "offset": offset},
        )
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            raise _failed("unerwartete Antwort", unexpected=True)
        return [r for r in results if isinstance(r, dict)]

    async def async_leaflets(self, industry: str, zip_code: str) -> list[dict[str, Any]]:
        """Leaflets of an industry at a postcode (see parse_leaflet())."""
        data = await self.async_get(
            LEAFLETS_PATH.format(industry=industry),
            {"as": "mobile", "zipCode": zip_code, "limit": LEAFLET_LIMIT, "offset": 0},
        )
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            raise _failed("unerwartete Antwort", unexpected=True)
        return [leaflet for r in results if (leaflet := parse_leaflet(r)) is not None]


async def async_variant_offers(
    client: CatalogClient, unique_name: str, zip_code: str, now: datetime
) -> tuple[list[dict[str, Any]], int]:
    """(current raw offers, pages) of one chain variant: pages of PAGE_LIMIT until the first
    expired offer ("filler" offers follow the current ones) or a short page, at most
    MAX_PAGES (totalResults is not trusted)."""
    current: list[dict[str, Any]] = []
    offset = 0
    pages = 0
    for _ in range(MAX_PAGES):
        page = await client.async_retailer_page(unique_name, zip_code, offset)
        pages += 1
        stop = len(page) < PAGE_LIMIT
        for raw in page:
            if _expired(raw, now):
                stop = True
                break
            current.append(raw)
        if stop:
            break
        offset += len(page)
    return current, pages


# ----------------------------------------------------------------------
# The catalog store
# ----------------------------------------------------------------------


def _empty() -> dict[str, Any]:
    return {
        "version": CLIENT_VERSION,
        "status": STATUS_PENDING,
        "last_run": None,
        "last_success": None,
        "signature": None,
        "errors": [],
        "requests": 0,
        "matched": 0,
        "learned": 0,
        "blocked_until": None,
        "publishers": {},
        "buckets": {},
        "leaflets": [],
    }


def _bucket_key(source: str, retailer: str, zip_code: str | None) -> str:
    return f"{source}|{retailer}|{zip_code or '*'}"


def _slim(offer: dict[str, Any]) -> dict[str, Any]:
    """The stored fields of an offer (empty values left out)."""
    return {
        k: offer[k]
        for k in _OFFER_FIELDS
        if k in offer and offer[k] is not None and offer[k] != "" and offer[k] != []
    }


class OfferCatalog:
    """The offer catalog of one config entry (kept in memory, saved after changes)."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize (empty until async_load)."""
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(
            hass, STORE_VERSION, f"{STORAGE_KEY}.catalog.{entry_id}"
        )
        self.data: dict[str, Any] = _empty()
        self.revision = 0
        self._offers_memo: tuple[Any, list[dict[str, Any]]] | None = None
        self._branch_memo: tuple[Any, dict[str, list[str]]] | None = None
        self._overlay_memo: tuple[Any, dict[str, dict[str, dict[str, Any]]]] | None = None
        # the keys the stored offers were last matched with (async_rematch_catalog())
        self.match_signature: str | None = None
        self.unloaded = False

    @staticmethod
    def store_key(entry_id: str) -> str:
        """Storage key of the catalog file of an entry."""
        return f"{STORAGE_KEY}.catalog.{entry_id}"

    async def async_load(self) -> None:
        """Read the catalog file (a missing or unreadable one is an empty catalog)."""
        try:
            data = await self._store.async_load()
        except (OSError, ValueError) as err:  # pragma: no cover - defensive
            _LOGGER.warning("Could not read the offer catalog: %s", err)
            data = None
        base = _empty()
        if isinstance(data, dict):
            for key, value in data.items():
                if key in base and (base[key] is None or isinstance(value, type(base[key]))):
                    base[key] = value
        self.data = base
        self._touch()

    def _touch(self) -> None:
        self.revision += 1
        self._offers_memo = None
        self._branch_memo = None
        self._overlay_memo = None

    async def async_save(self) -> None:
        """Write the catalog file now."""
        if not self.unloaded:
            await self._store.async_save(self.data)

    def save_later(self) -> None:
        """Write the catalog file soon."""
        if not self.unloaded:
            self._store.async_delay_save(lambda: self.data, 10)

    async def async_remove(self) -> None:
        """Delete the catalog file."""
        await self._store.async_remove()

    # -- buckets ------------------------------------------------------------------

    @property
    def buckets(self) -> dict[str, dict[str, Any]]:
        """{source|retailer|zip: {source, retailer, zip_code, status, error, count,
        updated, variants, offers, leaflets}}."""
        return self.data["buckets"]

    def bucket(self, source: str, retailer: str, zip_code: str | None) -> dict[str, Any] | None:
        """One bucket (None if unknown)."""
        return self.buckets.get(_bucket_key(source, retailer, zip_code))

    def set_bucket(
        self,
        source: str,
        retailer: str,
        zip_code: str | None,
        offers: list[dict[str, Any]] | None,
        status: str,
        error: str | None = None,
        now: datetime | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """Replace a bucket's offers (offers None keeps the previous ones: a failed fetch)."""
        key = _bucket_key(source, retailer, zip_code)
        previous = self.buckets.get(key) or {}
        bucket = {
            "source": source,
            "retailer": retailer,
            "zip_code": zip_code,
            "status": status,
            "error": error,
            "updated": (now or dt_util.utcnow()).isoformat()
            if offers is not None
            else previous.get("updated"),
            "offers": [_slim(o) for o in offers]
            if offers is not None
            else list(previous.get("offers") or []),
            **{k: v for k, v in previous.items() if k in ("variants", "leaflets")},
            **extra,
        }
        bucket["count"] = len(bucket["offers"])
        self.buckets[key] = bucket
        self._touch()
        return bucket

    def drop_buckets(self, keep: set[str]) -> None:
        """Remove the buckets of stores that are not selected any more."""
        removed = [k for k in self.buckets if k not in keep]
        for key in removed:
            del self.buckets[key]
        if removed:
            self._touch()

    def prune(self, today: date) -> bool:
        """Drop ended offers and leaflets. Returns True if something was removed."""
        day = today.isoformat()
        changed = False
        for bucket in self.buckets.values():
            offers = bucket.get("offers") or []
            kept = [o for o in offers if (o.get("valid_to") or "9999") >= day]
            if len(kept) != len(offers):
                bucket["offers"] = kept
                bucket["count"] = len(kept)
                changed = True
            leaflets = bucket.get("leaflets") or []
            current = [lf for lf in leaflets if (lf.get("valid_to") or "9999") >= day]
            if len(current) != len(leaflets):
                bucket["leaflets"] = current
                changed = True
        if changed:
            self._touch()
        return changed

    def put_source(
        self,
        manager: EssensplanerManager,
        source: str,
        retailer: str,
        offers: list[dict[str, Any]],
        status: str = STATUS_OK,
        error: str | None = None,
    ) -> None:
        """Store the whole current offer list of a direct source (EDEKA after its refresh);
        keys and kinds are set here. Saved soon."""
        copies = [dict(o) for o in offers]
        for offer in copies:
            offer["source"] = source
            offer["kind"] = classify_offer(
                str(offer.get("product") or offer.get("title") or ""),
                str(offer.get("description") or ""),
                offer.get("retailer") or retailer,
                [offer["category"]] if offer.get("category") else None,
            )
        matcher = KeyMatcher(all_keys(manager))
        for offer in copies:
            found = [] if offer.get("online_only") else matcher.offer_keys(offer)
            offer["keys"] = manager.offer_keys({**offer, "keys": found}) if found else []
        self.set_bucket(source, retailer, None, copies, status, error)
        self.save_later()

    # -- views --------------------------------------------------------------------

    def current_offers(self, today: date) -> list[dict[str, Any]]:
        """All offers that have not ended (one per id: zip codes and branches merged)."""
        memo_key = (self.revision, today)
        if self._offers_memo is not None and self._offers_memo[0] == memo_key:
            return self._offers_memo[1]
        day = today.isoformat()
        merged: dict[str, dict[str, Any]] = {}
        for bucket in self.buckets.values():
            for offer in bucket.get("offers") or []:
                if (offer.get("valid_to") or "9999") < day or not offer.get("id"):
                    continue
                existing = merged.get(offer["id"])
                if existing is None:
                    merged[offer["id"]] = dict(offer)
                    continue
                for field in ("zip_codes", "branch_ids", "keys"):
                    values = list(existing.get(field) or [])
                    for value in offer.get(field) or []:
                        if value not in values:
                            values.append(value)
                    if values:
                        existing[field] = values
        result = list(merged.values())
        self._offers_memo = (memo_key, result)
        return result

    def get_offer(self, offer_id: str, today: date) -> dict[str, Any] | None:
        """A current catalog offer by id."""
        return next((o for o in self.current_offers(today) if o.get("id") == offer_id), None)

    def leaflets(self, today: date) -> list[dict[str, Any]]:
        """Current and announced leaflets of chains without single offers."""
        day = today.isoformat()
        found: list[dict[str, Any]] = []
        for bucket in self.buckets.values():
            for leaflet in bucket.get("leaflets") or []:
                if (leaflet.get("valid_to") or "9999") >= day:
                    found.append({**leaflet, "zip_code": bucket.get("zip_code")})
        return found

    def publishers(self, zip_code: str, now: datetime) -> list[dict[str, Any]] | None:
        """Cached discovery of a postcode (None when missing or DISCOVERY_DAYS old)."""
        entry = dict_of(self.data["publishers"].get(zip_code))
        fetched = parse_time(entry.get("fetched"))
        if fetched is None or now - fetched >= timedelta(days=DISCOVERY_DAYS):
            return None
        items = entry.get("items")
        return list(items) if isinstance(items, list) else None

    def set_publishers(
        self, zip_code: str, items: list[dict[str, Any]] | None, now: datetime
    ) -> None:
        """Cache the discovery of a postcode (None forgets it: asked again next time)."""
        if items is None:
            self.data["publishers"].pop(zip_code, None)
        else:
            self.data["publishers"][zip_code] = {"fetched": now.isoformat(), "items": items}

    def publisher_ids(self, zip_code: str, retailers: Iterable[str]) -> list[int]:
        """Numeric marktguru ids of the chain variants of these retailers at a postcode
        (from the discovery cache, also when it is old; [] if unknown)."""
        wanted = set(retailers)
        entry = dict_of(self.data["publishers"].get(zip_code))
        return [
            int(item["id"])
            for item in entry.get("items") or []
            if isinstance(item, dict) and item.get("retailer") in wanted and item.get("id")
        ]

    def best_offers(self, today: date) -> dict[str, dict[str, dict[str, Any]]]:
        """{key: {retailer: offer info}}: the cheapest current offer per ingredient key and
        retailer (price list overlay; online-only offers left out)."""
        memo_key = (self.revision, today)
        if self._overlay_memo is not None and self._overlay_memo[0] == memo_key:
            return self._overlay_memo[1]
        day = today.isoformat()
        best: dict[str, dict[str, tuple[float, dict[str, Any]]]] = {}
        for offer in self.current_offers(today):
            retailer = offer.get("retailer")
            if (
                not retailer
                or offer.get("online_only")
                or (offer.get("valid_from") or "") > day
                or offer.get("price") is None
            ):
                continue
            value = float(offer.get("unit_price") or offer["price"])
            for key in offer.get("keys") or []:
                current = best.setdefault(key, {}).get(retailer)
                if current is None or value < current[0]:
                    best[key][retailer] = (value, offer)
        result = {
            key: {retailer: offer_info(offer) for retailer, (_, offer) in cells.items()}
            for key, cells in best.items()
        }
        self._overlay_memo = (memo_key, result)
        return result

    def summary(self, manager: EssensplanerManager) -> dict[str, Any]:
        """Status for the panel / services (no offers)."""
        today = manager.today()
        offers = self.current_offers(today)
        by_source: dict[str, int] = {}
        for offer in offers:
            by_source[offer.get("source") or "?"] = by_source.get(offer.get("source") or "?", 0) + 1
        data = self.data
        until = parse_time(data.get("blocked_until"))
        now = dt_util.utcnow()
        return {
            "status": catalog_status(manager),
            "updated": data.get("last_success"),
            "last_run": data.get("last_run"),
            "errors": list(data.get("errors") or [])[:MAX_ERRORS],
            "count": len(offers),
            "sources": by_source,
            "leaflets": len(self.leaflets(today)),
            "matched": data.get("matched") or 0,
            "learned": data.get("learned") or 0,
            "requests": data.get("requests") or 0,
            "blocked_until": until.isoformat() if until and until > now else None,
            "marktguru": manager.offers_source == OFFERS_MARKTGURU,
        }


# offers that live only in manager.offers: typed from a leaflet ("＋ Angebot aus Prospekt
# eintragen", voice) and the reduced articles of the ALDI SÜD / REWE price refresh
OWN_OFFER_SOURCES = ("manual", "aldi_online", "rewe_online")


def own_offers(manager: EssensplanerManager, today: date) -> list[dict[str, Any]]:
    """The offers of OWN_OFFER_SOURCES that have not ended, shaped like catalog offers
    (retailer resolved, kind, branch_ids = the branches they are tagged with); online-only
    ones and those whose id is in the catalog are left out."""
    day = today.isoformat()
    catalog = getattr(manager, "catalog", None)
    listed = catalog.current_offers(today) if catalog is not None else []
    known = {o.get("id") for o in listed}
    # a catalog offer pinned with "📌 Merken" (a manual copy) is listed once
    pinned = {
        (o.get("retailer"), o.get("price"), (o.get("valid_to") or "")[:10], fold(name))
        for o in listed
        for name in (
            str(o.get("title") or ""),
            str(o.get("product") or ""),
            f"{o.get('brand') or ''} {o.get('product') or o.get('title') or ''}",
        )
        if name.strip()
    }
    found: list[dict[str, Any]] = []
    for offer in manager.offers:
        if (
            not isinstance(offer, dict)
            or offer.get("source") not in OWN_OFFER_SOURCES
            or not offer.get("id")
            or offer["id"] in known
            or offer.get("online_only")
            or (offer.get("valid_to") or "9999")[:10] < day
            or offer.get("price") is None
        ):
            continue
        retailer = manager.offer_retailer(offer)
        if not retailer:
            continue
        name = fold(str(offer.get("title") or offer.get("product") or ""))
        if (retailer, offer.get("price"), (offer.get("valid_to") or "")[:10], name) in pinned:
            continue
        product = str(offer.get("product") or offer.get("title") or "")
        found.append(
            {
                **offer,
                "title": offer.get("title") or product,
                "retailer": retailer,
                "kind": offer.get("kind")
                or classify_offer(product, str(offer.get("description") or ""), retailer),
                "branch_ids": list(offer.get("branches") or []),
            }
        )
    return found


def price_overlay(
    manager: EssensplanerManager, today: date
) -> dict[str, dict[str, dict[str, Any]]]:
    """best_offers() of the catalog with the own offers (own_offers()) of the day: the
    cheapest current offer per key and retailer for the price list."""
    catalog: OfferCatalog | None = getattr(manager, "catalog", None)
    overlay = catalog.best_offers(today) if catalog is not None else {}
    day = today.isoformat()
    merged: dict[str, dict[str, dict[str, Any]]] | None = None
    for offer in own_offers(manager, today):
        if (offer.get("valid_from") or "")[:10] > day:
            continue
        for key in offer.get("keys") or []:
            if merged is None:  # the memo of best_offers() stays as it is
                merged = {k: dict(cells) for k, cells in overlay.items()}
            cells = merged.setdefault(key, {})
            current = cells.get(offer["retailer"])
            if current is None or float(offer["price"]) < float(current.get("price") or 1e9):
                cells[offer["retailer"]] = offer_info(offer)
    return merged if merged is not None else overlay


def offer_info(offer: dict[str, Any]) -> dict[str, Any]:
    """The short offer shown in a price list cell (display only, never a regular price)."""
    return {
        "id": offer.get("id"),
        "title": offer.get("title"),
        "price": offer.get("price"),
        "valid_from": offer.get("valid_from"),
        "valid_to": offer.get("valid_to"),
        "loyalty": bool(offer.get("loyalty")),
        "app_price": offer.get("app_price"),
        "pack_amount": offer.get("pack_amount"),
        "pack_unit": offer.get("pack_unit"),
        "source": offer.get("source"),
    }


# ----------------------------------------------------------------------
# What to fetch
# ----------------------------------------------------------------------


def marktguru_enabled(manager: EssensplanerManager) -> bool:
    """True with the option offers_source = marktguru."""
    return manager.offers_source == OFFERS_MARKTGURU


def _edeka_on(manager: EssensplanerManager) -> bool:
    from .edeka import edeka_enabled, edeka_markets

    return edeka_enabled(manager) and bool(edeka_markets(manager))


def _aldi_on(manager: EssensplanerManager) -> bool:
    from .aldi import aldi_branch, aldi_enabled

    return aldi_enabled(manager) and aldi_branch(manager)[0] is not None


def catalog_enabled(manager: EssensplanerManager) -> bool:
    """True if any catalog source is on (marktguru, EDEKA, ALDI SÜD option)."""
    from .aldi import aldi_enabled
    from .edeka import edeka_enabled

    return marktguru_enabled(manager) or aldi_enabled(manager) or edeka_enabled(manager)


def catalog_plan(manager: EssensplanerManager) -> dict[str, Any]:
    """{marktguru: [(zip, [retailers])] (offer_targets(), [] with marktguru off), edeka,
    aldi (direct sources on), signature (what was fetched: refetch when it changes)}."""
    targets = manager.offer_targets() if marktguru_enabled(manager) else []
    edeka = _edeka_on(manager)
    aldi = _aldi_on(manager)
    markets: list[str] = []
    if edeka:
        from .edeka import edeka_markets

        markets = sorted(m for _, m in edeka_markets(manager))
    point: str | None = None
    if aldi:
        from .aldi import aldi_branch

        point = aldi_branch(manager)[1]  # the linked service point, if any
    payload = {
        "mg": [[z, sorted(r)] for z, r in targets],
        "edeka": markets,
        "aldi": point or aldi,
    }
    signature = hashlib.sha1(
        json.dumps(payload, sort_keys=True).encode(), usedforsecurity=False
    ).hexdigest()[:16]
    direct = hashlib.sha1(
        json.dumps([markets, point or aldi]).encode(), usedforsecurity=False
    ).hexdigest()[:16]
    return {
        "marktguru": targets,
        "edeka": edeka,
        "aldi": aldi,
        "signature": signature,
        "direct": direct,
        "aldi_point": point,
        "payload": payload,
    }


def _resolved_plan(manager: EssensplanerManager, plan: dict[str, Any]) -> dict[str, Any]:
    """The plan after a refresh: when the run linked the ALDI SÜD service point itself
    (the nearest one of the branch, AldiSource.async_target()), what it fetched is the plan
    with that point – no store change, no second refresh (and no second round of
    marktguru requests). Any other change (a branch saved while the run was going on)
    keeps the plan the run started with, so it gets its own refresh."""
    after = catalog_plan(manager)
    before_payload, after_payload = plan.get("payload") or {}, after["payload"]
    if (
        plan.get("aldi")
        and plan.get("aldi_point") is None
        and after["aldi_point"] is not None
        and before_payload.get("mg") == after_payload["mg"]
        and before_payload.get("edeka") == after_payload["edeka"]
    ):
        return after
    return plan


def catalog_untried(manager: EssensplanerManager) -> bool:
    """True if the stores of the direct sources changed since the last refresh looked at
    them (an EDEKA market linked, an ALDI SÜD branch added or linked): a branch change then
    refreshes soon. Every refresh stores what it looked at, also a failed one (the daily
    check retries it), so this never repeats a refresh by itself."""
    from .aldi import aldi_enabled
    from .edeka import edeka_enabled

    if not (aldi_enabled(manager) or edeka_enabled(manager)):
        return False
    return catalog_plan(manager)["direct"] != manager.catalog.data.get("tried_direct")


def drop_disabled_sources(manager: EssensplanerManager) -> bool:
    """Forget the offers of sources switched off (catalog buckets and planning offers): an
    offer of marktguru must not stay listed after the user switched it off. Returns True
    if something was removed."""
    from .aldi import SOURCE as ALDI_ONLINE, aldi_enabled
    from .edeka import edeka_enabled

    off: set[str] = set()
    if not marktguru_enabled(manager):
        off.add(SOURCE_MARKTGURU)
    if not aldi_enabled(manager):
        off |= {SOURCE_ALDI, ALDI_ONLINE}
    if not edeka_enabled(manager):
        off.add(SOURCE_EDEKA)
    catalog = manager.catalog
    count = len(catalog.buckets)
    catalog.drop_buckets({k for k in catalog.buckets if k.split("|", 1)[0] not in off})
    offers = [o for o in manager.offers if o.get("source") not in off]
    removed = len(offers) != len(manager.offers) or len(catalog.buckets) != count
    manager.offers = offers
    return removed


def catalog_stale(catalog: OfferCatalog, plan: dict[str, Any], now: datetime) -> bool:
    """True if a scheduled refresh should fetch: REFRESH_DAYS after the last success, a new
    leaflet week (Saturday, Sunday and Monday after a success before that day: REWE and
    Netto publish the new week only on Sunday, ALDI and Rossmann already on Saturday) or
    other stores."""
    data = catalog.data
    last = parse_time(data.get("last_success"))
    if last is None or data.get("signature") != plan["signature"]:
        return True
    today = dt_util.as_local(now).date()
    seen = dt_util.as_local(last).date()
    if (today - seen).days >= REFRESH_DAYS:
        return True
    if today.weekday() in (0, 5, 6):
        return seen < today
    return False


def marktguru_paused(manager: EssensplanerManager) -> datetime | None:
    """End of the pause of marktguru requests (after it refused), None without one. Every
    marktguru request checks it: the catalog, the article search and search_offers."""
    until = parse_time(manager.catalog.data.get("blocked_until"))
    return until if until is not None and until > dt_util.utcnow() else None


def paused_message(until: datetime) -> str:
    """The German note of a marktguru pause."""
    return (
        "marktguru hat automatische Abfragen abgelehnt – pausiert bis "
        f"{dt_util.as_local(until).strftime('%d.%m. %H:%M')}."
    )


def pause_marktguru(manager: EssensplanerManager) -> datetime:
    """marktguru refused a request: no more requests for BLOCK_DAYS. Returns the end."""
    until = dt_util.utcnow() + timedelta(days=BLOCK_DAYS)
    catalog = manager.catalog
    catalog.data["blocked_until"] = until.isoformat()
    catalog._touch()
    catalog.save_later()
    return until


def catalog_status(manager: EssensplanerManager) -> str:
    """off | pending | ok | error | blocked."""
    if not catalog_enabled(manager):
        return STATUS_OFF
    data = manager.catalog.data
    until = parse_time(data.get("blocked_until"))
    if until is not None and until > dt_util.utcnow() and marktguru_enabled(manager):
        return STATUS_BLOCKED
    return str(data.get("status") or STATUS_PENDING)


# ----------------------------------------------------------------------
# Refresh
# ----------------------------------------------------------------------


async def async_refresh_catalog(
    hass: HomeAssistant, manager: EssensplanerManager, force: bool = False
) -> dict[str, Any]:
    """Refresh the offer catalog (see the module doc). Returns the result (offers meta).

    force=False (daily check, start, branch change) only fetches when catalog_stale();
    force=True (refresh_offers, button) at most once per MANUAL_MIN_HOURS unless the stores
    changed. One refresh per entry at a time: a second call waits for the running one.
    """
    task = getattr(manager, "_offers_task", None)
    if task is None or task.done():
        task = manager.entry.async_create_background_task(
            hass, _async_refresh(hass, manager, force), "essensplaner_refresh_offers"
        )
        manager._offers_task = task
    return await asyncio.shield(task)


def _result(manager: EssensplanerManager, **extra: Any) -> dict[str, Any]:
    """The result of a refresh: the offers meta (marktguru) with the catalog status."""
    catalog = manager.catalog
    base = dict(manager.offers_meta) if marktguru_enabled(manager) else {}
    summary = catalog.summary(manager)
    base.update(
        {
            "status": base.get("status") or summary["status"],
            "errors": list(base.get("errors") or summary["errors"]),
            "catalog": summary,
        }
    )
    base.update(extra)
    return base


async def _async_refresh(
    hass: HomeAssistant, manager: EssensplanerManager, force: bool
) -> dict[str, Any]:
    catalog: OfferCatalog = manager.catalog
    now = dt_util.utcnow()
    plan = catalog_plan(manager)
    if not catalog_enabled(manager):
        return _result(manager, status=STATUS_OFF, message=MSG_OFF)
    # the direct sources' stores this refresh looked at (fetched, failed or fresh): a
    # branch change only starts a refresh for others (catalog_untried())
    catalog.data["tried_direct"] = plan["direct"]
    if not plan["marktguru"] and not plan["edeka"] and not plan["aldi"]:
        if not marktguru_enabled(manager):
            return _result(manager, status=STATUS_OFF, message=MSG_NO_BRANCH)
        meta = {
            "source": SOURCE_MARKTGURU,
            "last_update": now.isoformat(),
            "status": STATUS_ERROR,
            "errors": [MSG_NO_TARGETS],
            "count": len([o for o in manager.offers if o.get("source") == SOURCE_MARKTGURU]),
            "targets": [],
        }
        manager.offers_meta = {**manager.offers_meta, **meta}
        manager.async_refresh_listeners()
        return _result(manager, **meta)
    if not force and not catalog_stale(catalog, plan, now):
        # nothing to fetch: what was added since the last match still gets its offers
        await async_rematch_catalog(manager)
        return _result(manager)
    last = parse_time(catalog.data.get("last_success"))
    if (
        force
        and last is not None
        and catalog.data.get("signature") == plan["signature"]
        and now - last < timedelta(hours=MANUAL_MIN_HOURS)
    ):
        until = last + timedelta(hours=MANUAL_MIN_HOURS)
        # no new request yet, but items added since the last fetch get their offers
        if await async_rematch_catalog(manager):
            message = f"Angebote neu abgeglichen – neu abrufen ab {time_text(until, now)}."
        else:
            message = f"Gerade erst aktualisiert – wieder möglich ab {time_text(until, now)}."
        return _result(manager, cooldown_until=until.isoformat(), message=message)
    return await _async_run(hass, manager, catalog, plan, force, now)


async def _async_run(
    hass: HomeAssistant,
    manager: EssensplanerManager,
    catalog: OfferCatalog,
    plan: dict[str, Any],
    force: bool,
    now: datetime,
) -> dict[str, Any]:
    today = manager.today()
    errors: list[str] = []
    succeeded: set[str] = set()
    failed: set[str] = set()
    # sources that failed without a pause: the next check fetches again
    retry: set[str] = set()
    keep: set[str] = set()

    # 1. EDEKA: the market leaflet (its own refresh rules; it stores its list here)
    edeka_matched = not plan["edeka"]
    if plan["edeka"]:
        from .edeka import META_KEY, RETAILER as EDEKA, async_refresh_edeka_offers

        edeka_before = (manager.price_sources_meta.get(META_KEY) or {}).get("last_success")
        status = await async_refresh_edeka_offers(hass, manager, force=force)
        # a fresh leaflet is not fetched: its planning offers are of an earlier match
        edeka_matched = (manager.price_sources_meta.get(META_KEY) or {}).get(
            "last_success"
        ) != edeka_before
        keep.add(_bucket_key(SOURCE_EDEKA, EDEKA, None))
        if status.get("status") in (STATUS_ERROR, STATUS_BLOCKED):
            errors.extend(f"EDEKA: {e}" for e in status.get("errors") or [])
            failed.add(SOURCE_EDEKA)
        elif catalog.bucket(SOURCE_EDEKA, EDEKA, None) is not None:
            succeeded.add(SOURCE_EDEKA)

    # 2. ALDI SÜD: the weekly offers
    if plan["aldi"]:
        from .aldi import async_fetch_aldi_offers

        key = _bucket_key(SOURCE_ALDI, ALDI_SUED, None)
        keep.add(key)
        offers, meta = await async_fetch_aldi_offers(hass, manager)
        if meta.get("status") == STATUS_OK:
            for offer in offers:
                offer["source"] = SOURCE_ALDI
                offer["valid_from"] = offer.get("valid_from") or today.isoformat()
            await _async_prepare(manager, offers)
            catalog.set_bucket(SOURCE_ALDI, ALDI_SUED, None, offers, STATUS_OK, now=now)
            succeeded.add(SOURCE_ALDI)
        else:
            message = "; ".join(meta.get("errors") or []) or str(meta.get("status"))
            errors.append(f"ALDI SÜD: {message}")
            catalog.set_bucket(SOURCE_ALDI, ALDI_SUED, None, None, STATUS_ERROR, message)
            failed.add(SOURCE_ALDI)
            if meta.get("status") != STATUS_BLOCKED:
                retry.add(SOURCE_ALDI)

    # 3. marktguru (option offers_source = marktguru)
    mg_meta: dict[str, Any] | None = None
    if marktguru_enabled(manager) and plan["marktguru"]:
        served = _served_directly(manager, catalog, plan)
        mg_meta = await _async_marktguru(hass, manager, catalog, plan["marktguru"], served, now)
        keep |= mg_meta.pop("_keep")
        errors.extend(mg_meta["errors"])
        if mg_meta["status"] == STATUS_OK:
            succeeded.add(SOURCE_MARKTGURU)
        else:
            failed.add(SOURCE_MARKTGURU)
            if mg_meta["status"] != STATUS_BLOCKED:
                retry.add(SOURCE_MARKTGURU)
    catalog.drop_buckets(keep)
    catalog.prune(today)

    # 4. local matching -> manager.offers, learning from the whole catalog
    offers = catalog.current_offers(today)
    planning = set(planning_keys(manager))
    learned = manager.learn_from_offers(
        [o for o in offers if not o.get("online_only") and o.get("keys")]
    )
    matched_total = 0
    replaced = False
    if SOURCE_ALDI in succeeded:
        matched = _matched(manager, offers, SOURCE_ALDI, planning)
        matched_total += len(matched)
        manager.replace_source_offers(SOURCE_ALDI, matched, None)
        replaced = True
    if mg_meta is not None:
        mg_meta["catalog_count"] = sum(1 for o in offers if o.get("source") == SOURCE_MARKTGURU)
        mg_meta["searched"] = len(planning)
        if mg_meta["status"] == STATUS_OK:
            matched = _matched(manager, offers, SOURCE_MARKTGURU, planning)
            matched_total += len(matched)
            mg_meta["count"] = len(matched)
            manager.replace_source_offers(SOURCE_MARKTGURU, matched, mg_meta)
            replaced = True
            # every regular price learned from the catalog (not only the matched offers)
            mg_meta["learned"] = max(int(mg_meta.get("learned") or 0), learned)
        else:
            # keep the previous offers, only report the problem
            mg_meta["count"] = sum(1 for o in manager.offers if o.get("source") == SOURCE_MARKTGURU)
            manager.offers_meta = {**manager.offers_meta, **mg_meta}
    if SOURCE_EDEKA in succeeded:
        matched_total += sum(1 for o in manager.offers if o.get("source") == SOURCE_EDEKA)

    status = STATUS_OK if succeeded else STATUS_ERROR
    if mg_meta is not None and mg_meta["status"] == STATUS_BLOCKED and not succeeded:
        status = STATUS_BLOCKED
    # the ALDI SÜD service point this run linked itself is what it fetched
    plan = _resolved_plan(manager, plan)
    catalog.data.update(
        {
            "status": status,
            "last_run": now.isoformat(),
            "errors": errors[:MAX_ERRORS],
            "matched": matched_total,
            "requests": (mg_meta or {}).get("requests", 0),
            "tried_direct": plan["direct"],
        }
    )
    if succeeded:
        catalog.data["learned"] = learned
    if succeeded and not retry:
        # a source that failed (not paused) is asked again at the next check
        catalog.data["last_success"] = now.isoformat()
        catalog.data["signature"] = plan["signature"]
    # the keys of this match; offers kept from earlier (a fresh EDEKA leaflet, a failed
    # source) are matched again at the next change or check
    catalog.match_signature = (
        _match_signature(all_keys(manager, sorted(planning)), planning)
        if edeka_matched and not failed
        else None
    )
    catalog._touch()
    await catalog.async_save()
    if not replaced:
        if learned:
            manager._after_price_change("prices")  # learned prices can move open items
        else:
            manager._changed("catalog")
    if mg_meta is not None:
        return _result(manager, **mg_meta)
    return _result(manager, status=status, errors=errors[:MAX_ERRORS], learned=learned)


async def _async_prepare(manager: EssensplanerManager, offers: list[dict[str, Any]]) -> None:
    """Kind and keys of fetched offers (yields to the event loop in between)."""
    for position, offer in enumerate(offers):
        if position and position % MATCH_CHUNK == 0:
            await asyncio.sleep(0)
        offer["kind"] = classify_offer(
            str(offer.get("product") or ""),
            str(offer.get("description") or ""),
            offer.get("retailer"),
            offer.get("categories") or ([offer["category"]] if offer.get("category") else None),
        )
    await async_match_offers(manager, offers, all_keys(manager))


def _matched(
    manager: EssensplanerManager, offers: list[dict[str, Any]], source: str, planning: set[str]
) -> list[dict[str, Any]]:
    """Copies of a source's catalog offers that fit a planning key (for manager.offers)."""
    taken = {o.get("id") for o in manager.offers if o.get("source") != source}
    matched = []
    for offer in offers:
        if (
            offer.get("source") != source
            or offer.get("online_only")
            or offer.get("id") in taken
            or not set(offer.get("keys") or []) & planning
        ):
            continue
        copy = {k: v for k, v in offer.items() if k not in ("kind",)}
        copy["keys"] = list(offer.get("keys") or [])
        matched.append(copy)
    return matched


def _match_signature(keys: list[str], planning: set[str]) -> str:
    """The keys a match used (the catalog keys and the planning keys)."""
    text = json.dumps([sorted(set(keys)), sorted(planning)], ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()


def _source_stored(catalog: OfferCatalog, source: str) -> bool:
    """True if the catalog holds offers of a source (a failed fetch keeps the earlier
    ones, like the planning offers)."""
    return any(b.get("source") == source and b.get("offers") for b in catalog.buckets.values())


async def async_rematch_catalog(manager: EssensplanerManager, force: bool = False) -> bool:
    """Match the stored catalog with the current keys again – no request.

    The planning offers (manager.offers: planning, shopping list, "Für meine Rezepte",
    Jarvis) of marktguru, ALDI SÜD's weekly offers and EDEKA were matched at the last
    fetch; an item put on the shopping list, a planned recipe, a watchlist entry or an own
    / receipt price added after it gets its offers here (debounced after such changes, at
    every check that does not fetch, after a start / reload and at the manual refresh's
    cooldown). The keys of every catalog offer (all_keys()) are set again, the regular
    prices of the catalog learned. Skipped while the keys are the same as at the last
    match (force: always). Returns True if it matched.
    """
    if manager.unloaded or not catalog_enabled(manager):
        return False
    catalog: OfferCatalog = manager.catalog
    planning = set(planning_keys(manager))
    keys = all_keys(manager, sorted(planning))
    signature = _match_signature(keys, planning)
    if not force and signature == catalog.match_signature:
        return False
    for bucket in list(catalog.buckets.values()):
        if bucket.get("offers"):
            await async_match_offers(manager, bucket["offers"], keys)
            if manager.unloaded:
                return False
    catalog._touch()
    catalog.save_later()
    today = manager.today()
    offers = catalog.current_offers(today)
    learned = manager.learn_from_offers(
        [o for o in offers if not o.get("online_only") and o.get("keys")]
    )
    replaced = False
    sources = []
    if _aldi_on(manager):
        sources.append(SOURCE_ALDI)
    if marktguru_enabled(manager):
        sources.append(SOURCE_MARKTGURU)
    for source in sources:
        if not _source_stored(catalog, source):
            continue
        matched = _matched(manager, offers, source, planning)
        manager.replace_source_offers(source, matched, None)
        replaced = True
        if source == SOURCE_MARKTGURU and manager.offers_meta:
            manager.offers_meta = {**manager.offers_meta, "count": len(matched)}
    if _edeka_on(manager):
        from .edeka import RETAILER as EDEKA, match_offers

        bucket = catalog.bucket(SOURCE_EDEKA, EDEKA, None)
        if bucket is not None and bucket.get("status") == STATUS_OK:
            day = today.isoformat()
            current = [
                {k: v for k, v in o.items() if k != "kind"}
                for o in bucket.get("offers") or []
                if (o.get("valid_to") or "9999") >= day
            ]
            # the planning copies hold more fields than the catalog (origin): keep them
            before = {o.get("id"): o for o in manager.offers if o.get("source") == SOURCE_EDEKA}
            matched = [{**before.get(o["id"], {}), **o} for o in match_offers(manager, current)]
            manager.replace_source_offers(SOURCE_EDEKA, matched, None)
            replaced = True
    catalog.match_signature = signature
    if not replaced:
        if learned:
            manager._after_price_change("prices")  # learned prices can move open items
        else:
            manager._changed("catalog")
    return True


def _served_directly(
    manager: EssensplanerManager, catalog: OfferCatalog, plan: dict[str, Any]
) -> set[tuple[str, str | None]]:
    """(retailer, zip | None = every zip) with single offers from the chain's own source:
    marktguru is not asked for them."""
    served: set[tuple[str, str | None]] = set()
    if plan["edeka"]:
        from .edeka import RETAILER as EDEKA, edeka_markets

        bucket = catalog.bucket(SOURCE_EDEKA, EDEKA, None)
        if bucket and bucket.get("status") == STATUS_OK and bucket.get("offers"):
            branch_zip = manager._offer_plan()[1]
            for branch, _ in edeka_markets(manager):
                served.add((EDEKA, branch_zip.get(branch.get("id"))))
    if plan["aldi"]:
        bucket = catalog.bucket(SOURCE_ALDI, ALDI_SUED, None)
        if bucket and bucket.get("status") == STATUS_OK and bucket.get("offers"):
            served.add((ALDI_SUED, None))
    return served


async def _async_marktguru(
    hass: HomeAssistant,
    manager: EssensplanerManager,
    catalog: OfferCatalog,
    targets: list[tuple[str, list[str]]],
    served: set[tuple[str, str | None]],
    now: datetime,
) -> dict[str, Any]:
    """Fetch the marktguru catalogs (and leaflets) of the targets. Returns the offers meta
    (1.3 shape: source, last_update, status, errors, targets, requests) plus _keep."""
    today = manager.today()
    meta: dict[str, Any] = {
        "source": SOURCE_MARKTGURU,
        "last_update": now.isoformat(),
        "status": STATUS_OK,
        "errors": [],
        "targets": [{"zip_code": z, "retailers": list(r)} for z, r in targets],
        "requests": 0,
        "_keep": set(),
    }
    keep: set[str] = meta["_keep"]
    for zip_code, retailers in targets:
        for retailer in retailers:
            if (retailer, zip_code) not in served and (retailer, None) not in served:
                keep.add(_bucket_key(SOURCE_MARKTGURU, retailer, zip_code))
    until = parse_time(catalog.data.get("blocked_until"))
    if until is not None and until > now:
        meta["status"] = STATUS_BLOCKED
        meta["errors"] = [
            "marktguru ist pausiert (keine automatischen Abfragen erlaubt) bis "
            f"{dt_util.as_local(until).strftime('%d.%m. %H:%M')}."
        ]
        return meta
    client = CatalogClient(hass)
    errors: list[str] = meta["errors"]
    succeeded = False
    stop: SourceError | None = None
    try:
        for zip_code, retailers in targets:
            wanted = [
                r for r in retailers if (r, zip_code) not in served and (r, None) not in served
            ]
            if not wanted:
                continue
            publishers = catalog.publishers(zip_code, now)
            if publishers is None:
                try:
                    publishers = await client.async_publishers(zip_code)
                except _STOP_ERRORS:
                    raise
                except SourceError as err:
                    errors.append(f"{zip_code}: {err.message}")
                    if not succeeded:
                        stop = err
                        break
                    continue
                catalog.set_publishers(zip_code, publishers, now)
                succeeded = True
            missing: list[str] = []
            for retailer in wanted:
                variants = [p for p in publishers if p["retailer"] == retailer]
                if not variants:
                    missing.append(retailer)
                    continue
                found = await _async_retailer(
                    client, catalog, manager, retailer, zip_code, variants, now, errors
                )
                succeeded = succeeded or found is not None
                if found == 0:
                    # nothing current: ask the discovery again next time; show leaflets
                    catalog.set_publishers(zip_code, None, now)
                    missing.append(retailer)
            if missing:
                ok = await _async_leaflets(client, catalog, missing, zip_code, now, today, errors)
                succeeded = succeeded or ok
    except _BudgetExceeded:
        errors.append(f"Anfragelimit erreicht ({MAX_REQUESTS} Anfragen) – Rest beim nächsten Mal.")
    except _STOP_ERRORS as err:
        stop = err
        errors.append(err.message)
        if isinstance(err, SourceBlocked):
            until = now + timedelta(days=BLOCK_DAYS)
            catalog.data["blocked_until"] = until.isoformat()
            errors.append(
                "Keine Abfragen bei marktguru bis "
                f"{dt_util.as_local(until).strftime('%d.%m.')} (Bisherige Angebote bleiben)."
            )
    meta["requests"] = client.requests
    if stop is not None and not succeeded:
        if stop.message not in errors:
            errors.insert(0, stop.message)
        meta["status"] = STATUS_BLOCKED if isinstance(stop, SourceBlocked) else STATUS_ERROR
    meta["errors"] = errors[:MAX_ERRORS]
    return meta


async def _async_retailer(
    client: CatalogClient,
    catalog: OfferCatalog,
    manager: EssensplanerManager,
    retailer: str,
    zip_code: str,
    variants: list[dict[str, Any]],
    now: datetime,
    errors: list[str],
) -> int | None:
    """Fetch every variant of a chain at a postcode into its bucket. Returns the number of
    current offers (None if every variant failed: the previous offers are kept)."""
    offers: dict[str, dict[str, Any]] = {}
    counts: list[dict[str, Any]] = []
    failures: list[str] = []
    for variant in variants:
        try:
            raw, pages = await async_variant_offers(client, variant["unique_name"], zip_code, now)
        except _STOP_ERRORS:
            raise
        except SourceError as err:
            failures.append(err.message)
            continue
        count = 0
        for item in raw:
            offer = normalize_marktguru_short(item)
            if offer is None or offer["id"] in offers:
                continue
            offer["retailer"] = offer.get("retailer") or retailer
            offer["zip_codes"] = [zip_code]
            offers[offer["id"]] = offer
            count += 1
        counts.append(
            {
                "unique_name": variant["unique_name"],
                "id": variant.get("id"),
                "count": count,
                "pages": pages,
            }
        )
    label = f"{retailer_name(retailer)} ({zip_code})"
    if not counts:
        message = failures[0] if failures else "keine Antwort"
        errors.append(f"{label}: {message}")
        catalog.set_bucket(SOURCE_MARKTGURU, retailer, zip_code, None, STATUS_ERROR, message)
        return None
    found = list(offers.values())
    await _async_prepare(manager, found)
    catalog.set_bucket(
        SOURCE_MARKTGURU,
        retailer,
        zip_code,
        found,
        STATUS_OK,
        f"{label}: {failures[0]}" if failures else None,
        now,
        variants=counts,
        leaflets=[],
    )
    if failures:
        errors.append(f"{label}: {failures[0]}")
    return len(found)


async def _async_leaflets(
    client: CatalogClient,
    catalog: OfferCatalog,
    retailers: list[str],
    zip_code: str,
    now: datetime,
    today: date,
    errors: list[str],
) -> bool:
    """Leaflet images of chains without single offers (one request per industry)."""
    by_industry: dict[str, list[str]] = {}
    for retailer in retailers:
        industry = INDUSTRIES.get(retailer)
        if industry:
            by_industry.setdefault(industry, []).append(retailer)
    ok = False
    day = today.isoformat()
    for industry, wanted in by_industry.items():
        try:
            leaflets = await client.async_leaflets(industry, zip_code)
        except _STOP_ERRORS:
            raise
        except SourceError as err:
            errors.append(f"{zip_code}: {err.message}")
            continue
        ok = True
        for retailer in wanted:
            mine = [
                lf
                for lf in leaflets
                if lf["retailer"] == retailer and (lf.get("valid_to") or "9999") >= day
            ]
            mine.sort(key=lambda lf: (lf.get("valid_from") or "", lf.get("id") or 0))
            catalog.set_bucket(
                SOURCE_MARKTGURU,
                retailer,
                zip_code,
                [],
                STATUS_OK,
                None,
                now,
                variants=[],
                leaflets=mine,
            )
    return ok


# ----------------------------------------------------------------------
# The store_offers websocket
# ----------------------------------------------------------------------


def _branch_index(
    manager: EssensplanerManager,
) -> tuple[dict[str, list[tuple[str, str | None]]], tuple[Any, ...]]:
    """({retailer: [(branch id, postcode its offers are fetched at)]}, memo key part)."""
    selected = manager.selected_branches()
    branch_zip = manager._offer_plan()[1]
    by_retailer: dict[str, list[tuple[str, str | None]]] = {}
    for branch in selected:
        if branch.get("retailer") and branch.get("id"):
            by_retailer.setdefault(branch["retailer"], []).append(
                (branch["id"], branch_zip.get(branch["id"]))
            )
    signature = tuple((r, tuple(v)) for r, v in sorted(by_retailer.items()))
    return by_retailer, signature


def _branch_ids(
    offer: dict[str, Any], by_retailer: dict[str, list[tuple[str, str | None]]]
) -> list[str]:
    """Branches an offer applies to, like tag_offer_branches(): an offer of a postcode to
    the branches whose offers are fetched there, an EDEKA offer to its linked branches, an
    offer without postcode (ALDI SÜD) to every branch of the chain."""
    candidates = by_retailer.get(offer.get("retailer") or "", [])
    pinned = offer.get("branch_ids") or ([offer["branch_id"]] if offer.get("branch_id") else None)
    zips = offer.get("zip_codes")
    return [
        bid
        for bid, zip_code in candidates
        if (bid in pinned if pinned else not zips or zip_code in zips)
    ]


def offer_branches(manager: EssensplanerManager, offer: dict[str, Any]) -> list[str]:
    """Selected branches a catalog offer applies to."""
    return _branch_ids(offer, _branch_index(manager)[0])


def _branch_map(
    manager: EssensplanerManager, catalog: OfferCatalog, offers: list[dict[str, Any]]
) -> dict[str, list[str]]:
    """{offer id: [branch ids]} of the current offers (cached per catalog revision)."""
    by_retailer, signature = _branch_index(manager)
    memo_key = (catalog.revision, manager.today(), signature)
    if catalog._branch_memo is not None and catalog._branch_memo[0] == memo_key:
        return catalog._branch_memo[1]
    result = {offer["id"]: _branch_ids(offer, by_retailer) for offer in offers}
    catalog._branch_memo = (memo_key, result)
    return result


def _reference(offer: dict[str, Any]) -> float | None:
    """The struck / regular price of an offer (old price, "Normalpreis")."""
    for field in ("old_price", "regular_price"):
        value = offer.get(field)
        if value and value > (offer.get("price") or 0):
            return float(value)
    return None


def _view(offer: dict[str, Any], branch_ids: list[str], today: str) -> dict[str, Any]:
    reference = _reference(offer)
    price = offer.get("price") or 0
    saving = round(reference - price, 2) if reference else None
    return {
        "id": offer.get("id"),
        "title": offer.get("title"),
        "product": offer.get("product"),
        "brand": offer.get("brand") or "",
        "description": offer.get("description") or "",
        "price": offer.get("price"),
        "old_price": offer.get("old_price"),
        "regular_price": offer.get("regular_price"),
        "app_price": offer.get("app_price"),
        "loyalty": bool(offer.get("loyalty")),
        "loyalty_note": offer.get("loyalty_note"),
        "online_only": bool(offer.get("online_only")),
        "deposit": offer.get("deposit"),
        "unit_price": offer.get("unit_price"),
        "base_unit": offer.get("base_unit"),
        "pack_amount": offer.get("pack_amount"),
        "pack_unit": offer.get("pack_unit"),
        "valid_from": offer.get("valid_from"),
        "valid_to": offer.get("valid_to"),
        "current": not offer.get("valid_from") or offer["valid_from"] <= today,
        "image": offer.get("image"),
        "kind": offer.get("kind") or KIND_UNKNOWN,
        "retailer": offer.get("retailer"),
        "store": offer.get("store") or retailer_name(offer.get("retailer")),
        "branch_ids": list(branch_ids),
        "keys": list(offer.get("keys") or []),
        "source": offer.get("source"),
        "saving": saving,
        "discount": round((1 - price / reference) * 100) if reference else None,
        "highlight": offer.get("highlight"),
    }


_SORT_KEYS = {
    "saving": lambda o: (-(o["saving"] or 0), -(o["discount"] or 0), o["price"] or 0),
    "price": lambda o: (o["price"] is None, o["price"] or 0, fold(o["title"] or "")),
    "unit_price": lambda o: (
        o["unit_price"] is None,
        o["base_unit"] or "",
        o["unit_price"] or 0,
        o["price"] or 0,
    ),
    "name": lambda o: (fold(o["title"] or ""), o["price"] or 0),
    "store": lambda o: (fold(o["store"] or ""), fold(o["title"] or "")),
}


def _matches_query(offer: dict[str, Any], query: str) -> bool:
    """The panel's search box: any text of the offer (a brand, "Kaffeevollautomat")."""
    folded = fold(query)
    text = f"{offer.get('title') or ''} {offer.get('description') or ''}"
    if folded and folded in fold(text):
        return True
    key = ingredient_key(query)
    return bool(key) and (key in (offer.get("keys") or []) or offer_matches(text, key))


def _text_query(query: str) -> Callable[[dict[str, Any]], bool]:
    """The panel's search box as a filter (see _matches_query())."""

    def matches(offer: dict[str, Any]) -> bool:
        return _matches_query(offer, query)

    return matches


def _key_query(query: str) -> Callable[[dict[str, Any]], bool]:
    """A product question (voice): an offer of the product itself – its ingredient key, or
    a product name the catalog matcher accepts for it (no Kaffeevollautomat for "Kaffee",
    no Granatapfel for "Apfel", no Butter-Spekulatius for "Butter")."""
    key = ingredient_key(query)
    matcher = KeyMatcher([key] if key else [])

    def matches(offer: dict[str, Any]) -> bool:
        if not key:
            return False
        if key in (offer.get("keys") or []):
            return True
        return bool(
            matcher.offer_keys({**offer, "product": offer.get("product") or offer.get("title")})
        )

    return matches


def _source_status(
    manager: EssensplanerManager,
    catalog: OfferCatalog,
    branch: dict[str, Any],
    zip_code: str | None,
) -> tuple[list[str], str, str | None, list[dict[str, Any]]]:
    """(sources, status, error, leaflets) of a branch: the chain's own source (EDEKA market,
    ALDI SÜD weekly offers, REWE's reduced articles of the online prices) first, marktguru
    for the others; status off when no source covers the chain (e.g. REWE without
    marktguru and online prices)."""
    from .aldi import aldi_enabled
    from .edeka import edeka_enabled, edeka_status
    from .rewe import RETAILER as REWE, SOURCE as REWE_ONLINE, rewe_market, rewe_status

    retailer = branch.get("retailer")
    sources: list[str] = []
    status: str | None = None
    error: str | None = None
    leaflets: list[dict[str, Any]] = []
    direct: dict[str, Any] | None = None
    if retailer == "edeka" and edeka_enabled(manager) and branch.get("edeka_market_id"):
        sources.append(SOURCE_EDEKA)
        direct = catalog.bucket(SOURCE_EDEKA, "edeka", None)
        info = edeka_status(manager)
        status = str(info.get("status") or STATUS_PENDING)
        if status in (STATUS_ERROR, STATUS_BLOCKED):
            error = next(iter(info.get("errors") or []), None) or info.get("message")
    elif retailer == ALDI_SUED and aldi_enabled(manager):
        sources.append(SOURCE_ALDI)
        direct = catalog.bucket(SOURCE_ALDI, ALDI_SUED, None)
        status = str((direct or {}).get("status") or STATUS_PENDING)
        error = (direct or {}).get("error")
    elif retailer == REWE and rewe_market(manager)[1] is not None:
        info = rewe_status(manager)
        if info.get("status") != STATUS_OFF:
            # reduced articles of the weekly REWE online prices (the leaflet: marktguru)
            sources.append(REWE_ONLINE)
            status = str(info.get("status") or STATUS_PENDING)
            if status in (STATUS_ERROR, STATUS_BLOCKED):
                error = next(iter(info.get("errors") or []), None) or info.get("message")
    covered = bool(direct and direct.get("status") == STATUS_OK and direct.get("offers"))
    if marktguru_enabled(manager) and zip_code and retailer and not covered:
        sources.append(SOURCE_MARKTGURU)
        bucket = catalog.bucket(SOURCE_MARKTGURU, retailer, zip_code)
        if bucket is None:
            status = status or (
                STATUS_BLOCKED if catalog_status(manager) == STATUS_BLOCKED else STATUS_PENDING
            )
        else:
            leaflets = [dict(lf) for lf in bucket.get("leaflets") or []]
            if status is None or bucket.get("offers") or leaflets:
                status = str(bucket.get("status") or STATUS_PENDING)
                error = bucket.get("error")
    return sources, status or STATUS_OFF, error, leaflets


def store_offers_view(
    manager: EssensplanerManager,
    branch_ids: list[str] | None = None,
    when: str = "current",
    kind: str = "all",
    query: str | None = None,
    mine: bool = False,
    sort: str = "saving",
    offset: int = 0,
    limit: int = 60,
    include_online: bool = False,
    match: str = "text",
) -> dict[str, Any]:
    """All offers of the saved stores (websocket essensplaner/store_offers).

    {total, offers: [...], stores: [{branch_id, label, retailer, store, count_current,
    count_upcoming, sources, leaflet_only (leaflet images and no catalog offers; own offers
    typed from the leaflet do not count), leaflets, status, error}], meta: {updated, status,
    errors, marktguru, sources, count}}. The store counts follow the kind / query / mine
    filters (not the store and time filters). Online-only offers only with include_online.
    match: "text" (the panel's search box: any text of the offer) or "key" (a product
    question: offers of the product itself, see _key_query()).
    """
    catalog: OfferCatalog = manager.catalog
    today = manager.today()
    day = today.isoformat()
    offers = catalog.current_offers(today)
    branch_map = _branch_map(manager, catalog, offers)
    # a store whose source has only leaflet images (NORMA) stays a leaflet tile when the
    # user types offers from its leaflet: only the catalog's offers count for leaflet_only
    catalog_ids = [o["id"] for o in offers]
    # the offers typed from a leaflet (e.g. NORMA) and ALDI SÜD's reduced articles, for the
    # branches they are tagged with
    extra = own_offers(manager, today)
    if extra:
        branch_map = {**branch_map, **{o["id"]: o["branch_ids"] for o in extra}}
        offers = [*offers, *extra]
    planning = set(planning_keys(manager)) if mine else set()
    folded_query = (query or "").strip()
    fits = _key_query(folded_query) if match == "key" else _text_query(folded_query)

    counts: dict[str, list[int]] = {}
    selected: list[dict[str, Any]] = []
    wanted = set(branch_ids or [])
    # without saved branches (1.2 setup: postcode + chains in the options) every offer of
    # the chosen chains counts, without a branch
    no_branches = not any(b.get("retailer") for b in manager.selected_branches())
    active = set(manager.active_retailers()) if no_branches else set()
    for offer in offers:
        branches = branch_map.get(offer["id"]) or []
        if not branches and not (no_branches and offer.get("retailer") in active):
            continue
        if offer.get("online_only") and not include_online:
            continue
        if not kind_matches(offer, kind):
            continue
        if mine and not set(offer.get("keys") or []) & planning:
            continue
        if folded_query and not fits(offer):
            continue
        current = not offer.get("valid_from") or offer["valid_from"] <= day
        for bid in branches:
            pair = counts.setdefault(bid, [0, 0])
            pair[0 if current else 1] += 1
        if wanted and not wanted & set(branches):
            continue
        if (when == "current" and not current) or (when == "upcoming" and current):
            continue
        selected.append(_view(offer, [b for b in branches if not wanted or b in wanted], day))
    selected.sort(key=_SORT_KEYS.get(sort, _SORT_KEYS["saving"]))
    limit = max(1, min(int(limit), MAX_VIEW_LIMIT))
    offset = max(0, int(offset))
    branch_zip = manager._offer_plan()[1]
    stores = []
    for branch in manager.selected_branches():
        if not branch.get("retailer") or not branch.get("id"):
            continue
        zip_code = branch_zip.get(branch["id"])
        sources, status, error, leaflets = _source_status(manager, catalog, branch, zip_code)
        current, upcoming = counts.get(branch["id"], [0, 0])
        has_offers = any(branch["id"] in (branch_map.get(i) or []) for i in catalog_ids)
        stores.append(
            {
                "branch_id": branch["id"],
                "label": manager.branch_label(branch),
                "retailer": branch["retailer"],
                "store": retailer_name(branch["retailer"]),
                "main": branch["id"] == manager.main_branch,
                "count_current": current,
                "count_upcoming": upcoming,
                "sources": sources,
                "leaflet_only": bool(leaflets) and not has_offers,
                "leaflets": leaflets,
                "status": status,
                "error": error,
            }
        )
    summary = catalog.summary(manager)
    return {
        "total": len(selected),
        "offset": offset,
        "limit": limit,
        "offers": selected[offset : offset + limit],
        "stores": stores,
        "meta": {
            "updated": summary["updated"],
            "last_run": summary["last_run"],
            "status": summary["status"],
            "errors": summary["errors"],
            "marktguru": summary["marktguru"],
            "sources": summary["sources"],
            "count": summary["count"],
            "blocked_until": summary["blocked_until"],
        },
    }
