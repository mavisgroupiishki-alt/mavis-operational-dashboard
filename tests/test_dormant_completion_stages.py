import unittest

from app.metrics import split_dormant_completions


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


if __name__ == "__main__":
    unittest.main()
