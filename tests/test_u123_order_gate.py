"""U123: the commit gate enforces "Antigravity audits -> Ollama fixes -> Antigravity reviews" for v7_harness code.

Receipts (2026-10-02, 윤겸스's order "이 순서가 반드시 지켜지게"):
- U122: Claude trimmed a 21-line patch to 20 lines to fit the `worker: apply` dictation limit, skipping Ollama
  and Antigravity; the gate accepted it because any APPLIED bundle counted.
- U122-F1: an Ollama run failed PROMPT_TOO_LARGE before the model was called (input_tokens 0); a failed row like
  that must not unlock a paid or dictated fallback.
- `Calculator-Exempt: <reason>` skipped the gate entirely (30 commits since 09-25).
- Antigravity's design audit (U123-A, relay_8c9ceacc) P1: nothing proved an audit happened before the fix.
Fixed acceptance written by the judge (claude) before the run.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.calculator_gate import audit_errors, check

GATED = "v7_harness/x.py"
BODY = b"A = 1\n"
BUNDLE = "b" * 64


class OrderGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.pd = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, task: str, *, review: dict | None, bundle: str = BUNDLE) -> None:
        run = self.pd / "runs" / task
        run.mkdir(parents=True, exist_ok=True)
        (run / "summary.json").write_text(json.dumps({"promotion": "APPLIED", "bundle_id": bundle,
                                                      "changed_files": [GATED]}), encoding="utf-8")
        stage = self.pd / "stage" / task / GATED
        stage.parent.mkdir(parents=True, exist_ok=True)
        stage.write_bytes(BODY)
        if review is not None:
            reviewer = review.pop("reviewer", "agy")
            (run / f"review_{reviewer}.json").write_text(json.dumps(review), encoding="utf-8")

    def _ok(self, **review: object) -> dict:
        return {"verdict": "PASS", "bundle_id": BUNDLE, "author_worker": "ollama", **review}

    def _violations(self, ledger: list[dict] | None = None, message: str = "fix: x") -> int:
        return len(check({GATED: BODY}, message, self.pd, ledger_rows=ledger or []))

    def test_ollama_bundle_with_matching_agy_pass_counts(self) -> None:
        self._run("U9-L", review=self._ok())
        self.assertEqual(0, self._violations())

    def test_codex_review_also_counts(self) -> None:
        self._run("U9-L", review=self._ok(reviewer="codex"))
        self.assertEqual(0, self._violations())

    def test_applied_bundle_without_review_is_refused(self) -> None:
        self._run("U9-L", review=None)
        self.assertEqual(1, self._violations())

    def test_failed_or_mismatched_review_is_refused(self) -> None:
        self._run("U9-F", review=self._ok(verdict="FAIL"))
        self._run("U9-M", review=self._ok(bundle_id="c" * 64))
        self.assertEqual(1, self._violations())

    def test_dictated_apply_needs_a_real_failed_ollama_run_of_the_card(self) -> None:
        self._run("U9-A", review=self._ok(author_worker="apply"))
        self.assertEqual(1, self._violations())
        precall = {"work_id": "U9-L", "worker": "ollama", "outcome": "BLOCKED", "input_tokens": 0}
        self.assertEqual(1, self._violations([precall]))
        other_card = {"work_id": "U8-L", "worker": "ollama", "outcome": "FAIL", "input_tokens": 900}
        self.assertEqual(1, self._violations([other_card]))
        real = {"work_id": "U9-L", "worker": "ollama", "outcome": "FAIL", "input_tokens": 900}
        self.assertEqual(0, self._violations([real]))

    def test_paid_author_needs_the_same_real_failed_ollama_run(self) -> None:
        self._run("U9-C", review=self._ok(author_worker="claude"))
        self.assertEqual(1, self._violations())
        real = {"work_id": "U9-L", "worker": "local", "outcome": "FAIL", "input_tokens": 900}
        self.assertEqual(0, self._violations([real]))

    def test_calculator_exempt_no_longer_skips_gated_code(self) -> None:
        self.assertEqual(1, self._violations(message="fix\n\nCalculator-Exempt: pilot down, see PLAN\n"))


class AuditTrailerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.ledger = Path(self._tmp.name) / "agy_auto.jsonl"
        rows = [{"message_id": "relay_req1", "state": "ANSWERED", "reply_id": "relay_abc123"},
                {"message_id": "relay_req2", "state": "FAILED", "reply_id": "relay_dead99"}]
        self.ledger.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_gated_commit_needs_an_audit_line(self) -> None:
        self.assertEqual(1, len(audit_errors("fix: x\n", [GATED], self.ledger)))

    def test_answered_antigravity_reply_satisfies_it(self) -> None:
        self.assertEqual([], audit_errors("fix: x\n\nAudit: relay_abc123\n", [GATED], self.ledger))

    def test_unknown_or_unanswered_reply_does_not(self) -> None:
        self.assertEqual(1, len(audit_errors("fix\n\nAudit: relay_ffff00\n", [GATED], self.ledger)))
        self.assertEqual(1, len(audit_errors("fix\n\nAudit: relay_dead99\n", [GATED], self.ledger)))

    def test_missing_ledger_fails_closed(self) -> None:
        self.assertEqual(1, len(audit_errors("fix\n\nAudit: relay_abc123\n", [GATED], self.ledger.with_name("no.jsonl"))))

    def test_no_gated_code_needs_no_audit(self) -> None:
        self.assertEqual([], audit_errors("docs: y\n", [], self.ledger))


if __name__ == "__main__":
    unittest.main()
