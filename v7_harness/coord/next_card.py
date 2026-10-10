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
# U146a-R: a claim belongs to a session id and lapses after this long without renewal. 7200 s is the longest background
# `coord watch` (7,200,000 ms cap); a session silent for longer is gone, so its card may be taken.
CLAIM_TTL_S = 7200


def coord_root(project: Path) -> Path:
    """R5: all worktrees agree on one schedule, kept in the main checkout (the git common dir's parent)."""
    project = Path(project)
    # U182: a worktree's top folder always holds `.git`; a folder that has its own .coord but no `.git` is a project
    # nested inside a larger repository (Lotto receipt 2026-10-11) and keeps its own schedule and mailbox.
    if (project / ".coord").is_dir() and not (project / ".git").exists():
        return project
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


def _claim(claims: Path, card: str, tool: str, session: str, now: float) -> bool:
    """U146a-R: take `card` for this session. A hook process exits right after it claims, so a PID never owned
    anything (PR112 counterexample); the session id does, until CLAIM_TTL_S passes without renewal.

    U146a-R2: read, decide and write happen under one OS file lock (Codex U146-R4: replace plus re-read gave two
    parallel winners). False when another session holds a live claim, or when the claim cannot be decided safely (lock
    busy past its timeout, the file held open outside the lock): fail closed, a later turn or another card goes on.
    """
    from v7_harness.coord.stream import StreamBusy, _exclusive

    path = claims / f"{card}.json"
    record = {"session": session, "tool": tool, "at": now}
    claims.mkdir(parents=True, exist_ok=True)
    try:
        with _exclusive(claims / ".lock"):
            try:
                held = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                held = None  # missing, truncated by a dead writer, or still empty: nobody owns it
            if isinstance(held, dict) and held.get("session") != session:
                holder, at = held.get("session"), held.get("at")
                if isinstance(holder, str) and holder and isinstance(at, (int, float)) and now - at < CLAIM_TTL_S:
                    return False
            # The own session renews; a lapsed, PID-only or unreadable claim is replaced. Readers never see a half
            # record because the write lands by replace.
            tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(record), encoding="utf-8")
            try:
                os.replace(tmp, path)
            except OSError:
                tmp.unlink(missing_ok=True)  # Windows: another handle holds the claim file open
                return False
            return True
    except StreamBusy:
        return False


def next_step(project: Path, tool: str, claim: bool = False, session: str | None = None,
              now: float | None = None) -> dict[str, Any]:
    project = Path(project)
    path = schedule_path(project)
    if not path.is_file():
        if (path.parent / "PLAN.md").is_file():  # U180C: a plan without a machine schedule is unscheduled work
            return {"state": "WAIT", "code": "SCHEDULE_MISSING", "reason": "coordinated project has no schedule",
                    "action": "register authorized work in .coord/master_schedule.json before stopping"}
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
            if not session:
                # U146a-R: PID-only ownership is refused; an unknown session claims nothing (a plain read still names it).
                return {"state": "WAIT", "reason": "a claim needs a session id (U146a-R)", "card": card}
            # The claim lives beside the schedule, so every worktree sees the same claims (R5).
            claims = path.parent / "next" / "claims"
            if not _claim(claims, card, tool, session, time.time() if now is None else now):
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
