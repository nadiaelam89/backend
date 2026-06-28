from __future__ import annotations

import asyncio
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
from app.services.fraud import assert_order_ip_allowed
from app.services.hashing import sha256_lower
from app.services.phone import normalize_saudi_phone
from app.services.pricing import (
    PRODUCT_NAMES_AR,
    PRODUCT_SLUGS,
    UPSELL_PRICE,
    calculate_total,
    canonical_product_id,
    resolve_bundle_product_ids,
    validate_item_price,
    validate_upsell_price,
)
from app.services.sheets_service import (
    send_order_to_sheets,
    send_order_update_to_sheets,
    send_upsell_accepted_to_sheets,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Order number generation
# ---------------------------------------------------------------------------


async def _generate_order_number(db: AsyncSession) -> str:
    """Generate sukoon-YYYYMMDD-NNNNNN order number using today's date and daily count."""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"sukoon-{today}-"

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
    client_country: str | None = None,
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
        if not validate_item_price(
            item.product_id,
            item.offer_quantity,
            item.price_sar,
            item.offer_id,
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Price tampered for product '{item.product_id}' "
                    f"qty={item.offer_quantity}: claimed {item.price_sar} SAR"
                ),
            )

    # 3. Optional IP fraud screening. When enabled, it blocks non-KSA/high-risk
    # requests before persistence unless the phone is explicitly whitelisted.
    await assert_order_ip_allowed(order_data, phone_result, client_ip, client_country)

    # 4. Compute server-side total
    total = calculate_total(order_data.items)

    # 5. Generate order number
    order_number = await _generate_order_number(db)

    # 6. Persist order
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
        client_country=client_country,
        client_user_agent=order_data.client_user_agent,
    )
    db.add(order)

    # 7. Persist items (expand bundles into separate products for fulfillment)
    for item in order_data.items:
        bundle_product_ids = resolve_bundle_product_ids(item.product_id, item.offer_id)

        if len(bundle_product_ids) == 1:
            product_id = bundle_product_ids[0]
            db.add(
                OrderItem(
                    id=uuid.uuid4(),
                    order_id=order.id,
                    product_id=product_id,
                    slug=item.slug or PRODUCT_SLUGS.get(product_id, ""),
                    name_ar=PRODUCT_NAMES_AR[product_id],
                    offer_id=item.offer_id,
                    offer_quantity=item.offer_quantity,
                    unit_context="standard_offer",
                    price_sar=item.price_sar,
                    added_from=item.added_from,
                )
            )
            continue

        for index, product_id in enumerate(bundle_product_ids):
            db.add(
                OrderItem(
                    id=uuid.uuid4(),
                    order_id=order.id,
                    product_id=product_id,
                    slug=PRODUCT_SLUGS.get(product_id, ""),
                    name_ar=PRODUCT_NAMES_AR[product_id],
                    offer_id=item.offer_id,
                    offer_quantity=1,
                    unit_context="bundle_primary" if index == 0 else "bundle_component",
                    price_sar=item.price_sar if index == 0 else 0,
                    added_from=item.added_from,
                )
            )

    await db.flush()
    await db.refresh(order, attribute_names=["items"])

    logger.info("Order %s persisted (total %d SAR)", order_number, total)

    return order


async def run_order_side_effects(order_id: uuid.UUID) -> None:
    """Run Sheets + CAPI after the HTTP response is sent."""
    from app.db.session import AsyncSessionLocal

    for attempt in range(5):
        async with AsyncSessionLocal() as db:
            try:
                result = await db.execute(
                    select(Order)
                    .options(selectinload(Order.items))
                    .where(Order.id == order_id)
                )
                order = result.scalar_one_or_none()
                if order is None:
                    if attempt < 4:
                        await asyncio.sleep(0.25 * (attempt + 1))
                        continue
                    logger.error("Side effects skipped: order id %s not found", order_id)
                    return

                await _dispatch_side_effects(db, order, order.phone_hash_sha256)
                await db.commit()
                return
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Side effects background task failed for %s (attempt %s): %s",
                    order_id,
                    attempt + 1,
                    exc,
                )
                await db.rollback()
                if attempt < 4:
                    await asyncio.sleep(0.25 * (attempt + 1))


async def run_upsell_side_effects(order_id: uuid.UUID, event_id: str) -> None:
    """Sync updated order + upsell line to Google Sheets after upsell is saved."""
    from app.db.session import AsyncSessionLocal

    for attempt in range(5):
        async with AsyncSessionLocal() as db:
            try:
                result = await db.execute(
                    select(Order)
                    .options(selectinload(Order.items))
                    .where(Order.id == order_id)
                )
                order = result.scalar_one_or_none()
                if order is None:
                    if attempt < 4:
                        await asyncio.sleep(0.25 * (attempt + 1))
                        continue
                    logger.error("Upsell side effects skipped: order id %s not found", order_id)
                    return

                update_result = await send_order_update_to_sheets(order)
                upsell_result = await send_upsell_accepted_to_sheets(order, event_id)
                order.sheet_response = {
                    "order_updated": update_result,
                    "upsell_accepted": upsell_result,
                }
                if update_result.get("ok"):
                    order.sheet_sent_at = datetime.now(timezone.utc)
                await db.commit()
                return
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Upsell side effects failed for %s (attempt %s): %s",
                    order_id,
                    attempt + 1,
                    exc,
                )
                await db.rollback()
                if attempt < 4:
                    await asyncio.sleep(0.25 * (attempt + 1))


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

    if order.status not in ("new", "upsell_added"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Order {order_id} is not eligible for upsell (status={order.status})",
        )

    # Check this product isn't already in the order
    existing_pids = {canonical_product_id(item.product_id) for item in order.items}
    upsell_pid = canonical_product_id(upsell_data.product_id)
    if upsell_pid in existing_pids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Product '{upsell_data.product_id}' is already in order {order_id}",
        )

    upsell_item = OrderItem(
        id=uuid.uuid4(),
        order_id=order.id,
        product_id=upsell_pid,
        slug=PRODUCT_SLUGS.get(upsell_pid, ""),
        name_ar=PRODUCT_NAMES_AR[upsell_pid],
        offer_id=f"{upsell_pid}_upsell",
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
    items = [
        {
            "name_ar": item.name_ar,
            "price_sar": item.price_sar,
            "quantity": item.offer_quantity,
        }
        for item in order.items
    ]
    product_names = [item.name_ar for item in order.items]
    return {
        "ok": True,
        "order_id": order.order_number,
        "status": order.status,
        "total_sar": order.total_sar,
        "product_names": product_names,
        "items": items,
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
        sheet_result = await send_order_to_sheets(order)
        order.sheet_response = sheet_result
        if sheet_result.get("ok"):
            order.sheet_sent_at = datetime.now(timezone.utc)
        else:
            logger.error("Sheets push failed for %s: %s", order.order_number, sheet_result)
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
