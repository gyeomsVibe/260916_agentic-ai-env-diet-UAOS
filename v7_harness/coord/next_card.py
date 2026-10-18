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
# U220: letters to an owner that sit unread longer than this mark it saturated. Measured 2026-10-19 on this project's
# acked ACTIONABLE letters, dispatch to ack: codex n=227 p50 285 s, p75 680 s; claude n=22 p50 146 s. 600 s is past
# most normal round trips and below the stall reroute's MAX_WAIT_S (1800 s). Provisional: re-measure, not optimized.
ASSIST_AGE_S = 600
# U220: two such letters mean the owner's queue grows faster than it drains (receipt: three relays in one Codex turn).
ASSIST_BACKLOG = 2
# U220-R4: the resource kinds an assist can prove disjoint; any other kind fails closed (Codex relay_11836ec0).
RESOURCE_KINDS = ("file", "worktree", "branch", "db", "port")
# U220-R5 (Codex relay_4c15703d): file and worktree both name physical paths, so they share one containment domain.
RESOURCE_DOMAIN = {"file": "path", "worktree": "path", "branch": "branch", "db": "db", "port": "port"}
# U220: steps that never move by assist; judging and merging keep their own routes (non-author judge, merger order).
NO_ASSIST_WORDS = ("verdict", "review", "judge", "merge")


def coord_root(project: Path) -> Path:
    """R5: all worktrees agree on one schedule, kept in the main checkout (the git common dir's parent)."""
    project = Path(project)
    # U182: a worktree's top folder always holds `.git`; a folder that has its own .coord but no `.git` is a project
    # nested inside a larger repository (Lotto receipt 2026-10-11) and keeps its own schedule and mailbox.
    from v7_harness.coord.hook_context import stage_work_dir

    # U211: a pilot stage carries a copied .coord without .git but belongs to the repository that holds its work dir.
    if (project / ".coord").is_dir() and not (project / ".git").exists() and stage_work_dir(project) is None:
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


def _claim(claims: Path, card: str, tool: str, session: str, now: float, schedule: Path | None = None, expected: dict | None = None,
           expected_schedule_sha: str | None = None, assist_for: str | None = None, revalidate=None) -> bool:
    """U146a-R: take `card` for this session. A hook process exits right after it claims, so a PID never owned
    anything (PR112 counterexample); the session id does, until CLAIM_TTL_S passes without renewal.

    U146a-R2: read, decide and write happen under one OS file lock (Codex U146-R4: replace plus re-read gave two
    parallel winners). False when another session holds a live claim, or when the claim cannot be decided safely (lock
    busy past its timeout, the file held open outside the lock): fail closed, a later turn or another card goes on.
    """
    from v7_harness.coord.stream import StreamBusy, _exclusive

    path = claims / f"{card}.json"
    record = {"session": session, "tool": tool, "at": now, **({"assist_for": assist_for} if assist_for else {})}
    claims.mkdir(parents=True, exist_ok=True)
    try:
        with _exclusive(claims / ".lock"):
            if schedule is not None:
                try:
                    raw = schedule.read_bytes()
                    # U195: an automatic claim holds only if the schedule is byte-identical to the one it was decided on
                    import hashlib
                    if expected_schedule_sha is not None and hashlib.sha256(raw).hexdigest() != expected_schedule_sha:
                        return False
                    phases = json.loads(raw.decode("utf-8"))["phases"]
                    if not isinstance(phases, list) or not all(isinstance(p, dict) for p in phases) or not isinstance(expected, dict):
                        return False
                    matches = [p for p in phases if p.get("phase_id") == card]
                    keys = ("phase_id", "state", "owner_tool", "owner_session", "worktree")
                    if len(matches) != 1 or any((k in matches[0], matches[0].get(k)) != (k in expected, expected.get(k)) for k in keys):
                        return False
                except (OSError, ValueError, KeyError, TypeError):
                    return False
            # U220-R: an assist claim re-decides saturation and resource exclusion here, under the lock
            if revalidate is not None and not revalidate():
                return False
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


