import asyncio
import unittest
from dataclasses import replace
from datetime import date
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import fixed_main, main
from app.bitrix_identity import issue_session, portal_host, read_session
from app.personal_workspace import _document_deadline, _stage_sla_state, build_personal_workday


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

    def test_call_context_returns_deal_amount_without_a_server_error(self):
        """The call detail card must remain usable when a linked deal is present."""
        configured = replace(main.settings, bitrix_portal_domain="mavisgroup.bitrix24.by", bitrix_local_session_secret="x" * 32)
        session = issue_session(
            portal="mavisgroup.bitrix24.by", user_id="9", role="manager",
            secret=configured.bitrix_local_session_secret, ttl_seconds=3600,
        )
        calls = AsyncMock(return_value={"ok": True, "status": "online", "data": {"calls": [
            {"activityId": "call-1", "dealId": "19796", "client": "ООО Тест", "score": 9},
        ]}})
        with (
            patch.object(main, "settings", configured),
            patch.object(main, "load_jarvis_operations", new=calls),
            patch.object(main.client, "call", new=AsyncMock(return_value={"result": {
                "ID": "19796", "TITLE": "ООО Тест", "STAGE_ID": "C1:NEW", "OPPORTUNITY": "1200.50",
                "COMPANY_TITLE": "ООО Тест", "DATE_MODIFY": "2026-11-03T10:00:00+03:00",
            }})),
            patch.object(main.client, "meta", new=AsyncMock(return_value={"statuses": {"C1:NEW": "Новая сделка"}})),
            patch.object(main, "_aiai_deal_context_summary", new=AsyncMock(return_value={"status": "unavailable"})),
            patch.object(main, "_registry_context", new=AsyncMock(return_value={"status": "online"})),
            TestClient(fixed_main.app, base_url="https://testserver") as client,
        ):
            client.cookies.set("mavis_bitrix_session", session)
            response = client.get("/api/cabinet/calls/call-1/context")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["deal"]["amount"], 1200.5)

    def test_registry_hydration_never_uses_company_name_without_an_unp(self):
        workday = {"iso_suot": {"candidates": [{"id": "10", "title": "Похожее название", "company": "Похожее название", "company_id": "55"}]}, "deals": {"priorities": []}, "availability": {}}
        lookup = AsyncMock(return_value={"status": "not_provided"})
        with (
            patch.object(main.client, "product_rows_many", new=AsyncMock(return_value={})),
            patch.object(main, "_company_unps", new=AsyncMock(return_value={})),
            patch.object(main, "_company_prior_iso_sales", new=AsyncMock(return_value={})),
            patch.object(main, "_manager_iso_suot_offers", new=AsyncMock(return_value={})),
            patch.object(main, "_registry_context", new=lookup),
        ):
            asyncio.run(main._hydrate_cabinet_registry(workday))
        lookup.assert_awaited_once_with("")
        self.assertEqual(workday["iso_suot"]["confirmed_gaps"], [])
        self.assertEqual(workday["iso_suot"]["candidates"][0]["registry"]["status"], "not_provided")

    def test_registry_hydration_requires_history_and_explicit_unoffered_call(self):
        workday = {"iso_suot": {"candidates": [{"id": "10", "title": "Компания", "company_id": "55"}]}, "deals": {"priorities": []}, "availability": {}}
        registry = AsyncMock(return_value={"status": "not_found"})
        with (
            patch.object(main.client, "product_rows_many", new=AsyncMock(return_value={})),
            patch.object(main, "_company_unps", new=AsyncMock(return_value={"55": "123456789"})),
            patch.object(main, "_company_prior_iso_sales", new=AsyncMock(return_value={"55": False})),
            patch.object(main, "_manager_iso_suot_offers", new=AsyncMock(return_value={"10": {"offered": False, "activity_id": "call-1"}})),
            patch.object(main, "_registry_context", new=registry),
        ):
            asyncio.run(main._hydrate_cabinet_registry(workday, "12"))
        registry.assert_awaited_once_with("123456789")
        self.assertEqual(len(workday["iso_suot"]["confirmed_gaps"]), 1)

    def test_registry_hydration_does_not_signal_when_previous_sale_already_has_iso(self):
        workday = {"iso_suot": {"candidates": [{"id": "10", "title": "Компания", "company_id": "55"}]}, "deals": {"priorities": []}, "availability": {}}
        with (
            patch.object(main.client, "product_rows_many", new=AsyncMock(return_value={})),
            patch.object(main, "_company_unps", new=AsyncMock(return_value={"55": "123456789"})),
            patch.object(main, "_company_prior_iso_sales", new=AsyncMock(return_value={"55": True})),
            patch.object(main, "_manager_iso_suot_offers", new=AsyncMock(return_value={"10": {"offered": False}})),
            patch.object(main, "_registry_context", new=AsyncMock(return_value={"status": "not_found"})),
        ):
            asyncio.run(main._hydrate_cabinet_registry(workday, "12"))
        self.assertEqual(workday["iso_suot"]["confirmed_gaps"], [])

    def test_registry_hydration_does_not_signal_when_sales_history_is_unavailable(self):
        workday = {"iso_suot": {"candidates": [{"id": "10", "title": "Компания", "company_id": "55"}]}, "deals": {"priorities": []}, "availability": {}}
        with (
            patch.object(main.client, "product_rows_many", new=AsyncMock(return_value={})),
            patch.object(main, "_company_unps", new=AsyncMock(return_value={"55": "123456789"})),
            patch.object(main, "_company_prior_iso_sales", new=AsyncMock(return_value={"55": None})),
            patch.object(main, "_manager_iso_suot_offers", new=AsyncMock(return_value={"10": {"offered": False}})),
            patch.object(main, "_registry_context", new=AsyncMock(return_value={"status": "not_found"})),
        ):
            asyncio.run(main._hydrate_cabinet_registry(workday, "12"))
        self.assertFalse(workday["iso_suot"]["candidates"][0]["sales_history_checked"])
        self.assertEqual(workday["iso_suot"]["confirmed_gaps"], [])

    def test_registry_hydration_does_not_signal_when_current_product_is_iso(self):
        workday = {"iso_suot": {"candidates": [{"id": "10", "title": "Компания", "company_id": "55"}]}, "deals": {"priorities": []}, "availability": {}}
        with (
            patch.object(main.client, "product_rows_many", new=AsyncMock(return_value={"10": [{"PRODUCT_NAME": "ИСО 9001"}]})),
            patch.object(main, "_company_unps", new=AsyncMock(return_value={"55": "123456789"})),
            patch.object(main, "_company_prior_iso_sales", new=AsyncMock(return_value={"55": False})),
            patch.object(main, "_manager_iso_suot_offers", new=AsyncMock(return_value={"10": {"offered": False}})),
            patch.object(main, "_registry_context", new=AsyncMock(return_value={"status": "not_found"})),
        ):
            asyncio.run(main._hydrate_cabinet_registry(workday, "12"))
        self.assertEqual(workday["iso_suot"]["confirmed_gaps"], [])

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
        return [{"ID": "10", "TITLE": "Без источника", "STAGE_ID": "NEW", "CLOSEDATE": "2026-10-28T10:00:00+03:00", "MOVED_TIME": "2026-10-27T10:00:00+03:00", "SOURCE_ID": "", "UF_CRM_171455": ""}]

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


