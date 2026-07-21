from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.config import settings

if TYPE_CHECKING:
    from app.schemas.orders import OrderItemRequest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STANDARD_PRICES: dict[int, int] = {
    1: 199,
    2: 349,
    3: 449,
    4: 499,
}

UPSELL_PRICE: int = 149

PaymentMethod = str  # cod (legacy orders may have other values in DB)

VALID_PRODUCTS: frozenset[str] = frozenset(
    {"magnesium_gummies", "saffron_gummies", "mushroom_coffee", "probiotic_gummies"}
)

# Legacy product keys accepted from older storefront / API clients.
LEGACY_PRODUCT_IDS: dict[str, str] = {
    "sleep_gummies": "magnesium_gummies",
    "focus_coffee": "mushroom_coffee",
}

ACCEPTED_PRODUCT_IDS: frozenset[str] = VALID_PRODUCTS | frozenset(LEGACY_PRODUCT_IDS.keys())

PRODUCT_NAMES_AR: dict[str, str] = {
    "magnesium_gummies": "علكة المغنيسيوم جلايسينات 400 ملغ",
    "saffron_gummies": "علكة الزعفران مع المغنيسيوم",
    "mushroom_coffee": "قهوة الفطر العضوية الفورية",
    "probiotic_gummies": "علكة البروبيوتك والبريبيوتك",
}

PRODUCT_SLUGS: dict[str, str] = {
    "magnesium_gummies": "magnesium-glycinate-gummies",
    "saffron_gummies": "saffron-magnesium-gummies",
    "mushroom_coffee": "organic-mushroom-coffee",
    "probiotic_gummies": "probiotic-prebiotic-gummies",
}

PRODUCT_SKUS: dict[str, str] = {
    "magnesium_gummies": "SKU-MG-GUM-400",
    "saffron_gummies": "SKU-SAF-MG-GUM",
    "mushroom_coffee": "SKU-MSK-COF-30",
    "probiotic_gummies": "SKU-PRO-PRE-GUM",
}

# Upsell mapping: primary product → upsell product
UPSELL_MAP: dict[str, str] = {
    "magnesium_gummies": "saffron_gummies",
    "saffron_gummies": "magnesium_gummies",
    "mushroom_coffee": "saffron_gummies",
    "probiotic_gummies": "magnesium_gummies",
}

# Bundle composition mirrors frontend product crossSellIds (canonical ids).
CROSS_SELL_IDS: dict[str, list[str]] = {
    "magnesium_gummies": ["saffron_gummies", "mushroom_coffee", "probiotic_gummies"],
    "saffron_gummies": ["magnesium_gummies", "mushroom_coffee", "probiotic_gummies"],
    "mushroom_coffee": ["saffron_gummies", "magnesium_gummies", "probiotic_gummies"],
    "probiotic_gummies": ["magnesium_gummies", "saffron_gummies", "mushroom_coffee"],
}


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _resolve_offer_quantity(offer_id: str, offer_quantity: int) -> int:
    """Bundle cart lines use offer_id suffixes; quantity must match the price tier."""
    if offer_id.endswith("_bundle_3"):
        return 4
    if offer_id.endswith("_bundle_2"):
        return 3
    if offer_id.endswith("_bundle_1"):
        return 2
    if offer_id.endswith("_4"):
        return 4
    if offer_id.endswith("_3"):
        return 3
    if offer_id.endswith("_2"):
        return 2
    if offer_id.endswith("_1"):
        return 1
    return offer_quantity


def canonical_product_id(product_id: str) -> str:
    """Normalize legacy storefront product keys to current catalog ids."""
    return LEGACY_PRODUCT_IDS.get(product_id, product_id)


def resolve_bundle_product_ids(product_id: str, offer_id: str) -> list[str]:
    """Expand bundle offer lines into the distinct products the customer receives."""
    primary = canonical_product_id(product_id)
    cross_sells = CROSS_SELL_IDS.get(primary, [])

    if offer_id.endswith("_bundle_3") and len(cross_sells) >= 3:
        return [primary, cross_sells[0], cross_sells[1], cross_sells[2]]
    if offer_id.endswith("_bundle_2") and len(cross_sells) >= 2:
        return [primary, cross_sells[0], cross_sells[1]]
    if offer_id.endswith("_bundle_1") and len(cross_sells) >= 1:
        return [primary, cross_sells[0]]
    return [primary]


def validate_item_price(
    product_id: str,
    offer_quantity: int,
    claimed_price: int,
    offer_id: str = "",
) -> bool:
    """Return True if the claimed price matches the server-side standard price table."""
    product_id = canonical_product_id(product_id)
    if product_id not in VALID_PRODUCTS:
        return False
    quantity = _resolve_offer_quantity(offer_id, offer_quantity)
    expected = STANDARD_PRICES.get(quantity)
    if expected is None:
        return False
    return claimed_price == expected


def validate_upsell_price(price: int) -> bool:
    """Return True if the claimed upsell price equals the fixed upsell price."""
    return price == UPSELL_PRICE


def calculate_subtotal(items: list[OrderItemRequest]) -> int:  # type: ignore[type-arg]
    """Sum all item prices. Prices have already been validated server-side."""
    return sum(item.price_sar for item in items)


def calculate_cod_fee(payment_method: str) -> int:
    return settings.COD_FEE_SAR if payment_method == "cod" else 0


def calculate_total(items: list[OrderItemRequest], payment_method: str = "") -> int:  # type: ignore[type-arg]
    """Subtotal plus COD fee when payment_method is cod."""
    return calculate_subtotal(items) + calculate_cod_fee(payment_method)


CATALOG_PRODUCT_ORDER: list[str] = [
    "magnesium_gummies",
    "saffron_gummies",
    "mushroom_coffee",
    "probiotic_gummies",
]


def get_eligible_upsells(product_ids: list[str]) -> list[str]:
    """Return products not already in the order (1 ordered → 2 upsells, 2 ordered → 1)."""
    unique = {canonical_product_id(pid) for pid in product_ids}
    return [pid for pid in CATALOG_PRODUCT_ORDER if pid not in unique]


def get_eligible_upsell(product_ids: list[str]) -> str | None:
    """Return the first eligible upsell product, if any."""
    upsells = get_eligible_upsells(product_ids)
    return upsells[0] if upsells else None
