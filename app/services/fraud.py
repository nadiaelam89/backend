from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import httpx
from fastapi import HTTPException, status

from app.core.config import settings
from app.services.pricing import PRODUCT_NAMES_AR

if TYPE_CHECKING:
    from app.schemas.orders import CreateOrderRequest
    from app.services.phone import PhoneResult

logger = logging.getLogger(__name__)

MAXMIND_MINFRAUD_INSIGHTS_URL = "https://minfraud.maxmind.com/minfraud/v2.0/insights"


@dataclass(frozen=True)
class FraudDecision:
    allowed: bool
    reason: str = "allowed"
    risk_score: float | None = None
    country_code: str | None = None


def _is_public_ip(ip_value: str | None) -> bool:
    if not ip_value:
        return False
    try:
        parsed = ipaddress.ip_address(ip_value)
    except ValueError:
        return False
    return parsed.is_global


def _phone_is_whitelisted(phone_result: PhoneResult) -> bool:
    whitelist = settings.whitelisted_phones
    return bool(
        phone_result.phone_e164 in whitelist
        or phone_result.phone_digits in whitelist
        or phone_result.phone_local in whitelist
    )


def _extract_country_code(response_body: dict) -> str | None:
    # minFraud Insights may include several location sections depending on inputs.
    candidates = [
        response_body.get("ip_address", {}),
        response_body.get("billing_address", {}),
        response_body.get("shipping_address", {}),
    ]
    for candidate in candidates:
        country = candidate.get("country") if isinstance(candidate, dict) else None
        if isinstance(country, dict) and country.get("iso_code"):
            return str(country["iso_code"])
        if isinstance(country, str):
            return country
    return None


def _build_minfraud_payload(
    order_data: CreateOrderRequest,
    phone_result: PhoneResult,
    client_ip: str,
) -> dict:
    full_name = order_data.name.strip()
    first_name = full_name.split()[0] if full_name else ""
    total = sum(item.price_sar for item in order_data.items)

    return {
        "device": {
            "ip_address": client_ip,
            "user_agent": order_data.client_user_agent,
        },
        "event": {
            "time": datetime.now(timezone.utc).isoformat(),
            "transaction_id": str(order_data.event_id),
            "type": "purchase",
        },
        "order": {
            "amount": total,
            "currency": order_data.currency,
            "referrer_uri": order_data.source_url,
        },
        "billing": {
            "country": "SA",
            "first_name": first_name,
            "phone_country_code": "966",
            "phone_number": phone_result.phone_digits[3:],
        },
        "shipping": {
            "country": "SA",
            "first_name": first_name,
            "phone_country_code": "966",
            "phone_number": phone_result.phone_digits[3:],
        },
        "shopping_cart": [
            {
                "category": "wellness",
                "item_id": item.product_id,
                "price": item.price_sar,
                "quantity": item.offer_quantity,
            }
            for item in order_data.items
        ],
        "custom_inputs": {
            "store": "sukoonhealth.shop",
            "payment_method": "COD",
            "products": [
                PRODUCT_NAMES_AR.get(item.product_id, item.product_id) for item in order_data.items
            ],
        },
    }


async def check_order_ip_fraud(
    order_data: CreateOrderRequest,
    phone_result: PhoneResult,
    client_ip: str | None,
) -> FraudDecision:
    if not settings.ENABLE_IP_FRAUD_CHECK:
        return FraudDecision(allowed=True, reason="disabled")

    if _phone_is_whitelisted(phone_result):
        return FraudDecision(allowed=True, reason="whitelisted_phone")

    if not _is_public_ip(client_ip):
        return FraudDecision(allowed=True, reason="non_public_or_missing_ip")

    if not settings.MAXMIND_ACCOUNT_ID or not settings.MAXMIND_LICENSE_KEY:
        logger.warning("MaxMind fraud check enabled but credentials are missing")
        return FraudDecision(allowed=True, reason="missing_credentials")

    payload = _build_minfraud_payload(order_data, phone_result, client_ip)

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.post(
                MAXMIND_MINFRAUD_INSIGHTS_URL,
                json=payload,
                auth=(settings.MAXMIND_ACCOUNT_ID, settings.MAXMIND_LICENSE_KEY),
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            body = response.json()
    except Exception as exc:  # noqa: BLE001
        logger.error("MaxMind fraud check failed open for IP %s: %s", client_ip, exc)
        return FraudDecision(allowed=True, reason="provider_error")

    risk_score = body.get("risk_score")
    risk_score_float = float(risk_score) if isinstance(risk_score, (int, float)) else None
    country_code = _extract_country_code(body)

    if country_code and country_code.upper() != settings.MAXMIND_ALLOWED_COUNTRY.upper():
        return FraudDecision(
            allowed=False,
            reason="non_allowed_country",
            risk_score=risk_score_float,
            country_code=country_code,
        )

    if (
        risk_score_float is not None
        and risk_score_float >= settings.MAXMIND_RISK_SCORE_THRESHOLD
    ):
        return FraudDecision(
            allowed=False,
            reason="high_risk_score",
            risk_score=risk_score_float,
            country_code=country_code,
        )

    return FraudDecision(
        allowed=True,
        reason="passed",
        risk_score=risk_score_float,
        country_code=country_code,
    )


async def assert_order_ip_allowed(
    order_data: CreateOrderRequest,
    phone_result: PhoneResult,
    client_ip: str | None,
) -> FraudDecision:
    decision = await check_order_ip_fraud(order_data, phone_result, client_ip)
    if decision.allowed:
        logger.info(
            "Allowed order by MaxMind fraud check: reason=%s risk_score=%s country=%s ip=%s",
            decision.reason,
            decision.risk_score,
            decision.country_code,
            client_ip,
        )
        return decision

    logger.warning(
        "Blocked order by MaxMind fraud check: reason=%s risk_score=%s country=%s ip=%s",
        decision.reason,
        decision.risk_score,
        decision.country_code,
        client_ip,
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="تعذر قبول الطلب حالياً بسبب فحص الأمان. إذا كنت تستخدم VPN أغلقه وحاول مرة أخرى.",
    )
