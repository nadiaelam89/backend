"""Checkout V2: payment methods, address, COD fee

Revision ID: 0003_checkout_v2
Revises: 0002_admin_dashboard
Create Date: 2026-06-30
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_checkout_v2"
down_revision = "0002_admin_dashboard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("cod_fee_sar", sa.Integer(), nullable=False, server_default="0"))
    op.add_column(
        "orders",
        sa.Column("payment_method", sa.Text(), nullable=False, server_default="cod"),
    )
    op.add_column(
        "orders",
        sa.Column("payment_status", sa.Text(), nullable=False, server_default="pending_confirmation"),
    )
    op.add_column("orders", sa.Column("city", sa.Text(), nullable=True))
    op.add_column("orders", sa.Column("address", sa.Text(), nullable=True))
    op.add_column("orders", sa.Column("customer_email", sa.Text(), nullable=True))
    op.add_column("orders", sa.Column("stripe_payment_intent_id", sa.Text(), nullable=True))
    op.add_column("orders", sa.Column("tabby_payment_id", sa.Text(), nullable=True))
    op.add_column("orders", sa.Column("tabby_session_id", sa.Text(), nullable=True))
    op.add_column("orders", sa.Column("tamara_order_id", sa.Text(), nullable=True))
    op.add_column("orders", sa.Column("tamara_checkout_id", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "tamara_checkout_id")
    op.drop_column("orders", "tamara_order_id")
    op.drop_column("orders", "tabby_session_id")
    op.drop_column("orders", "tabby_payment_id")
    op.drop_column("orders", "stripe_payment_intent_id")
    op.drop_column("orders", "customer_email")
    op.drop_column("orders", "address")
    op.drop_column("orders", "city")
    op.drop_column("orders", "payment_status")
    op.drop_column("orders", "payment_method")
    op.drop_column("orders", "cod_fee_sar")
