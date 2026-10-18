"""U218 (R5): two pilot slices on separate files, run on the same base, are approved one after another.

Seen twice in use (U214, U216): after `pilot run --approve A` wrote its file, `--approve B` returned
APPROVAL_MISMATCH because the replay diffed the whole tree, so A's applied file looked like B's change. The
replay now checks only the paths B's own bundle changed: each still holds B's base bytes (apply), or B's target
bytes (already applied), or anything else (drift, nothing written; U216-R3 SOURCE_DRIFTED once applied).
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.isolation.manifest import build_manifest, create_patch_bundle
from v7_harness.pilot import PilotConfig, run_pilot


def _scoped_replay_bundle(*args):
    from v7_harness.pilot import _scoped_replay_bundle as helper  # late: the R5 red run predates the helper

    return helper(*args)

FAKE_AGY = [sys.executable, str(Path(__file__).parent / "fixtures" / "fake_agy.py")]
CALC = "def mul(a, b):\n    return a * b\n"
NOTES = "def sub(a, b):\n    return a - b\n"


class DisjointSlices(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.source = root / "sample"
        self.source.mkdir()
        (self.source / "calc.py").write_text(CALC, encoding="utf-8")
        (self.source / "notes.py").write_text(NOTES, encoding="utf-8")
        self.home = root / "home"
        self.home.mkdir()
        self.work = root / "work"

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, task_id, target, approve=None):
        config = PilotConfig(task_id=task_id, title="add", prompt="Add add(a, b).", source_dir=self.source,
                             work_dir=self.work, agy_command=FAKE_AGY, watch_roots=[self.home],
                             print_timeout_s=60, approve_bundle_id=approve)
        env = {"FAKE_AGY_MODE": "success", "FAKE_AGY_OUTSIDE_DIR": str(self.home), "FAKE_AGY_TARGET": target}
        with mock.patch.dict(os.environ, env):
            return run_pilot(config)

    def _two_slices(self):
        a = self._run("R5-A", "calc.py")
        b = self._run("R5-B", "notes.py")
        self.assertEqual(["calc.py"], a["changed_files"])
        self.assertEqual(["notes.py"], b["changed_files"])
        return a["bundle_id"], b["bundle_id"]

    def _text(self, name):
        return (self.source / name).read_text(encoding="utf-8")

    def test_b_applies_after_a(self):
        a, b = self._two_slices()
        self.assertEqual("APPLIED", self._run("R5-A", "calc.py", approve=a)["promotion"])
        self.assertEqual("APPLIED", self._run("R5-B", "notes.py", approve=b)["promotion"])
        self.assertIn("def add(a, b):", self._text("calc.py"))
        self.assertIn("def add(a, b):", self._text("notes.py"))

    def test_re_approving_a_after_b_replays_without_writing(self):
        a, b = self._two_slices()
        self._run("R5-A", "calc.py", approve=a)
        self._run("R5-B", "notes.py", approve=b)
        before = {n: (self.source / n).read_bytes() for n in ("calc.py", "notes.py")}
        self.assertEqual("APPLIED", self._run("R5-A", "calc.py", approve=a)["promotion"])
        self.assertEqual("APPLIED", self._run("R5-B", "notes.py", approve=b)["promotion"])
        self.assertEqual(before, {n: (self.source / n).read_bytes() for n in before})

    def test_drift_on_b_own_file_is_refused_and_kept(self):
        a, b = self._two_slices()
        self._run("R5-A", "calc.py", approve=a)
        (self.source / "notes.py").write_text("x = 1\n", encoding="utf-8")
        self.assertEqual("APPROVAL_MISMATCH", self._run("R5-B", "notes.py", approve=b)["promotion"])
        self.assertEqual("x = 1\n", self._text("notes.py"))

    def test_drift_after_b_applied_is_source_drifted(self):
        a, b = self._two_slices()
        self._run("R5-A", "calc.py", approve=a)
        self._run("R5-B", "notes.py", approve=b)
        (self.source / "notes.py").write_text("x = 1\n", encoding="utf-8")
        self.assertEqual("SOURCE_DRIFTED", self._run("R5-B", "notes.py", approve=b)["promotion"])
        self.assertEqual("x = 1\n", self._text("notes.py"))

    def test_a_reverted_b_file_is_written_again(self):
        a, b = self._two_slices()
        self._run("R5-A", "calc.py", approve=a)
        self._run("R5-B", "notes.py", approve=b)
        (self.source / "notes.py").write_text(NOTES, encoding="utf-8")
        self.assertEqual("APPLIED", self._run("R5-B", "notes.py", approve=b)["promotion"])
        self.assertIn("def add(a, b):", self._text("notes.py"))

    def test_a_wrong_bundle_id_is_still_a_mismatch(self):
        a, b = self._two_slices()
        self._run("R5-A", "calc.py", approve=a)
        self.assertEqual("APPROVAL_MISMATCH", self._run("R5-B", "notes.py", approve=a)["promotion"])
        self.assertEqual(NOTES, self._text("notes.py"))


class ScopedHelper(unittest.TestCase):
    """The helper alone: a saved bundle on disk is judged by its own paths only."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.base, self.stage, self.runs = root / "base", root / "stage", root / "runs"
        for d in (self.base, self.stage, self.runs):
            d.mkdir()
        for d in (self.base, self.stage):
            (d / "calc.py").write_text(CALC, encoding="utf-8")
            (d / "notes.py").write_text(NOTES, encoding="utf-8")
        (self.stage / "notes.py").write_text(NOTES + "x = 2\n", encoding="utf-8")
        bundle = create_patch_bundle(build_manifest(self.base), build_manifest(self.stage), self.base, self.stage)
        (self.runs / "bundle.json").write_text(json.dumps(bundle.to_dict()), encoding="utf-8")
        self.bundle_id = bundle.bundle_id

    def tearDown(self):
        self._tmp.cleanup()

    def _state(self, bundle_id=None):
        return _scoped_replay_bundle(self.runs, bundle_id or self.bundle_id, self.base, None)

    def test_other_files_changed_still_apply_rebased(self):
        (self.base / "calc.py").write_text(CALC + "y = 3\n", encoding="utf-8")
        rebased, state = self._state()
        self.assertEqual("APPLY", state)
        self.assertEqual(build_manifest(self.base).manifest_hash, rebased.base_manifest_hash)
        rebased.verify_integrity()

    def test_own_target_bytes_are_applied(self):
        (self.base / "notes.py").write_text(NOTES + "x = 2\n", encoding="utf-8")
        self.assertEqual((None, "APPLIED"), self._state())

    def test_own_other_bytes_are_drifted(self):
        (self.base / "notes.py").write_text("x = 1\n", encoding="utf-8")
        self.assertEqual((None, "DRIFTED"), self._state())

    def test_unknown_without_a_matching_saved_bundle(self):
        self.assertEqual((None, "UNKNOWN"), self._state("0" * 64))
        (self.runs / "bundle.json").unlink()
        self.assertEqual((None, "UNKNOWN"), self._state())


if __name__ == "__main__":
    unittest.main()
