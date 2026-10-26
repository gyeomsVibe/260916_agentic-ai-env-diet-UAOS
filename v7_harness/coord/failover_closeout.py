"""U249: 3->2->1 Tool Quota Failover, Sole-Survivor Autonomous Closeout & >5s Foreground Wait Preemption.

Implements the three nonstop resilience invariants requested by 윤겸스 (2026-10-26), hardened per Claude judge review:
1. 3->2 Quota Failover (`replan_on_quota_limit`):
   When 1 tool hits `LIMITED` or `ABSENT`, its `READY`/`PLANNED` phases (plus `BLOCKED` phases
   whose `waiting_on` names an unavailable tool, and `ACTIVE` phases stalled past `ACTIVE_STALL_TIMEOUT_S`)
   are atomically replanned under `stall.lock` across the remaining `ACTIVE` tools (`TWO_TOOL_CONTINUITY`).
2. 2->1 Sole-Survivor Autonomous Continuity (`SOLE_SURVIVOR_AUTONOMOUS`):
   When 2 tools are `LIMITED`/`ABSENT` and only 1 `ACTIVE` tool remains, `REVIEW` phases stay `REVIEW`
   (never self-approved to `DONE`) with `acting_sole_survivor` + `needs_return_review`, and only phases
   that do not depend on an unapproved `REVIEW` phase proceed.
3. >5s Non-Background Wait Preemption & Natural Schedule Closeout
   (`preempt_foreground_wait` & `finalize_schedule_closeout`):
   Background daemon watchers (`coord watch`, `is_background_watcher=True`) may wait 0-token until an
   event arrives. Any non-background foreground wait >= `FOREGROUND_WAIT_LIMIT_S = 5.0` seconds audits
   the schedule under lock, triggers quota replanning, claims the next ready work whose dependencies are
   `DONE`, or—if all non-human schedule phases are `DONE`—executes natural schedule closeout.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from . import next_card, presence
from .stall import HUMAN_ONLY_RE, MAX_WAIT_S, STATE_DIR
from .stream import _exclusive

FOREGROUND_WAIT_LIMIT_S = 5.0
ACTIVE_STALL_TIMEOUT_S = float(MAX_WAIT_S)
TOOL_ORDER = ("claude", "antigravity", "codex")
REASSIGNABLE_STATES = ("READY", "PLANNED")


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _schedule_lock_path(root: Path) -> Path:
    lock_dir = root / STATE_DIR
    lock_dir.mkdir(parents=True, exist_ok=True)
    return lock_dir / "stall.lock"


def _is_human_only(phase: dict[str, Any]) -> bool:
    state = str(phase.get("state", ""))
    waiting_on = str(phase.get("waiting_on", ""))
    blocker_kind = str(phase.get("blocker_kind", ""))
    text = (
        f"{phase.get('phase_id', '')} {phase.get('title', '')} "
        f"{phase.get('human', '')} {phase.get('note', '')} "
        f"{waiting_on} {blocker_kind}"
    )
    if state == "HUMAN" or blocker_kind == "SAFETY_GATE":
        return True
    if waiting_on.lower() in ("human", "user", "윤겸스"):
        return True
    return bool(HUMAN_ONLY_RE.search(text))


def _waiting_on_unavailable(phase: dict[str, Any], unavailable_tools: list[str]) -> bool:
    waiting_on = str(phase.get("waiting_on") or "").strip().lower()
    if not waiting_on:
        return False
    for tool in unavailable_tools:
        if waiting_on == tool or waiting_on.startswith(f"{tool}-") or waiting_on.startswith(f"{tool}:"):
            return True
    return False


def _active_is_stalled(phase: dict[str, Any], moment: float, stall_timeout_s: float) -> bool:
    for key in ("waiting_since", "started_at", "updated_at", "claimed_at"):
        val = phase.get(key)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return (moment - float(val)) >= stall_timeout_s
    return False


def _depends_on_unapproved_review(phase: dict[str, Any], by_id: dict[str, dict[str, Any]], seen: frozenset[str] = frozenset()) -> bool:
    pid = str(phase.get("phase_id") or "")
    for dep in phase.get("depends_on") or []:
        dep_id = str(dep)
        if dep_id in seen:
            continue
        node = by_id.get(dep_id)
        if node is None:
            continue
        if str(node.get("state") or "") != "DONE":
            return True
        if _depends_on_unapproved_review(node, by_id, seen | {pid}):
            return True
    return False


def replan_on_quota_limit(
    project: Path | str,
    *,
    desk: dict[str, dict[str, Any]] | None = None,
    now: float | None = None,
    stall_timeout_s: float = ACTIVE_STALL_TIMEOUT_S,
) -> dict[str, Any]:
    """Audit tool presence and replan eligible phases owned by LIMITED/ABSENT tools under lock (3->2->1)."""
    root = next_card.coord_root(Path(project))
    moment = time.time() if now is None else float(now)
    if desk is None:
        desk = presence.read_all(root, now=moment)

    active_tools = [t for t in TOOL_ORDER if (desk.get(t) or {}).get("state") == "ACTIVE"]
    unavailable_tools = [t for t in TOOL_ORDER if (desk.get(t) or {}).get("state") in ("LIMITED", "ABSENT")]

    with _exclusive(_schedule_lock_path(root)):
        sched_file = next_card.schedule_path(root)
        schedule = _read_json(sched_file, None)
        if not isinstance(schedule, dict) or not isinstance(schedule.get("phases"), list):
            return {
                "ok": False,
                "mode": "NO_SCHEDULE",
                "active_tools": active_tools,
                "unavailable_tools": unavailable_tools,
                "replanned": [],
                "sole_survivor_reviews_deferred": [],
                "sole_survivor_reviews_promoted": [],
            }

        if not active_tools or not unavailable_tools:
            return {
                "ok": True,
                "mode": "THREE_TOOL_NORMAL" if len(active_tools) >= 3 else "NO_FAILOVER_NEEDED",
                "active_tools": active_tools,
                "unavailable_tools": unavailable_tools,
                "replanned": [],
                "sole_survivor_reviews_deferred": [],
                "sole_survivor_reviews_promoted": [],
            }

        sole_survivor = active_tools[0] if len(active_tools) == 1 else None
        mode = "SOLE_SURVIVOR_AUTONOMOUS" if sole_survivor else "TWO_TOOL_CONTINUITY"
        replanned: list[dict[str, Any]] = []
        reviews_deferred: list[str] = []
        rr_idx = 0

        by_id = {
            str(p["phase_id"]): p
            for p in schedule["phases"]
            if isinstance(p, dict) and p.get("phase_id")
        }

        for phase in schedule["phases"]:
            if not isinstance(phase, dict) or not phase.get("phase_id"):
                continue
            if _is_human_only(phase):
                continue
            pid = str(phase["phase_id"])
            state = str(phase.get("state", ""))
            owner = str(phase.get("owner_tool", ""))

            # Finding 1 (P1): Sole survivor NEVER self-approves REVIEW -> DONE.
            # Keep state == "REVIEW" and record needs_return_review so independent return review is required.
            if sole_survivor and state == "REVIEW":
                if _waiting_on_unavailable(phase, unavailable_tools) or owner in unavailable_tools or owner == sole_survivor:
                    phase["acting_sole_survivor"] = sole_survivor
                    phase["needs_return_review"] = list(unavailable_tools)
                    phase["failover_mode"] = mode
                    reviews_deferred.append(pid)
                continue

            # Finding 2 (P1): Reassign only READY/PLANNED; BLOCKED only when waiting_on names an unavailable tool;
            # ACTIVE only when owner is unavailable AND stalled past stall_timeout_s.
            eligible = False
            if state in REASSIGNABLE_STATES and owner in unavailable_tools:
                eligible = True
            elif state == "BLOCKED" and _waiting_on_unavailable(phase, unavailable_tools):
                eligible = True
            elif state == "ACTIVE" and owner in unavailable_tools and _active_is_stalled(phase, moment, stall_timeout_s):
                eligible = True

            if not eligible:
                continue

            # Phases that depend on a non-DONE (e.g. REVIEW) phase stay PLANNED (not promoted to READY)
            has_unapproved_dep = _depends_on_unapproved_review(phase, by_id)
            target_state = "PLANNED" if (state == "PLANNED" or has_unapproved_dep) else "READY"
            if has_unapproved_dep:
                phase["blocker_kind"] = "UNAPPROVED_REVIEW_DEPENDENCY"
            elif phase.get("blocker_kind") == "UNAPPROVED_REVIEW_DEPENDENCY":
                phase.pop("blocker_kind", None)

            new_owner = sole_survivor if sole_survivor else active_tools[rr_idx % len(active_tools)]
            rr_idx += 1
            phase["rerouted_from"] = {
                "owner_tool": owner,
                "state": state,
                "waiting_on": phase.get("waiting_on"),
                "unavailable_state": (desk.get(owner) or {}).get("state"),
            }
            phase.pop("waiting_on", None)
            phase["owner_tool"] = new_owner
            phase["state"] = target_state
            phase["failover_mode"] = mode
            if sole_survivor:
                phase["needs_return_review"] = list(unavailable_tools)
            replanned.append({
                "phase_id": pid,
                "from_owner": owner,
                "to_owner": new_owner,
                "old_state": state,
                "new_state": target_state,
                "mode": mode,
            })

        if replanned or reviews_deferred:
            history = schedule.get("failover_history")
            if not isinstance(history, list):
                history = []
            history.append({
                "mode": mode,
                "active_tools": active_tools,
                "unavailable_tools": unavailable_tools,
                "replanned_ids": [r["phase_id"] for r in replanned],
                "updated_at": moment,
            })
            schedule["failover_history"] = history
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
            "sole_survivor_reviews_deferred": reviews_deferred,
            "sole_survivor_reviews_promoted": [],
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
    with _exclusive(_schedule_lock_path(root)):
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
            "wait_elapsed_s": wait_elapsed_s,
        }
    if float(wait_elapsed_s) < FOREGROUND_WAIT_LIMIT_S:
        return {
            "preempted": False,
            "reason": "UNDER_5S_THRESHOLD",
            "wait_elapsed_s": wait_elapsed_s,
        }

    root = next_card.coord_root(Path(project))
    moment = time.time() if now is None else float(now)
    replan = replan_on_quota_limit(root, desk=desk, now=moment)
    closeout = finalize_schedule_closeout(root, tool=tool, now=moment)
    if closeout.get("closed_out"):
        return {
            "preempted": True,
            "action": "NATURAL_CLOSEOUT",
            "replan": replan,
            "closeout": closeout,
        }

    # Only allow phases whose dependencies are all DONE (never stack on an unapproved sole-survivor REVIEW)
    sched = _read_json(next_card.schedule_path(root), {})
    phases = sched.get("phases") if isinstance(sched, dict) and isinstance(sched.get("phases"), list) else []
    by_id = {str(p["phase_id"]): p for p in phases if isinstance(p, dict) and p.get("phase_id")}

    step = next_card.next_step(root, tool, claim=bool(session), session=session, now=moment)
    if step.get("state") == "NEXT":
        card_node = by_id.get(str(step.get("card") or ""))
        if card_node is not None and _depends_on_unapproved_review(card_node, by_id):
            step = {"state": "WAIT", "reason": "DEPENDS_ON_UNAPPROVED_REVIEW", "card": step.get("card")}
            for cand in phases:
                if not isinstance(cand, dict) or not cand.get("phase_id"):
                    continue
                if cand.get("owner_tool") not in (tool, "all") or cand.get("state") not in ("READY", "PLANNED"):
                    continue
                if _is_human_only(cand) or _depends_on_unapproved_review(cand, by_id):
                    continue
                step = {
                    "state": "NEXT",
                    "card": str(cand["phase_id"]),
                    "owner": cand.get("owner_tool"),
                    "claimed": bool(session),
                }
                break

    action = "CLAIM_NEXT_WORK" if step.get("state") == "NEXT" else "WAIT_HUMAN_OR_EXTERNAL"
    return {
        "preempted": True,
        "action": action,
        "replan": replan,
        "next_step": step,
        "closeout": closeout,
    }
