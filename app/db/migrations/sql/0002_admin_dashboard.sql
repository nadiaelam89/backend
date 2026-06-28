-- Sukoon Health admin dashboard migration
-- Run on PostgreSQL production database (EasyPanel)

ALTER TABLE orders
ADD COLUMN IF NOT EXISTS client_country TEXT;

CREATE TABLE IF NOT EXISTS site_events (
    id UUID PRIMARY KEY,
    session_id TEXT NOT NULL,
    event_name TEXT NOT NULL,
    page_path TEXT,
    product_id TEXT,
    value_sar INTEGER,
    utm JSONB,
    client_ip TEXT,
    client_country TEXT,
    client_user_agent TEXT,
    is_valid_traffic BOOLEAN NOT NULL DEFAULT FALSE,
    fraud_reason TEXT,
    risk_score DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_site_events_session_id ON site_events (session_id);
CREATE INDEX IF NOT EXISTS ix_site_events_event_name ON site_events (event_name);
CREATE INDEX IF NOT EXISTS ix_site_events_is_valid_traffic ON site_events (is_valid_traffic);
CREATE INDEX IF NOT EXISTS ix_site_events_created_at ON site_events (created_at);
