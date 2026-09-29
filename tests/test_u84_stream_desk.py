"""U84: a linked worktree's `coord log` and pilot events land in the main checkout's stream (the desk).

Seen 2026-09-29: the acting conductor ran `coord log --project .` in `.claude/worktrees/<name>`. The event went to that
worktree's gitignored `.coord/stream`, while `coord deliver` from the same folder reached the desk (U59). 76 events
from 2026-09-20 to 09-29 were stranded there, so the desk's codex_brief (brief.py reads the stream) never showed the
acting work Codex must re-review. U59 moved presence and mail, U72-L the ledger; the stream is the same runtime state.
"""

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from v7_harness.cli import main
from v7_harness.coord.stream import append_event, read_events, stream_dir


def _plan(root: Path) -> None:
    (root / ".coord").mkdir(parents=True, exist_ok=True)
    (root / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")


class StreamDeskTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.main = base / "repo"
        self.tree = self.main / ".claude" / "worktrees" / "w1"
        _plan(self.main)
        _plan(self.tree)
        (self.main / ".git" / "worktrees" / "w1").mkdir(parents=True)
        (self.tree / ".git").write_text(f"gitdir: {(self.main / '.git' / 'worktrees' / 'w1').as_posix()}\n",
                                        encoding="utf-8")

    def test_coord_log_from_a_worktree_lands_on_the_desk(self):
        with redirect_stdout(io.StringIO()):
            code = main(["coord", "log", "--project", str(self.tree), "--actor", "claude", "--kind", "NOTE",
                         "--step", "U84", "--summary", "acting work for Codex re-review"])
        self.assertEqual(0, code)
        self.assertFalse((self.tree / ".coord" / "stream").exists(), "the event was stranded in the worktree")
        events = read_events(self.main)
        self.assertEqual(["U84"], [event["step"] for event in events])

    def test_both_checkouts_read_one_stream(self):
        append_event(self.tree, actor="claude", kind="NOTE", step="W", summary="from the worktree")
        append_event(self.main, actor="claude", kind="NOTE", step="M", summary="from the desk")
        self.assertEqual(stream_dir(self.main), stream_dir(self.tree))
        self.assertEqual(read_events(self.main), read_events(self.tree))
        self.assertEqual({"W", "M"}, {event["step"] for event in read_events(self.main)})

    def test_a_plain_project_keeps_its_own_stream(self):
        plain = Path(self._tmp.name) / "plain"
        _plan(plain)
        append_event(plain, actor="claude", kind="NOTE", step="P", summary="plain folder")
        self.assertEqual(plain / ".coord" / "stream", stream_dir(plain))
        self.assertEqual(["P"], [event["step"] for event in read_events(plain)])


if __name__ == "__main__":
    unittest.main()
