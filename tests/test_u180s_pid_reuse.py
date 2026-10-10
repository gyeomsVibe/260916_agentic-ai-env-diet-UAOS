"""U180S rework: a stale loop.pid whose pid an unrelated process now owns must not block the sentinel for ever.

Receipt: ledger BLOCKED 20261010T2206-claude-0001. After a reboot the file still holds the last pid, Windows reuses
pids, and both launchers answered ALREADY_RUNNING with exit 0 while no sentinel ran (U122 regression).
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

WINDOWS = os.name == "nt"


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

    @unittest.skipUnless(WINDOWS, "process creation time is read on Windows only")
    def test_file_written_long_before_the_process_existed_is_stale(self):
        self.date_file(self.before - 86400)
        entered = False
        with lease(self.root):
            entered = True
        self.assertTrue(entered)
        self.assertEqual(str(self.other.pid), self.pid_file.read_text(encoding="utf-8"))  # evidence is kept

    @unittest.skipUnless(WINDOWS, "process creation time is read on Windows only")
    def test_file_inside_the_margin_still_belongs_to_the_live_process(self):
        self.date_file(self.before - sentinel_lease.REUSE_MARGIN_S / 2)
        with self.assertRaisesRegex(LeaseUnavailable, "LEGACY_ALIVE"):
            with lease(self.root):
                self.fail("entered")

    def test_unknown_creation_time_fails_closed(self):
        self.date_file(self.before - 86400)
        with mock.patch.object(sentinel_lease, "created_at", return_value=None):
            with self.assertRaisesRegex(LeaseUnavailable, "LEGACY_ALIVE"):
                with lease(self.root):
                    self.fail("entered")

    @unittest.skipUnless(WINDOWS, "process creation time is read on Windows only")
    def test_one_cycle_runs_through_the_cli(self):
        self.date_file(self.before - 86400)
        done = subprocess.run([sys.executable, "-m", "v7_harness.cli", "coord", "sentinel", "--project", str(self.root)],
                              capture_output=True, text=True, timeout=60, cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(0, done.returncode, done.stderr[-300:])
        self.assertNotIn("ALREADY_RUNNING", done.stdout)
        self.assertIn("paid_api_calls", done.stdout)


if __name__ == "__main__":
    unittest.main()
