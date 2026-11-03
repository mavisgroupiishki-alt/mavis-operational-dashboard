import asyncio
import unittest
from dataclasses import replace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import fixed_main, main
from app.bitrix_identity import issue_session, portal_host, read_session
from app.personal_workspace import build_personal_workday


class BitrixIdentityTests(unittest.TestCase):
    def test_salary_route_is_allowed_to_use_the_signed_bitrix_cookie(self):
        self.assertTrue(main.is_public_path("/api/cabinet/salary"))

    def test_call_context_and_activity_actions_reach_their_own_bitrix_session_guard(self):
        """The password middleware must not pre-empt the signed Bitrix session.

        Both endpoints call ``require_bitrix_identity`` themselves and check the
        selected manager/deal afterwards.  If they are omitted here, the
        middleware returns AUTH_REQUIRED before a manager can open a call.
        """
        self.assertTrue(main.is_public_path("/api/cabinet/calls/123/context"))
        self.assertTrue(main.is_public_path("/api/cabinet/activity-action"))

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

    def test_director_can_open_alena_workspace_but_manager_cannot_switch_employee(self):
        configured = replace(main.settings, bitrix_portal_domain="mavisgroup.bitrix24.by", bitrix_local_session_secret="x" * 32)
        director = issue_session(portal="mavisgroup.bitrix24.by", user_id="14", role="director", secret=configured.bitrix_local_session_secret, ttl_seconds=3600)
        manager = issue_session(portal="mavisgroup.bitrix24.by", user_id="9", role="manager", secret=configured.bitrix_local_session_secret, ttl_seconds=3600)
        meta = {"user_options": [{"id": "2272", "name": "Алена Хурсик", "active": True}]}
        calls = AsyncMock(return_value={"ok": True, "status": "online", "data": {"summary": {}, "calls": []}})
        with (
            patch.object(main, "settings", configured),
            patch.object(main.client, "meta", new=AsyncMock(return_value=meta)),
            patch.object(main, "load_jarvis_operations", new=calls),
            TestClient(fixed_main.app, base_url="https://testserver") as client,
        ):
            client.cookies.set("mavis_bitrix_session", manager)
            self.assertEqual(client.get("/api/cabinet/calls?manager_id=2272").status_code, 403)
            client.cookies.set("mavis_bitrix_session", director)
            response = client.get("/api/cabinet/calls?manager_id=2272")
            self.assertEqual(response.status_code, 200)
            calls.assert_awaited_once_with("personal-calls", {"manager_id": "2272"})

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

    def test_salary_uses_the_fact_already_loaded_by_the_workspace(self):
        configured = replace(main.settings, bitrix_portal_domain="mavisgroup.bitrix24.by", bitrix_local_session_secret="x" * 32)
        director = issue_session(portal="mavisgroup.bitrix24.by", user_id="14", role="director", secret=configured.bitrix_local_session_secret, ttl_seconds=3600)
        loader = AsyncMock()
        with (
            patch.object(main, "settings", configured),
            patch.object(main, "build_personal_workday", new=loader),
            TestClient(fixed_main.app, base_url="https://testserver") as client,
        ):
            client.cookies.set("mavis_bitrix_session", director)
            response = client.get("/api/cabinet/salary?fact_amount=1200")
            self.assertEqual(response.status_code, 200)
            loader.assert_not_awaited()

    def test_main_salary_uses_monthly_payroll_plan_before_legacy_settings(self):
        monthly_key = main.payroll_settings_key("12", "2026-11")
        values = {
            monthly_key: {"base": 1800, "plan": 55000},
            "cabinet_salary:12": {"monthly_base": 900, "monthly_plan": 10000, "commission_percent": 5},
        }
        with patch.object(main.storage, "get_setting", side_effect=lambda key, default={}: values.get(key, default)):
            result = main._cabinet_salary("12", "2026-11-03", 2000)
        self.assertEqual(result["monthly_plan"], 55000)
        self.assertEqual(result["monthly_base"], 1800)


