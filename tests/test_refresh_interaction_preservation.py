import unittest
from pathlib import Path


class RefreshInteractionPreservationTests(unittest.TestCase):
    def test_background_refresh_preserves_open_controls_and_chat_draft(self):
        script = (Path(__file__).resolve().parents[1] / "app" / "static" / "app.js").read_text()

        self.assertIn("function captureDashboardInteraction()", script)
        self.assertIn("function restoreDashboardInteraction(saved)", script)
        self.assertIn('querySelectorAll("details")', script)
        self.assertIn('chatDraft:$("#dashboardChatQuestion")?.value||""', script)
        self.assertIn("restoreDashboardInteraction(interaction);", script)

    def test_event_stream_is_coalesced_before_reloading_the_snapshot(self):
        script = (Path(__file__).resolve().parents[1] / "app" / "static" / "app.js").read_text()

        self.assertIn("function scheduleBackgroundLoad()", script)
        self.assertIn("const delay=Math.max(0,15000-(Date.now()-lastBackgroundRefreshAt));", script)
        self.assertIn("es.addEventListener('update',scheduleBackgroundLoad)", script)
        self.assertIn("setInterval(scheduleBackgroundLoad,120000)", script)


if __name__ == "__main__":
    unittest.main()
