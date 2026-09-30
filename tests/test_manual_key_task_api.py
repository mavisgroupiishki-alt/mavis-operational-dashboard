import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app import main


class FakeStorage:
    def __init__(self):
        self.rows = []
        self.comments = {}
        self.activity = {}
        self.templates = []
        self.saved_views = []

    def task_profiles(self):
        return [{"id": "profile-7", "name": "Роман", "active": True}]

    def task_projects(self):
        return [{"id": "project-1", "name": "Запуск", "archived": False}]

    def task_statuses(self):
        return [
            {"id": "backlog", "name": "Бэклог", "protected": True, "auto_assign_profile_id": ""},
            {"id": "new", "name": "Новая", "protected": False, "auto_assign_profile_id": ""},
            {"id": "review", "name": "На проверке", "protected": False, "auto_assign_profile_id": ""},
            {"id": "done", "name": "Завершена", "protected": True, "auto_assign_profile_id": ""},
        ]

    def task_templates(self):
        return list(self.templates)

    def add_task_template(self, values):
        row = {"id": f"template-{len(self.templates) + 1}", **values}
        self.templates.append(row)
        return row

    def remove_task_template(self, template_id):
        before = len(self.templates)
        self.templates = [row for row in self.templates if row["id"] != template_id]
        return len(self.templates) != before

    def task_saved_views(self):
        return list(self.saved_views)

    def add_task_saved_view(self, values):
        row = {"id": f"view-{len(self.saved_views) + 1}", **values}
        self.saved_views.append(row)
        return row

    def remove_task_saved_view(self, view_id, profile_id):
        before = len(self.saved_views)
        self.saved_views = [row for row in self.saved_views if not (row["id"] == view_id and row["profile_id"] == profile_id)]
        return len(self.saved_views) != before

    def workspace_tasks(self):
        return list(self.rows)

    def workspace_task(self, task_id):
        return next((dict(row) for row in self.rows if row["id"] == task_id), None)

    def key_task_team(self):
        return [{"id": "7", "name": "Роман"}]

    def manual_key_tasks(self):
        return list(self.rows)

    def add_workspace_task(self, task):
        value = {"id": "task-1", "created_at": "2026-09-22T10:00:00+00:00", **task}
        self.rows.append(value)
        return value

    def update_workspace_task(self, task_id, values):
        for row in self.rows:
            if row["id"] == task_id:
                row.update(values)
                if "archived" in values:
                    row["archived_at"] = "2026-09-29T10:00:00+00:00" if values["archived"] else ""
                return row
        return None

    def add_task_activity(self, task_id, text, author_profile_id="", author_name="Команда", kind="updated"):
        row = {"id": f"event-{len(self.activity.get(task_id, [])) + 1}", "text": text, "author_name": author_name, "kind": kind}
        self.activity.setdefault(task_id, []).append(row)
        return row

    def task_activity(self, task_id):
        return list(self.activity.get(task_id, []))

    def task_comments(self, task_id):
        return list(self.comments.get(task_id, []))

    def add_task_comment(self, task_id, text, author_profile_id, author_name):
        row = {"id": f"comment-{len(self.comments.get(task_id, [])) + 1}", "text": text, "author_profile_id": author_profile_id, "author_name": author_name, "created_at": "2026-09-25T10:00:00+00:00"}
        self.comments.setdefault(task_id, []).append(row)
        return row

    def create_next_recurrence_task(self, task_id):
        return None

    def remove_manual_key_task(self, task_id):
        before = len(self.rows)
        self.rows = [row for row in self.rows if row["id"] != task_id]
        return len(self.rows) != before