def _caps_available(phase) -> bool:
    """U195: a phase auto-promotes only inside finite, unexhausted caps (contract 65136bf)."""
    words = {"cap", "caps", "budget", "budgets", "limit", "limits", "token", "tokens", "quota", "remaining"}
    if any(key != "caps" and words & set(str(key).lower().split("_")) for key in phase):
        return False
    caps = phase.get("caps", {})
    if not isinstance(caps, dict):
        return False
    for value in caps.values():
        if not isinstance(value, dict) or set(value) != {"used", "limit"}:
            return False
        used, limit = value["used"], value["limit"]
        # exact int/float only (bool excluded); NaN fails both comparisons; huge ints compare exactly with inf
        if any(type(n) not in (int, float) or not -float("inf") < n < float("inf") for n in (used, limit)):
            return False
        if not 0 <= used < limit:
            return False
    return True


def _automatic_pending(phase, states) -> bool:
    """U195: a PENDING phase starts by itself only when it opts in and nothing protects it; anything odd fails closed."""
    if phase.get("state") != "PENDING" or phase.get("auto_promote") is not True:
        return False
    if "human" in phase or "gate_failed" in phase:
        return False
    if "rerouted_from" in phase:
        moved = phase["rerouted_from"]
        if not isinstance(moved, dict) or not isinstance(moved.get("state"), str):
            return False
        if moved["state"] in ("HUMAN", "PARKED", "SCOPE", "BLOCKED", "REWORK", "FAILED"):
            return False
    deps = phase.get("depends_on")
    if not isinstance(deps, list) or not all(isinstance(d, str) and d for d in deps) or len(set(deps)) != len(deps):
        return False
    if any(states.get(d) != "DONE" for d in deps):  # only DONE satisfies the automatic path (REVIEW does not)
        return False
    return _caps_available(phase)


def _bound_here(phase: dict, project: Path) -> bool:
    """U196: a phase that names a worktree is claimable only from that existing checkout (Codex relay_189466e7)."""
    if "worktree" not in phase:
        return True
    where = phase["worktree"]
    if not isinstance(where, str) or not where:
        return False
    try:
        return Path(where).is_dir() and os.path.samefile(where, project)
    except OSError:
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
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"))
        phases = data["phases"]
        if not isinstance(phases, list) or not all(isinstance(p, dict) for p in phases):
            raise ValueError("phases is not a list of objects")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"state": "WAIT", "reason": f"schedule unreadable: {exc}"}
    by_id = {str(p.get("phase_id")): p for p in phases}
    state_of = {pid_: p.get("state") for pid_, p in by_id.items()}
    # U195: the automatic path trusts only unique, non-empty string phase ids
    ids = [p.get("phase_id") for p in phases]
    unique = {i: p.get("state") for i, p in zip(ids, phases) if isinstance(i, str) and i and ids.count(i) == 1}
    candidates, stacked = [], []
    for p in phases:
        if p.get("state") == "PENDING":
            pid = p.get("phase_id")
            if isinstance(pid, str) and pid in unique and _automatic_pending(p, unique):
                candidates.append(p)
            continue
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
        assigned = p.get("owner_session")
        if "owner_session" in p and (not isinstance(assigned, str) or not assigned or assigned != session):
            continue
        card = str(p.get("phase_id"))
        if claim:
            if not session:
                # U146a-R: PID-only ownership is refused; an unknown session claims nothing (a plain read still names it).
                return {"state": "WAIT", "reason": "a claim needs a session id (U146a-R)", "card": card}
            if not _bound_here(p, project):
                # U196: a wrong or missing checkout claims nothing and writes no claim file
                return {"state": "WAIT", "code": "WORKTREE_MISMATCH", "card": card,
                        "reason": "phase.worktree is not this existing checkout"}
            # The claim lives beside the schedule, so every worktree sees the same claims (R5).
            claims = path.parent / "next" / "claims"
            sha = None
            if p.get("state") == "PENDING":
                import hashlib
                sha = hashlib.sha256(raw).hexdigest()
            moment = time.time() if now is None else now
            if not _claim(claims, card, tool, session, moment, schedule=path, expected=p, expected_schedule_sha=sha,
                          revalidate=lambda card=card: _no_assist_held(claims, tool, card, moment)):
                claimed_out = True
                continue
            return {"state": "NEXT", "card": card, "owner": p.get("owner_tool"), "claimed": True}
        return {"state": "NEXT", "card": card, "owner": p.get("owner_tool")}
    others = [p for p in candidates if p.get("owner_tool") not in (tool, "all")]
    if others and (helped := _assist(path, project, tool, others, claim, session, now, phases)) is not None:
        return helped
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


