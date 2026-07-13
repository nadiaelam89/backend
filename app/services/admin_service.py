from __future__ import annotations

from datetime import datetime, time, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import AnalyticsEvent, Order, OrderItem, SiteEvent
from app.schemas.admin import (
    AdminMetricsResponse,
    AdminOrderDetailResponse,
    AdminOrderItem,
    AdminOrderListItem,
    AdminOrdersListResponse,
)


def _parse_range(date_from: datetime | None, date_to: datetime | None) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    end = date_to or now
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    start = date_from or datetime.combine(end.date(), time.min, tzinfo=timezone.utc)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if start > end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date_from must be before date_to",
        )
    return start, end


async def _count_valid_events(
    db: AsyncSession,
    event_name: str,
    start: datetime,
    end: datetime,
) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(SiteEvent)
        .where(
            SiteEvent.event_name == event_name,
            SiteEvent.is_valid_traffic.is_(True),
            SiteEvent.created_at >= start,
            SiteEvent.created_at <= end,
        )
    )
    return int(result.scalar_one())


async def _count_unique_sessions(
    db: AsyncSession,
    start: datetime,
    end: datetime,
) -> int:
    result = await db.execute(
        select(func.count(func.distinct(SiteEvent.session_id)))
        .select_from(SiteEvent)
        .where(
            SiteEvent.event_name == "PageView",
            SiteEvent.is_valid_traffic.is_(True),
            SiteEvent.created_at >= start,
            SiteEvent.created_at <= end,
        )
    )
    return int(result.scalar_one())


async def purge_all_data(db: AsyncSession) -> dict[str, int]:
    """Delete all orders and tracking events. Irreversible."""
    deleted: dict[str, int] = {}
    for label, stmt in [
        ("analytics_events", delete(AnalyticsEvent)),
        ("order_items", delete(OrderItem)),
        ("site_events", delete(SiteEvent)),
        ("orders", delete(Order)),
    ]:
        result = await db.execute(stmt)
        deleted[label] = int(result.rowcount or 0)
    await db.commit()
    return deleted


async def get_admin_metrics(
    db: AsyncSession,
    date_from: datetime | None,
    date_to: datetime | None,
) -> AdminMetricsResponse:
    start, end = _parse_range(date_from, date_to)

    page_views = await _count_valid_events(db, "PageView", start, end)
    product_views = await _count_valid_events(db, "ViewContent", start, end)
    add_to_carts = await _count_valid_events(db, "AddToCart", start, end)
    initiate_checkouts = await _count_valid_events(db, "InitiateCheckout", start, end)
    unique_sessions = await _count_unique_sessions(db, start, end)

    blocked_result = await db.execute(
        select(func.count())
        .select_from(SiteEvent)
        .where(
            SiteEvent.is_valid_traffic.is_(False),
            SiteEvent.created_at >= start,
            SiteEvent.created_at <= end,
        )
    )
    blocked_events = int(blocked_result.scalar_one())

    valid_result = await db.execute(
        select(func.count())
        .select_from(SiteEvent)
        .where(
            SiteEvent.is_valid_traffic.is_(True),
            SiteEvent.created_at >= start,
            SiteEvent.created_at <= end,
        )
    )
    valid_events = int(valid_result.scalar_one())

    orders_result = await db.execute(
        select(func.count(), func.coalesce(func.sum(Order.total_sar), 0))
        .select_from(Order)
        .where(Order.created_at >= start, Order.created_at <= end)
    )
    orders_count, revenue = orders_result.one()
    orders_count = int(orders_count)
    revenue_sar = int(revenue or 0)

    upsells_result = await db.execute(
        select(func.count())
        .select_from(OrderItem)
        .join(Order, OrderItem.order_id == Order.id)
        .where(
            OrderItem.added_from == "upsell",
            Order.created_at >= start,
            Order.created_at <= end,
        )
    )
    upsells = int(upsells_result.scalar_one())

    conversion_rate = round((orders_count / unique_sessions) * 100, 2) if unique_sessions else 0.0
    checkout_conversion_rate = (
        round((orders_count / initiate_checkouts) * 100, 2) if initiate_checkouts else 0.0
    )
    average_order_value = round(revenue_sar / orders_count, 2) if orders_count else 0.0

    return AdminMetricsResponse(
        date_from=start,
        date_to=end,
        page_views=page_views,
        product_views=product_views,
        add_to_carts=add_to_carts,
        initiate_checkouts=initiate_checkouts,
        orders=orders_count,
        upsells=upsells,
        revenue_sar=revenue_sar,
        average_order_value_sar=average_order_value,
        conversion_rate=conversion_rate,
        checkout_conversion_rate=checkout_conversion_rate,
        unique_sessions=unique_sessions,
        blocked_events=blocked_events,
        valid_events=valid_events,
    )


async def list_admin_orders(
    db: AsyncSession,
    page: int,
    page_size: int,
    status_filter: str | None,
    search: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> AdminOrdersListResponse:
    start, end = _parse_range(date_from, date_to)
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)

    filters = [Order.created_at >= start, Order.created_at <= end]
    if status_filter:
        filters.append(Order.status == status_filter)
    if search:
        like = f"%{search.strip()}%"
        filters.append(
            or_(
                Order.order_number.ilike(like),
                Order.customer_name.ilike(like),
                Order.phone_local.ilike(like),
            )
        )

    total_result = await db.execute(select(func.count()).select_from(Order).where(*filters))
    total = int(total_result.scalar_one())

    result = await db.execute(
        select(Order)
        .options(selectinload(Order.items))
        .where(*filters)
        .order_by(Order.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    orders = result.scalars().all()

    items: list[AdminOrderListItem] = []
    for order in orders:
        utm_source = None
        if isinstance(order.utm, dict):
            utm_source = order.utm.get("utm_source")
        items.append(
            AdminOrderListItem(
                order_id=order.order_number,
                status=order.status,
                customer_name=order.customer_name,
                phone_local=order.phone_local,
                total_sar=order.total_sar,
                item_count=len(order.items),
                product_names=[item.name_ar for item in order.items],
                client_country=order.client_country,
                utm_source=utm_source,
                created_at=order.created_at,
            )
        )

    return AdminOrdersListResponse(
        total=total,
        page=page,
        page_size=page_size,
        orders=items,
    )


async def get_admin_order_detail(db: AsyncSession, order_id: str) -> AdminOrderDetailResponse:
    result = await db.execute(
        select(Order)
        .options(selectinload(Order.items))
        .where(Order.order_number == order_id)
    )
    order = result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    return AdminOrderDetailResponse(
        order_id=order.order_number,
        status=order.status,
        customer_name=order.customer_name,
        phone_local=order.phone_local,
        phone_e164=order.phone_e164,
        currency=order.currency,
        subtotal_sar=order.subtotal_sar,
        delivery_fee_sar=order.delivery_fee_sar,
        total_sar=order.total_sar,
        source_url=order.source_url,
        utm=order.utm,
        client_ip=order.client_ip,
        client_country=order.client_country,
        client_user_agent=order.client_user_agent,
        sheet_sent_at=order.sheet_sent_at,
        created_at=order.created_at,
        updated_at=order.updated_at,
        items=[
            AdminOrderItem(
                product_id=item.product_id,
                name_ar=item.name_ar,
                slug=item.slug,
                offer_id=item.offer_id,
                offer_quantity=item.offer_quantity,
                price_sar=item.price_sar,
                added_from=item.added_from,
                unit_context=item.unit_context,
            )
            for item in order.items
        ],
    )
