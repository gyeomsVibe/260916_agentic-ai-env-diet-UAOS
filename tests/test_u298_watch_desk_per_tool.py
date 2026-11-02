"""U298: main_desk_session(project, tool) reads user_desk_<tool>.json so _session_eligible works for antigravity/codex."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord import watch


def _write_desk(root: Path, tool: str, thread: str) -> None:
    path = root / ".coord" / "presence" / f"user_desk_{tool}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"thread": thread, "at": 1.0}), encoding="utf-8")


class TestU298WatchDeskPerTool(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_antigravity_and_codex_main_desk_take_unaddressed_when_claude_desk_differs(self) -> None:
        _write_desk(self.root, "claude", "claude-session-Y")
        _write_desk(self.root, "antigravity", "agy-session-X")
        _write_desk(self.root, "codex", "codex-session-Z")

        agy_letter = {"requested_target": "antigravity", "message": "PASS PR #261"}
        self.assertTrue(watch._session_eligible(self.root, "antigravity", agy_letter, "agy-session-X"))
        self.assertFalse(watch._session_eligible(self.root, "antigravity", agy_letter, "agy-child-W"))
        self.assertFalse(watch._session_eligible(self.root, "antigravity", agy_letter, "claude-session-Y"))

        codex_letter = {"requested_target": "codex", "message": "delta"}
        self.assertTrue(watch._session_eligible(self.root, "codex", codex_letter, "codex-session-Z"))
        self.assertFalse(watch._session_eligible(self.root, "codex", codex_letter, "claude-session-Y"))

    def test_existing_claude_default_and_agy_alias(self) -> None:
        _write_desk(self.root, "claude", "claude-session-Y")
        _write_desk(self.root, "antigravity", "agy-session-X")
        self.assertEqual(watch.main_desk_session(self.root), "claude-session-Y")
        self.assertEqual(watch.main_desk_session(self.root, "claude"), "claude-session-Y")
        self.assertEqual(watch.main_desk_session(self.root, "antigravity"), "agy-session-X")
        self.assertEqual(watch.main_desk_session(self.root, "agy"), "agy-session-X")
        claude_letter = {"requested_target": "claude", "message": "hi"}
        self.assertTrue(watch._session_eligible(self.root, "claude", claude_letter, "claude-session-Y"))
        self.assertFalse(watch._session_eligible(self.root, "claude", claude_letter, "agy-session-X"))


if __name__ == "__main__":
    unittest.main()
