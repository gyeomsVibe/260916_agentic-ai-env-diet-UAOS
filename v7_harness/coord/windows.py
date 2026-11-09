"""U114: one process (card) gets one dedicated, named window in each tool: Codex app-server thread, Claude desktop
session (U129: recorded, never `claude --bg`), Antigravity conversation. The record `.coord/windows/<card>.json` maps
the card to each tool's window id.
U279: Topic-grouped bounded window pool (`normalize_topic_key`, `window_for_topic`, `acquire_topic_window`) across
Codex, Claude Code, and Antigravity with Two-Phase Window Pool Cap (`MAX_ACTIVE_WINDOWS_PER_TOOL = 3`) outside remote
launch and dead-PID-safe `in_flight_leases`."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from v7_harness.coord.presence import read as read_presence

# A card id becomes a file name: no separators, spaces or "..", so a record never lands outside .coord/windows.
CARD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
# The three tools that own windows; Ollama is a calculator and has none.
TOOLS = ("codex", "claude", "antigravity")
# Antigravity answers the opening prompt before it prints the conversation id; one long card turn fits in 15 minutes.
AGY_TIMEOUT_S = 900
# U127: a record read or replace retries with 10 ms, 20 ms, ... back-off (about 2 s over 20 tries) while a parallel
# writer swaps it; the parallel test (8 threads x 10 writes) hit PermissionError on the first try without it.
RECORD_TRIES = 20
# U279: 3 active topic windows per tool bounds desktop sidebar/RAM sprawl (대화창 남발 방지) while the 5 process lanes
# (IMPL_CODE, VERIFY_AUDIT, ARCH_DESIGN, MERGE_RELEASE, RECOVERY_OPS — U287/U292) distribute work across the 3 tools
# (~1-2 lanes per tool at any instant, so 3 active topic windows per tool = 9 across 3 tools covers all 5 lanes with
# headroom for handoffs).
MAX_ACTIVE_WINDOWS_PER_TOOL = 3
# U127 / U279: maximum input tokens before a topic conversation window is rotated to a fresh window (leaves 30,000
# tokens headroom under the 100,000-token review cap after one ~28,000-token turn).
RESUME_MAX_INPUT = 70_000
# U279: first-line scan limit matches deliver.DELTA_LIMIT (120 chars); prefix scan limit is half a line (60 chars).
FIRST_LINE_SCAN_LIMIT = 120
PREFIX_SCAN_LIMIT = 60
# U279: cross-process file lock wait ceiling (200 * 0.01s = 2.0s) for short atomic window pool mutations.
WINDOW_LOCK_TRIES = 200
WINDOW_LOCK_SLEEP_S = 0.01

_CARD_FAMILY_RE = re.compile(r"(?:^|[^A-Za-z0-9])(U\d{2,4})(?=$|[^0-9])", re.IGNORECASE)
_SUBSTEP_SUFFIX_RE = re.compile(
    r"(?:[-_.](?:R\d+|L\d+|V\d+|A\d+|S\d+|STAGE\d*|FIX\d*|SLICE\d*|VERDICT|MANUAL|AUDIT|RETRY\d*|SPEC|\d{6,8}))+$",
    re.IGNORECASE,
)
_DESK_SYNC_RE = re.compile(r"^(?:CODEX[-_]RETURN|DESK[-_]|HANDOFF[-_]|RETURN[-_])", re.IGNORECASE)
_RSI_STREAM_RE = re.compile(r"^RSI[-_]([A-Za-z0-9]+)", re.IGNORECASE)
_REVIEW_STREAM_RE = re.compile(r"^(?:REVIEW|AUDIT)[-_]([A-Za-z0-9]+)", re.IGNORECASE)

_LOCAL_LOCKS = threading.local()
_PROC_LOCK_GUARD = threading.Lock()
_PROC_LOCKS: dict[str, threading.RLock] = {}


class WindowPoolExhaustedError(RuntimeError):
    """U279: Raised (or surfaced as `WINDOW_POOL_EXHAUSTED_IN_FLIGHT`) when all `MAX_ACTIVE_WINDOWS_PER_TOOL` slots
    have live `in_flight_leases` or live `RESERVING` PIDs."""


def _pid_is_definitely_dead(pid: object) -> bool:
    """U279: Return True ONLY when `pid` is proven dead.
    On Windows, `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)` returning NULL (`0`) treats ONLY
    `ERROR_INVALID_PARAMETER = 87` (PID does not exist in system table) as dead, never `ERROR_ACCESS_DENIED = 5`
    (which is a live protected/elevated process); if a handle is returned, `WaitForSingleObject == WAIT_OBJECT_0`
    proves the process has exited."""
    if type(pid) is not int or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        SYNCHRONIZE = 0x00100000
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        ERROR_INVALID_PARAMETER = 87
        WAIT_OBJECT_0 = 0x00000000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ctypes.get_last_error() == ERROR_INVALID_PARAMETER
        try:
            sync_handle = kernel32.OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if sync_handle:
                try:
                    return kernel32.WaitForSingleObject(sync_handle, 0) == WAIT_OBJECT_0
                finally:
                    kernel32.CloseHandle(sync_handle)
            exit_code = ctypes.c_ulong(0)
            STILL_ACTIVE = 259
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return exit_code.value != STILL_ACTIVE
            return False
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return False
    except ProcessLookupError:
        return True
    except OSError:
        return False


def _try_file_lock(fd: int) -> bool:
    if os.name == "nt":
        import msvcrt

        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    else:
        import fcntl

        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False


def _file_unlock(fd: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def _window_lock(project: Path, name: str = "pool"):
    """U279: Reentrant cross-process and cross-thread lock on `.coord/windows/.<name>.lock` so concurrent
    `record_window`, `release_window`, and `acquire_topic_window` calls never lose updates or exceed `max_active`."""
    held: dict[str, int] = getattr(_LOCAL_LOCKS, "held", None)
    if held is None:
        held = {}
        _LOCAL_LOCKS.held = held
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name or "pool")
    win_dir = Path(project) / ".coord" / "windows"
    win_dir.mkdir(parents=True, exist_ok=True)
    lock_path = (win_dir / f".{safe}.lock").resolve()
    key = os.path.normcase(str(lock_path))
    if held.get(key, 0) > 0:
        held[key] += 1
        try:
            yield
        finally:
            held[key] -= 1
        return

    with _PROC_LOCK_GUARD:
        rlock = _PROC_LOCKS.get(key)
        if rlock is None:
            rlock = threading.RLock()
            _PROC_LOCKS[key] = rlock
    with rlock:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        locked = False
        try:
            for _ in range(WINDOW_LOCK_TRIES):
                if _try_file_lock(fd):
                    locked = True
                    break
                time.sleep(WINDOW_LOCK_SLEEP_S)
            if not locked:
                raise TimeoutError(f"WINDOW_LOCK_TIMEOUT:{safe}")
            held[key] = 1
            yield
        finally:
            held.pop(key, None)
            if locked:
                try:
                    _file_unlock(fd)
                except OSError:
                    pass
            try:
                os.close(fd)
            except OSError:
                pass


# U129: a Claude window is a visible desktop session; its id is the Claude Code session UUID that `--resume` takes
# (CLAUDE_CODE_SESSION_ID inside that session). A banner prefix or a sidebar title is not one.
SESSION_ID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# U129: `claude --bg` sessions never show in the desktop app (docs agent-view), so nothing is launched; since
# 2026-10-02 every route is clickless (send_message into an idle visible session, never a task chip).
NO_VISIBLE_SESSION = ("a Claude card window is an idle visible Claude desktop session: the conductor sends it the "
                      "card with send_message and records it with `uaos coord window --card {card} --tool claude "
                      "--title <title> --session-id <session uuid>`; with no idle session `uaos coord window "
                      "--card {card} --tool auto` routes the card to Codex (ACTIVE) or Antigravity headless")
# U129: one desktop session works one card at a time, so a session held by another unreleased card is refused.
SESSION_BUSY = ("Claude desktop session {session} still holds card {holder}; the conductor releases it with "
                "`uaos coord window --card {holder} --tool claude --title <title> --release` or routes this card "
                "with `--tool auto`")


def normalize_topic_key(card: str, message: str = "") -> str:
    """U279: normalize a sub-card, retry, PR tag, or message prefix into a canonical topic key so related tasks share
    one window instead of spawning separate windows per micro-step (대화창 남발 방지)."""
    raw = (card or "").strip()
    if raw:
        if ".." in raw or not CARD_RE.fullmatch(raw):
            raise ValueError(f"bad card id: {card!r}")
        match = _CARD_FAMILY_RE.search(raw)
        if match:
            return match.group(1).upper()
        if _DESK_SYNC_RE.search(raw):
            return "DESK-SYNC"
        rsi_match = _RSI_STREAM_RE.search(raw)
        if rsi_match:
            token = rsi_match.group(1).upper()
            return "RSI-STREAM" if token == "STREAM" else f"RSI-{token}"
        rev_match = _REVIEW_STREAM_RE.search(raw)
        if rev_match:
            token = rev_match.group(1).upper()
            return "REVIEW-STREAM" if token == "STREAM" else f"REVIEW-{token}"
        stripped = _SUBSTEP_SUFFIX_RE.sub("", raw).strip("-_.")
        if stripped and CARD_RE.fullmatch(stripped):
            return stripped.upper()
        return raw
    if message:
        first_line = next((line.strip() for line in message.splitlines() if line.strip()), "")
        match = _CARD_FAMILY_RE.search(first_line[:FIRST_LINE_SCAN_LIMIT])
        if match:
            return match.group(1).upper()
        if _DESK_SYNC_RE.search(first_line[:PREFIX_SCAN_LIMIT]):
            return "DESK-SYNC"
    return ""


def window_title(card: str, title: str) -> str:
    return f"[{card}] {title}"


def _record_path(project: Path, card: str) -> Path:
    if not CARD_RE.fullmatch(card or "") or ".." in card:
        raise ValueError(f"bad card id: {card!r}")
    return Path(project) / ".coord" / "windows" / f"{card}.json"


def _registry_path(project: Path) -> Path:
    return Path(project) / ".coord" / "windows.json"


def _retry(op: Callable[[], Any]) -> Any:
    """U127: Windows refuses to open or replace a record while a parallel writer swaps it; retry with back-off."""
    for attempt in range(RECORD_TRIES):
        try:
            return op()
        except PermissionError:
            if attempt == RECORD_TRIES - 1:
                raise
            time.sleep(0.01 * (attempt + 1))


def _load(path: Path) -> dict[str, Any]:
    try:
        return _retry(lambda: json.loads(path.read_text(encoding="utf-8"))) if path.is_file() else {}
    except (ValueError, PermissionError, OSError):
        return {}


def _sync_registry_index(project: Path, card: str, record: dict[str, Any]) -> bool:
    """U279: Mirror per-card window state into `.coord/windows.json` under `registry_index` lock so callers inspecting
    either `.coord/windows/<card>.json` or `.coord/windows.json` observe identical durable state.
    On a persistent Windows sharing violation (`PermissionError` after `RECORD_TRIES`), records a durable
    `.coord/windows/.mirror_sync_warning.json` receipt instead of silently dropping the update."""
    reg_path = _registry_path(project)
    with _window_lock(project, "registry_index"):
        reg = _load(reg_path)
        if not isinstance(reg, dict):
            reg = {}
        cards = dict(reg.get("cards") or {})
        cards[card] = record
        reg["cards"] = cards
        reg["updated_at"] = time.time()
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = reg_path.with_name(f"windows.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            _retry(lambda: tmp.replace(reg_path))
            return True
        except PermissionError as exc:
            tmp.unlink(missing_ok=True)
            warn_path = Path(project) / ".coord" / "windows" / ".mirror_sync_warning.json"
            try:
                warn_path.write_text(
                    json.dumps(
                        {
                            "warning": "WINDOWS_MIRROR_SYNC_FAILED",
                            "card": card,
                            "error": f"{type(exc).__name__}:{exc}",
                            "at": time.time(),
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            except OSError:
                pass
            return False


def _prune_entry_leases(entry: dict[str, Any]) -> tuple[dict[str, dict[str, int | float]], bool]:
    """U279: Prune dead-PID or malformed entries from `in_flight_leases: dict[str, dict[str, int | float]]` using
    `_pid_is_definitely_dead(pid)`. Malformed leases (`not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0`)
    are dropped instead of re-stamped with the current writer's PID (P3-2). Returns `(live_leases, changed)`."""
    raw_leases = entry.get("in_flight_leases")
    live: dict[str, dict[str, int | float]] = {}
    changed = False
    if isinstance(raw_leases, dict):
        for lid, info in raw_leases.items():
            if not isinstance(info, dict):
                changed = True
                continue
            pid = info.get("pid")
            if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
                changed = True
                continue
            if _pid_is_definitely_dead(pid):
                changed = True
                continue
            live[str(lid)] = {"pid": int(pid), "at": float(info.get("at") or 0.0)}
    return live, changed


