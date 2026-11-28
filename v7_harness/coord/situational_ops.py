"""U355-B: situational regime detection and work-stealing routes (pure, 0 tokens); it never approves."""

from __future__ import annotations

from typing import Any
from v7_harness.calculator_gate import JUDGE_TOOL_NAMES, REVIEWERS
from v7_harness.coord.agy_moderator import is_codex_exclusive_keypoint
from v7_harness.coord.merge_route import MERGERS
from v7_harness.coord.nowait import peer_alive

TOOLS = ("codex", "claude", "antigravity")
_BY_ALIVE = {frozenset({"codex","claude","antigravity"}): "TRIO", frozenset({"claude","antigravity"}): "DUO_CLAUDE_AGY",
           frozenset({"codex","antigravity"}): "DUO_CODEX_AGY", frozenset({"codex","claude"}): "DUO_CODEX_CLAUDE",
           frozenset({"claude"}): "SOLO_CLAUDE", frozenset({"antigravity"}): "SOLO_AGY", frozenset({"codex"}): "SOLO_CODEX",
           frozenset(): "LOCAL_ONLY"}
REGIMES = tuple(_BY_ALIVE.values())
JUDGES = tuple(JUDGE_TOOL_NAMES[r] for r in REVIEWERS)
AUTHOR_ORDER = ("claude", "antigravity", "codex")

SELF_TEST_TAIL = ("build", "reinstall", "test")  # U403: a solo emergency card ships only after these pass


def alive_tools(desk: dict[str, Any], now: float) -> frozenset[str]:
    return frozenset(tool for tool in TOOLS if peer_alive(desk.get(tool) if isinstance(desk, dict) else None, now))

def detect_regime(desk: dict[str, Any], *, now: float) -> str:
    return _BY_ALIVE[alive_tools(desk, now)]

def _members(regime: str) -> frozenset[str] | None:
    return next((key for key, value in _BY_ALIVE.items() if value == regime), None)

def work_steal_route(regime: str, card: dict[str, Any], *, keypoint: bool | None = None) -> dict[str, Any]:
    card_id = str(card.get("card") or "")
    members = _members(regime)
    if not members:
        return {"card": card_id, "regime": regime, "action": "LOCAL_ONLY_HOLD", "author": "", "judge": "", "merger": ""}
    key = is_codex_exclusive_keypoint(card) if keypoint is None else bool(keypoint)
    given = str(card.get("author") or "")
    author = given if given in members else next((t for t in AUTHOR_ORDER if t in members), "")
    moved = given if given and given != author else ""  # U403-R2: an absent author never keeps the card
    if key and "codex" not in members:
        return {"card": card_id, "regime": regime, "action": "QUEUE_FOR_CODEX", "author": author, "judge": "", "merger": "", "author_reassigned_from": moved}
    if len(members) == 1 and card.get("emergency") is True:
        return dict(_solo_finish(regime, card_id, author, next((M for M in MERGERS if M in members), "")),
                    author_reassigned_from=moved)
    judge = ("codex" if author != "codex" else "") if key else next((J for J in JUDGES if J in members and J != author), "")
    merger = next((M for M in MERGERS if M in members), "")
    peer = next((t for t in sorted(members) if t != author), "") if not judge and not key and len(members) == 2 else ""
    action = "WAIT_FOR_JUDGE" if not (judge or peer) else "WAIT_FOR_MERGER" if not merger else "RUN_DUO_PEER" if peer else "RUN"
    return {"card": card_id, "regime": regime, "action": action, "author": author, "judge": judge, "merger": merger,
            "peer_judge": peer, "reference_judge": "", "rereview": "REQUIRED_ON_RETURN" if peer else "", "self_test_tail": (), "author_reassigned_from": moved}

def regime_plan(desk: dict[str, Any], cards: list[dict[str, Any]], *, now: float) -> dict[str, Any]:
    regime = detect_regime(desk, now=now)
    alive = sorted(alive_tools(desk, now))
    routes = [work_steal_route(regime, c) for c in cards]
    return {"regime": regime, "alive": alive, "routes": routes}


