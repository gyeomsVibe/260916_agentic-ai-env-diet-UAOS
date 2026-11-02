"""U300: Full resolution of the 5 UAOS-RSI structural dilemmas & RSI record defects + scheduled v7.6.3 operation."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from v7_harness import card_pipeline as cp
from v7_harness import docs_manager as dm
from v7_harness.coord.process_lanes import (
    CANONICAL_U300_DILEMMAS_RSI_SESSION_ID,
    _verify_live_rsi_state,
    build_context_diet_and_savings_receipt,
    filter_false_positive_external_writes,
    heal_all_rsi_dilemmas_and_record_session,
    heal_stop_gate_overheating,
    reconcile_rsi_worker_defects,
    reconcile_ssot_presence_and_schedule,
    slice_ollama_prompt_chunks,
)


class TestU300Rsi5DilemmasResolution(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".coord" / "rsi").mkdir(parents=True, exist_ok=True)
        (self.root / ".coord" / "presence").mkdir(parents=True, exist_ok=True)
        (self.root / ".coord" / "logs").mkdir(parents=True, exist_ok=True)
        (self.root / ".coord" / "usage").mkdir(parents=True, exist_ok=True)
        (self.root / ".coord" / "windows").mkdir(parents=True, exist_ok=True)
        (self.root / ".work").mkdir(parents=True, exist_ok=True)
        (self.root / "uaos_everywhere").mkdir(parents=True, exist_ok=True)
        real_canon = Path(__file__).resolve().parents[1] / "uaos_everywhere" / "uaos_global_rule_block.md"
        (self.root / "uaos_everywhere" / "uaos_global_rule_block.md").write_bytes(real_canon.read_bytes())
        (self.root / "GEMINI.md").write_text(
            "# GEMINI\n## UAOS-RSI\n- U300 5대 난제 및 RSI 기록 결함 전수 자가치유·스케줄링 표준(v7.6.3)\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_docs_manager_ignores_6digit_date_prefixes(self) -> None:
        docs_dir = self.root / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        (docs_dir / "133_dashboard.md").write_text("# 133\n", encoding="utf-8")
        (docs_dir / "134_UAOS_RSI_problems_and_dilemmas_full_audit_report.html").write_text(
            "<title>134 Report</title>", encoding="utf-8"
        )
        (docs_dir / "261023_usage-accounting.md").write_text("# Usage\n", encoding="utf-8")

        next_num, prefix = dm.allocate_next_doc_number(self.root)
        self.assertEqual(next_num, 135)
        self.assertEqual(prefix, "135_")

    def test_card_pipeline_claims_mcp_sessionless_rows_inside_card_window(self) -> None:
        import datetime
        start = 1_790_000_000.0
        cp.new_manual(self.root, "U300", "5 Dilemmas Resolution", now=start)
        olla_log = self.root / "olla_usage.jsonl"
        ts_str = datetime.datetime.fromtimestamp(start + 50.0).isoformat(timespec="seconds")
        olla_log.write_text(
            json.dumps({
                "ts": ts_str,
                "event": "digest",
                "caller": "unknown",
                "via": "mcp",
                "cached": False,
                "paid_tokens_if_read": 12000,
            })
            + "\n",
            encoding="utf-8",
        )
        res = cp.claim(self.root, "U300", "any-session-id", olla_log, now=start + 100.0)
        self.assertTrue(res["ok"])
        self.assertEqual(res["claimed"], 1)

    def test_dilemma_1_worker_scope_and_slice_guards(self) -> None:
        filtered = filter_false_positive_external_writes(
            [
                ".work/pilot_tmp/a.txt",
                "__pycache__/foo.pyc",
                "docs/00_DOCUMENT_INDEX.md",
                "v7_harness/coord/process_lanes.py",
                "unauthorized/hack.py",
            ],
            allowed_files=["v7_harness/coord/process_lanes.py"],
        )
        self.assertFalse(filtered["ok"])
        self.assertEqual(filtered["true_violations"], ["unauthorized/hack.py"])
        self.assertEqual(len(filtered["benign_ignored"]), 4)

        chunks = slice_ollama_prompt_chunks([f"line {i}" for i in range(45)], max_lines=20)
        self.assertEqual([len(c) for c in chunks], [20, 20, 5])

        rem = reconcile_rsi_worker_defects(self.root)
        self.assertEqual(rem["dilemma_1_status"], "RESOLVED_GUARD_ACTIVE")
        self.assertEqual(rem["ollama_max_slice_lines"], 20)
        self.assertTrue(rem["mcp_sessionless_claim_enabled"])

    def test_dilemma_2_context_diet_and_measured_savings(self) -> None:
        plan_lines = ["# Master Plan\n"] + [
            f"| U{i:03d} | Feature {i} | DONE | PR #{i} merged |\n" for i in range(1, 250)
        ] + [
            "| U300 | 5대 난제 전수 해결 | ACTIVE | in progress |\n"
        ]
        (self.root / ".coord" / "PLAN.md").write_text("".join(plan_lines), encoding="utf-8")

        receipt = build_context_diet_and_savings_receipt(self.root, max_recent_done=10)
        self.assertEqual(receipt["measurement_status"], "MEASURED")
        self.assertGreater(receipt["before_plan_bytes"], receipt["after_active_bytes"])
        self.assertGreater(receipt["saved_tokens_per_turn_est"], 0)
        self.assertGreater(receipt["reduction_pct"], 50.0)
        self.assertTrue((self.root / ".coord" / "PLAN_ACTIVE.md").is_file())
        self.assertTrue((self.root / ".coord" / "PLAN_ARCHIVE_INDEX.json").is_file())

    def test_dilemma_3_ssot_and_rules_sync_verification(self) -> None:
        gate = _verify_live_rsi_state(self.root, "7.6.3", "0.3.0-test")
        self.assertTrue(gate["rules_synced"])
        self.assertEqual(len(gate["canonical_rules_sha256"]), 64)

        ssot = reconcile_ssot_presence_and_schedule(self.root)
        self.assertTrue(ssot["ssot_aligned"])
        self.assertTrue(ssot["code_gate"]["rules_synced"])

    def test_dilemma_4_stop_gate_state_hash_deduplication_and_stale_clearance(self) -> None:
        # Write 5 identical stop_gate blocks for U180 and 1 for U299
        sg_log = self.root / ".coord" / "logs" / "stop_gate.jsonl"
        rows = [
            {"ts": 100 + i, "card": "U180", "reason": "STALL_HOLD", "state": "WAITING"}
            for i in range(5)
        ] + [{"ts": 200, "card": "U299", "reason": "DONE_CHECK", "state": "PASS"}]
        sg_log.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

        # Mark U299 as DONE in master_schedule.json and create a stale stop_gate_u299.json
        (self.root / ".coord" / "master_schedule.json").write_text(
            json.dumps({"phases": [{"phase_id": "U299", "state": "DONE"}]}),
            encoding="utf-8",
        )
        sg_guard = self.root / ".coord" / "presence" / "stop_gate_u299.json"
        sg_guard.write_text(json.dumps({"card": "U299", "reason": "STALE"}), encoding="utf-8")

        res = heal_stop_gate_overheating(self.root)
        self.assertEqual(res["dilemma_4_status"], "RESOLVED_STATE_HASH_DEDUP_ACTIVE")
        self.assertEqual(res["total_historical_events"], 6)
        self.assertEqual(res["unique_state_hashes"], 2)
        self.assertEqual(res["suppressed_duplicate_wakes"], 4)
        self.assertIn("stop_gate_u299.json", res["cleared_stale_guard_files"])
        self.assertFalse(sg_guard.exists())
        self.assertEqual(res["deleted_count"], 0)

    def test_full_u300_heal_and_rsi_watch_integration(self) -> None:
        (self.root / ".coord" / "PLAN.md").write_text(
            "# Plan\n" + "".join(f"| U{i:03d} | Done item | DONE |\n" for i in range(1, 60)),
            encoding="utf-8",
        )
        (self.root / ".coord" / "master_schedule.json").write_text(
            json.dumps({"phases": [{"phase_id": "U299", "state": "DONE", "owner_tool": "antigravity"}]}),
            encoding="utf-8",
        )
        res = heal_all_rsi_dilemmas_and_record_session(
            self.root,
            publish_mailbox_notices=True,
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["session_id"], CANONICAL_U300_DILEMMAS_RSI_SESSION_ID)
        self.assertEqual(res["operational_status"], "LIVE_OPERATING")
        self.assertEqual(res["live_declaration_ko"], "실가동 됨")
        self.assertTrue(res["all_5_dilemmas_resolved"])
        self.assertTrue(res["code_gate"]["rules_synced"])
        self.assertTrue(
            (self.root / ".coord" / "rsi" / "sessions" / CANONICAL_U300_DILEMMAS_RSI_SESSION_ID / "SESSION.json").is_file()
        )


if __name__ == "__main__":
    unittest.main()
