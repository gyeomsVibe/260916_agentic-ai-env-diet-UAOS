"""U329: mid-card message triage and flood control, for all three tools.

A tool in the middle of a card reads its inbox only at a safe checkpoint (between plan/execute/verify, before a
commit), in one batch, and sorts every message into P0 / ADOPT / DEFER / ACK. Priority is dynamic: a peer's better idea
is adopted when the *receiver* finds it beats the card's fixed acceptance or cuts cost at equal quality (author != judge),
inside an adoption budget (1 pivot per card, <=20 % of remaining budget, >=80 % progress small fixes only).
User messages are different (spec 6-1): always P0, kept verbatim, forwarded to the other two tools before acting, and
exempt from rate limit, merging, freeze and the pivot cap.

Flood control (spec 6): per-sender 3 ADOPT / 10 min; digest dedupe and same-topic merge; circuit breaker above 10 peer
messages / 10 min freezes everything but P0 until 15 quiet minutes; a reply to a reply never preempts; conflicting
proposals go to the conductor, never both adopted; queue cap 50 that never drops P0, ADOPT or user messages.
The numbers are starting values (spec 6, last line): savings UNMEASURED until the ledger compares runs.

The log is one JSONL file per (receiver, card), appended under the OS file lock from `stream._exclusive`, because on
Windows concurrent `O_APPEND` writes lose lines. Triage is a pure function of the log plus `now`, so it replays the same
way in every process and tests need no sleeping. No model is called.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from . import nowait
from .presence import TOOLS

TRIAGE_DIR = Path(".coord") / "triage"
WINDOW_S = 600                 # 10 min: spec 6-3/6-4 window
SENDER_ADOPT_LIMIT = 3         # per sender per window
BREAKER_LIMIT = 10             # more than this many peer messages per window freezes the card's inbox
QUIET_S = 900                  # 15 quiet minutes unfreeze
QUEUE_CAP = 50
ADOPT_COST_MAX_PCT = 20.0      # adoption cost share of the remaining card budget
LATE_PROGRESS = 0.8            # at or after this progress only small fixes are adopted
MAX_PIVOTS = 1                 # big direction changes per card (user requests excluded)
P0_TAGS = frozenset({"SAFETY", "SECURITY", "FILE_CONFLICT"})
STOP_RE = re.compile(r"즉시\s*중단|stop now|halt now", re.IGNORECASE)


def _paths(project: Path, to: str, card: str) -> tuple[Path, Path, Path, Path]:
    from .nowait import safe_name

    to, card = safe_name(to), safe_name(card)  # externally supplied ids never reach the file system raw
    base = Path(project) / TRIAGE_DIR / to
    return (base / f"{card}.jsonl", base / f"{card}.lock", base / f"{card}.state.json", base / f"{card}.archive.jsonl")


def digest(text: str) -> str:
    return hashlib.sha1(" ".join(str(text).lower().split()).encode("utf-8")).hexdigest()[:16]


def _lock(project: Path, to: str, card: str):
    from .stream import _exclusive

    return _exclusive(_paths(project, to, card)[1])


KEY_BYTES = 32


def _key_file(project: Path) -> Path:
    """The signing key lives OUTSIDE the workspace (the user's home, one file per project path), so a peer that can only
    read/write the repo cannot read it. `UAOS_TRIAGE_KEY_DIR` overrides the directory (tests, other hosts)."""
    root = os.environ.get("UAOS_TRIAGE_KEY_DIR") or str(Path.home() / ".uaos" / "triage_keys")
    tag = hashlib.sha256(str(Path(project).resolve()).encode("utf-8")).hexdigest()[:24]
    return Path(root) / f"{tag}.key"


def _key(project: Path) -> bytes:
    key_file = _key_file(project)
    for _ in range(3):
        try:
            key = key_file.read_bytes()
            if len(key) == KEY_BYTES:
                return key
        except OSError:
            pass
        key_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = key_file.with_name(f"{key_file.name}.{os.getpid()}.{os.urandom(3).hex()}.tmp")
        try:
            tmp.write_bytes(os.urandom(KEY_BYTES))  # complete before it is visible: no reader sees an empty key
            try:
                os.link(tmp, key_file)  # atomic publish; FileExistsError = another process won the race, read theirs
            except FileExistsError:
                pass
            except OSError:  # no hard links on this filesystem: fall back to exclusive create of the full content
                try:
                    with open(key_file, "xb") as fh:
                        fh.write(tmp.read_bytes())
                except FileExistsError:
                    pass
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass
    raise OSError("triage signing key unavailable")


def _mac(project: Path, domain: str, mid: str, text: str, card: str) -> str:
    """HMAC over a length-safe JSON tuple: the domain tag separates `auth` from `origin`, and no field can swallow another."""
    payload = json.dumps([domain, mid, text, card], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hmac.new(_key(project), payload, hashlib.sha256).hexdigest()


def user_auth(project: Path, mid: str, text: str, card: str = "") -> str:
    """Provenance stamp of a user message, bound to its id, text AND destination card (no replay into another card)."""
    return _mac(project, "auth", mid, text, card)


def origin_proof_for(project: Path, event_id: str, text: str, card: str = "") -> str:
    """What the native host path attaches to an event it authenticated; a different domain than `user_auth`."""
    return _mac(project, "origin", event_id, text, card)


def submit(project: Path, to: str, card: str, message: dict[str, Any]) -> dict[str, Any]:
    """Append one message to `to`'s inbox for `card`. Never wakes the receiver; it is read at its next checkpoint."""
    for key in ("id", "sender", "text"):
        if not message.get(key):
            raise ValueError(f"message needs {key}")
    record = {"ts": time.time(), "kind": "peer", **message, "to": to, "card": message.get("card") or card}
    if record["kind"] == "user":
        if hmac.compare_digest(str(record.get("auth", "")),
                               user_auth(project, record["id"], record["text"], str(card))):
            record.pop("auth", None)  # verified once at the door; the stamp is never stored, so it cannot be replayed
        else:
            # Codex R1 boundary 1: a peer cannot claim the user's authority. Unauthenticated -> an ordinary peer message,
            # stripped of every field that could still grant P0 (flags, tags).
            for key in ("p0", "exempt", "auth", "tags"):
                record.pop(key, None)
            record.update(kind="peer", spoofed_user=True)
    record["digest"] = digest(record["text"])
    line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
    log = _paths(project, to, card)[0]
    log.parent.mkdir(parents=True, exist_ok=True)
    with _lock(project, to, card):
        with open(log, "ab") as fh:
            fh.write(line.encode("utf-8"))
            fh.flush()
            os.fsync(fh.fileno())
    return record


def load(project: Path, to: str, card: str) -> list[dict[str, Any]]:
    """All messages by (ts, id); a repeated id (re-delivery) counts once, a torn last line is skipped."""
    log = _paths(project, to, card)[0]
    try:
        raw = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    seen: dict[str, dict[str, Any]] = {}
    for line in raw.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("id") and rec["id"] not in seen:
            seen[rec["id"]] = rec
    return sorted(seen.values(), key=lambda r: (float(r.get("ts", 0)), str(r["id"])))


def _state(project: Path, to: str, card: str) -> dict[str, Any]:
    try:
        data = json.loads(_paths(project, to, card)[2].read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(project: Path, to: str, card: str, state: dict[str, Any]) -> None:
    nowait.atomic_write_text(_paths(project, to, card)[2], json.dumps(state, ensure_ascii=False, sort_keys=True))


def breaker(messages: list[dict[str, Any]], now: float) -> dict[str, Any]:
    """Replay the circuit breaker. User messages are exempt and never counted. Returns per-id frozen flag + state now."""
    times: list[float] = []
    frozen = False
    last = None
    frozen_at: dict[str, bool] = {}
    entered = None
    for m in messages:
        if m.get("kind") == "user":
            frozen_at[m["id"]] = False
            continue
        ts = float(m.get("ts", 0))
        if frozen and last is not None and ts - last >= QUIET_S:
            frozen = False
        times = [t for t in times if ts - t < WINDOW_S] + [ts]
        if not frozen and len(times) > BREAKER_LIMIT:
            frozen, entered = True, ts
        last = ts
        frozen_at[m["id"]] = frozen
    if frozen and last is not None and now - last >= QUIET_S:
        frozen = False
    return {"frozen_now": frozen, "per_id": frozen_at, "entered_at": entered if frozen else None}


def triage(project: Path, to: str, card: str, *, now: float, progress: float = 0.0,
           card_files: tuple[str, ...] = (), acceptance: tuple[str, ...] = ()) -> dict[str, Any]:
    """Classify the whole inbox in one batch. Earlier decisions stay (monotonic); only new messages are decided."""
    with _lock(project, to, card):
        msgs = load(project, to, card)
        state = _state(project, to, card)
        decided: dict[str, dict[str, Any]] = state.get("decisions", {})
        pivots = int(state.get("pivots", 0))
        br = breaker(msgs, now)
        by_id = {m["id"]: m for m in msgs}
        first_digest: dict[str, str] = {}
        adopt_times: dict[str, list[float]] = {}
        for m in msgs:
            ts = float(m.get("ts", 0))
            old = decided.get(m["id"])
            d = old if old else _decide(m, by_id, first_digest, adopt_times, br, progress, pivots,
                                        card, card_files, acceptance)
            if m.get("kind") != "user" and d["class"] in ("ADOPT", "P0"):
                # only a message that actually carries the idea suppresses later copies; an ACK/DEFER must not (AGY)
                first_digest.setdefault(f"{m.get('kind')}|{m['digest']}", m["id"])
            if d["class"] == "ADOPT":
                adopt_times.setdefault(m["sender"], []).append(ts)
            if not old:
                decided[m["id"]] = d
        _mark_conflicts(msgs, decided)
        state.update(decisions=decided, pivots=pivots)
        _save_state(project, to, card, state)
        archived = _compact(project, to, card, msgs, decided)
    counts: dict[str, int] = {}
    for m in msgs:
        counts[decided[m["id"]]["class"]] = counts.get(decided[m["id"]]["class"], 0) + 1
    return {"decisions": {m["id"]: decided[m["id"]] for m in msgs}, "counts": counts, "frozen": br["frozen_now"],
            "interrupt_now": [m["id"] for m in msgs if decided[m["id"]]["class"] == "P0"
                              and decided[m["id"]].get("immediate")],
            "escalate": [i for i, d in decided.items() if d["class"] == "ESCALATE"],
            "pending": len(msgs) - archived, "archived": archived}


def _decide(m, by_id, first_digest, adopt_times, br, progress, pivots, card, card_files, acceptance):
    ts = float(m.get("ts", 0))
    if m.get("kind") == "user":
        # Spec 6-1 as corrected by 9.7-1: the desk router (card U332) takes user messages first. Inside a card session
        # a user message is a P0 interrupt only when it is "stop" or targets this card's own scope/files; a scope change
        # is applied at the next safe checkpoint through adoption (not at once), anything else lets the card finish.
        # Always verbatim and exempt from rate limit / merge / freeze / pivot cap.
        stop = bool(STOP_RE.search(m["text"]))
        mine = (m.get("card") == card or bool(set(m.get("files") or ()) & set(card_files))
                or bool(set(m.get("acceptance") or ()) & set(acceptance)))
        if stop or mine:
            return {"class": "P0", "why": "user: stop" if stop else "user: this card's scope", "immediate": stop,
                    "exempt": True}
        return {"class": "DEFER", "why": "user, other scope: desk router owns it; card continues", "exempt": True}
    key = f"{m.get('kind')}|{m['digest']}"
    p0 = bool(m.get("p0")) or bool(P0_TAGS & set(m.get("tags") or ()))
    if p0:  # Codex R1: a safety event is routed before the duplicate check, never merged away as a repeat
        return {"class": "P0", "why": "safety/conflict", "immediate": True}
    if key in first_digest:
        return {"class": "ACK", "why": "duplicate", "merged_into": first_digest[key]}
    if br["per_id"].get(m["id"]):
        return {"class": "DEFER", "why": "frozen: breaker open, P0 only"}
    parent = by_id.get(m.get("reply_to") or "")
    if m.get("reply_to") and parent is not None and parent.get("reply_to"):
        return {"class": "ACK", "why": "reply-to-reply never preempts"}
    related = (m.get("card") == card or bool(set(m.get("files") or ()) & set(card_files))
               or bool(set(m.get("acceptance") or ()) & set(acceptance)))
    if not related:
        return {"class": "ACK", "why": "unrelated"}
    if not m.get("evidence"):
        return {"class": "DEFER", "why": "no evidence"}
    if float(m.get("cost_pct", 0)) > ADOPT_COST_MAX_PCT:
        return {"class": "DEFER", "why": f"cost over {ADOPT_COST_MAX_PCT:g}% of remaining budget"}
    if progress >= LATE_PROGRESS and not m.get("small"):
        return {"class": "DEFER", "why": "late: only small fixes"}
    if m.get("pivot") and pivots >= MAX_PIVOTS:
        return {"class": "DEFER", "why": "pivot cap reached"}
    recent = [t for t in adopt_times.get(m["sender"], []) if ts - t < WINDOW_S]
    if len(recent) >= SENDER_ADOPT_LIMIT:
        return {"class": "DEFER", "why": "sender rate limit"}
    return {"class": "ADOPT", "why": "candidate"}


def _mark_conflicts(msgs, decided) -> None:
    """Opposing ADOPT candidates go to the conductor together; neither is adopted. Every rule reads the same
    pre-escalation snapshot (so one message may clash with several), and an already adopted message is final."""
    open_ids = {m["id"] for m in msgs if decided[m["id"]]["class"] == "ADOPT" and not decided[m["id"]].get("adopted")}
    topics: dict[str, list[dict[str, Any]]] = {}
    for m in msgs:
        if m["id"] in open_ids and m.get("topic"):
            topics.setdefault(m["topic"], []).append(m)
    clash: set[str] = set()
    for group in topics.values():
        if len({str(m.get("stance", "")) for m in group}) > 1:
            clash.update(m["id"] for m in group)
    for m in msgs:
        for other in m.get("conflicts_with") or ():
            if m["id"] in open_ids and other in open_ids:
                clash.update((m["id"], other))
    for mid in clash:
        decided[mid] = {"class": "ESCALATE", "why": "conflicting proposals → conductor"}  # one dict per id, no aliasing


def _compact(project, to, card, msgs, decided) -> int:
    """Queue cap 50: archive the oldest decided ACK/DEFER entries; P0, ADOPT, ESCALATE and user messages stay."""
    if len(msgs) <= QUEUE_CAP:
        return 0
    droppable = [m for m in msgs if decided[m["id"]]["class"] in ("ACK", "DEFER") and m.get("kind") != "user"]
    drop = droppable[: len(msgs) - QUEUE_CAP]
    if not drop:
        return 0
    log, _, _, archive = _paths(project, to, card)
    dropped = {m["id"] for m in drop}
    with open(archive, "ab") as fh:
        for m in drop:
            fh.write((json.dumps({**m, "decision": decided[m["id"]]}, ensure_ascii=False) + "\n").encode("utf-8"))
    keep = [m for m in msgs if m["id"] not in dropped]
    nowait.atomic_write_text(log, "".join(json.dumps(m, ensure_ascii=False, sort_keys=True) + "\n" for m in keep))
    return len(dropped)


def judge_adoption(project: Path, receiver: str, card: str, msg_id: str, *, acceptance_gain: bool = False,
                   cost_saving_same_quality: bool = False, pivot: bool = False) -> dict[str, Any]:
    """The receiver judges an ADOPT candidate against fixed acceptance and cost; the sender never judges its own."""
    with _lock(project, receiver, card):
        state = _state(project, receiver, card)
        decided = state.get("decisions", {})
        msg = next((m for m in load(project, receiver, card) if m["id"] == msg_id), None)
        if msg is None or msg_id not in decided:
            return {"adopted": False, "why": "unknown message"}
        if msg["sender"] == receiver:
            return {"adopted": False, "why": "author must not judge"}
        if decided[msg_id].get("adopted"):  # idempotent: a repeat call never re-counts a pivot or downgrades it
            return {"adopted": True, "why": "already adopted", "repeat": True}
        if msg.get("kind") == "user":
            # A user direction is a requirement, not an evidence contest; recorded as its own pivot, uncapped. Only a
            # record that passed the origin check at `submit` can still be kind=user (a forgery is demoted to peer).
            state["user_pivots"] = int(state.get("user_pivots", 0)) + (1 if pivot else 0)
            decided[msg_id] = {**decided[msg_id], "adopted": True}
            result = {"adopted": True, "why": "user directive", "user_pivot": pivot}
        elif decided[msg_id]["class"] != "ADOPT":
            result = {"adopted": False, "why": f"class {decided[msg_id]['class']}"}
        elif not (acceptance_gain or cost_saving_same_quality):
            decided[msg_id] = {"class": "DEFER", "why": "no acceptance gain or saving"}
            result = {"adopted": False, "why": "no acceptance gain or saving"}
        elif pivot and int(state.get("pivots", 0)) >= MAX_PIVOTS:
            decided[msg_id] = {"class": "DEFER", "why": "pivot cap reached"}
            result = {"adopted": False, "why": "pivot cap reached"}
        else:
            state["pivots"] = int(state.get("pivots", 0)) + (1 if pivot else 0)
            decided[msg_id] = {**decided[msg_id], "adopted": True}
            result = {"adopted": True, "why": "acceptance gain" if acceptance_gain else "cost saving"}
        state["decisions"] = decided
        _save_state(project, receiver, card, state)
        ledger = _paths(project, receiver, card)[0].with_suffix(".ledger.jsonl")  # same sanitized resolver as the log
        with open(ledger, "ab") as fh:
            fh.write((json.dumps({"id": msg_id, "sender": msg["sender"], **result, "ts": time.time()},
                                 ensure_ascii=False) + "\n").encode("utf-8"))
    return result


def receive_user_message(project: Path, receiver: str, card: str, text: str, *, msg_id: str | None = None,
                         ts: float | None = None, native_event_id: str | None = None,
                         confidential: bool = False, origin_proof: str | None = None) -> dict[str, Any]:
    """A user request. Codex R1 (relay_2a77fc7a): the receiver's own durable record is written FIRST, so a stop applies
    at the earliest safe boundary and nothing waits on a peer, a council or a forward. Then the peers are informed:
    verbatim and identically keyed (native event id, so two tools relaying one event execute once), or - when the
    content is `confidential` - an opaque reference that keeps the text at its origin. A forward never raises."""
    moment = time.time() if ts is None else ts
    mid = native_event_id or msg_id or f"user-{digest(text)}-{int(moment)}"
    record = {"id": mid, "sender": "user", "kind": "user", "text": text, "ts": moment, "p0": True}
    # Codex R1: user authority needs an authenticated origin proof from the host path. Without a valid proof the
    # record carries no stamp, so `submit` demotes it to an ordinary peer message (unresolved origin = no authority).
    verified = origin_proof is not None and hmac.compare_digest(
        str(origin_proof), origin_proof_for(project, mid, text, str(card)))
    if verified:
        record["auth"] = user_auth(project, mid, text, str(card))
    submit(project, receiver, card, record)  # 1. the receiver's durable lane, before any forwarding
    notice = f"[user directive {mid}: content held at origin ({receiver}); ask the origin for it]"
    forwarded = []
    for tool in (t for t in TOOLS if t != receiver):  # 2. best-effort; a failure here never delays the receiver
        sent = {**record, "forwarded_by": receiver}
        if confidential:
            sent.update(text=notice, opaque_ref=mid)
            sent.pop("auth", None)
            if verified:  # a stamp is minted only for an origin-verified event; otherwise the copy is demoted too
                sent["auth"] = user_auth(project, mid, notice, str(card))
        try:
            submit(project, tool, card, sent)
            forwarded.append(tool)
        except OSError:
            continue
    return {"id": mid, "forwarded_to": forwarded, "opaque": confidential}