def _live_claims(claims: Path, now: float) -> dict[str, dict]:
    """U220: card -> claim record for every claim with a session that is still inside CLAIM_TTL_S."""
    live = {}
    for path in claims.glob("*.json"):
        try:
            held = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        at = held.get("at") if isinstance(held, dict) else None
        if isinstance(at, (int, float)) and not isinstance(at, bool) and now - at < CLAIM_TTL_S and held.get("session"):
            live[path.stem] = held
    return live


def _letter_backlog(root: Path, owner: str, now: float) -> int:
    """U220: ACTIONABLE letters dispatched to `owner` between ASSIST_AGE_S and CLAIM_TTL_S ago, neither acked nor
    answered. A letter older than CLAIM_TTL_S belongs to a session that is gone, not a busy one (real inbox
    2026-10-19: 43 stale letters to claude would mark it busy forever), and skipping it by mtime keeps the scan cheap.
    U220-R: a letter bound to a native session counts only while that session is live on the owner's desk record."""
    from .desk_delta import canonical
    from .presence import _path
    from .stall import ACK, INBOX, _answered, _dispatched_at, _payload, _reply_to

    try:
        sessions = json.loads(_path(root, owner).read_text(encoding="utf-8")).get("sessions")
    except (OSError, ValueError, AttributeError):
        sessions = None
    live = {s for s, until in (sessions.items() if isinstance(sessions, dict) else ())
            if isinstance(until, (int, float)) and until > now}
    old, superseded = [], set()
    for path in (root / INBOX).glob("*.json"):
        try:
            if now - path.stat().st_mtime >= CLAIM_TTL_S:
                continue
        except OSError:
            continue
        body, since = _payload(path), _dispatched_at(root, path.stem)
        if body is None or since is None or not ASSIST_AGE_S <= now - since < CLAIM_TTL_S:
            continue  # a future or invalid dispatch time fails the window too
        if body.get("native_receiver") and body["native_receiver"] not in live:
            continue
        named = body.get("supersedes")
        named = [named] if isinstance(named, str) else named if isinstance(named, list) else []
        superseded |= {s for s in named if isinstance(s, str)}
        # U220-R2 (Codex relay_52c2dbec): an ACK or a reply is history, not new work for the owner
        if body.get("kind") == "ACK" or _reply_to(body):
            continue
        if body.get("wake_class") == "ACTIONABLE" and canonical(str(body.get("requested_target") or "")) == owner:
            old.append(path)
    old = [p for p in old if p.stem not in superseded]
    if len(old) < ASSIST_BACKLOG:
        return len(old)
    answered = _answered(root, now - CLAIM_TTL_S)
    return sum(p.stem not in answered and not (root / ACK / p.name).exists() for p in old)


def _assistable(phase: dict, tool: str, live: dict) -> bool:
    """U220: a ready implement card of another tool that no session holds and nothing reserves for a person, a
    session, a judge or a merger."""
    from .stall import CAPABILITY, HUMAN_ONLY_RE

    if phase.get("owner_tool") in (tool, "all") or tool not in CAPABILITY["implement"] or phase.get("assist") is False:
        return False
    if phase.get("state") not in CANDIDATE or "owner_session" in phase or "human" in phase:
        return False
    text = f"{phase.get('phase_id', '')} {phase.get('note', '')} {phase.get('waiting_on', '')}"
    if str(phase.get("phase_id")) in live or HUMAN_ONLY_RE.search(text):
        return False
    return not any(word in text.lower() for word in NO_ASSIST_WORDS)


