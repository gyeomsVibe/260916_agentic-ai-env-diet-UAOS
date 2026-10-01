"""U44: a worker claude contract runs end to end.

The first real claude run (2026-09-26) replied with a ===FILE block instead of editing the file and ended NO_CHANGES;
generated claude manuals could not pass lint (no remote_budget_usd); judge user was rejected.
"""

import tempfile
import unittest
from pathlib import Path

from v7_harness.adapters import claude_worker
from v7_harness.manual import lint, new_manual, output_rule


class ClaudeContractTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "a.py").write_text("X = 1\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _manual(self, worker, judge="codex", usd=0.0, tokens=50000):
        return new_manual(self.root, work_id="T1", worker=worker, goal="Set X = 2 in `a.py`.", inputs=["a.py"],
                          allow=["a.py"], acceptance="python -c 1", judge=judge, remote_budget_tokens=tokens,
                          remote_budget_usd=usd,
                          # U106: a paid worker on code needs a recorded reason; this fixture tests the claude contract.
                          paid_reason="fixture exercises the claude worker contract")

    def test_generated_claude_manual_passes_lint_with_usd_cap(self):
        text = self._manual("claude", usd=0.3)
        self.assertIn("remote_budget_usd: 0.3", text)
        report = lint(text, self.root)
        self.assertTrue(report.ok, report.errors)

    def test_claude_manual_without_usd_cap_still_fails(self):
        report = lint(self._manual("claude"), self.root)
        self.assertIn("REMOTE_WITHOUT_USD_CAP: worker claude needs remote_budget_usd > 0", report.errors)

    def test_tool_workers_are_told_to_edit_files(self):
        for worker in ("claude", "agy", "lane"):
            text = self._manual(worker, judge="user" if worker != "agy" else "codex", usd=0.3)
            self.assertIn("Edit the files under `allow` directly", text)
            self.assertNotIn("Reply with ===FILE / ===EDIT blocks only", text)

    def test_block_workers_keep_the_block_rule(self):
        for worker in ("local", "apply"):
            self.assertTrue(output_rule(worker).startswith("- Reply with ===FILE / ===EDIT blocks only"))

    def test_user_is_an_accepted_judge(self):
        report = lint(self._manual("claude", judge="user", usd=0.3), self.root)
        self.assertTrue(report.ok, report.errors)

    def test_claude_still_cannot_judge_its_own_work(self):
        report = lint(self._manual("claude", judge="claude", usd=0.3), self.root)
        self.assertTrue(any(e.startswith("SELF_JUDGE") for e in report.errors), report.errors)

    def test_worker_system_prompt_overrides_old_block_manuals(self):
        self.assertIn("Edit or Write", claude_worker.SYSTEM)
        self.assertIn("not your reply", claude_worker.SYSTEM)

    def test_review_uses_its_own_small_turn_limit(self):
        cmd = claude_worker.review_command("p", "sonnet", 0.5)
        turns = cmd[cmd.index("--max-turns") + 1]
        self.assertEqual(turns, claude_worker.REVIEW_MAX_TURNS)
        self.assertLessEqual(int(turns), 10)
        worker = claude_worker.worker_command("p", "sonnet", 0.5)
        self.assertEqual(worker[worker.index("--max-turns") + 1], claude_worker.MAX_TURNS)

    def test_review_prompt_says_the_diff_is_complete(self):
        from v7_harness.review import review_prompt
        text = review_prompt("T1", "contract", "diff")
        self.assertIn("The diff below is the complete change", text)
        self.assertNotIn("Read files in the current directory if needed", text)

    def _review_fixture(self, replies, after="X = 2\n"):
        import json as _json
        work, source, stage = self.root / "work", self.root / "src", self.root / "stage"
        runs = work / "runs" / "T9"
        for folder in (runs, source, stage):
            folder.mkdir(parents=True)
        (source / "a.py").write_text("X = 1\n", encoding="utf-8")
        (stage / "a.py").write_text(after, encoding="utf-8")
        (runs / "worker").write_text("apply", encoding="utf-8")
        (runs / "summary.json").write_text(_json.dumps({"agy_workspace": str(stage), "changed_files": ["a.py"],
                                                          "bundle_id": "b"}), encoding="utf-8")
        calls = []

        class Done:
            def __init__(self, data):
                self.stdout = _json.dumps(data).encode("utf-8")

        def runner(argv, **kwargs):
            calls.append(argv)
            self.stdin_inputs.append(kwargs.get("input"))
            return Done(replies[len(calls) - 1])

        self.stdin_inputs = []
        return work, source, runner, calls

    def test_a_long_review_request_goes_on_stdin_not_the_command_line(self):
        from v7_harness import review
        long_after = "".join(f"LINE_{i} = {i}\n" for i in range(3000))
        work, source, runner, calls = self._review_fixture([
            {"subtype": "success", "session_id": "s1", "num_turns": 1, "total_cost_usd": 0.02,
             "result": '{"verdict": "PASS", "counterexamples": []}', "usage": {"input_tokens": 1, "output_tokens": 5}},
        ], after=long_after)
        record = review.run_review(task_id="T9", work_dir=work, source=source, manual_text="contract",
                                   reviewer="claude", budget=10_000, budget_usd=0.5, runner=runner)
        self.assertEqual("PASS", record["verdict"])
        argv = calls[0]
        self.assertEqual(review.STDIN_PROMPT, argv[argv.index("-p") + 1])
        self.assertLess(len(" ".join(argv)), 32_767)
        sent = self.stdin_inputs[0].decode("utf-8")
        self.assertIn("```diff", sent)
        self.assertIn("LINE_2999 = 2999", sent)

    def test_a_short_review_request_stays_on_the_command_line(self):
        from v7_harness import review
        work, source, runner, calls = self._review_fixture([
            {"subtype": "success", "session_id": "s1", "num_turns": 1, "total_cost_usd": 0.02,
             "result": '{"verdict": "PASS", "counterexamples": []}', "usage": {"input_tokens": 1, "output_tokens": 5}},
        ])
        review.run_review(task_id="T9", work_dir=work, source=source, manual_text="contract",
                          reviewer="claude", budget=10_000, budget_usd=0.5, runner=runner)
        self.assertIn("```diff", calls[0][calls[0].index("-p") + 1])
        self.assertIsNone(self.stdin_inputs[0])

    def test_a_review_out_of_turns_gets_one_forced_final_answer(self):
        from v7_harness import review
        work, source, runner, calls = self._review_fixture([
            {"subtype": "error_max_turns", "is_error": True, "session_id": "s1", "result": "", "num_turns": 4,
             "total_cost_usd": 0.10, "usage": {"input_tokens": 10, "output_tokens": 20, "cache_read_input_tokens": 300}},
            {"subtype": "success", "session_id": "s1", "num_turns": 1, "total_cost_usd": 0.12,
             "result": '{"verdict": "PASS", "counterexamples": []}',
             "usage": {"input_tokens": 1, "output_tokens": 5, "cache_read_input_tokens": 100}},
        ])
        record = review.run_review(task_id="T9", work_dir=work, source=source, manual_text="contract",
                                   reviewer="claude", budget=10_000, budget_usd=0.5, runner=runner)
        self.assertEqual(2, len(calls))
        second = calls[1]
        self.assertEqual("s1", second[second.index("--resume") + 1])
        self.assertEqual("1", second[second.index("--max-turns") + 1])
        self.assertEqual("0.40", second[second.index("--max-budget-usd") + 1])
        self.assertEqual(review.FINAL_ANSWER, second[second.index("-p") + 1])
        self.assertEqual(("PASS", "WITHIN", ""), (record["verdict"], record["cost_gate"], record["error"]))
        self.assertEqual((11, 25, 400, 5, 120000), tuple(record["usage"][k] for k in (
            "input_tokens", "output_tokens", "cache_read_input_tokens", "turns", "cost_microusd")))

    def test_a_review_that_answered_badly_is_not_resumed(self):
        from v7_harness import review
        work, source, runner, calls = self._review_fixture([
            {"subtype": "success", "session_id": "s1", "result": "looks fine", "num_turns": 2, "total_cost_usd": 0.05,
             "usage": {"input_tokens": 10, "output_tokens": 20}},
        ])
        record = review.run_review(task_id="T9", work_dir=work, source=source, manual_text="contract",
                                   reviewer="claude", budget=10_000, budget_usd=0.5, runner=runner)
        self.assertEqual(1, len(calls))
        self.assertEqual("UNUSABLE", record["verdict"])
        self.assertIn("REVIEW_UNPARSED", record["error"])
        self.assertIn("(success)", record["error"])

    def test_a_review_with_no_dollars_left_is_not_resumed(self):
        from v7_harness import review
        work, source, runner, calls = self._review_fixture([
            {"subtype": "error_max_turns", "is_error": True, "session_id": "s1", "result": "", "num_turns": 4,
             "total_cost_usd": 0.495, "usage": {"input_tokens": 10, "output_tokens": 20}},
        ])
        record = review.run_review(task_id="T9", work_dir=work, source=source, manual_text="contract",
                                   reviewer="claude", budget=10_000, budget_usd=0.5, runner=runner)
        self.assertEqual((1, "UNUSABLE"), (len(calls), record["verdict"]))
        self.assertNotIn("--resume", calls[0])


if __name__ == "__main__":
    unittest.main()
