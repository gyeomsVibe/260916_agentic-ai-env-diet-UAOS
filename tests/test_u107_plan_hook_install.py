"""U107-A: Claude Code and Codex get the per-prompt local-model split hint Antigravity already gets, durably.

Receipt (윤겸스, 2026-10-01): "너희도 Antigravity처럼 올라마를 자동으로 자유롭게 사용 … 3대 도구 공통으로". Antigravity gets
PLAN_HINT on every invocation (`olla hook-agy PreInvocation`); Claude and Codex had `olla hook-plan` only by a hand edit
of their home config, which the next `uaos install --apply` would neither keep in step nor remove. The installer now
wires it on UserPromptSubmit for both, only where `olla` is installed, and the hint no longer asks for the retired
`- 과정:` report line (brief-ko dropped it, U92). Fixed acceptance written by the judge (claude) first.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness import olla
from tests.test_u103_olla_parity import AGY_OLLA_GUARD

PLAN = "olla hook-plan"


def _commands(groups: list) -> list[str]:
    return [h.get("command") for g in groups for h in g.get("hooks", [])]


class PlanHookInstallTests(unittest.TestCase):
    def _home(self, olla_path: str | None, *steps: tuple[str, ...]) -> tuple[dict, dict]:
        from tests.test_u37_install_everywhere import _home, _run

        with tempfile.TemporaryDirectory() as temp:
            home = _home(Path(temp))
            (home / ".gemini" / "config" / "hooks.json").write_text(json.dumps({"olla-guard": AGY_OLLA_GUARD}),
                                                                    encoding="utf-8")
            with mock.patch("v7_harness.global_install.shutil.which",
                            side_effect=lambda name, *a, **k: olla_path if name == "olla" else None):
                for step in steps:
                    self.assertEqual(0, _run(home, *step)[0], step)
            claude = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8")).get("hooks", {})
            codex = json.loads((home / ".codex" / "hooks.json").read_text(encoding="utf-8")).get("hooks", {})
        return claude, codex

    def test_both_tools_get_the_plan_hint_once_when_olla_is_installed(self) -> None:
        # Applying twice must not stack a second copy: the hint rides on every prompt.
        claude, codex = self._home("D:/AI-Models/bin/olla", ("--apply",), ("--apply",), ("--check",))
        for hooks in (claude, codex):
            self.assertEqual(1, _commands(hooks["UserPromptSubmit"]).count(PLAN))
            # The presence hook that carries P1 hand-offs stays next to it.
            self.assertTrue(any("uaos.py" in str(c) for c in _commands(hooks["UserPromptSubmit"])))

    def test_no_plan_hint_without_olla(self) -> None:
        claude, codex = self._home(None, ("--apply",))
        for hooks in (claude, codex):
            self.assertNotIn(PLAN, _commands(hooks.get("UserPromptSubmit", [])))

    def test_uninstall_removes_the_plan_hint(self) -> None:
        claude, codex = self._home("D:/AI-Models/bin/olla", ("--apply",), ("--apply", "--uninstall"))
        for hooks in (claude, codex):
            self.assertNotIn(PLAN, _commands(hooks.get("UserPromptSubmit", [])))


class PlanHintTextTests(unittest.TestCase):
    def test_hint_no_longer_asks_for_the_retired_process_line(self) -> None:
        self.assertNotIn("과정", olla.PLAN_HINT)
        self.assertIn("**결과**:", olla.PLAN_HINT)
        self.assertIn("local_read_map", olla.PLAN_HINT)


if __name__ == "__main__":
    unittest.main()
