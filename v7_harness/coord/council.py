"""U329: directive council. A user directive that changes direction, design or priority opens a 3-tool debate first.

Flow (spec 9.2-9.4): open (verbatim text) -> round 1 independent drafts (hidden from each other) -> round 2 one critique
each -> decide -> ADR in `.coord/decisions/<ID>.md`. Decision: policy/knowledge topics by 2/3 agreement among the
responders, code/reasoning topics by evidence (most fixed-acceptance gates passed), ties and deadlocks by the conductor
(Codex while ACTIVE, else Claude). Early stop: all round-1 positions equal -> decide at once, no round 2.
Limits: one council per topic (a same-topic directive joins it), at most 2 open (more wait QUEUED), 30 min overall.

No infinite wait (spec 9.4, `nowait`): peers that are not ACTIVE with a fresh signal abstain *when the council opens*;
each round has a deadline; silence is an abstention; zero responders -> the conductor decides alone and the ADR is marked
`re_review`; a reply after the deadline is only an adoption candidate (`late_reply` -> msg_triage), never a reversal.
`advance` is a pure state step taking `now`; nothing sleeps except the optional `drive` loop used by a caller that
chooses to block, and that loop is bounded by the council's own deadlines.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from . import msg_triage, nowait
from .presence import TOOLS

COUNCIL_DIR = Path(".coord") / "council"
DECISIONS_DIR = Path(".coord") / "decisions"
MAX_OPEN = 2                 # three tools debating 3+ topics at once stops card progress (spec 9.3)
COUNCIL_MAX_S = 1800         # 30 min hard ceiling (spec 9.2-6)
ROUND_DEADLINE_S = nowait.REPLY_DEADLINE_S
OPEN_STATES = ("ROUND1", "ROUND2")
KINDS = ("policy", "code")


def _lock(project: Path):
    from .stream import _exclusive

    return _exclusive(Path(project) / COUNCIL_DIR / "council.lock")


def _file(project: Path, cid: str) -> Path:
    return Path(project) / COUNCIL_DIR / f"{nowait.safe_name(cid)}.json"


def _read(project: Path, cid: str) -> dict[str, Any] | None:
    try:
        return json.loads(_file(project, cid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(project: Path, rec: dict[str, Any]) -> None:
    path = _file(project, rec["id"])
    nowait.atomic_write_text(path, json.dumps(rec, ensure_ascii=False, indent=1, sort_keys=True))


def _all(project: Path) -> list[dict[str, Any]]:
    root = Path(project) / COUNCIL_DIR
    out = []
    for p in sorted(root.glob("*.json")) if root.is_dir() else []:
        rec = _read(project, p.stem)
        if rec:
            out.append(rec)
    return out


def needs_council(*, changes_design: bool = False, changes_priority: bool = False,
                  changes_direction: bool = False) -> bool:
    """Size triage: a quick job (a few tool calls, no design change) is only shared as a NOTICE and done at once."""
    return changes_design or changes_priority or changes_direction


def slug(topic: str) -> str:
    return re.sub(r"[^a-z0-9가-힣]+", "-", topic.lower()).strip("-")[:40] or "topic"


def open_council(project: Path, *, topic: str, directive: str, opener: str, desk: dict[str, dict[str, Any]],
                 now: float, kind: str = "policy", council_id: str | None = None,
                 deadline_s: float = ROUND_DEADLINE_S) -> dict[str, Any]:
    """Open (or join, or queue) a council. `directive` is stored verbatim; never summarised."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    with _lock(project):
        records = _all(project)
        same = next((r for r in records if r["topic"] == slug(topic) and r["state"] in OPEN_STATES + ("QUEUED",)), None)
        if same:
            same["directives"].append({"by": opener, "text": directive, "at": now})
            _write(project, same)
            return {"id": same["id"], "state": same["state"], "joined": True}
        open_now = [r for r in records if r["state"] in OPEN_STATES]
        plan = nowait.plan_wait(desk, opener, now, deadline_s=deadline_s)
        cid = council_id or f"C-{slug(topic)}-{int(now)}"
        rec = {"id": cid, "topic": slug(topic), "kind": kind, "opener": opener, "opened": now,
               "directives": [{"by": opener, "text": directive, "at": now}],
               "state": "QUEUED" if len(open_now) >= MAX_OPEN else "ROUND1",
               "participants": [opener] + [t for t in plan["wait_for"]],
               "abstain": plan["abstain"], "deadline_s": deadline_s, "round_deadline": now + deadline_s,
               "drafts": {}, "critiques": {}, "decision": None,
               "conductor": nowait.conductor_of(desk)}
        _write(project, rec)
    return {"id": cid, "state": rec["state"], "joined": False, "abstain": rec["abstain"],
            "participants": rec["participants"]}


