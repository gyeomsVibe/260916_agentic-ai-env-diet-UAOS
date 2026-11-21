"""U329: no infinite wait. Every wait has a deadline and a fallback; silence is an abstention, never a veto.

Receipt (2026-11-20): this session's Antigravity auto-answer could not run tools and answered BLOCKED forever, and
Codex was marked ACTIVE yet idle for 700 h. A flow that waits for every peer's reply therefore never ends (U166 stall.py
rerouted only when every ACTIVE tool had agreed). Rule, designed from the coldest case (every peer silent):

* wait only for a peer whose presence is ACTIVE *and* whose signal is fresh (`FRESH_SIGNAL_S`); the others abstain
  up front, before anything is sent;
* every wait carries a deadline: ACK 10 s (a watcher answers it with no model), content `REPLY_DEADLINE_S`;
* with zero responders the conductor decides alone and the decision is marked for re-review;
* waits are asynchronous: a caller records one and returns, it never sleeps on it;
* a cycle in the wait graph (A waits on B, B on A) is broken in authority order Codex -> Claude -> Antigravity;
* PUBLISHED is not ACK: no ACK in time tries the next path once, then the peer abstains;
* the same failure cause on the same path 3 times -> that path is BLOCKED for the card.

Values and why: 10 s ACK = a deterministic watcher needs no LLM turn; 120 s reply = one LLM turn takes tens of
seconds to minutes (spec 9.4-1, UNMEASURED, adjust from the ledger); 60 s signal = presence beats arrive per turn.
No model is called anywhere here.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from .presence import SUCCESSION, TOOLS

ACK_DEADLINE_S = 10
REPLY_DEADLINE_S = 120
FRESH_SIGNAL_S = 60
MAX_SAME_CAUSE_FAILURES = 3
# Path order for re-sending a letter that was PUBLISHED but never ACKed (spec 9.4 item 6): letter, open the window,
# then a different tool carries it.
DELIVERY_PATHS = ("letter", "window", "other_tool")
WAIT_DIR = Path(".coord") / "stall"
GRAPH = WAIT_DIR / "wait_graph.json"
FAILURES = WAIT_DIR / "wait_failures.json"


def signal_age(record: dict[str, Any] | None, now: float) -> float | None:
    """Seconds since the tool's last presence beat; None when the record carries no readable observation time.
    Live `presence.mark()` writes an ISO-8601 string; numeric epochs (tests, other writers) are accepted too."""
    from .presence import _epoch

    observed = (record or {}).get("observed_at")
    if isinstance(observed, str):
        observed = _epoch(observed)
    if isinstance(observed, bool) or not isinstance(observed, (int, float)):
        return None
    return max(0.0, now - float(observed))


def peer_alive(record: dict[str, Any] | None, now: float, *, fresh_s: float = FRESH_SIGNAL_S) -> bool:
    """True only for ACTIVE with a fresh signal. An unknown age fails closed: no evidence of life, no waiting."""
    if (record or {}).get("state") != "ACTIVE":
        return False
    age = signal_age(record, now)
    return age is not None and age <= fresh_s


def conductor_of(desk: dict[str, dict[str, Any]]) -> str:
    """The conductor under the global authority rules (`presence.conductor`): Codex while ACTIVE, else Claude, else
    Antigravity. Fails closed: with nobody ACTIVE, or an expired heartbeat before an ACTIVE tool, it returns "none"."""
    from .presence import conductor

    name = conductor(desk)["conductor"]
    return name if name in TOOLS else "none"


def plan_wait(desk: dict[str, dict[str, Any]], asker: str, now: float, *,
              deadline_s: float = REPLY_DEADLINE_S, fresh_s: float = FRESH_SIGNAL_S) -> dict[str, Any]:
    """Before sending: who is worth waiting for, who abstains now, when the wait ends and what happens then."""
    peers = [t for t in TOOLS if t != asker]
    wait_for = [t for t in peers if peer_alive(desk.get(t), now, fresh_s=fresh_s)]
    return {"asker": asker, "wait_for": wait_for, "abstain": [t for t in peers if t not in wait_for],
            "started": now, "deadline": now + deadline_s,
            "fallback": "decide_with_responders" if wait_for else "conductor_decides_alone"}


def settle(plan: dict[str, Any], replied: list[str], now: float) -> dict[str, Any]:
    """Whether the wait is over. Over = every awaited peer replied, or the deadline passed (silence = abstain)."""
    replied_set = set(replied) & set(plan["wait_for"])
    complete = replied_set == set(plan["wait_for"])
    expired = now >= plan["deadline"]
    silent = sorted(set(plan["wait_for"]) - replied_set) if (complete or expired) else []
    return {"done": complete or expired, "responders": sorted(replied_set),
            "abstained": sorted(set(plan["abstain"]) | set(silent)),
            "zero_responders": (complete or expired) and not replied_set}


# ---- wait graph: cycles broken by authority order -------------------------------------------------------------

def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return default


REPLACE_TRIES = 6  # Windows os.replace fails with PermissionError while a reader holds the target; 6 x 0.02-0.12 s


def replace_retry(src: Path, dst: Path) -> None:
    """os.replace with a short retry on Windows sharing violations (AGY re-audit P2)."""
    for attempt in range(REPLACE_TRIES):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == REPLACE_TRIES - 1:
                raise
            time.sleep(0.02 * (attempt + 1))


def safe_name(value: str) -> str:
    """A file-name-safe form of an externally supplied id (no separators, no `..`, no Windows-reserved characters)."""
    import re

    cleaned = re.sub(r"\.{2,}", "_", re.sub(r"[^A-Za-z0-9._-]", "_", str(value))).strip(".") or "_"
    return cleaned[:80]


def atomic_write_text(path: Path, text: str) -> None:
    """Write via a unique temp file and an atomic replace; the temp file never outlives a failure (AGY re-audit 4)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:6]}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        replace_retry(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _write_atomic(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True))


