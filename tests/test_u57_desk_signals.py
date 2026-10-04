"""U57: desk signals that stop the user from relaying, approving, or copy-pasting between sessions (2026-09-28).

A. A Codex heartbeat written for a prompt that Codex then refused with usage_limit_exceeded reads LIMITED.
B. `coord watch` wakes on a new letter for its tool at zero model tokens, and times out with exit 3.
C. `coord deliver` to Claude leaves the letter queued while an interactive session watches, instead of cold `claude -p`.
D. `coord presence --lease` writes the lease that a later ACTIVE heartbeat cannot overwrite.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from v7_harness.cli import main
from v7_harness.coord import presence
from v7_harness.coord.deliver import deliver
from v7_harness.coord.mailbox import Mailbox
from v7_harness.coord.watch import watch, watch_file, watcher_live


def _rollout(root: Path, completed_at: float, error: dict | None, name: str = "a") -> Path:
    day = datetime.fromtimestamp(completed_at)
    folder = root / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"rollout-{name}.jsonl"
    event = {"type": "event_msg", "payload": {"type": "task_complete", "completed_at": int(completed_at),
                                              "started_at": int(completed_at) - 5}}
    if error is not None:
        event["payload"]["error"] = error
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"type": "event_msg", "payload": {"type": "user_message"}}) + "\n")
        handle.write(json.dumps(event) + "\n")
    return path


def _refusal(reset: datetime) -> dict:
    clock = reset.strftime("%I:%M %p").lstrip("0")
    return {"message": f"You've hit your usage limit. ... or try again at {clock}.",
            "codex_error_info": "usage_limit_exceeded"}


class _Project(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord" / "mailbox").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        self.sessions = Path(self._tmp.name) / "codex_sessions"
        self.sessions.mkdir()
        self._env = patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(self.sessions)})
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()
        self._tmp.cleanup()


class TestCodexQuotaEvidence(_Project):
    def test_refused_prompt_reads_limited_until_reset(self):
        now = time.time()
        # the heartbeat outlives the reset so the last assertion sees ACTIVE, not an expired UNKNOWN
        presence.mark(self.project, "codex", "ACTIVE", now=now - 10, ttl_s=4 * 3600)
        reset = (datetime.fromtimestamp(now) + timedelta(hours=2)).replace(second=0, microsecond=0)
        _rollout(self.sessions, now - 5, _refusal(reset))
        state = presence.read(self.project, "codex", now=now)
        self.assertEqual("LIMITED", state["state"])
        self.assertEqual("usage_limit_exceeded", state["evidence"]["reason"])
        self.assertAlmostEqual(reset.timestamp(), state["expires_at"], delta=1)
        # after the reset the same heartbeat is ACTIVE again
        self.assertEqual("ACTIVE", presence.read(self.project, "codex", now=reset.timestamp() + 1)["state"])

    def test_reset_clock_before_refusal_rolls_to_next_day(self):
        now = time.time()
        presence.mark(self.project, "codex", "ACTIVE", now=now - 10)
        earlier = (datetime.fromtimestamp(now) - timedelta(hours=1)).replace(second=0, microsecond=0)
        _rollout(self.sessions, now - 5, _refusal(earlier))
        state = presence.read(self.project, "codex", now=now)
        self.assertEqual("LIMITED", state["state"])
        self.assertAlmostEqual((earlier + timedelta(days=1)).timestamp(), state["expires_at"], delta=3700)
        self.assertGreater(state["expires_at"], now)

    def test_heartbeat_newer_than_refusal_stays_active(self):
        now = time.time()
        reset = datetime.fromtimestamp(now) + timedelta(hours=2)
        _rollout(self.sessions, now - 600, _refusal(reset))
        presence.mark(self.project, "codex", "ACTIVE", now=now - 10)
        self.assertEqual("ACTIVE", presence.read(self.project, "codex", now=now)["state"])

    def test_successful_turn_after_refusal_stays_active(self):
        now = time.time()
        presence.mark(self.project, "codex", "ACTIVE", now=now - 100)
        _rollout(self.sessions, now - 90, _refusal(datetime.fromtimestamp(now) + timedelta(hours=2)), name="a")
        _rollout(self.sessions, now - 20, None, name="b")
        os.utime(next(self.sessions.rglob("rollout-b.jsonl")), (now, now))
        self.assertEqual("ACTIVE", presence.read(self.project, "codex", now=now)["state"])

    def test_missing_or_bad_logs_change_nothing(self):
        now = time.time()
        presence.mark(self.project, "codex", "ACTIVE", now=now - 10)
        self.assertEqual("ACTIVE", presence.read(self.project, "codex", now=now)["state"])
        folder = self.sessions / "2026" / "09" / "28"
        folder.mkdir(parents=True)
        (folder / "rollout-x.jsonl").write_bytes(b"\xff\xfe not json \"task_complete\"\n")
        self.assertEqual("ACTIVE", presence.read(self.project, "codex", now=now)["state"])

    def test_route_goes_to_claude_after_refusal(self):
        now = time.time()
        presence.mark(self.project, "codex", "ACTIVE", now=now - 10)
        presence.mark(self.project, "claude", "ACTIVE", now=now - 10)
        _rollout(self.sessions, now - 5, _refusal(datetime.fromtimestamp(now) + timedelta(hours=1)))
        self.assertEqual("claude", presence.conductor(presence.read_all(self.project, now=now))["conductor"])

    def test_other_tools_ignore_codex_logs(self):
        now = time.time()
        presence.mark(self.project, "claude", "ACTIVE", now=now - 10)
        _rollout(self.sessions, now - 5, _refusal(datetime.fromtimestamp(now) + timedelta(hours=1)))
        self.assertEqual("ACTIVE", presence.read(self.project, "claude", now=now)["state"])


class TestWatch(_Project):
    def _letter(self, message_id: str, target: str) -> None:
        Mailbox(self.project / ".coord" / "mailbox").publish(
            message_id, {"kind": "NOTE", "actor": "claude", "requested_target": target, "message": "x"})

    def test_returns_new_letter_for_target_and_ignores_old_and_others(self):
        self._letter("old_letter", "claude")
        ticks = {"n": 0}

        def sleep(_s):
            ticks["n"] += 1
            self.assertTrue(watcher_live(self.project, "claude"))
            if ticks["n"] == 1:
                self._letter("for_codex", "codex")
            elif ticks["n"] == 2:
                self._letter("for_claude", "claude")

        found = watch(self.project, ("claude",), timeout_s=60, interval_s=1, sleep=sleep)
        self.assertEqual("for_claude", found["id"])
        self.assertEqual("claude", found["requested_target"])
        self.assertFalse(watch_file(self.project, "claude").exists())

    def test_timeout_returns_none_and_clears_watch_file(self):
        clock = {"t": 1000.0}

        def sleep(s):
            clock["t"] += s

        self.assertIsNone(watch(self.project, ("claude",), timeout_s=5, interval_s=2,
                                clock=lambda: clock["t"], sleep=sleep))
        self.assertFalse(watch_file(self.project, "claude").exists())
        self.assertFalse(watcher_live(self.project, "claude"))

    def test_cli_timeout_exit_3_and_new_letter_exit_0(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["coord", "watch", "--project", str(self.project), "--target", "claude",
                         "--timeout", "0", "--interval", "0.01"])
        self.assertEqual(3, code)
        self.assertEqual("TIMEOUT", json.loads(out.getvalue())["reason"])

        def sleep(_s):
            self._letter("wake_me", "codex")

        out = io.StringIO()
        # U141-A rev 6: an untagged letter wakes only the legacy policy; the structured default is in test_u141a.
        with patch("v7_harness.coord.watch.time.sleep", sleep), redirect_stdout(out):
            code = main(["coord", "watch", "--project", str(self.project), "--target", "claude",
                         "--target", "codex", "--timeout", "30", "--interval", "0.01", "--policy", "legacy"])
        self.assertEqual(0, code)
        self.assertEqual("wake_me", json.loads(out.getvalue())["id"])

    def test_unknown_tool_rejected_before_writing(self):
        with self.assertRaises(ValueError):
            watch(self.project, ("nobody",), timeout_s=0)
        self.assertFalse((self.project / ".coord" / "presence").exists())

    def test_expired_watch_file_is_not_live(self):
        target = watch_file(self.project, "claude")
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps({"expires_at": time.time() - 1}), encoding="utf-8")
        self.assertFalse(watcher_live(self.project, "claude"))
        target.write_text("not json", encoding="utf-8")
        self.assertFalse(watcher_live(self.project, "claude"))


class _Runner:
    def __init__(self):
        self.calls = []

    def __call__(self, command, **_kw):
        self.calls.append(command)
        raise AssertionError("a cold session must not start while a watcher is live")


class TestDeliverQueuesForWatcher(_Project):
    def _live_watch(self) -> None:
        target = watch_file(self.project, "claude")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"tool": "claude", "token": "t", "expires_at": time.time() + 300}),
                          encoding="utf-8")

    def test_explicit_claude_target_is_queued(self):
        self._live_watch()
        runner = _Runner()
        with patch("v7_harness.coord.deliver.shutil.which", return_value="claude"):
            result = deliver(self.project, message="U57 queued", actor="codex", target="claude", runner=runner)
        self.assertEqual("QUEUED_INTERACTIVE", result.reason)
        self.assertEqual([], runner.calls)
        self.assertIn(result.message_id, Mailbox(self.project / ".coord" / "mailbox").list_inbox())

    def test_auto_route_to_claude_is_queued(self):
        self._live_watch()
        presence.mark(self.project, "codex", "LIMITED")
        presence.mark(self.project, "claude", "ACTIVE")
        runner = _Runner()
        result = deliver(self.project, message="U57 auto", actor="antigravity", runner=runner)
        self.assertEqual(("claude", "QUEUED_INTERACTIVE"), (result.target, result.reason))
        self.assertEqual([], runner.calls)

    def test_cli_reports_queued_as_ok(self):
        self._live_watch()
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["coord", "deliver", "--project", str(self.project), "--actor", "codex",
                         "--target", "claude", "--message", "U57 cli"])
        self.assertEqual(0, code)
        body = json.loads(out.getvalue())
        self.assertEqual((True, "QUEUED_INTERACTIVE"), (body["ok"], body["reason"]))


class TestPresenceLeaseFlag(_Project):
    def test_lease_survives_active_heartbeat(self):
        with redirect_stdout(io.StringIO()):
            code = main(["coord", "presence", "--project", str(self.project), "--tool", "codex",
                         "--state", "LIMITED", "--ttl", "600", "--lease"])
        self.assertEqual(0, code)
        presence.mark(self.project, "codex", "ACTIVE")
        self.assertEqual("LIMITED", presence.read(self.project, "codex")["state"])

    def test_without_flag_heartbeat_replaces(self):
        with redirect_stdout(io.StringIO()):
            main(["coord", "presence", "--project", str(self.project), "--tool", "codex",
                  "--state", "LIMITED", "--ttl", "600"])
        presence.mark(self.project, "codex", "ACTIVE")
        self.assertEqual("ACTIVE", presence.read(self.project, "codex")["state"])


if __name__ == "__main__":
    unittest.main()
