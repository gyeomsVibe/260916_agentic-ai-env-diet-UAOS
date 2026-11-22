"""U361: desk_delta fast scan — evt_* prefilter, lazy `git ls-files`, one `git status` per prepare+ack.

Receipt: every prompt hook of every tool runs `desk_delta.prepare_delta`; in a busy inbox it parsed each pilot
`evt_*.json` only to reject it from the session replay, always ran `git ls-files` even with no fresh file, and ran
`git status` twice (once in `absence_items`, again in `ack()`). Fixed acceptance written by the author (claude)
before the implementation; the behaviour each test pins is unchanged output, only the work done to produce it.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import desk_delta

# Fake clock (epoch seconds); the first look without a cursor covers NOW - 3600 .. NOW.
NOW = 1_800_000_000.0
# A busy inbox: 300 pilot run events is the order seen in real projects' inboxes.
EVENTS = 300


def _git(root: Path, *args: str) -> str:
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t", GIT_AUTHOR_DATE=f"@{int(NOW - 7200)} +0000",
               GIT_COMMITTER_DATE=f"@{int(NOW - 7200)} +0000")
    done = subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True, env=env)
    return done.stdout


def _write(path: Path, text: str, at: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.utime(path, (at, at))
    return path


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.inbox = self.root / ".coord" / "mailbox" / "inbox"
        self.inbox.mkdir(parents=True)
        desk_delta._PAYLOAD_CACHE.clear()
        self.addCleanup(desk_delta._PAYLOAD_CACHE.clear)

    def _patch(self, target: str, **kwargs) -> mock.MagicMock:
        patcher = mock.patch(target, **kwargs)
        started = patcher.start()
        self.addCleanup(patcher.stop)
        return started

    def _record_git(self) -> list[tuple[str, ...]]:
        calls: list[tuple[str, ...]] = []
        real = desk_delta._git

        def spy(root, *args):
            calls.append(tuple(args))
            return real(root, *args)

        self._patch("v7_harness.coord.desk_delta._git", side_effect=spy)
        return calls


class ReplayPrefilterTests(_Base):
    def _fill(self) -> tuple[Path, Path]:
        for i in range(EVENTS):
            body = {"message_id": f"evt_{i:04d}", "payload": {"actor": "antigravity", "message": f"run {i}"}}
            _write(self.inbox / f"evt_20261122T0000-antigravity-{i:04d}.json", json.dumps(body), NOW - 10)
        # Arrival order (mtime) is the reverse of name order, so the sort key is really (st_mtime_ns, name).
        late = _write(self.inbox / "relay_aaaa.json", json.dumps(
            {"message_id": "relay_aaaa", "payload": {"actor": "claude", "requested_target": "codex",
                                                     "message": "second"}}), NOW - 20)
        early = _write(self.inbox / "relay_zzzz.json", json.dumps(
            {"message_id": "relay_zzzz", "payload": {"actor": "claude", "requested_target": "codex",
                                                     "message": "first"}}), NOW - 30)
        self._patch("v7_harness.coord.desk_sync.desk_identity", return_value=("PROJECT_BOUND", {"thread": "desk"}))
        return early, late

    def test_replay_reads_no_evt_file_and_orders_relays(self) -> None:
        early, late = self._fill()
        evt_reads: list[str] = []
        real_read = Path.read_text

        def spy(self_path, *args, **kwargs):
            if self_path.name.startswith("evt_"):
                evt_reads.append(self_path.name)
            return real_read(self_path, *args, **kwargs)

        with mock.patch.object(Path, "read_text", autospec=True, side_effect=spy):
            replay = desk_delta._replay_letters(self.root, "codex", "desk")
        self.assertEqual(evt_reads, [], f"{len(evt_reads)} evt_* files were read")
        self.assertEqual([p.name for p in replay], [early.name, late.name])

        # The fresh run events still reach the delta as one collapsed, counted line.
        self._patch("v7_harness.coord.desk_sync.prepare_notice", return_value=("", lambda: None))
        self._patch("v7_harness.coord.desk_delta.absence_items", return_value=[])
        text, _ack = desk_delta.prepare_delta(self.root, "codex", "desk", now=NOW)
        self.assertIn(f"RESUME_PENDING {early.stem}", text)
        self.assertIn(f"{EVENTS} run event(s) from antigravity, newest", text)


class LazyLsFilesTests(_Base):
    def test_ls_files_only_when_a_file_is_fresh(self) -> None:
        tasks = self.root / ".coord" / "tasks"
        tracked = _write(tasks / "tracked.md", "old report\n", NOW - 7200)
        _git(self.root, "init", "-q")
        _git(self.root, "add", "--", ".coord/tasks/tracked.md")
        _git(self.root, "commit", "-q", "-m", "base")
        os.utime(tracked, (NOW - 7200, NOW - 7200))
        calls = self._record_git()
        since = NOW - 3600

        items = desk_delta.absence_items(self.root, since, "claude")
        self.assertEqual([c for c in calls if "ls-files" in c], [])
        self.assertEqual([i for i in items if i.startswith("file ")], [])

        # A fresh tracked file and a fresh untracked one: ls-files runs and only the untracked one is news.
        os.utime(tracked, (NOW - 10, NOW - 10))
        _write(tasks / "new.md", "new report\n", NOW - 10)
        calls.clear()
        items = desk_delta.absence_items(self.root, since, "claude")
        self.assertEqual(len([c for c in calls if "ls-files" in c]), 1)
        self.assertEqual([i for i in items if i.startswith("file ")], ["file .coord/tasks/new.md"])


class SingleStatusTests(_Base):
    def setUp(self) -> None:
        super().setUp()
        _write(self.root / "a.txt", "one\n", NOW - 7200)
        _git(self.root, "init", "-q")
        _git(self.root, "add", "--", "a.txt")
        _git(self.root, "commit", "-q", "-m", "base")
        _write(self.root / "a.txt", "two\n", NOW - 10)
        self.expected = [f"uncommitted {line.strip()}" for line in _git(
            self.root, "-c", "core.quotePath=false", "status", "--porcelain", "--untracked-files=no").splitlines()
            if line.strip()]
        self.assertEqual(self.expected, ["uncommitted M a.txt"])
        self._patch("v7_harness.coord.desk_sync.prepare_notice", return_value=("", lambda: None))

    def _cursor(self, session: str) -> dict:
        return json.loads(desk_delta.cursor_path(self.root, "claude", session).read_text(encoding="utf-8"))

    @staticmethod
    def _statuses(calls: list[tuple[str, ...]]) -> int:
        return len([c for c in calls if "status" in c])

    def test_one_status_call_for_prepare_and_ack(self) -> None:
        calls = self._record_git()
        text, ack = desk_delta.prepare_delta(self.root, "claude", "s1", now=NOW)
        self.assertIn("uncommitted M a.txt", text)
        ack()
        self.assertEqual(self._statuses(calls), 1, calls)
        self.assertEqual(self._cursor("s1")["uncommitted"], self.expected)

    def test_ack_falls_back_to_its_own_status_call(self) -> None:
        calls = self._record_git()
        with mock.patch.object(desk_delta, "absence_items", return_value=[]):
            text, ack = desk_delta.prepare_delta(self.root, "claude", "s2", now=NOW)
            self.assertEqual(self._statuses(calls), 0, calls)
            ack()
        self.assertNotIn("uncommitted", text)
        self.assertEqual(self._statuses(calls), 1, calls)
        self.assertEqual(self._cursor("s2")["uncommitted"], self.expected)


class ReadOnlyTests(_Base):
    def _snapshot(self) -> dict[str, bytes | None]:
        # `.git` is git's own cache (git status may refresh its index); the project tree is everything else.
        seen: dict[str, bytes | None] = {}
        for path in sorted(self.root.rglob("*")):
            rel = path.relative_to(self.root).as_posix()
            if rel == ".git" or rel.startswith(".git/"):
                continue
            seen[rel] = path.read_bytes() if path.is_file() else None
        return seen

    def test_prepare_without_ack_writes_nothing(self) -> None:
        _write(self.root / ".coord" / "PLAN.md", "| Card | Status | Owner | Note |\n| U1 | TODO | c | x |\n", NOW - 7200)
        _write(self.root / "a.txt", "one\n", NOW - 7200)
        _git(self.root, "init", "-q")
        _git(self.root, "add", "--", "a.txt", ".coord/PLAN.md")
        _git(self.root, "commit", "-q", "-m", "base")
        _write(self.root / "a.txt", "two\n", NOW - 10)
        _write(self.root / ".coord" / "tasks" / "fresh.md", "fresh\n", NOW - 10)
        for i in range(5):
            _write(self.inbox / f"evt_20261122T0000-codex-{i:04d}.json",
                   json.dumps({"payload": {"actor": "codex", "message": f"run {i}"}}), NOW - 10)
        _write(self.inbox / "relay_bbbb.json",
               json.dumps({"payload": {"actor": "codex", "requested_target": "claude", "message": "hi"}}), NOW - 10)
        # A real project's mailbox already has the skeleton `Mailbox()` creates (desk_sync opens it on every look);
        # the invariant is that prepare_delta itself adds or changes nothing on top of it.
        for sub in ("tmp", "claimed", "ack"):
            (self.root / ".coord" / "mailbox" / sub).mkdir(parents=True, exist_ok=True)
        _git(self.root, "status", "--porcelain")  # settle git's index before the snapshot
        before = self._snapshot()
        self.maxDiff = None
        self._patch("v7_harness.coord.desk_sync.desk_identity", return_value=("PROJECT_BOUND", {"thread": "s1"}))
        text, _ack = desk_delta.prepare_delta(self.root, "claude", "s1", now=NOW)
        self.assertIn("relay_bbbb", text)
        self.assertIn("5 run event(s) from codex", text)
        self.assertEqual(self._snapshot(), before)
        self.assertFalse(desk_delta.cursor_path(self.root, "claude", "s1").exists())


if __name__ == "__main__":
    unittest.main()
