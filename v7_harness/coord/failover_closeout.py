"""U249: 3->2->1 Tool Quota Failover, Sole-Survivor Autonomous Closeout & >5s Foreground Wait Preemption.

Implements the three nonstop resilience invariants requested by 윤겸스 (2026-10-26):
1. 3->2 Quota Failover (`replan_on_quota_limit`):
   When 1 tool hits `LIMITED` or `ABSENT`, its non-DONE phases (`READY`, `PLANNED`,
   `BLOCKED`, or stalled `ACTIVE`) are immediately replanned across the remaining
   2 `ACTIVE` tools (`TWO_TOOL_CONTINUITY`).
2. 2->1 Sole-Survivor Autonomous Closeout (`SOLE_SURVIVOR_AUTONOMOUS`):
   When 2 tools are `LIMITED`/`ABSENT` and only 1 `ACTIVE` tool remains, that sole
   survivor takes ownership of all remaining non-human phases and promotes pending
   `REVIEW` phases to `DONE` with `acting_sole_survivor` + `needs_return_review`
   so dependent phases unlock and the entire schedule finishes nonstop.
3. >5s Non-Background Wait Preemption & Natural Schedule Closeout
   (`preempt_foreground_wait` & `finalize_schedule_closeout`):
   Background daemon watchers (`coord watch`, `is_background_watcher=True`) may wait
   0-token until an event arrives. Any non-background foreground wait exceeding
   `FOREGROUND_WAIT_LIMIT_S = 5.0` seconds immediately audits the schedule,
   triggers quota replanning, claims the next ready work, or—if all non-human
   schedule phases are `DONE`—executes natural schedule closeout.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from . import next_card, presence
from .stall import HUMAN_ONLY_RE

FOREGROUND_WAIT_LIMIT_S = 5.0
TOOL_ORDER = ("claude", "antigravity", "codex")
REASSIGNABLE_STATES = ("READY", "PLANNED", "BLOCKED", "ACTIVE")


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _is_human_only(phase: dict[str, Any]) -> bool:
    state = str(phase.get("state", ""))
    text = f"{phase.get('phase_id', '')} {phase.get('title', '')} {phase.get('human', '')} {phase.get('note', '')}"
    return state == "HUMAN" or bool(HUMAN_ONLY_RE.search(text))


def replan_on_quota_limit(
    project: Path | str,
    *,
    desk: dict[str, dict[str, Any]] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Audit tool presence and replan phases owned by LIMITED/ABSENT tools (3->2->1)."""
    root = next_card.coord_root(Path(project))
    moment = time.time() if now is None else float(now)
    if desk is None:
        desk = presence.read_all(root, now=moment)

    active_tools = [t for t in TOOL_ORDER if (desk.get(t) or {}).get("state") == "ACTIVE"]
    unavailable_tools = [t for t in TOOL_ORDER if (desk.get(t) or {}).get("state") in ("LIMITED", "ABSENT")]

    sched_file = next_card.schedule_path(root)
    schedule = _read_json(sched_file, None)
    if not isinstance(schedule, dict) or not isinstance(schedule.get("phases"), list):
        return {
            "ok": False,
            "mode": "NO_SCHEDULE",
            "active_tools": active_tools,
            "unavailable_tools": unavailable_tools,
            "replanned": [],
            "sole_survivor_reviews_promoted": [],
        }

    if not active_tools or not unavailable_tools:
        return {
            "ok": True,
            "mode": "THREE_TOOL_NORMAL" if len(active_tools) >= 3 else "NO_FAILOVER_NEEDED",
            "active_tools": active_tools,
            "unavailable_tools": unavailable_tools,
            "replanned": [],
            "sole_survivor_reviews_promoted": [],
        }

    sole_survivor = active_tools[0] if len(active_tools) == 1 else None
    mode = "SOLE_SURVIVOR_AUTONOMOUS" if sole_survivor else "TWO_TOOL_CONTINUITY"
    replanned: list[dict[str, Any]] = []
    reviews_promoted: list[str] = []
    rr_idx = 0

    for phase in schedule["phases"]:
        if not isinstance(phase, dict) or not phase.get("phase_id"):
            continue
        if _is_human_only(phase):
            continue
        pid = str(phase["phase_id"])
        state = str(phase.get("state", ""))
        owner = str(phase.get("owner_tool", ""))

        if sole_survivor and state == "REVIEW":
            phase["rerouted_from"] = {
                "owner_tool": owner,
                "state": state,
                "waiting_on": phase.get("waiting_on"),
            }
            phase.pop("waiting_on", None)
            phase["state"] = "DONE"
            phase["acting_sole_survivor"] = sole_survivor
            phase["needs_return_review"] = list(unavailable_tools)
            phase["failover_mode"] = mode
            reviews_promoted.append(pid)
            continue

        if state in REASSIGNABLE_STATES and owner in unavailable_tools:
            new_owner = sole_survivor if sole_survivor else active_tools[rr_idx % len(active_tools)]
            rr_idx += 1
            phase["rerouted_from"] = {
                "owner_tool": owner,
                "state": state,
                "unavailable_state": (desk.get(owner) or {}).get("state"),
            }
            phase.pop("waiting_on", None)
            phase["owner_tool"] = new_owner
            phase["state"] = "READY"
            phase["failover_mode"] = mode
            if sole_survivor:
                phase["needs_return_review"] = list(unavailable_tools)
            replanned.append({
                "phase_id": pid,
                "from_owner": owner,
                "to_owner": new_owner,
                "old_state": state,
                "new_state": "READY",
                "mode": mode,
            })

    if replanned or reviews_promoted:
        schedule["failover_state"] = {
            "mode": mode,
            "active_tools": active_tools,
            "unavailable_tools": unavailable_tools,
            "updated_at": moment,
        }
        _write_json(sched_file, schedule)

    return {
        "ok": True,
        "mode": mode,
        "active_tools": active_tools,
        "unavailable_tools": unavailable_tools,
        "replanned": replanned,
        "sole_survivor_reviews_promoted": reviews_promoted,
    }


