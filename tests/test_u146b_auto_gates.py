"""U146-B: the nonstop-chain Stop gate reaches Codex and Antigravity (docs/75 §5), a LIMITED tool is not pushed into a
new card (R7 budget), and the push grant can expire.

Hook formats (Stage 0): Codex Stop reads `session_id` and answers {"decision": "block", "reason"}
(https://learn.chatgpt.com/docs/hooks); Antigravity Stop reads `conversationId`, `fullyIdle` and answers
{"decision": "continue", "reason"} (https://antigravity.google/docs/hooks).
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests.test_u146a_next_card import Base, phase
from v7_harness.coord import presence
from v7_harness.coord import stop_gate as G

REPO = Path(__file__).resolve().parents[1]


def _plan(root: Path) -> None:
    (root / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")


class ToolFormats(Base):
    def test_codex_blocks_with_its_session_id(self):
        self.schedule(phase("A", "READY", owner="codex"))
        out = G.gate(self.root, "codex", session="c1")
        self.assertEqual({"decision": "block"}, {"decision": out["decision"]})
        self.assertIn("A", out["reason"])

    def test_antigravity_answers_continue(self):
        self.schedule(phase("A", "READY", owner="antigravity"))
        out = G.gate(self.root, "antigravity", session="g1")
        self.assertEqual("continue", out["decision"])
        self.assertIn("A", out["reason"])

    def test_session_comes_from_session_id_or_conversation_id(self):
        self.assertEqual("s1", G.hook_session({"session_id": "s1"}))
        self.assertEqual("g1", G.hook_session({"conversationId": "g1"}))
        self.assertIsNone(G.hook_session({}))
        self.assertIsNone(G.hook_session({"session_id": 7}))

    def test_antigravity_that_is_not_fully_idle_is_not_held(self):
        self.assertFalse(G.should_gate({"conversationId": "g1", "fullyIdle": False}))
        self.assertTrue(G.should_gate({"conversationId": "g1", "fullyIdle": True}))
        self.assertTrue(G.should_gate({"session_id": "c1", "stop_hook_active": False}))


class BudgetR7(Base):
    def test_a_limited_tool_is_not_pushed_into_a_new_card(self):
        # R7: each block is a paid turn; a tool whose desk says LIMITED has no budget for a new card.
        self.schedule(phase("A", "READY", owner="codex"))
        presence.mark(self.root, "codex", "LIMITED", ttl_s=3600, lease=True)
        self.assertIsNone(G.gate(self.root, "codex", session="c1"))
        self.assertFalse((self.root / ".coord" / "presence" / "stop_gate_codex.json").exists())

    def test_an_active_tool_is_still_held(self):
        self.schedule(phase("A", "READY", owner="codex"))
        presence.mark(self.root, "codex", "ACTIVE", ttl_s=3600)
        self.assertEqual("block", G.gate(self.root, "codex", session="c1")["decision"])


class GrantExpiry(Base):
    def grant(self, **over):
        data = {"enabled": True, "branches": ["claude/*"], "never": ["main"], "force": False}
        data.update(over)
        path = self.root / ".coord" / "grants"
        path.mkdir(parents=True, exist_ok=True)
        (path / "push.json").write_text(json.dumps(data), encoding="utf-8")
        git = lambda *a: subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a], cwd=self.root,
                                        check=True, capture_output=True)
        if not (self.root / ".git").exists():
            git("init", "-q")
        git("add", ".coord/grants/push.json")
        git("commit", "-q", "--allow-empty", "-m", "grant")
        git("update-ref", "refs/remotes/origin/main", "HEAD")

    def test_an_expired_grant_denies(self):
        self.grant(expires_at="2020-01-01T00:00:00+00:00")
        out = G.push_check(self.root, "claude/x")
        self.assertEqual("DENY", out["decision"])
        self.assertIn("expired", out["reason"])

    def test_a_future_grant_allows_in_iso_or_epoch(self):
        for value in ("2999-01-01T00:00:00+00:00", time.time() + 3600):
            self.grant(expires_at=value)
            self.assertEqual("ALLOW", G.push_check(self.root, "claude/x")["decision"], value)

    def test_an_unreadable_or_naive_expiry_denies(self):
        for value in ("soon", "2999-01-01T00:00:00", True, [1]):
            self.grant(expires_at=value)
            self.assertEqual("DENY", G.push_check(self.root, "claude/x")["decision"], value)

    def test_a_grant_without_expiry_keeps_its_meaning(self):
        self.grant()
        self.assertEqual("ALLOW", G.push_check(self.root, "claude/x")["decision"])


class FromHookCli(Base):
    def run_cli(self, *args, stdin="", env_extra=None):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        env.pop("UAOS_WORKER", None)
        env.pop("CLAUDE_PROJECT_DIR", None)
        env.update(env_extra or {})
        return subprocess.run([sys.executable, "-m", "v7_harness.cli", *args], input=stdin, capture_output=True,
                              text=True, encoding="utf-8", env=env, cwd=REPO, timeout=120)

    def test_codex_hook_finds_the_project_from_cwd(self):
        _plan(self.root)
        self.schedule(phase("A", "READY", owner="codex"))
        hook = json.dumps({"session_id": "c1", "cwd": str(self.root), "stop_hook_active": False})
        res = self.run_cli("coord", "stop-gate", "--tool", "codex", "--from-hook", stdin=hook)
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertEqual("block", json.loads(res.stdout)["decision"])

    def test_antigravity_hook_finds_the_project_from_workspace_paths(self):
        _plan(self.root)
        self.schedule(phase("A", "READY", owner="antigravity"))
        hook = json.dumps({"conversationId": "g1", "workspacePaths": [str(self.root)], "fullyIdle": True})
        res = self.run_cli("coord", "stop-gate", "--tool", "antigravity", "--from-hook", stdin=hook)
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertEqual("continue", json.loads(res.stdout)["decision"])

    def test_outside_a_project_or_in_a_worker_nothing_is_printed(self):
        self.schedule(phase("A", "READY", owner="codex"))  # no PLAN.md: not a UAOS project
        hook = json.dumps({"session_id": "c1", "cwd": str(self.root)})
        res = self.run_cli("coord", "stop-gate", "--tool", "codex", "--from-hook", stdin=hook)
        self.assertEqual(("", 0), (res.stdout.strip(), res.returncode))
        _plan(self.root)
        res = self.run_cli("coord", "stop-gate", "--tool", "codex", "--from-hook", stdin=hook,
                           env_extra={"UAOS_WORKER": "1"})
        self.assertEqual(("", 0), (res.stdout.strip(), res.returncode))

    def test_claude_global_hook_steps_aside_for_a_project_stop_hook(self):
        # agy audit relay_45d07985: Claude needs the gate in every UAOS project, but a stop is gated once.
        _plan(self.root)
        self.schedule(phase("A", "READY", owner="claude"))
        hook = json.dumps({"session_id": "k1", "cwd": str(self.root), "stop_hook_active": False})
        res = self.run_cli("coord", "stop-gate", "--tool", "claude", "--from-hook", stdin=hook)
        self.assertEqual("block", json.loads(res.stdout)["decision"])
        (self.root / ".claude").mkdir(exist_ok=True)
        (self.root / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": "python -m v7_harness.cli coord stop-gate --project . --tool claude"}]}]}}),
            encoding="utf-8")
        res = self.run_cli("coord", "stop-gate", "--tool", "claude", "--from-hook", stdin=hook)
        self.assertEqual(("", 0), (res.stdout.strip(), res.returncode))

    def test_bad_input_never_fails_the_session(self):
        res = self.run_cli("coord", "stop-gate", "--tool", "antigravity", "--from-hook", stdin="not json")
        self.assertEqual(0, res.returncode, res.stderr)


class HeadlessWorkerIsNotASession(unittest.TestCase):
    def test_the_agy_pilot_launcher_marks_its_worker(self):
        # agy audit relay_3e404354: a headless pilot agy run must never be held on a new card by the Stop gate.
        from unittest import mock

        from v7_harness.adapters.agy import AgyRequest
        from v7_harness.execution import agy_launcher

        seen = {}

        def fake_popen(argv, **kwargs):
            seen.update(kwargs)
            raise RuntimeError("stop before a real process")

        with tempfile.TemporaryDirectory() as temp:
            request = AgyRequest(task_id="t", title="t", prompt="p", workspace=Path(temp), isolation_mode="staging",
                                 print_timeout_s=5)
            launcher = agy_launcher.AgyProcessLauncher(agy_command=["agy"], request=request, runs_dir=Path(temp) / "r")
            with mock.patch.object(agy_launcher.subprocess, "Popen", fake_popen), \
                    mock.patch.object(agy_launcher, "_create_win_job", lambda: None):
                with self.assertRaises(RuntimeError):
                    launcher.launch(attempt_id="a1", acceptance_hash="h")
        self.assertEqual("1", seen["env"]["UAOS_WORKER"])


class Install(unittest.TestCase):
    def test_all_three_tools_get_a_global_stop_hook(self):
        from tests.test_u37_install_everywhere import _home, _run

        with tempfile.TemporaryDirectory() as temp:
            home = _home(Path(temp))
            self.assertEqual(0, _run(home, "--apply")[0])
            codex = json.loads((home / ".codex" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
            agy = json.loads((home / ".gemini" / "config" / "hooks.json").read_text(encoding="utf-8"))
            claude = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))["hooks"]
            self.assertEqual(0, _run(home, "--check")[0])
        for hooks, tool in ((codex, "codex"), (claude, "claude")):
            command = hooks["Stop"][-1]["hooks"][0]["command"]
            for part in ("coord stop-gate", f"--tool {tool}", "--from-hook"):
                self.assertIn(part, command)
        agy_cmds = [h["command"] for group in agy.values() if isinstance(group, dict) for h in group.get("Stop", [])]
        self.assertTrue(any("coord stop-gate" in c and "--tool antigravity" in c and "--from-hook" in c
                            for c in agy_cmds), agy_cmds)

    def test_rules_name_the_gate_for_all_three_tools(self):
        for tool in ("codex", "antigravity"):
            text = (REPO / "uaos_everywhere" / "adapters" / f"{tool}.md").read_text(encoding="utf-8")
            self.assertIn("coord stop-gate", text, tool)
        block = (REPO / "uaos_everywhere" / "uaos_global_rule_block.md").read_text(encoding="utf-8")
        self.assertIn("expires_at", block)


if __name__ == "__main__":
    unittest.main()
