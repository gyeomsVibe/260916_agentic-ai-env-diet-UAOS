"""Independent U42-R1 Windows scheduler wrapper regression."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from v7_harness import rsi_release


class WindowsWrapperTests(unittest.TestCase):
    def test_install_materializes_and_schedules_absolute_wrapper(self) -> None:
        calls, stored = [], {}

        def run(command, **kwargs):
            command = list(command)
            calls.append((command, kwargs))
            if "/XML" in command and command[1] == "/Create":
                stored["xml"] = Path(command[command.index("/XML") + 1]).read_text(encoding="utf-16")
            if "/XML" in command and command[1] == "/Query":
                return subprocess.CompletedProcess(command, 0, stored["xml"], "")
            return subprocess.CompletedProcess(command, 0, "SUCCESS", "")

        with tempfile.TemporaryDirectory() as d:
            project = Path(d).resolve()
            launcher = project / "uaos.py"  # U157: the task runs the installed launcher, which must exist
            launcher.write_text("", encoding="utf-8")
            result = rsi_release.windows_schedule(
                # U157 amendment: install refuses a missing interpreter, so this one must exist.
                project, sys.executable, action="install", apply=True, run=run, launcher=launcher,
            )
            wrapper = Path(result["wrapper_path"])
            self.assertTrue(wrapper.is_absolute())
            self.assertTrue(wrapper.is_file())
            # U157 amendment: the task is imported as XML, so the wrapper is the Exec/Command element, not /TR.
            command = ET.fromstring(stored["xml"][stored["xml"].index("<Task"):]).findtext(
                ".//{http://schemas.microsoft.com/windows/2004/02/mit/task}Command")
            self.assertEqual(str(wrapper), command)
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
