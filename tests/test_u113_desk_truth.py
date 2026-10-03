"""U113: the desk tells the truth about who can take a letter now, and no letter waits in a LIMITED tool's thread.

Receipts (2026-10-01):
- Codex was LIMITED (usage limit until 10-04 02:35), yet `coord deliver --target codex` ran `codex queue` for every
  letter; 7 relays piled up in Codex's thread, each one a paid Codex turn (~140k context) when it returns. A returning
  tool already sees the inbox through its hooks (desk delta, U103), so a LIMITED or ABSENT target gets the mailbox only.
- The desk said `antigravity=UNKNOWN` while Antigravity was open and had answered three hours earlier. An expired
  heartbeat is not "unknown": the desk now names it `IDLE(<age>)`; UNKNOWN stays for a tool never seen. Routing does
  not change: an idle tool still does not conduct (fail closed, U45).
Fixed acceptance written by the judge (claude) first.
"""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import presence
from v7_harness.coord.deliver import deliver
from v7_harness.coord.hook_context import agy_line, brief_line


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, command, **_kw):
        self.calls.append(command)
        raise OSError("codex not installed here")


class _Isolated(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        self.sessions = Path(self._tmp.name) / "codex-sessions"  # never the PC's real Codex logs
        self.sessions.mkdir()
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(self.sessions)})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()


class NoLetterWaitsInALimitedThread(_Isolated):
    def test_limited_or_absent_codex_gets_the_mailbox_only(self):
        for n, state in enumerate(("LIMITED", "ABSENT")):
            presence.mark(self.project, "codex", state)
            runner = _Recorder()
            with mock.patch("v7_harness.coord.deliver.shutil.which", return_value="codex"):
                result = deliver(self.project, message=f"U113 {state}", actor="claude", target="codex",
                                 runner=runner, thread="t1")
            # U134-C: still no dispatch while LIMITED/ABSENT, but the letter is queued for the next ACTIVE turn.
            self.assertEqual(("codex", "QUEUED_UNTIL_ACTIVE"), (result.target, result.reason), state)
            self.assertEqual([], runner.calls, state)
            self.assertTrue((self.project / ".coord" / "mailbox" / "inbox" / f"{result.message_id}.json").is_file())

    def test_active_codex_is_still_dispatched(self):
        presence.mark(self.project, "codex", "ACTIVE")
        runner = _Recorder()
        thread_id = "0199cccc-0000-7000-8000-000000000003"
        day = self.sessions / "2026" / "10" / "03"
        day.mkdir(parents=True, exist_ok=True)
        path = day / f"rollout-2026-10-03T06-00-00-{thread_id}.jsonl"
        path.write_text(json.dumps({"type": "session_meta", "payload": {"id": thread_id, "session_id": thread_id, "cwd": str(self.project)}}) + "\n", encoding="utf-8")
        with mock.patch("v7_harness.coord.deliver.shutil.which", return_value="codex"):
            deliver(self.project, message="U113 active", actor="claude", target="codex", runner=runner, thread=thread_id)
        self.assertEqual(1, len(runner.calls))
        self.assertIn("queue", runner.calls[0])


class DeskNamesIdleTools(_Isolated):
    def _desk(self):
        return {tool: presence.read(self.project, tool) for tool in presence.SUCCESSION}

    def test_expired_heartbeat_reads_idle_with_its_age_and_never_seen_reads_unknown(self):
        presence.mark(self.project, "antigravity", "ACTIVE", ttl_s=3600, now=time.time() - 3 * 3600 - 60)
        presence.mark(self.project, "claude", "ACTIVE")
        line = brief_line(self.project, self._desk())
        self.assertIn("antigravity=IDLE(3h)", line)
        self.assertIn("claude=ACTIVE", line)
        self.assertIn("codex=UNKNOWN", line)

    def test_antigravity_hook_line_uses_the_same_labels(self):
        presence.mark(self.project, "codex", "ACTIVE", ttl_s=60, now=time.time() - 30 * 60)
        line = agy_line(self.project, self._desk(), "{}")
        self.assertIn("codex=IDLE(30m)", line)  # the age counts from the last heartbeat, not from its expiry

    def test_desk_label_words(self):
        now = time.time()
        self.assertEqual("ACTIVE", presence.desk_label({"state": "ACTIVE"}, now))
        self.assertEqual("LIMITED", presence.desk_label({"state": "LIMITED", "observed_at": None}, now))
        self.assertEqual("UNKNOWN", presence.desk_label({"state": "UNKNOWN", "observed_at": None}, now))
        presence.mark(self.project, "claude", "ACTIVE", ttl_s=60, now=now - 125 * 60)
        self.assertEqual("IDLE(2h)", presence.desk_label(presence.read(self.project, "claude", now=now), now))
        presence.mark(self.project, "claude", "ACTIVE", ttl_s=60, now=now - 5 * 60)
        self.assertEqual("IDLE(5m)", presence.desk_label(presence.read(self.project, "claude", now=now), now))

    def test_idle_still_does_not_conduct(self):
        presence.mark(self.project, "codex", "ACTIVE", ttl_s=60, now=time.time() - 7200)
        presence.mark(self.project, "claude", "ACTIVE")
        self.assertEqual("UNKNOWN", presence.conductor(self._desk())["conductor"])


class HarnessOnlyWorkersWatchTheStage(unittest.TestCase):
    """U113-D a001 was blocked as EXTERNAL_WRITE for `~/.codex/config.toml`: the running Codex app rewrote its own
    config while the local model answered (U106-A2-agy: the Claude app's settings.json). A local or apply worker never
    touches the file system (the harness writes the stage), so home and temp watches catch only other apps there.
    A worker with tools (agy, claude, lane, cascade with escalation) keeps every watch."""

    def test_local_and_apply_watch_only_the_stage(self):
        from v7_harness.cli import mandatory_watch_roots
        with tempfile.TemporaryDirectory() as d:
            work, source = Path(d) / ".coord", Path(d) / "src"
            for worker in ("local", "apply"):
                self.assertEqual([(work / "stage").resolve()], mandatory_watch_roots(work, source, worker), worker)
            for worker in ("agy", "claude", "lane", "cascade"):
                self.assertIn(Path.home().resolve(), mandatory_watch_roots(work, source, worker), worker)
            self.assertIn(Path.home().resolve(), mandatory_watch_roots(work, source))  # default stays strict


if __name__ == "__main__":
    unittest.main()
