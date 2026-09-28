"""U75 (U46-G1, docs/47 §2-2): a merge commit passes the calculator gate when every gated file equals one parent.

Seen 2026-09-26: merges 6e02901 and 1e5b316 needed `Calculator-Exempt` only because the gate saw a merged file that
no APPLIED bundle had produced, although each side had already passed the gate on its own branch.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from v7_harness.calculator_gate import check, parent_digests

GATED = "v7_harness/m.py"


def _git(root: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=root, env=env, check=True, capture_output=True, text=True).stdout


class MergeParentRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.pilot = self.root / "no_pilot"  # no APPLIED bundle anywhere: only a parent can explain a file
        _git(self.root, "init", "-q", "-b", "main")
        _git(self.root, "config", "core.hooksPath", "no-hooks")  # the unit under test is check(), not the hook
        (self.root / "v7_harness").mkdir()
        self._write(GATED, "a = 1\n")
        (self.root / "other.txt").write_text("base\n", encoding="utf-8")
        _git(self.root, "add", ".")
        _git(self.root, "commit", "-q", "-m", "base")
        _git(self.root, "checkout", "-q", "-b", "side")
        self._write(GATED, "a = 2\n")
        _git(self.root, "commit", "-q", "-am", "side")
        _git(self.root, "checkout", "-q", "main")
        (self.root / "other.txt").write_text("main\n", encoding="utf-8")
        _git(self.root, "commit", "-q", "-am", "main")
        _git(self.root, "merge", "-q", "--no-commit", "--no-ff", "side")
        self._cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self) -> None:
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def _write(self, rel: str, text: str) -> None:
        (self.root / rel).write_bytes(text.encode("utf-8"))

    def _staged(self) -> dict[str, bytes]:
        return {GATED: subprocess.check_output(["git", "show", f":{GATED}"], cwd=self.root)}

    def test_a_file_equal_to_a_merge_parent_passes_without_an_exempt_line(self) -> None:
        staged = self._staged()
        self.assertEqual([], check(staged, "merge side", self.pilot, parent_digests(list(staged))))

    def test_new_content_written_during_the_merge_is_still_refused(self) -> None:
        self._write(GATED, "a = 3  # hand-written conflict resolution\n")
        _git(self.root, "add", GATED)
        staged = self._staged()
        violations = check(staged, "merge side", self.pilot, parent_digests(list(staged)))
        self.assertEqual(1, len(violations))
        self.assertIn(GATED, violations[0])

    def test_outside_a_merge_the_parent_route_is_closed(self) -> None:
        _git(self.root, "merge", "--abort")
        self._write(GATED, "a = 1\n")  # equals HEAD, but an ordinary commit gets no parent credit
        self.assertEqual({}, parent_digests([GATED]))
        self.assertEqual(1, len(check({GATED: b"a = 1\n"}, "plain", self.pilot, parent_digests([GATED]))))


if __name__ == "__main__":
    unittest.main()
