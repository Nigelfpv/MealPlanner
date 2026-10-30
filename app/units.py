"""Unit handling: normalisation, conversion and ingredient densities.

The same tables are sent to the browser (GET /api/units) so the recipe page
and the server convert identically.
"""

import re

# Base unit per dimension: mass -> g, volume -> ml, count -> pc
MASS = {"mg": 0.001, "g": 1.0, "kg": 1000.0, "oz": 28.3495, "lb": 453.592}
VOLUME = {
    "ml": 1.0, "cl": 10.0, "dl": 100.0, "l": 1000.0,
    "tsp": 5.0, "tbsp": 15.0, "cup": 240.0, "floz": 29.5735, "pinch": 0.3,
}
COUNT = {"pc": 1.0}
# Units that are counted but not convertible without extra info.
PACKAGE_UNITS = ["clove", "slice", "can", "jar", "pack", "bunch", "bag", "bottle", "handful", "sprig", "to taste"]

LABELS = {
    "mg": "mg", "g": "g", "kg": "kg", "oz": "oz", "lb": "lb",
    "ml": "ml", "cl": "cl", "dl": "dl", "l": "l", "tsp": "tsp", "tbsp": "tbsp", "cup": "cup",
    "floz": "fl oz", "pinch": "pinch", "pc": "pc",
}

ALIASES = {
    "gram": "g", "grams": "g", "gr": "g", "grs": "g",
    "kilo": "kg", "kilos": "kg", "kilogram": "kg", "kilograms": "kg",
    "milligram": "mg", "milligrams": "mg",
    "ounce": "oz", "ounces": "oz", "pound": "lb", "pounds": "lb", "lbs": "lb",
    "milliliter": "ml", "milliliters": "ml", "millilitre": "ml", "millilitres": "ml", "mls": "ml",
    "liter": "l", "liters": "l", "litre": "l", "litres": "l", "ltr": "l",
    "centiliter": "cl", "deciliter": "dl",
    "teaspoon": "tsp", "teaspoons": "tsp", "tsps": "tsp", "tl": "tsp",
    "tablespoon": "tbsp", "tablespoons": "tbsp", "tbsps": "tbsp", "tbs": "tbsp", "el": "tbsp",
    "cups": "cup", "fl oz": "floz", "fl. oz": "floz", "fluid ounce": "floz", "fluid ounces": "floz",
    "pinches": "pinch",
    "piece": "pc", "pieces": "pc", "pcs": "pc", "x": "pc", "stuks": "pc", "stuk": "pc", "unit": "pc",
    "units": "pc", "whole": "pc", "": "pc",
    "cloves": "clove", "slices": "slice", "cans": "can", "tin": "can", "tins": "can", "jars": "jar",
    "packs": "pack", "packet": "pack", "packets": "pack", "package": "pack", "bunches": "bunch",
    "bags": "bag", "bottles": "bottle", "handfuls": "handful", "sprigs": "sprig",
}

# Grams per millilitre for common kitchen ingredients. Matched by keyword
# (longest keyword first) when the ingredient has no density of its own.
DENSITIES = {
    "water": 1.0, "stock": 1.0, "broth": 1.0, "bouillon": 1.0, "wine": 0.99, "beer": 1.01,
    "milk": 1.03, "buttermilk": 1.03, "cream": 1.0, "sour cream": 1.0, "creme fraiche": 1.0,
    "crème fraîche": 1.0, "yogurt": 1.03, "yoghurt": 1.03, "quark": 1.05,
    "oil": 0.92, "olive oil": 0.92, "butter": 0.96, "melted butter": 0.91, "margarine": 0.96,
    "salt": 1.2, "sea salt": 1.0, "coarse salt": 1.0, "sugar": 0.85, "brown sugar": 0.9,
    "icing sugar": 0.56, "powdered sugar": 0.56, "honey": 1.42, "syrup": 1.33, "maple syrup": 1.32,
    "flour": 0.53, "cornstarch": 0.54, "cornflour": 0.54, "maizena": 0.54, "breadcrumbs": 0.45,
    "panko": 0.25, "baking powder": 0.9, "baking soda": 1.1, "yeast": 0.6, "cocoa": 0.42,
    "rice": 0.85, "oats": 0.41, "rolled oats": 0.41, "couscous": 0.73, "quinoa": 0.72,
    "lentils": 0.82, "bulgur": 0.75, "semolina": 0.68,
    "soy sauce": 1.15, "vinegar": 1.01, "lemon juice": 1.03, "lime juice": 1.03, "juice": 1.04,
    "ketchup": 1.15, "mayonnaise": 0.94, "mustard": 1.05, "tomato paste": 1.1, "tomato puree": 1.05,
    "passata": 1.04, "pesto": 0.95, "jam": 1.33, "peanut butter": 1.08, "sambal": 1.05,
    "parmesan": 0.42, "grated cheese": 0.38, "cheese": 0.45, "cream cheese": 1.0,
    "pepper": 0.5, "black pepper": 0.5, "paprika": 0.46, "cumin": 0.4, "cinnamon": 0.53,
    "oregano": 0.18, "thyme": 0.3, "chili flakes": 0.4, "curry powder": 0.42, "garlic powder": 0.53,
    "spice": 0.5, "nuts": 0.6, "raisins": 0.6, "chocolate chips": 0.72, "coffee": 0.4,
}

