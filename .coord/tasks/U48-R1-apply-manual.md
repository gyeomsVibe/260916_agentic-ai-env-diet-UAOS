```contract
work_id: U48-R1
worker: apply
goal: Install v7_harness as an immutable versioned runtime under ~/.uaos/runtime and point the launcher at it, not at a worktree.
inputs:
- v7_harness/global_install.py sha256=b486b34099d71eaf3bc8235ab68fc8800f53292716b9228d312dd6c183fe06d6
allow:
- v7_harness/runtime_install.py
- v7_harness/global_install.py
- tests/test_u48_r1_runtime_install.py
acceptance: C:/Python314/python.exe D:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/.work/u45_claude/.coord/tasks/U48-R1-fixed-gate.py
forbidden: design changes; edits outside allow; editing or deleting other tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Fixed acceptance gate SHA-256: `a81e292495da52979a0f38946bf1c247e0636fb1b7bd72eb453f947c4f478fc3`. Card: PLAN U48-R1. Tests use a temporary home only.

===FILE: v7_harness/runtime_install.py===
"""U48-R1: versioned UAOS runtime, so no project depends on a git worktree staying where it is.

Why (2026-09-27): `~/.uaos/uaos.py` put `.work/u45_claude` on sys.path. Removing that worktree or switching its
branch would stop `uaos` in every project at once. This copies `v7_harness` into an immutable
`~/.uaos/runtime/<VERSION>-<digest12>/` and points the launcher at `runtime/current.json` instead of the repository.

    python -m v7_harness.runtime_install                  # preview (default; writes nothing)
    python -m v7_harness.runtime_install --apply          # install this repo's harness and make it current
    python -m v7_harness.runtime_install --list
    python -m v7_harness.runtime_install --apply --rollback [VERSION]   # previous version when VERSION is omitted
    python ~/.uaos/uaos.py runtime --apply --rollback [VERSION]         # the same from the installed runtime, no repo
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = "MANIFEST.json"
CURRENT = "current.json"
# The digest suffix makes each distinct build its own directory: a VERSION file that was not bumped can never
# overwrite an installed runtime. 12 hex chars = 48 bits, ample for the handful of builds one PC keeps.
DIGEST_CHARS = 12
# os.replace on Windows fails with PermissionError while another process holds the target open; 8 parallel
# installers showed this. 50 tries x 20 ms bounds the wait at about 1 s.
REPLACE_TRIES = 50
REPLACE_SLEEP_S = 0.02


class RuntimeError_(Exception):
    """A refusal with a stable code as its first word (RUNTIME_CORRUPT, UNKNOWN_VERSION, NO_PREVIOUS, ...)."""


def _files(repo: Path) -> dict[str, bytes]:
    root = repo / "v7_harness"
    out = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            out[path.relative_to(repo).as_posix()] = path.read_bytes()
    if "v7_harness/cli.py" not in out:
        raise RuntimeError_(f"NO_HARNESS {root}")
    return out


def _digest(hashes: dict[str, str]) -> str:
    """Build digest over {relative path: file sha256}. The launcher repeats this exact loop (keep them identical)."""
    h = hashlib.sha256()
    for rel, hexsum in sorted(hashes.items()):
        h.update(rel.encode("utf-8") + b"\0" + hexsum.encode("ascii") + b"\n")
    return h.hexdigest()


def build_id(repo: Path) -> tuple[str, dict[str, bytes], str]:
    files = _files(repo)
    digest = _digest({rel: hashlib.sha256(data).hexdigest() for rel, data in files.items()})
    version = (repo / "uaos_everywhere" / "VERSION").read_text(encoding="utf-8").strip()
    return f"{version}-{digest[:DIGEST_CHARS]}", files, digest


def runtime_dir(home: Path) -> Path:
    return Path(home) / ".uaos" / "runtime"


def verify(home: Path, version: str) -> dict[str, Any]:
    """Re-hash an installed runtime against its manifest; raise RUNTIME_CORRUPT on any difference."""
    root = runtime_dir(home) / version
    try:
        manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError_(f"UNKNOWN_VERSION {version}: {exc}") from exc
    on_disk = {}
    for path in (root / "v7_harness").rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            on_disk[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    if on_disk != manifest.get("files"):
        raise RuntimeError_(f"RUNTIME_CORRUPT {version}: files differ from {MANIFEST}")
    # Codex R1 review: the manifest is writable too, so a runtime whose code and manifest were changed together must
    # still fail. The directory name carries the build digest; recompute it from the files and require the match.
    digest = _digest(on_disk)
    if (manifest.get("version") != version or manifest.get("digest") != digest
            or not version.endswith("-" + digest[:DIGEST_CHARS])):
        raise RuntimeError_(f"RUNTIME_CORRUPT {version}: build digest does not match the version name")
    return manifest


def _replace(src: Path, dst: Path) -> None:
    for attempt in range(REPLACE_TRIES):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == REPLACE_TRIES - 1:
                raise
            time.sleep(REPLACE_SLEEP_S)


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    _replace(tmp, path)


def read_current(home: Path) -> dict[str, Any]:
    try:
        return json.loads((runtime_dir(home) / CURRENT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


LAUNCHER = r'''"""UAOS launcher (U48-R1): runs the installed runtime named in ~/.uaos/runtime/current.json.

No repository or worktree is on sys.path. Every start re-hashes the runtime against its manifest and the build digest
in its name, and refuses a changed runtime (Codex R1 review: a tampered current runtime must not run).
    uaos --version
    uaos runtime --apply --rollback [VERSION]    # works even when the current runtime is refused
"""
import hashlib
import json
import sys
from pathlib import Path

UAOS = Path(__file__).resolve().parent
RUNTIME = UAOS / "runtime"


def verified(version):
    """True only when the files, the manifest and the digest suffix of the version name all agree."""
    if not version:
        return False
    root = RUNTIME / version
    try:
        manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
        on_disk = {}
        for path in (root / "v7_harness").rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                on_disk[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, ValueError):
        return False
    h = hashlib.sha256()  # the same loop as runtime_install._digest
    for rel, hexsum in sorted(on_disk.items()):
        h.update(rel.encode("utf-8") + b"\0" + hexsum.encode("ascii") + b"\n")
    digest = h.hexdigest()
    return (on_disk == manifest.get("files") and manifest.get("version") == version
            and manifest.get("digest") == digest and version.endswith("-" + digest[:12])
            and "v7_harness/cli.py" in on_disk)


try:
    CURRENT = json.loads((RUNTIME / "current.json").read_text(encoding="utf-8"))
except (OSError, ValueError) as exc:
    sys.exit(f"UAOS_RUNTIME_MISSING current.json: {exc}")
args = sys.argv[1:]
if args[:1] == ["runtime"]:
    # Recovery path: use the current runtime if it verifies, else the previous one, so a rollback never depends on
    # the runtime being rolled back from.
    chosen = next((v for v in (CURRENT.get("version"), CURRENT.get("previous")) if verified(v)), None)
    if chosen is None:
        sys.exit("UAOS_RUNTIME_CORRUPT: neither the current nor the previous runtime verifies")
    sys.path.insert(0, str(RUNTIME / chosen))
    from v7_harness.runtime_install import main as runtime_main  # noqa: E402
    sys.exit(runtime_main(["--home", str(UAOS.parent)] + args[1:]))
VERSION = CURRENT.get("version")
if not verified(VERSION):
    sys.exit(f"UAOS_RUNTIME_CORRUPT {VERSION}: run `uaos runtime --apply --rollback` or reinstall")
if args == ["--version"]:
    print(VERSION)
    sys.exit(0)
sys.path.insert(0, str(RUNTIME / VERSION))
from v7_harness.cli import main  # noqa: E402

sys.exit(main())
'''


def launcher_text() -> str:
    """Launcher that follows runtime/current.json, so a rollback rewrites one small file and nothing else."""
    return LAUNCHER


def plan(home: Path, repo: Path = REPO_ROOT) -> dict[str, Any]:
    version, files, digest = build_id(repo)
    root = runtime_dir(home) / version
    launcher = Path(home) / ".uaos" / "uaos.py"
    current = read_current(home).get("version")
    old_launcher = launcher.read_text(encoding="utf-8") if launcher.is_file() else None
    return {"version": version, "digest": digest, "files": len(files), "runtime": str(root),
            "runtime_action": "UNCHANGED" if (root / MANIFEST).is_file() else "CREATE",
            "current_before": current, "current_action": "UNCHANGED" if current == version else "SET",
            "launcher": str(launcher),
            "launcher_action": "UNCHANGED" if old_launcher == launcher_text() else (
                "UPDATE" if old_launcher is not None else "CREATE")}


def install(home: Path, repo: Path = REPO_ROOT) -> dict[str, Any]:
    """Copy the harness into an immutable runtime (atomic rename), then make it current. Safe to run in parallel."""
    report = plan(home, repo)
    version, files, digest = build_id(repo)
    base = runtime_dir(home)
    root = base / version
    if not (root / MANIFEST).is_file():
        stage = base / f".{version}.{uuid.uuid4().hex}.tmp"
        manifest = {"version": version, "digest": digest, "source_repo": repo.as_posix(),
                    "files": {rel: hashlib.sha256(data).hexdigest() for rel, data in files.items()}}
        for rel, data in files.items():
            (stage / rel).parent.mkdir(parents=True, exist_ok=True)
            (stage / rel).write_bytes(data)
        (stage / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        try:
            os.rename(stage, root)  # a directory rename never merges: the first installer wins, the rest verify
        except OSError:
            shutil.rmtree(stage, ignore_errors=True)
            if not (root / MANIFEST).is_file():
                raise
    verify(home, version)
    _set_current(home, version)
    _write_launcher(home, report)
    return report


def _set_current(home: Path, version: str) -> None:
    previous = read_current(home).get("version")
    if previous == version:
        return
    _write_atomic(runtime_dir(home) / CURRENT, json.dumps(
        {"version": version, "previous": previous, "set_at": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")


def _write_launcher(home: Path, report: dict[str, Any]) -> None:
    launcher = Path(home) / ".uaos" / "uaos.py"
    if report["launcher_action"] == "UNCHANGED" or (launcher.is_file()
                                                     and launcher.read_text(encoding="utf-8") == launcher_text()):
        return
    if launcher.is_file():  # same backup root as global_install, so one place holds every UAOS home backup
        backup = Path(home) / ".uaos-backups" / f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}" / "uaos.py"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(launcher, backup)
        report["launcher_backup"] = str(backup)
    _write_atomic(launcher, launcher_text())


def installed(home: Path) -> list[str]:
    base = runtime_dir(home)
    return sorted(p.name for p in base.iterdir() if (p / MANIFEST).is_file()) if base.is_dir() else []


def rollback(home: Path, version: str | None = None) -> dict[str, Any]:
    current = read_current(home)
    target = version or current.get("previous")
    if not target:
        raise RuntimeError_("NO_PREVIOUS: current.json names no previous version")
    verify(home, target)
    _set_current(home, target)
    return {"version": target, "current_before": current.get("version")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="runtime_install", description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="Write (default is a preview)")
    parser.add_argument("--rollback", nargs="?", const="", default=None, metavar="VERSION")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--home", type=Path, default=Path.home(), help=argparse.SUPPRESS)
    parser.add_argument("--repo", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.list:
            out: dict[str, Any] = {"installed": installed(args.home), "current": read_current(args.home)}
        elif args.rollback is not None:
            if not args.apply:
                target = args.rollback or read_current(args.home).get("previous")
                out = {"dry_run": True, "rollback_to": target}
            else:
                out = rollback(args.home, args.rollback or None)
        else:
            out = install(args.home, args.repo) if args.apply else {"dry_run": True, **plan(args.home, args.repo)}
    except RuntimeError_ as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **out}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
===END===

===FILE: tests/test_u48_r1_runtime_install.py===
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
===END===

===EDIT: v7_harness/global_install.py===
<<<<<<< SEARCH
        changes.append(_text_change("launcher", launcher, _read(launcher), launcher_text(repo)))
=======
        # U48-R1: once a versioned runtime is current, the launcher follows it; writing the repo launcher here would
        # put the worktree back on sys.path and undo the install.
        from v7_harness import runtime_install
        wanted = (runtime_install.launcher_text() if runtime_install.read_current(home).get("version")
                  else launcher_text(repo))
        changes.append(_text_change("launcher", launcher, _read(launcher), wanted))
>>>>>>> REPLACE

## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
