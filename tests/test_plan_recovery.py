import unittest

from app.recovery import (
    RECOVERED_VALUES,
    SEPTEMBER_2026_DORMANT_BASELINE,
    restore_confirmed_september_dormant_baseline,
    restore_missing_production_plan,
)


class FakeStorage:
    def __init__(self, plans=None):
        self.plans = plans or {}
        self.writes = []

    def plan_dict(self, month):
        return self.plans.get(month, {})

    def set_plans(self, month, scope, context_type, context_key, values):
        self.writes.append((month, scope, context_type, context_key, values))


class FakeDormantStorage:
    def __init__(self, baseline=None):
        self.baseline = baseline or {}
        self.writes = []

    def dormant_baseline(self, month):
        return self.baseline

    def set_dormant_baseline(self, month, value):
        self.writes.append((month, value))
        self.baseline = value


class PlanRecoveryTests(unittest.TestCase):
    def test_restores_missing_captured_context(self):
        storage = FakeStorage()

        self.assertTrue(restore_missing_production_plan(storage))
        self.assertEqual(storage.writes[0][:4], ("2026-09", "production", "overall", ""))
        self.assertEqual(storage.writes[0][4], RECOVERED_VALUES)

    def test_never_overwrites_existing_plan(self):
        storage = FakeStorage({"2026-09": {"production|overall|": {"closed_count": 999}}})

        self.assertFalse(restore_missing_production_plan(storage))
        self.assertEqual(storage.writes, [])

    def test_replaces_old_september_dormant_baseline_once(self):
        storage = FakeDormantStorage({"count": 298, "source": "confirmed_manual"})

        self.assertTrue(restore_confirmed_september_dormant_baseline(storage))
        self.assertEqual(storage.writes, [("2026-09", SEPTEMBER_2026_DORMANT_BASELINE)])
        self.assertFalse(restore_confirmed_september_dormant_baseline(storage))


if __name__ == "__main__":
    unittest.main()
