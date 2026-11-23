"""U334 freeze-tag (얼음땡): a frozen tool is covered by its peers and thawed by them at its reset time.

윤겸스 (2026-11-20): when one of the 3 tools stops on its 5 h / weekly limit, the others take over its cards and keep
the work going; when the limit resets and the tool cannot restart itself, a peer revives it. Four duties, all local and
deterministic (zero paid tokens; the scheduler is Windows Task Scheduler, never a paid poll):

1. `detect`   read the real quota signal of one tool (provider payload only) -> FROZEN / OK / UNKNOWN. A remaining
              percentage is never turned into tokens; anything not provably exhausted-and-fresh is UNKNOWN and fails
              closed (never ACTIVE, never frozen with a made-up reset).
2. `takeover` re-route a frozen tool's cards to ACTIVE peers in authority order (Codex > Claude > Antigravity, and
              Antigravity only while both others are not ACTIVE). A peer that stays silent for ABSTAIN_S abstains
              (U329 concept: silence = abstain), so a mute peer can never hold a reroute (U166 hang).
3. `thaw_due` at reset_at (+ clock-skew margin) one peer claims the revival, calls the tool's real resume adapter,
              and counts it done only on a SECOND signal (a newer heartbeat or a completed turn), never on exit 0.
              Failures back off exponentially; past REVIVE_DEADLINE_S the tool is BLOCKED and woken at its next reset.
4. `schedule` the earliest due time is written as a one-shot Task Scheduler job so nothing polls while all sleep.

Stage 0 sources: docs/U334 (see `.coord/results/U334.md`). State lives in `.coord/freeze/state.json`.
"""

from __future__ import annotations

import functools
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import uuid
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .presence import TOOLS
from .quota_sources import VERIFIED_EVIDENCE, _epoch

# Global rules, Authority: Codex conducts while ACTIVE, else Claude, Antigravity only while both are away.
AUTHORITY = ("codex", "claude", "antigravity")
STATE_DIR = Path(".coord") / "freeze"
SCHEDULE = Path(".coord") / "master_schedule.json"
FIVE_HOUR_S = 5 * 3600
SEVEN_DAY_S = 7 * 86400
# U329 concept: reply within 120 s, silence is an abstention. The same number bounds how long a peer may sit on a reroute.
ABSTAIN_S = 120
# A provider reset can be a few seconds early on its clock or ours; 60 s past it is the earliest a revive is tried
# (CLOCK_SKEW_S of quota_sources is 300 s for readings; 60 s is enough for a clock that is NTP-synced).
SKEW_MARGIN_S = 60
# A reset further away than the longest window plus the margin cannot be real (clock skew or a corrupt record): UNKNOWN.
MAX_PLAUSIBLE_RESET_S = SEVEN_DAY_S + 3600
# Reset unknown: probe at 15 min, doubling, so an unknown never means "never retry" and never means "retry now".
PROBE_UNKNOWN_S = 900
# Revive backoff 30 s, 60 s, 120 s ... capped at 15 min; 4 tries per hour per tool stops a revive storm.
BACKOFF_BASE_S = 30
BACKOFF_CAP_S = 900
MAX_ATTEMPTS_PER_HOUR = 4
# After this long past the reset a tool that stays dead is BLOCKED and woken at its next reset (2 h = 24 backoff-capped tries).
REVIVE_DEADLINE_S = 7200
VERIFY_POLLS = 6
VERIFY_POLL_S = 5.0
RESUME_TIMEOUT_S = 600  # one headless resume call (CommandAdapter.resume subprocess timeout)
# One claim at a time per tool. A live attempt holds it for at most one resume call plus the verification polls; the
# claim must outlive that (AGY review U334-D: a 600 s TTL lapsed mid-verification and let a second peer start a duplicate
# resume), so a dead reviver's claim lapses one minute after the longest live attempt could have finished.
CLAIM_TTL_S = RESUME_TIMEOUT_S + VERIFY_POLLS * VERIFY_POLL_S + 60
HUMAN_ONLY_RE = re.compile(r"delet|deploy|publish|spend|payment|credential|secret|permission|push|삭제|배포|지출|권한|푸시",
                           re.IGNORECASE)
MOVABLE_STATES = ("READY", "RUNNING", "IN_PROGRESS", "ACTIVE")


# ------------------------------------------------------------------ state
def _root(project: Path) -> Path:
    try:
        from .next_card import coord_root

        return coord_root(Path(project))
    except Exception:  # noqa: BLE001 - a missing git must not stop a freeze record
        return Path(project)


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8")
    for _ in range(20):  # Windows: os.replace fails while a reader holds the file
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.01)
    os.replace(tmp, path)


def _lock(project: Path):
    from .stream import _exclusive

    return _exclusive(_root(project) / STATE_DIR / "freeze.lock")


def load(project: Path) -> dict[str, Any]:
    data = _read(_root(project) / STATE_DIR / "state.json", {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("tools", {})
    data.setdefault("offers", {})
    data.setdefault("acks", {})
    return data


def _save(project: Path, data: dict[str, Any]) -> None:
    _write(_root(project) / STATE_DIR / "state.json", data)


def log_event(project: Path, kind: str, now: float, **fields: Any) -> None:
    """One append-only line per event (BLOCKED, FROZEN, THAWED ...); callers hold the freeze lock."""
    path = _root(project) / STATE_DIR / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"kind": kind, "at": now, **fields}, ensure_ascii=False, sort_keys=True) + "\n")


