"""U166: waiting is a failure. A step that waits too long on one tool or on the user is rerouted by agreement.

윤겸스 (2026-10-05): Claude ended a turn with "Codex will re-review when it returns" while Antigravity could act, and
listed merges as user work while Antigravity could merge. Every tool's per-prompt hook (`--delta`, all 3 tools) runs
`scan`: it finds the waits on disk (queued verdict requests, waiting master-schedule phases that are not on the
Safety human-only list), and once one is older than
MAX_WAIT_S it names the tools that can do the step instead. The tool whose hook ran records its agreement; when every
ACTIVE tool has agreed (absent tools excluded), the reroute is written into `.coord/master_schedule.json`: a waiting
phase is reassigned in place as READY to the first capable tool, a waiting letter gets a new READY phase. Only then is
the owner told to act. Peers learn of a stall and its votes in their own hook output, which is how a
notice counts as delivered in UAOS. No model is called: reading a few small files costs no paid tokens.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from .merge_route import MERGERS
from .presence import TOOLS

# Half the Claude main-session cache lifetime (1 h, global rules): a reroute starts before a resumed waiting session
# pays a full cache rebuild, and a normal review round trip (minutes) never trips it.
MAX_WAIT_S = 1800
# Who can do each kind of step, in order of preference. merge: 윤겸스's order (merge_route.MERGERS). verdict: Codex
# conducts, Antigravity is the independent judge when it is away. letter: any peer that can read and act on it.
# implement: Claude is the default implementer (global rules), then Antigravity, then Codex.
CAPABILITY = {
    "merge": MERGERS,
    "verdict": ("codex", "antigravity"),
    "implement": ("claude", "antigravity", "codex"),
}
WAIT_STATES = ("HUMAN", "REVIEW", "BLOCKED")
# How long an adoption notice stays visible after its wait is gone: the Claude/Codex usage window is 5 hours (global
# rules), so a tool that was paused by its limit still hears of the reroute at its first prompt back.
NOTICE_KEEP_S = 6 * 3600
# The Safety human-only list (global rules): a phase that names one of these stays with 윤겸스 and is never rerouted,
# even when it also says "merge" (Antigravity design audit relay_45a03503, defect 1). Matching is deliberately broad:
# a false hit only leaves a step with the user, a miss would hand a human decision to a tool.
HUMAN_ONLY_RE = re.compile(
    r"delet|deploy|publish|public post|store submission|spend|payment|billing|money|purchase|account|credential|"
    r"secret|password|permission|system setting|push|삭제|배포|게시|공개|지출|결제|구매|계정|자격|비밀|권한|시스템 설정|푸시",
    re.IGNORECASE)
STATE_DIR = Path(".coord") / "stall"
SCHEDULE = Path(".coord") / "master_schedule.json"
QUEUED = Path(".coord") / "mailbox" / "delivery" / "queued"


def _item_id(item: str) -> str:
    return "STALL-" + hashlib.sha256(item.encode("utf-8")).hexdigest()[:8]


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False, indent=2))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _letter_waits(project: Path) -> list[dict[str, Any]]:
    found = []
    root = project / QUEUED
    for target_dir in sorted(p for p in root.glob("*") if p.is_dir()):
        target = target_dir.name
        for letter in sorted(target_dir.glob("*.json")):
            try:
                payload = json.loads(letter.read_text(encoding="utf-8"))
                since = letter.stat().st_mtime
            except (OSError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            # Only a letter that asks for a verdict is a step someone waits on; a status note or ACK is not
            # (relay_45a03503, defect 1), and U120 already uses this token as the wake word.
            if "VERDICT_REQUESTED=YES" not in str(payload.get("message", "")):
                continue
            found.append({"item": f"letter:{target}:{letter.stem}", "kind": "verdict", "waiting_on": target,
                          "author": str(payload.get("actor", "")), "since": since, "pr": ""})
    return found


def _phase_waits(schedule: dict[str, Any]) -> list[dict[str, Any]]:
    found = []
    for phase in schedule.get("phases") or []:
        if not isinstance(phase, dict) or not phase.get("phase_id"):
            continue
        state, waiting_on = str(phase.get("state", "")), str(phase.get("waiting_on", ""))
        if state not in WAIT_STATES and not waiting_on:
            continue
        text = f"{phase['phase_id']} {phase.get('human', '')} {phase.get('note', '')}".lower()
        if state == "HUMAN" and HUMAN_ONLY_RE.search(text):
            continue
        if "merge" in text:
            kind = "merge"
        elif "verdict" in waiting_on.lower() or state == "REVIEW":
            kind = "verdict"
        else:
            kind = "implement"
        on = waiting_on.split("-")[0] if waiting_on else ("human" if state == "HUMAN" else "unknown")
        found.append({"item": f"phase:{phase['phase_id']}", "kind": kind, "waiting_on": on,
                      "author": str(phase.get("owner_tool", "")), "since": None, "pr": str(phase.get("pr", "")),
                      "declared": _declared(phase.get("waiting_since"))})
    return found


def _declared(value: Any) -> float | None:
    """A phase's own `waiting_since` (epoch seconds or ISO 8601), if it has one."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        from datetime import datetime

        try:
            return datetime.fromisoformat(value).timestamp()
        except ValueError:
            return None
    return None


