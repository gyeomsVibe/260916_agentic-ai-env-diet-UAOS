"""U192: card audit counts an Antigravity review file only when the record carries what review.py writes for a real
agy run. Receipt: docs/rsi/20261009-nonstop-package-a-incident.md condition 4 says no other reviewer may count as
Antigravity. Before this fix, a hand-written {"verdict": "PASS"} file filled the agy slot."""
import json
import tempfile
import unittest
from pathlib import Path

from v7_harness import card_pipeline as cp

REAL = {"task_id": "U900-L1", "reviewer": "agy", "verdict": "PASS", "cost_gate": "WITHIN",
        "judge_conversation_id": "conv-agy-1", "usage": {"input_tokens": 1200, "output_tokens": 80}}


class AgyReviewProvenanceTest(unittest.TestCase):
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

    def test_real_agy_record_fills_the_slot(self):
        out = self._audit(REAL)
        self.assertTrue(out["ok"], out)
        self.assertTrue(any("U900-L1 PASS" in item for item in out["agy"]))

    def test_hand_written_verdict_only_file_does_not_count(self):
        self.assertEqual(self._audit({"verdict": "PASS"})["missing"], ["agy"])

    def test_another_reviewer_does_not_count_as_agy(self):
        for reviewer in ("claude", "codex", None):
            with self.subTest(reviewer=reviewer):
                self.assertEqual(self._audit({**REAL, "reviewer": reviewer})["missing"], ["agy"])

    def test_record_without_an_agy_conversation_does_not_count(self):
        for conv in (None, ""):
            with self.subTest(conv=conv):
                self.assertEqual(self._audit({**REAL, "judge_conversation_id": conv})["missing"], ["agy"])

    def test_over_budget_or_unusable_record_does_not_count(self):
        self.assertEqual(self._audit({**REAL, "cost_gate": "OVER"})["missing"], ["agy"])
        self.assertEqual(self._audit({**REAL, "verdict": "UNUSABLE"})["missing"], ["agy"])

    def test_record_with_no_tokens_spent_does_not_count(self):
        self.assertEqual(self._audit({**REAL, "usage": {"input_tokens": 0}})["missing"], ["agy"])
        self.assertEqual(self._audit({**REAL, "usage": None})["missing"], ["agy"])


if __name__ == "__main__":
    unittest.main()
