"""Profile preferences (1.5.1): diet, allergies, cuisines, flavours, kitchen devices,
cooking days and time limits ("Dein Geschmack", "Essen", "Dein Plan" in the panel's ⚙️).

Pure rules on a recipe dict (name, tags, ingredients [{name, category}], steps):

- recipe_diet(): vegan, vegetarisch, pescetarisch or fleisch (tags first, else the
  ingredients),
- recipe_allergens(): the allergens of the ingredients (a keyword table on the folded
  words; "Reis" / "Eis" are no egg, "Kokosmilch" no milk, "laktosefrei" no lactose …),
- recipe_devices(): what the recipe needs – groups of alternatives ("im Ofen oder in der
  Mikrowelle" is satisfied by either),
- recipe_cuisines() / recipe_flavors(): soft hints for the ranking,
- profile_filter(): the hard rules (diet, allergies, excluded ingredients, missing
  devices) with German reasons, profile_score(): the soft boost of liked cuisines and
  flavours.

The analysis of a recipe is cached per recipe signature (name, tags, ingredients, steps).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
import re
from typing import Any

from .ingredients import fold, guess_category, is_pantry_item

# --------------------------------------------------------------------------------------
# Choices (the option values; German labels: options_schema.CHOICE_LABELS_DE)
# --------------------------------------------------------------------------------------
DIET_ALL = "alles"
DIET_FLEXI = "flexitarisch"
DIET_PESCE = "pescetarisch"
DIET_VEGGIE = "vegetarisch"
DIET_VEGAN = "vegan"
DIETS = [DIET_ALL, DIET_FLEXI, DIET_PESCE, DIET_VEGGIE, DIET_VEGAN]
DEFAULT_DIET = DIET_ALL

# what a recipe is (recipe_diet())
RECIPE_MEAT = "fleisch"
RECIPE_FISH = "pescetarisch"
RECIPE_VEGGIE = "vegetarisch"
RECIPE_VEGAN = "vegan"
_RECIPE_RANK = {RECIPE_MEAT: 0, RECIPE_FISH: 1, RECIPE_VEGGIE: 2, RECIPE_VEGAN: 3}
_DIET_NEEDS = {DIET_ALL: 0, DIET_FLEXI: 0, DIET_PESCE: 1, DIET_VEGGIE: 2, DIET_VEGAN: 3}
# flexitarian: at most this many meat dishes per week in the auto plan
FLEXI_MEAT_PER_WEEK = 2

ALLERGENS = [
    "gluten",
    "laktose",
    "ei",
    "nuesse",
    "erdnuesse",
    "fisch",
    "krebstiere",
    "soja",
    "sellerie",
    "senf",
    "sesam",
]
CUISINES = [
    "deutsch",
    "italienisch",
    "asiatisch",
    "mexikanisch",
    "griechisch",
    "indisch",
    "orientalisch",
    "franzoesisch",
    "amerikanisch",
    "spanisch",
]
FLAVORS = ["herzhaft", "wuerzig", "scharf", "mild", "suess", "frisch", "deftig", "cremig"]
DEVICE_OVEN = "backofen"
DEVICE_STOVE = "herd"
DEVICE_MICROWAVE = "mikrowelle"
DEVICE_AIRFRYER = "heissluftfritteuse"
DEVICE_GRILL = "grill"
DEVICE_MIXER = "kuechenmaschine"
DEVICE_PRESSURE = "schnellkochtopf"
DEVICE_SLOW = "slowcooker"
DEVICE_RACLETTE = "raclette"
DEVICE_FONDUE = "fondue"
DEVICE_WAFFLE = "waffeleisen"
DEVICES = [
    DEVICE_OVEN,
    DEVICE_STOVE,
    DEVICE_MICROWAVE,
    DEVICE_AIRFRYER,
    DEVICE_GRILL,
    DEVICE_MIXER,
    DEVICE_PRESSURE,
    DEVICE_SLOW,
    DEVICE_RACLETTE,
    DEVICE_FONDUE,
    DEVICE_WAFFLE,
]
DEFAULT_KITCHEN = [DEVICE_OVEN, DEVICE_STOVE, DEVICE_MICROWAVE]
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DEFAULT_COOK_DAYS = list(WEEKDAYS)
# minutes of the time limits (0 = egal); the panel offers these, the option takes 0–240
TIME_CHOICES = [0, 15, 20, 30, 45, 60, 90]
TIME_RANGE = (0, 240)

# German names for the reasons and the AI payload
ALLERGEN_NAMES = {
    "gluten": "Gluten",
    "laktose": "Laktose",
    "ei": "Ei",
    "nuesse": "Nüsse",
    "erdnuesse": "Erdnüsse",
    "fisch": "Fisch",
    "krebstiere": "Krebstiere",
    "soja": "Soja",
    "sellerie": "Sellerie",
    "senf": "Senf",
    "sesam": "Sesam",
}
DEVICE_NAMES = {
    DEVICE_OVEN: "Backofen",
    DEVICE_STOVE: "Herd",
    DEVICE_MICROWAVE: "Mikrowelle",
    DEVICE_AIRFRYER: "Heißluftfritteuse",
    DEVICE_GRILL: "Grill",
    DEVICE_MIXER: "Küchenmaschine",
    DEVICE_PRESSURE: "Schnellkochtopf",
    DEVICE_SLOW: "Slow Cooker",
    DEVICE_RACLETTE: "Raclette",
    DEVICE_FONDUE: "Fondue",
    DEVICE_WAFFLE: "Waffeleisen",
}
DIET_NAMES = {
    DIET_ALL: "Keine Einschränkungen",
    DIET_FLEXI: "Flexitarisch (wenig Fleisch)",
    DIET_PESCE: "Pescetarisch",
    DIET_VEGGIE: "Vegetarisch",
    DIET_VEGAN: "Vegan",
}
CUISINE_NAMES = {
    "deutsch": "Deutsch / Hausmannskost",
    "italienisch": "Italienisch",
    "asiatisch": "Asiatisch",
    "mexikanisch": "Mexikanisch",
    "griechisch": "Griechisch",
    "indisch": "Indisch",
    "orientalisch": "Orientalisch",
    "franzoesisch": "Französisch",
    "amerikanisch": "Amerikanisch",
    "spanisch": "Spanisch",
}
FLAVOR_NAMES = {
    "herzhaft": "herzhaft",
    "wuerzig": "würzig",
    "scharf": "scharf",
    "mild": "mild",
    "suess": "süß",
    "frisch": "frisch",
    "deftig": "deftig",
    "cremig": "cremig",
}
WEEKDAY_SHORT = {
    "mon": "Mo",
    "tue": "Di",
    "wed": "Mi",
    "thu": "Do",
    "fri": "Fr",
    "sat": "Sa",
    "sun": "So",
}

# --------------------------------------------------------------------------------------
# Diet: meat and fish words (folded; (word, mode) – "part": anywhere in a word, "start":
# the start of a word, "end": its end, "word": the whole word)
# --------------------------------------------------------------------------------------
_MEAT_WORDS: tuple[tuple[str, str], ...] = (
    ("fleisch", "part"),
    ("hack", "start"),
    ("hack", "end"),
    ("haehnchen", "part"),
    ("huhn", "part"),
    ("huehner", "part"),
    ("chicken", "part"),
    ("pute", "start"),
    ("truthahn", "part"),
    ("ente", "start"),
    ("gans", "start"),
    ("gaense", "start"),
    ("rind", "start"),
    ("rind", "end"),
    ("kalb", "start"),
    ("schwein", "part"),
    ("lamm", "start"),
    ("hirsch", "start"),
    ("reh", "start"),
    ("kaninchen", "part"),
    ("speck", "part"),
    ("bacon", "part"),
    ("schinken", "part"),
    ("salami", "part"),
    ("wurst", "part"),
    ("wuerst", "part"),
    ("chorizo", "part"),
    ("kassler", "part"),
    ("kasseler", "part"),
    ("leber", "part"),
    ("steak", "part"),
    ("schnitzel", "part"),
    ("gulasch", "part"),
    ("geschnetzelt", "part"),
    ("frikadelle", "part"),
    ("bulette", "part"),
    ("nugget", "part"),
    ("cevapcici", "part"),
    ("doener", "part"),
    ("gyros", "part"),
    ("pancetta", "part"),
    ("prosciutto", "part"),
    ("mortadella", "part"),
    ("pastrami", "part"),
    ("corned", "part"),
    ("roastbeef", "part"),
    ("tafelspitz", "part"),
    ("bratwurst", "part"),
    ("wiener", "word"),
    ("maultasche", "part"),
    ("gelatine", "part"),
    ("eisbein", "part"),
    ("haxe", "part"),
    ("rippchen", "part"),
    ("spareribs", "part"),
    ("kotelett", "part"),
    ("lende", "part"),
    ("nacken", "start"),
    ("mett", "start"),
    ("gefluegel", "part"),
    ("wildfond", "part"),
    ("bolognese", "part"),
    ("kalbsfond", "part"),
    ("rinderfond", "part"),
)
# words that contain a meat word but are none
_NOT_MEAT = (
    "fruchtfleisch",
    "fleischtomate",
    "sojahack",
    "veggie",
    "huehnerei",
    "hirschhornsalz",
    "lammsalat",
    "blumenkohlsteak",
    "selleriesteak",
    "tofusteak",
    "sellerieschnitzel",
    "kohlrabischnitzel",
    "gemuesegulasch",
    "gemuesefrikadelle",
    "gemuesebruehe",
    "gemuesefond",
    "rindenmulch",
    "linsenbolognese",
    "gemuesebolognese",
)
_FISH_WORDS: tuple[tuple[str, str], ...] = tuple(
    (w, "part")
    for w in (
        "fisch",
        "lachs",
        "kabeljau",
        "forelle",
        "hering",
        "matjes",
        "makrele",
        "sardelle",
        "sardine",
        "anchovi",
        "zander",
        "scholle",
        "dorsch",
        "pangasius",
        "tilapia",
        "barsch",
        "karpfen",
        "heilbutt",
        "steinbutt",
        "seehecht",
        "dorade",
        "surimi",
        "kaviar",
        "garnele",
        "shrimp",
        "scampi",
        "krabbe",
        "krebs",
        "hummer",
        "languste",
        "gamba",
        "muschel",
        "tintenfisch",
        "calamar",
        "oktopus",
        "pulpo",
        "meeresfruechte",
        "schlemmerfilet",
    )
)
_NOT_FISH = ("lachsschinken", "muschelnudel")
# crustaceans and molluscs (not "Fisch" as an allergen)
_SEAFOOD = frozenset(
    {
        "garnele",
        "shrimp",
        "scampi",
        "krabbe",
        "krebs",
        "hummer",
        "languste",
        "gamba",
        "muschel",
        "tintenfisch",
        "calamar",
        "oktopus",
        "pulpo",
        "meeresfruechte",
    }
)
# a line that says it is vegetarian ("vegane Wurst", "Veggie-Burger")
_VEG_LINE = re.compile(r"(^| )(vegan\w*|vegetarisch\w*|veggie\w*|fleischlos\w*)( |$)")
# other animal products (vegan only without them)
_ANIMAL_WORDS: tuple[tuple[str, str], ...] = (
    ("honig", "part"),
    ("gelatine", "part"),
    ("eierlikoer", "part"),
)

# --------------------------------------------------------------------------------------
# Allergens: (word part, mode) as above; "phrase": words of the whole line
# --------------------------------------------------------------------------------------
_ALLERGEN_WORDS: dict[str, tuple[tuple[str, str], ...]] = {
    "gluten": (
        *(
            (w, "part")
            for w in (
                "weizen",
                "dinkel",
                "roggen",
                "gerste",
                "hafer",
                "gruenkern",
                "kamut",
                "seitan",
                "paniermehl",
                "semmelbroesel",
                "bulgur",
                "couscous",
                "griess",
                "nudel",
                "spaghetti",
                "penne",
                "fusilli",
                "farfalle",
                "tagliatelle",
                "makkaroni",
                "maccheroni",
                "rigatoni",
                "linguine",
                "lasagne",
                "tortellini",
                "tortelloni",
                "ravioli",
                "cannelloni",
                "maultasche",
                "gnocchi",
                "spaetzle",
                "knoedel",
                "mehl",
                "brot",
                "broetchen",
                "toast",
                "baguette",
                "ciabatta",
                "semmel",
                "brezel",
                "laugen",
                "croissant",
                "crouton",
                "wrap",
                "tortilla",
                "fladen",
                "keks",
                "zwieback",
                "biskuit",
                "lebkuchen",
                "malz",
                "teriyaki",
                "panko",
                "graupen",
                "pizza",
                "flammkuchen",
                "kaiserschmarrn",
                "pfannkuchen",
                "waffel",
                "nugget",
                "panier",
                "fischstaebchen",
                "fruehlingsrolle",
                "cornflakes",
            )
        ),
        ("pasta", "word"),
        ("pasta", "end"),
        ("emmer", "word"),
        ("teig", "end"),
        ("bier", "word"),
        ("bier", "end"),
    ),
    "laktose": (
        *(
            (w, "part")
            for w in (
                "milch",
                "sahne",
                "rahm",
                "schmand",
                "butter",
                "kaese",
                "quark",
                "joghurt",
                "jogurt",
                "skyr",
                "kefir",
                "molke",
                "mascarpone",
                "mozzarella",
                "burrata",
                "parmesan",
                "pecorino",
                "gouda",
                "emmentaler",
                "edamer",
                "halloumi",
                "ricotta",
                "gorgonzola",
                "camembert",
                "cheddar",
                "raclette",
                "cremefine",
                "pesto",
                "bechamel",
                "hollandaise",
                "tzatziki",
                "eiscreme",
                "kaiserschmarrn",
            )
        ),
        ("ghee", "word"),
        ("grana", "word"),
        ("feta", "word"),
        ("brie", "word"),
        ("creme fraiche", "phrase"),
        ("creme double", "phrase"),
    ),
    "ei": (
        *(
            (w, "part")
            for w in (
                "eigelb",
                "eiklar",
                "eidotter",
                "huehnerei",
                "wachtelei",
                "spiegelei",
                "ruehrei",
                "eiernudel",
                "eierteig",
                "eierlikoer",
                "mayonnaise",
                "remoulade",
                "aioli",
                "hollandaise",
                "spaetzle",
                "baiser",
                "biskuit",
                "kaiserschmarrn",
                "pfannkuchen",
                "tortellini",
                "maultasche",
            )
        ),
        ("ei", "word"),
        ("eier", "word"),
        ("eiweiss", "word"),
        ("mayo", "word"),
    ),
    "nuesse": tuple(
        (w, "part")
        for w in (
            "mandel",
            "haselnuss",
            "haselnuess",
            "walnuss",
            "walnuess",
            "cashew",
            "pistazie",
            "pekannuss",
            "pecan",
            "macadamia",
            "paranuss",
            "nuss",
            "nuess",
            "marzipan",
            "nougat",
            "krokant",
        )
    ),
    "erdnuesse": (("erdnuss", "part"), ("erdnuess", "part")),
    "fisch": (
        *((w, "part") for w, _ in _FISH_WORDS if w not in _SEAFOOD),
        ("worcester", "part"),
    ),
    "krebstiere": tuple(
        (w, "part")
        for w in ("garnele", "shrimp", "scampi", "krabbe", "krebs", "hummer", "languste", "gamba")
    ),
    "soja": (
        *((w, "part") for w in ("soja", "tofu", "edamame", "miso", "tempeh", "teriyaki", "hoisin")),
    ),
    "sellerie": (("sellerie", "part"), ("suppengruen", "part")),
    "senf": (("senf", "part"), ("dijon", "part")),
    "sesam": (
        ("sesam", "part"),
        ("tahin", "part"),
        ("hummus", "part"),
        ("humus", "word"),
        ("gomasio", "part"),
    ),
}
# words that look like an allergen but are none ("Kokosmilch" is no milk, "Muskatnuss" no
# nut); checked on the word that matched
_ALLERGEN_EXCEPTIONS: dict[str, tuple[str, ...]] = {
    "gluten": (
        "glutenfrei",
        "mehlig",
        "reisnudel",
        "glasnudel",
        "zucchininudel",
        "konjaknudel",
        "reismehl",
        "maismehl",
        "mandelmehl",
        "kokosmehl",
        "kichererbsenmehl",
        "kartoffelmehl",
        "johannisbrotkernmehl",
        "buchweizen",
        "maisgriess",
        "reisgriess",
        "maistortilla",
        "reiswaffel",
        "kartoffelknoedel",
        "kartoffelteig",
        "brotgewuerz",
        "pizzatomate",
        "pizzakaese",
        "pizzagewuerz",
    ),
    "laktose": (
        "laktosefrei",
        "milchfrei",
        "kokosmilch",
        "hafermilch",
        "sojamilch",
        "mandelmilch",
        "reismilch",
        "cashewmilch",
        "haselnussmilch",
        "dinkelmilch",
        "erbsenmilch",
        "pflanzenmilch",
        "milchreis",
        "kokossahne",
        "hafersahne",
        "sojasahne",
        "pflanzensahne",
        "kokosjoghurt",
        "sojajoghurt",
        "haferjoghurt",
        "erdnussbutter",
        "mandelbutter",
        "cashewbutter",
        "kakaobutter",
        "nussbutter",
        "sheabutter",
        "pflanzenbutter",
        "butterbohne",
        "butternut",
        "kaeseersatz",
        "leberkaese",
        "rahmen",
    ),
    "ei": ("eifrei",),
    "nuesse": (
        "muskatnuss",
        "muskatnuess",
        "kokosnuss",
        "kokosnuess",
        "erdnuss",
        "erdnuess",
        "nussschinken",
    ),
    "fisch": ("lachsschinken", "muschelnudel"),
}
# a whole line without the allergen ("vegane Butter", "laktosefreie Milch", "glutenfreie
# Nudeln", "Tortilla-Chips")
_LINE_FREE = {
    "gluten": re.compile(r"glutenfrei|tortilla chip|mais tortilla"),
    "laktose": re.compile(
        r"laktosefrei|milchfrei|(^| )(vegan|vegane|veganer|veganes|pflanzlich\w*)( |$)"
    ),
    "ei": re.compile(r"eifrei|ohne ei|(^| )(vegan|vegane|veganer|veganes)( |$)"),
}
_SOY_SAUCE = re.compile(r"sojasauce|sojasosse|soja sauce|soja sosse")

# --------------------------------------------------------------------------------------
# Devices: words in the steps (folded) and the tags that need one
# --------------------------------------------------------------------------------------
_DEVICE_PATTERNS: dict[str, re.Pattern[str]] = {
    DEVICE_OVEN: re.compile(
        r"(^| )(back)?ofen( |$)|backofen|umluft|unterhitze|backblech|auflaufform"
        r"|(^| )(im|in den|aus dem) ofen( |$)"
    ),
    DEVICE_MICROWAVE: re.compile(r"mikrowelle"),
    DEVICE_AIRFRYER: re.compile(r"heissluftfritteuse|heissluft fritteuse|airfryer|air fryer"),
    DEVICE_GRILL: re.compile(r"(^| )grill( |$)|grillrost|(^| )grillen( |$)|holzkohle|gasgrill"),
    DEVICE_MIXER: re.compile(r"thermomix|kuechenmaschine|monsieur cuisine|varoma"),
    DEVICE_PRESSURE: re.compile(r"schnellkochtopf|dampfdrucktopf|instant ?pot|druckgarer"),
    DEVICE_SLOW: re.compile(r"slow ?cooker|schongarer|crock ?pot"),
    DEVICE_RACLETTE: re.compile(r"raclette ?(geraet|grill|pfaenn)|pfaennchen"),
    DEVICE_FONDUE: re.compile(r"fonduetopf|fondue ?(topf|gabel|set)|rechaud"),
    DEVICE_WAFFLE: re.compile(r"waffeleisen"),
    DEVICE_STOVE: re.compile(
        r"pfanne|(^| )(koch)?topf|(^| )wok( |$)|(^| )herd( |$)|kasserolle"
        r"|koecheln|aufkochen|anbraten|anduensten|duensten|blanchier|(^| )(braten|kochen)( |$)"
    ),
}
# "Grillpfanne", "Backofengrill", "Grillschale" (on a grill: keeps the grill), "Grillgewürz"
_GRILL_NOT = re.compile(r"grillpfanne|backofengrill|ofengrill|grillgewuerz|grillsosse|grillsauce")
_ALT = re.compile(r"(^| )oder( |$)")
_TAG_DEVICES = {
    "ofen": DEVICE_OVEN,
    "backen": DEVICE_OVEN,
    "auflauf": DEVICE_OVEN,
    "pizza": DEVICE_OVEN,
    "kuchen": DEVICE_OVEN,
    "fondue": DEVICE_FONDUE,
    "raclette": DEVICE_RACLETTE,
    "heissluftfritteuse": DEVICE_AIRFRYER,
    "airfryer": DEVICE_AIRFRYER,
    "thermomix": DEVICE_MIXER,
    "slowcooker": DEVICE_SLOW,
}

# --------------------------------------------------------------------------------------
# Cuisines (by tag) and flavours (tags, name, ingredients)
# --------------------------------------------------------------------------------------
_CUISINE_TAGS = {
    "deutsch": (
        "deutsch",
        "hausmannskost",
        "schwaebisch",
        "bayerisch",
        "fraenkisch",
        "norddeutsch",
        "rheinisch",
        "oesterreichisch",
        "schweizerisch",
    ),
    "italienisch": ("italienisch", "pizza"),
    "asiatisch": (
        "asiatisch",
        "thailaendisch",
        "chinesisch",
        "japanisch",
        "vietnamesisch",
        "koreanisch",
        "indonesisch",
    ),
    "mexikanisch": ("mexikanisch", "tex mex", "texmex"),
    "griechisch": ("griechisch",),
    "indisch": ("indisch",),
    "orientalisch": (
        "orientalisch",
        "tuerkisch",
        "arabisch",
        "libanesisch",
        "marokkanisch",
        "persisch",
    ),
    "franzoesisch": ("franzoesisch",),
    "amerikanisch": ("amerikanisch",),
    "spanisch": ("spanisch", "tapas"),
}
_NOT_ITALIAN = re.compile(r"mac and cheese|mac n cheese|nudelsalat|kaesespaetzle|spaetzle")
_FLAVOR_WORDS = {
    "scharf": (
        "chili",
        "jalapeno",
        "sriracha",
        "sambal",
        "cayenne",
        "harissa",
        "tabasco",
        "pfefferschote",
        "peperoncini",
        "currypaste",
        "gochujang",
        "wasabi",
    ),
    "wuerzig": (
        "curry",
        "kreuzkuemmel",
        "kurkuma",
        "garam masala",
        "ras el hanout",
        "zimt",
        "ingwer",
        "piment",
        "koriander",
        "rauchpaprika",
        "geraeuchert",
        "chili",
    ),
    "frisch": (
        "salat",
        "zitrone",
        "limette",
        "gurke",
        "rucola",
        "minze",
        "basilikum",
        "dill",
        "petersilie",
        "koriander",
        "schnittlauch",
        "kraeuter",
        "tomate",
    ),
    "deftig": (
        "speck",
        "bacon",
        "bratwurst",
        "wurst",
        "sauerkraut",
        "schweinebauch",
        "eisbein",
        "kassler",
        "kasseler",
        "leberkaese",
        "knoedel",
        "schmalz",
        "haxe",
    ),
    "cremig": (
        "sahne",
        "rahm",
        "schmand",
        "creme fraiche",
        "mascarpone",
        "frischkaese",
        "kaesesosse",
        "kaesesauce",
        "hollandaise",
        "kokosmilch",
        "cremefine",
    ),
    "herzhaft": (
        "kaese",
        "speck",
        "schinken",
        "zwiebel",
        "hack",
        "wurst",
        "parmesan",
        "bergkaese",
    ),
}
_FLAVOR_TAGS = {
    "scharf": ("scharf",),
    "wuerzig": ("curry", "indisch", "orientalisch", "mexikanisch", "thailaendisch"),
    "frisch": ("salat", "sommer", "bowl"),
    "deftig": ("eintopf", "braten", "schwaebisch", "bayerisch", "hausmannskost"),
    "cremig": ("cremig",),
    "suess": ("suess", "dessert", "kuchen"),
    "mild": ("mild", "kinder"),
    "herzhaft": ("herzhaft", "auflauf", "eintopf", "braten", "pfanne"),
}
_FLAVOR_NAME = {
    "scharf": ("scharf", "chili", "diavolo", "arrabbiata", "vindaloo"),
    "cremig": ("cremig", "rahm", "sahne", "carbonara", "alfredo", "creme"),
    "frisch": ("salat", "bowl", "sommer"),
    "suess": ("suess", "dessert", "pudding", "muffin", "waffel", "pfannkuchen", "kaiserschmarrn"),
    "deftig": ("deftig", "eintopf", "braten", "haxe", "kraut"),
}
READY_MEAL_TAG = "fertiggericht"


# --------------------------------------------------------------------------------------
# The analysis of a recipe (cached)
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class RecipeInfo:
    """What the rules know about a recipe."""

    diet: str
    allergens: frozenset[str]
    devices: tuple[frozenset[str], ...]  # groups of alternatives, each one is needed
    cuisines: frozenset[str]
    flavors: frozenset[str]
    minutes: int | None


_CACHE: dict[tuple[Any, ...], RecipeInfo] = {}
_CACHE_MAX = 4096


def _raw_lines(recipe: Mapping[str, Any]) -> list[tuple[str, str]]:
    """(name, note) of the ingredients (a line of text: the whole line as the name)."""
    result = []
    for item in recipe.get("ingredients") or []:
        if isinstance(item, dict):
            name = str(item.get("name") or "")
            if name:
                result.append((name, str(item.get("note") or "")))
        elif isinstance(item, str) and item.strip():
            result.append((item, ""))
    return result


def _signature(recipe: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        recipe.get("id"),
        str(recipe.get("name") or ""),
        tuple(str(t) for t in recipe.get("tags") or []),
        tuple(_raw_lines(recipe)),
        tuple(str(s) for s in recipe.get("steps") or []),
        recipe.get("total_time"),
        recipe.get("prep_time"),
        recipe.get("cook_time"),
    )


def recipe_info(recipe: Mapping[str, Any]) -> RecipeInfo:
    """The analysis of a recipe (diet, allergens, devices, cuisines, flavours, minutes)."""
    key = _signature(recipe)
    if (cached := _CACHE.get(key)) is not None:
        return cached
    tags = {fold(str(t)) for t in recipe.get("tags") or []}
    raw = _raw_lines(recipe)
    # the names and the notes ("z. B. Gouda") are lines of their own
    lines = [fold(n) for n, _ in raw] + [fold(note) for _, note in raw if note]
    steps = [fold(str(s)) for s in recipe.get("steps") or []]
    name = fold(str(recipe.get("name") or ""))
    allergens = _allergens(lines)
    info = RecipeInfo(
        diet=_diet(tags, raw, allergens),
        allergens=frozenset(allergens),
        devices=_devices(tags, steps, name),
        cuisines=frozenset(_cuisines(tags, name)),
        flavors=frozenset(_flavors(tags, lines, name)),
        minutes=recipe_minutes(recipe),
    )
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.clear()
    _CACHE[key] = info
    return info


def recipe_minutes(recipe: Mapping[str, Any]) -> int | None:
    """The total time of a recipe in minutes (prep + cook when there is no total), None
    when unknown."""
    try:
        total = int(recipe.get("total_time") or 0)
    except (TypeError, ValueError):
        total = 0
    if total > 0:
        return total
    total = 0
    for key in ("prep_time", "cook_time"):
        try:
            total += max(0, int(recipe.get(key) or 0))
        except (TypeError, ValueError):
            continue
    return total or None


def _match(token: str, word: str, mode: str) -> bool:
    if mode == "word":
        return token == word
    if mode == "start":
        return token.startswith(word)
    if mode == "end":
        return token.endswith(word)
    return word in token


def _line_has(line: str, words: Iterable[tuple[str, str]], exceptions: Iterable[str] = ()) -> bool:
    """True if a word of the (folded) line matches one of the words, unless the word
    contains an exception."""
    exc = tuple(exceptions)
    for word, mode in words:
        if mode == "phrase":
            if f" {word} " in f" {line} ":
                return True
            continue
        for token in line.split():
            if _match(token, word, mode) and not any(e in token for e in exc):
                return True
    return False


def _diet(tags: set[str], raw: list[tuple[str, str]], allergens: set[str]) -> str:
    if "vegan" in tags:
        return RECIPE_VEGAN
    if "vegetarisch" in tags:
        return RECIPE_VEGGIE
    meat = fish = animal = False
    for name, _note in raw:
        line = fold(name)
        if _VEG_LINE.search(line):
            continue
        if _line_has(line, _FISH_WORDS, _NOT_FISH):
            fish = True
        elif _line_has(line, _MEAT_WORDS, _NOT_MEAT) or (
            guess_category(name) == "Fleisch & Fisch"
            and not re.search(r"soja|tofu|seitan|tempeh|lupine", line)
        ):
            meat = True
        if _line_has(line, _ANIMAL_WORDS):
            animal = True
    if meat:
        return RECIPE_MEAT
    if fish:
        return RECIPE_FISH
    if READY_MEAL_TAG in tags:
        # a ready meal without a "vegetarisch" tag: its filling is not known (canned
        # ravioli, a frozen Bami Goreng) – not vegetarian
        return RECIPE_MEAT
    if not raw or animal or allergens & {"laktose", "ei"}:
        # no ingredients: not known – vegetarian, never vegan
        return RECIPE_VEGGIE
    return RECIPE_VEGAN


def _allergens(lines: list[str]) -> set[str]:
    found: set[str] = set()
    for line in lines:
        for allergen, words in _ALLERGEN_WORDS.items():
            if allergen in found:
                continue
            free = _LINE_FREE.get(allergen)
            if free is not None and free.search(line):
                continue
            if _line_has(line, words, _ALLERGEN_EXCEPTIONS.get(allergen, ())):
                found.add(allergen)
        # soy sauce: soy and wheat (not tamari, not gluten free)
        if _SOY_SAUCE.search(line):
            found.add("soja")
            if "tamari" not in line and "glutenfrei" not in line:
                found.add("gluten")
    return found


def _devices(tags: set[str], steps: list[str], name: str) -> tuple[frozenset[str], ...]:
    groups: list[frozenset[str]] = []

    def add(group: Iterable[str]) -> None:
        g = frozenset(group)
        if g and g not in groups:
            groups.append(g)

    def needed(device: str) -> bool:
        return any(device in g for g in groups)

    grill_tag = "grillen" in tags or "grill" in tags
    for step in steps:
        found: dict[str, bool] = {}  # device -> only mentioned after an "oder"
        for device, pattern in _DEVICE_PATTERNS.items():
            for match in pattern.finditer(step):
                if device == DEVICE_GRILL:
                    around = step[max(0, match.start() - 8) : match.end() + 8]
                    if _GRILL_NOT.search(around) or not grill_tag:
                        continue
                before = " ".join(step[: match.start()].split()[-4:])
                alt = bool(_ALT.search(before))
                found[device] = found.get(device, True) and alt
        if not found:
            continue
        required = {d for d, alt in found.items() if not alt}
        optional = {d for d, alt in found.items() if alt}
        if optional and required:
            add(required | optional)  # "im Ofen oder in der Mikrowelle": either
        elif len(optional) > 1:
            add(optional)  # "in die Glut oder auf den Grill … (oder im Ofen)"
        elif optional:
            add(optional | {DEVICE_STOVE})  # "… braten (oder im Ofen backen)"
        else:
            for device in required:
                add({device})
    for tag, device in _TAG_DEVICES.items():
        if tag in tags and not needed(device):
            add({device})
    if re.search(r"(^| )fondue", name) and not needed(DEVICE_FONDUE):
        add({DEVICE_FONDUE})
    if re.search(r"(^| )raclette( |$)", name) and not needed(DEVICE_RACLETTE):
        add({DEVICE_RACLETTE})
    if re.search(r"(^| )waffel(n)?( |$)", name) and not needed(DEVICE_WAFFLE):
        add({DEVICE_WAFFLE})
    # the stove only counts when a step names it (pan, pot, simmering …)
    return tuple(groups)


def _cuisines(tags: set[str], name: str = "") -> set[str]:
    found = {c for c, words in _CUISINE_TAGS.items() if tags & set(words)}
    if "pasta" in tags and not found and not _NOT_ITALIAN.search(name):
        found.add("italienisch")  # a pasta dish without another cuisine
    if "klassiker" in tags and not found:
        found.add("deutsch")
    return found


def _flavors(tags: set[str], names: list[str], name: str) -> set[str]:
    found: set[str] = set()
    for flavor, words in _FLAVOR_TAGS.items():
        if tags & set(words):
            found.add(flavor)
    for flavor, words in _FLAVOR_NAME.items():
        if any(w in name for w in words):
            found.add(flavor)
    for flavor, words in _FLAVOR_WORDS.items():
        hits = sum(1 for n in names if any(w in n for w in words))
        if hits >= (2 if flavor in ("frisch", "wuerzig", "herzhaft") else 1):
            found.add(flavor)
    if "suess" in found:
        found.discard("herzhaft")
        found.discard("deftig")
    if "scharf" in found:
        found.discard("mild")
    return found


# --------------------------------------------------------------------------------------
# Public helpers
# --------------------------------------------------------------------------------------
def recipe_diet(recipe: Mapping[str, Any]) -> str:
    """vegan, vegetarisch, pescetarisch (fish or seafood, no meat) or fleisch."""
    return recipe_info(recipe).diet


def recipe_allergens(recipe: Mapping[str, Any]) -> set[str]:
    """The allergens (ALLERGENS ids) of a recipe's ingredients."""
    return set(recipe_info(recipe).allergens)


