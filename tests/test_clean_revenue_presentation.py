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

        with (
            patch.object(main, "_apply_runtime", return_value=snap),
            patch.object(main, "cached_clean_revenue", return_value=finance),
            patch.object(main, "schedule_clean_revenue_refresh"),
        ):
            result = asyncio.run(main.operational_snapshot({}, {}, "2026-09"))

        metrics = result["sales"]["overall"]["total"]["metrics"]
        self.assertEqual(metrics["sales_amount"], 44640.0)
        self.assertEqual(metrics["average_check"], 3188.57)
        self.assertEqual(result["clean_revenue"]["incoming_amount"], 44640.0)

    def test_operational_snapshot_never_waits_for_clean_revenue_network(self):
        finance = {"status": "online", "value": 33925.0, "contractor_amount": 8000.0, "incoming_amount": 41925.0}
        with (
            patch.object(main, "_apply_runtime", return_value={"sales": {"overall": {"total": {"metrics": {}}}}}),
            patch.object(main, "cached_clean_revenue", return_value=finance),
            patch.object(main, "schedule_clean_revenue_refresh"),
            patch.object(main, "load_clean_revenue", new=AsyncMock(side_effect=AssertionError("network must be background only"))),
        ):
            result = asyncio.run(main.operational_snapshot({}, {}, "2026-09"))

        self.assertEqual(result["clean_revenue"]["value"], 33925.0)

    def test_failed_finance_refresh_uses_cooldown_before_retrying(self):
        async def exercise():
            task = main.schedule_clean_revenue_refresh("2026-09")
            await task
            return main.schedule_clean_revenue_refresh("2026-09")

        with (
            patch.object(main, "clean_revenue_cache", {}),
            patch.object(main, "clean_revenue_cache_time", {}),
            patch.object(main, "clean_revenue_tasks", {}),
            patch.object(main, "clean_revenue_failures", {}),
            patch.object(main.storage, "get_setting", return_value={}),
            patch.object(main, "load_clean_revenue", new=AsyncMock(return_value={"status": "unavailable", "reason": "source_timeout"})),
        ):
            second_task = asyncio.run(exercise())

        self.assertIsNone(second_task)


if __name__ == "__main__":
    unittest.main()
