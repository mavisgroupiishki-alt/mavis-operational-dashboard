import tempfile
import unittest
from pathlib import Path

from app.storage import Storage


class MonthlyTeamVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self.tempdir.name) / "dashboard.sqlite3")
        self.storage._set("team", {
            "managers": ["Анна", "Борис"],
            "experts": ["Елена", "Фёдор"],
        })

    def tearDown(self):
        self.tempdir.cleanup()

    def test_hiding_a_manager_only_affects_the_selected_month(self):
        self.storage.set_team_member_hidden("2026-10", "manager", "Анна", True)

        self.assertEqual(self.storage.team_for_month("2026-10")["managers"], ["Борис"])
        self.assertEqual(self.storage.team_for_month("2026-09")["managers"], ["Анна", "Борис"])
        self.assertEqual(self.storage.team()["managers"], ["Анна", "Борис"])

    def test_showing_a_member_restores_them_only_in_that_month(self):
        self.storage.set_team_member_hidden("2026-10", "expert", "Елена", True)
        self.storage.set_team_member_hidden("2026-10", "expert", "Елена", False)

        self.assertEqual(self.storage.hidden_team("2026-10")["experts"], [])
        self.assertIn("Елена", self.storage.team_for_month("2026-10")["experts"])
        self.assertIn("Фёдор", self.storage.team_for_month("2026-10")["experts"])

    def test_invalid_month_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "ГГГГ-ММ"):
            self.storage.set_team_member_hidden("october", "manager", "Анна", True)

    def test_one_time_roster_addition_does_not_restore_a_manually_removed_manager(self):
        self.assertTrue(self.storage.add_team_member_once(
            "2026-11-add-ekaterina-sales", "manager", "Екатерина"
        ))
        self.assertIn("Екатерина", self.storage.team()["managers"])
        self.storage.remove_team_member("manager", "Екатерина")

        self.assertFalse(self.storage.add_team_member_once(
            "2026-11-add-ekaterina-sales", "manager", "Екатерина"
        ))
        self.assertNotIn("Екатерина", self.storage.team()["managers"])

    def test_weekly_schedule_is_enabled_once_without_overriding_a_later_disable(self):
        self.storage.set_setting("telegram_report_schedule", {"chat_id": "-1001", "enabled": True})

        self.assertTrue(self.storage.enable_weekly_reports_once("enable-weekly"))
        self.assertTrue(self.storage.get_setting("telegram_report_schedule")["weekly_enabled"])
        self.storage.set_setting("telegram_report_schedule", {
            "chat_id": "-1001", "enabled": True, "weekly_enabled": False,
        })

        self.assertFalse(self.storage.enable_weekly_reports_once("enable-weekly"))
        self.assertFalse(self.storage.get_setting("telegram_report_schedule")["weekly_enabled"])


if __name__ == "__main__":
    unittest.main()
