"""U47-J6 frozen acceptance (written by Claude): Codex judges a bundle headlessly through `codex exec`.

2026-09-27: agy answered 429 for 162h, Claude judged its own dictated bundles, and Codex's re-review (reached with
`codex exec`) rejected two of them and asked for this route: Codex first, agy second, and no approval (REVIEW) when
neither answers. The judge call must not write a desk heartbeat (UAOS_WORKER=1), must run read-only, and must
approve only a parsed verdict that names this bundle within budget.
"""

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness import judge
from v7_harness.coord.presence import mark, read

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
EVENTS = [{"type": "thread.started", "thread_id": "th-1"}, {"type": "turn.started"},
          {"type": "turn.completed", "usage": {"input_tokens": 12_000, "cached_input_tokens": 8_000,
                                              "output_tokens": 900, "reasoning_output_tokens": 400}}]


class Done:
    def __init__(self, stdout=b"", returncode=0):
        self.stdout = stdout
        self.stderr = b""
        self.returncode = returncode


class CodexJudgeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.work, self.source, stage, self.project = root / "work", root / "src", root / "stage", root / "project"
        self.runs = self.work / "runs" / "T1"
        for folder in (self.runs, self.source, stage, self.project):
            folder.mkdir(parents=True)
        (self.source / "a.py").write_text("X = 1\n", encoding="utf-8")
        (stage / "a.py").write_text("X = 2\n", encoding="utf-8")
        (self.runs / "worker").write_text("apply", encoding="utf-8")
        (self.runs / "summary.json").write_text(json.dumps(
            {"agy_workspace": str(stage), "changed_files": ["a.py"], "bundle_id": "b1",
             "promotion": "DRY_RUN_PASSED", "acceptance_exit": 0}), encoding="utf-8")
        self.manual = root / "m.md"
        self.calls = []
        self.approvals = []

    def tearDown(self):
        self._tmp.cleanup()

    def run_codex(self, answer, returncode=0, events=EVENTS, judge_name="codex", desk=None):
        self.manual.write_text(MANUAL.format(judge=judge_name), encoding="utf-8")

        def runner(argv, **kwargs):
            self.calls.append((argv, kwargs))
            if answer is not None:
                Path(argv[argv.index("-o") + 1]).write_text(json.dumps(answer), encoding="utf-8")
            return Done("\n".join(json.dumps(e) for e in events).encode("utf-8"), returncode)

        def approver(cmd, **kwargs):
            self.approvals.append(cmd)
            return Done(b"APPLIED")
        return judge.run_judge(task_id="T1", work_dir=self.work, source=self.source, manual_path=self.manual,
                               project=self.project, judge="codex", budget=50_000, runner=runner,
                               approver=approver, desk=desk if desk is not None else {"codex": {"state": "ACTIVE"}})

    def test_approve_runs_read_only_without_heartbeat_and_approves_as_codex(self):
        record = self.run_codex({"verdict": "APPROVE", "bundle_id": "b1", "evidence": ["a.py:1 X = 2"]})
        argv, kwargs = self.calls[0]
        self.assertEqual(["codex", "exec", "-s", "read-only"], argv[:4])
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", argv)
        self.assertEqual("1", kwargs["env"]["UAOS_WORKER"])
        self.assertIn(b"bundle b1", kwargs["input"])
        self.assertEqual("APPROVE", record["verdict"])
        self.assertEqual("th-1", record["judge_conversation_id"])
        self.assertEqual({"input_tokens": 12_000, "output_tokens": 900}, judge.gate_usage(record["usage"]))
        self.assertTrue(record["applied"])
        self.assertEqual("codex", self.approvals[0][self.approvals[0].index("--coord-actor") + 1])
        self.assertTrue((self.runs / "judge_codex.json").is_file())

    def test_codex_judges_whatever_its_desk_says(self):
        self.assertEqual("REJECT", self.run_codex({"verdict": "REJECT", "bundle_id": "b1", "evidence": ["x"]},
                                                  desk={"codex": {"state": "UNKNOWN"}})["verdict"])
        self.assertEqual([], self.approvals)

    def test_failed_call_fails_closed(self):
        errors = [{"type": "thread.started", "thread_id": "th-2"},
                  {"type": "turn.failed", "error": {"message": "usage limit reached"}}]
        record = self.run_codex(None, returncode=1, events=errors)
        self.assertEqual("UNUSABLE", record["verdict"])
        self.assertIn("JUDGE_FAILED:codex", record["error"])
        self.assertIn("usage limit", record["provider_message"])
        self.assertEqual([], self.approvals)

    def test_verdict_for_another_bundle_or_over_budget_is_unusable(self):
        self.assertEqual("UNUSABLE", self.run_codex({"verdict": "APPROVE", "bundle_id": "zz", "evidence": []})["verdict"])
        (self.runs / "judge_codex.json").unlink()
        big = [EVENTS[0], {"type": "turn.completed", "usage": {"input_tokens": 60_000, "output_tokens": 10}}]
        self.assertEqual("UNUSABLE", self.run_codex({"verdict": "APPROVE", "bundle_id": "b1", "evidence": []},
                                                    events=big)["verdict"])
        self.assertEqual([], self.approvals)

    def test_contract_must_name_codex(self):
        with self.assertRaisesRegex(judge.JudgeRefused, "NOT_THE_NAMED_JUDGE"):
            self.run_codex({"verdict": "APPROVE", "bundle_id": "b1", "evidence": []}, judge_name="claude")

    def test_agy_quota_lease_survives_the_next_heartbeat(self):
        self.manual.write_text(MANUAL.format(judge="antigravity"), encoding="utf-8")
        envelope = {"conversation_id": "c1", "status": "ERROR", "response": "",
                    "error": "RESOURCE_EXHAUSTED (code 429): Individual quota reached. Resets in 2h0m0s."}
        judge.run_judge(task_id="T1", work_dir=self.work, source=self.source, manual_path=self.manual,
                        project=self.project, budget=10_000,
                        runner=lambda argv, **k: Done(json.dumps(envelope).encode("utf-8")),
                        approver=lambda *a, **k: Done(), desk={"codex": {"state": "LIMITED"}})
        mark(self.project, "antigravity", "ACTIVE", ttl_s=3600)
        self.assertEqual("LIMITED", read(self.project, "antigravity")["state"])


if __name__ == "__main__":
    unittest.main()
