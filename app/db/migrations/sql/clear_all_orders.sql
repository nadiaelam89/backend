-- Clear all orders and tracking data (IRREVERSIBLE)
-- Run in EasyPanel Postgres terminal: psql -U sukoonhealth -d sukoonhealth

DELETE FROM analytics_events;
DELETE FROM order_items;
DELETE FROM site_events;
DELETE FROM orders;
