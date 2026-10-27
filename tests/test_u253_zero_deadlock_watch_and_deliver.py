from __future__ import annotations

import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import deliver, watch
from v7_harness.coord.mailbox import Mailbox


class TestU253ZeroDeadlockWatchAndDeliver(unittest.TestCase):
    """U253: Reproducing tests for the 5 root causes of 3-tool infinite wait / deadlock."""

    def test_rc1_verdict_and_handoff_tokens_infer_actionable_wake(self) -> None:
        """RC-1: Standalone VERDICT_REQUESTED and VERDICT PASS/REWORK/FAIL must infer ACTIONABLE, never drop to LEGACY."""
        self.assertTrue(
            deliver._requires_wake(
                "VERDICT_REQUESTED U225 (judge=codex, rerouted to claude). Bundle e8b13dae ready."
            )
        )
        self.assertTrue(
            deliver._requires_wake(
                "VERDICT PASS (conditional) U245-U251 rework in .work/wt_u241_control_ux"
            )
        )
        self.assertTrue(deliver._requires_wake("VERDICT REWORK U245-U251: fix findings 1-5"))
        self.assertTrue(deliver._requires_wake("U251 READY FOR PEER REVIEW"))
        self.assertTrue(deliver._requires_wake("U251-TIMING DIAGNOSTIC RECEIPT READY"))
        self.assertFalse(deliver._requires_wake("VERDICT_REQUESTED=NO status update only"))
        self.assertFalse(deliver._requires_wake("VERDICT_REQUESTED=FALSE status update"))
        self.assertFalse(deliver._requires_wake("ACK_ONLY VERDICT PASS echo"))
        self.assertFalse(deliver._requires_wake("no VERDICT_REQUESTED in this turn"))

    def test_rc2_claude_session_already_in_use_falls_back_to_ephemeral_session(self) -> None:
        """RC-2: When interactive Claude holds claude-session.json open, retry once with a fresh --session-id."""
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            sess_file = proj / ".coord" / "mailbox" / "delivery" / "claude-session.json"
            sess_file.parent.mkdir(parents=True, exist_ok=True)
            locked_id = "8d94eeeb-a66e-404e-947d-ee69c4756dfb"
            sess_file.write_text(json.dumps({"session_id": locked_id, "ready": True}), encoding="utf-8")

            calls: list[list[str]] = []

            def fake_runner(argv: list[str], **kwargs: object) -> object:
                calls.append(list(argv))
                if len(calls) == 1:
                    return types.SimpleNamespace(
                        returncode=1,
                        stdout="",
                        stderr=f"Error: Session ID {locked_id} is already in use.",
                    )
                return types.SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps({"result": "ACK_FROM_EPHEMERAL_HEADLESS", "is_error": False}),
                    stderr="",
                )

            with mock.patch("shutil.which", return_value="claude"):
                res = deliver._deliver_to_claude_locked(
                    "ACTIONABLE_DELTA U253 test",
                    project_dir=proj,
                    runner=fake_runner,
                )

            self.assertTrue(res.delivered)
            self.assertEqual(res.reason, "SENT")
            self.assertEqual(res.output, "ACK_FROM_EPHEMERAL_HEADLESS")
            self.assertEqual(len(calls), 2)
            self.assertIn("--resume", calls[0])
            self.assertIn(locked_id, calls[0])
            self.assertIn("--session-id", calls[1])
            self.assertNotIn(locked_id, calls[1])
            saved = json.loads(sess_file.read_text(encoding="utf-8"))
            self.assertEqual(saved["session_id"], locked_id)

    def test_rc3_antigravity_live_watcher_queues_interactive_without_headless_subagent(self) -> None:
        """RC-3: When antigravity has a live waking watcher, deliver() returns QUEUED_INTERACTIVE and skips agy_dispatch."""
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            (proj / ".coord").mkdir(parents=True, exist_ok=True)
            (proj / ".coord" / "PLAN.md").write_text("# Plan\n", encoding="utf-8")
            watch._beat(proj, ("antigravity",), "tok1", 2.0, 9999999999.0, wakes_session=True)
            with mock.patch("v7_harness.coord.agy_dispatch.dispatch") as mock_dispatch:
                res = deliver.deliver(
                    proj,
                    actor="claude",
                    target="antigravity",
                    message="VERDICT PASS (conditional) U245-U251 rework ready",
                )
            self.assertEqual(res.reason, "QUEUED_INTERACTIVE")
            mock_dispatch.assert_not_called()

    def test_rc4_watch_level_triggered_wakes_on_direct_master_schedule_ready_mutation(self) -> None:
        """RC-4: watch(policy='structured', wakes_session=True) wakes on unclaimed READY phase in master_schedule.json."""
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            coord_dir = proj / ".coord"
            coord_dir.mkdir(parents=True, exist_ok=True)
            sched_data = {
                "schedule_id": "U253-TEST",
                "title": "Zero Deadlock Schedule",
                "goal": "No lost wakeups",
                "current_phase_id": "U253-P2",
                "updated_at": "2026-10-26T20:45:00",
                "phases": [
                    {
                        "phase_id": "U253-P1",
                        "title": "Completed Prerequisite",
                        "owner_tool": "codex",
                        "mia_stage": "Step 1",
                        "depends_on": [],
                        "state": "DONE",
                        "updated_at": "2026-10-26T20:40:00",
                    },
                    {
                        "phase_id": "U253-P2",
                        "title": "Rerouted Ready Step",
                        "owner_tool": "antigravity",
                        "mia_stage": "Step 4",
                        "depends_on": ["U253-P1"],
                        "state": "READY",
                        "updated_at": "2026-10-26T20:45:00",
                    },
                ],
            }
            (coord_dir / "master_schedule.json").write_text(json.dumps(sched_data), encoding="utf-8")

            woken = watch.watch(
                proj,
                ("antigravity",),
                timeout_s=0.2,
                interval_s=0.05,
                policy="structured",
                wakes_session=True,
            )
            self.assertIsNotNone(woken)
            assert woken is not None
            self.assertEqual(woken["kind"], "SCHEDULE_READY")
            self.assertEqual(woken["card"], "U253-P2")
            self.assertEqual(woken["requested_target"], "antigravity")
            self.assertEqual(woken["wake_class"], "ACTIONABLE")

            second = watch.watch(
                proj,
                ("antigravity",),
                timeout_s=0.1,
                interval_s=0.05,
                policy="structured",
                wakes_session=True,
            )
            self.assertIsNone(second)



if __name__ == "__main__":
    unittest.main()
