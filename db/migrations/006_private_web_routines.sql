-- ============================================================
-- FamApp – migration 006: private web app support
-- Adds family routines and UI helper columns.
-- ============================================================

alter table known_places
    add column if not exists place_type text not null default 'general';

create table if not exists family_routines (
    id uuid primary key default gen_random_uuid(),
    title text not null,
    days text[] not null default '{}',
    outbound_time text,
    return_time text,
    outbound_responsible text,
    return_responsible text,
    place_alias text,
    place_name text,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists family_routines_active_idx on family_routines (is_active);

create trigger family_routines_updated_at
    before update on family_routines
    for each row execute procedure set_updated_at();
