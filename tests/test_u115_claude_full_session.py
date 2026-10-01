"""U115 judge finding: a Claude window letter must resume the window's full session id, where its transcript lives.

Live evidence 2026-10-01 (window b5a6062d, the U115 window itself): `claude --bg` printed the 8-hex prefix `b5a6062d`,
which U114 records, but `claude --resume` takes the full id (`claude agents --json`: sessionId
`b5a6062d-09f3-…`). The session started in the main checkout, entered a worktree, and its transcript now sits under
that worktree's `~/.claude/projects/<slug>/` folder, so a resume from the main checkout would not find it. The transcript
file names the full id and its rows carry the latest `cwd`. Fixed acceptance written by the judge (claude); no paid call.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from v7_harness.coord import presence
from v7_harness.coord.deliver import deliver
from v7_harness.coord.windows import claude_session

FULL = "b5a6062d-09f3-4952-bfa0-59d3dac8ac65"


class _Runner:
    def __init__(self):
        self.calls = []

    def __call__(self, command, **kw):
        self.calls.append((list(command), kw.get("cwd")))
        return SimpleNamespace(returncode=0, stdout=json.dumps({"result": "ok"}), stderr="")


class ClaudeFullSession(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.project = root / "proj"
        (self.project / ".coord").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        self.home = root / "claude-home"
        self.worktree = str(root / "proj-worktree")
        transcript = self.home / "projects" / "proj-worktree" / f"{FULL}.jsonl"
        transcript.parent.mkdir(parents=True)
        transcript.write_text("\n".join([
            json.dumps({"type": "custom-title", "sessionId": FULL}),
            json.dumps({"type": "attachment", "cwd": str(self.project), "sessionId": FULL}),
            "not json",
            json.dumps({"type": "assistant", "cwd": self.worktree, "sessionId": FULL}),
        ]) + "\n", encoding="utf-8")
        sessions = root / "codex-sessions"
        sessions.mkdir()
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(sessions),
                                                 "CLAUDE_CONFIG_DIR": str(self.home)})
        self._env.start()
        self._which = mock.patch("v7_harness.coord.deliver.shutil.which", side_effect=lambda name: name)
        self._which.start()

    def tearDown(self):
        self._which.stop()
        self._env.stop()
        self._tmp.cleanup()

    def test_the_prefix_resolves_to_the_full_id_and_the_latest_cwd(self):
        self.assertEqual((FULL, self.worktree), claude_session("b5a6062d"))

    def test_an_unknown_or_ambiguous_prefix_is_returned_as_is(self):
        self.assertEqual(("ffffffff", ""), claude_session("ffffffff"))
        twin = self.home / "projects" / "other" / "b5a6062d-0000-0000-0000-000000000000.jsonl"
        twin.parent.mkdir(parents=True)
        twin.write_text("{}\n", encoding="utf-8")
        self.assertEqual(("b5a6062d", ""), claude_session("b5a6062d"))

    def test_a_window_letter_resumes_the_full_id_in_the_transcript_cwd(self):
        presence.mark(self.project, "claude", "ACTIVE")
        record = self.project / ".coord" / "windows" / "U115.json"
        record.parent.mkdir(parents=True)
        record.write_text(json.dumps({"card": "U115", "title": "[U115] t",
                                      "tools": {"claude": {"id": "b5a6062d", "opened_at": 0}}}), encoding="utf-8")
        runner = _Runner()
        deliver(self.project, message="U115 full id ACTIONABLE_DELTA", actor="codex", target="claude",
                runner=runner, card="U115")
        argv, cwd = runner.calls[0]
        self.assertEqual(FULL, argv[argv.index("--resume") + 1])
        self.assertEqual(self.worktree, cwd)


if __name__ == "__main__":
    unittest.main()
