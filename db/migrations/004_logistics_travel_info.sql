-- ============================================================
-- FamApp – migration 004: logistics alert travel info
-- Adds travel_minutes and leave_at_utc so due-alert messages
-- can display the exact departure time and trip duration.
-- ============================================================

alter table logistics_alerts
    add column if not exists travel_minutes integer,
    add column if not exists leave_at_utc   timestamptz;
