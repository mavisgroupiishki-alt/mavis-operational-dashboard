import unittest

from app.metrics import SALES_CATEGORY_IDS, sales_block


class SalesScopeTests(unittest.TestCase):
    def test_sales_dashboard_uses_only_primary_sales_funnel(self):
        self.assertEqual(SALES_CATEGORY_IDS, [0])

    def test_expert_handoffs_belong_to_repeat_sales(self):
        self.assertEqual(
            sales_block("Новый", "Передан экспертом"),
            "Повторные продажи по базе",
        )
        self.assertEqual(
            sales_block("Новый", "Передан экспертам"),
            "Повторные продажи по базе",
        )


if __name__ == "__main__":
    unittest.main()
