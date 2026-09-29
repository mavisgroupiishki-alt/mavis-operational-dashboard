import asyncio
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app import main


class FakeBitrix:
    portal = "https://portal.example"

    async def deal_list(self, filters, select):
        self.asserted_deal_filter = filters
        return [
            {"ID": "101", "TITLE": "Проект А", "COMPANY_ID": "10", "ASSIGNED_BY_ID": "7", "STAGE_ID": "NEW"},
            {"ID": "102", "TITLE": "Проект Б", "COMPANY_ID": "20", "ASSIGNED_BY_ID": "8", "STAGE_ID": "PREPARATION"},
            {"ID": "103", "TITLE": "Без компании", "COMPANY_ID": "", "ASSIGNED_BY_ID": "8", "STAGE_ID": "NEW"},
        ]

    async def list_all(self, method, params):
        if method == "crm.company.list":
            return [{"ID": "10", "TITLE": "Альфа"}, {"ID": "20", "TITLE": "Бета"}]
        if method == "crm.activity.list":
            owner_type = params["filter"]["OWNER_TYPE_ID"]
            if owner_type == 2:
                # A recent call is linked to the deal of company Альфа.
                return [{"OWNER_ID": "101", "OWNER_TYPE_ID": "2", "TYPE_ID": "2", "CREATED": "2026-09-28T09:00:00+03:00"}]
            if owner_type == 4:
                return []
        raise AssertionError(f"Unexpected Bitrix request: {method} {params}")

    async def meta(self):
        return {"users": {"7": "Анна", "8": "Ирина"}}


class DashboardChatCommunicationTests(unittest.TestCase):
    def setUp(self):
        main.communication_gap_cache.clear()

    def test_gap_list_uses_recent_calls_from_deal_or_company(self):
        now = datetime(2026, 9, 29, 12, 0, tzinfo=ZoneInfo("Europe/Minsk"))
        with patch.object(main, "client", FakeBitrix()):
            result = asyncio.run(main.load_sales_communication_gaps(now))

        self.assertEqual(result["status"], "online")
        self.assertEqual(result["active_companies"], 2)
        self.assertEqual(result["active_deals_without_company"], 1)
        self.assertEqual(result["companies_without_call_count"], 1)
        self.assertEqual(result["companies_without_call"], [{
            "company_id": "20",
            "company": "Бета",
            "active_deals": 1,
            "deal_id": "102",
            "deal_title": "Проект Б",
            "manager": "Ирина",
            "stage": "PREPARATION",
            "url": "https://portal.example/crm/deal/details/102/",
        }])

    def test_chat_context_marks_missing_call_history_as_unavailable(self):
        async def unavailable():
            return {"status": "unavailable", "scope_note": "История звонков временно недоступна."}

        with patch.object(main, "load_sales_communication_gaps", unavailable), patch.object(main.storage, "key_task_team", return_value=[]):
            context = asyncio.run(main._dashboard_chat_context("2026-09", "month"))

        self.assertEqual(context["communications"]["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
