from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.orders import OrderItemRequest, PaymentMethodType, UTMData


class CheckoutPaymentRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    phone: str
    city: str = Field(..., min_length=2, max_length=60)
    address: str = Field(..., min_length=5, max_length=200)
    email: str | None = Field(default=None, max_length=120)
    items: list[OrderItemRequest] = Field(..., min_length=1)
    currency: Literal["SAR"] = "SAR"
    source_url: str | None = None
    utm: UTMData | None = None
    event_id: UUID
    fbp: str | None = None
    fbc: str | None = None
    ttp: str | None = None
    client_user_agent: str | None = None


class StripeIntentResponse(BaseModel):
    ok: bool = True
    client_secret: str
    order_id: str
    total_sar: int


class RedirectPaymentResponse(BaseModel):
    ok: bool = True
    order_id: str
    payment_url: str
    total_sar: int
