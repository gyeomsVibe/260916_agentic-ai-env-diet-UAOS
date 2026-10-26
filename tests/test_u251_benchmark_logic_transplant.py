"""U251: Unit & Integration Tests for Benchmark Logic Transplant (OpenRig + Show GN + REA)."""

from __future__ import annotations

import unittest

from v7_harness.benchmark_logic_transplant import (
    ESTIMATED_EAGER_MCP_SCHEMA_TOKENS,
    build_five_chip_telemetry_snapshot,
    build_three_tool_seat_registry,
    select_rea_analysis_tier,
)


class TestU251BenchmarkLogicTransplant(unittest.TestCase):
    def test_openrig_three_tool_seat_registry_and_failover(self) -> None:
        phases = [
            {"id": "U251-A", "owner": "codex", "status": "READY"},
            {"id": "U251-B", "owner": "claude", "status": "ACTIVE"},
            {"id": "U251-C", "owner": "antigravity", "status": "DONE"},
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
        self.assertIn("U251-A", registry["reassigned_cards"])
        self.assertEqual(len(registry["seats"]), 4)  # codex, claude, antigravity, ollama

    def test_showgn_five_chip_telemetry_and_5s_wait_preemption(self) -> None:
        phases = [
            {"id": "U251-1", "owner": "antigravity", "status": "READY"},
            {"id": "U251-2", "owner": "codex", "status": "DONE"},
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
            "U251-1",
        )

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


if __name__ == "__main__":
    unittest.main()
