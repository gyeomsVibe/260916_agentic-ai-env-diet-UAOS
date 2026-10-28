"""U279: 3-Tool (Codex, Claude Code, Antigravity) Topic-Grouped Bounded Window Pool & Coalescing Ingress Tests.

Verifies the 6 measurable acceptance gates from `.coord/tasks/U279-3tool-topic-window-coalescing-spec.md`:
1. Screenshot reproduction (`media_1793113686297_bca5c8d9.png`): 10 `[agy-auto] ... ACK_ONLY` NOTICEs + 1 ACTIONABLE
   relay to Codex invoke `codex queue` exactly 1 time (0 queue spam for NOTICE/ACK_ONLY).
2. Topic-key normalization (`normalize_topic_key`) & sub-card window reuse across Codex, Claude Code, and Antigravity
   (`U275-R1`, `U275-R8-L1`, `PR244-U275`, `U275_VERDICT` -> single `[U275]` window).
3. Bounded active window pool (`MAX_ACTIVE_WINDOWS_PER_TOOL = 3`) with LRU eviction (`POOL_CAP_LRU_EVICTED`) and
   least-loaded sharing (`share_least_loaded`) to prevent window proliferation (대화창 남발 방지).
4. Context-bloat rotation at `RESUME_MAX_INPUT = 70_000` tokens (`TOKEN_CAP_ROTATED`).
5. Same-topic burst coalescing (`coalesce_burst=True` -> `COALESCED_INTO_TOPIC_BATCH` + single `[UAOS topic-batch]` turn).
6. Claude per-topic lock sharding (`claude-topic-<topic>.turn.lock`) for parallel execution & `already in use` failover.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from v7_harness.coord import agy_dispatch, presence
from v7_harness.coord.deliver import deliver
from v7_harness.coord.windows import (
    MAX_ACTIVE_WINDOWS_PER_TOOL,
    RESUME_MAX_INPUT,
    acquire_topic_window,
    active_topic_windows,
    normalize_topic_key,
    record_window,
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
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        self.sessions = Path(self._tmp.name) / "codex-sessions"
        self.sessions.mkdir()
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(self.sessions)})
        self._env.start()
        self._which = mock.patch("v7_harness.coord.deliver.shutil.which", side_effect=lambda name: name)
        self._which.start()
        presence.mark(self.project, "codex", "ACTIVE")
        presence.mark(self.project, "claude", "ACTIVE")
        presence.mark(self.project, "antigravity", "ACTIVE")

    def tearDown(self):
        self._which.stop()
        self._env.stop()
        self._tmp.cleanup()

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

        # 10 `[agy-auto]` NOTICE / ACK_ONLY replies identical in structure to the screenshot's 10 stacked items
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

        # 1 real ACTIONABLE handoff (`CODEX-RETURN`)
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
        # Only 1 `codex queue` invocation instead of 11!
        self.assertEqual(1, len(runner.calls))
        self.assertIn("queue", runner.calls[0])

    def test_2_topic_grouping_reuses_same_window_across_all_3_tools(self):
        """Related sub-cards (`U275-R1`, `U275-R8-L1`, `PR244-U275`, `U275_VERDICT`) map to canonical `U275`."""
        for subcard in ("U275", "U275-R1", "U275-R8-L1", "PR244-U275", "U275_VERDICT", "RSI-U275-FIX"):
            self.assertEqual("U275", normalize_topic_key(subcard), subcard)
        self.assertEqual("DESK-SYNC", normalize_topic_key("CODEX-RETURN"))
        self.assertEqual("DESK-SYNC", normalize_topic_key("DESK-261028-1"))

        codex_tid = "0199aaaa-0000-7000-8000-000000000275"
        claude_sid = "27500000-0000-4000-8000-000000000275"
        agy_cid = "conv-u275-shared"
        self._register_codex_rollout(codex_tid)

        # Record the canonical `[U275]` window for all 3 tools
        record_window(self.project, "U275", "codex", codex_tid, now=100.0)
        record_window(self.project, "U275", "claude", claude_sid, now=100.0)
        record_window(self.project, "U275", "antigravity", agy_cid, now=100.0, last_input_tokens=24_000)

        # Sub-cards automatically resolve to the `[U275]` window in all 3 tools without opening new windows
        for sub in ("U275-R1", "U275-R8-L1", "PR244-U275"):
            self.assertEqual(codex_tid, window_for(self.project, sub, "codex"))
            self.assertEqual(claude_sid, window_for(self.project, sub, "claude"))
            self.assertEqual(agy_cid, window_for(self.project, sub, "antigravity"))

        # Verify `deliver` routes `card="U275-R8-L1"` into `codex_tid` (not the user desk!)
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

        # Verify Antigravity `agy_dispatch` reuses `conv-u275-shared` when called for `U275-R8-L1`
        agy_calls = []

        def agy_runner(argv, **kwargs):
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

    def test_3_bounded_window_pool_cap_evicts_lru_and_prevents_window_sprawl(self):
        """Opening more than `MAX_ACTIVE_WINDOWS_PER_TOOL` (3) distinct topics evicts LRU or shares least-loaded."""
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

        # Open 3 topic windows: U271 (t=10), U272 (t=20), U273 (t=30)
        w1 = acquire_topic_window(self.project, "U271-R1", "codex", "t1", "p1", rpc=fake_rpc, now=10.0)
        w2 = acquire_topic_window(self.project, "U272-R1", "codex", "t2", "p2", rpc=fake_rpc, now=20.0)
        w3 = acquire_topic_window(self.project, "U273-R1", "codex", "t3", "p3", rpc=fake_rpc, now=30.0)
        self.assertFalse(w1["reused"])
        self.assertFalse(w2["reused"])
        self.assertFalse(w3["reused"])

        # Re-requesting a subcard of U271 (`U271-R2`) at t=40 reuses U271 and bumps its `last_active_at` to 40.0!
        w1_reuse = acquire_topic_window(self.project, "U271-R2", "codex", "t1", "p1b", rpc=fake_rpc, now=40.0)
        self.assertTrue(w1_reuse["reused"])
        self.assertEqual(w1["id"], w1_reuse["id"])
        self.assertIn("U271-R2", w1_reuse["subcards"])
        self.assertEqual(3, len(active_topic_windows(self.project, "codex")))

        # Now U272 (last_active_at=20.0) is the oldest idle (LRU) window!
        # Opening a 4th distinct topic `U274` at t=50 must auto-release `U272` and keep active windows == 3.
        w4 = acquire_topic_window(self.project, "U274", "codex", "t4", "p4", rpc=fake_rpc, now=50.0)
        self.assertFalse(w4["reused"])
        self.assertEqual(["U272"], w4.get("evicted_lru"))
        active = active_topic_windows(self.project, "codex")
        self.assertEqual(MAX_ACTIVE_WINDOWS_PER_TOOL, len(active))
        self.assertEqual({"U271", "U273", "U274"}, {item["card"] for item in active})
        self.assertEqual("POOL_CAP_LRU_EVICTED", window_entry(self.project, "U272", "codex").get("released_reason"))

        # Test `overflow_policy="share_least_loaded"` on a 5th topic `U275`: binds to least-loaded without opening a new RPC thread
        w5 = acquire_topic_window(
            self.project, "U275", "codex", "t5", "p5", rpc=fake_rpc, now=60.0, overflow_policy="share_least_loaded"
        )
        self.assertTrue(w5["reused"])
        self.assertIn(w5["shared_from"], {"U271", "U273", "U274"})

    def test_4_topic_window_rotates_cleanly_at_70k_input_tokens(self):
        """When a topic window reaches `RESUME_MAX_INPUT` (70,000 tokens), `acquire_topic_window` rotates to a fresh ID."""
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

        # Next subcard `U276-R2` sees 72,000 >= 70,000 (`RESUME_MAX_INPUT`) and rotates to `conv-u276-rotated`
        second = acquire_topic_window(self.project, "U276-R2", "antigravity", "title", "prompt", runner=fake_agy_runner, now=20.0)
        self.assertFalse(second["reused"])
        self.assertEqual("conv-u276-rotated", second["id"])
        self.assertEqual("conv-u276-first", second["rotated_from"])
        self.assertEqual(21_000, second["last_input_tokens"])

    def test_5_same_topic_burst_relays_coalesce_into_single_batch_turn(self):
        """Rapid-fire updates for the same `(target, topic_key)` coalesce and flush in a single batch turn."""
        topic_tid = "0199cccc-0000-7000-8000-000000000275"
        self._register_codex_rollout(topic_tid)
        record_window(self.project, "U275", "codex", topic_tid, now=10.0)
        runner = _FakeRunner()

        r1 = deliver(
            self.project,
            message="ACTIONABLE_DELTA: U275 slice 1 ready",
            actor="claude",
            target="codex",
            runner=runner,
            card="U275-R1",
            coalesce_burst=True,
        )
        r2 = deliver(
            self.project,
            message="ACTIONABLE_DELTA: U275 slice 2 ready",
            actor="antigravity",
            target="codex",
            runner=runner,
            card="U275-R2",
            coalesce_burst=True,
        )
        self.assertEqual("COALESCED_INTO_TOPIC_BATCH", r1.reason)
        self.assertEqual("COALESCED_INTO_TOPIC_BATCH", r2.reason)
        self.assertEqual(0, len(runner.calls))

        # Final flush turn (`coalesce_burst=False`) drains both coalesced deltas into one `codex queue` call
        r3 = deliver(
            self.project,
            message="ACTIONABLE_DELTA VERDICT_REQUESTED=YES: U275 final review",
            actor="claude",
            target="codex",
            runner=runner,
            card="U275-R3",
            coalesce_burst=False,
        )
        self.assertEqual("DISPATCHED", r3.reason)
        self.assertEqual(1, len(runner.calls))
        sent_msg = runner.calls[0][runner.calls[0].index("--message") + 1]
        self.assertIn("[UAOS topic-batch topic=U275 coalesced_count=3]", sent_msg)
        self.assertIn(r1.message_id, sent_msg)
        self.assertIn(r2.message_id, sent_msg)

    def test_6_claude_parallel_topic_locks_and_session_in_use_failover(self):
        """Distinct topics (`U276` vs `U277`) use sharded Claude turn locks in parallel and recover from busy sessions."""
        barrier = threading.Barrier(2, timeout=5.0)
        overlap_proved = {"ok": False}
        calls_lock = threading.Lock()
        claude_calls: list[list[str]] = []

        def parallel_claude_runner(argv, **_kwargs):
            with calls_lock:
                claude_calls.append(list(argv))
            # Both topic threads must enter `parallel_claude_runner` simultaneously; a single global lock would deadlock
            # this barrier!
            barrier.wait()
            overlap_proved["ok"] = True
            return SimpleNamespace(returncode=0, stdout=json.dumps({"result": "ok"}), stderr="")

        results: list[ str ] = []

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

        self.assertTrue(overlap_proved["ok"], "Claude topic locks did not run in parallel!")
        self.assertEqual(["DISPATCHED", "DISPATCHED"], results)

        # Verify automatic failover when a recorded Claude session is "already in use"
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
        self.assertIn("--resume", retry_calls[0])
        self.assertIn("--session-id", retry_calls[1])


if __name__ == "__main__":
    unittest.main()