# Grams per piece, used to convert counted items to weight.
UNIT_WEIGHTS = {
    "egg": 60, "onion": 150, "red onion": 150, "shallot": 40, "garlic": 5, "clove": 5,
    "potato": 170, "carrot": 80, "tomato": 120, "cherry tomato": 15, "bell pepper": 160,
    "pepper": 160, "zucchini": 250, "courgette": 250, "eggplant": 300, "aubergine": 300,
    "lemon": 100, "lime": 65, "apple": 180, "banana": 120, "orange": 180, "avocado": 170,
    "leek": 250, "chili": 15, "mushroom": 20, "tortilla": 60, "wrap": 60, "bread roll": 70,
}

def norm_unit(unit: str | None) -> str:
    """Map free-form unit text to a canonical key (unknown units are kept, lower-cased)."""
    if unit is None:
        return "pc"
    u = unit.strip().lower().rstrip(".")
    if u in MASS or u in VOLUME or u in COUNT:
        return u
    if u in ALIASES:
        return ALIASES[u]
    if u.endswith("s") and u[:-1] in ALIASES:
        return ALIASES[u[:-1]]
    return u


def dimension(unit: str) -> str | None:
    u = norm_unit(unit)
    if u in MASS:
        return "mass"
    if u in VOLUME:
        return "volume"
    if u in COUNT:
        return "count"
    return None


def norm_name(name: str) -> str:
    n = (name or "").strip().lower()
    n = re.sub(r"\s+", " ", n)
    return n


def _keyword_lookup(table: dict, name: str):
    n = norm_name(name)
    if not n:
        return None
    if n in table:
        return table[n]
    best = None
    for key in sorted(table, key=len, reverse=True):
        if re.search(r"\b" + re.escape(key) + r"(e?s)?\b", n):
            best = table[key]
            break
    return best


def default_density(name: str) -> float | None:
    return _keyword_lookup(DENSITIES, name)


def default_unit_weight(name: str) -> float | None:
    return _keyword_lookup(UNIT_WEIGHTS, name)


def to_base(qty: float, unit: str, density: float | None = None, unit_weight: float | None = None):
    """Return (amount, dimension) in base units (g / ml / pc), or None if not convertible."""
    u = norm_unit(unit)
    if qty is None:
        return None
    if u in MASS:
        return qty * MASS[u], "mass"
    if u in VOLUME:
        return qty * VOLUME[u], "volume"
    if u in COUNT:
        return qty * COUNT[u], "count"
    return None


def convert(qty: float, from_unit: str, to_unit: str,
            density: float | None = None, unit_weight: float | None = None) -> float | None:
    """Convert between any two units, using density (g/ml) and unit weight (g/pc) when needed."""
    f, t = norm_unit(from_unit), norm_unit(to_unit)
    if qty is None:
        return None
    if f == t:
        return qty
    base = to_base(qty, f, density, unit_weight)
    if base is None:
        return None
    amount, dim = base
    tdim = dimension(t)
    if tdim is None:
        return None
    # move amount into the target dimension
    if dim != tdim:
        grams = None
        if dim == "mass":
            grams = amount
        elif dim == "volume" and density:
            grams = amount * density
        elif dim == "count" and unit_weight:
            grams = amount * unit_weight
        if grams is None:
            return None
        if tdim == "mass":
            amount = grams
        elif tdim == "volume" and density:
            amount = grams / density
        elif tdim == "count" and unit_weight:
            amount = grams / unit_weight
        else:
            return None
    table = MASS if tdim == "mass" else VOLUME if tdim == "volume" else COUNT
    return amount / table[t]


def tables() -> dict:
    return {
        "mass": MASS, "volume": VOLUME, "count": COUNT, "package": PACKAGE_UNITS,
        "labels": LABELS, "aliases": ALIASES, "densities": DENSITIES, "unit_weights": UNIT_WEIGHTS,
    }
