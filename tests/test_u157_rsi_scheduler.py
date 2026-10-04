"""U157: the RSI scheduler is installed truthfully and runs the installed runtime.

Receipt (2026-10-04): `windows_schedule` returned status APPLIED for a non-zero schtasks exit, scheduled an unquoted
`/TR <root>\\.work\\rsi watch.cmd` that splits at the space, and no UAOS task existed among 268 scheduled tasks.
Contract: .work/u157/contract_v1.md (Codex GO relay_bf916dac). The task is imported as XML (Exec/Command holds the
path as one element, so spaces need no shell quoting), it is verified by reading it back, and every failure is
FAILED with a reason. The wrapper calls the installed `~/.uaos/uaos.py`, never the checkout module.

v2 (Codex REWORK relay_c8628506): the interpreter is resolved on PATH, not under the project, and a missing one is
refused. The wrapper leaves an exit receipt in `.coord/rsi/schedule_last.json`, and a real run of the wrapper
proves it. Overlap: Task Scheduler's IgnoreNew is asserted here. The in-process lock is proven by real processes in
tests/test_u42_r1_hardening.py::test_atomic_lock_allows_exactly_one_process_owner, and its TTL defect is card
U157-L.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from v7_harness import rsi_release

NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


class FakeSchtasks:
    """Records every call; /Create /XML stores the file, /Query /XML returns it (or an override)."""

    def __init__(self, create_rc=0, query_rc=0, query_xml=None, other_rc=0):
        self.calls, self.stored = [], None
        self.create_rc, self.query_rc, self.query_xml, self.other_rc = create_rc, query_rc, query_xml, other_rc

    def __call__(self, command, **kwargs):
        command = list(command)
        self.calls.append((command, kwargs))
        if command[:2] == ["schtasks", "/Create"] and "/XML" in command:
            self.stored = Path(command[command.index("/XML") + 1]).read_text(encoding="utf-16")
            return subprocess.CompletedProcess(command, self.create_rc, "SUCCESS", "")
        if command[:2] == ["schtasks", "/Query"] and "/XML" in command:
            text = self.query_xml if self.query_xml is not None else self.stored
            return subprocess.CompletedProcess(command, self.query_rc, text if self.query_rc == 0 else "",
                                               "" if self.query_rc == 0 else "ERROR: task not found")
        return subprocess.CompletedProcess(command, self.other_rc, "SUCCESS", "" if self.other_rc == 0 else "ERROR")


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name).resolve()
        self.project = root / "My Work" / "UAOS root"
        self.project.mkdir(parents=True)
        self.launcher = root / "home dir" / ".uaos" / "uaos.py"
        self.launcher.parent.mkdir(parents=True)
        self.launcher.write_text("# installed runtime stand-in\n", encoding="utf-8")
        self.python = root / "Program Files" / "Python" / "python.exe"  # spaced interpreter path; exists only
        self.python.parent.mkdir(parents=True)
        self.python.write_bytes(b"")

    def tearDown(self):
        self._tmp.cleanup()

    def schedule(self, action="install", apply=True, run=None, launcher=None, python=None):
        return rsi_release.windows_schedule(self.project, str(python or self.python), action=action, apply=apply,
                                            run=run, launcher=launcher or self.launcher)

    @staticmethod
    def task(xml_text):
        return ET.fromstring(xml_text[xml_text.index("<Task"):])


class InstallRunsTheInstalledRuntime(Base):
    def test_spaced_paths_survive_and_the_wrapper_calls_the_installed_launcher(self):
        fake = FakeSchtasks()
        result = self.schedule(run=fake)
        self.assertEqual((True, "APPLIED"), (result["ok"], result["status"]), result)
        create = fake.calls[0][0]
        self.assertEqual(["schtasks", "/Create"], create[:2])
        self.assertIn("/XML", create)
        self.assertNotIn("/TR", create)
        xml_file = Path(create[create.index("/XML") + 1])
        self.assertEqual(b"\xff\xfe", xml_file.read_bytes()[:2])  # schtasks /XML reads UTF-16 LE
        task = self.task(fake.stored)
        wrapper = Path(result["wrapper_path"])
        self.assertEqual(str(wrapper), task.findtext(".//t:Exec/t:Command", namespaces=NS))
        self.assertEqual(str(self.project), task.findtext(".//t:Exec/t:WorkingDirectory", namespaces=NS))
        text = wrapper.read_text(encoding="utf-8")
        for quoted in (f'"{self.python}"', f'"{self.launcher}"', f'"{self.project}"'):
            self.assertIn(quoted, text)
        self.assertIn(" rsi watch --project ", text)
        self.assertIn("schedule_last.json", text)
        self.assertNotIn("-m v7_harness", text)
        self.assertNotIn(" ", wrapper.name)

    def test_bare_interpreter_resolves_on_path_not_under_the_project(self):
        bare = Path(sys.executable).name
        result = self.schedule(apply=False, python=bare)
        found = shutil.which(bare)
        self.assertIsNotNone(found)
        self.assertIn(f'"{found}"', result["wrapper_text"])  # not resolved: a venv launcher must stay a venv one
        self.assertNotIn(f'"{self.project / bare}"', result["wrapper_text"])

    def test_missing_interpreter_fails_closed_before_any_schtasks_call(self):
        fake = FakeSchtasks()
        for python in ("no-such-python-u157.exe", str(self.python.parent / "absent.exe")):
            result = self.schedule(run=fake, python=python)
            self.assertEqual((False, "FAILED", "INTERPRETER_MISSING"),
                             (result["ok"], result["status"], result["reason"]))
        self.assertEqual([], fake.calls)

    @unittest.skipUnless(os.name == "nt", "the wrapper is a Windows batch file")
    def test_real_wrapper_run_keeps_the_exit_code_and_leaves_a_receipt(self):
        self.launcher.write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
        result = self.schedule(run=FakeSchtasks(), python=sys.executable)
        self.assertTrue(result["ok"], result)
        done = subprocess.run([result["wrapper_path"]], capture_output=True, text=True, timeout=60)
        self.assertEqual(3, done.returncode, done.stderr)
        receipt = json.loads((self.project / ".coord" / "rsi" / "schedule_last.json").read_text(encoding="utf-8"))
        self.assertEqual(3, receipt["exit"])

    def test_task_xml_has_fifteen_minute_repetition_logon_catch_up_and_no_overlap(self):
        fake = FakeSchtasks()
        self.schedule(run=fake)
        task = self.task(fake.stored)
        self.assertEqual("PT15M", task.findtext(".//t:CalendarTrigger/t:Repetition/t:Interval", namespaces=NS))
        self.assertIsNotNone(task.find(".//t:LogonTrigger", NS))
        self.assertEqual("IgnoreNew", task.findtext(".//t:Settings/t:MultipleInstancesPolicy", namespaces=NS))
        self.assertEqual("true", task.findtext(".//t:Settings/t:StartWhenAvailable", namespaces=NS))
        self.assertEqual("InteractiveToken", task.findtext(".//t:Principal/t:LogonType", namespaces=NS))
        self.assertEqual("LeastPrivilege", task.findtext(".//t:Principal/t:RunLevel", namespaces=NS))

    def test_missing_installed_runtime_fails_closed_before_any_schtasks_call(self):
        fake = FakeSchtasks()
        result = self.schedule(run=fake, launcher=self.launcher.parent / "absent.py")
        self.assertEqual((False, "FAILED", "RUNTIME_MISSING"), (result["ok"], result["status"], result["reason"]))
        self.assertEqual([], fake.calls)


class FailuresAreNeverApplied(Base):
    def test_create_failure(self):
        fake = FakeSchtasks(create_rc=1)
        result = self.schedule(run=fake)
        self.assertEqual((False, "FAILED", "CREATE_FAILED"), (result["ok"], result["status"], result["reason"]))
        self.assertEqual(1, len(fake.calls))

    def test_create_ok_but_query_fails(self):
        result = self.schedule(run=FakeSchtasks(query_rc=1))
        self.assertEqual((False, "FAILED", "VERIFY_MISSING"), (result["ok"], result["status"], result["reason"]))

    def test_installed_action_differs(self):
        probe = FakeSchtasks()
        self.schedule(run=probe)
        wrong = probe.stored.replace(str(Path(self.project / ".work" / "rsi_watch.cmd")), r"C:\elsewhere\x.cmd")
        result = self.schedule(run=FakeSchtasks(query_xml=wrong))
        self.assertEqual((False, "FAILED"), (result["ok"], result["status"]))
        self.assertEqual("VERIFY_MISMATCH:command", result["reason"])

    def test_installed_trigger_differs(self):
        probe = FakeSchtasks()
        self.schedule(run=probe)
        result = self.schedule(run=FakeSchtasks(query_xml=probe.stored.replace("PT15M", "PT1H")))
        self.assertEqual("VERIFY_MISMATCH:repetition", result["reason"])

    def test_applied_never_appears_with_ok_false(self):
        results = [self.schedule(run=FakeSchtasks(create_rc=1)), self.schedule(run=FakeSchtasks(query_rc=1)),
                   self.schedule(action="remove", run=FakeSchtasks(other_rc=1)),
                   self.schedule(action="manual-now", run=FakeSchtasks(other_rc=1))]
        for result in results:
            self.assertFalse(result["ok"], result)
            self.assertNotEqual("APPLIED", result["status"], result)


class StatusIsReadOnlyAndPreviewsRunNothing(Base):
    def test_status_queries_once_without_apply(self):
        fake = FakeSchtasks()
        result = self.schedule(action="status", apply=False, run=fake)
        self.assertEqual(1, len(fake.calls))
        command = fake.calls[0][0]
        self.assertEqual(["schtasks", "/Query"], command[:2])
        for verb in ("/Create", "/Delete", "/Change", "/Run", "/End"):
            self.assertNotIn(verb, command)
        self.assertTrue(result["ok"])

    def test_install_remove_manual_now_preview_runs_nothing(self):
        fake = FakeSchtasks()
        for action in ("install", "remove", "manual-now"):
            self.assertEqual("DRY_RUN", self.schedule(action=action, apply=False, run=fake)["status"])
        self.assertEqual([], fake.calls)
        self.assertFalse((self.project / ".work" / "rsi_watch.cmd").exists())


if __name__ == "__main__":
    unittest.main()
