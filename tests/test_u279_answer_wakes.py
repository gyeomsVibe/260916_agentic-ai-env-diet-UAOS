"""U279-F1: verdict_requested=False means "I am not asking you for a verdict", not "this needs no turn".

Codex U279 design verdict P1-1 (.work/desk_261028_1/U279_DESIGN_VERDICT.md): an ACTIONABLE answer carrying PASS/REVISE
with verdict_requested=False was filtered out, the same lost wake as U277. NOTICE and ACK_ONLY stay at zero dispatches.
"""

from __future__ import annotations

import unittest

from v7_harness.coord.deliver import _wants_wake

PLAIN = "plain note about the stage"


class AnswerWakesTest(unittest.TestCase):
    def test_actionable_answer_not_requesting_a_verdict_still_wakes(self):
        self.assertTrue(_wants_wake("REVISE U279 see verdict file", wake_class="ACTIONABLE", verdict_requested=False))

    def test_explicit_verdict_not_requesting_a_verdict_still_wakes(self):
        for verdict in ("PASS", "REVISE"):
            with self.subTest(verdict=verdict):
                self.assertTrue(_wants_wake(PLAIN, verdict=verdict, verdict_requested=False))

    def test_notice_and_ack_only_never_wake(self):
        for wake_class in ("NOTICE", "ACK_ONLY"):
            for verdict_requested in (None, False, True):
                with self.subTest(wake_class=wake_class, verdict_requested=verdict_requested):
                    self.assertFalse(_wants_wake(PLAIN, wake_class=wake_class, verdict="PASS",
                                                 verdict_requested=verdict_requested))
        self.assertFalse(_wants_wake("ACK_ONLY unchanged", verdict="PASS", verdict_requested=False))

    def test_plain_letter_marked_false_stays_quiet(self):
        self.assertFalse(_wants_wake(PLAIN, verdict_requested=False))
        self.assertFalse(_wants_wake("ACTIONABLE_DELTA new commit", verdict_requested=False))


if __name__ == "__main__":
    unittest.main()
