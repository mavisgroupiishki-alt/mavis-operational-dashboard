import copy
import unittest
from dataclasses import replace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import fixed_main, main


class MarketerAccessTests(unittest.TestCase):
    def setUp(self):
        self.access_settings = replace(
            main.settings,
            view_password="owner-password",
            marketer_password="marketer-password",
            dashboard_session_secret="test-session-secret",
        )
        self.key = ("2026-09", "month", "", "")
        self.snapshot = {
            "ok": True,
            "month_key": "2026-09",
            "period": "month",
            "updated_at": "2026-09-24T12:00:00+03:00",
            "sales": {
                "overall": {"total": {"metrics": {"sales": 49, "sales_amount": 89600}}},
                "managers": [{"name": "Ирина", "total": {"metrics": {"sales": 20}}}],
            },
            "production": {"kpi": {"closed_count": 18, "closed_amount": 22450}},
            "plans": {"sales|overall|": {"sales_amount": 160000}},
        }

    def _client(self):
        cache = {self.key: {"ok": True}}
        return TestClient(fixed_main.app), cache

    def test_marketer_snapshot_redacts_operational_values_and_blocks_drilldown(self):
        with (
            patch.object(main, "settings", self.access_settings),
            patch.object(main, "cache", {self.key: {"ok": True}}),
            patch.object(main, "detail_cache", {self.key: {}}),
            patch.object(main, "cache_time", {self.key: 0}),
            patch.object(main, "operational_snapshot", new=AsyncMock(return_value=copy.deepcopy(self.snapshot))),
            patch.object(main, "load_jarvis_operations", new=AsyncMock(return_value={"ok": True, "status": "online", "data": {"summary": {"sales": 12}}})),
        ):
            with TestClient(fixed_main.app, base_url="https://testserver") as client:
                login = client.post("/login", data={"password": "marketer-password"}, follow_redirects=False)
                self.assertEqual(login.status_code, 303)
                payload = client.get("/api/snapshot?month=2026-09&period=month&compact=1").json()
                self.assertEqual(payload["access"], {"role": "marketer", "masked": True})
                self.assertIsNone(payload["sales"]["overall"]["total"]["metrics"]["sales"])
                self.assertEqual(payload["sales"]["managers"][0]["name"], "")
                self.assertIsNone(payload["production"]["kpi"]["closed_amount"])
                blocked = client.get("/api/drilldown?scope=sales&metric=sales&month=2026-09")
                self.assertEqual(blocked.status_code, 403)
                self.assertEqual(client.get("/api/sales-section?month=2026-09&period=month").status_code, 403)
                marketing = client.get("/api/marketing?month=2026-09")
                self.assertEqual(marketing.status_code, 200)
                self.assertEqual(marketing.json()["data"]["summary"]["sales"], 12)

    def test_full_access_keeps_operational_values(self):
        with (
            patch.object(main, "settings", self.access_settings),
            patch.object(main, "cache", {self.key: {"ok": True}}),
            patch.object(main, "detail_cache", {self.key: {}}),
            patch.object(main, "cache_time", {self.key: 0}),
            patch.object(main, "operational_snapshot", new=AsyncMock(return_value=copy.deepcopy(self.snapshot))),
        ):
            with TestClient(fixed_main.app, base_url="https://testserver") as client:
                login = client.post("/login", data={"password": "owner-password"}, follow_redirects=False)
                self.assertEqual(login.status_code, 303)
                payload = client.get("/api/snapshot?month=2026-09&period=month&compact=1").json()
                self.assertNotIn("access", payload)
                self.assertEqual(payload["sales"]["overall"]["total"]["metrics"]["sales"], 49)
                self.assertEqual(payload["production"]["kpi"]["closed_amount"], 22450)

    def test_forged_role_cookie_does_not_grant_access(self):
        with patch.object(main, "settings", self.access_settings):
            with TestClient(fixed_main.app, base_url="https://testserver") as client:
                client.cookies.set("mavis_access", "full.not-a-valid-signature")
                response = client.get("/api/snapshot?month=2026-09&period=month")
                self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
