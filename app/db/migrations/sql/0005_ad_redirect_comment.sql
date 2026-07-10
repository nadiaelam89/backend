-- Run on production if not using Alembic auto-migrate
ALTER TABLE ad_redirects ADD COLUMN IF NOT EXISTS comment TEXT;
