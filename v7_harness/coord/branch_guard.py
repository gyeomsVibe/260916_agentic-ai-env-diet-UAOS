"""U295: one writer per PR branch, a frozen head while a verdict is open, full heads in verdicts, a closed schedule.

Receipts (.coord/notes/BOTTLENECK_RECEIPTS_261102.md, 2026-11-02): two tools wrote the same PR branch (B2), a push
landed while its review ran so the verdict went stale (B4), a short sha in a verdict letter was refused at merge (B3),
and merged cards stayed READY so the sentinel kept waking a LIMITED owner (B8).

Stage 0: a lease names one holder with a duration and is taken over only after it expires
(https://kubernetes.io/docs/concepts/architecture/leases/); GitHub dismisses an approval once new commits change the
diff (https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches);
`git rev-parse --verify <rev>^{commit}` resolves an abbreviated sha only when it is unambiguous
(https://git-scm.com/docs/git-rev-parse); `os.replace` is an atomic rename (https://docs.python.org/3/library/os.html#os.replace).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

TOOLS = ("codex", "claude", "antigravity")
TOOL_ALIAS = {"agy": "antigravity"}
# Four hours: longer than one card's implement-and-test run (U294: ~2 h) and shorter than a 5 h usage window, so a
# holder that hit its limit frees the branch before the window resets. A holder renews by acquiring again.
LEASE_TTL_S = 4 * 3600.0
LEASE_DIR = Path(".coord") / "leases"
FREEZE_LEDGER = Path(".coord") / "verdict_freeze.jsonl"
SCHEDULE = Path(".coord") / "master_schedule.json"
FULL_SHA_RE = re.compile(r"\b[0-9a-f]{40}\b")
# Seven hex digits is git's default abbreviation; fewer is ambiguous in any real repository.
SHORT_SHA_RE = re.compile(r"\b[0-9a-f]{7,39}\b")
CARD_RE = re.compile(r"\bU\d{1,4}\b")
GIT_S = 15


class LeaseHeld(RuntimeError):
    pass


def _tool(name: str) -> str:
    value = TOOL_ALIAS.get(str(name).strip().lower(), str(name).strip().lower())
    if value not in TOOLS:
        raise ValueError(f"tool must be one of {TOOLS}")
    return value


def _desk(project: Path) -> Path:
    from .hook_context import shared_desk  # U59: a linked worktree shares the main checkout's desk

    return Path(shared_desk(Path(project)))


def _safe(branch: str) -> str:
    if not branch or ".." in branch or branch.startswith("/"):
        raise ValueError("branch must be a relative ref name")
    return re.sub(r"[^A-Za-z0-9_.-]", "__", branch)


def _write_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def lease_path(project: Path, branch: str) -> Path:
    return _desk(project) / LEASE_DIR / f"{_safe(branch)}.json"


def holder(project: Path, branch: str, *, now: float | None = None) -> dict[str, Any] | None:
    """The live lease on `branch`, or None when there is none or it expired."""
    row = _read(lease_path(project, branch))
    moment = time.time() if now is None else now
    if row is None or not isinstance(row.get("expires_at"), (int, float)) or row["expires_at"] <= moment:
        return None
    return row


def acquire(project: Path, branch: str, *, tool: str, session: str = "", head: str = "",
            ttl: float = LEASE_TTL_S, now: float | None = None) -> dict[str, Any]:
    """Take or renew the lease. A live lease of another tool or session raises LeaseHeld (one writer per branch)."""
    from .stream import _exclusive

    who = _tool(tool)
    moment = time.time() if now is None else now
    path = lease_path(project, branch)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive(path.with_suffix(".lock")):
        live = holder(project, branch, now=moment)
        if live is not None and (live.get("tool"), live.get("session", "")) != (who, session):
            raise LeaseHeld(f"LEASE_HELD: {branch} is held by {live.get('tool')} session "
                            f"{live.get('session') or '-'} until {int(live['expires_at'])}")
        row = {"branch": branch, "tool": who, "session": session, "head": head,
               "acquired_at": (live or {}).get("acquired_at", moment), "renewed_at": moment,
               "expires_at": moment + float(ttl)}
        _write_atomic(path, row)
    return row


def release(project: Path, branch: str, *, tool: str, session: str = "") -> bool:
    """Only the holder releases; the file stays as an expired record (nothing is deleted)."""
    from .stream import _exclusive

    who = _tool(tool)
    path = lease_path(project, branch)
    with _exclusive(path.with_suffix(".lock")):
        live = holder(project, branch)
        if live is None or (live.get("tool"), live.get("session", "")) != (who, session):
            return False
        live["expires_at"] = time.time()
        live["released"] = True
        _write_atomic(path, live)
    return True


def leases(project: Path, *, now: float | None = None) -> list[dict[str, Any]]:
    """Live leases, for briefings: the holder comes from this record, not from a model's reply (B1)."""
    folder = _desk(project) / LEASE_DIR
    moment = time.time() if now is None else now
    rows = [_read(path) for path in sorted(folder.glob("*.json"))] if folder.is_dir() else []
    return [row for row in rows if row and isinstance(row.get("expires_at"), (int, float))
            and row["expires_at"] > moment]