def route(wait: dict[str, Any], desk: dict[str, dict[str, Any]]) -> list[str]:
    """Capable ACTIVE tools other than the one waited on; a verdict never goes to its own author."""
    out = []
    for tool in CAPABILITY[wait["kind"]]:
        if tool == wait["waiting_on"] or (desk.get(tool) or {}).get("state") != "ACTIVE":
            continue
        if wait["kind"] == "verdict" and tool == wait["author"]:
            continue
        out.append(tool)
    return out


def action(wait: dict[str, Any], owner: str) -> str:
    if wait["kind"] == "merge":
        pr = wait["pr"].lstrip("#") or "<pr>"
        return (f"uaos coord merge --pr {pr} --head <sha> --verdict <judge relay> "
                f"(merger order {'/'.join(MERGERS)})")
    if wait["kind"] == "verdict":
        return f"{owner} gives the independent verdict (pilot review/judge --reviewer {owner})"
    return f"{owner} takes the step"


def scan(project: Path, tool: str, *, now: float | None = None,
         desk: dict[str, dict[str, Any]] | None = None, max_wait_s: int = MAX_WAIT_S) -> dict[str, Any]:
    from .next_card import coord_root
    from .stream import _exclusive

    # One schedule and one stall state for every worktree, kept in the main checkout (U146-A R5).
    project = coord_root(Path(project))
    moment = time.time() if now is None else now
    if desk is None:
        from .presence import read_all

        desk = read_all(project, now=moment)
    present = sorted(t for t in TOOLS if (desk.get(t) or {}).get("state") == "ACTIVE")
    state_dir = project / STATE_DIR
    result: dict[str, Any] = {"stalled": [], "adopted": [], "blocked": [], "error": None}
    with _exclusive(state_dir / "stall.lock"):
        try:
            schedule = _read_json(project / SCHEDULE, {"phases": []})
            if not isinstance(schedule, dict):
                raise ValueError("schedule is not an object")
        except (OSError, ValueError) as exc:
            result["error"] = f"schedule {type(exc).__name__}"
            schedule = None
        seen = _read_json(state_dir / "seen.json", {})
        votes = _read_json(state_dir / "votes.json", {})
        adopted = _read_json(state_dir / "adopted.json", {})
        if not all(isinstance(x, dict) for x in (seen, votes, adopted)):
            result["error"] = "stall state corrupt"
            return result
        waits = _letter_waits(project) + (_phase_waits(schedule) if schedule is not None else [])
        live = {w["item"] for w in waits}
        seen = {k: v for k, v in seen.items() if k in live}
        # A phase has waited at least since the schedule file was last written: it was already in its waiting state
        # then, because the file has not changed since. So the first scan of an old wait sees its real age (Codex
        # judge U166-APPLY4, finding 1); a declared `waiting_since` is used when it is earlier still.
        try:
            written = (project / SCHEDULE).stat().st_mtime
        except OSError:
            written = moment
        for wait in waits:
            if wait["since"] is None:
                first = min(float(seen.get(wait["item"], moment)), written, wait.pop("declared", None) or moment)
                wait["since"] = seen[wait["item"]] = first
        changed_schedule = False
        for wait in waits:
            age = moment - float(wait["since"])
            done = adopted.get(wait["item"])
            # An adoption covers only the wait instance it was made for; a phase that waits again later is a new
            # instance with a new start and is rerouted again (Codex judge U166-APPLY4, finding 2).
            if age < max_wait_s or (isinstance(done, dict) and done.get("since") == wait["since"]):
                continue
            owners = route(wait, desk)
            entry = {"item": wait["item"], "kind": wait["kind"], "waiting_on": wait["waiting_on"],
                     "age_s": int(age), "route": owners}
            if not owners:
                result["blocked"].append(entry)
                continue
            # A vote holds only for this wait instance and this owner, and only while fresh: a vote cast for an
            # earlier instance, another route, or older than the wait limit is dropped (relay_45a03503, defect 4).
            # Absent tools are not counted because presence expires a silent heartbeat to UNKNOWN (presence.py), so
            # a crashed tool leaves the quorum by itself (defect 3). With one ACTIVE tool, that tool is the conductor
            # under the global authority order, so its own agreement suffices.
            ballot = votes.get(wait["item"])
            if (not isinstance(ballot, dict) or ballot.get("owner") != owners[0]
                    or ballot.get("since") != wait["since"] or not isinstance(ballot.get("by"), dict)):
                ballot = {"owner": owners[0], "since": wait["since"], "by": {}}
            ballot["by"] = {t: ts for t, ts in ballot["by"].items()
                            if isinstance(ts, (int, float)) and moment - ts < max_wait_s}
            ballot["by"][tool] = moment
            votes[wait["item"]] = ballot
            voters = sorted(ballot["by"])
            entry.update({"owner": owners[0], "action": action(wait, owners[0]), "voters": voters,
                          "present": present})
            result["stalled"].append(entry)
            if schedule is not None and present and set(present) <= set(voters):
                note = "U166 reroute: waiting is a failure"
                original = next((p for p in schedule.get("phases") or [] if isinstance(p, dict)
                                 and wait["item"] == f"phase:{p.get('phase_id')}"), None)
                if original is not None:
                    # Reassign the waiting phase itself, so its dependents stay linked and the tool that was waited
                    # on cannot take the same step again when it returns (Codex judge U166-APPLY3, finding 2).
                    original["rerouted_from"] = {k: original.get(k) for k in ("owner_tool", "state", "waiting_on")}
                    original.pop("waiting_on", None)
                    original.update({"state": "READY", "owner_tool": owners[0], "action": entry["action"],
                                     "agreed_by": present, "note": note})
                    phase_id = str(original["phase_id"])
                else:
                    phase_id = _item_id(wait["item"])
                    schedule.setdefault("phases", []).append(
                        {"phase_id": phase_id, "state": "READY", "owner_tool": owners[0], "depends_on": [],
                         "source": wait["item"], "kind": wait["kind"], "action": entry["action"],
                         "agreed_by": present, "note": note})
                adopted[wait["item"]] = {"phase_id": phase_id, "owner": owners[0], "at": moment,
                                         "since": wait["since"]}
                result["adopted"].append({"phase_id": phase_id, "source": wait["item"], "owner_tool": owners[0],
                                          "agreed_by": present})
                changed_schedule = True
        if changed_schedule:
            _write_json(project / SCHEDULE, schedule)
        votes = {k: v for k, v in votes.items() if k in live}
        # An adoption is kept while its wait is still on disk, or for NOTICE_KEEP_S after it, so every tool hears of
        # it at its next prompt (a reassigned phase stops being a wait at once).
        adopted = {k: v for k, v in adopted.items() if isinstance(v, dict)
                   and (k in live or moment - float(v.get("at", 0)) < NOTICE_KEEP_S)}
        fresh = {p["source"] for p in result["adopted"]}
        result["settled"] = [{"item": k, "phase_id": v["phase_id"], "owner": v["owner"]}
                             for k, v in sorted(adopted.items()) if k not in fresh]
        _write_json(state_dir / "seen.json", seen)
        _write_json(state_dir / "votes.json", votes)
        _write_json(state_dir / "adopted.json", adopted)
    return result


