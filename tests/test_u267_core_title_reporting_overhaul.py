"""U267: 3-tool user reporting overhaul — every status/result/wait line must carry a concise Korean core title,
never bare card/PR/SHA identifiers alone (`BARE_ID_REPORT_FORBIDDEN`).
"""

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness import card_pipeline, cli, firewall_audit
from v7_harness.coord import wait_reason

ROOT = Path(__file__).resolve().parents[1]
PR_URL = "https://github.com/gyeomsVibe/260916_agentic-ai-env-diet-UAOS/pull/227"
SHA = "ecd0bef1234567890abcdef1234567890abcdef1"


class U267CoreTitleReportingOverhaulTests(unittest.TestCase):
    def test_1_bare_id_status_lines_are_rejected_and_core_titled_lines_pass(self):
        bad_report = "\n".join([
            "- U260 (PR #227): DONE (ecd0bef 병합·런타임 반영 완료) → 종료",
            "- U261 (PR #228): DONE (a81bbe5 병합·런타임 반영 완료) → 종료",
            "- U258 & U263 (PR #226): REVIEW (R5 head 8a107de, 45/45 테스트 통과) → Claude·Codex 동일 헤드 PASS 수신 즉시 자동 병합",
            "- U265 (PR #229): REVIEW (head 4d0e154) → 동료 도구 독립 판정 수신 즉시 자동 병합",
        ])
        problems = card_pipeline.validate_user_status_lines(bad_report)
        self.assertEqual(4, len(problems), problems)
        for p in problems:
            self.assertIn("BARE_ID_REPORT_FORBIDDEN", p)

        for bare in ("U260", "U260 (PR #227)", "PR #227", "U258 & U263 (PR #226)", "ecd0bef", ""):
            self.assertTrue(card_pipeline.is_bare_id_label(bare), bare)
            with self.assertRaises(ValueError, msg=bare):
                card_pipeline.format_status_line("U260", bare, "DONE", "종료", pr=227)

        good_line = card_pipeline.format_status_line(
            "U260",
            "U260: 종료 카드 해묵은 P1 알림 자동 소거",
            "DONE",
            "종료",
            pr=227,
            detail="ecd0bef 병합·런타임 반영 완료",
        )
        self.assertEqual(
            "- 종료 카드 해묵은 P1 알림 자동 소거 (U260, PR #227): DONE (ecd0bef 병합·런타임 반영 완료) → 종료",
            good_line,
        )
        self.assertEqual([], card_pipeline.validate_user_status_lines(good_line))

    def test_2_card_title_and_collect_results_resolve_core_title_and_user_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            main = Path(tmp) / "main"
            (main / ".git").mkdir(parents=True)
            card_pipeline.new_manual(main, "U260", "종료 카드 해묵은 P1 알림 자동 소거", now=100.0)
            self.assertEqual("종료 카드 해묵은 P1 알림 자동 소거", card_pipeline.card_title(main, "U260"))

            made = card_pipeline.write_result(main, "U260", PR_URL, "yes", "45/0", "none")
            self.assertEqual(f"RESULT U260 | PR {PR_URL} | MERGEABLE yes | tests 45/0 | blocker none", made["line"])
            self.assertEqual("종료 카드 해묵은 P1 알림 자동 소거", made["title"])
            self.assertIn("종료 카드 해묵은 P1 알림 자동 소거 (U260, PR #227)", made["user_line"])
            self.assertEqual([], card_pipeline.validate_user_status_lines(made["user_line"]))

            rows = card_pipeline.collect_results(main)
            self.assertEqual(1, len(rows))
            self.assertEqual("종료 카드 해묵은 P1 알림 자동 소거", rows[0]["title"])
            self.assertIn("종료 카드 해묵은 P1 알림 자동 소거 (U260, PR #227)", rows[0]["user_line"])

            report = card_pipeline.done_report(
                "UAOS",
                "U260",
                "종료된 카드의 이전 차단 편지가 더 이상 P1 경보를 울리지 않습니다",
                PR_URL,
                SHA,
                title="종료 카드 해묵은 P1 알림 자동 소거",
            )
            self.assertIn("종료 카드 해묵은 P1 알림 자동 소거(U260)", report.splitlines()[0])

    def test_3_wait_reason_and_wait_status_report_include_core_titles(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".coord" / "presence").mkdir(parents=True)
            sched = {
                "schedule_id": "U267",
                "phases": [
                    {
                        "phase_id": "U265",
                        "title": "대시보드 0토큰 증분 스캔 및 공식 모델명 정본화",
                        "state": "REVIEW",
                        "author_tool": "antigravity",
                        "reviewer": "claude",
                        "waiting_on": "peer-verdict",
                    },
                    {
                        "phase_id": "U266",
                        "title": "3대 도구 대화창 제목 자동변환 개편",
                        "state": "ACTIVE",
                        "owner_tool": "antigravity",
                        "waiting_on": "implementation",
                    },
                ],
            }
            (project / ".coord" / "master_schedule.json").write_text(json.dumps(sched), encoding="utf-8")
            lines = wait_reason.reasons(project, "claude", now=1792080000.0)
            self.assertEqual(2, len(lines), lines)
            self.assertIn("[대시보드 0토큰 증분 스캔 및 공식 모델명 정본화] U265 판정 대기 중", lines[0])
            self.assertIn("[3대 도구 대화창 제목 자동변환 개편] U266 작업 대기 중", lines[1])

            rep = wait_reason.write_wait_status_report(project, "claude", now=1792080000.0)
            self.assertEqual("WAITING", rep["state"])
            self.assertTrue(any("대시보드 0토큰 증분 스캔 및 공식 모델명 정본화" in r for r in rep["remaining"]), rep)
            self.assertEqual("", card_pipeline.card_title(project, "A"))

    def test_4_global_rule_block_and_project_rules_codify_core_title_reporting(self):
        block = (ROOT / "uaos_everywhere" / "uaos_global_rule_block.md").read_text(encoding="utf-8")
        self.assertIn("U267", block)
        self.assertIn("핵심 제목", block)
        self.assertIn("BARE_ID_REPORT_FORBIDDEN", block)
        for doc in ("AGENTS.md", "GEMINI.md", "CLAUDE.md"):
            content = (ROOT / doc).read_text(encoding="utf-8")
            self.assertIn("U267", content, doc)
            self.assertIn("핵심 제목", content, doc)

    def test_5_card_pipeline_adds_no_subprocess_exec_sites(self):
        sites = firewall_audit.audit(ROOT)
        self.assertEqual([s for s in sites if s.path == "v7_harness/card_pipeline.py"], [])


if __name__ == "__main__":
    unittest.main()
