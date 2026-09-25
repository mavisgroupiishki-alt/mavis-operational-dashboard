from datetime import datetime
import unittest

from app.key_tasks import build_key_tasks, build_task_workspace


NOW = datetime.fromisoformat("2026-09-22T12:00:00+03:00")


class KeyTasksTests(unittest.TestCase):
    def test_board_groups_dashboard_owned_tasks_by_selected_employee_and_week(self):
        result = build_key_tasks(
            [
                {"id": "one", "title": "Позвонить клиенту", "responsible_id": "7", "deadline": "2026-09-23", "priority": "high"},
                {"id": "two", "title": "Подготовить КП", "responsible_id": "7", "deadline": "2026-09-29", "priority": "normal"},
                {"id": "three", "title": "Без срока", "responsible_id": "8", "deadline": "", "priority": "normal"},
            ],
            [{"id": "7", "name": "Роман"}, {"id": "8", "name": "Ирина"}], NOW, "Europe/Minsk",
        )

        self.assertEqual(result["people"][0]["active_count"], 2)
        self.assertEqual(result["people"][1]["active_count"], 1)
        first_week = next(row for row in result["weekly_people"]["2026-09-21"] if row["id"] == "7")
        second_week = next(row for row in result["weekly_people"]["2026-09-28"] if row["id"] == "7")
        self.assertEqual([task["id"] for task in first_week["tasks"]], ["one"])
        self.assertEqual([task["id"] for task in second_week["tasks"]], ["two"])
        self.assertEqual(result["no_deadline"][0]["id"], "three")

    def test_board_keeps_manual_task_details_without_bitrix_url(self):
        result = build_key_tasks(
            [{"id": "one", "title": "Проверить договор", "responsible_id": "7", "deadline": "2026-09-23", "priority": "high"}],
            [{"id": "7", "name": "Роман"}], NOW, "Europe/Minsk",
        )

        task = result["people"][0]["tasks"][0]
        self.assertEqual(task["responsible"], "Роман")
        self.assertEqual(task["priority"], "high")
        self.assertEqual(task["task_url"], "")

    def test_workspace_preserves_dismissed_profile_on_historical_task(self):
        result = build_task_workspace(
            [{"id": "one", "title": "Старый отчёт", "responsible_id": "tanya", "executor_ids": ["tanya"], "status": "in_progress"}],
            [{"id": "tanya", "name": "Таня", "active": False}], [], [], NOW, "Europe/Minsk",
        )

        task = result["tasks"][0]
        self.assertTrue(task["responsible"]["dismissed"])
        self.assertEqual(task["executors"][0]["name"], "Таня")
        self.assertEqual(task["status_label"], "В работе")
