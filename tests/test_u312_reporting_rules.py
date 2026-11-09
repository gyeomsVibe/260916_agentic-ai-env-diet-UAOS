"""U312 operating policy: card purpose/current work and bilingual thrift are universal."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class U312ReportingRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.block = (ROOT / 'uaos_everywhere/uaos_global_rule_block.md').read_text(encoding='utf-8')
        cls.policy = next(line for line in cls.block.splitlines() if line.startswith('- **카드 목적·현재 작업 요약'))

    def test_policy_applies_to_every_user_query_and_all_three_tools(self):
        for phrase in ('U312', '3도구 공통', '모든 사용자 질의 답변', '한글/영어 병기', 'Korean/English paired key summaries'):
            self.assertIn(phrase, self.policy)

    def test_master_detail_results_and_waits_explain_card_and_current_work(self):
        for phrase in ('마스터/세부 스케줄·결과·진행·대기', '카드 ID + 구현 목적의 핵심 제목 + 현재 작업',
                       'ID + meaningful purpose title + current work', 'ID 단독 보고를 금지'):
            self.assertIn(phrase, self.policy)

    def test_budget_reuses_recorded_translations_without_weakening_quality(self):
        for phrase in ('토큰예산 대비 최대성과', '품질 관문을 낮추지 않는다', '기록된 한글/영어 필드를 재사용',
                       '번역은 한 번 기록', 'no paid translation per report', '추측하지 않는다'):
            self.assertIn(phrase, self.policy)

    def test_english_inter_agent_language_is_separate_from_user_bilingual(self):
        self.assertIn('inter-agent messages and relays: English only', self.policy)
        self.assertIn('도구 간 메시지·릴레이는 항상 영어', self.policy)

    def test_bounds_and_explicit_guide_exception_are_preserved(self):
        self.assertIn('최대 5줄·600자', self.policy)
        self.assertIn('명시 요청한 완전 가이드만 길이 예외', self.policy)
        self.assertIn('U267', self.block)
        self.assertIn('U271', self.block)
        self.assertIn('BARE_ID_REPORT_FORBIDDEN', self.block)

    def test_rule_version_matches_portable_header_and_includes_u312(self):
        version = (ROOT / 'uaos_everywhere/VERSION').read_text(encoding='utf-8').strip()
        self.assertRegex(version, r'^\d+\.\d+\.\d+$')
        self.assertGreaterEqual(tuple(map(int, version.split('.'))), (0, 6, 0))
        self.assertIn(f'<!-- uaos-version: {version} -->', self.block)


if __name__ == '__main__':
    unittest.main()