def _entry_is_in_flight(entry: dict[str, Any]) -> bool:
    live, _ = _prune_entry_leases(entry)
    if live:
        return True
    if "in_flight_leases" in entry and isinstance(entry.get("in_flight_leases"), dict):
        return False
    return bool(entry.get("in_flight")) or (type(entry.get("in_flight_count")) is int and entry["in_flight_count"] > 0)


def claude_session(short: str) -> tuple[str, str]:
    """U115 judge: a U114 window record may hold an id prefix, but `--resume` needs the full id, and the transcript moves with a
    session that entered a worktree. Return (full id, latest cwd) from the one transcript `<prefix>*.jsonl` under
    `$CLAUDE_CONFIG_DIR` (default ~/.claude) `/projects/*/`; with none or several matches return (short, "")."""
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    found = sorted((home / "projects").glob(f"*/{short}*.jsonl"))
    if len(found) != 1:
        return short, ""
    cwd = ""
    with found[0].open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("cwd"):
                cwd = str(row["cwd"])
    return found[0].stem, cwd


def claude_session_identity(thread: str) -> tuple[str, str]:
    """U190-A strict native identity (Codex REVISE relay_b1204616: a file name is not a session).

    ("OK", latest cwd) only when the claude_session lookup finds exactly one transcript, its name is the thread, at
    least one row carries a sessionId and every sessionId is the thread; ("UNREADABLE", "") on a read error;
    ("UNVERIFIED", "") otherwise."""
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    try:
        found = sorted((home / "projects").glob(f"*/{thread}*.jsonl"))
        if len(found) != 1 or found[0].stem != thread:
            return "UNVERIFIED", ""
        cwd, named = "", False
        with found[0].open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                if row.get("sessionId") is not None:
                    if row["sessionId"] != thread:
                        return "UNVERIFIED", ""
                    named = True
                if row.get("cwd"):
                    cwd = str(row["cwd"])
    except OSError:
        return "UNREADABLE", ""
    return ("OK", cwd) if named else ("UNVERIFIED", "")


