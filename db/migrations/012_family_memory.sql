-- ============================================================
-- FamApp – migration 012: memoria familiar
-- ============================================================
-- Notas de contexto persistente: preferencias, alergias,
-- médicos de cabecera, datos importantes de cada miembro.
-- "Gaetano no come mariscos" → family_note con subject="gaetano"
-- "¿qué recordás de Giuseppe?" → query por subject
-- ============================================================

create table if not exists family_notes (
    id         uuid primary key default gen_random_uuid(),
    subject    text not null default 'general',   -- nickname o categoría ("gaetano", "salud", "general")
    note       text not null,
    added_by   text,                              -- número o nickname de quien anotó
    created_at timestamptz not null default now()
);

create index if not exists family_notes_subject_idx on family_notes (subject);

-- RLS
alter table family_notes enable row level security;

create policy "auth_users_all_family_notes" on family_notes
    for all to authenticated using (true) with check (true);
