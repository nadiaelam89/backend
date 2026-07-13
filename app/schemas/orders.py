from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.services.pricing import ACCEPTED_PRODUCT_IDS, VALID_PRODUCTS, canonical_product_id

PaymentMethodType = Literal["cod"]


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
        if v not in ACCEPTED_PRODUCT_IDS:
            raise ValueError(
                f"Unknown product_id '{v}'. Valid: {sorted(ACCEPTED_PRODUCT_IDS)}"
            )
        return canonical_product_id(v)


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class CreateOrderRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    phone: str = Field(..., description="Saudi phone number in any accepted format")
    city: str = Field(default="", max_length=60)
    address: str = Field(default="", max_length=200)
    email: str | None = Field(default=None, max_length=120)
    payment_method: PaymentMethodType = "cod"
    items: list[OrderItemRequest] = Field(..., min_length=1)
    currency: Literal["SAR"] = "SAR"
    source_url: str | None = None
    utm: UTMData | None = None
    event_id: UUID = Field(..., description="Client-generated idempotency UUID")
    fbp: str | None = None
    fbc: str | None = None
    ttp: str | None = None
    client_user_agent: str | None = None

    @field_validator("city", "address")
    @classmethod
    def validate_address_for_checkout(cls, v: str, info) -> str:
        return v.strip()


class UpsellRequest(BaseModel):
    product_id: str = Field(..., description="Upsell product to add")
    price_sar: int = Field(..., gt=0)
    event_id: UUID

    @field_validator("product_id")
    @classmethod
    def validate_product_id(cls, v: str) -> str:
        if v not in ACCEPTED_PRODUCT_IDS:
            raise ValueError(f"Unknown product_id '{v}'.")
        return canonical_product_id(v)


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
    subtotal_sar: int = 0
    cod_fee_sar: int = 0
    payment_method: PaymentMethodType = "cod"
    payment_status: str = "pending_confirmation"
    eligible_upsell: EligibleUpsell | None = None
    eligible_upsells: list[EligibleUpsell] = Field(default_factory=list)


class PaymentStatusResponse(BaseModel):
    ok: bool = True
    order_id: str
    payment_status: str
    payment_method: PaymentMethodType
    total_sar: int


class UpsellResponse(BaseModel):
    ok: bool = True
    order_id: str
    new_total_sar: int


class OrderSummaryItem(BaseModel):
    product_id: str
    name_ar: str
    price_sar: int
    quantity: int = 1


class OrderSummaryResponse(BaseModel):
    ok: bool = True
    order_id: str
    event_id: str
    status: str
    total_sar: int
    product_names: list[str]
    items: list[OrderSummaryItem] = Field(default_factory=list)
    eligible_upsell_product_ids: list[str] = Field(default_factory=list)