def lease_check(project: Path, branch: str, tool: str | None, session: str = "") -> dict[str, str] | None:
    """None when the push may go on; a DENY row when another writer holds the branch or the pusher is unnamed."""
    live = holder(project, branch)
    if live is None:
        return None
    if not tool:
        return {"decision": "DENY", "reason": f"LEASE_HELD: {branch} is leased to {live.get('tool')}; pass --tool"}
    # Another tool never writes; within one tool a named session must match a named holder session.
    if _tool(tool) != live.get("tool") or (session and live.get("session") and session != live.get("session")):
        return {"decision": "DENY", "reason": f"LEASE_HELD: {branch} is leased to {live.get('tool')} session "
                                              f"{live.get('session') or '-'}"}
    return None


GIT_READS = ("rev-parse",)  # the only git command this module runs: a read-only ref lookup
GIT_FLAGS = ("--verify", "-q")
REV_RE = re.compile(r"^[A-Za-z0-9_./^{}-]+$")


def _check_git_args(args: tuple[str, ...]) -> None:
    """A caller's branch or sha is one rev operand: never a flag (`-x` would be option injection) or a second command."""
    if not args or args[0] not in GIT_READS:
        raise ValueError("only git rev-parse is run here")
    for arg in args[1:]:
        if arg not in GIT_FLAGS and (arg.startswith("-") or not REV_RE.match(arg)):
            raise ValueError(f"unsafe git operand {arg!r}")


def _git(project: Path, *args: str) -> str:
    try:
        _check_git_args(args)
    except ValueError:
        return ""
    try:
        done = subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True, timeout=GIT_S)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def frozen_requests(project: Path, branch: str) -> list[dict[str, Any]]:
    """Open verdict requests that pin the branch's pushed head (origin/<branch>)."""
    from . import requests

    remote = _git(project, "rev-parse", "--verify", "-q", f"refs/remotes/origin/{branch}")
    if not FULL_SHA_RE.fullmatch(remote):
        return []
    return [row for row in requests._rows(Path(project))
            if row.get("state") in requests.WAITING_STATES and str(row.get("head", "")).lower() == remote]


def freeze_check(project: Path, branch: str, *, supersede: bool = False, actor: str = "",
                 now: float | None = None) -> dict[str, Any] | None:
    """B4: refuse a push that moves a head an open verdict request pins. `supersede` lets it through and records
    each request as STALE in the freeze ledger, returned under `stale` so the caller wakes the requester once."""
    local = _git(project, "rev-parse", "--verify", "-q", f"refs/heads/{branch}")
    pinned = frozen_requests(project, branch)
    if not pinned or (local and local == str(pinned[0].get("head", "")).lower()):
        return None
    ids = [str(row.get("request_id", "")) for row in pinned]
    if not supersede:
        return {"decision": "DENY", "reason": f"VERDICT_FREEZE: {branch} head {pinned[0].get('head')} is under open "
                                              f"verdict request(s) {', '.join(ids)}; wait for the verdict or pass "
                                              "--supersede (the requester is told the verdict is stale)"}
    moment = time.time() if now is None else now
    stale = [{"ts": moment, "branch": branch, "request_id": row.get("request_id"), "requester": row.get("requester"),
              "head": row.get("head"), "new_head": local, "actor": actor, "state": "STALE"} for row in pinned]
    path = _desk(project) / FREEZE_LEDGER
    path.parent.mkdir(parents=True, exist_ok=True)
    from .stream import _exclusive

    with _exclusive(path.with_suffix(".lock")):
        with path.open("a", encoding="utf-8") as handle:
            for row in stale:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return {"decision": "ALLOW", "reason": "VERDICT_FREEZE superseded", "stale": stale}


