import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from app.metrics import F_SALES_LINK, exclude_dormant_to_production, has_sales_origin, observed_period_end, was_in_production_on


class ProductionArrivalFactTests(unittest.TestCase):
    def test_current_period_stops_at_the_end_of_today(self):
        tz = ZoneInfo("Europe/Minsk")
        now = datetime(2026, 9, 11, 12, 0, tzinfo=tz)
        month_end = datetime(2026, 10, 1, tzinfo=tz)

        self.assertEqual(
            observed_period_end(month_end, now),
            datetime(2026, 9, 12, tzinfo=tz),
        )

    def test_finished_period_keeps_its_original_end(self):
        tz = ZoneInfo("Europe/Minsk")
        now = datetime(2026, 9, 11, 12, 0, tzinfo=tz)
        august_end = datetime(2026, 9, 1, tzinfo=tz)

        self.assertEqual(observed_period_end(august_end, now), august_end)

    def test_counts_only_deals_active_in_production_at_start_of_day(self):
        tz = ZoneInfo("Europe/Minsk")
        boundary = datetime(2026, 9, 1, tzinfo=tz)

        self.assertTrue(was_in_production_on({"UF_CRM_1703225329": "2026-08-31T10:00:00+03:00"}, boundary, tz))
        self.assertFalse(was_in_production_on({"UF_CRM_1703225329": "2026-09-01T10:00:00+03:00"}, boundary, tz))
        self.assertFalse(was_in_production_on({"UF_CRM_1703225329": "2026-08-20T10:00:00+03:00", "CLOSEDATE": "2026-08-31T18:00:00+03:00"}, boundary, tz))

    def test_arrivals_require_a_link_to_a_sales_deal(self):
        self.assertTrue(has_sales_origin({F_SALES_LINK: "D_123"}))
        self.assertTrue(has_sales_origin({F_SALES_LINK: ["", {"id": 123}]}))
        self.assertFalse(has_sales_origin({F_SALES_LINK: ""}))
        self.assertFalse(has_sales_origin({F_SALES_LINK: ["", None, 0]}))

    def test_arrivals_exclude_cards_transferred_from_dormant_funnel(self):
        rows = [{"ID": "101"}, {"ID": "102"}]
        self.assertEqual(exclude_dormant_to_production(rows, {"102"}), [{"ID": "101"}])



if __name__ == "__main__":
    unittest.main()