def _assist(path: Path, project: Path, tool: str, others: list[dict], claim: bool, session: str | None,
            now: float | None, phases: list) -> dict[str, Any] | None:
    """U220 work stealing: an idle tool takes a saturated owner's ready implement card. Authority does not move: the
    card ends at REVIEW and its owner or the conductor judges it. A claim re-decides everything under the claim lock."""
    moment = time.time() if now is None else now
    claims, root = path.parent / "next" / "claims", path.parent.parent
    if not _helper_ready(root, project, tool, moment):
        return None
    by_id = {str(p.get("phase_id")): p for p in phases}
    live, busy = _live_claims(claims, moment), {}
    for p in others:
        owner, card = str(p.get("owner_tool")), str(p.get("phase_id"))
        if not _assistable(p, tool, live) or not _admissible(p, phases) or not _free(p, tool, live, by_id, root):
            continue
        if owner not in busy:
            busy[owner] = _saturated(root, owner, live, moment)
        if not busy[owner]:
            continue
        found = {"state": "NEXT", "card": card, "owner": owner, "assist_for": owner}
        if not claim:
            return found

        def recheck(owner=owner, card=card) -> bool:
            # U220-R2: re-read the schedule under the claim lock, so a dependency, cap or state change, an owner claim
            # or an ack that lands while the helper decides refuses the claim
            fresh = _live_claims(claims, moment)
            if not _helper_ready(root, project, tool, moment):  # U220-R3: helper state and QUIET_LOCK at commit too
                return False
            try:
                fresh_phases = json.loads(path.read_bytes().decode("utf-8"))["phases"]
            except (OSError, ValueError, KeyError, TypeError):
                return False
            if not isinstance(fresh_phases, list) or not all(isinstance(x, dict) for x in fresh_phases):
                return False
            mine = [x for x in fresh_phases if x.get("phase_id") == card]
            fresh_by_id = {str(x.get("phase_id")): x for x in fresh_phases}
            return (len(mine) == 1 and mine[0].get("owner_tool") == owner and _assistable(mine[0], tool, fresh)
                    and _admissible(mine[0], fresh_phases) and _free(mine[0], tool, fresh, fresh_by_id, root)
                    and _saturated(root, owner, fresh, moment))

        if session and _bound_here(p, project) and _claim(claims, card, tool, session, moment, schedule=path,
                                                         expected=p, assist_for=owner, revalidate=recheck):
            return {**found, "claimed": True}
    return None


def _resources(phase: dict | None, project: Path) -> set[tuple[str, str]] | None:
    """U220-R4 (Codex relay_11836ec0): what a phase may touch, as typed identities (kind, identity). Entries come from
    `resources`, else `allowed_files`, plus the phase's worktree and branch. An entry is `kind:value` for a kind in
    RESOURCE_KINDS; an untyped entry is a file. Files resolve against one base, the phase's worktree else the project
    root, to a real path (symlinks followed), so an absolute and a project-relative name of one file are one identity.
    None (unknown disjointness, fail closed) for no list, a malformed entry, an unknown kind, a non-numeric port or a
    file or worktree outside the project."""
    phase = phase or {}
    value = phase.get("resources", phase.get("allowed_files"))
    if not isinstance(value, list) or not value or not all(isinstance(r, str) and r for r in value):
        return None
    try:
        root = Path(project).resolve()
        base = root
        if "worktree" in phase:
            if not isinstance(phase["worktree"], str) or not phase["worktree"]:
                return None
            base = (root / phase["worktree"]).resolve()
            value = [*value, f"worktree:{phase['worktree']}"]
        if "branch" in phase:
            if not isinstance(phase["branch"], str) or not phase["branch"]:
                return None
            value = [*value, f"branch:{phase['branch']}"]
        out = set()
        for entry in value:
            kind, _, rest = entry.partition(":")
            if len(kind) < 2 or not rest:  # a drive letter (C:\...) or no colon: an untyped file
                kind, rest = "file", entry
            if kind not in RESOURCE_KINDS or not rest.strip():
                return None
            if kind in ("file", "worktree"):
                parts = Path(rest).parts
                # a glob names everything under its literal prefix (conservative)
                cut = next((i for i, part in enumerate(parts) if any(c in part for c in "*?[")), len(parts))
                real = ((root if kind == "worktree" else base) / Path(*parts[:cut])).resolve() if cut else base
                if real != root and root not in real.parents:
                    return None
                out.add((kind, os.path.normcase(str(real))))
            elif kind == "port":
                if not rest.strip().isdigit():
                    return None
                out.add((kind, str(int(rest))))
            else:  # branch and db names compare case-insensitively (a false overlap only refuses)
                out.add((kind, rest.strip().casefold()))
        return out
    except (OSError, ValueError, RuntimeError):
        return None


