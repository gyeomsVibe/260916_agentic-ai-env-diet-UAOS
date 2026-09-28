from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{20,}"),
]

REQUIRED_KEYS = (
    "schema",
    "work_id",
    "actor",
    "model",
    "kind",
    "collection_mode",
    "input_tokens",
    "output_tokens",
    "wall_time_s",
    "outcome",
    "receipt",
    "independent_verifier",
    "rsi_eligible",
    "exclusion_reason",
)

NULLABLE_KEYS = {
    "model",
    "input_tokens",
    "output_tokens",
    "wall_time_s",
    "independent_verifier",
    "exclusion_reason",
}

NON_NULLABLE_KEYS = set(REQUIRED_KEYS) - NULLABLE_KEYS

NON_EMPTY_STRING_KEYS = (
    "schema",
    "work_id",
    "actor",
    "kind",
    "collection_mode",
    "outcome",
    "receipt",
)

NULLABLE_STRING_KEYS = (
    "model",
    "independent_verifier",
    "exclusion_reason",
)


class UsageRejected(Exception):
    """Raised when a usage record fails validation or secret check."""
    pass


def _check_secrets(obj: Any) -> None:
    if isinstance(obj, str):
        for pat in SECRET_PATTERNS:
            if pat.search(obj):
                raise UsageRejected("secret detected in usage record")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _check_secrets(k)
            _check_secrets(v)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _check_secrets(item)


