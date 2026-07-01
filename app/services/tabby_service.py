from __future__ import annotations

import logging

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.schemas.payments import CheckoutPaymentRequest
from app.services.checkout_order import create_checkout_order_from_payment_request
from app.services.phone import normalize_saudi_phone
from app.services.pricing import PRODUCT_NAMES_AR, canonical_product_id

logger = logging.getLogger(__name__)

TABBY_API = "https://api.tabby.ai"


def _headers() -> dict[str, str]:
    if not settings.TABBY_SECRET_KEY or not settings.TABBY_MERCHANT_CODE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tabby is not configured",
        )
    return {
        "Authorization": f"Bearer {settings.TABBY_SECRET_KEY}",
        "Content-Type": "application/json",
        "X-Merchant-Code": settings.TABBY_MERCHANT_CODE,
    }


def _split_name(full_name: str) -> tuple[str, str]:
    parts = full_name.strip().split()
    if len(parts) == 1:
        return parts[0], parts[0]
    return parts[0], " ".join(parts[1:])


async def create_tabby_session(
    db: AsyncSession,
    data: CheckoutPaymentRequest,
    client_ip: str | None,
    client_country: str | None,
) -> tuple[str, str, int]:
    order = await create_checkout_order_from_payment_request(
        db,
        data,
        payment_method="tabby",
        payment_status="pending",
        client_ip=client_ip,
        client_country=client_country,
    )

    phone = normalize_saudi_phone(data.phone)
    amount = f"{order.total_sar:.2f}"
    site = settings.SITE_URL.rstrip("/")

    payload = {
        "payment": {
            "amount": amount,
            "currency": "SAR",
            "description": f"طلب {order.order_number}",
            "buyer": {
                "name": data.name.strip(),
                "phone": phone.phone_e164 if phone.is_valid else data.phone,
                "email": data.email or f"orders+{order.order_number}@sukoonhealth.shop",
            },
            "order": {
                "reference_id": order.order_number,
                "items": [
                    {
                        "title": PRODUCT_NAMES_AR.get(
                            canonical_product_id(item.product_id), item.product_id
                        ),
                        "quantity": item.offer_quantity,
                        "unit_price": f"{item.price_sar:.2f}",
                        "reference_id": item.offer_id,
                    }
                    for item in data.items
                ],
            },
            "shipping_address": {
                "city": data.city,
                "address": data.address,
                "zip": "00000",
            },
        },
        "lang": "ar",
        "merchant_code": settings.TABBY_MERCHANT_CODE,
        "merchant_urls": {
            "success": f"{site}/checkout/tabby/success?order_id={order.order_number}",
            "cancel": f"{site}/checkout?cancelled=tabby",
            "failure": f"{site}/checkout?failed=tabby",
        },
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{TABBY_API}/api/v2/checkout",
            headers=_headers(),
            json=payload,
        )

    if response.status_code >= 400:
        logger.error("Tabby session failed: %s", response.text)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="تعذر إنشاء جلسة تابي",
        )

    body = response.json()
    payment_url = (
        body.get("configuration", {}).get("available_products", {}).get("installments", [{}])[0]
        if isinstance(body.get("configuration"), dict)
        else None
    )
    if not payment_url:
        payment_url = body.get("payment_url") or body.get("url")

    if not payment_url and isinstance(body.get("configuration"), dict):
        products = body["configuration"].get("available_products") or {}
        for key in ("installments", "pay_later"):
            entries = products.get(key)
            if isinstance(entries, list) and entries:
                payment_url = entries[0].get("web_url") or entries[0].get("url")
                if payment_url:
                    break

    payment = body.get("payment") or {}
    order.tabby_payment_id = payment.get("id")
    order.tabby_session_id = body.get("id")
    await db.flush()

    if not payment_url:
        logger.error("Tabby response missing payment URL: %s", body)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="تعذر الحصول على رابط تابي",
        )

    return payment_url, order.order_number, order.total_sar


async def get_tabby_payment(payment_id: str) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{TABBY_API}/api/v2/payments/{payment_id}",
            headers=_headers(),
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Tabby payment lookup failed")
    return response.json()


async def capture_tabby_payment(payment_id: str, amount: str, reference_id: str) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{TABBY_API}/api/v2/payments/{payment_id}/captures",
            headers=_headers(),
            json={"amount": amount, "reference_id": reference_id},
        )
    if response.status_code >= 400:
        logger.error("Tabby capture failed: %s", response.text)
        raise HTTPException(status_code=502, detail="Tabby capture failed")
    return response.json()
