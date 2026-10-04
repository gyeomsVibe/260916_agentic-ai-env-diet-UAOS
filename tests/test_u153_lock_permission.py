"""U153: a Windows delete-pending lock file counts as busy, so a parallel record is never lost.

Receipt (2026-10-04): tests.test_u150_repeat_error.Record.test_parallel_records_lose_no_line failed 2/15 (Codex,
origin/main 7b59a3c) and 1/30 (Claude). Traceback: repeat_error._Lock.__enter__ -> os.open(O_CREAT|O_EXCL) raised
PermissionError [Errno 13] on user_error_reports.lock. On Windows a file another thread just unlinked stays
"delete pending" for a moment and CreateFile answers ACCESS_DENIED, not ERROR_FILE_EXISTS, so the lock treated a
busy lock as fatal and the report row was dropped. Second receipt of this class after U48-R1 (launcher race).
"""

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import repeat_error as re_

T0 = 1_790_000_000.0


class LockTreatsDeletePendingAsBusy(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        (self.project / ".coord").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_permission_error_once_then_free_records_the_row(self):
        real_open = os.open
        calls = []

        def flaky_open(path, flags, *args, **kwargs):
            if str(path).endswith(".lock") and not calls:
                calls.append(path)
                raise PermissionError(13, "Permission denied", str(path))
            return real_open(path, flags, *args, **kwargs)

        with mock.patch.object(re_.os, "open", side_effect=flaky_open):
            re_.record(self.project, "claude", "메시지 ID 충돌 결함 고쳐줘", now=T0)
        self.assertEqual(1, len(calls))
        self.assertEqual(1, len(re_.load(self.project)))

    def test_permission_error_that_never_clears_still_times_out(self):
        def always_denied(path, flags, *args, **kwargs):
            raise PermissionError(13, "Permission denied", str(path))

        lock = self.project / ".coord" / "x.lock"
        started = time.monotonic()
        with mock.patch.object(re_, "LOCK_WAIT_S", 0.2), \
                mock.patch.object(re_.os, "open", side_effect=always_denied):
            with self.assertRaises(TimeoutError):
                with re_._Lock(lock):
                    pass
        self.assertLess(time.monotonic() - started, 5)


if __name__ == "__main__":
    unittest.main()
