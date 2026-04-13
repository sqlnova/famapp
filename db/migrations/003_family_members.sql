-- ============================================================
-- FamApp – migration 003: family members + logistics responsible
-- ============================================================

-- ── family_members ────────────────────────────────────────────
-- One row per family member. The nickname (e.g. "papa", "mama")
-- is what gets stored in calendar event descriptions and used
-- throughout the system to route notifications.
create table if not exists family_members (
    id              uuid primary key default gen_random_uuid(),
    name            text not null,           -- display name: "Papá", "Mamá"
    nickname        text not null unique,    -- short slug: "papa", "mama"
    whatsapp_number text not null,           -- whatsapp:+54911...
    created_at      timestamptz not null default now()
);

-- ── logistics_alerts: add responsible column ─────────────────
-- Stores the WhatsApp number of whoever should receive this alert.
-- NULL means "broadcast to everyone".
alter table logistics_alerts
    add column if not exists responsible_whatsapp text;
