-- ============================================================
-- FamApp – migration 002: daily summary + shopping improvements
-- ============================================================

-- ── daily_summaries ──────────────────────────────────────────
-- Tracks which days already had a morning summary sent.
create table if not exists daily_summaries (
    id         uuid primary key default gen_random_uuid(),
    summary_date date not null unique,
    sent_at    timestamptz not null default now(),
    content    text
);

-- ── shopping_items: add notes + store columns ─────────────────
alter table shopping_items
    add column if not exists notes text,
    add column if not exists store text,
    add column if not exists done_at timestamptz;

-- ── logistics_alerts: add event context columns ───────────────
-- Needed so due-alert messages can show the event name and time.
alter table logistics_alerts
    add column if not exists event_title    text,
    add column if not exists event_start_utc timestamptz;
