from __future__ import annotations

import uuid

import pytest

from app.core.config import settings
from app.schemas.orders import CreateOrderRequest
from app.services.fraud import check_order_ip_fraud
from app.services.phone import normalize_saudi_phone


def _order_request() -> CreateOrderRequest:
    return CreateOrderRequest(
        name="نورة العمري",
        phone="0512345678",
        items=[
            {
                "product_id": "sleep_gummies",
                "slug": "sleep-melatonin-gummies",
                "offer_id": "sleep_3",
                "offer_quantity": 3,
                "price_sar": 349,
                "added_from": "pdp",
            }
        ],
        currency="SAR",
        event_id=uuid.uuid4(),
        source_url="https://sukoonhealth.shop/products/sleep-melatonin-gummies",
    )


@pytest.mark.asyncio
async def test_fraud_check_disabled_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENABLE_IP_FRAUD_CHECK", False)

    phone = normalize_saudi_phone("0512345678")
    decision = await check_order_ip_fraud(_order_request(), phone, "8.8.8.8")

    assert decision.allowed is True
    assert decision.reason == "disabled"


@pytest.mark.asyncio
async def test_fraud_check_whitelisted_phone_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENABLE_IP_FRAUD_CHECK", True)
    monkeypatch.setattr(settings, "WHITELISTED_PHONES", "+966512345678")

    phone = normalize_saudi_phone("0512345678")
    decision = await check_order_ip_fraud(_order_request(), phone, "8.8.8.8")

    assert decision.allowed is True
    assert decision.reason == "whitelisted_phone"


@pytest.mark.asyncio
async def test_fraud_check_missing_credentials_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENABLE_IP_FRAUD_CHECK", True)
    monkeypatch.setattr(settings, "WHITELISTED_PHONES", "")
    monkeypatch.setattr(settings, "MAXMIND_ACCOUNT_ID", "")
    monkeypatch.setattr(settings, "MAXMIND_LICENSE_KEY", "")

    phone = normalize_saudi_phone("0512345678")
    decision = await check_order_ip_fraud(_order_request(), phone, "8.8.8.8")

    assert decision.allowed is True
    assert decision.reason == "missing_credentials"


@pytest.mark.asyncio
async def test_fraud_check_high_risk_score_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"risk_score": 99.0}

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def post(self, *args, **kwargs) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(settings, "ENABLE_IP_FRAUD_CHECK", True)
    monkeypatch.setattr(settings, "WHITELISTED_PHONES", "")
    monkeypatch.setattr(settings, "MAXMIND_ACCOUNT_ID", "12345")
    monkeypatch.setattr(settings, "MAXMIND_LICENSE_KEY", "test-license")
    monkeypatch.setattr(settings, "MAXMIND_RISK_SCORE_THRESHOLD", 25.0)
    monkeypatch.setattr("app.services.fraud.httpx.AsyncClient", FakeClient)

    phone = normalize_saudi_phone("0512345678")
    decision = await check_order_ip_fraud(_order_request(), phone, "8.8.8.8")

    assert decision.allowed is False
    assert decision.reason == "high_risk_score"
    assert decision.risk_score == 99.0


@pytest.mark.asyncio
async def test_fraud_check_non_allowed_country_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"risk_score": 1.0, "ip_address": {"country": {"iso_code": "AE"}}}

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def post(self, *args, **kwargs) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(settings, "ENABLE_IP_FRAUD_CHECK", True)
    monkeypatch.setattr(settings, "WHITELISTED_PHONES", "")
    monkeypatch.setattr(settings, "MAXMIND_ACCOUNT_ID", "12345")
    monkeypatch.setattr(settings, "MAXMIND_LICENSE_KEY", "test-license")
    monkeypatch.setattr(settings, "MAXMIND_ALLOWED_COUNTRY", "SA")
    monkeypatch.setattr("app.services.fraud.httpx.AsyncClient", FakeClient)

    phone = normalize_saudi_phone("0512345678")
    decision = await check_order_ip_fraud(_order_request(), phone, "8.8.8.8")

    assert decision.allowed is False
    assert decision.reason == "non_allowed_country"
    assert decision.country_code == "AE"
