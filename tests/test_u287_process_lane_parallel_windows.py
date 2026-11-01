"""U287: Unit, Concurrency & Vaccine tests for 3-Tool Common Process-Classification Parallel Window Multiplexing."""
from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord.mailbox import Mailbox
from v7_harness.coord.presence import mark
from v7_harness.coord.process_lanes import (
    PROCESS_LANE_SPECS,
    classify_process_lane,
    collect_pending_processes,
    ensure_claude_lane_session,
    handoff_lane_result,
    lane_window_for,
    list_lane_windows,
    multiplex_and_dispatch_parallel,
    open_or_reuse_lane_window,
    select_active_tool_for_lane,
)


class TestU287ProcessLaneParallelWindows(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        (self.project / ".coord" / "mailbox").mkdir(parents=True, exist_ok=True)
        (self.project / ".coord" / "PLAN.md").write_text("# Test Plan\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_classify_process_lane_taxonomy(self) -> None:
        """All 5 canonical process lanes classify accurately by kind, flags, allowed_files, and keywords."""
        self.assertEqual(
            classify_process_lane({"kind": "P1", "message": "Urgent stall"}),
            "RECOVERY_OPS",
        )
        self.assertEqual(
            classify_process_lane({"p1_alert": True, "message": "Deadlock detected"}),
            "RECOVERY_OPS",
        )
        self.assertEqual(
            classify_process_lane({"verdict_requested": True, "message": "Please judge U287"}),
            "VERIFY_AUDIT",
        )
        self.assertEqual(
            classify_process_lane({"kind": "MERGE", "pr": 287}),
            "MERGE_RELEASE",
        )
        self.assertEqual(
            classify_process_lane({"allowed_files": ["docs/01_design.md", ".coord/tasks/U287-manual.md"]}),
            "ARCH_DESIGN",
        )
        self.assertEqual(
            classify_process_lane({"message": "Implement feature patch in v7_harness/cli.py"}),
            "IMPL_CODE",
        )
        self.assertEqual(
            classify_process_lane({"message": "Anything"}, explicit_lane="custom-lane-01"),
            "CUSTOM_LANE_01",
        )

    def test_open_and_reuse_dedicated_lane_windows_across_three_tools(self) -> None:
        """Each (lane_id, tool) pair gets its own isolated conversation window and reuses it idempotently."""
        for lane in PROCESS_LANE_SPECS:
            seen_ids: set[str] = set()
            for tool in ("codex", "claude", "antigravity"):
                first = open_or_reuse_lane_window(self.project, lane, tool, card="U287")
                self.assertTrue(first["ok"])
                self.assertFalse(first["reused"])
                self.assertTrue(first["id"])
                self.assertIn(f"[LANE:{lane}]", first["title"])
                seen_ids.add(first["id"])

                second = open_or_reuse_lane_window(self.project, lane, tool, card="U288")
                self.assertTrue(second["reused"])
                self.assertEqual(first["id"], second["id"])
                self.assertEqual(second["cards"], ["U287", "U288"])
                self.assertEqual(lane_window_for(self.project, lane, tool), first["id"])

            # Distinct tools within the same lane have distinct session/thread UUIDs
            self.assertEqual(len(seen_ids), 3)

    def test_parallel_lane_dispatch_eliminates_head_of_line_blocking(self) -> None:
        """4 concurrent process lanes execute in parallel: a slow lane (350ms) never blocks fast lanes."""
        mark(self.project, "codex", "ACTIVE")
        mark(self.project, "claude", "ACTIVE")
        mark(self.project, "antigravity", "ACTIVE")

        box = Mailbox(self.project / ".coord" / "mailbox")
        box.publish("msg_impl_1", {"kind": "IMPLEMENT", "actor": "codex", "card": "U287", "message": "Implement module A"})
        box.publish("msg_impl_2", {"kind": "IMPLEMENT", "actor": "codex", "card": "U287", "message": "Implement module B"})
        box.publish("msg_verify_1", {"kind": "VERIFY", "actor": "claude", "verdict_requested": True, "message": "Audit U287"})
        box.publish("msg_arch_1", {"kind": "DESIGN", "actor": "antigravity", "message": "MIA Stage 3 macro plan"})
        box.publish("msg_rec_1", {"kind": "BLOCKED", "actor": "claude", "p1_alert": True, "message": "Recover stall"})

        grouped = collect_pending_processes(self.project)
        self.assertEqual(len(grouped["IMPL_CODE"]), 2)
        self.assertEqual(len(grouped["VERIFY_AUDIT"]), 1)
        self.assertEqual(len(grouped["ARCH_DESIGN"]), 1)
        self.assertEqual(len(grouped["RECOVERY_OPS"]), 1)

        completion_times: dict[str, float] = {}
        lock = threading.Lock()
        t0 = time.monotonic()

        def _fake_sender(lane_id: str, tool: str, window_id: str, envelope: str, items: list) -> dict:
            # Simulate a slow bottleneck on IMPL_CODE (350ms) while other lanes finish in 20ms
            if lane_id == "IMPL_CODE":
                time.sleep(0.85)
            else:
                time.sleep(0.02)
            with lock:
                completion_times[lane_id] = time.monotonic() - t0
            return {"ok": True, "reason": "DISPATCHED", "message_id": f"batch_{lane_id}", "output": "OK"}

        res = multiplex_and_dispatch_parallel(
            self.project,
            actor="antigravity",
            max_workers=4,
            custom_sender=_fake_sender,
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["state"], "DISPATCHED_PARALLEL")
        self.assertEqual(res["lanes_dispatched"], 4)
        self.assertEqual(res["total_items"], 5)

        # Fast lanes MUST complete well before the 350ms slow lane (proving zero HoL blocking!)
        for fast_lane in ("VERIFY_AUDIT", "ARCH_DESIGN", "RECOVERY_OPS"):
            self.assertLess(
                completion_times[fast_lane],
                completion_times['IMPL_CODE'] - 0.20,
                f"{fast_lane} was blocked by IMPL_CODE ({completion_times[fast_lane]:.3f}s)",
            )
        self.assertGreaterEqual(completion_times["IMPL_CODE"], 0.80)

    def test_vaccine_claude_session_already_in_use_auto_rotates_and_parallel_locks(self) -> None:
        """Vaccine test: if Claude CLI reports 'Session ID is already in use', deliver auto-rotates UUID and succeeds."""
        from v7_harness.coord.deliver import _deliver_to_claude

        sid_initial, sfile, _ready = ensure_claude_lane_session(self.project, "VERIFY_AUDIT")
        calls: list[list[str]] = []

        def _fake_runner(argv: list[str], **kwargs):
            calls.append(list(argv))
            if len(calls) == 1:
                cp = subprocess.CompletedProcess(
                    argv, 1, stdout="", stderr=f"Error: Session ID {sid_initial} is already in use."
                )
                return cp
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps({"result": "ROTATED_LANE_OK", "is_error": False}), stderr=""
            )

        with mock.patch("shutil.which", return_value="claude"):
            result = _deliver_to_claude(
                "Verify counterexample",
                project_dir=self.project,
                runner=_fake_runner,
                lane="VERIFY_AUDIT",
            )

        self.assertTrue(result.delivered)
        self.assertEqual(result.reason, "SENT")
        self.assertEqual(result.output, "ROTATED_LANE_OK")
        self.assertEqual(len(calls), 2)
        # Verify the session UUID rotated on retry
        sid_after, _, ready_after = ensure_claude_lane_session(self.project, "VERIFY_AUDIT")
        self.assertNotEqual(sid_initial, sid_after)
        self.assertTrue(ready_after)

    def test_vaccine_limited_tool_automatic_peer_lane_failover_and_handoff(self) -> None:
        """Vaccine test: when Codex is LIMITED, lane routing and handoff immediately fail over to an ACTIVE peer."""
        mark(self.project, "codex", "LIMITED")
        mark(self.project, "claude", "ACTIVE")
        mark(self.project, "antigravity", "ACTIVE")

        selected, reason = select_active_tool_for_lane(
            self.project, "IMPL_CODE", requested_target="codex", actor="antigravity"
        )
        self.assertEqual(selected, "claude")
        self.assertEqual(reason, "LANE_FAILOVER_PEER")

        # Real-time handoff from claude to codex (LIMITED) automatically routes to antigravity's VERIFY_AUDIT window
        with mock.patch.dict("os.environ", {"UAOS_AGY_AUTO": "0"}):
            handoff = handoff_lane_result(
                self.project,
                lane_id="VERIFY_AUDIT",
                from_tool="claude",
                to_tool="codex",
                card="U287",
                summary="Impl done, requesting immediate parallel verification",
                verdict_requested=True,
            )
        self.assertTrue(handoff["ok"])
        self.assertEqual(handoff["to_tool"], "antigravity")
        self.assertEqual(handoff["route_reason"], "LANE_FAILOVER_PEER")
        self.assertTrue(handoff["window_id"])

        status = list_lane_windows(self.project)
        self.assertTrue(status["ok"])
        self.assertIn("VERIFY_AUDIT", status["lanes"])



    def test_audit_and_clear_nonstop_obstacles(self) -> None:
        """Obstacle census & clearance recovers stale locks, verifies 3-tool verdict routing, and provisions 5x3 lane windows."""
        from v7_harness.coord.process_lanes import audit_and_clear_nonstop_obstacles

        delivery_dir = self.project / ".coord" / "mailbox" / "delivery"
        delivery_dir.mkdir(parents=True, exist_ok=True)
        stale_lock = delivery_dir / "claude-session.turn.lock"
        stale_lock.write_text("99999", encoding="utf-8")
        old_time = time.time() - 300.0
        import os
        os.utime(stale_lock, (old_time, old_time))

        res = audit_and_clear_nonstop_obstacles(self.project, stale_lock_age_s=150.0)
        self.assertTrue(res["ok"])
        self.assertFalse(stale_lock.exists())
        self.assertIn("claude-session.turn.lock", res["obstacles_status"]["stale_turn_locks_recovered"])
        self.assertTrue(res["obstacles_status"]["stall_verdict_3tool_capable"])
        self.assertTrue(res["obstacles_status"]["per_lane_parallel_windows_ready"])
        self.assertEqual(len(res["provisioned_lanes"]), 5)



    def test_context_bloat_window_rotation_and_relay_burst_coalescing(self) -> None:
        """Context bloat (>= max_turns) rotates lane window UUID; 8 stacked relays coalesce by lane & drop echoes."""
        from v7_harness.coord.process_lanes import coalesce_relays_by_lane, ensure_fresh_lane_window

        w1 = ensure_fresh_lane_window(self.project, "VERIFY_AUDIT", "codex", max_turns=2)
        self.assertFalse(w1["rotated_for_context_bloat"])
        w2 = ensure_fresh_lane_window(self.project, "VERIFY_AUDIT", "codex", max_turns=2)
        self.assertFalse(w2["rotated_for_context_bloat"])
        self.assertEqual(w1["id"], w2["id"])

        # 3rd turn exceeds max_turns=2 -> automatically rotates to a fresh dedicated conversation window!
        w3 = ensure_fresh_lane_window(self.project, "VERIFY_AUDIT", "codex", max_turns=2)
        self.assertTrue(w3["rotated_for_context_bloat"])
        self.assertNotEqual(w1["id"], w3["id"])
        self.assertIn("MAX_TURNS_REACHED", w3["rotate_reason"])

        # Simulate the screenshot: 8 stacked relays including duplicate REVISE echo confirmations
        stacked_relays = [
            {"message_id": "relay_1", "actor": "claude", "card": "U279", "verdict_requested": True, "message": "Audit U279 rev4"},
            {"message_id": "relay_2", "actor": "claude", "card": "U279", "verdict_requested": True, "message": "Audit U279 rev4"},  # duplicate
            {"message_id": "relay_3", "actor": "codex", "card": "U279", "message": "결과: 이미 수신 처리한 U279 개정 4의 REVISE 확인 통지입니다."},  # echo
            {"message_id": "relay_4", "actor": "antigravity", "card": "U287", "verdict_requested": True, "message": "Verify U287 lane mux"},
            {"message_id": "relay_5", "actor": "claude", "card": "U290", "kind": "IMPLEMENT", "message": "Implement U290 patch"},
            {"message_id": "relay_6", "actor": "claude", "card": "U290", "kind": "IMPLEMENT", "message": "Implement U290 tests"},
            {"message_id": "relay_7", "actor": "codex", "card": "U277", "kind": "BLOCKED", "p1_alert": True, "message": "Recover stall"},
            {"message_id": "relay_8", "actor": "claude", "card": "U289", "kind": "DESIGN", "message": "MIA Stage 3 design"},
        ]
        coalesced = coalesce_relays_by_lane(stacked_relays)
        # 8 relays reduced to 4 distinct lane turns (duplicate & echo dropped; same-lane items batched into 1 turn!)
        self.assertEqual(set(coalesced.keys()), {"VERIFY_AUDIT", "IMPL_CODE", "RECOVERY_OPS", "ARCH_DESIGN"})
        self.assertEqual(coalesced["VERIFY_AUDIT"]["count"], 2)
        self.assertEqual(coalesced["IMPL_CODE"]["count"], 2)



    def test_echo_confirmation_storm_blocked_by_requires_wake(self) -> None:
        """Red-Team fix: Echo confirmations mentioning REVISE/VERDICT must return False in _requires_wake."""
        from v7_harness.coord.deliver import _requires_wake

        self.assertFalse(_requires_wake("결과: 이미 수신 처리한 U279 개정 4의 REVISE 확인 통지입니다."))
        self.assertFalse(_requires_wake("결과: U279 개정 4의 추가 결함 수신 확인을 처리했습니다."))
        self.assertFalse(_requires_wake("Re relay_b7a795ae: your U290C PASS is recorded as advisory evidence."))
        self.assertTrue(_requires_wake("VERDICT REWORK U287: fix line 42"))


    def test_card_by_card_parallel_windows_and_3tool_rsi_upgrade_session_broadcast(self) -> None:
        """U292: Card-by-card parallel windows bind to classification lanes, and standalone RSI session broadcasts to all 3 tools."""
        from v7_harness.coord.desk_delta import absence_items
        from v7_harness.coord.process_lanes import (
            latest_rsi_upgrade_session,
            open_or_reuse_card_parallel_windows,
            record_rsi_upgrade_session,
        )

        prov = open_or_reuse_card_parallel_windows(
            self.project,
            ["U287", "U291", "U292"],
            lane_map={"U287": "IMPL_CODE", "U291": "VERIFY_AUDIT", "U292": "ARCH_DESIGN"},
        )
        self.assertTrue(prov["ok"])
        self.assertEqual(prov["cards_provisioned"], 3)
        self.assertEqual(prov["cards"]["U287"]["lane_id"], "IMPL_CODE")
        self.assertEqual(prov["cards"]["U291"]["lane_id"], "VERIFY_AUDIT")
        self.assertEqual(prov["cards"]["U292"]["lane_id"], "ARCH_DESIGN")
        for card in ("U287", "U291", "U292"):
            for tool in ("codex", "claude", "antigravity"):
                self.assertTrue(prov["cards"][card]["tools"][tool]["window_id"])

        before_ts = time.time() - 5.0
        rsi_res = record_rsi_upgrade_session(
            self.project,
            session_id="U292-CARD-LANE-PARALLEL-WINDOWS-20261101",
            title="3-Tool Card & Process-Lane Parallel Window Execution OS Upgrade",
            summary_ko="카드별·분류별 병렬 대화창 가동 로직 3대 도구 전역 규칙 고정 및 실가동 완료.",
            rules_version="7.6.2",
            runtime_version="7.6.2-u292",
            actor="antigravity",
        )
        self.assertTrue(rsi_res["ok"])
        self.assertEqual(rsi_res["visibility"], ["codex", "claude", "antigravity"])
        self.assertEqual(len(rsi_res["published_mailbox_ids"]), 3)
        self.assertTrue(Path(rsi_res["session_json"]).is_file())
        self.assertTrue(Path(rsi_res["report_md"]).is_file())

        latest = latest_rsi_upgrade_session(self.project)
        self.assertIsNotNone(latest)
        self.assertEqual(latest["session_id"], "U292-CARD-LANE-PARALLEL-WINDOWS-20261101")
        self.assertEqual(latest["global_rules_version"], "7.6.2")

        # Verify all 3 tools see the standalone RSI session in desk_delta.absence_items
        for tool in ("codex", "claude", "antigravity"):
            items = absence_items(self.project, before_ts, tool)
            self.assertTrue(
                any("rsi_session U292-CARD-LANE-PARALLEL-WINDOWS-20261101" in it for it in items),
                f"{tool} did not see rsi_session in absence_items: {items}",
            )


if __name__ == "__main__":




    unittest.main()
