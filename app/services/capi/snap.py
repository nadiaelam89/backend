from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.db.models import Order

logger = logging.getLogger(__name__)

SNAP_CAPI_URL = "https://tr.snapchat.com/v2/conversion"


async def send_purchase_event(
    order: Order,
    phone_hash: str,
    pixel_id: str,
    access_token: str,
) -> dict[str, Any]:
    """Send a PURCHASE event to Snap Conversions API.

    Returns a dict with keys: success (bool), status (int|None), body (dict|None).
    Never raises.
    """
    if not access_token or not pixel_id:
        logger.warning("Snap CAPI not configured; skipping (pixel_id=%s)", pixel_id)
        return {"success": False, "status": None, "body": None}

    payload: dict[str, Any] = {
        "pixel_id": pixel_id,
        "event_type": "PURCHASE",
        "event_conversion_type": "WEB",
        "event_tag": order.order_number,
        "timestamp": int(time.time() * 1000),
        "hashed_phone_number": phone_hash,
        "price": order.total_sar,
        "currency": order.currency,
        "transaction_id": order.event_id,
        "item_ids": [item.product_id for item in order.items],
        "description": " | ".join(item.name_ar for item in order.items),
        **({"ip_address": order.client_ip} if order.client_ip else {}),
        **({"user_agent": order.client_user_agent} if order.client_user_agent else {}),
        **({"page_url": order.source_url} if order.source_url else {}),
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(SNAP_CAPI_URL, json=payload, headers=headers)
            body: dict = response.json() if response.content else {}
            logger.info(
                "Snap CAPI Purchase sent for order %s → HTTP %s",
                order.order_number,
                response.status_code,
            )
            return {"success": response.is_success, "status": response.status_code, "body": body}
    except Exception as exc:  # noqa: BLE001
        logger.error("Snap CAPI failed for order %s: %s", order.order_number, exc)
        return {"success": False, "status": None, "body": None}
