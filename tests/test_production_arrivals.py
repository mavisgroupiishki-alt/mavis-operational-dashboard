import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from app.metrics import observed_period_end


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


if __name__ == "__main__":
    unittest.main()
