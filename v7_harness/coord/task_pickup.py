"""U161: Autonomous Work Stealing and Task Pickup on Idle Timeout.

When an agent (Antigravity, Codex, or Claude) has no active turn or is waiting for tasks,
idle task pickup inspects the coordination state:
1. Mailbox inspection: checks for pending ACTIONABLE letters or verification/audit requests addressed to the actor.
2. Plan inspection: checks .coord/PLAN.md for READY cards assigned to the actor or unassigned.
3. Conductor request: if no task is found and auto_request is enabled (or on idle timeout),
   sends a zero-paid-token inquiry to the active conductor requesting task assignment.

Theory & Best Practices:
- Blumofe & Leiserson (1999) work-stealing algorithm bounds.
- Zero-paid-token deterministic checks.
- Fail-closed and idempotent claiming via Mailbox atomic claims.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from v7_harness.coord import presence
from v7_harness.coord.deliver import deliver
from v7_harness.coord.mailbox import Mailbox
from v7_harness.coord.watch import classify, migration_record


READY_CARD_RE = re.compile(r"\|\s*([A-Za-z0-9_-]+)\s*\|\s*READY\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|")


def scan_mailbox_for_tasks(project: Path, actor: str) -> dict[str, Any] | None:
    """Scan inbox for ACTIONABLE messages or audit requests addressed to actor."""
    mailbox_dir = Path(project) / ".coord" / "mailbox"
    if not mailbox_dir.exists():
        return None
    box = Mailbox(mailbox_dir)
    inbox_ids = box.list_inbox()
    for message_id in inbox_ids:
        msg = box.read_message(message_id)
        if not msg or not isinstance(msg.get("payload"), dict):
            continue
        payload = msg["payload"]
        target = payload.get("requested_target") or payload.get("to")
        if target not in (actor, None, "*", "any"):
            continue
        cls, _diag = classify(payload, migration_record(project, message_id, payload.get("digest")))
        if cls == "ACTIONABLE" or payload.get("verdict_requested") is True:
            return {
                "status": "ACTIONABLE_LETTER",
                "message_id": message_id,
                "actor": payload.get("actor"),
                "card": payload.get("card"),
                "delta": payload.get("delta"),
                "summary": (payload.get("message") or "")[:200],
            }
    return None


def scan_plan_for_ready_tasks(project: Path, actor: str) -> dict[str, Any] | None:
    """Scan .coord/PLAN.md for READY cards that actor can undertake."""
    plan_file = Path(project) / ".coord" / "PLAN.md"
    if not plan_file.is_file():
        return None
    try:
        content = plan_file.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in content.splitlines():
        m = READY_CARD_RE.search(line)
        if m:
            card_id = m.group(1).strip()
            owner = m.group(2).strip().lower()
            desc = m.group(3).strip()
            if actor.lower() in owner or owner in ("unassigned", "ready", "tbd", "all", "-"):
                return {
                    "status": "READY_CARD",
                    "card": card_id,
                    "owner": owner,
                    "description": desc,
                }
    return None


def request_task_from_conductor(
    project: Path,
    actor: str,
    *,
    runner: Any = None,
) -> dict[str, Any]:
    """Send an inquiry letter to the active conductor asking for the next task."""
    desk = presence.read_all(project)
    cond = presence.conductor(desk)
    target = cond.get("conductor")
    if not target or target in ("none", "UNKNOWN", actor):
        for candidate in ("codex", "claude"):
            if candidate != actor:
                target = candidate
                break
    msg = f"[idle-pickup] {actor} is idle and has no pending tasks. Requesting next ready task assignment or audit verification."
    res = deliver(
        Path(project),
        message=msg,
        actor=actor,
        target=target,
        wake_class="NOTICE",
        delta=f"Idle task request from {actor}",
        runner=runner,
    )
    return {
        "status": "TASK_REQUESTED",
        "target": target,
        "message_id": res.message_id,
    }


def pickup_task(
    project: Path,
    actor: str,
    *,
    auto_request: bool = False,
    runner: Any = None,
) -> dict[str, Any]:
    """Autonomous work stealing & task pickup entry point."""
    project = Path(project).resolve()
    # 1. Check mailbox
    mb_task = scan_mailbox_for_tasks(project, actor)
    if mb_task:
        return mb_task

    # 2. Check plan
    plan_task = scan_plan_for_ready_tasks(project, actor)
    if plan_task:
        return plan_task

    # 3. If idle and auto_request is True, ask conductor
    if auto_request:
        return request_task_from_conductor(project, actor, runner=runner)

    return {"status": "IDLE", "actor": actor, "message": "No actionable tasks found"}


def list_incoming_tasks(
    project: Path,
    from_actor: str = "claude",
    to_actor: str = "antigravity",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """List incoming tasks/letters from a specific peer tool with full provenance state."""
    project = Path(project).resolve()
    mailbox_dir = project / ".coord" / "mailbox"
    results = []
    if not mailbox_dir.exists():
        return results

    box = Mailbox(mailbox_dir)
    inbox_ids = set(box.list_inbox())
    ack_dir = mailbox_dir / "ack"
    all_files = list((mailbox_dir / "inbox").glob("*.json"))
    if ack_dir.exists():
        all_files.extend(ack_dir.glob("*.json"))

    all_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    for p in all_files:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        payload = data.get("payload") if isinstance(data, dict) else None
        if not isinstance(payload, dict):
            continue
        actor = payload.get("actor")
        target = payload.get("requested_target") or payload.get("to")
        if from_actor and actor != from_actor:
            continue
        if to_actor and target not in (to_actor, None, "*", "any"):
            continue

        msg_id = data.get("message_id") or p.stem
        state = "PENDING_INBOX" if msg_id in inbox_ids else "PROCESSED_ACK"
        mtime = p.stat().st_mtime
        results.append({
            "message_id": msg_id,
            "state": state,
            "actor": actor,
            "target": target,
            "card": payload.get("card"),
            "delta": payload.get("delta"),
            "wake_class": payload.get("wake_class"),
            "verdict_requested": payload.get("verdict_requested", False),
            "summary": (payload.get("message") or "")[:200],
            "mtime": mtime,
        })
        if len(results) >= limit:
            break
    return results
