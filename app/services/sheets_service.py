from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from app.core.config import settings
from app.db.models import Order

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

    payload = {
        "secret": settings.GOOGLE_SHEETS_WEBHOOK_SECRET,
        "type": "order_created",
        "order": {
            "created_at": order.created_at.isoformat() if order.created_at else datetime.now(timezone.utc).isoformat(),
            "order_id": order.order_number,
            "status": order.status,
            "name": order.customer_name,
            "phone_local": order.phone_local,
            "phone_e164": order.phone_e164,
            "products_text": _build_products_text(order),
            "items": _build_items_payload(order),
            "subtotal_sar": order.subtotal_sar,
            "delivery_fee_sar": order.delivery_fee_sar,
            "total_sar": order.total_sar,
            "payment_method": "COD",
            "source_url": order.source_url or "",
            "utm": order.utm or {},
            "event_id": order.event_id,
            "notes": "",
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
