import copy
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import main
from app.main import compact_snapshot_payload


class FastStartupTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
