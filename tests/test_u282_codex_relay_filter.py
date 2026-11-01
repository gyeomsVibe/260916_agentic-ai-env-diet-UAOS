"""U282: a letter that asks Codex for nothing never becomes a paid Codex turn.

Receipt (2026-10-28 22:5x KST, user screenshot of the Codex app): 8 UAOS relays sat in Codex's queue while Codex
worked a 30-minute turn; each one becomes its own Codex turn (~140k context). Two of them were Codex's own letters
(actor=codex, no target): the auto route picked the ACTIVE tool, which was the sender itself (relay_6a3014c5,
relay_f0722b8d). relay_f0722b8d was also wake_class=NOTICE with an ACK_ONLY marker, yet `codex queue` ran because
the codex branch, unlike the claude branch (U64, U74-D), never asked whether the letter wants a turn.

Rules (fixed acceptance, written before the code):
- R1 SELF_ADDRESSED: auto routing never resolves to the sender; a Codex letter goes to Claude or the mailbox.
- R2 NO_WAKE: a letter to Codex with wake_class NOTICE, verdict_requested=False or an ACK_ONLY text marker (with no wake token beside it) is
  published to the inbox (Codex reads it through its hooks' desk delta, U103) and never runs `codex queue`.
- Untagged letters and real deltas keep today's dispatch (U113 test_active_codex_is_still_dispatched).
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import presence
from v7_harness.coord.deliver import deliver

THREAD = "0199cccc-0000-7000-8000-000000000282"


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, command, **_kw):
        self.calls.append(command)
        raise OSError("codex not installed here")


class _Isolated(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        self.sessions = Path(self._tmp.name) / "codex-sessions"  # never the PC's real Codex logs
        day = self.sessions / "2026" / "10" / "28"
        day.mkdir(parents=True)
        (day / f"rollout-2026-10-28T13-00-00-{THREAD}.jsonl").write_text(json.dumps(
            {"type": "session_meta", "payload": {"id": THREAD, "session_id": THREAD, "cwd": str(self.project)}})
            + "\n", encoding="utf-8")
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(self.sessions)})
        self._env.start()
        presence.mark(self.project, "codex", "ACTIVE")
        self.runner = _Recorder()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def _send(self, message, **kw):
        kw.setdefault("actor", "claude")
        kw.setdefault("target", "codex")
        with mock.patch("v7_harness.coord.deliver.shutil.which", return_value="codex"):
            return deliver(self.project, message=message, runner=self.runner, thread=THREAD, **kw)

    def _inbox(self, result):
        return (self.project / ".coord" / "mailbox" / "inbox" / f"{result.message_id}.json").is_file()


class NoWakeLetterNeverQueuesCodex(_Isolated):
    def test_notice_is_published_not_queued(self):
        result = self._send("U282 status: handoff file written", wake_class="NOTICE")
        self.assertEqual(("codex", "QUEUED_NOTICE", []), (result.target, result.reason, self.runner.calls))
        self.assertTrue(self._inbox(result))

    def test_ack_only_marker_is_published_not_queued(self):
        result = self._send("ACK_ONLY requested handoff complete")
        self.assertEqual(("QUEUED_NOTICE", []), (result.reason, self.runner.calls))
        self.assertTrue(self._inbox(result))

    def test_verdict_not_requested_is_published_not_queued(self):
        result = self._send("U282 relay summary for the record", verdict_requested=False)
        self.assertEqual(("QUEUED_NOTICE", []), (result.reason, self.runner.calls))

    def test_quoted_ack_only_does_not_hide_a_real_request(self):
        result = self._send('ACTIONABLE_DELTA verdict_requested=yes: judge U282; the old letter said "ACK_ONLY"')
        self.assertEqual(1, len(self.runner.calls))
        self.assertIn("queue", self.runner.calls[0])

    def test_unquoted_ack_only_beside_a_real_request_still_queues(self):
        # Codex judge REVISE (U282 r1): a marker must not silence a request that names its own wake token.
        self._send("ACTIONABLE_DELTA verdict_requested=yes: judge U282; previous status ACK_ONLY")
        self.assertEqual(1, len(self.runner.calls))

    def test_verdict_request_is_still_queued(self):
        result = self._send("U282 verdict requested on bundle abc", wake_class="ACTIONABLE",
                            verdict_requested=True, delta="judge U282")
        self.assertNotEqual("QUEUED_NOTICE", result.reason)
        self.assertEqual(1, len(self.runner.calls))

    def test_notice_to_limited_codex_is_not_queued_for_its_return(self):
        presence.mark(self.project, "codex", "LIMITED")
        result = self._send("U282 notice while limited", wake_class="NOTICE")
        self.assertEqual(("QUEUED_NOTICE", []), (result.reason, self.runner.calls))
        queued = self.project / ".coord" / "mailbox" / "delivery" / "queued" / "codex"
        self.assertEqual([], list(queued.glob("*.json")) if queued.is_dir() else [])

    def test_untagged_letter_keeps_todays_dispatch(self):
        self._send("U282 untagged plain letter")
        self.assertEqual(1, len(self.runner.calls))


class AutoRouteNeverAddressesTheSender(_Isolated):
    def test_codex_letter_with_no_target_does_not_queue_into_codex(self):
        result = self._send("Current PRIMARY generation29 verified", actor="codex", target=None,
                            wake_class="ACTIONABLE", delta="primary verified")
        self.assertEqual([], [c for c in self.runner.calls if "queue" in c])
        self.assertNotEqual("codex", result.target)

    def test_claude_letter_with_no_target_still_reaches_active_codex(self):
        self._send("ACTIONABLE_DELTA U282 auto", actor="claude", target=None)
        self.assertEqual(1, len(self.runner.calls))


if __name__ == "__main__":
    unittest.main()
