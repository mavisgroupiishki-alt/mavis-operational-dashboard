# Задачи: Рабочее пространство задач

## Группа 1: Данные и контракт

- [x] T001 Расширить устойчивое хранение профилей, проектов и совместимых ручных задач (файл: app/storage.py) | balanced/medium | скилл: systematic-debugging | агент: —
- [x] T002 Обновить чистые преобразования задач и их тесты (файлы: app/key_tasks.py, tests/test_key_tasks.py) | balanced/medium | скилл: systematic-debugging | агент: —
- [x] T003 Добавить CRUD API задач, профилей и проектов с проверкой полезных ошибок (файлы: app/main.py, tests/test_manual_key_task_api.py) (зависит от: T001, T002) | balanced/medium | скилл: systematic-debugging | агент: —

## Контрольная точка 1

Проверить: старые ручные задачи читаются как новые, добавление/изменение/фильтрация не требуют Bitrix и данные сохраняются.

## Группа 2: Интерфейс

- [x] T004 Заменить стартовую карточку и диалоги раздела задач (файл: app/static/index.html) (зависит от: T003) | balanced/medium | скилл: frontend-design | агент: —
- [x] T005 Реализовать профиль, фильтры, канбан, список, Гант и CRUD-клиент (файл: app/static/app.js) (зависит от: T003, T004) | balanced/medium | скилл: impeccable, design-taste-frontend, emil-design-eng, frontend-design | агент: —
- [x] T006 Добавить адаптивные стили трёх представлений задач (файл: app/static/styles.css) (зависит от: T004, T005) | balanced/medium | скилл: impeccable, web-design-guidelines | агент: —

## Контрольная точка 2

Проверить: на desktop и iPhone доступны все три представления, фильтры и сохранённый выбор профиля.

## Группа 3: Проверка

- [x] T007 Расширить тесты хранилища и API для профилей, проектов, увольнения и обновления задач (файлы: tests/test_manual_key_task_storage.py, tests/test_manual_key_task_api.py) | fast/low | скилл: qa-testing-playwright | агент: —
- [x] T008 Прогнать целевые и полный набор тестов, синтаксис, а также desktop/iPhone UI-проверку (зависит от: T001-T007) | fast/low | скилл: verification-before-completion, web-design-guidelines | агент: —
