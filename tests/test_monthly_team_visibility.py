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


if __name__ == "__main__":
    unittest.main()
