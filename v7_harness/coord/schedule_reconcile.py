"""U366: reconcile the live master and sub-process schedules into the Epoch 5 state (0 tokens, deterministic).

Receipt: `.coord/master_schedule.json` kept `current_phase_id: U315` after U315 merged (PR #293), and 12 review
items from 2026-11-08 stayed BLOCKED although later releases resolved 11 of them, so every stall scan and HUD read a
stale head. The live files are runtime state, not tracked, and carry keys `MasterSchedule.from_dict()` rejects (legacy
phases lack title/mia_stage; extra top-level keys), so this module edits them as open dicts and keeps every unknown
key verbatim. Reconciliation metadata (fencing epoch, three-tier categories) lives in its own file,
`.coord/schedule_categories.json`, so a minimal `MasterSchedule.to_dict()` schedule still loads after a run.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schedule_planner import _atomic_write, _backup, _locked, _paths, _read_json

CARD = "U366"
# The epoch the director runs in since the U350 desk-director release (contract U366 1.A).
DEFAULT_EPOCH = 5
# The first card after the last release on main (U365 = PR #320, 0.6.22) whose phase is not done: the Epoch 5 head.
EPOCH5_HEAD = "U366"
# Contract U366 1.B: the 11 review items of 2026-11-08 that later releases resolved or replaced.
SUPERSEDED = {
    "U311-SOURCE-REVIEW-261108": "PR #293", "U312-SOURCE-REVIEW-261108": "PR #293",
    "U313-SOURCE-REVIEW-261108": "PR #293", "U314-SOURCE-REVIEW-261108": "PR #293",
    "U315-SOURCE-REVIEW-261108": "PR #293", "U316-SOURCE-REVIEW-261108": "PR #293",
    "U317-SOURCE-REVIEW-261108": "PR #293", "U318-SOURCE-REVIEW-261108": "PR #293",
    "U321-SOURCE-RELEASE-261108": "PR #295-#302", "U321-A4B-INDEPENDENT-261108": "Antigravity independent verifier",
    "U324-HELPER-QUALIFY-261108": "PR #287",
}
# A genuine hold: waits on Codex-exclusive evaluator work, so it is isolated, never closed.
HELD = {"U325": "HELD_FOR_CODEX"}
# Contract U366 2.B step 3, measured against origin/main 847ce93b on 2026-11-23 (U365 = PR #320 is the last merge).
CATEGORIES = {
    "LIVE": ["U350", "U346-MICRO", "U354-A", "U337-P1", "U364", "U365"],
    "STAGED_UNWIRED": ["U351", "U352", "U363"],
    "HELD_BLOCKED": ["U349-B", "U334", "U348", "U347", "U335-LIB", "U325"],
}
TERMINAL = ("DONE", "DONE_SCOPED", "DONE_ELSEWHERE", "DONE_SUPERSEDED", "RETIRED", "SUPERSEDED", "MERGED")


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _ts(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str) and value:
        text = value.replace("Z", "+00:00")
        if len(text) > 5 and text[-5] in "+-" and text[-3] != ":":
            text = text[:-2] + ":" + text[-2:]  # 2026-11-09T00:13:57+0900 -> +09:00
        try:
            stamp = datetime.fromisoformat(text)
        except ValueError:
            return None
        # A naive stamp is local time, as MasterTaskScheduler.save_schedule and schedule_planner._now_iso write it
        # (time.strftime) and schedule_planner._ts reads it; an aware stamp keeps its own offset.
        return stamp.timestamp()
    return None


def find_cycle(phases: list[Any]) -> list[str]:
    """The first `depends_on` cycle among the phases as [a, b, ..., a], or [] when the graph is a DAG."""
    graph: dict[str, list[str]] = {}
    for phase in phases:
        if isinstance(phase, dict) and isinstance(phase.get("phase_id"), str):
            deps = phase.get("depends_on")
            graph[phase["phase_id"]] = [d for d in deps if isinstance(d, str)] if isinstance(deps, list) else []
    color: dict[str, int] = {}
    for start in graph:
        if color.get(start):
            continue
        stack: list[tuple[str, int]] = [(start, 0)]
        path: list[str] = []
        while stack:
            node, index = stack.pop()
            if index == 0:
                color[node] = 1
                path.append(node)
            deps = [d for d in graph.get(node, []) if d in graph]
            if index < len(deps):
                stack.append((node, index + 1))
                nxt = deps[index]
                if color.get(nxt) == 1:
                    return path[path.index(nxt):] + [nxt]
                if not color.get(nxt):
                    stack.append((nxt, 0))
            else:
                color[node] = 2
                path.pop()
    return []


def _plan(master: dict[str, Any], stamp: str) -> tuple[list[dict[str, Any]], str | None]:
    """Phase changes to make (applied in place) and the new current_phase_id (None: keep)."""
    changes: list[dict[str, Any]] = []
    phases = [p for p in master.get("phases", []) if isinstance(p, dict)]
    for phase in phases:
        pid = phase.get("phase_id")
        if phase.get("state") != "BLOCKED":
            continue
        if pid in SUPERSEDED:
            to, note = "DONE_SUPERSEDED", f"Closed as superseded by {SUPERSEDED[pid]} on main"
        elif pid in HELD:
            to, note = HELD[pid], "Genuine hold isolated; it blocks no other card"
        else:
            continue
        changes.append({"phase_id": pid, "from": "BLOCKED", "to": to})
        phase["state"] = to
        phase["updated_at"] = stamp
        evidence = phase.get("evidence") if isinstance(phase.get("evidence"), dict) else {}
        evidence["u366_reconcile"] = {"from": "BLOCKED", "note": note, "at": stamp}
        phase["evidence"] = evidence
    by_id = {p.get("phase_id"): p for p in phases}
    current = by_id.get(master.get("current_phase_id"))
    head = None
    if master.get("current_phase_id") != EPOCH5_HEAD and (current is None or current.get("state") in TERMINAL):
        head = EPOCH5_HEAD
        if EPOCH5_HEAD not in by_id:
            master.setdefault("phases", []).append({
                "phase_id": EPOCH5_HEAD, "title": "Schedule reconciliation into the Epoch 5 state",
                "owner_tool": "claude", "mia_stage": "Step 9. Implementation", "depends_on": [], "state": "ACTIVE",
                "allowed_files": [], "acceptance_cmd": "", "evidence": {}, "blocker_reason": "", "updated_at": stamp})
    return changes, head


def reconcile_master_schedule(project_root: Path | str = ".", *, dry_run: bool = False, now: float | None = None,
                              fencing_epoch: int | None = None) -> dict[str, Any]:
    """Reconcile `.coord/master_schedule.json` and `.coord/sub_process_schedule.json` into the Epoch 5 state.

    Fail-closed answers (nothing written): MASTER_MISSING, CYCLE_DETECTED, STALE_EPOCH, STALE_STATE, WRITE_FAILED.
    A second run is a no-op (`changed: False`); the head-change notice is written once per (from, to, epoch)."""
    desk = Path(project_root).resolve()
    now = time.time() if now is None else float(now)
    master_path, sub_path = _paths(desk)
    cat_path = desk / ".coord" / "schedule_categories.json"
    notice_path = desk / ".coord" / "schedule_reconcile_notice.json"
    if dry_run:
        return _reconcile(desk, master_path, sub_path, cat_path, notice_path, now, fencing_epoch, dry_run=True)
    with _locked(desk):
        return _reconcile(desk, master_path, sub_path, cat_path, notice_path, now, fencing_epoch, dry_run=False)


def _reconcile(desk: Path, master_path: Path, sub_path: Path, cat_path: Path, notice_path: Path, now: float,
               fencing_epoch: int | None, *, dry_run: bool) -> dict[str, Any]:
    master = _read_json(master_path)
    if not isinstance(master.get("phases"), list):
        return {"ok": False, "reason": "MASTER_MISSING", "path": str(master_path)}
    cycle = find_cycle(master["phases"])
    if cycle:
        return {"ok": False, "reason": "CYCLE_DETECTED", "cycle": cycle}
    prior = _read_json(cat_path)
    stored = max(int(prior.get("fencing_epoch") or 0), int(master.get("fencing_epoch") or 0))
    epoch = max(DEFAULT_EPOCH, stored) if fencing_epoch is None else int(fencing_epoch)
    if epoch < stored:
        return {"ok": False, "reason": "STALE_EPOCH", "fencing_epoch": epoch, "stored_epoch": stored}
    last = max(_ts(prior.get("updated_at")) or 0.0, _ts(master.get("updated_at")) or 0.0)
    if now < last:
        return {"ok": False, "reason": "STALE_STATE", "now": _iso(now), "stored_updated_at": _iso(last)}
    stamp = _iso(now)
    old_head = master.get("current_phase_id")
    changes, head = _plan(master, stamp)
    categories = {tier: list(cards) for tier, cards in CATEGORIES.items()}
    for phase in master["phases"]:
        pid = phase.get("phase_id") if isinstance(phase, dict) else None
        if isinstance(pid, str) and pid.strip() and str(phase.get("state", "")).startswith("HELD") \
                and pid not in categories["HELD_BLOCKED"]:
            categories["HELD_BLOCKED"].append(pid)
    held = set(categories["HELD_BLOCKED"])
    for tier in ("LIVE", "STAGED_UNWIRED"):  # a held card is in one tier only, so it never reads as active
        categories[tier] = [c for c in categories[tier] if c not in held]
    new_head = head or old_head
    failover = master.get("failover_state")
    report: dict[str, Any] = {
        "ok": True, "card": CARD, "dry_run": dry_run, "fencing_epoch": epoch, "changes": changes,
        "current_phase_id": {"from": old_head, "to": new_head}, "categories": categories,
        "acting_conductor": master.get("acting_conductor",
                                       failover.get("mode") if isinstance(failover, dict) else None),
        "changed": bool(changes or head), "notified": False}
    lead = [new_head] if isinstance(new_head, str) and new_head and new_head not in held else []
    active = lead + [c for c in categories["STAGED_UNWIRED"] if c != new_head and c not in held]
    report["active_cards"] = active
    if dry_run:
        return report
    sub = _read_json(sub_path) if sub_path.is_file() else None
    cat_doc = {"schema": "uaos-schedule-categories-v1", "card": CARD, "fencing_epoch": epoch, "updated_at": stamp,
               "current_phase_id": new_head, "categories": categories}
    for key, value in prior.items():
        cat_doc.setdefault(key, value)
    notice_key = f"{old_head}->{new_head}@{epoch}"
    notify = head is not None and _read_json(notice_path).get("key") != notice_key
    try:
        if report["changed"]:
            _backup(desk, master_path)
            master["current_phase_id"] = new_head
            master["updated_at"] = stamp
            _atomic_write(master_path, master)
        if isinstance(sub, dict) and sub.get("active_cards") != active:
            _backup(desk, sub_path)
            sub["active_cards"] = active
            sub["updated_at"] = stamp
            _atomic_write(sub_path, sub)
        if any(prior.get(key) != cat_doc[key] for key in ("fencing_epoch", "current_phase_id", "categories")):
            _atomic_write(cat_path, cat_doc)
        if notify:
            _atomic_write(notice_path, {"key": notice_key, "from": old_head, "to": new_head, "fencing_epoch": epoch,
                                        "at": stamp, "card": CARD})
    except OSError as exc:
        for tmp in desk.joinpath(".coord").glob(".*.tmp"):
            try:
                tmp.unlink()
            except OSError:
                pass
        return {"ok": False, "reason": "WRITE_FAILED", "error": f"{type(exc).__name__}: {exc}"}
    report["notified"] = notify
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m v7_harness.coord.schedule_reconcile",
                                     description="U366: reconcile the master/sub schedules into the Epoch 5 state.")
    parser.add_argument("--project", default=".")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--fencing-epoch", type=int, default=None)
    args = parser.parse_args(argv)
    result = reconcile_master_schedule(args.project, dry_run=args.dry_run, fencing_epoch=args.fencing_epoch)
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
