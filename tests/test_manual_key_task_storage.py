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


if __name__ == "__main__":
    unittest.main()
