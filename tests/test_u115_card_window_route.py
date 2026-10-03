"""U115: a letter about a card goes into that card's window.

Receipt (2026-10-01): U114 opened one named window per card in each tool (`.coord/windows/<card>.json`), but
`coord deliver` still dropped every letter into the tool's default thread, so a card's window never heard about its
own card. `coord deliver --card U##` now dispatches into the window recorded for the resolved target tool:
codex -> `codex queue --thread <window>`, claude -> `claude -p ... --resume <window>`, antigravity -> mailbox only with
the window recorded. Without `--card`, or without a window, behaviour is exactly today's. A LIMITED/ABSENT target stays
mailbox-only (U113) even when a window exists. Fixed acceptance written by the judge (claude) first; no test here
starts a paid session (fake runners, fake `shutil.which`, isolated Codex session logs).
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from v7_harness.cli import build_parser
from v7_harness.coord import presence
from v7_harness.coord.deliver import deliver


class _Runner:
    """Records argv; answers like a successful CLI (claude JSON reply, codex queue ok)."""

    def __init__(self):
        self.calls = []

    def __call__(self, command, **_kw):
        self.calls.append(list(command))
        return SimpleNamespace(returncode=0, stdout=json.dumps({"result": "ok"}), stderr="")


class _Isolated(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        self.sessions = Path(self._tmp.name) / "codex-sessions"  # never the PC's real Codex logs
        self.sessions.mkdir()
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(self.sessions)})
        self._env.start()
        self._which = mock.patch("v7_harness.coord.deliver.shutil.which", side_effect=lambda name: name)
        self._which.start()

    def tearDown(self):
        self._which.stop()
        self._env.stop()
        self._tmp.cleanup()

    def _window(self, card, **ids):
        path = self.project / ".coord" / "windows" / f"{card}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        tools = {tool: {"id": window_id, "opened_at": 0} for tool, window_id in ids.items()}
        path.write_text(json.dumps({"card": card, "title": f"[{card}] t", "tools": tools}), encoding="utf-8")

    def _payload(self, result):
        letter = self.project / ".coord" / "mailbox" / "inbox" / f"{result.message_id}.json"
        return json.loads(letter.read_text(encoding="utf-8"))["payload"]

    @staticmethod
    def _after(argv, flag):
        return argv[argv.index(flag) + 1]


class CodexWindow(_Isolated):
    def test_card_with_a_codex_window_queues_into_that_thread(self):
        presence.mark(self.project, "codex", "ACTIVE")
        win_thread = "0199aaaa-0000-7000-8000-000000000001"
        def_thread = "0199bbbb-0000-7000-8000-000000000002"
        day = self.sessions / "2026" / "10" / "03"
        day.mkdir(parents=True, exist_ok=True)
        for tid in (win_thread, def_thread):
            (day / f"rollout-2026-10-03T06-00-00-{tid}.jsonl").write_text(
                json.dumps({"type": "session_meta", "payload": {"id": tid, "session_id": tid, "cwd": str(self.project)}}) + "\n",
                encoding="utf-8",
            )
        self._window("U115", codex=win_thread)
        runner = _Runner()
        result = deliver(self.project, message="U115 codex window", actor="claude", target="codex",
                         thread=def_thread, runner=runner, card="U115")
        self.assertEqual(1, len(runner.calls))
        self.assertIn("queue", runner.calls[0])
        self.assertEqual(win_thread, self._after(runner.calls[0], "--thread"))
        payload = self._payload(result)
        self.assertEqual(("U115", win_thread), (payload["card"], payload["window"]))

    def test_without_card_or_without_a_window_the_default_thread_is_used(self):
        presence.mark(self.project, "codex", "ACTIVE")
        win_thread = "0199aaaa-0000-7000-8000-000000000001"
        def_thread = "0199bbbb-0000-7000-8000-000000000002"
        day = self.sessions / "2026" / "10" / "03"
        day.mkdir(parents=True, exist_ok=True)
        for tid in (win_thread, def_thread):
            (day / f"rollout-2026-10-03T06-00-00-{tid}.jsonl").write_text(
                json.dumps({"type": "session_meta", "payload": {"id": tid, "session_id": tid, "cwd": str(self.project)}}) + "\n",
                encoding="utf-8",
            )
        self._window("U115", codex=win_thread)
        for n, card in enumerate(("", "U999")):
            runner = _Runner()
            result = deliver(self.project, message=f"U115 default {n}", actor="claude", target="codex",
                             thread=def_thread, runner=runner, card=card)
            self.assertEqual(def_thread, self._after(runner.calls[0], "--thread"), card)
            payload = self._payload(result)
            if card:
                self.assertEqual(("U999", None), (payload["card"], payload.get("window")))
            else:  # no --card: today's payload bytes, unchanged
                self.assertNotIn("card", payload)
                self.assertNotIn("window", payload)


class ClaudeWindow(_Isolated):
    def test_card_with_a_claude_window_resumes_that_session(self):
        presence.mark(self.project, "claude", "ACTIVE")
        self._window("U115", claude="abc12345def")
        runner = _Runner()
        result = deliver(self.project, message="U115 claude window ACTIONABLE_DELTA", actor="codex",
                         target="claude", runner=runner, card="U115")
        self.assertEqual(1, len(runner.calls))
        argv = runner.calls[0]
        self.assertEqual("abc12345def", self._after(argv, "--resume"))
        self.assertNotIn("--session-id", argv)
        # The default delivery session is not touched by a window letter.
        self.assertFalse((self.project / ".coord" / "mailbox" / "delivery" / "claude-session.json").exists())
        self.assertEqual("abc12345def", self._payload(result)["window"])

    def test_without_card_claude_keeps_the_default_delivery_session(self):
        presence.mark(self.project, "claude", "ACTIVE")
        self._window("U115", claude="abc12345def")
        runner = _Runner()
        deliver(self.project, message="U115 claude default ACTIONABLE_DELTA", actor="codex", target="claude",
                runner=runner)
        argv = runner.calls[0]
        self.assertIn("--session-id", argv)
        self.assertNotIn("abc12345def", argv)


class AntigravityWindow(_Isolated):
    def test_antigravity_stays_mailbox_only_and_records_the_window(self):
        presence.mark(self.project, "antigravity", "ACTIVE")
        self._window("U115", antigravity="conv-1")
        runner = _Runner()
        result = deliver(self.project, message="U115 agy window", actor="claude", target="antigravity",
                         runner=runner, card="U115")
        self.assertEqual(("antigravity", "PUBLISHED"), (result.target, result.reason))
        self.assertEqual([], runner.calls)
        payload = self._payload(result)
        self.assertEqual(("U115", "conv-1"), (payload["card"], payload["window"]))


class LimitedTargetIgnoresTheWindow(_Isolated):
    def test_limited_or_absent_target_with_a_window_gets_the_mailbox_only(self):
        self._window("U115", codex="thr-window", claude="abc12345def")
        for tool in ("codex", "claude"):
            for state in ("LIMITED", "ABSENT"):
                presence.mark(self.project, tool, state)
                runner = _Runner()
                result = deliver(self.project, message=f"U115 {tool} {state} ACTIONABLE_DELTA", actor="claude",
                                 target=tool, runner=runner, card="U115")
                # U134-C: queued for the tool's next ACTIVE turn instead of a bare mailbox_only; still no dispatch.
                self.assertEqual((tool, "QUEUED_UNTIL_ACTIVE"), (result.target, result.reason), (tool, state))
                self.assertEqual([], runner.calls, (tool, state))
                payload = self._payload(result)
                self.assertEqual("U115", payload["card"])
                self.assertIsNone(payload.get("window"), (tool, state))


class CardIdAndCli(_Isolated):
    def test_bad_card_id_is_refused_before_anything_is_published(self):
        presence.mark(self.project, "codex", "ACTIVE")
        runner = _Runner()
        with self.assertRaises(ValueError):
            deliver(self.project, message="U115 bad card", actor="claude", target="codex", thread="t",
                    runner=runner, card="../x")
        self.assertEqual([], runner.calls)
        inbox = self.project / ".coord" / "mailbox" / "inbox"
        self.assertEqual([], list(inbox.glob("*.json")) if inbox.is_dir() else [])

    def test_cli_deliver_accepts_card_and_passes_it(self):
        args = build_parser().parse_args(["coord", "deliver", "--project", str(self.project), "--actor", "claude",
                                          "--target", "codex", "--message", "hi", "--card", "U115"])
        self.assertEqual("U115", args.card)
        seen = {}

        def fake(project, **kw):
            seen.update(kw)
            return SimpleNamespace(target="codex", reason="DISPATCHED", message_id="m", digest="d", receipt="",
                                   output="")

        with mock.patch("v7_harness.coord.deliver.deliver", side_effect=fake), \
                mock.patch("builtins.print"):
            self.assertEqual(0, args.func(args))
        self.assertEqual("U115", seen["card"])
        no_card = build_parser().parse_args(["coord", "deliver", "--actor", "claude", "--message", "hi"])
        self.assertEqual("", no_card.card)


if __name__ == "__main__":
    unittest.main()
