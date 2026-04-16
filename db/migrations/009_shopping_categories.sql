-- ============================================================
-- FamApp – migration 009: categorías en lista de compras
-- ============================================================
-- Agrega una columna category a shopping_items para poder
-- agrupar por sección (Lácteos, Almacén, Verdulería, etc.)
-- y una columna times_purchased para detectar ítems recurrentes.
-- ============================================================

alter table shopping_items
    add column if not exists category text not null default 'Otros';

alter table shopping_items
    add column if not exists times_purchased int not null default 0;

-- Índice para filtrar por categoría
create index if not exists shopping_items_category_idx on shopping_items (category);
