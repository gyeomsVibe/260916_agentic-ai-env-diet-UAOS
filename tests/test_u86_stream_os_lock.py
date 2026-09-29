"""U86: the stream lock is an OS file lock; a live, paused holder keeps it and a dead holder's lock frees at once.

Before U86 `_exclusive` was an O_EXCL lock file taken over when its mtime was 60 s old. The file's age says nothing about
its holder: a holder paused longer than that (suspended laptop, debugger, a slow retention rollup) lost the lock while
still writing, so two writers could overlap - the U83 defect in the mailbox guard. A holder that crashed instead blocked
every writer for up to 60 s. The OS lock is released by the OS when the holder dies and is never taken from a live one.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import stream
from v7_harness.coord.stream import StreamBusy, _exclusive

ROOT = Path(__file__).resolve().parents[1]
HOLDER = (
    "import os, sys\n"
    "from pathlib import Path\n"
    "from v7_harness.coord.stream import _exclusive\n"
    "with _exclusive(Path(sys.argv[1])):\n"
    "    print('held', flush=True)\n"
    "    if sys.argv[2] == 'crash':\n"
    "        os._exit(0)  # dies holding the lock: no finally, no unlink\n"
    "    sys.stdin.readline()  # paused until the test lets it go\n"
    "print('released', flush=True)\n"
)


class StreamOsLockTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.lock = Path(tmp.name) / ".stream.lock"

    def _holder(self, mode: str) -> subprocess.Popen:
        proc = subprocess.Popen([sys.executable, "-c", HOLDER, str(self.lock), mode], cwd=ROOT,
                                env=dict(os.environ, PYTHONPATH=str(ROOT)), stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, text=True)
        self.addCleanup(proc.kill)
        self.assertEqual("held", proc.stdout.readline().strip())
        return proc

    def test_a_paused_holder_keeps_the_lock_however_old_the_file(self) -> None:
        proc = self._holder("pause")
        old = time.time() - 3600  # far past the former 60 s takeover age
        os.utime(self.lock, (old, old))
        with mock.patch.object(stream, "LOCK_TIMEOUT_S", 0.5):
            with self.assertRaises(StreamBusy):
                with _exclusive(self.lock):
                    self.fail("entered while a live holder had the lock")
        self.assertTrue(self.lock.exists())
        proc.stdin.write("\n")
        proc.stdin.flush()
        self.assertEqual("released", proc.stdout.readline().strip())
        self.assertEqual(0, proc.wait(timeout=30))
        with _exclusive(self.lock):
            pass

    def test_a_crashed_holder_frees_the_lock_without_waiting(self) -> None:
        proc = self._holder("crash")
        self.assertEqual(0, proc.wait(timeout=30))
        self.assertTrue(self.lock.exists(), "the crashed holder left its lock file")
        started = time.monotonic()
        with mock.patch.object(stream, "LOCK_TIMEOUT_S", 2.0):  # a fresh file used to block for the full timeout
            with _exclusive(self.lock):
                pass
        self.assertLess(time.monotonic() - started, 1.0)

    def test_the_lock_file_is_kept_and_reused(self) -> None:
        for _ in range(3):
            with _exclusive(self.lock):
                self.assertTrue(self.lock.exists())
        self.assertTrue(self.lock.exists())


if __name__ == "__main__":
    unittest.main()
