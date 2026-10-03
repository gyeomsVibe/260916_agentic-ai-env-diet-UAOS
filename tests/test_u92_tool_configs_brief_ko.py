"""U92: the repository copy of the brief-ko output style matches the report shape the tools actually use.

Seen 2026-09-29 after the v7.0.0 rules merge: tool-configs/claude/output-styles/brief-ko.md still carried the pre-v6.2
shape (결과·과정·근거, "Say nothing between tool calls") while ~/.claude/output-styles/brief-ko.md had moved on through
v6.2, v6.2.1, and v7.0.0. The installer's --check does not cover output styles, so a restore from this folder would
have brought back an old report shape without any warning.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COPY = ROOT / "tool-configs" / "claude" / "output-styles" / "brief-ko.md"
HOME_STYLE = Path.home() / ".claude" / "output-styles" / "brief-ko.md"


def normalized(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").strip()


class BriefKoCopyTests(unittest.TestCase):
    def test_copy_has_the_current_report_shape(self) -> None:
        text = normalized(COPY)
        # U132 (2026-10-02, 윤겸스): the five-field shape gave 20-line reports; the style now caps a report at 3 lines.
        for line in ("**결과**:", "at most 3 lines", "no nested bullets"):
            self.assertIn(line, text)
        self.assertNotIn("- 근거:", text)
        self.assertNotIn("- 과정:", text)
        self.assertNotIn("Say nothing between tool calls", text)

    @unittest.skipUnless(HOME_STYLE.is_file(), "no installed brief-ko output style on this machine")
    def test_copy_matches_the_installed_style(self) -> None:
        self.assertEqual(normalized(COPY), normalized(HOME_STYLE))

    def test_readme_does_not_offer_the_pre_v6_claude_rules_as_a_restore_source(self) -> None:
        readme = normalized(ROOT / "tool-configs" / "README.md")
        self.assertNotIn("결과·과정·근거", readme)
        self.assertIn("갱신 안 함", readme)


if __name__ == "__main__":
    unittest.main()
