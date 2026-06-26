from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.services.pricing import VALID_PRODUCTS


# ---------------------------------------------------------------------------
# Sub-schemas
# ---------------------------------------------------------------------------


class UTMData(BaseModel):
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_content: str | None = None
    utm_term: str | None = None

    model_config = {"extra": "allow"}


class OrderItemRequest(BaseModel):
    product_id: str = Field(..., description="Product identifier key")
    slug: str = Field(..., description="Product URL slug")
    offer_id: str = Field(..., description="Offer identifier")
    offer_quantity: int = Field(..., ge=1, le=3)
    price_sar: int = Field(..., gt=0)
    added_from: str = Field(default="pdp")

    @field_validator("product_id")
    @classmethod
    def validate_product_id(cls, v: str) -> str:
        if v not in VALID_PRODUCTS:
            raise ValueError(f"Unknown product_id '{v}'. Valid: {sorted(VALID_PRODUCTS)}")
        return v


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class CreateOrderRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    phone: str = Field(..., description="Saudi phone number in any accepted format")
    items: list[OrderItemRequest] = Field(..., min_length=1)
    currency: Literal["SAR"] = "SAR"
    source_url: str | None = None
    utm: UTMData | None = None
    event_id: UUID = Field(..., description="Client-generated idempotency UUID")
    fbp: str | None = None
    fbc: str | None = None
    ttp: str | None = None
    client_user_agent: str | None = None


class UpsellRequest(BaseModel):
    product_id: str = Field(..., description="Upsell product to add")
    price_sar: int = Field(..., gt=0)
    event_id: UUID

    @field_validator("product_id")
    @classmethod
    def validate_product_id(cls, v: str) -> str:
        if v not in VALID_PRODUCTS:
            raise ValueError(f"Unknown product_id '{v}'.")
        return v


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class EligibleUpsell(BaseModel):
    product_id: str
    price_sar: int
    expires_in_seconds: int


class CreateOrderResponse(BaseModel):
    ok: bool = True
    order_id: str
    event_id: UUID
    total_sar: int
    eligible_upsell: EligibleUpsell | None = None


class UpsellResponse(BaseModel):
    ok: bool = True
    order_id: str
    new_total_sar: int


class OrderSummaryResponse(BaseModel):
    ok: bool = True
    order_id: str
    status: str
    total_sar: int
    product_names: list[str]
