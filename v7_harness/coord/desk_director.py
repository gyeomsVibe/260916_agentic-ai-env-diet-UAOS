"""U350 desk director: top-level director state under Charter Article 18 (federated hierarchical control plane).

State lives in `.coord/presence/director_state.json`: one PRIMARY_DIRECTOR (★), Director Aides (`보좌-`/`AS-` titles)
that watch non-critical work with authority 0, and subcommanders (●) that act only inside their own tool domain.
Upward rollups are capped at 15 lines. `desk_router` still owns card decomposition and window launch.

C27: an assistant title can never be PRIMARY_DIRECTOR; its authority is 0 in every role.
C28: stale cleanup refuses while a live `.work/QUIET_LOCK` exists and fails closed if the backup copy fails.
C29: an aide launch carries UAOS_WORKER=1, max_turns <= 6, no paid 429 retry loop, cost UNMEASURED.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from .desk_router import _Lock

STATE_REL = ".coord/presence/director_state.json"
PRIMARY, AIDE, SUBCOMMANDER = "PRIMARY_DIRECTOR", "DIRECTOR_AIDE", "SUBCOMMANDER"
ASSISTANT_TITLE_RE = re.compile(r"(?:보좌|AS)-")
ROLLUP_MAX_LINES = 15  # Article 18: an upward summary must fit one screen of the primary desk
QUIET_LOCK_MAX_AGE_S = 3600.0  # same bound agy_moderator uses: an older QUIET_LOCK is stale
AIDE_MAX_TURNS = 6  # C29 Tier 0.5 recursion barrier
_AUTHORITY = {PRIMARY: 2, SUBCOMMANDER: 1, AIDE: 0}


def is_assistant_title(title: str) -> bool:
    """C27 match: the literal regex anywhere in the title. A `CLASS-` false positive only loses authority, which
    fails closed; narrowing the match could let an assistant through."""
    return bool(ASSISTANT_TITLE_RE.search(title or ""))


def authority_of(title: str, *, role: str) -> int:
    return 0 if is_assistant_title(title) else _AUTHORITY.get(role, 0)


def can_act(*, actor_tool: str, role: str, target_domain: str) -> bool:
    """Article 18 domain isolation: primary acts anywhere, a subcommander only in its own tool, an aide never."""
    if role == PRIMARY:
        return True
    return role == SUBCOMMANDER and actor_tool == target_domain


def rollup_summary(lines: list[str]) -> str:
    """At most ROLLUP_MAX_LINES lines; overflow keeps the first lines and ends with a `(+N more)` marker."""
    flat = [part for line in lines for part in str(line).splitlines()]
    if len(flat) <= ROLLUP_MAX_LINES:
        return "\n".join(flat)
    keep = ROLLUP_MAX_LINES - 1
    return "\n".join(flat[:keep] + [f"... (+{len(flat) - keep} more)"])


def load_state(project: Path) -> dict[str, Any]:
    path = Path(project) / STATE_REL
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    doc = doc if isinstance(doc, dict) else {}
    doc.setdefault("primary", None)
    doc.setdefault("aides", {})
    return doc


def _save_state(project: Path, doc: dict[str, Any]) -> None:
    path = Path(project) / STATE_REL
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _lock(project: Path) -> _Lock:
    folder = Path(project) / ".coord" / "presence"
    folder.mkdir(parents=True, exist_ok=True)
    return _Lock(folder / ".director_state.lock")


def claim_primary(project: Path, *, tool: str, title: str, now: float | None = None) -> dict[str, Any]:
    """Set PRIMARY_DIRECTOR. An assistant title is refused before any write (C27)."""
    if is_assistant_title(title):
        return {"ok": False, "reason": "ASSISTANT_TITLE", "title": title}
    with _lock(project):
        doc = load_state(project)
        doc["primary"] = {"tool": tool, "title": title, "role": PRIMARY,
                          "authority": authority_of(title, role=PRIMARY), "at": time.time() if now is None else now}
        _save_state(project, doc)
    return {"ok": True, "primary": doc["primary"]}


def register_aide(project: Path, *, title: str, tool: str, now: float | None = None) -> dict[str, Any]:
    """Record a Director Aide. Only assistant titles qualify, and the aide's authority is stored as 0."""
    if not is_assistant_title(title):
        return {"ok": False, "reason": "NOT_ASSISTANT_TITLE", "title": title}
    with _lock(project):
        doc = load_state(project)
        doc["aides"][title] = {"tool": tool, "role": AIDE, "authority": 0, "at": time.time() if now is None else now}
        _save_state(project, doc)
    return {"ok": True, "aide": doc["aides"][title]}


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":  # os.kill(pid, 0) on Windows sends CTRL_C_EVENT, so query the process instead
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def quiet_lock_live(project: Path, *, now: float | None = None) -> bool:
    """C28: `.work/QUIET_LOCK` is live when its PID runs and it is at most QUIET_LOCK_MAX_AGE_S old."""
    path = Path(project) / ".work" / "QUIET_LOCK"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return path.is_file()  # an unreadable lock that exists is treated as live: fail closed
    pid = doc.get("pid") if isinstance(doc, dict) else None
    started = doc.get("started_at") if isinstance(doc, dict) else None
    if not isinstance(pid, int) or isinstance(pid, bool) or not isinstance(started, (int, float)):
        return True  # unknown shape: fail closed rather than clean under someone's quiet window
    age = (time.time() if now is None else now) - float(started)
    return age <= QUIET_LOCK_MAX_AGE_S and _pid_alive(pid)


