"""U302: documents written from any tool's worktree land in the main checkout's docs/, numbered in sequence."""

import argparse
import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from v7_harness import cli
from v7_harness.docs_manager import allocate_next_doc_number, parse_doc_filename


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


class DocsRootHubTests(unittest.TestCase):
    def test_date_prefix_is_not_a_sequence_number(self):
        self.assertEqual(parse_doc_filename("261023_usage-accounting.md")[0], None)
        self.assertEqual(parse_doc_filename("134_report.html")[0], 134)
        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp) / "docs"
            docs.mkdir()
            for name in ("133_a.md", "134_b.html", "261023_usage-accounting.md"):
                (docs / name).write_text("# t\n", encoding="utf-8")
            self.assertEqual(allocate_next_doc_number(Path(tmp))[0], 135)

    def test_docs_new_from_a_worktree_writes_to_main_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            main = Path(tmp) / "main"
            main.mkdir()
            git(main, "init", "-q", "-b", "main")
            git(main, "config", "user.email", "t@t")
            git(main, "config", "user.name", "t")
            (main / ".coord").mkdir()
            (main / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")  # marks the UAOS desk
            (main / "docs").mkdir()
            (main / "docs" / "01_first.md").write_text("# first\n", encoding="utf-8")
            git(main, "add", ".")
            git(main, "commit", "-q", "-m", "base")
            wt = Path(tmp) / "wt"
            git(main, "worktree", "add", "-q", "-b", "card", str(wt))
            src = Path(tmp) / "report.md"
            src.write_text("# report\n", encoding="utf-8")
            args = argparse.Namespace(project=str(wt), title="report", slug="report", category="", tool="claude",
                                      ext="md", from_file=str(src))
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cli.cmd_docs_new(args), 0)
            self.assertTrue((main / "docs" / "02_report.md").is_file())
            self.assertFalse((wt / "docs" / "02_report.md").exists())


if __name__ == "__main__":
    unittest.main()
