"""U194: a verdict request to Antigravity wakes the U120 headless auto-answer.

Receipt relay_19f9c6aa (2026-10-15): `coord deliver --target antigravity --verdict-requested` published a letter but no
auto-answer ran, because the U169 wake rule read only wake_class and the text; U193's audit request needed a hand-added
`--wake-class ACTIONABLE --delta`. Design APPROVED narrowed to target antigravity (Codex relay_5be83219): the sound for
codex/claude, NOTICE/ACK_ONLY refusal, loop protection and the cost controls stay as they are.
Fixed acceptance written by the implementer first (judge: Codex); no paid call.
"""
from __future__ import annotations

import json
import time
import unittest
from unittest import mock

from tests import test_u120_agy_auto_reply as u120  # module import: pytest must not collect U120's class twice
from v7_harness.coord import agy_dispatch
from v7_harness.coord.deliver import deliver

PLAIN = "please audit bundle B"  # no wake word: only the structured flag may ask for a turn


class VerdictWakesAgy(unittest.TestCase):
    setUp = u120.AgyAutoReply.setUp
    tearDown = u120.AgyAutoReply.tearDown
    runner = u120.AgyAutoReply.runner
    box = u120.AgyAutoReply.box
    letters = u120.AgyAutoReply.letters

    def send(self, message=PLAIN, **fields):
        return deliver(self.project, message=message, actor="claude", target="antigravity", runner=self.runner,
                       **fields)

    def test_plain_letter_without_the_flag_stays_unread(self):
        result = self.send()
        self.assertEqual([], self.calls)
        self.assertNotIn("AGY_", result.output)

    def test_verdict_request_dispatches_one_headless_answer(self):
        result = self.send(verdict_requested=True)
        self.assertEqual(1, len(self.calls), result)
        self.assertTrue(result.output.startswith("AGY_ANSWERED"), result.output)

    def test_verdict_requested_false_does_not_dispatch(self):
        self.send(verdict_requested=False)
        self.assertEqual([], self.calls)

    def test_non_boolean_verdict_request_never_dispatches(self):
        for value in ("yes", 1, "true"):
            with self.subTest(value=value):
                try:
                    self.send(message=f"{PLAIN} {value!r}", verdict_requested=value)
                except (TypeError, ValueError):
                    pass
                self.assertEqual([], self.calls)

    def test_notice_or_ack_only_with_a_verdict_request_never_dispatches(self):
        for wake_class in ("NOTICE", "ACK_ONLY"):
            with self.subTest(wake_class=wake_class):
                self.send(message=f"{PLAIN} {wake_class}", verdict_requested=True, wake_class=wake_class)
                self.assertEqual([], self.calls)

    def test_the_daily_cap_still_stops_a_verdict_request(self):
        ledger = self.project / ".coord" / "mailbox" / "delivery" / "agy_auto.jsonl"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text("".join(json.dumps({"ts": time.time(), "state": "ANSWERED"}) + "\n"
                                  for _ in range(agy_dispatch.DAILY_CAP)), encoding="utf-8")
        result = self.send(verdict_requested=True)
        self.assertEqual([], self.calls)
        self.assertIn("CAP_REACHED", result.output)

    def test_a_duplicate_verdict_request_is_answered_once(self):
        first = self.send(verdict_requested=True)
        second = self.send(verdict_requested=True)
        self.assertEqual(first.message_id, second.message_id)
        self.assertEqual(1, len(self.calls), second.output)

    def test_a_tagged_verdict_request_never_dispatches_again(self):
        result = self.send(message=f"{agy_dispatch.AUTO_TAG} re relay_x: {PLAIN}", verdict_requested=True)
        self.assertEqual([], self.calls)
        self.assertIn("SKIPPED_LOOP", result.output)

    def test_the_sound_rule_for_other_targets_is_unchanged(self):
        with mock.patch("v7_harness.coord.ring.ring") as ring:
            deliver(self.project, message=PLAIN, actor="claude", target=None, verdict_requested=True)
        self.assertEqual([], ring.call_args_list, "U194 is narrowed to antigravity; the U143 sound is untouched")


if __name__ == "__main__":
    unittest.main()
