"""U50: context admission gate. docs/49 §2·§5 U-TOK-2.

The manual's optional `context_allow:` list names the extra files (patterns) a worker call may see. When the list is
present, a file reaches the call only if it is a pinned input, sits under `allow` (the worker has to see what it
edits), or matches `context_allow`; everything else the prompt happens to mention is left out and recorded as denied.
Nothing widens the list automatically: if a denial makes the acceptance fail, the fix is a new manual with a wider
list, and the denial record shows what was missing. A manual without `context_allow` keeps the old behaviour, except
that a file outside the workspace ("..", absolute path, symlink or junction) is never read in either mode.

U50-R2 (Codex TOCTOU verdict on U50-R1): admission used to return names and the caller re-read `workspace / name`
later, so a junction swapped in after the check leaked the file behind it. Admission now reads each admitted file once,
through one open handle whose final path (the path the operating system actually opened, links resolved) must lie
under the workspace, and hands out that text. Callers never open an admitted name again.
"""

from __future__ import annotations

import fnmatch
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

PINNED_RE = re.compile(r"^- (\S+) sha256=[0-9a-f]{64}\s*$", re.M)


@dataclass
class Admission:
    active: bool
    admitted: list[str] = field(default_factory=list)
    denied: list[str] = field(default_factory=list)
    escaped: list[str] = field(default_factory=list)
    # name -> text read through the checked handle; the only content a caller may use.
    snapshots: dict[str, str] = field(default_factory=dict)


def _norm(path: str) -> str:
    return path.strip().replace("\\", "/")


def _lexical_ok(rel: str) -> bool:
    pure = PurePosixPath(rel)
    return bool(rel) and not pure.is_absolute() and not re.match(r"^[A-Za-z]:", rel) and ".." not in pure.parts


def inside(workspace: Path, path: str) -> bool:
    """U50-R1 (Codex counterexample docs/../../outside.txt): a candidate is readable only if it is relative, has no
    "..", and still lies under the workspace after resolve() follows symlinks and junctions (reparse points).
    A pre-filter only: the read in snapshot() re-checks the path of the handle it actually opened."""
    rel = _norm(path)
    if not _lexical_ok(rel):
        return False
    root = Path(workspace).resolve()
    try:
        (root / rel).resolve().relative_to(root)
    except (ValueError, OSError):
        return False
    return True


def _fd_path(fd: int) -> str | None:
    """The final path of an open file: what the OS opened after following every link. None = cannot tell (refuse)."""
    if os.name == "nt":
        import ctypes
        import msvcrt
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD,
                                                       wintypes.DWORD]
        kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
        handle = msvcrt.get_osfhandle(fd)
        # 32767 = the longest extended-length path Windows accepts, so one call always fits.
        buffer = ctypes.create_unicode_buffer(32768)
        length = kernel32.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
        if not length or length >= len(buffer):
            return None
        path = buffer.value
        if path.startswith("\\\\?\\UNC\\"):
            return "\\\\" + path[8:]
        return path[4:] if path.startswith("\\\\?\\") else path
    if sys.platform.startswith("linux"):
        try:
            return os.readlink(f"/proc/self/fd/{fd}")
        except OSError:
            return None
    if sys.platform == "darwin":
        import fcntl

        try:
            # F_GETPATH = 50 on macOS: the kernel's path for the vnode behind the descriptor; MAXPATHLEN = 1024.
            raw = fcntl.fcntl(fd, 50, b"\0" * 1024)
            return raw.split(b"\0", 1)[0].decode("utf-8", "surrogateescape")
        except OSError:
            return None
    return None


def _under(path: str, root: Path) -> bool:
    # normpath, not realpath: resolving the handle's path again would follow the (possibly swapped) links a second time.
    try:
        Path(os.path.normcase(os.path.normpath(path))).relative_to(Path(os.path.normcase(str(root))))
    except ValueError:
        return False
    return True


def snapshot(workspace: Path, path: str) -> str | None:
    """Read one workspace file as text, or None when it is not provably inside. The check is on the open handle, so a
    link swapped in between any earlier check and this read is caught, and the text returned is the text checked."""
    rel = _norm(path)
    if not _lexical_ok(rel):
        return None
    root = Path(workspace).resolve()
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(root / rel, flags)
    except OSError:
        return None
    with os.fdopen(fd, "r", encoding="utf-8") as handle:
        real = _fd_path(fd)
        if real is None or not _under(real, root):
            return None
        try:
            return handle.read()
        except (OSError, UnicodeDecodeError):
            return None


def matches(path: str, patterns: list[str]) -> bool:
    """fnmatch on the posix path; a pattern ending in "/" admits everything under that folder."""
    path = _norm(path)
    for raw in patterns:
        pattern = _norm(raw)
        if not pattern:
            continue
        if pattern.endswith("/"):
            if path.startswith(pattern):
                return True
        elif fnmatch.fnmatchcase(path, pattern) or PurePosixPath(path) == PurePosixPath(pattern):
            return True
    return False


def admit(prompt: str, candidates: list[str], workspace: Path, read: bool = True) -> Admission:
    """Split candidates into admitted and denied by the contract in the prompt; order is kept, denials are sorted.
    The workspace boundary is checked first and in every mode, before any pattern match or read. With read=True each
    admitted file is also snapshotted; a file whose checked read fails moves to escaped."""
    from v7_harness.manual import parse_contract

    escaped = sorted(p for p in candidates if not inside(workspace, p))
    candidates = [p for p in candidates if p not in escaped]
    contract = parse_contract(prompt) or {}
    result = Admission(active="context_allow" in contract, escaped=escaped)
    if not result.active:
        result.admitted = list(candidates)
    else:
        pinned = {_norm(m) for m in PINNED_RE.findall(prompt)}
        patterns = [*contract.get("allow", []), *contract.get("context_allow", [])]
        for path in candidates:
            if _norm(path) in pinned or matches(path, patterns):
                result.admitted.append(path)
            else:
                result.denied.append(path)
        result.denied.sort()
    if read:
        for path in list(result.admitted):
            text = snapshot(workspace, path)
            if text is None:
                result.admitted.remove(path)
                result.escaped = sorted({*result.escaped, path})
            else:
                result.snapshots[path] = text
    return result