def record_usage(
    project_root: Path,
    entry: dict[str, Any],
    lock_timeout_s: float = 10.0,
) -> Path:
    if not isinstance(entry, dict):
        raise UsageRejected("entry must be a dict")

    for k in REQUIRED_KEYS:
        if k not in entry:
            raise UsageRejected(f"missing required key: {k}")
        if k in NON_NULLABLE_KEYS and entry[k] is None:
            raise UsageRejected(f"key cannot be null: {k}")

    # schema validation
    if entry["schema"] != "uaos-usage-v2":
        raise UsageRejected("schema must equal 'uaos-usage-v2'")

    # non-empty string validation
    for k in NON_EMPTY_STRING_KEYS:
        val = entry[k]
        if not isinstance(val, str) or len(val.strip()) == 0:
            raise UsageRejected(f"{k} must be a non-empty string")

    # nullable string validation
    for k in NULLABLE_STRING_KEYS:
        val = entry[k]
        if val is not None and not isinstance(val, str):
            raise UsageRejected(f"{k} must be a string or null")

    # rsi_eligible validation
    if not isinstance(entry["rsi_eligible"], bool):
        raise UsageRejected("rsi_eligible must be bool")

    # token counts validation
    for token_key in ("input_tokens", "output_tokens"):
        val = entry[token_key]
        if val is not None:
            if isinstance(val, bool) or not isinstance(val, int) or val < 0:
                raise UsageRejected(f"{token_key} must be a non-negative integer or null")

    # wall_time_s validation
    wall_time = entry["wall_time_s"]
    if wall_time is not None:
        if isinstance(wall_time, bool) or not isinstance(wall_time, (int, float)) or wall_time < 0:
            raise UsageRejected("wall_time_s must be a non-negative number or null")

    # Secret check on all values/strings
    _check_secrets(entry)

    # Immutability & ts handling
    record = dict(entry)
    if "ts" not in record or record["ts"] is None:
        record["ts"] = time.time()
    elif isinstance(record["ts"], bool) or not isinstance(record["ts"], (int, float)) or record["ts"] < 0:
        raise UsageRejected("ts must be a non-negative number")

    try:
        line = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    except (TypeError, ValueError) as err:
        raise UsageRejected(f"failed to serialize usage record: {err}") from err

    for pat in SECRET_PATTERNS:
        if pat.search(line):
            raise UsageRejected("secret detected in usage record")

    with _ledger_lock(Path(project_root), lock_timeout_s) as target_file:
        with open(target_file, "ab") as f:
            f.write(line.encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        return target_file


def ledger_file(project_root: Path) -> Path:
    """U72-L: the one ledger of a repository. A linked worktree's rows belong to the main checkout's desk (U59).

    Seen 2026-09-28: every pilot run from `.work/<id>` worktrees appended to that worktree's copy of the tracked
    `runs.jsonl`, which is never committed, so U68-U71 left no row in the desk ledger that admission and RSI read.
    """
    from .hook_context import shared_desk

    return shared_desk(Path(project_root)) / ".coord" / "usage" / "runs.jsonl"


class _ledger_lock:
    """The ledger's exclusive lock file; yields the ledger path. Fails closed with UsageRejected on timeout."""

    def __init__(self, project_root: Path, lock_timeout_s: float) -> None:
        self.target_file = ledger_file(project_root)
        self.lock_timeout_s = lock_timeout_s

    def __enter__(self) -> Path:
        self.target_file.parent.mkdir(parents=True, exist_ok=True)
        self.fd = _acquire(self.target_file.with_name("runs.jsonl.lock"), self.lock_timeout_s)
        return self.target_file

    def __exit__(self, *exc: Any) -> None:
        _release(self.fd, self.target_file.with_name("runs.jsonl.lock"))


def _acquire(lock_file: Path, lock_timeout_s: float) -> int:
    t_end = time.time() + lock_timeout_s
    fd: int | None = None
    while True:
        try:
            fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            break
        except (FileExistsError, PermissionError):
            if time.time() >= t_end:
                break
            time.sleep(0.005)

    if fd is None:
        raise UsageRejected("usage ledger lock timeout")
    return fd


def _release(fd: int, lock_file: Path) -> None:
    try:
        os.close(fd)
    except OSError:
        pass
    unlink_end = time.time() + 1.0
    while time.time() < unlink_end:
        try:
            os.unlink(str(lock_file))
            break
        except FileNotFoundError:
            break
        except OSError:
            time.sleep(0.002)


def _row_key(line: str) -> str | None:
    """A row's identity: its parsed JSON in canonical form, so CRLF checkouts and key order do not split one row."""
    try:
        row = json.loads(line)
    except ValueError:
        return None
    if not isinstance(row, dict):
        return None
    return json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _rows(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return [line.strip() for line in text.splitlines() if line.strip()]


def linked_worktrees(desk: Path) -> list[Path]:
    """Every linked checkout of this repository, read from `<desk>/.git/worktrees/<name>/gitdir`.

    Git records each linked worktree there as the path of its `.git` file. Reading those files needs no subprocess,
    so this adds no command-execution site to the U54 firewall audit.
    """
    trees = []
    for record in sorted((Path(desk) / ".git" / "worktrees").glob("*/gitdir")):
        try:
            marker = Path(record.read_text(encoding="utf-8").strip())
        except (OSError, UnicodeDecodeError):
            continue
        if marker.name == ".git" and marker.parent.is_dir():
            trees.append(marker.parent)
    return trees


def collect(project_root: Path, *, trees: list[Path] | None = None, apply: bool = False,
            lock_timeout_s: float = 10.0) -> dict[str, Any]:
    """U72-L: find rows that exist only in a worktree's ledger copy and, with apply, append them to the desk ledger.

    A row counts once however many worktrees hold it. The rows are appended byte for byte as their worktree wrote
    them (never re-validated or re-stamped: the ledger is append-only history). The whole read-compare-append runs
    under the ledger lock, so two collectors at once still append each row once.
    """
    desk = ledger_file(Path(project_root)).parent.parent.parent
    trees = linked_worktrees(desk) if trees is None else trees
    with _ledger_lock(desk, lock_timeout_s) as target_file:
        known = {key for key in map(_row_key, _rows(target_file)) if key}
        orphans: list[str] = []
        by_tree: dict[str, int] = {}
        for tree in trees:
            for line in _rows(Path(tree) / ".coord" / "usage" / "runs.jsonl"):
                key = _row_key(line)
                if key is None or key in known:
                    continue
                _check_secrets(json.loads(line))
                known.add(key)
                orphans.append(line)
                by_tree[str(tree)] = by_tree.get(str(tree), 0) + 1
        if apply and orphans:
            data = target_file.read_bytes() if target_file.is_file() else b""
            prefix = b"\n" if data and not data.endswith(b"\n") else b""
            with open(target_file, "ab") as f:
                f.write(prefix + "".join(line + "\n" for line in orphans).encode("utf-8"))
                f.flush()
                os.fsync(f.fileno())
    return {"ledger": str(target_file), "trees": len(trees), "orphans": len(orphans), "by_tree": by_tree,
            "appended": len(orphans) if apply else 0, "mode": "APPLY" if apply else "DRY_RUN"}
