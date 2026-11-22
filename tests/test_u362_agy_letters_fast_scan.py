"""U362: agy_letters prefilters inbox names (os.scandir) so evt_*.json payloads are never read.

Receipt: the Antigravity prompt hook (agy_line -> agy_letters) globbed every *.json in the mailbox inbox and parsed
each one, including the hundreds of evt_* event files that can never be a letter, on the first model call of a turn.
Fixed acceptance: no Path.read_text call on an evt_* file, same newest-first order, bad entries still skipped.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord.hook_context import agy_letters, agy_line, desk_label
from v7_harness.coord.mode import mode_phrase

DESK = {"codex": {"state": "LIMITED"}, "claude": {"state": "ACTIVE"}, "antigravity": {"state": "ACTIVE"}}
EVENT = json.dumps({"conversationId": "g1", "invocationNum": 0})
EVT_COUNT = 300  # large enough that a per-file read would be an obvious cost, small enough to build in ms

_REAL_READ_TEXT = Path.read_text


class AgyLettersFastScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        self.inbox = self.project / ".coord" / "mailbox" / "inbox"
        self.inbox.mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _letter(self, name: str, target_key: str, target: str, message: str, mtime: float) -> None:
        path = self.inbox / f"{name}.json"
        path.write_text(json.dumps({"message_id": name, "payload": {
            "actor": "claude", target_key: target, "message": message}}), encoding="utf-8")
        os.utime(path, (mtime, mtime))

    def _read_log(self) -> list[Path]:
        """Patch Path.read_text with a wrapper that records every path then reads for real."""
        reads: list[Path] = []

        def spy(path: Path, *args, **kwargs):
            reads.append(Path(path))
            return _REAL_READ_TEXT(path, *args, **kwargs)

        patcher = mock.patch.object(Path, "read_text", autospec=True, side_effect=spy)
        patcher.start()
        self.addCleanup(patcher.stop)
        return reads

    def _fill(self) -> None:
        for index in range(EVT_COUNT):
            (self.inbox / f"evt_{index:04d}.json").write_text(
                json.dumps({"payload": {"requested_target": "antigravity", "to": "antigravity"}}), encoding="utf-8")
        self._letter("claude_old", "requested_target", "antigravity", "old order", mtime=1_000_000)
        self._letter("relay_new", "to", "antigravity", "new order", mtime=2_000_000)
        self._letter("claude_only", "requested_target", "claude", "for claude", mtime=3_000_000)

    def test_agy_letters_skips_evt_files_and_keeps_newest_first_order(self) -> None:
        self._fill()
        reads = self._read_log()
        self.assertEqual(["relay_new", "claude_old"], agy_letters(self.project))
        self.assertEqual([], [p for p in reads if p.name.startswith("evt_")])

    def test_agy_letters_ignores_json_dirs_and_corrupt_json(self) -> None:
        (self.inbox / "dir.json").mkdir()
        (self.inbox / "relay_bad.json").write_text("{not json", encoding="utf-8")
        self._letter("relay_ok", "requested_target", "antigravity", "fine", mtime=2_000_000)
        self.assertEqual(["relay_ok"], agy_letters(self.project))

    def test_agy_line_names_letters_without_reading_evt_files(self) -> None:
        self._fill()
        reads = self._read_log()
        line = agy_line(self.project, DESK, EVENT)
        self.assertEqual([], [p for p in reads if p.name.startswith("evt_")])
        desk = ", ".join(f"{tool}={desk_label(info)}" for tool, info in DESK.items())
        expected_head = (f"UAOS project {self.project.name}: desk {desk}. Antigravity conducts only while codex and "
                         "claude are both LIMITED/ABSENT; otherwise it does only work orders addressed to "
                         f"antigravity and never judges its own work. {mode_phrase(self.project)} ")
        self.assertTrue(line.startswith(expected_head), line)
        self.assertIn("2 letter(s) for antigravity in .coord/mailbox/inbox, newest first: relay_new, claude_old. "
                      "Newest says: new order ", line)


if __name__ == "__main__":
    unittest.main()
