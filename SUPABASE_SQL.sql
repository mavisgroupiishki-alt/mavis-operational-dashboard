-- Выполнить один раз в Supabase -> SQL Editor.
-- Таблица хранит планы, комментарии, ручной NPS, состав команды и настройки.

create table if not exists public.mavis_dashboard_kv (
  key text primary key,
  value jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

alter table public.mavis_dashboard_kv enable row level security;

-- Приложение использует только серверный SUPABASE_KEY (service role / secret key),
-- поэтому публичные RLS policies создавать не нужно.
