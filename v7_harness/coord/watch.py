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

import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from v7_harness.coord.mailbox import Mailbox
from v7_harness.coord.presence import PRESENCE_DIR, TOOLS, replace_with_retry

# 2 s between inbox scans (U94, 2026-09-30): a letter waits at most one interval before the watch wakes; the
# hand-written loop of 2026-09-27 used 30 s. A scan lists the inbox and reads only letters it has not seen (U94-R1):
# re-reading all 464 desk letters took 132 ms a scan, so 2 s kept a watcher busy 6.6% of the time (15x the 30 s
# cost); the listing alone took 8.1 ms (0.4%). Never tokens either way.
DEFAULT_INTERVAL_S = 2.0
# 4 h per watch: the longest single wait seen on 2026-09-27 (Codex quota window). The session re-arms it after.
DEFAULT_TIMEOUT_S = 4 * 3600.0
# A watcher counts as live for three missed scans, and never less than 90 s, so one slow scan does not make
# `coord deliver` fall back to a cold session while the watcher is still running.
LIVE_SCANS = 3
LIVE_MIN_S = 90.0
# Longer than the 120 s Claude dispatch timeout plus receipt writes. A crashed dispatcher must not suppress the
# interactive fallback forever; after this bound the marker is evidence of failure, not an active dispatch.
PENDING_MAX_AGE_S = 300.0
# U179: 60 s between long-wait scans. A scan takes the stall lock, reads the schedule and the queued letters and
# writes three small state files, so it does not run on every 2 s inbox scan; 60 s bounds lateness to 3% of
# stall.MAX_WAIT_S (1800 s). Never tokens.
STALL_SCAN_S = 60.0
# U141-A: an empty O_EXCL placeholder younger than this is a claim being written (the full record follows within
# milliseconds), so it counts as EXISTS. An older empty one is a crashed claim: CORRUPT, kept, never a wake.
PLACEHOLDER_GRACE_S = 5.0

# U141-A wake policy (rev 4 f57b2186, Codex APPROVE relay_bcb089d1; rev 5 delta). Only these structured envelope
# fields decide a paid wake; the message text is never read, so a quoted marker cannot wake anyone.
WAKE_CLASSES = ("ACTIONABLE", "NOTICE")
VERDICTS = ("PASS", "REVISE", "FAIL", "APPROVE", "PIVOT", "REWORK")
STRUCTURED_FIELDS = ("wake_class", "verdict_requested", "verdict", "delta")
RECEIPT_KEYS = ("target", "message_id", "digest", "pid", "process_created", "created_at")


def watch_file(project: Path, tool: str) -> Path:
    if tool not in TOOLS:
        raise ValueError(f"unknown tool: {tool}")
    return Path(project) / PRESENCE_DIR / f"{tool}.watch.json"


def _beat(project: Path, tools: tuple[str, ...], token: str, interval_s: float, moment: float,
          wakes_session: bool = False) -> None:
    live_for = max(LIVE_SCANS * interval_s, LIVE_MIN_S)
    for tool in tools:
        target = watch_file(project, tool)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps({"tool": tool, "token": token, "pid": os.getpid(),
                                   "expires_at": moment + live_for, "wakes_session": wakes_session}),
                       encoding="utf-8")
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


