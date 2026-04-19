-- ============================================================
-- FamApp – migration 013: learning layer del planner
-- ============================================================
-- Tres tablas que cierran el loop de aprendizaje del copiloto:
--
--   plan_feedback  — señales crudas: qué hizo el usuario con cada bloque
--                    del plan (aceptar, cambiar responsable, ignorar).
--   preference_profiles
--                  — afinidades agregadas (responsable × lugar × tipo),
--                    calculadas a partir de plan_feedback. Alimentan el
--                    asignador determinista.
--   support_network_members
--                  — terceros de confianza (abuelos, nannies, vecinos,
--                    carpools) que pueden cubrir logística cuando el
--                    núcleo está ocupado.
-- ============================================================

-- ── Red de apoyo extendida ───────────────────────────────────
create table if not exists support_network_members (
    id                uuid primary key default gen_random_uuid(),
    name              text not null,
    nickname          text not null unique,
    role              text not null default 'other',
    can_drive         boolean not null default true,
    allowed_kinds     text[] not null default '{}',
    allowed_children  text[] not null default '{}',
    trust_level       numeric(3,2) not null default 0.5,
    contactable_via   text,
    notes             text,
    is_active         boolean not null default true,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now()
);

create index if not exists support_network_active_idx
    on support_network_members (is_active);

-- ── Preferencias aprendidas ──────────────────────────────────
create table if not exists preference_profiles (
    id               uuid primary key default gen_random_uuid(),
    member_nickname  text not null,
    place_alias      text,
    block_kind       text,
    weekday          smallint,
    score            numeric(4,3) not null default 0.5,
    sample_size      integer not null default 0,
    last_updated     timestamptz not null default now(),
    unique (member_nickname, place_alias, block_kind, weekday)
);

create index if not exists preference_profiles_member_idx
    on preference_profiles (member_nickname);

-- ── Feedback del plan ────────────────────────────────────────
create table if not exists plan_feedback (
    id              uuid primary key default gen_random_uuid(),
    plan_date       date not null,
    block_id        uuid,
    user_nickname   text not null,
    action          text not null,       -- accept | override | edit | ignore
    old_responsible text,
    new_responsible text,
    place_alias     text,
    block_kind      text,
    weekday         smallint,
    delta           jsonb not null default '{}'::jsonb,
    created_at      timestamptz not null default now()
);

create index if not exists plan_feedback_date_idx   on plan_feedback (plan_date desc);
create index if not exists plan_feedback_block_idx  on plan_feedback (block_id);
create index if not exists plan_feedback_member_idx on plan_feedback (new_responsible);

-- ── RLS ──────────────────────────────────────────────────────
alter table support_network_members enable row level security;
alter table preference_profiles      enable row level security;
alter table plan_feedback            enable row level security;

create policy "auth_users_all_support_network" on support_network_members
    for all to authenticated using (true) with check (true);

create policy "auth_users_all_preference_profiles" on preference_profiles
    for all to authenticated using (true) with check (true);

create policy "auth_users_all_plan_feedback" on plan_feedback
    for all to authenticated using (true) with check (true);
