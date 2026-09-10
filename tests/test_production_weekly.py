import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from app.metrics import filter_prod_details, production_weekly_dynamics


class ProductionWeeklyDynamicsTests(unittest.TestCase):
    def setUp(self):
        self.month_start = datetime(2026, 9, 1, tzinfo=ZoneInfo("Europe/Minsk"))
        self.rows = [
            {"id": "1", "amount": 100.0, "close": "2026-09-01T10:00:00+03:00", "close_week": 0, "prod_days": 10, "norm_days": 14, "in_norm": True, "is_closed_success": True},
            {"id": "2", "amount": 500.0, "close": "2026-09-10T10:00:00+03:00", "close_week": 1, "prod_days": 20, "norm_days": 14, "in_norm": False, "is_closed_success": True},
            {"id": "old", "amount": 900.0, "close": "2026-08-31T10:00:00+03:00", "close_week": -1, "prod_days": 5, "norm_days": 7, "in_norm": True, "is_closed_success": True},
        ]

    def test_weeks_and_days_reconcile_to_monthly_closed_result(self):
        result = production_weekly_dynamics(self.rows, self.month_start)

        self.assertEqual(sum(result["weeks"]["closed_count"]), 2)
        self.assertEqual(sum(result["weeks"]["closed_amount"]), 600)
        self.assertEqual(result["days"]["closed_amount"][0], 100)
        self.assertEqual(result["days"]["closed_amount"][9], 500)

    def test_drilldown_filters_closed_products_by_week_and_day(self):
        details = {"closed": self.rows}

        self.assertEqual([row["id"] for row in filter_prod_details(details, "closed_amount", week=1)], ["2"])
        self.assertEqual([row["id"] for row in filter_prod_details(details, "closed_amount", week=1, day=10)], ["2"])


if __name__ == "__main__":
    unittest.main()
