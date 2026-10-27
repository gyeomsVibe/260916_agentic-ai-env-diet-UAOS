"""U271/U272: Tests for 3-tool Ollama active offload boost and Claude Ollama/Haiku 5:3:2 disjoint parallel routing."""

from __future__ import annotations
import unittest

from v7_harness.delegation import (
    BOOST_READ_MAP_LINE_THRESHOLD,
    CRITICAL_OFFLOAD_CODE_LINE_LIMIT,
    DICTATION_CODE_LINE_LIMIT,
    HAIKU_PREFLIGHT_TOKEN_CAP,
    NORMAL_READ_MAP_LINE_THRESHOLD,
    compute_agy_ollama_boost_plan,
    compute_claude_532_dispatch_plan,
    disjoint_parallel_errors,
    partition_disjoint_parallel_lanes,
)
from v7_harness.coord.capacity_planner import compute_subworker_optimization


class TestU271OllamaHaikuDisjointParallel(unittest.TestCase):
    def test_disjoint_parallel_overlap_detected(self) -> None:
        contract = {
            "work_id": "U272-T1",
            "caller": "claude",
            "worker": "local",
            "allow": ["v7_harness/delegation.py", "tests/test_u272.py"],
            "haiku_allow": ["tests/test_u272.py", "docs/00_DOCUMENT_INDEX.md"],
        }
        errs = disjoint_parallel_errors(contract)
        self.assertTrue(any("DISJOINT_PARALLEL_OVERLAP" in e for e in errs))
        self.assertTrue(any("tests/test_u272.py" in e for e in errs))

    def test_disjoint_parallel_clean_split_passes(self) -> None:
        contract = {
            "work_id": "U272-T2",
            "caller": "claude",
            "worker": "local",
            "allow": ["v7_harness/delegation.py"],
            "haiku_allow": ["tests/test_u272.py", "docs/00_DOCUMENT_INDEX.md"],
            "remote_budget_tokens": "12000",
        }
        errs = disjoint_parallel_errors(contract)
        self.assertEqual(errs, [])

    def test_haiku_quarantined_on_antigravity_and_codex(self) -> None:
        for tool in ("antigravity", "codex"):
            contract = {
                "work_id": "U272-T3",
                "caller": tool,
                "worker": "claude",
                "model": "claude-haiku-5-5",
                "remote_budget_tokens": "8000",
            }
            errs = disjoint_parallel_errors(contract)
            self.assertTrue(any("HAIKU_QUARANTINED_ON_TOOL" in e for e in errs), f"Failed for {tool}")

    def test_haiku_preflight_cap_enforced(self) -> None:
        contract = {
            "work_id": "U272-T4",
            "caller": "claude",
            "worker": "claude",
            "model": "claude-haiku-5-5",
            "remote_budget_tokens": str(HAIKU_PREFLIGHT_TOKEN_CAP + 1),
        }
        errs = disjoint_parallel_errors(contract)
        self.assertTrue(any("HAIKU_CAP_EXCEEDED" in e for e in errs))

    def test_partition_disjoint_lanes_claude_vs_antigravity(self) -> None:
        candidate_files = [
            "v7_harness/delegation.py",
            "v7_harness/manual.py",
            "tests/test_u272.py",
            "docs/99_report.html",
        ]
        claude_plan = partition_disjoint_parallel_lanes(candidate_files, caller_tool="claude", utilization_5h_pct=85.0)
        self.assertTrue(claude_plan["disjoint_verified"])
        self.assertTrue(claude_plan["ollama_boost_active"])
        self.assertEqual(claude_plan["ollama_slice_line_limit"], CRITICAL_OFFLOAD_CODE_LINE_LIMIT)
        self.assertEqual(claude_plan["read_map_line_threshold"], BOOST_READ_MAP_LINE_THRESHOLD)
        self.assertEqual(claude_plan["ollama_lane"], ["v7_harness/delegation.py", "v7_harness/manual.py"])
        self.assertEqual(claude_plan["haiku_lane"], ["tests/test_u272.py", "docs/99_report.html"])
        self.assertEqual(claude_plan["target_ratio"], {"ollama_pct": 50.0, "haiku_pct": 30.0, "paid_core_pct": 20.0})

        agy_plan = partition_disjoint_parallel_lanes(candidate_files, caller_tool="antigravity", utilization_5h_pct=50.0)
        self.assertTrue(agy_plan["disjoint_verified"])
        self.assertFalse(agy_plan["ollama_boost_active"])
        self.assertEqual(agy_plan["ollama_slice_line_limit"], DICTATION_CODE_LINE_LIMIT)
        self.assertEqual(agy_plan["read_map_line_threshold"], NORMAL_READ_MAP_LINE_THRESHOLD)
        self.assertEqual(agy_plan["haiku_lane"], [])
        self.assertEqual(len(agy_plan["ollama_lane"]), 4)
        self.assertEqual(agy_plan["target_ratio"], {"ollama_pct": 60.0, "haiku_pct": 0.0, "paid_core_pct": 40.0})

    def test_agy_ollama_boost_plan_and_claude_532_dispatch(self) -> None:
        boost = compute_agy_ollama_boost_plan(
            utilization_5h_pct=100.0,
            file_line_counts={"v7_harness/cli.py": 2700, "v7_harness/small.py": 120, "v7_harness/med.py": 210},
        )
        self.assertTrue(boost["boost_active"])
        self.assertEqual(boost["code_slice_line_limit"], 30)
        self.assertEqual(boost["read_map_line_threshold"], 180)
        self.assertEqual(boost["mandatory_local_read_map_files"], ["v7_harness/cli.py", "v7_harness/med.py"])
        self.assertGreater(boost["estimated_saved_paid_tokens"], 0)

        c532 = compute_claude_532_dispatch_plan(
            ollama_calls_5h=23,
            haiku_calls_5h=38,
            opus_sonnet_calls_5h=456,
            haiku_remaining_5h_tokens=2063363,
        )
        self.assertEqual(c532["current_ratio_pct"]["ollama_pct"], 4.4)
        self.assertEqual(c532["current_ratio_pct"]["haiku_pct"], 7.4)
        self.assertEqual(c532["current_ratio_pct"]["paid_core_pct"], 88.2)
        self.assertEqual(c532["next_recommended_worker_tier"], "ollama")

    def test_compute_subworker_optimization_telemetry(self) -> None:
        mock_engines = {
            "antigravity": {"budget_utilization_5h_pct": 100.0, "status_tier": "CRITICAL_OFFLOAD", "window_5h": {"calls": 1182}},
            "claude": {"budget_utilization_5h_pct": 100.0, "status_tier": "CRITICAL_OFFLOAD", "window_5h": {"calls": 456}},
            "codex": {"budget_utilization_5h_pct": 92.8, "status_tier": "LIMITED_PAUSE", "window_5h": {"calls": 279}},
            "haiku": {"budget_utilization_5h_pct": 31.2, "status_tier": "HEALTHY", "usable_remaining_5h_tokens": 2063363, "window_5h": {"calls": 38}},
            "ollama": {"budget_utilization_5h_pct": 0.0, "status_tier": "UNLIMITED_LOCAL", "window_5h": {"calls": 23}},
        }
        opt = compute_subworker_optimization(mock_engines)
        self.assertEqual(opt["schema"], "uaos-subworker-optimization-v1")
        self.assertTrue(opt["three_tool_ollama_boost"]["antigravity"]["active"])
        self.assertEqual(opt["three_tool_ollama_boost"]["antigravity"]["slice_line_limit"], 30)
        self.assertEqual(opt["three_tool_ollama_boost"]["antigravity"]["mandatory_read_map_lines"], 180)
        self.assertEqual(opt["claude_internal_subworker_balance"]["target_golden_ratio"]["ollama_pct"], 50.0)
        self.assertEqual(opt["claude_internal_subworker_balance"]["target_golden_ratio"]["haiku_pct"], 30.0)
        self.assertEqual(opt["claude_internal_subworker_balance"]["target_golden_ratio"]["opus_sonnet_pct"], 20.0)
        self.assertEqual(opt["claude_internal_subworker_balance"]["next_recommended_worker_tier"], "ollama")


if __name__ == "__main__":
    unittest.main()
