"""U239 fixed acceptance: Always-On RSI Value Evaluator (evaluate_roi_metrics)."""
from pathlib import Path
import tempfile
import unittest


class U239RsiEvaluatorTests(unittest.TestCase):
    def test_evaluate_roi_metrics_computes_yield_and_offload_ratio(self):
        from v7_harness.invocation import evaluate_roi_metrics, finish_attempt, start_attempt

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "invocations.sqlite3"
            h = "a" * 64
            a1 = start_attempt(
                caller="antigravity",
                project=root,
                work_id="U239-T1",
                purpose="local_draft",
                model="qwen2.5-coder:7b",
                input_sha256=h,
                db=db,
            )
            finish_attempt(a1, outcome="SUCCEEDED", input_tokens=1000, output_tokens=200, db=db)

            a2 = start_attempt(
                caller="claude",
                project=root,
                work_id="U239-T2",
                purpose="claude_worker",
                model="claude-haiku-5-5",
                input_sha256=h,
                db=db,
            )
            finish_attempt(a2, outcome="FAILED", error_class="TIMEOUT", input_tokens=500, output_tokens=0, db=db)

            metrics = evaluate_roi_metrics(db=db, window=10)
            self.assertEqual(metrics["schema"], "uaos-rsi-roi-v1")
            self.assertEqual(metrics["window_attempts"], 2)
            self.assertEqual(metrics["succeeded_attempts"], 1)
            self.assertAlmostEqual(metrics["first_pass_yield"], 0.5)
            self.assertEqual(metrics["local_calls"], 1)
            self.assertEqual(metrics["paid_calls"], 1)
            self.assertAlmostEqual(metrics["local_offload_ratio"], 0.5)
            self.assertEqual(metrics["quota_saving"], "UNMEASURED")
            self.assertFalse(metrics["auto_adopt"])


if __name__ == "__main__":
    unittest.main()