def recipe_devices(recipe: Mapping[str, Any]) -> list[frozenset[str]]:
    """What a recipe needs: groups of alternatives, each group needs one of its devices."""
    return list(recipe_info(recipe).devices)


def recipe_cuisines(recipe: Mapping[str, Any]) -> set[str]:
    """The cuisines (CUISINES ids) of a recipe (by its tags)."""
    return set(recipe_info(recipe).cuisines)


def recipe_flavors(recipe: Mapping[str, Any]) -> set[str]:
    """The flavours (FLAVORS ids) of a recipe (tags, name, ingredients; modest)."""
    return set(recipe_info(recipe).flavors)


def missing_devices(recipe: Mapping[str, Any], kitchen: Iterable[str]) -> list[str]:
    """The devices a recipe needs that the kitchen lacks (one per unmet group)."""
    have = set(kitchen)
    missing = []
    for group in recipe_info(recipe).devices:
        if not group & have:
            missing.append(sorted(group, key=DEVICES.index)[0])
    return missing


def diet_allows(recipe_kind_of_diet: str, diet: str) -> bool:
    """True if a recipe of this kind (recipe_diet()) fits the diet."""
    return _RECIPE_RANK.get(recipe_kind_of_diet, 0) >= _DIET_NEEDS.get(diet, 0)