def _solo_finish(regime: str, card_id: str, tool: str, merger: str) -> dict[str, Any]:
    """U403: one live tool finishes an emergency card; the formal judge stays empty (never self-approval)."""
    return {"card": card_id, "regime": regime, "action": "SOLO_EMERGENCY_FINISH", "author": tool, "judge": "",
            "merger": merger, "peer_judge": "", "reference_judge": f"{tool}:fresh_session",
            "rereview": "REQUIRED_ON_RETURN", "self_test_tail": SELF_TEST_TAIL}


def route_from_presence(presence: Any, card: dict[str, Any], *, now: float) -> dict[str, Any]:
    """U403-R2: the route for one card from a raw presence desk; fails closed like hook_context.situational_line
    (non-dict desk, records without `observed_at`, or any error read as no live peer)."""
    desk = {t: i for t, i in presence.items() if isinstance(i, dict) and i.get("observed_at") is not None} \
        if isinstance(presence, dict) else {}
    try:
        regime = detect_regime(desk, now=now)
        alive = sorted(alive_tools(desk, now))
    except Exception:  # fail closed
        regime, alive = "LOCAL_ONLY", []
    return {"regime": regime, "alive": alive, "route": work_steal_route(regime, card)}


RUNNABLE = ("RUN", "RUN_DUO_PEER", "SOLO_EMERGENCY_FINISH")


def regime_admission(project: Any, card: dict[str, Any], *, now: float) -> dict[str, Any]:
    """U403-R3 (moved from cli for the U403-LAND commit gate): the presence route is a suggestion; `ready` is True only
    when it is runnable AND the canonical participation decision (read-only snapshot) admits its author as EXECUTOR and
    any named judge as a live EXECUTOR. HALT, JUDGE_ONLY, OFFLINE, UNKNOWN, an expired decision or any error leaves
    `ready` False (fail closed)."""
    from pathlib import Path

    from v7_harness.coord import participation, presence

    project = Path(project)
    try:
        out = route_from_presence(presence.read_all(project), card, now=now)
    except Exception as exc:  # fail closed: an unreadable desk routes nothing
        out = {"regime": "LOCAL_ONLY", "alive": [], "route": {"action": "LOCAL_ONLY_HOLD", "author": "", "judge": "",
                                                              "error": type(exc).__name__}}
    route = out["route"]
    runnable = route["action"] in RUNNABLE
    admission: dict[str, Any] = {"admitted": False, "mode": "UNKNOWN", "author_role": "UNKNOWN",
                                 "judge_role": "", "reason": "NOT_RUNNABLE"}
    try:
        decision = participation.snapshot(project, now=now, write_file=False)
        roles = decision.get("roles") if isinstance(decision, dict) else None
        if not isinstance(roles, dict):
            raise ValueError("NO_ROLES")
        expires = participation._finite(decision.get("expires_at"))
        author_role = roles.get(route.get("author") or "", participation.UNKNOWN)
        judge = route.get("judge") or route.get("peer_judge") or ""  # RUN_DUO_PEER names its judge `peer_judge`
        judge_role = roles.get(judge, participation.UNKNOWN) if judge else ""
        admission.update(mode=decision.get("mode", "UNKNOWN"), author_role=author_role, judge_role=judge_role)
        if expires is None or now >= expires:
            admission["reason"] = "DECISION_EXPIRED"
        elif decision.get("mode") == "HALT":
            admission["reason"] = "HALT"
        elif author_role != participation.EXECUTOR:
            admission["reason"] = f"AUTHOR_{author_role}"
        elif judge and judge_role != participation.EXECUTOR:
            admission["reason"] = f"JUDGE_{judge_role}"
        elif runnable:
            admission.update(admitted=True, reason="EXECUTOR_ADMITTED")
    except Exception as exc:  # fail closed
        admission["reason"] = f"ADMISSION_ERROR:{type(exc).__name__}"
    out["presence_route_informational"] = True
    out["admissions_consulted"] = True
    out["admission"] = admission
    out["ready"] = bool(runnable and admission["admitted"])
    return out