def _is_entry_active(entry: dict[str, Any]) -> bool:
    if not isinstance(entry, dict) or not entry.get("id"):
        return False
    if entry.get("released_at") or entry.get("state") in ("RELEASED", "RESERVING"):
        return False
    return True


def window_for(project: Path, card: str, tool: str) -> str | None:
    exact = _load(_record_path(project, card)).get("tools", {}).get(tool, {})
    if _is_entry_active(exact):
        return str(exact["id"])
    # U279: if `card` is a derived sub-card (e.g. `U275-R8-L1`, `PR244-U275`), automatically reuse the canonical
    # topic window (`U275`) so sub-tasks do not fall back to the primary user desk or demand separate windows.
    topic = normalize_topic_key(card)
    if topic and topic != card:
        topic_entry = _load(_record_path(project, topic)).get("tools", {}).get(tool, {})
        if _is_entry_active(topic_entry):
            return str(topic_entry["id"])
    return None


def window_entry(project: Path, card: str, tool: str) -> dict[str, Any]:
    """U127: the card's window entry for one tool ({} when there is none), with dead-PID leases pruned."""
    entry = dict(_load(_record_path(project, card)).get("tools", {}).get(tool) or {})
    if not entry:
        return {}
    if "in_flight_leases" in entry:
        live, _ = _prune_entry_leases(entry)
        entry["in_flight_leases"] = live
        entry["in_flight_count"] = len(live)
        entry["in_flight"] = bool(live)
    return entry


def window_entry_for_topic(project: Path, card: str, tool: str) -> tuple[str, dict[str, Any]]:
    """U279: return `(resolved_topic_or_card, entry)` checking the exact card first, then its canonical `topic_key`."""
    exact = window_entry(project, card, tool)
    if _is_entry_active(exact):
        return card, exact
    topic = normalize_topic_key(card)
    if topic and topic != card:
        topic_entry = window_entry(project, topic, tool)
        if _is_entry_active(topic_entry):
            return topic, topic_entry
    return (topic or card), exact


def window_for_topic(project: Path, card: str, tool: str) -> str | None:
    """U279: resolve an active window ID for `card` or its canonical `topic_key`."""
    _, entry = window_entry_for_topic(project, card, tool)
    if _is_entry_active(entry):
        return str(entry["id"])
    return None


def _write_card_record_locked(project: Path, card: str, tool: str, entry: dict[str, Any], *,
                              title: str | None = None) -> dict[str, Any]:
    path = _record_path(project, card)
    record = _load(path)
    record = {
        "card": card,
        "title": title or record.get("title") or f"[{card}]",
        "tools": {**record.get("tools", {}), tool: entry},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.stem}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        _retry(lambda: tmp.replace(path))
    except PermissionError:
        tmp.unlink(missing_ok=True)
        raise
    _sync_registry_index(project, card, record)
    return entry


