"""U168 (master schedule P3-MIA-STANDARDIZATION, skill side): one repo source installs the mia-strategic skill for
Claude Code, Codex and Antigravity, and `--check` reports a copy that drifted (frozen acceptance).

Receipt (2026-10-05): the three SKILL.md copies were hand-edited on 2026-10-04 17:21 with no source in the repo;
a Claude session that loaded the skill earlier still ran the 4-stage text while the global rules named 11 stages.
Split agreed with Antigravity (relay_c92b14a2 / relay_32c6dc5d PASS): Antigravity owns the repo-side 11-stage
pipeline, Claude owns the three-tool skill install.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.test_u37_install_everywhere import _home, _run

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "uaos_everywhere" / "skills" / "mia-strategic" / "SKILL.md"
DESTS = {
    "claude": Path(".claude") / "skills" / "mia-strategic" / "SKILL.md",
    "codex": Path(".codex") / "skills" / "mia-strategic" / "SKILL.md",
    "antigravity": Path(".gemini") / "config" / "plugins" / "mia-modular-intelligence-architect" / "skills"
                   / "mia-strategic" / "SKILL.md",
}


class SkillInstall(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = _home(Path(self._tmp.name))

    def text(self, tool):
        return (self.home / DESTS[tool]).read_text(encoding="utf-8")

    def test_the_source_is_the_11_stage_canon(self):
        source = SOURCE.read_text(encoding="utf-8")
        for stage in ("0. 사전 근거자료조사", "1. 기획", "5. 세부계획", "9. 구현", "10. 디버깅 및 최종검증"):
            self.assertIn(stage, source)

    def test_apply_installs_the_same_skill_for_all_three_tools(self):
        self.assertEqual(0, _run(self.home, "--apply")[0])
        source = SOURCE.read_text(encoding="utf-8")
        for tool in DESTS:
            self.assertEqual(source, self.text(tool), tool)
        self.assertEqual(0, _run(self.home, "--check")[0])

    def test_a_hand_edited_copy_is_drift_and_apply_restores_it(self):
        _run(self.home, "--apply")
        (self.home / DESTS["codex"]).write_text("# old 4-stage skill\n", encoding="utf-8")
        code, out = _run(self.home, "--check")
        self.assertEqual(1, code)
        self.assertTrue(any("codex" in item and "mia-strategic" in item for item in out["drift"]), out["drift"])
        self.assertEqual(0, _run(self.home, "--apply")[0])
        self.assertEqual(SOURCE.read_text(encoding="utf-8"), self.text("codex"))

    def test_other_skill_files_are_kept(self):
        extra = self.home / DESTS["claude"].parent / "LICENSE.md"
        extra.parent.mkdir(parents=True)
        extra.write_text("mine\n", encoding="utf-8")
        _run(self.home, "--apply")
        self.assertEqual("mine\n", extra.read_text(encoding="utf-8"))

    def test_uninstall_leaves_the_skill(self):
        _run(self.home, "--apply")
        _run(self.home, "--uninstall", "--apply")
        for tool in DESTS:
            self.assertTrue((self.home / DESTS[tool]).is_file(), tool)

    def test_a_missing_tool_folder_gets_no_skill(self):
        import shutil

        shutil.rmtree(self.home / ".codex")
        _run(self.home, "--apply")
        self.assertFalse((self.home / ".codex").exists())


if __name__ == "__main__":
    unittest.main()
