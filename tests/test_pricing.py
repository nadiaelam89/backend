"""Tests for server-side price validation and total calculation."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.pricing import (
    UPSELL_PRICE,
    VALID_PRODUCTS,
    calculate_total,
    canonical_product_id,
    get_eligible_upsell,
    validate_item_price,
    validate_upsell_price,
)


# ---------------------------------------------------------------------------
# validate_item_price
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "product_id,qty,price,expected",
    [
        ("magnesium_gummies", 1, 199, True),
        ("magnesium_gummies", 2, 349, True),
        ("magnesium_gummies", 3, 449, True),
        ("saffron_gummies", 1, 199, True),
        ("saffron_gummies", 2, 349, True),
        ("saffron_gummies", 3, 449, True),
        ("mushroom_coffee", 1, 199, True),
        ("mushroom_coffee", 2, 349, True),
        ("mushroom_coffee", 3, 449, True),
    ],
)
def test_valid_item_prices(product_id: str, qty: int, price: int, expected: bool) -> None:
    assert validate_item_price(product_id, qty, price) is expected


@pytest.mark.parametrize(
    "product_id,qty,claimed_price,description",
    [
        ("magnesium_gummies", 1, 99, "price too low"),
        ("magnesium_gummies", 1, 198, "price off by one (low)"),
        ("magnesium_gummies", 1, 200, "price off by one (high)"),
        ("magnesium_gummies", 2, 199, "qty 2 price is 349, not 199"),
        ("magnesium_gummies", 3, 349, "qty 3 price is 449, not 349"),
        ("magnesium_gummies", 3, 0, "zero price"),
        ("magnesium_gummies", 3, -449, "negative price"),
        ("unknown_product", 1, 199, "unknown product"),
        ("magnesium_gummies", 4, 199, "quantity 4 is not in price table"),
        ("magnesium_gummies", 0, 199, "quantity 0 is invalid"),
    ],
)
def test_tampered_item_prices(
    product_id: str, qty: int, claimed_price: int, description: str
) -> None:
    result = validate_item_price(product_id, qty, claimed_price)
    assert result is False, f"Expected rejection for: {description}"


@pytest.mark.parametrize(
    "product_id,offer_id,qty,price",
    [
        ("magnesium_gummies", "magnesium_gummies_bundle_1", 1, 349),
        ("magnesium_gummies", "magnesium_gummies_bundle_2", 1, 449),
        ("saffron_gummies", "saffron_gummies_bundle_1", 1, 349),
    ],
)
def test_bundle_offer_ids_resolve_quantity(
    product_id: str, offer_id: str, qty: int, price: int
) -> None:
    assert validate_item_price(product_id, qty, price, offer_id) is True


def test_bundle_offer_id_with_wrong_price_rejected() -> None:
    assert (
        validate_item_price("magnesium_gummies", 1, 349, "magnesium_gummies_bundle_1")
        is False
    )


def test_legacy_product_ids_normalize_for_pricing() -> None:
    assert validate_item_price("sleep_gummies", 1, 199) is True
    assert validate_item_price("focus_coffee", 3, 449) is True
    assert canonical_product_id("sleep_gummies") == "magnesium_gummies"


# ---------------------------------------------------------------------------
# validate_upsell_price
# ---------------------------------------------------------------------------


def test_valid_upsell_price() -> None:
    assert validate_upsell_price(UPSELL_PRICE) is True


@pytest.mark.parametrize("price", [0, 1, 98, 100, 199, 349, -99])
def test_invalid_upsell_prices(price: int) -> None:
    assert validate_upsell_price(price) is False


# ---------------------------------------------------------------------------
# calculate_total
# ---------------------------------------------------------------------------


def _make_item(price: int) -> MagicMock:
    item = MagicMock()
    item.price_sar = price
    return item


def test_calculate_total_single_item() -> None:
    items = [_make_item(349)]
    assert calculate_total(items) == 349


def test_calculate_total_multiple_items() -> None:
    items = [_make_item(349), _make_item(149)]
    assert calculate_total(items) == 498


def test_calculate_total_empty() -> None:
    assert calculate_total([]) == 0


# ---------------------------------------------------------------------------
# get_eligible_upsell
# ---------------------------------------------------------------------------


def test_upsell_magnesium_gets_saffron() -> None:
    result = get_eligible_upsell(["magnesium_gummies"])
    assert result == "saffron_gummies"


def test_upsell_saffron_gets_magnesium() -> None:
    result = get_eligible_upsell(["saffron_gummies"])
    assert result == "magnesium_gummies"


def test_upsell_mushroom_coffee_gets_saffron() -> None:
    result = get_eligible_upsell(["mushroom_coffee"])
    assert result == "saffron_gummies"


def test_upsell_all_three_products_returns_none() -> None:
    result = get_eligible_upsell(
        ["magnesium_gummies", "saffron_gummies", "mushroom_coffee"]
    )
    assert result is None


def test_upsell_already_has_target_skips() -> None:
    result = get_eligible_upsell(["magnesium_gummies", "saffron_gummies"])
    assert result is None


def test_valid_products_set() -> None:
    assert "magnesium_gummies" in VALID_PRODUCTS
    assert "saffron_gummies" in VALID_PRODUCTS
    assert "mushroom_coffee" in VALID_PRODUCTS
    assert len(VALID_PRODUCTS) == 3
