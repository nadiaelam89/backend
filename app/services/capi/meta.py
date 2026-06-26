from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.db.models import Order

logger = logging.getLogger(__name__)

META_CAPI_URL = "https://graph.facebook.com/v19.0/{pixel_id}/events"


async def send_purchase_event(
    order: Order,
    phone_hash: str,
    access_token: str,
    pixel_id: str,
) -> dict[str, Any]:
    """Send a Purchase event to Meta Conversions API.

    Returns a dict with keys: success (bool), status (int|None), body (dict|None).
    Never raises – failures are surfaced via the return value and logged.
    """
    if not access_token or not pixel_id:
        logger.warning("Meta CAPI not configured; skipping (pixel_id=%s)", pixel_id)
        return {"success": False, "status": None, "body": None}

    contents = [
        {
            "id": item.product_id,
            "quantity": item.offer_quantity,
            "item_price": item.price_sar,
        }
        for item in order.items
    ]

    event_payload: dict[str, Any] = {
        "data": [
            {
                "event_name": "Purchase",
                "event_time": int(time.time()),
                "event_id": order.event_id,
                "action_source": "website",
                "user_data": {
                    "ph": [phone_hash],
                    **({"fbp": order.fbp} if order.fbp else {}),
                    **({"fbc": order.fbc} if order.fbc else {}),
                    **({"client_ip_address": order.client_ip} if order.client_ip else {}),
                    **({"client_user_agent": order.client_user_agent} if order.client_user_agent else {}),
                },
                "custom_data": {
                    "currency": order.currency,
                    "value": order.total_sar,
                    "order_id": order.order_number,
                    "contents": contents,
                    "content_type": "product",
                },
            }
        ],
        "access_token": access_token,
    }

    url = META_CAPI_URL.format(pixel_id=pixel_id)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=event_payload)
            body: dict = response.json() if response.content else {}
            logger.info(
                "Meta CAPI Purchase sent for order %s → HTTP %s",
                order.order_number,
                response.status_code,
            )
            return {"success": response.is_success, "status": response.status_code, "body": body}
    except Exception as exc:  # noqa: BLE001
        logger.error("Meta CAPI failed for order %s: %s", order.order_number, exc)
        return {"success": False, "status": None, "body": None}
