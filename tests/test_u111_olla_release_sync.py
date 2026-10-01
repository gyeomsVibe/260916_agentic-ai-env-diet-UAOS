"""U111: the `olla` on PATH runs the merged code, not whatever was copied last.

Receipt (2026-10-01, after PR #81 merged): `olla hook-shell` still printed the pre-U108 deny with no outline. The
launcher runs a copied release (`PYTHONPATH=<release>`) that nothing refreshed: 51 of its v7_harness files differed
from main. The same manual redeploy was needed for U103. The installer now treats the release like the other files
it owns: --check reports drift, --apply copies (backups first). Like U91's scheduled tasks, the release belongs to
this PC's real user, so a test or staging --home never touches it.
Fixed acceptance written by the judge (claude) first.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_u37_install_everywhere import PYTHON, _home, _run
from v7_harness import global_install as gi


def _repo(root: Path) -> Path:
    repo = root / "repo"
    (repo / "v7_harness" / "adapters").mkdir(parents=True)
    (repo / "v7_harness" / "olla.py").write_text("NEW = 2\n", encoding="utf-8")
    (repo / "v7_harness" / "adapters" / "added.py").write_text("ADDED = 1\n", encoding="utf-8")
    (repo / "v7_harness" / "same.py").write_text("SAME = 1\n", encoding="utf-8")
    for pkg in ("", "adapters/"):  # two stale files with one name: their backups must not overwrite each other
        (repo / "v7_harness" / f"{pkg}__init__.py").write_text(f"# new {pkg}\n", encoding="utf-8")
    cache = repo / "v7_harness" / "__pycache__"
    cache.mkdir()
    (cache / "olla.cpython-314.py").write_text("compiled\n", encoding="utf-8")
    return repo


def _release(root: Path) -> Path:
    release = root / "olla-release"
    (release / "v7_harness").mkdir(parents=True)
    (release / "v7_harness" / "olla.py").write_text("OLD = 1\n", encoding="utf-8")
    (release / "v7_harness" / "same.py").write_text("SAME = 1\n", encoding="utf-8")
    (release / "v7_harness" / "adapters").mkdir()
    for pkg in ("", "adapters/"):
        (release / "v7_harness" / f"{pkg}__init__.py").write_text(f"# old {pkg}\n", encoding="utf-8")
    return release


class ReleaseDirTests(unittest.TestCase):
    def test_bash_and_cmd_launchers_name_the_release(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            release = _release(root)
            bash = root / "olla"
            bash.write_text(f'#!/usr/bin/env bash\nPYTHONPATH="{release.as_posix()}${{PYTHONPATH:+;$PYTHONPATH}}" '
                            "exec python -P -m v7_harness.olla \"$@\"\n", encoding="utf-8")
            cmd = root / "olla.cmd"
            cmd.write_text(f'@echo off\nset "PYTHONPATH={release.as_posix()};%PYTHONPATH%"\n'
                           "python -P -m v7_harness.olla %*\n", encoding="utf-8")
            for launcher in (bash, cmd):
                self.assertEqual(release.resolve(), gi.olla_release_dir(lambda _n, p=launcher: str(p)).resolve())

    def test_no_launcher_or_no_copy_means_no_release(self):
        with tempfile.TemporaryDirectory() as d:
            plain = Path(d) / "olla"
            plain.write_text("#!/bin/sh\nexec python -m v7_harness.olla\n", encoding="utf-8")
            self.assertIsNone(gi.olla_release_dir(lambda _n: None))
            self.assertIsNone(gi.olla_release_dir(lambda _n: str(plain)))
            empty = Path(d) / "olla2"
            empty.write_text(f'PYTHONPATH="{(Path(d) / "nowhere").as_posix()}" python\n', encoding="utf-8")
            self.assertIsNone(gi.olla_release_dir(lambda _n: str(empty)))


class ReleaseSyncTests(unittest.TestCase):
    def test_stale_release_files_are_planned_and_applied_then_clean(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            home, repo, release = _home(root), _repo(root), _release(root)
            changes = [c for c in gi.plan(home, PYTHON, repo=repo, olla_release=release) if c.target == "olla release"]
            planned = {c.path.relative_to(release).as_posix(): c.action for c in changes}
            self.assertEqual({"v7_harness/olla.py": "UPDATE", "v7_harness/adapters/added.py": "CREATE",
                              "v7_harness/__init__.py": "UPDATE", "v7_harness/adapters/__init__.py": "UPDATE"}, planned)
            result = gi.apply(changes, home, backup_root=root / "backups")
            self.assertEqual("NEW = 2\n", (release / "v7_harness" / "olla.py").read_text(encoding="utf-8"))
            self.assertTrue((release / "v7_harness" / "adapters" / "added.py").is_file())
            self.assertFalse((release / "v7_harness" / "__pycache__").exists())
            self.assertEqual(3, len(set(result["backups"])))  # each overwritten file kept its own backup
            again = [c for c in gi.plan(home, PYTHON, repo=repo, olla_release=release)
                     if c.target == "olla release" and c.action != "UNCHANGED"]
            self.assertEqual([], again)

    def test_uninstall_leaves_the_release_alone(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            home, repo, release = _home(root), _repo(root), _release(root)
            changes = gi.plan(home, PYTHON, repo=repo, olla_release=release, uninstall=True)
            self.assertFalse([c for c in changes if c.target == "olla release"])

    def test_a_test_or_staging_home_never_looks_for_the_release(self):
        with tempfile.TemporaryDirectory() as d:
            home = _home(Path(d))
            with mock.patch.object(gi, "olla_release_dir", side_effect=AssertionError("touched the PC release")):
                code, out = _run(home, "--check")
            self.assertFalse([c for c in out["changes"] if c["target"] == "olla release"])
            self.assertIn(code, (0, 1))


if __name__ == "__main__":
    unittest.main()
