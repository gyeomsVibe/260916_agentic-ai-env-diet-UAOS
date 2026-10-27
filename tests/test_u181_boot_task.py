"""U181: boot-time sentinel supervision — the task definition, its plan (registers nothing) and its launcher.

Receipt: register .coord/tasks/U180-systemic-recovery.md package 3 (2026-10-10): supervision started only after logon.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import boot_task
from v7_harness.coord.sentinel_lease import LeaseUnavailable, lease

REPO = Path(__file__).resolve().parents[1]
USER = "DESK\\yoon & <co>"  # XML-special characters must survive
PYTHON = "C:\\Python314\\pythonw.exe"
LAUNCHER = "C:\\Users\\yoon\\.uaos\\uaos.py"


def _home(base, roots):
    """A home whose .uaos holds one sentinel_*.cmd per root, as global_install writes them."""
    uaos = Path(base) / "home" / ".uaos"
    uaos.mkdir(parents=True)
    for index, root in enumerate(roots):
        (uaos / f"sentinel_p{index}.cmd").write_text(
            f'@echo off\nstart "" "{PYTHON}" "{LAUNCHER}" coord sentinel --project "{root}" --loop --interval 60 --ring\n',
            encoding="utf-8")
    return uaos.parent


class TaskXml(unittest.TestCase):
    def test_definition_is_a_valid_boot_task(self):
        text = boot_task.task_xml(USER, PYTHON, LAUNCHER)
        self.assertEqual([], boot_task.validate(text))
        for needed in ("<BootTrigger>", "<LogonType>S4U</LogonType>", "<RunLevel>LeastPrivilege</RunLevel>",
                       "<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>", "coord boot --launch",
                       "yoon &amp; &lt;co&gt;"):
            self.assertIn(needed, text)
        self.assertEqual(1, text.count("<Exec>"))  # actions run one after another: a second loop would never start
        self.assertNotIn("--ring", text)  # nobody hears a ring before logon
        self.assertNotIn("Password", text)
        self.assertNotIn("HighestAvailable", text)

    def test_validator_rejects_unsafe_definitions(self):
        good = boot_task.task_xml(USER, PYTHON, LAUNCHER)
        action = good[good.index("<Exec>"):good.index("</Exec>") + len("</Exec>")]
        cases = {
            "two actions": good.replace(action, action + action),
            "no boot trigger": good.replace("BootTrigger", "LogonTrigger"),
            "stored password": good.replace("S4U", "Password"),
            "elevated": good.replace("LeastPrivilege", "HighestAvailable"),
            "parallel instances": good.replace("IgnoreNew", "Parallel"),
            "ring before logon": good.replace("--launch", "--launch --ring"),
            "not xml": "<Task",
        }
        for name, text in cases.items():
            with self.subTest(name):
                self.assertNotEqual([], boot_task.validate(text))


class Plan(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def test_projects_come_from_installed_launchers_once_and_existing_only(self):
        one, two = self.base / "one", self.base / "two"
        one.mkdir()
        two.mkdir()
        home = _home(self.base, [one, two, one, self.base / "gone"])
        self.assertEqual([str(one), str(two)], boot_task.projects(home))
        self.assertEqual([], boot_task.projects(self.base / "no-home"))

    def test_plan_writes_one_file_and_registers_nothing(self):
        project = self.base / "one"
        project.mkdir()
        home = _home(self.base, [project])
        before = sorted(p.name for p in (home / ".uaos").iterdir())
        with mock.patch.object(subprocess, "run", side_effect=AssertionError("no process")), \
                mock.patch.object(subprocess, "Popen", side_effect=AssertionError("no process")):
            result = boot_task.plan(home, user=USER, python=PYTHON)
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["registered"])
        self.assertEqual([str(project)], result["projects"])
        xml = Path(result["xml"])
        self.assertEqual(home / ".uaos" / "boot", xml.parent)
        self.assertEqual(sorted(before + ["boot"]), sorted(p.name for p in (home / ".uaos").iterdir()))
        self.assertEqual([xml.name], [p.name for p in xml.parent.iterdir()])
        self.assertEqual([], boot_task.validate(xml.read_text(encoding="utf-16")))
        self.assertIn(str(home / ".uaos" / "uaos.py"), xml.read_text(encoding="utf-16"))
        self.assertIn(f'/TN "{boot_task.TASK_NAME}"', result["register"])
        self.assertIn(f'/XML "{xml}"', result["register"])
        self.assertTrue(result["register"].startswith("schtasks /Create "))
        self.assertNotIn("/F", result["register"])  # never overwrite an existing task silently
        self.assertEqual(f'schtasks /Delete /TN "{boot_task.TASK_NAME}" /F', result["uninstall"])

    def test_cli_prints_the_plan(self):
        home = _home(self.base, [])
        done = subprocess.run([sys.executable, "-m", "v7_harness.cli", "coord", "boot", "--home", str(home)],
                              capture_output=True, text=True, encoding="utf-8", timeout=60, cwd=REPO)
        self.assertEqual(0, done.returncode, done.stderr[-300:])
        result = json.loads(done.stdout)
        self.assertFalse(result["registered"])
        self.assertTrue(Path(result["xml"]).is_file())


class Launch(unittest.TestCase):
    """Two real launchers (boot task and logon launcher) for one project: exactly one loop runs."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.project = self.base / "project"
        (self.project / ".coord").mkdir(parents=True)
        self.home = _home(self.base, [self.project])
        # The installed launcher runs the runtime; here it runs this checkout.
        (self.home / ".uaos" / "uaos.py").write_text(
            f"import sys\nsys.path.insert(0, {str(REPO)!r})\nfrom v7_harness.cli import main\nsys.exit(main())\n",
            encoding="utf-8")
        self.command = [sys.executable, "-m", "v7_harness.cli", "coord", "boot", "--launch", "--home", str(self.home)]

    def _stop(self, process, children):
        for pid in children:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"] if os.name == "nt" else ["kill", "-9", str(pid)],
                           capture_output=True)
        if process.poll() is None:
            process.kill()
        process.wait(timeout=30)
        process.stdout.close()

    def _held(self):
        try:
            with lease(self.project):
                return False
        except LeaseUnavailable:
            return True

    def test_second_launcher_starts_no_second_loop(self):
        first = subprocess.Popen(self.command, stdout=subprocess.PIPE, text=True, cwd=REPO)
        started = json.loads(first.stdout.readline())
        self.addCleanup(self._stop, first, started["children"])
        self.assertEqual(1, len(started["children"]))
        deadline = time.monotonic() + 30
        while not self._held():
            self.assertLess(time.monotonic(), deadline, "the first loop never took the lease")
            self.assertIsNone(first.poll(), "the first launcher left")
            time.sleep(0.1)
        second = subprocess.run(self.command, capture_output=True, text=True, timeout=60, cwd=REPO)
        self.assertEqual(0, second.returncode, second.stderr[-300:])  # a busy lease is the expected answer, not a failure
        self.assertEqual(1, len(json.loads(second.stdout.splitlines()[0])["children"]))
        self.assertIsNone(first.poll(), "the first launcher must keep supervising")
        self.assertTrue(self._held())
        log = (self.project / ".work" / "sentinel" / "sentinel.log").read_text(encoding="utf-8")
        self.assertIn("LEASE_BUSY_OR_LOCK_ERROR", log)

    def test_no_projects_is_a_clean_exit(self):
        empty = _home(self.base / "other", [])
        done = subprocess.run([*self.command[:-1], str(empty)], capture_output=True, text=True, timeout=60, cwd=REPO)
        self.assertEqual(0, done.returncode, done.stderr[-300:])
        self.assertEqual([], json.loads(done.stdout.splitlines()[0])["children"])

    def test_a_crashed_loop_fails_the_launcher_so_the_task_restarts_it(self):
        (self.home / ".uaos" / "uaos.py").write_text("import sys\nsys.exit(7)\n", encoding="utf-8")
        done = subprocess.run(self.command, capture_output=True, text=True, timeout=60, cwd=REPO)
        self.assertEqual(1, done.returncode)


if __name__ == "__main__":
    unittest.main()
