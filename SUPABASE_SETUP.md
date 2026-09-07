# Подключение Supabase

## 1. Создать таблицу

Supabase -> SQL Editor -> New query -> вставить содержимое `SUPABASE_SQL.sql` -> Run.

## 2. Взять URL и server secret

В Supabase открой настройки проекта / API и скопируй:

- Project URL -> `SUPABASE_URL`
- server-side secret/service-role key -> `SUPABASE_KEY`

Не используй этот secret во frontend и не добавляй его в GitHub.

## 3. Добавить в Render

Render -> mavis-operational-dashboard -> Environment:

```text
SUPABASE_URL=...
SUPABASE_KEY=...
```

Save and deploy.

## 4. Проверка

Открой:

```text
https://mavis-operational-dashboard.onrender.com/health
```

Если `storage = Supabase`, постоянное хранилище работает.

## 5. Важно для бесплатного Render

После успешной проверки Supabase persistent disk на Render больше не нужен. Удали disk и переключи instance на Free, если старый сервис был создан на Starter.
