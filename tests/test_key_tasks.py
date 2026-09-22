from datetime import datetime
import unittest

from app.key_tasks import build_key_tasks, is_active_task, task_sort_key


NOW = datetime.fromisoformat("2026-09-22T12:00:00+03:00")


def task(identifier, *, deadline="", created="2026-09-20T09:00:00+03:00", status="2", priority="1"):
    return {
        "ID": str(identifier), "TITLE": f"Task {identifier}", "DEADLINE": deadline,
        "CREATED_DATE": created, "STATUS": status, "PRIORITY": priority,
    }


class KeyTasksTests(unittest.TestCase):
    def test_active_task_excludes_completed_deferred_and_declined(self):
        self.assertTrue(is_active_task(task(1, status="1")))
        self.assertTrue(is_active_task(task(2, status="4")))
        self.assertFalse(is_active_task(task(3, status="5")))
        self.assertFalse(is_active_task(task(4, status="6")))
        self.assertFalse(is_active_task(task(5, status="7")))

    def test_priority_order_is_overdue_then_deadline_then_high_priority(self):
        rows = [
            task("normal-with-deadline", deadline="2026-09-24T10:00:00+03:00"),
            task("high-without-deadline", priority="2"),
            task("overdue", deadline="2026-09-21T10:00:00+03:00"),
            task("nearer-deadline", deadline="2026-09-23T10:00:00+03:00"),
        ]
        ordered = sorted(rows, key=lambda row: task_sort_key(row, NOW, NOW.tzinfo))
        self.assertEqual([row["ID"] for row in ordered], ["overdue", "nearer-deadline", "normal-with-deadline", "high-without-deadline"])

    def test_key_task_board_keeps_only_five_active_tasks_per_selected_person(self):
        source = [task(index, deadline=f"2026-09-{23 + index:02d}T10:00:00+03:00") for index in range(1, 7)]
        source.append(task("completed", status="5"))
        result = build_key_tasks(
            {"7": source}, [{"id": "7", "name": "Роман"}],
            "https://mavisgroup.bitrix24.by", NOW, "Europe/Minsk",
        )
        person = result["people"][0]
        self.assertEqual(person["active_count"], 6)
        self.assertEqual(len(person["tasks"]), 5)
        self.assertNotIn("completed", [row["id"] for row in person["tasks"]])
        self.assertTrue(person["tasks"][0]["task_url"].endswith("/task/view/1/"))
        self.assertEqual(len(result["weekly_people"]["2026-09-28"][0]["tasks"]), 2)
