"""U310: transient coordination lock contention must not terminate hooks or watchers."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import presence, requests, stall, stream, watch
from tests.test_u179_wait_watchdog import Clock, _queue


class StreamBusyRecovery(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".coord").mkdir()
        for tool in ("claude", "antigravity"):
            presence.mark(self.root, tool, "ACTIVE")

    def held_lock(self):
        lock = self.root / ".coord" / "stall" / "stall.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock, os.O_CREAT | os.O_RDWR)
        self.assertTrue(stream._try_lock(fd))
        return fd

    def test_watch_retries_after_real_stall_lock_is_released(self):
        _queue(self.root, "codex", "relay_u310", "claude", 2 * 3600)
        fd = self.held_lock()
        released = False
        clock = Clock()
        started = clock()

        def release():
            nonlocal released
            if not released:
                released = True
                stream._unlock(fd)
                os.close(fd)

        def tick(seconds):
            clock.sleep(seconds)
            if clock() - started >= watch.STALL_SCAN_S:
                release()

        try:
            with mock.patch.object(stream, "LOCK_TIMEOUT_S", 0.01):
                with self.assertRaises(stream.StreamBusy):
                    stall.scan(self.root, "claude", now=clock())
                found = watch.watch(self.root, ("claude",), policy="structured",
                                    timeout_s=watch.STALL_SCAN_S * 2 + 10,
                                    clock=clock, sleep=tick)
        finally:
            release()
        self.assertIsNotNone(found)
        self.assertEqual("STALLED_WAIT", found["reason"])
        self.assertEqual("letter:codex:relay_u310", found["item"])

    def test_hook_defers_on_held_lock_without_schedule_mutation_then_recovers(self):
        _queue(self.root, "codex", "relay_hook", "claude", 2 * 3600)
        schedule = self.root / ".coord" / "master_schedule.json"
        before = schedule.read_bytes() if schedule.exists() else None
        fd = self.held_lock()
        try:
            with mock.patch.object(stream, "LOCK_TIMEOUT_S", 0.01):
                self.assertEqual("", stall.hook_lines(self.root, "claude"))
            self.assertEqual(before, schedule.read_bytes() if schedule.exists() else None)
        finally:
            stream._unlock(fd)
            os.close(fd)
        self.assertIn("WAIT IS FAILURE", stall.hook_lines(self.root, "claude"))

    def test_request_scan_retries_after_stream_busy(self):
        row = {"requester": "codex", "request_id": "request_u310", "outcome": "PASS"}
        with mock.patch.object(requests, "scan", side_effect=[stream.StreamBusy("STREAM_LOCK_TIMEOUT"), []]):
            with mock.patch.object(requests, "answered", return_value=[row]):
                with mock.patch.object(requests, "claim_wake", return_value=True):
                    self.assertIsNone(watch._request_wake(self.root, ("codex",), "desk", 20, 10))
                    self.assertEqual("REQUEST_ANSWERED", watch._request_wake(self.root, ("codex",), "desk", 21, 10)["reason"])


if __name__ == "__main__":
    unittest.main()
