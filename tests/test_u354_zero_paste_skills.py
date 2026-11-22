"""U354-A: zero-paste desk skill, the /go /takeover /resume command sources and the Stage 0-R MIA tier router.

Receipt (contract `.work/notes/command_tower_261122/U354_ZERO_PASTE_UX_CONTRACT_261122.md`): the user pasted a
2,136-character takeover prompt into every new desk, and every 1-3 line idea ran all 11 MIA stages. Fixed acceptance:
the canonical skill carries the 3 protocols and the Safety 7 human-only list; the existing installer (unchanged,
C7 hold) already plans the skill for all 3 tools; the commands keep the Safety and author!=judge gates; the router
picks Fast/Standard/Full by the letter's rules, escalates upward only, and never claims a measured saving.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from v7_harness import global_install as gi
from v7_harness.coord.mia_triage import INVARIANTS, classify_mia_tier

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "uaos_everywhere" / "skills" / "uaos-desk" / "SKILL.md"
COMMANDS = REPO / "uaos_everywhere" / "commands"
SAFETY_7 = ("삭제", "원격 푸시", "배포", "공개 게시", "유료 지출", "계정/권한 변경", "OS 설정 변경")
BYPASS = ("bypass safety", "skip judge", "auto-push without approval", "--no-verify", "승인 없이 push",
          "safety 면제")


def _home(root: Path) -> Path:
    home = root / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".codex").mkdir()
    (home / ".gemini" / "config").mkdir(parents=True)
    return home


class DeskSkillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = SKILL.read_text(encoding="utf-8")

    def test_frontmatter_and_triggers(self) -> None:
        self.assertTrue(self.text.startswith("---\nname: uaos-desk\ndescription: "))
        for trigger in ("총괄", "이어서", "재개", "/go", "/takeover", "/resume"):
            self.assertIn(trigger, self.text.split("---", 2)[1])

    def test_three_protocols(self) -> None:
        self.assertIn("## 실행 프로토콜 3종", self.text)
        for heading in ("### 1. 신규 아이디어 구체화", "### 2. 총괄 승격 및 창구 인계", "### 3. 한도 리셋 및 동결 해동"):
            self.assertEqual(self.text.count(heading), 1, heading)
        for word in ("Stage 0-R", "MIA-Fast", "MIA-Standard", "MIA-Full", "fencing_epoch", "READY"):
            self.assertIn(word, self.text)

    def test_safety_7_cannot_be_bypassed(self) -> None:
        invariants = self.text.split("## 안전 및 권한 불변성", 1)[1]
        for item in SAFETY_7:
            self.assertIn(item, invariants)
        self.assertIn("면제할 수 없다", invariants)
        self.assertIn("`author != judge`", invariants)
        self.assertIn("절대 생략할 수 없으며", self.text)
        for phrase in BYPASS:
            self.assertNotIn(phrase, self.text.lower())


class InstallerSyncTests(unittest.TestCase):
    """C7 hold: the generic `uaos_everywhere/skills/*/SKILL.md` loop already ships the desk skill to all 3 tools."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = _home(Path(self._tmp.name))
        self.source = SKILL.read_text(encoding="utf-8")

    def test_plan_syncs_desk_skill_to_all_three_tools(self) -> None:
        changes = {c.target: c for c in gi.plan(self.home, sys.executable, repo=REPO, rules=False)}
        for tool in ("claude", "codex", "antigravity"):
            change = changes[f"{tool} skill uaos-desk"]
            self.assertEqual(change.action, "CREATE")
            self.assertEqual(change.path, self.home / gi.SKILL_DIRS[tool] / "uaos-desk" / "SKILL.md")
            self.assertEqual(change.new_text, self.source)

    def test_plan_is_unchanged_once_installed(self) -> None:
        for tool in ("claude", "codex", "antigravity"):
            dest = self.home / gi.SKILL_DIRS[tool] / "uaos-desk" / "SKILL.md"
            dest.parent.mkdir(parents=True)
            dest.write_text(self.source, encoding="utf-8", newline="")
        changes = {c.target: c for c in gi.plan(self.home, sys.executable, repo=REPO, rules=False)}
        for tool in ("claude", "codex", "antigravity"):
            self.assertEqual(changes[f"{tool} skill uaos-desk"].action, "UNCHANGED")

    def test_installer_has_no_desk_special_case(self) -> None:
        installer = (REPO / "v7_harness" / "global_install.py").read_text(encoding="utf-8")
        self.assertNotIn("uaos-desk", installer)
        self.assertIn('glob("*/SKILL.md")', installer)


