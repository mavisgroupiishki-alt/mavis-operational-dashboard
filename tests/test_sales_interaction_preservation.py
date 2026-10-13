import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SalesInteractionPreservationTests(unittest.TestCase):
    def test_async_sales_loaders_do_not_replace_open_breakdowns(self):
        source = (ROOT / "app/static/app.js").read_text(encoding="utf-8")

        self.assertIn("function renderSalesIfIdle()", source)
        self.assertNotIn(
            'if(requestedView()==="sales"&&state?.sales?.details_loaded)renderSales()',
            source,
        )
        self.assertIn("finally{salesTodayLoading=false;renderSalesIfIdle()}", source)


if __name__ == "__main__":
    unittest.main()
