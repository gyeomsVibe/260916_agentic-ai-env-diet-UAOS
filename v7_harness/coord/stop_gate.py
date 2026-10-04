"""U146-A: the end-of-turn gate and the push-grant check of the nonstop chain.

`gate` blocks a turn end once while the tool's own NEXT card is ready, then lets the stop through unless verified
progress happened (Antigravity audit relay_5d1e13d0 [HIGH]). `push_check` reads the user's standing push grant,
deny by default.

U146-B: the same gate is the Stop hook of Codex and Antigravity too (docs/75 §5), a LIMITED tool is not pushed into a
new card (R7), and a grant with `expires_at` stops counting once it passes.
"""

from __future__ import annotations

import datetime as _dt
import fnmatch
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from v7_harness import pilot_dirs
from v7_harness.coord import next_card

# Each block is a full-context paid turn, so one re-entry without progress, then fail closed (audit relay_5d1e13d0).
MAX_BLOCKS = 1
# Stage 0: Claude and Codex Stop hooks hold a turn with "block" (https://learn.chatgpt.com/docs/hooks); Antigravity's
# Stop hook re-enters its loop with "continue" (https://antigravity.google/docs/hooks).
HOLD_DECISION = {"claude": "block", "codex": "block", "antigravity": "continue"}
# R7: a tool whose desk says it has no budget left is not asked to start a new card.
NO_BUDGET_STATES = ("LIMITED",)


def hook_session(payload: Any) -> str | None:
    """The session that owns the claim: `session_id` (Claude, Codex) or `conversationId` (Antigravity)."""
    if not isinstance(payload, dict):
        return None
    for key in ("session_id", "conversationId"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:200]  # same bound as hook_context.hook_session
    return None


def should_gate(payload: Any) -> bool:
    """Antigravity reports `fullyIdle: false` while work is still pending; only a fully idle stop is held."""
    return not (isinstance(payload, dict) and payload.get("fullyIdle") is False)


def project_owns_gate(project: Path, tool: str) -> bool:
    """A project whose own Claude settings already run the gate (this repo since U146-A) keeps it; the global hook
    steps aside so one stop is gated once."""
    if tool != "claude":
        return False
    try:
        text = (Path(project) / ".claude" / "settings.json").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return "coord stop-gate" in text and "--from-hook" not in text


def progress_signature(project: Path) -> list:
    """Verified advancement only: a commit, a schedule status change, or a new pilot run.

    Ledger rows, results, `.coord/log` and `.coord/presence` are not progress: a pilot failing repeatedly writes them
    without advancing (the audit's spin case).
    """
    project = Path(project)
    try:
        done = subprocess.run(["git", "-C", str(project), "rev-parse", "HEAD"], capture_output=True, text=True,
                              timeout=10)
        head = done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else None
    except (OSError, subprocess.SubprocessError):
        head = None
    schedule = next_card.schedule_path(project)
    schedule_mtime = schedule.stat().st_mtime if schedule.is_file() else None
    # U146a-R: runs live in every pilot dir (pilot_dirs.discover: .coord/pilot, .coord, .work/<x>), of this worktree and
    # of the main checkout; one summary.json per run, so a missing dir simply adds nothing.
    roots = {Path(d).resolve() for base in (project, next_card.coord_root(project)) for d in pilot_dirs.discover(base)}
    mtimes = [s.stat().st_mtime for root in sorted(roots) for s in (root / "runs").glob("*/summary.json")]
    return [head, schedule_mtime, max(mtimes) if mtimes else None, len(mtimes)]


def _write_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def gate(project: Path, tool: str, session: str | None = None, now: float | None = None) -> dict[str, Any] | None:
    project = Path(project)
    if not session:
        return None  # U146a-R: no session id, no claim and no block (UNKNOWN is no ground for acting)
    from v7_harness.coord import presence

    if presence.read(project, tool, now=now).get("state") in NO_BUDGET_STATES:
        return None  # R7: no claim and no paid re-entry for a tool without budget
    step = next_card.next_step(project, tool, claim=True, session=session, now=now)
    if step.get("state") != "NEXT":
        return None
    card = step["card"]
    guard_path = project / ".coord" / "presence" / f"stop_gate_{tool}.json"
    try:
        guard = json.loads(guard_path.read_text(encoding="utf-8"))
        if not isinstance(guard, dict):
            guard = {}
    except (OSError, ValueError):
        guard = {}
    progress = progress_signature(project)
    blocks = guard.get("blocks") if isinstance(guard.get("blocks"), int) else 0
    if guard.get("card") != card or guard.get("progress") != progress:
        blocks = 0
    if blocks >= MAX_BLOCKS:
        log = project / ".coord" / "log" / "stop_gate.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        row = {"kind": "BLOCKED", "tool": tool, "card": card, "blocks": blocks,
               "at": time.time() if now is None else now}
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return None
    _write_atomic(guard_path, {"card": card, "blocks": blocks + 1, "progress": progress})
    return {"decision": HOLD_DECISION.get(tool, "block"),
            "reason": f"NEXT {card} (owner {step.get('owner')}) is ready: start it now; human-list items go in the "
                      "final batched report"}


def _expiry(value: Any) -> float | None:
    """Epoch seconds of `expires_at`, or None when doubtful: a bool, a naive time (no offset) or any other text."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    try:
        moment = _dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment.timestamp() if moment.tzinfo is not None else None


def push_check(project: Path, branch: str, force: bool = False) -> dict[str, str]:
    """R2 + U146a-R: ALLOW only a branch the grant on origin/main names. A working-tree edit or a local commit is
    agent-writable, so only the blob a human merged counts. Every missing or doubtful case is DENY."""
    root = next_card.coord_root(Path(project))
    try:
        done = subprocess.run(["git", "-C", str(root), "show", "refs/remotes/origin/main:.coord/grants/push.json"],
                              capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"decision": "DENY", "reason": f"git unavailable: {exc}"}
    if done.returncode != 0:
        return {"decision": "DENY", "reason": "no push grant committed on origin/main"}
    try:
        grant = json.loads(done.stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        return {"decision": "DENY", "reason": f"no readable push grant: {exc}"}
    if not isinstance(grant, dict) or grant.get("enabled") is not True:
        return {"decision": "DENY", "reason": "push grant not enabled"}
    if "expires_at" in grant:
        expires = _expiry(grant["expires_at"])
        if expires is None:
            return {"decision": "DENY", "reason": "push grant expires_at unreadable (ISO 8601 with offset, or epoch)"}
        if time.time() >= expires:
            return {"decision": "DENY", "reason": "push grant expired"}
    if force and grant.get("force") is not True:
        return {"decision": "DENY", "reason": "force push is never granted"}
    never = grant.get("never") if isinstance(grant.get("never"), list) else []
    if any(fnmatch.fnmatchcase(branch, str(pat)) for pat in never):
        return {"decision": "DENY", "reason": f"{branch} is in never"}
    branches = grant.get("branches") if isinstance(grant.get("branches"), list) else []
    if not any(fnmatch.fnmatchcase(branch, str(pat)) for pat in branches):
        return {"decision": "DENY", "reason": f"{branch} matches no granted pattern"}
    return {"decision": "ALLOW", "reason": f"{branch} matches the push grant"}
