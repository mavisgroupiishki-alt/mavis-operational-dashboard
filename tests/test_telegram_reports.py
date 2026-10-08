import asyncio
from datetime import datetime
import unittest
from zoneinfo import ZoneInfo

from app.telegram_reports import (
    ReportDeliveryError,
    SALES_BI_MANAGERS,
    _dashboard_financial_values_ready,
    _safe_page_location,
    _wait_for_bi_report_ready,
    build_daily_report_texts,
)


def snapshot(plan=None, clean_revenue=700, daily_clean_revenue=120, incoming=850):
    plans = {} if plan is None else {"sales|overall|": {"sales_amount": plan}}
    return {
        "clean_revenue": {"status": "online", "value": clean_revenue, "incoming_amount": incoming},
        "daily_sales": {"clean_revenue": {"status": "online", "value": daily_clean_revenue}},
        "plans": plans,
        "production": {"kpi": {"closed_count": 0, "closed_amount": 0}},
    }


class TelegramReportsTests(unittest.TestCase):
    def test_dashboard_capture_refuses_finance_loading_labels(self):
        self.assertFalse(_dashboard_financial_values_ready(["Считаю…", "Считаю…", "Считаю…"]))
        self.assertFalse(_dashboard_financial_values_ready(["—", "—", "—"]))
        self.assertTrue(_dashboard_financial_values_ready([
            "4 450 BYN", "4 450 BYN", "22 348 BYN / 135 000 BYN",
        ]))

    def test_bi_reports_are_limited_to_the_sales_department(self):
        self.assertEqual(SALES_BI_MANAGERS, (
            "Алена Хурсик",
            "Ирина Базылева",
            "Ирина Богомольцева",
            "Роман Авсеенко",
        ))

    def test_bi_capture_waits_until_loading_indicators_disappear(self):
        frame = _FakeBiFrame([True, False, False])

        asyncio.run(_wait_for_bi_report_ready(frame, timeout_ms=10, poll_ms=1, stable_ms=1))

        self.assertGreaterEqual(frame.wait_count, 2)

    def test_bi_capture_refuses_a_report_that_keeps_loading(self):
        frame = _FakeBiFrame([True])

        with self.assertRaisesRegex(ReportDeliveryError, "не завершил подготовку"):
            asyncio.run(_wait_for_bi_report_ready(frame, timeout_ms=3, poll_ms=1, stable_ms=1))

    def test_safe_page_location_hides_oauth_query(self):
        self.assertEqual(
            _safe_page_location("https://auth2.bitrix24.by/oauth?state=secret&token=secret"),
            "auth2.bitrix24.by/oauth",
        )

    def test_manager_style_text_uses_current_fact_and_no_invented_plan(self):
        result = build_daily_report_texts(snapshot(), datetime(2026, 10, 2, 9, tzinfo=ZoneInfo("Europe/Minsk")))

        self.assertEqual(result.sales, (
            "Пятница, 2 октября 2026\n\n"
            "💰 Сумма продаж - 120 BYN\n\n"
            "📈 Факт плана продаж октября - 700 BYN / —"
        ))
        self.assertEqual(result.experts, (
            "Пятница, 2 октября 2026 🍂\n\n"
            "✅ Количество закрытых продуктов - 0 шт\n"
            "💰 Сумма закрытых актов - 0 BYN\n\n"
            "✔ Факт отдела октября - 0 BYN"
        ))


    def test_text_refuses_missing_financial_source(self):
        data = snapshot()
        data["clean_revenue"] = {"status": "updating", "value": None, "incoming_amount": 999}

        with self.assertRaisesRegex(ReportDeliveryError, "Чистая выручка"):
            build_daily_report_texts(data, datetime(2026, 10, 2, tzinfo=ZoneInfo("Europe/Minsk")))

    def test_text_refuses_month_revenue_as_a_substitute_for_daily_sales(self):
        data = snapshot()
        data.pop("daily_sales")

        with self.assertRaisesRegex(ReportDeliveryError, "за день"):
            build_daily_report_texts(data, datetime(2026, 10, 2, tzinfo=ZoneInfo("Europe/Minsk")))


class _FakeBiFrame:
    def __init__(self, loading_states):
        self.loading_states = loading_states
        self.index = 0
        self.wait_count = 0

    def get_by_text(self, text, exact=False):
        if text != "Готовим данные отчёта" or not exact:
            raise AssertionError("Expected an exact BI loading indicator query")
        return _FakeLoadingIndicator(self)

    async def wait_for_timeout(self, _milliseconds):
        self.wait_count += 1
        self.index += 1


class _FakeLoadingIndicator:
    def __init__(self, frame):
        self.frame = frame

    async def count(self):
        return 1

    def nth(self, _index):
        return self

    async def is_visible(self):
        return self.frame.loading_states[min(self.frame.index, len(self.frame.loading_states) - 1)]
