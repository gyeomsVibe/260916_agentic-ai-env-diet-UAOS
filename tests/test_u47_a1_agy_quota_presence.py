"""U47-A1 frozen acceptance (written by Claude): an agy quota answer marks Antigravity LIMITED on the desk.

2026-09-27 01:5x: the desk read antigravity=ACTIVE (a session heartbeat), so the conductor mailed Antigravity a
verdict request and asked the user to relay it. The real call answered "RESOURCE_EXHAUSTED ... Resets in 162h49m0s",
but `pilot judge` kept only "JUDGE_FAILED:agy QUOTA" and left the desk ACTIVE. The provider's message must be kept
and the desk must read LIMITED until the reset, so routing stops sending work to a tool that cannot answer.
"""

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness import judge
from v7_harness.coord.presence import read

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
QUOTA_MSG = ("API error (attempt 6): RESOURCE_EXHAUSTED (code 429): Individual quota reached. Please upgrade your "
             "subscription to increase your limits. Resets in 162h49m0s.")


class Done:
    def __init__(self, stdout=b"", returncode=0):
        self.stdout = stdout
        self.stderr = b""
        self.returncode = returncode


class AgyQuotaPresenceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.work, self.source, stage = root / "work", root / "src", root / "stage"
        self.project = root / "project"
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
        self.manual.write_text(MANUAL, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def run_with(self, error_text, status="ERROR"):
        envelope = {"conversation_id": "c1", "status": status, "response": "", "error": error_text}

        def runner(argv, **kwargs):
            return Done(json.dumps(envelope).encode("utf-8"))
        return judge.run_judge(task_id="T1", work_dir=self.work, source=self.source, manual_path=self.manual,
                               project=self.project, budget=10_000, runner=runner,
                               approver=lambda *a, **k: Done(), desk={"codex": {"state": "LIMITED"}})

    def test_quota_keeps_message_and_marks_limited_until_reset(self):
        record = self.run_with(QUOTA_MSG)
        self.assertEqual("UNUSABLE", record["verdict"])
        self.assertIn("Resets in 162h49m0s", record["provider_message"])
        self.assertEqual("LIMITED", record["presence_marked"])
        desk = read(self.project, "antigravity")
        self.assertEqual("LIMITED", desk["state"])
        ttl = desk["expires_at"] - json.loads((self.runs / "judge_agy.json").read_text(encoding="utf-8"))["marked_at"]
        self.assertAlmostEqual(162 * 3600 + 49 * 60, ttl, delta=5)

    def test_quota_without_reset_time_uses_one_hour(self):
        self.assertEqual(3600, judge.quota_ttl("429 RESOURCE_EXHAUSTED"))
        self.assertEqual(2 * 3600 + 5 * 60, judge.quota_ttl("Resets in 2h5m0s."))
        self.assertEqual(90, judge.quota_ttl("resets in 1m30s"))

    def test_other_failures_leave_the_desk_alone(self):
        record = self.run_with("503 no capacity")
        self.assertEqual("", record["presence_marked"])
        self.assertIn("no capacity", record["provider_message"])
        self.assertEqual("UNKNOWN", read(self.project, "antigravity")["state"])


if __name__ == "__main__":
    unittest.main()
