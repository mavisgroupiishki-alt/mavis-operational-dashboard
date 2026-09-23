from pathlib import Path
import unittest


class SoftBackgroundRefreshTest(unittest.TestCase):
    def test_background_refresh_reconciles_only_the_visible_view(self):
        source = Path("app/static/app.js").read_text()

        self.assertIn("function softRenderCurrentView()", source)
        self.assertIn("function reconcileNode(target,source)", source)
        self.assertIn("const mode={background:Boolean(options.background)};", source)
        self.assertIn("if(activeLoadMode===mode)activeLoadMode=null", source)
        self.assertIn("if(activeLoadMode?.background&&state?.ok&&softRenderCurrentView())return;", source)


if __name__ == "__main__":
    unittest.main()
