"""U239B/U239C fixed acceptance: Codex counterexamples for evaluate_roi_metrics."""
from pathlib import Path
import tempfile
import unittest


class U239BRsiCounterexampleTests(unittest.TestCase):
    def test_provider_ollama_with_nondefault_model_counts_as_local_not_paid(self):
        from v7_harness.invocation import evaluate_roi_metrics, finish_attempt, start_attempt

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "invocations.sqlite3"
            h = "b" * 64
            a1 = start_attempt(
                caller="codex",
                project=root,
                work_id="U239B-CE1",
                purpose="local_draft",
                model="qwen3:4b",
                input_sha256=h,
                db=db,
            )
            finish_attempt(
                a1,
                outcome="SUCCEEDED",
                input_tokens=400,
                output_tokens=80,
                db=db,
                provider="ollama",
                cost_usd=0,
            )
            metrics = evaluate_roi_metrics(db=db, window=10)
            self.assertEqual(metrics["local_calls"], 1)
            self.assertEqual(metrics["paid_calls"], 0)
            self.assertAlmostEqual(metrics["local_offload_ratio"], 1.0)

    def test_retry_after_failed_first_attempt_is_not_counted_as_first_pass(self):
        from v7_harness.invocation import evaluate_roi_metrics, finish_attempt, start_attempt

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "invocations.sqlite3"
            h = "c" * 64
            a_fail = start_attempt(
                caller="claude",
                project=root,
                work_id="WORK-A",
                purpose="pilot_local",
                model="qwen2.5-coder:7b",
                input_sha256=h,
                db=db,
            )
            finish_attempt(a_fail, outcome="FAILED", error_class="PARSE_ERROR", input_tokens=500, output_tokens=10, db=db)

            a_retry = start_attempt(
                caller="claude",
                project=root,
                work_id="WORK-A",
                purpose="pilot_local",
                model="qwen2.5-coder:7b",
                input_sha256=h,
                db=db,
            )
            finish_attempt(a_retry, outcome="SUCCEEDED", input_tokens=500, output_tokens=100, db=db)

            b_pass = start_attempt(
                caller="antigravity",
                project=root,
                work_id="WORK-B",
                purpose="pilot_local",
                model="qwen2.5-coder:7b",
                input_sha256=h,
                db=db,
            )
            finish_attempt(b_pass, outcome="SUCCEEDED", input_tokens=400, output_tokens=90, db=db)

            metrics = evaluate_roi_metrics(db=db, window=10)
            self.assertEqual(metrics["window_attempts"], 3)
            self.assertEqual(metrics["succeeded_attempts"], 2)
            self.assertAlmostEqual(metrics["first_pass_yield"], 0.5)

    def test_unknown_provider_and_model_stays_unknown_not_paid(self):
        from v7_harness.invocation import evaluate_roi_metrics, finish_attempt, start_attempt

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "invocations.sqlite3"
            h = "d" * 64
            u1 = start_attempt(
                caller="codex",
                project=root,
                work_id="WORK-U",
                purpose="custom_probe",
                model="custom-unclassified-model",
                input_sha256=h,
                db=db,
            )
            finish_attempt(u1, outcome="SUCCEEDED", input_tokens=100, output_tokens=20, db=db)
            metrics = evaluate_roi_metrics(db=db, window=10)
            self.assertEqual(metrics["local_calls"], 0)
            self.assertEqual(metrics["paid_calls"], 0)
            self.assertEqual(metrics["unknown_route_calls"], 1)

    def test_retry_is_not_first_pass_when_first_failure_falls_outside_window(self):
        from v7_harness.invocation import evaluate_roi_metrics, finish_attempt, start_attempt

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "calls.sqlite3"
            for work, outcome in [("A", "FAILED"), ("A", "SUCCEEDED"), ("B", "SUCCEEDED")]:
                attempt = start_attempt(
                    caller="codex",
                    project=root,
                    work_id=work,
                    purpose="local_draft",
                    model="qwen2.5-coder:7b",
                    input_sha256="a" * 64,
                    db=db,
                )
                finish_attempt(attempt, outcome=outcome, db=db)
            self.assertEqual(0.5, evaluate_roi_metrics(db=db, window=2)["first_pass_yield"])

    def test_different_projects_with_same_work_id_remain_distinct(self):
        from v7_harness.invocation import evaluate_roi_metrics, finish_attempt, start_attempt

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "calls.sqlite3"
            for name, outcome in [("project-a", "FAILED"), ("project-b", "SUCCEEDED")]:
                project = root / name
                project.mkdir()
                attempt = start_attempt(
                    caller="codex",
                    project=project,
                    work_id="U01",
                    purpose="local_draft",
                    model="qwen2.5-coder:7b",
                    input_sha256="a" * 64,
                    db=db,
                )
                finish_attempt(attempt, outcome=outcome, db=db)
            self.assertEqual(0.5, evaluate_roi_metrics(db=db, window=10)["first_pass_yield"])


if __name__ == "__main__":
    unittest.main()
