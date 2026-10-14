"""U188: a verdict written only as text to a turn-based tool is refused visibly instead of published asleep.

Receipt (user report 2026-10-14: "Codex and Claude both sit idle, months of fixes never cured it"). In the live
mailbox 98 of 198 codex->claude letters had no waking class: 26 explicit NOTICE and 72 untagged without a
U141-B wake token (counts show the class, not that each letter needed action). relay_f3fcef63 (U187 REVISE) and relay_1be9792b (WAKE NOT ACCEPTED) were NOTICE, so the live
structured watcher stayed asleep and Claude idled holding actionable work; 36 of 72 claude->codex letters were the
same. The wake depended on the sender remembering a tag, so every fix that relied on agents tagging decayed.

Codex design verdict relay_61456b14: text never becomes authoritative and an explicit NOTICE never wakes; a
contradiction fails visibly. Rule: for a codex or claude receiver, an uppercase verdict token as a whole word in the
first unquoted line, with no structured verdict, verdict request or ACTIONABLE class, is refused before publish
(UNSTRUCTURED_VERDICT, CLI exit 1). The sender resends with `--verdict`, or marks a status echo ACK_ONLY. Antigravity
keeps U169; lower case, quoted text, later lines and the auto route are unchanged.
"""
from __future__ import annotations

import unittest

from tests.test_u141b_producer_wake import Base
from v7_harness.coord import watch as W
from v7_harness.coord.deliver import deliver

REVISE = ("U187-A1 exactbundleba1d868a: REVISE, no promotion. Independent disposable-root cases both suppress.\n"
          "Do not retry paid AGY review until deterministic refusals pass.")
NOT_ACCEPTED = "WAKE proof1931eca937b0 contractd43315ea: NOT ACCEPTED. Deterministic scratch counterexample."


class UnstructuredVerdictRefused(Base):
    def test_the_real_verdicts_are_refused_untagged_or_notice(self):
        for message in (REVISE, NOT_ACCEPTED):
            for fields in ({}, {"wake_class": "NOTICE"}):
                with self.subTest(message=message[:20], fields=fields):
                    result = deliver(self.root, actor="codex", message=message, target="claude", **fields)
                    self.assertEqual("UNSTRUCTURED_VERDICT", result.reason)
                    self.assertIn("--verdict", result.output)
                    self.assertEqual([], list(self.box.list_inbox()))
                    self.assertIsNone(self.watch("claude"))

    def test_each_verdict_token_is_refused_to_codex(self):
        for token in ("PASS", "FAIL", "REVISE", "REWORK", "PIVOT", "APPROVE", "NO-GO", "ACCEPTED", "NOT ACCEPTED"):
            with self.subTest(token=token):
                result = deliver(self.root, actor="claude", message=f"U188 bundle 1: {token}", target="codex")
                self.assertEqual("UNSTRUCTURED_VERDICT", result.reason)


class StructuredVerdictWakes(Base):
    def test_a_structured_verdict_wakes_claude_and_codex(self):
        for actor, target in (("codex", "claude"), ("claude", "codex")):
            with self.subTest(target=target):
                result = deliver(self.root, actor=actor, message=REVISE, target=target, verdict="REVISE")
                self.assertNotIn(result.reason, ("UNSTRUCTURED_VERDICT", "INVALID_INTENT"))
                self.assertEqual(("ACTIONABLE", ""), W.classify(self.payload(result)))
                self.assertEqual(result.message_id, self.watch(target)["id"])

    def test_an_explicit_actionable_or_request_is_accepted(self):
        for fields in ({"wake_class": "ACTIONABLE", "delta": "U187 revise"}, {"verdict_requested": True}):
            with self.subTest(fields=fields):
                result = deliver(self.root, actor="codex", message=NOT_ACCEPTED, target="claude", **fields)
                self.assertNotIn(result.reason, ("UNSTRUCTURED_VERDICT", "INVALID_INTENT"))
                self.assertEqual("ACTIONABLE", W.classify(self.payload(result))[0])


class StatusTextUnchanged(Base):
    def test_status_text_publishes_without_a_wake(self):
        cases = {
            "lower case": ("the tests pass and the file was revised", {}),
            "inside a word": ("PASSWORD rotation and BYPASS mode are FAILSAFE notes", {}),
            "second line only": ("status of U188\nPASS on the focused tests", {}),
            "quoted": ('status: the word "REVISE" is a verdict label', {}),
            "ack only": ("ACK_ONLY U188 bundle 1: PASS", {}),
            "ack only notice": ("ACK_ONLY U188 bundle 1: PASS", {"wake_class": "NOTICE"}),
        }
        for name, (message, fields) in cases.items():
            with self.subTest(case=name):
                result = deliver(self.root, actor="codex", message=message, target="claude", **fields)
                self.assertNotEqual("UNSTRUCTURED_VERDICT", result.reason)
                self.assertIn(result.message_id, list(self.box.list_inbox()))
                self.assertIsNone(self.watch("claude"))

    def test_antigravity_keeps_an_explicit_notice(self):
        result = deliver(self.root, actor="codex", message="U188 bundle 1: PASS", target="antigravity",
                         wake_class="NOTICE")
        self.assertEqual(("NOTICE", ""), W.classify(self.payload(result)))

    def test_auto_route_letter_is_unchanged(self):
        result = deliver(self.root, actor="claude", message="U188 bundle 1: PASS")
        self.assertNotEqual("UNSTRUCTURED_VERDICT", result.reason)
        self.assertNotIn("wake_class", self.payload(result))


if __name__ == "__main__":
    unittest.main()
