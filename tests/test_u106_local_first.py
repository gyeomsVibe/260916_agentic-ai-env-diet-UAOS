"""U106-A: code work goes to the free local model (Ollama) first; a paid worker only after it failed, automatically.

Receipt (윤겸스, 2026-10-01): "이 과정 어디에서도 올라마를 자동으로 선택해서 안 쓰는구나." Facts: U105-A1 ran on
Antigravity (604,187 tokens) although the router printed "--worker local 권장" (specificity 100/100); the advice was a
warning only, `pilot run --worker` defaulted to agy, and the commander wrote `worker: agy` by hand. Ledger 2026-10-01:
ollama 46 runs / 98k tokens vs antigravity 48 runs / 8.4M. `cascade` (Ollama first, escalate to the paid worker on a
failed acceptance) and `auto` already existed but nothing made them the default.
Rule fixed here:
- lint: a paid worker (agy, claude) whose allow list names a non-test code file is refused (LOCAL_FIRST) unless
  `paid_after: <work_id>` names a failed Ollama/local/cascade run of the same card. Docs, notes and research are exempt
  (a local model has no web access and they are not code).
- U106-A2 (tests/test_u106_subcontract.py) adds `paid_reason`, the `auto` default and Antigravity's Ollama
  subcontract, after 윤겸스 clarified the commander chooses by fit.
Written by the judge (claude) before the implementation; the worker must not edit it.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.manual import lint

SPEC = b"sample spec\n"
SPEC_SHA = hashlib.sha256(SPEC).hexdigest()


def manual(*, worker: str = "agy", allow: str = "v7_harness/sample.py", extra: str = "") -> str:
    return (
        "```contract\n"
        "work_id: T7-A1\n"
        f"worker: {worker}\n"
        "goal: add a sample constant for the local-first gate test\n"
        "inputs:\n"
        f"- spec.md sha256={SPEC_SHA}\n"
        "allow:\n"
        f"- {allow}\n"
        "acceptance: python -m unittest tests.test_sample\n"
        "forbidden: edits outside allow\n"
        "stop: two failures with the same cause\n"
        "judge: claude\n"
        "timeout_s: 60\n"
        "remote_budget_tokens: 500000\n"
        "remote_budget_usd: 1\n"
        f"{extra}"
        "```\n\n"
        "## Instructions for the worker\n\n"
        "1. In `v7_harness/sample.py` add `LIMIT = 3` must be an int.\n"
    )


class LocalFirstLintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        (self.project / "spec.md").write_bytes(SPEC)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _ledger(self, **row: object) -> None:
        path = self.project / ".coord" / "usage" / "runs.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")

    def _codes(self, text: str) -> list[str]:
        return [error.split(":")[0] for error in lint(text, self.project).errors]

    def test_paid_code_work_without_a_local_try_is_refused(self) -> None:
        for worker in ("agy", "claude"):
            self.assertIn("LOCAL_FIRST", self._codes(manual(worker=worker)), worker)

    def test_error_names_the_route(self) -> None:
        errors = [e for e in lint(manual(), self.project).errors if e.startswith("LOCAL_FIRST")]
        self.assertTrue(errors and "cascade" in errors[0] and "paid_after" in errors[0], errors)

    def test_local_routes_are_not_gated(self) -> None:
        for worker in ("local", "cascade"):
            self.assertNotIn("LOCAL_FIRST", self._codes(manual(worker=worker)), worker)

    def test_docs_notes_and_tests_are_exempt(self) -> None:
        for allow in (".coord/notes/U9_research.md", "docs/66_balance.md", "tests/test_sample.py"):
            self.assertNotIn("LOCAL_FIRST", self._codes(manual(allow=allow)), allow)

    def test_paid_after_a_failed_local_run_of_the_same_card_passes(self) -> None:
        for worker in ("ollama", "local", "cascade"):
            self._ledger(work_id=f"T7-L{worker}", worker=worker, outcome="BLOCKED")
            self.assertNotIn("LOCAL_FIRST", self._codes(manual(extra=f"paid_after: T7-L{worker}\n")), worker)

    def test_paid_after_needs_a_real_failed_local_row(self) -> None:
        self._ledger(work_id="T7-OK", worker="ollama", outcome="PASS")
        self._ledger(work_id="T7-AGY", worker="agy", outcome="BLOCKED")
        self._ledger(work_id="T8-L1", worker="ollama", outcome="FAIL")
        for ref in ("T7-missing", "T7-OK", "T7-AGY", "T8-L1"):
            self.assertIn("LOCAL_FIRST", self._codes(manual(extra=f"paid_after: {ref}\n")), ref)


# The CLI half (auto default, --paid-after/--paid-reason) moved to tests/test_u106_subcontract.py (U106-A2).


if __name__ == "__main__":
    unittest.main()
