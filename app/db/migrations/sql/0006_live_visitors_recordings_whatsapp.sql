-- Live visitors, session recordings, WhatsApp inbox
-- Run on production if not using Alembic auto-migrate

CREATE TABLE IF NOT EXISTS visitor_presence (
    session_id TEXT PRIMARY KEY,
    page_path TEXT,
    client_ip TEXT,
    client_country TEXT,
    client_user_agent TEXT,
    is_valid_traffic BOOLEAN NOT NULL DEFAULT false,
    fraud_reason TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_visitor_presence_client_ip ON visitor_presence (client_ip);
CREATE INDEX IF NOT EXISTS ix_visitor_presence_client_country ON visitor_presence (client_country);
CREATE INDEX IF NOT EXISTS ix_visitor_presence_last_seen_at ON visitor_presence (last_seen_at);

CREATE TABLE IF NOT EXISTS session_recordings (
    id UUID PRIMARY KEY,
    session_id TEXT NOT NULL,
    page_path TEXT,
    client_ip TEXT,
    client_country TEXT,
    client_user_agent TEXT,
    event_count INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'recording',
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_session_recordings_session_id ON session_recordings (session_id);
CREATE INDEX IF NOT EXISTS ix_session_recordings_started_at ON session_recordings (started_at);

CREATE TABLE IF NOT EXISTS session_recording_chunks (
    id UUID PRIMARY KEY,
    recording_id UUID NOT NULL REFERENCES session_recordings(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    events_json TEXT NOT NULL,
    event_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_session_recording_chunks_recording_id ON session_recording_chunks (recording_id);

CREATE TABLE IF NOT EXISTS whatsapp_conversations (
    id UUID PRIMARY KEY,
    wa_id TEXT NOT NULL UNIQUE,
    customer_name TEXT,
    customer_phone TEXT,
    last_message_preview TEXT,
    unread_count INTEGER NOT NULL DEFAULT 0,
    last_message_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_whatsapp_conversations_wa_id ON whatsapp_conversations (wa_id);
CREATE INDEX IF NOT EXISTS ix_whatsapp_conversations_last_message_at ON whatsapp_conversations (last_message_at);

CREATE TABLE IF NOT EXISTS whatsapp_messages (
    id UUID PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES whatsapp_conversations(id) ON DELETE CASCADE,
    direction TEXT NOT NULL,
    body TEXT NOT NULL,
    wa_message_id TEXT,
    status TEXT NOT NULL DEFAULT 'received',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_whatsapp_messages_conversation_id ON whatsapp_messages (conversation_id);
CREATE INDEX IF NOT EXISTS ix_whatsapp_messages_wa_message_id ON whatsapp_messages (wa_message_id);
CREATE INDEX IF NOT EXISTS ix_whatsapp_messages_created_at ON whatsapp_messages (created_at);
