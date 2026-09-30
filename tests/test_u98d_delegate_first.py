"""U98-D: a paid conductor may not dictate more than 20 lines of code to `worker: apply` before a delegate tried.

Receipt (2026-09-30, 윤겸스's report, the ledger): from 09-26 to 09-30 the ledger holds 174 apply rows against 14 Ollama
and 17 Antigravity rows. Apply spends 0 tokens itself, but the paid conductor wrote every line of its code, so the
Ollama and Antigravity routes the rules require were skipped. Fixed acceptance written by the judge (claude).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.delegation import DICTATION_CODE_LINE_LIMIT, dictated_code_lines, delegate_first_errors
from v7_harness.manual import lint


def manual(*, worker: str = "apply", path: str = "v7_harness/sample.py", lines: int = 25, extra: str = "") -> str:
    body = "\n".join(f"x{i} = {i}" for i in range(lines))
    return (
        "```contract\n"
        "work_id: T1\n"
        f"worker: {worker}\n"
        "goal: add sample constants for the delegation gate test\n"
        "inputs:\n"
        "allow:\n"
        f"- {path}\n"
        "acceptance: python -m unittest tests.test_sample\n"
        "forbidden: edits outside allow\n"
        "stop: two failures with the same cause\n"
        "judge: claude\n"
        "timeout_s: 60\n"
        f"{extra}"
        "```\n\n"
        f"===FILE: {path}===\n{body}\n===END===\n"
    )


class DelegateFirstTests(unittest.TestCase):
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

    def _codes(self, text: str) -> list[str]:
        return [error.split(":")[0] for error in lint(text, self.project).errors]

    def test_limit_is_twenty(self) -> None:
        self.assertEqual(20, DICTATION_CODE_LINE_LIMIT)

    def test_long_dictated_code_is_refused(self) -> None:
        self.assertIn("DELEGATE_FIRST", self._codes(manual(lines=25)))

    def test_short_patch_passes(self) -> None:
        self.assertNotIn("DELEGATE_FIRST", self._codes(manual(lines=20)))

    def test_tests_and_docs_are_exempt(self) -> None:
        self.assertNotIn("DELEGATE_FIRST", self._codes(manual(path="tests/test_sample.py", lines=60)))
        self.assertNotIn("DELEGATE_FIRST", self._codes(manual(path="docs/notes.md", lines=60)))

    def test_other_workers_are_not_gated(self) -> None:
        self.assertNotIn("DELEGATE_FIRST", self._codes(manual(worker="local", lines=60)))

    def test_apply_after_a_failed_delegate_passes(self) -> None:
        self._ledger(work_id="T1-L", worker="ollama", outcome="FAIL")
        self.assertNotIn("DELEGATE_FIRST", self._codes(manual(lines=25, extra="apply_after: T1-L\n")))

    def test_apply_after_needs_a_real_failed_delegate_row(self) -> None:
        self._ledger(work_id="T1-P", worker="apply", outcome="FAIL")
        self._ledger(work_id="T1-OK", worker="agy", outcome="PASS")
        for ref in ("T1-missing", "T1-P", "T1-OK"):
            self.assertIn("DELEGATE_FIRST", self._codes(manual(lines=25, extra=f"apply_after: {ref}\n")), ref)

    def test_edit_blocks_count_replace_lines_only(self) -> None:
        replace = "\n".join(f"y{i} = {i}" for i in range(21))
        text = ("===EDIT: v7_harness/a.py===\n<<<<<<< SEARCH\nold = 1\n=======\n"
                f"{replace}\n>>>>>>> REPLACE\n===END===\n")
        self.assertEqual(21, dictated_code_lines(text))
        self.assertEqual(["DELEGATE_FIRST"], [e.split(":")[0] for e in delegate_first_errors(text, {"worker": "apply"}, self.project)])


if __name__ == "__main__":
    unittest.main()
