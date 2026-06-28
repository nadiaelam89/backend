from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from app.core.config import settings
from app.db.models import Order
from app.services.pricing import PRODUCT_SKUS

logger = logging.getLogger(__name__)


def _build_products_text(order: Order) -> str:
    """Build a human-readable product summary, e.g. 'علكة النوم x 3'."""
    parts: list[str] = []
    for item in order.items:
        parts.append(f"{item.name_ar} x {item.offer_quantity}")
    return " | ".join(parts)


def _build_items_payload(order: Order) -> list[dict]:
    return [
        {
            "product_id": item.product_id,
            "slug": item.slug,
            "name_ar": item.name_ar,
            "offer_id": item.offer_id,
            "offer_quantity": item.offer_quantity,
            "unit_context": item.unit_context,
            "price_sar": item.price_sar,
        }
        for item in order.items
    ]


async def send_order_to_sheets(order: Order) -> None:
    """POST the order to the configured Google Sheets webhook.

    Failures are caught and logged – they must NOT propagate to callers so that
    a Sheets outage never breaks order creation.
    """
    if not settings.GOOGLE_SHEETS_WEBHOOK_URL:
        logger.warning("GOOGLE_SHEETS_WEBHOOK_URL is not configured; skipping Sheets push")
        return

    products = [item.name_ar for item in order.items]
    skus = [PRODUCT_SKUS.get(item.product_id, "SKU-UNKNOWN") for item in order.items]
    quantities = [str(item.offer_quantity) for item in order.items]
    
    created_date = order.created_at if order.created_at else datetime.now(timezone.utc)
    date_str = created_date.strftime("%d/%m/%Y")
    
    phone = order.phone_e164.replace("+", "") if order.phone_e164 else ""

    payload = {
        "secret": settings.GOOGLE_SHEETS_WEBHOOK_SECRET,
        "type": "order_created",
        "order": {
            "date": date_str,
            "orderid": order.order_number,
            "country": "KSA",
            "name": order.customer_name,
            "phone": phone,
            "product": "/".join(products),
            "sku": "/".join(skus),
            "quantity": "/".join(quantities),
            "totalprice": order.total_sar,
            "currency": "SAR",
            "status": ""
        },
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(settings.GOOGLE_SHEETS_WEBHOOK_URL, json=payload)
            response.raise_for_status()
            logger.info(
                "Sheets webhook delivered for order %s (HTTP %s)",
                order.order_number,
                response.status_code,
            )
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Sheets webhook HTTP error for order %s: %s %s",
            order.order_number,
            exc.response.status_code,
            exc.response.text[:200],
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Sheets webhook failed for order %s: %s",
            order.order_number,
            str(exc),
        )
