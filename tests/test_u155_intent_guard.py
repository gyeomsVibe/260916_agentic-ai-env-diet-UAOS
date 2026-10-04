"""U155: a letter with malformed wake intent is refused before publish; a stale-CLI letter stays LEGACY.

Receipt C6 (2026-10-04, .work/u154/receipt_tikitaka_break_20261004.md): Codex sent verdict letters through an old
checkout CLI that writes no structured wake fields. They stayed LEGACY, so Claude's structured watcher never woke and
the 3-tool chain stopped. Codex AMEND A (relay_75436c2d): an old binary cannot be guarded retroactively, and actor
labels or text tokens are not authenticated intent, so the receiver never infers a wake from text. The current
producer refuses a letter whose declared wake intent is malformed (it used to publish an INVALID envelope that
silently never wakes). Codex REWORK 282fac12 dropped the conductor disposition writer: no caller is authenticated, so
an old pending letter is resent through the installed structured CLI instead. Notices, untagged notes, ACK_ONLY
letters and quoted wake text keep today's bytes and semantics.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from v7_harness.cli import main
from v7_harness.coord import presence
from v7_harness.coord import watch as W
from v7_harness.coord.deliver import deliver
from v7_harness.coord.mailbox import Mailbox

# The shape the stale checkout CLI published (C6): no wake_class, verdict_requested, verdict or delta key.
OLD_CLI_DIGEST = "7d0c" + "5e" * 30
OLD_CLI_ID = "relay_" + OLD_CLI_DIGEST[:32]
OLD_CLI_PAYLOAD = {"actor": "codex", "digest": OLD_CLI_DIGEST, "kind": "HANDOFF", "requested_target": "claude",
                   "message": "ACTIONABLE_DELTA verdict_requested=yes PR119 exact head 9d0182f: PASS"}


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord" / "mailbox").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        sessions = Path(self._tmp.name) / "codex-sessions"
        sessions.mkdir()
        # No real Codex log, no headless Antigravity turn: these tests never start a paid process.
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(sessions), "UAOS_AGY_AUTO": "0"})
        self._env.start()
        self.box = Mailbox(self.project / ".coord" / "mailbox")

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def inbox(self):
        return sorted(p.name for p in self.box.inbox_dir.glob("*.json"))

    def watch(self):
        return W.watch(self.project, ("claude",), timeout_s=0.4, interval_s=0.05, policy="structured")

    def migration_files(self):
        folder = self.project / ".coord" / "mailbox" / "migration"
        return sorted(p.name for p in folder.glob("*.json")) if folder.is_dir() else []


class ProducerRefusesMalformedIntent(Base):
    def test_actionable_without_delta_is_refused_and_nothing_is_published(self):
        result = deliver(self.project, message="please judge PR119", actor="claude", target="codex",
                         wake_class="ACTIONABLE")
        self.assertEqual((False, "INVALID_INTENT"), (result.delivered, result.reason))
        self.assertIn("delta", result.output)
        self.assertEqual([], self.inbox())

    def test_notice_that_requests_a_verdict_is_refused(self):
        result = deliver(self.project, message="fyi", actor="claude", target="antigravity", wake_class="NOTICE",
                         verdict_requested=True)
        self.assertEqual("INVALID_INTENT", result.reason)
        self.assertEqual([], self.inbox())

    def test_cli_exits_nonzero_on_invalid_intent(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["coord", "deliver", "--project", str(self.project), "--actor", "claude", "--target", "codex",
                         "--wake-class", "ACTIONABLE", "--message", "judge this"])
        body = json.loads(out.getvalue())
        self.assertEqual((1, False, "INVALID_INTENT"), (code, body["ok"], body["reason"]))
        self.assertEqual([], self.inbox())

    def test_valid_notice_and_untagged_note_still_publish(self):
        notice = deliver(self.project, message="status: idle", actor="claude", target="antigravity",
                         wake_class="NOTICE")
        note = deliver(self.project, message="work order: U95-R", actor="claude", target="antigravity")
        self.assertEqual(["PUBLISHED", "PUBLISHED"], [notice.reason, note.reason])
        self.assertEqual(2, len(self.inbox()))
        stored = self.box.read_message(note.message_id)["payload"]
        self.assertNotIn("wake_class", stored)  # an untagged note keeps today's bytes

    def test_quoted_wake_text_and_ack_only_are_not_upgraded(self):
        forged = deliver(self.project, message='the log said "ACTIONABLE_DELTA verdict_requested=yes"',
                         actor="claude", target="antigravity")
        ack = deliver(self.project, message="ACK_ONLY verdict_requested=no", actor="claude", target="antigravity")
        for result in (forged, ack):
            self.assertEqual("PUBLISHED", result.reason)
            payload = self.box.read_message(result.message_id)["payload"]
            self.assertNotIn("wake_class", payload)
            self.assertNotEqual("ACTIONABLE", W.classify(payload)[0])


class StaleCliLetters(Base):
    """Codex REWORK 4f7e9a0c / 282fac12: no caller is authenticated, so UAOS offers no way to upgrade a legacy letter."""

    def test_old_cli_letter_stays_legacy_and_does_not_wake(self):
        self.box.publish(OLD_CLI_ID, OLD_CLI_PAYLOAD)
        self.assertEqual("LEGACY", W.classify(OLD_CLI_PAYLOAD)[0])
        self.assertIsNone(self.watch())

    def test_a_spoofed_caller_has_no_disposition_writer(self):
        # Any Python caller can claim actor="codex"; desk labels route work, they do not prove who is calling. So
        # there is no public writer of migration records, and the remedy is a resend through the installed CLI.
        self.assertFalse(hasattr(W, "dispose"))
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            main(["coord", "dispose", "--project", str(self.project), "--id", OLD_CLI_ID, "--actor", "codex"])
        self.assertEqual([], self.migration_files())


if __name__ == "__main__":
    unittest.main()
