import unittest
from pathlib import Path

from v7_harness import global_install as gi


ROOT = Path(__file__).resolve().parents[1]


class AdaptiveNonstopPortableRulesTest(unittest.TestCase):
    def test_portable_block_preserves_replanning_and_terminal_gate(self):
        text = (ROOT / "uaos_everywhere" / "uaos_global_rule_block.md").read_text(encoding="utf-8")
        for phrase in (
            "요구·증거·설계·소유권 또는",
            "영향받은 가정·카드",
            "설계·고정 인수·계약 매뉴얼",
            "내부 의존성이지 사용자 일이 아니지만",
            "다시 시작이나 계속 명령",
            "종료 관문",
            "영속 인계·유료 토큰 0 감시",
            "`UNKNOWN`은 변화 아님",
            "최대 2회",
            "3배 비용 회귀는 실패",
            "사람 확인 목록을 바꾸지 않는다",
            "감시 만료",
            "자기 승인하지 않으며",
            "`OPEN`이고 병합 가능",
        ):
            self.assertIn(phrase, text)

    def test_actual_generated_header_keeps_single_writer(self):
        marker = "<!-- GENERATED from English canonical rules v5.29.0. Edit the source files, not this deployment. -->"
        generated = f"# Codex Global Rules\n\n{marker}\n# Canonical global agent rules\n"
        self.assertTrue(gi._is_canon_generated(generated))
        self.assertTrue(gi._is_canon_generated("\ufeff" + generated))
        self.assertTrue(gi._is_canon_generated(marker + "\n# legacy generated rules\n"))
        self.assertFalse(gi._is_canon_generated(f"# Personal rules\n- quote: {marker}\n"))
        self.assertFalse(gi._is_canon_generated(f"# Personal rules\n\n{marker}\n"))


if __name__ == "__main__":
    unittest.main()
