"""U359: a lock left by a killed process no longer blocks every prompt hook for LOCK_WAIT_S.

Receipt (real use, 2026-11-22, live 0.6.13 cProfile): the PreInvocation hook took 14.4 s. repeat_error.on_prompt ->
deliver_unseen -> _Lock.__enter__ slept 486 x 0.02 s = 10.0 s against `.coord/usage/user_error_receipts.lock`, 26 days
old, then raised TimeoutError, which cli.py swallowed. The 6.0 s hook ack budget was gone, so desk_delta.ack() never
ran. A lock older than LOCK_STALE_S is cleared, and a holder only removes the lock it wrote itself.
"""

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import repeat_error as re_

T0 = time.time()


class StaleLock(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name)
        self.usage = self.project / ".coord" / "usage"
        self.usage.mkdir(parents=True)

    def _lock(self, name, age_s):
        path = self.usage / name
        path.write_text("99999:dead", encoding="ascii")
        stamp = time.time() - age_s
        os.utime(path, (stamp, stamp))
        return path

    def test_stale_receipts_lock_is_cleared_at_once(self):
        lock = self._lock("user_error_receipts.lock", 120)
        re_.record(self.project, "codex", "메시지 ID 충돌 결함 고쳐줘", now=T0)
        start = time.monotonic()
        line = re_.on_prompt(self.project, "claude", "안녕", now=T0 + 1)
        self.assertLess(time.monotonic() - start, 1.0)
        self.assertIn("USER ERROR REPORTED TO codex", line)
        self.assertFalse(lock.exists(), "the lock is released on exit")

    def test_stale_reports_lock_is_cleared_and_record_succeeds(self):
        lock = self._lock("user_error_reports.lock", 120)
        start = time.monotonic()
        got = re_.record(self.project, "claude", "결함 고쳐줘", now=T0)
        self.assertLess(time.monotonic() - start, 1.0)
        self.assertEqual(1, got["count"])
        self.assertEqual(1, len(re_.load(self.project)))
        self.assertFalse(lock.exists())

    def test_fresh_lock_is_not_broken_and_times_out(self):
        lock = self._lock("user_error_reports.lock", 0)
        with mock.patch.object(re_, "LOCK_WAIT_S", 0.3):
            start = time.monotonic()
            with self.assertRaises(TimeoutError):
                re_.record(self.project, "claude", "결함 고쳐줘", now=T0)
            self.assertGreaterEqual(time.monotonic() - start, 0.3)
        self.assertTrue(lock.exists(), "a live holder's lock is never removed")
        self.assertEqual("99999:dead", lock.read_text(encoding="ascii"))

    def test_old_holder_does_not_unlink_a_new_holders_lock(self):
        path = self.usage / "x.lock"
        old = re_._Lock(path)
        old.__enter__()
        path.write_text("12345:newholder", encoding="ascii")  # the lock expired and someone else took it
        old.__exit__(None, None, None)
        self.assertTrue(path.exists())
        self.assertEqual("12345:newholder", path.read_text(encoding="ascii"))
        own = re_._Lock(self.usage / "y.lock")
        with own:
            self.assertTrue((self.usage / "y.lock").exists())
        self.assertFalse((self.usage / "y.lock").exists())

    def test_parallel_record_and_deliver_lose_no_line(self):
        self._lock("user_error_reports.lock", 120)
        self._lock("user_error_receipts.lock", 120)

        def rec(i):
            re_.record(self.project, f"tool{i % 3}", f"결함 {i} 고쳐줘 case{i}", now=T0 + i)

        def dlv(i):
            re_.deliver_unseen(self.project, "claude", now=T0 + 20 + i)

        workers = [threading.Thread(target=rec, args=(i,)) for i in range(12)]
        workers += [threading.Thread(target=dlv, args=(i,)) for i in range(6)]
        for w in workers:
            w.start()
        for w in workers:
            w.join()
        self.assertEqual(12, len(re_.load(self.project)))
        receipts = re_._read_jsonl(re_._receipts(self.project))
        self.assertEqual(len(receipts), len({r["report"] for r in receipts}), "each report receipted once")
        self.assertFalse(any(self.usage.glob("*.lock")))


if __name__ == "__main__":
    unittest.main()
