from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.db.models import Order

logger = logging.getLogger(__name__)

TIKTOK_EVENTS_URL = "https://business-api.tiktok.com/open_api/v1.3/event/track/"


async def send_purchase_event(
    order: Order,
    phone_hash: str,
    pixel_code: str,
    access_token: str,
) -> dict[str, Any]:
    """Send a PlaceAnOrder / Purchase event to TikTok Events API.

    Returns a dict with keys: success (bool), status (int|None), body (dict|None).
    Never raises.
    """
    if not access_token or not pixel_code:
        logger.warning("TikTok CAPI not configured; skipping (pixel_code=%s)", pixel_code)
        return {"success": False, "status": None, "body": None}

    contents = [
        {
            "content_id": item.product_id,
            "content_name": item.name_ar,
            "quantity": item.offer_quantity,
            "price": item.price_sar,
        }
        for item in order.items
    ]

    payload: dict[str, Any] = {
        "pixel_code": pixel_code,
        "event": "PlaceAnOrder",
        "event_id": order.event_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "context": {
            "user": {
                "phone_number": phone_hash,
                **({"ttp": order.ttp} if order.ttp else {}),
            },
            **(
                {
                    "ip": order.client_ip,
                    "user_agent": order.client_user_agent,
                }
                if order.client_ip
                else {}
            ),
            "page": {"url": order.source_url or ""},
        },
        "properties": {
            "currency": order.currency,
            "value": order.total_sar,
            "order_id": order.order_number,
            "contents": contents,
        },
    }

    headers = {
        "Access-Token": access_token,
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(TIKTOK_EVENTS_URL, json=payload, headers=headers)
            body: dict = response.json() if response.content else {}
            logger.info(
                "TikTok CAPI Purchase sent for order %s → HTTP %s",
                order.order_number,
                response.status_code,
            )
            return {"success": response.is_success, "status": response.status_code, "body": body}
    except Exception as exc:  # noqa: BLE001
        logger.error("TikTok CAPI failed for order %s: %s", order.order_number, exc)
        return {"success": False, "status": None, "body": None}