def _positions(rec: dict[str, Any]) -> dict[str, str]:
    return {t: str(d.get("position", "")).strip().lower() for t, d in rec["drafts"].items()}


def submit_draft(project: Path, cid: str, tool: str, position: str, text: str = "", *,
                 evidence_score: int = 0) -> dict[str, Any]:
    """Round 1: an independent draft. Only from a participant, once; drafts of others stay hidden (`visible_drafts`)."""
    with _lock(project):
        rec = _read(project, cid)
        if not rec or rec["state"] != "ROUND1" or tool not in rec["participants"]:
            return {"accepted": False, "why": "not open for this tool"}
        if tool in rec["drafts"]:  # one draft per tool: a repeat is refused, never silently swallowed (AGY re-audit)
            return {"accepted": False, "why": "draft already submitted"}
        rec["drafts"][tool] = {"position": position, "text": text, "score": evidence_score}
        _write(project, rec)
    return {"accepted": True}


def submit_critique(project: Path, cid: str, tool: str, text: str, *, revised_position: str | None = None,
                    evidence_score: int | None = None) -> dict[str, Any]:
    """Round 2: one critique/improvement per tool; it may revise the tool's own position."""
    with _lock(project):
        rec = _read(project, cid)
        if not rec or rec["state"] != "ROUND2" or tool not in rec["drafts"]:
            return {"accepted": False, "why": "not open for this tool"}
        if tool in rec["critiques"]:  # one critique per tool: a repeat must not change position/score (AGY re-audit)
            return {"accepted": False, "why": "critique already submitted"}
        rec["critiques"][tool] = {"text": text, "revised": revised_position}
        if revised_position:
            rec["drafts"][tool]["position"] = revised_position
        if evidence_score is not None:
            rec["drafts"][tool]["score"] = evidence_score
        _write(project, rec)
    return {"accepted": True}


def visible_drafts(project: Path, cid: str, tool: str) -> dict[str, Any]:
    """Independence: during round 1 a tool sees only its own draft; others appear once round 1 is closed."""
    rec = _read(project, cid) or {}
    if rec.get("state") == "ROUND1":
        return {tool: rec["drafts"][tool]} if tool in rec.get("drafts", {}) else {}
    return rec.get("drafts", {})


def _decide(rec: dict[str, Any]) -> dict[str, Any]:
    pos = _positions(rec)
    responders = sorted(pos, key=lambda t: TOOLS.index(t) if t in TOOLS else len(TOOLS))  # authority order
    if not responders:
        return {"outcome": None, "method": "conductor_alone", "by": rec["conductor"], "re_review": True,
                "responders": [], "reason": "zero responders"}
    if rec["kind"] == "code":
        top = max(int(d.get("score", 0)) for d in rec["drafts"].values())
        leaders = [t for t in responders if int(rec["drafts"][t].get("score", 0)) == top]  # authority order
        if len({pos[t] for t in leaders}) == 1:  # one leader, or tied leaders that agree: evidence decides
            return {"outcome": rec["drafts"][leaders[0]]["position"], "method": "evidence", "by": leaders[0],
                    "responders": responders, "re_review": False}
        # tied top scores that disagree: the conductor breaks the tie among the LEADERS only, never a lower score
        chair = rec["conductor"] if rec["conductor"] in leaders else leaders[0]
        return {"outcome": rec["drafts"][chair]["position"], "method": "conductor_tiebreak", "by": chair,
                "responders": responders, "re_review": False}
    else:
        tally: dict[str, int] = {}
        for p in pos.values():
            tally[p] = tally.get(p, 0) + 1
        best, votes = max(tally.items(), key=lambda kv: kv[1])
        if votes * 3 >= 2 * len(responders):  # 2/3 of the responders; one responder decides alone
            return {"outcome": best, "method": "consensus_2of3", "responders": responders, "re_review": False}
    # tie / deadlock: the conductor chooses its own draft if it answered, else the first responder in authority order
    chair = rec["conductor"] if rec["conductor"] in rec["drafts"] else responders[0]
    return {"outcome": rec["drafts"][chair]["position"], "method": "conductor_tiebreak", "by": chair,
            "responders": responders, "re_review": False}


