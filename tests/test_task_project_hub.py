from datetime import datetime
import tempfile
import unittest
from pathlib import Path

from app.key_tasks import build_task_workspace
from app.storage import Storage


NOW = datetime.fromisoformat("2026-09-25T12:00:00+03:00")


class TaskProjectHubStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self.tmp.name) / "dashboard.sqlite3")
        self.profile = self.storage.add_task_profile("Таня")
        self.project = self.storage.add_task_project("Запуск сайта")

    def tearDown(self):
        self.tmp.cleanup()

    def test_backlog_can_be_created_without_deadline_but_regular_task_requires_it(self):
        backlog = self.storage.add_workspace_task({
            "title": "Идея для сайта", "description": "Проверить после запуска",
            "responsible_id": self.profile["id"], "executor_ids": [self.profile["id"]],
            "project_id": self.project["id"], "priority": "normal", "backlog": True,
        })

        self.assertTrue(backlog["backlog"])
        self.assertEqual(backlog["deadline"], "")
        with self.assertRaisesRegex(ValueError, "Укажите срок"):
            self.storage.add_workspace_task({
                "title": "Срочная задача", "description": "Нужно сегодня",
                "responsible_id": self.profile["id"], "executor_ids": [self.profile["id"]],
                "project_id": self.project["id"], "priority": "high",
            })

    def test_templates_persist_and_can_be_deleted(self):
        template = self.storage.add_task_template({
            "name": "Еженедельный отчёт", "title": "Подготовить отчёт",
            "description": "Собрать цифры и выводы", "priority": "high",
        })

        self.assertEqual(self.storage.task_templates()[0]["title"], "Подготовить отчёт")
        self.assertTrue(self.storage.remove_task_template(template["id"]))
        self.assertEqual(self.storage.task_templates(), [])


class TaskProjectHubPresentationTests(unittest.TestCase):
    def test_workspace_includes_project_summary_and_person_load(self):
        profile = {"id": "tanya", "name": "Таня", "active": True}
        result = build_task_workspace(
            [
                {"id": "a", "title": "Срочная", "description": "Описание", "responsible_id": "tanya", "executor_ids": ["tanya"], "project_id": "launch", "status": "in_progress", "deadline": "2026-09-24"},
                {"id": "b", "title": "Идея", "description": "Описание", "responsible_id": "tanya", "executor_ids": ["tanya"], "project_id": "launch", "status": "new", "backlog": True},
            ],
            [profile], [{"id": "launch", "name": "Запуск сайта", "archived": False}], [], NOW, "Europe/Minsk",
        )

        summary = result["project_summaries"][0]
        self.assertEqual(summary["active_count"], 2)
        self.assertEqual(summary["backlog_count"], 1)
        self.assertEqual(summary["overdue_count"], 1)
        self.assertEqual(result["workload"][0]["open_count"], 2)
        self.assertTrue(next(row for row in result["tasks"] if row["id"] == "b")["backlog"])


if __name__ == "__main__":
    unittest.main()