def find_cycle(edges: list[dict[str, Any]]) -> list[str]:
    """One cycle of waiters (e.g. ['claude', 'codex']) or []. Edges: {waiter, on}."""
    nxt: dict[str, set[str]] = {}
    for e in edges:
        nxt.setdefault(e["waiter"], set()).add(e["on"])
    for start in sorted(nxt):
        stack = [(start, [start])]
        while stack:
            node, path = stack.pop()
            for follow in sorted(nxt.get(node, ())):
                if follow == start:
                    return path
                if follow not in path:
                    stack.append((follow, path + [follow]))
    return []


def add_wait(project: Path, waiter: str, on: str, reason: str, *, now: float,
             deadline_s: float = REPLY_DEADLINE_S) -> dict[str, Any]:
    """Record that `waiter` waits on `on` until the deadline. Returns the edge plus the cycle break, if any."""
    from .stream import _exclusive

    project = Path(project)
    with _exclusive(project / WAIT_DIR / "wait_graph.lock"):
        edges = [e for e in _read(project / GRAPH, []) if isinstance(e, dict) and e.get("deadline", 0) > now]
        edge = {"waiter": waiter, "on": on, "reason": reason, "since": now, "deadline": now + deadline_s}
        edges = [e for e in edges if (e["waiter"], e["on"]) != (waiter, on)] + [edge]
        broken = None
        for _ in range(len(edges) + 1):  # one edge can close several cycles: break until the graph is acyclic
            cycle = find_cycle(edges)
            if not cycle:
                break
            # The highest-authority member stops waiting and decides: authority order is the tie-break.
            winner = min(cycle, key=lambda t: SUCCESSION.index(t) if t in SUCCESSION else len(SUCCESSION))
            edges = [e for e in edges if not (e["waiter"] == winner and e["on"] in cycle)]
            broken = broken or {"cycle": cycle, "released": winner, "rule": "authority order codex>claude>antigravity"}
        _write_atomic(project / GRAPH, edges)
    return {"edge": edge, "broken": broken}


def clear_wait(project: Path, waiter: str, on: str) -> None:
    from .stream import _exclusive

    project = Path(project)
    with _exclusive(project / WAIT_DIR / "wait_graph.lock"):
        edges = [e for e in _read(project / GRAPH, []) if (e.get("waiter"), e.get("on")) != (waiter, on)]
        _write_atomic(project / GRAPH, edges)


# ---- PUBLISHED != ACK, and same-cause failures -----------------------------------------------------------------

