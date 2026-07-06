from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from app.db.models import Order
from app.services.capi.logging import log_capi_result

logger = logging.getLogger(__name__)

SNAP_CAPI_URL = "https://tr.snapchat.com/v3/{pixel_id}/events"


def build_snap_purchase_payload(order: Order, phone_hash: str) -> dict[str, Any]:
    contents = [
        {
            "id": item.product_id,
            "quantity": item.offer_quantity,
            "item_price": item.price_sar,
        }
        for item in order.items
    ]

    user_data: dict[str, Any] = {"ph": [phone_hash]}
    if order.client_ip:
        user_data["client_ip_address"] = order.client_ip
    if order.client_user_agent:
        user_data["client_user_agent"] = order.client_user_agent

    return {
        "data": [
            {
                "event_name": "PURCHASE",
                "event_time": int(time.time()),
                "event_id": order.event_id,
                "action_source": "WEB",
                "event_source_url": order.source_url or "",
                "user_data": user_data,
                "custom_data": {
                    "currency": order.currency,
                    "value": order.total_sar,
                    "order_id": order.order_number,
                    "content_ids": [item.product_id for item in order.items],
                    "contents": contents,
                },
            }
        ]
    }


async def send_purchase_event(
    order: Order,
    phone_hash: str,
    pixel_id: str,
    access_token: str,
) -> dict[str, Any]:
    """Send a PURCHASE event to Snap Conversions API v3."""
    if not access_token or not pixel_id:
        logger.warning("Snap CAPI not configured; skipping (pixel_id=%s)", pixel_id)
        return {"success": False, "status": None, "body": None}

    payload = build_snap_purchase_payload(order, phone_hash)
    request_summary = {
        "pixel_id": pixel_id,
        "event_name": "PURCHASE",
        "event_id": order.event_id,
        "value": order.total_sar,
        "currency": order.currency,
        "has_phone_hash": bool(phone_hash),
        "api_version": "v3",
    }

    query = urlencode({"access_token": access_token})
    url = f"{SNAP_CAPI_URL.format(pixel_id=pixel_id)}?{query}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            body: dict = response.json() if response.content else {}
            result = {
                "success": response.is_success,
                "status": response.status_code,
                "body": body,
            }
            log_capi_result(
                "snap",
                order_number=order.order_number,
                event_id=order.event_id,
                event_name="PURCHASE",
                request_summary=request_summary,
                result=result,
            )
            return result
    except Exception as exc:  # noqa: BLE001
        logger.error("Snap CAPI failed for order %s: %s", order.order_number, exc)
        return {"success": False, "status": None, "body": None}