def events(project: Path) -> list[dict[str, Any]]:
    out = []
    try:
        for line in (_root(project) / STATE_DIR / "events.jsonl").read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    return out


# ------------------------------------------------------------------ 1. detect
def _used_pct(window: Any) -> float | None:
    """A finite, non-bool number or None; NaN/inf/bool/strings are not readings (fail closed)."""
    used = window.get("used_pct") if isinstance(window, dict) else None
    if isinstance(used, bool) or not isinstance(used, (int, float)) or not math.isfinite(used):
        return None
    return float(used)


def _window_exhausted(window: dict[str, Any] | None) -> tuple[bool, float | None]:
    """(exhausted, reset epoch). Only a FRESH window at 100 % counts; every other state is not evidence of a freeze."""
    if not isinstance(window, dict) or window.get("state") != "FRESH":
        return False, None
    used = _used_pct(window)
    if used is None or used < 100.0:
        return False, None
    return True, _epoch(window.get("resets_at"))


def account_from_antigravity(quota: dict[str, Any] | None) -> dict[str, Any] | None:
    """The cockpit cache is a provider payload: its selected pool plays the 5 h window."""
    pool = (quota or {}).get("selected_pool")
    if not isinstance(pool, dict):
        return None
    return {"evidence": VERIFIED_EVIDENCE, "five_hour": pool, "seven_day": None, "source": quota.get("source")}


def detect(tool: str, account: dict[str, Any] | None, *, now: float,
           lease: dict[str, Any] | None = None) -> dict[str, Any]:
    """FROZEN with reset_at, OK, or UNKNOWN. `lease` is a provider LIMITED presence record (a real 429 answer)."""
    base = {"tool": tool, "at": now, "verdict": "UNKNOWN", "reset_at": None, "reset_known": False, "reason": ""}
    if tool not in TOOLS:
        return {**base, "reason": "unknown tool"}
    reset_candidates: list[float | None] = []
    source = None
    if isinstance(account, dict) and account.get("evidence") == VERIFIED_EVIDENCE:
        source = account.get("source")
        flags = [_window_exhausted(account.get(k)) for k in ("five_hour", "seven_day")]
        reset_candidates = [r for ok, r in flags if ok]
        if any(ok for ok, _ in flags):
            known = [r for r in reset_candidates if r is not None]
            # every exhausted window must clear before the tool can work, so the LATEST reset counts
            reset_at = max(known) if len(known) == len(reset_candidates) and known else None
            return _frozen(base, reset_at, now, f"exhausted window ({source})")
    expires = lease.get("expires_at") if isinstance(lease, dict) else None
    numeric = isinstance(expires, (int, float)) and not isinstance(expires, bool) and math.isfinite(expires)
    if isinstance(lease, dict) and lease.get("state") == "LIMITED" and lease.get("lease_source") == "provider"             and (expires is None or (numeric and expires > now)):
        # an active provider 429 outranks a cached "below 100 %" reading
        return _frozen(base, float(expires) if numeric else None, now, "provider LIMITED lease")
    if isinstance(account, dict) and account.get("evidence") == VERIFIED_EVIDENCE:
        windows = [account.get(k) for k in ("five_hour", "seven_day") if account.get(k)]
        if windows and all(isinstance(w, dict) and w.get("state") == "FRESH" and _used_pct(w) is not None for w in windows):
            return {**base, "verdict": "OK", "reason": f"fresh readings below 100% ({source})"}
    return {**base, "reason": "no fresh provider reading (fail closed)"}


def _frozen(base: dict[str, Any], reset_at: float | None, now: float, why: str) -> dict[str, Any]:
    known = reset_at is not None and math.isfinite(reset_at) and now - SEVEN_DAY_S < reset_at <= now + MAX_PLAUSIBLE_RESET_S
    return {**base, "verdict": "FROZEN", "reset_at": float(reset_at) if known else None, "reset_known": bool(known),
            "reason": why if known or reset_at is None else f"{why}; implausible reset ignored (clock skew)"}


