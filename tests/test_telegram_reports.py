from datetime import datetime
import unittest
from zoneinfo import ZoneInfo

from app.telegram_reports import ReportDeliveryError, build_daily_report_texts


def snapshot(plan=None, incoming=850):
    plans = {} if plan is None else {"sales|overall|": {"sales_amount": plan}}
    return {
        "clean_revenue": {"status": "online", "incoming_amount": incoming},
        "plans": plans,
        "production": {"kpi": {"closed_count": 0, "closed_amount": 0}},
    }


class TelegramReportsTests(unittest.TestCase):
    def test_manager_style_text_uses_current_fact_and_no_invented_plan(self):
        result = build_daily_report_texts(snapshot(), datetime(2026, 10, 2, 9, tzinfo=ZoneInfo("Europe/Minsk")))

        self.assertEqual(result.sales, (
            "Пятница, 2 октября 2026\n\n"
            "💰 Сумма продаж - 850 BYN\n\n"
            "📈 Факт плана продаж октября - 850 BYN / —"
        ))
        self.assertEqual(result.experts, (
            "Пятница, 2 октября 2026 🍂\n\n"
            "✅ Количество закрытых продуктов - 0 шт\n"
            "💰 Сумма закрытых актов - 0 BYN\n\n"
            "✔ Факт отдела октября - 0 BYN"
        ))


    def test_text_refuses_missing_financial_source(self):
        data = snapshot()
        data["clean_revenue"] = {"status": "updating", "incoming_amount": None}

        with self.assertRaisesRegex(ReportDeliveryError, "Поступления продаж"):
            build_daily_report_texts(data, datetime(2026, 10, 2, tzinfo=ZoneInfo("Europe/Minsk")))
