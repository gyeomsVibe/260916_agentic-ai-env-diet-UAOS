"""U172 (master schedule P4-A): one tracked tiki-taka canon (frozen acceptance).

Receipt: the user ordered tiki-taka to be a global rule, yet on 2026-10-05 origin/main's rule block never named it, and
its only description was the untracked note .coord/notes/U144_TIKI_TAKA_3TOOL_PIPELINE.md, which still taught a
6-stage MIA pipeline after P3 (U168/U170) made 11 stages the canon. Agreed with Antigravity (relay_b89b904a): a tracked
doc names the mechanisms that now exist, and the global rule block defines tiki-taka in one line.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "78_u172-tiki-taka-three-tool-pipeline.md"
BLOCK = ROOT / "uaos_everywhere" / "uaos_global_rule_block.md"


class TikiTakaCanon(unittest.TestCase):
    def test_rule_block_defines_tiki_taka_in_exactly_one_line(self):
        lines = [line for line in BLOCK.read_text(encoding="utf-8").splitlines() if line.startswith("- 티키타카(U172)")]
        self.assertEqual(1, len(lines))
        for phrase in ("uaos coord deliver", "5턴", "U166", "작성하지 않은 도구"):
            self.assertIn(phrase, lines[0])

    def test_doc_names_the_mechanisms_that_exist(self):
        text = DOC.read_text(encoding="utf-8")
        for phrase in ("coord deliver", "U120", "U166", "coord next", "stop-gate", "5턴", "10. 디버깅 및 최종검증",
                       "U144_TIKI_TAKA_3TOOL_PIPELINE.md"):
            self.assertIn(phrase, text)

    def test_doc_drops_the_stale_six_stage_pipeline(self):
        self.assertNotIn("6단계", DOC.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
