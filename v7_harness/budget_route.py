"""Deterministic UAOS authority routing without inventing token counts from quota percentages."""

from __future__ import annotations

VALID_STATES = frozenset({"ACTIVE", "LIMITED", "ABSENT", "UNKNOWN"})
AWAY = frozenset({"LIMITED", "ABSENT"})


def route_authority(codex: str, claude: str, antigravity: str) -> str:
    """Return the sole current authority, or a fail-closed blocker.

    Provider percentages and reset windows are deliberately absent: they describe provider
    availability, not fungible token balances. Call-level token/USD/time caps remain contracts.

    U49-R1 (2026-09-27): tools are consulted in succession order and an UNKNOWN blocks only when that
    tool's state decides the answer. Before, codex ABSENT + claude ACTIVE + antigravity UNKNOWN was
    BLOCKED_UNKNOWN although Antigravity may act only when both Codex and Claude are away.
    """
    states = tuple(str(value).upper() for value in (codex, claude, antigravity))
    if any(value not in VALID_STATES for value in states):
        return "BLOCKED_UNKNOWN"
    for tool, state in zip(("codex", "claude", "antigravity"), states):
        if state == "UNKNOWN":
            return "BLOCKED_UNKNOWN"
        if state == "ACTIVE":
            return tool
    return "BLOCKED_NO_ACTIVE_AUTHORITY"
