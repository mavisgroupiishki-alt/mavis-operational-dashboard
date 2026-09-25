# Задачи: Обсуждение, повторение и напоминания задач

## Группа 1: Долговременные данные и сервер

- [x] T001 Расширить нормализацию, хранение активности и календарное повторение (файл: `app/storage.py`) | balanced/medium | скилл: speckit | агент: —
- [x] T002 Расширить payload рабочего пространства повторением (файл: `app/key_tasks.py`) | balanced/medium | скилл: speckit | агент: —
- [x] T003 Добавить API комментариев, истории и защищённой генерации следующей задачи (файл: `app/main.py`, зависит от: T001, T002) | balanced/medium | скилл: systematic-debugging | агент: —

## Контрольная точка 1

Проверить: комментарии и история сохраняются; повторяемая задача порождает ровно один будущий экземпляр.

## Группа 2: Интерфейс

- [x] T004 Добавить элементы диалога, события и напоминание о просрочке (файл: `app/static/index.html`) | balanced/medium | скилл: impeccable, frontend-design | агент: —
- [x] T005 Реализовать загрузку активности, создание комментариев, повторение и быстрый фильтр (файл: `app/static/app.js`, зависит от: T003, T004) | balanced/medium | скилл: frontend-design | агент: —
- [x] T006 Оформить мобильную и настольную подачу активности и напоминаний (файл: `app/static/styles.css`, зависит от: T004) | balanced/medium | скилл: web-design-guidelines | агент: —
- [x] T007 Обновить версию офлайн-кеша (файлы: `app/static/index.html`, `app/static/service-worker.js`, зависит от: T005) | fast/low | скилл: — | агент: —

## Контрольная точка 2

Проверить: комментарий, история, повторение и фильтр просроченных работают в браузере на desktop и iPhone.

## Группа 3: Проверка

- [x] T008 Добавить storage/API/presentation-тесты (файлы: `tests/test_manual_key_task_storage.py`, `tests/test_manual_key_task_api.py`, `tests/test_key_tasks.py`) | balanced/medium | скилл: verification-before-completion | агент: —
- [x] T009 Запустить тесты, проверки синтаксиса, diff и browser QA (зависит от: T008) | fast/low | скилл: verification-before-completion | агент: —
