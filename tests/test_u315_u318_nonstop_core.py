from __future__ import annotations

import json
import unittest
from pathlib import Path

from v7_harness.coord.nonstop_orchestrator import (
    acquire_sequential_input_lease,
    adapt_code_graph_for_tool,
    build_universal_3tool_technology_matrix,
    build_zero_token_code_graph,
    enforce_session_rotation_gate,
    generate_cross_tool_handoff,
    prepare_three_tool_nonstop_schedule,
    verify_surgical_diff_and_security,
)

ROOT = Path(__file__).resolve().parents[1]


class TestU315ToU318NonstopCore(unittest.TestCase):
    def test_u315_code_graph_and_rotation_gate(self) -> None:
        graph = build_zero_token_code_graph(ROOT)
        self.assertEqual(graph["llm_tokens_used"], 0)
        self.assertGreater(graph["total_nodes"], 20)
        self.assertTrue((ROOT / ".coord" / "code_graph.json").is_file())
        self.assertTrue((ROOT / ".coord" / "GRAPH_REPORT.md").is_file())

        ok_state = enforce_session_rotation_gate(transcript_bytes=50_000, turn_count=5)
        self.assertTrue(ok_state["ok"])
        self.assertFalse(ok_state["rotate_required"])

        rot_state = enforce_session_rotation_gate(transcript_bytes=200_000, turn_count=13)
        self.assertFalse(rot_state["ok"])
        self.assertTrue(rot_state["rotate_required"])
        self.assertEqual(rot_state["action"], "ROTATE_AND_HANDOFF_NOW")

    def test_u316_cross_tool_handoff_and_memory_decay(self) -> None:
        h1 = generate_cross_tool_handoff(
            ROOT,
            card_id="U316",
            from_tool="codex",
            to_tool="claude",
            progress_pct=80,
            passed_gates=["SP1", "SP2", "SP3"],
            remaining_slice="Run SP4 independent cross-judge verification",
        )
        self.assertEqual(h1["card_id"], "U316")
        h2 = generate_cross_tool_handoff(
            ROOT,
            card_id="U316",
            from_tool="claude",
            to_tool="antigravity",
            progress_pct=95,
            passed_gates=["SP1", "SP2", "SP3", "SP4"],
            remaining_slice="Run SP5 merge and runtime install",
        )
        self.assertTrue(h2["restore_page_archive"].startswith(".coord/handoffs/archive/U316_"))

    def test_u317_input_lease_and_surgical_security_gate(self) -> None:
        lease = acquire_sequential_input_lease(
            ROOT,
            resource_id="branch_main_merge",
            owner_tool="antigravity",
            card_id="U317",
        )
        self.assertTrue(lease["ok"])
        self.assertEqual(lease["status"], "LEASE_ACQUIRED_VERIFIED")

        blocked = acquire_sequential_input_lease(
            ROOT,
            resource_id="branch_main_merge",
            owner_tool="codex",
            card_id="U317",
        )
        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["status"], "LEASE_HELD_BY_PEER")

        clean_diff = verify_surgical_diff_and_security(14, "+def clean_helper(x: int) -> int: return x + 1")
        self.assertTrue(clean_diff["ok"])

        bloated = verify_surgical_diff_and_security(35, "+line " * 35)
        self.assertFalse(bloated["surgical_slice_ok"])

    def test_u318_three_tool_nonstop_schedule_sync(self) -> None:
        res = prepare_three_tool_nonstop_schedule(ROOT)
        self.assertTrue(res["ok"])
        self.assertEqual(res["active_cards"], ["U315", "U316", "U317", "U318"])

        sub_doc = json.loads((ROOT / ".coord" / "sub_process_schedule.json").read_text(encoding="utf-8"))
        for card in sub_doc["card_sub_schedules"]:
            self.assertNotEqual(card["assigned_verifier"], "blocked")
            self.assertNotEqual(card["assigned_executor"], card["assigned_verifier"])

    def test_u319_universal_3tool_tech_matrix_and_graphify_adapters(self) -> None:
        matrix = build_universal_3tool_technology_matrix(ROOT)
        self.assertEqual(matrix["schema"], "uaos.universal_3tool_tech_matrix.v1")
        self.assertEqual(matrix["total_technologies"], 10)
        self.assertEqual(matrix["tools_covered"], ["codex", "claude", "antigravity"])

        g_audit = matrix["technologies"]["graphify"]["native_status_by_tool"]
        self.assertFalse(g_audit["codex"]["already_applied_natively"])
        self.assertFalse(g_audit["claude"]["already_applied_natively"])
        self.assertFalse(g_audit["antigravity"]["already_applied_natively"])

        for tool, expected_helper in (("codex", "gpt-6-luna"), ("claude", "claude-haiku-5-5"), ("antigravity", "gemini-3.5-flash-lite")):
            adapted = adapt_code_graph_for_tool(ROOT, tool, card_id="U315")
            self.assertEqual(adapted["tool"], tool)
            self.assertEqual(adapted["helper_model"], expected_helper)
            self.assertGreater(len(adapted["god_nodes"]), 0)


if __name__ == "__main__":
    unittest.main()
