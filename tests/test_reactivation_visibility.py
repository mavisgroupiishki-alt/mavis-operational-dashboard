import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReactivationVisibilityTests(unittest.TestCase):
    def test_unavailable_reactivation_source_does_not_show_an_empty_panel(self):
        source = (ROOT / "app/static/app.js").read_text(encoding="utf-8")

        start = source.index("function reactivationBlock()")
        block = source[start : source.index("async function loadReactivationQueue", start)]
        self.assertIn('if(!reactivationData)return "";', block)
        self.assertNotIn("Очередь временно недоступна", block)


if __name__ == "__main__":
    unittest.main()
