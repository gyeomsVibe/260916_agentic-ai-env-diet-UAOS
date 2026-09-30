"""U102-N: the prompt hook hides Claude's own mailbox letters, so real news from other tools is not buried.

Receipt (2026-09-30): the hook listed `evt_20260930T2341-claude-0001.json`, a RUN event Claude itself had written.
The old filter looked only at `name.split("-")[0]` (`evt_20260930t2341`) and the `claude_to_` prefix, so 240 of the
inbox's evt letters, all Claude's own, were shown to Claude as news. A relay sent by `coord deliver --actor claude`
has no name hint at all; only its payload `actor` says who wrote it.
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

# Fake clock (seconds): the cursor starts at T0 - 3600 (the hook's default), letters land at T0 - 10.
T0 = 1_800_000_000.0


class OwnLetterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.inbox = self.root / ".coord" / "mailbox" / "inbox"
        self.inbox.mkdir(parents=True)
        self.patches = [
            mock.patch.object(codex_delta, "ROOT", self.root),
            mock.patch.object(codex_delta, "COORDS", [self.root / ".coord"]),
            mock.patch.object(codex_delta, "CURSOR", self.root / "hooks" / "codex_delta_cursor.json"),
            # Git history and leases are U101's concern; this test looks at letters only.
            mock.patch.dict("sys.modules", {"absence_brief": mock.Mock(absence_items=lambda root, since: [])}),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self) -> None:
        for patch in self.patches:
            patch.stop()
        self.tmp.cleanup()

    def _letter(self, name: str, actor: str, message: str) -> None:
        letter = {"message_id": name, "payload": {"actor": actor, "kind": "RUN", "summary": message}}
        path = self.inbox / f"{name}.json"
        path.write_text(json.dumps(letter), encoding="utf-8")
        os.utime(path, (T0 - 10, T0 - 10))

    def _prompt(self) -> str:
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(json.dumps({"session_id": "s1"}))), \
                mock.patch("time.time", return_value=T0), redirect_stdout(out):
            self.assertEqual(0, codex_delta.main())
        return out.getvalue()

    def test_own_evt_letter_is_hidden(self) -> None:
        self._letter("evt_20260930T2341-claude-0001", "claude", "own run finished")
        self.assertNotIn("own run finished", self._prompt())

    def test_own_relay_is_hidden_by_actor(self) -> None:
        self._letter("relay_1a2b3c4d", "claude", "own relay to antigravity")
        self.assertNotIn("own relay to antigravity", self._prompt())

    def test_other_tools_letters_still_show(self) -> None:
        self._letter("evt_20260930T2341-codex-0001", "codex", "codex verdict ready")
        self._letter("relay_9f8e7d6c", "antigravity", "antigravity handoff")
        out = self._prompt()
        self.assertIn("codex verdict ready", out)
        self.assertIn("antigravity handoff", out)


if __name__ == "__main__":
    unittest.main()
