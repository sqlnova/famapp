-- ============================================================
-- FamApp – migration 005: minor members + known places
-- ============================================================

-- ── family_members: mark minors ───────────────────────────────
-- is_minor = true  → the "llevar + retirar" rule applies automatically
-- is_minor = false → adult (papa, mama, abuelos, etc.)
alter table family_members
    add column if not exists is_minor boolean not null default false;

-- ── known_places ──────────────────────────────────────────────
-- Stores short aliases (e.g. "colegio", "club") mapped to full
-- addresses used by the schedule and logistics agents.
create table if not exists known_places (
    id         uuid primary key default gen_random_uuid(),
    alias      text not null unique,   -- short name: "colegio", "club"
    name       text not null,          -- display name: "Club Regatas Resistencia"
    address    text not null,          -- full address for Google Maps
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create trigger known_places_updated_at
    before update on known_places
    for each row execute procedure set_updated_at();
