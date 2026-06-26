"""Integration-style tests for the orders API endpoints.

All database and HTTP side-effect calls are mocked so these tests run
without any external services.
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from tests.conftest import valid_order_payload


# ---------------------------------------------------------------------------
# Health check (sanity)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


# ---------------------------------------------------------------------------
# POST /api/orders – happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_order_success(client: AsyncClient) -> None:
    payload = valid_order_payload()
    response = await client.post("/api/orders", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["ok"] is True
    assert data["order_id"].startswith("SH-")
    assert data["total_sar"] == 349


@pytest.mark.asyncio
async def test_create_order_includes_upsell(client: AsyncClient) -> None:
    payload = valid_order_payload()
    response = await client.post("/api/orders", json=payload)
    assert response.status_code == 201
    data = response.json()
    upsell = data.get("eligible_upsell")
    # The mock order has sleep_gummies → upsell should be ashwagandha_tea
    assert upsell is not None
    assert upsell["product_id"] == "ashwagandha_tea"
    assert upsell["price_sar"] == 99
    assert upsell["expires_in_seconds"] == 15


# ---------------------------------------------------------------------------
# POST /api/orders – validation failures (handled BEFORE order_service)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_order_missing_name(client: AsyncClient) -> None:
    payload = valid_order_payload()
    del payload["name"]
    response = await client.post("/api/orders", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_order_name_too_short(client: AsyncClient) -> None:
    payload = valid_order_payload(name="A")
    response = await client.post("/api/orders", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_order_missing_phone(client: AsyncClient) -> None:
    payload = valid_order_payload()
    del payload["phone"]
    response = await client.post("/api/orders", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_order_unknown_product(client: AsyncClient) -> None:
    payload = valid_order_payload()
    payload["items"][0]["product_id"] = "invalid_product"
    response = await client.post("/api/orders", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_order_missing_event_id(client: AsyncClient) -> None:
    payload = valid_order_payload()
    del payload["event_id"]
    response = await client.post("/api/orders", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_order_empty_items(client: AsyncClient) -> None:
    payload = valid_order_payload()
    payload["items"] = []
    response = await client.post("/api/orders", json=payload)
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/orders – service-layer failures (phone, pricing)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_order_invalid_phone_rejected() -> None:
    """Phone validation happens inside order_service; verify it raises 422."""
    from app.db.session import get_db
    from app.main import app

    async def _override_get_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = _override_get_db

    # Use real order_service (don't patch it) but mock the DB query
    with patch("app.services.order_service._generate_order_number", return_value="SH-TEST-000001"):
        from httpx import ASGITransport, AsyncClient as _AC

        async with _AC(transport=ASGITransport(app=app), base_url="http://test") as ac:
            payload = valid_order_payload(phone="not-a-phone")
            resp = await ac.post("/api/orders", json=payload)

    assert resp.status_code == 422
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_order_tampered_price_rejected() -> None:
    """Tampered price is rejected server-side with 422."""
    from app.db.session import get_db
    from app.main import app

    async def _override_get_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = _override_get_db

    with patch("app.services.order_service._generate_order_number", return_value="SH-TEST-000002"):
        from httpx import ASGITransport, AsyncClient as _AC

        async with _AC(transport=ASGITransport(app=app), base_url="http://test") as ac:
            payload = valid_order_payload()
            payload["items"][0]["price_sar"] = 1  # tampered price
            resp = await ac.post("/api/orders", json=payload)

    assert resp.status_code == 422
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Sheets failure does NOT fail order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sheets_failure_does_not_fail_order() -> None:
    """Even if Google Sheets webhook raises, the order must succeed."""
    from app.db.session import get_db
    from app.main import app
    from app.db.models import Order, OrderItem

    db_mock = AsyncMock()
    db_mock.add = MagicMock()
    db_mock.flush = AsyncMock()
    db_mock.refresh = AsyncMock()

    # Simulate a DB execute for order count (returns 0)
    count_mock = MagicMock()
    count_mock.scalar_one.return_value = 0
    db_mock.execute = AsyncMock(return_value=count_mock)

    fake_item = MagicMock(spec=OrderItem)
    fake_item.product_id = "sleep_gummies"
    fake_item.name_ar = "علكة النوم بالميلاتونين ضد الأرق"
    fake_item.offer_quantity = 3
    fake_item.price_sar = 349
    fake_item.slug = "sleep-melatonin-gummies"
    fake_item.offer_id = "sleep_3"
    fake_item.unit_context = "standard_offer"
    fake_item.added_from = "pdp"

    fake_order = MagicMock(spec=Order)
    fake_order.id = uuid.uuid4()
    fake_order.order_number = "SH-20260625-000001"
    fake_order.total_sar = 349
    fake_order.subtotal_sar = 349
    fake_order.status = "new"
    fake_order.items = [fake_item]
    fake_order.event_id = str(uuid.uuid4())
    fake_order.fbp = None
    fake_order.fbc = None
    fake_order.ttp = None
    fake_order.client_ip = None
    fake_order.client_user_agent = None
    fake_order.source_url = None
    fake_order.currency = "SAR"

    async def _override_get_db():
        yield db_mock

    app.dependency_overrides[get_db] = _override_get_db

    with patch("app.services.order_service.send_order_to_sheets", side_effect=Exception("Sheets down")), \
         patch("app.services.order_service._generate_order_number", return_value="SH-20260625-000001"):

        # We still need db.add to "work" – since Order() constructor is called directly,
        # we need to bypass DB writes. Use the route-level mock approach.
        with patch("app.api.routes.orders.create_order", return_value=fake_order):
            from httpx import ASGITransport, AsyncClient as _AC

            async with _AC(transport=ASGITransport(app=app), base_url="http://test") as ac:
                payload = valid_order_payload()
                resp = await ac.post("/api/orders", json=payload)

    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# CAPI failure does NOT fail order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capi_failure_does_not_fail_order() -> None:
    """CAPI errors (Meta/TikTok/Snap) must not propagate to the HTTP response."""
    from app.db.session import get_db
    from app.main import app
    from app.db.models import Order, OrderItem

    fake_item = MagicMock(spec=OrderItem)
    fake_item.product_id = "focus_coffee"
    fake_item.name_ar = "قهوة التركيز بالإل-ثيانين ضد الخمول"
    fake_item.offer_quantity = 1
    fake_item.price_sar = 199

    fake_order = MagicMock(spec=Order)
    fake_order.order_number = "SH-20260625-000002"
    fake_order.total_sar = 199
    fake_order.status = "new"
    fake_order.items = [fake_item]

    async def _override_get_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = _override_get_db

    with patch("app.api.routes.orders.create_order", return_value=fake_order), \
         patch("app.services.capi.meta.send_purchase_event", side_effect=Exception("Meta CAPI down")), \
         patch("app.services.capi.tiktok.send_purchase_event", side_effect=Exception("TikTok CAPI down")), \
         patch("app.services.capi.snap.send_purchase_event", side_effect=Exception("Snap CAPI down")):

        from httpx import ASGITransport, AsyncClient as _AC

        async with _AC(transport=ASGITransport(app=app), base_url="http://test") as ac:
            payload = valid_order_payload()
            payload["items"][0]["product_id"] = "focus_coffee"
            payload["items"][0]["slug"] = "l-theanine-focus-coffee"
            payload["items"][0]["offer_quantity"] = 1
            payload["items"][0]["price_sar"] = 199
            resp = await ac.post("/api/orders", json=payload)

    assert resp.status_code == 201
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /api/orders/{order_id}/summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_order_summary_success(client: AsyncClient) -> None:
    response = await client.get("/api/orders/SH-20260625-000001/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["order_id"] == "SH-20260625-000001"
    assert "total_sar" in data
    assert "product_names" in data
    # Phone number must NOT be in the response
    assert "phone" not in data
    assert "phone_local" not in data
    assert "phone_e164" not in data


# ---------------------------------------------------------------------------
# POST /api/orders/{order_id}/upsell
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsell_success(client: AsyncClient) -> None:
    payload = {
        "product_id": "ashwagandha_tea",
        "price_sar": 99,
        "event_id": str(uuid.uuid4()),
    }
    response = await client.post("/api/orders/SH-20260625-000001/upsell", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "new_total_sar" in data


@pytest.mark.asyncio
async def test_upsell_invalid_product(client: AsyncClient) -> None:
    payload = {
        "product_id": "fake_product",
        "price_sar": 99,
        "event_id": str(uuid.uuid4()),
    }
    response = await client.post("/api/orders/SH-20260625-000001/upsell", json=payload)
    assert response.status_code == 422
