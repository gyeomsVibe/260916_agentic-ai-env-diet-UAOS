"""Regression tests for letter visibility and backlog aggregation."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord import desk_delta

NOW = 1_800_000_000.0


class AddressedLetterFirstLookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.inbox = self.root / ".coord" / "mailbox" / "inbox"
        self.inbox.mkdir(parents=True)
        (self.root / ".coord" / "mailbox" / "ack").mkdir(parents=True)
        (self.root / ".coord" / "PLAN.md").write_text("| Card | Status | Owner | Note |\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "init", "-q"], check=True, capture_output=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _letter(self, name: str, target: str, message: str, age_s: float) -> Path:
        path = self.inbox / f"{name}.json"
        path.write_text(json.dumps({"message_id": name, "payload": {
            "actor": "antigravity", "kind": "HANDOFF", "requested_target": target, "message": message}}),
            encoding="utf-8")
        os.utime(path, (NOW - age_s, NOW - age_s))
        return path

    def test_addressed_letter_older_than_one_hour_is_shown_on_first_look(self) -> None:
        # 72 minutes old, as in the receipt.
        self._letter("relay_consult", "claude", "MIA STRATEGIC CONSULTATION requesting Claude review", 72 * 60)
        text = desk_delta.delta_text(self.root, "claude", "new-session", now=NOW)
        self.assertIn("relay_consult", text)

    def test_letter_for_another_tool_keeps_the_one_hour_window(self) -> None:
        self._letter("relay_other", "codex", "for codex only", 72 * 60)
        text = desk_delta.delta_text(self.root, "claude", "new-session", now=NOW)
        self.assertNotIn("relay_other", text)

    def test_acked_addressed_letter_is_not_shown(self) -> None:
        letter = self._letter("relay_done", "claude", "already handled", 72 * 60)
        (self.root / ".coord" / "mailbox" / "ack" / letter.name).write_text("{}", encoding="utf-8")
        text = desk_delta.delta_text(self.root, "claude", "new-session", now=NOW)
        self.assertNotIn("relay_done", text)

    def test_older_unacked_backlog_is_counted_not_silent(self) -> None:
        self._letter("relay_ancient", "claude", "two days old", 2 * 86400)
        text = desk_delta.delta_text(self.root, "claude", "new-session", now=NOW)
        self.assertIn("UNACKED_BACKLOG 1", text)
        self.assertNotIn("relay_ancient", text)


class FirstLookHelperTests(unittest.TestCase):
    def test_helper_classifies_fresh_backlog_and_skips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Path(tmp) / "mailbox" / "inbox"
            inbox.mkdir(parents=True)
            (inbox.parent / "ack").mkdir()
            self.assertEqual(desk_delta.ADDRESSED_FIRST_LOOK_S, 86400)
            cases = {"fresh": ("claude", 72 * 60), "backlog": ("claude", 2 * 86400), None: ("codex", 60)}
            for expected, (target, age) in cases.items():
                path = inbox / f"relay_{expected}.json"
                path.write_text(json.dumps({"payload": {"requested_target": target}}), encoding="utf-8")
                os.utime(path, (NOW - age, NOW - age))
                self.assertEqual(desk_delta._first_look_addressed(path, inbox, "claude", NOW), expected)
            acked = inbox / "relay_fresh.json"
            (inbox.parent / "ack" / acked.name).write_text("{}", encoding="utf-8")
            self.assertIsNone(desk_delta._first_look_addressed(acked, inbox, "claude", NOW))


if __name__ == "__main__":
    unittest.main()
