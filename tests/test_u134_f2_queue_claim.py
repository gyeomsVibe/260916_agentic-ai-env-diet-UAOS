"""U134-F2 fixed acceptance: a queued letter is claimed one at a time under a per-letter OS lock.

Receipt: Codex rev3 verdict relay_4e5ed6c2 (2026-10-03) refused lease expiry plus a pre-send token check (TOCTOU: an
owner paused after its check may resume and send after a reclaim). Required instead:
- A per-letter OS lifetime lock, held across the ownership check, the send and the settle.
- Recovery must take that same lock, so a live paused owner is never robbed by age.
- Healthy path: exactly one send. Crash path: the original message id is kept.
- Recovery stays scoped to that message (no global `recover_stale_claims`).
- A corrupt marker never overwrites existing `.failed` evidence.

The owners here are real child processes. They are paused inside the send, then released or killed, and the OS drops
the lock of a killed process. Written by the judge (acting conductor Claude while Codex is LIMITED) before dispatch.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import deliver as deliver_mod
from v7_harness.coord import presence
from v7_harness.coord.deliver import deliver, dispatch_queued

THREAD = "01a1006f-4196-7ff0-87ac-f6523066cd8c"
REPO = Path(__file__).resolve().parents[1]
# Why 60 s: a child process start and import takes about 1-3 s on this Windows host; 60 s only runs out on a hang.
WAIT_S = 60.0

CHILD = r"""
import sys, time, types
from pathlib import Path
from unittest import mock
from v7_harness.coord.deliver import dispatch_queued

project, calls, go = (Path(a) for a in sys.argv[1:4])

def runner(command, **_kw):
    with calls.open("a", encoding="utf-8") as handle:
        handle.write(command[-1].replace("\n", " ") + "\n")
    deadline = time.time() + 120
    while not go.exists() and time.time() < deadline:
        time.sleep(0.05)
    return types.SimpleNamespace(returncode=0, stdout="", stderr="")

with mock.patch("v7_harness.coord.deliver.shutil.which", return_value="codex"):
    dispatch_queued(project, "codex", runner=runner)
