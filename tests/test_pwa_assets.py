import re
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


class PwaAssetTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_manifest_and_service_worker_are_public_and_installable(self):
        home = self.client.get("/")
        manifest = self.client.get("/manifest.webmanifest")
        worker = self.client.get("/service-worker.js")

        self.assertEqual(home.status_code, 200)
        self.assertIn('data-period-preset="current"', home.text)
        self.assertIn('data-period-preset="previous"', home.text)
        self.assertIn('data-period-preset="custom"', home.text)
        self.assertNotIn('value="this_week"', home.text)
        self.assertNotIn('value="last_week"', home.text)
        self.assertIn('id="installIosSteps"', home.text)
        self.assertIn("На экран „Домой“", home.text)
        self.assertIn('id="dashboardChatWidget"', home.text)
        self.assertEqual(manifest.status_code, 200)
        self.assertTrue(manifest.headers["content-type"].startswith("application/manifest+json"))
        self.assertIn('"display": "standalone"', manifest.text)
        self.assertEqual(worker.status_code, 200)
        self.assertEqual(worker.headers["service-worker-allowed"], "/")
        script_version = re.search(r'/static/app\.js\?v=([\d.]+)', home.text)
        style_version = re.search(r'/static/styles\.css\?v=([\d.]+)', home.text)
        self.assertIsNotNone(script_version)
        self.assertIsNotNone(style_version)
        self.assertEqual(script_version.group(1), style_version.group(1))
        self.assertIn(f"mavis-operational-v{script_version.group(1)}", worker.text)
        self.assertIn(f"/static/app.js?v={script_version.group(1)}", worker.text)
        self.assertIn(f"/static/styles.css?v={style_version.group(1)}", worker.text)

    def test_experts_render_has_production_kpis_in_scope(self):
        script = (Path(__file__).resolve().parents[1] / "app" / "static" / "app.js").read_text()

        experts_function = re.search(
            r"function renderExperts\(\)\{(?P<body>.*?)\n\}\n\nfunction reasonTable",
            script,
            re.DOTALL,
        )
        self.assertIsNotNone(experts_function)
        self.assertIn("const p=state.production.kpi;", experts_function.group("body"))
        self.assertIn("Активные зависшие — ожидаемое закрытие в месяце", experts_function.group("body"))
        self.assertNotIn("В воронке «Зависшие»", experts_function.group("body"))

    def test_production_breakdowns_have_direct_plan_actions(self):
        script = (Path(__file__).resolve().parents[1] / "app" / "static" / "app.js").read_text()

        self.assertIn('data-production-week-plans="1"', script)
        self.assertIn('data-production-product-plans="1"', script)
        self.assertIn('data-production-expert-plans="1"', script)
        self.assertIn('openPlanDialog("production","week","0")', script)
        self.assertIn('openPlanDialog("production","product")', script)
        self.assertIn('openPlanDialog("production","expert")', script)

    def test_bitrix_chat_is_a_global_widget(self):
        script = (Path(__file__).resolve().parents[1] / "app" / "static" / "app.js").read_text()

        self.assertIn("function renderDashboardChat()", script)
        self.assertIn("function setDashboardChatOpen", script)
        self.assertIn('data-dashboard-chat-toggle="1"', script)
        self.assertIn('data-dashboard-chat-close="1"', script)
        self.assertIn('dashboardChatOpen=true;persistDashboardChatState();renderDashboardChat()', script)
        self.assertNotIn("${dashboardChatMarkup()}</section>`", script)


if __name__ == "__main__":
    unittest.main()
