import asyncio
import unittest
from dataclasses import replace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import fixed_main, main
from app.bitrix_identity import issue_session, portal_host, read_session
from app.personal_workspace import build_personal_workday


class BitrixIdentityTests(unittest.TestCase):
    def test_portal_host_rejects_paths_credentials_and_invalid_ports(self):
        self.assertEqual(portal_host("mavisgroup.bitrix24.by"), "mavisgroup.bitrix24.by")
        self.assertEqual(portal_host("https://evil.test/mavisgroup.bitrix24.by"), "")
        self.assertEqual(portal_host("https://user:pass@mavisgroup.bitrix24.by"), "")
        self.assertEqual(portal_host("https://mavisgroup.bitrix24.by:not-a-port"), "")

    def test_session_is_signed_and_expires(self):
        token = issue_session(
            portal="mavisgroup.bitrix24.by",
            user_id="12",
            role="director",
            secret="x" * 32,
            ttl_seconds=3600,
            now=100,
        )
        self.assertEqual(read_session(token, secret="x" * 32, now=101).role, "director")
        self.assertIsNone(read_session(token + "tampered", secret="x" * 32, now=101))
        self.assertIsNone(read_session(token, secret="x" * 32, now=3700))

    def test_launch_assigns_director_only_by_configured_bitrix_id(self):
        configured = replace(
            main.settings,
            bitrix_portal_domain="mavisgroup.bitrix24.by",
            bitrix_local_application_token="installation-token",
            bitrix_local_session_secret="x" * 32,
            bitrix_director_user_ids="77,88",
        )
        with (
            patch.object(main, "settings", configured),
            patch.object(main, "verify_bitrix_launch", new=AsyncMock(return_value=("mavisgroup.bitrix24.by", "77"))),
            TestClient(fixed_main.app, base_url="https://testserver") as client,
        ):
            launched = client.post("/bitrix/launch", data={"DOMAIN": "mavisgroup.bitrix24.by", "AUTH_ID": "launch-token", "APPLICATION_TOKEN": "installation-token"}, follow_redirects=False)
            self.assertEqual(launched.status_code, 303)
            self.assertEqual(launched.headers["location"], "/cabinet")
            self.assertEqual(client.get("/api/cabinet/me").json()["role"], "director")

    def test_launch_rejects_an_unverified_bitrix_application_token(self):
        configured = replace(
            main.settings,
            bitrix_portal_domain="mavisgroup.bitrix24.by",
            bitrix_local_application_token="installation-token",
            bitrix_local_session_secret="x" * 32,
        )
        verifier = AsyncMock(return_value=("mavisgroup.bitrix24.by", "77"))
        with (
            patch.object(main, "settings", configured),
            patch.object(main, "verify_bitrix_launch", new=verifier),
            TestClient(fixed_main.app, base_url="https://testserver") as client,
        ):
            response = client.post(
                "/bitrix/launch",
                data={"DOMAIN": "mavisgroup.bitrix24.by", "AUTH_ID": "launch-token", "APPLICATION_TOKEN": "forged"},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 403)
            verifier.assert_not_awaited()

    def test_first_install_keeps_only_a_fingerprint_and_then_allows_launch(self):
        configured = replace(
            main.settings,
            bitrix_portal_domain="mavisgroup.bitrix24.by",
            bitrix_local_application_token="",
            bitrix_local_session_secret="x" * 32,
            bitrix_director_user_ids="14",
        )
        saved = {}
        verifier = AsyncMock(return_value=("mavisgroup.bitrix24.by", "14"))
        with (
            patch.object(main, "settings", configured),
            patch.object(main, "verify_bitrix_launch", new=verifier),
            patch.object(main.storage, "get_setting", side_effect=lambda key, default="": saved.get(key, default)),
            patch.object(main.storage, "set_setting", side_effect=lambda key, value: saved.__setitem__(key, value)),
            TestClient(fixed_main.app, base_url="https://testserver") as client,
        ):
            installed = client.post("/bitrix/install?DOMAIN=mavisgroup.bitrix24.by", data={"AUTH_ID": "install", "APPLICATION_TOKEN": "bitrix-private-token"})
            self.assertEqual(installed.status_code, 200)
            self.assertNotIn("bitrix-private-token", str(saved))
            launched = client.post("/bitrix/launch", data={"DOMAIN": "mavisgroup.bitrix24.by", "AUTH_ID": "launch", "APPLICATION_TOKEN": "bitrix-private-token"}, follow_redirects=False)
            self.assertEqual(launched.status_code, 303)

    def test_first_install_rejects_non_director(self):
        configured = replace(
            main.settings,
            bitrix_portal_domain="mavisgroup.bitrix24.by",
            bitrix_local_application_token="",
            bitrix_local_session_secret="x" * 32,
            bitrix_director_user_ids="14",
        )
        with (
            patch.object(main, "settings", configured),
            patch.object(main, "verify_bitrix_launch", new=AsyncMock(return_value=("mavisgroup.bitrix24.by", "99"))),
            TestClient(fixed_main.app, base_url="https://testserver") as client,
        ):
            self.assertEqual(client.post("/bitrix/install", data={"DOMAIN": "mavisgroup.bitrix24.by", "AUTH_ID": "install", "APPLICATION_TOKEN": "token"}).status_code, 403)

    def test_cabinet_api_rejects_an_unverified_browser_user_id(self):
        configured = replace(
            main.settings,
            bitrix_portal_domain="mavisgroup.bitrix24.by",
            bitrix_local_application_token="installation-token",
            bitrix_local_session_secret="x" * 32,
        )
        with patch.object(main, "settings", configured), TestClient(fixed_main.app, base_url="https://testserver") as client:
            self.assertEqual(client.get("/api/cabinet/me?user_id=77").status_code, 401)

    def test_listening_scopes_a_manager_to_own_calls_and_director_to_team(self):
        configured = replace(
            main.settings,
            bitrix_portal_domain="mavisgroup.bitrix24.by",
            bitrix_local_application_token="installation-token",
            bitrix_local_session_secret="x" * 32,
        )
        manager_session = issue_session(
            portal="mavisgroup.bitrix24.by", user_id="9", role="manager",
            secret=configured.bitrix_local_session_secret, ttl_seconds=3600,
        )
        director_session = issue_session(
            portal="mavisgroup.bitrix24.by", user_id="14", role="director",
            secret=configured.bitrix_local_session_secret, ttl_seconds=3600,
        )
        with (
            patch.object(main, "settings", configured),
            patch.object(main, "jarvis_embed_payload", side_effect=lambda **kwargs: {"ok": True, "url": f"https://jarvis.test/dashboard-embed?role={kwargs['role']}&user_id={kwargs['user_id']}"}),
            TestClient(fixed_main.app, base_url="https://testserver") as client,
        ):
            client.cookies.set("mavis_bitrix_session", manager_session)
            manager_response = client.get("/api/cabinet/listening", follow_redirects=False)
            self.assertEqual(manager_response.status_code, 302)
            self.assertIn("role=manager&user_id=9", manager_response.headers["location"])
            client.cookies.set("mavis_bitrix_session", director_session)
            response = client.get("/api/cabinet/listening", follow_redirects=False)
            self.assertEqual(response.status_code, 302)
            self.assertIn("role=director&user_id=", response.headers["location"])

    def test_director_can_configure_salary_but_manager_cannot(self):
        configured = replace(main.settings, bitrix_portal_domain="mavisgroup.bitrix24.by", bitrix_local_session_secret="x" * 32)
        director = issue_session(portal="mavisgroup.bitrix24.by", user_id="14", role="director", secret=configured.bitrix_local_session_secret, ttl_seconds=3600)
        manager = issue_session(portal="mavisgroup.bitrix24.by", user_id="9", role="manager", secret=configured.bitrix_local_session_secret, ttl_seconds=3600)
        saved = {}
        with (
            patch.object(main, "settings", configured),
            patch.object(main.storage, "set_setting", side_effect=lambda key, value: saved.__setitem__(key, value)),
            TestClient(fixed_main.app, base_url="https://testserver") as client,
        ):
            client.cookies.set("mavis_bitrix_session", manager)
            self.assertEqual(client.put("/api/cabinet/salary", json={"user_id": "9", "monthly_base": 1000, "commission_percent": 5, "monthly_plan": 10000}).status_code, 403)
            client.cookies.set("mavis_bitrix_session", director)
            response = client.put("/api/cabinet/salary", json={"user_id": "9", "monthly_base": 1000, "commission_percent": 5, "monthly_plan": 10000})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(saved["cabinet_salary:9"]["commission_percent"], 5)


