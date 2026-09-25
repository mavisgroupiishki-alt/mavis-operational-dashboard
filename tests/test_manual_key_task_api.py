import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app import main


class FakeStorage:
    def __init__(self):
        self.rows = []

    def task_profiles(self):
        return [{"id": "profile-7", "name": "Роман", "active": True}]

    def task_projects(self):
        return []

    def workspace_tasks(self):
        return list(self.rows)

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

    def remove_manual_key_task(self, task_id):
        before = len(self.rows)
        self.rows = [row for row in self.rows if row["id"] != task_id]
        return len(self.rows) != before


class ManualKeyTaskApiTests(unittest.TestCase):
    def test_create_and_delete_dashboard_task_without_bitrix_task_write(self):
        storage = FakeStorage()
        with patch.object(main, "storage", storage), patch.object(main, "broadcast", new=AsyncMock()) as broadcast:
            response = asyncio.run(main.add_key_task(main.KeyTaskBody(
                title="Подготовить отчёт", responsible_id="profile-7", executor_ids=["profile-7"], deadline="2026-09-23", priority="high"
            )))
            deleted = asyncio.run(main.delete_key_task("task-1"))

        self.assertEqual(response["task"]["title"], "Подготовить отчёт")
        self.assertEqual(deleted, {"ok": True})
        self.assertEqual(storage.rows, [])
        self.assertEqual(broadcast.await_count, 2)


if __name__ == "__main__":
    unittest.main()
