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
            "executor_ids": [profile["id"]], "project_id": project["id"], "status": "new",
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


if __name__ == "__main__":
    unittest.main()
