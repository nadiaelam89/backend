"""Ad redirect slugs for /ads/{slug} links

Revision ID: 0004_ad_redirects
Revises: 0003_checkout_v2
Create Date: 2026-07-09
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_ad_redirects"
down_revision = "0003_checkout_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ad_redirects" in inspector.get_table_names():
        return

    op.create_table(
        "ad_redirects",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("target_path", sa.Text(), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_ad_redirects_slug", "ad_redirects", ["slug"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ad_redirects" not in inspector.get_table_names():
        return

    op.drop_index("ix_ad_redirects_slug", table_name="ad_redirects")
    op.drop_table("ad_redirects")
