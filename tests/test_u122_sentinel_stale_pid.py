"""U122: a sentinel pid file whose pid Windows reused for an unrelated process must not block the loop.

Receipt (2026-10-02): .work/sentinel/loop.pid held 10076, the dead loop's pid, which a Claude.exe renderer now
used; every logon start logged ALREADY_RUNNING and the 0-token sentinel stayed down for about 17 hours (no RSI
review letters after 2026-10-01 20:58). A live loop rewrites its pid file every cycle, so a file older than three
cycles (floor 180 s) is stale whatever process now holds that pid.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from v7_harness.cli import _sentinel_loop_owner

PYTHON = sys.executable


class SentinelStalePidTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.pid_file = Path(self._tmp.name) / "loop.pid"
        # Stands in for the unrelated process that inherited the dead loop's pid.
        self.other = subprocess.Popen([PYTHON, "-c", "import time; time.sleep(30)"])
        self.pid_file.write_text(str(self.other.pid), encoding="utf-8")

    def tearDown(self) -> None:
        self.other.kill()
        self.other.wait()
        self._tmp.cleanup()

    def _age(self, seconds: float) -> None:
        stamp = time.time() - seconds
        os.utime(self.pid_file, (stamp, stamp))

    def test_reused_pid_with_old_file_is_not_an_owner(self) -> None:
        self._age(3600)
        self.assertEqual(0, _sentinel_loop_owner(self.pid_file, 60))

    def test_fresh_file_with_live_pid_is_the_owner(self) -> None:
        self.assertEqual(self.other.pid, _sentinel_loop_owner(self.pid_file, 60))

    def test_threshold_scales_with_interval(self) -> None:
        self._age(300)
        self.assertEqual(0, _sentinel_loop_owner(self.pid_file, 60))
        self.assertEqual(self.other.pid, _sentinel_loop_owner(self.pid_file, 120))

    def test_missing_or_garbled_file_is_no_owner(self) -> None:
        self.pid_file.write_text("x", encoding="utf-8")
        self.assertEqual(0, _sentinel_loop_owner(self.pid_file, 60))
        self.pid_file.unlink()
        self.assertEqual(0, _sentinel_loop_owner(self.pid_file, 60))


if __name__ == "__main__":
    unittest.main()
