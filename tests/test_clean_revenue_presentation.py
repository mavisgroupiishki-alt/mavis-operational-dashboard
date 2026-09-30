import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app import main


class CleanRevenuePresentationTests(unittest.TestCase):
    def test_finance_overdue_rows_are_normalized_and_linked_to_bitrix_deals(self):
        payload = {"overdueScheduleRows": [
            {"scheduleId": "11", "dealId": "44", "dealTitle": "Просрочено", "stageName": "Договор", "date": "2026-09-17", "planned": "1200", "bankConfirmed": 100, "manualConfirmed": "50", "remaining": "1050"},
            {"scheduleId": "bad", "dealId": "not-a-deal", "date": "2026-09-17", "remaining": "100"},
        ]}
        with patch.object(main.client, "webhook", "https://portal.bitrix24.by/rest/1/token/"):
            rows = main.clean_revenue_overdue_rows(payload)

        self.assertEqual(rows, [{
            "deal_id": "44", "deal_title": "Просрочено", "stage": "Договор", "date": "2026-09-17",
            "planned": 1200.0, "bank_confirmed": 100.0, "manual_confirmed": 50.0, "remaining": 1050.0,
            "url": "https://portal.bitrix24.by/crm/deal/details/44/",
        }])

    def test_deal_linked_finance_is_classified_without_proportional_allocation(self):
        payload = {"dealRevenueRows": [{
            "dealId": "44", "dealTitle": "Сделка партнёра", "bankConfirmed": 1200,
            "manualConfirmed": 0, "contractorApplied": 200, "cleanRevenue": 1000,
        }]}
        rows = main.clean_revenue_deal_rows(payload)
        meta = {
            "users": {"7": "Ирина"},
            "sources": {"22": "Партнёрка Белтехэкспертиза"},
            "enums": {main.F_DEAL_CLIENT_TYPE: {"1": "Новый клиент"}},
        }
        deal = {
            "ID": "44", "CATEGORY_ID": 0, "DATE_CREATE": "2026-09-11T10:00:00+03:00",
            "SOURCE_ID": "22", main.F_DEAL_CLIENT_TYPE: "1", "ASSIGNED_BY_ID": "7",
        }
        with (
            patch.object(main.client, "meta", new=AsyncMock(return_value=meta)),
            patch.object(main.client, "deal_list", new=AsyncMock(return_value=[deal])),
        ):
            enriched = asyncio.run(main.enrich_clean_revenue_deal_rows("2026-09", rows))

        self.assertEqual(enriched[0]["clean_revenue"], 1000.0)
        self.assertEqual(enriched[0]["group"], "Холодные продажи")
        self.assertEqual(enriched[0]["period_type"], "current")
        self.assertEqual(enriched[0]["manager"], "Ирина")

    def test_payment_rows_keep_the_ledger_date_for_weekly_net_revenue(self):
        payload = {"paymentRevenueRows": [{
            "dealId": "44", "dealTitle": "Сделка партнёра", "date": "2026-09-11",
            "bankConfirmed": 1200, "manualConfirmed": 0, "contractorApplied": 200,
            "cleanRevenue": 1000,
        }, {"dealId": "bad", "date": "2026-09-12"}]}

        self.assertEqual(main.clean_revenue_payment_rows(payload), [{
            "deal_id": "44", "deal_title": "Сделка партнёра", "date": "2026-09-11",
            "bank_confirmed": 1200.0, "manual_confirmed": 0.0,
            "contractor_applied": 200.0, "clean_revenue": 1000.0,
        }])

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

    def test_finance_refreshes_again_after_one_minute(self):
        async def exercise():
            task = main.schedule_clean_revenue_refresh("2026-09")
            self.assertIsNotNone(task)
            await task

        refreshed = {"status": "online", "value": 73280.0, "contractor_amount": 10000.0}
        with (
            patch.object(main, "clean_revenue_cache", {"2026-09": {"status": "online", "value": 72030.0}}),
            patch.object(main, "clean_revenue_cache_time", {"2026-09": 939.0}),
            patch.object(main, "clean_revenue_tasks", {}),
            patch.object(main, "clean_revenue_failures", {}),
            patch.object(main.time, "monotonic", return_value=1000.0),
            patch.object(main, "load_clean_revenue", new=AsyncMock(return_value=refreshed)) as load,
            patch.object(main, "broadcast", new=AsyncMock()),
        ):
            asyncio.run(exercise())

        load.assert_awaited_once_with("2026-09")


if __name__ == "__main__":
    unittest.main()
