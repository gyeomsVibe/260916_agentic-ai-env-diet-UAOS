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


# U134: a SessionStart or UserPromptSubmit hook runs only when a turn really starts, so it proves the tool has
# capacity now; PostToolUse runs mid-turn and Stop/SessionEnd prove nothing new.
TURN_START_EVENTS = ("SessionStart", "UserPromptSubmit")
# U134: one append-only log of desk events beside the heartbeats (LEASE_CLEARED_BY_TURN), read by people and tests.
EVENTS_FILE = "events.jsonl"
# U134: a hook must return in milliseconds, so queued letters are sent by a detached process that outlives it.
QUEUE_SPAWN_CODE = ("import sys; from v7_harness.coord.deliver import dispatch_queued; "
                    "dispatch_queued(sys.argv[1], sys.argv[2])")


class PresenceRejected(ValueError):
    pass


def _path(project: Path, tool: str) -> Path:
    if tool not in TOOLS:
        raise PresenceRejected(f"unknown tool: {tool}")
    return Path(project) / PRESENCE_DIR / f"{tool}.json"


def mark(project: Path, tool: str, state: str, *, ttl_s: int = DEFAULT_TTL_S, now: float | None = None,
         lease: bool = False, session: str | None = None, turn_start: bool = False, dispatch: bool = False,
         runner: Any = None) -> Path:
    """Write one heartbeat. `lease=True` records a capability fact (e.g. a provider's quota answer) that a session
    heartbeat of another state cannot overwrite before it expires.

    U47-A1b: Codex's re-review (2026-09-27) found that the next ACTIVE session hook replaced the LIMITED state
    `pilot judge` had recorded from agy's 429 answer, so routing again sent verdict requests to a tool that could not
    answer. A live lease is kept and the heartbeat is dropped; another lease replaces it.

    U134 (2026-10-03): a manual LIMITED lease from 2026-09-30 dropped every Codex turn for 3 days. An ACTIVE heartbeat
    from a real turn start (`turn_start=True`) proves capacity, so it replaces a LIMITED/ABSENT lease and logs
    LEASE_CLEARED_BY_TURN. `dispatch=True` (the hook path) then sends the letters queued while the tool was away.
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
    held = ""
    cleared = ""
    # U47-RW1c: Codex's race (2026-09-27) let a heartbeat pass the lease check, a lease land, and the heartbeat then
    # replace it. The check and the replace now happen under one lock shared by threads and processes.
    with _tool_lock(target):
        if not lease and _live_lease(target, moment, state):
            held = _lease_state(target)
        if held and turn_start and state == "ACTIVE" and held in ("LIMITED", "ABSENT"):
            cleared = held
        if not held or cleared:
            if session and not lease:
                record = _merge_session(target, record, session, state, moment, ttl_s)
            tmp = target.with_name(f".{tool}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
            tmp.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            replace_with_retry(tmp, target)
    if cleared:
        _log_event(target.parent, {"kind": "LEASE_CLEARED_BY_TURN", "tool": tool, "cleared_state": cleared,
                                   "at": record["observed_at"], "session": session or ""})
    # An ACTIVE lease also means the desk reads ACTIVE, so its queued letters may go too.
    if dispatch and state == "ACTIVE" and (not held or cleared or held == "ACTIVE"):
        _dispatch_queued(project, tool, runner)
    return target


# U60 (2026-09-28): on Windows os.replace answers PermissionError (WinError 5) while another process has the target
# open for a read; a `coord watch` beat died on it. A read holds the file for milliseconds, so 20 tries 10 ms apart
# (200 ms) outlast it; the lock above already keeps writers apart.
REPLACE_TRIES = 20
REPLACE_WAIT_S = 0.01


def replace_with_retry(tmp: Path, target: Path) -> None:
    """os.replace that waits out a reader holding the target; the last PermissionError is raised, tmp removed."""
    for attempt in range(REPLACE_TRIES):
        try:
            os.replace(tmp, target)
            return
        except PermissionError:
            if attempt == REPLACE_TRIES - 1:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(REPLACE_WAIT_S)


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


def _merge_session(target: Path, record: dict[str, Any], session: str, state: str, moment: float,
                   ttl_s: int) -> dict[str, Any]:
    """U58: one tool can have several sessions open; the desk reads ACTIVE while any of them is live.

    Seen 2026-09-28: `coord deliver` started a cold `claude -p`, its SessionEnd hook wrote claude ABSENT for 24 h,
    and `coord route` returned BLOCKED_NO_ACTIVE_AUTHORITY while the acting conductor's session was still open.
    Each ACTIVE heartbeat now registers its session id; ABSENT removes only that id, and the tool reads ABSENT only
    when no registered session is still within its TTL. Called under the tool lock.
    """
    sessions: dict[str, float] = {}
    try:
        previous = json.loads(target.read_text(encoding="utf-8"))
        if isinstance(previous, dict) and isinstance(previous.get("sessions"), dict):
            sessions = {str(k): float(v) for k, v in previous["sessions"].items()
                        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > moment}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        pass
    if state == "ACTIVE":
        sessions[session] = moment + ttl_s
    else:
        sessions.pop(session, None)
    if state != "ACTIVE" and sessions:
        # Another session is still at the desk: keep ACTIVE until the last live session's heartbeat expires.
        return {**record, "state": "ACTIVE", "expires_at": max(sessions.values()), "sessions": sessions}
    if state == "ACTIVE":
        return {**record, "expires_at": max(sessions.values()), "sessions": sessions}
    return {**record, "sessions": {}}


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


# U113: the desk said antigravity=UNKNOWN while Antigravity was open and had answered three hours before. Routing still
# treats IDLE like UNKNOWN (fail closed); only the word on the desk changes.
def desk_label(info: dict[str, Any], now: float | None = None) -> str:
    """The desk word for one tool: an expired heartbeat reads IDLE(<age>), a tool never seen UNKNOWN."""
    state = str(info.get("state") or "UNKNOWN")
    seen = _epoch(info.get("observed_at")) if state == "UNKNOWN" else None
    if seen is None:
        return state
    age = (time.time() if now is None else now) - seen
    return f"IDLE({int(age // 60)}m)" if age < 3600 else f"IDLE({int(age // 3600)}h)"


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
    # U100-P: a weekly limit prints the date too; read it before the clock-only form (2026-09-28 rollout).
    dated = re.search(r"try again at ([A-Z][a-z]{2}) (\d{1,2})(?:st|nd|rd|th), (\d{4}) (\d{1,2}):(\d{2})\s*([AP]M)",
                      message or "", re.IGNORECASE)
    if dated:
        try:
            day = datetime.strptime(f"{dated.group(1).title()} {dated.group(2)} {dated.group(3)}", "%b %d %Y")
        except ValueError:
            return completed_at + UNPARSED_RESET_S
        hour = int(dated.group(4)) % 12 + (12 if dated.group(6).upper() == "PM" else 0)
        return day.replace(hour=hour, minute=int(dated.group(5))).timestamp()
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


def hook_turn_start(stdin_text: str) -> bool:
    """U134: True when the hook payload names a real turn start (SessionStart or UserPromptSubmit)."""
    try:
        payload = json.loads(stdin_text or "")
    except (TypeError, ValueError):
        return False
    return isinstance(payload, dict) and payload.get("hook_event_name") in TURN_START_EVENTS


def _lease_state(target: Path) -> str:
    """U134: the state a live lease holds; read under the tool lock right after `_live_lease` answered True."""
    try:
        record = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ""
    return str(record.get("state") or "") if isinstance(record, dict) else ""


def _log_event(presence_dir: Path, event: dict[str, Any]) -> None:
    """U134: append one desk event line. Two tools can clear their leases at once and Windows loses concurrent
    appends, so the events file has its own lock (taken after the heartbeat lock is released: it is not reentrant)."""
    path = presence_dir / EVENTS_FILE
    with _tool_lock(path):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def _dispatch_queued(project: Path, tool: str, runner: Any) -> None:
    """U134-B: send the letters queued while `tool` was LIMITED/ABSENT. A test passes a stub runner and dispatches
    in-process; a hook starts a detached process so the session never waits for `codex queue` or a paid turn."""
    import subprocess
    import sys

    from v7_harness.coord.deliver import dispatch_queued, queued_letters

    if not queued_letters(project, tool):
        return
    if runner is not None:
        dispatch_queued(project, tool, runner=runner)
        return
    flags: dict[str, Any] = ({"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
                             if os.name == "nt" else {"start_new_session": True})
    subprocess.Popen([sys.executable, "-c", QUEUE_SPAWN_CODE, str(project), tool],
                     cwd=str(Path(__file__).resolve().parents[2]), stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **flags)
