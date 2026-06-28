from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import httpx

from app.core.config import settings
from app.services.fraud import (
    MAXMIND_MINFRAUD_INSIGHTS_URL,
    FraudDecision,
    _extract_country_code,
    _is_public_ip,
)

logger = logging.getLogger(__name__)

_IP_DECISION_CACHE: dict[str, tuple[FraudDecision, float]] = {}
_CACHE_TTL_SECONDS = 3600


def _cache_get(ip: str) -> FraudDecision | None:
    cached = _IP_DECISION_CACHE.get(ip)
    if not cached:
        return None
    decision, expires_at = cached
    if time.time() > expires_at:
        _IP_DECISION_CACHE.pop(ip, None)
        return None
    return decision


def _cache_set(ip: str, decision: FraudDecision) -> None:
    _IP_DECISION_CACHE[ip] = (decision, time.time() + _CACHE_TTL_SECONDS)


def _cloudflare_only_decision(client_country: str | None) -> FraudDecision:
    allowed_country = settings.MAXMIND_ALLOWED_COUNTRY.upper()
    if client_country and client_country.upper() == allowed_country:
        return FraudDecision(allowed=True, reason="cloudflare_country_allowed", country_code=client_country)
    if client_country:
        return FraudDecision(
            allowed=False,
            reason="non_allowed_cloudflare_country",
            country_code=client_country,
        )
    return FraudDecision(allowed=True, reason="country_unknown_fail_open", country_code=None)


async def check_visitor_ip_fraud(
    client_ip: str | None,
    client_country: str | None = None,
    user_agent: str | None = None,
) -> FraudDecision:
    """Classify storefront traffic for analytics (KSA, non-VPN when enabled)."""
    allowed_country = settings.MAXMIND_ALLOWED_COUNTRY.upper()

    if not settings.ENABLE_IP_FRAUD_CHECK:
        return _cloudflare_only_decision(client_country)

    if client_country and client_country.upper() != allowed_country:
        return FraudDecision(
            allowed=False,
            reason="non_allowed_cloudflare_country",
            country_code=client_country,
        )

    if not _is_public_ip(client_ip):
        return _cloudflare_only_decision(client_country)

    assert client_ip is not None
    cached = _cache_get(client_ip)
    if cached:
        return cached

    if not settings.MAXMIND_ACCOUNT_ID or not settings.MAXMIND_LICENSE_KEY:
        decision = _cloudflare_only_decision(client_country)
        _cache_set(client_ip, decision)
        return decision

    payload = {
        "device": {
            "ip_address": client_ip,
            "user_agent": user_agent,
        },
        "event": {
            "time": datetime.now(timezone.utc).isoformat(),
            "type": "page_view",
        },
    }

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
        logger.error("Visitor MaxMind check failed for IP %s: %s", client_ip, exc)
        decision = _cloudflare_only_decision(client_country)
        _cache_set(client_ip, decision)
        return decision

    risk_score = body.get("risk_score")
    risk_score_float = float(risk_score) if isinstance(risk_score, (int, float)) else None
    country_code = _extract_country_code(body)

    if country_code and country_code.upper() != allowed_country:
        decision = FraudDecision(
            allowed=False,
            reason="non_allowed_country",
            risk_score=risk_score_float,
            country_code=country_code,
        )
        _cache_set(client_ip, decision)
        return decision

    if (
        risk_score_float is not None
        and risk_score_float >= settings.MAXMIND_RISK_SCORE_THRESHOLD
    ):
        decision = FraudDecision(
            allowed=False,
            reason="high_risk_score",
            risk_score=risk_score_float,
            country_code=country_code,
        )
        _cache_set(client_ip, decision)
        return decision

    decision = FraudDecision(
        allowed=True,
        reason="passed",
        risk_score=risk_score_float,
        country_code=country_code or client_country,
    )
    _cache_set(client_ip, decision)
    return decision
