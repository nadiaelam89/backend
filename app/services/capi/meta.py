from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.db.models import Order
from app.services.capi.logging import log_capi_result

logger = logging.getLogger(__name__)

META_CAPI_URL = "https://graph.facebook.com/v21.0/{pixel_id}/events"


def build_meta_purchase_payload(
    order: Order,
    phone_hash: str,
    access_token: str,
    pixel_id: str,
) -> dict[str, Any]:
    contents = [
        {
            "id": item.product_id,
            "quantity": item.offer_quantity,
            "item_price": item.price_sar,
        }
        for item in order.items
    ]

    return {
        "data": [
            {
                "event_name": "Purchase",
                "event_time": int(time.time()),
                "event_id": order.event_id,
                "action_source": "website",
                "event_source_url": order.source_url or "",
                "user_data": {
                    "ph": [phone_hash],
                    **({"fbp": order.fbp} if order.fbp else {}),
                    **({"fbc": order.fbc} if order.fbc else {}),
                    **({"client_ip_address": order.client_ip} if order.client_ip else {}),
                    **(
                        {"client_user_agent": order.client_user_agent}
                        if order.client_user_agent
                        else {}
                    ),
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


async def send_purchase_event(
    order: Order,
    phone_hash: str,
    access_token: str,
    pixel_id: str,
) -> dict[str, Any]:
    """Send a Purchase event to Meta Conversions API."""
    if not access_token or not pixel_id:
        logger.warning("Meta CAPI not configured; skipping (pixel_id=%s)", pixel_id)
        return {"success": False, "status": None, "body": None}

    event_payload = build_meta_purchase_payload(order, phone_hash, access_token, pixel_id)
    request_summary = {
        "pixel_id": pixel_id,
        "event_name": "Purchase",
        "event_id": order.event_id,
        "value": order.total_sar,
        "currency": order.currency,
        "has_phone_hash": bool(phone_hash),
        "has_fbp": bool(order.fbp),
        "has_fbc": bool(order.fbc),
    }

    url = META_CAPI_URL.format(pixel_id=pixel_id)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=event_payload)
            body: dict = response.json() if response.content else {}
            result = {
                "success": response.is_success,
                "status": response.status_code,
                "body": body,
            }
            log_capi_result(
                "meta",
                order_number=order.order_number,
                event_id=order.event_id,
                event_name="Purchase",
                request_summary=request_summary,
                result=result,
            )
            return result
    except Exception as exc:  # noqa: BLE001
        logger.error("Meta CAPI failed for order %s: %s", order.order_number, exc)
        return {"success": False, "status": None, "body": None}
