"""U240 fixed acceptance: All-Package Project Finisher & Doc Hub Sync (sync_project_hub)."""
from pathlib import Path
import tempfile
import unittest


class U240ProjectFinisherTests(unittest.TestCase):
    def test_sync_project_hub_synchronizes_index_and_html_hub_for_checkout(self):
        from v7_harness.card_pipeline import sync_project_hub

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs"
            docs.mkdir(parents=True, exist_ok=True)
            (docs / "01_final_report.html").write_text(
                "<html><head><title>U240 Final Report</title></head><body>Done</body></html>",
                encoding="utf-8",
            )
            res = sync_project_hub(root)
            self.assertTrue(res["ok"])
            index_md = Path(res["index_md"])
            hub_html = Path(res["hub_html"])
            self.assertTrue(index_md.is_file())
            self.assertTrue(hub_html.is_file())
            self.assertIn("U240 Final Report", index_md.read_text(encoding="utf-8"))
            self.assertIn("U240 Final Report", hub_html.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
