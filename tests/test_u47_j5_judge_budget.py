"""U47-J5 frozen acceptance (written by Claude): a judgement's token cap scales with the diff it reads.

R1c's 34 KB bundle cost 114,644 tokens against the fixed 100,000 cap and came back UNUSABLE although agy approved it.
With no --budget, `run_judge` now uses `judge_budget(len(diff))` = clamp(30,000 + 3 x diff chars, 100,000, 250,000);
an explicit budget still wins, and the record names the cap it used.
"""

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness import judge

MANUAL = """```contract
work_id: T1
worker: apply
goal: g
allow:
- a.py
acceptance: python -c "pass"
judge: antigravity
remote_budget_tokens: 0
```
"""


class Done:
    def __init__(self, stdout=b"", returncode=0):
        self.stdout = stdout
        self.stderr = b""
        self.returncode = returncode


class BudgetFormulaTest(unittest.TestCase):
    def test_clamped_linear_in_diff_chars(self):
        self.assertEqual(100_000, judge.judge_budget(0))
        self.assertEqual(100_000, judge.judge_budget(-5))
        self.assertEqual(132_000, judge.judge_budget(34_000))
        self.assertEqual(250_000, judge.judge_budget(73_334))
        self.assertEqual(250_000, judge.judge_budget(10**7))

    def test_cli_default_budget_is_automatic(self):
        from v7_harness.cli import build_parser
        args = build_parser().parse_args(["pilot", "judge", "--task", "T1", "--work-dir", "w", "--manual", "m"])
        self.assertIsNone(args.budget)


class RunJudgeBudgetTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.work, self.source, stage = root / "work", root / "src", root / "stage"
        self.runs = self.work / "runs" / "T1"
        for folder in (self.runs, self.source, stage):
            folder.mkdir(parents=True)
        (self.source / "a.py").write_text("X = 1\n", encoding="utf-8")
        (stage / "a.py").write_text("".join(f"X{i} = {i}\n" for i in range(4000)), encoding="utf-8")
        # U47-RW1e: 4,000 lines = a 53,826-char diff (budget 191,478). RW1d refuses a diff over 60,000 chars,
        # so the old 6,000-line fixture (81,826 chars) could no longer reach the budget formula.
        (self.runs / "worker").write_text("claude", encoding="utf-8")
        (self.runs / "summary.json").write_text(json.dumps(
            {"agy_workspace": str(stage), "changed_files": ["a.py"], "bundle_id": "b1",
             "promotion": "DRY_RUN_PASSED", "acceptance_exit": 0}), encoding="utf-8")
        self.manual = root / "m.md"
        self.manual.write_text(MANUAL, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def runner(argv, **kwargs):
        envelope = {"status": "SUCCESS", "conversation_id": "conv-9",
                    "usage": {"input_tokens": 150_000, "output_tokens": 0},
                    "structured_output": {"verdict": "APPROVE", "bundle_id": "b1", "evidence": ["a.py:1 ok"]}}
        return Done(json.dumps(envelope).encode("utf-8"))

    def _judge(self, **kw):
        return judge.run_judge(task_id="T1", work_dir=self.work, source=self.source, manual_path=self.manual,
                               runner=self.runner, apply=False, desk={"codex": {"state": "ABSENT"}}, **kw)

    def test_no_budget_scales_with_the_diff(self):
        record = self._judge()
        self.assertGreaterEqual(record["budget"], 180_000)
        self.assertLessEqual(record["budget"], 250_000)
        self.assertEqual("WITHIN", record["cost_gate"])
        self.assertEqual("APPROVE", record["verdict"])

    def test_explicit_budget_still_wins(self):
        record = self._judge(budget=100_000)
        self.assertEqual(100_000, record["budget"])
        self.assertEqual("UNUSABLE", record["verdict"])

    def test_zero_budget_is_refused(self):
        with self.assertRaises(judge.JudgeRefused) as caught:
            self._judge(budget=0)
        self.assertIn("JUDGE_WITHOUT_BUDGET", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
