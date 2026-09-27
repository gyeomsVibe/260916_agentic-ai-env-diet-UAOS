"""U48-J1 frozen acceptance (written by Claude from Codex's design judgement, 2026-09-27).

Codex's binding J1 design: a binding approval needs a receipt holding the bundle digest, the judge's conversation id,
parsed usage and the gate outcome, plus a ledger reference. The U46 receipt had no acceptance outcome and was written
*before* the usage-ledger call, so a ledger failure never reached the file on disk.
"""

import json
import unittest

from tests.test_u46_pilot_judge import JudgeTest


class JudgeReceiptTest(JudgeTest):
    def test_receipt_on_disk_carries_digest_conversation_usage_gate_and_ledger(self):
        (self.source / ".coord").mkdir()
        (self.source / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        record = self.judge(codex="ABSENT")
        on_disk = json.loads((self.runs / "judge_agy.json").read_text(encoding="utf-8"))
        for receipt in (record, on_disk):
            self.assertEqual("b1", receipt["bundle_id"])
            self.assertEqual("conv-9", receipt["judge_conversation_id"])
            self.assertEqual({"input_tokens": 100, "output_tokens": 20}, receipt["usage"])
            self.assertEqual("WITHIN", receipt["cost_gate"])
            self.assertEqual(0, receipt["acceptance_exit"])
            self.assertEqual("T1-judge-agy", receipt["usage_ledger"]["work_id"])
            self.assertTrue(receipt["usage_ledger"]["path"].endswith("runs.jsonl"))
        self.assertTrue(record["applied"])

    def test_receipt_names_a_skipped_ledger_instead_of_omitting_it(self):
        record = self.judge(codex="ABSENT")
        on_disk = json.loads((self.runs / "judge_agy.json").read_text(encoding="utf-8"))
        self.assertEqual("NOT_A_PROJECT", on_disk["usage_ledger"]["skipped"])
        self.assertEqual(record["usage_ledger"], on_disk["usage_ledger"])

    def test_over_budget_receipt_still_records_the_ledger_and_never_applies(self):
        record = self.judge(codex="ABSENT", runner=self.runner(usage={"input_tokens": 9_000, "output_tokens": 5_000}))
        self.assertEqual("UNUSABLE", record["verdict"])
        self.assertFalse(record["applied"])
        self.assertIn("usage_ledger", json.loads((self.runs / "judge_agy.json").read_text(encoding="utf-8")))
        self.assertEqual([], self.approvals)


if __name__ == "__main__":
    unittest.main()
