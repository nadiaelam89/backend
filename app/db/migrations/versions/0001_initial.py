"""Initial schema: orders, order_items, analytics_events

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-25 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_number", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="new"),
        sa.Column("customer_name", sa.Text(), nullable=False),
        sa.Column("phone_local", sa.Text(), nullable=False),
        sa.Column("phone_e164", sa.Text(), nullable=False),
        sa.Column("phone_hash_sha256", sa.Text(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False, server_default="SAR"),
        sa.Column("subtotal_sar", sa.Integer(), nullable=False),
        sa.Column("delivery_fee_sar", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_sar", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("utm", postgresql.JSONB(), nullable=True),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("fbp", sa.Text(), nullable=True),
        sa.Column("fbc", sa.Text(), nullable=True),
        sa.Column("ttp", sa.Text(), nullable=True),
        sa.Column("client_ip", sa.Text(), nullable=True),
        sa.Column("client_user_agent", sa.Text(), nullable=True),
        sa.Column("sheet_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sheet_response", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_orders_order_number", "orders", ["order_number"], unique=True)

    op.create_table(
        "order_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("product_id", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name_ar", sa.Text(), nullable=False),
        sa.Column("offer_id", sa.Text(), nullable=False),
        sa.Column("offer_quantity", sa.Integer(), nullable=False),
        sa.Column("unit_context", sa.Text(), nullable=False, server_default="standard_offer"),
        sa.Column("price_sar", sa.Integer(), nullable=False),
        sa.Column("added_from", sa.Text(), nullable=False, server_default="pdp"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])

    op.create_table(
        "analytics_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("event_name", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_analytics_events_order_id", "analytics_events", ["order_id"])


def downgrade() -> None:
    op.drop_table("analytics_events")
    op.drop_table("order_items")
    op.drop_table("orders")
