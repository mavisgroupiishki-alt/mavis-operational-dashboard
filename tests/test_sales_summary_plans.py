from pathlib import Path
import unittest


class SalesSummaryPlansTest(unittest.TestCase):
    def test_sales_top_summary_uses_saved_plans_for_finance_and_sales(self):
        source = Path("app/static/app.js").read_text()

        self.assertIn("function salesSummaryMetric", source)
        self.assertIn('getPlan("sales","sales_amount")', source)
        self.assertNotIn("function contractorPlan", source)
        self.assertIn('salesSummaryMetric("Общая сумма поступлений",financial.incoming,"money",0,incomingRevenueCaption(),false)', source)
        self.assertIn('salesSummaryMetric("Чистая выручка",cleanRevenue,"money",cleanRevenuePlan,cleanRevenueCaption())', source)
        self.assertIn('salesSummaryMetric("Подрядчики",contractors,"money",0,contractorCaption(),false)', source)
        self.assertIn('salesSummaryMetric("Продажи месяца",x.sales,"num",salesPlan)', source)


if __name__ == "__main__":
    unittest.main()
