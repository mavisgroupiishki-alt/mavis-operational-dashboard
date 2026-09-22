import unittest
from pathlib import Path


class RefreshInteractionPreservationTests(unittest.TestCase):
    def test_background_refresh_preserves_open_controls_and_chat_draft(self):
        script = (Path(__file__).resolve().parents[1] / "app" / "static" / "app.js").read_text()

        self.assertIn("function captureDashboardInteraction()", script)
        self.assertIn("function restoreDashboardInteraction(saved)", script)
        self.assertIn('querySelectorAll("details")', script)
        self.assertIn("chatDraft:dashboardChatDraft", script)
        self.assertIn("restoreDashboardInteraction(interaction);", script)

    def test_chat_state_is_persisted_independently_from_dom_rerenders(self):
        script = (Path(__file__).resolve().parents[1] / "app" / "static" / "app.js").read_text()

        self.assertIn("DASHBOARD_CHAT_STATE_KEY", script)
        self.assertIn("sessionStorage.setItem", script)
        self.assertIn("persistDashboardChatState", script)
        self.assertIn("dashboardChatDraft", script)

    def test_event_stream_is_coalesced_before_reloading_the_snapshot(self):
        script = (Path(__file__).resolve().parents[1] / "app" / "static" / "app.js").read_text()

        self.assertIn("function scheduleBackgroundLoad()", script)
        self.assertIn("const delay=Math.max(0,15000-(Date.now()-lastBackgroundRefreshAt));", script)
        self.assertIn("es.addEventListener('update',scheduleBackgroundLoad)", script)
        self.assertIn("setInterval(scheduleBackgroundLoad,120000)", script)


if __name__ == "__main__":
    unittest.main()
