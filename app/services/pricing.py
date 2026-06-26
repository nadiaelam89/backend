from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas.orders import OrderItemRequest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STANDARD_PRICES: dict[int, int] = {
    1: 199,
    2: 279,
    3: 349,
}

UPSELL_PRICE: int = 99

VALID_PRODUCTS: frozenset[str] = frozenset(
    {"sleep_gummies", "ashwagandha_tea", "focus_coffee"}
)

PRODUCT_NAMES_AR: dict[str, str] = {
    "sleep_gummies": "علكة النوم بالميلاتونين ضد الأرق",
    "ashwagandha_tea": "شاي الأشواجندا ضد التوتر",
    "focus_coffee": "قهوة التركيز بالإل-ثيانين ضد الخمول",
}

PRODUCT_SLUGS: dict[str, str] = {
    "sleep_gummies": "sleep-melatonin-gummies",
    "ashwagandha_tea": "ashwagandha-tea",
    "focus_coffee": "l-theanine-focus-coffee",
}

# Upsell mapping: primary product → upsell product
UPSELL_MAP: dict[str, str] = {
    "sleep_gummies": "ashwagandha_tea",
    "ashwagandha_tea": "sleep_gummies",
    "focus_coffee": "ashwagandha_tea",
}


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def validate_item_price(product_id: str, offer_quantity: int, claimed_price: int) -> bool:
    """Return True if the claimed price matches the server-side standard price table."""
    if product_id not in VALID_PRODUCTS:
        return False
    expected = STANDARD_PRICES.get(offer_quantity)
    if expected is None:
        return False
    return claimed_price == expected


def validate_upsell_price(price: int) -> bool:
    """Return True if the claimed upsell price equals the fixed upsell price."""
    return price == UPSELL_PRICE


def calculate_total(items: list[OrderItemRequest]) -> int:  # type: ignore[type-arg]
    """Sum all item prices. Prices have already been validated server-side."""
    return sum(item.price_sar for item in items)


def get_eligible_upsell(product_ids: list[str]) -> str | None:
    """Return the upsell product_id to offer, or None if no upsell applies."""
    unique = set(product_ids)
    if unique == VALID_PRODUCTS:
        # All 3 products already in cart – skip upsell
        return None
    # Use the last (or first) product to determine upsell
    for pid in reversed(product_ids):
        candidate = UPSELL_MAP.get(pid)
        if candidate and candidate not in unique:
            return candidate
    return None
