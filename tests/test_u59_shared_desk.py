"""U59 frozen acceptance (written by Claude): a linked worktree's session uses the main checkout's desk.

Seen 2026-09-28: a session in `.claude/worktrees/<name>` wrote presence into the worktree's own `.coord`, `coord watch`
there crashed on a missing mailbox, and the main checkout, where letters and routing live, kept claude ABSENT.
"""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from v7_harness.cli import main
from v7_harness.coord.hook_context import hook_project, shared_desk
from v7_harness.coord.presence import read
from v7_harness.coord.watch import watch


def _plan(root: Path) -> None:
    (root / ".coord").mkdir(parents=True, exist_ok=True)
    (root / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")


class SharedDeskTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.main = base / "repo"
        self.tree = self.main / ".claude" / "worktrees" / "w1"
        _plan(self.main)
        _plan(self.tree)
        (self.main / ".git" / "worktrees" / "w1").mkdir(parents=True)
        (self.tree / ".git").write_text(f"gitdir: {(self.main / '.git' / 'worktrees' / 'w1').as_posix()}\n",
                                        encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_worktree_maps_to_the_main_checkout(self):
        self.assertEqual(self.main, shared_desk(self.tree))
        self.assertEqual(self.main, shared_desk(self.main))

    def test_submodule_and_plain_folder_are_unchanged(self):
        sub = self.main / "sub"
        _plan(sub)
        (self.main / ".git" / "modules" / "sub").mkdir(parents=True)
        (sub / ".git").write_text(f"gitdir: {(self.main / '.git' / 'modules' / 'sub').as_posix()}\n",
                                  encoding="utf-8")
        self.assertEqual(sub, shared_desk(sub))
        plain = Path(self._tmp.name) / "plain"
        plain.mkdir()
        self.assertEqual(plain, shared_desk(plain))

    def test_main_without_a_plan_keeps_the_worktree(self):
        (self.main / ".coord" / "PLAN.md").unlink()
        self.assertEqual(self.tree, shared_desk(self.tree))

    def test_hook_from_a_worktree_writes_the_main_desk(self):
        found = hook_project(json.dumps({"cwd": str(self.tree)}), None, env={})
        self.assertEqual(self.main.resolve(), found.resolve())
        payload = json.dumps({"session_id": "s1", "cwd": str(self.tree)})
        with redirect_stdout(io.StringIO()), \
                mock.patch("v7_harness.coord.hook_context.read_stdin", return_value=payload), \
                mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": "", "UAOS_WORKER": ""}):
            self.assertEqual(0, main(["coord", "presence", "--tool", "claude", "--state", "ACTIVE", "--from-hook",
                                      "--say", "none"]))
        self.assertEqual("ACTIVE", read(self.main, "claude")["state"])
        self.assertFalse((self.tree / ".coord" / "presence").exists())

    def test_desk_commands_given_a_worktree_use_the_main_checkout(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(0, main(["coord", "presence", "--tool", "claude", "--state", "ACTIVE",
                                      "--project", str(self.tree)]))
        self.assertEqual("ACTIVE", read(self.main, "claude")["state"])
        self.assertEqual("UNKNOWN", read(self.tree, "claude")["state"])


class WatchWithoutMailboxTest(unittest.TestCase):
    def test_watch_on_a_project_with_no_mailbox_times_out_cleanly(self):
        with tempfile.TemporaryDirectory() as d:
            _plan(Path(d))
            self.assertIsNone(watch(Path(d), ("claude",), timeout_s=0, interval_s=1, sleep=lambda _s: None))
            self.assertTrue((Path(d) / ".coord" / "mailbox").is_dir())


if __name__ == "__main__":
    unittest.main()
