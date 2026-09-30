"""U103-O: Claude Code and Codex use the local model the way Antigravity already does.

Receipt (윤겸스, 2026-10-01, screenshot of Antigravity calling olla local_draft): "Antigravity seems to use the Ollama MCP;
I have not seen Claude Code or Codex use it." `olla stats`: antigravity digest 20 after deny_whole_read 17, codex digest 0.
Antigravity's olla-guard refuses a whole-file read of >= 8,000 tokens and points to the 0-token digest; Claude and Codex
had no such gate (the installer never wired one). This adds the same gate for both, only where `olla` is installed,
and leaves Antigravity's olla-guard group untouched. Fixed acceptance written by the judge (claude) first.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from v7_harness import olla

AGY_OLLA_GUARD = {"enabled": True, "PreInvocation": [{"type": "command", "command": "olla hook-agy PreInvocation"}]}


class CodexShellDenyTests(unittest.TestCase):
    """`olla hook-shell` on Codex PreToolUse refuses a whole-file print of a big file before it spends tokens."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        # 8,000 tokens x 3 bytes per token = 24,000 bytes is the limit; 30,000 bytes is over it.
        (self.root / "big.py").write_text("x = 1\n" * 5000, encoding="utf-8")
        (self.root / "small.py").write_text("x = 1\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _hook(self, event: dict) -> str:
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.object(olla, "_stdin_text", return_value=json.dumps(event)), \
                mock.patch.object(olla, "log_usage"), mock.patch.object(olla, "read_hint", return_value=None):
            self.assertEqual(0, olla.cmd_hook_shell(mock.Mock()))
        return out.getvalue()

    def _pre(self, command) -> dict:
        return {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(self.root),
                "tool_input": {"command": command}}

    def test_big_whole_read_is_denied_with_the_local_route(self) -> None:
        output = json.loads(self._hook(self._pre("cat big.py")))["hookSpecificOutput"]
        self.assertEqual("PreToolUse", output["hookEventName"])
        self.assertEqual("deny", output["permissionDecision"])
        self.assertIn("olla digest", output["permissionDecisionReason"])

    def test_wrapped_powershell_read_is_denied_too(self) -> None:
        output = json.loads(self._hook(self._pre(["powershell", "-Command", "Get-Content big.py"])))
        self.assertEqual("deny", output["hookSpecificOutput"]["permissionDecision"])

    def test_small_or_ranged_reads_pass_silently(self) -> None:
        self.assertEqual("", self._hook(self._pre("cat small.py")))
        self.assertEqual("", self._hook(self._pre("cat big.py | head -40")))
        self.assertEqual("", self._hook(self._pre("sed -n '1,40p' big.py")))


class InstallerOllaHookTests(unittest.TestCase):
    """The installer wires the gates only when `olla` is on PATH, and keeps Antigravity's olla-guard as it was."""

    def _install(self, olla_path: str | None) -> tuple[dict, dict, dict]:
        from tests.test_u37_install_everywhere import _home, _run

        with tempfile.TemporaryDirectory() as temp:
            home = _home(Path(temp))
            agy_file = home / ".gemini" / "config" / "hooks.json"
            agy_file.write_text(json.dumps({"olla-guard": AGY_OLLA_GUARD}), encoding="utf-8")
            with mock.patch("v7_harness.global_install.shutil.which",
                            side_effect=lambda name, *a, **k: olla_path if name == "olla" else None):
                self.assertEqual(0, _run(home, "--apply")[0])
                self.assertEqual(0, _run(home, "--check")[0])
            claude = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))["hooks"]
            codex = json.loads((home / ".codex" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
            agy = json.loads(agy_file.read_text(encoding="utf-8"))
        return claude, codex, agy

    def test_gates_are_wired_when_olla_is_installed(self) -> None:
        claude, codex, agy = self._install("D:/AI-Models/bin/olla")
        read = claude["PreToolUse"][-1]
        self.assertEqual("Read", read["matcher"])
        self.assertEqual("olla hook-read", read["hooks"][0]["command"])
        self.assertEqual("olla hook-shell", codex["PreToolUse"][-1]["hooks"][0]["command"])
        self.assertEqual(AGY_OLLA_GUARD, agy["olla-guard"])

    def test_nothing_is_wired_without_olla(self) -> None:
        claude, codex, agy = self._install(None)
        self.assertNotIn("PreToolUse", claude)
        self.assertNotIn("PreToolUse", codex)
        self.assertEqual(AGY_OLLA_GUARD, agy["olla-guard"])


if __name__ == "__main__":
    unittest.main()
