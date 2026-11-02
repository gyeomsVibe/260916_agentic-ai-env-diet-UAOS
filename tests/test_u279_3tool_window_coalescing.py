"""U279: Lossless Topic-Window Transport & Two-Phase Window Pool Cap Tests.

Verifies the U279 Route Change & Claude REVISE requirements:
1. Screenshot reproduction (`media_1793113686297_bca5c8d9.png`): 10 `[agy-auto] ... ACK_ONLY` NOTICEs + 1 ACTIONABLE
   relay to Codex invoke `codex queue` exactly 1 time (0 queue spam for NOTICE/ACK_ONLY).
2. Synchronous per-message topic-window reuse across Codex, Claude Code, and Antigravity (`U275-R1`, `U275-R8-L1`,
   `PR244-U275`, `U275_VERDICT` -> single `[U275]` window in `.coord/windows.json` and `.coord/windows/U275.json`) with
   zero deferred burst buffering (`1 message = 1 delivery/accepted/<mid>.json` and `1 .coord/mailbox/ack/<mid>.json`).
3. Two-Phase Window Pool Cap (`MAX_ACTIVE_WINDOWS_PER_TOOL = 3`) in `v7_harness/coord/windows.py`:
   - Phase 1 (short lock `pool_<tool>` -> `card_<card>`, no subprocess launch): reuses `ACTIVE` window or prunes dead
     PIDs, evicts oldest LRU `ACTIVE` window with `in_flight_leases == {}`, writes `state="RESERVING"`,
     `reserving_pid=os.getpid()`, `reservation_id=<uuid4_hex>`, and releases `pool_<tool>` before remote launch.
   - Phase 2 (remote launch outside `pool_<tool>` lock): slow launches never block concurrent operations on other cards.
   - Phase 3 (finalize under `card_<card>` lock): transitions `RESERVING` to `state="ACTIVE"` on success or
     `state="RELEASED"` (`release_reason="launch_failed"`) on failure.
   - When all 3 slots have live `in_flight_leases` or live `RESERVING` PIDs, fails closed with
     `WINDOW_POOL_EXHAUSTED_IN_FLIGHT` (or raises `WindowPoolExhaustedError` when `raise_on_exhausted=True`).
4. Context-bloat rotation at `RESUME_MAX_INPUT = 70_000` tokens (`TOKEN_CAP_ROTATED`).
5. Non-windowed card letters share the single default `claude-session.json` (P2-2 fix), while active card windows use
   per-topic turn locks in parallel and durably persist failover UUIDs (`failover_id` / `window_id`) into
   `.coord/windows/<card>.json` and `.coord/windows.json` (P2-3 fix).
6. Dead-PID-safe `_recover_dead_dispatcher` in `v7_harness/coord/agy_dispatch.py`: bounded `_recover_lock(guard, 0.2)`,
   `_pid_is_definitely_dead(pid)` (`OpenProcess` returning `0` treats only `ERROR_INVALID_PARAMETER = 87` as dead, never
   `ERROR_ACCESS_DENIED = 5`), and never unlinks empty or malformed guard files.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from v7_harness.coord import agy_dispatch, presence
from v7_harness.coord.deliver import _project_mailbox, _recover_dead_dispatcher, deliver
from v7_harness.coord.windows import (
    MAX_ACTIVE_WINDOWS_PER_TOOL,
    RESUME_MAX_INPUT,
    WindowPoolExhaustedError,
    _pid_is_definitely_dead,
    acquire_topic_window,
    acquire_window_lease,
    active_topic_windows,
    normalize_topic_key,
    open_window,
    record_window,
    release_window_lease,
    set_window_in_flight,
    window_entry,
    window_for,
    window_for_topic,
)


class _FakeRunner:
    def __init__(self):
        self.calls: list[list[str]] = []

    def __call__(self, argv, **_kwargs):
        self.calls.append(list(argv))
        return SimpleNamespace(returncode=0, stdout=json.dumps({"result": "ok"}), stderr="")


class TestU279ThreeToolWindowCoalescing(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        self.sessions = Path(self._tmp.name) / "codex-sessions"
        self.sessions.mkdir()
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(self.sessions)})
        self._env.start()
        self.addCleanup(self._env.stop)
        self._which = mock.patch("v7_harness.coord.deliver.shutil.which", side_effect=lambda name: name)
        self._which.start()
        self.addCleanup(self._which.stop)
        presence.mark(self.project, "codex", "ACTIVE")
        presence.mark(self.project, "claude", "ACTIVE")
        presence.mark(self.project, "antigravity", "ACTIVE")

    def _register_codex_rollout(self, thread_id: str) -> None:
        day = self.sessions / "2026" / "10" / "28"
        day.mkdir(parents=True, exist_ok=True)
        rollout = day / f"rollout-2026-10-28T00-00-00-{thread_id}.jsonl"
        rollout.write_text(
            json.dumps({
                "type": "session_meta",
                "payload": {"id": thread_id, "session_id": thread_id, "cwd": str(self.project)},
            }) + "\n",
            encoding="utf-8",
        )

    def test_1_screenshot_reproduction_10_ack_only_notices_never_spam_codex_queue(self):
        """Reproduce `media_1793113686297_bca5c8d9.png`: 10 `[agy-auto] ... ACK_ONLY` NOTICEs + 1 ACTIONABLE relay."""
        desk_thread = "01a17dde-9866-7301-8f77-b9290f615f69"
        self._register_codex_rollout(desk_thread)
        runner = _FakeRunner()

        for i in range(10):
            res = deliver(
                self.project,
                message=f"[agy-auto] re relay_req_{i}: Noted — ACK_ONLY (verdict_requested=no).",
                actor="antigravity",
                target="codex",
                thread=desk_thread,
                runner=runner,
                wake_class="NOTICE",
                verdict_requested=False,
            )
            self.assertIn(res.reason, ("QUEUED_ACK_ONLY", "QUEUED_NOTICE"))
            self.assertFalse(res.delivered)

        actionable = deliver(
            self.project,
            message="[CODEX-RETURN] ACTIONABLE_DELTA VERDICT_REQUESTED=YES: inspect U276 bundle",
            actor="antigravity",
            target="codex",
            thread=desk_thread,
            runner=runner,
            card="CODEX-RETURN",
            wake_class="ACTIONABLE",
            verdict_requested=True,
            delta="inspect U276 bundle",
        )
        self.assertEqual("DISPATCHED", actionable.reason)
        self.assertEqual(1, len(runner.calls))
        self.assertIn("queue", runner.calls[0])

    def test_2_topic_grouping_reuses_same_window_across_all_3_tools_and_syncs_windows_json(self):
        """Related sub-cards (`U275-R1`, `U275-R8-L1`, `PR244-U275`, `U275_VERDICT`) map to canonical `U275`."""
        for subcard in ("U275", "U275-R1", "U275-R8-L1", "PR244-U275", "U275_VERDICT", "RSI-U275-FIX"):
            self.assertEqual("U275", normalize_topic_key(subcard), subcard)
        self.assertEqual("DESK-SYNC", normalize_topic_key("CODEX-RETURN"))
        self.assertEqual("DESK-SYNC", normalize_topic_key("DESK-261028-1"))
        self.assertEqual("RSI-ALPHA", normalize_topic_key("RSI-ALPHA"))
        self.assertEqual("REVIEW-BETA", normalize_topic_key("REVIEW-BETA"))

        codex_tid = "0199aaaa-0000-7000-8000-000000000275"
        claude_sid = "27500000-0000-4000-8000-000000000275"
        agy_cid = "conv-u275-shared"
        self._register_codex_rollout(codex_tid)

        record_window(self.project, "U275", "codex", codex_tid, now=100.0)
        record_window(self.project, "U275", "claude", claude_sid, now=100.0)
        record_window(self.project, "U275", "antigravity", agy_cid, now=100.0, last_input_tokens=24_000)

        # Verify `.coord/windows.json` is durably populated alongside `.coord/windows/U275.json`
        reg = json.loads((self.project / ".coord" / "windows.json").read_text(encoding="utf-8"))
        self.assertEqual(codex_tid, reg["cards"]["U275"]["tools"]["codex"]["id"])
        self.assertEqual(claude_sid, reg["cards"]["U275"]["tools"]["claude"]["id"])
        self.assertEqual(agy_cid, reg["cards"]["U275"]["tools"]["antigravity"]["id"])

        for sub in ("U275-R1", "U275-R8-L1", "PR244-U275"):
            self.assertEqual(codex_tid, window_for(self.project, sub, "codex"))
            self.assertEqual(claude_sid, window_for(self.project, sub, "claude"))
            self.assertEqual(agy_cid, window_for(self.project, sub, "antigravity"))
            self.assertEqual(codex_tid, window_for_topic(self.project, sub, "codex"))

        desk_tid = "0199bbbb-0000-7000-8000-000000000999"
        self._register_codex_rollout(desk_tid)
        runner = _FakeRunner()
        res = deliver(
            self.project,
            message="ACTIONABLE_DELTA verdict_requested=yes: U275-R8-L1 check",
            actor="claude",
            target="codex",
            thread=desk_tid,
            runner=runner,
            card="U275-R8-L1",
        )
        self.assertEqual("DISPATCHED", res.reason)
        self.assertEqual(codex_tid, runner.calls[0][runner.calls[0].index("--thread") + 1])

        agy_calls = []

        def agy_runner(argv, **_kwargs):
            agy_calls.append(list(argv))
            if Path(argv[0]).stem == "agy":
                env = {
                    "status": "SUCCESS",
                    "conversation_id": agy_cid,
                    "usage": {"input_tokens": 38_000, "output_tokens": 400},
                    "response": "VERDICT: PASS subcard verified.",
                }
                return SimpleNamespace(returncode=0, stdout=json.dumps(env).encode("utf-8"), stderr=b"")
            return SimpleNamespace(returncode=0, stdout=json.dumps({"result": "ok"}), stderr="")

        row = agy_dispatch.dispatch(
            self.project,
            message_id="relay_subcard_u275_r8",
            actor="claude",
            message="Please audit U275-R8-L1",
            runner=agy_runner,
            card="U275-R8-L1",
            audit=True,
        )
        self.assertEqual("ANSWERED", row["state"])
        self.assertIn("--conversation", agy_calls[0])
        self.assertEqual(agy_cid, agy_calls[0][agy_calls[0].index("--conversation") + 1])
        self.assertEqual(38_000, window_entry(self.project, "U275", "antigravity")["last_input_tokens"])

    def test_3_synchronous_per_message_dispatch_without_deferred_burst_buffering(self):
        """Route Change: Every `coord deliver` call dispatches immediately through the single-message durable path
        (`1 message = 1 delivery/accepted/<mid>.json` and `1 .coord/mailbox/ack/<mid>.json` on `coord ack --id`)."""
        topic_tid = "0199cccc-0000-7000-8000-000000000275"
        self._register_codex_rollout(topic_tid)
        record_window(self.project, "U275", "codex", topic_tid, now=10.0)
        runner = _FakeRunner()
        box = _project_mailbox(self.project)
        wt_root = str(Path(__file__).resolve().parents[1])

        r1 = deliver(
            self.project,
            message="ACTIONABLE_DELTA: U275 slice 1 ready",
            actor="claude",
            target="codex",
            runner=runner,
            card="U275-R1",
        )
        r2 = deliver(
            self.project,
            message="ACTIONABLE_DELTA: U275 slice 2 ready",
            actor="antigravity",
            target="codex",
            runner=runner,
            card="U275-R2",
        )
        self.assertEqual("DISPATCHED", r1.reason)
        self.assertEqual("DISPATCHED", r2.reason)
        self.assertEqual(2, len(runner.calls))
        for idx, res in enumerate((r1, r2)):
            self.assertEqual(topic_tid, runner.calls[idx][runner.calls[idx].index("--thread") + 1])
            self.assertTrue((box.root / "delivery" / "accepted" / f"{res.message_id}.json").is_file())
            self.assertTrue((box.inbox_dir / f"{res.message_id}.json").is_file())
            cli_ack = subprocess.run(
                [sys.executable, "-m", "v7_harness.cli", "coord", "ack", "--id", res.message_id],
                cwd=str(self.project),
                env={**os.environ, "PYTHONPATH": wt_root},
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(0, cli_ack.returncode, cli_ack.stderr)
            self.assertTrue((box.ack_dir / f"{res.message_id}.json").is_file())

    def test_4_two_phase_window_pool_cap_evicts_lru_and_rotates_at_70k_tokens(self):
        """Two-Phase Pool Cap (`MAX_ACTIVE_WINDOWS_PER_TOOL = 3`) evicts oldest idle LRU window and rotates at 70k."""
        created_threads = iter([
            "01990000-0000-7000-8000-000000000001",
            "01990000-0000-7000-8000-000000000002",
            "01990000-0000-7000-8000-000000000003",
            "01990000-0000-7000-8000-000000000004",
        ])

        def fake_rpc(method: str, _params: dict) -> dict:
            if method == "thread/start":
                return {"thread": {"id": next(created_threads)}}
            return {}

        w1 = acquire_topic_window(self.project, "U271-R1", "codex", "t1", "p1", rpc=fake_rpc, now=10.0)
        w2 = acquire_topic_window(self.project, "U272-R1", "codex", "t2", "p2", rpc=fake_rpc, now=20.0)
        w3 = acquire_topic_window(self.project, "U273-R1", "codex", "t3", "p3", rpc=fake_rpc, now=30.0)
        self.assertFalse(w1["reused"])
        self.assertFalse(w2["reused"])
        self.assertFalse(w3["reused"])
        self.assertEqual("ACTIVE", w1["state"])

        w1_reuse = acquire_topic_window(self.project, "U271-R2", "codex", "t1", "p1b", rpc=fake_rpc, now=40.0)
        self.assertTrue(w1_reuse["reused"])
        self.assertEqual(w1["id"], w1_reuse["id"])
        self.assertIn("U271-R2", w1_reuse["subcards"])
        self.assertEqual(3, len(active_topic_windows(self.project, "codex")))

        # U272 (last_active_at=20.0) is the oldest idle LRU window; opening U274 evicts U272 in Phase 1
        w4 = acquire_topic_window(self.project, "U274", "codex", "t4", "p4", rpc=fake_rpc, now=50.0)
        self.assertFalse(w4["reused"])
        self.assertEqual(["U272"], w4.get("evicted_lru"))
        active = active_topic_windows(self.project, "codex")
        self.assertEqual(MAX_ACTIVE_WINDOWS_PER_TOOL, len(active))
        self.assertEqual({"U271", "U273", "U274"}, {item["card"] for item in active})
        u272_entry = window_entry(self.project, "U272", "codex")
        self.assertEqual("RELEASED", u272_entry.get("state"))
        self.assertEqual("POOL_CAP_LRU_EVICTED", u272_entry.get("released_reason"))

        w5 = acquire_topic_window(
            self.project, "U275", "codex", "t5", "p5", rpc=fake_rpc, now=60.0, overflow_policy="share_least_loaded"
        )
        self.assertTrue(w5["reused"])
        self.assertIn(w5["shared_from"], {"U271", "U273", "U274"})

        # Context-bloat rotation at `RESUME_MAX_INPUT = 70_000`
        convs = iter([("conv-u276-first", 72_000), ("conv-u276-rotated", 21_000)])

        def fake_agy_runner(*_args, **_kwargs):
            cid, tok = next(convs)
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"conversation_id": cid, "usage": {"input_tokens": tok}}),
                stderr="",
            )

        first = acquire_topic_window(self.project, "U276-R1", "antigravity", "title", "prompt", runner=fake_agy_runner, now=10.0)
        self.assertEqual("conv-u276-first", first["id"])
        self.assertEqual(72_000, first["last_input_tokens"])
        second = acquire_topic_window(self.project, "U276-R2", "antigravity", "title", "prompt", runner=fake_agy_runner, now=20.0)
        self.assertFalse(second["reused"])
        self.assertEqual("conv-u276-rotated", second["id"])
        self.assertEqual("conv-u276-first", second["rotated_from"])
        self.assertEqual(21_000, second["last_input_tokens"])

    def test_5_two_phase_launch_outside_pool_lock_and_launch_failure_releases_slot(self):
        """Phase 2 runs `_open_antigravity` outside `pool_<tool>` lock so concurrent operations on other cards are never
        blocked during subprocess startup; Phase 3 marks `state='RELEASED'` (`release_reason='launch_failed'`) on failure."""
        launch_entered = threading.Event()
        allow_finish = threading.Event()
        observed_reserving: dict[str, object] = {}

        def slow_agy_runner(*_a, **_k):
            # Inside Phase 2, `U501` must be in `RESERVING` state with `reserving_pid == os.getpid()` and `reservation_id`
            raw_u501 = json.loads((self.project / ".coord" / "windows" / "U501.json").read_text(encoding="utf-8"))
            observed_reserving.update(raw_u501["tools"]["antigravity"])
            launch_entered.set()
            allow_finish.wait(timeout=5.0)
            return SimpleNamespace(returncode=0, stdout='{"conversation_id":"conv-501"}', stderr="")

        t_slow = threading.Thread(
            target=lambda: acquire_topic_window(
                self.project, "U501", "antigravity", "t501", "p501", runner=slow_agy_runner, now=60.0, max_active=3
            )
        )
        t_slow.start()
        self.assertTrue(launch_entered.wait(timeout=3.0))
        self.assertEqual("RESERVING", observed_reserving.get("state"))
        self.assertEqual(os.getpid(), observed_reserving.get("reserving_pid"))
        self.assertTrue(observed_reserving.get("reservation_id"))

        # While `U501` is blocked inside Phase 2 remote launch, acquiring another slot `U502` on the SAME tool
        # (`antigravity`) must NOT block on `pool_antigravity`!
        t0 = time.monotonic()
        fast_res = acquire_topic_window(
            self.project,
            "U502",
            "antigravity",
            "t502",
            "p502",
            runner=lambda *_a, **_k: SimpleNamespace(returncode=0, stdout='{"conversation_id":"conv-502"}', stderr=""),
            now=61.0,
            max_active=3,
        )
        elapsed_same_tool = time.monotonic() - t0
        allow_finish.set()
        t_slow.join(timeout=5.0)

        self.assertEqual("ACTIVE", fast_res.get("state"))
        self.assertLess(elapsed_same_tool, 0.5, "Phase 2 remote launch held pool_<tool> lock and blocked U502!")
        self.assertEqual("ACTIVE", window_entry(self.project, "U501", "antigravity").get("state"))

        # Verify Phase 3 launch failure transitions RESERVING -> RELEASED (`release_reason="launch_failed"`)
        # AND when pool is at capacity (3/3 active: U501, U502, U504), a Phase-2 launch failure on U505 restores
        # the LRU victim (U501) back to ACTIVE instead of losing it!
        acquire_topic_window(
            self.project,
            "U504",
            "antigravity",
            "t504",
            "p504",
            runner=lambda *_a, **_k: SimpleNamespace(returncode=0, stdout='{"conversation_id":"conv-504"}', stderr=""),
            now=65.0,
            max_active=3,
        )
        self.assertEqual(["U501", "U502", "U504"], [w["card"] for w in active_topic_windows(self.project, "antigravity")])

        def failing_runner(*_a, **_k):
            raise RuntimeError("agy subprocess failed")

        with self.assertRaises(RuntimeError):
            acquire_topic_window(
                self.project, "U503", "antigravity", "t503", "p503", runner=failing_runner, now=70.0, max_active=3
            )
        failed_entry = window_entry(self.project, "U503", "antigravity")
        self.assertEqual("RELEASED", failed_entry.get("state"))
        self.assertEqual("launch_failed", failed_entry.get("release_reason"))
        # LRU victim U501 must be restored to ACTIVE after U503's Phase-2 launch failed!
        self.assertEqual("ACTIVE", window_entry(self.project, "U501", "antigravity").get("state"))
        self.assertEqual("conv-501", window_for(self.project, "U501", "antigravity"))
        self.assertEqual(["U501", "U502", "U504"], [w["card"] for w in active_topic_windows(self.project, "antigravity")])

    def test_6_in_flight_leases_and_dead_pid_pruning_and_pool_exhausted_fail_closed(self):
        """Dead-PID leases and dead-PID RESERVING slots are pruned automatically, while live `in_flight_leases`
        prevent LRU eviction and fail closed with `WINDOW_POOL_EXHAUSTED_IN_FLIGHT`."""
        # Populate 3 active windows for `antigravity`
        for idx, cid in enumerate(("U401", "U402", "U403"), start=1):
            record_window(self.project, cid, "antigravity", f"conv-{cid}", now=float(idx), topic_key=cid)

        # Acquire live leases on all 3 windows
        l1 = acquire_window_lease(self.project, "U401", "antigravity", now=10.0)
        l2 = acquire_window_lease(self.project, "U402", "antigravity", now=11.0)
        l3 = acquire_window_lease(self.project, "U403", "antigravity", now=12.0)
        self.assertTrue(l1 and l2 and l3)

        # All 3 slots have live in-flight leases -> 4th window fails closed with `WINDOW_POOL_EXHAUSTED_IN_FLIGHT`
        exhausted = acquire_topic_window(
            self.project,
            "U404",
            "antigravity",
            "t404",
            "p404",
            runner=lambda *_a, **_k: SimpleNamespace(returncode=0, stdout='{"conversation_id":"conv-404"}', stderr=""),
            now=50.0,
            max_active=3,
        )
        self.assertEqual("WINDOW_POOL_EXHAUSTED_IN_FLIGHT", exhausted.get("refused"))
        with self.assertRaises(WindowPoolExhaustedError):
            acquire_topic_window(
                self.project,
                "U404",
                "antigravity",
                "t404",
                "p404",
                runner=lambda *_a, **_k: SimpleNamespace(returncode=0, stdout='{"conversation_id":"conv-404"}', stderr=""),
                now=50.0,
                max_active=3,
                raise_on_exhausted=True,
            )

        # Spawn a real short-lived child process that acquires a lease on `U401` and exits without releasing it
        wt_root = str(Path(__file__).resolve().parents[1])
        release_window_lease(self.project, "U401", "antigravity", l1)
        child_lease_code = (
            "import sys; "
            f"sys.path.insert(0, {wt_root!r}); "
            "from pathlib import Path; "
            "from v7_harness.coord.windows import acquire_window_lease; "
            f"acquire_window_lease(Path({str(self.project)!r}), 'U401', 'antigravity', lease_id='dead-child-lease')"
        )
        cp = subprocess.run([sys.executable, "-c", child_lease_code], capture_output=True, text=True, timeout=10)
        self.assertEqual(0, cp.returncode, cp.stderr)

        # Now `U401` has a lease owned by a dead PID! `acquire_topic_window` for `U404` must prune `U401`'s dead-PID
        # lease and evict `U401` cleanly!
        opened_u404 = acquire_topic_window(
            self.project,
            "U404",
            "antigravity",
            "t404",
            "p404",
            runner=lambda *_a, **_k: SimpleNamespace(returncode=0, stdout='{"conversation_id":"conv-404"}', stderr=""),
            now=60.0,
            max_active=3,
        )
        self.assertEqual("ACTIVE", opened_u404.get("state"))
        self.assertEqual(["U401"], opened_u404.get("evicted_lru"))
        release_window_lease(self.project, "U402", "antigravity", l2)
        release_window_lease(self.project, "U403", "antigravity", l3)

    def test_7_non_windowed_claude_shares_session_and_failover_persists_window_id(self):
        """(P2-2) Non-windowed card letters reuse `claude-session.json` without per-card session sharding.
        (P2-3) Active card windows run in parallel under `claude-topic-<topic>.turn.lock` and persist failover IDs."""
        runner = _FakeRunner()
        r1 = deliver(
            self.project,
            message="ACTIONABLE_DELTA verdict_requested=yes: check U280",
            actor="codex",
            target="claude",
            runner=runner,
            card="U280-R1",
        )
        r2 = deliver(
            self.project,
            message="ACTIONABLE_DELTA verdict_requested=yes: check U281",
            actor="codex",
            target="claude",
            runner=runner,
            card="U281-R1",
        )
        self.assertEqual("DISPATCHED", r1.reason)
        self.assertEqual("DISPATCHED", r2.reason)
        deliv_dir = self.project / ".coord" / "mailbox" / "delivery"
        self.assertTrue((deliv_dir / "claude-session.json").is_file())
        self.assertFalse((deliv_dir / "claude-session-U280.json").exists())
        self.assertFalse((deliv_dir / "claude-session-U281.json").exists())

        # Parallel Claude card windows (`U276` vs `U277`)
        record_window(self.project, "U276", "claude", "27600000-0000-4000-8000-000000000276", now=10.0, topic_key="U276")
        record_window(self.project, "U277", "claude", "27700000-0000-4000-8000-000000000277", now=10.0, topic_key="U277")
        barrier = threading.Barrier(2, timeout=5.0)
        overlap_proved = {"ok": False}

        def parallel_claude_runner(_argv, **_kwargs):
            barrier.wait()
            overlap_proved["ok"] = True
            return SimpleNamespace(returncode=0, stdout=json.dumps({"result": "ok"}), stderr="")

        results: list[str] = []

        def send_topic(card_name: str):
            res = deliver(
                self.project,
                message=f"ACTIONABLE_DELTA verdict_requested=yes: work on {card_name}",
                actor="codex",
                target="claude",
                runner=parallel_claude_runner,
                card=card_name,
            )
            results.append(res.reason)

        t1 = threading.Thread(target=send_topic, args=("U276-R1",))
        t2 = threading.Thread(target=send_topic, args=("U277-R1",))
        t1.start()
        t2.start()
        t1.join(timeout=10.0)
        t2.join(timeout=10.0)
        self.assertTrue(overlap_proved["ok"])
        self.assertEqual(["DISPATCHED", "DISPATCHED"], results)

        # Verify automatic failover when a recorded Claude card window is "already in use" persists into windows.json!
        busy_sid = "11111111-2222-4333-8444-555555555555"
        record_window(self.project, "U278", "claude", busy_sid, now=10.0)
        retry_calls: list[list[str]] = []

        def busy_then_ok_runner(argv, **_kwargs):
            retry_calls.append(list(argv))
            if len(retry_calls) == 1:
                return SimpleNamespace(returncode=1, stdout="", stderr=f"Error: Session ID {busy_sid} is already in use.")
            return SimpleNamespace(returncode=0, stdout=json.dumps({"result": "recovered"}), stderr="")

        recovered = deliver(
            self.project,
            message="ACTIONABLE_DELTA verdict_requested=yes: U278 urgent check",
            actor="codex",
            target="claude",
            runner=busy_then_ok_runner,
            card="U278-R1",
        )
        self.assertEqual("DISPATCHED", recovered.reason)
        self.assertEqual(2, len(retry_calls))
        new_sid = retry_calls[1][retry_calls[1].index("--session-id") + 1]
        self.assertNotEqual(busy_sid, new_sid)
        self.assertEqual(new_sid, window_for(self.project, "U278", "claude"))
        u278_entry = window_entry(self.project, "U278", "claude")
        self.assertEqual(busy_sid, u278_entry.get("failover_from"))
        self.assertEqual(new_sid, u278_entry.get("failover_id"))
        self.assertEqual(new_sid, u278_entry.get("window_id"))
        reg = json.loads((self.project / ".coord" / "windows.json").read_text(encoding="utf-8"))
        self.assertEqual(new_sid, reg["cards"]["U278"]["tools"]["claude"]["id"])

    def test_8_parallel_acquire_topic_window_enforces_cap_and_refused_open_preserves_victims(self):
        """Truly parallel `acquire_topic_window` calls across 6 threads never exceed `MAX_ACTIVE_WINDOWS_PER_TOOL = 3`,
        and a refused open never evicts existing windows."""
        rpc_lock = threading.Lock()
        seq = {"n": 0}

        def thread_safe_rpc(method: str, _params: dict) -> dict:
            if method == "thread/start":
                with rpc_lock:
                    seq["n"] += 1
                    idx = seq["n"]
                time.sleep(0.01)
                return {"thread": {"id": f"0199eeee-0000-7000-8000-{idx:012d}"}}
            return {}

        barrier = threading.Barrier(6, timeout=5.0)
        errors: list[Exception] = []

        def worker(i: int) -> None:
            try:
                barrier.wait()
                acquire_topic_window(
                    self.project,
                    f"U30{i}",
                    "codex",
                    f"title-{i}",
                    f"prompt-{i}",
                    rpc=thread_safe_rpc,
                    now=100.0 + i,
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(1, 7)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        self.assertEqual([], errors)
        active = active_topic_windows(self.project, "codex")
        self.assertEqual(MAX_ACTIVE_WINDOWS_PER_TOOL, len(active), f"Active pool exceeded cap: {active}")

        before_cards = {item["card"] for item in active}
        presence.mark(self.project, "codex", "LIMITED")
        refused = acquire_topic_window(self.project, "U399", "codex", "t99", "p99", rpc=thread_safe_rpc, now=200.0)
        self.assertEqual("LIMITED", refused.get("refused"))
        after_cards = {item["card"] for item in active_topic_windows(self.project, "codex")}
        self.assertEqual(before_cards, after_cards, "Refused open evicted active windows!")
        presence.mark(self.project, "codex", "ACTIVE")

    def test_9_dead_pid_safe_recover_dead_dispatcher_and_overlapping_in_flight(self):
        """`_recover_dead_dispatcher` in `agy_dispatch.py`:
        (1) Never deletes empty or malformed guard files.
        (2) On Windows, `OpenProcess` returning `0` treats ONLY `ERROR_INVALID_PARAMETER = 87` as dead, never
            `ERROR_ACCESS_DENIED = 5`.
        (3) Multiprocess barrier: never steals a live child process's guard/claim, and recovers it once the child exits.
        (4) Overlapping `set_window_in_flight` turns preserve `in_flight=True` until all turns finish, and same-card
            `open_window` launches only once."""
        box = _project_mailbox(self.project)
        guards_dir = box.root / "delivery" / "guards"
        guards_dir.mkdir(parents=True, exist_ok=True)

        # (1) Empty or malformed guard is NEVER unlinked
        empty_mid = "relay_empty_guard_race_test"
        empty_guard = guards_dir / f"{empty_mid}.lock"
        empty_guard.write_text("", encoding="utf-8")
        self.assertFalse(_recover_dead_dispatcher(box, empty_mid))
        self.assertTrue(empty_guard.is_file())
        empty_guard.write_text("{corrupt-json", encoding="utf-8")
        self.assertFalse(_recover_dead_dispatcher(box, empty_mid))
        self.assertTrue(empty_guard.is_file())
        empty_guard.unlink(missing_ok=True)

        # (2) Windows OpenProcess error codes
        if os.name == "nt":
            with mock.patch("ctypes.WinDLL") as m_dll:
                fake_k32 = mock.MagicMock()
                fake_k32.OpenProcess.return_value = 0
                m_dll.return_value = fake_k32
                with mock.patch("ctypes.get_last_error", return_value=5):  # ERROR_ACCESS_DENIED
                    self.assertFalse(_pid_is_definitely_dead(99999))
                with mock.patch("ctypes.get_last_error", return_value=87):  # ERROR_INVALID_PARAMETER
                    self.assertTrue(_pid_is_definitely_dead(99999))

        # (3) Multiprocess barrier test for `_recover_dead_dispatcher`
        mp_mid = "relay_mp_barrier_guard_test"
        ready_flag = self.project / "mp_guard_ready.flag"
        release_flag = self.project / "mp_guard_release.flag"
        wt_root = str(Path(__file__).resolve().parents[1])
        child_guard_code = (
            "import json, os, sys, time; "
            f"sys.path.insert(0, {wt_root!r}); "
            "from pathlib import Path; "
            "from v7_harness.coord.deliver import _project_mailbox; "
            f"proj = Path({str(self.project)!r}); "
            "box = _project_mailbox(proj); "
            f"mid = {mp_mid!r}; "
            "box.publish(mid, {'kind': 'HANDOFF', 'actor': 'claude', 'message': 'live', 'digest': 'd1', 'requested_target': 'codex'}); "
            "claim = box.claim(mid, 'dispatcher'); "
            "guard = box.root / 'delivery' / 'guards' / f'{mid}.lock'; "
            "guard.parent.mkdir(parents=True, exist_ok=True); "
            "guard.write_text(json.dumps({'message_id': mid, 'pid': os.getpid(), 'owner': 'child'}), encoding='utf-8'); "
            f"Path({str(ready_flag)!r}).write_text('1', encoding='utf-8'); "
            "t_end = time.monotonic() + 5.0; "
            f"[time.sleep(0.01) for _ in range(500) if time.monotonic() < t_end and not Path({str(release_flag)!r}).is_file()]"
        )
        proc = subprocess.Popen(
            [sys.executable, "-c", child_guard_code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        try:
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and not ready_flag.is_file():
                time.sleep(0.01)
            self.assertTrue(ready_flag.is_file())
            self.assertFalse(_recover_dead_dispatcher(box, mp_mid))
            self.assertTrue((guards_dir / f"{mp_mid}.lock").is_file())
            self.assertFalse((box.inbox_dir / f"{mp_mid}.json").is_file())
        finally:
            release_flag.write_text("1", encoding="utf-8")
            proc.communicate(timeout=5.0)
        self.assertTrue(_recover_dead_dispatcher(box, mp_mid))
        self.assertTrue((box.inbox_dir / f"{mp_mid}.json").is_file())

        # (4) Overlapping `set_window_in_flight` turns and simultaneous same-card `open_window`
        record_window(self.project, "U802", "antigravity", "conv-802", now=10.0, topic_key="U802")
        set_window_in_flight(self.project, "U802-R1", "antigravity", True)
        set_window_in_flight(self.project, "U802-R2", "antigravity", True)
        self.assertEqual(2, window_entry(self.project, "U802", "antigravity").get("in_flight_count"))
        self.assertTrue(window_entry(self.project, "U802", "antigravity").get("in_flight"))
        set_window_in_flight(self.project, "U802-R1", "antigravity", False)
        self.assertEqual(1, window_entry(self.project, "U802", "antigravity").get("in_flight_count"))
        self.assertTrue(window_entry(self.project, "U802", "antigravity").get("in_flight"))
        set_window_in_flight(self.project, "U802-R2", "antigravity", False)
        self.assertEqual(0, window_entry(self.project, "U802", "antigravity").get("in_flight_count"))
        self.assertFalse(window_entry(self.project, "U802", "antigravity").get("in_flight"))

        same_card_calls = []
        same_lock = threading.Lock()
        b_same = threading.Barrier(2, timeout=5.0)

        def same_card_runner(argv, **_kw):
            with same_lock:
                same_card_calls.append(list(argv))
            time.sleep(0.03)
            return SimpleNamespace(returncode=0, stdout='{"conversation_id":"conv-u601-once","usage":{"input_tokens":1200}}', stderr="")

        same_results = []

        def call_open():
            b_same.wait()
            same_results.append(open_window(self.project, "U601", "antigravity", "t601", "p601", runner=same_card_runner, now=10.0))

        th1 = threading.Thread(target=call_open)
        th2 = threading.Thread(target=call_open)
        th1.start()
        th2.start()
        th1.join(timeout=5.0)
        th2.join(timeout=5.0)
        self.assertEqual(1, len(same_card_calls))
        self.assertEqual({False, True}, {r["reused"] for r in same_results})

    def test_10_post_success_bookkeeping_lock_timeout_never_loses_paid_turn_or_causes_redispatch(self):
        """P2-1 regression test:
        - Probe A: `release_window_lease` raises `TimeoutError('WINDOW_LOCK_TIMEOUT:card_U301')` after runner succeeds:
          `turns_run == 1`, `accepted == 1`, `reason == 'DISPATCHED'`, `WINDOW_BOOKKEEPING_FAILED` receipt written,
          and a second `deliver()` call returns `DISPATCHED` without running the runner a second time.
        - Probe B: Claude failover `record_window` raises `TimeoutError('WINDOW_LOCK_TIMEOUT:card_U302')` after retry
          succeeds: `turns_run == 2`, `accepted == 1`, `reason == 'DISPATCHED'` (never `DELIVERY_FAILED`),
          `WINDOW_BOOKKEEPING_FAILED` receipt written.
        - Probe C: `agy_dispatch` `release_window_lease` and `record_window` raise `TimeoutError` after a paid turn:
          the paid answer is kept (`_replay` exists, ledger state is `ANSWERED`), never lost!
        - Pre-dispatch `acquire_window_lease` timeout returns structured `WINDOW_LOCK_TIMEOUT` refusal without crashing."""
        box = _project_mailbox(self.project)
        accepted_dir = box.root / "delivery" / "accepted"
        attempts_dir = box.root / "delivery" / "attempts"

        # ── Probe A: `release_window_lease` raises `TimeoutError` after successful turn ──
        u301_tid = "01993010-0000-7000-8000-000000000301"
        self._register_codex_rollout(u301_tid)
        record_window(self.project, "U301", "codex", u301_tid, now=10.0)
        runner_a = _FakeRunner()
        msg_a = "ACTIONABLE_DELTA verdict_requested=yes: U301 probe A"
        with mock.patch(
            "v7_harness.coord.windows.release_window_lease",
            side_effect=TimeoutError("WINDOW_LOCK_TIMEOUT:card_U301"),
        ):
            res_a = deliver(
                self.project,
                message=msg_a,
                actor="claude",
                target="codex",
                runner=runner_a,
                card="U301-R1",
            )
        self.assertEqual("DISPATCHED", res_a.reason)
        self.assertEqual(1, len(runner_a.calls))
        self.assertTrue((accepted_dir / f"{res_a.message_id}.json").is_file())
        # Verify `WINDOW_BOOKKEEPING_FAILED` attempt receipt was recorded
        attempt_states_a = [
            json.loads(p.read_text(encoding="utf-8")).get("state")
            for p in attempts_dir.glob(f"{res_a.message_id}_*.json")
        ]
        self.assertIn("DISPATCHED", attempt_states_a)
        self.assertIn("WINDOW_BOOKKEEPING_FAILED", attempt_states_a)
        # Re-calling `deliver` with the same letter must see the accepted receipt and NOT run a duplicate turn!
        res_a_retry = deliver(
            self.project,
            message=msg_a,
            actor="claude",
            target="codex",
            runner=runner_a,
            card="U301-R1",
        )
        self.assertEqual("DISPATCHED", res_a_retry.reason)
        self.assertEqual(1, len(runner_a.calls))

        # ── Probe B: Claude failover `record_window` raises `TimeoutError` after retry succeeds ──
        busy_sid = "30200000-0000-4000-8000-000000000302"
        record_window(self.project, "U302", "claude", busy_sid, now=10.0)
        probe_b_calls: list[list[str]] = []

        def probe_b_runner(argv, **_kwargs):
            probe_b_calls.append(list(argv))
            if len(probe_b_calls) == 1:
                return SimpleNamespace(returncode=1, stdout="", stderr=f"Error: Session ID {busy_sid} is already in use.")
            return SimpleNamespace(returncode=0, stdout=json.dumps({"result": "probe-b-ok"}), stderr="")

        with mock.patch(
            "v7_harness.coord.windows.record_window",
            side_effect=TimeoutError("WINDOW_LOCK_TIMEOUT:card_U302"),
        ):
            res_b = deliver(
                self.project,
                message="ACTIONABLE_DELTA verdict_requested=yes: U302 probe B",
                actor="codex",
                target="claude",
                runner=probe_b_runner,
                card="U302-R1",
            )
        self.assertEqual("DISPATCHED", res_b.reason)
        self.assertEqual(2, len(probe_b_calls))
        self.assertTrue((accepted_dir / f"{res_b.message_id}.json").is_file())
        failover_warnings = list(attempts_dir.glob("claude_failover_bookkeeping_*.json"))
        self.assertTrue(failover_warnings)

        # ── Probe C: `agy_dispatch` post-turn `release_window_lease` & `record_window` raise `TimeoutError` ──
        record_window(self.project, "U303", "antigravity", "conv-u303", now=10.0, last_input_tokens=15_000)
        agy_turns = {"n": 0}

        def probe_c_runner(argv, **_kwargs):
            if Path(argv[0]).stem == "agy":
                agy_turns["n"] += 1
                env = {
                    "status": "SUCCESS",
                    "conversation_id": "conv-u303",
                    "usage": {"input_tokens": 22_000, "output_tokens": 300},
                    "response": "VERDICT: PASS probe C preserved.",
                }
                return SimpleNamespace(returncode=0, stdout=json.dumps(env).encode("utf-8"), stderr=b"")
            return SimpleNamespace(returncode=0, stdout=json.dumps({"result": "ok"}), stderr="")

        with mock.patch(
            "v7_harness.coord.windows.release_window_lease",
            side_effect=TimeoutError("WINDOW_LOCK_TIMEOUT:card_U303"),
        ), mock.patch(
            "v7_harness.coord.windows.record_window",
            side_effect=TimeoutError("WINDOW_LOCK_TIMEOUT:card_U303"),
        ):
            row_c = agy_dispatch.dispatch(
                self.project,
                message_id="relay_probe_c_u303",
                actor="claude",
                message="Please audit U303",
                runner=probe_c_runner,
                card="U303-R1",
                audit=True,
            )
        self.assertEqual("ANSWERED", row_c["state"])
        self.assertEqual(1, agy_turns["n"])
        self.assertTrue(agy_dispatch._answered(self.project, "relay_probe_c_u303"))
        kept_env, kept_err = agy_dispatch._replay(self.project, "relay_probe_c_u303", "claude", "Please audit U303")
        self.assertEqual("", kept_err)
        self.assertIsNotNone(kept_env)

        # ── Pre-dispatch `acquire_window_lease` timeout returns structured refusal without raising or spending cap ──
        with mock.patch(
            "v7_harness.coord.windows.acquire_window_lease",
            side_effect=TimeoutError("WINDOW_LOCK_TIMEOUT:card_U301"),
        ):
            refused_deliver = deliver(
                self.project,
                message="ACTIONABLE_DELTA verdict_requested=yes: U301 pre-dispatch lock timeout",
                actor="claude",
                target="codex",
                runner=runner_a,
                card="U301-R2",
            )
            self.assertEqual("WINDOW_LOCK_TIMEOUT", refused_deliver.reason)
            self.assertFalse(refused_deliver.delivered)

            refused_agy = agy_dispatch.dispatch(
                self.project,
                message_id="relay_probe_pre_timeout_u303",
                actor="claude",
                message="Please audit U303 pre-timeout",
                runner=probe_c_runner,
                card="U303-R2",
                audit=False,
            )
            self.assertEqual("FAILED", refused_agy["state"])
            self.assertEqual("WINDOW_LOCK_TIMEOUT", refused_agy["error"])
            self.assertIsNone(refused_agy["reservation"])

    def test_11_cli_coord_window_pool_flag_and_p3_hardening(self):
        """P2-2 & P3-1..P3-6 regression test:
        - `coord window --pool` (and `open_window(..., pool=True)`) routes through `acquire_topic_window` so sub-cards
          coalesce into canonical topic keys, enforce `MAX_ACTIVE_WINDOWS_PER_TOOL = 3`, and rotate at 70k tokens.
        - P3-2: `_prune_entry_leases` drops malformed leases (`pid` not int or bool) instead of re-stamping with current PID.
        - P3-3: `set_window_in_flight(False)` never pops another process's live lease.
        - P3-4: `_sync_registry_index` writes `.coord/windows/.mirror_sync_warning.json` when `PermissionError` persists."""
        from v7_harness import cli
        from v7_harness.card_pipeline import TEMPLATE
        from v7_harness.coord.windows import _prune_entry_leases, _sync_registry_index

        manual = self.project / "manual_pool.md"
        manual.write_text(TEMPLATE.format(card="U279", title="Pool CLI"), encoding="utf-8")

        created = iter(["conv-pool-1", "conv-pool-2", "conv-pool-3", "conv-pool-4"])

        def pool_runner(*_a, **_kw):
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"conversation_id": next(created), "usage": {"input_tokens": 12_000}}),
                stderr="",
            )

        with mock.patch("v7_harness.coord.windows.subprocess.run", side_effect=pool_runner):
            for idx, card_arg in enumerate(("U701-R1", "U701-R2", "U702-R1", "U703-R1", "U704-R1"), start=1):
                with mock.patch("sys.stdout", new_callable=__import__("io").StringIO) as out:
                    args = cli.build_parser().parse_args([
                        "coord", "window", "--project", str(self.project),
                        "--card", card_arg, "--tool", "antigravity",
                        "--title", f"pool-{idx}", "--prompt-file", str(manual), "--pool",
                    ])
                    rc = args.func(args)
                self.assertEqual(0, rc)
                payload = json.loads(out.getvalue())
                if card_arg == "U701-R2":
                    self.assertTrue(payload["reused"])
                    self.assertEqual("U701", payload["topic_key"])
        active_pool = active_topic_windows(self.project, "antigravity")
        self.assertLessEqual(len(active_pool), MAX_ACTIVE_WINDOWS_PER_TOOL)

        # P3-2: Malformed leases (`pid` is str, None, or bool) are dropped, never re-stamped with `os.getpid()`
        live_pruned, changed = _prune_entry_leases({
            "in_flight_leases": {
                "bad-str": {"pid": "not-an-int", "at": 1.0},
                "bad-bool": {"pid": True, "at": 1.0},
                "bad-none": {"pid": None, "at": 1.0},
                "good-self": {"pid": os.getpid(), "at": 2.0},
            }
        })
        self.assertTrue(changed)
        self.assertEqual(["good-self"], list(live_pruned.keys()))

        # P3-3: `set_window_in_flight(False)` from PID B never pops PID A's live lease
        record_window(self.project, "U709", "codex", "01997090-0000-7000-8000-000000000709", now=10.0)
        acquire_window_lease(self.project, "U709", "codex", lease_id="self-lease", pid=os.getpid(), now=11.0)
        set_window_in_flight(self.project, "U709", "codex", False, pid=os.getpid() + 99999)
        self.assertEqual(1, window_entry(self.project, "U709", "codex").get("in_flight_count"))
        release_window_lease(self.project, "U709", "codex", "self-lease")

        # P3-4: `_sync_registry_index` writes `.mirror_sync_warning.json` when `PermissionError` persists
        with mock.patch("v7_harness.coord.windows._retry", side_effect=PermissionError("locked")):
            ok_sync = _sync_registry_index(self.project, "U709", {"card": "U709", "tools": {}})
        self.assertFalse(ok_sync)
        warn_file = self.project / ".coord" / "windows" / ".mirror_sync_warning.json"
        self.assertTrue(warn_file.is_file())
        warn_data = json.loads(warn_file.read_text(encoding="utf-8"))
        self.assertEqual("WINDOWS_MIRROR_SYNC_FAILED", warn_data.get("warning"))


if __name__ == "__main__":
    unittest.main()