def _overlap(mine: set, theirs: set) -> bool:
    """U220-R5: two resources overlap when they are one identity of one domain, or in the path domain (file and
    worktree) one path contains the other (a directory or worktree covers its files, whatever their kind)."""
    for kind, a in mine:
        for other, b in theirs:
            if RESOURCE_DOMAIN[kind] != RESOURCE_DOMAIN[other]:
                continue
            if a == b or (RESOURCE_DOMAIN[kind] == "path" and (a.startswith(b + os.sep) or b.startswith(a + os.sep))):
                return True
    return False


def _free(phase: dict, tool: str, live: dict, by_id: dict, project: Path) -> bool:
    """U220-R (Codex relay_43bbc628, relay_52c2dbec): one active step per platform, so a helper tool that holds any live
    claim takes nothing; and no resource shared with a card that a session runs now. A running card that declares no
    resources may touch anything, so it blocks every assist (fail closed)."""
    mine = _resources(phase, project)
    if mine is None or any(r.get("tool") == tool for r in live.values()):
        return False
    for card in live:
        theirs = _resources(by_id.get(card), project)
        if theirs is None or _overlap(mine, theirs):
            return False
    return True


def _admissible(phase: dict, phases: list) -> bool:
    """U220-R2 (Codex relay_52c2dbec): admission fails closed on a duplicate or empty id, a malformed or unmet
    dependency, an exhausted or malformed cap, a protected history and a missing contract (acceptance command)."""
    pid = phase.get("phase_id")
    if not isinstance(pid, str) or not pid or [p.get("phase_id") for p in phases].count(pid) != 1:
        return False
    if any(key in phase for key in ("gate_failed", "rerouted_from", "parked_at", "blocker_reason", "blocker")):
        return False
    cmd = phase.get("acceptance_cmd")
    if not isinstance(cmd, str) or not cmd.strip() or not _caps_available(phase):
        return False
    deps = phase.get("depends_on", [])
    if not isinstance(deps, list) or not all(isinstance(d, str) and d for d in deps):
        return False
    states = {p.get("phase_id"): p.get("state") for p in phases}
    return all([p.get("phase_id") for p in phases].count(d) == 1 and states[d] in SATISFIED for d in deps)


def _saturated(root: Path, owner: str, live: dict, now: float) -> bool:
    """U220-R: the owner is ACTIVE on the desk now and runs another claimed card or has a backlog of current unread
    letters. A LIMITED, ABSENT or UNKNOWN owner is left to the succession and stall routes (fail closed)."""
    from .presence import TOOLS, read

    if owner not in TOOLS or read(root, owner, now=now).get("state") != "ACTIVE":
        return False
    return any(r.get("tool") == owner for r in live.values()) or _letter_backlog(root, owner, now) >= ASSIST_BACKLOG


def _helper_ready(root: Path, project: Path, tool: str, now: float) -> bool:
    """U220-R2: an assist needs a helper the desk knows as ACTIVE and a checkout no pilot run holds (QUIET_LOCK).
    U220-R3: checked before the decision and again under the claim lock."""
    from .presence import read

    return read(root, tool, now=now).get("state") == "ACTIVE" and not (Path(project) / ".work" / "QUIET_LOCK").exists()


def _no_assist_held(claims: Path, tool: str, card: str, now: float) -> bool:
    """U220-R3 (Codex relay_9dbab448): while any session of `tool` runs an assist, the tool takes no own card either,
    so one platform never runs two steps. Own cards without assists keep their session contract unchanged."""
    return not any(r.get("tool") == tool and r.get("assist_for") and held != card
                   for held, r in _live_claims(claims, now).items())
