from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import settings
from app.db.models import Order
from app.services.pricing import PRODUCT_NAMES_AR, PRODUCT_SKUS, canonical_product_id

logger = logging.getLogger(__name__)


def _gas_response_ok(response: httpx.Response) -> bool:
    if response.status_code < 400:
        return True
    try:
        data = response.json()
        return bool(data.get("ok"))
    except Exception:  # noqa: BLE001
        normalized = response.text.replace(" ", "").lower()
        return '"ok":true' in normalized


def build_order_sheet_row(order: Order) -> dict[str, object]:
    products = [item.name_ar for item in order.items]
    skus = [
        PRODUCT_SKUS.get(canonical_product_id(item.product_id), "SKU-UNKNOWN")
        for item in order.items
    ]
    quantities = [str(item.offer_quantity) for item in order.items]

    created_date = order.created_at if order.created_at else datetime.now(timezone.utc)
    date_str = created_date.strftime("%d/%m/%Y")
    phone = order.phone_e164.replace("+", "") if order.phone_e164 else ""

    return {
        "date": date_str,
        "orderid": order.order_number,
        "country": "KSA",
        "name": order.customer_name,
        "phone": phone,
        "product": " + ".join(products),
        "sku": " + ".join(skus),
        "quantity": " + ".join(quantities),
        "totalprice": order.total_sar,
        "currency": "SAR",
        "status": order.status or "",
    }


async def send_order_to_sheets(order: Order) -> dict[str, object]:
    """POST a new order row to the configured Google Sheets webhook."""
    return await _send_sheets_payload(
        {"type": "order_created", "order": build_order_sheet_row(order)},
        order.order_number,
        "order_created",
    )


async def send_order_update_to_sheets(order: Order) -> dict[str, object]:
    """Update an existing Orders row after upsell or order changes."""
    return await _send_sheets_payload(
        {"type": "order_updated", "order": build_order_sheet_row(order)},
        order.order_number,
        "order_updated",
    )


async def send_upsell_accepted_to_sheets(order: Order, event_id: str) -> dict[str, object]:
    """Append a row to the Upsells tab."""
    upsell_items = [item for item in order.items if item.added_from == "upsell"]
    if not upsell_items:
        return {"ok": False, "error": "no_upsell_item"}

    item = upsell_items[-1]
    return await _send_sheets_payload(
        {
            "type": "upsell_accepted",
            "upsell": {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "order_id": order.order_number,
                "product_id": item.product_id,
                "product_name": item.name_ar or PRODUCT_NAMES_AR.get(item.product_id, ""),
                "price_sar": item.price_sar,
                "event_id": event_id,
            },
        },
        order.order_number,
        "upsell_accepted",
    )


async def _send_sheets_payload(
    payload: dict[str, Any],
    order_number: str,
    event_type: str,
) -> dict[str, object]:
    if not settings.GOOGLE_SHEETS_WEBHOOK_URL:
        logger.warning("GOOGLE_SHEETS_WEBHOOK_URL is not configured; skipping Sheets push")
        return {"ok": False, "error": "webhook_not_configured"}

    webhook_host = settings.GOOGLE_SHEETS_WEBHOOK_URL.split("/macros/s/")[0]
    logger.info(
        "Sending %s for order %s to Sheets webhook (%s...)",
        event_type,
        order_number,
        webhook_host,
    )

    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
            response = await _post_google_apps_script(
                client, settings.GOOGLE_SHEETS_WEBHOOK_URL, payload
            )
            body = response.text[:500]

            if _gas_response_ok(response):
                logger.info(
                    "Sheets %s delivered for order %s (HTTP %s): %s",
                    event_type,
                    order_number,
                    response.status_code,
                    body[:200],
                )
                return {"ok": True, "status_code": response.status_code, "body": body}

            logger.error(
                "Sheets %s failed for order %s (HTTP %s): %s",
                event_type,
                order_number,
                response.status_code,
                body,
            )
            return {
                "ok": False,
                "status_code": response.status_code,
                "error": body,
            }
    except Exception as exc:  # noqa: BLE001
        logger.error("Sheets %s failed for order %s: %s", event_type, order_number, str(exc))
        return {"ok": False, "error": str(exc)}


async def _post_google_apps_script(
    client: httpx.AsyncClient,
    url: str,
    payload: dict[str, object],
) -> httpx.Response:
    """Google Apps Script /exec URLs 302 after POST; follow with GET."""
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "SukoonHealth-API/1.0",
    }
    first = await client.post(url, json=payload, headers=headers)

    if first.status_code not in {301, 302, 303, 307, 308}:
        return first

    location = first.headers.get("location")
    if not location:
        match = re.search(r'href="([^"]+)"', first.text, re.IGNORECASE)
        location = html.unescape(match.group(1)) if match else None

    if not location:
        logger.warning("Sheets webhook returned %s without redirect URL", first.status_code)
        return first

    logger.info("Sheets webhook redirect -> GET %s...", location[:80])
    return await client.get(location, headers=headers, follow_redirects=True)
