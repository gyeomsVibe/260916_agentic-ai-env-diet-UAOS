"""U210: the Stop gate holds a turn end while an ACTIONABLE letter addressed to the tool is still in the inbox.

Receipt 2026-10-18: Codex letter relay_9f21437a (the U209-R2C contract, requested_target claude) woke the Claude
session, the turn ended unread because no NEXT card was on the schedule for Claude, and Codex waited on receiver
consumption: both tools idle.
"""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from v7_harness.coord import stop_gate


def _letter(root: Path, name: str, payload: dict, age_s: float = 0.0) -> Path:
    inbox = root / ".coord" / "mailbox" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / f"{name}.json"
    path.write_text(json.dumps({"message_id": name, "payload": payload}), encoding="utf-8")
    if age_s:
        stamp = time.time() - age_s
        os.utime(path, (stamp, stamp))
    return path


class LetterStopGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / ".coord").mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_unread_actionable_letter_holds_once(self) -> None:
        _letter(self.root, "relay_aa", {"actor": "codex", "requested_target": "claude", "wake_class": "ACTIONABLE",
                                        "delta": "U209-R2C contract"})
        first = stop_gate.gate(self.root, "claude", session="s1")
        self.assertIsNotNone(first)
        self.assertEqual(first["decision"], "block")
        self.assertIn("relay_aa", first["reason"])
        self.assertIsNone(stop_gate.gate(self.root, "claude", session="s1"))  # one hold per letter, no spin

    def test_new_letter_holds_again(self) -> None:
        _letter(self.root, "relay_aa", {"actor": "codex", "requested_target": "claude", "wake_class": "ACTIONABLE"})
        self.assertIsNotNone(stop_gate.gate(self.root, "claude", session="s1"))
        _letter(self.root, "relay_bb", {"actor": "codex", "requested_target": "claude", "wake_class": "ACTIONABLE"})
        second = stop_gate.gate(self.root, "claude", session="s1")
        self.assertIsNotNone(second)
        self.assertIn("relay_bb", second["reason"])
        self.assertNotIn("relay_aa", second["reason"])

    def test_ignored_letters(self) -> None:
        _letter(self.root, "relay_other", {"actor": "claude", "requested_target": "codex", "wake_class": "ACTIONABLE"})
        _letter(self.root, "relay_quiet", {"actor": "codex", "requested_target": "claude", "wake_class": "ACK_ONLY"})
        _letter(self.root, "relay_old", {"actor": "codex", "requested_target": "claude", "wake_class": "ACTIONABLE"},
                age_s=stop_gate.LETTER_FRESH_S + 60)
        _letter(self.root, "evt_run", {"actor": "codex", "requested_target": "claude", "wake_class": "ACTIONABLE"})
        self.assertEqual(stop_gate.pending_letters(self.root, "claude"), [])
        self.assertIsNone(stop_gate.gate(self.root, "claude", session="s1"))

    def test_codex_gets_the_same_hold(self) -> None:
        _letter(self.root, "relay_cc", {"actor": "claude", "requested_target": "codex", "wake_class": "ACTIONABLE"})
        held = stop_gate.gate(self.root, "codex", session="c1")
        self.assertIsNotNone(held)
        self.assertEqual(held["decision"], "block")

    def test_no_session_no_hold(self) -> None:
        _letter(self.root, "relay_aa", {"actor": "codex", "requested_target": "claude", "wake_class": "ACTIONABLE"})
        self.assertIsNone(stop_gate.gate(self.root, "claude", session=None))


if __name__ == "__main__":
    unittest.main()
