"""U297/U297: Comprehensive tests for Official 3-Tool Helper Model Declaration,
Reasoning Model Lineup Catalog, Thinking Level (Low/Medium/High) Auto-Selection,
Master/Sub-Process Schedule Optimization, and Claude Code Ollama+Haiku 5.5 Parallel Audit.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from v7_harness.coord.capacity_planner import (
    build_capacity_aware_schedule,
    build_sub_process_schedule,
    compute_subworker_optimization,
)
from v7_harness.coord.helper_thinking_router import (
    OFFICIAL_TOOL_MODEL_LINEUP,
    PROCESS_LANES,
    SUB_PROCESS_STAGES,
    THINKING_LEVELS,
    audit_and_optimize_claude_ollama_haiku_parallel,
    get_official_tool_lineup,
    infer_lane_from_card_metadata,
    optimize_master_and_sub_schedules,
    select_optimal_helper_and_thinking,
)
from v7_harness.delegation import compute_3tool_helper_parallel_plan


class TestU297HelperThinkingOrchestration(unittest.TestCase):
    def test_official_3tool_helper_and_reasoning_lineup_declaration(self) -> None:
        lineup = get_official_tool_lineup()
        self.assertEqual(set(lineup.keys()), {"codex", "antigravity", "claude"})

        # 1. Codex official lineup & helper designation
        codex = lineup["codex"]
        self.assertEqual(codex["calculator_model"], "qwen2.5-coder:7b")
        # U304-B: one helper per tool; main GPT-6.1 Sol with Astra as the keypoint-only escalation (U257)
        self.assertEqual(codex["primary_helper_model"], "gpt-6-luna")
        self.assertEqual(codex["designated_helper_models"], ("gpt-6-luna",))
        self.assertEqual(codex["all_reasoning_models"], ("gpt-6.1-sol", "gpt-6-astra"))
        self.assertEqual(codex["thinking_levels"], ("Low", "Medium", "High"))
        self.assertEqual(codex["thinking_param_name"], "reasoning_effort")

        # 2. Antigravity official lineup & helper designation
        agy = lineup["antigravity"]
        self.assertEqual(agy["calculator_model"], "qwen2.5-coder:7b")
        # S4: one helper per tool, Gemini 3.8 Flash (3.5 Flash-Lite is not offered by the agy CLI)
        self.assertEqual(agy["primary_helper_model"], "gemini-3.8-flash")
        self.assertEqual(agy["designated_helper_models"], ("gemini-3.8-flash",))
        self.assertEqual(agy["all_reasoning_models"], ("gemini-4-argon",))
        self.assertEqual(agy["thinking_levels"], ("Low", "Medium", "High"))
        self.assertEqual(agy["thinking_param_name"], "thinking_level")

        # 3. Claude Code official lineup & helper designation
        claude = lineup["claude"]
        self.assertEqual(claude["calculator_model"], "qwen2.5-coder:7b")
        self.assertEqual(claude["primary_helper_model"], "claude-haiku-5-5")
        self.assertEqual(claude["designated_helper_models"], ("claude-haiku-5-5",))
        self.assertEqual(claude["helper_preflight_cap_tokens"], 12000)
        self.assertEqual(claude["all_reasoning_models"], ("claude-opus-5-5",))  # U304-B: sonnet removed
        self.assertEqual(claude["thinking_levels"], ("Low", "Medium", "High"))
        self.assertEqual(claude["thinking_param_name"], "effort")

    def test_auto_selection_across_roles_lanes_and_sub_stages(self) -> None:
        for tool in ("codex", "antigravity", "claude"):
            catalog = OFFICIAL_TOOL_MODEL_LINEUP[tool]
            for stage in SUB_PROCESS_STAGES:
                sel = select_optimal_helper_and_thinking(
                    tool,
                    card="U297",
                    sub_stage=stage,
                    purpose=f"Stage test {stage}",
                )
                self.assertIn(sel["designated_helper_model"], catalog["designated_helper_models"])
                self.assertIn(sel["designated_reasoning_model"], catalog["all_reasoning_models"])
                self.assertIn(sel["helper_thinking_level"], THINKING_LEVELS)
                self.assertIn(sel["reasoning_thinking_level"], THINKING_LEVELS)
                self.assertTrue(sel["disjoint_parallel_ready"])

            # Verify stage-specific thinking depth progression
            sp1 = select_optimal_helper_and_thinking(tool, sub_stage="SP1_RESEARCH_DRAFT")
            sp2 = select_optimal_helper_and_thinking(tool, sub_stage="SP2_MIA_DESIGN_AUDIT", is_keypoint=True)
            sp3 = select_optimal_helper_and_thinking(tool, sub_stage="SP3_CODE_EXECUTION", multi_file=True)
            sp4 = select_optimal_helper_and_thinking(tool, sub_stage="SP4_INDEPENDENT_VERIFY")
            sp5 = select_optimal_helper_and_thinking(tool, sub_stage="SP5_MERGE_AND_RUNTIME")

            self.assertEqual(sp1["helper_thinking_level"], "Low")
            self.assertEqual(sp1["reasoning_thinking_level"], "Low")
            self.assertEqual(sp2["helper_thinking_level"], "Medium")
            self.assertEqual(sp2["reasoning_thinking_level"], "High")
            self.assertEqual(sp3["helper_thinking_level"], "Medium")
            self.assertEqual(sp4["helper_thinking_level"], "Low")
            self.assertEqual(sp4["reasoning_thinking_level"], "High")
            self.assertEqual(sp5["helper_thinking_level"], "Low")
            self.assertEqual(sp5["reasoning_thinking_level"], "Low")

        # U304-B: a Codex keypoint escalates to Astra (U257); everything else stays on the main model
        codex_kp = select_optimal_helper_and_thinking("codex", lane_id="ARCH_DESIGN", is_keypoint=True)
        self.assertEqual(codex_kp["designated_reasoning_model"], "gpt-6-astra")
        self.assertEqual(codex_kp["reasoning_thinking_level"], "High")

        codex_verify = select_optimal_helper_and_thinking("codex", lane_id="VERIFY_AUDIT")
        self.assertEqual(codex_verify["designated_helper_model"], "gpt-6-luna")
        self.assertEqual(codex_verify["designated_reasoning_model"], "gpt-6.1-sol")

        # U304-B: the retired Claude-thinking / GPT-OSS routes are ignored flags now
        agy_claude = select_optimal_helper_and_thinking(
            "antigravity",
            lane_id="VERIFY_AUDIT",
            prefer_claude_thinking_on_agy=True,
        )
        self.assertEqual(agy_claude["designated_reasoning_model"], "gemini-4-argon")
        self.assertEqual(agy_claude["reasoning_thinking_level"], "High")

        agy_oss = select_optimal_helper_and_thinking(
            "antigravity",
            lane_id="IMPL_CODE",
            prefer_open_source_on_agy=True,
        )
        self.assertEqual(agy_oss["designated_helper_model"], "gemini-3.8-flash")
        self.assertEqual(agy_oss["helper_thinking_level"], "Low")

    def test_3tool_disjoint_parallel_plan_partitions_paths_cleanly(self) -> None:
        paths = [
            "v7_harness/coord/helper_thinking_router.py",
            "v7_harness/coord/capacity_planner.py",
            "tests/test_u297_helper_thinking_orchestration.py",
            "docs/102_MIA_U297_3Tool_Helper_Model_Declaration_and_Thinking_Level_Auto_Orchestration.md",
        ]
        for tool, expected_helper in (
            ("codex", "gpt-6-luna"),
            ("antigravity", "gemini-3.8-flash"),
            ("claude", "claude-haiku-5-5"),
        ):
            plan = compute_3tool_helper_parallel_plan(
                paths,
                caller_tool=tool,
                card="U297",
                role="implementer",
                sub_stage="SP3_CODE_EXECUTION",
            )
            self.assertEqual(plan["designated_helper_model"], expected_helper)
            self.assertTrue(plan["disjoint_verified"])
            self.assertEqual(len(plan["ollama_code_lane"]), 2)
            self.assertEqual(len(plan["helper_test_doc_lane"]), 2)
            self.assertIn(plan["helper_thinking_level"], THINKING_LEVELS)
            self.assertIn(plan["reasoning_thinking_level"], THINKING_LEVELS)

    def test_claude_ollama_haiku_parallel_census_and_optimization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".coord" / "usage").mkdir(parents=True, exist_ok=True)
            (root / ".coord" / "PLAN.md").write_text("# Plan\n", encoding="utf-8")
            rows = [
                {"work_id": "U290-1", "caller": "claude", "worker": "ollama", "model": "qwen2.5-coder:7b", "input_tokens": 1200, "output_tokens": 200},
                {"work_id": "U290-2", "caller": "claude", "worker": "claude", "model": "claude-opus-5-5", "input_tokens": 5000, "output_tokens": 900},
                {"work_id": "U290-3", "caller": "claude", "worker": "claude", "model": "claude-sonnet-5-5", "input_tokens": 4200, "output_tokens": 800},
                {"work_id": "U290-4", "caller": "claude", "worker": "haiku-5.5", "model": "claude-haiku-5-5", "input_tokens": 3000, "output_tokens": 500},
            ]
            (root / ".coord" / "usage" / "runs.jsonl").write_text(
                "\n".join(json.dumps(r) for r in rows) + "\n",
                encoding="utf-8",
            )
            audit = audit_and_optimize_claude_ollama_haiku_parallel(root)
            self.assertEqual(audit["total_ledger_runs"], 4)
            self.assertEqual(audit["haiku_5_5_telemetry"]["designated_helper_model"], "claude-haiku-5-5")
            self.assertEqual(audit["haiku_5_5_telemetry"]["total_runs"], 1)
            self.assertTrue(audit["haiku_5_5_telemetry"]["cap_compliant"])
            self.assertIn(
                audit["parallel_operation_optimization"]["priority_action"],
                ("PROMOTE_HAIKU_5_5_DISJOINT_SUBAGENT", "PROMOTE_OLLAMA_CLI_CALCULATOR", "BALANCED_5_3_2_MAINTAINED"),
            )

    def test_master_and_sub_schedule_full_optimization_and_capacity_planner_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".coord").mkdir(parents=True, exist_ok=True)
            (root / ".coord" / "PLAN.md").write_text("# Plan\n", encoding="utf-8")
            master_data = {
                "phases": [
                    {
                        "phase_id": "U297",
                        "title": "3대 도구 공식 도우미 모델 선언 및 자동 선정",
                        "state": "ACTIVE",
                        "owner_tool": "antigravity",
                        "reviewer": "claude",
                        "estimated_tokens": 24000,
                    },
                    {
                        "phase_id": "U296",
                        "title": "Codex 핵심 아키텍처 키포인트 검증",
                        "state": "READY",
                        "owner_tool": "codex",
                        "reviewer": "antigravity",
                        "keypoint": True,
                        "estimated_tokens": 20000,
                    },
                    {
                        "phase_id": "U297",
                        "title": "Claude Haiku 5.5 이원 분리 병렬 최적화",
                        "state": "REVIEW",
                        "owner_tool": "claude",
                        "reviewer": "antigravity",
                        "estimated_tokens": 18000,
                    },
                ]
            }
            (root / ".coord" / "master_schedule.json").write_text(
                json.dumps(master_data, ensure_ascii=False),
                encoding="utf-8",
            )
            mock_engines = {
                "antigravity": {
                    "presence_state": "ACTIVE",
                    "status_tier": "HEALTHY",
                    "usable_remaining_5h_tokens": 500000,
                    "budget_utilization_5h_pct": 25.0,
                    "window_5h": {"calls": 10},
                },
                "claude": {
                    "presence_state": "ACTIVE",
                    "status_tier": "HEALTHY",
                    "usable_remaining_5h_tokens": 250000,
                    "budget_utilization_5h_pct": 35.0,
                    "window_5h": {"calls": 8},
                },
                "codex": {
                    "presence_state": "ACTIVE",
                    "status_tier": "HEALTHY",
                    "usable_remaining_5h_tokens": 200000,
                    "budget_utilization_5h_pct": 20.0,
                    "window_5h": {"calls": 5},
                },
                "ollama": {"window_5h": {"calls": 20}},
                "haiku": {"window_5h": {"calls": 6}, "usable_remaining_5h_tokens": 1500000},
            }

            sched_plan = build_capacity_aware_schedule(root, mock_engines)
            self.assertIn("three_tool_helper_designation", sched_plan)
            self.assertEqual(len(sched_plan["phase_assignments"]), 3)
            for assign in sched_plan["phase_assignments"]:
                self.assertIn("helper_thinking_selection", assign)
                self.assertIn("verifier_helper_thinking_selection", assign)
                sel = assign["helper_thinking_selection"]
                self.assertIn(sel["helper_thinking_level"], THINKING_LEVELS)
                self.assertIn(sel["reasoning_thinking_level"], THINKING_LEVELS)

            sub_sched = build_sub_process_schedule(root, mock_engines, sched_plan)
            self.assertIn("official_3tool_helper_designation", sub_sched)
            self.assertEqual(sub_sched["total_active_cards"], 3)
            for card_s in sub_sched["card_sub_schedules"]:
                self.assertIn("designated_helper_model", card_s)
                self.assertIn("designated_reasoning_model", card_s)
                for sp in card_s["sub_processes"]:
                    self.assertIn("designated_helper_model", sp)
                    self.assertIn("helper_thinking_level", sp)
                    self.assertIn("designated_reasoning_model", sp)
                    self.assertIn("reasoning_thinking_level", sp)

            # Persist sub_process_schedule.json and run full optimizer
            (root / ".coord" / "sub_process_schedule.json").write_text(
                json.dumps(sub_sched, ensure_ascii=False),
                encoding="utf-8",
            )
            full_opt = optimize_master_and_sub_schedules(root, engines=mock_engines)
            self.assertEqual(full_opt["master_schedule_summary"]["total_master_phases"], 3)
            self.assertEqual(full_opt["sub_process_schedule_summary"]["total_cards"], 3)
            self.assertEqual(full_opt["sub_process_schedule_summary"]["total_sub_stages"], 15)

            sub_opt = compute_subworker_optimization(mock_engines)
            self.assertIn("official_3tool_helper_designation", sub_opt)
            self.assertEqual(
                sub_opt["three_tool_ollama_boost"]["codex"]["designated_helper_model"],
                "gpt-6-luna",
            )
            self.assertEqual(
                sub_opt["three_tool_ollama_boost"]["antigravity"]["designated_helper_model"],
                "gemini-3.8-flash",
            )
            self.assertEqual(
                sub_opt["three_tool_ollama_boost"]["claude"]["designated_helper_model"],
                "claude-haiku-5-5",
            )

    def test_cli_helper_matrix_and_parallel_thread_safety(self) -> None:
        # 1. Verify parallel thread safety across 12 concurrent calls
        def _worker(i: int) -> str:
            tool = ("codex", "antigravity", "claude")[i % 3]
            lane = PROCESS_LANES[i % len(PROCESS_LANES)]
            stage = SUB_PROCESS_STAGES[i % len(SUB_PROCESS_STAGES)]
            res = select_optimal_helper_and_thinking(
                tool,
                card=f"U{290 + i}",
                lane_id=lane,
                sub_stage=stage,
                is_keypoint=(i % 2 == 0),
                utilization_5h_pct=float((i * 15) % 95),
            )
            return f"{res['tool']}:{res['designated_helper_model']}:{res['reasoning_thinking_level']}"

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(_worker, range(12)))
        self.assertEqual(len(results), 12)

        # 2. Verify CLI subcommand `coord helper-matrix --action select`
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "v7_harness.cli",
                "coord",
                "helper-matrix",
                "--action",
                "select",
                "--tool",
                "codex",
                "--card",
                "U297",
                "--lane",
                "ARCH_DESIGN",
                "--keypoint",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        out = json.loads(proc.stdout)
        self.assertEqual(out["tool"], "codex")
        self.assertEqual(out["designated_reasoning_model"], "gpt-6-astra")
        self.assertEqual(out["reasoning_thinking_level"], "High")


if __name__ == "__main__":
    unittest.main()
