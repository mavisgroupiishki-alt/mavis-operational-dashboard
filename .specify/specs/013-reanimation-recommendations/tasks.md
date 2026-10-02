# Задачи: Реанимируем реанимацию

## Группа 1: Контракт и безопасная аналитика Jarvis

- [x] T001 Добавить модель и детерминированные правила исключения рекомендаций (файл: `/Users/admin/Documents/РОП/sales-analytics/src/reactivation.py`) | frontier/high | скилл: systematic-debugging | агент: —
- [x] T002 Добавить ограниченный Bitrix-адаптер для сделок реанимации и явного переноса (файл: `/Users/admin/Documents/РОП/sales-analytics/src/reactivation.py`) | frontier/high | скилл: systematic-debugging | агент: —
- [x] T003 Добавить защищённые маршруты Jarvis и аудит (файл: `/Users/admin/Documents/РОП/sales-analytics/app.py`) | balanced/medium | скилл: speckit | агент: —
- [x] T004 Добавить тесты экспорта и переноса (файл: `/Users/admin/Documents/РОП/sales-analytics/tests/test_reactivation.py`) | balanced/medium | скилл: verification-before-completion | агент: —

## Контрольная точка 1

Проверить: рекомендации не меняют CRM; действие без токена или с неподходящей сделкой отклоняется.

## Группа 2: Дашборд и явный пользовательский поток

- [x] T005 Добавить серверный прокси GET/POST и ролевую проверку (файл: `app/main.py`) | balanced/medium | скилл: verification-before-completion | агент: —
- [x] T006 Отрисовать раскрываемую очередь, доказательства и подтверждаемую кнопку (файл: `app/static/app.js`) | balanced/medium | скилл: verification-before-completion | агент: —
- [x] T007 Добавить стили и проверки клиентских ассетов (файлы: `app/static/styles.css`, `tests/test_pwa_assets.py`) | balanced/medium | скилл: verification-before-completion | агент: —

## Контрольная точка 2

Проверить: браузер не получает секрет, маркетолог получает 403, успешное действие обновляет строку очереди.

## Группа 3: Проверка

- [x] T008 Запустить тесты Jarvis и дашборда, проверку синтаксиса JavaScript и `git diff --check` | balanced/medium | скилл: verification-before-completion | агент: —
