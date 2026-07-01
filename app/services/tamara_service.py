from __future__ import annotations

import logging

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.schemas.payments import CheckoutPaymentRequest
from app.services.checkout_order import create_checkout_order_from_payment_request
from app.services.phone import normalize_saudi_phone
from app.services.pricing import PRODUCT_NAMES_AR, PRODUCT_SKUS, canonical_product_id

logger = logging.getLogger(__name__)


def _headers() -> dict[str, str]:
    if not settings.TAMARA_API_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tamara is not configured",
        )
    return {
        "Authorization": f"Bearer {settings.TAMARA_API_TOKEN}",
        "Content-Type": "application/json",
    }


def _split_name(full_name: str) -> tuple[str, str]:
    parts = full_name.strip().split()
    if len(parts) == 1:
        return parts[0], parts[0]
    return parts[0], " ".join(parts[1:])


def _tamara_phone(phone: str) -> str:
    result = normalize_saudi_phone(phone)
    if result.is_valid:
        return result.phone_digits[3:]  # 9665xxxxxxxx -> 5xxxxxxxx
    return phone.lstrip("0").replace("+966", "")


async def create_tamara_checkout(
    db: AsyncSession,
    data: CheckoutPaymentRequest,
    client_ip: str | None,
    client_country: str | None,
) -> tuple[str, str, int]:
    order = await create_checkout_order_from_payment_request(
        db,
        data,
        payment_method="tamara",
        payment_status="pending",
        client_ip=client_ip,
        client_country=client_country,
    )

    first_name, last_name = _split_name(data.name)
    phone_number = _tamara_phone(data.phone)
    site = settings.SITE_URL.rstrip("/")
    api_url = settings.TAMARA_API_URL.rstrip("/")

    items_payload = []
    for item in data.items:
        pid = canonical_product_id(item.product_id)
        items_payload.append(
            {
                "name": PRODUCT_NAMES_AR.get(pid, pid),
                "type": "Physical",
                "reference_id": pid,
                "sku": PRODUCT_SKUS.get(pid, item.offer_id),
                "quantity": item.offer_quantity,
                "unit_price": {"amount": item.price_sar, "currency": "SAR"},
                "total_amount": {"amount": item.price_sar, "currency": "SAR"},
                "discount_amount": {"amount": 0, "currency": "SAR"},
                "tax_amount": {"amount": 0, "currency": "SAR"},
            }
        )

    payload = {
        "total_amount": {"amount": order.total_sar, "currency": "SAR"},
        "shipping_amount": {"amount": 0, "currency": "SAR"},
        "tax_amount": {"amount": 0, "currency": "SAR"},
        "order_reference_id": order.order_number,
        "order_number": order.order_number,
        "items": items_payload,
        "consumer": {
            "email": data.email or f"orders+{order.order_number}@sukoonhealth.shop",
            "first_name": first_name,
            "last_name": last_name,
            "phone_number": phone_number,
        },
        "country_code": "SA",
        "description": f"طلب سُكون للصحة {order.order_number}",
        "payment_type": "PAY_BY_INSTALMENTS",
        "instalments": 3,
        "locale": "ar_SA",
        "shipping_address": {
            "first_name": first_name,
            "last_name": last_name,
            "line1": data.address,
            "line2": "",
            "city": data.city,
            "region": data.city,
            "country_code": "SA",
            "phone_number": phone_number,
        },
        "merchant_url": {
            "success": f"{site}/checkout/tamara/success?order_id={order.order_number}",
            "cancel": f"{site}/checkout?cancelled=tamara",
            "failure": f"{site}/checkout?failed=tamara",
            "notification": f"{settings.API_PUBLIC_URL.rstrip('/')}/api/webhooks/tamara",
        },
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{api_url}/checkout",
            headers=_headers(),
            json=payload,
        )

    if response.status_code >= 400:
        logger.error("Tamara checkout failed: %s", response.text)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="تعذر إنشاء جلسة تمارا",
        )

    body = response.json()
    checkout_url = body.get("checkout_url")
    order.tamara_order_id = body.get("order_id")
    order.tamara_checkout_id = body.get("checkout_id")
    await db.flush()

    if not checkout_url:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="تعذر الحصول على رابط تمارا",
        )

    return checkout_url, order.order_number, order.total_sar


async def authorise_tamara_order(tamara_order_id: str) -> dict:
    api_url = settings.TAMARA_API_URL.rstrip("/")
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{api_url}/orders/{tamara_order_id}/authorise",
            headers=_headers(),
        )
    if response.status_code >= 400:
        logger.error("Tamara authorise failed: %s", response.text)
        raise HTTPException(status_code=502, detail="Tamara authorise failed")
    return response.json()
