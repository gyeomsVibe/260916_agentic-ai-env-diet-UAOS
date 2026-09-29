"""U84: a linked worktree's `coord log` and pilot events land in the main checkout's stream (the desk).

Seen 2026-09-29: the acting conductor ran `coord log --project .` in `.claude/worktrees/<name>`. The event went to that
worktree's gitignored `.coord/stream`, while `coord deliver` from the same folder reached the desk (U59). 76 events
from 2026-09-20 to 09-29 were stranded there, so the desk's codex_brief (brief.py reads the stream) never showed the
acting work Codex must re-review. U59 moved presence and mail, U72-L the ledger; the stream is the same runtime state.
"""

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path

from v7_harness.cli import main
from v7_harness.coord.stream import append_event, archive_settled, read_events, stream_dir

REPO = Path(__file__).resolve().parents[1]


def samples_path(project: Path) -> Path:
    return stream_dir(project) / "metrics" / "samples.jsonl"


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

    def test_archive_from_a_worktree_reports_a_path_that_resolves(self):
        # U84-F1 (Codex REJECT of U84): the archive moved to the desk, then relative_to(worktree) raised after the
        # stream had already been rewritten.
        append_event(self.tree, actor="codex", kind="VERDICT", step="V", summary="settled",
                     evidence={"cmd": "unittest", "exit": 0}, now=datetime.now().astimezone() - timedelta(minutes=1))
        append_event(self.tree, actor="claude", kind="NOTE", step="L", summary="live")  # a minute later: stays live
        report = archive_settled(self.tree)
        self.assertEqual((1, 1), (report["archived"], report["kept"]))
        self.assertTrue((self.tree / report["archive"]).is_file())
        self.assertEqual(["L"], [event["step"] for event in read_events(self.main)])

    def test_parallel_events_from_both_checkouts_keep_every_sample(self):
        # U84-F1 (Codex REJECT of U84): samples from the desk and its worktrees now share one file, so they are
        # written under the stream lock. 6 processes x 8 events with the 10-minute spacing off must leave 48 rows.
        child = (
            "import sys\n"
            "from pathlib import Path\n"
            "from v7_harness.coord import metrics\n"
            "from v7_harness.coord.stream import append_event\n"
            "metrics.MIN_INTERVAL_S = -1  # sample every event\n"
            "for n in range(8):\n"
            "    append_event(Path(sys.argv[1]), actor='claude', kind='NOTE', step=f'{sys.argv[2]}-{n}', summary='p')\n"
        )
        procs = [subprocess.Popen([sys.executable, "-c", child, str(self.tree if i % 2 else self.main), f"p{i}"],
                                  cwd=REPO) for i in range(6)]
        self.assertEqual([0] * 6, [proc.wait(timeout=120) for proc in procs])
        self.assertEqual(48, len(read_events(self.main)))
        rows = samples_path(self.main).read_text(encoding="utf-8").splitlines()
        self.assertEqual(48, len(rows), "a concurrent sample append was lost or duplicated")
        self.assertEqual(48, len([json.loads(row) for row in rows]))

    def test_a_plain_project_keeps_its_own_stream(self):
        plain = Path(self._tmp.name) / "plain"
        _plan(plain)
        append_event(plain, actor="claude", kind="NOTE", step="P", summary="plain folder")
        self.assertEqual(plain / ".coord" / "stream", stream_dir(plain))
        self.assertEqual(["P"], [event["step"] for event in read_events(plain)])


if __name__ == "__main__":
    unittest.main()
