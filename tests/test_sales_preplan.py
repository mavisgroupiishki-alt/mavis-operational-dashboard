import unittest
from pathlib import Path

from app.metrics import filter_sales_details, preplan_stage_ids


class SalesPreplanTests(unittest.TestCase):
    def test_preplan_uses_stage_titles_10_through_12_not_portal_specific_ids(self):
        meta = {
            "status_by_entity": {
                "DEAL_STAGE": {
                    "UC_CONTRACT": "10. Договор клиенту выслан",
                    "UC_WEEK": "11. Согласовано, оплата до конца недели",
                    "UC_MONTH": "12. Согласовано, оплата до конца месяца",
                    "UC_PREPAY": "14. Предоплата получена",
                    "100": "100. Не включать",
                }
            }
        }

        self.assertEqual(preplan_stage_ids(meta), {"UC_CONTRACT", "UC_WEEK", "UC_MONTH"})

    def test_preplan_drilldown_uses_only_live_preplan_deals(self):
        details = {
            "leads": [],
            "deals": [],
            "active": [{"id": "other", "stage": "5. КП отправлено"}],
            "preplan": [
                {"id": "contract", "manager": "Ирина", "stage": "10. Договор клиенту выслан"},
                {"id": "month", "manager": "Роман", "stage": "12. Согласовано, оплата до конца месяца"},
            ],
        }

        self.assertEqual([row["id"] for row in filter_sales_details(details, "preplan")], ["contract", "month"])
        self.assertEqual([row["id"] for row in filter_sales_details(details, "preplan", manager="Ирина")], ["contract"])

    def test_sales_summary_renders_clickable_preplan_card(self):
        source = Path("app/static/app.js").read_text(encoding="utf-8")

        self.assertIn("function preplanSummaryMetric", source)
        self.assertIn('drillAttrs("sales","preplan")', source)
        self.assertIn("${preplanSummaryMetric(preplan)}", source)


if __name__ == "__main__":
    unittest.main()
