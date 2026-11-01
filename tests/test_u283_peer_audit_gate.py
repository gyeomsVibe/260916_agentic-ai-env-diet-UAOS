"""U283: a non-author peer PASS letter satisfies AUDIT_FIRST.

Receipt (2026-10-29, evt_20261029T0006 U282-COMMIT): Antigravity hit its usage
limit, the gate accepted only Antigravity replies, so every new v7_harness
commit dead-locked although Codex could audit Claude's code (author != judge,
U257 cross-approval). The author tool comes from the branch prefix; a letter
from that same tool never counts, and with no known author only Antigravity counts.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.calculator_gate import audit_errors, author_tool

GATED = "v7_harness/x.py"


class PeerAudit(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mailbox = Path(self.tmp.name) / "mailbox"
        (self.mailbox / "delivery").mkdir(parents=True)
        (self.mailbox / "ack").mkdir()
        (self.mailbox / "inbox").mkdir()
        self.ledger = self.mailbox / "delivery" / "agy_auto.jsonl"
        self.ledger.write_text("", encoding="utf-8")

    def letter(self, mid: str, **payload) -> None:
        body = {"message_id": mid, "payload": {"actor": "codex", "kind": "HANDOFF", "verdict": "PASS", **payload}}
        (self.mailbox / "ack" / f"{mid}.json").write_text(json.dumps(body), encoding="utf-8")

    def check(self, mid: str, author):
        return audit_errors(f"feat\n\nAudit: {mid}\n", [GATED], self.ledger, author=author)

    def test_branch_prefix_names_author(self):
        self.assertEqual("claude", author_tool("claude/u283-peer-audit-gate"))
        self.assertEqual("antigravity", author_tool("agy/u275-x"))
        self.assertEqual("codex", author_tool("codex/u278"))
        self.assertIsNone(author_tool("main"))
        self.assertIsNone(author_tool(""))

    def test_peer_pass_from_other_tool_is_accepted(self):
        self.letter("relay_c1")
        self.letter("relay_c2", actor="claude")
        self.assertEqual([], self.check("relay_c1", "claude"))
        self.assertEqual([], self.check("relay_c2", "codex"))
        self.assertEqual([], self.check("relay_c2", "antigravity"))

    def test_self_audit_is_refused(self):
        self.letter("relay_s1")
        self.letter("relay_s2", actor="claude")
        self.letter("relay_s3", actor="antigravity")
        self.assertEqual(1, len(self.check("relay_s1", "codex")))
        self.assertEqual(1, len(self.check("relay_s2", "claude")))
        self.assertEqual(1, len(self.check("relay_s3", "antigravity")))

    def test_unknown_author_accepts_only_antigravity(self):
        self.letter("relay_a1")
        self.letter("relay_a2", actor="antigravity")
        self.assertEqual(1, len(self.check("relay_a1", None)))
        self.assertEqual([], self.check("relay_a2", None))

    def test_non_pass_or_foreign_actor_refused(self):
        self.letter("relay_f1", verdict="REVISE")
        self.letter("relay_f2", actor="user")
        self.letter("relay_f3", verdict=None)
        for mid in ("relay_f1", "relay_f2", "relay_f3", "relay_missing"):
            self.assertEqual(1, len(self.check(mid, "claude")), mid)


if __name__ == "__main__":
    unittest.main()
