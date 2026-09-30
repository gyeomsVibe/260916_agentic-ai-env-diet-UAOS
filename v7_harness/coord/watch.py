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

# 2 s between inbox scans: the hand-written loop used 30 s on 2026-09-27 and a letter waited at most that long;
# one scan lists one directory, so a shorter interval costs only disk reads, never tokens.
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