def record_window(project: Path, card: str, tool: str, window_id: str, *, now: float | None = None,
                  title: str | None = None, **extra: Any) -> dict[str, Any]:
    """U127 / U279: atomically write one tool's window for a card under per-card `_window_lock` so parallel
    writers on the same card serialize without blocking other cards or lanes."""
    path = _record_path(project, card)
    with _window_lock(project, f"card_{card}"):
        record = _load(path)
        ts = time.time() if now is None else now
        old = record.get("tools", {}).get(tool) or {}
        state = extra.pop("state", None)
        extra.pop("window_id", None)
        if state is None:
            state = "RELEASED" if extra.get("released_at") else "ACTIVE"
        entry: dict[str, Any] = {
            "id": window_id,
            "window_id": window_id,
            "state": state,
            "opened_at": ts,
            "last_active_at": ts,
            "updated_at": ts,
            **extra,
        }
        if old.get("id") == window_id and "opened_at" in old:
            entry["opened_at"] = old["opened_at"]
        if "subcards" in old and "subcards" not in extra:
            entry["subcards"] = old["subcards"]
        if "topic_key" in old and "topic_key" not in extra:
            entry["topic_key"] = old["topic_key"]
        if "in_flight_leases" in entry:
            live, _ = _prune_entry_leases(entry)
            entry["in_flight_leases"] = live
            entry["in_flight_count"] = len(live)
            entry["in_flight"] = bool(live)
        elif "in_flight_leases" in old and "in_flight" not in extra and "in_flight_count" not in extra:
            live, _ = _prune_entry_leases(old)
            entry["in_flight_leases"] = live
            entry["in_flight_count"] = len(live)
            entry["in_flight"] = bool(live)
        elif extra.get("in_flight") is True and "in_flight_leases" not in extra:
            lid = f"manual-{os.getpid()}"
            entry["in_flight_leases"] = {lid: {"pid": os.getpid(), "at": ts}}
            entry["in_flight_count"] = 1
            entry["in_flight"] = True
        elif extra.get("in_flight") is False and "in_flight_leases" not in extra:
            entry["in_flight_leases"] = {}
            entry["in_flight_count"] = 0
            entry["in_flight"] = False
        return _write_card_record_locked(project, card, tool, entry, title=title)


def acquire_window_lease(project: Path, card: str, tool: str, *, lease_id: str | None = None,
                         pid: int | None = None, now: float | None = None) -> str:
    """U279: Acquire a dead-PID-safe in-flight lease on `(card, tool)` under `card_<topic>` lock."""
    project = Path(project)
    lid = lease_id or uuid.uuid4().hex
    owner_pid = os.getpid() if pid is None else int(pid)
    ts = time.time() if now is None else now
    topic, entry = window_entry_for_topic(project, card, tool)
    target_card = topic if entry else (normalize_topic_key(card) or card)
    with _window_lock(project, f"card_{target_card}"):
        raw = _load(_record_path(project, target_card)).get("tools", {}).get(tool) or {}
        if not raw.get("id") or raw.get("released_at") or raw.get("state") == "RELEASED":
            return ""
        live, _ = _prune_entry_leases(raw)
        live[lid] = {"pid": owner_pid, "at": ts}
        updated = {
            **raw,
            "in_flight_leases": live,
            "in_flight_count": len(live),
            "in_flight": True,
            "last_active_at": ts,
            "updated_at": ts,
        }
        _write_card_record_locked(project, target_card, tool, updated)
        return lid


def release_window_lease(project: Path, card: str, tool: str, lease_id: str, *, now: float | None = None) -> None:
    """U279: Release a specific `lease_id` from `in_flight_leases` under `card_<topic>` lock, pruning dead-PID leases."""
    if not lease_id:
        return
    project = Path(project)
    ts = time.time() if now is None else now
    topic, entry = window_entry_for_topic(project, card, tool)
    target_card = topic if entry else (normalize_topic_key(card) or card)
    with _window_lock(project, f"card_{target_card}"):
        raw = _load(_record_path(project, target_card)).get("tools", {}).get(tool) or {}
        if not raw:
            return
        live, _ = _prune_entry_leases(raw)
        live.pop(lease_id, None)
        updated = {
            **raw,
            "in_flight_leases": live,
            "in_flight_count": len(live),
            "in_flight": bool(live),
            "updated_at": ts,
        }
        _write_card_record_locked(project, target_card, tool, updated)


@contextmanager
def window_lease(project: Path, card: str, tool: str):
    """U279: Context manager that acquires and releases a dead-PID-safe in-flight lease around a live window turn."""
    lid = acquire_window_lease(project, card, tool)
    try:
        yield lid
    finally:
        if lid:
            release_window_lease(project, card, tool, lid)


def set_window_in_flight(project: Path, card: str, tool: str, in_flight: bool, *, pid: int | None = None) -> None:
    """U279: Reference-counted dead-PID-safe lease wrapper for callers using boolean `set_window_in_flight`.
    Only removes a lease owned by `target_pid` (defaults to `os.getpid()`), never another process's live lease (P3-3)."""
    project = Path(project)
    ts = time.time()
    target_pid = os.getpid() if pid is None else int(pid)
    topic, entry = window_entry_for_topic(project, card, tool)
    target_card = topic if entry else (normalize_topic_key(card) or card)
    with _window_lock(project, f"card_{target_card}"):
        raw = _load(_record_path(project, target_card)).get("tools", {}).get(tool) or {}
        if not raw.get("id") or raw.get("released_at") or raw.get("state") == "RELEASED":
            return
        live, _ = _prune_entry_leases(raw)
        if in_flight:
            lid = f"turn-{target_pid}-{uuid.uuid4().hex[:8]}"
            live[lid] = {"pid": target_pid, "at": ts}
        else:
            own_keys = [k for k, v in live.items() if v.get("pid") == target_pid]
            if own_keys:
                live.pop(own_keys[-1], None)
        updated = {
            **raw,
            "in_flight_leases": live,
            "in_flight_count": len(live),
            "in_flight": bool(live),
            "updated_at": ts,
        }
        if in_flight:
            updated["last_active_at"] = ts
        _write_card_record_locked(project, target_card, tool, updated)


