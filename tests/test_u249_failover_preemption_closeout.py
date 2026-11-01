from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord import stop_gate
from v7_harness.coord.failover_closeout import (
    ACTIVE_STALL_TIMEOUT_S,
    FOREGROUND_WAIT_LIMIT_S,
    finalize_schedule_closeout,
    preempt_foreground_wait,
    replan_on_quota_limit,
)


class TestU249FailoverPreemptionCloseout(unittest.TestCase):
    def _write_schedule(self, root: Path, phases: list[dict]) -> Path:
        coord = root / ".coord"
        coord.mkdir(parents=True, exist_ok=True)
        (coord / "PLAN.md").write_text("# Plan\n", encoding="utf-8")
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
            self.assertEqual(by_id["U1"]["state"], "READY")
            self.assertEqual(by_id["U2"]["state"], "PLANNED")
            self.assertEqual(by_id["U3"]["state"], "HUMAN")
            self.assertEqual(by_id["U3"]["owner_tool"], "codex")

    def test_finding_1_sole_survivor_review_stays_non_done_and_only_independent_phases_proceed(self):
        """Finding 1 (P1): Sole survivor never self-approves REVIEW -> DONE; only independent phases proceed."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_schedule(
                root,
                [
                    {
                        "phase_id": "U1",
                        "state": "REVIEW",
                        "owner_tool": "antigravity",
                        "waiting_on": "codex-verdict",
                        "depends_on": [],
                    },
                    {
                        "phase_id": "U2-DEPENDENT",
                        "state": "READY",
                        "owner_tool": "claude",
                        "depends_on": ["U1"],
                    },
                    {
                        "phase_id": "U3-INDEPENDENT",
                        "state": "READY",
                        "owner_tool": "claude",
                        "depends_on": [],
                    },
                ],
            )
            desk = {
                "codex": {"state": "LIMITED"},
                "claude": {"state": "LIMITED"},
                "antigravity": {"state": "ACTIVE"},
            }
            res = replan_on_quota_limit(root, desk=desk, now=2000.0)
            self.assertEqual(res["mode"], "SOLE_SURVIVOR_AUTONOMOUS")
            self.assertEqual(res["sole_survivor_reviews_promoted"], [])
            self.assertEqual(res["sole_survivor_reviews_deferred"], ["U1"])

            saved = json.loads((root / ".coord" / "master_schedule.json").read_text(encoding="utf-8"))
            by_id = {p["phase_id"]: p for p in saved["phases"]}
            self.assertEqual(by_id["U1"]["state"], "REVIEW")
            self.assertNotEqual(by_id["U1"]["state"], "DONE")
            self.assertEqual(by_id["U1"]["needs_return_review"], ["claude", "codex"])
            # Dependent phase U2-DEPENDENT is held back as PLANNED because U1 is still REVIEW (non-DONE)
            self.assertEqual(by_id["U2-DEPENDENT"]["state"], "PLANNED")
            # Independent phase U3-INDEPENDENT is READY for sole survivor antigravity
            self.assertEqual(by_id["U3-INDEPENDENT"]["state"], "READY")
            self.assertEqual(by_id["U3-INDEPENDENT"]["owner_tool"], "antigravity")

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
            self.assertEqual(preempt["next_step"]["card"], "U3-INDEPENDENT")

    def test_finding_2_blocked_on_human_and_fresh_active_stay_untouched(self):
        """Finding 2 (P1): BLOCKED on human stays BLOCKED; fresh ACTIVE stays ACTIVE; only stalled ACTIVE or unavailable-tool BLOCKED reassigns."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = 5000.0
            self._write_schedule(
                root,
                [
                    {
                        "phase_id": "B-HUMAN",
                        "state": "BLOCKED",
                        "owner_tool": "codex",
                        "waiting_on": "human",
                        "note": "waiting on user approval",
                    },
                    {
                        "phase_id": "B-EXT",
                        "state": "BLOCKED",
                        "owner_tool": "codex",
                        "waiting_on": "external-api-reset",
                    },
                    {
                        "phase_id": "B-CODEX",
                        "state": "BLOCKED",
                        "owner_tool": "claude",
                        "waiting_on": "codex-verdict",
                    },
                    {
                        "phase_id": "A-FRESH",
                        "state": "ACTIVE",
                        "owner_tool": "codex",
                        "started_at": now - 60.0,
                    },
                    {
                        "phase_id": "A-STALLED",
                        "state": "ACTIVE",
                        "owner_tool": "codex",
                        "started_at": now - (ACTIVE_STALL_TIMEOUT_S + 10.0),
                    },
                ],
            )
            desk = {
                "codex": {"state": "LIMITED"},
                "claude": {"state": "ACTIVE"},
                "antigravity": {"state": "ACTIVE"},
            }
            res = replan_on_quota_limit(root, desk=desk, now=now)
            replanned_ids = {r["phase_id"] for r in res["replanned"]}
            self.assertEqual(replanned_ids, {"B-CODEX", "A-STALLED"})

            saved = json.loads((root / ".coord" / "master_schedule.json").read_text(encoding="utf-8"))
            by_id = {p["phase_id"]: p for p in saved["phases"]}
            self.assertEqual(by_id["B-HUMAN"]["state"], "BLOCKED")
            self.assertEqual(by_id["B-HUMAN"]["waiting_on"], "human")
            self.assertEqual(by_id["B-EXT"]["state"], "BLOCKED")
            self.assertEqual(by_id["B-EXT"]["waiting_on"], "external-api-reset")
            self.assertEqual(by_id["A-FRESH"]["state"], "ACTIVE")
            self.assertEqual(by_id["A-FRESH"]["owner_tool"], "codex")
            self.assertEqual(by_id["B-CODEX"]["state"], "READY")
            self.assertEqual(by_id["A-STALLED"]["state"], "READY")

    def test_finding_3_concurrent_replan_from_two_processes_keeps_both_updates(self):
        """Finding 3 (P2): Two real OS processes running replan_on_quota_limit concurrently under stall.lock preserve both updates."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_schedule(
                root,
                [
                    {"phase_id": "P-CODEX", "state": "READY", "owner_tool": "codex", "depends_on": []},
                    {"phase_id": "P-CLAUDE", "state": "READY", "owner_tool": "claude", "depends_on": []},
                ],
            )
            wt_root = str(Path(__file__).resolve().parents[1])
            worker_code = (
                "import sys; sys.path.insert(0, sys.argv[1]); "
                "from v7_harness.coord.failover_closeout import replan_on_quota_limit; "
                "desk = {'codex': {'state': sys.argv[3]}, 'claude': {'state': sys.argv[4]}, 'antigravity': {'state': 'ACTIVE'}}; "
                "replan_on_quota_limit(sys.argv[2], desk=desk, now=float(sys.argv[5]))"
            )
            p1 = subprocess.Popen([sys.executable, "-B", "-c", worker_code, wt_root, str(root), "LIMITED", "ACTIVE", "1001.0"])
            p2 = subprocess.Popen([sys.executable, "-B", "-c", worker_code, wt_root, str(root), "ACTIVE", "LIMITED", "1002.0"])
            self.assertEqual(p1.wait(timeout=15), 0)
            self.assertEqual(p2.wait(timeout=15), 0)

            saved = json.loads((root / ".coord" / "master_schedule.json").read_text(encoding="utf-8"))
            by_id = {p["phase_id"]: p for p in saved["phases"]}
            self.assertIn("rerouted_from", by_id["P-CODEX"])
            self.assertIn("rerouted_from", by_id["P-CLAUDE"])
            self.assertEqual(len(saved.get("failover_history", [])), 2)

    def test_finding_4_stop_gate_calls_failover_and_holds_on_replanned_card(self):
        """Finding 4 (P2): stop_gate.gate() invokes replan_on_quota_limit so a LIMITED peer's READY card is claimed and held."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_schedule(
                root,
                [
                    {"phase_id": "U-FAILOVER-GATE", "state": "READY", "owner_tool": "codex", "depends_on": []},
                ],
            )
            from v7_harness.coord import presence

            presence.mark(root, "codex", "LIMITED", now=1000.0)
            presence.mark(root, "antigravity", "ACTIVE", now=1000.0, session="agy-sess-1")
            res = stop_gate.gate(root, "antigravity", session="agy-sess-1", now=1001.0)
            self.assertIsNotNone(res)
            assert res is not None
            self.assertEqual(res["decision"], "continue")
            self.assertIn("U-FAILOVER-GATE", res["reason"])

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