def wake_stale(project: Path, row: dict[str, Any]) -> str:
    """Wake the requester of a superseded verdict request once per (request, new head); never silently stale."""
    from .mailbox import Mailbox

    requester = TOOL_ALIAS.get(str(row.get("requester", "")), str(row.get("requester", "")))
    if requester not in TOOLS:
        return ""
    root = _desk(project) / ".coord" / "mailbox"
    root.mkdir(parents=True, exist_ok=True)
    box = Mailbox(root)
    key = f"{row.get('request_id')}|{row.get('new_head')}"
    message_id = "verdict_stale_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    if box.has_message(message_id):
        return ""
    delta = (f"VERDICT STALE (U295): {row.get('branch')} moved {str(row.get('head'))[:12]} -> "
             f"{str(row.get('new_head'))[:12]} by {row.get('actor') or 'unknown'}; request {row.get('request_id')} "
             "judges an old head: re-request on the new head")
    box.publish(message_id=message_id, payload={
        "recipient": requester, "requested_target": requester, "wake_class": "ACTIONABLE", "delta": delta[:200],
        "wake_reason": delta, "actor": "sentinel", "message": delta})
    return message_id


def embed_full_head(project: Path, message: str) -> str:
    """B3: a verdict letter names the full 40-char head. A lone short sha that git resolves unambiguously gets the
    full sha appended as `head=<sha>`; a message that already has one, or none, or two different ones, is unchanged."""
    if FULL_SHA_RE.search(message or ""):
        return message
    shorts = {m.group(0) for m in SHORT_SHA_RE.finditer(message or "") if not m.group(0).isdigit()}
    if len(shorts) != 1:
        return message
    full = _git(project, "rev-parse", "--verify", "-q", f"{shorts.pop()}^{{commit}}")
    return f"{message} head={full}" if FULL_SHA_RE.fullmatch(full) else message


def close_merged_phases(project: Path, *, title: str, pr: int, head: str, now: float | None = None) -> list[str]:
    """B8: after a merge, mark DONE the schedule phases whose id is a card named in the PR title. Atomic replace."""
    from .next_card import coord_root
    from .stream import _exclusive

    cards = set(CARD_RE.findall(title or ""))
    path = coord_root(Path(project)) / SCHEDULE
    if not cards or not path.is_file():
        return []
    closed: list[str] = []
    with _exclusive(path.with_suffix(".lock")):
        schedule = _read(path)
        if schedule is None or not isinstance(schedule.get("phases"), list):
            return []
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(time.time() if now is None else now))
        for phase in schedule["phases"]:
            if isinstance(phase, dict) and phase.get("phase_id") in cards \
                    and not str(phase.get("state", "")).startswith("DONE"):
                phase["state"] = "DONE"
                phase["note"] = f"merged PR #{pr} at {head[:12]} (U295 auto-close)"
                closed.append(str(phase["phase_id"]))
        if closed:
            schedule["updated_at"] = stamp
            _write_atomic(path, schedule)
    return closed


def wake_recipient(owner: str, desk: dict[str, dict[str, Any]]) -> str | None:
    """B8: a wake goes to its owner unless the owner is LIMITED or ABSENT; then to the acting conductor, or nobody."""
    from ..budget_route import route_authority

    if (desk.get(owner) or {}).get("state") not in ("LIMITED", "ABSENT"):
        return owner
    conductor = route_authority(*((desk.get(t) or {}).get("state", "UNKNOWN") for t in TOOLS))
    return conductor if conductor in TOOLS and conductor != owner else None
