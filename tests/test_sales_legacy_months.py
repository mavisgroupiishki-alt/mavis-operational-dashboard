import asyncio
import unittest
from unittest.mock import patch

from app import main


class SalesLegacyMonthsTests(unittest.TestCase):
    def test_july_and_august_are_the_only_deal_amount_financial_months(self):
        self.assertEqual(main.LEGACY_DEAL_AMOUNT_MONTHS, frozenset({"2026-07", "2026-08"}))

    def test_legacy_month_uses_successful_deal_amount_without_finance_refresh(self):
        snapshot = {
            "sales": {"overall": {"total": {"metrics": {"sales": 3, "sales_amount": 4200.0}}}}
        }
        with (
            patch.object(main, "_apply_runtime", return_value=snapshot),
            patch.object(main, "cached_clean_revenue") as cached,
            patch.object(main, "schedule_clean_revenue_refresh") as refresh,
            patch.object(main, "cached_automatic_nps", return_value={}),
            patch.object(main, "schedule_automatic_nps_refresh"),
        ):
            result = asyncio.run(main.operational_snapshot({}, {}, "2026-08"))

        self.assertEqual(result["sales"]["financial_source"], "deal_amount")
        self.assertEqual(result["clean_revenue"], {
            "status": "deal_amount", "source": "OPPORTUNITY", "value": 4200.0,
            "incoming_amount": 4200.0, "contractor_amount": 0.0,
            "note": "Для июля и августа 2026 финансовые показатели считаются из суммы успешных сделок Bitrix (OPPORTUNITY).",
        })
        cached.assert_not_called()
        refresh.assert_not_called()

    def test_september_keeps_payment_schedule_finance(self):
        snapshot = {
            "sales": {"overall": {"total": {"metrics": {"sales_amount": 4200.0}}}}
        }
        finance = {"status": "online", "value": 3100.0, "contractor_amount": 1100.0}
        with (
            patch.object(main, "_apply_runtime", return_value=snapshot),
            patch.object(main, "cached_clean_revenue", return_value=finance),
            patch.object(main, "schedule_clean_revenue_refresh") as refresh,
            patch.object(main, "cached_automatic_nps", return_value={}),
            patch.object(main, "schedule_automatic_nps_refresh"),
        ):
            result = asyncio.run(main.operational_snapshot({}, {}, "2026-09"))

        self.assertNotIn("financial_source", result["sales"])
        self.assertEqual(result["clean_revenue"]["incoming_amount"], 4200.0)
        refresh.assert_called_once_with("2026-09")

    def test_browser_has_explicit_legacy_labels_and_does_not_render_ledger_as_history(self):
        source = (main.STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn('function usesDealAmountRevenue(){return state?.sales?.financial_source==="deal_amount"}', source)
        self.assertIn('return "Сумма успешных сделок Bitrix (OPPORTUNITY)";', source)
        self.assertIn('if(usesDealAmountRevenue())return "";', source)
        self.assertIn('Сумма продаж Bitrix', source)

    def test_compact_snapshot_keeps_legacy_financial_source(self):
        snapshot = {
            "sales": {
                "financial_source": "deal_amount",
                "overall": {},
                "stages": [],
                "active_deals_count": 0,
                "sale_filter": {},
                "classification": {},
                "available_sources": [],
            }
        }

        compact = main.compact_snapshot_payload(snapshot)

        self.assertEqual(compact["sales"]["financial_source"], "deal_amount")


if __name__ == "__main__":
    unittest.main()