def cleanup_stale(project: Path, *, max_age_s: float, now: float | None = None, date: str = "") -> dict[str, Any]:
    """Drop aides older than `max_age_s`. Refuses under a live QUIET_LOCK; backs up first and fails closed (C28)."""
    moment = time.time() if now is None else now
    if quiet_lock_live(project, now=moment):
        return {"ok": False, "reason": "QUIET_LOCK_LIVE", "removed": []}
    with _lock(project):
        doc = load_state(project)
        stale = sorted(t for t, a in doc["aides"].items() if moment - float(a.get("at", 0)) > max_age_s)
        if not stale:
            return {"ok": True, "removed": []}
        backup = Path(project) / ".work" / f"backup_{date or time.strftime('%y%m%d', time.localtime(moment))}"
        try:
            backup.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(project) / STATE_REL, backup / "director_state.json")
        except OSError as exc:
            return {"ok": False, "reason": "BACKUP_FAILED", "error": str(exc), "removed": []}
        for title in stale:
            del doc["aides"][title]
        _save_state(project, doc)
    return {"ok": True, "removed": stale, "backup": str(backup)}


def aide_launch_spec(*, max_turns: int = AIDE_MAX_TURNS) -> dict[str, Any]:
    """C29 launch contract for a Director Aide worker. Over-cap turns raise instead of being clamped silently."""
    if not 1 <= max_turns <= AIDE_MAX_TURNS:
        raise ValueError(f"max_turns must be 1..{AIDE_MAX_TURNS}, got {max_turns}")
    return {"env": {"UAOS_WORKER": "1"}, "max_turns": max_turns, "retry_on_429": False,
            "on_429": "FALLBACK_TIER_0A", "cost": "UNMEASURED"}


def on_rate_limit(status: int, *, attempt: int) -> dict[str, Any]:
    """C29: a 429 falls back to Tier 0-A at once on every attempt; there is no paid retry loop."""
    del attempt  # the decision must not depend on how many times we were limited
    if status == 429:
        return {"action": "FALLBACK_TIER_0A", "retry": False, "cost": "UNMEASURED"}
    return {"action": "CONTINUE", "retry": False, "cost": "UNMEASURED"}
