"""U355-B: situational regime detection and work-stealing routes (pure, 0 tokens).

Receipt: 2026-11-21/22 DUO idle (relay_830aa06d): with Codex LIMITED, ready non-keypoint cards waited ~9 h because no
code told the live pair (Claude + Antigravity) who authors, who judges and who merges. The engine only reads presence
records and existing gate constants; it never approves, and an UNKNOWN or stale tool counts as absent (fail closed).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NOW = 1_800_000_000.0


def _rec(state: str, age: float = 10.0) -> dict:
    return {"state": state, "observed_at": NOW - age}


def _desk(codex: str, claude: str, agy: str) -> dict:
    return {"codex": _rec(codex), "claude": _rec(claude), "antigravity": _rec(agy)}


CARD = {"card": "U900", "allowed_files": ["v7_harness/coord/situational_ops.py"]}
KEY = {"card": "U901", "allowed_files": ["v7_harness/calculator_gate.py"]}


class RegimeTests(unittest.TestCase):
    def test_all_eight_regimes(self) -> None:
        from v7_harness.coord.situational_ops import detect_regime

        A, L = "ACTIVE", "LIMITED"
        cases = {
            (A, A, A): "TRIO",
            (L, A, A): "DUO_CLAUDE_AGY",
            (A, L, A): "DUO_CODEX_AGY",
            (A, A, L): "DUO_CODEX_CLAUDE",
            (L, A, L): "SOLO_CLAUDE",
            (L, L, A): "SOLO_AGY",
            (A, L, L): "SOLO_CODEX",
            (L, L, L): "LOCAL_ONLY",
        }
        for states, regime in cases.items():
            with self.subTest(states=states):
                self.assertEqual(detect_regime(_desk(*states), now=NOW), regime)

    def test_unknown_stale_or_missing_fails_closed(self) -> None:
        from v7_harness.coord.situational_ops import detect_regime

        desk = _desk("UNKNOWN", "ACTIVE", "ACTIVE")
        self.assertEqual(detect_regime(desk, now=NOW), "DUO_CLAUDE_AGY")
        desk["codex"] = _rec("ACTIVE", age=10_000.0)  # stale heartbeat: no evidence of life
        self.assertEqual(detect_regime(desk, now=NOW), "DUO_CLAUDE_AGY")
        self.assertEqual(detect_regime({}, now=NOW), "LOCAL_ONLY")
        self.assertEqual(detect_regime({"codex": {"state": "ACTIVE"}}, now=NOW), "LOCAL_ONLY")


class RouteTests(unittest.TestCase):
    def test_duo_claude_agy_routes_non_keypoint(self) -> None:
        from v7_harness.coord.situational_ops import work_steal_route

        route = work_steal_route("DUO_CLAUDE_AGY", CARD)
        self.assertEqual((route["action"], route["author"], route["judge"], route["merger"]),
                         ("RUN", "claude", "antigravity", "antigravity"))

    def test_keypoint_waits_for_codex(self) -> None:
        from v7_harness.coord.situational_ops import work_steal_route

        self.assertEqual(work_steal_route("DUO_CLAUDE_AGY", KEY)["action"], "QUEUE_FOR_CODEX")
        self.assertEqual(work_steal_route("DUO_CLAUDE_AGY", CARD, keypoint=True)["action"], "QUEUE_FOR_CODEX")
        trio = work_steal_route("TRIO", KEY)
        self.assertEqual((trio["action"], trio["judge"]), ("RUN", "codex"))

    def test_solo_never_self_approves(self) -> None:
        from v7_harness.coord.situational_ops import work_steal_route

        for regime, author in (("SOLO_CLAUDE", "claude"), ("SOLO_AGY", "antigravity"), ("SOLO_CODEX", "codex")):
            with self.subTest(regime=regime):
                route = work_steal_route(regime, CARD)
                self.assertEqual(route["action"], "WAIT_FOR_JUDGE")
                self.assertNotEqual(route["judge"], route["author"])
                self.assertEqual(route["judge"], "")

    def test_judge_is_never_the_author_and_only_a_calculator_gate_reviewer(self) -> None:
        from v7_harness.calculator_gate import JUDGE_TOOL_NAMES, REVIEWERS
        from v7_harness.coord.situational_ops import REGIMES, work_steal_route

        allowed = {JUDGE_TOOL_NAMES[r] for r in REVIEWERS}
        for regime in REGIMES:
            route = work_steal_route(regime, dict(CARD, author="antigravity"))
            if route["judge"]:
                self.assertIn(route["judge"], allowed)
                self.assertNotEqual(route["judge"], route["author"])

    def test_duo_codex_claude_has_no_agy_judge_but_codex_judges(self) -> None:
        from v7_harness.coord.situational_ops import work_steal_route

        route = work_steal_route("DUO_CODEX_CLAUDE", CARD)
        self.assertEqual((route["author"], route["judge"], route["merger"]), ("claude", "codex", "codex"))

    def test_local_only_holds(self) -> None:
        from v7_harness.coord.situational_ops import work_steal_route

        self.assertEqual(work_steal_route("LOCAL_ONLY", CARD)["action"], "LOCAL_ONLY_HOLD")
        self.assertEqual(work_steal_route("NOT_A_REGIME", CARD)["action"], "LOCAL_ONLY_HOLD")

    def test_regime_plan(self) -> None:
        from v7_harness.coord.situational_ops import regime_plan

        plan = regime_plan(_desk("LIMITED", "ACTIVE", "ACTIVE"), [CARD, KEY], now=NOW)
        self.assertEqual(plan["regime"], "DUO_CLAUDE_AGY")
        self.assertEqual([r["action"] for r in plan["routes"]], ["RUN", "QUEUE_FOR_CODEX"])
        self.assertEqual([r["card"] for r in plan["routes"]], ["U900", "U901"])


if __name__ == "__main__":
    unittest.main()
