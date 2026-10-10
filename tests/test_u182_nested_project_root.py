"""U182: a project folder nested inside a larger git repository keeps its own .coord.

Receipt (2026-10-11, Lotto recovery, register U180 package "real project"): the Lotto project is a folder inside
another repository. `coord_root` sent it to that repository's top, which has no schedule, so `coord next` answered
DONE "no schedule" to all three tools while the project's own MASTER_SCHEDULE had a READY step.
"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord.next_card import coord_root, next_step, schedule_path


def _git(cwd, *args):
    done = subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          capture_output=True, text=True, timeout=60)
    if done.returncode != 0:
        raise AssertionError(done.stderr)


class NestedProject(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.outer = Path(self.temp.name).resolve() / "outer"
        self.nested = self.outer / "_workspace" / "14_project"
        (self.nested / ".coord").mkdir(parents=True)
        (self.nested / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        _git(self.outer.parent, "init", "-q", str(self.outer))
        (self.outer / "readme.txt").write_text("x\n", encoding="utf-8")
        _git(self.outer, "add", "readme.txt")
        _git(self.outer, "commit", "-q", "-m", "first")

    def test_nested_project_is_its_own_coord_root(self):
        self.assertEqual(self.nested, coord_root(self.nested))
        self.assertEqual(self.nested / ".coord" / "master_schedule.json", schedule_path(self.nested))

    def test_a_plan_without_a_schedule_is_not_done(self):
        for tool in ("codex", "claude", "antigravity"):
            with self.subTest(tool):
                answer = next_step(self.nested, tool)
                self.assertEqual("WAIT", answer["state"], answer)
                self.assertEqual("SCHEDULE_MISSING", answer["code"])

    def test_the_nested_schedule_is_the_one_read(self):
        (self.nested / ".coord" / "master_schedule.json").write_text(json.dumps({"schedule_id": "T", "phases": [
            {"phase_id": "M2", "state": "READY", "owner_tool": "codex", "depends_on": []}]}), encoding="utf-8")
        answer = next_step(self.nested, "codex")
        self.assertEqual({"state": "NEXT", "card": "M2", "owner": "codex"}, answer)

    def test_a_worktree_still_shares_the_main_checkout(self):
        (self.outer / ".coord").mkdir()
        worktree = self.outer.parent / "wt"
        _git(self.outer, "worktree", "add", "-q", "-b", "side", str(worktree))
        (worktree / ".coord").mkdir(exist_ok=True)
        self.assertEqual(self.outer, coord_root(worktree))
        self.assertEqual(self.outer, coord_root(self.outer))

    def test_a_subfolder_without_its_own_coord_uses_the_repository(self):
        plain = self.outer / "docs"
        plain.mkdir()
        self.assertEqual(self.outer, coord_root(plain))


if __name__ == "__main__":
    unittest.main()
