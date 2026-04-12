-- ============================================================
-- FamApp – initial schema
-- Run in Supabase SQL editor or via CLI:
--   supabase db push
-- ============================================================

-- ── Extensions ───────────────────────────────────────────────
create extension if not exists "pgcrypto";

-- ── messages ─────────────────────────────────────────────────
-- Stores every incoming WhatsApp message and its processing result.
create table if not exists messages (
    id            uuid primary key default gen_random_uuid(),
    message_sid   text not null unique,
    from_number   text not null,
    body          text not null default '',
    intent        text,
    entities      jsonb,
    response      text,
    status        text not null default 'received'
                      check (status in ('received','processing','responded','failed')),
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now()
);

create index if not exists messages_from_number_idx on messages (from_number);
create index if not exists messages_created_at_idx  on messages (created_at desc);

-- auto-update updated_at
create or replace function set_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create trigger messages_updated_at
    before update on messages
    for each row execute procedure set_updated_at();


-- ── shopping_items ────────────────────────────────────────────
create table if not exists shopping_items (
    id         uuid primary key default gen_random_uuid(),
    name       text not null,
    quantity   text,
    unit       text,
    added_by   text,
    done       boolean not null default false,
    added_at   timestamptz not null default now()
);

create index if not exists shopping_items_done_idx on shopping_items (done);


-- ── tasks ─────────────────────────────────────────────────────
-- Generic task queue used by agents to hand off work.
create table if not exists tasks (
    id           uuid primary key default gen_random_uuid(),
    agent        text not null,     -- 'schedule' | 'logistics' | 'shopping'
    payload      jsonb not null,
    status       text not null default 'pending'
                     check (status in ('pending','in_progress','done','cancelled')),
    triggered_by text,              -- message_sid that originated this task
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);

create index if not exists tasks_agent_status_idx on tasks (agent, status);

create trigger tasks_updated_at
    before update on tasks
    for each row execute procedure set_updated_at();


-- ── logistics_alerts ─────────────────────────────────────────
-- Proactive "leave in N minutes" alerts scheduled by Logistics Agent.
create table if not exists logistics_alerts (
    id              uuid primary key default gen_random_uuid(),
    calendar_event_id text,
    destination     text not null,
    origin          text,
    scheduled_send  timestamptz not null,
    sent            boolean not null default false,
    send_to         text[],         -- array of whatsapp: numbers
    created_at      timestamptz not null default now()
);

create index if not exists logistics_alerts_scheduled_idx
    on logistics_alerts (scheduled_send)
    where sent = false;
