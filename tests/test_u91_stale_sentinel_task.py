"""U91: `--check` reports a scheduled sentinel that runs a checkout instead of the installed runtime.

Seen 2026-09-29: after U88 merged, the P1 wake came back. A hand-made "UAOS Sentinel 30m" task ran
`python -m v7_harness.cli coord sentinel` in the desk checkout, dozens of merges behind, and its loop lock made the
runtime sentinel (sentinel_*.cmd via ~/.uaos/uaos.py) skip with ALREADY_RUNNING at every logon.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from v7_harness import global_install
from v7_harness.global_install import stale_sentinel_tasks

STALE = {"name": "UAOS Sentinel 30m",
         "run": 'C:\\Python314\\python.exe -m v7_harness.cli coord sentinel --project "D:\\p" --loop --interval 1800'}
CURRENT = {"name": "UAOS Sentinel p", "run": "C:\\Users\\u\\.uaos\\sentinel_p.cmd "}
LAUNCHER = {"name": "UAOS direct", "run": 'python.exe "C:\\Users\\u\\.uaos\\uaos.py" coord sentinel --project "D:\\p"'}
OTHER = {"name": "Backup", "run": "robocopy a b"}


class _Done:
    def __init__(self, returncode: int, stdout: str) -> None:
        self.returncode, self.stdout, self.stderr = returncode, stdout, ""


def _run(payload: object, returncode: int = 0):
    def run(argv, **_kwargs):
        return _Done(returncode, payload if isinstance(payload, str) else json.dumps(payload))
    return run


class StaleSentinelTaskTests(unittest.TestCase):
    def test_only_a_checkout_sentinel_is_stale(self) -> None:
        found = stale_sentinel_tasks(run=_run([STALE, CURRENT, LAUNCHER, OTHER]), system="Windows")
        self.assertEqual(["UAOS Sentinel 30m"], [task["name"] for task in found])

    def test_a_single_task_object_is_read(self) -> None:
        self.assertEqual(1, len(stale_sentinel_tasks(run=_run(STALE), system="Windows")))

    def test_a_failed_query_is_unknown_not_clean(self) -> None:
        self.assertIsNone(stale_sentinel_tasks(run=_run("", returncode=1), system="Windows"))
        self.assertIsNone(stale_sentinel_tasks(run=_run("not json"), system="Windows"))
        self.assertEqual([], stale_sentinel_tasks(run=_run([STALE]), system="Linux"))

    def test_check_counts_a_stale_task_as_drift(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            with mock.patch.object(global_install, "stale_sentinel_tasks", return_value=[STALE]), \
                    mock.patch.object(global_install.Path, "home", return_value=home), redirect_stdout(io.StringIO()) as out:
                code = global_install.main(["--check", "--no-rules", "--home", str(home)])
            report = json.loads(out.getvalue())
            self.assertEqual(1, code)
            self.assertIn("stale sentinel task: UAOS Sentinel 30m", report["drift"])
            self.assertIn("--register-sentinel", report["stale_sentinel_advice"])

    def test_check_with_another_home_does_not_query_this_pc(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(global_install, "stale_sentinel_tasks", side_effect=AssertionError("queried")), \
                    redirect_stdout(io.StringIO()):
                global_install.main(["--check", "--no-rules", "--home", d])


if __name__ == "__main__":
    unittest.main()
