from pathlib import Path
import unittest


class SalesSummaryPlansTest(unittest.TestCase):
    def test_sales_top_summary_uses_saved_plans_for_finance_and_sales(self):
        source = Path("app/static/app.js").read_text()

        self.assertIn("function salesSummaryMetric", source)
        self.assertIn("function contractorPlan", source)
        self.assertIn('getPlan("sales","sales_amount")', source)
        self.assertIn('getPlan("sales","net_revenue")', source)
        self.assertIn('salesSummaryMetric("Продажи месяца",x.sales,"num",salesPlan)', source)


if __name__ == "__main__":
    unittest.main()
