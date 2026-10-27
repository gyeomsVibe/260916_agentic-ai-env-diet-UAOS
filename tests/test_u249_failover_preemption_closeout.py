import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord.failover_closeout import (
    FOREGROUND_WAIT_LIMIT_S,
    finalize_schedule_closeout,
    preempt_foreground_wait,
    replan_on_quota_limit,
)


class TestU249FailoverPreemptionCloseout(unittest.TestCase):
    def _write_schedule(self, root: Path, phases: list[dict]) -> Path:
        coord = root / ".coord"
        coord.mkdir(parents=True, exist_ok=True)
        sched_path = coord / "master_schedule.json"
        sched_path.write_text(
            json.dumps({"schedule_id": "U249-TEST", "phases": phases}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return sched_path

    def test_3_to_2_quota_failover_reassigns_limited_tool_phases(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_schedule(
                root,
                [
                    {"phase_id": "U1", "state": "READY", "owner_tool": "codex", "depends_on": []},
                    {"phase_id": "U2", "state": "PLANNED", "owner_tool": "codex", "depends_on": ["U1"]},
                    {"phase_id": "U3", "state": "HUMAN", "owner_tool": "codex", "human": "account billing change"},
                ],
            )
            desk = {
                "codex": {"state": "LIMITED"},
                "claude": {"state": "ACTIVE"},
                "antigravity": {"state": "ACTIVE"},
            }
            res = replan_on_quota_limit(root, desk=desk, now=1000.0)
            self.assertEqual(res["mode"], "TWO_TOOL_CONTINUITY")
            self.assertEqual(len(res["replanned"]), 2)
            owners = {r["phase_id"]: r["to_owner"] for r in res["replanned"]}
            self.assertEqual(owners["U1"], "claude")
            self.assertEqual(owners["U2"], "antigravity")

            saved = json.loads((root / ".coord" / "master_schedule.json").read_text(encoding="utf-8"))
            by_id = {p["phase_id"]: p for p in saved["phases"]}
            self.assertEqual(by_id["U3"]["state"], "HUMAN")
            self.assertEqual(by_id["U3"]["owner_tool"], "codex")

    def test_2_to_1_sole_survivor_promotes_reviews_and_claims_remaining(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_schedule(
                root,
                [
                    {"phase_id": "U1", "state": "REVIEW", "owner_tool": "claude", "waiting_on": "codex-verdict", "depends_on": []},
                    {"phase_id": "U2", "state": "READY", "owner_tool": "claude", "depends_on": ["U1"]},
                ],
            )
            desk = {
                "codex": {"state": "LIMITED"},
                "claude": {"state": "LIMITED"},
                "antigravity": {"state": "ACTIVE"},
            }
            res = replan_on_quota_limit(root, desk=desk, now=2000.0)
            self.assertEqual(res["mode"], "SOLE_SURVIVOR_AUTONOMOUS")
            self.assertEqual(res["sole_survivor_reviews_promoted"], ["U1"])
            self.assertEqual(len(res["replanned"]), 1)
            self.assertEqual(res["replanned"][0]["to_owner"], "antigravity")

            preempt = preempt_foreground_wait(
                root,
                "antigravity",
                wait_elapsed_s=5.2,
                is_background_watcher=False,
                desk=desk,
                session="agy-session-1",
                now=2005.2,
            )
            self.assertTrue(preempt["preempted"])
            self.assertEqual(preempt["action"], "CLAIM_NEXT_WORK")
            self.assertEqual(preempt["next_step"]["card"], "U2")

    def test_foreground_wait_exempts_background_watcher_and_under_5s(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_schedule(root, [{"phase_id": "U1", "state": "READY", "owner_tool": "antigravity", "depends_on": []}])
            bg = preempt_foreground_wait(root, "antigravity", wait_elapsed_s=60.0, is_background_watcher=True)
            self.assertFalse(bg["preempted"])
            self.assertEqual(bg["reason"], "BACKGROUND_WATCHER_EXEMPT")

            short = preempt_foreground_wait(root, "antigravity", wait_elapsed_s=4.9, is_background_watcher=False)
            self.assertFalse(short["preempted"])
            self.assertEqual(short["reason"], "UNDER_5S_THRESHOLD")
            self.assertEqual(FOREGROUND_WAIT_LIMIT_S, 5.0)

    def test_natural_closeout_when_all_non_human_phases_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_schedule(
                root,
                [
                    {"phase_id": "U1", "state": "DONE", "owner_tool": "claude", "needs_return_review": ["codex"]},
                    {"phase_id": "U2", "state": "DONE", "owner_tool": "antigravity"},
                ],
            )
            guard = root / ".coord" / "presence" / "stop_gate_antigravity.json"
            guard.parent.mkdir(parents=True, exist_ok=True)
            guard.write_text('{"card": "U2", "blocks": 1}', encoding="utf-8")

            res = preempt_foreground_wait(
                root,
                "antigravity",
                wait_elapsed_s=5.5,
                is_background_watcher=False,
                desk={"antigravity": {"state": "ACTIVE"}, "codex": {"state": "LIMITED"}, "claude": {"state": "LIMITED"}},
                now=3000.0,
            )
            self.assertTrue(res["preempted"])
            self.assertEqual(res["action"], "NATURAL_CLOSEOUT")
            self.assertTrue(res["closeout"]["closed_out"])
            self.assertEqual(res["closeout"]["completed_count"], 2)
            self.assertFalse(guard.exists())
            self.assertTrue(Path(res["closeout"]["receipt_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
