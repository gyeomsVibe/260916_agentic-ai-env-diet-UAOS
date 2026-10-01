"""U120: a real delta from Claude or Codex to Antigravity gets a headless one-turn answer, mailed back to the sender.

Receipt (2026-10-01, user report): letters to Antigravity stayed unread until the user pasted them by hand (U103,
U118), and the user asked that the three tools link both ways without any prompt. No CLI wakes the interactive
Antigravity, but U119 proved a headless one-turn answer inside its cap (27,989 tokens, 14 s). So `deliver` hands such a
letter to `agy_dispatch.dispatch`: inline letter, empty box folder, no tools; the answer goes back to the sender as a
letter from antigravity tagged `[agy-auto]`, and the original letter is acked so the interactive session does not redo
it. Guards: a tagged letter never dispatches again (no ping-pong), a daily cap, `UAOS_AGY_AUTO=0` opts out, only
claude/codex senders, and a failed run leaves the letter unread (U118 route).
Fixed acceptance written by the judge (claude) first; no paid call.
"""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from v7_harness.coord import agy_dispatch, presence
from v7_harness.coord.deliver import deliver
from v7_harness.coord.mailbox import Mailbox
from v7_harness.coord.watch import watch_file


class AgyAutoReply(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        sessions = Path(self._tmp.name) / "codex-sessions"
        sessions.mkdir()
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(sessions)})
        self._env.start()
        os.environ.pop("UAOS_AGY_AUTO", None)
        self._which = mock.patch("v7_harness.coord.deliver.shutil.which", side_effect=lambda name: name)
        self._which.start()
        presence.mark(self.project, "claude", "ACTIVE")
        beat = watch_file(self.project, "claude")  # a session-waking Claude watcher takes the reply (U117)
        beat.parent.mkdir(parents=True, exist_ok=True)
        beat.write_text(json.dumps({"tool": "claude", "token": "t", "pid": 1, "expires_at": time.time() + 300,
                                    "wakes_session": True}), encoding="utf-8")
        self.calls = []
        self.status = "SUCCESS"

    def tearDown(self):
        self._which.stop()
        self._env.stop()
        self._tmp.cleanup()

    def runner(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        if Path(argv[0]).stem != "agy":
            raise AssertionError(f"only agy may run here: {argv[0]}")
        envelope = {"status": self.status, "conversation_id": "conv-auto",
                    "usage": {"input_tokens": 25_000, "output_tokens": 900},
                    "response": "PASS: the change matches the contract."}
        return SimpleNamespace(returncode=0 if self.status == "SUCCESS" else 1,
                               stdout=json.dumps(envelope).encode("utf-8"), stderr=b"")

    def box(self):
        return Mailbox(self.project / ".coord" / "mailbox")

    def letters(self):
        box = self.box()
        return {mid: box.read_message(mid) for mid in box.list_inbox()}

    def send(self, message, actor="claude"):
        return deliver(self.project, message=message, actor=actor, target="antigravity", runner=self.runner)

    def test_a_real_delta_gets_a_headless_reply_back_to_the_sender(self):
        result = self.send("[review] verdict_requested=yes ACTIONABLE_DELTA: check diff X")
        self.assertEqual(1, len(self.calls))
        argv, kwargs = self.calls[0]
        prompt = argv[argv.index("-p") + 1]
        self.assertIn("check diff X", prompt)
        self.assertIn("Do not call any tool", prompt)
        self.assertNotIn("--dangerously-skip-permissions", argv)
        box_dir = self.project / ".coord" / "mailbox" / "delivery" / "agy_box"
        # U120-A: Windows temp may give an 8.3 short name (KIMYOO~1) while deliver resolves it; same folder either way.
        self.assertEqual(box_dir.resolve(), Path(kwargs["cwd"]).resolve())
        self.assertEqual([], list(box_dir.iterdir()))
        self.assertTrue(result.output.startswith("AGY_ANSWERED"), result.output)
        self.assertFalse(self.box().has_message(result.message_id) and result.message_id in self.box().list_inbox())
        replies = [m for m in self.letters().values() if m and m["payload"].get("actor") == "antigravity"]
        self.assertEqual(1, len(replies))
        text = replies[0]["payload"]["message"]
        self.assertIn(agy_dispatch.AUTO_TAG, text)
        self.assertIn("PASS: the change matches the contract.", text)
        self.assertIn(result.message_id, text)
        self.assertEqual("claude", replies[0]["payload"].get("requested_target"))

    def test_a_tagged_letter_never_dispatches_again(self):
        result = self.send(f"{agy_dispatch.AUTO_TAG} re relay_x: ACTIONABLE_DELTA verdict_requested=yes")
        self.assertEqual([], self.calls)
        self.assertIn("SKIPPED_LOOP", result.output)

    def test_the_daily_cap_stops_dispatch(self):
        ledger = self.project / ".coord" / "mailbox" / "delivery" / "agy_auto.jsonl"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text("".join(json.dumps({"ts": time.time(), "state": "ANSWERED"}) + "\n"
                                  for _ in range(agy_dispatch.DAILY_CAP)), encoding="utf-8")
        result = self.send("ACTIONABLE_DELTA verdict_requested=yes")
        self.assertEqual([], self.calls)
        self.assertIn("CAP_REACHED", result.output)

    def test_opt_out_keeps_the_u118_unread_route(self):
        with mock.patch.dict(os.environ, {"UAOS_AGY_AUTO": "0"}):
            result = self.send("ACTIONABLE_DELTA verdict_requested=yes")
        self.assertEqual([], self.calls)
        self.assertIn("UNREAD", result.output)

    def test_only_claude_and_codex_senders_dispatch(self):
        result = self.send("ACTIONABLE_DELTA verdict_requested=yes", actor="user")
        self.assertEqual([], self.calls)
        self.assertIn("UNREAD", result.output)

    def test_a_failed_run_leaves_the_letter_unread(self):
        self.status = "ERROR"
        result = self.send("ACTIONABLE_DELTA verdict_requested=yes")
        self.assertEqual(1, len(self.calls))
        self.assertIn("AGY_FAILED", result.output)
        self.assertIn(result.message_id, self.box().list_inbox())
        self.assertFalse(any(m and m["payload"].get("actor") == "antigravity" for m in self.letters().values()))


if __name__ == "__main__":
    unittest.main()
