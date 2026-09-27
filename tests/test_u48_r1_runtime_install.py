"""U48-R1 acceptance: the launcher runs an installed runtime, not the worktree (Claude, 2026-09-27).

Codex's card gate: after the source is renamed, `uaos --version` and `coord inbox` still exit 0; rollback to the
previous version is one command; the default is a dry run. Added: an installed runtime is immutable (tamper is
refused), 8 parallel installers leave one verified runtime, and global_install keeps the runtime launcher.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from v7_harness import global_install as gi
from v7_harness import runtime_install as ri

REPO = Path(__file__).resolve().parent.parent


def _copy_repo(dst: Path, version: str = "9.9.0") -> Path:
    shutil.copytree(REPO / "v7_harness", dst / "v7_harness", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (dst / "uaos_everywhere").mkdir(parents=True)
    (dst / "uaos_everywhere" / "VERSION").write_text(version + "\n", encoding="utf-8")
    return dst


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    # PYTHONPATH is cleared so the only harness the child can import is the one the launcher puts on sys.path.
    env = {k: v for k, v in __import__("os").environ.items() if k != "PYTHONPATH"}
    return subprocess.run([sys.executable, *args], cwd=cwd, capture_output=True, text=True, timeout=120, env=env)


class RuntimeInstallTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="u48r1_"))
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.repo = _copy_repo(self.tmp / "repo")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_default_is_a_dry_run(self) -> None:
        self.assertEqual(0, ri.main(["--home", str(self.home), "--repo", str(self.repo)]))
        self.assertEqual([], list(self.home.rglob("*")))

    def test_launcher_survives_renaming_the_source(self) -> None:
        report = ri.install(self.home, self.repo)
        self.assertTrue(report["version"].startswith("9.9.0-"))
        self.repo.rename(self.tmp / "repo_moved")  # the worktree is gone from where it was installed
        launcher = self.home / ".uaos" / "uaos.py"
        self.assertNotIn("repo", launcher.read_text(encoding="utf-8").split('"""')[-1])
        away = self.tmp / "elsewhere"
        away.mkdir()
        version = _run([str(launcher), "--version"], away)
        self.assertEqual((0, report["version"]), (version.returncode, version.stdout.strip()), version.stderr)
        project = self.tmp / "project"
        project.mkdir()
        init = _run([str(launcher), "coord", "init", "--project", str(project)], away)
        self.assertEqual(0, init.returncode, init.stderr)
        inbox = _run([str(launcher), "coord", "inbox", "--project", str(project)], away)
        self.assertEqual(0, inbox.returncode, inbox.stderr)

    def _two_versions(self) -> tuple[str, str]:
        first = ri.install(self.home, self.repo)["version"]
        (self.repo / "uaos_everywhere" / "VERSION").write_text("9.9.1\n", encoding="utf-8")
        second = ri.install(self.home, self.repo)["version"]
        self.assertNotEqual(first, second)
        self.assertEqual(second, ri.read_current(self.home)["version"])
        return first, second

    def test_rollback_is_one_command_without_the_source(self) -> None:
        # Codex R1 review: the rollback gate must run as a separate command after the source is gone.
        first, second = self._two_versions()
        self.repo.rename(self.tmp / "repo_moved")
        launcher = str(self.home / ".uaos" / "uaos.py")
        back = _run([launcher, "runtime", "--apply", "--rollback"], self.tmp)
        self.assertEqual(0, back.returncode, back.stderr)
        out = _run([launcher, "--version"], self.tmp)
        self.assertEqual(first, out.stdout.strip(), out.stderr)
        self.assertEqual(sorted([first, second]), ri.installed(self.home))

    def test_launcher_refuses_a_tampered_current_runtime_and_can_still_roll_back(self) -> None:
        # Codex R1 review: a changed current runtime must not run, and --version must not report it as fine.
        first, second = self._two_versions()
        cli = ri.runtime_dir(self.home) / second / "v7_harness" / "cli.py"
        cli.write_bytes(cli.read_bytes() + b"\n# tampered\n")
        launcher = str(self.home / ".uaos" / "uaos.py")
        for args in (["--version"], ["coord", "inbox", "--project", str(self.tmp)]):
            out = _run([launcher, *args], self.tmp)
            self.assertNotEqual(0, out.returncode, args)
            self.assertIn("UAOS_RUNTIME_CORRUPT", out.stderr)
        back = _run([launcher, "runtime", "--apply", "--rollback"], self.tmp)
        self.assertEqual(0, back.returncode, back.stderr)
        self.assertEqual(first, _run([launcher, "--version"], self.tmp).stdout.strip())

    def test_code_and_manifest_changed_together_are_refused(self) -> None:
        # Codex R1 review: the manifest is writable, so rewriting it to match changed code must still fail.
        version = ri.install(self.home, self.repo)["version"]
        root = ri.runtime_dir(self.home) / version
        cli = root / "v7_harness" / "cli.py"
        cli.write_bytes(cli.read_bytes() + b"\n# tampered\n")
        manifest = json.loads((root / ri.MANIFEST).read_text(encoding="utf-8"))
        manifest["files"]["v7_harness/cli.py"] = __import__("hashlib").sha256(cli.read_bytes()).hexdigest()
        (root / ri.MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ri.RuntimeError_, "^RUNTIME_CORRUPT"):
            ri.verify(self.home, version)
        out = _run([str(self.home / ".uaos" / "uaos.py"), "--version"], self.tmp)
        self.assertNotEqual(0, out.returncode)
        self.assertIn("UAOS_RUNTIME_CORRUPT", out.stderr)

    def test_rollback_dry_run_changes_nothing(self) -> None:
        first = ri.install(self.home, self.repo)["version"]
        (self.repo / "uaos_everywhere" / "VERSION").write_text("9.9.1\n", encoding="utf-8")
        ri.install(self.home, self.repo)
        before = ri.read_current(self.home)
        self.assertEqual(0, ri.main(["--home", str(self.home), "--rollback"]))
        self.assertEqual(before, ri.read_current(self.home))
        self.assertNotEqual(first, before["version"])

    def test_tampered_runtime_is_refused(self) -> None:
        version = ri.install(self.home, self.repo)["version"]
        cli = ri.runtime_dir(self.home) / version / "v7_harness" / "cli.py"
        cli.write_bytes(cli.read_bytes() + b"\n# tampered\n")
        with self.assertRaisesRegex(ri.RuntimeError_, "^RUNTIME_CORRUPT"):
            ri.install(self.home, self.repo)
        with self.assertRaisesRegex(ri.RuntimeError_, "^RUNTIME_CORRUPT"):
            ri.rollback(self.home, version)

    def test_unknown_version_and_no_previous_fail_closed(self) -> None:
        with self.assertRaisesRegex(ri.RuntimeError_, "^NO_PREVIOUS"):
            ri.rollback(self.home)
        ri.install(self.home, self.repo)
        with self.assertRaisesRegex(ri.RuntimeError_, "^UNKNOWN_VERSION"):
            ri.rollback(self.home, "0.0.0-deadbeef0000")
        self.assertEqual(1, ri.main(["--home", str(self.home), "--apply", "--rollback", "0.0.0-deadbeef0000"]))

    def test_existing_launcher_is_backed_up(self) -> None:
        launcher = self.home / ".uaos" / "uaos.py"
        launcher.parent.mkdir(parents=True)
        launcher.write_text("# old repo launcher\n", encoding="utf-8")
        report = ri.install(self.home, self.repo)
        self.assertEqual("# old repo launcher\n", Path(report["launcher_backup"]).read_text(encoding="utf-8"))

    def test_eight_parallel_installers_leave_one_verified_runtime(self) -> None:
        cmd = [sys.executable, "-m", "v7_harness.runtime_install", "--apply", "--home", str(self.home),
               "--repo", str(self.repo)]
        procs = [subprocess.Popen(cmd, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for _ in range(8)]
        outs = [p.communicate(timeout=180) for p in procs]
        self.assertEqual([0] * 8, [p.returncode for p in procs], [o[1][-400:] for o in outs])
        versions = {json.loads(o[0])["version"] for o in outs}
        self.assertEqual(1, len(versions))
        self.assertEqual(sorted(versions), ri.installed(self.home))
        ri.verify(self.home, versions.pop())
        leftovers = [p.name for p in ri.runtime_dir(self.home).iterdir() if p.name.endswith(".tmp")]
        self.assertEqual([], leftovers)

    def test_global_install_keeps_the_runtime_launcher(self) -> None:
        ri.install(self.home, self.repo)
        changes = gi.plan(self.home, sys.executable, repo=self.repo, rules=False, enable_codex_hooks=False)
        launcher = [c for c in changes if c.target == "launcher"][0]
        self.assertEqual("UNCHANGED", launcher.action)

    def test_global_install_without_runtime_still_writes_the_repo_launcher(self) -> None:
        changes = gi.plan(self.home, sys.executable, repo=self.repo, rules=False, enable_codex_hooks=False)
        launcher = [c for c in changes if c.target == "launcher"][0]
        self.assertEqual("CREATE", launcher.action)
        self.assertIn(self.repo.as_posix(), launcher.new_text)


if __name__ == "__main__":
    unittest.main()
