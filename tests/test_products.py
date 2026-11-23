from decimal import Decimal

from household.products import package_size, parse_requirement, rank_products


def product(pid, name, size, price=3.39, stock="HIGH"):
    return {
        "productId": pid,
        "description": name,
        "brand": "Kroger",
        "items": [
            {
                "size": size,
                "price": {"regular": price},
                "inventory": {"stockLevel": stock},
                "soldBy": "UNIT",
            }
        ],
    }


def test_requirement_and_package_units_are_compatible():
    req = parse_requirement("1/2 cup heavy cream")
    assert req["term"] == "heavy cream"
    assert req["amount"] == Decimal("4") and req["dimension"] == "volume"
    assert package_size("1 pt") == {"amount": Decimal("16"), "dimension": "volume", "unit": "fl oz"}
    assert package_size("2 x 16 fl oz")["amount"] == Decimal("32")
    assert package_size("1 lb")["dimension"] == "mass"
    assert parse_requirement("1/4 - 1/2 cup heavy cream")["amount"] == Decimal("4")
    assert parse_requirement("milk")["amount"] is None
    assert parse_requirement("2 15 oz cans tomatoes")["amount"] is None
    assert package_size("6 bottles / 16.9 fl oz") is None


def test_heavy_cream_matching_filters_substitutes_and_ranks_in_stock_packages():
    candidates = rank_products(
        parse_requirement("1/2 cup heavy cream"),
        [
            product("quart", "Heavy Whipping Cream", "1 qt", 5, "TEMPORARILY_OUT_OF_STOCK"),
            product("pint", "Heavy Whipping Cream", "1 pt"),
            product("alternative", "Dairy Free Heavy Whipping Cream Alternative", "16 fl oz"),
            product("fraiche", "Creme Fraiche", "8 oz"),
            product("whipping", "Whipping Cream", "1 pt"),
        ],
    )
    assert [c["product_id"] for c in candidates] == ["pint", "quart"]
    assert candidates[0]["packages"] == 1
    assert candidates[0]["remaining"] == 12
    assert candidates[0]["selectable"] is True
    assert candidates[1]["selectable"] is False


def test_package_count_rounds_up_without_cross_dimension_guessing():
    candidates = rank_products(
        parse_requirement("3 cups heavy cream"), [product("pint", "Heavy Cream", "1 pt")]
    )
    assert candidates[0]["packages"] == 2 and candidates[0]["remaining"] == 8
    unknown = rank_products(
        parse_requirement("2 onions"), [product("onion", "Yellow Onions", "1 lb")]
    )[0]
    assert unknown["packages"] is None and unknown["quantity_review"] is True


def test_preferred_product_and_missing_price():
    candidates = rank_products(
        parse_requirement("1/2 cup heavy cream"),
        [product("pint", "Heavy Cream", "1 pt", None), product("quart", "Heavy Cream", "1 qt", 5)],
        preferred_id="pint",
    )
    assert candidates[0]["product_id"] == "pint" and candidates[0]["preferred"]
    assert candidates[0]["estimated_total"] is None


def test_missing_package_metadata_is_reviewed_and_malformed_entries_are_skipped():
    value = product("unknown", "Heavy Cream", None)
    ranked = rank_products(
        parse_requirement("1/2 cup heavy cream"), [None, {"description": None}, value]
    )
    assert len(ranked) == 1
    assert ranked[0]["quantity_review"] and ranked[0]["size"] == "Unknown size"


def test_dairy_free_and_coconut_milk_are_not_silent_dairy_substitutes():
    values = [
        product("cow", "Whole Milk", "1 gal"),
        product("coconut", "Coconut Milk", "14 oz"),
        product("free", "Dairy-Free Milk Alternative", "16 fl oz"),
    ]
    assert [p["product_id"] for p in rank_products(parse_requirement("2 cups milk"), values)] == [
        "cow"
    ]


def test_prepared_or_flavored_foods_do_not_match_raw_ingredients():
    assert (
        rank_products(
            parse_requirement("1 lb chicken"), [product("soup", "Chicken Noodle Soup", "16 oz")]
        )
        == []
    )
    assert (
        rank_products(
            parse_requirement("1 cup milk"), [product("flavored", "Chocolate Milk", "1 pt")]
        )
        == []
    )
    assert rank_products(
        parse_requirement("1 cup chocolate milk"), [product("flavored", "Chocolate Milk", "1 pt")]
    )


def test_container_counts_are_not_treated_as_individual_food_counts():
    req = parse_requirement("2 packages tortillas")
    assert req["term"] == "tortilla" and req["amount"] is None
    assert rank_products(req, [product("tortilla", "Flour Tortillas", "10 ct")])[0][
        "quantity_review"
    ]


def test_zero_or_null_promo_uses_regular_price():
    for promo in [None, 0]:
        value = product("cream", "Heavy Cream", "1 pt")
        value["items"][0]["price"]["promo"] = promo
        assert rank_products(parse_requirement("1 cup heavy cream"), [value])[0]["price"] == 3.39


def test_butter_does_not_match_nut_butter_or_compound_dishes():
    values = [
        product("dairy", "Salted Butter", "16 oz"),
        product("peanut", "Creamy Peanut Butter", "16 oz"),
        product("dish", "Butter Chicken", "16 oz"),
    ]
    assert [p["product_id"] for p in rank_products(parse_requirement("1 lb butter"), values)] == [
        "dairy"
    ]
    assert rank_products(parse_requirement("1 lb peanut butter"), [values[1]])


def test_abbreviated_cups_are_separated_from_ingredient_name():
    for text in ["1 c chicken broth", "1 c. chicken broth", "1 C chicken broth"]:
        req = parse_requirement(text)
        assert req["term"] == "chicken broth"
        assert req["amount"] == Decimal("8") and req["unit"] == "fl oz"
