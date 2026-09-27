"""U47-RW1d red-first counterexamples for the rejected RW1c stage."""

import json
import tempfile
import unittest
from pathlib import Path

from tests import test_u47_j6_codex_judge as j6_tests
from v7_harness import judge
from v7_harness.coord.presence import mark, read
from v7_harness.review import MAX_DIFF_CHARS


APPROVE = {"verdict": "APPROVE", "bundle_id": "b1", "evidence": ["x"]}


class Rw1dCounterexamplesTest(unittest.TestCase):
    def test_failed_event_blocks_valid_approve_even_with_zero_exit(self):
        case = j6_tests.CodexJudgeTest(methodName="test_failed_call_fails_closed")
        case.setUp()
        try:
            events = [
                {"type": "thread.started", "thread_id": "th-failed"},
                {"type": "turn.failed", "error": {"message": "quota"}},
            ]
            record = case.run_codex(APPROVE, returncode=0, events=events)
            self.assertEqual("UNUSABLE", record["verdict"])
            self.assertIn("JUDGE_FAILED:codex", record["error"])
            self.assertIn("quota", record["provider_message"])
            self.assertFalse(record.get("applied"))
            self.assertEqual([], case.approvals)
        finally:
            case.tearDown()

    def test_same_state_heartbeat_cannot_shorten_live_quota_lease(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            original_expiry = 1_000.0 + 162 * 3600
            mark(project, "antigravity", "LIMITED", ttl_s=162 * 3600, now=1_000.0, lease=True)
            mark(project, "antigravity", "LIMITED", ttl_s=3600, now=1_001.0)
            desk = read(project, "antigravity", now=5_000.0)
            self.assertEqual("LIMITED", desk["state"])
            self.assertEqual(original_expiry, desk["expires_at"])
            mark(project, "antigravity", "ACTIVE", ttl_s=3600, now=5_001.0)
            self.assertEqual("LIMITED", read(project, "antigravity", now=5_002.0)["state"])

    def test_oversized_complete_diff_is_refused_before_judge_call(self):
        case = j6_tests.CodexJudgeTest(methodName="test_failed_call_fails_closed")
        case.setUp()
        try:
            summary = json.loads((case.runs / "summary.json").read_text(encoding="utf-8"))
            stage_file = Path(summary["agy_workspace"]) / "a.py"
            stage_file.write_text("X = 2\n" * (MAX_DIFF_CHARS // 6 + 100), encoding="utf-8")
            with self.assertRaisesRegex(judge.JudgeRefused, "DIFF_TOO_LARGE"):
                case.run_codex(APPROVE)
            self.assertEqual([], case.calls)
            self.assertEqual([], case.approvals)
        finally:
            case.tearDown()


if __name__ == "__main__":
    unittest.main()
