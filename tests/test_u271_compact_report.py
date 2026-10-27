"""U271: the user report is one compact BLUF block — at most 5 lines and 600 characters, no nested bullets — the
same budget the olla report gate (olla.REPORT_MAX_LINES/REPORT_MAX_CHARS) already measures every turn."""

import unittest
from pathlib import Path

from v7_harness import card_pipeline, firewall_audit, olla

ROOT = Path(__file__).resolve().parents[1]
URL = "https://github.com/gyeomsVibe/260916_agentic-ai-env-diet-UAOS/pull/233"
SHA = "863324d5f9a8da519fd4347c2573da2c3ed89b12"

# The 2026-10-27 report the user called too long: 10 lines, nested bullets, five unchanged DONE cards.
VERBOSE = "\n".join([
    "**결과**: UAOS-RSI의 3대 도구 사용자 보고 핵심 제목 의무화 및 전역 규칙·런타임 전면 개편(U267)이 완료됐습니다 — 모든 상태·결과·대기 줄에 한글 핵심 제목을 의무화하고 카드 ID 단독 보고를 전역 규칙과 런타임에서 원천 차단합니다",
    f"- 근거: 변경이 {URL} 로 병합됐고(커밋 863324d, 병합 커밋 2837d67, Claude 교차 판정 relay_1c07034089b362dec993c6cb890ba211 PASS, CI 40431197441 전체 스위트 2,685건 통과, 단위 테스트 127/127 통과), 런타임 0.3.0-b29d0e3d4b64 및 전역 규칙 v7.6.0에 설치됐습니다.",
    "  - 반영 코드·규칙: card_pipeline.py (clean_core_title, is_bare_id_label, card_title, format_status_line), wait_reason.py, cli.py",
    "  - 1차 출처: Conventional Commits v1.0.0, Keep a Changelog v1.1.0, Google Developer Documentation Style Guide",
    "- 3대 도구 사용자 보고 핵심 제목 의무화 및 전역 규칙·런타임 전면 개편 (U267, PR #233): DONE (863324d 병합) → 종료",
    "- 종료 카드 해묵은 P1 알림 자동 소거 (U260, PR #227): DONE (ecd0bef 병합·런타임 반영 완료) → 종료",
    "- coord listen 훅 타임아웃 상향 (U261, PR #228): DONE (a81bbe5 병합·런타임 반영 완료) → 종료",
    "- 동일 커밋 비작성자 PASS 병합 가드 (U258 & U263, PR #226): DONE (8a107de 병합·런타임 반영 완료) → 종료",
    "- 대시보드 0토큰 증분 스캔 (U265, PR #229): DONE (3e04551 병합·런타임 반영 완료) → 종료",
    "- 다음: 사용자가 할 일은 없습니다. 새 세션부터 바로 적용됩니다.",
])

COMPACT = "\n".join([
    "**결과**: 사용자 보고 핵심 제목 의무화 완료 — 모든 상태 줄에 한글 제목이 붙고 ID 단독 보고는 차단됩니다",
    f"- 근거: [PR #233]({URL}) 병합 863324d · 테스트 127/0 · 런타임 b29d0e3d4b64",
    "- 다음: 없음(새 세션부터 적용)",
])


class U271CompactReportTests(unittest.TestCase):
    def test_1_budget_is_the_olla_report_gate(self):
        self.assertEqual(card_pipeline.REPORT_MAX_LINES, olla.REPORT_MAX_LINES)
        self.assertEqual(card_pipeline.REPORT_MAX_CHARS, olla.REPORT_MAX_CHARS)

    def test_2_the_verbose_report_is_refused_for_lines_chars_and_nesting(self):
        problems = card_pipeline.compact_report_problems(VERBOSE)
        for code in ("OVER_LINES", "OVER_CHARS", "NESTED"):
            self.assertTrue(any(p.startswith(code) for p in problems), (code, problems))

    def test_3_a_compact_report_passes(self):
        self.assertEqual([], card_pipeline.compact_report_problems(COMPACT))

    def test_4_a_bare_id_status_line_is_still_refused(self):
        problems = card_pipeline.compact_report_problems("- U260 (PR #227): DONE → 종료")
        self.assertTrue(any("BARE_ID_REPORT_FORBIDDEN" in p for p in problems), problems)

    def test_5_done_report_fits_the_budget_and_leads_with_the_title(self):
        report = card_pipeline.done_report(
            "UAOS-RSI", "U267",
            "모든 상태·결과·대기 줄에 한글 핵심 제목을 의무화하고 카드 ID 단독 보고를 원천 차단합니다",
            URL, SHA, "0.3.0-b29d0e3d4b64", title="사용자 보고 핵심 제목 의무화")
        lines = report.splitlines()
        self.assertEqual(3, len(lines))
        self.assertTrue(lines[0].startswith("**결과**: 사용자 보고 핵심 제목 의무화(U267) 완료 — "), lines[0])
        self.assertIn(URL, lines[1])
        self.assertEqual([], card_pipeline.compact_report_problems(report))
        self.assertLess(len(report), len(VERBOSE) // 3)

    def test_6_rules_codify_the_compact_report(self):
        block = (ROOT / "uaos_everywhere" / "uaos_global_rule_block.md").read_text(encoding="utf-8")
        for needle in ("U271", "5줄", "600자", "변경된 항목만"):
            self.assertIn(needle, block)
        for doc in ("AGENTS.md", "GEMINI.md", "CLAUDE.md"):
            self.assertIn("U271", (ROOT / doc).read_text(encoding="utf-8"), doc)

    def test_7_card_pipeline_adds_no_subprocess_exec_sites(self):
        sites = firewall_audit.audit(ROOT)
        self.assertEqual([s for s in sites if s.path == "v7_harness/card_pipeline.py"], [])


if __name__ == "__main__":
    unittest.main()
