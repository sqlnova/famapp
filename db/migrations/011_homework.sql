-- ============================================================
-- FamApp – migration 011: tareas escolares
-- ============================================================
-- Permite registrar tareas de chicos por WhatsApp.
-- "Giuseppe tiene que entregar la maqueta el viernes"
-- ============================================================

create table if not exists homework_tasks (
    id          uuid primary key default gen_random_uuid(),
    child_name  text not null,                      -- nombre del chico (ej: "Giuseppe")
    subject     text not null default 'General',    -- materia (ej: "Matemáticas")
    description text not null,                      -- detalle de la tarea
    due_date    date not null,
    done        boolean not null default false,
    added_by    text,                               -- número o nickname de quien anotó
    done_at     timestamptz,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

create index if not exists homework_done_idx     on homework_tasks (done);
create index if not exists homework_due_date_idx on homework_tasks (due_date);
create index if not exists homework_child_idx    on homework_tasks (child_name);

create trigger homework_updated_at
    before update on homework_tasks
    for each row execute procedure set_updated_at();

-- RLS
alter table homework_tasks enable row level security;

create policy "auth_users_all_homework" on homework_tasks
    for all to authenticated using (true) with check (true);
