"""U103: every tool (Claude, Codex, Antigravity) in any UAOS project learns what the others changed, never its own.

Receipt (윤겸스, 2026-10-01): "not only you — the notice must be common to all three tools; UAOS-RSI works in any
project." Facts found: the delta hook ran only in Claude's settings, its ROOT was this one project's path, and it hid
only Claude's letters. Codex's prompt hook printed nothing (`--say none`); Antigravity saw only letters addressed to it.
`v7_harness.coord.desk_delta` moves the logic into the runtime that every project installs, keyed by the calling tool.
Fixed acceptance written by the judge (claude) before the implementation.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from v7_harness.coord import desk_delta

# Fake clock (epoch seconds). Letters and files land at NOW - 10; the first look defaults to NOW - 3600.
NOW = 1_800_000_000.0


def _git(root: Path, *args: str, at: float = NOW - 10) -> None:
    env = dict(os.environ, GIT_AUTHOR_DATE=f"@{int(at)} +0000", GIT_COMMITTER_DATE=f"@{int(at)} +0000",
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env=env)


class DeskDeltaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.inbox = self.root / ".coord" / "mailbox" / "inbox"
        self.inbox.mkdir(parents=True)
        (self.root / ".coord" / "PLAN.md").write_text("| Card | Status | Owner | Note |\n| U1 | TODO | c | x |\n",
                                                      encoding="utf-8")
        _git(self.root, "init", "-q")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _letter(self, name: str, actor: str, message: str) -> None:
        path = self.inbox / f"{name}.json"
        path.write_text(json.dumps({"message_id": name, "payload": {"actor": actor, "message": message}}),
                        encoding="utf-8")
        os.utime(path, (NOW - 10, NOW - 10))

    def _look(self, tool: str, session: str = "s1", now: float = NOW) -> str:
        return desk_delta.delta_text(self.root, tool, session, now=now)

    def test_each_tool_skips_only_its_own_letters(self) -> None:
        self._letter("evt_20260930T2341-claude-0001", "claude", "claude ran U1")
        self._letter("evt_20260930T2342-codex-0001", "codex", "codex judged U1")
        self._letter("relay_aaaa", "antigravity", "antigravity validated U1")
        for tool, own, others in (("claude", "claude ran U1", ("codex judged U1", "antigravity validated U1")),
                                  ("codex", "codex judged U1", ("claude ran U1", "antigravity validated U1")),
                                  ("antigravity", "antigravity validated U1", ("claude ran U1", "codex judged U1"))):
            text = self._look(tool)
            self.assertNotIn(own, text, tool)
            for line in others:
                self.assertIn(line, text, tool)

    def test_agy_alias_is_antigravity(self) -> None:
        self._letter("relay_bbbb", "antigravity", "antigravity note")
        self.assertNotIn("antigravity note", self._look("agy"))

    def test_second_look_is_silent_and_sessions_are_separate(self) -> None:
        self._letter("relay_cccc", "codex", "codex verdict")
        self.assertIn("codex verdict", self._look("claude", "s1"))
        self.assertEqual("", self._look("claude", "s1", now=NOW + 5))
        self.assertIn("codex verdict", self._look("claude", "s2", now=NOW + 5))

    def test_plan_status_change_is_reported(self) -> None:
        self._look("codex")
        plan = self.root / ".coord" / "PLAN.md"
        plan.write_text(plan.read_text(encoding="utf-8").replace("| U1 | TODO |", "| U1 | DONE |"), encoding="utf-8")
        self.assertIn("PLAN U1: TODO -> DONE", self._look("codex", now=NOW + 5))

    def test_commits_skip_the_callers_own_trailer(self) -> None:
        (self.root / "a.txt").write_text("a", encoding="utf-8")
        _git(self.root, "add", "a.txt")
        _git(self.root, "commit", "-q", "-m", "feat: claude change\n\nCo-Authored-By: Claude Opus 5.5 <x@y>")
        self.assertNotIn("feat: claude change", self._look("claude"))
        self.assertIn("feat: claude change", self._look("codex"))

    def test_run_events_collapse_so_commits_and_relays_stay_visible(self) -> None:
        # First real run (2026-10-01): 26 of Codex's 27 items were Claude's pilot run events; the cap hid the rest.
        for index in range(20):
            self._letter(f"evt_20261001T0030-claude-{index:04d}", "claude", f"pilot U{index}: APPLIED")
        self._letter("relay_eeee", "antigravity", "antigravity verdict PASS")
        (self.root / "b.txt").write_text("b", encoding="utf-8")
        _git(self.root, "add", "b.txt")
        _git(self.root, "commit", "-q", "-m", "feat: other change")
        text = self._look("codex")
        self.assertIn("antigravity verdict PASS", text)
        self.assertIn("feat: other change", text)
        self.assertIn("20 run event(s) from claude", text)
        self.assertIn("pilot U19: APPLIED", text)
        self.assertLessEqual(len(text.splitlines()), 1 + desk_delta.MAX_LINES + 1)

    def test_cursor_lives_in_the_project_not_in_home(self) -> None:
        self._look("codex", "sess/1")
        cursors = list((self.root / ".coord" / "presence").glob("desk_delta_*.json"))
        self.assertEqual(1, len(cursors))
        self.assertNotIn("/", cursors[0].name.replace("desk_delta_", ""))

    def test_nothing_new_is_empty(self) -> None:
        self.assertEqual("", self._look("claude"))

    def test_header_tells_the_tool_to_audit(self) -> None:
        self._letter("relay_dddd", "codex", "codex verdict")
        text = self._look("antigravity")
        self.assertTrue(text.startswith("DESK DELTA for antigravity"), text[:80])
        self.assertIn("audit", text)


class DeskDeltaHookTests(unittest.TestCase):
    """`coord presence --from-hook --delta` adds the delta to each tool's own hook output format."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        inbox = self.root / ".coord" / "mailbox" / "inbox"
        inbox.mkdir(parents=True)
        (self.root / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        for name, actor in (("relay_c1", "claude"), ("relay_x1", "codex")):
            (inbox / f"{name}.json").write_text(json.dumps({"payload": {"actor": actor, "message": f"{actor} news"}}),
                                                encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _hook(self, tool: str, say: str, payload: dict, delta: bool = True) -> str:
        from v7_harness.cli import main

        argv = ["coord", "presence", "--tool", tool, "--state", "ACTIVE", "--from-hook", "--project", str(self.root),
                "--say", say] + (["--delta"] if delta else [])
        out = io.StringIO()
        # CLAUDE_PROJECT_DIR and UAOS_WORKER are emptied so a run inside a real session never finds the real desk.
        with redirect_stdout(out), mock.patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": "", "UAOS_WORKER": ""}), \
                mock.patch("v7_harness.coord.hook_context.read_stdin", return_value=json.dumps(payload)):
            self.assertEqual(0, main(argv))
        return out.getvalue()

    def test_codex_prompt_hook_prints_the_delta_without_its_own_letter(self) -> None:
        text = self._hook("codex", "none", {"session_id": "x1"})
        self.assertIn("DESK DELTA for codex", text)
        self.assertIn("claude news", text)
        self.assertNotIn("codex news", text)

    def test_without_delta_flag_say_none_stays_silent(self) -> None:
        self.assertEqual("", self._hook("codex", "none", {"session_id": "x1"}, delta=False))

    def test_antigravity_gets_inject_steps_once_per_turn(self) -> None:
        first = json.loads(self._hook("antigravity", "agy", {"conversationId": "g1", "invocationNum": 0}))
        message = first["injectSteps"][0]["ephemeralMessage"]
        self.assertIn("DESK DELTA for antigravity", message)
        self.assertIn("codex news", message)
        later = json.loads(self._hook("antigravity", "agy", {"conversationId": "g1", "invocationNum": 1}))
        self.assertEqual({}, later)

    def test_claude_prompt_hook_hides_its_own_letter(self) -> None:
        text = self._hook("claude", "p1", {"session_id": "c1"})
        self.assertIn("codex news", text)
        self.assertNotIn("claude news", text)


class DeskDeltaInstallTests(unittest.TestCase):
    """The installer wires `--delta` into each tool's per-prompt hook, so any project gets it (temporary HOME)."""

    def test_each_tools_prompt_hook_asks_for_the_delta(self) -> None:
        from tests.test_u37_install_everywhere import _home, _run

        with tempfile.TemporaryDirectory() as temp:
            home = _home(Path(temp))
            self.assertEqual(0, _run(home, "--apply")[0])
            claude = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))["hooks"]
            codex = json.loads((home / ".codex" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
            agy = json.loads((home / ".gemini" / "config" / "hooks.json").read_text(encoding="utf-8"))
            self.assertIn("--delta", claude["UserPromptSubmit"][0]["hooks"][0]["command"])
            self.assertIn("--delta", codex["UserPromptSubmit"][0]["hooks"][0]["command"])
            self.assertIn("--delta", agy["uaos-presence"]["PreInvocation"][0]["command"])
            self.assertNotIn("--delta", claude["SessionEnd"][0]["hooks"][0]["command"])
            self.assertEqual(0, _run(home, "--check")[0])


if __name__ == "__main__":
    unittest.main()
