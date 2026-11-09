"""The resident daemon PID must name Python, not a Windows venv redirector."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness import disjoint_mediator as dm


class DaemonExecutableSelection(unittest.TestCase):
    def _spawn_command(self, platform, base):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (mock.patch.object(dm.sys, "platform", platform),
                  mock.patch.object(dm.sys, "executable", "venv-redirector.exe"),
                  mock.patch.object(dm.sys, "_base_executable", base, create=True),
                  mock.patch("subprocess.Popen") as popen):
                popen.return_value.pid = 12345
                result = dm.ensure_independent_flagman_daemon(root)
                self.assertEqual(12345, result["pid"])
                return popen.call_args.args[0]

    def test_windows_uses_existing_base_interpreter_to_keep_real_child_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "python.exe"
            base.write_bytes(b"test executable existence only")
            command = self._spawn_command("win32", str(base))
            self.assertEqual(str(base), command[0])
            self.assertIn("sys.path.insert(0,", command[2])
            self.assertIn("str(os.getpid())", command[2])

    def test_invalid_or_missing_base_interpreter_keeps_existing_route(self):
        for base in (None, "", 7, "missing-base-python.exe"):
            with self.subTest(base=base):
                self.assertEqual("venv-redirector.exe", self._spawn_command("win32", base)[0])

    def test_non_windows_keeps_its_interpreter_even_with_existing_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "python"
            base.write_bytes(b"test executable existence only")
            self.assertEqual("venv-redirector.exe", self._spawn_command("linux", str(base))[0])


if __name__ == "__main__":
    unittest.main()
