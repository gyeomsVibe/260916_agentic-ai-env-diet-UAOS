"""U45: General UAOS budget, manual core, and template initialization tests."""

from __future__ import annotations

import argparse
from pathlib import Path
import tempfile
import unittest

from v7_harness.budget_route import route_authority
from v7_harness.cli import cmd_coord_init, PROJECT_MANUAL_TEMPLATE, CONTRACT_MANUAL_TEMPLATE
from v7_harness.global_install import ADAPTER_SOURCE, RULE_BLOCK_SOURCE, plan, uaos_command
from v7_harness.manual import lint


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
            self.assertTrue(lint(contract_tpl.read_text(encoding="utf-8"), root).ok)

            # A second init is a no-op and preserves user-owned bytes.
            before = {path: path.read_bytes() for path in (plan, proj_man, contract_tpl)}
            self.assertEqual(0, cmd_coord_init(args))
            self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_version_is_bumped_to_0_3_0(self) -> None:
        version_file = Path(__file__).resolve().parent.parent / "uaos_everywhere" / "VERSION"
        self.assertTrue(version_file.is_file())
        self.assertEqual("0.3.0", version_file.read_text(encoding="utf-8").strip())

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

    def test_budget_route_is_state_based_and_unknown_fails_closed(self) -> None:
        self.assertEqual("codex", route_authority("ACTIVE", "ACTIVE", "ACTIVE"))
        self.assertEqual("claude", route_authority("LIMITED", "ACTIVE", "ACTIVE"))
        self.assertEqual("antigravity", route_authority("ABSENT", "LIMITED", "ACTIVE"))
        self.assertEqual("BLOCKED_UNKNOWN", route_authority("UNKNOWN", "ACTIVE", "ACTIVE"))
        self.assertEqual("BLOCKED_NO_ACTIVE_AUTHORITY", route_authority("ABSENT", "ABSENT", "LIMITED"))

    def test_installer_keeps_common_bytes_and_adds_only_matching_adapter(self) -> None:
        common = RULE_BLOCK_SOURCE.read_text(encoding="utf-8").strip()
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            for folder in (".claude", ".codex", ".gemini"):
                (home / folder).mkdir()
            changes = plan(home, "python", repo=Path(__file__).resolve().parent.parent)
            rule_changes = {c.target.split()[0]: c.new_text for c in changes if c.target.endswith(" rules")}
            self.assertEqual({"claude", "codex", "antigravity"}, set(rule_changes))
            for tool, rendered in rule_changes.items():
                command = uaos_command("python", home / ".uaos" / "uaos.py")
                self.assertIn(common.replace("{uaos}", command), rendered)
                self.assertIn(ADAPTER_SOURCE[tool].read_text(encoding="utf-8").strip(), rendered)
                for other, source in ADAPTER_SOURCE.items():
                    if other != tool:
                        self.assertNotIn(source.read_text(encoding="utf-8").strip(), rendered)

    def test_role_adapters_are_minimal(self) -> None:
        for source in ADAPTER_SOURCE.values():
            bullets = [line for line in source.read_text(encoding="utf-8").splitlines() if line.startswith("- ")]
            self.assertLessEqual(len(bullets), 6)
            self.assertGreater(len(bullets), 0)

    def test_version_update_is_present_once_in_both_readmes(self) -> None:
        root = Path(__file__).resolve().parent.parent
        for relative in ("README.md", "uaos_everywhere/README.md"):
            text = (root / relative).read_text(encoding="utf-8")
            self.assertEqual(1, text.count("<!-- uaos-update:u45-0.3.0 -->"))
            self.assertEqual(1, text.count("## 업데이트 (0.3.0, 2026-09-26)"))


if __name__ == "__main__":
    unittest.main()