class CommandSourceTests(unittest.TestCase):
    def _read(self, name: str) -> str:
        return (COMMANDS / f"{name}.md").read_text(encoding="utf-8")

    def test_three_commands_have_frontmatter_and_safety(self) -> None:
        self.assertEqual(sorted(p.name for p in COMMANDS.glob("*.md")), ["go.md", "resume.md", "takeover.md"])
        for name in ("go", "takeover", "resume"):
            text = self._read(name)
            self.assertTrue(text.startswith(f"---\ndescription: /{name}"), name)
            self.assertIn("Safety 사람 전용 외", text, name)
            for phrase in BYPASS:
                self.assertNotIn(phrase, text.lower(), name)

    def test_go_binds_arguments_and_cross_judge(self) -> None:
        go = self._read("go")
        self.assertEqual(go.count("$ARGUMENTS"), 1)
        for word in ("Stage 0-R", "MIA-Fast", "author!=judge"):
            self.assertIn(word, go)
        self.assertIn("author!=judge", self._read("resume"))
        self.assertIn("fencing_epoch", self._read("takeover"))


class MiaTriageTests(unittest.TestCase):
    def _tier(self, text: str, **kw) -> str:
        return classify_mia_tier(text, **kw)["tier"]

    def test_fast_for_small_plain_fix(self) -> None:
        result = classify_mia_tier("오타 수정", file_count=1)
        self.assertEqual((result["tier"], result["steps"], result["thinking_level"]), ("MIA-Fast", 4, "Low"))
        self.assertFalse(result["escalated"])
        self.assertIsNone(result["escalation_reason"])
        self.assertEqual(self._tier("fix typo in build log", paths=["a.py", "b.py"]), "MIA-Fast")

    def test_standard_is_the_default(self) -> None:
        result = classify_mia_tier("대시보드 신규 추가", file_count=2)
        self.assertEqual((result["tier"], result["steps"], result["thinking_level"]), ("MIA-Standard", 6, "Medium"))
        self.assertEqual(result["card_slots"], ["Research", "MIA", "Execute", "Verify"])
        self.assertFalse(result["escalated"])
        self.assertEqual(self._tier("오타 수정"), "MIA-Standard")  # unknown file count is never Fast
        self.assertEqual(self._tier("add UI toggle", file_count=1), "MIA-Standard")
        self.assertEqual(self._tier("refactor helper", file_count=1), "MIA-Standard")

    def test_auto_escalation_from_fast(self) -> None:
        for kw, reason in ((dict(file_count=1, prior_failures=1), "prior_failures==1"),
                           (dict(file_count=3), "file_count>=3"),
                           (dict(file_count=2, needs_external_spec=True), "needs_external_spec")):
            result = classify_mia_tier("오타 수정", **kw)
            self.assertEqual(result["tier"], "MIA-Standard", kw)
            self.assertTrue(result["escalated"], kw)
            self.assertIn(reason, result["escalation_reason"])

    def test_full_triggers(self) -> None:
        self.assertEqual(self._tier("작은 수정", file_count=1, explicit_mia=True), "MIA-Full")
        self.assertEqual(self._tier("MIA모드 발동: 로그 정리", file_count=1), "MIA-Full")
        self.assertEqual(self._tier("MIA 전략절차로 검토", file_count=1), "MIA-Full")
        self.assertEqual(self._tier("문구 수정", file_count=6), "MIA-Full")
        for word in ("권한", "삭제", "전역", "보안", "규칙", "스키마", "아키텍처", "security", "Permission", "schema",
                     "kernel", "evaluator", "calculator_gate", "global_install"):
            self.assertEqual(self._tier(f"{word} 손보기", file_count=1), "MIA-Full", word)
        for path in ("v7_harness/calculator_gate.py", "v7_harness\\rsi.py", "./v7_harness/global_install.py",
                     "uaos_everywhere/uaos_global_rule_block.md", ".githooks/pre-commit"):
            result = classify_mia_tier("fix", paths=[path])
            self.assertEqual(result["tier"], "MIA-Full", path)
            self.assertTrue(any(r.startswith("sensitive_path:") for r in result["reasons"]), path)

    def test_two_failures_escalate_to_full(self) -> None:
        result = classify_mia_tier("오타 수정", file_count=1, prior_failures=2)
        self.assertEqual((result["tier"], result["steps"], result["thinking_level"]), ("MIA-Full", 11, "High"))
        self.assertTrue(result["escalated"])
        self.assertEqual(result["escalation_reason"], "prior_failures>=2")

    def test_ascii_keywords_match_whole_words(self) -> None:
        self.assertEqual(self._tier("rebuild guide", file_count=1), "MIA-Fast")  # `ui` inside a word
        self.assertEqual(self._tier("schemata", file_count=1), "MIA-Fast")

    def test_invariants_and_unmeasured_on_every_tier(self) -> None:
        cases = [dict(text="오타", file_count=1), dict(text="신규 기능", file_count=2),
                 dict(text="보안", file_count=1)]
        tiers = set()
        for case in cases:
            result = classify_mia_tier(**case)
            tiers.add(result["tier"])
            self.assertEqual(result["invariants"], list(INVARIANTS))
            self.assertEqual(result["invariants"], ["author!=judge", "fixed_acceptance_exit_0",
                                                    "backup_before_overwrite", "safety_7_human_only"])
            self.assertEqual(result["token_savings"], "UNMEASURED")
            self.assertTrue(result["reasons"])
        self.assertEqual(tiers, {"MIA-Fast", "MIA-Standard", "MIA-Full"})


