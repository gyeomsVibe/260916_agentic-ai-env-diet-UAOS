"""U46-J4: `pilot judge --judge agy` — while Codex is away, Antigravity's CLI verdict drives the unchanged approval gate."""

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
judge: {judge}
remote_budget_tokens: 0
```
"""


class Done:
    def __init__(self, stdout=b"", returncode=0):
        self.stdout = stdout
        self.stderr = b""
        self.returncode = returncode


class JudgeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.work, self.source, stage = root / "work", root / "src", root / "stage"
        self.runs = self.work / "runs" / "T1"
        for folder in (self.runs, self.source, stage):
            folder.mkdir(parents=True)
        (self.source / "a.py").write_text("X = 1\n", encoding="utf-8")
        (stage / "a.py").write_text("X = 2\n", encoding="utf-8")
        (self.runs / "worker").write_text("claude", encoding="utf-8")
        (self.runs / "summary.json").write_text(json.dumps(
            {"agy_workspace": str(stage), "changed_files": ["a.py"], "bundle_id": "b1",
             "promotion": "DRY_RUN_PASSED", "acceptance_exit": 0}), encoding="utf-8")
        self.manual = root / "m.md"
        self.manual.write_text(MANUAL.format(judge="antigravity"), encoding="utf-8")
        self.calls, self.approvals = [], []

    def tearDown(self):
        self._tmp.cleanup()

    def runner(self, verdict="APPROVE", bundle_id="b1", usage=None, status="SUCCESS"):
        envelope = {"status": status, "conversation_id": "conv-9",
                    "usage": usage or {"input_tokens": 100, "output_tokens": 20},
                    "structured_output": {"verdict": verdict, "bundle_id": bundle_id, "evidence": ["a.py:1 ok"]}}

        def run(argv, **kwargs):
            self.calls.append((argv, kwargs))
            return Done(json.dumps(envelope).encode("utf-8"))
        return run

    def approver(self, argv, **kwargs):
        self.approvals.append(argv)
        return Done(b'{"state": "APPLIED"}')

    def judge(self, codex="LIMITED", **kw):
        kw.setdefault("runner", self.runner())
        return judge.run_judge(task_id="T1", work_dir=self.work, source=self.source, manual_path=self.manual,
                               budget=10_000, approver=self.approver, desk={"codex": {"state": codex}}, **kw)

    def test_codex_active_or_unknown_judges_itself(self):
        for state in ("ACTIVE", "UNKNOWN"):
            with self.assertRaises(judge.JudgeRefused) as caught:
                self.judge(codex=state)
            self.assertIn("CODEX_JUDGES", str(caught.exception))
        self.assertEqual([], self.calls)

    def test_approve_while_codex_away_applies_through_the_unchanged_gate(self):
        record = self.judge(codex="ABSENT")
        self.assertEqual("APPROVE", record["verdict"])
        self.assertTrue(record["applied"])
        self.assertEqual("conv-9", record["judge_conversation_id"])
        self.assertTrue(record["verdict_sha256"])
        argv, kwargs = self.calls[0]
        self.assertNotIn("--dangerously-skip-permissions", argv)
        self.assertIn("plan", argv[argv.index("--mode") + 1])
        self.assertIn("--json-schema", argv)
        self.assertEqual(str(self.runs.resolve()), kwargs["cwd"])  # resolve() expands a Windows 8.3 temp path
        cmd = self.approvals[0]
        self.assertEqual(["--approve", "b1"], cmd[cmd.index("--approve"):cmd.index("--approve") + 2])
        self.assertEqual("antigravity", cmd[cmd.index("--coord-actor") + 1])
        self.assertEqual("claude", cmd[cmd.index("--worker") + 1])
        self.assertTrue((self.runs / "judge_agy.json").is_file())

    def test_reject_mismatch_or_over_budget_never_applies(self):
        cases = [dict(verdict="REJECT"), dict(bundle_id="other"), dict(usage={"input_tokens": 9_000,
                                                                             "output_tokens": 500,
                                                                             "thinking_tokens": 800})]
        for case in cases:
            (self.runs / "judge_agy.json").unlink(missing_ok=True)
            record = self.judge(runner=self.runner(**case))
            self.assertFalse(record["applied"])
            self.assertIn(record["verdict"], ("REJECT", "UNUSABLE"))
        self.assertEqual([], self.approvals)

    def test_failed_call_is_unusable(self):
        record = self.judge(runner=self.runner(status="ERROR"))
        self.assertEqual("UNUSABLE", record["verdict"])
        self.assertEqual([], self.approvals)

    def test_one_call_per_bundle(self):
        self.judge(apply=False)
        with self.assertRaises(judge.JudgeRefused) as caught:
            self.judge()
        self.assertIn("ALREADY_JUDGED", str(caught.exception))
        self.assertEqual(1, len(self.calls))

    def test_agy_never_judges_its_own_bundle_or_a_contract_naming_another_judge(self):
        (self.runs / "worker").write_text("agy", encoding="utf-8")
        with self.assertRaises(judge.JudgeRefused) as caught:
            self.judge()
        self.assertIn("JUDGE_IS_AUTHOR", str(caught.exception))
        (self.runs / "worker").write_text("claude", encoding="utf-8")
        self.manual.write_text(MANUAL.format(judge="codex"), encoding="utf-8")
        with self.assertRaises(judge.JudgeRefused) as caught:
            self.judge()
        self.assertIn("NOT_THE_NAMED_JUDGE", str(caught.exception))
        self.assertEqual([], self.calls)

    def test_a_bundle_that_did_not_pass_acceptance_is_not_judged(self):
        summary = json.loads((self.runs / "summary.json").read_text(encoding="utf-8"))
        summary["acceptance_exit"] = 1
        (self.runs / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        with self.assertRaises(judge.JudgeRefused) as caught:
            self.judge()
        self.assertIn("NOT_READY", str(caught.exception))

    def test_cli_parses_pilot_judge(self):
        from v7_harness.cli import build_parser
        args = build_parser().parse_args(["pilot", "judge", "--task", "T1", "--work-dir", "w", "--manual", "m"])
        self.assertEqual(("agy", None, True), (args.judge, args.budget, not args.no_apply))  # U47-J5: auto


if __name__ == "__main__":
    unittest.main()
