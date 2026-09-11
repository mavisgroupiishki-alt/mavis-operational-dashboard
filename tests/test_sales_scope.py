import unittest

from app.metrics import SALES_CATEGORY_IDS


class SalesScopeTests(unittest.TestCase):
    def test_sales_dashboard_uses_only_primary_sales_funnel(self):
        self.assertEqual(SALES_CATEGORY_IDS, [0])


if __name__ == "__main__":
    unittest.main()
