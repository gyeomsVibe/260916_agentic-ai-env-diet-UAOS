"""U53: Codex <-> Claude relay keeps one Claude conversation and never loses its reply."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from v7_harness.coord.deliver import deliver


class RecordingRunner:
    def __init__(self, replies: list[str]):
        self.replies = iter(replies)
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), dict(kwargs)))
        reply = next(self.replies)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"type": "result", "result": reply}, ensure_ascii=False),
            stderr="",
        )


class NonstopClaudeRelayTests(unittest.TestCase):
    def test_reply_is_utf8_safe_persisted_and_reused_on_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            project = Path(d)
            (project / ".coord" / "mailbox").mkdir(parents=True)
            runner = RecordingRunner(["한국어 응답"])
            with patch("v7_harness.coord.deliver.shutil.which", return_value="claude"):
                first = deliver(project, message="same", actor="codex", target="claude", runner=runner)
                second = deliver(project, message="same", actor="codex", target="claude", runner=runner)

            self.assertEqual("한국어 응답", first.output)
            self.assertEqual("한국어 응답", second.output)
            self.assertEqual(1, len(runner.calls))
            receipt = json.loads(Path(first.receipt).read_text(encoding="utf-8"))
            self.assertEqual("한국어 응답", receipt["output"])
            self.assertEqual("DISPATCHED", receipt["state"])
            kwargs = runner.calls[0][1]
            self.assertEqual("utf-8", kwargs["encoding"])
            self.assertEqual("replace", kwargs["errors"])

    def test_distinct_messages_resume_one_persisted_claude_session(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            project = Path(d)
            (project / ".coord" / "mailbox").mkdir(parents=True)
            runner = RecordingRunner(["first reply", "second reply"])
            with patch("v7_harness.coord.deliver.shutil.which", return_value="claude"):
                first = deliver(project, message="one", actor="codex", target="claude", runner=runner)
                second = deliver(project, message="two", actor="codex", target="claude", runner=runner)

            first_argv, _ = runner.calls[0]
            second_argv, _ = runner.calls[1]
            self.assertIn("--session-id", first_argv)
            session_id = first_argv[first_argv.index("--session-id") + 1]
            self.assertIn("--resume", second_argv)
            self.assertEqual(session_id, second_argv[second_argv.index("--resume") + 1])
            self.assertNotIn("After processing, run coord ack", first_argv[first_argv.index("-p") + 1])
            self.assertEqual("first reply", first.output)
            self.assertEqual("second reply", second.output)

    def test_secret_in_reply_is_not_printed_or_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            project = Path(d)
            (project / ".coord" / "mailbox").mkdir(parents=True)
            runner = RecordingRunner(["api_key=sk-abc1234567890abcdefghij"])
            with patch("v7_harness.coord.deliver.shutil.which", return_value="claude"):
                result = deliver(project, message="clean", actor="codex", target="claude", runner=runner)

            self.assertEqual("DELIVERY_FAILED:SECRET_IN_RESPONSE", result.reason)
            self.assertEqual("", result.output)
            receipt = json.loads(Path(result.receipt).read_text(encoding="utf-8"))
            self.assertEqual("", receipt["output"])
            self.assertNotIn("sk-", json.dumps(receipt))


if __name__ == "__main__":
    unittest.main()
