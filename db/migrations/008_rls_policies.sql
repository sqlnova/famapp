-- ============================================================
-- FamApp – migration 008: Row-Level Security (RLS)
-- ============================================================
-- Objetivo: restringir el acceso a datos sensibles sólo a usuarios
-- autenticados mediante Supabase Auth (JWT válido).
-- La SUPABASE_ANON_KEY se expone en el browser por diseño, pero sin
-- RLS cualquier visitante podría leer/escribir toda la base.
-- ============================================================

-- ── Habilitar RLS en todas las tablas con datos sensibles ─────

alter table messages            enable row level security;
alter table shopping_items      enable row level security;
alter table tasks               enable row level security;
alter table logistics_alerts    enable row level security;
alter table family_members      enable row level security;


-- ── Políticas para usuarios autenticados ─────────────────────
-- Cualquier usuario con un JWT válido de Supabase Auth puede
-- leer y escribir. El control de acceso más fino (por usuario)
-- queda fuera del alcance de este MVP familiar.

-- messages
create policy "auth_users_all_messages" on messages
    for all
    to authenticated
    using (true)
    with check (true);

-- shopping_items
create policy "auth_users_all_shopping" on shopping_items
    for all
    to authenticated
    using (true)
    with check (true);

-- tasks
create policy "auth_users_all_tasks" on tasks
    for all
    to authenticated
    using (true)
    with check (true);

-- logistics_alerts
create policy "auth_users_all_logistics_alerts" on logistics_alerts
    for all
    to authenticated
    using (true)
    with check (true);

-- family_members
create policy "auth_users_all_family_members" on family_members
    for all
    to authenticated
    using (true)
    with check (true);


-- ── Acceso de service_role (backend del servidor) ─────────────
-- La SERVICE_ROLE_KEY del backend bypasea RLS por defecto en
-- Supabase, por lo que no se necesitan políticas adicionales.
-- Documentado aquí para claridad:
--
--   get_supabase() → usa SERVICE_ROLE_KEY → RLS bypass ✓
--   browser (anon/jwt) → usa ANON_KEY + JWT → aplica RLS ✓


-- ── Tablas adicionales si existen (migrations 005-007) ────────

-- known_places
do $$ begin
    if exists (select 1 from information_schema.tables where table_name = 'known_places') then
        execute 'alter table known_places enable row level security';
        execute $pol$
            create policy "auth_users_all_known_places" on known_places
                for all to authenticated using (true) with check (true)
        $pol$;
    end if;
end $$;

-- family_routines
do $$ begin
    if exists (select 1 from information_schema.tables where table_name = 'family_routines') then
        execute 'alter table family_routines enable row level security';
        execute $pol$
            create policy "auth_users_all_family_routines" on family_routines
                for all to authenticated using (true) with check (true)
        $pol$;
    end if;
end $$;
