"""Independent U42-R1 Windows scheduler wrapper regression."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from v7_harness import rsi_release


class WindowsWrapperTests(unittest.TestCase):
    def test_install_materializes_and_schedules_absolute_wrapper(self) -> None:
        calls = []

        def run(command, **kwargs):
            calls.append((list(command), kwargs))
            return subprocess.CompletedProcess(command, 0, "SUCCESS", "")

        with tempfile.TemporaryDirectory() as d:
            project = Path(d).resolve()
            result = rsi_release.windows_schedule(
                project, r"C:\Python\python.exe", action="install", apply=True, run=run,
            )
            wrapper = Path(result["wrapper_path"])
            self.assertTrue(wrapper.is_absolute())
            self.assertTrue(wrapper.is_file())
            self.assertEqual(str(wrapper), calls[0][0][calls[0][0].index("/TR") + 1])
            self.assertEqual(project, calls[0][1]["cwd"])
            self.assertIn(str(project), wrapper.read_text(encoding="utf-8"))

    def test_status_tolerates_missing_decoded_output(self) -> None:
        def run(command, **kwargs):
            self.assertEqual("utf-8", kwargs["encoding"])
            self.assertEqual("replace", kwargs["errors"])
            return subprocess.CompletedProcess(command, 0, None, None)

        result = rsi_release.windows_schedule(
            Path.cwd(), r"C:\Python\python.exe", action="status", apply=True, run=run,
        )
        self.assertTrue(result["ok"])
        self.assertEqual("", result["output"])
        self.assertEqual("", result["error"])


if __name__ == "__main__":
    unittest.main()
