-- ============================================================
-- FamApp – migration 007: schema alignment for places/routines
-- Ensures API payload fields exist in Supabase tables.
-- ============================================================

alter table if exists known_places
    add column if not exists place_type text not null default 'general';

alter table if exists family_routines
    add column if not exists children text[] not null default '{}';
