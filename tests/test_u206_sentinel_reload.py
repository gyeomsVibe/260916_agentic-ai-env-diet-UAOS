"""U206: a runtime install restarts the resident sentinel loops on the new code.

Receipt (2026-10-16): the boot launcher's loop started 10-15 22:09 kept running that code; its log never shows the U200
`agy_backlog` key, so the U200 and U203 installs never reached the resident loop and stalled steps went unscanned.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from v7_harness.coord import boot_task

REPO = Path(__file__).resolve().parents[1]


class Reload(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.project = base / "project"
        (self.project / ".coord").mkdir(parents=True)
        uaos = base / "home" / ".uaos"
        (uaos / "runtime").mkdir(parents=True)
        self.home = uaos.parent
        (uaos / "sentinel_project.cmd").write_text(
            f'@echo off\r\n"python" "%~dp0uaos.py" coord sentinel --project "{self.project}" --loop\r\n',
            encoding="utf-8")
        self.pids = base / "pids.txt"
        # Each fake loop records its pid and lives until it is ended.
        (uaos / "uaos.py").write_text(
            f"import os, time\nopen({str(self.pids)!r}, 'a').write(f'{{os.getpid()}}\\n')\ntime.sleep(120)\n",
            encoding="utf-8")
        self.set_version("1.0.0-aaaa")

    def set_version(self, version):
        (self.home / ".uaos" / "runtime" / "current.json").write_text(json.dumps({"version": version}),
                                                                      encoding="utf-8")

    def started(self, count, deadline_s=30):
        deadline = time.monotonic() + deadline_s
        while time.monotonic() < deadline:
            if self.pids.exists() and len(self.pids.read_text().split()) >= count:
                return self.pids.read_text().split()
            time.sleep(0.2)
        self.fail(f"fewer than {count} loops started")

    def test_version_reads_the_installed_runtime(self):
        self.assertEqual("1.0.0-aaaa", boot_task._version(self.home))
        (self.home / ".uaos" / "runtime" / "current.json").write_text("{", encoding="utf-8")
        self.assertEqual("", boot_task._version(self.home))

    def test_a_new_install_restarts_the_loop(self):
        launcher = subprocess.Popen([sys.executable, "-m", "v7_harness.cli", "coord", "boot", "--launch", "--home",
                                     str(self.home)], stdout=subprocess.DEVNULL, cwd=REPO)

        def stop():
            if launcher.poll() is None:
                subprocess.run(["taskkill", "/PID", str(launcher.pid), "/T", "/F"] if os.name == "nt"
                               else ["kill", "-9", str(launcher.pid)], capture_output=True)
            launcher.wait(timeout=30)

        self.addCleanup(stop)
        first = self.started(1)
        time.sleep(2 * boot_task.POLL_S)
        self.assertEqual(1, len(self.pids.read_text().split()), "no restart without a new install")
        (self.home / ".uaos" / "runtime" / "current.json").write_text("{", encoding="utf-8")  # mid-install
        time.sleep(3 * boot_task.POLL_S)
        self.assertEqual(1, len(self.pids.read_text().split()), "an unreadable pointer is no new version")
        self.set_version("1.0.1-bbbb")
        second = self.started(2)
        self.assertNotEqual(first[0], second[1])
        self.assertIsNone(launcher.poll(), "the launcher keeps supervising after the restart")


if __name__ == "__main__":
    unittest.main()
