from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SiteEventName = Literal[
    "PageView",
    "ViewContent",
    "AddToCart",
    "InitiateCheckout",
    "UpsellAccepted",
]


class TrackEventRequest(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=80)
    event_name: SiteEventName
    page_path: str | None = None
    product_id: str | None = None
    value_sar: int | None = Field(default=None, ge=0)
    utm: dict | None = None
    client_user_agent: str | None = None


class TrackEventResponse(BaseModel):
    ok: bool = True
    is_valid_traffic: bool
