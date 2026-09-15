import asyncio
import copy
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import main
from app.metrics import derive_production_period
from app.main import compact_snapshot_payload


class FastStartupTests(unittest.TestCase):
    def test_prewarm_months_include_current_and_previous_month(self):
        self.assertEqual(
            main.prewarm_months("2026-01"),
            [("2026-01", "month"), ("2025-12", "month")],
        )

    def test_custom_period_is_derived_from_monthly_production_records(self):
        production = {
            "production_at_month_start": {"count": 4, "as_of": "2026-09-01T00:00:00+03:00", "rule": "test"},
        }
        details = {
            "new": [
                {"id": "1", "prod_start": "2026-09-02T00:00:00+03:00", "created": "2026-09-02T00:00:00+03:00", "amount": 100},
                {"id": "2", "prod_start": "2026-09-12T00:00:00+03:00", "created": "2026-09-12T00:00:00+03:00", "amount": 200},
            ],
            "closed": [
                {"id": "1", "close": "2026-09-03T00:00:00+03:00", "amount": 100},
                {"id": "2", "close": "2026-09-13T00:00:00+03:00", "amount": 200},
            ],
            "returns": [], "active": [], "dormant": [], "returned": [],
            "dormant_to_production": [], "dormant_to_return": [],
            "dormant_entered_since_month_start": [], "overdue": [],
            "active_missing_expected": [], "active_missing_service": [],
            "active_missing_expert": [], "closed_without_act": [],
        }

        result = derive_production_period(
            "2026-09", "custom", "Europe/Minsk", production, details,
            "2026-09-02", "2026-09-03",
        )

        self.assertIsNotNone(result)
        derived, derived_details = result
        self.assertEqual(derived["kpi"]["new_count"], 1)
        self.assertEqual(derived["kpi"]["closed_count"], 1)
        self.assertEqual([row["id"] for row in derived_details["new"]], ["1"])
        self.assertEqual([row["id"] for row in derived_details["closed"]], ["1"])

    def test_custom_period_refuses_legacy_month_snapshot_without_production_rows(self):
        base_key = ("2026-09", "month", "", "")
        with (
            patch.object(main, "cache", {base_key: {"ok": True, "production": {}}}),
            patch.object(main, "detail_cache", {base_key: {}}),
        ):
            result = asyncio.run(main.derive_snapshot_from_month_cache(
                "2026-09", "custom", "2026-09-02", "2026-09-03"
            ))

        self.assertFalse(result)

    def test_compact_snapshot_keeps_hub_metrics_and_removes_sales_trees(self):
        source = {
            "ok": True,
            "production": {"kpi": {"closed_count": 4}},
            "sales": {
                "overall": {"total": {"metrics": {"sales": 14}}},
                "stages": [{"name": "Переговоры", "count": 3}],
                "active_deals_count": 9,
                "sale_filter": {"stage_names": ["Продажа"]},
                "classification": {"name": "source"},
                "available_sources": ["Сайт"],
                "groups": [{"name": "Холодные продажи"}],
                "source_blocks": [{"name": "Сайт"}],
                "exact_sources": [{"name": "SEO"}],
                "product_managers": [{"name": "Менеджер"}],
                "product_categories": [{"name": "Продукт"}],
                "managers": [
                    {
                        "name": "Анна",
                        "total": {"metrics": {"sales": 3, "sales_amount": 9000}},
                        "groups": [{"name": "Холодные продажи"}],
                        "sources": [{"name": "Сайт"}],
                    }
                ],
            },
        }
        before = copy.deepcopy(source)

        result = compact_snapshot_payload(source)

        self.assertEqual(result["sales"]["overall"], source["sales"]["overall"])
        self.assertEqual(result["sales"]["stages"], source["sales"]["stages"])
        self.assertEqual(result["sales"]["active_deals_count"], 9)
        self.assertEqual(result["sales"]["managers"], [{"name": "Анна", "total": {"metrics": {"sales": 3, "sales_amount": 9000}}}])
        self.assertFalse(result["sales"]["details_loaded"])
        for key in ("groups", "source_blocks", "exact_sources", "product_managers", "product_categories"):
            self.assertNotIn(key, result["sales"])
        self.assertEqual(source, before)

    def test_compact_snapshot_does_not_require_sales_payload(self):
        source = {"ok": True, "production": {"kpi": {"closed_count": 4}}}

        self.assertEqual(compact_snapshot_payload(source), source)

    def test_sales_section_returns_full_tree_only_when_requested(self):
        key = ("2026-09", "month", "", "")
        full_sales = {
            "overall": {"total": {"metrics": {"sales": 14}}},
            "managers": [{"name": "Анна", "groups": [{"name": "Холодные продажи"}]}],
        }
        with (
            patch.object(main, "cache", {key: {"ok": True}}),
            patch.object(main, "detail_cache", {key: {}}),
            patch.object(main, "_apply_runtime", return_value={"sales": full_sales}),
        ):
            response = TestClient(main.app).get("/api/sales-section?month=2026-09&period=month")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sales"], full_sales)

    def test_render_sync_guard_honors_compact_snapshot(self):
        from app import fixed_main

        key = ("2026-09", "month", "", "")
        snapshot = {
            "ok": True,
            "sales": {
                "overall": {"total": {"metrics": {"sales": 14}}},
                "groups": [{"name": "Холодные продажи"}],
                "managers": [{"name": "Анна", "total": {"metrics": {"sales": 3}}, "groups": [{"name": "Холодные продажи"}]}],
            },
        }
        with (
            patch.object(main, "cache", {key: {"ok": True}}),
            patch.object(main, "detail_cache", {key: {}}),
            patch.object(main, "cache_time", {key: 0}),
            patch.object(main, "operational_snapshot", new=AsyncMock(return_value=snapshot)),
        ):
            response = TestClient(fixed_main.app).get("/api/snapshot?month=2026-09&period=month&compact=1")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("groups", response.json()["sales"])

    def test_render_sync_guard_serves_custom_range_from_month_snapshot(self):
        from app import fixed_main

        base_key = ("2026-09", "month", "", "")
        monthly = {
            "ok": True, "month_key": "2026-09", "period": "month",
            "sales": {"overall": {"total": {"metrics": {"sales": 2}}}},
            "production": {"production_at_month_start": {"count": 0}},
        }
        details = {
            "production": {
                "new": [{"id": "1", "prod_start": "2026-09-02T00:00:00+03:00", "created": "2026-09-02T00:00:00+03:00", "amount": 100}],
                "closed": [{"id": "1", "close": "2026-09-03T00:00:00+03:00", "amount": 100}],
                "returns": [], "active": [], "dormant": [], "returned": [],
                "dormant_to_production": [], "dormant_to_return": [], "dormant_entered_since_month_start": [],
                "overdue": [], "active_missing_expected": [], "active_missing_service": [],
                "active_missing_expert": [], "closed_without_act": [],
            }
        }
        with (
            patch.object(main, "cache", {base_key: monthly}),
            patch.object(main, "detail_cache", {base_key: details}),
            patch.object(main, "cache_time", {base_key: 0}),
            patch.object(main, "operational_snapshot", new=AsyncMock(side_effect=lambda snapshot, _details, _month, **_kwargs: snapshot)),
        ):
            response = TestClient(fixed_main.app).get(
                "/api/snapshot?month=2026-09&period=custom&custom_start=2026-09-02&custom_end=2026-09-03&compact=1"
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["derived_from_month_snapshot"])
        self.assertEqual(response.json()["production"]["kpi"]["closed_count"], 1)

    def test_stale_derived_range_refreshes_month_not_exact_range(self):
        from app import fixed_main

        key = ("2026-09", "custom", "2026-09-02", "2026-09-03")
        derived = {
            "ok": True,
            "derived_from_month_snapshot": True,
            "sales": {"overall": {"total": {"metrics": {}}}},
            "production": {"kpi": {}},
        }
        with (
            patch.object(main, "cache", {key: derived}),
            patch.object(main, "detail_cache", {key: {}}),
            patch.object(main, "cache_time", {key: 0}),
            patch.object(main, "operational_snapshot", new=AsyncMock(side_effect=lambda snapshot, _details, _month, **_kwargs: snapshot)),
            patch.object(fixed_main, "schedule_snapshot") as schedule,
        ):
            response = TestClient(fixed_main.app).get(
                "/api/snapshot?month=2026-09&period=custom&custom_start=2026-09-02&custom_end=2026-09-03"
            )

        self.assertEqual(response.status_code, 200)
        schedule.assert_called_once_with("2026-09", "month", force=True)


if __name__ == "__main__":
    unittest.main()
