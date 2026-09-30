import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from app.metrics import aggregate_sales, sales_block


TZ = ZoneInfo("Europe/Minsk")
MONTH_START = datetime(2026, 9, 1, tzinfo=TZ)


def lead(identifier, day, qualified):
    return {
        "id": identifier,
        "period_type": "current",
        "week": 0 if day <= 7 else 1,
        "created": f"2026-09-{day:02d}T10:00:00+03:00",
        "is_qualified": qualified,
    }


def deal(identifier, created_day, *, sold=False, close_day=None, previous=False):
    created_month = "2026-08" if previous else "2026-09"
    creation_week = -1 if previous else (0 if created_day <= 7 else 1)
    sale_week = (0 if close_day <= 7 else 1 if close_day <= 14 else 2) if close_day else -1
    return {
        "id": identifier,
        "title": identifier,
        "manager": "Менеджер",
        "source": "Источник",
        "url": "",
        "period_type": "previous" if previous else "current",
        "creation_week": creation_week,
        "sale_week": sale_week,
        "created": f"{created_month}-{created_day:02d}T10:00:00+03:00",
        "close": f"2026-09-{close_day:02d}T10:00:00+03:00" if close_day else None,
        "is_won": sold,
        "sale_in_report_month": sold,
        "is_lost": False,
        "lost_in_report_month": False,
        "amount": 1000,
        "products": [{"name": "СПК", "category": "Строительство", "quantity": 1, "amount": 1000}],
    }


class SalesWeeklyCohortTests(unittest.TestCase):
    def test_source_less_automatic_deal_is_repeat_not_incoming(self):
        self.assertEqual(
            sales_block("Новый", "Прочее", source_missing=True),
            "Повторные продажи по базе",
        )
        self.assertEqual(
            sales_block("Новый", "Google реклама", source_missing=False),
            "Входящий трафик продажи",
        )

    def test_weekly_and_daily_conversion_exclude_sales_tail(self):
        records = {
            "leads": [lead("l1", 2, True), lead("l2", 2, False), lead("l3", 10, True)],
            "deals": [
                deal("d1", 2),
                deal("d2", 2),
                # Created in week 2 and successful in week 3: it belongs to
                # the week-2 conversion cohort, not to the week-3 sales flow.
                deal("d3", 10, sold=True, close_day=15),
                # This is a tail sale created before September. It remains in
                # the sales flow but must not affect a September week cohort.
                deal("tail", 20, sold=True, close_day=3, previous=True),
            ],
        }

        result = aggregate_sales(records, "total", month_start=MONTH_START)
        weeks = result["weeks"]
        days = result["days"]

        self.assertEqual(weeks["sales"][0], 1)
        self.assertEqual(weeks["lead_to_sale_rate"][0], 0)
        self.assertEqual(weeks["qualified_to_sale_rate"][0], 0)
        self.assertEqual(weeks["deal_to_sale_rate"][0], 0)
        self.assertEqual(weeks["week_tail_deals"][0], 1)
        self.assertEqual(weeks["total_deal_to_sale_rate"][0], 33.3)
        self.assertEqual(weeks["product_sale_rate"][0], 0)

        self.assertEqual(weeks["lead_to_sale_rate"][1], 100)
        self.assertEqual(weeks["qualified_to_sale_rate"][1], 100)
        self.assertEqual(weeks["deal_to_sale_rate"][1], 100)
        self.assertEqual(weeks["total_deal_to_sale_rate"][1], 0)
        self.assertEqual(weeks["product_sale_rate"][1], 100)

        # Day 10 (index 9) keeps the same cohort rule as the weekly tile.
        self.assertEqual(days["deal_to_sale_rate"][9], 100)
        self.assertEqual(days["lead_to_sale_rate"][9], 100)

    def test_sales_flow_exposes_tail_separately_from_creation_cohort(self):
        records = {
            "leads": [],
            "deals": [
                # Created in week 1 but sold in week 2: it is a conversion
                # of the first week's cohort, not a week-2 created sale.
                deal("current", 2, sold=True, close_day=10),
                # A historical deal sold in week 2 must be visible as tail,
                # without inflating the current creation cohort.
                deal("tail", 20, sold=True, close_day=10, previous=True),
            ],
        }

        result = aggregate_sales(records, "total", month_start=MONTH_START)

        self.assertEqual(result["metrics"]["deal_to_sale_rate"], 100)
        self.assertEqual(result["metrics"]["tail_deal_to_sale_rate"], 100)
        self.assertEqual(result["metrics"]["total_deal_to_sale_rate"], 100)
        self.assertEqual(result["weeks"]["cohort_sales"][0], 1)
        self.assertEqual(result["weeks"]["tail_sales"][1], 1)
        self.assertEqual(result["weeks"]["sales"][1], 2)
        self.assertEqual(result["weeks"]["week_tail_deals"][1], 2)
        self.assertEqual(result["weeks"]["total_deal_to_sale_rate"][1], 100)

    def test_client_type_breakdown_keeps_its_own_tail(self):
        current = deal("new", 2, sold=True, close_day=10)
        current["client_type"] = "Новый"
        tail = deal("repeat", 20, sold=True, close_day=10, previous=True)
        tail["client_type"] = "Повторный"
        records = {"leads": [], "deals": [current, tail]}

        result = aggregate_sales(records, "total", client_type="Повторный", month_start=MONTH_START)

        self.assertEqual(result["metrics"]["sales"], 1)
        self.assertEqual(result["metrics"]["tail_sales"], 1)
        self.assertEqual(result["metrics"]["cohort_sales"], 0)


if __name__ == "__main__":
    unittest.main()
