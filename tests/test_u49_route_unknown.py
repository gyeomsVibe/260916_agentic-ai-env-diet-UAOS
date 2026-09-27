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
