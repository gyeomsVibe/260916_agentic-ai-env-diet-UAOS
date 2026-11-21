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
    author = str(card.get("author") or "") or next((t for t in AUTHOR_ORDER if t in members), "")
    if key and "codex" not in members:
        return {"card": card_id, "regime": regime, "action": "QUEUE_FOR_CODEX", "author": author, "judge": "", "merger": ""}
    judge = ("codex" if author != "codex" else "") if key else next((J for J in JUDGES if J in members and J != author), "")
    merger = next((M for M in MERGERS if M in members), "")
    action = "WAIT_FOR_JUDGE" if not judge else "WAIT_FOR_MERGER" if not merger else "RUN"
    return {"card": card_id, "regime": regime, "action": action, "author": author, "judge": judge, "merger": merger}

def regime_plan(desk: dict[str, Any], cards: list[dict[str, Any]], *, now: float) -> dict[str, Any]:
    regime = detect_regime(desk, now=now)
    alive = sorted(alive_tools(desk, now))
    routes = [work_steal_route(regime, c) for c in cards]
    return {"regime": regime, "alive": alive, "routes": routes}