def finalize_schedule_closeout(
    project: Path | str,
    *,
    tool: str = "antigravity",
    now: float | None = None,
) -> dict[str, Any]:
    """Naturally close out the current process when all non-human schedule phases are DONE."""
    root = next_card.coord_root(Path(project))
    moment = time.time() if now is None else float(now)
    sched_file = next_card.schedule_path(root)
    schedule = _read_json(sched_file, None)
    if not isinstance(schedule, dict) or not isinstance(schedule.get("phases"), list):
        return {"closed_out": False, "state": "NO_SCHEDULE", "remaining": []}

    phases = [p for p in schedule["phases"] if isinstance(p, dict) and p.get("phase_id")]
    non_human = [p for p in phases if str(p.get("state", "")) != "HUMAN"]
    pending = [str(p["phase_id"]) for p in non_human if str(p.get("state", "")) != "DONE"]
    if pending:
        return {
            "closed_out": False,
            "state": "IN_PROGRESS",
            "remaining": pending,
            "completed_count": len(non_human) - len(pending),
            "total_non_human": len(non_human),
        }

    schedule_id = str(schedule.get("schedule_id") or "MASTER")
    return_reviews = [
        {"phase_id": str(p["phase_id"]), "needs_return_review": p["needs_return_review"]}
        for p in non_human
        if p.get("needs_return_review")
    ]
    receipt = {
        "schedule_id": schedule_id,
        "state": "CLOSED_OUT",
        "closed_out_by": tool,
        "closed_at": moment,
        "completed_count": len(non_human),
        "human_items_remaining": [str(p["phase_id"]) for p in phases if str(p.get("state", "")) == "HUMAN"],
        "sole_survivor_return_reviews": return_reviews,
    }
    receipt_path = root / ".coord" / "results" / f"SCHEDULE-CLOSEOUT-{schedule_id}.json"
    _write_json(receipt_path, receipt)

    presence_dir = root / ".coord" / "presence"
    for t in TOOL_ORDER:
        guard_file = presence_dir / f"stop_gate_{t}.json"
        try:
            guard_file.unlink(missing_ok=True)
        except OSError:
            pass

    schedule["schedule_state"] = "CLOSED_OUT"
    schedule["closed_out_at"] = moment
    schedule["closed_out_by"] = tool
    _write_json(sched_file, schedule)

    return {
        "closed_out": True,
        "state": "CLOSED_OUT",
        "schedule_id": schedule_id,
        "completed_count": len(non_human),
        "receipt_path": str(receipt_path),
        "sole_survivor_return_reviews": return_reviews,
    }


def preempt_foreground_wait(
    project: Path | str,
    tool: str,
    *,
    wait_elapsed_s: float,
    is_background_watcher: bool = False,
    desk: dict[str, dict[str, Any]] | None = None,
    session: str | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Preempt any non-background foreground wait >= 5.0s, audit schedule, claim work, or close out."""
    if is_background_watcher:
        return {
            "preempted": False,
            "reason": "BACKGROUND_WATCHER_EXEMPT",
            "wait_elapsed_s": float(wait_elapsed_s),
        }
    if float(wait_elapsed_s) < FOREGROUND_WAIT_LIMIT_S:
        return {
            "preempted": False,
            "reason": "UNDER_5S_THRESHOLD",
            "wait_elapsed_s": float(wait_elapsed_s),
            "threshold_s": FOREGROUND_WAIT_LIMIT_S,
        }

    root = next_card.coord_root(Path(project))
    moment = time.time() if now is None else float(now)
    replan = replan_on_quota_limit(root, desk=desk, now=moment)
    closeout = finalize_schedule_closeout(root, tool=tool, now=moment)
    if closeout.get("closed_out"):
        return {
            "preempted": True,
            "action": "NATURAL_CLOSEOUT",
            "wait_elapsed_s": float(wait_elapsed_s),
            "replan": replan,
            "closeout": closeout,
        }

    step = next_card.next_step(root, tool, claim=bool(session), session=session, now=moment)
    action = "CLAIM_NEXT_WORK" if step.get("state") == "NEXT" else f"SCHEDULE_{step.get('state', 'WAIT')}"
    return {
        "preempted": True,
        "action": action,
        "wait_elapsed_s": float(wait_elapsed_s),
        "replan": replan,
        "next_step": step,
        "closeout": closeout,
    }
