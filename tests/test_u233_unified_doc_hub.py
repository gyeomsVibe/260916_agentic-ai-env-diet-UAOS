"""U233 fixed acceptance: shared_desk docs resolution, HTML/process hub generation, and --from-file publishing."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from v7_harness import docs_manager as dm  # noqa: E402
from v7_harness.cli import main  # noqa: E402


def run(*argv: str) -> tuple[int, dict]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(list(argv))
    text = out.getvalue().strip()
    return code, json.loads(text[text.index("{"):]) if "{" in text else {}


class UnifiedDocHubTests(unittest.TestCase):
    def test_1_worktree_docs_commands_resolve_to_shared_desk(self):
        with tempfile.TemporaryDirectory() as tmp:
            desk = Path(tmp) / "main_desk"
            wt = Path(tmp) / "linked_wt"
            desk.mkdir()
            wt.mkdir()
            with mock.patch("v7_harness.coord.hook_context.shared_desk", return_value=desk):
                code, data = run("docs", "new", "Worktree Doc", "--project", str(wt), "--slug", "wt-doc")
                self.assertEqual(code, 0)
                self.assertEqual(data["created"], "docs/01_wt-doc.md")
                self.assertTrue((desk / "docs" / "01_wt-doc.md").is_file())
                self.assertFalse((wt / "docs" / "01_wt-doc.md").exists())
                code2, data2 = run("docs", "next-num", "--project", str(wt))
                self.assertEqual((code2, data2["next_number"]), (0, 2))

    def test_2_extract_doc_title_supports_html_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            html_file = root / "87_report.html"
            html_file.write_text("<html><head><title>U230 Nonstop Report | UAOS</title></head><body></body></html>", encoding="utf-8")
            self.assertEqual(dm.extract_doc_title(html_file), "U230 Nonstop Report / UAOS")

    def test_3_sync_doc_index_generates_00_document_hub_html_and_excludes_it_from_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs"
            docs.mkdir()
            (docs / "01_design.md").write_text("# Main Design\n", encoding="utf-8")
            (docs / "02_dashboard.html").write_text("<html><head><title>HTML Dashboard</title></head></html>", encoding="utf-8")
            count = dm.sync_doc_index(root)
            self.assertEqual(count, 2)
            hub = docs / "00_DOCUMENT_HUB.html"
            self.assertTrue(hub.is_file())
            hub_text = hub.read_text(encoding="utf-8")
            self.assertIn("01_design.md", hub_text)
            self.assertIn("02_dashboard.html", hub_text)
            self.assertIn("HTML Dashboard", hub_text)
            # Re-sync must still return 2 (00_DOCUMENT_HUB.html is an index, not a numbered doc)
            self.assertEqual(dm.sync_doc_index(root), 2)

    def test_4_register_new_doc_supports_html_ext_and_from_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "draft.html"
            src.write_text("<!DOCTYPE html><title>Draft Widget</title><h1>Draft</h1>", encoding="utf-8")
            code, data = run("docs", "new", "Draft Widget", "--project", str(root), "--slug", "widget", "--ext", "html", "--from-file", str(src))
            self.assertEqual(code, 0)
            self.assertEqual(data["created"], "docs/01_widget.html")
            created_path = root / "docs" / "01_widget.html"
            self.assertTrue(created_path.is_file())
            self.assertIn("Draft Widget", created_path.read_text(encoding="utf-8"))
            self.assertTrue((root / "docs" / "00_DOCUMENT_HUB.html").is_file())


if __name__ == "__main__":
    unittest.main()
