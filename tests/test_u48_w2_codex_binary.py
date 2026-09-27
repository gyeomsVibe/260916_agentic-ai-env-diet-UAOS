"""U48-W2: the pilot judge finds the codex npm shim on Windows instead of failing with FileNotFoundError."""

from __future__ import annotations

import inspect
import shutil
import subprocess
import unittest
from unittest import mock

from v7_harness import judge


class CodexBinaryResolution(unittest.TestCase):
    def test_run_judge_default_runner_resolves_the_binary(self) -> None:
        self.assertIs(judge.run_resolved, inspect.signature(judge.run_judge).parameters["runner"].default)

    def test_run_resolved_uses_the_path_lookup_and_keeps_the_arguments(self) -> None:
        with mock.patch.object(judge.shutil, "which", return_value=r"C:\npm\codex.CMD") as which, \
             mock.patch.object(judge.subprocess, "run", return_value="done") as run:
            self.assertEqual("done", judge.run_resolved(["codex", "exec", "-"], input=b"x", timeout=5))
        which.assert_called_once_with("codex")
        run.assert_called_once_with([r"C:\npm\codex.CMD", "exec", "-"], input=b"x", timeout=5)

    def test_missing_binary_keeps_its_bare_name(self) -> None:
        with mock.patch.object(judge.shutil, "which", return_value=None), \
             mock.patch.object(judge.subprocess, "run", side_effect=FileNotFoundError("codex")) as run:
            with self.assertRaises(FileNotFoundError):
                judge.run_resolved(["codex", "--version"])
        self.assertEqual(["codex", "--version"], run.call_args.args[0])

    @unittest.skipUnless(shutil.which(judge.CODEX_BINARY), "codex CLI not installed")
    def test_real_codex_version_starts(self) -> None:
        # `--version` makes no model call. Before the fix a bare "codex" raised FileNotFoundError on Windows.
        done = judge.run_resolved([judge.CODEX_BINARY, "--version"], capture_output=True, timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)


if __name__ == "__main__":
    unittest.main()
