"""U122-F1: a failed heartbeat write must not kill the resident sentinel loop.

Receipt (2026-10-02, Antigravity audit of U122 via the U120 auto reply, judged by Claude against the code): U122 made
the loop rewrite .work/sentinel/loop.pid every cycle but left that write outside the per-cycle try, so one transient
PermissionError (antivirus or backup lock) ends the 0-token sentinel - the same silent stop U122 fixed.
"""
from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from v7_harness.cli import main

_REAL_WRITE_TEXT = Path.write_text


class _Stop(Exception):
    pass


class HeartbeatWriteFailureTest(unittest.TestCase):
    def test_loop_reports_a_locked_pid_file_and_goes_on(self) -> None:
        calls = {"pid": 0}

        def flaky_write(self: Path, *args, **kwargs):
            if self.name == "loop.pid":
                calls["pid"] += 1
                if calls["pid"] == 1:
                    raise PermissionError("locked by another process")
            return _REAL_WRITE_TEXT(self, *args, **kwargs)

        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "s.log"
            with mock.patch.object(Path, "write_text", autospec=True, side_effect=flaky_write), \
                    mock.patch("time.sleep", side_effect=[None, _Stop()]), redirect_stdout(io.StringIO()):
                with self.assertRaises(_Stop):
                    main(["coord", "sentinel", "--project", d, "--loop", "--interval", "1", "--log", str(log)])
            lines = log.read_text(encoding="utf-8").splitlines()
            self.assertEqual(2, len(lines))
            self.assertIn("PermissionError", lines[0])
            self.assertGreaterEqual(calls["pid"], 2)


if __name__ == "__main__":
    unittest.main()
