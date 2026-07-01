from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Order, OrderItem
from app.schemas.orders import CreateOrderRequest, OrderItemRequest
from app.schemas.payments import CheckoutPaymentRequest
from app.services.fraud import assert_order_ip_allowed
from app.services.hashing import sha256_lower
from app.services.phone import normalize_saudi_phone
from app.services.pricing import (
    PRODUCT_NAMES_AR,
    PRODUCT_SLUGS,
    calculate_cod_fee,
    calculate_subtotal,
    canonical_product_id,
    resolve_bundle_product_ids,
    validate_item_price,
)


async def _generate_order_number(db: AsyncSession) -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"sukoon-{today}-"
    count_result = await db.execute(
        select(func.count()).where(Order.order_number.like(f"{prefix}%"))
    )
    count: int = count_result.scalar_one()
    return f"{prefix}{count + 1:06d}"


def _validate_items(items: list[OrderItemRequest]) -> None:
    for item in items:
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


def _validate_address(city: str, address: str) -> None:
    if len(city.strip()) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="City is required (min 2 characters)",
        )
    if len(address.strip()) < 5:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Address is required (min 5 characters)",
        )


async def create_checkout_order(
    db: AsyncSession,
    *,
    name: str,
    phone: str,
    city: str,
    address: str,
    email: str | None,
    payment_method: str,
    payment_status: str,
    items: list[OrderItemRequest],
    currency: str,
    source_url: str | None,
    utm: dict | None,
    event_id: str,
    fbp: str | None,
    fbc: str | None,
    ttp: str | None,
    client_ip: str | None,
    client_country: str | None,
    client_user_agent: str | None,
    order_status: str = "new",
) -> Order:
    phone_result = normalize_saudi_phone(phone)
    if not phone_result.is_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid phone number: {phone_result.error}",
        )

    _validate_items(items)
    _validate_address(city, address)

    order_data = CreateOrderRequest(
        name=name,
        phone=phone,
        city=city,
        address=address,
        email=email,
        payment_method=payment_method,  # type: ignore[arg-type]
        items=items,
        currency="SAR",
        source_url=source_url,
        utm=None,
        event_id=uuid.UUID(event_id),
        fbp=fbp,
        fbc=fbc,
        ttp=ttp,
        client_user_agent=client_user_agent,
    )
    await assert_order_ip_allowed(order_data, phone_result, client_ip, client_country)

    subtotal = calculate_subtotal(items)
    cod_fee = calculate_cod_fee(payment_method)
    total = subtotal + cod_fee
    order_number = await _generate_order_number(db)
    phone_hash = sha256_lower(phone_result.phone_digits)

    order = Order(
        id=uuid.uuid4(),
        order_number=order_number,
        status=order_status,
        customer_name=name.strip(),
        phone_local=phone_result.phone_local,
        phone_e164=phone_result.phone_e164,
        phone_hash_sha256=phone_hash,
        currency=currency,
        subtotal_sar=subtotal,
        delivery_fee_sar=0,
        cod_fee_sar=cod_fee,
        total_sar=total,
        payment_method=payment_method,
        payment_status=payment_status,
        city=city.strip(),
        address=address.strip(),
        customer_email=email,
        source_url=source_url,
        utm=utm,
        event_id=event_id,
        fbp=fbp,
        fbc=fbc,
        ttp=ttp,
        client_ip=client_ip,
        client_country=client_country,
        client_user_agent=client_user_agent,
    )
    db.add(order)

    for item in items:
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
    return order


async def create_checkout_order_from_payment_request(
    db: AsyncSession,
    data: CheckoutPaymentRequest,
    *,
    payment_method: str,
    payment_status: str,
    client_ip: str | None,
    client_country: str | None,
) -> Order:
    utm = data.utm.model_dump(exclude_none=True) if data.utm else None
    return await create_checkout_order(
        db,
        name=data.name,
        phone=data.phone,
        city=data.city,
        address=data.address,
        email=data.email,
        payment_method=payment_method,
        payment_status=payment_status,
        items=data.items,
        currency=data.currency,
        source_url=data.source_url,
        utm=utm,
        event_id=str(data.event_id),
        fbp=data.fbp,
        fbc=data.fbc,
        ttp=data.ttp,
        client_ip=client_ip,
        client_country=client_country,
        client_user_agent=data.client_user_agent,
    )