def _prune_pool_for_tool(project: Path, tool: str, *, now: float | None = None) -> list[dict[str, Any]]:
    """U279: Under `pool_<tool>` lock, prune dead-PID `in_flight_leases` and stale `RESERVING` records whose
    `reserving_pid` satisfies `_pid_is_definitely_dead(reserving_pid)`. Returns all non-released slots (`ACTIVE` + live
    `RESERVING`) ordered oldest-active first (LRU)."""
    win_dir = Path(project) / ".coord" / "windows"
    if not win_dir.is_dir():
        return []
    ts = time.time() if now is None else now
    slots: list[dict[str, Any]] = []
    for path in sorted(win_dir.glob("*.json")):
        card_id = path.stem
        if not CARD_RE.fullmatch(card_id):
            continue
        with _window_lock(project, f"card_{card_id}"):
            rec = _load(path)
            entry = (rec.get("tools") or {}).get(tool)
            if not isinstance(entry, dict):
                continue
            state = entry.get("state") or ("RELEASED" if entry.get("released_at") else "ACTIVE")
            if state == "RELEASED" or entry.get("released_at"):
                continue
            if state == "RESERVING":
                rpid = entry.get("reserving_pid")
                if _pid_is_definitely_dead(rpid):
                    released_entry = {
                        **entry,
                        "state": "RELEASED",
                        "released_at": ts,
                        "release_reason": "dead_reserving_pid",
                        "released_reason": "dead_reserving_pid",
                        "updated_at": ts,
                    }
                    _write_card_record_locked(project, card_id, tool, released_entry)
                    continue
                slots.append({
                    "card": str(rec.get("card") or card_id),
                    "topic_key": normalize_topic_key(str(rec.get("card") or card_id)),
                    "id": str(entry.get("id") or ""),
                    "state": "RESERVING",
                    "reserving_pid": rpid,
                    "reservation_id": str(entry.get("reservation_id") or ""),
                    "opened_at": float(entry.get("opened_at") or ts),
                    "last_active_at": float(entry.get("last_active_at") or entry.get("updated_at") or ts),
                    "last_input_tokens": 0,
                    "in_flight_leases": {},
                    "in_flight": True,
                    "in_flight_count": 1,
                    "subcards": list(entry.get("subcards") or []),
                    "entry": entry,
                })
                continue
            if not entry.get("id"):
                continue
            live_leases, changed = _prune_entry_leases(entry)
            if changed:
                entry = {
                    **entry,
                    "in_flight_leases": live_leases,
                    "in_flight_count": len(live_leases),
                    "in_flight": bool(live_leases),
                    "updated_at": ts,
                }
                _write_card_record_locked(project, card_id, tool, entry)
            in_flight_flag = bool(live_leases) if "in_flight_leases" in entry else _entry_is_in_flight(entry)
            slots.append({
                "card": str(rec.get("card") or card_id),
                "topic_key": normalize_topic_key(str(rec.get("card") or card_id)),
                "id": str(entry["id"]),
                "state": "ACTIVE",
                "opened_at": float(entry.get("opened_at") or 0.0),
                "last_active_at": float(entry.get("last_active_at") or entry.get("opened_at") or 0.0),
                "last_input_tokens": int(entry["last_input_tokens"]) if type(entry.get("last_input_tokens")) is int else 0,
                "in_flight_leases": live_leases,
                "in_flight": in_flight_flag,
                "in_flight_count": len(live_leases) if "in_flight_leases" in entry else (1 if in_flight_flag else 0),
                "subcards": list(entry.get("subcards") or []),
                "entry": entry,
            })
    slots.sort(key=lambda item: (item["last_active_at"], item["opened_at"], item["card"]))
    return slots


def active_topic_windows(project: Path, tool: str) -> list[dict[str, Any]]:
    """U279: return all `ACTIVE` (unreleased, non-reserving) windows for `tool` across `.coord/windows/*.json`, ordered
    oldest-active first (LRU order), pruning any dead-PID leases."""
    return [slot for slot in _prune_pool_for_tool(project, tool) if slot.get("state") == "ACTIVE"]