def record(project: Path, verdict: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
    """Store a FROZEN verdict in the freeze state and in presence (LIMITED lease until the reset)."""
    moment = time.time() if now is None else now
    tool = verdict["tool"]
    if verdict.get("verdict") != "FROZEN":
        return {}
    with _lock(project):
        data = load(project)
        row = data["tools"].get(tool) or {}
        if row.get("state") == "FROZEN":
            # keep attempts/backoff; a later reset replaces an earlier one, an unknown never overwrites a known one
            new_at = verdict.get("reset_at")
            if verdict["reset_known"] and new_at is not None and (
                    not row.get("reset_known") or row.get("reset_at") is None or new_at > row["reset_at"]):
                row["reset_at"], row["reset_known"] = verdict["reset_at"], True
        else:
            row = {"state": "FROZEN", "frozen_at": moment, "reset_at": verdict["reset_at"],
                   "reset_known": verdict["reset_known"], "attempts": 0, "attempt_log": [], "next_attempt_at": None,
                   "claim": None, "blocked": False}
            log_event(project, "FROZEN", moment, tool=tool, reset_at=verdict["reset_at"], reason=verdict["reason"])
        data["tools"][tool] = row
        _save(project, data)
    _mark_presence(project, tool, "LIMITED", row, moment)
    return row


def _bound_session(project: Path, tool: str) -> str | None:
    """The user-desk session bound to this tool (`.coord/presence/user_desk_<tool>.json` thread), if any."""
    try:
        desk = json.loads((_root(project) / ".coord" / "presence" / f"user_desk_{tool}.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    thread = str(desk.get("thread") or "").strip() if isinstance(desk, dict) else ""
    return thread or None


def _mark_presence(project: Path, tool: str, state: str, row: dict[str, Any], moment: float) -> None:
    try:
        from . import presence

        if state == "LIMITED":
            cur = _provider_lease(project, tool, moment)
            if cur and cur.get("lease_source") == "provider":
                return  # a real provider 429 lease must not be relabelled "manual" (it would then self-thaw next scan)
            ttl = int(max(60, (row.get("reset_at") or moment + PROBE_UNKNOWN_S) - moment))
            # AGY review U334-E F1: an unbound manual lease is fenced off a live desk-bound session and dropped, which
            # leaves presence ACTIVE beside a FROZEN row. The freeze is the account's own fact, so it names the bound
            # session and lands.
            presence.mark(_root(project), tool, "LIMITED", ttl_s=ttl, now=moment, lease=True, lease_source="manual",
                          session=_bound_session(project, tool))
        elif presence.read(_root(project), tool, now=moment).get("state") != "ACTIVE":
            # AGY review U334-E F2: a session-less ACTIVE write replaces the record and erases its live session table;
            # a revived tool already beats ACTIVE itself, so only a LIMITED/UNKNOWN mirror is rewritten
            presence.mark(_root(project), tool, "ACTIVE", now=moment, turn_start=True)
    except Exception:  # noqa: BLE001 - presence is a mirror; the freeze state stays authoritative
        pass


def frozen_tools(project: Path) -> dict[str, dict[str, Any]]:
    return {t: r for t, r in load(project)["tools"].items() if isinstance(r, dict) and r.get("state") == "FROZEN"}


def scan(project: Path, *, home: Path | None = None, now: float | None = None,
         accounts: dict[str, dict[str, Any] | None] | None = None) -> dict[str, dict[str, Any]]:
    """Read every tool's real signal, record freezes, and clear a freeze the provider itself now shows as over."""
    moment = time.time() if now is None else now
    if accounts is None:
        from . import quota_sources as qs

        home = home or Path.home()
        accounts = {"codex": qs.codex_quota(home, moment), "claude": qs.claude_quota(home, moment),
                    "antigravity": account_from_antigravity(qs.antigravity_quota(home, moment))}
    out: dict[str, dict[str, Any]] = {}
    for tool in TOOLS:
        verdict = detect(tool, accounts.get(tool), now=moment, lease=_provider_lease(project, tool, moment))
        out[tool] = verdict
        if verdict["verdict"] == "FROZEN":
            record(project, verdict, now=moment)
        elif verdict["verdict"] == "OK" and tool in frozen_tools(project):
            _thaw_done(project, tool, moment, "self (fresh provider reading below 100%)")
    return out


def _provider_lease(project: Path, tool: str, moment: float) -> dict[str, Any] | None:
    try:
        rec = json.loads((_root(project) / ".coord" / "presence" / f"{tool}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(rec, dict) and rec.get("lease") and rec.get("state") == "LIMITED" and \
            isinstance(rec.get("expires_at"), (int, float)) and not isinstance(rec.get("expires_at"), bool) \
            and rec["expires_at"] > moment:
        return rec
    return None


# ------------------------------------------------------------------ 2. takeover
def candidates(frozen: str, desk: dict[str, dict[str, Any]], frozen_set: set[str]) -> list[str]:
    """ACTIVE, non-frozen peers by authority; Antigravity conducts only while neither Codex nor Claude is available."""
    peers = [t for t in AUTHORITY if t != frozen and t not in frozen_set and (desk.get(t) or {}).get("state") == "ACTIVE"]
    main = [t for t in peers if t != "antigravity"]
    if main:
        return main
    # Antigravity conducts only when both senior tools are positively LIMITED/ABSENT (or frozen); UNKNOWN fails closed
    senior_out = all(t == frozen or t in frozen_set or (desk.get(t) or {}).get("state") in ("LIMITED", "ABSENT")
                     for t in AUTHORITY if t != "antigravity")
    return peers if senior_out else []


def ack(project: Path, tool: str, *, now: float | None = None) -> None:
    """A peer's one-line reply to a takeover offer (its watcher or hook calls this)."""
    moment = time.time() if now is None else now
    with _lock(project):
        data = load(project)
        data["acks"][tool] = moment
        _save(project, data)


def takeover(project: Path, frozen: str, *, desk: dict[str, dict[str, Any]], now: float | None = None) -> dict[str, Any]:
    moment = time.time() if now is None else now
    root = _root(project)
    result: dict[str, Any] = {"moved": [], "pending": [], "kept": [], "owner": None}
    with _lock(project):
        data = load(project)
        frozen_set = {t for t, r in data["tools"].items() if isinstance(r, dict) and r.get("state") == "FROZEN"}
        frozen_set.add(frozen)
        cands = candidates(frozen, desk, frozen_set)
        schedule = _read(root / SCHEDULE, None)
        if not isinstance(schedule, dict) or not cands:
            return {**result, "error": None if cands else "no ACTIVE peer"}
        offer = data["offers"].setdefault(frozen, {"offered_at": moment})
        acked = [t for t in cands if float(data["acks"].get(t, 0)) >= float(offer["offered_at"])]
        # an acking peer in authority order wins at once when it is the first candidate; otherwise the offer waits at
        # most ABSTAIN_S, then silence is abstention and the first acker (else the first candidate) takes the cards
        if acked and acked[0] == cands[0]:
            owner = cands[0]
        elif moment - float(offer["offered_at"]) >= ABSTAIN_S:
            owner = acked[0] if acked else cands[0]
        else:
            owner = None
        if owner is None:
            result["pending"] = [{"peer": cands[0], "abstain_at": float(offer["offered_at"]) + ABSTAIN_S}]
            _save(project, data)
            return result
        row = data["tools"].get(frozen) or {}
        for phase in schedule.get("phases") or []:
            if not isinstance(phase, dict) or phase.get("owner_tool") != frozen or phase.get("state") not in MOVABLE_STATES:
                continue
            if HUMAN_ONLY_RE.search(f"{phase.get('action', '')} {phase.get('phase_id', '')}"):
                result["kept"].append(str(phase.get("phase_id")))
                continue
            checkpoint = phase.get("checkpoint") or _checkpoint_file(root, str(phase.get("phase_id")))
            phase["rerouted_from"] = {k: phase.get(k) for k in ("owner_tool", "owner_session", "state")}
            phase["rerouted_from"].update({"reason": "FROZEN", "reset_at": row.get("reset_at")})
            phase.pop("owner_session", None)
            phase.pop("waiting_on", None)
            phase.update({"owner_tool": owner, "state": "READY", "note": "U334 freeze-tag takeover"})
            if checkpoint:
                phase["resume_from"] = checkpoint
            result["moved"].append({"phase_id": phase.get("phase_id"), "to": owner, "checkpoint": checkpoint})
        if result["moved"]:
            _write(root / SCHEDULE, schedule)
            log_event(project, "TAKEOVER", moment, frozen=frozen, owner=owner, cards=[m["phase_id"] for m in result["moved"]])
        result["owner"] = owner
        _save(project, data)
    return result


def _checkpoint_file(root: Path, phase_id: str) -> str | None:
    path = root / ".coord" / "checkpoints" / f"{phase_id}.json"
    return str(path.relative_to(root)).replace("\\", "/") if path.is_file() else None


def blocked_check(project: Path, *, desk: dict[str, dict[str, Any]], now: float | None = None) -> dict[str, Any] | None:
    """All three frozen -> BLOCKED with the wake time of the earliest reset (never a wait on a human)."""
    moment = time.time() if now is None else now
    with _lock(project):
        data = load(project)
        rows = {t: data["tools"].get(t) or {} for t in TOOLS}
        blocked_file = _root(project) / STATE_DIR / "blocked.json"
        if not all(r.get("state") == "FROZEN" for r in rows.values()):
            if _read(blocked_file, {}).get("state") == "BLOCKED":
                _write(blocked_file, {"state": "CLEAR", "cleared_at": moment})  # recovery: no stale BLOCKED left behind
            return None
        wake = _earliest_due(rows, moment)
        due = min(_due_at(r) for r in rows.values())
        info = {"state": "BLOCKED", "reason": "all 3 tools FROZEN", "wake_at": wake, "due_at": due,
                "resets": {t: r.get("reset_at") for t, r in rows.items()}}
        previous = _read(blocked_file, {})
        _write(blocked_file, info)
        if previous.get("state") != "BLOCKED" or previous.get("due_at") != due:  # an overdue wake moves every tick: not news
            log_event(project, "BLOCKED", moment, **{k: v for k, v in info.items() if k != "state"})
    return info


def _due_at(row: dict[str, Any]) -> float:
    """The earliest moment a revive of this frozen tool may be tried."""
    if row.get("reset_known") and row.get("reset_at") is not None:
        base = float(row["reset_at"]) + SKEW_MARGIN_S
    else:
        base = float(row.get("frozen_at") or 0) + PROBE_UNKNOWN_S
    nxt = row.get("next_attempt_at")
    if isinstance(nxt, (int, float)) and not isinstance(nxt, bool):
        base = max(base, float(nxt))
    return base


def _earliest_due(rows: dict[str, dict[str, Any]], moment: float) -> float:
    dues = [_due_at(r) for r in rows.values() if r.get("state") == "FROZEN"]
    return max(min(dues), moment) if dues else moment + PROBE_UNKNOWN_S


# ------------------------------------------------------------------ 3. thaw
def thaw_due(project: Path, actor: str, adapters: dict[str, Any], *, desk: dict[str, dict[str, Any]],
             now: float | None = None, sleep: Callable[[float], None] = time.sleep) -> list[dict[str, Any]]:
    """Revive every frozen tool whose time has come. `actor` is an ACTIVE peer tool or "scheduler"."""
    out: list[dict[str, Any]] = []
    if actor != "scheduler" and ((desk.get(actor) or {}).get("state") != "ACTIVE" or actor in frozen_tools(project)):
        return [{"result": "ACTOR_NOT_ACTIVE", "actor": actor}]  # a desk read before this tick's scan can be stale
    for tool in TOOLS:
        if tool == actor:
            continue
        moment = time.time() if now is None else now  # a revive can take minutes: read the clock per tool
        with _lock(project):
            data = load(project)
            row = data["tools"].get(tool)
            if not isinstance(row, dict) or row.get("state") != "FROZEN":
                continue
            if moment < _due_at(row):
                out.append({"tool": tool, "result": "NOT_DUE", "due_at": _due_at(row)})
                continue
            claim = row.get("claim")
            if isinstance(claim, dict) and moment - float(claim.get("at", 0)) < CLAIM_TTL_S:
                out.append({"tool": tool, "result": "CLAIMED", "by": claim.get("by")})  # duplicate revive guard
                continue
            recent = [t for t in row.get("attempt_log") or [] if moment - float(t) < 3600]
            if len(recent) >= MAX_ATTEMPTS_PER_HOUR:
                row["next_attempt_at"] = max(float(row.get("next_attempt_at") or 0), min(recent) + 3600)
                _save(project, data)
                out.append({"tool": tool, "result": "STORM_CAP", "next_attempt_at": row["next_attempt_at"]})
                continue
            attempt_id = uuid.uuid4().hex
            row["claim"] = {"by": actor, "at": moment, "id": attempt_id}
            row["attempt_log"] = recent + [moment]
            adapter = adapters.get(tool)
            baseline_phase = _phase_for_resume(project, tool)
            _save(project, data)
        verified, error = _revive(adapter, project, tool, baseline_phase, sleep)
        moment = time.time() if now is None else now  # the outcome is stamped when it happened, not when the tick began
        thawed = False
        with _lock(project):  # one lock for the whole outcome: no gap where another reviver can claim a half-finished row
            data = load(project)
            row = data["tools"].get(tool) or {}
            mine = isinstance(row.get("claim"), dict) and row["claim"].get("id") == attempt_id
            if not mine or row.get("state") != "FROZEN":
                # a stale attempt (its claim lapsed and another reviver took over, or the tool already thawed) must
                # neither clear the newer claim nor commit its own success over it
                out.append({"tool": tool, "result": "STALE_ATTEMPT", "by": actor})
                continue
            if verified:
                data["tools"][tool] = {"state": "ACTIVE", "thawed_at": moment, "frozen_at": row.get("frozen_at"),
                                       "how": f"revived by {actor}"}
                data["offers"].pop(tool, None)
                _save(project, data)
                log_event(project, "THAWED", moment, tool=tool, how=f"revived by {actor}")
                out.append({"tool": tool, "result": "THAWED", "by": actor})
                thawed = True
            else:
                row["claim"] = None
                row["attempts"] = int(row.get("attempts") or 0) + 1
                delay = min(BACKOFF_BASE_S * 2 ** (row["attempts"] - 1), BACKOFF_CAP_S)
                row["next_attempt_at"] = moment + delay
                result = {"tool": tool, "result": "RETRY", "error": error, "next_attempt_at": row["next_attempt_at"]}
                window_at = row.get("window_at")
                anchor = float(row["reset_at"]) if row.get("reset_known") and row.get("reset_at") is not None else (
                    float(window_at) if isinstance(window_at, (int, float)) and not isinstance(window_at, bool)
                    else float(row.get("frozen_at") or moment))
                if moment - anchor >= REVIVE_DEADLINE_S:
                    # past the deadline: BLOCKED, and the next try is the next reset (one 5 h window later), not a retry loop
                    nxt = anchor + FIVE_HOUR_S * (math.floor((moment - anchor) / FIVE_HOUR_S) + 1)
                    # a predicted window edge is a probe time, not a provider-observed reset: reset_known stays False
                    row.update({"blocked": True, "next_attempt_at": nxt, "attempts": 0, "reset_at": None, "reset_known": False,
                                "window_at": nxt})  # window_at keeps the 5 h phase for the next probe
                    log_event(project, "BLOCKED", moment, tool=tool, reason=f"revive failed past deadline: {error}", wake_at=nxt)
                    result = {"tool": tool, "result": "BLOCKED", "error": error, "wake_at": nxt}
                data["tools"][tool] = row
                _save(project, data)
                out.append(result)
        if thawed:
            _mark_presence(project, tool, "ACTIVE", {}, moment)  # presence has its own lock; the freeze row is already ACTIVE
    return out


def _phase_for_resume(project: Path, tool: str) -> dict[str, Any]:
    """The card the tool owned when it froze, so the revive prompt can name its checkpoint."""
    schedule = _read(_root(project) / SCHEDULE, {})
    for phase in (schedule.get("phases") or []) if isinstance(schedule, dict) else []:
        if not isinstance(phase, dict) or any(str(phase.get(k, "")).upper() == "DONE" for k in ("state", "status")):
            continue
        origin = phase.get("rerouted_from")
        if isinstance(origin, dict) and origin.get("owner_tool") == tool and origin.get("reason") == "FROZEN":
            return {"phase_id": phase.get("phase_id"), "checkpoint": phase.get("resume_from")}
    return {}


def _revive(adapter: Any, project: Path, tool: str, phase: dict[str, Any], sleep: Callable[[float], None]) -> tuple[bool, str]:
    """Resume, then demand a second signal; exit 0 or a returned handle alone is not a revival."""
    if adapter is None:
        return False, "no resume adapter"
    try:
        baseline = adapter.baseline(project)
        adapter.resume(project, phase)
    except Exception as exc:  # noqa: BLE001 - a broken adapter is a retry, not a crash of the peer's watcher
        return False, f"resume failed: {type(exc).__name__}"
    for poll in range(VERIFY_POLLS):
        try:
            if adapter.signal(project, baseline):
                return True, ""
        except Exception as exc:  # noqa: BLE001
            return False, f"signal failed: {type(exc).__name__}"
        if poll < VERIFY_POLLS - 1:
            sleep(VERIFY_POLL_S)
    return False, "no second signal (resume returned but the tool never showed a new heartbeat or turn)"


def _thaw_done(project: Path, tool: str, moment: float, how: str) -> None:
    with _lock(project):
        data = load(project)
        row = data["tools"].get(tool) or {}
        data["tools"][tool] = {"state": "ACTIVE", "thawed_at": moment, "frozen_at": row.get("frozen_at"), "how": how}
        data["offers"].pop(tool, None)
        _save(project, data)
        log_event(project, "THAWED", moment, tool=tool, how=how)
    _mark_presence(project, tool, "ACTIVE", {}, moment)


# ------------------------------------------------------------------ 4. scheduler (zero paid tokens)
def next_wake(project: Path, *, now: float | None = None) -> float | None:
    moment = time.time() if now is None else now
    rows = frozen_tools(project)
    return _earliest_due(rows, moment) if rows else None


def task_name(project: Path) -> str:
    return "UAOS-Thaw-" + hashlib.sha256(str(_root(project).resolve()).encode("utf-8")).hexdigest()[:8]


def _task_when(wake_at: float, now: float | None = None) -> datetime:
    """Minute resolution, never the current or a past minute (a /SC ONCE job in the past fails to register)."""
    moment = time.time() if now is None else now
    return datetime.fromtimestamp(math.ceil(max(wake_at, moment + 60) / 60) * 60)


def task_xml(project: Path, wake_at: float, *, uaos: str | None = None, python: str | None = None,
             now: float | None = None) -> str:
    """Task definition with an ISO StartBoundary: unlike /SD it does not depend on the machine's date format."""
    from xml.sax.saxutils import escape

    runner = uaos or str(Path.home() / ".uaos" / "uaos.py")
    args = f'"{runner}" coord freeze --project "{_root(project)}" --action thaw --actor scheduler'
    start = _task_when(wake_at, now).strftime("%Y-%m-%dT%H:%M:%S")
    return ('<?xml version="1.0" encoding="UTF-16"?>\n<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
            f'<Triggers><TimeTrigger><StartBoundary>{start}</StartBoundary><Enabled>true</Enabled></TimeTrigger></Triggers>'
            '<Settings><StartWhenAvailable>true</StartWhenAvailable></Settings>'
            f'<Actions Context="Author"><Exec><Command>{escape(python or sys.executable)}</Command>'
            f'<Arguments>{escape(args)}</Arguments></Exec></Actions></Task>')


def schtasks_argv(project: Path, wake_at: float, *, uaos: str | None = None, python: str | None = None) -> list[str]:
    """A one-shot Task Scheduler job from an XML definition: runs `uaos coord freeze --action thaw` at wake_at, no model call."""
    return ["schtasks", "/Create", "/F", "/TN", task_name(project), "/XML", str(_root(project) / STATE_DIR / "thaw_task.xml")]


def schedule(project: Path, *, now: float | None = None, runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    wake = next_wake(project, now=now)
    if wake is None:
        return {"scheduled": False, "reason": "nothing frozen"}
    argv = schtasks_argv(project, wake)
    if os.name != "nt":
        return {"scheduled": False, "reason": "Task Scheduler is Windows only; watchers revive instead", "wake_at": wake, "argv": argv}
    xml_path = Path(argv[-1])
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    with _lock(project):  # two ticks must not truncate the definition while schtasks reads it
        xml_path.write_text(task_xml(project, wake, now=now), encoding="utf-16")
        done = runner(argv, capture_output=True, text=True, timeout=30)
    return {"scheduled": getattr(done, "returncode", 1) == 0, "wake_at": wake, "argv": argv}


# ------------------------------------------------------------------ collaboration is the rule (윤겸스 2026-11-20)
# "혼자하지 말고 협업해라 이게 기본이다": no freeze event stays inside one tool. Every takeover, thaw and BLOCKED is
# sent to every other tool as a letter, and a card taken over from a frozen tool closes only on a verdict from a tool
# that is not its author (author != judge, fail closed when no such verdict exists).
Notifier = Callable[[Path, str, str], None]


def deliver_letter(project: Path, target: str, message: str, source: str = "claude") -> None:
    """Default notifier: the real mailbox (`uaos coord deliver`), a local file write, no paid call."""
    uaos = str(Path.home() / ".uaos" / "uaos.py")
    done = subprocess.run([sys.executable, uaos, "coord", "deliver", "--project", str(_root(project)), "--actor", source,
                    "--target", target, "--wake-class", "ACTIONABLE", "--delta", message[:200], "--message", message],
                   capture_output=True, text=True, timeout=60)
    if done.returncode != 0:
        raise RuntimeError(f"deliver exit {done.returncode}")  # tell_peers logs NOTIFY_FAILED instead of counting it sent


def tell_peers(project: Path, source: str, message: str, notifier: Notifier | None) -> list[str]:
    """Letter every other tool; a failing letter never stops the work (it is logged and the loop moves on)."""
    sent = []
    for target in AUTHORITY:
        if target == source or notifier is None:
            continue
        try:
            notifier(project, target, f"[U334 freeze-tag] {message}")
            sent.append(target)
        except Exception as exc:  # noqa: BLE001
            with _lock(project):
                log_event(project, "NOTIFY_FAILED", time.time(), target=target, error=type(exc).__name__)
    return sent


def collab_gate(author: str, verdicts: list[dict[str, Any]]) -> dict[str, Any]:
    """PASS only with a PASS verdict from a tool other than the author; otherwise the card stays open (UNKNOWN)."""
    if author not in TOOLS:
        return {"gate": "OPEN", "reason": "unknown author (fail closed)"}
    judges = [v for v in verdicts if isinstance(v, dict) and v.get("by") in TOOLS and v.get("by") != author]
    if not judges:
        return {"gate": "OPEN", "reason": "no independent verdict (author != judge)"}
    if any(str(v.get("result")).upper() != "PASS" for v in judges):
        return {"gate": "REWORK", "reason": "an independent judge did not pass it"}
    return {"gate": "PASS", "judges": sorted({v["by"] for v in judges})}


# ------------------------------------------------------------------ peer watcher tick + real adapters
def _desk_after_scan(project: Path, desk: dict[str, dict[str, Any]],
                     verdicts: dict[str, dict[str, Any]], moment: float) -> dict[str, dict[str, Any]]:
    """The caller's desk overlaid with this scan: a tool it froze is LIMITED, a tool it self-thawed is ACTIVE."""
    rows = load(project)["tools"]
    fresh = {t: dict(v) for t, v in desk.items() if isinstance(v, dict)}
    for tool in TOOLS:
        verdict = (verdicts.get(tool) or {}).get("verdict")
        row = rows.get(tool) if isinstance(rows.get(tool), dict) else {}
        if verdict == "FROZEN" or row.get("state") == "FROZEN":
            fresh[tool] = {**fresh.get(tool, {}), "state": "LIMITED"}
        elif verdict == "OK" and row.get("state") == "ACTIVE" and row.get("thawed_at") == moment:  # thawed by this scan only
            fresh[tool] = {**fresh.get(tool, {}), "state": "ACTIVE"}
    return fresh


def peer_tick(project: Path, tool: str, adapters: dict[str, Any], *, desk: dict[str, dict[str, Any]],
              home: Path | None = None, now: float | None = None, accounts: dict | None = None,
              sleep: Callable[[float], None] = time.sleep, notifier: Notifier | None = None) -> dict[str, Any]:
    """What one ACTIVE peer's watcher does per beat: scan -> take over -> thaw what is due -> BLOCKED check (fresh desk) -> schedule."""
    moment = time.time() if now is None else now
    verdicts = scan(project, home=home, now=moment, accounts=accounts)
    desk = _desk_after_scan(project, desk, verdicts, moment)  # takeover/thaw must see the freezes and self-thaws scan just made
    moves = [takeover(project, t, desk=desk, now=moment) for t in frozen_tools(project)]
    # thaw first: a revived tool is not "all frozen". It gets the caller's `now` (None in production), not the tick's
    # frozen moment: a revive takes minutes, so thaw_due reads the live clock per tool and per outcome (AGY review U334-F)
    thaw = thaw_due(project, tool, adapters, desk=desk, now=now, sleep=sleep)
    if any(t.get("result") == "THAWED" for t in thaw):
        from .presence import read_all  # the desk read before the thaw is stale: a revived peer is no longer frozen
        desk = read_all(_root(project), now=time.time() if now is None else moment)
    blocked = blocked_check(project, desk=desk, now=time.time() if now is None else moment)
    letters: list[str] = []
    for move in moves:
        if move.get("moved"):
            ids = ",".join(str(m["phase_id"]) for m in move["moved"])
            letters += tell_peers(project, tool, f"cards {ids} moved to {move['owner']} (frozen peer); judge != author", notifier)
    for item in thaw:
        if item.get("result") in ("THAWED", "BLOCKED"):
            letters += tell_peers(project, tool, f"{item['tool']} {item['result']}", notifier)
    if blocked:
        letters += tell_peers(project, tool, f"ALL FROZEN, wake at {blocked['wake_at']}", notifier)
    return {"verdicts": {t: v["verdict"] for t, v in verdicts.items()}, "takeover": moves, "blocked": blocked,
            "thaw": thaw, "letters": letters}


class CommandAdapter:
    """Real resume path of one tool. `baseline` and `signal` read only local files, so verification costs nothing."""

    def __init__(self, tool: str, *, runner: Callable[..., Any] = subprocess.run, session: str | None = None,
                 prompt: str = "U334 thaw: your limit window reset. Read `uaos coord inbox` and continue your cards "
                               "from their checkpoints.") -> None:
        if session and tool != "claude":
            raise ValueError("a named session can only be resumed for claude (fail closed)")
        self.tool, self.runner, self.session, self.prompt = tool, runner, session, prompt
        self.resumed_session: str | None = None  # id the last resume run reported; the only unnamed revival signal

    def baseline(self, project: Path) -> dict[str, Any]:
        from . import presence

        self.resumed_session = None  # a new attempt never inherits the previous run's id
        rec = presence.read(_root(project), self.tool)
        return {"observed_at": rec.get("observed_at"), "sessions": dict(self._sessions(project)),
                "started_at": time.time()}

    def _sessions(self, project: Path) -> dict[str, Any]:
        """Session ids registered in the tool's own heartbeat file (presence.read hides them)."""
        from . import presence

        try:
            rec = json.loads(presence._path(_root(project), self.tool).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        sess = rec.get("sessions") if isinstance(rec, dict) else None
        return sess if isinstance(sess, dict) else {}

    def _turns(self) -> int:
        return 0

    def resume(self, project: Path, phase: dict[str, Any]) -> None:
        text = self.prompt + (f" Resume card {phase['phase_id']} from {phase['checkpoint']}." if phase.get("checkpoint") else "")
        flags = {"capture_output": True, "text": True, "encoding": "utf-8", "errors": "replace", "timeout": RESUME_TIMEOUT_S,
                 "cwd": str(_root(project))}
        if os.name == "nt":
            flags["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        if self.tool == "claude":
            argv = ["claude", "-p", text, "--output-format", "json"] + (["--resume", self.session] if self.session else [])
        elif self.tool == "antigravity":
            argv = ["agy", "-p", text, "--output-format", "json"]
        elif self.tool == "codex":  # headless exec; its recovery is verified by signal(), never by exit code
            argv = ["codex", "exec", "--json", text]
        else:
            raise ValueError(f"unknown tool: {self.tool}")  # fail closed, never fall through to codex
        exe = shutil.which(argv[0])  # Windows .cmd shims are not found by a bare name
        if exe:
            argv[0] = exe
        done = self.runner(argv, **flags)
        if getattr(done, "returncode", 1) != 0:
            raise RuntimeError(f"exit {getattr(done, 'returncode', '?')}")

        self.resumed_session = _run_session_id(getattr(done, "stdout", ""))

    def signal(self, project: Path, baseline: dict[str, Any]) -> bool:
        from . import presence

        rec = presence.read(_root(project), self.tool)
        new_at, old_at = presence._epoch(rec.get("observed_at")), presence._epoch(baseline.get("observed_at"))
        if rec.get("state") != "ACTIVE" or new_at is None:
            return False
        if baseline.get("observed_at") is not None and (old_at is None or new_at <= old_at):
            return False  # must be strictly newer than the pre-resume record (an older ACTIVE is not a signal)
        # correlate with the recovery itself: a heartbeat of the resumed session (named) or of a session id that was
        # not registered before the resume; an older session's routine heartbeat is not evidence
        live = self._sessions(project)
        before = baseline.get("sessions") or {}
        if self.session:  # the named session's own expiry stamp must have advanced (observed_at is tool-wide)
            now_stamp, old_stamp = live.get(self.session), before.get(self.session, 0)
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (now_stamp, old_stamp)):
                return False  # None / non-numeric stamp: fail closed
            return float(now_stamp) > float(old_stamp)
        sid = self.resumed_session  # only the session this resume run reported counts, never any new session
        if not sid or sid in before:
            return False
        stamp = live.get(sid)
        return isinstance(stamp, (int, float)) and not isinstance(stamp, bool) and math.isfinite(stamp) and stamp > 0


def default_adapters(runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    return {t: CommandAdapter(t, runner=runner) for t in TOOLS}


def main(project: Path, action: str, actor: str = "scheduler", *, now: float | None = None) -> dict[str, Any]:
    from .presence import read_all

    if actor != "scheduler" and actor not in TOOLS:
        raise ValueError(f"unknown actor: {actor}")
    moment = time.time() if now is None else now
    desk = read_all(_root(project), now=moment)
    if action == "scan":
        return {"verdicts": scan(project, now=moment)}
    if action == "status":
        return {"tools": load(project)["tools"], "wake_at": next_wake(project, now=moment)}
    if action == "schedule":
        return schedule(project, now=moment)
    if action == "thaw":
        if actor != "scheduler":
            res = peer_tick(project, actor, default_adapters(), desk=desk, now=now,  # live clocks downstream (U334-F)
                            notifier=functools.partial(deliver_letter, source=actor))
        else:
            res = {"thaw": thaw_due(project, "scheduler", default_adapters(), desk=desk, now=now)}
            res["blocked"] = blocked_check(project, desk=read_all(_root(project), now=time.time() if now is None else moment),
                                           now=time.time() if now is None else moment)  # clear/refresh BLOCKED after the thaw
        res["schedule"] = schedule(project, now=time.time() if now is None else moment)  # thaw may have taken minutes
        return res
    raise ValueError(f"unknown action: {action}")


def _run_session_id(stdout: Any) -> str | None:
    """Session id the resume run itself reports (claude/agy JSON `session_id`, codex --json `thread_id`)."""
    for line in [str(stdout or "")] + str(stdout or "").splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            sid = obj.get("session_id") or obj.get("thread_id")
            if isinstance(sid, str) and sid:
                return sid
    return None