class _Client:
    portal = "https://mavisgroup.bitrix24.by"

    async def list_all(self, method, _params, limit=None):
        if method == "voximplant.statistic.get":
            return [
                {"PORTAL_USER_ID": "12", "CALL_DURATION": "61"},
                {"PORTAL_USER_ID": "12", "CALL_DURATION": "59"},
                {"PORTAL_USER_ID": "99", "CALL_DURATION": "360"},
            ]
        if method == "crm.activity.list":
            return [{
                "ID": "700", "OWNER_ID": "10", "OWNER_TYPE_ID": "2", "TYPE_ID": "2",
                "COMPLETED": "N", "DEADLINE": "2026-10-20T10:00:00+03:00",
                "SUBJECT": "Перезвонить клиенту",
            }]
        raise AssertionError(method)

    async def tasks_for_responsible(self, user_id, limit):
        self.assert_user(user_id)
        return [
            {"ID": "1", "STATUS": "2", "DEADLINE": "2026-10-28T10:00:00+03:00", "UF_CRM_TASK_DEAL": "D_99"},
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


class _PromisedContactClient(_Client):
    async def list_all(self, method, params, limit=None):
        if method == "voximplant.statistic.get":
            return []
        if method == "crm.activity.list":
            return []
        raise AssertionError(method)

    async def deal_list(self, filters, _select):
        self.assert_user(filters["ASSIGNED_BY_ID"])
        return [{
            "ID": "10", "TITLE": "Клиент с обещанным звонком", "STAGE_ID": "NEW",
            "SOURCE_ID": "WEB", "UF_CRM_1756973967704": "1",
            "COMMENTS": "Договорились связаться 01.11.2026 и уточнить оплату.",
        }]


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
        self.assertEqual(result["deals"]["overdue_count"], 1)
        self.assertEqual(result["availability"]["stage_sla"], "not_configured")
        self.assertEqual(result["availability"]["iso_suot_registry"], "needs_connection")
        self.assertEqual(result["profile"]["name"], "Анна Жихарева")
        self.assertEqual(result["leads"]["month_count"], 1)
        self.assertEqual(result["deals"]["stages"][0]["name"], "1. Новая сделка")
        self.assertEqual(result["deals"]["conversion"]["created_count"], 1)
        self.assertIn("созданных", result["deals"]["conversion"]["definition"])

    def test_comment_promise_without_activity_or_follow_up_call_is_prioritized(self):
        with patch("app.personal_workspace.datetime") as mocked_datetime:
            from datetime import datetime
            mocked_datetime.now.return_value = datetime.fromisoformat("2026-11-02T12:00:00+03:00")
            mocked_datetime.combine = datetime.combine
            mocked_datetime.fromisoformat = datetime.fromisoformat
            result = asyncio.run(build_personal_workday(_PromisedContactClient(), "12", "2026-11-01", "Europe/Moscow"))
        self.assertEqual(result["deals"]["priorities"][0]["id"], "10")
        self.assertIn("01.11", result["deals"]["priorities"][0]["reason"])

    def test_week_period_returns_a_weekly_call_norm_and_bounds(self):
        with patch("app.personal_workspace.datetime") as mocked_datetime:
            from datetime import datetime
            mocked_datetime.now.return_value = datetime.fromisoformat("2026-10-29T12:00:00+03:00")
            mocked_datetime.combine = datetime.combine
            mocked_datetime.fromisoformat = datetime.fromisoformat
            result = asyncio.run(build_personal_workday(_Client(), "12", "2026-10-28", "Europe/Moscow", "week"))
        self.assertEqual(result["period"], "week")
        self.assertEqual(result["period_start"], "2026-10-26")
        self.assertEqual(result["period_end"], "2026-11-01")
        self.assertEqual(result["calls"]["target"], 250)


class PersonalCallNormalizationTests(unittest.TestCase):
    def test_unscored_reason_and_iso_alert_are_only_taken_from_confirmed_data(self):
        result = main._public_personal_calls({
            "ok": True,
            "status": "online",
            "data": {"calls": [
                {
                    "activityId": "call-1", "client": "ООО Без статуса", "status": "pending",
                    "recommendation": "Анализ ещё не готов",
                },
                {
                    "activityId": "call-2", "client": "ООО Проверка", "score": 8.5,
                    "isoSuot": {"registryMissing": True, "offered": False},
                },
                {
                    "activityId": "call-3", "client": "ООО Неизвестно", "score": 9,
                },
            ]},
        })
        pending, confirmed_gap, unknown = result["data"]["calls"]
        self.assertEqual(pending["notScoredReason"], "Анализ ещё не готов")
        self.assertTrue(confirmed_gap["isoSuotAlert"])
        self.assertEqual(confirmed_gap["isoSuotStatus"], "confirmed_gap")
        self.assertFalse(unknown["isoSuotAlert"])
        self.assertEqual(unknown["isoSuotStatus"], "not_provided")


if __name__ == "__main__":
    unittest.main()