@dataclass(frozen=True)
class Profile:
    """The profile options of the manager (see profile_from_options())."""

    diet: str = DIET_ALL
    allergies: frozenset[str] = frozenset()
    cuisines: frozenset[str] = frozenset()
    flavors: frozenset[str] = frozenset()
    kitchen: frozenset[str] = frozenset(DEFAULT_KITCHEN)
    cook_days: frozenset[str] = frozenset(WEEKDAYS)
    weekday_time: int = 0
    weekend_time: int = 0
    excluded: tuple[str, ...] = field(default=())

    def time_limit(self, day: date) -> int:
        """The time limit of a day in minutes (0 = none)."""
        return self.weekend_time if day.weekday() >= 5 else self.weekday_time

    def cooks_on(self, day: date) -> bool:
        """True if the household cooks on that day (main meals)."""
        return WEEKDAYS[day.weekday()] in self.cook_days

    def export(self) -> dict[str, Any]:
        """For the panel and the AI (no personal data: preferences only)."""
        return {
            "diet": self.diet,
            "allergies": sorted(self.allergies, key=ALLERGENS.index),
            "cuisines": sorted(self.cuisines, key=CUISINES.index),
            "flavors": sorted(self.flavors, key=FLAVORS.index),
            "kitchen": sorted(self.kitchen, key=DEVICES.index),
            "cook_days": [d for d in WEEKDAYS if d in self.cook_days],
            "weekday_time": self.weekday_time,
            "weekend_time": self.weekend_time,
        }


