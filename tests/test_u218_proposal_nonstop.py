"""U218: a proposed follow-up enters the no-approval tiki-taka chain, never a user click (frozen acceptance).

Receipt: on 2026-10-18 Claude left three follow-ups as app proposal cards; the user had to click each, and one
(U214-CLOSURE) duplicated a card a Codex executor already owned, because the proposal skipped the three-tool
consultation. The user then ordered every tool's proposals into the no-approval nonstop tiki-taka procedure, whose
purpose is the most output per token budget. First shipped under U217, which collided with the installer
read-retry card; Codex REVISE (relay_3f608230) moved it to U218, kept peer-unavailable and UNKNOWN fencing in the
wording, and forbade dressing a standing order up as a user's own session request.

These are source-wording checks only: they do not prove the installed workflow runs or that tokens are saved.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLOCK = ROOT / "uaos_everywhere" / "uaos_global_rule_block.md"
ADAPTERS = ROOT / "uaos_everywhere" / "adapters"


class ProposalNonstopTest(unittest.TestCase):
    def test_the_one_tiki_taka_line_routes_proposals_for_all_tools(self) -> None:
        lines = [line for line in BLOCK.read_text(encoding="utf-8").splitlines() if line.startswith("- 티키타카(U172)")]
        self.assertEqual(1, len(lines))
        line = lines[0]
        for phrase in ("제안(U218)", "PROPOSAL", "쓰지 않은 카드 번호", "단일 소유자", "중복", "LIMITED/ABSENT",
                       "UNKNOWN", "무승인", "토큰"):
            self.assertIn(phrase, line)
        self.assertNotIn("제안(U217)", line)

    def test_claude_adapter_replaces_the_click_card_without_synthetic_provenance(self) -> None:
        text = (ADAPTERS / "claude.md").read_text(encoding="utf-8")
        for phrase in ("제안(U218)", "own_initiative", "PROPOSAL", "user_asked", "실제로 별도 세션을 요청"):
            self.assertIn(phrase, text)
        self.assertNotIn("상시 지시에 따라 `initiation: user_asked`", text)

    def test_adapters_stay_minimal(self) -> None:
        for tool in ("claude", "codex", "antigravity"):
            bullets = [line for line in (ADAPTERS / f"{tool}.md").read_text(encoding="utf-8").splitlines()
                       if line.startswith("- ")]
            self.assertLessEqual(len(bullets), 6, tool)


if __name__ == "__main__":
    unittest.main()
