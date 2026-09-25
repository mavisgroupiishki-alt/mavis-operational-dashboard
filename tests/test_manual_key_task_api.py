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

    def task_profiles(self):
        return [{"id": "profile-7", "name": "Роман", "active": True}]

    def task_projects(self):
        return [{"id": "project-1", "name": "Запуск", "archived": False}]

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

    def workspace_tasks(self):
        return list(self.rows)

    def workspace_task(self, task_id):
        return next((row for row in self.rows if row["id"] == task_id), None)

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