def delivery_state(published_at: float | None, acked_at: float | None, now: float, *,
                   tried: tuple[str, ...] = ("letter",), ack_s: float = ACK_DEADLINE_S) -> dict[str, Any]:
    """PUBLISHED is not read. No ACK by the deadline: switch to the next path once; paths used up -> abstain."""
    if acked_at is not None:
        return {"state": "ACKED", "next": None}
    if published_at is None:
        return {"state": "NOT_SENT", "next": DELIVERY_PATHS[0]}
    if now - published_at < ack_s:
        return {"state": "PUBLISHED", "next": None}
    remaining = [p for p in DELIVERY_PATHS if p not in tried]
    return {"state": "ACK_OVERDUE", "next": remaining[0] if remaining else None,
            "abstain": not remaining}


def record_wait_failure(project: Path, card: str, path: str, cause: str, *, now: float) -> dict[str, Any]:
    """Count a failed wait per (card, path, cause); the 3rd identical one blocks that path for the card."""
    from .stream import _exclusive

    project = Path(project)
    key = json.dumps([card, path, cause], ensure_ascii=False)  # no delimiter collision
    with _exclusive(project / WAIT_DIR / "wait_failures.lock"):
        data = _read(project / FAILURES, {})
        row = data.get(key) or {"count": 0}
        row.update(count=row["count"] + 1, last=now)
        row["blocked"] = row["count"] >= MAX_SAME_CAUSE_FAILURES
        data[key] = row
        _write_atomic(project / FAILURES, data)
    return {"key": key, **row, "log": "BLOCKED" if row["blocked"] else "RETRY"}


def path_blocked(project: Path, card: str, path: str) -> bool:
    data = _read(Path(project) / FAILURES, {})
    prefix = json.dumps([card, path], ensure_ascii=False)[:-1] + ", "  # '["card", "path", ' -> exact (card, path) match
    return any(k.startswith(prefix) and v.get("blocked") for k, v in data.items() if isinstance(v, dict))


def now_s() -> float:
    return time.time()


# ---- optimistic progress (spec 9.4-2 priority 2): send, checkpoint, keep going --------------------------------------
OPTIMISTIC = WAIT_DIR / "optimistic.json"


def send_optimistic(project: Path, card: str, step: str, peer: str, checkpoint_ref: str, *, now: float) -> dict[str, Any]:
    """After sending to `peer`, never enter a waiting state: record the checkpoint (a commit/snapshot the caller made
    at this step) and return at once so the caller continues with its own best plan. Nothing here can block."""
    from .stream import _exclusive

    project = Path(project)
    with _exclusive(project / WAIT_DIR / "optimistic.lock"):
        data = _read(project / OPTIMISTIC, {})
        data[f"{card}|{step}"] = {"card": card, "step": step, "peer": peer, "checkpoint": checkpoint_ref,
                                  "sent_at": now, "state": "OPEN"}
        _write_atomic(project / OPTIMISTIC, data)
    return {"continue": True, "waiting": False, "checkpoint": checkpoint_ref}


def late_reply_outcome(project: Path, card: str, step: str, *, improves: bool, now: float) -> dict[str, Any]:
    """A late reply goes through adoption: if the receiver judged it better, roll back to that step's checkpoint and
    redo from there; otherwise it is only recorded. The caller performs the rollback; this names the ref."""
    from .stream import _exclusive

    project = Path(project)
    key = f"{card}|{step}"
    with _exclusive(project / WAIT_DIR / "optimistic.lock"):
        data = _read(project / OPTIMISTIC, {})
        row = data.get(key)
        if not row:
            return {"rollback_to": None, "why": "unknown step"}
        row.update(state="ROLLBACK" if improves else "KEPT", replied_at=now)
        _write_atomic(project / OPTIMISTIC, data)
    return {"rollback_to": row["checkpoint"] if improves else None, "why": "adopted" if improves else "not better"}


def open_waits(project: Path, card: str) -> list[str]:
    """Steps still flagged OPEN. They never block anything: this is a ledger, not a wait."""
    data = _read(Path(project) / OPTIMISTIC, {})
    return [v["step"] for v in data.values() if v.get("card") == card and v.get("state") == "OPEN"]
