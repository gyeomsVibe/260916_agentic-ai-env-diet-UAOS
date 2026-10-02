"""U131: the U127 resume cap must hold for a card window whose size was never recorded.

Receipt (2026-10-02): `coord deliver --card U129` to Antigravity answered relay_92514bb4 in conversation 4785a32f with
264,544 input tokens, far past RESUME_MAX_INPUT (70,000). `.coord/windows/U129.json` had that conversation from
`coord window --card U129 --tool antigravity` (opened_at about an hour before the letter) with no `last_input_tokens`,
so dispatch read the missing count as 0 and resumed an agentic conversation of unknown size. agy reports each turn's
own input (the whole conversation re-read), so the cap compares the last turn, not a running sum.
Fixed acceptance written by the judge (claude) before the run.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from v7_harness.coord import agy_dispatch, presence, windows
from v7_harness.coord.deliver import deliver
from v7_harness.coord.watch import watch_file

LETTER = "[review] verdict_requested=yes ACTIONABLE_DELTA: check diff X"


class UnrecordedWindowTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        sessions = Path(self._tmp.name) / "codex-sessions"
        sessions.mkdir()
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(sessions)})
        self._env.start()
        os.environ.pop("UAOS_AGY_AUTO", None)
        self._which = mock.patch("v7_harness.coord.deliver.shutil.which", side_effect=lambda name: name)
        self._which.start()
        presence.mark(self.project, "claude", "ACTIVE")
        presence.mark(self.project, "antigravity", "ACTIVE")
        beat = watch_file(self.project, "claude")  # a session-waking Claude watcher takes the reply (U117)
        beat.parent.mkdir(parents=True, exist_ok=True)
        beat.write_text(json.dumps({"tool": "claude", "token": "t", "pid": 1, "expires_at": time.time() + 300,
                                    "wakes_session": True}), encoding="utf-8")
        self.calls: list[list[str]] = []
        self.input_tokens = 25_000

    def tearDown(self) -> None:
        self._which.stop()
        self._env.stop()
        self._tmp.cleanup()

    def runner(self, argv, **kwargs):
        self.calls.append(list(argv))
        if Path(argv[0]).stem != "agy":
            raise AssertionError(f"only agy may run here: {argv[0]}")
        envelope = {"status": "SUCCESS", "conversation_id": "conv-new",
                    "usage": {"input_tokens": self.input_tokens, "output_tokens": 900}, "response": "PASS"}
        stdout = json.dumps(envelope)
        return SimpleNamespace(returncode=0, stdout=stdout if kwargs.get("text") else stdout.encode("utf-8"), stderr=b"")

    def send(self) -> None:
        deliver(self.project, message=LETTER, actor="claude", target="antigravity", runner=self.runner, card="U9")

    def _resumed(self) -> str | None:
        argv = self.calls[-1]
        return argv[argv.index("--conversation") + 1] if "--conversation" in argv else None

    def test_window_without_a_recorded_size_starts_fresh(self) -> None:
        windows.record_window(self.project, "U9", "antigravity", "conv-unknown")  # the U129 shape: no token count
        self.send()
        self.assertIsNone(self._resumed())
        entry = windows.window_entry(self.project, "U9", "antigravity")
        self.assertEqual(("conv-new", 25_000), (entry["id"], entry["last_input_tokens"]))

    def test_non_count_sizes_start_fresh(self) -> None:
        # U131-A audit: bool is an int subclass, so `true` in a hand-edited record would read as 1 token.
        for bad in (True, -5, 3.0, "100"):
            with self.subTest(bad=bad):
                windows.record_window(self.project, "U9", "antigravity", "conv-bad", last_input_tokens=bad)
                self.send()
                self.assertIsNone(self._resumed())

    def test_opened_window_ignores_a_non_count_size(self) -> None:
        self.input_tokens = True
        opened = windows.open_window(self.project, "U9", "antigravity", "x", "read the manual", runner=self.runner)
        self.assertNotIn("last_input_tokens", opened)

    def test_small_recorded_window_still_resumes(self) -> None:
        windows.record_window(self.project, "U9", "antigravity", "conv-1", last_input_tokens=0)
        self.send()
        self.assertEqual("conv-1", self._resumed())

    def test_opened_window_records_its_size(self) -> None:
        self.input_tokens = 264_544  # the U129 opening turn read the project with tools
        opened = windows.open_window(self.project, "U9", "antigravity", "x", "read the manual", runner=self.runner)
        self.assertEqual(264_544, opened["last_input_tokens"])
        self.assertEqual(264_544, windows.window_entry(self.project, "U9", "antigravity")["last_input_tokens"])

    def test_heavy_opened_window_is_not_resumed_by_a_letter(self) -> None:
        self.input_tokens = 264_544
        windows.open_window(self.project, "U9", "antigravity", "x", "read the manual", runner=self.runner)
        self.input_tokens = 25_000
        self.send()
        self.assertIsNone(self._resumed())

    def test_small_opened_window_is_resumed_by_a_letter(self) -> None:
        windows.open_window(self.project, "U9", "antigravity", "x", "read the manual", runner=self.runner)
        self.send()
        self.assertEqual("conv-new", self._resumed())
        self.assertLess(25_000, agy_dispatch.RESUME_MAX_INPUT)


if __name__ == "__main__":
    unittest.main()
