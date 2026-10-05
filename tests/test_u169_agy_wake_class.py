"""U169: the Antigravity auto-answer (U120) obeys an explicit wake class, like the U143 sound (frozen acceptance).

Receipt: P1 event evt_20261004T1819-claude-0001 (U120-ACK-SUPPRESS). `deliver` started the headless answer only when
the letter's TEXT asked for a turn, so a letter sent with `--wake-class ACTIONABLE` whose prose named the
acknowledgement-only token got no answer, and an explicit NOTICE whose text looked like a request still spent a paid
call. The rule now matches the U143 ring: an explicit ACTIONABLE dispatches, an explicit NOTICE never does, and only a
letter with no explicit class falls back to the text check.
"""

import unittest

from tests.test_u120_agy_auto_reply import AgyAutoReply as _Base
from v7_harness.coord.deliver import deliver


class AgyWakeClass(_Base):
    def send_with(self, message, **fields):
        return deliver(self.project, message=message, actor="claude", target="antigravity", runner=self.runner,
                       **fields)

    def test_explicit_actionable_dispatches_even_when_the_text_names_ack_only(self):
        result = self.send_with("Status: the previous letter said ACK_ONLY by mistake; review diff X.",
                                wake_class="ACTIONABLE", delta="review diff X")
        self.assertEqual(1, len(self.calls))
        self.assertTrue(result.output.startswith("AGY_ANSWERED"), result.output)

    def test_explicit_notice_never_dispatches_even_when_the_text_asks(self):
        result = self.send_with("ACTIONABLE_DELTA verdict_requested=yes: review diff X", wake_class="NOTICE")
        self.assertEqual(0, len(self.calls))  # a count, not the call list: a failure must not print the env
        self.assertFalse(result.output.startswith("AGY_"), result.output)

    def test_no_explicit_class_keeps_the_text_check(self):
        self.send_with("ACK_ONLY: nothing changed")
        self.assertEqual(0, len(self.calls))
        self.send_with("ACTIONABLE_DELTA verdict_requested=yes: review diff Y")
        self.assertEqual(1, len(self.calls))


# Importing the base re-runs its U120 tests here too: the old behaviour must hold beside the new rule.

if __name__ == "__main__":
    unittest.main()
