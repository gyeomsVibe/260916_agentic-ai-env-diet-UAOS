```contract
work_id: U60
worker: apply
goal: A Windows os.replace refusal (WinError 5 while another process reads the target) neither kills `coord watch` nor leaves a presence heartbeat half-written.
inputs:
- v7_harness/coord/presence.py sha256=1041a52becebcc4323e0765cac85634f3c0c36e890c7351c86f6cd4d709d2ab2
- v7_harness/coord/watch.py sha256=02f2508f389407ed5b44ffbf8b7a4e7dc7e4be072b3fc94ce3f70240c1530aff
allow:
- v7_harness/coord/presence.py
- v7_harness/coord/watch.py
- tests/test_u60_replace_retry.py
acceptance: C:/Python314/python.exe -m unittest tests.test_u60_replace_retry tests.test_u59_shared_desk tests.test_u58_session_presence tests.test_u57_desk_signals
forbidden: design changes; edits outside allow; weakening or deleting existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Card: U60. Seen 2026-09-28: the acting conductor's background `coord watch --target claude` on the main checkout exited with PermissionError [WinError 5] from os.replace(.claude.watch.json.*.tmp -> claude.watch.json). Fix: presence.replace_with_retry() tries 20 times 10 ms apart (a read holds the file for milliseconds), removes the temp file and raises on the last refusal; mark() uses it; watch _beat uses it and skips a refused beat (the file stays live for three scans and the inbox scan runs anyway). Stacked on U59. Issued under the user's order of 2026-09-28 ('프로젝트 완성될때까지 논스톱 무승인 진행하라'), judge claude (ACTING); Codex re-reviews. Red on HEAD 3 errors, 39 OK in overlay.

===FILE: v7_harness/coord/presence.py===
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
         lease: bool = False, session: str | None = None) -> Path:
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
        if session and not lease:
            record = _merge_session(target, record, session, state, moment, ttl_s)
        tmp = target.with_name(f".{tool}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        replace_with_retry(tmp, target)
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
===FILE: v7_harness/coord/watch.py===
"""U57: `coord watch` — block until a new mailbox letter for a tool arrives, at zero model tokens.

Why (2026-09-27/28): an interactive session wakes only on a user prompt. Letters between Claude sessions were held
by the app for the user's approval (sessions with different permission modes), one expired unseen, and the acting
conductor had to hand-write a shell loop over the inbox to be woken. The user then had to approve or copy messages.
This makes that loop a tested harness command: a session runs it in the background, and it exits when a letter for
its tool lands, so the session wakes without the user.

While a watch runs it keeps `.coord/presence/<tool>.watch.json` fresh. `coord deliver` reads that file: a live
watcher means an interactive session is listening, so the letter is left in the inbox for it (QUEUED_INTERACTIVE)
instead of starting a cold headless session that cannot see the conversation.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from v7_harness.coord.mailbox import Mailbox
from v7_harness.coord.presence import PRESENCE_DIR, TOOLS, replace_with_retry

# 30 s between inbox scans: the hand-written loop used 30 s on 2026-09-27 and a letter waited at most that long;
# one scan lists one directory, so a shorter interval costs only disk reads, never tokens.
DEFAULT_INTERVAL_S = 30.0
# 4 h per watch: the longest single wait seen on 2026-09-27 (Codex quota window). The session re-arms it after.
DEFAULT_TIMEOUT_S = 4 * 3600.0
# A watcher counts as live for three missed scans, and never less than 90 s, so one slow scan does not make
# `coord deliver` fall back to a cold session while the watcher is still running.
LIVE_SCANS = 3
LIVE_MIN_S = 90.0


def watch_file(project: Path, tool: str) -> Path:
    if tool not in TOOLS:
        raise ValueError(f"unknown tool: {tool}")
    return Path(project) / PRESENCE_DIR / f"{tool}.watch.json"


def _beat(project: Path, tools: tuple[str, ...], token: str, interval_s: float, moment: float) -> None:
    live_for = max(LIVE_SCANS * interval_s, LIVE_MIN_S)
    for tool in tools:
        target = watch_file(project, tool)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps({"tool": tool, "token": token, "pid": os.getpid(),
                                   "expires_at": moment + live_for}), encoding="utf-8")
        try:
            replace_with_retry(tmp, target)
        except PermissionError:
            # U60: a missed beat is not a missed letter. The file stays live for three scans, the next beat
            # rewrites it, and the inbox scan below runs either way.
            pass


def _clear(project: Path, tools: tuple[str, ...], token: str) -> None:
    """Remove only this watch's files; a newer watch for the same tool keeps its own."""
    for tool in tools:
        target = watch_file(project, tool)
        try:
            if json.loads(target.read_text(encoding="utf-8")).get("token") == token:
                target.unlink(missing_ok=True)
        except (OSError, ValueError, AttributeError):
            pass


def watcher_live(project: Path, tool: str, *, now: float | None = None) -> bool:
    moment = time.time() if now is None else now
    try:
        record = json.loads(watch_file(project, tool).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    expires_at = record.get("expires_at") if isinstance(record, dict) else None
    return isinstance(expires_at, (int, float)) and not isinstance(expires_at, bool) and expires_at > moment


def _addressed(payload: Any, tools: tuple[str, ...]) -> bool:
    if not isinstance(payload, dict):
        return False
    return payload.get("requested_target") in tools or payload.get("to") in tools


def watch(project: Path, tools: tuple[str, ...], *, timeout_s: float = DEFAULT_TIMEOUT_S,
          interval_s: float = DEFAULT_INTERVAL_S, clock: Callable[[], float] | None = None,
          sleep: Callable[[float], None] | None = None) -> dict[str, Any] | None:
    """Return the first letter addressed to one of `tools` that was not in the inbox when the watch began.

    Letters already waiting are what `coord inbox` shows at session start; the watch reports only new ones, so a
    re-armed watch never wakes the session twice for the same letter. None means the timeout passed.
    """
    clock = clock or time.time
    sleep = sleep or time.sleep  # looked up per call so tests and callers can patch time.sleep
    for tool in tools:
        watch_file(project, tool)  # validates the name before anything is written
    # U59: a project whose first letter has not arrived yet has no mailbox folder; waiting on it is still valid.
    mailbox_dir = Path(project) / ".coord" / "mailbox"
    mailbox_dir.mkdir(parents=True, exist_ok=True)
    box = Mailbox(mailbox_dir)
    seen = set(box.list_inbox())
    token = uuid.uuid4().hex
    deadline = clock() + timeout_s
    try:
        while True:
            _beat(project, tools, token, interval_s, clock())
            for message_id, payload in box.peek():
                if message_id in seen:
                    continue
                seen.add(message_id)
                if _addressed(payload, tools):
                    body = payload if isinstance(payload, dict) else {}
                    return {"id": message_id, "kind": body.get("kind"), "actor": body.get("actor"),
                            "requested_target": body.get("requested_target") or body.get("to")}
            if clock() >= deadline:
                return None
            sleep(interval_s)
    finally:
        _clear(project, tools, token)
===FILE: tests/test_u60_replace_retry.py===
"""U60 frozen acceptance (written by Claude): a Windows replace refusal does not kill a watch or lose a heartbeat.

Seen 2026-09-28: `coord watch` exited with PermissionError [WinError 5] from os.replace on claude.watch.json while
another process had the file open.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import presence
from v7_harness.coord.mailbox import Mailbox
from v7_harness.coord.presence import mark, read
from v7_harness.coord.watch import watch, watch_file

REAL_REPLACE = os.replace


def refuse(times):
    calls = {"n": 0}

    def fake(src, dst):
        # os.replace is patched module-wide; only desk files are refused so the mailbox still publishes.
        if Path(dst).parent.name != "presence":
            return REAL_REPLACE(src, dst)
        calls["n"] += 1
        if times is None or calls["n"] <= times:
            raise PermissionError(5, "Access is denied")
        return REAL_REPLACE(src, dst)

    return fake, calls


class ReplaceRetryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        (self.project / ".coord").mkdir()
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def leftovers(self):
        return sorted(p.name for p in (self.project / ".coord" / "presence").glob("*.tmp"))

    def test_heartbeat_waits_out_a_short_refusal(self):
        fake, calls = refuse(3)
        with mock.patch.object(presence.os, "replace", fake), mock.patch.object(presence, "REPLACE_WAIT_S", 0):
            mark(self.project, "claude", "ACTIVE", ttl_s=3600)
        self.assertEqual(4, calls["n"])
        self.assertEqual("ACTIVE", read(self.project, "claude")["state"])
        self.assertEqual([], self.leftovers())

    def test_heartbeat_that_never_lands_raises_and_leaves_no_temp_file(self):
        fake, _ = refuse(None)
        with mock.patch.object(presence.os, "replace", fake), mock.patch.object(presence, "REPLACE_WAIT_S", 0):
            with self.assertRaises(PermissionError):
                mark(self.project, "claude", "ACTIVE", ttl_s=3600)
        self.assertEqual([], self.leftovers())

    def test_watch_survives_a_refused_beat_and_still_finds_the_letter(self):
        (self.project / ".coord" / "mailbox").mkdir(parents=True)

        def sleep(_s):
            Mailbox(self.project / ".coord" / "mailbox").publish(
                "m1", {"kind": "NOTE", "actor": "codex", "requested_target": "claude", "message": "x"})

        fake, _ = refuse(None)
        with mock.patch.object(presence.os, "replace", fake), mock.patch.object(presence, "REPLACE_WAIT_S", 0):
            found = watch(self.project, ("claude",), timeout_s=60, interval_s=1, sleep=sleep)
        self.assertIsNotNone(found)
        self.assertEqual("m1", found["id"])
        self.assertFalse(watch_file(self.project, "claude").exists())
        self.assertEqual([], self.leftovers())


if __name__ == "__main__":
    unittest.main()
===END===

## Output

- Reply with ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.
