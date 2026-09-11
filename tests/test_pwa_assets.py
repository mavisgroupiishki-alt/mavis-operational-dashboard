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
        self.assertIn("mavis-operational-v3.1.3", worker.text)


if __name__ == "__main__":
    unittest.main()