class _Client:
    portal = "https://mavisgroup.bitrix24.by"

    async def list_all(self, method, _params):
        if method == "voximplant.statistic.get":
            return [
                {"PORTAL_USER_ID": "12", "CALL_DURATION": "61"},
                {"PORTAL_USER_ID": "12", "CALL_DURATION": "59"},
                {"PORTAL_USER_ID": "99", "CALL_DURATION": "360"},
            ]
        raise AssertionError(method)

    async def tasks_for_responsible(self, user_id, limit):
        self.assert_user(user_id)
        return [
            {"ID": "1", "STATUS": "2", "DEADLINE": "2026-10-28T10:00:00+03:00", "UF_CRM_TASK_DEAL": "D_10"},
            {"ID": "2", "STATUS": "5", "DEADLINE": "2026-10-20T10:00:00+03:00", "UF_CRM_TASK_DEAL": "D_11"},
        ]

    async def deal_list(self, filters, _select):
        self.assert_user(filters["ASSIGNED_BY_ID"])
        return [{"ID": "10", "TITLE": "Без источника", "STAGE_ID": "NEW", "CLOSEDATE": "2026-10-28T10:00:00+03:00", "SOURCE_ID": "", "UF_CRM_171455": ""}]

    async def lead_list(self, filters, _select):
        self.assert_user(filters["ASSIGNED_BY_ID"])
        return [{"ID": "88", "TITLE": "Новый лид"}]

    async def meta(self):
        return {"users": {"12": "Анна Жихарева"}, "status_by_entity": {"DEAL_STAGE": {"NEW": "1. Новая сделка"}}}

    @staticmethod
    def assert_user(user_id):
        assert str(user_id) == "12"