def hook_lines(project: Path, tool: str, *, now: float | None = None) -> str:
    """The per-prompt hook text: one line per stalled step, shown only when it changed since this tool last saw it."""
    result = scan(project, tool, now=now)
    lines = []
    # Only an agreed reroute tells a tool to act (Codex judge U166-APPLY3, finding 1); before that it is a proposal
    # that this prompt has just agreed to.
    for entry in result["stalled"]:
        if entry["item"] in {p["source"] for p in result["adopted"]}:
            continue
        lines.append(f"WAIT IS FAILURE (U166): {entry['item']} waited {entry['age_s'] // 60} min on "
                     f"{entry['waiting_on']}; proposed reroute → {entry['owner']}: {entry['action']} "
                     f"(agreed {len(entry['voters'])}/{len(entry['present'])} present; adopted when all agree)")
    for phase in result["adopted"]:
        you = " — you take it now" if phase["owner_tool"] == tool else ""
        lines.append(f"ADOPTED (U166): {phase['source']} → {phase['owner_tool']} as {phase['phase_id']} on the "
                     f"master schedule, agreed by {','.join(phase['agreed_by'])}{you}")
    for entry in result.get("settled", []):
        you = " — you take it now" if entry["owner"] == tool else ""
        lines.append(f"REROUTED (U166): {entry['item']} → {entry['owner']} as {entry['phase_id']} on the master "
                     f"schedule (see uaos coord next){you}")
    for entry in result["blocked"]:
        lines.append(f"WAIT IS FAILURE (U166): {entry['item']} waited {entry['age_s'] // 60} min on "
                     f"{entry['waiting_on']} and no ACTIVE tool can take it: log BLOCKED and take the next card")
    text = "\n".join(lines)
    from .next_card import coord_root

    marker = coord_root(Path(project)) / STATE_DIR / f"shown_{tool}.txt"
    try:
        if text and marker.read_text(encoding="utf-8") == text:
            return ""
    except OSError:
        pass
    if text:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(text, encoding="utf-8")
    return text
