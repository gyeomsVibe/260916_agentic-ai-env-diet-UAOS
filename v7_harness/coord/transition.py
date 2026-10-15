"""U197: zero-paid work-transition controller, run by the sentinel each cycle.

Receipt: .work/userdesk_261015/IDLE_ROOT_CAUSE.md causes 1, 4, 5. A dependency-ready card sat READY while its
owner's watcher was alive and never woken, and an UNKNOWN desk told nobody to refresh it. Pattern: transactional
outbox plus idempotent consumer: the durable record is written before the letter, so a retry never sends twice.
It only reads the schedule and only publishes letters: no paid call, no claim, no schedule write (U195/U196 own those).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from .mailbox import Mailbox
from .next_card import next_step, schedule_path
from .presence import TOOLS, conductor, read_all
from .stall import MAX_WAIT_S
from .watch import watcher_live

OUTBOX = Path(".coord") / "transition" / "outbox"
RETRY_S = MAX_WAIT_S  # the stall scan's own wait limit: a wake unanswered this long is a stalled hand-off
MAX_ATTEMPTS = 3  # then one P1 to the conductor; more letters to a dead session only grow its inbox


def _row(project: Path, card: str) -> dict[str, Any] | None:
    try:
        phases = json.loads(schedule_path(project).read_text(encoding="utf-8"))["phases"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    rows = [p for p in phases if isinstance(p, dict) and str(p.get("phase_id")) == card] if isinstance(phases, list) else []
    return rows[0] if len(rows) == 1 else None


def _key(tool: str, card: str, row: dict[str, Any] | None) -> str:
    row = row or {}
    raw = "|".join(str(x) for x in (tool, card, row.get("state"), row.get("owner_tool"), row.get("owner_session")))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _write(path: Path, record: dict[str, Any], *, exclusive: bool = False) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive:
        try:
            with open(path, "x", encoding="utf-8") as handle:
                handle.write(json.dumps(record))
            return True
        except FileExistsError:
            return False
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(record), encoding="utf-8")
    os.replace(tmp, path)
    return True


def _claimed(project: Path, record: dict[str, Any]) -> bool:
    claim = schedule_path(project).parent / "next" / "claims" / f"{record['card']}.json"
    try:
        held = json.loads(claim.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    at = held.get("at") if isinstance(held, dict) else None
    return (held.get("tool") == record["tool"] and isinstance(at, (int, float)) and not isinstance(at, bool)
            and at >= record["first_at"])


def _letter(box: Mailbox, message_id: str, target: str, delta: str, **extra: Any) -> bool:
    if box.has_message(message_id):
        return False
    box.publish(message_id=message_id, payload={"actor": "sentinel", "requested_target": target,
                                                "wake_class": "ACTIONABLE", "delta": delta[:200], **extra})
    return True


def run_transitions(project: Path, box: Mailbox, *, now: float | None = None) -> dict[str, Any]:
    project = Path(project)
    moment = time.time() if now is None else now
    out: dict[str, Any] = {"published": [], "acked": [], "exhausted": [], "paid_api_calls": 0}
    outbox = project / OUTBOX
    desk = read_all(project, now=moment)
    lead = conductor(desk)["conductor"]
    if lead == "UNKNOWN":
        states = "|".join(f"{t}={(desk.get(t) or {}).get('state', 'UNKNOWN')}" for t in TOOLS)
        key = hashlib.sha256(states.encode("utf-8")).hexdigest()
        for tool in TOOLS:
            if not watcher_live(project, tool, now=moment):
                continue
            message_id = f"transition_unknown_{key[:24]}_{tool}"
            if _letter(box, message_id, tool, f"CONDUCTOR_UNKNOWN ({states}): refresh with coord presence",
                       transition_key=key):
                out["published"].append(message_id)
    # Pass 1: settle records already sent (ack, retry, escalate).
    for path in sorted(outbox.glob("*.json")) if outbox.is_dir() else []:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(record, dict) or record.get("status") != "SENT":
            continue
        if _claimed(project, record) or _key(record["tool"], record["card"], _row(project, record["card"])) != path.stem:
            record.update(status="ACKED", acked_at=moment)
            _write(path, record)
            out["acked"].append(path.stem)
            continue
        if moment - record["last_at"] < RETRY_S:
            continue
        if record["attempts"] >= MAX_ATTEMPTS:
            target = lead if lead in TOOLS else ""
            message_id = f"transition_p1_{path.stem[:24]}"
            if not box.has_message(message_id):
                box.publish(message_id=message_id, payload={
                    "kind": "BLOCKED", "is_p1": True, "step": record["card"], "actor": "sentinel",
                    "requested_target": target or "conductor", "wake_class": "ACTIONABLE",
                    "delta": f"{record['card']} unclaimed by {record['tool']} after {record['attempts']} wakes"})
            record.update(status="EXHAUSTED", exhausted_at=moment)
            _write(path, record)
            out["exhausted"].append(path.stem)
            continue
        record["attempts"] += 1
        record["last_at"] = moment
        _write(path, record)
        message_id = f"transition_{path.stem[:24]}_{record['attempts']}"
        if _letter(box, message_id, record["tool"], _delta(record), transition_key=path.stem):
            out["published"].append(message_id)
    # Pass 2: open a record for each new transition, then send its first letter.
    for tool in TOOLS:
        step = next_step(project, tool)
        if step.get("state") != "NEXT":
            continue
        card = str(step["card"])
        key = _key(tool, card, _row(project, card))
        record = {"tool": tool, "card": card, "status": "SENT", "attempts": 1, "first_at": moment, "last_at": moment}
        if not _write(outbox / f"{key}.json", record, exclusive=True):
            continue
        message_id = f"transition_{key[:24]}_1"
        if _letter(box, message_id, tool, _delta(record), transition_key=key):
            out["published"].append(message_id)
    return out


def _delta(record: dict[str, Any]) -> str:
    return (f"NEXT card {record['card']} for {record['tool']} (wake {record['attempts']}/{MAX_ATTEMPTS}): "
            f"uaos coord next --tool {record['tool']} --claim --session <id>")
