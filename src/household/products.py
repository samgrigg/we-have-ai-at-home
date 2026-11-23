"""Conservative ingredient matching and compatible-unit package arithmetic."""

import math
import re
from decimal import Decimal
from fractions import Fraction

from household.recipes import NUMBER, UNICODE_FRACTIONS

# US customary liquid measures; masses use grams. Never cross dimensions.
UNITS = {}
for names, dimension, factor, base in [
    ("cup cups", "volume", "8", "fl oz"),
    ("tbsp tablespoon tablespoons", "volume", "0.5", "fl oz"),
    ("tsp teaspoon teaspoons", "volume", str(Decimal(1) / Decimal(6)), "fl oz"),
    ("fl oz|fluid ounce|fluid ounces|floz", "volume", "1", "fl oz"),
    ("pt pint pints", "volume", "16", "fl oz"),
    ("qt quart quarts", "volume", "32", "fl oz"),
    ("gal gallon gallons", "volume", "128", "fl oz"),
    ("ml milliliter milliliters", "volume", str(Decimal(1) / Decimal("29.5735295625")), "fl oz"),
    ("l liter liters", "volume", str(Decimal(1000) / Decimal("29.5735295625")), "fl oz"),
    ("oz ounce ounces", "mass", "28.349523125", "g"),
    ("lb lbs pound pounds", "mass", "453.59237", "g"),
    ("g gram grams", "mass", "1", "g"),
    ("kg kilogram kilograms", "mass", "1000", "g"),
    ("ct count each piece pieces", "count", "1", "count"),
]:
    for name in names.split("|") if "|" in names else names.split():
        UNITS[name] = (dimension, Decimal(factor), base)
UNIT_PATTERN = "|".join(re.escape(unit) for unit in sorted(UNITS, key=len, reverse=True))
QUANTITY = re.compile(r"^(" + NUMBER + r")(?:\s*[-–]\s*(" + NUMBER + r"))?\s*")
UNIT = re.compile(r"^(" + UNIT_PATTERN + r")\b\.?\s*", re.I)
STOP = {
    "a",
    "an",
    "the",
    "of",
    "chopped",
    "diced",
    "minced",
    "drained",
    "rinsed",
    "optional",
    "to",
    "taste",
    "can",
    "cans",
    "canned",
    "package",
    "packages",
    "kernel",
    "kernels",
}
CONTAINERS = {
    "package",
    "packages",
    "pack",
    "packs",
    "can",
    "cans",
    "carton",
    "cartons",
    "bag",
    "bags",
    "bottle",
    "bottles",
    "bunch",
    "bunches",
    "tub",
    "tubs",
    "jar",
    "jars",
    "box",
    "boxes",
}
STOP.update(CONTAINERS)
STOP.update(word for unit in UNITS for word in unit.split())


def expanded(text):
    text = text.lower().replace("⁄", "/")
    for glyph, value in UNICODE_FRACTIONS.items():
        text = re.sub(r"(\d)" + glyph, r"\1 " + value, text).replace(glyph, value)
    return text


def number(value):
    return sum(
        (Decimal(Fraction(x).numerator) / Decimal(Fraction(x).denominator) for x in value.split()),
        Decimal(),
    )


def terms(text):
    words = re.findall(r"[a-z]+", text.lower().replace("-", " "))
    return [
        word[:-2]
        if word.endswith("oes")
        else word[:-1]
        if word.endswith("s") and not word.endswith("ss")
        else word
        for word in words
        if word not in STOP
    ]


def parse_requirement(text):
    text = expanded(text)
    amount = None
    dimension = None
    unit = None
    remainder = text
    match = QUANTITY.match(text)
    if match:
        remainder = text[match.end() :]
        try:
            qty = number(match[2] or match[1])
            unit_match = UNIT.match(remainder)
            if qty > 0 and unit_match:
                dimension, factor, unit = UNITS[unit_match[1].lower()]
                amount = qty * factor
                remainder = remainder[unit_match.end() :]
            elif (
                qty > 0
                and not re.match(r"\d", remainder)
                and not any(word in CONTAINERS for word in re.findall(r"[a-z]+", remainder))
            ):
                dimension = "count"
                unit = "count"
                amount = qty
        except (ValueError, ZeroDivisionError, ArithmeticError):
            pass
    # More numeric quantities indicate package notation/compound amounts: review manually.
    if re.search(r"\d", remainder):
        amount = dimension = unit = None
    clean = remainder.split(",")[0].split("(")[0]
    search = " ".join(terms(clean))[:100]
    return {"term": search or text[:100], "amount": amount, "dimension": dimension, "unit": unit}