class PersonalWorkspaceTests(unittest.TestCase):
    def test_workday_only_counts_authenticated_user_and_keeps_unknown_integrations_honest(self):
        with patch("app.personal_workspace.datetime") as mocked_datetime:
            from datetime import datetime
            mocked_datetime.now.return_value = datetime.fromisoformat("2026-10-29T12:00:00+03:00")
            mocked_datetime.combine = datetime.combine
            mocked_datetime.fromisoformat = datetime.fromisoformat
            result = asyncio.run(build_personal_workday(_Client(), "12", "2026-10-28", "Europe/Moscow"))
        self.assertEqual(result["calls"]["total"], 2)
        self.assertEqual(result["calls"]["successful_from_minute"], 1)
        self.assertEqual(result["tasks"]["overdue_count"], 1)
        self.assertEqual(result["deals"]["without_open_task_count"], 0)
        self.assertEqual(result["availability"]["stage_sla"], "not_configured")
        self.assertEqual(result["availability"]["iso_suot_registry"], "needs_connection")
        self.assertEqual(result["profile"]["name"], "Анна Жихарева")
        self.assertEqual(result["leads"]["month_count"], 1)
        self.assertEqual(result["deals"]["stages"][0]["name"], "1. Новая сделка")


if __name__ == "__main__":
    unittest.main()