class _NoTouchClient(_Client):
    async def list_all(self, method, params, limit=None):
        if method == "voximplant.statistic.get":
            return []
        if method == "crm.activity.list":
            if params["filter"]["COMPLETED"] == "Y":
                return [{"ID": "701", "OWNER_ID": "10", "COMPLETED": "Y", "LAST_UPDATED": "2026-10-15T10:00:00+03:00"}]
            return []
        raise AssertionError(method)

    async def deal_list(self, filters, _select):
        self.assert_user(filters["ASSIGNED_BY_ID"])
        return [{
            "ID": "10", "TITLE": "Давняя сделка без касания", "STAGE_ID": "NEW",
            "DATE_CREATE": "2026-10-01T10:00:00+03:00", "MOVED_TIME": "2026-10-01T10:00:00+03:00",
            "SOURCE_ID": "WEB", "UF_CRM_171455": "",
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
        self.assertEqual(result["availability"]["stage_sla"], "online")
        self.assertEqual(result["availability"]["iso_suot_registry"], "needs_connection")
        self.assertEqual(result["profile"]["name"], "Анна Жихарева")
        self.assertEqual(result["leads"]["month_count"], 1)
        self.assertEqual(result["deals"]["stages"][0]["name"], "1. Новая сделка")
        self.assertEqual(result["deals"]["conversion"]["created_count"], 1)
        self.assertIn("созданных", result["deals"]["conversion"]["definition"])
        self.assertEqual(result["stage_sla"]["breached_count"], 1)
        self.assertEqual(result["stage_sla"]["breached"][0]["stage_sla"]["rule"], "До конца рабочего дня")
        self.assertGreater(result["stage_sla"]["breached"][0]["stage_sla"]["actual_days"], 1)
        self.assertEqual(result["deals"]["next_step"]["percent"], 100.0)
        self.assertEqual(result["deals"]["stage_averages"][0]["stage"], "1. Новая сделка")
        self.assertEqual(result["deals"]["call_to_next_step"]["successful_linked_calls"], 0)

    def test_document_deadline_requires_a_document_keyword_and_explicit_near_date(self):
        from datetime import date
        self.assertEqual(_document_deadline("БИС действует до 21.11.2026", date(2026, 11, 4)), date(2026, 11, 21))
        self.assertIsNone(_document_deadline("Созвониться 21.11.2026", date(2026, 11, 4)))

    def test_kp_stage_sla_exposes_norm_fact_and_excess(self):
        from datetime import datetime
        moved = datetime.fromisoformat("2026-10-01T10:00:00+03:00")
        now = datetime.fromisoformat("2026-10-05T10:00:00+03:00")
        state = _stage_sla_state("КП отправлено", moved, now)
        self.assertEqual(state["rule"], "Не более 2 дней")
        self.assertEqual(state["limit_days"], 2)
        self.assertEqual(state["actual_days"], 4)
        self.assertEqual(state["overdue_hours"], 48)

    def test_comment_promise_without_activity_or_follow_up_call_is_prioritized(self):
        with patch("app.personal_workspace.datetime") as mocked_datetime:
            from datetime import datetime
            mocked_datetime.now.return_value = datetime.fromisoformat("2026-11-02T12:00:00+03:00")
            mocked_datetime.combine = datetime.combine
            mocked_datetime.fromisoformat = datetime.fromisoformat
            result = asyncio.run(build_personal_workday(_PromisedContactClient(), "12", "2026-11-01", "Europe/Moscow"))
        self.assertEqual(result["deals"]["priorities"][0]["id"], "10")
        self.assertIn("01.11", result["deals"]["priorities"][0]["reason"])

    def test_deferred_demand_uses_the_explicit_call_agreement_not_last_touch(self):
        workday = {
            "deals": {
                "priorities": [],
                "deferred_demand": [{
                    "id": "10", "title": "Отложенный спрос", "comments": "Клиент просил перезвонить позже.",
                    "last_touch_at": "2026-11-04T15:00:00+03:00", "url": "https://portal/crm/deal/details/10/",
                }],
            },
            "availability": {},
        }
        main._hydrate_deferred_demand_agreements(workday, {
            "10": {"status": "online", "agreement": {
                "date": "2026-11-03", "source": "разбор Jarvis", "evidence": "Договорились перезвонить 03.11.2026.",
            }},
        }, date(2026, 11, 5))
        row = workday["deals"]["deferred_demand"][0]
        self.assertEqual(row["agreement"]["source"], "разбор Jarvis")
        self.assertEqual(row["agreement_status"], "contact_due")
        self.assertIn("10", {item["id"] for item in workday["deals"]["priorities"]})
        self.assertIn("не заменяет", row["reason"])

    def test_deferred_demand_without_explicit_agreement_requires_review(self):
        workday = {
            "deals": {"priorities": [], "deferred_demand": [{
                "id": "10", "title": "Отложенный спрос", "comments": "Клиент подумает.",
                "last_touch_at": "2026-11-04T15:00:00+03:00", "url": "https://portal/crm/deal/details/10/",
            }]},
            "availability": {},
        }
        main._hydrate_deferred_demand_agreements(workday, {"10": {"status": "online"}}, date(2026, 11, 5))
        row = workday["deals"]["deferred_demand"][0]
        self.assertEqual(row["agreement_status"], "requires_review")
        self.assertIn("не подтверждена", row["reason"])
        self.assertIn("10", {item["id"] for item in workday["deals"]["priorities"]})

    def test_jarvis_deferred_agreement_requires_contact_and_an_explicit_date(self):
        agreement = main._deferred_call_agreement({
            "recommendation": "Договорились перезвонить клиенту 12.11.2026 и уточнить решение.",
        }, date(2026, 11, 5))
        self.assertEqual(agreement["date"], "2026-11-12")
        self.assertEqual(agreement["source"], "разбор Jarvis")
        self.assertIsNone(main._deferred_call_agreement({"recommendation": "Клиент обсуждал бюджет 12.11.2026."}, date(2026, 11, 5)))

    def test_each_active_deal_gets_cached_aiai_context_when_jarvis_has_no_breakdown(self):
        async def run():
            saved = {}
            configured = replace(main.settings, aiai_api_key="test-key", aiai_context_model="test-model")
            payload = {"ok": True, "status": "online", "data": {"calls": [{"dealId": "10", "status": "pending"}]}}
            workday = {"deals": {"active": [{
                "id": "10", "title": "Сделка", "stage_name": "Отложенный спрос", "amount": 3000,
                "comments": "Клиент просил связаться позже.", "recent_touches": [],
            }]}, "availability": {}}
            analysis = AsyncMock(return_value={
                "status": "online", "summary": "В Jarvis нет разбора; уточнить дату следующего контакта.",
                "priority": "high", "needs_action": True,
                "agreement": {"date": "2026-11-12", "source": "анализ AIAI.BY", "evidence": "связаться позже"},
            })
            with (
                patch.object(main, "settings", configured),
                patch.object(main, "load_jarvis_operations", new=AsyncMock(return_value=payload)),
                patch.object(main.storage, "get_setting", side_effect=lambda key, default={}: saved.get(key, default)),
                patch.object(main.storage, "set_setting", side_effect=lambda key, value: saved.__setitem__(key, value)),
                patch.object(main, "_aiai_deal_action_analysis", new=analysis),
            ):
                first = await main._hydrate_portfolio_context_analysis(workday, "12")
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                second = await main._hydrate_portfolio_context_analysis(workday, "12")
            return first, second, workday, analysis

        first, second, workday, analysis = asyncio.run(run())
        self.assertEqual(first, {})
        self.assertEqual(second["10"]["agreement"]["source"], "анализ AIAI.BY")
        self.assertEqual(workday["deals"]["context_analysis"][0]["analysis"]["status"], "online")
        analysis.assert_awaited_once()

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

    def test_week_without_touch_is_explicitly_warned_and_never_transfers_the_deal(self):
        with patch("app.personal_workspace.datetime") as mocked_datetime:
            from datetime import datetime
            mocked_datetime.now.return_value = datetime.fromisoformat("2026-10-29T12:00:00+03:00")
            mocked_datetime.combine = datetime.combine
            mocked_datetime.fromisoformat = datetime.fromisoformat
            result = asyncio.run(build_personal_workday(_NoTouchClient(), "12", "2026-10-29", "Europe/Moscow"))
        row = result["deals"]["week_without_touch"][0]
        self.assertEqual(row["id"], "10")
        self.assertIn("может передать", row["reason"])

    def test_evening_snapshot_contains_norm_speed_and_untouched_deals(self):
        snapshot = main._cabinet_evening_snapshot({
            "date": "2026-10-29", "calls": {"successful_from_minute": 17, "target": 50, "remaining": 33},
            "tasks": {"overdue_count": 2}, "stage_sla": {"breached_count": 3},
            "deals": {"week_without_touch": [{"id": "10"}], "capacity": {"active_count": 41, "target": 70}},
            "iso_suot": {"confirmed_gaps": [{"id": "11"}]},
        }, "2026-10-29T18:00:00+03:00")
        self.assertEqual(snapshot["calls"]["target"], 50)
        self.assertEqual(snapshot["speed"]["stage_breaches"], 3)
        self.assertEqual(snapshot["week_without_touch"][0]["id"], "10")


class PersonalCallNormalizationTests(unittest.TestCase):
    def test_unscored_reason_and_iso_alert_are_only_taken_from_server_confirmed_data(self):
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
        }, {"call-2": {"reason": "Полная проверка подтверждена."}})
        pending, confirmed_gap, unknown = result["data"]["calls"]
        self.assertEqual(pending["notScoredReason"], "Анализ ещё не готов")
        self.assertTrue(confirmed_gap["isoSuotAlert"])
        self.assertEqual(confirmed_gap["isoSuotStatus"], "confirmed_gap")
        self.assertFalse(unknown["isoSuotAlert"])
        self.assertEqual(unknown["isoSuotStatus"], "not_provided")


if __name__ == "__main__":
    unittest.main()
