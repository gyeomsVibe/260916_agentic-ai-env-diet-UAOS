"""U104: Antigravity's prompt hook shows the newest letters addressed to it, not the oldest.

Receipt (윤겸스, 2026-10-01): the U103-V verdict order (relay_2d1f…, 00:48) never reached Antigravity; at 00:54 it
replied it was still waiting for that letter, and the user pasted Claude's status line into Antigravity by hand.
Cause, measured on the real inbox: 12 unacked letters were addressed to Antigravity and `agy_line` named the first 5
by file name, all from 2026-09-26; the new letter was number 11. The sender-side check (`deliver` ok: true) passed.
Fixed acceptance written by the judge (claude) before the fix; it checks the receiver's own hook text.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord.hook_context import AGY_SHOWN, agy_letters, agy_line

DESK = {"codex": {"state": "LIMITED"}, "claude": {"state": "ACTIVE"}, "antigravity": {"state": "ACTIVE"}}
EVENT = json.dumps({"conversationId": "g1", "invocationNum": 0})


class AntigravitySeesNewLettersTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        self.inbox = self.project / ".coord" / "mailbox" / "inbox"
        self.inbox.mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        # Eleven old orders whose names sort before the new one, like claude_to_agy_* from 2026-09-26.
        for index in range(11):
            self._letter(f"claude_old_{index:02d}", f"old order {index}", mtime=1_000_000 + index)
        self._letter("relay_2d1f", "U103-V read-only validation of PR #78", mtime=2_000_000)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _letter(self, name: str, message: str, mtime: float) -> None:
        path = self.inbox / f"{name}.json"
        path.write_text(json.dumps({"message_id": name, "payload": {
            "actor": "claude", "requested_target": "antigravity", "message": message}}), encoding="utf-8")
        os.utime(path, (mtime, mtime))

    def test_newest_letter_comes_first(self) -> None:
        self.assertEqual("relay_2d1f", agy_letters(self.project)[0])

    def test_hook_line_names_the_new_letter_and_its_order(self) -> None:
        line = agy_line(self.project, DESK, EVENT)
        self.assertIn("relay_2d1f", line)
        self.assertIn("U103-V read-only validation", line)
        self.assertIn("12 letter(s)", line)

    def test_hook_line_still_caps_the_ids_shown(self) -> None:
        line = agy_line(self.project, DESK, EVENT)
        shown = [name for name in agy_letters(self.project) if name in line]
        self.assertEqual(AGY_SHOWN, len(shown))


if __name__ == "__main__":
    unittest.main()
