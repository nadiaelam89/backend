from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# Portable column types: native UUID + JSONB on PostgreSQL (production),
# and generic UUID/JSON on other backends like SQLite (local development).
UUIDType = Uuid(as_uuid=True)
JSONType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    order_number: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="new")

    customer_name: Mapped[str] = mapped_column(Text, nullable=False)
    phone_local: Mapped[str] = mapped_column(Text, nullable=False)
    phone_e164: Mapped[str] = mapped_column(Text, nullable=False)
    phone_hash_sha256: Mapped[str] = mapped_column(Text, nullable=False)

    currency: Mapped[str] = mapped_column(Text, nullable=False, default="SAR")
    subtotal_sar: Mapped[int] = mapped_column(Integer, nullable=False)
    delivery_fee_sar: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_sar: Mapped[int] = mapped_column(Integer, nullable=False)

    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    utm: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    event_id: Mapped[str] = mapped_column(Text, nullable=False)
    fbp: Mapped[str | None] = mapped_column(Text, nullable=True)
    fbc: Mapped[str | None] = mapped_column(Text, nullable=True)
    ttp: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_ip: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    sheet_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sheet_response: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    items: Mapped[list[OrderItem]] = relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan"
    )
    analytics_events: Mapped[list[AnalyticsEvent]] = relationship(
        "AnalyticsEvent", back_populates="order"
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )

    product_id: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name_ar: Mapped[str] = mapped_column(Text, nullable=False)
    offer_id: Mapped[str] = mapped_column(Text, nullable=False)
    offer_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_context: Mapped[str] = mapped_column(Text, nullable=False, default="standard_offer")
    price_sar: Mapped[int] = mapped_column(Integer, nullable=False)
    added_from: Mapped[str] = mapped_column(Text, nullable=False, default="pdp")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    order: Mapped[Order] = relationship("Order", back_populates="items")


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True
    )

    event_id: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    event_name: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONType, nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    order: Mapped[Order | None] = relationship("Order", back_populates="analytics_events")
