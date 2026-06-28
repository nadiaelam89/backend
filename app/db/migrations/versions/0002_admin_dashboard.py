"""Admin dashboard: site_events + orders.client_country

Revision ID: 0002_admin_dashboard
Revises: 0001_initial
Create Date: 2026-06-28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_admin_dashboard"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("client_country", sa.Text(), nullable=True))

    op.create_table(
        "site_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("event_name", sa.Text(), nullable=False),
        sa.Column("page_path", sa.Text(), nullable=True),
        sa.Column("product_id", sa.Text(), nullable=True),
        sa.Column("value_sar", sa.Integer(), nullable=True),
        sa.Column("utm", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("client_ip", sa.Text(), nullable=True),
        sa.Column("client_country", sa.Text(), nullable=True),
        sa.Column("client_user_agent", sa.Text(), nullable=True),
        sa.Column("is_valid_traffic", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fraud_reason", sa.Text(), nullable=True),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_site_events_session_id", "site_events", ["session_id"])
    op.create_index("ix_site_events_event_name", "site_events", ["event_name"])
    op.create_index("ix_site_events_is_valid_traffic", "site_events", ["is_valid_traffic"])
    op.create_index("ix_site_events_created_at", "site_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_site_events_created_at", table_name="site_events")
    op.drop_index("ix_site_events_is_valid_traffic", table_name="site_events")
    op.drop_index("ix_site_events_event_name", table_name="site_events")
    op.drop_index("ix_site_events_session_id", table_name="site_events")
    op.drop_table("site_events")
    op.drop_column("orders", "client_country")