class ManualKeyTaskApiTests(unittest.TestCase):
    def test_create_and_delete_dashboard_task_without_bitrix_task_write(self):
        storage = FakeStorage()
        with patch.object(main, "storage", storage), patch.object(main, "broadcast", new=AsyncMock()) as broadcast:
            response = asyncio.run(main.add_key_task(main.KeyTaskBody(
                title="Подготовить отчёт", description="Собрать цифры", project_id="project-1", responsible_id="profile-7", executor_ids=["profile-7"], deadline="2026-09-23", priority="high"
            )))
            deleted = asyncio.run(main.delete_key_task("task-1"))

        self.assertEqual(response["task"]["title"], "Подготовить отчёт")
        self.assertEqual(deleted, {"ok": True})
        self.assertEqual(storage.rows, [])
        self.assertEqual(broadcast.await_count, 2)
        self.assertEqual(storage.activity["task-1"][0]["text"], "Задача создана")

    def test_api_rejects_regular_task_without_deadline_and_description(self):
        storage = FakeStorage()
        with patch.object(main, "storage", storage), patch.object(main, "broadcast", new=AsyncMock()):
            with self.assertRaisesRegex(Exception, "Добавьте описание"):
                asyncio.run(main.add_key_task(main.KeyTaskBody(
                    title="Проверить", project_id="project-1", responsible_id="profile-7", executor_ids=["profile-7"]
                )))
            with self.assertRaisesRegex(Exception, "Укажите срок"):
                asyncio.run(main.add_key_task(main.KeyTaskBody(
                    title="Проверить", description="Нужно сделать", project_id="project-1", responsible_id="profile-7", executor_ids=["profile-7"]
                )))
            created = asyncio.run(main.add_key_task(main.KeyTaskBody(
                title="Идея", description="Проверить позже", project_id="project-1", responsible_id="profile-7", executor_ids=["profile-7"], backlog=True
            )))
        self.assertTrue(created["task"]["backlog"])

    def test_api_allows_task_without_project_and_archives_it(self):
        storage = FakeStorage()
        with patch.object(main, "storage", storage), patch.object(main, "broadcast", new=AsyncMock()):
            created = asyncio.run(main.add_key_task(main.KeyTaskBody(
                title="Общая задача", description="Без проекта", responsible_id="profile-7",
                executor_ids=["profile-7"], deadline="2026-09-29",
            )))
            archived = asyncio.run(main.patch_key_task(created["task"]["id"], main.KeyTaskPatchBody(archived=True)))

        self.assertEqual(created["task"]["project_id"], "")
        self.assertTrue(archived["task"]["archived_at"])

    def test_api_keeps_links_and_records_link_change_in_history(self):
        storage = FakeStorage()
        with patch.object(main, "storage", storage), patch.object(main, "broadcast", new=AsyncMock()):
            created = asyncio.run(main.add_key_task(main.KeyTaskBody(
                title="Итог встречи: клиент", description="Договорённость: отправить КП",
                responsible_id="profile-7", executor_ids=["profile-7"], deadline="2026-09-30",
                links=[{"url": "https://example.bitrix24.ru/crm/deal/details/42/", "label": "Сделка"}],
            )))
            asyncio.run(main.patch_key_task(created["task"]["id"], main.KeyTaskPatchBody(
                links=[{"url": "https://docs.google.com/document/d/example", "label": "Итог"}],
            )))

        self.assertEqual(storage.rows[0]["links"][0]["label"], "Итог")
        self.assertIn("Обновлены связанные ссылки", [event["text"] for event in storage.activity["task-1"]])

    def test_task_workspace_enriches_attached_bitrix_deal_without_storing_crm_data(self):
        class FakeBitrix:
            portal = "https://example.bitrix24.ru"

            async def deal_list(self, filters, fields):
                self.filters = filters
                self.fields = fields
                return [{
                    "ID": "42", "TITLE": "Сделка Альфа", "COMPANY_TITLE": "ООО Альфа",
                    "OPPORTUNITY": "12500", "STAGE_ID": "C1:WON", "CONTACT_ID": "",
                }]

            async def meta(self):
                return {"statuses": {"C1:WON": "Успешно"}}

        storage = FakeStorage()
        storage.rows.append({
            "id": "task-1", "title": "Проверить сделку", "description": "Сверить условия",
            "responsible_id": "profile-7", "executor_ids": ["profile-7"], "status": "new", "deadline": "2026-09-30",
            "links": [{"url": "https://example.bitrix24.ru/crm/deal/details/42/", "label": ""}],
        })
        fake_client = FakeBitrix()
        main.task_link_deal_cache.clear()
        main.task_link_deal_cache_time.clear()
        with patch.object(main, "storage", storage), patch.object(main, "client", fake_client):
            response = asyncio.run(main.get_key_tasks())

        preview = response["tasks"][0]["links"][0]["deal"]
        self.assertEqual(preview, {"id": "42", "client": "ООО Альфа", "amount": 12500.0, "stage": "Успешно"})
        self.assertEqual(fake_client.filters, {"@ID": ["42"]})
        self.assertNotIn("deal", storage.rows[0]["links"][0])

    def test_stage_automation_assigns_configured_profile(self):
        storage = FakeStorage()
        storage.rows.append({
            "id": "task-1", "title": "Проверить", "description": "Договор",
            "responsible_id": "profile-7", "executor_ids": ["profile-7"], "status": "new",
        })
        storage.task_statuses = lambda: [
            {"id": "new", "name": "Новая", "auto_assign_profile_id": ""},
            {"id": "review", "name": "На проверке", "auto_assign_profile_id": "profile-7"},
            {"id": "done", "name": "Завершена", "auto_assign_profile_id": ""},
        ]
        with patch.object(main, "storage", storage), patch.object(main, "broadcast", new=AsyncMock()):
            response = asyncio.run(main.patch_key_task("task-1", main.KeyTaskPatchBody(status="review")))

        self.assertEqual(response["task"]["responsible_id"], "profile-7")
        self.assertEqual(response["task"]["executor_ids"], ["profile-7"])
        self.assertIn("Автодействие этапа", storage.activity["task-1"][-1]["text"])

    def test_bulk_update_changes_selected_tasks_and_records_history(self):
        storage = FakeStorage()
        storage.rows.extend([
            {"id": "task-1", "title": "Первый", "description": "Проверить", "responsible_id": "profile-7", "executor_ids": ["profile-7"], "status": "new", "deadline": "2026-09-30"},
            {"id": "task-2", "title": "Второй", "description": "Проверить", "responsible_id": "profile-7", "executor_ids": ["profile-7"], "status": "new", "deadline": "2026-09-30"},
        ])
        with patch.object(main, "storage", storage), patch.object(main, "broadcast", new=AsyncMock()) as broadcast:
            response = asyncio.run(main.bulk_update_key_tasks(main.KeyTaskBulkBody(
                task_ids=["task-1", "task-2"], status="review", deadline="2026-10-02",
            )))

        self.assertEqual([row["status"] for row in response["tasks"]], ["review", "review"])
        self.assertEqual([row["deadline"] for row in response["tasks"]], ["2026-10-02", "2026-10-02"])
        self.assertTrue(all(any(event["text"] == "Массовое изменение" for event in storage.activity[row["id"]]) for row in response["tasks"]))
        self.assertEqual(broadcast.await_count, 1)

    def test_bulk_update_rejects_completion_without_per_task_hours(self):
        storage = FakeStorage()
        with patch.object(main, "storage", storage), patch.object(main, "broadcast", new=AsyncMock()):
            with self.assertRaisesRegex(Exception, "Завершайте задачи по одной"):
                asyncio.run(main.bulk_update_key_tasks(main.KeyTaskBulkBody(task_ids=["task-1"], status="done")))

    def test_saved_view_is_owned_by_selected_profile(self):
        storage = FakeStorage()
        with patch.object(main, "storage", storage), patch.object(main, "broadcast", new=AsyncMock()):
            created = asyncio.run(main.add_task_saved_view(main.TaskSavedViewBody(
                name="Мои просроченные", profile_id="profile-7", filters={"executor": "profile-7", "deadline": "overdue"}
            )))
            deleted = asyncio.run(main.delete_task_saved_view(created["view"]["id"], "profile-7"))

        self.assertEqual(created["view"]["filters"]["deadline"], "overdue")
        self.assertEqual(deleted, {"ok": True})
        self.assertEqual(storage.saved_views, [])

    def test_comment_is_signed_by_selected_profile_and_kept_with_task(self):
        storage = FakeStorage()
        storage.rows.append({"id": "task-1", "title": "Проверить", "responsible_id": "profile-7"})
        with patch.object(main, "storage", storage), patch.object(main, "broadcast", new=AsyncMock()):
            response = asyncio.run(main.add_key_task_comment("task-1", main.TaskCommentBody(text="Жду ответ клиента", author_profile_id="profile-7")))
            activity = asyncio.run(main.get_key_task_activity("task-1"))

        self.assertEqual(response["comment"]["author_name"], "Роман")
        self.assertEqual(activity["comments"][0]["text"], "Жду ответ клиента")
        self.assertEqual(activity["activity"][0]["text"], "Добавлен комментарий")

    def test_template_api_creates_and_deletes_dashboard_template(self):
        storage = FakeStorage()
        with patch.object(main, "storage", storage), patch.object(main, "broadcast", new=AsyncMock()) as broadcast:
            created = asyncio.run(main.add_task_template(main.TaskTemplateBody(
                name="Еженедельный отчёт", title="Подготовить отчёт",
                description="Собрать показатели", priority="high",
            )))
            deleted = asyncio.run(main.delete_task_template(created["template"]["id"]))

        self.assertEqual(created["template"]["name"], "Еженедельный отчёт")
        self.assertEqual(deleted, {"ok": True})
        self.assertEqual(storage.templates, [])
        self.assertEqual(broadcast.await_count, 2)


if __name__ == "__main__":
    unittest.main()
