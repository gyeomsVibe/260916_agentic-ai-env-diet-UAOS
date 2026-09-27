"""Who is at the desk: one heartbeat file per tool, written by that tool's own session hooks.

The user used to declare "Codex is absent" by hand in PLAN.md, and that line stayed true until someone edited it.
A heartbeat carries its own expiry, so a tool that stops reporting (quota, crash, closed window) turns UNKNOWN
by itself. Reading and writing a small JSON file costs no model tokens.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PRESENCE_DIR = Path(".coord") / "presence"
TOOLS = ("codex", "claude", "antigravity")
STATES = ("ACTIVE", "LIMITED", "ABSENT")
DEFAULT_TTL_S = 3600


class PresenceRejected(ValueError):
    pass


def _path(project: Path, tool: str) -> Path:
    if tool not in TOOLS:
        raise PresenceRejected(f"unknown tool: {tool}")
    return Path(project) / PRESENCE_DIR / f"{tool}.json"


def mark(project: Path, tool: str, state: str, *, ttl_s: int = DEFAULT_TTL_S, now: float | None = None,
         lease: bool = False) -> Path:
    """Write one heartbeat. `lease=True` records a capability fact (e.g. a provider's quota answer) that a session
    heartbeat of another state cannot overwrite before it expires.

    U47-A1b: Codex's re-review (2026-09-27) found that the next ACTIVE session hook replaced the LIMITED state
    `pilot judge` had recorded from agy's 429 answer, so routing again sent verdict requests to a tool that could not
    answer. A live lease is kept and the heartbeat is dropped; another lease replaces it.
    """
    if state not in STATES:
        raise PresenceRejected(f"unknown state: {state}")
    if ttl_s <= 0:
        raise PresenceRejected("ttl_s must be positive")
    moment = time.time() if now is None else now
    target = _path(project, tool)
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "tool": tool,
        "state": state,
        "observed_at": (datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=moment)).isoformat(timespec="seconds"),
        "expires_at": moment + ttl_s,
    }
    if lease:
        record["lease"] = True
    # U47-RW1c: Codex's race (2026-09-27) let a heartbeat pass the lease check, a lease land, and the heartbeat then
    # replace it. The check and the replace now happen under one lock shared by threads and processes.
    with _tool_lock(target):
        if not lease and _live_lease(target, moment, state):
            return target
        tmp = target.with_name(f".{tool}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(tmp, target)
    return target


# A heartbeat write takes milliseconds; 10 s of waiting means a stuck writer, and a lock file older than 60 s is taken
# as left by a dead process (the same bounds as coord/stream.py, measured there under an 8-process race).
LOCK_TIMEOUT_S = 10.0
LOCK_STALE_S = 60.0
_THREAD_LOCK = threading.Lock()


@contextmanager
def _tool_lock(target: Path):
    """Exclusive O_EXCL lock file beside the heartbeat; raises PresenceRejected on timeout (the write is dropped)."""
    lock_path = target.with_name(f".{target.stem}.lock")
    deadline = time.monotonic() + LOCK_TIMEOUT_S
    with _THREAD_LOCK:
        handle = None
        while handle is None:
            try:
                handle = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except (FileExistsError, PermissionError):
                # Windows answers PermissionError for a lock file pending deletion: another writer holds it.
                try:
                    age = time.time() - lock_path.stat().st_mtime
                except (FileNotFoundError, PermissionError):
                    time.sleep(0.01)
                    continue
                if age > LOCK_STALE_S:
                    lock_path.unlink(missing_ok=True)
                    continue
                if time.monotonic() > deadline:
                    raise PresenceRejected("PRESENCE_LOCK_TIMEOUT") from None
                time.sleep(0.01)
        try:
            yield
        finally:
            os.close(handle)
            lock_path.unlink(missing_ok=True)


def _live_lease(target: Path, moment: float, state: str) -> bool:
    """True while the file holds an unexpired lease of a different state; an unreadable file holds nothing."""
    try:
        record = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    # U47-RW1d: a capability lease protects its original expiry from every ordinary heartbeat. A same-state
    # heartbeat is not new quota evidence and must not shorten a 162-hour provider lease to the session TTL.
    if not isinstance(record, dict) or record.get("lease") is not True:
        return False
    expires_at = record.get("expires_at")
    return isinstance(expires_at, (int, float)) and not isinstance(expires_at, bool) and expires_at > moment


def read(project: Path, tool: str, *, now: float | None = None) -> dict[str, Any]:
    moment = time.time() if now is None else now
    unknown = {"tool": tool, "state": "UNKNOWN", "observed_at": None, "expires_at": None}
    try:
        record = json.loads(_path(project, tool).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return unknown
    if not isinstance(record, dict):
        return unknown
    expires_at = record.get("expires_at")
    if record.get("state") not in STATES or isinstance(expires_at, bool) or not isinstance(expires_at, (int, float)):
        return unknown
    if expires_at <= moment:
        return {**unknown, "observed_at": record.get("observed_at"), "expires_at": expires_at}
    if tool == "codex" and record["state"] == "ACTIVE":
        blocked = codex_quota_block(_epoch(record.get("observed_at")), moment)
        if blocked is not None:
            return {"tool": tool, "state": "LIMITED", "observed_at": record.get("observed_at"),
                    "expires_at": blocked["until"], "evidence": blocked}
    return {"tool": tool, "state": record["state"], "observed_at": record.get("observed_at"), "expires_at": expires_at}


# U57-A (2026-09-27): Codex's UserPromptSubmit hook writes ACTIVE before the turn runs, so a relay prompt that Codex
# then refused with `usage_limit_exceeded` left the desk saying ACTIVE. `coord route` sent work to Codex and the
# acting conductor had to write a LIMITED lease by hand. Codex records the refusal in its own rollout log; reading
# the newest one turns that ACTIVE into LIMITED until the reset time Codex printed. Reading is local and costs no
# tokens; a missing or unreadable log changes nothing.
CODEX_SESSIONS_ENV = "UAOS_CODEX_SESSIONS"
# The last task_complete line of a rollout sits in its final lines; 64 KiB held 20+ events in the 2026-09-27 logs.
ROLLOUT_TAIL_BYTES = 64 * 1024
# Newest three rollouts of the newest two day folders: sessions run in parallel and one may cross midnight.
ROLLOUT_DAYS = 2
ROLLOUT_FILES = 3
# The hook stamps observed_at in whole seconds just before the turn starts; 5 s covers the truncation and the gap.
HEARTBEAT_SLACK_S = 5
# When the reset time cannot be parsed, assume one hour; the next refused prompt writes a fresh refusal anyway.
UNPARSED_RESET_S = 3600


def _epoch(stamp: Any) -> float | None:
    if not isinstance(stamp, str):
        return None
    try:
        parsed = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _codex_rollouts() -> list[Path]:
    root = Path(os.environ.get(CODEX_SESSIONS_ENV) or (Path.home() / ".codex" / "sessions"))
    try:
        days = sorted((d for d in root.glob("*/*/*") if d.is_dir()), key=lambda d: d.parts[-3:], reverse=True)
        files = [f for d in days[:ROLLOUT_DAYS] for f in d.glob("rollout-*.jsonl") if f.is_file()]
        return sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)[:ROLLOUT_FILES]
    except OSError:
        return []


def _last_task_complete(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - ROLLOUT_TAIL_BYTES))
            lines = handle.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if '"task_complete"' not in line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue  # the first line of the tail may be cut
        payload = event.get("payload") if isinstance(event, dict) else None
        if isinstance(payload, dict) and payload.get("type") == "task_complete":
            return payload
    return None


def _reset_at(message: str, completed_at: float) -> float:
    match = re.search(r"try again at (\d{1,2}):(\d{2})\s*([AP]M)", message or "", re.IGNORECASE)
    if not match:
        return completed_at + UNPARSED_RESET_S
    hour, minute, half = int(match.group(1)) % 12, int(match.group(2)), match.group(3).upper()
    hour += 12 if half == "PM" else 0
    # Codex prints the reset in the machine's local time; roll to the next day when that clock time has passed.
    local = datetime.fromtimestamp(completed_at).astimezone()
    reset = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if reset.timestamp() <= completed_at:
        reset += timedelta(days=1)
    return reset.timestamp()


def codex_quota_block(observed_epoch: float | None, moment: float) -> dict[str, Any] | None:
    """Return the refusal that outranks an ACTIVE heartbeat, or None.

    It counts only when Codex refused a turn at or after the heartbeat (the heartbeat was for that failed prompt), the
    refusal is not in the future of `moment`, and the reset time has not passed. A heartbeat written after the refusal
    is a newer prompt and wins; if that prompt is refused too, its own refusal is newer again.
    """
    if observed_epoch is None:
        return None
    newest: dict[str, Any] | None = None
    for path in _codex_rollouts():
        payload = _last_task_complete(path)
        completed = payload.get("completed_at") if payload else None
        if isinstance(completed, (int, float)) and not isinstance(completed, bool) and (
                newest is None or completed > newest["completed_at"]):
            newest = {"completed_at": completed, "payload": payload, "rollout": str(path)}
    if newest is None:
        return None
    error = newest["payload"].get("error")
    if not isinstance(error, dict) or error.get("codex_error_info") != "usage_limit_exceeded":
        return None
    completed_at = float(newest["completed_at"])
    if completed_at + HEARTBEAT_SLACK_S < observed_epoch or completed_at > moment:
        return None
    until = _reset_at(str(error.get("message", "")), completed_at)
    if until <= moment:
        return None
    return {"source": "codex_rollout", "reason": "usage_limit_exceeded", "completed_at": completed_at,
            "until": until, "rollout": newest["rollout"]}


def read_all(project: Path, *, now: float | None = None) -> dict[str, dict[str, Any]]:
    return {tool: read(project, tool, now=now) for tool in TOOLS}


# U45 G1/G3: the succession order of docs/27 §4. Codex conducts; Claude acts while Codex is LIMITED or ABSENT;
# Antigravity acts only while both are. Only desk states count: a quota figure beside a state is ignored on purpose.
SUCCESSION = ("codex", "claude", "antigravity")
AWAY = ("LIMITED", "ABSENT")


def conductor(desk: dict[str, dict[str, Any]]) -> dict[str, Any]:
    for position, tool in enumerate(SUCCESSION):
        state = (desk.get(tool) or {}).get("state", "UNKNOWN")
        if state == "ACTIVE":
            acting = position > 0
            reason = f"{tool} ACTIVE" + (f"; {', '.join(SUCCESSION[:position])} away" if acting else "")
            return {"conductor": tool, "acting": acting, "reason": reason}
        if state not in AWAY:
            # An expired heartbeat is not absence: stop here instead of handing authority to the next tool.
            return {"conductor": "UNKNOWN", "acting": False, "reason": f"{tool} {state}: heartbeat not current"}
    return {"conductor": "none", "acting": False, "reason": "all three tools LIMITED or ABSENT"}
