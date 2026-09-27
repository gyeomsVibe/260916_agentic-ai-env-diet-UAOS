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
