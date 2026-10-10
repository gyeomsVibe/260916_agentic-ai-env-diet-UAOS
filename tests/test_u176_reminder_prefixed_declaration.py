"""U176: a user-window declaration typed behind Claude Code's own leading `<system-reminder>` block still counts.

Receipt (2026-10-10): the first prompt of a desktop worktree session arrived as the worktree reminder followed by
"지금부터 여기가 새로운 사용자 대상 대화창구이다…"; no title was claimed and the window kept its generated name.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord import repeat_error
from v7_harness.coord import user_window as uw
from v7_harness.coord.deliver import is_human_prompt, typed_prompt

ROOT = Path(__file__).resolve().parents[1]
REMINDER = ("<system-reminder>\nYou are operating in a git worktree.\nWorktree path: D:\\w\\.claude\\worktrees\\x\n"
            "Worktree name: x\n</system-reminder>\n\n")
TYPED = "지금부터 여기가 새로운 사용자 대상 대화창구이다. 출석하고 타도구에게 알려라."
SESSION = "11111111-2222-4333-8444-555555555555"


class ReminderPrefixTest(unittest.TestCase):
    def test_leading_reminders_are_dropped_and_nothing_else(self):
        self.assertEqual(typed_prompt(REMINDER + TYPED), TYPED)
        self.assertEqual(typed_prompt(REMINDER + REMINDER + TYPED), TYPED)
        self.assertEqual(typed_prompt('<system-reminder data-kind="worktree">x</system-reminder>\n' + TYPED), TYPED)
        self.assertEqual(typed_prompt(TYPED), TYPED)
        self.assertIsNone(typed_prompt(None))
        mid = TYPED + "\n" + REMINDER
        self.assertEqual(typed_prompt(mid), mid)

    def test_declaration_behind_a_reminder_counts(self):
        self.assertTrue(uw.is_declaration(REMINDER + TYPED))

    def test_injected_text_stays_rejected(self):
        for text in (REMINDER, REMINDER + "<task-notification>대화창구이다 여기</task-notification>",
                     "<task-notification>지금부터 여기가 대화창구이다</task-notification>",
                     "<system-reminder>지금부터 여기가 대화창구이다"):
            self.assertFalse(uw.is_declaration(text), text)
        self.assertFalse(is_human_prompt(REMINDER))
        self.assertFalse(is_human_prompt("<system-reminders>x</system-reminders>" + TYPED))
        self.assertTrue(is_human_prompt(REMINDER + TYPED))

    def test_error_report_behind_a_reminder_counts(self):
        self.assertTrue(repeat_error.is_error_report(REMINDER + "대화창 이름 변경 오류를 고쳐줘"))
        self.assertFalse(repeat_error.is_error_report(REMINDER))

    def test_prompt_hook_names_the_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "proj"
            (project / ".coord").mkdir(parents=True)
            (project / ".coord" / "PLAN.md").write_text("# PLAN\n", encoding="utf-8")
            event = {"session_id": SESSION, "hook_event_name": "UserPromptSubmit", "cwd": str(project),
                     "prompt": REMINDER + TYPED}
            env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "UAOS_WORKER")}
            env["PYTHONPATH"] = str(ROOT)
            run = subprocess.run(
                [sys.executable, "-m", "v7_harness.cli", "coord", "presence", "--tool", "claude", "--state", "ACTIVE",
                 "--from-hook", "--say", "p1", "--delta"],
                input=json.dumps(event).encode("utf-8"), capture_output=True, env=env, cwd=str(ROOT), timeout=60)
            out = run.stdout.decode("utf-8", "replace")
            self.assertEqual(run.returncode, 0, run.stderr.decode("utf-8", "replace"))
            self.assertIn("set_session_title", out)
            self.assertRegex(out, r"\[사용자 대화창구-\d{6}-1\]")
            record = json.loads((project / ".coord" / "presence" / "user_windows.json").read_text(encoding="utf-8"))
            self.assertEqual(record["claude"][0]["thread"], SESSION)
            desk = json.loads((project / ".coord" / "presence" / "user_desk_claude.json").read_text(encoding="utf-8"))
            self.assertEqual(desk["thread"], SESSION)


if __name__ == "__main__":
    unittest.main()
