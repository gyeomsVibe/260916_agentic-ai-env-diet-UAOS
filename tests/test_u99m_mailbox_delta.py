"""U99-M: every Claude session sees each new mailbox letter once, so the user never pastes a relay.

Receipt (2026-09-30, 윤겸스's report): Antigravity sent relay_59377bed (HANDOFF to claude) at 21:13. The prompt hook
showed nothing, and the user pasted Antigravity's output by hand. The cause was one cursor file shared by all Claude
sessions: another session's hook run moved it to 21:19:53, past the letter. A relay letter also showed as raw JSON,
because the hook read only `summary` or `verdict`, not `message`.
Fixed acceptance written by the judge (claude) before the fix.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from uaos_everywhere.hooks import codex_delta

# Fake clock (seconds): both sessions look at T0, the letter lands at T0+10, then A and B look again.
T0 = 1_800_000_000.0


class MailboxDeltaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.inbox = self.root / ".coord" / "mailbox" / "inbox"
        self.inbox.mkdir(parents=True)
        self.patches = [
            mock.patch.object(codex_delta, "ROOT", self.root),
            mock.patch.object(codex_delta, "COORDS", [self.root / ".coord"]),
            mock.patch.object(codex_delta, "CURSOR", self.root / "hooks" / "codex_delta_cursor.json"),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self) -> None:
        for patch in self.patches:
            patch.stop()
        self.tmp.cleanup()

    def _letter(self, at: float) -> None:
        letter = {"message_id": "relay_1", "payload": {"actor": "antigravity", "kind": "HANDOFF",
                                                      "message": "안티그래비티 대기: 다음 매뉴얼을 주세요",
                                                      "requested_target": "claude"}}
        path = self.inbox / "relay_1.json"
        path.write_text(json.dumps(letter, ensure_ascii=False), encoding="utf-8")
        os.utime(path, (at, at))

    def _prompt(self, session_id: str, at: float) -> str:
        out = io.StringIO()
        stdin = io.StringIO(json.dumps({"session_id": session_id}))
        with mock.patch("sys.stdin", stdin), mock.patch("time.time", return_value=at), redirect_stdout(out):
            self.assertEqual(0, codex_delta.main())
        return out.getvalue()

    def test_one_session_does_not_swallow_a_letter_for_another(self) -> None:
        self._prompt("A", T0)
        self._prompt("B", T0)
        self._letter(T0 + 10)
        self.assertIn("relay_1", self._prompt("A", T0 + 20))
        self.assertIn("relay_1", self._prompt("B", T0 + 30))

    def test_a_letter_is_shown_once_per_session(self) -> None:
        self._prompt("A", T0)
        self._letter(T0 + 10)
        self.assertIn("relay_1", self._prompt("A", T0 + 20))
        self.assertNotIn("relay_1", self._prompt("A", T0 + 30))

    def test_relay_message_text_is_shown(self) -> None:
        self._prompt("A", T0)
        self._letter(T0 + 10)
        self.assertIn("다음 매뉴얼을 주세요", self._prompt("A", T0 + 20))

    def test_session_id_cannot_escape_the_hooks_folder(self) -> None:
        self._prompt("../../evil", T0)
        written = [p for p in self.root.rglob("*") if p.is_file() and "cursor" in p.name]
        self.assertTrue(written)
        self.assertTrue(all(p.parent == self.root / "hooks" for p in written), written)


if __name__ == "__main__":
    unittest.main()