def watcher_wakes(project: Path, tool: str) -> bool:
    """U117: a live watcher whose exit wakes its own session (a Claude Code background task) takes real deltas too."""
    try:
        record = json.loads(watch_file(project, tool).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return watcher_live(project, tool) and isinstance(record, dict) and record.get("wakes_session") is True


def _addressed(payload: Any, tools: tuple[str, ...]) -> bool:
    if not isinstance(payload, dict):
        return False
    return payload.get("requested_target") in tools or payload.get("to") in tools


def classify(payload: Any, migration: dict[str, Any] | None = None) -> tuple[str, str]:
    """U141-A: (ACTIONABLE | NOTICE | INVALID | LEGACY, diagnostic) from the structured fields only.

    Every field is validated before any row matches, so an early matching row cannot hide a contradictory field.
    """
    body = dict(payload) if isinstance(payload, dict) else {}
    if isinstance(migration, dict):
        # A digest-bound migration record overrides the four structured fields; the stored envelope is never rewritten.
        for key in STRUCTURED_FIELDS:
            if key in migration:
                body[key] = migration[key]
    present = [key for key in STRUCTURED_FIELDS if key in body]
    if not present:
        return "LEGACY", "no structured wake field"
    wake_class = body.get("wake_class")
    verdict = body.get("verdict")
    requested = body.get("verdict_requested")
    delta = body.get("delta")
    if "wake_class" in body and wake_class not in WAKE_CLASSES:
        return "INVALID", f"wake_class {wake_class!r} is not ACTIONABLE or NOTICE"
    if "verdict" in body and verdict not in VERDICTS:
        return "INVALID", f"verdict {verdict!r} is not one of {', '.join(VERDICTS)}"
    if "verdict_requested" in body and not isinstance(requested, bool):
        return "INVALID", f"verdict_requested {requested!r} is not a bool"
    if "delta" in body and not (isinstance(delta, str) and delta.strip()):
        return "INVALID", "delta is empty"
    has_verdict = "verdict" in body
    if wake_class == "NOTICE":
        if has_verdict or requested is True:
            return "INVALID", "NOTICE carries a verdict or verdict_requested"
        return "NOTICE", ""
    if not (str(body.get("actor") or "").strip() and str(body.get("requested_target") or "").strip()):
        return "INVALID", "an actionable letter needs actor and requested_target"
    if wake_class == "ACTIONABLE":
        if "delta" in body:
            return "ACTIONABLE", ""
        return "INVALID", "ACTIONABLE without delta"
    if requested is True or has_verdict:
        return "ACTIONABLE", ""
    return "INVALID", "no policy row"


def migration_record(project: Path, message_id: str, digest: Any) -> dict[str, Any] | None:
    """U141-A: a legacy letter's wake fields, valid only while bound to that exact message id and digest."""
    path = Path(project) / ".coord" / "mailbox" / "migration" / f"{message_id}.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    if record.get("source_message_id") != message_id or record.get("source_digest") != digest or not digest:
        return None
    return record


def letter_digest(message_id: str, body: Any) -> str:
    """The receipt key: the envelope digest, or, for producers that write none (thrift, sentinel), the id's sha256."""
    digest = body.get("digest") if isinstance(body, dict) else None
    if isinstance(digest, str) and digest.strip():
        return digest
    return hashlib.sha256(str(message_id).encode("utf-8")).hexdigest()


def _receipt_name(digest: Any) -> str:
    clean = "".join(ch for ch in str(digest or "") if ch.isalnum())
    if not clean:
        raise ValueError("a wake receipt needs a digest")
    return f"{clean}.json"


def pending_wake_path(project: Path, target: str, digest: Any) -> Path:
    watch_file(project, target)  # validates the tool name
    return Path(project) / PRESENCE_DIR / "pending_wake" / target / _receipt_name(digest)


def acked_wake_path(project: Path, target: str, digest: Any) -> Path:
    watch_file(project, target)
    return Path(project) / PRESENCE_DIR / "pending_wake" / target / "acked" / _receipt_name(digest)


def process_identity(pid: int) -> int | None:
    """U141-A: the creation time of a live process, so a reused PID never looks like the old owner. None if gone."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
        kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        process_query_limited_information = 0x1000
        still_active = 259
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return None
        try:
            code = wintypes.DWORD()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value != still_active:
                return None  # an exited process whose handle is still held elsewhere
            times = [wintypes.FILETIME() for _ in range(4)]
            if not kernel32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                return None
            return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        finally:
            kernel32.CloseHandle(handle)
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
    except OSError:
        try:
            os.kill(pid, 0)
        except OSError:
            return None
        return 0  # alive, but this platform has no /proc creation time; PID reuse cannot be told apart here
    # Field 22 (starttime) follows the ")" that closes the command name, which may itself hold spaces.
    fields = stat.rsplit(")", 1)[-1].split()
    try:
        return int(fields[19])
    except (IndexError, ValueError):
        return None


def _write_atomic(path: Path, record: dict[str, Any]) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    replace_with_retry(tmp, path)


def _receipt_state(path: Path, clock: Callable[[], float]) -> str:
    """EXISTS for a full record or a fresh placeholder; CORRUPT for anything else (kept as evidence)."""
    try:
        raw = path.read_bytes()
        age = clock() - path.stat().st_mtime
    except FileNotFoundError:
        return "MISSING"
    except OSError:
        return "EXISTS"  # being replaced right now (Windows sharing violation): fail closed, no second wake
    if not raw:
        return "EXISTS" if age < PLACEHOLDER_GRACE_S else "CORRUPT"
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return "CORRUPT"
    if not isinstance(record, dict) or any(key not in record for key in RECEIPT_KEYS):
        return "CORRUPT"
    return "EXISTS"


def claim_wake(project: Path, target: str, message_id: str, digest: Any, *,
               clock: Callable[[], float] | None = None) -> str:
    """U141-A: ACKED | CLAIMED | EXISTS | CORRUPT. Only CLAIMED may wake a session, so a letter wakes at most once."""
    clock = clock or time.time
    pending = pending_wake_path(project, target, digest)
    if acked_wake_path(project, target, digest).is_file():
        return "ACKED"
    pending.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(pending), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        state = _receipt_state(pending, clock)
        return "EXISTS" if state == "MISSING" else state
    os.close(fd)
    pid = os.getpid()
    _write_atomic(pending, {"target": target, "message_id": message_id, "digest": digest, "pid": pid,
                            "process_created": process_identity(pid), "created_at": clock()})
    return "CLAIMED"


def lock_file(project: Path, tool: str) -> Path:
    watch_file(project, tool)
    return Path(project) / PRESENCE_DIR / f"{tool}.watch.lock.json"


def _lock_owner_live(path: Path) -> bool:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False
    except (OSError, ValueError):
        return False  # unreadable: treated as stale and replaced
    if not isinstance(record, dict):
        return False
    created = process_identity(record.get("pid"))
    return created is not None and created == record.get("process_created")


def _take_locks(project: Path, tools: tuple[str, ...], mine: dict[str, Any]) -> tuple[list[str], str | None]:
    taken: list[str] = []
    for tool in tools:
        path = lock_file(project, tool)
        path.parent.mkdir(parents=True, exist_ok=True)
        if _lock_owner_live(path):
            return taken, tool
        _write_atomic(path, mine)
        taken.append(tool)
    return taken, None


def _release_locks(project: Path, tools: list[str], mine: dict[str, Any]) -> None:
    """Remove only this watcher's locks; a replacement watcher keeps its own."""
    for tool in tools:
        path = lock_file(project, tool)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(record, dict) and record.get("pid") == mine["pid"] and \
                    record.get("process_created") == mine["process_created"] and record.get("token") == mine["token"]:
                path.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass


def _stalled_wait(project: Path, tools: tuple[str, ...], clock: Callable[[], float]) -> dict[str, Any] | None:
    """U179: the first stalled wait one of `tools` has a part in and has not been woken for yet."""
    from v7_harness.coord import stall

    for tool in tools:
        try:
            result = stall.scan(project, tool, now=clock())
        except (OSError, ValueError):
            continue  # a locked or unreadable stall state: the next scan looks again, the watch goes on
        for entry in result["stalled"] + result["blocked"]:
            if tool not in (entry["author"], entry["waiting_on"], entry.get("owner")):
                continue
            # One receipt per wait instance: a step that waits again later has a new `since` and wakes again.
            key = f"stall:{entry['item']}:{entry['since']}"
            if claim_wake(project, tool, key, hashlib.sha256(key.encode("utf-8")).hexdigest(),
                          clock=clock) == "CLAIMED":
                return {"id": key, "reason": "STALLED_WAIT", "item": entry["item"], "kind": entry["kind"],
                        "waiting_on": entry["waiting_on"], "age_s": entry["age_s"], "owner": entry.get("owner"),
                        "requested_target": tool}
    return None


def watch(project: Path, tools: tuple[str, ...], *, timeout_s: float = DEFAULT_TIMEOUT_S,
          interval_s: float = DEFAULT_INTERVAL_S, clock: Callable[[], float] | None = None,
          sleep: Callable[[float], None] | None = None, wakes_session: bool = False,
          policy: str = "legacy") -> dict[str, Any] | None:
    """Return the first letter addressed to one of `tools` that was not in the inbox when the watch began.

    Letters already waiting are what `coord inbox` shows at session start; the watch reports only new ones, so a
    re-armed watch never wakes the session twice for the same letter. None means the timeout passed.

    U141-A `policy="structured"` (the CLI default): one watcher per target (a live owner returns
    ALREADY_WATCHING), no start snapshot, and only an ACTIONABLE letter whose wake receipt this watcher CLAIMED wakes
    the session. The receipt, not the snapshot, keeps a re-armed watcher from waking twice.
    """
    if policy not in ("legacy", "structured"):
        raise ValueError(f"unknown watch policy: {policy}")
    clock = clock or time.time
    sleep = sleep or time.sleep  # looked up per call so tests and callers can patch time.sleep
    for tool in tools:
        watch_file(project, tool)  # validates the name before anything is written
    # U59: a project whose first letter has not arrived yet has no mailbox folder; waiting on it is still valid.
    mailbox_dir = Path(project) / ".coord" / "mailbox"
    mailbox_dir.mkdir(parents=True, exist_ok=True)
    box = Mailbox(mailbox_dir)
    structured = policy == "structured"
    token = uuid.uuid4().hex
    locks: list[str] = []
    mine = {"pid": os.getpid(), "process_created": process_identity(os.getpid()), "token": token}
    if structured:
        locks, owned_by_other = _take_locks(project, tools, mine)
        if owned_by_other is not None:
            _release_locks(project, locks, mine)
            return {"state": "ALREADY_WATCHING", "tool": owned_by_other}
    seen = set() if structured else set(box.list_inbox())
    deadline = clock() + timeout_s
    next_stall_scan = deadline - timeout_s  # the first scan runs at once; no extra clock read (U117 test counts them)
    try:
        while True:
            _beat(project, tools, token, interval_s, clock(), wakes_session)
            # U94-R1: decide on the name first and read a letter's file only when its id is new to this watch.
            for message_id in box.list_inbox():
                if message_id in seen:
                    continue
                # U64-F: `coord deliver` already handed this letter to a Claude process (its accepted receipt
                # exists); waking the interactive session too would pay a second turn for the same letter.
                if (mailbox_dir / "delivery" / "accepted" / f"{message_id}.json").is_file():
                    seen.add(message_id)
                    continue
                # U66: the marker exists before a direct-dispatch letter is published. Do not mark it seen: if the
                # dispatch fails, the sender removes the marker and this same watcher becomes the fallback route.
                pending = mailbox_dir / "delivery" / "pending" / f"{message_id}.json"
                try:
                    pending_live = clock() - pending.stat().st_mtime <= PENDING_MAX_AGE_S
                except OSError:
                    pending_live = False
                if pending_live:
                    continue
                data = box.read_message(message_id)
                if data is None:
                    continue  # claimed meanwhile, or not readable yet: the next scan looks again, as peek() did
                seen.add(message_id)
                payload = data.get("payload")
                if _addressed(payload, tools):
                    body = payload if isinstance(payload, dict) else {}
                    found = {"id": message_id, "kind": body.get("kind"), "actor": body.get("actor"),
                             "requested_target": body.get("requested_target") or body.get("to")}
                    if not structured:
                        return found
                    target = found["requested_target"]
                    target = target if target in tools else tools[0]
                    cls, _diag = classify(body, migration_record(project, message_id, body.get("digest")))
                    if cls != "ACTIONABLE":
                        continue  # NOTICE, INVALID and LEGACY never wake; the hook shows them at zero tokens
                    if claim_wake(project, target, message_id, letter_digest(message_id, body),
                                  clock=clock) == "CLAIMED":
                        return {**found, "wake_class": cls}
            if structured and clock() >= next_stall_scan:
                next_stall_scan = clock() + STALL_SCAN_S
                stalled = _stalled_wait(Path(project), tools, clock)
                if stalled is not None:
                    return stalled
            if clock() >= deadline:
                return None
            sleep(interval_s)
    finally:
        _clear(project, tools, token)
        _release_locks(project, locks, mine)