def _close(project: Path, rec: dict[str, Any], decision: dict[str, Any], now: float, why: str) -> None:
    decision = dict(decision)
    absent = sorted(set(TOOLS) - set(decision.get("responders", [])))
    decision.update(closed_by=why, abstained=absent, decided_at=now)
    decision["re_review"] = bool(decision.get("re_review") or absent)  # a returning tool re-reviews (spec 9.2-7)
    rec.update(state="DECIDED", decision=decision)
    _write(project, rec)
    write_adr(project, rec)
    # the next queued council now has room
    queued = sorted((r for r in _all(project) if r["state"] == "QUEUED"), key=lambda r: (r.get("opened", 0), r["id"]))  # FIFO
    open_now = [r for r in _all(project) if r["state"] in OPEN_STATES]
    for nxt in queued[: max(0, MAX_OPEN - len(open_now))]:
        nxt.update(state="ROUND1", round_deadline=now + nxt["deadline_s"], opened=now)
        _write(project, nxt)


def advance(project: Path, cid: str, *, now: float) -> dict[str, Any]:
    """One non-blocking step of the state machine; call it from any hook, watcher event or loop with the clock."""
    with _lock(project):
        rec = _read(project, cid)
        if not rec:
            return {"state": "UNKNOWN"}
        if rec["state"] in ("ROUND1", "ROUND2"):
            if now - rec["opened"] >= COUNCIL_MAX_S:
                _close(project, rec, _decide(rec), now, "council time limit")
            elif rec["state"] == "ROUND1":
                done = set(rec["drafts"]) >= set(rec["participants"])
                if done or now >= rec["round_deadline"]:
                    positions = set(_positions(rec).values())
                    if len(positions) <= 1:  # nobody or all equal: early stop, no round 2
                        _close(project, rec, _decide(rec), now,
                               "early stop: no dissent" if positions else "no responders")
                    else:
                        rec.update(state="ROUND2", round_deadline=now + rec["deadline_s"])
                        _write(project, rec)
            else:
                done = set(rec["critiques"]) >= set(rec["drafts"])
                if done or now >= rec["round_deadline"]:
                    _close(project, rec, _decide(rec), now, "round 2 complete" if done else "round 2 deadline")
        rec = _read(project, cid)
    return {"state": rec["state"], "decision": rec.get("decision")}


def late_reply(project: Path, cid: str, tool: str, text: str, *, receiver: str, card: str,
               now: float) -> dict[str, Any]:
    """A reply after the council closed: never reverses the decision, enters triage as an adoption candidate."""
    msg_triage.submit(project, receiver, card, {"id": f"late-{cid}-{tool}", "sender": tool, "text": text,
                                                "ts": now, "topic": cid, "evidence": True, "small": True})
    return {"routed": "msg_triage"}


def write_adr(project: Path, rec: dict[str, Any]) -> Path:
    """`.coord/decisions/<ID>.md`, atomic. The directive text is verbatim."""
    d = rec["decision"]
    lines = [f"# ADR {rec['id']}", "", f"- topic: {rec['topic']} ({rec['kind']})",
             f"- outcome: {d.get('outcome')}", f"- method: {d['method']} (by {d.get('by', 'responders')})",
             f"- responders: {', '.join(d['responders']) or 'none'}", f"- abstained: {', '.join(d['abstained']) or 'none'}",
             f"- closed by: {d['closed_by']}", f"- re_review: {'yes' if d['re_review'] else 'no'}", "",
             "## Directive (verbatim)"]
    lines += [f"> [{x['by']}] {x['text']}" for x in rec["directives"]]
    lines += ["", "## Drafts"] + [f"- {t}: {v['position']}" for t, v in sorted(rec["drafts"].items())]
    path = Path(project) / DECISIONS_DIR / f"{nowait.safe_name(rec['id'])}.md"
    nowait.atomic_write_text(path, "\n".join(lines) + "\n")
    return path


def drive(project: Path, cid: str, *, now_fn=time.time, sleep=time.sleep, tick: float = 0.2,
          hard_timeout_s: float = COUNCIL_MAX_S, mono=time.monotonic) -> dict[str, Any]:
    """Optional blocking loop for a caller that chooses to wait. Bounded by the council's own deadlines AND a wall clock
    cap, so even a stuck clock cannot hang it."""
    tick = max(0.01, float(tick))  # a zero/negative tick would spin
    stop = mono() + hard_timeout_s
    while True:
        out = advance(project, cid, now=now_fn())
        left = stop - mono()
        if out["state"] not in OPEN_STATES or left <= 0:
            return out
        sleep(min(tick, left))  # never sleeps past the hard cap
