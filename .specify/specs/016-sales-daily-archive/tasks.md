# Задачи: Архив ежедневного отчёта продаж

## Группа 1: Серверный контракт и хранение

- [x] T001 Добавить immutable‑хранилище дневных снимков (файл: `app/storage.py`) | balanced/medium | скилл: speckit | агент: —
- [x] T002 Добавить режимы online/archive/fallback в дневной агрегатор и endpoint (файлы: `app/daily_sales.py`, `app/main.py`) | balanced/medium | скилл: systematic-debugging | агент: —
- [x] T003 Добавить серверный цикл фиксации предыдущего дня (файл: `app/main.py`) | balanced/medium | скилл: systematic-debugging | агент: —

## Контрольная точка 1

Проверить: архивная дата читается без Bitrix, а повторная фиксация не перезаписывает запись.

## Группа 2: Интерфейс

- [x] T004 Показать режим и время происхождения данных в ежедневном отчёте (файл: `app/static/app.js`) | fast/low | скилл: — | агент: —
- [x] T005 Обновить версию статических ресурсов (файл: `app/static/index.html`) | fast/low | скилл: — | агент: —

## Группа 3: Верификация

- [x] T006 Добавить тесты неизменяемости, online/fallback режимов и времени архивирования (файлы: `tests/test_daily_sales.py`, `tests/test_daily_sales_archive.py`) | fast/low | скилл: verification-before-completion | агент: —
- [ ] T007 Выполнить целевые тесты, Python/JS-проверки и live-проверку production (файлы: затронутые) | fast/low | скилл: verification-before-completion | агент: —
