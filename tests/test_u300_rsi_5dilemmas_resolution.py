"""U300 R3: Regression tests for the 5 UAOS-RSI structural dilemmas, 16 problems (P1-P16), D1-D13, and Claude F1-F11 + R1-R3."""

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

from v7_harness.adapters.agy import AgyRequest
from v7_harness.coord import stop_gate
from v7_harness.coord.process_lanes import (
    CANONICAL_U300_DILEMMAS_RSI_SESSION_ID,
    build_context_diet_and_savings_receipt,
    build_workspace_garbage_manifest,
    heal_all_rsi_dilemmas_and_record_session,
    heal_stop_gate_overheating,
    reconcile_rsi_worker_defects,
    reconcile_ssot_presence_and_schedule,
    split_plan_archive,
)
from v7_harness.docs_manager import allocate_next_doc_number
from v7_harness.execution.agy_launcher import AgyProcessLauncher
from v7_harness.isolation.errors import ExternalWriteDetectedError
from v7_harness.isolation.security import DEFAULT_WATCH_EXCLUDES, _watch_path_excluded, snapshot_watch_roots


class TestU300Rsi5DilemmasResolution(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.desk = Path(self.tmp.name)
        (self.desk / ".coord" / "presence").mkdir(parents=True, exist_ok=True)
        (self.desk / ".coord" / "mailbox" / "inbox").mkdir(parents=True, exist_ok=True)
        (self.desk / ".coord" / "usage").mkdir(parents=True, exist_ok=True)
        (self.desk / ".coord" / "rsi").mkdir(parents=True, exist_ok=True)
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
        # R1: Generic tmp???????? globs MUST NOT be in DEFAULT_WATCH_EXCLUDES (no sandbox weakening)
        self.assertNotIn("tmp????????", DEFAULT_WATCH_EXCLUDES)
        self.assertNotIn("tmp????????/**", DEFAULT_WATCH_EXCLUDES)

        for noisy_rel in (
            "uaos_test_olla_usage_26316.jsonl",
            "uaos_test_olla_usage_26316.lock",
            "codex-clipboard-6fI91y.png",
            "cv_debug.log",
        ):
            self.assertTrue(
                _watch_path_excluded(noisy_rel, DEFAULT_WATCH_EXCLUDES),
                f"Expected transient TEMP noise {noisy_rel!r} to be excluded by DEFAULT_WATCH_EXCLUDES",
            )

        for bad_rel in ("unauthorized_escape.py", "src/core.py", ".coord/tamper.json", "tmpABCDEFGH", "tmpABCDEFGH/escape.txt"):
            self.assertFalse(
                _watch_path_excluded(bad_rel, DEFAULT_WATCH_EXCLUDES),
                f"Expected {bad_rel!r} NOT to be excluded by DEFAULT_WATCH_EXCLUDES",
            )

        # R1: Worker mkdtemp lands in run-private runs_dir/tmp, while global %TEMP%\tmpABCDEFGH still raises EXTERNAL_WRITE
        global_temp = self.desk / "global_temp"
        global_temp.mkdir(parents=True, exist_ok=True)
        snap = snapshot_watch_roots([global_temp], recursive_roots=[global_temp])

        runs_dir = self.desk / ".coord" / "pilot" / "runs" / "U300-MKDTEMP"
        stage_dir = self.desk / ".coord" / "pilot" / "stage" / "U300-MKDTEMP"
        stage_dir.mkdir(parents=True, exist_ok=True)
        probe_out = stage_dir / "mkdtemp_path.txt"
        worker_script = self.desk / ".work" / "mkdtemp_worker.py"
        worker_script.write_text(
            "import json, pathlib, tempfile\n"
            "d = tempfile.mkdtemp()\n"
            "(pathlib.Path(d) / 'inner.txt').write_text('ok', encoding='utf-8')\n"
            f"pathlib.Path({str(probe_out)!r}).write_text(d, encoding='utf-8')\n"
            "print(json.dumps({'status': 'SUCCESS', 'response': 'ok', 'usage': {'input_tokens': 1, 'output_tokens': 1}}))\n",
            encoding="utf-8",
        )
        req = AgyRequest(
            task_id="U300-MKDTEMP",
            title="test",
            prompt="test",
            workspace=stage_dir,
            isolation_mode="staging",
            print_timeout_s=30,
        )
        launcher = AgyProcessLauncher(
            agy_command=[sys.executable, str(worker_script)],
            request=req,
            runs_dir=runs_dir,
        )
        decision = launcher.launch(attempt_id="U300-MKDTEMP-a001", acceptance_hash="h1")
        self.assertTrue(decision.successful)
        created_tmp_dir = Path(probe_out.read_text(encoding="utf-8").strip()).resolve()
        self.assertTrue(created_tmp_dir.is_relative_to((runs_dir / "tmp").resolve()))
        snap.assert_unchanged()

        escape_dir = global_temp / "tmpABCDEFGH"
        escape_dir.mkdir(parents=True, exist_ok=True)
        (escape_dir / "escape.txt").write_text("bad\n", encoding="utf-8")
        with self.assertRaises(ExternalWriteDetectedError):
            snap.assert_unchanged()

    def test_dilemma_2_lossless_plan_split_and_unmeasured_savings(self) -> None:
        plan_path = self.desk / ".coord" / "PLAN.md"
        original_lines = plan_path.read_text(encoding="utf-8").splitlines()
        original_card_rows = [ln for ln in original_lines if ln.startswith("| ") and not ln.startswith("| ID ") and not ln.startswith("|---")]
        self.assertEqual(len(original_card_rows), 39)

        rcp = split_plan_archive(self.desk)
        self.assertTrue(rcp["ok"])
        self.assertTrue(rcp["lossless_verified"])
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

        self.assertEqual(len(active_card_rows), 3)
        self.assertEqual(len(archived_card_rows), 36)
        self.assertEqual(sorted(active_card_rows + archived_card_rows), sorted(original_card_rows))

        rcp2 = build_context_diet_and_savings_receipt(self.desk)
        self.assertTrue(rcp2["lossless_verified"])
        archive_lines_2 = archive_path.read_text(encoding="utf-8").splitlines()
        archived_card_rows_2 = [ln for ln in archive_lines_2 if ln.startswith("| ") and not ln.startswith("| ID ") and not ln.startswith("|---")]
        self.assertEqual(len(archived_card_rows_2), 36)

    def test_dilemma_4_stop_gate_write_point_dedup_under_parallel_calls(self) -> None:
        first = stop_gate.gate(self.desk, "antigravity", session="sess-u300")
        self.assertIsNotNone(first)
        self.assertEqual(first["decision"], "continue")

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

        sg_guard = self.desk / ".coord" / "presence" / "stop_gate_antigravity.json"
        old_ts = time.time() - 172800
        os.utime(sg_guard, (old_ts, old_ts))
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

        # R2 + R4 + R5: Before 50 post-fix runs exist, reconcile_rsi_worker_defects reports UNMEASURED / DEGRADED
        cutoff_epoch = time.mktime(time.strptime("2026-11-03T02:00:00", "%Y-%m-%dT%H:%M:%S"))
        runs_path = self.desk / ".coord" / "usage" / "runs.jsonl"
        runs_path.write_text(
            "\n".join(
                [
                    json.dumps({"work_id": "U300-1", "worker": "ollama", "outcome": "BLOCKED", "reason": "EXTERNAL_WRITE", "ts": cutoff_epoch - 3600.0}),
                    json.dumps({"work_id": "U300-2", "worker": "ollama", "outcome": "REWORK", "reason": "CODE", "ts": cutoff_epoch - 1800.0}),
                    json.dumps({"work_id": "U300-3", "worker": "ollama", "outcome": "UNUSABLE", "reason": "EMPTY_OUTPUT", "ts": "not-a-float"}),
                    json.dumps({"work_id": "U300-4", "worker": "ollama", "outcome": "PASS", "ts": cutoff_epoch + 60.0}),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        d1_pre = reconcile_rsi_worker_defects(self.desk)
        self.assertEqual(d1_pre["dilemma_1_status"], "DEGRADED")
        self.assertFalse(d1_pre["has_post_fix_50_window"])
        self.assertEqual(d1_pre["last_50_by_worker"]["ollama"]["post_fix_runs"], 1)
        self.assertEqual(d1_pre["observed_worker_totals"]["ollama"]["blocked"], 3)
        self.assertEqual(d1_pre["observed_cause_counts"].get("CODE"), 1)
        self.assertEqual(d1_pre["observed_cause_counts"].get("EMPTY_OUTPUT"), 1)

        res_pre = heal_all_rsi_dilemmas_and_record_session(self.desk, publish_mailbox_notices=False)
        self.assertEqual(res_pre["operational_status"], "DEGRADED")
        self.assertFalse(res_pre["all_5_dilemmas_resolved"])

        # R2 + R3 + R4: Write 50 post-fix PASS runs with epoch float ts >= cutoff_epoch and a user-approved deletion_receipt_20261103.json
        post_fix_lines = [
            json.dumps({"work_id": f"U300-PF-{i}", "worker": "ollama", "outcome": "PASS", "ts": cutoff_epoch + 120.0 + float(i)})
            for i in range(50)
        ]
        runs_path.write_text("\n".join(post_fix_lines) + "\n", encoding="utf-8")

        removed_items = (
            [{"path": f"wt_{i}", "kind": "worktree", "bytes": 1000} for i in range(57)]
            + [{"path": f"work_{i}", "kind": "work", "bytes": 1000} for i in range(444)]
        )
        (self.desk / ".coord" / "rsi" / "deletion_receipt_20261103.json").write_text(
            json.dumps(
                {
                    "schema": "uaos-deletion-receipt-v1",
                    "apply": True,
                    "at": "2026-11-03T01:43:33+0900",
                    "policy": "merged+clean+48h worktrees via git worktree remove; .work >14d not protected",
                    "removed": removed_items,
                    "bytes_removed": 3794946516,
                }
            ),
            encoding="utf-8",
        )

        d5 = build_workspace_garbage_manifest(self.desk)
        self.assertTrue(d5["deletion_receipt_verified"])
        self.assertEqual(d5["removed_worktrees_count"], 57)
        self.assertEqual(d5["removed_work_entries_count"], 444)
        self.assertEqual(d5["deleted_count"], 501)
        self.assertEqual(d5["bytes_removed"], 3794946516)

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
