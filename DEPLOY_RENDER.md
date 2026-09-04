# Публикация MAVIS Dashboard на Render

## Цель
Один публично доступный URL, который можно открыть на телевизоре в офисе и у сотрудников. Изменение планов защищается `ADMIN_KEY`; при необходимости весь просмотр защищается `VIEW_PASSWORD`.

## Шаг 1 — репозиторий
Создай пустой приватный репозиторий, например `mavis-operational-dashboard`, и загрузи туда содержимое этой папки.

Не загружай `.env` — он исключён через `.gitignore`.

## Шаг 2 — Blueprint
Render Dashboard → **New → Blueprint** → выбрать репозиторий.

`render.yaml` уже задаёт:
- Docker runtime;
- регион Frankfurt;
- `/health`;
- `/var/data` для постоянного хранения планов;
- все названия environment variables.

## Шаг 3 — секреты
В Render заполнить:

```text
BITRIX_WEBHOOK=<webhook Bitrix>
BITRIX_EVENT_TOKEN=<случайный секрет>
ADMIN_KEY=<секрет редактирования планов>
VIEW_PASSWORD=<опционально: общий пароль для входа>
```

## Шаг 4 — Bitrix realtime
После получения URL Render настроить исходящий webhook / события CRM на:

```text
https://<service>.onrender.com/api/bitrix/event?token=<BITRIX_EVENT_TOKEN>
```

Основные события: создание и изменение сделки; для переносов между воронками контрольная синхронизация раз в 60 секунд остаётся страховкой.

## Шаг 5 — офисный экран
Открыть URL в Chrome → TV → полноэкранный режим браузера.

TV скрывает управляющие вкладки/фильтры и увеличивает ключевые цифры. Обычный режим остаётся для руководителя и аналитики.

## v2.3: Supabase для планов / комментариев / NPS

На Render Free локальная файловая система временная. Чтобы ручные данные не удалялись после redeploy, настрой Supabase:

1. Создай проект в Supabase.
2. Выполни `SUPABASE_SQL.sql` в SQL Editor.
3. В Render -> Environment добавь `SUPABASE_URL` и `SUPABASE_KEY`.
4. Redeploy.
5. Проверь `/health`: поле `storage` должно быть `Supabase`.

Сам факт и аналитика по-прежнему берутся напрямую из Bitrix. Supabase хранит только ручные настройки приложения.
