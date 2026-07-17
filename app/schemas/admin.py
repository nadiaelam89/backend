from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AdminLoginRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=80)
    password: str = Field(..., min_length=4, max_length=120)


class AdminLoginResponse(BaseModel):
    ok: bool = True
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class AdminDailyTrendItem(BaseModel):
    date: str
    orders: int
    revenue_sar: int


class AdminChannelRevenueItem(BaseModel):
    channel: str
    orders: int
    revenue_sar: int


class AdminMetricsResponse(BaseModel):
    ok: bool = True
    date_from: datetime
    date_to: datetime
    page_views: int
    product_views: int
    add_to_carts: int
    initiate_checkouts: int
    orders: int
    upsells: int
    upsell_take_rate: float
    revenue_sar: int
    average_order_value_sar: float
    average_pieces_per_order: float
    conversion_rate: float
    checkout_conversion_rate: float
    unique_sessions: int
    blocked_events: int
    valid_events: int
    last_event_at: datetime | None = None
    latest_event_at: datetime | None = None
    daily_trend: list[AdminDailyTrendItem]
    channel_revenue: list[AdminChannelRevenueItem]


class AdminOrderItem(BaseModel):
    product_id: str
    name_ar: str
    slug: str
    offer_id: str
    offer_quantity: int
    price_sar: int
    added_from: str
    unit_context: str


class AdminOrderListItem(BaseModel):
    order_id: str
    status: str
    customer_name: str
    phone_local: str
    total_sar: int
    item_count: int
    product_names: list[str]
    client_country: str | None
    utm_source: str | None
    created_at: datetime


class AdminOrdersListResponse(BaseModel):
    ok: bool = True
    total: int
    page: int
    page_size: int
    orders: list[AdminOrderListItem]


class AdminPurgeDataResponse(BaseModel):
    ok: bool = True
    deleted: dict[str, int]


class AdminOrderDetailResponse(BaseModel):
    ok: bool = True
    order_id: str
    status: str
    customer_name: str
    phone_local: str
    phone_e164: str
    currency: str
    subtotal_sar: int
    delivery_fee_sar: int
    total_sar: int
    source_url: str | None
    utm: dict | None
    client_ip: str | None
    client_country: str | None
    client_user_agent: str | None
    sheet_sent_at: datetime | None
    created_at: datetime
    updated_at: datetime
    items: list[AdminOrderItem]
