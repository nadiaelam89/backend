"""Optional comment on ad redirects

Revision ID: 0005_ad_redirect_comment
Revises: 0004_ad_redirects
Create Date: 2026-07-10
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005_ad_redirect_comment"
down_revision = "0004_ad_redirects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ad_redirects" not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns("ad_redirects")}
    if "comment" not in columns:
        op.add_column("ad_redirects", sa.Column("comment", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ad_redirects" not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns("ad_redirects")}
    if "comment" in columns:
        op.drop_column("ad_redirects", "comment")
