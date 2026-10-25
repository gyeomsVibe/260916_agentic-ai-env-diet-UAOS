"""U235: a native Antigravity PASS verdict letter satisfies AUDIT_FIRST.

Receipt (2026-10-25, U234): Antigravity's native session sent two PASS verdict
letters (kind HANDOFF, verdict PASS) to claude, but the gate only read the
auto-responder ledger, so Claude waited for a reply and Antigravity waited for
the commit: both idled until 윤겸스 reported it (U150-B report #2).
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.calculator_gate import audit_errors

GATED = "v7_harness/x.py"


class NativeVerdict(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mailbox = Path(self.tmp.name) / "mailbox"
        (self.mailbox / "delivery").mkdir(parents=True)
        (self.mailbox / "ack").mkdir()
        (self.mailbox / "inbox").mkdir()
        self.ledger = self.mailbox / "delivery" / "agy_auto.jsonl"
        self.ledger.write_text("", encoding="utf-8")

    def letter(self, folder: str, mid: str, **payload) -> None:
        body = {"message_id": mid, "payload": {"actor": "antigravity", "kind": "HANDOFF",
                                               "requested_target": "claude", "verdict": "PASS", **payload}}
        (self.mailbox / folder / f"{mid}.json").write_text(json.dumps(body), encoding="utf-8")

    def test_native_pass_letter_in_ack_or_inbox_is_accepted(self):
        self.letter("ack", "relay_be90f6")
        self.letter("inbox", "relay_aa11")
        self.assertEqual([], audit_errors("feat\n\nAudit: relay_be90f6\n", [GATED], self.ledger))
        self.assertEqual([], audit_errors("feat\n\nAudit: relay_aa11\n", [GATED], self.ledger))

    def test_non_pass_or_non_antigravity_letters_stay_refused(self):
        self.letter("ack", "relay_b1", verdict="FAIL")
        self.letter("ack", "relay_b2", actor="claude")
        self.letter("ack", "relay_b3", verdict=None)
        for mid in ("relay_b1", "relay_b2", "relay_b3", "relay_missing"):
            self.assertEqual(1, len(audit_errors(f"feat\n\nAudit: {mid}\n", [GATED], self.ledger)), mid)


if __name__ == "__main__":
    unittest.main()
