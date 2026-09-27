"""U48-W1: `pilot run` with the default `--work-dir .coord` inside the source.

2026-09-27: build_manifest(source) hashed `.coord/coord.sqlite3.writer.lock`, which the same pilot holds with a byte
lock, and raised PermissionError; once past that, the run's own `.coord/runs/<task>` records read as SOURCE_DIVERGED.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from v7_harness.broker.core import BrokerCore
from v7_harness.isolation.manifest import build_manifest
from v7_harness.pilot import work_dir_excludes

REPO = Path(__file__).resolve().parents[1]


class DefaultWorkDirTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "a.py").write_text("X = 1\n", encoding="utf-8")
        (self.root / ".coord" / "runs" / "OLD").mkdir(parents=True)
        (self.root / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        # Older run records under runs/ are tracked files and must stay in the manifest.
        (self.root / ".coord" / "runs" / "OLD" / "keep.md").write_text("kept\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_manifest_skips_the_writer_lock_the_pilot_holds(self):
        core = BrokerCore(self.root / ".coord" / "coord.sqlite3")
        core.start()
        try:
            paths = [e.path for e in build_manifest(self.root).entries]
        finally:
            core.close()
        self.assertIn("a.py", paths)
        self.assertIn(".coord/runs/OLD/keep.md", paths)
        self.assertFalse([p for p in paths if "coord.sqlite3" in p], paths)

    def test_a_nested_work_dir_lock_is_skipped_too(self):
        (self.root / "wd").mkdir()
        core = BrokerCore(self.root / "wd" / "coord.sqlite3")
        core.start()
        try:
            excludes = work_dir_excludes(self.root / "wd", self.root, "T1")
            paths = [e.path for e in build_manifest(self.root, excludes=excludes).entries]
        finally:
            core.close()
        self.assertFalse([p for p in paths if p.startswith("wd/coord.sqlite3")], paths)

    def test_excludes_follow_where_the_work_dir_sits(self):
        inside = work_dir_excludes(self.root / ".coord", self.root, "T1")
        self.assertIn(".coord/coord.sqlite3.writer.lock", inside)
        self.assertIn(".coord/runs/T1", inside)
        self.assertIn(".coord/stage", inside)
        self.assertNotIn(".coord/runs", inside)
        self.assertIn("runs/T1", work_dir_excludes(self.root, self.root, "T1"))
        with tempfile.TemporaryDirectory() as other:
            self.assertEqual([], work_dir_excludes(Path(other), self.root, "T1"))

    def _cli(self, *argv):
        env = dict(os.environ, PYTHONPATH=str(REPO))
        return subprocess.run([sys.executable, "-m", "v7_harness.cli", *argv], cwd=self.root, env=env,
                              capture_output=True, text=True, encoding="utf-8", timeout=180)

    def test_pilot_run_with_the_default_work_dir_applies_end_to_end(self):
        instructions = Path(self._tmp.name + "_instr.txt")
        instructions.write_text("===FILE: a.py===\nX = 2\n", encoding="utf-8")
        self.addCleanup(instructions.unlink)
        made = self._cli("pilot", "manual", "new", "--out", ".coord/T1.md", "--work-id", "T1", "--worker", "apply",
                         "--goal", "Set X = 2 in a.py.", "--input", "a.py", "--allow", "a.py",
                         "--accept", f'"{sys.executable}" -c "import a; assert a.X == 2"', "--judge", "codex",
                         "--instructions-file", str(instructions))
        self.assertEqual(0, made.returncode, made.stdout + made.stderr)

        # No --work-dir: the default `.coord` sits inside the source.
        run = self._cli("pilot", "run", "--task", "T1", "--worker", "apply", "--source", ".",
                        "--manual", ".coord/T1.md")
        self.assertNotIn("PermissionError", run.stderr)
        self.assertEqual(0, run.returncode, run.stdout + run.stderr)
        summary = json.loads(run.stdout)
        self.assertEqual(("SUCCEEDED", "DRY_RUN_PASSED", ["a.py"], 0),
                         (summary["state"], summary["promotion"], summary["changed_files"],
                          summary["acceptance_exit"]), summary)

        approve = self._cli("pilot", "run", "--task", "T1", "--worker", "apply", "--source", ".",
                            "--manual", ".coord/T1.md", "--approve", summary["bundle_id"], "--coord-actor", "codex")
        self.assertEqual(0, approve.returncode, approve.stdout + approve.stderr)
        self.assertEqual("APPLIED", json.loads(approve.stdout)["promotion"])
        self.assertEqual("X = 2\n", (self.root / "a.py").read_text(encoding="utf-8"))
        self.assertEqual("kept\n", (self.root / ".coord" / "runs" / "OLD" / "keep.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
