from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from app.db.models import Order, OrderItem
from app.services.capi.meta import build_meta_purchase_payload
from app.services.capi.snap import build_snap_purchase_payload
from app.services.capi.tiktok import build_tiktok_purchase_payload
from app.services.hashing import sha256_lower


def _sample_order() -> Order:
    item = MagicMock(spec=OrderItem)
    item.product_id = "magnesium_gummies"
    item.name_ar = "علكة المغنيسيوم"
    item.offer_quantity = 3
    item.price_sar = 449

    order = MagicMock(spec=Order)
    order.order_number = "SH-20260625-000001"
    order.event_id = str(uuid.uuid4())
    order.currency = "SAR"
    order.total_sar = 449
    order.source_url = "https://sukoonhealth.shop/checkout"
    order.fbp = "fb.1.123"
    order.fbc = "fb.1.456"
    order.ttp = "ttp.1.789"
    order.client_ip = "203.0.113.10"
    order.client_user_agent = "Mozilla/5.0 Test"
    order.items = [item]
    return order


@pytest.fixture
def phone_hash() -> str:
    return sha256_lower("966512345678")


def test_meta_purchase_payload_shape(phone_hash: str) -> None:
    order = _sample_order()
    payload = build_meta_purchase_payload(order, phone_hash, "token", "pixel123")

    event = payload["data"][0]
    assert event["event_name"] == "Purchase"
    assert event["event_id"] == order.event_id
    assert event["action_source"] == "website"
    assert event["event_source_url"] == order.source_url
    assert event["user_data"]["ph"] == [phone_hash]
    assert event["user_data"]["fbp"] == order.fbp
    assert event["custom_data"]["value"] == 449
    assert event["custom_data"]["contents"][0]["id"] == "magnesium_gummies"


def test_tiktok_purchase_payload_shape(phone_hash: str) -> None:
    order = _sample_order()
    payload = build_tiktok_purchase_payload(order, phone_hash, "PIXELCODE")

    assert payload["event_source"] == "web"
    assert payload["event_source_id"] == "PIXELCODE"
    event = payload["data"][0]
    assert event["event"] == "CompletePayment"
    assert event["event_id"] == order.event_id
    assert event["user"]["phone_number"] == phone_hash
    assert event["user"]["ttp"] == order.ttp
    assert event["properties"]["order_id"] == order.order_number


def test_snap_v3_purchase_payload_shape(phone_hash: str) -> None:
    order = _sample_order()
    payload = build_snap_purchase_payload(order, phone_hash)

    event = payload["data"][0]
    assert event["event_name"] == "PURCHASE"
    assert event["event_id"] == order.event_id
    assert event["action_source"] == "WEB"
    assert event["user_data"]["ph"] == [phone_hash]
    assert event["custom_data"]["value"] == 449
    assert event["custom_data"]["content_ids"] == ["magnesium_gummies"]
