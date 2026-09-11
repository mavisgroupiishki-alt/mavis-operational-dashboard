import re
import unittest

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


if __name__ == "__main__":
    unittest.main()
