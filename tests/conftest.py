from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# ------------------------------------------------------------------ #
# App / DB imports are deferred inside fixtures so that importing the  #
# conftest never triggers a real DB connection.                        #
# ------------------------------------------------------------------ #


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# ---------------------------------------------------------------------------
# Minimal DB session mock
# ---------------------------------------------------------------------------


def make_db_session() -> AsyncMock:
    """Return an AsyncMock that behaves like an AsyncSession."""
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.fixture
def mock_db() -> AsyncMock:
    return make_db_session()


# ---------------------------------------------------------------------------
# HTTP test client (no real DB)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    from app.db.session import get_db
    from app.main import app

    db_mock = make_db_session()

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_mock

    app.dependency_overrides[get_db] = _override_get_db

    # Patch order_service so it doesn't hit the DB
    with patch("app.api.routes.orders.create_order") as mock_create, \
         patch("app.api.routes.orders.add_upsell") as mock_upsell, \
         patch("app.api.routes.orders.get_order_summary") as mock_summary:

        # Defaults – individual tests can override via the patched fixtures
        _setup_default_mocks(mock_create, mock_upsell, mock_summary)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac

    app.dependency_overrides.clear()


def _setup_default_mocks(mock_create: Any, mock_upsell: Any, mock_summary: Any) -> None:
    """Configure sensible defaults so that happy-path tests don't need extra setup."""
    from app.db.models import Order, OrderItem

    fake_item = MagicMock(spec=OrderItem)
    fake_item.product_id = "sleep_gummies"
    fake_item.name_ar = "علكة النوم بالميلاتونين ضد الأرق"
    fake_item.offer_quantity = 3
    fake_item.price_sar = 349

    fake_order = MagicMock(spec=Order)
    fake_order.order_number = "SH-20260625-000001"
    fake_order.total_sar = 349
    fake_order.status = "new"
    fake_order.items = [fake_item]

    mock_create.return_value = fake_order
    mock_upsell.return_value = fake_order
    mock_summary.return_value = {
        "ok": True,
        "order_id": "SH-20260625-000001",
        "status": "new",
        "total_sar": 349,
        "product_names": ["علكة النوم بالميلاتونين ضد الأرق"],
    }


# ---------------------------------------------------------------------------
# Shared test data helpers
# ---------------------------------------------------------------------------


def valid_order_payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "أحمد العمري",
        "phone": "0512345678",
        "items": [
            {
                "product_id": "sleep_gummies",
                "slug": "sleep-melatonin-gummies",
                "offer_id": "sleep_3",
                "offer_quantity": 3,
                "price_sar": 349,
                "added_from": "pdp",
            }
        ],
        "currency": "SAR",
        "event_id": str(uuid.uuid4()),
    }
    base.update(overrides)
    return base
