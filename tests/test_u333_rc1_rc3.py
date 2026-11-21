"""U333 partitioned offline tests: RC-1 (Codex lane desk fallback) and RC-3 (Claude lane atomic rotation + CAS guard).

RC-1 and RC-3 checks live in separate TestCase classes so each defect is independently identifiable.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from v7_harness.coord import presence
from v7_harness.coord import watch as W
from v7_harness.coord.deliver import deliver
from v7_harness.coord.process_lanes import (
    ClaudeLaneStateError,
    ensure_claude_lane_session,
    mark_claude_lane_session_ready,
)

CODEX_DESK = "0199eeee-0000-7000-8000-000000000333"
OTHER_THREAD = "0199ffff-0000-7000-8000-000000000999"


def _register_rollout(sessions: Path, project: Path, thread_id: str) -> None:
    day = sessions / "2026" / "11" / "20"
    day.mkdir(parents=True, exist_ok=True)
    meta = {"type": "session_meta", "payload": {"id": thread_id, "session_id": thread_id, "cwd": str(project)}}
    (day / f"rollout-2026-11-20T00-00-00-{thread_id}.jsonl").write_text(json.dumps(meta) + "\n", encoding="utf-8")


class _Recorder:
    def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.calls: list[list[str]] = []
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def __call__(self, argv, **_kwargs):
        self.calls.append(list(argv))
        out = self.stdout or json.dumps({"result": "ok"})
        return SimpleNamespace(returncode=self.returncode, stdout=out, stderr=self.stderr)


class _U333Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord" / "presence").mkdir(parents=True, exist_ok=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        self.sessions = Path(self._tmp.name) / "codex-sessions"
        self.sessions.mkdir(parents=True, exist_ok=True)
        env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(self.sessions)})
        env.start()
        self.addCleanup(env.stop)
        which = mock.patch("v7_harness.coord.deliver.shutil.which", side_effect=lambda name: name)
        which.start()
        self.addCleanup(which.stop)

    def _setup_verified_codex_desk(self) -> None:
        _register_rollout(self.sessions, self.project, CODEX_DESK)
        (self.project / ".coord" / "presence" / "user_desk_codex.json").write_text(
            json.dumps({"thread": CODEX_DESK, "at": time.time(), "source": "UserPromptSubmit"}),
            encoding="utf-8",
        )
        presence.mark(self.project, "codex", "ACTIVE", ttl_s=3600)


class TestU333RC1CodexLaneDeskFallback(_U333Base):
    """RC-1: Unbound Codex lane mail uses verified designated desk only; never bootstraps or silent-reroutes."""

    def test_rc1_unbound_codex_lane_falls_back_to_verified_designated_desk(self) -> None:
        self._setup_verified_codex_desk()
        rec = _Recorder()
        res = deliver(
            self.project,
            message="unbound lane update",
            actor="antigravity",
            target="codex",
            lane="ARCH_DESIGN",
            wake_class="ACTIONABLE",
            delta="lane fallback",
            runner=rec,
        )
        self.assertEqual(res.reason, "DISPATCHED")
        self.assertEqual(len(rec.calls), 1)
        self.assertIn(CODEX_DESK, rec.calls[0])

    def test_rc1_missing_designated_desk_never_bootstraps_newest(self) -> None:
        _register_rollout(self.sessions, self.project, OTHER_THREAD)
        presence.mark(self.project, "codex", "ACTIVE", ttl_s=3600)
        rec = _Recorder()
        res = deliver(
            self.project,
            message="unbound lane no desk",
            actor="antigravity",
            target="codex",
            lane="ARCH_DESIGN",
            wake_class="ACTIONABLE",
            delta="no desk",
            runner=rec,
        )
        self.assertEqual(res.reason, "QUEUED_UNTIL_ACTIVE")
        self.assertEqual(len(rec.calls), 0)

    def test_rc1_desk_fallback_nonzero_dispatch_never_guesses_other_thread(self) -> None:
        self._setup_verified_codex_desk()
        _register_rollout(self.sessions, self.project, OTHER_THREAD)
        rec = _Recorder(returncode=1, stderr="queue failed")
        res = deliver(
            self.project,
            message="unbound lane nonzero",
            actor="antigravity",
            target="codex",
            lane="ARCH_DESIGN",
            wake_class="ACTIONABLE",
            delta="nonzero desk",
            runner=rec,
        )
        self.assertEqual(res.reason, "DELIVERY_FAILED:rc=1")
        self.assertEqual(len(rec.calls), 1)
        self.assertIn(CODEX_DESK, rec.calls[0])

    def test_rc1_bound_card_lane_never_silently_reroutes_to_desk(self) -> None:
        self._setup_verified_codex_desk()
        rec = _Recorder()
        res = deliver(
            self.project,
            message="bound card msg",
            actor="antigravity",
            target="codex",
            card="COMM-REALTIME-261120",
            lane="ARCH_DESIGN",
            wake_class="ACTIONABLE",
            delta="bound card",
            runner=rec,
        )
        self.assertEqual(res.reason, "QUEUED_UNTIL_ACTIVE")
        self.assertEqual(len(rec.calls), 0)

    def test_rc1_limited_codex_stays_fail_closed(self) -> None:
        self._setup_verified_codex_desk()
        presence.mark(self.project, "codex", "LIMITED", lease=True, ttl_s=3600)
        rec = _Recorder()
        res = deliver(
            self.project,
            message="unbound lane while limited",
            actor="antigravity",
            target="codex",
            lane="ARCH_DESIGN",
            wake_class="ACTIONABLE",
            delta="limited check",
            runner=rec,
        )
        self.assertEqual(res.reason, "QUEUED_UNTIL_ACTIVE")
        self.assertEqual(len(rec.calls), 0)


class TestU333RC3ClaudeLaneSessionRotation(_U333Base):
    """RC-3: Atomic non-colliding Claude lane rotation, preserved state, and late old-session CAS guard."""

    def test_rc3_claude_lane_rotate_preserves_state_and_writes_old_in_flight_receipt(self) -> None:
        presence.mark(self.project, "claude", "ACTIVE", ttl_s=3600)
        sid0, path0, _ = ensure_claude_lane_session(self.project, "ARCH_DESIGN", rotate=False)
        gen0 = int(json.loads(path0.read_text(encoding="utf-8"))["generation"])
        rec = _Recorder(returncode=1, stdout="", stderr="Error: Session ID x is already in use.\n")

        res = deliver(
            self.project,
            message="claude lane test",
            actor="antigravity",
            target="claude",
            lane="ARCH_DESIGN",
            wake_class="ACTIONABLE",
            delta="claude collision check",
            runner=rec,
        )
        self.assertFalse(res.delivered)
        self.assertTrue(path0.is_file(), "claude-lane session file must never be unlinked on failed send")

        state = json.loads(path0.read_text(encoding="utf-8"))
        self.assertGreater(int(state["generation"]), gen0)
        self.assertNotEqual(state["session_id"], sid0)
        self.assertEqual(state.get("prior_in_flight", {}).get("session_id"), sid0)

        attempts_dir = self.project / ".coord" / "mailbox" / "delivery" / "attempts"
        rot_receipts = sorted(attempts_dir.glob("claude-lane-ARCH_DESIGN_rotation_*.json"))
        self.assertTrue(rot_receipts, "expected durable rotation receipt preserving old in-flight session")
        rot_data = json.loads(rot_receipts[0].read_text(encoding="utf-8"))
        self.assertEqual(rot_data.get("old_session_id"), sid0)
        self.assertEqual(int(rot_data.get("old_generation")), gen0)
        self.assertEqual(rot_data.get("new_session_id"), state["session_id"])

        sid2, path2, _ = ensure_claude_lane_session(self.project, "ARCH_DESIGN", rotate=True)
        gen2 = int(json.loads(path2.read_text(encoding="utf-8"))["generation"])
        self.assertNotIn(sid2, {sid0, state["session_id"]})
        self.assertGreater(gen2, int(state["generation"]))
        for sid in (sid0, state["session_id"], sid2):
            uuid.UUID(sid)

    def test_rc3_concurrent_lane_rotations_advance_generation_atomically(self) -> None:
        workers = 8
        barrier = threading.Barrier(workers)
        results: list[str] = []
        errors: list[BaseException] = []
        lock = threading.Lock()

        def worker() -> None:
            try:
                barrier.wait(timeout=10.0)
                sid, _path, _ = ensure_claude_lane_session(self.project, "ARCH_DESIGN", rotate=True)
                with lock:
                    results.append(sid)
            except BaseException as exc:  # noqa: BLE001
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15.0)

        self.assertEqual(errors, [])
        self.assertEqual(len(results), workers)
        self.assertEqual(len(set(results)), workers)
        lane_file = self.project / ".coord" / "mailbox" / "delivery" / "claude-lane-ARCH_DESIGN.json"
        state = json.loads(lane_file.read_text(encoding="utf-8"))
        self.assertGreaterEqual(int(state["generation"]), workers)

    def test_rc3_late_old_session_completion_cannot_mark_new_generation_ready_or_overwrite_state(self) -> None:
        presence.mark(self.project, "claude", "ACTIVE", ttl_s=3600)
        sid0, path0, ready0 = ensure_claude_lane_session(self.project, "ARCH_DESIGN", rotate=False)
        self.assertFalse(ready0)
        rotated: dict[str, object] = {}

        def racing_runner(argv, **_kwargs):
            rotated["argv"] = list(argv)
            sid1, _path1, ready1 = ensure_claude_lane_session(self.project, "ARCH_DESIGN", rotate=True)
            rotated["sid1"] = sid1
            rotated["ready1"] = ready1
            return SimpleNamespace(returncode=0, stdout=json.dumps({"result": "late ok"}), stderr="")

        res = deliver(
            self.project,
            message="claude lane late completion",
            actor="antigravity",
            target="claude",
            lane="ARCH_DESIGN",
            wake_class="ACTIONABLE",
            delta="late completion guard",
            runner=racing_runner,
        )
        self.assertEqual(res.reason, "DISPATCHED")
        self.assertIn(sid0, rotated["argv"])
        self.assertTrue(path0.is_file())

        state = json.loads(path0.read_text(encoding="utf-8"))
        self.assertEqual(state["session_id"], rotated["sid1"])
        self.assertEqual(int(state["generation"]), 1)
        self.assertFalse(
            bool(state["ready"]),
            "late completion of superseded session must never mark rotated generation ready=True",
        )
        self.assertEqual(state.get("prior_in_flight", {}).get("session_id"), sid0)

        attempts_dir = self.project / ".coord" / "mailbox" / "delivery" / "attempts"
        rot_receipts = sorted(attempts_dir.glob("claude-lane-ARCH_DESIGN_rotation_*.json"))
        self.assertTrue(rot_receipts, "expected durable rotation receipt")
        stale_receipts = sorted(attempts_dir.glob("claude-lane-ARCH_DESIGN_stale_completion_*.json"))
        self.assertEqual(len(stale_receipts), 1, "expected distinct durable stale-completion receipt")
        stale_data = json.loads(stale_receipts[0].read_text(encoding="utf-8"))
        self.assertEqual(stale_data.get("schema"), "u333-lane-stale-completion-v1")
        self.assertEqual(stale_data.get("completed_session_id"), sid0)
        self.assertEqual(stale_data.get("active_session_id"), rotated["sid1"])
        self.assertEqual(int(stale_data.get("active_generation")), 1)
        self.assertFalse(bool(stale_data.get("active_ready")))
        self.assertEqual(stale_data.get("action"), "IGNORED_STALE_COMPLETION")

    def test_rc3_watcher_liveness_never_grants_active_or_overrides_limited(self) -> None:
        now = time.time()
        (self.project / ".coord" / "presence" / "codex.json").write_text(
            json.dumps(
                {
                    "tool": "codex",
                    "state": "ACTIVE",
                    "observed_at": "2026-11-19T16:00:00+00:00",
                    "expires_at": now - 600.0,
                }
            ),
            encoding="utf-8",
        )
        (self.project / ".coord" / "presence" / "codex.test.watch.json").write_text(
            json.dumps(
                {
                    "tool": "codex",
                    "token": "tok-test",
                    "pid": os.getpid(),
                    "expires_at": now + 300.0,
                    "wakes_session": True,
                    "session": CODEX_DESK,
                    "adapter": "claude-bg-task",
                    "process_created": W.process_identity(os.getpid()),
                }
            ),
            encoding="utf-8",
        )
        self.assertTrue(W.watcher_live(self.project, "codex", now=now))
        self.assertEqual(presence.read(self.project, "codex", now=now)["state"], "UNKNOWN")
        self.assertNotEqual(presence.conductor(presence.read_all(self.project, now=now))["conductor"], "codex")

        presence.mark(self.project, "codex", "LIMITED", lease=True, ttl_s=3600)
        self.assertTrue(W.watcher_live(self.project, "codex", now=now))
        self.assertEqual(presence.read(self.project, "codex")["state"], "LIMITED")

    def test_rc3_fault_at_lane_state_replace_leaves_no_rotation_receipt_and_keeps_former_authoritative(self) -> None:
        sid0, path0, _ = ensure_claude_lane_session(self.project, "ARCH_DESIGN", rotate=False)
        attempts_dir = self.project / ".coord" / "mailbox" / "delivery" / "attempts"
        intent_path = self.project / ".coord" / "mailbox" / "delivery" / "claude-lane-ARCH_DESIGN.rotation.intent.json"

        real_replace = os.replace

        def fail_state_replace(src, dst):
            if Path(dst) == path0:
                raise PermissionError("injected fault at lane-state replace")
            return real_replace(src, dst)

        with mock.patch("v7_harness.coord.process_lanes.os.replace", side_effect=fail_state_replace):
            with self.assertRaises(PermissionError):
                ensure_claude_lane_session(self.project, "ARCH_DESIGN", rotate=True)

        state_after_fault = json.loads(path0.read_text(encoding="utf-8"))
        self.assertEqual(state_after_fault["session_id"], sid0)
        self.assertEqual(int(state_after_fault["generation"]), 0)
        self.assertEqual(list(attempts_dir.glob("claude-lane-ARCH_DESIGN_rotation_*.json")), [])
        self.assertFalse(intent_path.exists())

        sid_check, _, _ = ensure_claude_lane_session(self.project, "ARCH_DESIGN", rotate=False)
        self.assertEqual(sid_check, sid0)
        sid1, _, _ = ensure_claude_lane_session(self.project, "ARCH_DESIGN", rotate=True)
        self.assertNotEqual(sid1, sid0)
        self.assertEqual(len(list(attempts_dir.glob("claude-lane-ARCH_DESIGN_rotation_*.json"))), 1)

    def test_rc3_fault_at_rotation_receipt_write_recovers_committed_state_on_next_call(self) -> None:
        sid0, path0, _ = ensure_claude_lane_session(self.project, "ARCH_DESIGN", rotate=False)
        attempts_dir = self.project / ".coord" / "mailbox" / "delivery" / "attempts"
        intent_path = self.project / ".coord" / "mailbox" / "delivery" / "claude-lane-ARCH_DESIGN.rotation.intent.json"

        real_replace = os.replace

        def fail_receipt_replace(src, dst):
            if "_rotation_" in Path(dst).name:
                raise PermissionError("injected fault at rotation receipt write")
            return real_replace(src, dst)

        with mock.patch("v7_harness.coord.process_lanes.os.replace", side_effect=fail_receipt_replace):
            with self.assertRaises(PermissionError):
                ensure_claude_lane_session(self.project, "ARCH_DESIGN", rotate=True)

        committed = json.loads(path0.read_text(encoding="utf-8"))
        sid1 = committed["session_id"]
        self.assertNotEqual(sid1, sid0)
        self.assertEqual(int(committed["generation"]), 1)
        self.assertTrue(intent_path.is_file(), "durable intent must remain for recovery when receipt write fails")
        self.assertEqual(list(attempts_dir.glob("claude-lane-ARCH_DESIGN_rotation_*.json")), [])

        sid_recovered, _, _ = ensure_claude_lane_session(self.project, "ARCH_DESIGN", rotate=False)
        self.assertEqual(sid_recovered, sid1)
        self.assertFalse(intent_path.exists())
        receipts = sorted(attempts_dir.glob("claude-lane-ARCH_DESIGN_rotation_*.json"))
        self.assertEqual(len(receipts), 1)
        rec = json.loads(receipts[0].read_text(encoding="utf-8"))
        self.assertEqual(rec["old_session_id"], sid0)
        self.assertEqual(rec["new_session_id"], sid1)
        self.assertEqual(int(rec["old_generation"]), 0)
        self.assertEqual(int(rec["new_generation"]), 1)

        # Idempotent subsequent call must not create duplicate rotation receipts.
        sid_again, _, _ = ensure_claude_lane_session(self.project, "ARCH_DESIGN", rotate=False)
        self.assertEqual(sid_again, sid1)
        self.assertEqual(len(list(attempts_dir.glob("claude-lane-ARCH_DESIGN_rotation_*.json"))), 1)

    def test_rc3_missing_or_corrupt_active_state_fails_closed(self) -> None:
        delivery_dir = self.project / ".coord" / "mailbox" / "delivery"
        delivery_dir.mkdir(parents=True, exist_ok=True)
        lane_file = delivery_dir / "claude-lane-ARCH_DESIGN.json"
        intent_file = delivery_dir / "claude-lane-ARCH_DESIGN.rotation.intent.json"

        # 1. Missing active lane state fails closed on mark_claude_lane_session_ready (never creates ready=True).
        with self.assertRaises(ClaudeLaneStateError):
            mark_claude_lane_session_ready(self.project, "ARCH_DESIGN", str(uuid.uuid4()))
        self.assertFalse(lane_file.exists())

        # 2. Corrupt JSON active lane state fails closed on both ensure and mark_ready without clobbering.
        corrupt_text = "{corrupt-json"
        lane_file.write_text(corrupt_text, encoding="utf-8")
        with self.assertRaises(ClaudeLaneStateError):
            ensure_claude_lane_session(self.project, "ARCH_DESIGN", rotate=False)
        with self.assertRaises(ClaudeLaneStateError):
            ensure_claude_lane_session(self.project, "ARCH_DESIGN", rotate=True)
        with self.assertRaises(ClaudeLaneStateError):
            mark_claude_lane_session_ready(self.project, "ARCH_DESIGN", str(uuid.uuid4()))
        self.assertEqual(lane_file.read_text(encoding="utf-8"), corrupt_text)

        # 3. Schema-invalid active lane state (non-UUID session_id) fails closed.
        lane_file.write_text(json.dumps({"lane_id": "ARCH_DESIGN", "session_id": "not-a-uuid", "generation": 1, "ready": False}), encoding="utf-8")
        with self.assertRaises(ClaudeLaneStateError):
            ensure_claude_lane_session(self.project, "ARCH_DESIGN", rotate=False)
        with self.assertRaises(ClaudeLaneStateError):
            mark_claude_lane_session_ready(self.project, "ARCH_DESIGN", "not-a-uuid")

        # 4. Valid active lane state + corrupt rotation intent fails closed.
        lane_file.unlink()
        sid0, _, _ = ensure_claude_lane_session(self.project, "ARCH_DESIGN", rotate=False)
        intent_file.write_text("{corrupt-intent", encoding="utf-8")
        with self.assertRaises(ClaudeLaneStateError):
            ensure_claude_lane_session(self.project, "ARCH_DESIGN", rotate=False)
        with self.assertRaises(ClaudeLaneStateError):
            mark_claude_lane_session_ready(self.project, "ARCH_DESIGN", sid0)


if __name__ == "__main__":
    unittest.main()
