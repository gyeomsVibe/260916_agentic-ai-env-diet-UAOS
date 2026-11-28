"""MODE-SDT: which situation-manual mode (SOLO / DUO / TRIO / HALT) the desk is in now, from presence only (0 tokens).

Design: docs/140 (Solo/Duo/Trio situation manual). Mode = number of tools whose presence is ACTIVE:
3 TRIO (beta-test window), 2 DUO (default build unit, author != judge), 1 SOLO (one tool ships, deferred
re-review), 0 HALT. UNKNOWN never counts as ACTIVE (same rule as participation.classify and nowait.peer_alive), and
any UNKNOWN tool marks the answer fail_closed: the mode may be too low, never too high. This module never approves
and never dispatches; paid admission stays with `coord participation` (S5).
"""
from __future__ import annotations

from typing import Any

TOOLS = ("codex", "claude", "antigravity")
MODES = {3: "TRIO", 2: "DUO", 1: "SOLO", 0: "HALT"}
# docs/136 regime names for the same alive set (situational_ops._BY_ALIVE, duplicated to keep this module pure).
_REGIME = {frozenset(TOOLS): "TRIO", frozenset({"claude", "antigravity"}): "DUO_CLAUDE_AGY",
           frozenset({"codex", "antigravity"}): "DUO_CODEX_AGY", frozenset({"codex", "claude"}): "DUO_CODEX_CLAUDE",
           frozenset({"claude"}): "SOLO_CLAUDE", frozenset({"antigravity"}): "SOLO_AGY",
           frozenset({"codex"}): "SOLO_CODEX", frozenset(): "LOCAL_ONLY"}
# One line per mode: what the desk does next (docs/140 section 2).
NEXT = {"TRIO": "beta-test window: monitor, then joint fix/harden, remove [self-implement/test] tag",
        "DUO": "build unit: author != judge across the two ACTIVE tools",
        "SOLO": "ship alone, record fixes as RSI receipts, queue deferred re-review for the returning tool",
        "HALT": "no ACTIVE tool: local Ollama/deterministic work only, wake on presence change"}


def collab_mode(states: dict[str, Any] | None) -> dict[str, Any]:
    states = states if isinstance(states, dict) else {}
    norm = {t: str(states.get(t) or "UNKNOWN").upper() for t in TOOLS}
    active = [t for t in TOOLS if norm[t] == "ACTIVE"]
    offline = [t for t in TOOLS if norm[t] in ("LIMITED", "ABSENT")]
    unknown = [t for t in TOOLS if t not in active and t not in offline]
    mode = MODES[len(active)]
    return {"mode": mode, "regime": _REGIME[frozenset(active)], "active": active, "offline": offline,
            "unknown": unknown, "fail_closed": bool(unknown) or mode == "HALT", "next": NEXT[mode],
            "self_approval": False}
