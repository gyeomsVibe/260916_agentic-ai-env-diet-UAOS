"""U238 fixed acceptance: Zero-touch project doc hub bootstrap (bootstrap_project_docs)."""
from pathlib import Path
import tempfile
import unittest


class U238AutobootInitTests(unittest.TestCase):
    def test_bootstrap_project_docs_creates_markdown_index_and_html_hub(self):
        from v7_harness.docs_manager import bootstrap_project_docs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = bootstrap_project_docs(root)
            self.assertTrue(result["ok"])
            index_md = root / "docs" / "00_DOCUMENT_INDEX.md"
            hub_html = root / "docs" / "00_DOCUMENT_HUB.html"
            self.assertTrue(index_md.is_file())
            self.assertTrue(hub_html.is_file())
            self.assertEqual(Path(result["index_md"]), index_md)
            self.assertEqual(Path(result["hub_html"]), hub_html)

    def test_bootstrap_project_docs_is_idempotent_and_indexes_existing_docs(self):
        from v7_harness.docs_manager import bootstrap_project_docs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs"
            docs.mkdir(parents=True, exist_ok=True)
            (docs / "01_intro.md").write_text("# Intro Doc\n\nHello\n", encoding="utf-8")
            first = bootstrap_project_docs(root)
            second = bootstrap_project_docs(root)
            self.assertEqual(first["index_md"], second["index_md"])
            self.assertIn("Intro Doc", (docs / "00_DOCUMENT_INDEX.md").read_text(encoding="utf-8"))
            self.assertIn("Intro Doc", (docs / "00_DOCUMENT_HUB.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
