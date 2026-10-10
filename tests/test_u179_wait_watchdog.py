"""U179 slice A: an idle tool's watcher runs the long-wait scan itself and wakes its session once per stalled wait.

Receipt (2026-10-10, user report): "the procedure for a long wait does not run". `stall.scan` had one automatic
caller, the per-prompt hook, so a session that waited without a prompt never scanned (.work/d4/report.md).
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import presence, stall, watch

REPO = Path(__file__).resolve().parents[1]
ASK = "ACTIONABLE_DELTA VERDICT_REQUESTED=YES review U1"


def _queue(root: Path, target: str, name: str, actor: str, age_s: float, message: str = ASK) -> None:
    folder = root / ".coord" / "mailbox" / "delivery" / "queued" / target
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.json"
    path.write_text(json.dumps({"actor": actor, "message": message, "message_id": name}), encoding="utf-8")
    then = time.time() - age_s
    os.utime(path, (then, then))


class Clock:
    """Wall time that moves only when the watcher sleeps, so a four-hour watch runs in milliseconds."""

    def __init__(self):
        self.now = time.time()

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".coord").mkdir()
        for tool in ("claude", "antigravity"):
            presence.mark(self.root, tool, "ACTIVE")
        # The hook is the route that failed: no test here may pass through it.
        patcher = mock.patch.object(stall, "hook_lines", side_effect=AssertionError("the hook is not the route"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _watch(self, tools=("claude",), timeout_s=300.0, policy="structured"):
        clock = Clock()
        return watch.watch(self.root, tools, timeout_s=timeout_s, clock=clock, sleep=clock.sleep, policy=policy)


class IdleWatcher(Base):
    def test_stalled_wait_wakes_an_idle_watcher_without_a_prompt(self):
        _queue(self.root, "codex", "relay_a", "claude", 2 * 3600)
        found = self._watch()
        self.assertEqual("STALLED_WAIT", found["reason"])
        self.assertEqual("letter:codex:relay_a", found["item"])
        self.assertEqual("codex", found["waiting_on"])
        self.assertEqual("antigravity", found["owner"])  # verdict route with Codex away
        self.assertGreaterEqual(found["age_s"], 2 * 3600)

    def test_a_wait_under_the_limit_does_not_wake(self):
        _queue(self.root, "codex", "relay_a", "claude", stall.MAX_WAIT_S - 120)
        self.assertIsNone(self._watch(timeout_s=60.0))

    def test_the_wait_becomes_due_while_the_watcher_idles(self):
        _queue(self.root, "codex", "relay_a", "claude", stall.MAX_WAIT_S - 120)
        found = self._watch(timeout_s=600.0)
        self.assertEqual("STALLED_WAIT", found["reason"])

    def test_one_wake_per_wait_and_a_new_wait_wakes_again(self):
        _queue(self.root, "codex", "relay_a", "claude", 2 * 3600)
        self.assertEqual("STALLED_WAIT", self._watch()["reason"])
        self.assertIsNone(self._watch(), "a re-armed watcher must not wake twice for the same wait")
        _queue(self.root, "codex", "relay_b", "claude", 2 * 3600)
        again = self._watch()
        self.assertEqual("letter:codex:relay_b", again["item"])

    def test_a_tool_with_no_part_in_the_wait_is_not_woken(self):
        # Codex wrote it, Codex is waited on, Antigravity is the takeover owner: Claude pays no turn for it.
        _queue(self.root, "codex", "relay_a", "codex", 2 * 3600)
        self.assertIsNone(self._watch(tools=("claude",)))
        self.assertEqual("STALLED_WAIT", self._watch(tools=("antigravity",))["reason"])

    def test_a_wait_nobody_can_take_wakes_its_author(self):
        presence.mark(self.root, "antigravity", "LIMITED", lease=True)
        _queue(self.root, "codex", "relay_a", "claude", 2 * 3600)
        found = self._watch()
        self.assertEqual("STALLED_WAIT", found["reason"])
        self.assertIsNone(found["owner"])

    def test_a_status_note_is_not_a_wait(self):
        _queue(self.root, "codex", "relay_a", "claude", 2 * 3600, message="status only")
        self.assertIsNone(self._watch())


class Cadence(Base):
    def test_scan_runs_on_its_own_interval_not_every_inbox_scan(self):
        with mock.patch.object(stall, "scan", wraps=stall.scan) as scan:
            self.assertIsNone(self._watch(timeout_s=600.0))
        allowed = 600.0 / watch.STALL_SCAN_S + 2
        self.assertGreaterEqual(scan.call_count, 2)
        self.assertLessEqual(scan.call_count, allowed)

    def test_a_failing_scan_never_ends_the_watch(self):
        _queue(self.root, "codex", "relay_a", "claude", 2 * 3600)
        with mock.patch.object(stall, "scan", side_effect=OSError("locked")):
            self.assertIsNone(self._watch(timeout_s=200.0))

    def test_the_legacy_policy_does_not_scan(self):
        _queue(self.root, "codex", "relay_a", "claude", 2 * 3600)
        with mock.patch.object(stall, "scan", side_effect=AssertionError("legacy watch must not scan")):
            self.assertIsNone(self._watch(policy="legacy"))


class RealProcesses(Base):
    def _cli(self):
        return subprocess.run(
            [sys.executable, "-m", "v7_harness.cli", "coord", "watch", "--project", str(self.root), "--target",
             "claude", "--wakes-session", "--timeout", "20"],
            capture_output=True, text=True, encoding="utf-8", timeout=120, cwd=REPO)

    def test_an_idle_watch_process_exits_with_the_stalled_wait(self):
        _queue(self.root, "codex", "relay_a", "claude", stall.MAX_WAIT_S + 1)
        done = self._cli()
        self.assertEqual(0, done.returncode, done.stdout[-300:] + done.stderr[-300:])
        result = json.loads(done.stdout.splitlines()[-1])
        self.assertEqual("STALLED_WAIT", result["reason"])
        self.assertEqual("letter:codex:relay_a", result["item"])

    def test_parallel_watch_processes_wake_once(self):
        # One watcher per target holds the lock; the others leave with ALREADY_WATCHING or see the claim.
        _queue(self.root, "codex", "relay_a", "claude", 2 * 3600)
        command = [sys.executable, "-m", "v7_harness.cli", "coord", "watch", "--project", str(self.root),
                   "--target", "claude", "--wakes-session", "--timeout", "6"]
        running = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, cwd=REPO)
                   for _ in range(8)]
        reasons = []
        for process in running:
            out, _ = process.communicate(timeout=120)
            reasons.append(json.loads(out.splitlines()[-1])["reason"])
        self.assertEqual(1, reasons.count("STALLED_WAIT"), reasons)


if __name__ == "__main__":
    unittest.main()
