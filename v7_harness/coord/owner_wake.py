"""U205: the resident sentinel wakes the owner of a ready step that nobody has started.

Receipt (2026-10-16): U196-REROUTE-BINDING sat PENDING with its dependency DONE for 15 hours, owned by an idle Claude;
U166/U203 watch only waiting states (HUMAN, REVIEW, BLOCKED), so a ready step had no alarm at all. Stage 0: a
level-triggered controller reconciles every object that is not in its desired state on each loop, not only those that
raised an event (https://kubernetes.io/docs/concepts/architecture/controller/).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .stall import MAX_WAIT_S, NOTICE_KEEP_S, SCHEDULE, STATE_DIR, _read_json, _write_json

# Steps an owner must start or redo itself; waiting states belong to the U166 stall scan, DONE* and HUMAN to nobody.
READY_STATES = ("PENDING", "READY", "REWORK")
TOOLS = ("codex", "claude", "antigravity")


def ready_steps(schedule: dict[str, Any], *, now: float, seen: dict[str, float]) -> list[dict[str, Any]]:
    """Ready steps whose dependencies are all DONE and which have stayed ready for MAX_WAIT_S.

    The wait counts from when a scan first saw the step ready (kept in `seen`, pruned to the steps ready now), not from
    the schedule's mtime or `updated_at`: an unrelated schedule write must not restart it, and a step whose dependency
    has just finished gets its full MAX_WAIT_S (Antigravity audit relay_bcc4ae4a, defect 1).
    """
    phases = [p for p in schedule.get("phases") or [] if isinstance(p, dict) and p.get("phase_id")]
    state = {str(p["phase_id"]): str(p.get("state", "")) for p in phases}
    found, live = [], set()
    for phase in phases:
        owner = str(phase.get("owner_tool", ""))
        if str(phase.get("state", "")) not in READY_STATES or owner not in TOOLS:
            continue
        if any(not state.get(str(dep), "").startswith("DONE") for dep in phase.get("depends_on") or []):
            continue
        key = f"{phase['phase_id']}|{phase['state']}|{owner}"
        live.add(key)
        since = float(seen.setdefault(key, now))
        if now - since >= MAX_WAIT_S:
            found.append({"phase_id": str(phase["phase_id"]), "state": str(phase["state"]), "owner": owner,
                          "since": since})
    for key in set(seen) - live:
        del seen[key]
    return found


def wake_owners(project: Path, box: Any, *, now: float) -> list[str]:
    """Publish one ACTIONABLE wake per ready step to its owner; repeat at most once per NOTICE_KEEP_S (6 h)."""
    path = Path(project) / SCHEDULE
    try:
        schedule = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    seen_path = Path(project) / STATE_DIR / "ready_seen.json"
    seen = _read_json(seen_path, {})
    if not isinstance(schedule, dict) or not isinstance(seen, dict):
        return []
    sent = []
    steps = ready_steps(schedule, now=now, seen=seen)
    _write_json(seen_path, seen)
    for step in steps:
        # One id per step instance (state and start) and per 6 h window, so an ignored wake repeats but never floods.
        key = f"{step['phase_id']}|{step['state']}|{step['owner']}|{step['since']}|{int(now // NOTICE_KEEP_S)}"
        message_id = "owner_wake_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
        if box.has_message(message_id):
            continue
        delta = (f"OWNER WAKE (U205): {step['phase_id']} is {step['state']} with its dependencies DONE and untouched "
                 f"{int((now - step['since']) // 60)} min; you own it: take it now or hand it off by coord deliver")
        box.publish(message_id=message_id, payload={
            "recipient": step["owner"], "requested_target": step["owner"], "wake_class": "ACTIONABLE",
            "delta": delta[:200], "wake_reason": delta, "actor": "sentinel", "card": step["phase_id"]})
        sent.append(message_id)
    return sent
