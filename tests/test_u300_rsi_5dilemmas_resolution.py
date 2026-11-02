"""U300 R2: Regression tests for the 5 UAOS-RSI structural dilemmas, 16 problems (P1-P16), and D1-D13 resolutions."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from v7_harness.coord import stop_gate
from v7_harness.coord.process_lanes import (
    CANONICAL_U300_DILEMMAS_RSI_SESSION_ID,
    build_context_diet_and_savings_receipt,
    heal_all_rsi_dilemmas_and_record_session,
    heal_stop_gate_overheating,
    reconcile_rsi_worker_defects,
    reconcile_ssot_presence_and_schedule,
    split_plan_archive,
)
from v7_harness.docs_manager import allocate_next_doc_number
from v7_harness.isolation.security import DEFAULT_WATCH_EXCLUDES, _watch_path_excluded


class TestU300Rsi5DilemmasResolution(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.desk = Path(self.tmp.name)
        (self.desk / ".coord" / "presence").mkdir(parents=True, exist_ok=True)
        (self.desk / ".coord" / "mailbox" / "inbox").mkdir(parents=True, exist_ok=True)
        (self.desk / ".coord" / "usage").mkdir(parents=True, exist_ok=True)
        (self.desk / ".work" / "wt_u299_active").mkdir(parents=True, exist_ok=True)

        canon_src = Path(__file__).resolve().parents[1] / "uaos_everywhere" / "uaos_global_rule_block.md"
        canon_dst = self.desk / "uaos_everywhere" / "uaos_global_rule_block.md"
        canon_dst.parent.mkdir(parents=True, exist_ok=True)
        canon_bytes = canon_src.read_bytes() if canon_src.is_file() else b"# UAOS-RSI Global Rules\n"
        canon_dst.write_bytes(canon_bytes)
        (self.desk / "GEMINI.md").write_bytes(canon_bytes)

        now = time.time()
        for tool, state in (("codex", "LIMITED"), ("claude", "ACTIVE"), ("antigravity", "ACTIVE")):
            (self.desk / ".coord" / "presence" / f"{tool}.json").write_text(
                json.dumps({"tool": tool, "state": state, "updated_at": now, "expires_at": now + 3600}),
                encoding="utf-8",
            )

        plan_lines = [
            "# 통합 실행 계획",
            "",
            "상태 기준: `READY → ACTIVE → REVIEW → DONE`; 한 번에 활성 단계 하나, 단계별 단일 소유자 한 명.",
            "",
            "| ID | 상태 | 소유자 | 산출물/판정 |",
            "|---|---|---|---|",
        ]
        for idx in range(1, 35):
            plan_lines.append(
                f"| U{idx:02d} | DONE | Antigravity | 완료된 카드 {idx:02d} 상세 설명 및 회귀 검증 완료 (PR #{idx}) — verbatim text {idx} |"
            )
        plan_lines.append("| U24 | SUPERSEDED (U15 정본 환원) | Codex | 사이드바 직접 생성 배제 |")
        plan_lines.append("| U47-C2 | DECIDED (사용자 위임) | claude | 캐시 읽기 전액 계산 유지 |")
        plan_lines.append("| U298 | REVIEW | Antigravity | 감시 세션 분리 검토 대기 |")
        plan_lines.append("| U300 | ACTIVE | Antigravity | 5대 난제 및 RSI 기록 결함 전수 해결 |")
        plan_lines.append("| U301 | READY | Claude | 버전 게이트 및 자동 업데이트 연결 |")
        plan_lines.append("- 2026-09-18 역사적 로그 1: R0 정정 구현 완료.")
        plan_lines.append("- 2026-09-19 역사적 로그 2: R3 라이브 재측정 완료.")
        (self.desk / ".coord" / "PLAN.md").write_text("\n".join(plan_lines) + "\n", encoding="utf-8")

        (self.desk / ".coord" / "master_schedule.json").write_text(
            json.dumps(
                {
                    "phases": [
                        {"id": "U297", "phase_id": "U297", "title": "Helper Lineup", "state": "DONE", "owner": "antigravity", "owner_tool": "antigravity"},
                        {"id": "U300", "phase_id": "U300", "title": "5 Dilemmas Resolution", "state": "READY", "owner": "antigravity", "owner_tool": "antigravity"},
                    ]
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (self.desk / ".coord" / "sub_process_schedule.json").write_text(
            json.dumps(
                {
                    "cards": {
                        "U300": {
                            "title": "5 Dilemmas Resolution",
                            "owner": "antigravity",
                            "stages": {
                                "SP1_RESEARCH_SPEC": {"state": "DONE"},
                                "SP2_MANUAL_CONTRACT": {"state": "DONE"},
                                "SP3_ISOLATED_IMPL": {"state": "ACTIVE"},
                            },
                        }
                    }
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_docs_manager_ignores_yymmdd_date_prefixes(self) -> None:
        docs_dir = self.desk / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        (docs_dir / "01_intro.md").write_text("# Intro\n", encoding="utf-8")
        (docs_dir / "134_audit_report.html").write_text("<h1>Audit</h1>\n", encoding="utf-8")
        (docs_dir / "260929_legacy_date_prefixed_doc.md").write_text("# Legacy\n", encoding="utf-8")
        (docs_dir / "261001_another_date_doc.md").write_text("# Legacy 2\n", encoding="utf-8")

        next_num, next_prefix = allocate_next_doc_number(self.desk)
        self.assertEqual(next_num, 135)
        self.assertEqual(next_prefix, "135_")

    def test_dilemma_1_security_watch_excludes_real_temp_noise_only(self) -> None:
        # Real transient %TEMP% noise patterns from blocked pilot receipts (U134-F2, U301-L2, R0CLOSE2/3, U23_FIX_SENTINEL2)
        for noisy_rel in (
            "uaos_test_olla_usage_26316.jsonl",
            "uaos_test_olla_usage_26316.lock",
            "tmpph23ka_j",
            "tmprsn4161r",
            "tmpph23ka_j/nested.tmp",
            "codex-clipboard-6fI91y.png",
            "cv_debug.log",
        ):
            self.assertTrue(
                _watch_path_excluded(noisy_rel, DEFAULT_WATCH_EXCLUDES),
                f"Expected transient TEMP noise {noisy_rel!r} to be excluded by DEFAULT_WATCH_EXCLUDES",
            )

        # Real unauthorized writes outside allowed patterns must never be excluded
        for bad_rel in ("unauthorized_escape.py", "src/core.py", ".coord/tamper.json", "tmp_not_8_chars_long.txt"):
            self.assertFalse(
                _watch_path_excluded(bad_rel, DEFAULT_WATCH_EXCLUDES),
                f"Expected {bad_rel!r} NOT to be excluded by DEFAULT_WATCH_EXCLUDES",
            )

        rem = reconcile_rsi_worker_defects(self.desk)
        self.assertEqual(rem["dilemma_1_status"], "GUARD_VERIFIED")
        self.assertTrue(rem["security_watch_excludes_verified"])

    def test_dilemma_2_lossless_plan_split_and_unmeasured_savings(self) -> None:
        plan_path = self.desk / ".coord" / "PLAN.md"
        original_lines = plan_path.read_text(encoding="utf-8").splitlines()
        original_card_rows = [ln for ln in original_lines if ln.startswith("| ") and not ln.startswith("| ID ") and not ln.startswith("|---")]
        self.assertEqual(len(original_card_rows), 39)

        rcp = split_plan_archive(self.desk)
        self.assertTrue(rcp["ok"])
        self.assertTrue(rcp["lossless_verified"])
        # Per global rule & F4: without a controlled paid-token run pair, token savings MUST remain UNMEASURED
        self.assertEqual(rcp["measurement_status"], "UNMEASURED")
        self.assertEqual(rcp["token_savings_status"], "UNMEASURED")
        self.assertGreater(rcp["saved_bytes"], 0)
        self.assertTrue(Path(rcp["backup_path"]).is_file())
        self.assertEqual(Path(rcp["backup_path"]).read_text(encoding="utf-8").splitlines(), original_lines)

        active_lines = plan_path.read_text(encoding="utf-8").splitlines()
        archive_path = self.desk / ".coord" / "PLAN_ARCHIVE.md"
        self.assertTrue(archive_path.is_file())
        archive_lines = archive_path.read_text(encoding="utf-8").splitlines()

        active_card_rows = [ln for ln in active_lines if ln.startswith("| ") and not ln.startswith("| ID ") and not ln.startswith("|---")]
        archived_card_rows = [ln for ln in archive_lines if ln.startswith("| ") and not ln.startswith("| ID ") and not ln.startswith("|---")]

        # Active PLAN.md keeps only the 3 non-terminal cards (U298 REVIEW, U300 ACTIVE, U301 READY)
        self.assertEqual(len(active_card_rows), 3)
        # Archive holds all 36 terminal cards (34 DONE + 1 SUPERSEDED + 1 DECIDED)
        self.assertEqual(len(archived_card_rows), 36)
        # 100% lossless round-trip: every original card row is preserved verbatim
        self.assertEqual(sorted(active_card_rows + archived_card_rows), sorted(original_card_rows))

        # Idempotency check on second invocation
        rcp2 = build_context_diet_and_savings_receipt(self.desk)
        self.assertTrue(rcp2["lossless_verified"])
        archive_lines_2 = archive_path.read_text(encoding="utf-8").splitlines()
        archived_card_rows_2 = [ln for ln in archive_lines_2 if ln.startswith("| ") and not ln.startswith("| ID ") and not ln.startswith("|---")]
        self.assertEqual(len(archived_card_rows_2), 36)

    def test_dilemma_4_stop_gate_write_point_dedup_under_parallel_calls(self) -> None:
        # 1st stop blocks the tool
        first = stop_gate.gate(self.desk, "antigravity", session="sess-u300")
        self.assertIsNotNone(first)
        self.assertEqual(first["decision"], "continue")

        # 2nd through 9th stops (run in parallel across threads) without progress must let stop through
        # and write AT MOST ONE "BLOCKED" entry to .coord/log/stop_gate.jsonl for the same (card, progress) state.
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: stop_gate.gate(self.desk, "antigravity", session="sess-u300"), range(8)))
        for r in results:
            self.assertIsNone(r)

        sg_log = self.desk / ".coord" / "log" / "stop_gate.jsonl"
        self.assertTrue(sg_log.is_file())
        rows = [json.loads(ln) for ln in sg_log.read_text(encoding="utf-8").splitlines() if ln.strip()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["card"], "U300")
        self.assertTrue(rows[0].get("state_hash"))

        # Simulate verified progress -> resets guard -> blocks once -> next stop logs 1 new state_hash
        run_dir = self.desk / ".coord" / "pilot" / "runs" / "U300-1"
        run_dir.mkdir(parents=True, exist_ok=True)
        summary_file = run_dir / "summary.json"
        summary_file.write_text("{}", encoding="utf-8")
        future_ts = time.time() + 1200
        os.utime(summary_file, (future_ts, future_ts))

        again = stop_gate.gate(self.desk, "antigravity", session="sess-u300")
        self.assertIsNotNone(again)
        self.assertIsNone(stop_gate.gate(self.desk, "antigravity", session="sess-u300"))
        self.assertIsNone(stop_gate.gate(self.desk, "antigravity", session="sess-u300"))

        rows_after = [json.loads(ln) for ln in sg_log.read_text(encoding="utf-8").splitlines() if ln.strip()]
        self.assertEqual(len(rows_after), 2)
        self.assertNotEqual(rows_after[0]["state_hash"], rows_after[1]["state_hash"])

        # Active stop_gate_antigravity.json must NOT be moved/deleted even if its mtime is old
        sg_guard = self.desk / ".coord" / "presence" / "stop_gate_antigravity.json"
        old_ts = time.time() - 172800
        os.utime(sg_guard, (old_ts, old_ts))
        # Merged card guard IS archived cleanly
        merged_guard = self.desk / ".coord" / "presence" / "stop_gate_U297.json"
        merged_guard.write_text(json.dumps({"card": "U297", "blocks": 2}), encoding="utf-8")

        dedup = heal_stop_gate_overheating(self.desk)
        self.assertEqual(dedup["dilemma_4_status"], "STATE_HASH_DEDUP_VERIFIED")
        self.assertEqual(dedup["consecutive_state_hash_duplicates"], 0)
        self.assertEqual(dedup["deleted_count"], 0)
        self.assertTrue(sg_guard.is_file(), "Active stop_gate guard must not be moved based on age_s > 86400")
        self.assertIn("stop_gate_U297.json", dedup["cleared_stale_guard_files"])

    def test_dilemma_3_and_5_end_to_end_session_and_cli_heal_dilemmas(self) -> None:
        ssot = reconcile_ssot_presence_and_schedule(self.desk)
        self.assertTrue(ssot["ssot_aligned"])
        self.assertTrue(ssot["code_gate"]["rules_synced"])

        res = heal_all_rsi_dilemmas_and_record_session(self.desk, publish_mailbox_notices=True)
        self.assertTrue(res["ok"])
        self.assertEqual(res["session_id"], CANONICAL_U300_DILEMMAS_RSI_SESSION_ID)
        self.assertEqual(res["operational_status"], "LIVE_OPERATING")
        self.assertEqual(res["live_declaration_ko"], "실가동 됨")
        self.assertTrue(res["all_5_dilemmas_resolved"])

        # CLI `coord lanes --action heal-dilemmas`
        proc = subprocess.run(
            [sys.executable, "-m", "v7_harness.cli", "coord", "lanes", "--project", str(self.desk), "--action", "heal-dilemmas"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        cli_out = json.loads(proc.stdout)
        self.assertEqual(cli_out["operational_status"], "LIVE_OPERATING")
        self.assertTrue(cli_out["all_5_dilemmas_resolved"])


if __name__ == "__main__":
    unittest.main()
