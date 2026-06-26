from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.models import AnalyticsEvent, Order, OrderItem
from app.schemas.orders import CreateOrderRequest, UpsellRequest
from app.services.hashing import sha256_lower
from app.services.phone import normalize_saudi_phone
from app.services.pricing import (
    PRODUCT_NAMES_AR,
    PRODUCT_SLUGS,
    UPSELL_PRICE,
    calculate_total,
    get_eligible_upsell,
    validate_item_price,
    validate_upsell_price,
)
from app.services.sheets_service import send_order_to_sheets

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Order number generation
# ---------------------------------------------------------------------------


async def _generate_order_number(db: AsyncSession) -> str:
    """Generate SH-YYYYMMDD-NNNNNN order number using today's date and daily count."""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"SH-{today}-"

    count_result = await db.execute(
        select(func.count()).where(Order.order_number.like(f"{prefix}%"))
    )
    count: int = count_result.scalar_one()
    sequence = count + 1
    return f"{prefix}{sequence:06d}"


# ---------------------------------------------------------------------------
# Create order
# ---------------------------------------------------------------------------


async def create_order(
    db: AsyncSession,
    order_data: CreateOrderRequest,
    client_ip: str | None,
) -> Order:
    """Validate, persist, and asynchronously dispatch side effects for a new order."""

    # 1. Phone validation
    phone_result = normalize_saudi_phone(order_data.phone)
    if not phone_result.is_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid phone number: {phone_result.error}",
        )

    phone_hash = sha256_lower(phone_result.phone_digits)
    masked = "****" + phone_result.phone_local[-4:]
    logger.info("Creating order for customer %s, phone %s", order_data.name, masked)

    # 2. Server-side price validation for every item
    for item in order_data.items:
        if not validate_item_price(item.product_id, item.offer_quantity, item.price_sar):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Price tampered for product '{item.product_id}' "
                    f"qty={item.offer_quantity}: claimed {item.price_sar} SAR"
                ),
            )

    # 3. Compute server-side total
    total = calculate_total(order_data.items)

    # 4. Generate order number
    order_number = await _generate_order_number(db)

    # 5. Persist order
    order = Order(
        id=uuid.uuid4(),
        order_number=order_number,
        status="new",
        customer_name=order_data.name,
        phone_local=phone_result.phone_local,
        phone_e164=phone_result.phone_e164,
        phone_hash_sha256=phone_hash,
        currency=order_data.currency,
        subtotal_sar=total,
        delivery_fee_sar=0,
        total_sar=total,
        source_url=order_data.source_url,
        utm=order_data.utm.model_dump(exclude_none=True) if order_data.utm else None,
        event_id=str(order_data.event_id),
        fbp=order_data.fbp,
        fbc=order_data.fbc,
        ttp=order_data.ttp,
        client_ip=client_ip,
        client_user_agent=order_data.client_user_agent,
    )
    db.add(order)

    # 6. Persist items
    for item in order_data.items:
        db_item = OrderItem(
            id=uuid.uuid4(),
            order_id=order.id,
            product_id=item.product_id,
            slug=item.slug or PRODUCT_SLUGS.get(item.product_id, ""),
            name_ar=PRODUCT_NAMES_AR[item.product_id],
            offer_id=item.offer_id,
            offer_quantity=item.offer_quantity,
            unit_context="standard_offer",
            price_sar=item.price_sar,
            added_from=item.added_from,
        )
        db.add(db_item)

    await db.flush()
    await db.refresh(order, attribute_names=["items"])

    logger.info("Order %s persisted (total %d SAR)", order_number, total)

    # 7. Background side effects: Sheets + CAPI (must not raise)
    await _dispatch_side_effects(db, order, phone_hash)

    return order


# ---------------------------------------------------------------------------
# Upsell
# ---------------------------------------------------------------------------


