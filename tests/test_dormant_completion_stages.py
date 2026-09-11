import unittest

from app.metrics import dormant_funnel_entries, split_dormant_completions, split_dormant_completion_history


class DormantCompletionStageTests(unittest.TestCase):
    def test_uses_actual_completion_names_instead_of_generic_won_codes(self):
        rows = [
            {"id": "1", "stage": "В производство"},
            {"id": "2", "stage": "Возврат"},
            {"id": "3", "stage": "Закрыто без решения"},
        ]

        to_production, to_returns = split_dormant_completions(rows)

        self.assertEqual([row["id"] for row in to_production], ["1"])
        self.assertEqual([row["id"] for row in to_returns], ["2"])

    def test_uses_stage_history_for_completion_dialog_results(self):
        rows = [
            {"OWNER_ID": "101", "STAGE_ID": "C30:WON", "TYPE_ID": 3},
            {"OWNER_ID": "102", "STAGE_ID": "C30:APOLOGY", "TYPE_ID": 3},
            {"OWNER_ID": "103", "STAGE_ID": "C30:WON", "TYPE_ID": 2},
        ]
        labels = {"C30:WON": "В производство", "C30:APOLOGY": "Возврат"}

        to_production, to_returns = split_dormant_completion_history(rows, labels)

        self.assertEqual([row["id"] for row in to_production], ["101"])
        self.assertEqual([row["id"] for row in to_returns], ["102"])

    def test_selects_only_funnel_entries_to_dormant(self):
        history = [
            {"OWNER_ID": "1", "CATEGORY_ID": 30, "TYPE_ID": 5},
            {"OWNER_ID": "2", "CATEGORY_ID": 30, "TYPE_ID": 2},
            {"OWNER_ID": "3", "CATEGORY_ID": 28, "TYPE_ID": 5},
        ]

        self.assertEqual([row["OWNER_ID"] for row in dormant_funnel_entries(history)], ["1"])


if __name__ == "__main__":
    unittest.main()