"""


class _Runner:
    def __init__(self):
        self.calls = []
        self._lock = threading.Lock()

    def __call__(self, command, **_kw):
        with self._lock:
            self.calls.append(list(command))
        return mock.Mock(returncode=0, stdout="", stderr="")


class F2QueueClaimTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.project = base / "proj"
        (self.project / ".coord").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        self.sessions = base / "codex-sessions"
        day = self.sessions / "2026" / "10" / "03"
        day.mkdir(parents=True)
        (day / f"rollout-2026-10-03T06-24-00-{THREAD}.jsonl").write_text(
            json.dumps({"type": "session_meta", "payload": {"id": THREAD, "session_id": THREAD,
                                                            "cwd": str(self.project)}}) + "\n",
            encoding="utf-8")
        self.calls_file = base / "child_calls.txt"
        self.go_file = base / "go"
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(self.sessions)})
        self._env.start()
        self._which = mock.patch("v7_harness.coord.deliver.shutil.which", return_value="codex")
        self._which.start()
        self.children = []
        presence.mark(self.project, "codex", "LIMITED", ttl_s=86400, lease=True, lease_source="manual")

    def tearDown(self):
        self.go_file.write_text("go", encoding="utf-8")
        for child in self.children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=WAIT_S)
        self._which.stop()
        self._env.stop()
        self._tmp.cleanup()

    # helpers -------------------------------------------------------------------------------------------------------
    def _queue(self, text):
        result = deliver(self.project, message=f"ACTIONABLE_DELTA {text}", actor="claude", target="codex",
                         runner=_Runner(), thread=THREAD)
        self.assertEqual("QUEUED_UNTIL_ACTIVE", result.reason)
        return result.message_id

    def _activate(self):
        # A turn-start heartbeat without dispatch: clears the manual lease, sends nothing.
        presence.mark(self.project, "codex", "ACTIVE", session="s1", turn_start=True)

    def _queue_dir(self):
        return self.project / ".coord" / "mailbox" / "delivery" / "queued" / "codex"

    def _pending_letters(self):
        folder = self._queue_dir()
        return sorted(p.name for p in folder.iterdir()
                      if p.name.endswith(".json") or p.name.endswith(".taking")) if folder.is_dir() else []

    def _start_paused_child(self):
        env = dict(os.environ, PYTHONPATH=str(REPO))
        child = subprocess.Popen([sys.executable, "-c", CHILD, str(self.project), str(self.calls_file),
                                  str(self.go_file)], cwd=str(REPO), env=env)
        self.children.append(child)
        deadline = time.monotonic() + WAIT_S
        while time.monotonic() < deadline:
            if self.calls_file.is_file() and self.calls_file.read_text(encoding="utf-8").strip():
                return child
            if child.poll() is not None:
                self.fail(f"child exited early with {child.returncode}")
            time.sleep(0.05)
        self.fail("child never reached its send")

    def _child_sends(self):
        if not self.calls_file.is_file():
            return []
        return [line for line in self.calls_file.read_text(encoding="utf-8").splitlines() if line.strip()]

    # tests ---------------------------------------------------------------------------------------------------------
    def test_healthy_path_sends_exactly_once_and_empties_the_queue(self):
        message_id = self._queue("healthy")
        self._activate()
        runner = _Runner()
        dispatch_queued(self.project, "codex", runner=runner)
        dispatch_queued(self.project, "codex", runner=runner)
        self.assertEqual(1, len(runner.calls))
        self.assertIn(message_id, runner.calls[0][-1])
        self.assertEqual([], self._pending_letters())

    def test_a_live_owner_paused_after_its_check_is_not_robbed(self):
        message_id = self._queue("paused owner")
        self._activate()
        child = self._start_paused_child()
        runner = _Runner()
        dispatch_queued(self.project, "codex", runner=runner)  # attempted reclaim while the owner is paused
        self.assertEqual([], runner.calls)
        self.go_file.write_text("go", encoding="utf-8")  # the owner resumes and settles
        self.assertEqual(0, child.wait(timeout=WAIT_S))
        dispatch_queued(self.project, "codex", runner=runner)
        sends = self._child_sends()
        self.assertEqual(1, len(sends))
        self.assertIn(message_id, sends[0])
        self.assertEqual([], runner.calls)
        self.assertEqual([], self._pending_letters())

    def test_a_dead_owner_is_recovered_once_with_the_original_message_id(self):
        message_id = self._queue("dead owner")
        self._activate()
        # A claim of another, unrelated message: scoped recovery must leave it where it is.
        box_claimed = self.project / ".coord" / "mailbox" / "claimed"
        box_claimed.mkdir(parents=True, exist_ok=True)
        unrelated = box_claimed / "relay_ffffffffffffffffffffffffffffffff_dispatcher_1_x.json"
        unrelated.write_text(json.dumps({"message_id": "relay_ffffffffffffffffffffffffffffffff"}), encoding="utf-8")
        old = time.time() - 3600
        os.utime(unrelated, (old, old))
        child = self._start_paused_child()
        child.kill()  # genuine death inside the send: the OS drops its lock
        child.wait(timeout=WAIT_S)
        runner = _Runner()
        # The dead owner's per-message dispatch guard is still young (U83 age rule), so this heartbeat only waits:
        # nothing is sent, and the letter stays queued without spending one of its tries.
        dispatch_queued(self.project, "codex", runner=runner)
        self.assertEqual([], runner.calls)
        queued = self._queue_dir() / f"{message_id}.json"
        self.assertTrue(queued.is_file(), self._pending_letters())
        self.assertEqual(0, json.loads(queued.read_text(encoding="utf-8")).get("attempts"))
        with mock.patch.object(deliver_mod, "GUARD_STALE_S", 0.0):  # the guard has aged past its stale bound
            dispatch_queued(self.project, "codex", runner=runner)
            dispatch_queued(self.project, "codex", runner=runner)
        self.assertEqual(1, len(runner.calls), runner.calls)
        self.assertIn(message_id, runner.calls[0][-1])
        self.assertEqual([], self._pending_letters())
        self.assertTrue(unrelated.is_file())
        self.assertEqual([], sorted(p.name for p in box_claimed.glob(f"{message_id}_*")))

    def test_recovery_is_scoped_to_one_letter(self):
        first = self._queue("letter one")
        second = self._queue("letter two")
        self._activate()
        child = self._start_paused_child()  # owns the first letter in name order and is paused in its send
        held = sorted([first, second])[0]
        free = sorted([first, second])[1]
        self.assertIn(held, self._child_sends()[0])
        runner = _Runner()
        dispatch_queued(self.project, "codex", runner=runner)
        self.assertEqual(1, len(runner.calls))
        self.assertIn(free, runner.calls[0][-1])
        self.go_file.write_text("go", encoding="utf-8")
        self.assertEqual(0, child.wait(timeout=WAIT_S))
        sends = self._child_sends()
        self.assertEqual(1, len(sends))
        self.assertIn(held, sends[0])
        self.assertEqual([], self._pending_letters())

    def test_a_corrupt_marker_keeps_existing_failed_evidence(self):
        self._activate()
        folder = self._queue_dir()
        folder.mkdir(parents=True, exist_ok=True)
        stem = "relay_0123456789abcdef0123456789abcdef"
        (folder / f"{stem}.json").write_text("{not json", encoding="utf-8")
        evidence = folder / f"{stem}.failed"
        evidence.write_text("EARLIER EVIDENCE", encoding="utf-8")
        dispatch_queued(self.project, "codex", runner=_Runner())
        self.assertEqual("EARLIER EVIDENCE", evidence.read_text(encoding="utf-8"))
        self.assertFalse((folder / f"{stem}.json").exists())
        parked = [p for p in folder.iterdir() if p.name.startswith(stem) and p != evidence and "failed" in p.name]
        self.assertEqual(1, len(parked), sorted(p.name for p in folder.iterdir()))
        self.assertEqual("{not json", parked[0].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
