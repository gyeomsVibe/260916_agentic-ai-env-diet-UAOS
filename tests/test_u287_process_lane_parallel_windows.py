"""U287: Unit, Concurrency & Vaccine tests for 3-Tool Common Process-Classification Parallel Window Multiplexing."""
from __future__ import annotations

import json
import os
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
    _lane_lock,
    classify_process_lane,
    collect_pending_processes,
    dispatch_single_lane_batch,
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
        self.codex_sessions_dir = self.project / ".codex_sessions"
        self.codex_sessions_dir.mkdir(parents=True, exist_ok=True)
        self._codex_env_patcher = mock.patch.dict(
            os.environ, {"UAOS_CODEX_SESSIONS": str(self.codex_sessions_dir)}
        )
        self._codex_env_patcher.start()
        (self.project / ".coord" / "mailbox").mkdir(parents=True, exist_ok=True)
        (self.project / ".coord" / "PLAN.md").write_text("# Test Plan\n", encoding="utf-8")
        # S5 D-R2: lane dispatch now needs a boot participation snapshot; these lane tests assume every tool executes.
        (self.project / ".coord" / "participation.json").write_text(json.dumps({
            "mode": "TRIO", "roles": {t: "EXECUTOR" for t in ("codex", "claude", "antigravity")},
            "decided_at": time.time(), "expires_at": time.time() + 3600}), encoding="utf-8")

    def tearDown(self) -> None:
        self._codex_env_patcher.stop()
        self._tmp.cleanup()

    def test_classify_process_lane_taxonomy_and_word_boundaries(self) -> None:
        """All 5 canonical process lanes classify accurately by kind, flags, allowed_files, and whole-word keywords."""
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
        # Whole-word boundary check: substrings like 'latest' (~test), 'PLAN.md' (~plan), 'health' (~heal)
        # must NOT false-match VERIFY_AUDIT / ARCH_DESIGN / RECOVERY_OPS when implementing code!
        self.assertEqual(
            classify_process_lane({"message": "Update latest status in PLAN.md for health endpoint"}),
            "IMPL_CODE",
        )

    def test_open_and_reuse_dedicated_lane_windows_and_codex_rollout_isolation(self) -> None:
        """Each (lane_id, tool) pair gets its own window; opening lane windows never writes fake rollout stubs into Codex's session store."""
        from v7_harness.coord.deliver import _codex_thread
        from v7_harness.coord.process_lanes import _resolve_codex_lane_thread

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

        # P1 guard: opening/reusing lane windows MUST NEVER create or forge rollout files in _codex_sessions()
        self.assertEqual(list(self.codex_sessions_dir.rglob("*.jsonl")), [])
        codex_wid = lane_window_for(self.project, "IMPL_CODE", "codex")
        assert codex_wid is not None
        self.assertEqual(_resolve_codex_lane_thread(self.project, codex_wid), "")

        # When a real Codex-created rollout exists, _resolve_codex_lane_thread resolves a verified non-desk lane thread,
        # never an unbound lane UUID and never the designated user desk thread ("user threads stay user-only").
        from v7_harness.coord.deliver import register_user_desk
        real_desk_tid = "11111111-2222-4333-8444-555555555555"
        real_lane_tid = "22222222-3333-4444-8555-666666666666"
        day_dir = self.codex_sessions_dir / "2026" / "11" / "02"
        day_dir.mkdir(parents=True, exist_ok=True)
        for tid in (real_desk_tid, real_lane_tid):
            rollout = day_dir / f"rollout-2026-11-02T00-00-00-{tid}.jsonl"
            rollout.write_text(
                json.dumps({
                    "timestamp": "2026-11-02T00:00:00Z",
                    "type": "session_meta",
                    "payload": {"id": tid, "session_id": tid, "cwd": str(self.project.resolve())},
                }) + "\n",
                encoding="utf-8",
            )
        register_user_desk(self.project, "codex", real_desk_tid, source="UserPromptSubmit")
        self.assertEqual(_resolve_codex_lane_thread(self.project, real_lane_tid), real_lane_tid)
        self.assertEqual(_resolve_codex_lane_thread(self.project, real_desk_tid), "")
        self.assertEqual(_resolve_codex_lane_thread(self.project, codex_wid), "")
        chosen, _fb, status = _codex_thread(self.project, "")
        self.assertEqual(status, "DISPATCH")
        self.assertEqual(chosen, real_desk_tid)

    def test_lane_lock_mutual_exclusion_and_timeout(self) -> None:
        """Direct discriminating test for _lane_lock: same lane blocks/times out, different lane acquires immediately."""
        from v7_harness.coord import process_lanes as pl_mod

        holder_ready = threading.Event()
        release_holder = threading.Event()

        def _hold_impl_lock() -> None:
            with pl_mod._lane_lock(self.project, "IMPL_CODE", timeout_s=5.0):
                holder_ready.set()
                release_holder.wait(timeout=5.0)

        t = threading.Thread(target=_hold_impl_lock, daemon=True)
        t.start()
        self.assertTrue(holder_ready.wait(timeout=2.0))
        try:
            # Contending on the SAME lane ("IMPL_CODE") must raise TimeoutError when held
            with self.assertRaises(TimeoutError):
                with pl_mod._lane_lock(self.project, "IMPL_CODE", timeout_s=0.08):
                    pass

            # Acquiring a DIFFERENT lane ("VERIFY_AUDIT") must succeed immediately (< 50ms)
            t0 = time.monotonic()
            with pl_mod._lane_lock(self.project, "VERIFY_AUDIT", timeout_s=0.5):
                elapsed = time.monotonic() - t0
            self.assertLess(elapsed, 0.25)
        finally:
            release_holder.set()
            t.join(timeout=2.0)

    def test_parallel_lane_dispatch_via_real_deliver_and_per_lane_turn_locks(self) -> None:
        """4 concurrent process lanes execute through real deliver() + _claude_turn(lane=...), proving zero HoL blocking and zero wake amplification."""
        mark(self.project, "codex", "LIMITED")
        mark(self.project, "claude", "ACTIVE")
        mark(self.project, "antigravity", "LIMITED")

        box = Mailbox(self.project / ".coord" / "mailbox")
        box.publish("msg_impl_1", {"kind": "IMPLEMENT", "actor": "codex", "card": "U287", "message": "Implement module A"})
        box.publish("msg_impl_2", {"kind": "IMPLEMENT", "actor": "codex", "card": "U287", "message": "Implement module B"})
        box.publish("msg_verify_1", {"kind": "VERIFY", "actor": "codex", "verdict_requested": True, "message": "Audit U287"})
        box.publish("msg_arch_1", {"kind": "DESIGN", "actor": "codex", "message": "MIA Stage 3 macro plan"})
        box.publish("msg_rec_1", {"kind": "BLOCKED", "actor": "codex", "p1_alert": True, "message": "Recover stall"})

        grouped = collect_pending_processes(self.project)
        self.assertEqual(len(grouped["IMPL_CODE"]), 2)
        self.assertEqual(len(grouped["VERIFY_AUDIT"]), 1)
        self.assertEqual(len(grouped["ARCH_DESIGN"]), 1)
        self.assertEqual(len(grouped["RECOVERY_OPS"]), 1)

        completion_times: dict[str, float] = {}
        observed_lock_files: set[str] = set()
        lock = threading.Lock()
        t0 = time.monotonic()

        def _real_deliver_runner(argv: list[str], **kwargs):
            # Inspect active .turn.lock files in .coord/mailbox/delivery while inside _claude_turn
            delivery_dir = self.project / ".coord" / "mailbox" / "delivery"
            cmd_text = " ".join(str(x) for x in argv)
            detected_lane = "UNKNOWN"
            for lid in ("IMPL_CODE", "VERIFY_AUDIT", "ARCH_DESIGN", "RECOVERY_OPS"):
                if f"LANE={lid}" in cmd_text:
                    detected_lane = lid
                    break
            if delivery_dir.is_dir():
                for lf in delivery_dir.glob("*.turn.lock"):
                    with lock:
                        observed_lock_files.add(lf.name)
            if detected_lane == "IMPL_CODE":
                time.sleep(0.55)
            else:
                time.sleep(0.02)
            with lock:
                completion_times[detected_lane] = time.monotonic() - t0
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps({"result": f"OK_{detected_lane}", "is_error": False}), stderr=""
            )

        with mock.patch("shutil.which", return_value="claude"), mock.patch.dict(os.environ, {"UAOS_AGY_AUTO": "0"}):
            res = multiplex_and_dispatch_parallel(
                self.project,
                actor="antigravity",
                max_workers=4,
                runner=_real_deliver_runner,
            )

        self.assertTrue(res["ok"])
        self.assertEqual(res["state"], "DISPATCHED_PARALLEL")
        self.assertEqual(res["lanes_dispatched"], 4)
        self.assertEqual(res["total_items"], 5)

        # Verify distinct per-lane turn locks were created during _deliver_to_claude
        for lid in ("IMPL_CODE", "VERIFY_AUDIT", "ARCH_DESIGN", "RECOVERY_OPS"):
            self.assertIn(f"claude-lane-{lid}.turn.lock", observed_lock_files)

        # Fast lanes MUST complete well before the 550ms slow lane (proving per-lane lock concurrency!)
        for fast_lane in ("VERIFY_AUDIT", "ARCH_DESIGN", "RECOVERY_OPS"):
            self.assertLess(
                completion_times[fast_lane],
                completion_times["IMPL_CODE"] - 0.20,
                f"{fast_lane} was blocked by IMPL_CODE ({completion_times[fast_lane]:.3f}s)",
            )

        # P1 Regression Proof: Calling collect_pending_processes / multiplex_and_dispatch_parallel a second time
        # MUST NOT re-collect the already-dispatched source letters or the newly published lane batch envelopes!
        grouped_after = collect_pending_processes(self.project)
        self.assertEqual(grouped_after, {})
        res_second = multiplex_and_dispatch_parallel(
            self.project,
            actor="antigravity",
            max_workers=4,
            runner=_real_deliver_runner,
        )
        self.assertEqual(res_second["state"], "IDLE_NO_PENDING")
        self.assertEqual(res_second["total_items"], 0)

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
        sid_after, _, ready_after = ensure_claude_lane_session(self.project, "VERIFY_AUDIT")
        self.assertNotEqual(sid_initial, sid_after)
        self.assertTrue(ready_after)

    def test_failover_rotates_only_failed_primary_tool_and_preserves_healthy_peer_window(self) -> None:
        """P2 fix verification: when primary tool fails delivery, only the failed tool rotates; healthy peer reuses its window."""
        mark(self.project, "codex", "ACTIVE")
        mark(self.project, "claude", "ACTIVE")
        mark(self.project, "antigravity", "LIMITED")

        codex_initial = open_or_reuse_lane_window(self.project, "IMPL_CODE", "codex")["id"]
        claude_initial = open_or_reuse_lane_window(self.project, "IMPL_CODE", "claude")["id"]

        box = Mailbox(self.project / ".coord" / "mailbox")
        box.publish("msg_failover_1", {"kind": "IMPLEMENT", "actor": "antigravity", "card": "U292", "message": "Patch"})
        items = collect_pending_processes(self.project)["IMPL_CODE"]

        def _sender_fail_codex_succeed_claude(lane_id: str, tool: str, window_id: str, envelope: str, batch: list) -> dict:
            if tool == "codex":
                return {"ok": False, "reason": "DELIVERY_FAILED:rc=1", "message_id": "m1", "output": "fail"}
            return {"ok": True, "reason": "SENT", "message_id": "m2", "output": "ok"}

        res = dispatch_single_lane_batch(
            self.project,
            "IMPL_CODE",
            items,
            actor="antigravity",
            preferred_tool="codex",
            custom_sender=_sender_fail_codex_succeed_claude,
        )
        self.assertTrue(res["ok"])
        self.assertTrue(res["failover_used"])
        self.assertEqual(res["failed_primary_tool"], "codex")
        self.assertEqual(res["tool"], "claude")
        # Healthy peer (claude) MUST keep its existing window UUID without unnecessary rotation
        self.assertEqual(res["window_id"], claude_initial)
        self.assertEqual(lane_window_for(self.project, "IMPL_CODE", "claude"), claude_initial)
        # Failed primary (codex) MUST have rotated to generation 1
        self.assertNotEqual(lane_window_for(self.project, "IMPL_CODE", "codex"), codex_initial)

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

    def test_audit_and_clear_nonstop_obstacles_respects_live_pid(self) -> None:
        """Obstacle clearance recovers dead-PID stale locks (>150s) but never steals a lock held by a live PID."""
        from v7_harness.coord.process_lanes import audit_and_clear_nonstop_obstacles

        delivery_dir = self.project / ".coord" / "mailbox" / "delivery"
        delivery_dir.mkdir(parents=True, exist_ok=True)
        old_time = time.time() - 300.0

        dead_lock = delivery_dir / "claude-session.turn.lock"
        dead_lock.write_text("99999999", encoding="utf-8")
        os.utime(dead_lock, (old_time, old_time))

        live_lock = delivery_dir / "claude-lane-IMPL_CODE.turn.lock"
        live_lock.write_text(str(os.getpid()), encoding="utf-8")
        os.utime(live_lock, (old_time, old_time))

        res = audit_and_clear_nonstop_obstacles(self.project, stale_lock_age_s=150.0)
        self.assertTrue(res["ok"])
        self.assertFalse(dead_lock.exists())
        self.assertTrue(live_lock.exists(), "Live PID turn lock must not be renamed!")
        self.assertIn("claude-session.turn.lock", res["obstacles_status"]["stale_turn_locks_recovered"])
        self.assertNotIn("claude-lane-IMPL_CODE.turn.lock", res["obstacles_status"]["stale_turn_locks_recovered"])

    def test_context_bloat_window_rotation_and_relay_burst_coalescing(self) -> None:
        """Context bloat (>= max_turns) rotates only that tool's lane window UUID; 8 stacked relays coalesce by lane."""
        from v7_harness.coord.process_lanes import coalesce_relays_by_lane, ensure_fresh_lane_window

        w1 = ensure_fresh_lane_window(self.project, "VERIFY_AUDIT", "codex", max_turns=2)
        self.assertFalse(w1["rotated_for_context_bloat"])
        w2 = ensure_fresh_lane_window(self.project, "VERIFY_AUDIT", "codex", max_turns=2)
        self.assertFalse(w2["rotated_for_context_bloat"])
        self.assertEqual(w1["id"], w2["id"])

        # Another tool ("claude") on the same lane has 0 turns and MUST NOT rotate because of codex's turns
        w_claude = ensure_fresh_lane_window(self.project, "VERIFY_AUDIT", "claude", max_turns=2)
        self.assertFalse(w_claude["rotated_for_context_bloat"])

        # 3rd turn on codex exceeds max_turns=2 -> automatically rotates codex to generation+1!
        w3 = ensure_fresh_lane_window(self.project, "VERIFY_AUDIT", "codex", max_turns=2)
        self.assertTrue(w3["rotated_for_context_bloat"])
        self.assertNotEqual(w1["id"], w3["id"])
        self.assertIn("MAX_TURNS_REACHED", w3["rotate_reason"])

        # M5 mutation guard: dispatch_single_lane_batch and handoff_lane_result MUST wire ensure_fresh_lane_window
        # (so when turns >= MAX_LANE_TURNS=12, dispatch and handoff rotate the window to generation+1).
        from v7_harness.coord.process_lanes import MAX_LANE_TURNS, lane_window_path
        mark(self.project, "claude", "ACTIVE")
        mark(self.project, "codex", "LIMITED")
        mark(self.project, "antigravity", "LIMITED")
        impl_init = open_or_reuse_lane_window(self.project, "IMPL_CODE", "claude")["id"]
        impl_rec_path = lane_window_path(self.project, "IMPL_CODE")
        impl_rec = json.loads(impl_rec_path.read_text(encoding="utf-8"))
        impl_rec["windows"]["claude"]["turns"] = MAX_LANE_TURNS
        impl_rec_path.write_text(json.dumps(impl_rec), encoding="utf-8")

        box = Mailbox(self.project / ".coord" / "mailbox")
        box.publish("msg_m5_1", {"kind": "IMPLEMENT", "actor": "codex", "card": "U292", "message": "M5 rotation check"})
        m5_items = collect_pending_processes(self.project)["IMPL_CODE"]
        m5_res = dispatch_single_lane_batch(
            self.project,
            "IMPL_CODE",
            m5_items,
            actor="antigravity",
            preferred_tool="claude",
            custom_sender=lambda lid, tool, wid, env, batch: {"ok": True, "reason": "SENT", "message_id": "m5_ok", "output": "ok"},
        )
        self.assertTrue(m5_res["rotated_for_context_bloat"], "dispatch_single_lane_batch must rotate bloated window (M5)")
        self.assertNotEqual(m5_res["window_id"], impl_init)

        stacked_relays = [
            {"message_id": "relay_1", "actor": "claude", "card": "U279", "verdict_requested": True, "message": "Audit U279 rev4"},
            {"message_id": "relay_2", "actor": "claude", "card": "U279", "verdict_requested": True, "message": "Audit U279 rev4"},
            {"message_id": "relay_3", "actor": "codex", "card": "U279", "message": "결과: 이미 수신 처리한 U279 개정 4의 REVISE 확인 통지입니다."},
            {"message_id": "relay_4", "actor": "antigravity", "card": "U287", "verdict_requested": True, "message": "Verify U287 lane mux"},
            {"message_id": "relay_5", "actor": "claude", "card": "U290", "kind": "IMPLEMENT", "message": "Implement U290 patch"},
            {"message_id": "relay_6", "actor": "claude", "card": "U290", "kind": "IMPLEMENT", "message": "Implement U290 tests"},
            {"message_id": "relay_7", "actor": "codex", "card": "U277", "kind": "BLOCKED", "p1_alert": True, "message": "Recover stall"},
            {"message_id": "relay_8", "actor": "claude", "card": "U289", "kind": "DESIGN", "message": "MIA Stage 3 design"},
        ]
        coalesced = coalesce_relays_by_lane(stacked_relays)
        self.assertEqual(set(coalesced.keys()), {"VERIFY_AUDIT", "IMPL_CODE", "RECOVERY_OPS", "ARCH_DESIGN"})
        self.assertEqual(coalesced["VERIFY_AUDIT"]["count"], 2)
        self.assertEqual(coalesced["IMPL_CODE"]["count"], 2)

    def test_echo_confirmation_storm_blocked_by_requires_wake_but_quoted_echo_still_wakes(self) -> None:
        """Unquoted echo confirmations return False in _requires_wake, but an actionable verdict quoting echo text still wakes."""
        from v7_harness.coord.deliver import _requires_wake

        self.assertFalse(_requires_wake("결과: 이미 수신 처리한 U279 개정 4의 REVISE 확인 통지입니다."))
        self.assertFalse(_requires_wake("결과: U279 개정 4의 추가 결함 수신 확인을 처리했습니다."))
        self.assertFalse(_requires_wake("Re relay_b7a795ae: your U290C PASS is recorded as advisory evidence."))
        self.assertTrue(_requires_wake("VERDICT REWORK U287: fix line 42"))
        # Quoted echo phrase inside a real ACTIONABLE_DELTA / VERDICT must NOT suppress the wake!
        self.assertTrue(
            _requires_wake('VERDICT: REVISE U292 — filter matched "이미 수신 처리한" inside quotes.')
        )

    def test_card_by_card_parallel_windows_and_3tool_rsi_upgrade_session_broadcast(self) -> None:
        """U292: Card-by-card parallel windows bind to classification lanes, and standalone RSI session records factual non-self-approved gate state."""
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
        self.assertEqual(rsi_res["code_gate"]["status"], "RECORDED_PENDING_JUDGE")
        self.assertFalse(rsi_res["code_gate"]["self_approved"])
        self.assertFalse(rsi_res["code_gate"]["rules_synced"], "PLAN.md alone must not mark rules_synced=True")
        rule_file = self.project / "uaos_everywhere" / "uaos_global_rule_block.md"
        rule_file.parent.mkdir(parents=True, exist_ok=True)
        rule_file.write_text("# arbitrary file mentioning UAOS-RSI v7.6.2\n", encoding="utf-8")
        rsi_unsynced = record_rsi_upgrade_session(
            self.project,
            session_id="U292-CARD-LANE-PARALLEL-WINDOWS-20261101",
            title="3-Tool Card & Process-Lane Parallel Window Execution OS Upgrade",
            summary_ko="카드별·분류별 병렬 대화창 가동 로직 3대 도구 전역 규칙 고정 및 실가동 완료.",
            rules_version="7.6.2",
            runtime_version="7.6.2-u292",
            actor="antigravity",
        )
        self.assertFalse(rsi_unsynced["code_gate"]["rules_synced"], "Substring 'UAOS-RSI' alone must not mark rules_synced=True")
        installed_canon = Path(__file__).resolve().parents[1] / "uaos_everywhere" / "uaos_global_rule_block.md"
        rule_file.write_bytes(installed_canon.read_bytes())
        rsi_synced = record_rsi_upgrade_session(
            self.project,
            session_id="U292-CARD-LANE-PARALLEL-WINDOWS-20261101",
            title="3-Tool Card & Process-Lane Parallel Window Execution OS Upgrade",
            summary_ko="카드별·분류별 병렬 대화창 가동 로직 3대 도구 전역 규칙 고정 및 실가동 완료.",
            rules_version="7.6.2",
            runtime_version="7.6.2-u292",
            actor="antigravity",
        )
        self.assertTrue(rsi_synced["code_gate"]["rules_synced"])
        self.assertTrue(Path(rsi_res["session_json"]).is_file())
        self.assertTrue(Path(rsi_res["report_md"]).is_file())

        latest = latest_rsi_upgrade_session(self.project)
        self.assertIsNotNone(latest)
        self.assertEqual(latest["session_id"], "U292-CARD-LANE-PARALLEL-WINDOWS-20261101")
        self.assertEqual(latest["global_rules_version"], "7.6.2")

        for tool in ("codex", "claude", "antigravity"):
            items = absence_items(self.project, before_ts, tool)
            self.assertTrue(
                any("rsi_session U292-CARD-LANE-PARALLEL-WINDOWS-20261101" in it for it in items),
                f"{tool} did not see rsi_session in absence_items: {items}",
            )

    def test_amp_probe_zero_compounding_under_all_limited(self) -> None:
        """Exact regression test for Claude's amp_probe/probe.py: 3 repeated multiplex calls under all-LIMITED tools must ack source and never compound inbox items."""
        for t in ("codex", "claude", "antigravity"):
            mark(self.project, t, "LIMITED", ttl_s=3600)
        box = Mailbox(self.project / ".coord" / "mailbox")
        box.publish("m1", {"kind": "NOTE", "actor": "codex", "message": "implement patch", "requested_target": "codex"})

        def _boom(*_a, **_k):
            raise RuntimeError("runner called")

        counts: list[int] = []
        with mock.patch("v7_harness.coord.ring.ring", lambda *_a, **_k: None, create=True):
            for _ in range(3):
                r = multiplex_and_dispatch_parallel(self.project, actor="antigravity", runner=_boom)
                counts.append(r["total_items"])

        self.assertEqual(counts, [1, 0, 0])
        peek_ids = [mid for mid, _ in box.peek()]
        self.assertIn("m1", peek_ids, "Source letter m1 must NOT be acked when delivery is QUEUED_UNTIL_ACTIVE")
        self.assertEqual(len(peek_ids), 2, "Inbox must contain only m1 + 1 queued batch envelope (no compounding)")


if __name__ == "__main__":
    unittest.main()
