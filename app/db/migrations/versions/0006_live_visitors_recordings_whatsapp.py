"""Live visitors, session recordings, WhatsApp inbox

Revision ID: 0006_live_ops
Revises: 0005_ad_redirect_comment
Create Date: 2026-09-12
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0006_live_ops"
down_revision = "0005_ad_redirect_comment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "visitor_presence",
        sa.Column("session_id", sa.Text(), primary_key=True),
        sa.Column("page_path", sa.Text(), nullable=True),
        sa.Column("client_ip", sa.Text(), nullable=True),
        sa.Column("client_country", sa.Text(), nullable=True),
        sa.Column("client_user_agent", sa.Text(), nullable=True),
        sa.Column("is_valid_traffic", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fraud_reason", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_visitor_presence_client_ip", "visitor_presence", ["client_ip"])
    op.create_index("ix_visitor_presence_client_country", "visitor_presence", ["client_country"])
    op.create_index("ix_visitor_presence_last_seen_at", "visitor_presence", ["last_seen_at"])

    op.create_table(
        "session_recordings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("page_path", sa.Text(), nullable=True),
        sa.Column("client_ip", sa.Text(), nullable=True),
        sa.Column("client_country", sa.Text(), nullable=True),
        sa.Column("client_user_agent", sa.Text(), nullable=True),
        sa.Column("event_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.Text(), nullable=False, server_default="recording"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_session_recordings_session_id", "session_recordings", ["session_id"])
    op.create_index("ix_session_recordings_started_at", "session_recordings", ["started_at"])

    op.create_table(
        "session_recording_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("recording_id", sa.Uuid(), sa.ForeignKey("session_recordings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("events_json", sa.Text(), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_session_recording_chunks_recording_id", "session_recording_chunks", ["recording_id"])

    op.create_table(
        "whatsapp_conversations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("wa_id", sa.Text(), nullable=False),
        sa.Column("customer_name", sa.Text(), nullable=True),
        sa.Column("customer_phone", sa.Text(), nullable=True),
        sa.Column("last_message_preview", sa.Text(), nullable=True),
        sa.Column("unread_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_whatsapp_conversations_wa_id", "whatsapp_conversations", ["wa_id"], unique=True)
    op.create_index("ix_whatsapp_conversations_last_message_at", "whatsapp_conversations", ["last_message_at"])

    op.create_table(
        "whatsapp_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("whatsapp_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("wa_message_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="received"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_whatsapp_messages_conversation_id", "whatsapp_messages", ["conversation_id"])
    op.create_index("ix_whatsapp_messages_wa_message_id", "whatsapp_messages", ["wa_message_id"])
    op.create_index("ix_whatsapp_messages_created_at", "whatsapp_messages", ["created_at"])


def downgrade() -> None:
    op.drop_table("whatsapp_messages")
    op.drop_table("whatsapp_conversations")
    op.drop_table("session_recording_chunks")
    op.drop_table("session_recordings")
    op.drop_table("visitor_presence")
