import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app import main


class FakeStorage:
    def __init__(self):
        self.values = {}

    def dormant_baseline(self, month):
        return self.values.get(month, {})

    def set_dormant_baseline(self, month, value):
        self.values[month] = value


class DormantFlowTests(unittest.TestCase):
    def test_september_uses_confirmed_first_day_total_without_overwrite(self):
        storage = FakeStorage()
        with patch.object(main, "storage", storage):
            baseline = main._capture_dormant_baseline("2026-09", {"production": {"dormant": [{"id": "1"}]}})
            again = main._capture_dormant_baseline("2026-09", {"production": {"dormant": [{"id": "2"}]}})

        self.assertEqual(baseline["count"], 298)
        self.assertEqual(again["count"], 298)
        self.assertEqual(again["ids"], [])

    def test_future_month_captures_ids_only_on_the_first_day(self):
        storage = FakeStorage()
        first_day = datetime(2026, 10, 1, 8, tzinfo=ZoneInfo("Europe/Minsk"))
        with patch.object(main, "storage", storage):
            baseline = main._capture_dormant_baseline("2026-10", {"production": {"dormant": [{"id": 22}, {"id": "31"}]}}, first_day)

        self.assertEqual(baseline["count"], 2)
        self.assertEqual(baseline["ids"], ["22", "31"])

    def test_flow_counts_only_saved_cohort_transitions(self):
        storage = FakeStorage()
        storage.set_dormant_baseline("2026-10", {"baseline_date": "2026-10-01", "count": 2, "ids": ["22", "31"]})
        details = {"production": {"dormant": [{"id": "22"}], "dormant_to_return": [{"id": "31"}, {"id": "99"}], "dormant_to_production": [{"id": "22"}]}}
        with patch.object(main, "storage", storage):
            flow = main._stuck_flow("2026-10", details, datetime(2026, 10, 4, tzinfo=ZoneInfo("Europe/Minsk")))

        self.assertEqual(flow["current_count"], 1)
        self.assertEqual(flow["to_returns_count"], 1)
        self.assertEqual(flow["to_production_count"], 1)
        self.assertEqual(flow["current_delta"], {"value": -1, "pct": -50.0})


if __name__ == "__main__":
    unittest.main()
