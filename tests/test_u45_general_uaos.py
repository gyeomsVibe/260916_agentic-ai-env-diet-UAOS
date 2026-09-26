"""U45: General UAOS budget, manual core, and template initialization tests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
import unittest

from v7_harness.cli import cmd_coord_init, PROJECT_MANUAL_TEMPLATE, CONTRACT_MANUAL_TEMPLATE


class GeneralUaosCoreTests(unittest.TestCase):
    def test_coord_init_creates_project_manual_and_contract_template(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            args = argparse.Namespace(project=str(root))
            ret = cmd_coord_init(args)
            self.assertEqual(0, ret)
            
            plan = root / ".coord" / "PLAN.md"
            proj_man = root / ".coord" / "PROJECT_MANUAL.md"
            contract_tpl = root / ".coord" / "tasks" / "contract_template.md"
            
            self.assertTrue(plan.is_file())
            self.assertTrue(proj_man.is_file())
            self.assertTrue(contract_tpl.is_file())
            
            self.assertIn("프로젝트 총괄 매뉴얼", proj_man.read_text(encoding="utf-8"))
            self.assertIn("work_id:", contract_tpl.read_text(encoding="utf-8"))

    def test_version_is_bumped_to_0_2_0(self) -> None:
        version_file = Path(__file__).resolve().parent.parent / "uaos_everywhere" / "VERSION"
        self.assertTrue(version_file.is_file())
        self.assertEqual("0.2.0", version_file.read_text(encoding="utf-8").strip())

    def test_global_rule_block_has_core_invariants(self) -> None:
        block_file = Path(__file__).resolve().parent.parent / "uaos_everywhere" / "uaos_global_rule_block.md"
        self.assertTrue(block_file.is_file())
        text = block_file.read_text(encoding="utf-8")
        self.assertIn("계약 매뉴얼", text)
        self.assertIn("Ollama는 계산기다", text)
        self.assertIn("건설적 자율 릴레이", text)
        self.assertIn("자가개선(RSI)", text)
        self.assertIn("권한대행", text)
        self.assertIn("멈추고 사용자에게 물을 것", text)


if __name__ == "__main__":
    unittest.main()
