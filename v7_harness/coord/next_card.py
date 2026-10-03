"""U146-A: a deterministic next-card source, so the three tools chain card to card without a user prompt.

Receipt (2026-10-04): 윤겸스 had to prompt between every U141-A step. `next_step` reads only the master schedule and
names the tool's next card. It makes no network or paid call and writes only a claim file when asked to claim.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

# A dependency in one of these states lets its successor start. REVIEW waits only for a verdict, so a successor may
# stack on its branch (S3).
SATISFIED = ("DONE", "REVIEW")
# ACTIVE is in flight, owned by a running session, so it is never a candidate.
CANDIDATE = ("READY", "PLANNED")
# R4: one rejected base reworks every stacked child; 3 matches the three-failure stop rule.
MAX_REVIEW_STACK = 3


def coord_root(project: Path) -> Path:
    """R5: all worktrees agree on one schedule, kept in the main checkout (the git common dir's parent)."""
    try:
        done = subprocess.run(["git", "-C", str(project), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                              capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return Path(project)
    if done.returncode != 0 or not done.stdout.strip():
        return Path(project)
    return Path(done.stdout.strip()).parent


def schedule_path(project: Path) -> Path:
    return coord_root(project) / ".coord" / "master_schedule.json"


def _review_depth(pid: str, by_id: dict[str, dict], seen: frozenset = frozenset()) -> int:
    """The longest chain of REVIEW phases reachable from `pid` through depends_on (a cycle stops the walk)."""
    best = 0
    for dep in by_id.get(pid, {}).get("depends_on") or []:
        node = by_id.get(dep)
        if node is None or node.get("state") != "REVIEW" or dep in seen:
            continue
        best = max(best, 1 + _review_depth(dep, by_id, seen | {pid}))
    return best


def _claim(claims: Path, card: str, tool: str, pid: int) -> bool:
    """R3: take `card` for this process. False only when a different live process holds it."""
    from v7_harness.coord.watch import process_identity

    path = claims / f"{card}.json"
    record = {"pid": pid, "process_created": process_identity(pid), "tool": tool, "at": time.time()}
    claims.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(record, f)
        return True
    try:
        held = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        held = None
    if isinstance(held, dict):
        if held.get("pid") == pid:
            return True
        holder = held.get("pid")
        created = held.get("process_created")
        if isinstance(holder, int) and created is not None and process_identity(holder) == created:
            return False
    # A dead or unreadable claim is replaced atomically, then re-read so a concurrent replacer wins at most once.
    tmp = path.with_name(f"{path.name}.{pid}.tmp")
    tmp.write_text(json.dumps(record), encoding="utf-8")
    os.replace(tmp, path)
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("pid") == pid
    except (OSError, ValueError):
        return False


def next_step(project: Path, tool: str, claim: bool = False, pid: int | None = None) -> dict[str, Any]:
    project = Path(project)
    path = schedule_path(project)
    if not path.is_file():
        return {"state": "DONE", "reason": "no schedule"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        phases = data["phases"]
        if not isinstance(phases, list) or not all(isinstance(p, dict) for p in phases):
            raise ValueError("phases is not a list of objects")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"state": "WAIT", "reason": f"schedule unreadable: {exc}"}
    by_id = {str(p.get("phase_id")): p for p in phases}
    state_of = {pid_: p.get("state") for pid_, p in by_id.items()}
    candidates, stacked = [], []
    for p in phases:
        if p.get("state") not in CANDIDATE:
            continue
        if not all(state_of.get(d) in SATISFIED for d in p.get("depends_on") or []):
            continue
        if _review_depth(str(p.get("phase_id")), by_id) >= MAX_REVIEW_STACK:
            stacked.append(p)
            continue
        candidates.append(p)
    own = [p for p in candidates if p.get("owner_tool") in (tool, "all")]
    claimed_out = False
    for p in own:
        card = str(p.get("phase_id"))
        if claim:
            # The claim lives beside the schedule, so every worktree sees the same claims (R5).
            claims = path.parent / "next" / "claims"
            if not _claim(claims, card, tool, os.getpid() if pid is None else pid):
                claimed_out = True
                continue
            return {"state": "NEXT", "card": card, "owner": p.get("owner_tool"), "claimed": True}
        return {"state": "NEXT", "card": card, "owner": p.get("owner_tool")}
    others = [p for p in candidates if p.get("owner_tool") not in (tool, "all")]
    if others:
        return {"state": "HANDOFF", "card": str(others[0].get("phase_id")), "owner": others[0].get("owner_tool")}
    remaining = [p for p in phases if p.get("state") != "DONE"]
    open_cards = [str(p.get("phase_id")) for p in remaining if p.get("state") != "HUMAN"]
    if stacked:
        return {"state": "WAIT", "reason": "review stack at MAX_REVIEW_STACK; waiting for codex verdict",
                "cards": open_cards}
    if claimed_out:
        return {"state": "WAIT", "reason": "own cards are claimed by live sessions", "cards": open_cards}
    if not remaining:
        return {"state": "DONE"}
    if not open_cards:
        return {"state": "HUMAN", "items": [p.get("human") or str(p.get("phase_id")) for p in remaining]}
    return {"state": "WAIT", "cards": open_cards}