def _choice_set(value: Any, allowed: list[str], default: Iterable[str] = ()) -> frozenset[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return frozenset(default)
    return frozenset(v for v in value if v in allowed)


def _minutes(value: Any) -> int:
    try:
        number = int(float(value or 0))
    except (TypeError, ValueError):
        return 0
    return min(max(number, TIME_RANGE[0]), TIME_RANGE[1])


def profile_from_options(options: Mapping[str, Any], excluded: Iterable[str] = ()) -> Profile:
    """The profile of the options (missing or broken values: the defaults = the old
    behaviour)."""
    from .const import (
        CONF_ALLERGIES,
        CONF_COOK_DAYS,
        CONF_DIET,
        CONF_KITCHEN,
        CONF_LIKED_CUISINES,
        CONF_LIKED_FLAVORS,
        CONF_WEEKDAY_TIME,
        CONF_WEEKEND_TIME,
    )

    diet = options.get(CONF_DIET)
    kitchen = options.get(CONF_KITCHEN)
    cook_days = _choice_set(options.get(CONF_COOK_DAYS), WEEKDAYS, WEEKDAYS)
    return Profile(
        diet=diet if diet in DIETS else DIET_ALL,
        allergies=_choice_set(options.get(CONF_ALLERGIES), ALLERGENS),
        cuisines=_choice_set(options.get(CONF_LIKED_CUISINES), CUISINES),
        flavors=_choice_set(options.get(CONF_LIKED_FLAVORS), FLAVORS),
        kitchen=_choice_set(kitchen, DEVICES, DEFAULT_KITCHEN)
        if isinstance(kitchen, (list, tuple))
        else frozenset(DEFAULT_KITCHEN),
        cook_days=cook_days or frozenset(WEEKDAYS),
        weekday_time=_minutes(options.get(CONF_WEEKDAY_TIME)),
        weekend_time=_minutes(options.get(CONF_WEEKEND_TIME)),
        excluded=tuple(excluded),
    )


def excluded_hits(recipe: Mapping[str, Any], excluded: Iterable[str]) -> list[str]:
    """The excluded tags or ingredients ("Pilze", "Fisch") a recipe has (the rule of 1.0:
    a tag, or an ingredient that is or contains the word)."""
    items = [e for e in excluded if e]
    if not items:
        return []
    tags = {fold(str(t)) for t in recipe.get("tags") or []}
    names = [
        str(i.get("name") or "") if isinstance(i, dict) else str(i)
        for i in recipe.get("ingredients") or []
    ]
    hits = []
    for item in items:
        key = fold(item)
        if not key:
            continue
        if key in tags or any(is_pantry_item(n, [item]) or key in fold(n) for n in names):
            hits.append(item)
    return hits


def diet_reason(recipe_diet_kind: str, diet: str) -> str:
    """The German badge of a recipe that does not fit the diet ("🥩 nicht vegetarisch")."""
    emoji = "🐟" if recipe_diet_kind == RECIPE_FISH else "🥩"
    if diet == DIET_VEGAN and recipe_diet_kind == RECIPE_VEGGIE:
        emoji = "🧀"
    return f"{emoji} nicht {diet}"


def profile_filter(
    recipe: Mapping[str, Any], profile: Profile, devices: bool = True
) -> tuple[bool, list[str]]:
    """The hard rules of the profile: (ok, reasons) – diet, allergies, excluded
    ingredients and (devices True) missing kitchen devices. Reasons are short German
    badges ("🥩 nicht vegetarisch", "⚠️ Gluten", "🚫 Pilze", "🔥 braucht Backofen")."""
    reasons = profile_conflicts(recipe, profile, devices=devices)
    return not reasons, reasons


def profile_conflicts(
    recipe: Mapping[str, Any], profile: Profile, devices: bool = True
) -> list[str]:
    """profile_filter()'s reasons only."""
    info = recipe_info(recipe)
    reasons: list[str] = []
    if not diet_allows(info.diet, profile.diet):
        reasons.append(diet_reason(info.diet, profile.diet))
    for allergen in ALLERGENS:
        if allergen in profile.allergies and allergen in info.allergens:
            reasons.append(f"⚠️ {ALLERGEN_NAMES[allergen]}")
    reasons.extend(f"🚫 {hit}" for hit in excluded_hits(recipe, profile.excluded))
    if devices:
        reasons.extend(
            f"🔥 braucht {DEVICE_NAMES[d]}" for d in missing_devices(recipe, profile.kitchen)
        )
    return reasons


def profile_score(recipe: Mapping[str, Any], profile: Profile) -> float:
    """The soft boost of liked cuisines and flavours (1.0 = neutral; at most about 2.1)."""
    if not profile.cuisines and not profile.flavors and profile.diet != DIET_FLEXI:
        return 1.0
    info = recipe_info(recipe)
    score = 1.0
    if profile.cuisines and info.cuisines & profile.cuisines:
        score += 0.6
    if profile.flavors:
        score += 0.25 * min(2, len(info.flavors & profile.flavors))
    if profile.diet == DIET_FLEXI and info.diet == RECIPE_MEAT:
        score *= 0.6  # flexitarian: meat now and then
    return score


def is_meat(recipe: Mapping[str, Any]) -> bool:
    """True for a meat dish (recipe_diet() fleisch)."""
    return recipe_info(recipe).diet == RECIPE_MEAT


def is_ready_meal(recipe: Mapping[str, Any]) -> bool:
    """True for a ready meal (tag Fertiggericht)."""
    return READY_MEAL_TAG in {fold(str(t)) for t in recipe.get("tags") or []}


def summary_texts(profile: Profile) -> dict[str, Any]:
    """The profile in German words (AI payloads)."""
    return {
        "ernaehrung": DIET_NAMES.get(profile.diet, profile.diet),
        "allergien": [ALLERGEN_NAMES[a] for a in ALLERGENS if a in profile.allergies],
        "kuechen": [CUISINE_NAMES[c] for c in CUISINES if c in profile.cuisines],
        "aromen": [FLAVOR_NAMES[f] for f in FLAVORS if f in profile.flavors],
        "geraete": [DEVICE_NAMES[d] for d in DEVICES if d in profile.kitchen],
        "kochtage": [WEEKDAY_SHORT[d] for d in WEEKDAYS if d in profile.cook_days],
        "zeit_werktags_min": profile.weekday_time or None,
        "zeit_wochenende_min": profile.weekend_time or None,
    }


__all__ = [
    "ALLERGENS",
    "CUISINES",
    "DEFAULT_COOK_DAYS",
    "DEFAULT_KITCHEN",
    "DEVICES",
    "DIETS",
    "FLAVORS",
    "TIME_CHOICES",
    "WEEKDAYS",
    "Profile",
    "excluded_hits",
    "missing_devices",
    "profile_conflicts",
    "profile_filter",
    "profile_from_options",
    "profile_score",
    "recipe_allergens",
    "recipe_cuisines",
    "recipe_devices",
    "recipe_diet",
    "recipe_flavors",
    "recipe_info",
    "recipe_minutes",
]
