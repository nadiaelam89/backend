"""Tests for server-side price validation and total calculation."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.pricing import (
    STANDARD_PRICES,
    UPSELL_PRICE,
    VALID_PRODUCTS,
    calculate_total,
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
        ("sleep_gummies", 1, 199, True),
        ("sleep_gummies", 2, 279, True),
        ("sleep_gummies", 3, 349, True),
        ("ashwagandha_tea", 1, 199, True),
        ("ashwagandha_tea", 2, 279, True),
        ("ashwagandha_tea", 3, 349, True),
        ("focus_coffee", 1, 199, True),
        ("focus_coffee", 2, 279, True),
        ("focus_coffee", 3, 349, True),
    ],
)
def test_valid_item_prices(product_id: str, qty: int, price: int, expected: bool) -> None:
    assert validate_item_price(product_id, qty, price) is expected


@pytest.mark.parametrize(
    "product_id,qty,claimed_price,description",
    [
        ("sleep_gummies", 1, 99, "price too low"),
        ("sleep_gummies", 1, 198, "price off by one (low)"),
        ("sleep_gummies", 1, 200, "price off by one (high)"),
        ("sleep_gummies", 2, 199, "qty 2 price is 279, not 199"),
        ("sleep_gummies", 3, 279, "qty 3 price is 349, not 279"),
        ("sleep_gummies", 3, 0, "zero price"),
        ("sleep_gummies", 3, -349, "negative price"),
        ("unknown_product", 1, 199, "unknown product"),
        ("sleep_gummies", 4, 199, "quantity 4 is not in price table"),
        ("sleep_gummies", 0, 199, "quantity 0 is invalid"),
    ],
)
def test_tampered_item_prices(
    product_id: str, qty: int, claimed_price: int, description: str
) -> None:
    result = validate_item_price(product_id, qty, claimed_price)
    assert result is False, f"Expected rejection for: {description}"


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
    items = [_make_item(279), _make_item(99)]
    assert calculate_total(items) == 378


def test_calculate_total_empty() -> None:
    assert calculate_total([]) == 0


# ---------------------------------------------------------------------------
# get_eligible_upsell
# ---------------------------------------------------------------------------


def test_upsell_sleep_gummies_gets_ashwagandha() -> None:
    result = get_eligible_upsell(["sleep_gummies"])
    assert result == "ashwagandha_tea"


def test_upsell_ashwagandha_gets_sleep_gummies() -> None:
    result = get_eligible_upsell(["ashwagandha_tea"])
    assert result == "sleep_gummies"


def test_upsell_focus_coffee_gets_ashwagandha() -> None:
    result = get_eligible_upsell(["focus_coffee"])
    assert result == "ashwagandha_tea"


def test_upsell_all_three_products_returns_none() -> None:
    result = get_eligible_upsell(["sleep_gummies", "ashwagandha_tea", "focus_coffee"])
    assert result is None


def test_upsell_already_has_target_skips() -> None:
    # sleep_gummies would suggest ashwagandha_tea, but it's already in cart
    result = get_eligible_upsell(["sleep_gummies", "ashwagandha_tea"])
    # focus_coffee is the remaining option; no direct mapping applies
    # since neither sleep_gummies → ashwagandha_tea (already present)
    # we expect no upsell or focus_coffee depending on logic
    # The function scans in reverse; sleep_gummies → ashwagandha_tea (already present) → skip
    # ashwagandha_tea → sleep_gummies (already present) → skip → returns None
    assert result is None


def test_valid_products_set() -> None:
    assert "sleep_gummies" in VALID_PRODUCTS
    assert "ashwagandha_tea" in VALID_PRODUCTS
    assert "focus_coffee" in VALID_PRODUCTS
    assert len(VALID_PRODUCTS) == 3