class MiaTriageReviewR2Tests(unittest.TestCase):
    """AGY REVISE on U354-A-A2 (relay_eaf8a65f): four counterexamples that routed risky work to MIA-Fast."""

    def _tier(self, text: str, **kw) -> str:
        return classify_mia_tier(text, **kw)["tier"]

    def test_c1_backslash_sensitive_path_in_text(self) -> None:
        for text in ("fix v7_harness\\rsi.py", "edit .githooks\\pre-commit",
                     "edit uaos_everywhere\\uaos_global_rule_block.md"):
            result = classify_mia_tier(text, file_count=1)
            self.assertEqual(result["tier"], "MIA-Full", text)
            self.assertTrue(any(r.startswith("sensitive_path:") for r in result["reasons"]), text)

    def test_c2_case_variant_windows_paths(self) -> None:
        for path in ("V7_Harness\\rsi.py", ".GitHooks\\pre-commit", "D:\\Repo\\V7_HARNESS\\Calculator_Gate.py"):
            self.assertEqual(self._tier("fix", paths=[path]), "MIA-Full", path)

    def test_c3_english_high_risk_parity_and_boundaries(self) -> None:
        for text in ("delete records", "update global rule", "update permissions", "patch auth_permission",
                     "new architecture"):
            self.assertEqual(self._tier(text, file_count=1), "MIA-Full", text)
        self.assertEqual(self._tier("rebuild guide", file_count=1), "MIA-Fast")
        self.assertEqual(self._tier("schemata", file_count=1), "MIA-Fast")

    def test_c4_blank_paths_are_unknown_scope(self) -> None:
        for paths in ([""], ["   "], ["", " "]):
            result = classify_mia_tier("오타 수정", paths=paths)
            self.assertEqual(result["tier"], "MIA-Standard", paths)
            self.assertIsNone(result["file_count"], paths)
        self.assertEqual(classify_mia_tier("오타 수정", paths=["a.py", "", "A.PY"])["file_count"], 1)


if __name__ == "__main__":
    unittest.main()
