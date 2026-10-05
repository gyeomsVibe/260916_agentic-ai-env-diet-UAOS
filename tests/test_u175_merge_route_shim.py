"""U175: `coord merge` must start the Codex merger on Windows, where `codex` is an npm shim (codex.cmd).

Receipt (2026-10-05, coord log 20261005T1155-claude-0001): `coord merge --pr 136` skipped Antigravity (LIMITED) and the
Codex route failed with FileNotFoundError before Codex started, because subprocess.run(["codex", ...]) does not apply
PATHEXT. The same cause broke every codex judgement once (judge.run_resolved, U48-W1 note).
"""

from __future__ import annotations

import inspect
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import merge_route


class MergeRouteResolvesShim(unittest.TestCase):
    def test_default_runner_resolves_argv0(self):
        seen = []

        def fake_run(argv, **kwargs):
            seen.append(argv)
            return subprocess.CompletedProcess(argv, 1, b"", b"")

        default = inspect.signature(merge_route.merge).parameters["runner"].default
        self.assertIsNot(subprocess.run, default, "the bare subprocess.run default cannot start codex.cmd")
        with mock.patch("shutil.which", lambda name: "C:/shim/" + name + ".cmd"), \
                mock.patch("subprocess.run", fake_run):
            with tempfile.TemporaryDirectory() as tmp:
                merge_route.merge(Path(tmp), 7, "a" * 40, "relay_" + "0" * 32,
                                  desk={t: {"state": "ACTIVE"} for t in merge_route.MERGERS})
        self.assertTrue(seen, "the default runner was never used")
        self.assertEqual("C:/shim/gh.cmd", seen[0][0])

    @unittest.skipUnless(sys.platform == "win32", "PATHEXT shims exist only on Windows")
    def test_real_cmd_shim_starts_through_default_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            shim = Path(tmp) / "u175shim.cmd"
            shim.write_text("@echo off\r\nexit /b 0\r\n", encoding="ascii")
            env_path = tmp + os.pathsep + os.environ.get("PATH", "")
            with mock.patch.dict(os.environ, {"PATH": env_path}):
                with self.assertRaises(FileNotFoundError):  # the receipt: a bare name never reaches the shim
                    subprocess.run(["u175shim"], capture_output=True, timeout=30)
                runner = inspect.signature(merge_route.merge).parameters["runner"].default
                if runner is None:
                    from v7_harness.judge import run_resolved as runner
                done = runner(["u175shim"], capture_output=True, timeout=30)
        self.assertEqual(0, done.returncode)


if __name__ == "__main__":
    unittest.main()
