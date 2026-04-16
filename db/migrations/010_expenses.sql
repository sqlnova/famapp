-- ============================================================
-- FamApp – migration 010: registro de gastos familiares
-- ============================================================
-- Tabla para rastrear gastos del hogar desde WhatsApp.
-- "Anoté $8500 en el súper" → expense row con categoría auto-detectada.
-- ============================================================

create table if not exists expenses (
    id          uuid primary key default gen_random_uuid(),
    description text not null,
    amount      numeric(12, 2) not null,
    category    text not null default 'General',   -- Supermercado, Servicios, Salud, etc.
    paid_by     text,                               -- nickname del que pagó (puede ser null)
    expense_date date not null default current_date,
    notes       text,
    created_at  timestamptz not null default now()
);

create index if not exists expenses_date_idx      on expenses (expense_date desc);
create index if not exists expenses_category_idx  on expenses (category);
create index if not exists expenses_paid_by_idx   on expenses (paid_by);

-- RLS: sólo usuarios autenticados
alter table expenses enable row level security;

create policy "auth_users_all_expenses" on expenses
    for all to authenticated using (true) with check (true);
