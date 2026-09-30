import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app.key_tasks import build_task_workspace
from app.storage import Storage


class TaskStatusStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self.tmp.name) / "dashboard.sqlite3")
        self.profile = self.storage.add_task_profile("Ира", "ОП Директор")

    def tearDown(self):
        self.tmp.cleanup()

    def test_stage_can_be_renamed_and_deleted_with_safe_task_move(self):
        stage = self.storage.add_task_status("Согласование")
        task = self.storage.add_workspace_task({
            "title": "Согласовать договор", "description": "Проверить правки",
            "responsible_id": self.profile["id"], "executor_ids": [self.profile["id"]],
            "status": stage["id"], "deadline": "2026-09-30",
        })

        renamed = self.storage.update_task_status(stage["id"], name="Юридическая проверка")
        removed = self.storage.remove_task_status(stage["id"], "review")

        self.assertEqual(renamed["name"], "Юридическая проверка")
        self.assertEqual(removed["id"], stage["id"])
        self.assertEqual(self.storage.workspace_task(task["id"])["status"], "review")
        self.assertNotIn(stage["id"], {row["id"] for row in self.storage.task_statuses()})

    def test_system_stages_cannot_be_deleted(self):
        with self.assertRaisesRegex(ValueError, "Системный этап"):
            self.storage.remove_task_status("backlog", "new")

    def test_removed_default_stage_is_not_reintroduced_by_backlog_or_recurrence(self):
        self.storage.remove_task_status("new", "planned")
        task = self.storage.add_workspace_task({
            "title": "Запланировать", "description": "Проверить сценарий",
            "responsible_id": self.profile["id"], "executor_ids": [self.profile["id"]],
            "status": "backlog", "backlog": True,
        })

        restored = self.storage.update_workspace_task(task["id"], {"backlog": False})
        self.assertEqual(restored["status"], "planned")

        self.storage.update_workspace_task(task["id"], {
            "status": "done", "backlog": False, "deadline": "2026-09-30", "actual_hours": 1, "recurrence": "weekly",
        })
        copy = self.storage.create_next_recurrence_task(task["id"])
        self.assertEqual(copy["status"], "planned")

    def test_workspace_exposes_custom_stage_and_automation_setting(self):
        stage = self.storage.add_task_status("Проверка директора")
        self.storage.update_task_status(stage["id"], auto_assign_profile_id=self.profile["id"], sla_days=3)
        result = build_task_workspace(
            [], self.storage.task_profiles(), [], [], datetime.fromisoformat("2026-09-29T10:00:00+03:00"),
            "Europe/Minsk", self.storage.task_statuses(),
        )

        row = next(item for item in result["statuses"] if item["id"] == stage["id"])
        self.assertEqual(row["name"], "Проверка директора")
        self.assertEqual(row["auto_assign_profile_id"], self.profile["id"])
        self.assertEqual(row["sla_days"], 3)

    def test_default_review_stage_assigns_operations_director(self):
        review = next(row for row in self.storage.task_statuses() if row["id"] == "review")

        self.assertEqual(review["auto_assign_profile_id"], "task-profile-ira")

    def test_stage_transition_records_time_for_sla(self):
        task = self.storage.add_workspace_task({
            "title": "Проверить смету", "description": "Нужна проверка руководителя",
            "responsible_id": self.profile["id"], "executor_ids": [self.profile["id"]],
            "status": "new", "deadline": "2026-09-30",
        })

        moved = self.storage.update_workspace_task(task["id"], {"status": "review"})

        self.assertEqual(moved["status"], "review")
        self.assertTrue(moved["status_changed_at"])

    def test_workspace_sla_and_observer_do_not_add_executor_workload(self):
        observer = self.storage.add_task_profile("Таня", "РОП")
        result = build_task_workspace(
            [{
                "id": "review-task", "title": "Согласовать КП", "description": "Проверка цены",
                "responsible_id": self.profile["id"], "executor_ids": [self.profile["id"]],
                "watcher_ids": [observer["id"]], "status": "review", "deadline": "2026-09-30",
                "status_changed_at": "2026-09-24T09:00:00+03:00",
            }],
            self.storage.task_profiles(), [], [], datetime.fromisoformat("2026-09-29T10:00:00+03:00"),
            "Europe/Minsk", self.storage.task_statuses(),
        )

        task = result["tasks"][0]
        tana_workload = next(row for row in result["workload"] if row["id"] == observer["id"])
        self.assertEqual(task["sla_state"], "breached")
        self.assertEqual(task["watchers"][0]["id"], observer["id"])
        self.assertEqual(tana_workload["open_count"], 0)
        self.assertEqual(result["reminders"]["sla_breached_count"], 1)


if __name__ == "__main__":
    unittest.main()