def package_size(size):
    text = expanded(size).strip()
    multiplier = Decimal(1)
    pack = re.match(r"^(\d+)\s*[x×]\s*", text)
    if pack:
        multiplier = Decimal(pack[1])
        text = text[pack.end() :]
    match = QUANTITY.match(text)
    if not match or match[2]:
        return None
    rest = text[match.end() :]
    unit_match = UNIT.fullmatch(rest)
    if not unit_match:
        return None
    try:
        qty = number(match[1]) * multiplier
        if not Decimal(0) < qty <= Decimal("100000"):
            return None
        dimension, factor, base = UNITS[unit_match[1].lower()]
        return {"amount": qty * factor, "dimension": dimension, "unit": base}
    except (ValueError, ArithmeticError):
        return None


def suitable(term, description):
    needed = set(terms(term))
    actual = set(terms(description))
    if not needed or not needed.issubset(actual):
        return False
    unrequested_forms = {
        "soup",
        "broth",
        "stock",
        "sauce",
        "dip",
        "seasoning",
        "breaded",
        "cooked",
        "rotisserie",
        "chocolate",
        "vanilla",
        "strawberry",
        "caramel",
        "flavored",
        "cracker",
        "noodle",
        "dressing",
        "gravy",
    }
    if (actual & unrequested_forms) - needed:
        return False
    # Search engines return related foods; do not silently substitute dietary variants.
    for attribute in [
        "dairy free",
        "lactose free",
        "fat free",
        "sugar free",
        "gluten free",
        "plant based",
    ]:
        if attribute in description.lower().replace(
            "-", " "
        ) and attribute not in term.lower().replace("-", " "):
            return False
    for attribute in [
        "alternative",
        "substitute",
        "powder",
        "condensed",
        "evaporated",
        "sweetened",
    ]:
        if attribute in actual and attribute not in needed:
            return False
    if {"milk", "cream", "butter"} & needed:
        for source in {
            "almond",
            "coconut",
            "oat",
            "soy",
            "cashew",
            "peanut",
            "sunflower",
            "sesame",
            "apple",
            "pumpkin",
        }:
            if source in actual and source not in needed:
                return False
    if "butter" in needed and "chicken" in actual and "chicken" not in needed:
        return False
    # Frozen versus fresh is a material choice, even though it is not a search keyword.
    if "frozen" in term.lower() and "frozen" not in description.lower():
        return False
    return True


def rank_products(requirement, products, preferred_id=None):
    result = []
    for product in products:
        if (
            not isinstance(product, dict)
            or not isinstance(product.get("productId"), str)
            or not product["productId"]
        ):
            continue
        description = product.get("description", "")
        if not isinstance(description, str):
            continue
        if not suitable(requirement["term"], description):
            continue
        items = product.get("items")
        if not isinstance(items, list):
            continue
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            size = item.get("size") or "Unknown size"
            if not isinstance(size, str):
                size = "Unknown size"
            package = package_size(size)
            inventory = item.get("inventory")
            stock = (
                inventory.get("stockLevel", "UNKNOWN") if isinstance(inventory, dict) else "UNKNOWN"
            )
            if not isinstance(stock, str):
                stock = "UNKNOWN"
            selectable = stock not in {"TEMPORARILY_OUT_OF_STOCK", "OUT_OF_STOCK"}
            price_data = item.get("price")
            price_data = price_data if isinstance(price_data, dict) else {}
            observed = [price_data.get(key) for key in ("promo", "regular")]
            valid_prices = [
                Decimal(str(value))
                for value in observed
                if type(value) in (int, float) and math.isfinite(value) and value > 0
            ]
            price = min(valid_prices) if valid_prices else None
            compatible = bool(
                package
                and requirement["amount"]
                and package["dimension"] == requirement["dimension"]
                and item.get("soldBy", "UNIT") == "UNIT"
            )
            count = (
                max(1, math.ceil(requirement["amount"] / package["amount"])) if compatible else None
            )
            remaining = package["amount"] * count - requirement["amount"] if compatible else None
            result.append(
                {
                    "candidate_id": str(product.get("productId")) + ":" + str(index),
                    "product_id": str(product.get("productId")),
                    "description": description[:240],
                    "brand": str(product.get("brand", ""))[:100],
                    "size": size[:100],
                    "price": float(price) if price is not None else None,
                    "stock": stock,
                    "selectable": selectable,
                    "packages": count,
                    "remaining": float(remaining) if remaining is not None else None,
                    "unit": package["unit"] if package else None,
                    "quantity_review": not compatible,
                    "package_amount": float(package["amount"]) if compatible else None,
                    "estimated_total": float(price * count)
                    if price is not None and count is not None
                    else None,
                    "preferred": str(product.get("productId")) == preferred_id,
                }
            )

    def score(c):
        return (
            not c["selectable"],
            not c["preferred"],
            c["quantity_review"],
            c["estimated_total"] is None,
            c["estimated_total"] or 0,
            c["remaining"] or 0,
            c["description"],
        )

    result.sort(key=score)
    return result[:12]
