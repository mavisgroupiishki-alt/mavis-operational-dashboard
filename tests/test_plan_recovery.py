import unittest

from app.recovery import RECOVERED_VALUES, restore_missing_production_plan


class FakeStorage:
    def __init__(self, plans=None):
        self.plans = plans or {}
        self.writes = []

    def plan_dict(self, month):
        return self.plans.get(month, {})

    def set_plans(self, month, scope, context_type, context_key, values):
        self.writes.append((month, scope, context_type, context_key, values))


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


if __name__ == "__main__":
    unittest.main()
