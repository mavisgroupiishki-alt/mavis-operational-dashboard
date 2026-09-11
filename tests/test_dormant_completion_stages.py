import unittest

from app.metrics import (
    direct_dormant_to_production_history,
    dormant_funnel_entries,
    filter_prod_details,
    split_dormant_completions,
    split_dormant_completion_history,
)


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

    def test_counts_direct_move_from_dormant_to_production(self):
        rows = [
            # Bitrix keeps the source stage in stage history for a funnel
            # transfer, so the target production stage is not available here.
            {"OWNER_ID": "25238", "CATEGORY_ID": 30, "TYPE_ID": 5, "STAGE_ID": "C30:NEW"},
            # Some events are indexed in the target funnel but still carry
            # the source-stage identifier.
            {"OWNER_ID": "25239", "CATEGORY_ID": 28, "TYPE_ID": 5, "STAGE_ID": "C30:NEW"},
            {"OWNER_ID": "25240", "CATEGORY_ID": 28, "TYPE_ID": 5, "STAGE_ID": "C20:NEW"},
            {"OWNER_ID": "25241", "CATEGORY_ID": 30, "TYPE_ID": 3, "STAGE_ID": "C30:WON"},
        ]

        direct = direct_dormant_to_production_history(rows, {"C28:NEW": "Не распределенные"})

        self.assertEqual([row["id"] for row in direct], ["25238", "25239"])
        self.assertEqual(direct[0]["stage"], "Прямой перенос")

    def test_all_dormant_reason_metric_opens_dormant_cards_not_production(self):
        details = {
            "dormant": [{"id": "30", "stuck_reasons": ["Нет документов"]}],
            "dormant_expected": [],
            "active": [{"id": "28", "stuck_reasons": ["Нет документов"]}],
        }

        rows = filter_prod_details(details, "dormant_all_with_reason_count", reason="Нет документов")

        self.assertEqual([row["id"] for row in rows], ["30"])


if __name__ == "__main__":
    unittest.main()
