"""U222 fixed acceptance: `uaos docs new|sync|next-num` and the `coord init` docs wiring. Tempdirs only."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from v7_harness.cli import main  # noqa: E402


def run(*argv: str) -> tuple[int, dict]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(list(argv))
    text = out.getvalue().strip()
    return code, json.loads(text[text.index("{"):]) if "{" in text else {}


class DocsCommands(unittest.TestCase):
    def test_next_num_on_empty_project_is_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, data = run("docs", "next-num", "--project", tmp)
            self.assertEqual((code, data["next_number"], data["prefix"]), (0, 1, "01_"))

    def test_new_creates_numbered_file_and_index_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, data = run("docs", "new", "Hello World", "--project", tmp, "--slug", "hello")
            self.assertEqual((code, data["created"]), (0, "docs/01_hello.md"))
            self.assertTrue((Path(tmp) / "docs" / "01_hello.md").is_file())
            index = (Path(tmp) / "docs" / "00_DOCUMENT_INDEX.md").read_text(encoding="utf-8")
            self.assertIn("[01_hello.md]", index)
            code, data = run("docs", "next-num", "--project", tmp)
            self.assertEqual(data["next_number"], 2)

    def test_sync_lists_every_document_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp) / "docs"
            docs.mkdir()
            (docs / "05_a.md").write_text("# A\n", encoding="utf-8")
            (docs / "06_b.md").write_text("# B\n", encoding="utf-8")
            code, data = run("docs", "sync", "--project", tmp)
            self.assertEqual((code, data["synced_count"]), (0, 2))
            index = (docs / "00_DOCUMENT_INDEX.md").read_text(encoding="utf-8")
            self.assertEqual((index.count("[05_a.md]"), index.count("[06_b.md]")), (1, 1))

    def test_unsafe_slug_is_refused_and_nothing_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                run("docs", "new", "T", "--project", tmp, "--slug", "../x")
            names = [p.name for p in (Path(tmp) / "docs").iterdir()]
            self.assertEqual(names, ["00_DOCUMENT_INDEX.md"])


class CoordInitDocs(unittest.TestCase):
    def test_coord_init_creates_docs_index_in_tempdir_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, data = run("coord", "init", "--project", tmp)
            self.assertEqual(code, 0)
            self.assertTrue((Path(tmp) / "docs" / "00_DOCUMENT_INDEX.md").is_file())
            self.assertIn("docs/00_DOCUMENT_INDEX.md", data["created"])
            self.assertEqual(data["docs_index"], "docs/00_DOCUMENT_INDEX.md")

    def test_coord_init_keeps_an_existing_index_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            idx = Path(tmp) / "docs" / "00_DOCUMENT_INDEX.md"
            idx.parent.mkdir()
            idx.write_text("MINE", encoding="utf-8")
            run("coord", "init", "--project", tmp)
            self.assertEqual(idx.read_text(encoding="utf-8"), "MINE")


if __name__ == "__main__":
    unittest.main()
