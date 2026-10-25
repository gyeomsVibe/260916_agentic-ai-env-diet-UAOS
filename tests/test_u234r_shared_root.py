"""U234 rework: a linked git worktree votes into the main checkout's shared title store.

Receipt (2026-10-25, Codex REWORK relay_b712654c): from `.claude/worktrees/<name>` the store resolved the
worktree's own `.coord`, so schedule_digest raised on a missing master schedule and db_path disagreed with
shared_desk.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord import title_consensus as tc
from v7_harness.coord.hook_context import shared_desk


class SharedRoot(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.main = Path(tmp.name) / "main"
        (self.main / ".coord").mkdir(parents=True)
        (self.main / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        self.schedule = self.main / ".coord" / "master_schedule.json"
        self.schedule.write_text(json.dumps({"phases": [{"phase_id": "P1", "title": "a"}]}), encoding="utf-8")
        gitdir = self.main / ".git" / "worktrees" / "wt"
        gitdir.mkdir(parents=True)
        self.wt = self.main / ".claude" / "worktrees" / "wt"
        (self.wt / ".coord").mkdir(parents=True)
        (self.wt / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")

    def test_worktree_resolves_shared_desk_store_and_digest(self):
        self.assertEqual(tc.db_path(self.wt), tc.db_path(shared_desk(self.wt)))
        self.assertEqual(tc.db_path(self.wt), tc.db_path(self.main))
        self.assertEqual(tc.schedule_digest(self.wt), tc.schedule_digest(self.main))

    def test_worktree_votes_reach_main_without_master_write(self):
        before = self.schedule.read_bytes()
        digest = tc.schedule_digest(self.main)
        for tool in tc.TOOLS:
            result = tc.cast_vote(self.wt, tool, "창구", digest)
        self.assertTrue(result["accepted"])
        self.assertEqual((True, "창구"), tc.accepted_topic(self.main))
        self.assertFalse((self.wt / ".coord" / tc.DB_NAME).exists())
        self.assertEqual(before, self.schedule.read_bytes())


if __name__ == "__main__":
    unittest.main()
