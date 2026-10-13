import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StaticAssetVersionsTests(unittest.TestCase):
    def test_frontend_build_marker_matches_cache_bust_version(self):
        index = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        service_worker = (ROOT / "app/static/service-worker.js").read_text(encoding="utf-8")
        app = (ROOT / "app/static/app.js").read_text(encoding="utf-8")

        index_version = re.search(r"/static/app\.js\?v=([\d.]+)", index).group(1)
        worker_version = re.search(r'CACHE_NAME="mavis-operational-v([\d.]+)"', service_worker).group(1)
        marker_version = re.search(r'b\.textContent="v([\d.]+)"', app).group(1)

        self.assertEqual(index_version, worker_version)
        self.assertEqual(index_version, marker_version)


if __name__ == "__main__":
    unittest.main()
