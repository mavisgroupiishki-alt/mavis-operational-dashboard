import tempfile
import unittest
from pathlib import Path

from app.storage import Storage


class ManualKeyTaskStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self.tmp.name) / "dashboard.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_and_remove_dashboard_owned_task(self):
        task = self.storage.add_manual_key_task({
            "title": "Подготовить план недели",
            "responsible_id": "7",
            "deadline": "2026-09-23",
            "priority": "high",
        })

        self.assertTrue(task["id"])
        self.assertEqual(self.storage.manual_key_tasks()[0]["title"], "Подготовить план недели")
        self.assertTrue(self.storage.remove_manual_key_task(task["id"]))
        self.assertEqual(self.storage.manual_key_tasks(), [])

    def test_blank_task_title_is_rejected(self):
        with self.assertRaises(ValueError):
            self.storage.add_manual_key_task({"title": "   ", "responsible_id": "7", "deadline": "2026-09-23"})

    def test_workspace_task_keeps_assignment_after_profile_is_deleted(self):
        profile = self.storage.add_task_profile("Таня")
        project = self.storage.add_task_project("Октябрь")
        task = self.storage.add_workspace_task({
            "title": "Подготовить встречу", "responsible_id": profile["id"],
            "executor_ids": [profile["id"]], "project_id": project["id"], "status": "new", "deadline": "2026-09-23", "description": "Подготовить материалы",
        })

        self.storage.deactivate_task_profile(profile["id"])
        row = self.storage.workspace_tasks()[0]

        self.assertEqual(row["id"], task["id"])
        self.assertEqual(row["executor_ids"], [profile["id"]])
        self.assertEqual(row["status"], "new")
        self.assertEqual(row["project_id"], project["id"])

    def test_workspace_task_update_validates_status(self):
        task = self.storage.add_manual_key_task({"title": "Проверить", "responsible_id": "7"})
        with self.assertRaises(ValueError):
            self.storage.update_workspace_task(task["id"], {"status": "unknown"})

    def test_recurring_task_creates_one_next_week_after_completion(self):
        profile = self.storage.add_task_profile("Аня")
        project = self.storage.add_task_project("Отчётность")
        task = self.storage.add_workspace_task({
            "title": "Еженедельный отчёт", "responsible_id": profile["id"], "executor_ids": [profile["id"]],
            "deadline": "2026-09-30", "status": "new", "recurrence": "weekly", "project_id": project["id"], "description": "Собрать показатели",
        })

        self.storage.update_workspace_task(task["id"], {"status": "done"})
        next_task = self.storage.create_next_recurrence_task(task["id"])

        self.assertEqual(next_task["deadline"], "2026-10-07")
        self.assertEqual(next_task["status"], "new")
        self.assertEqual(next_task["recurrence"], "weekly")
        self.assertIsNone(self.storage.create_next_recurrence_task(task["id"]))

    def test_monthly_recurrence_uses_last_day_of_short_month_and_comments_persist(self):
        profile = self.storage.add_task_profile("Ира")
        project = self.storage.add_task_project("Отчётность")
        task = self.storage.add_workspace_task({
            "title": "Месячный отчёт", "responsible_id": profile["id"], "executor_ids": [profile["id"]], "deadline": "2026-01-31", "recurrence": "monthly", "project_id": project["id"], "description": "Собрать показатели",
        })
        self.storage.update_workspace_task(task["id"], {"status": "done"})

        next_task = self.storage.create_next_recurrence_task(task["id"])
        comment = self.storage.add_task_comment(task["id"], "Данные проверены", profile["id"], profile["name"])

        self.assertEqual(next_task["deadline"], "2026-02-28")
        self.assertEqual(self.storage.task_comments(task["id"])[0]["id"], comment["id"])


if __name__ == "__main__":
    unittest.main()
