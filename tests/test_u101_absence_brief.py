"""U101: tell a returning tool what the other tools changed, from ground truth rather than from letters.

Receipt (윤겸스, 2026-09-30): after Claude's usage limit the user had to type "audit what Antigravity built while you
were away". The prompt hook showed only mailbox letters, task files named codex/review, and PLAN status changes.
It missed the Codex lease Antigravity wrote by hand, an uncommitted PLAN edit in the main checkout, Antigravity's
task files and its direct commits (U100 audit). Fixed acceptance written by the judge (claude) before the code.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from uaos_everywhere.hooks.absence_brief import absence_items

SINCE = 1_800_000_050.0


def _git(root: Path, *args: str, when: int | None = None) -> None:
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t")
    if when is not None:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"@{when} +0000"
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env=env)


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(timespec="seconds")


class AbsenceBriefTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _git(self.root, "init", "-q")
        (self.root / "PLAN.md").write_text("v1\n", encoding="utf-8")
        _git(self.root, "add", "PLAN.md")
        _git(self.root, "commit", "-q", "-m", "old work before the absence", when=1_800_000_000)
        (self.root / "a.txt").write_text("a\n", encoding="utf-8")
        _git(self.root, "add", "a.txt")
        _git(self.root, "commit", "-q", "-m", "agy direct change", when=1_800_000_100)
        (self.root / "b.txt").write_text("b\n", encoding="utf-8")
        _git(self.root, "add", "b.txt")
        _git(self.root, "commit", "-q", "-m", "claude own change\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>",
             when=1_800_000_200)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_commits_by_other_tools_since_the_cursor(self) -> None:
        text = "\n".join(absence_items(self.root, SINCE))
        self.assertIn("agy direct change", text)
        self.assertNotIn("old work before the absence", text)
        self.assertNotIn("claude own change", text)

    def test_uncommitted_edit_to_a_tracked_file(self) -> None:
        (self.root / "PLAN.md").write_text("v2 edited by another tool\n", encoding="utf-8")
        self.assertTrue(any("uncommitted" in item and "PLAN.md" in item for item in absence_items(self.root, SINCE)))

    def test_hand_written_lease_of_another_tool(self) -> None:
        presence = self.root / ".coord" / "presence"
        presence.mkdir(parents=True)
        for tool, record in (
                ("codex", {"state": "ABSENT", "lease": True, "observed_at": _iso(SINCE + 10), "expires_at": SINCE + 9e5}),
                ("antigravity", {"state": "ACTIVE", "observed_at": _iso(SINCE + 10), "expires_at": SINCE + 900}),
                ("claude", {"state": "LIMITED", "lease": True, "observed_at": _iso(SINCE + 10), "expires_at": SINCE + 900}),
                ("codex.watch", {"state": "ACTIVE", "lease": True, "observed_at": _iso(SINCE + 10), "expires_at": SINCE + 900})):
            (presence / f"{tool}.json").write_text(json.dumps(record), encoding="utf-8")
        leases = [item for item in absence_items(self.root, SINCE) if "lease" in item]
        self.assertEqual(1, len(leases), leases)
        self.assertIn("codex", leases[0])
        self.assertIn("ABSENT", leases[0])

    def test_lease_older_than_the_cursor_is_not_news(self) -> None:
        presence = self.root / ".coord" / "presence"
        presence.mkdir(parents=True)
        (presence / "codex.json").write_text(json.dumps(
            {"state": "LIMITED", "lease": True, "observed_at": _iso(SINCE - 10), "expires_at": SINCE + 9e5}), encoding="utf-8")
        self.assertFalse([item for item in absence_items(self.root, SINCE) if "lease" in item])

    def test_new_task_and_note_files_by_any_name(self) -> None:
        for folder, name, stamp in (("tasks", "U99-decision-memo.md", SINCE + 5), ("notes", "agy_report.md", SINCE + 5),
                                    ("tasks", "old-manual.md", SINCE - 5)):
            path = self.root / ".coord" / folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x", encoding="utf-8")
            os.utime(path, (stamp, stamp))
        text = "\n".join(absence_items(self.root, SINCE))
        self.assertIn("U99-decision-memo.md", text)
        self.assertIn("agy_report.md", text)
        self.assertNotIn("old-manual.md", text)

    def test_folder_without_git_still_reports_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".coord" / "notes" / "n.md"
            path.parent.mkdir(parents=True)
            path.write_text("x", encoding="utf-8")
            os.utime(path, (SINCE + 5, SINCE + 5))
            self.assertEqual(1, len(absence_items(Path(tmp), SINCE)))


if __name__ == "__main__":
    unittest.main()
