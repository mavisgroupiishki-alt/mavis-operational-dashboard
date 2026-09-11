import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app import main


class CleanRevenuePresentationTests(unittest.TestCase):
    def test_operational_snapshot_derives_confirmed_incoming_from_finance_ledger(self):
        snap = {
            "sales": {
                "overall": {
                    "total": {"metrics": {"sales_amount": 44640.0, "sales": 14, "average_check": 3188.57}}
                }
            }
        }
        finance = {"status": "online", "value": 33890.0, "contractor_amount": 10750.0}

        with patch.object(main, "_apply_runtime", return_value=snap), patch.object(main, "load_clean_revenue", new=AsyncMock(return_value=finance)):
            result = asyncio.run(main.operational_snapshot({}, {}, "2026-09"))

        metrics = result["sales"]["overall"]["total"]["metrics"]
        self.assertEqual(metrics["sales_amount"], 44640.0)
        self.assertEqual(metrics["average_check"], 3188.57)
        self.assertEqual(result["clean_revenue"]["incoming_amount"], 44640.0)


if __name__ == "__main__":
    unittest.main()
