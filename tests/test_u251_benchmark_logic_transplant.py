"""U251 / U261 / U267: Unit & Integration Tests for Benchmark Logic Transplant (OpenRig + Show GN + REA)
and Unified 5-Chip Telemetry Integration with `capacity_planner.py`.
"""

from __future__ import annotations

import unittest

from v7_harness.benchmark_logic_transplant import (
    ESTIMATED_EAGER_MCP_SCHEMA_TOKENS,
    THREE_TOOL_DEFAULT_ROLES,
    build_five_chip_telemetry_snapshot,
    build_three_tool_seat_registry,
    select_rea_analysis_tier,
)


class TestU251BenchmarkLogicTransplant(unittest.TestCase):
    def test_openrig_three_tool_seat_registry_and_failover(self) -> None:
        phases = [
            {"phase_id": "U261-A", "owner_tool": "codex", "state": "READY"},
            {"phase_id": "U261-B", "owner_tool": "claude", "state": "ACTIVE"},
            {"phase_id": "U261-C", "owner_tool": "antigravity", "state": "DONE"},
        ]
        # When Codex hits quota (LIMITED), Claude + Antigravity absorb its READY card
        registry = build_three_tool_seat_registry(
            presence_states={"codex": "LIMITED", "claude": "ACTIVE", "antigravity": "ACTIVE"},
            schedule_phases=phases,
            non_interruptive=True,
        )
        self.assertEqual(registry["orchestrator"], "UAOS-RSI-3Tool-TikiTaka")
        self.assertEqual(registry["mode"], "TWO_TOOL_CONTINUITY")
        self.assertEqual(registry["conductor"], "claude")
        self.assertIn("U261-A", registry["reassigned_cards"])
        self.assertEqual(phases[0]["owner_tool"], "claude")
        self.assertEqual(len(registry["seats"]), 4)  # codex, claude, antigravity, ollama

    def test_u257_keypoint_reserve_and_sole_survivor_no_self_judge(self) -> None:
        # 1. Routine failover when Claude is LIMITED should route to Antigravity (preserving Codex quota)
        routine_phases = [
            {"phase_id": "U261-R1", "owner_tool": "claude", "state": "READY"},
        ]
        reg_routine = build_three_tool_seat_registry(
            presence_states={"codex": "ACTIVE", "claude": "LIMITED", "antigravity": "ACTIVE"},
            schedule_phases=routine_phases,
        )
        self.assertEqual(reg_routine["conductor"], "codex")
        self.assertEqual(routine_phases[0]["owner_tool"], "antigravity")

        # 2. Sole survivor NEVER self-approves REVIEW -> DONE (author != judge)
        sole_phases = [
            {"phase_id": "U261-REV", "owner_tool": "antigravity", "state": "REVIEW"},
        ]
        reg_sole = build_three_tool_seat_registry(
            presence_states={"codex": "LIMITED", "claude": "ABSENT", "antigravity": "ACTIVE"},
            schedule_phases=sole_phases,
        )
        self.assertEqual(reg_sole["mode"], "SOLE_SURVIVOR_AUTONOMOUS")
        self.assertEqual(sole_phases[0]["state"], "REVIEW")
        self.assertTrue(sole_phases[0]["needs_return_review"])
        self.assertIn("U261-REV", reg_sole["deferred_sole_survivor_reviews"])
        self.assertEqual(reg_sole["promoted_sole_survivor"], [])

    def test_showgn_five_chip_telemetry_and_5s_wait_preemption(self) -> None:
        phases = [
            {"phase_id": "U261-1", "owner_tool": "antigravity", "state": "READY"},
            {"phase_id": "U261-2", "owner_tool": "codex", "state": "DONE"},
        ]
        snapshot = build_five_chip_telemetry_snapshot(
            schedule_phases=phases,
            presence_states={"codex": "ACTIVE", "claude": "ACTIVE", "antigravity": "ACTIVE"},
            changed_files=[{"path": "v7_harness/benchmark_logic_transplant.py", "added": 180, "removed": 0}],
            active_watchers=["coord watch --target antigravity"],
            quota_reset_times={"codex": "2026-10-26T23:00:00+09:00"},
            foreground_wait_s=6.2,
            is_background_watcher=False,
            acting_tool="antigravity",
        )
        chips = snapshot["chips"]
        self.assertEqual(chips["1_todos_schedule"]["total"], 2)
        self.assertEqual(chips["1_todos_schedule"]["done"], 1)
        self.assertEqual(chips["4_changed_files_diff"]["lines_added"], 180)
        self.assertEqual(
            chips["3_background_watchers"]["wait_decision"]["action"],
            "PREEMPT_AND_CLAIM",
        )
        self.assertEqual(
            chips["3_background_watchers"]["wait_decision"]["claimed_phase"],
            "U261-1",
        )
        self.assertEqual(phases[0]["state"], "ACTIVE")

    def test_rea_two_tier_on_demand_vs_default_router(self) -> None:
        # Normal Python source task -> Tier 1 only (saves ~14,000 paid tokens/call)
        t1 = select_rea_analysis_tier("v7_harness/coord/failover_closeout.py")
        self.assertEqual(t1["selected_tier"], "TIER_1_DEFAULT_CORE_ONLY")
        self.assertTrue(t1["tier1_default_active"])
        self.assertFalse(t1["tier2_on_demand_active"])
        self.assertEqual(t1["paid_schema_tokens_saved_per_call"], ESTIMATED_EAGER_MCP_SCHEMA_TOKENS)

        # Binary / ASAR / .work/library target -> Tier 2 On-Demand activated
        t2_bin = select_rea_analysis_tier("C:/target/app.asar")
        self.assertEqual(t2_bin["selected_tier"], "TIER_2_ON_DEMAND_REVERSE_ENGINEERING")
        self.assertTrue(t2_bin["tier1_default_active"])
        self.assertTrue(t2_bin["tier2_on_demand_active"])

        t2_lib = select_rea_analysis_tier(".work/library/rea/src/index.ts")
        self.assertEqual(t2_lib["selected_tier"], "TIER_2_ON_DEMAND_REVERSE_ENGINEERING")
        self.assertTrue(t2_lib["tier2_on_demand_active"])

    def test_u267_readonly_non_mutation_terminal_states_and_5engine_seats(self) -> None:
        # Verify official Google AI Ultra 5x · Gemini 4 Argon naming in THREE_TOOL_DEFAULT_ROLES
        self.assertEqual(
            THREE_TOOL_DEFAULT_ROLES["antigravity"]["role"],
            "Google AI Ultra (Pro 대비 5x 사용량) · Gemini 4 Argon",
        )
        phases = [
            {"phase_id": "U267-1", "owner_tool": "codex", "state": "READY"},
            {"phase_id": "U267-2", "owner_tool": "claude", "state": "MERGED"},
            {"phase_id": "U267-3", "owner_tool": "antigravity", "state": "DONE_SCOPED"},
        ]
        snap = build_five_chip_telemetry_snapshot(
            schedule_phases=phases,
            presence_states={"codex": "LIMITED", "claude": "ACTIVE", "antigravity": "ACTIVE"},
            changed_files=[{"path": "v7_harness/coord/capacity_planner.py", "added": 95, "removed": 4}],
            active_watchers=["coord watch --target antigravity"],
            foreground_wait_s=10.0,
            is_background_watcher=False,
            acting_tool="antigravity",
            mutate_schedule=False,
            include_haiku=True,
            engines_summary={
                "codex": {"used_5h_effective_tokens": 40000, "usable_remaining_5h_tokens": 0, "usable_cards_capacity": 0},
                "claude": {"used_5h_effective_tokens": 80000, "usable_remaining_5h_tokens": 120000, "usable_cards_capacity": 2},
                "antigravity": {"used_5h_effective_tokens": 25000, "usable_remaining_5h_tokens": 1700000, "usable_cards_capacity": 37},
            },
        )
        self.assertTrue(snap["read_only"])
        # Caller's phases list must NOT be mutated when mutate_schedule=False
        self.assertEqual(phases[0]["owner_tool"], "codex")
        self.assertEqual(phases[0]["state"], "READY")
        # Both MERGED and DONE_SCOPED must be counted as done (TERMINAL_STATES)
        self.assertEqual(snap["chips"]["1_todos_schedule"]["done"], 2)
        self.assertEqual(snap["chips"]["1_todos_schedule"]["remaining"], 1)
        # 5 seats when include_haiku=True
        self.assertEqual(len(snap["chips"]["2_three_tool_seats"]["seats"]), 5)
        self.assertEqual(snap["chips"]["3_background_watchers"]["wait_decision"]["action"], "READ_ONLY_WAIT_OBSERVED")


if __name__ == "__main__":
    unittest.main()
