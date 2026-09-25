# Технический план: Проектный центр задач

**Спека:** [spec.md](spec.md)  **Создан:** 2026-09-25

## Технологии

Существующие FastAPI, Pydantic, `Storage`, vanilla JavaScript и CSS. Новые зависимости не требуются: состояние уже сохраняется тем же ключ-значение хранилищем, что задачи и комментарии.

## Архитектура

`Storage` нормализует новый флаг `backlog` и набор шаблонов. `build_task_workspace` добавляет агрегаты проектов и людей, не меняя старую форму задач. API валидирует обязательные поля на сервере. Клиент рендерит сначала проектный каталог, затем один выбранный проект с существующими представлениями.

```
Storage (tasks + templates)
          |
build_task_workspace -> projects[] + workload[] + tasks[]
          |
FastAPI validation / APIs
          |
project tiles -> selected project -> Kanban | list | Gantt
```

## Схема данных

- `manual_key_tasks`: добавляется `backlog: bool`; старые задачи получают `false`.
- `task_workspace_templates`: `id`, `name`, `title`, `description`, `priority`, `created_at`.
- Проектная сводка создаётся на чтении: `active_count`, `backlog_count`, `overdue_count`.
- Нагрузка сотрудника создаётся на чтении: `open_count`, `overdue_count`, `backlog_count`.

## API / интерфейсы

- `POST /api/key-tasks` и `PATCH /api/key-tasks/{task_id}` принимают `backlog`.
- `GET /api/key-tasks` возвращает `project_summaries`, `workload`, `templates`.
- `GET|POST /api/key-tasks/templates` читает и создаёт шаблоны.
- `DELETE /api/key-tasks/templates/{template_id}` удаляет шаблон.

## Ресурсы по блокам

| Блок | Модель | Скиллы | Агенты | Обоснование |
| --- | --- | --- | --- | --- |
| Хранилище и API | balanced/medium | speckit | — | Локальная CRUD-логика и строгая валидация. |
| Проектный интерфейс | balanced/medium | impeccable, frontend-design, emil-design-eng | — | Существующий интерфейс требует бережного, доступного редизайна. |
| Проверка | fast/low | web-design-guidelines, verification-before-completion | — | Тесты и статическая проверка. |

## Риски

- Старые задачи могут не иметь проекта или срока. Они остаются в плитке «Без проекта», а срок не становится обязательным задним числом.
- Обязательность нельзя полагать только на форму: проверка повторяется в API и хранилище.
- Гант должен игнорировать бэклог, иначе бессрочные задачи исказят временную шкалу.

## Проверка конституции

- [x] Ручные данные сохраняются через текущий `Storage` и не заменяются обновлением.
- [x] Нет записи в Bitrix24 и нет передачи секретов в браузер.
- [x] Новые данные ограничены задачами и не затрагивают тяжёлые CRM-запросы.
