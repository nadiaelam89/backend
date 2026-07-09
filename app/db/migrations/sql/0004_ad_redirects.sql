-- Run on production if not using Alembic auto-migrate
CREATE TABLE IF NOT EXISTS ad_redirects (
    id UUID PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    target_path TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_ad_redirects_slug ON ad_redirects (slug);
