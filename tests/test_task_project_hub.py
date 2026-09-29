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

    def test_task_without_project_and_archived_task_are_preserved(self):
        task = self.storage.add_workspace_task({
            "title": "Общая задача", "description": "Не относится к проекту",
            "responsible_id": self.profile["id"], "executor_ids": [self.profile["id"]],
            "priority": "normal", "deadline": "2026-09-28",
        })
        archived = self.storage.update_workspace_task(task["id"], {"archived": True})
        self.assertTrue(archived["archived_at"])
        restored = self.storage.update_workspace_task(task["id"], {"archived": False})
        self.assertEqual(restored["archived_at"], "")

    def test_task_profile_keeps_role_for_workspace_labels(self):
        profile = self.storage.add_task_profile("Ирина", "РОП")
        updated = self.storage.update_task_profile(profile["id"], role="РЭКС")

        self.assertEqual(updated["role"], "РЭКС")
        self.assertEqual(
            next(row for row in self.storage.task_profiles() if row["id"] == profile["id"])["role"],
            "РЭКС",
        )

    def test_templates_persist_and_can_be_deleted(self):
        template = self.storage.add_task_template({
            "name": "Еженедельный отчёт", "title": "Подготовить отчёт",
            "description": "Собрать цифры и выводы", "priority": "high",
        })

        self.assertEqual(self.storage.task_templates()[0]["title"], "Подготовить отчёт")
        self.assertTrue(self.storage.remove_task_template(template["id"]))
        self.assertEqual(self.storage.task_templates(), [])

    def test_saved_view_persists_filters_for_its_owner(self):
        view = self.storage.add_task_saved_view({
            "name": "Срочные у Тани", "profile_id": self.profile["id"],
            "filters": {"executor": self.profile["id"], "deadline": "week"},
        })

        self.assertEqual(self.storage.task_saved_views()[0]["filters"]["deadline"], "week")
        self.assertTrue(self.storage.remove_task_saved_view(view["id"], self.profile["id"]))
        self.assertEqual(self.storage.task_saved_views(), [])

    def test_task_can_move_between_expanded_kanban_stages(self):
        task = self.storage.add_workspace_task({
            "title": "Проверить макет", "description": "Отдать на согласование",
            "responsible_id": self.profile["id"], "executor_ids": [self.profile["id"]],
            "project_id": self.project["id"], "priority": "normal", "deadline": "2026-09-28",
        })

        moved = self.storage.update_workspace_task(task["id"], {"status": "backlog"})
        self.assertEqual(moved["status"], "backlog")
        self.assertTrue(moved["backlog"])

        restored = self.storage.update_workspace_task(task["id"], {"status": "ready"})
        self.assertEqual(restored["status"], "ready")
        self.assertFalse(restored["backlog"])

    def test_finishing_task_requires_actual_hours_and_keeps_effort(self):
        task = self.storage.add_workspace_task({
            "title": "Подготовить смету", "description": "Сверить все строки",
            "responsible_id": self.profile["id"], "executor_ids": [self.profile["id"]],
            "project_id": self.project["id"], "priority": "normal", "deadline": "2026-09-28",
            "planned_hours": 3.5,
        })

        with self.assertRaisesRegex(ValueError, "фактически затраченные"):
            self.storage.update_workspace_task(task["id"], {"status": "done"})

        done = self.storage.update_workspace_task(task["id"], {"status": "done", "actual_hours": 2.25})
        self.assertEqual(done["planned_hours"], 3.5)
        self.assertEqual(done["actual_hours"], 2.25)
        self.assertTrue(done["completed_at"])


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

    def test_workspace_uses_role_labels_and_excludes_archived_from_load(self):
        result = build_task_workspace(
            [
                {"id": "active", "title": "Работа", "responsible_id": "lead", "executor_ids": ["lead"], "project_id": "launch", "status": "new"},
                {"id": "archived", "title": "Архив", "responsible_id": "lead", "executor_ids": ["lead"], "status": "new", "archived_at": "2026-09-20T10:00:00+03:00"},
            ],
            [{"id": "lead", "name": "Таня", "role": "РОП", "active": True}], [{"id": "launch", "name": "Запуск", "archived": False}], [], NOW, "Europe/Minsk",
        )

        self.assertEqual(result["tasks"][0]["responsible"]["label"], "РОП")
        self.assertEqual(result["workload"][0]["label"], "РОП")
        self.assertEqual(result["workload"][0]["open_count"], 1)
        self.assertEqual(result["project_summaries"][0]["active_count"], 1)

    def test_legacy_backlog_is_shown_as_a_separate_stage(self):
        result = build_task_workspace(
            [{"id": "idea", "title": "Идея", "responsible_id": "tanya", "executor_ids": ["tanya"], "status": "new", "backlog": True}],
            [{"id": "tanya", "name": "Таня", "active": True}], [], [], NOW, "Europe/Minsk",
        )

        task = result["tasks"][0]
        self.assertEqual(task["status"], "backlog")
        self.assertEqual(task["status_label"], "Бэклог")

    def test_workspace_calculates_weekly_hours_and_dashboard_reminders(self):
        profile = {"id": "tanya", "name": "Таня", "active": True}
        result = build_task_workspace(
            [
                {"id": "plan", "title": "Срок завтра", "responsible_id": "tanya", "executor_ids": ["tanya"], "status": "in_progress", "deadline": "2026-09-26", "planned_hours": 3.5},
                {"id": "done", "title": "Закрыта", "responsible_id": "tanya", "executor_ids": ["tanya"], "status": "done", "deadline": "2026-09-22", "completed_at": "2026-09-23T11:00:00+03:00", "actual_hours": 2.25},
                {"id": "today", "title": "Сегодня", "responsible_id": "tanya", "executor_ids": ["tanya"], "status": "new", "deadline": "2026-09-25"},
                {"id": "late", "title": "Просрочена", "responsible_id": "tanya", "executor_ids": ["tanya"], "status": "new", "deadline": "2026-09-24"},
                {"id": "soon", "title": "Скоро", "responsible_id": "tanya", "executor_ids": ["tanya"], "status": "new", "deadline": "2026-09-27"},
            ],
            [profile], [], [], NOW, "Europe/Minsk",
        )

        load = result["workload"][0]
        self.assertEqual(load["week_planned_hours"], 3.5)
        self.assertEqual(load["week_actual_hours"], 2.25)
        self.assertEqual(result["reminders"]["overdue_count"], 1)
        self.assertEqual(result["reminders"]["today_count"], 1)
        self.assertEqual(result["reminders"]["soon_count"], 2)


if __name__ == "__main__":
    unittest.main()
