"""U183: a live pid in loop.pid is never handed over on a file time; only the kernel's DEAD answer frees the project.

Receipts: ledger BLOCKED 20261010T2206-claude-0001 (a reused pid blocked both launchers after a reboot) and Codex
return review U183 (PR 145 answered that receipt by comparing the file time with the process creation time, so a
restored or touched file time handed a living owner's project to a second loop). A file time is writable by anyone;
the block is kept and reported, the bypass is not.
"""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import sentinel_lease
from v7_harness.coord.sentinel_lease import LeaseUnavailable, lease


class PidReuse(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pid_file = self.root / ".work" / "sentinel" / "loop.pid"
        self.pid_file.parent.mkdir(parents=True)
        self.before = time.time()
        self.other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(self.other.wait)
        self.addCleanup(self.other.kill)
        self.pid_file.write_text(str(self.other.pid), encoding="utf-8")

    def date_file(self, when):
        os.utime(self.pid_file, (when, when))

    def refused(self, reason):
        with self.assertRaisesRegex(LeaseUnavailable, reason):
            with lease(self.root):
                self.fail("entered")
        self.assertEqual(str(self.other.pid), self.pid_file.read_text(encoding="utf-8"))  # evidence is kept

    def test_file_written_long_before_the_process_existed_still_refuses(self):
        for when in (self.before - 86400, 1):
            with self.subTest(when=when):
                self.date_file(when)
                self.refused("LEGACY_ALIVE")

    def test_file_written_after_the_process_started_refuses(self):
        self.date_file(time.time())
        self.refused("LEGACY_ALIVE")

    def test_unknown_process_state_fails_closed_whatever_the_file_time(self):
        self.date_file(self.before - 86400)
        with mock.patch.object(sentinel_lease, "pid_state", return_value="UNKNOWN"):
            self.refused("LEGACY_UNKNOWN")

    def test_the_cli_reports_an_unverified_duplicate_and_runs_no_cycle(self):
        self.date_file(self.before - 86400)
        done = subprocess.run([sys.executable, "-m", "v7_harness.cli", "coord", "sentinel", "--project", str(self.root)],
                              capture_output=True, text=True, timeout=60, cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(0, done.returncode, done.stderr[-300:])
        self.assertIn('"skipped": "ALREADY_RUNNING"', done.stdout)
        self.assertIn('"operator_verified": false', done.stdout)
        self.assertNotIn("paid_api_calls", done.stdout)


if __name__ == "__main__":
    unittest.main()
