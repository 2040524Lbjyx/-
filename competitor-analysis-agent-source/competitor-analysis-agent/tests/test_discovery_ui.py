"""Exercise confirmation and stale-result guards through the real Streamlit app."""
from pathlib import Path
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest


class DiscoveryUITests(unittest.TestCase):
    def test_selection_requires_confirmation_and_profile_edits_invalidate_it(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20).run()
        self.assertFalse(app.exception)
        modes = [r for r in app.radio if "帮我找竞品" in r.options]
        self.assertTrue(modes, "Missing discovery entry")
        modes[0].set_value("帮我找竞品").run()
        self.assertTrue(next(b for b in app.button if b.label == "🚀 开始分析").disabled)
        app.text_area(key="discovery_description").set_value("团队知识管理").run()
        candidates = [{"name": name, "reason": "知识管理需求相近", "sources": [{"url": "https://example.com/review", "title": "Review", "snippet": name}]} for name in ["Obsidian", "Anytype", "Logseq"]]
        with patch("services.competitor_discovery.CompetitorDiscovery.discover", return_value=candidates), patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            app.run()
            app.button(key="discover_competitors").click().run()
        self.assertFalse(app.exception)
        app.multiselect(key="discovery_selection").set_value(["Obsidian", "Anytype"]).run()
        self.assertTrue(next(b for b in app.button if b.label == "🚀 开始分析").disabled)
        app.button(key="confirm_discovery").click().run()
        self.assertFalse(next(b for b in app.button if b.label == "🚀 开始分析").disabled)
        self.assertTrue(any("Obsidian" in i.value and "Anytype" in i.value for i in app.info))
        # Run the existing demo path to prove the confirmed selection reaches analysis.
        next(b for b in app.button if b.label == "🚀 开始分析").click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["last_result"]["competitors"], ["Obsidian", "Anytype"])
        app.multiselect(key="discovery_selection").set_value(["Anytype", "Logseq"]).run()
        self.assertTrue(next(b for b in app.button if b.label == "🚀 开始分析").disabled)
        app.button(key="confirm_discovery").click().run()
        app.text_area(key="discovery_description").set_value("视频剪辑").run()
        self.assertTrue(next(b for b in app.button if b.label == "🚀 开始分析").disabled)
        self.assertFalse(any(m.key == "discovery_selection" for m in app.multiselect))


if __name__ == "__main__":
    unittest.main()
