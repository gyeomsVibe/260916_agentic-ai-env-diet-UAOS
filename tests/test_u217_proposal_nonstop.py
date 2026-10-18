"""U217: a proposed follow-up enters the no-approval tiki-taka chain, never a user click (frozen acceptance).

Receipt: on 2026-10-18 Claude left three follow-ups as app proposal cards; the user had to click each, and one
(U214-CLOSURE) duplicated a card a Codex executor already owned, because the proposal skipped the three-tool
consultation. The user then ordered every tool's proposals into the no-approval nonstop tiki-taka procedure, whose
purpose is the most output per token budget.
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
        for phrase in ("제안(U217)", "PROPOSAL", "중복", "무승인", "토큰"):
            self.assertIn(phrase, line)

    def test_claude_adapter_replaces_the_click_card(self) -> None:
        text = (ADAPTERS / "claude.md").read_text(encoding="utf-8")
        for phrase in ("own_initiative", "PROPOSAL", "user_asked"):
            self.assertIn(phrase, text)

    def test_adapters_stay_minimal(self) -> None:
        for tool in ("claude", "codex", "antigravity"):
            bullets = [line for line in (ADAPTERS / f"{tool}.md").read_text(encoding="utf-8").splitlines()
                       if line.startswith("- ")]
            self.assertLessEqual(len(bullets), 6, tool)


if __name__ == "__main__":
    unittest.main()