async def add_upsell(
    db: AsyncSession,
    order_id: str,
    upsell_data: UpsellRequest,
) -> Order:
    """Add a single upsell item to an existing order."""

    # Validate upsell price server-side
    if not validate_upsell_price(upsell_data.price_sar):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid upsell price: {upsell_data.price_sar} SAR (expected {UPSELL_PRICE})",
        )

    order = await _get_order_or_404(db, order_id)

    if order.status not in ("new",):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Order {order_id} is not eligible for upsell (status={order.status})",
        )

    # Check this product isn't already in the order
    existing_pids = {item.product_id for item in order.items}
    if upsell_data.product_id in existing_pids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Product '{upsell_data.product_id}' is already in order {order_id}",
        )

    upsell_item = OrderItem(
        id=uuid.uuid4(),
        order_id=order.id,
        product_id=upsell_data.product_id,
        slug=PRODUCT_SLUGS.get(upsell_data.product_id, ""),
        name_ar=PRODUCT_NAMES_AR[upsell_data.product_id],
        offer_id=f"{upsell_data.product_id}_upsell",
        offer_quantity=1,
        unit_context="post_order_upsell",
        price_sar=upsell_data.price_sar,
        added_from="upsell",
    )
    db.add(upsell_item)

    order.total_sar = order.total_sar + upsell_data.price_sar
    order.subtotal_sar = order.subtotal_sar + upsell_data.price_sar
    order.status = "upsell_added"

    await db.flush()
    await db.refresh(order, attribute_names=["items"])

    logger.info(
        "Upsell %s added to order %s → new total %d SAR",
        upsell_data.product_id,
        order.order_number,
        order.total_sar,
    )
    return order


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


async def get_order_summary(db: AsyncSession, order_id: str) -> dict:
    """Return a safe order summary (no PII phone number)."""
    order = await _get_order_or_404(db, order_id)
    product_names = [item.name_ar for item in order.items]
    return {
        "ok": True,
        "order_id": order.order_number,
        "status": order.status,
        "total_sar": order.total_sar,
        "product_names": product_names,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_order_or_404(db: AsyncSession, order_id: str) -> Order:
    result = await db.execute(
        select(Order)
        .options(selectinload(Order.items))
        .where(Order.order_number == order_id)
    )
    order = result.scalar_one_or_none()
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order '{order_id}' not found",
        )
    return order


async def _dispatch_side_effects(db: AsyncSession, order: Order, phone_hash: str) -> None:
    """Fire-and-forget: Sheets + Meta/TikTok/Snap CAPI.

    All errors are caught internally. The order is already committed.
    """
    # Google Sheets
    try:
        await send_order_to_sheets(order)
        order.sheet_sent_at = datetime.now(timezone.utc)
    except Exception as exc:  # noqa: BLE001
        logger.error("Sheets dispatch error for %s: %s", order.order_number, exc)

    # Meta CAPI
    if settings.META_PIXEL_ID and settings.META_ACCESS_TOKEN:
        try:
            from app.services.capi.meta import send_purchase_event as meta_send

            result = await meta_send(
                order=order,
                phone_hash=phone_hash,
                access_token=settings.META_ACCESS_TOKEN,
                pixel_id=settings.META_PIXEL_ID,
            )
            await _save_analytics_event(db, order, "meta", "Purchase", result)
        except Exception as exc:  # noqa: BLE001
            logger.error("Meta CAPI dispatch error for %s: %s", order.order_number, exc)

    # TikTok CAPI
    if settings.TIKTOK_PIXEL_CODE and settings.TIKTOK_ACCESS_TOKEN:
        try:
            from app.services.capi.tiktok import send_purchase_event as tiktok_send

            result = await tiktok_send(
                order=order,
                phone_hash=phone_hash,
                pixel_code=settings.TIKTOK_PIXEL_CODE,
                access_token=settings.TIKTOK_ACCESS_TOKEN,
            )
            await _save_analytics_event(db, order, "tiktok", "Purchase", result)
        except Exception as exc:  # noqa: BLE001
            logger.error("TikTok CAPI dispatch error for %s: %s", order.order_number, exc)

    # Snap CAPI
    if settings.SNAP_PIXEL_ID and settings.SNAP_ACCESS_TOKEN:
        try:
            from app.services.capi.snap import send_purchase_event as snap_send

            result = await snap_send(
                order=order,
                phone_hash=phone_hash,
                pixel_id=settings.SNAP_PIXEL_ID,
                access_token=settings.SNAP_ACCESS_TOKEN,
            )
            await _save_analytics_event(db, order, "snap", "Purchase", result)
        except Exception as exc:  # noqa: BLE001
            logger.error("Snap CAPI dispatch error for %s: %s", order.order_number, exc)


async def _save_analytics_event(
    db: AsyncSession,
    order: Order,
    platform: str,
    event_name: str,
    result: dict,
) -> None:
    now = datetime.now(timezone.utc)
    event = AnalyticsEvent(
        id=uuid.uuid4(),
        order_id=order.id,
        event_id=order.event_id,
        platform=platform,
        event_name=event_name,
        payload=result.get("body") or {},
        response_status=result.get("status"),
        response_body=result.get("body"),
        sent_at=now,
    )
    db.add(event)
    try:
        await db.flush()
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to save analytics event (%s) for %s: %s", platform, order.order_number, exc)
