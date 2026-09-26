"""Deterministic UAOS authority routing without inventing token counts from quota percentages."""

from __future__ import annotations

VALID_STATES = frozenset({"ACTIVE", "LIMITED", "ABSENT", "UNKNOWN"})


def route_authority(codex: str, claude: str, antigravity: str) -> str:
    """Return the sole current authority, or a fail-closed blocker.

    Provider percentages and reset windows are deliberately absent: they describe provider
    availability, not fungible token balances. Call-level token/USD/time caps remain contracts.
    """
    states = tuple(str(value).upper() for value in (codex, claude, antigravity))
    if any(value not in VALID_STATES for value in states) or "UNKNOWN" in states:
        return "BLOCKED_UNKNOWN"
    codex_state, claude_state, antigravity_state = states
    if codex_state == "ACTIVE":
        return "codex"
    if codex_state in {"LIMITED", "ABSENT"} and claude_state == "ACTIVE":
        return "claude"
    if (codex_state in {"LIMITED", "ABSENT"} and claude_state in {"LIMITED", "ABSENT"}
            and antigravity_state == "ACTIVE"):
        return "antigravity"
    return "BLOCKED_NO_ACTIVE_AUTHORITY"