def _codex_rpc_session() -> Callable[[str, dict], dict]:
    """A JSON-RPC client over one `codex app-server` stdio process (the official thread API, not Codex's own files)."""
    proc = subprocess.Popen([shutil.which("codex") or "codex", "app-server"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if os.name == "nt" else 0)
    counter = {"id": 0}

    def send(message: dict) -> None:
        proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        proc.stdin.flush()

    def answer(request_id: int) -> dict:
        for line in proc.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError(str(message["error"]))
                return message.get("result") or {}
        raise RuntimeError("codex app-server closed before answering")

    def call(method: str, params: dict) -> dict:
        counter["id"] += 1
        send({"jsonrpc": "2.0", "id": counter["id"], "method": method, "params": params})
        return answer(counter["id"])

    send({"jsonrpc": "2.0", "id": 0, "method": "initialize",
          "params": {"clientInfo": {"name": "uaos", "title": "UAOS", "version": "0"}}})
    answer(0)
    send({"jsonrpc": "2.0", "method": "initialized"})
    call.proc = proc
    return call


def _open_codex(project: Path, title: str, prompt: str, rpc: Callable[[str, dict], dict] | None) -> str:
    own = rpc is None
    if own:
        rpc = _codex_rpc_session()
    try:
        thread_id = rpc("thread/start", {"cwd": str(project)})["thread"]["id"]
        rpc("turn/start", {"threadId": thread_id, "input": [{"type": "text", "text": prompt}]})
        # The name comes after the first turn: before it the thread has no rollout, so no sidebar row (U114 probe).
        rpc("thread/name/set", {"threadId": thread_id, "name": title})
        return thread_id
    finally:
        if own:
            rpc.proc.kill()


def _open_antigravity(project: Path, prompt: str, runner: Callable[..., Any]) -> tuple[str, int | None]:
    kwargs: dict[str, Any] = dict(
        cwd=str(project), capture_output=True, text=True, encoding="utf-8", timeout=AGY_TIMEOUT_S
    )
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    done = runner([shutil.which("agy") or "agy", "-p", prompt, "--output-format", "json"], **kwargs)
    raw = done.stdout or ""
    try:
        envelope = json.loads(raw)
    except ValueError:
        match = re.search(r"\{.*\}", raw, re.S)
        envelope = json.loads(match.group(0)) if match else {}
    tokens = (envelope.get("usage") or {}).get("input_tokens")
    return str(envelope["conversation_id"]), tokens if type(tokens) is int and tokens >= 0 else None


def open_window(project: Path, card: str, tool: str, title: str, prompt: str, *,
                runner: Callable[..., Any] | None = None, rpc: Callable[[str, dict], dict] | None = None,
                now: float | None = None, session_id: str | None = None, pool: bool = False) -> dict[str, Any]:
    project = Path(project)
    if runner is None:
        runner = subprocess.run
    if pool:
        return acquire_topic_window(project, card, tool, title, prompt, runner=runner, rpc=rpc, now=now,
                                    session_id=session_id)
    path = _record_path(project, card)
    if tool not in TOOLS:
        raise ValueError(f"unknown tool: {tool}")
    if session_id is not None and tool != "claude":
        raise ValueError("--session-id applies to claude only")
    raw_session_id = session_id
    if session_id is not None:
        session_id = _claude_session_id(session_id)
    # Hold per-(card, tool) lock `open_<card>_<tool>` across launch so concurrent callers for the SAME
    # (card, tool) never launch twice, while callers for any OTHER card or tool are never blocked.
    with _window_lock(project, f"open_{card}_{tool}"):
        with _window_lock(project, f"card_{card}"):
            record = _load(path)
            existing = record.get("tools", {}).get(tool)
            if existing and _is_entry_active(existing):  # U129: a released window is done, never reused
                return {**existing, "reused": True}
            state = read_presence(project, tool)["state"]
            if state in ("LIMITED", "ABSENT"):  # U113: nothing waits in a limited tool's thread
                return {"refused": state, "tool": tool, "card": card}
            if tool == "claude":
                if session_id is None:
                    return {"refused": "NO_VISIBLE_SESSION", "tool": tool, "card": card,
                            "message": NO_VISIBLE_SESSION.format(card=card)}
                holder = session_busy(project, session_id, card)
                if holder:
                    return {"refused": "SESSION_BUSY", "tool": tool, "card": card, "held_by": holder,
                            "message": SESSION_BUSY.format(session=session_id, holder=holder)}
        name = window_title(card, title)
        extra: dict[str, Any] = {}
        if tool == "codex":
            window_id = _open_codex(project, name, prompt, rpc)
        elif tool == "claude":
            window_id = str(session_id)
            if isinstance(raw_session_id, str) and raw_session_id.strip().lower().startswith("local_"):
                extra["native_id"] = f"local_{window_id}"
        else:
            window_id, tokens = _open_antigravity(project, prompt, runner)
            if tokens is not None:  # U131: the opening turn's size, so the U127 resume cap can read it
                extra["last_input_tokens"] = tokens
        with _window_lock(project, f"card_{card}"):
            record = _load(path)
            existing = record.get("tools", {}).get(tool)
            if existing and _is_entry_active(existing):
                return {**existing, "reused": True}
            ts = time.time() if now is None else now
            public_entry: dict[str, Any] = {"id": window_id, "opened_at": ts, **extra}
            entry = {
                **public_entry,
                "state": "ACTIVE",
                "last_active_at": ts,
                "updated_at": ts,
                "in_flight_leases": {},
                "in_flight_count": 0,
                "in_flight": False,
            }
            _write_card_record_locked(project, card, tool, entry, title=name)
            return {**public_entry, "reused": False}


def acquire_topic_window(
    project: Path,
    card: str,
    tool: str,
    title: str,
    prompt: str,
    *,
    runner: Callable[..., Any] | None = None,
    rpc: Callable[[str, dict], dict] | None = None,
    now: float | None = None,
    session_id: str | None = None,
    max_active: int = MAX_ACTIVE_WINDOWS_PER_TOOL,
    token_cap: int = RESUME_MAX_INPUT,
    overflow_policy: str = "evict_lru",
    dry_run: bool = False,
    raise_on_exhausted: bool = False,
) -> dict[str, Any]:
    """U279: Two-Phase Topic-Grouped Window Pool Cap (`MAX_ACTIVE_WINDOWS_PER_TOOL = 3`) Outside Remote Launch.

    Phase 1 (Short Lock `pool_<tool>` -> `card_<topic_key>`, no subprocess launch):
      - If `topic_key` already has an `ACTIVE` window under `token_cap`, reuse it immediately (`reused=True`).
      - Check tool presence / Claude session availability before mutating the pool so refused opens never evict victims.
      - Prune dead-PID leases and stale `RESERVING` slots whose `reserving_pid` is dead (`_pid_is_definitely_dead`).
      - While `active + reserving >= max_active` (`3`), evict the oldest LRU `ACTIVE` window with
        `in_flight_leases == {}`, marking `state="RELEASED"`; if all slots have live `in_flight_leases` or live
        `RESERVING` PIDs, fail closed with `WINDOW_POOL_EXHAUSTED_IN_FLIGHT` (or raise `WindowPoolExhaustedError` when
        `raise_on_exhausted=True`).
      - Write a placeholder record with `state="RESERVING"`, `reserving_pid=os.getpid()`, `reservation_id=<uuid4_hex>`
        and RELEASE `pool_<tool>` and `card_<topic_key>` locks.
    Phase 2 (Remote Launch Outside `pool_<tool>` Lock):
      - Run `_open_codex` / `_open_antigravity` / Claude session assignment without holding `pool_<tool>`.
    Phase 3 (Finalize Under `card_<topic_key>` Lock):
      - Transition the `RESERVING` record (matching `reservation_id`) to `state="ACTIVE"` on success, or to
        `state="RELEASED"` (`release_reason="launch_failed"`) on failure/exception."""
    project = Path(project)
    if runner is None:
        runner = subprocess.run
    if tool not in TOOLS:
        raise ValueError(f"unknown tool: {tool}")
    if session_id is not None and tool != "claude":
        raise ValueError("--session-id applies to claude only")
    if session_id is not None:
        session_id = _claude_session_id(session_id)
    ts = time.time() if now is None else now
    topic_key = normalize_topic_key(card, prompt) or card
    _record_path(project, topic_key)

    rotated_from: str | None = None
    rotated_snapshot: dict[str, Any] | None = None
    evicted_cards: list[str] = []
    evicted_snapshots: list[tuple[str, dict[str, Any]]] = []
    reservation_id = uuid.uuid4().hex

    # Serialize same-(topic_key, tool) launches while keeping other topics and tools unblocked during Phase 2.
    with _window_lock(project, f"open_{topic_key}_{tool}"):
        # ── Phase 1: Short Lock (`pool_<tool>` -> `card_<topic_key>`, zero subprocess I/O) ──
        with _window_lock(project, f"pool_{tool}"):
            with _window_lock(project, f"card_{topic_key}"):
                existing = window_entry(project, topic_key, tool)
                if _is_entry_active(existing):
                    tokens = existing.get("last_input_tokens")
                    if type(tokens) is int and tokens >= token_cap:
                        rotated_from = str(existing["id"])
                        rotated_snapshot = json.loads(json.dumps(existing))
                    else:
                        subcards = list(existing.get("subcards") or [])
                        if card not in subcards:
                            subcards.append(card)
                        updated = record_window(
                            project,
                            topic_key,
                            tool,
                            str(existing["id"]),
                            now=ts,
                            **{
                                k: v
                                for k, v in existing.items()
                                if k not in ("id", "state", "opened_at", "last_active_at", "updated_at", "subcards", "topic_key")
                            },
                            state="ACTIVE",
                            subcards=subcards,
                            topic_key=topic_key,
                        )
                        return {**updated, "reused": True, "topic_key": topic_key, "card": card}

                # Pre-check presence and Claude session before touching any pool slot so a refused open never evicts victims.
                state = read_presence(project, tool)["state"]
                if state in ("LIMITED", "ABSENT"):
                    return {"refused": state, "tool": tool, "card": topic_key, "topic_key": topic_key, "requested_card": card}
                if tool == "claude":
                    if session_id is None:
                        return {
                            "refused": "NO_VISIBLE_SESSION",
                            "tool": tool,
                            "card": topic_key,
                            "topic_key": topic_key,
                            "requested_card": card,
                            "message": NO_VISIBLE_SESSION.format(card=topic_key),
                        }
                    holder = session_busy(project, session_id, topic_key)
                    if holder:
                        return {
                            "refused": "SESSION_BUSY",
                            "tool": tool,
                            "card": topic_key,
                            "topic_key": topic_key,
                            "requested_card": card,
                            "held_by": holder,
                            "message": SESSION_BUSY.format(session=session_id, holder=holder),
                        }

                if rotated_from:
                    release_window(project, topic_key, tool, now=ts, reason="TOKEN_CAP_ROTATED")

            slots = [s for s in _prune_pool_for_tool(project, tool, now=ts) if s["card"] != topic_key]
            if max_active > 0 and len(slots) >= max_active:
                active_only = [s for s in slots if s.get("state") == "ACTIVE"]
                if overflow_policy == "share_least_loaded" and active_only:
                    least = min(active_only, key=lambda item: (item["last_input_tokens"], item["last_active_at"]))
                    subcards = list(least["subcards"])
                    if card not in subcards:
                        subcards.append(card)
                    shared = record_window(
                        project,
                        topic_key,
                        tool,
                        least["id"],
                        now=ts,
                        state="ACTIVE",
                        topic_key=topic_key,
                        shared_from=least["card"],
                        subcards=subcards,
                        last_input_tokens=least["last_input_tokens"],
                    )
                    return {**shared, "reused": True, "topic_key": topic_key, "card": card, "shared_from": least["card"]}

                while len(slots) >= max_active:
                    victim = next(
                        (
                            s
                            for s in slots
                            if s.get("state") == "ACTIVE"
                            and not s.get("in_flight")
                            and not s.get("in_flight_leases")
                        ),
                        None,
                    )
                    if victim is None:
                        if raise_on_exhausted:
                            raise WindowPoolExhaustedError(f"WINDOW_POOL_EXHAUSTED_IN_FLIGHT:{tool}:{topic_key}")
                        return {
                            "refused": "WINDOW_POOL_EXHAUSTED_IN_FLIGHT",
                            "reason": "POOL_ALL_IN_FLIGHT",
                            "tool": tool,
                            "card": topic_key,
                            "topic_key": topic_key,
                            "requested_card": card,
                        }
                    evict_card = victim["card"]
                    with _window_lock(project, f"card_{evict_card}"):
                        fresh_victim = window_entry(project, evict_card, tool)
                        live_leases, _ = _prune_entry_leases(fresh_victim)
                        if live_leases or _entry_is_in_flight(fresh_victim):
                            victim["in_flight"] = True
                            victim["in_flight_leases"] = live_leases
                            continue
                        victim_snapshot = json.loads(json.dumps(fresh_victim))
                        rel_entry = {
                            **fresh_victim,
                            "state": "RELEASED",
                            "released_at": ts,
                            "release_reason": "POOL_CAP_LRU_EVICTED",
                            "released_reason": "POOL_CAP_LRU_EVICTED",
                            "evicted_by_reservation": reservation_id,
                            "updated_at": ts,
                        }
                        _write_card_record_locked(project, evict_card, tool, rel_entry)
                        evicted_cards.append(evict_card)
                        evicted_snapshots.append((evict_card, victim_snapshot))
                        slots = [s for s in slots if s["card"] != evict_card]

            # Write RESERVING placeholder under `card_<topic_key>` lock and release both `card_<topic_key>` and `pool_<tool>`!
            with _window_lock(project, f"card_{topic_key}"):
                reserving_entry: dict[str, Any] = {
                    "id": "",
                    "state": "RESERVING",
                    "reserving_pid": os.getpid(),
                    "reservation_id": reservation_id,
                    "opened_at": ts,
                    "last_active_at": ts,
                    "updated_at": ts,
                    "topic_key": topic_key,
                    "in_flight_leases": {},
                    "in_flight_count": 0,
                    "in_flight": False,
                }
                if rotated_from:
                    reserving_entry["rotated_from"] = rotated_from
                if evicted_cards:
                    reserving_entry["evicted_lru"] = list(evicted_cards)
                _write_card_record_locked(project, topic_key, tool, reserving_entry, title=window_title(topic_key, title))

        # ── Phase 2: Remote Launch Outside `pool_<tool>` Lock ──
        name = window_title(topic_key, title)
        window_id = ""
        tokens: int | None = None
        launch_error: BaseException | None = None
        try:
            if dry_run:
                window_id = session_id or f"dryrun-{tool}-{topic_key.lower()}"
            elif tool == "codex":
                window_id = _open_codex(project, name, prompt, rpc)
            elif tool == "claude":
                window_id = str(session_id)
            else:
                window_id, tokens = _open_antigravity(project, prompt, runner)
            if not window_id:
                raise RuntimeError("empty_window_id")
        except BaseException as exc:  # noqa: BLE001
            launch_error = exc

        # ── Phase 3: Finalize Under `card_<topic_key>` Lock (or `pool_<tool>` on launch failure rollback) ──
        if launch_error is not None:
            with _window_lock(project, f"pool_{tool}"):
                with _window_lock(project, f"card_{topic_key}"):
                    current = _load(_record_path(project, topic_key)).get("tools", {}).get(tool) or {}
                    if current.get("reservation_id") == reservation_id:
                        if rotated_snapshot is not None:
                            _write_card_record_locked(project, topic_key, tool, rotated_snapshot, title=name)
                        else:
                            failed_entry = {
                                **current,
                                "state": "RELEASED",
                                "released_at": ts,
                                "release_reason": "launch_failed",
                                "released_reason": "launch_failed",
                                "updated_at": time.time() if now is None else now,
                            }
                            _write_card_record_locked(project, topic_key, tool, failed_entry, title=name)
                for evict_card, victim_snap in evicted_snapshots:
                    with _window_lock(project, f"card_{evict_card}"):
                        cur_victim = _load(_record_path(project, evict_card)).get("tools", {}).get(tool) or {}
                        if (
                            cur_victim.get("state") == "RELEASED"
                            and cur_victim.get("evicted_by_reservation") == reservation_id
                        ):
                            _write_card_record_locked(project, evict_card, tool, victim_snap)
            raise launch_error

        with _window_lock(project, f"card_{topic_key}"):
            subcards = [topic_key] if card == topic_key else [topic_key, card]
            active_entry: dict[str, Any] = {
                "id": window_id,
                "state": "ACTIVE",
                "reservation_id": reservation_id,
                "opened_at": ts,
                "last_active_at": ts,
                "updated_at": ts,
                "topic_key": topic_key,
                "subcards": subcards,
                "in_flight_leases": {},
                "in_flight_count": 0,
                "in_flight": False,
            }
            if tokens is not None:
                active_entry["last_input_tokens"] = tokens
            if rotated_from:
                active_entry["rotated_from"] = rotated_from
            if evicted_cards:
                active_entry["evicted_lru"] = list(evicted_cards)
            saved = _write_card_record_locked(project, topic_key, tool, active_entry, title=name)
            return {**saved, "reused": False, "topic_key": topic_key, "card": card}


def _claude_session_id(session_id: str) -> str:
    """U129/U293: the caller's desktop session id (bare UUID or `local_<uuid>`), lower-cased to bare UUID."""
    from .card_sessions import normalize_claude_session_id

    bare_uuid, _native_id = normalize_claude_session_id(session_id)
    return bare_uuid


def session_busy(project: Path, session_id: str, card: str) -> str | None:
    """U129: the other card whose unreleased Claude window is this desktop session, else None."""
    session_id = _claude_session_id(session_id)
    topic = normalize_topic_key(card)
    for path in sorted((Path(project) / ".coord" / "windows").glob("*.json")):
        if path.stem in (card, topic):
            continue
        entry = _load(path).get("tools", {}).get("claude") or {}
        if entry.get("id") == session_id and _is_entry_active(entry):
            return path.stem
    return None


def release_window(project: Path, card: str, tool: str, *, now: float | None = None,
                   reason: str | None = None, require_idle: bool = False) -> dict[str, Any]:
    """U129 / U279: mark a card's window done under `card_<card>` lock. When `require_idle=True`, atomically
    prunes dead-PID leases and verifies `in_flight_leases == {}` inside the same `card_<card>` lock before releasing."""
    with _window_lock(project, f"card_{card}"):
        entry = window_entry(project, card, tool)
        if not entry:
            return {"released": False, "card": card, "tool": tool}
        if entry.get("released_at") or entry.get("state") == "RELEASED":
            return {"released": not require_idle, "card": card, "tool": tool}
        if require_idle and _entry_is_in_flight(entry):
            return {"released": False, "busy": True, "card": card, "tool": tool}
        ts = time.time() if now is None else now
        extra = {k: v for k, v in entry.items() if k not in ("id", "opened_at", "state", "updated_at")}
        if reason:
            extra["release_reason"] = reason
            extra["released_reason"] = reason
        record_window(project, card, tool, str(entry.get("id") or ""), now=ts, state="RELEASED", released_at=ts, **extra)
        return {"released": True, "card": card, "tool": tool}


def route_window(project: Path, card: str, *, session_id: str | None = None) -> dict[str, Any]:
    """U129: the clickless route for a card: Codex (ACTIVE) -> idle visible Claude session -> Antigravity headless."""
    _record_path(project, card)
    topic_key = normalize_topic_key(card)
    if read_presence(project, "codex")["state"] == "ACTIVE":
        return {"route": "codex", "card": card, "topic_key": topic_key,
                "step": "conductor: open the card's Codex app-server thread (`uaos coord window --tool codex`)"}
    busy = None
    if session_id is not None:
        session_id = _claude_session_id(session_id)
        busy = session_busy(project, session_id, card)
        if busy is None:
            return {"route": "claude", "card": card, "topic_key": topic_key, "session_id": session_id,
                    "step": f"conductor: send the card manual to Claude desktop session {session_id} with send_message, "
                            f"then record it (`uaos coord window --tool claude --session-id {session_id}`)"}
    route = {"route": "antigravity", "card": card, "topic_key": topic_key,
             "step": "conductor: send the card to Antigravity headless (`agy -p`) and relay its result"}
    if busy:
        route["busy"] = busy
    return route


def open_lane_window(project: Path, lane: str, tool: str, title: str = "", prompt: str = "", **extra: Any) -> dict[str, Any]:
    """U287: Open or reuse a dedicated process-classification lane conversation window across any of the 3 tools."""
    from .process_lanes import open_or_reuse_lane_window, select_active_tool_for_lane

    resolved_tool = tool
    if tool == "auto":
        resolved_tool, _reason = select_active_tool_for_lane(project, lane)
    return open_or_reuse_lane_window(
        project,
        lane,
        resolved_tool,
        title=title,
        prompt=prompt,
        card=str(extra.get("card") or ""),
        session_id=extra.get("session_id"),
        rotate=bool(extra.get("rotate", False)),
    )
