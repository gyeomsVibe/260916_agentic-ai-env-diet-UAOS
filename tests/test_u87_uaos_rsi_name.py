"""U87: the portable rule block carries the formal name UAOS-RSI and each tool adapter its role and budget.

User order 2026-09-29: UAOS-RSI is the default operating system of every agentic AI environment, with each tool's role
and token budget set per tool. The global-rules canon (v6.0.0) says so on this PC; this block is what the installer
writes on a PC without that canon, so it must say the same.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from v7_harness.global_install import ADAPTER_SOURCE, RULE_BLOCK_SOURCE, plan

ROOT = Path(__file__).resolve().parents[1]


class UaosRsiNameTests(unittest.TestCase):
    def test_block_heading_is_the_formal_name(self) -> None:
        first = RULE_BLOCK_SOURCE.read_text(encoding="utf-8").splitlines()[0]
        self.assertTrue(first.startswith("## UAOS-RSI — "), first)
        self.assertIn("기본 운영체제", first)

    def test_every_adapter_sets_role_and_budget(self) -> None:
        for tool, path in ADAPTER_SOURCE.items():
            text = Path(path).read_text(encoding="utf-8")
            self.assertEqual(1, text.count("- UAOS-RSI 역할:"), tool)
            self.assertEqual(1, text.count("- UAOS-RSI 예산:"), tool)

    def test_a_plain_home_gets_the_name_and_only_its_own_budget(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            for folder in (".claude", ".codex", ".gemini"):
                (home / folder).mkdir()
            changes = {change.target: change for change in plan(home, "python", repo=ROOT)}
            for tool in ("claude", "codex", "antigravity"):
                text = changes[f"{tool} rules"].new_text
                self.assertIn("## UAOS-RSI — ", text)
                self.assertEqual(1, text.count("- UAOS-RSI 예산:"), tool)


if __name__ == "__main__":
    unittest.main()
