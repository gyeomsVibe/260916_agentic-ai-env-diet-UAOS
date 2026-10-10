"""U176: the nonstop-default rule is present in all three adapters and the project rule files.

Receipt (2026-10-06, user report): tools kept asking for approval (settings.json allow-list, DONE status, merge) although
the user's stance is unattended nonstop work. Fixed acceptance: each file carries the U176 bullet, the five-item human
list, the deny-never-shrinks clause, and the tiki-taka consensus clause.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    ROOT / "uaos_everywhere" / "adapters" / "claude.md",
    ROOT / "uaos_everywhere" / "adapters" / "codex.md",
    ROOT / "uaos_everywhere" / "adapters" / "antigravity.md",
    ROOT / "AGENTS.md",
    ROOT / "GEMINI.md",
    ROOT / "CLAUDE.md",
]


class NonstopDefault(unittest.TestCase):
    def test_every_rule_file_carries_u176(self):
        for f in FILES:
            text = f.read_text(encoding="utf-8")
            self.assertIn("U176", text, f.name)
            self.assertIn("무승인 논스톱", text, f.name)
            self.assertIn("사람 전용은 다섯", text, f.name)
            self.assertIn("거부 규칙은 줄이지 않는다", text, f.name)
            self.assertIn("티키타카", text, f.name)


if __name__ == "__main__":
    unittest.main()
