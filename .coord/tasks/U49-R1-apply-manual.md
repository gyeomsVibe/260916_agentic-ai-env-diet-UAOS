```contract
work_id: U49-R1
worker: apply
goal: route_authority consults Codex, Claude, Antigravity in succession order and returns BLOCKED_UNKNOWN only when the deciding tool is UNKNOWN (invalid states still fail closed).
inputs:
- v7_harness/budget_route.py sha256=16a19bfc3b003605c1b6bce61ef794597dde792337b1306cd69fc0a0d82324dd
- tests/test_u45_general_uaos.py sha256=5f04a361fcf053cd0217655d3afc20a05b5d4a22e373deb80b5439331f4bd7c8
allow:
- v7_harness/budget_route.py
- tests/test_u49_route_unknown.py
acceptance: C:/Python314/python.exe -m unittest tests.test_u49_route_unknown tests.test_u45_general_uaos
forbidden: design changes; edits outside allow; weakening or deleting existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Card: PLAN U49-R1. Measured 2026-09-27 19:04: codex ABSENT, claude ACTIVE, antigravity UNKNOWN returned BLOCKED_UNKNOWN. New test file is red on HEAD (observed case, codex-active case, 64-combination reference). Existing U45 route test is unchanged and must stay green. Acting judge Claude under the user's order; Codex re-reviews.

===FILE: v7_harness/budget_route.py===
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
===FILE: tests/test_u49_route_unknown.py===
"""U49-R1: an UNKNOWN blocks authority routing only when that tool's state decides the answer."""

from __future__ import annotations

import itertools
import unittest

from v7_harness.budget_route import route_authority

STATES = ("ACTIVE", "LIMITED", "ABSENT", "UNKNOWN")


def reference(codex: str, claude: str, antigravity: str) -> str:
    """The succession rule written out case by case (global rules: Codex, then Claude, then Antigravity)."""
    if codex == "UNKNOWN":
        return "BLOCKED_UNKNOWN"
    if codex == "ACTIVE":
        return "codex"
    if claude == "UNKNOWN":
        return "BLOCKED_UNKNOWN"
    if claude == "ACTIVE":
        return "claude"
    if antigravity == "UNKNOWN":
        return "BLOCKED_UNKNOWN"
    if antigravity == "ACTIVE":
        return "antigravity"
    return "BLOCKED_NO_ACTIVE_AUTHORITY"


class RouteUnknownTests(unittest.TestCase):
    def test_observed_case_codex_absent_claude_active_agy_unknown(self) -> None:
        # Measured 2026-09-27 19:04: this returned BLOCKED_UNKNOWN before U49-R1.
        self.assertEqual("claude", route_authority("ABSENT", "ACTIVE", "UNKNOWN"))

    def test_codex_active_is_not_blocked_by_unknown_deputies(self) -> None:
        self.assertEqual("codex", route_authority("ACTIVE", "UNKNOWN", "UNKNOWN"))

    def test_deciding_unknown_still_fails_closed(self) -> None:
        self.assertEqual("BLOCKED_UNKNOWN", route_authority("UNKNOWN", "ACTIVE", "ACTIVE"))
        self.assertEqual("BLOCKED_UNKNOWN", route_authority("LIMITED", "UNKNOWN", "ACTIVE"))
        self.assertEqual("BLOCKED_UNKNOWN", route_authority("ABSENT", "LIMITED", "UNKNOWN"))

    def test_invalid_state_anywhere_fails_closed(self) -> None:
        self.assertEqual("BLOCKED_UNKNOWN", route_authority("ACTIVE", "ACTIVE", "BUSY"))

    def test_all_64_combinations_match_the_succession_rule(self) -> None:
        for combo in itertools.product(STATES, repeat=3):
            with self.subTest(combo=combo):
                self.assertEqual(reference(*combo), route_authority(*combo))


if __name__ == "__main__":
    unittest.main()
===END===

## Output

- Reply with ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.
