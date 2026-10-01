"""U46-J1: `pilot review --reviewer agy` asks Antigravity through its CLI, read-only, under the token budget gate."""

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness import review


class Done:
    def __init__(self, envelope, returncode=0):
        self.stdout = json.dumps(envelope).encode("utf-8")
        self.stderr = b""
        self.returncode = returncode


class AgyReviewTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.work, self.source, stage = root / "work", root / "src", root / "stage"
        self.runs = self.work / "runs" / "T1"
        for folder in (self.runs, self.source, stage):
            folder.mkdir(parents=True)
        (self.source / "a.py").write_text("X = 1\n", encoding="utf-8")
        (stage / "a.py").write_text("X = 2\n", encoding="utf-8")
        (self.runs / "worker").write_text("apply", encoding="utf-8")
        (self.runs / "summary.json").write_text(json.dumps(
            {"agy_workspace": str(stage), "changed_files": ["a.py"], "bundle_id": "b1"}), encoding="utf-8")
        self.calls = []

    def tearDown(self):
        self._tmp.cleanup()

    def runner(self, envelope, returncode=0):
        def run(argv, **kwargs):
            self.calls.append((argv, kwargs))
            return Done(envelope, returncode)
        return run

    def ok(self, text, usage=None):
        return {"status": "SUCCESS", "conversation_id": "conv-1", "response": text,
                "usage": usage or {"input_tokens": 100, "output_tokens": 20}}

    def test_agy_review_is_read_only_advisory_and_keeps_the_conversation_id(self):
        record = review.run_review(task_id="T1", work_dir=self.work, source=self.source, manual_text="contract",
                                   reviewer="agy", budget=10_000,
                                   runner=self.runner(self.ok('{"verdict": "PASS", "counterexamples": []}')))
        self.assertEqual("PASS", record["verdict"])
        self.assertTrue(record["advisory"])
        self.assertEqual("conv-1", record["judge_conversation_id"])
        argv, kwargs = self.calls[0]
        self.assertEqual("agy", Path(argv[0]).stem)
        self.assertNotIn("--dangerously-skip-permissions", argv)
        # U119-R2: a fitting request runs inline in an empty box under the run folder (agy read and ran files there).
        self.assertEqual(str(self.runs / "agy_box"), kwargs["cwd"])
        request = (self.runs / "review_agy_request.md").read_text(encoding="utf-8")
        self.assertIn("```diff", request)
        self.assertIn("+X = 2", request)
        self.assertLess(len(" ".join(argv)), 32_767)
        self.assertTrue((self.runs / "review_agy.json").is_file())

    def test_agy_review_needs_a_token_budget_but_no_dollar_cap(self):
        with self.assertRaises(review.ReviewRefused):
            review.run_review(task_id="T1", work_dir=self.work, source=self.source, manual_text="c",
                              reviewer="agy", budget=0, runner=self.runner(self.ok("{}")))
        record = review.run_review(task_id="T1", work_dir=self.work, source=self.source, manual_text="c",
                                   reviewer="agy", budget=5_000, budget_usd=0,
                                   runner=self.runner(self.ok('{"verdict": "REWORK", "counterexamples": ["x"]}')))
        self.assertEqual("REWORK", record["verdict"])

    def test_agy_never_reviews_its_own_bundle(self):
        (self.runs / "worker").write_text("agy", encoding="utf-8")
        with self.assertRaises(review.ReviewRefused) as caught:
            review.run_review(task_id="T1", work_dir=self.work, source=self.source, manual_text="c",
                              reviewer="agy", budget=5_000, runner=self.runner(self.ok("{}")))
        self.assertIn("REVIEWER_IS_AUTHOR", str(caught.exception))

    def test_over_budget_or_failed_agy_review_is_unusable(self):
        record = review.run_review(task_id="T1", work_dir=self.work, source=self.source, manual_text="c",
                                   reviewer="agy", budget=50,
                                   runner=self.runner(self.ok('{"verdict": "PASS"}')))
        self.assertEqual("UNUSABLE", record["verdict"])
        failed = review.run_review(task_id="T1", work_dir=self.work, source=self.source, manual_text="c",
                                   reviewer="agy", budget=5_000,
                                   runner=self.runner({"status": "ERROR", "error": "429 quota", "usage": {}}))
        self.assertEqual("UNUSABLE", failed["verdict"])
        self.assertIn("QUOTA", failed["error"])

    def test_the_claude_reviewer_still_needs_a_dollar_cap(self):
        with self.assertRaises(review.ReviewRefused) as caught:
            review.run_review(task_id="T1", work_dir=self.work, source=self.source, manual_text="c",
                              reviewer="claude", budget=5_000, budget_usd=0)
        self.assertIn("REVIEW_WITHOUT_USD_CAP", str(caught.exception))

    def test_cli_accepts_the_agy_reviewer_without_a_dollar_cap(self):
        from v7_harness.cli import build_parser
        args = build_parser().parse_args(["pilot", "review", "--task", "T1", "--work-dir", "w", "--manual", "m",
                                          "--reviewer", "agy", "--budget", "5000"])
        self.assertEqual("agy", args.reviewer)


if __name__ == "__main__":
    unittest.main()
