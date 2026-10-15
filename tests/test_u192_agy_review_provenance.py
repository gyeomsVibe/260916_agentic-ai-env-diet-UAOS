"""U192: card audit counts an Antigravity review file only when the record passes review.py's strict agy schema.
Receipt: docs/rsi/20261009-nonstop-package-a-incident.md condition 4; before this fix a hand-written
{"verdict": "PASS"} file filled the agy slot.

Scope (Codex REVISE relay_0e17d7f3): this is schema hardening only. A hand-written record that copies every field
still passes; it is not proof that an agy run happened and does not close condition 4."""
import json
import tempfile
import unittest
from pathlib import Path

from v7_harness import card_pipeline as cp

REAL = {"task_id": "U900-L1", "bundle_id": "ab" * 32, "reviewer": "agy", "verdict": "PASS", "cost_gate": "WITHIN",
        "judge_conversation_id": "conv-agy-1", "usage": {"input_tokens": 1200, "output_tokens": 80}}


class AgyReviewSchemaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.desk = Path(self.tmp.name)
        ledger = self.desk / ".coord" / "usage" / "runs.jsonl"
        ledger.parent.mkdir(parents=True)
        ledger.write_text(json.dumps({"work_id": "U900-L1", "worker": "local", "input_tokens": 10}) + "\n",
                          encoding="utf-8")
        self.run = self.desk / ".coord" / "runs" / "U900-L1"
        self.run.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _audit(self, record):
        (self.run / "review_agy.json").write_text(json.dumps(record), encoding="utf-8")
        return cp.audit(self.desk, "U900", run_dirs=[self.desk / ".coord"])

    def _refused(self, **change):
        self.assertEqual(self._audit({**REAL, **change})["missing"], ["agy"], change)

    def test_strict_agy_record_fills_the_slot(self):
        out = self._audit(REAL)
        self.assertTrue(out["ok"], out)
        self.assertTrue(any("U900-L1 PASS" in item for item in out["agy"]))

    def test_hand_written_verdict_only_file_does_not_count(self):
        self.assertEqual(self._audit({"verdict": "PASS"})["missing"], ["agy"])

    def test_another_reviewer_does_not_count_as_agy(self):
        for reviewer in ("claude", "codex", None):
            self._refused(reviewer=reviewer)

    def test_conversation_must_be_a_nonempty_string(self):
        for conv in (None, "", True, 1):
            self._refused(judge_conversation_id=conv)

    def test_over_budget_or_unusable_record_does_not_count(self):
        self._refused(cost_gate="OVER")
        self._refused(verdict="UNUSABLE")

    def test_input_tokens_must_be_a_positive_integer(self):
        for usage in ({"input_tokens": 0}, None, {"input_tokens": True}, {"input_tokens": 1.5},
                      {"input_tokens": "500"}):
            self._refused(usage=usage)

    def test_malformed_tokens_are_refused_not_raised(self):
        self._refused(usage={"input_tokens": "not-an-integer"})

    def test_record_for_another_task_does_not_count(self):
        for task in ("UNRELATED", None, ""):
            self._refused(task_id=task)

    def test_bundle_must_be_a_nonzero_sha256(self):
        for bundle in ("0" * 64, "", None, "xyz", "AB" * 32, True):
            self._refused(bundle_id=bundle)


if __name__ == "__main__":
    unittest.main()
