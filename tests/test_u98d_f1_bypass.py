"""U98-D-F1: close the four P1 bypasses of the delegation-first gate found by Antigravity's review (U98-D-R).

Receipt (2026-09-30, `.coord/notes/U98-D-agy-review.md`, each reproduced by the judge):
1. `pilot run --worker apply --prompt ...` without `--manual` skipped lint, so any amount of code was applied.
2. `.PY`, `.ps1` and other code files counted 0 lines.
3. Ledger rows with outcome APPROVE or no outcome counted as a failed delegate run.
4. Any old failed row of another card could be cited in `apply_after`.
Fixed acceptance written by the judge (claude).
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from v7_harness.cli import main
from v7_harness.delegation import dictated_code_lines, delegate_first_errors


def block(path: str, lines: int = 25) -> str:
    return f"===FILE: {path}===\n" + "\n".join(f"x{i} = {i}" for i in range(lines)) + "\n===END===\n"


class F1BypassTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _ledger(self, **row: object) -> None:
        path = self.project / ".coord" / "usage" / "runs.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")

    def _refused(self, work_id: str, after: str) -> bool:
        contract = {"worker": "apply", "work_id": work_id, "apply_after": after}
        return bool(delegate_first_errors(block("v7_harness/a.py"), contract, self.project))

    def test_other_code_suffixes_and_case_count(self) -> None:
        for path in ("v7_harness/a.PY", "scripts/run.ps1", "scripts/run.sh", "web/app.js", "v7_harness/a.pyi"):
            self.assertEqual(25, dictated_code_lines(block(path)), path)

    def test_paths_are_normalized_before_the_tests_exemption(self) -> None:
        self.assertEqual(25, dictated_code_lines(block("./v7_harness/a.py")))
        self.assertEqual(0, dictated_code_lines(block("tests\\test_a.py")))
        self.assertEqual(0, dictated_code_lines(block("docs/a.md")))

    def test_only_real_failure_outcomes_count(self) -> None:
        self._ledger(work_id="T1-A", worker="agy", outcome="APPROVE")
        self._ledger(work_id="T1-N", worker="ollama")
        self._ledger(work_id="T1-B", worker="ollama", outcome="BLOCKED")
        self.assertTrue(self._refused("T1", "T1-A"))
        self.assertTrue(self._refused("T1", "T1-N"))
        self.assertFalse(self._refused("T1", "T1-B"))

    def test_failed_run_must_belong_to_the_same_card(self) -> None:
        self._ledger(work_id="U42-L", worker="ollama", outcome="FAIL")
        self.assertTrue(self._refused("T1", "U42-L"))
        self.assertFalse(self._refused("U42-A1", "U42-L"))

    def test_apply_without_manual_is_refused_before_any_run(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["pilot", "run", "--task", "T9", "--source", str(self.project), "--worker", "apply",
                         "--prompt", block("v7_harness/a.py")])
        self.assertEqual(2, code)
        self.assertIn("DELEGATE_FIRST", out.getvalue())
        self.assertFalse((self.project / "v7_harness" / "a.py").exists())


if __name__ == "__main__":
    unittest.main()
