"""U214: a letter bound to one native receiver stays bound from deliver to ACK, and nobody else can erase it.

Receipt (2026-10-18, roundtable `.coord/reviews/U214-roundtable-root-decision-261018.json`): Codex asked owner
923a686c for a handshake (relay_fc6aefbc); the user desk session a6f8e928 consumed and ACKed it instead, so the bound
payload vanished and the desk waited on an owner who never saw it. Known causes: explicit thread omitted from the
payload and the no-card identity, and a wrong-consumer ACK erasing the bound payload. Antigravity review
relay_c1933f32 (blocker 1): a caller without a session must still see bound letters, or the hold goes silent again.
"""
import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord import deliver, stop_gate
from v7_harness.coord.mailbox import Mailbox, MailboxRejected


class ReceiverBinding(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".coord" / "mailbox").mkdir(parents=True)
        self.box = Mailbox(self.root / ".coord" / "mailbox")

    def _letter(self, name, **extra):
        body = {"actor": "codex", "requested_target": "claude", "wake_class": "ACTIONABLE", "message": "handshake",
                **extra}
        self.box.publish(name, body)

    # --- identity and payload --------------------------------------------------------------------------------
    def test_an_explicit_thread_is_stored_as_the_receiver(self):
        body = deliver._payload("codex", "m", "d", "claude", window="thread-A")
        self.assertEqual("thread-A", body["native_receiver"])

    def test_a_letter_without_a_thread_keeps_todays_bytes(self):
        self.assertNotIn("native_receiver", deliver._payload("codex", "m", "d", "claude"))

    def test_a_letter_to_antigravity_is_never_bound(self):
        # Antigravity review relay_2d46a6ae: its headless auto-reply acks under its own id, so a bound key would block it.
        self.assertNotIn("native_receiver", deliver._payload("claude", "m", "d", "antigravity", window="thread-A"))

    def test_the_same_text_to_two_receivers_is_two_letters(self):
        one = deliver._digest("codex", "m", window="thread-A", target="claude")
        two = deliver._digest("codex", "m", window="thread-B", target="claude")
        self.assertNotEqual(one, two)
        self.assertEqual(deliver._digest("codex", "m", target="claude"),
                         deliver._digest("codex", "m", target="claude"))

    # --- ACK ---------------------------------------------------------------------------------------------------
    def test_a_wrong_consumer_ack_keeps_the_bound_letter(self):
        self._letter("relay_a", native_receiver="thread-A")
        claim = self.box.claim("relay_a", "thread-B")
        with self.assertRaises(MailboxRejected):
            self.box.ack(claim)
        self.assertIn("relay_a", self.box.list_inbox())

    def test_the_bound_consumer_ack_settles_the_letter(self):
        self._letter("relay_a", native_receiver="thread-A")
        self.box.ack(self.box.claim("relay_a", "thread-A"))
        self.assertNotIn("relay_a", self.box.list_inbox())

    def test_an_unbound_letter_is_acked_by_any_consumer(self):
        self._letter("relay_a")
        self.box.ack(self.box.claim("relay_a", "commander"))
        self.assertNotIn("relay_a", self.box.list_inbox())

    # --- who is held ------------------------------------------------------------------------------------------
    def test_a_letter_bound_to_another_session_does_not_hold_this_one(self):
        self._letter("relay_a", native_receiver="thread-A")
        self.assertEqual([], stop_gate.pending_letters(self.root, "claude", session="thread-B"))

    def test_the_bound_session_is_held(self):
        self._letter("relay_a", native_receiver="thread-A")
        self.assertEqual(["relay_a"], stop_gate.pending_letters(self.root, "claude", session="thread-A"))

    def test_a_caller_without_a_session_still_sees_bound_letters(self):
        self._letter("relay_a", native_receiver="thread-A")
        self._letter("relay_b", card="U9")
        self.assertEqual(["relay_a", "relay_b"],
                         sorted(stop_gate.pending_letters(self.root, "claude", session=None)))

    def test_a_malformed_card_record_never_raises(self):
        (self.root / ".coord" / "windows.json").write_text(json.dumps([]), encoding="utf-8")
        self._letter("relay_a", card="U9")
        self.assertEqual([], stop_gate.pending_letters(self.root, "claude", session="thread-B"))


if __name__ == "__main__":
    unittest.main()
