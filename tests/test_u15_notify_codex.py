"""U15 S4: 전달기 계약 — 중복·루프·유출·폭주 차단."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from v7_harness.coord import notify as notify_module
from v7_harness.coord.notify import (
    MESSAGE_MAX_CHARS,
    MESSAGE_MAX_LINES,
    NotifyRefused,
    build_message,
    notify,
    read_cursor,
    resolve_thread,
    write_cursor,
)

KST = timezone(timedelta(hours=9))


class FakeRunner:
    def __init__(self, returncode: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.returncode = returncode

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        return SimpleNamespace(returncode=self.returncode, stdout="", stderr="")


class U15NotifyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        self.now = datetime(2026, 9, 20, 20, 40, tzinfo=KST)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _notify(self, **kwargs):
        params = {
            "thread": "01a0adeb-5356-7ee3-a271-09444aea9c92",
            "actor": "claude",
            "brief_text": "# brief\n- 사건 1\n",
            "headline": "R2FIX15 반영 완료, 전체 335 OK",
            "pending": ["bundle fec3bded 판정"],
            "now": self.now,
            "dry_run": False,
            "runner": FakeRunner(),
        }
        params.update(kwargs)
        return notify(self.project, **params), params["runner"]

    def test_message_is_data_not_instruction(self) -> None:
        message = build_message(actor="claude", brief_path=".coord/codex_brief.md", headline="요약", pending=[])
        self.assertTrue(message.startswith("[DATA] from=claude verdict_requested=no"))
        self.assertLessEqual(len(message.splitlines()), MESSAGE_MAX_LINES)
        self.assertLessEqual(len(message), MESSAGE_MAX_CHARS)

    def test_pending_marks_a_verdict_request(self) -> None:
        message = build_message(actor="antigravity", brief_path="p", headline="h", pending=["a", "b", "c"])
        self.assertIn("verdict_requested=yes", message)
        self.assertEqual(2, message.count("판정대기:"))

    def test_secret_shaped_message_is_refused(self) -> None:
        with self.assertRaises(NotifyRefused) as caught:
            build_message(actor="claude", brief_path="p", headline="token: ghp_abcdefghijklmnopqrstu", pending=[])
        self.assertEqual("SECRET_IN_MESSAGE", str(caught.exception))

    def test_dry_run_builds_the_command_without_sending(self) -> None:
        runner = FakeRunner()
        result = notify(
            self.project,
            thread="t1",
            actor="claude",
            brief_text="# brief\n",
            headline="요약",
            now=self.now,
            dry_run=True,
            runner=runner,
        )
        self.assertFalse(result.sent)
        self.assertEqual("DRY_RUN", result.reason)
        self.assertEqual([], runner.calls)
        self.assertEqual(("codex", "queue", "--thread", "t1", "--message", result.message), result.command)
        self.assertEqual("", read_cursor(self.project)["last_hash"])

    def test_send_records_a_cursor(self) -> None:
        result, runner = self._notify()
        self.assertTrue(result.sent)
        self.assertEqual(1, len(runner.calls))
        self.assertEqual("codex", runner.calls[0][0])
        cursor = read_cursor(self.project)
        self.assertNotEqual("", cursor["last_hash"])
        self.assertEqual(1, cursor["sent_today"])

    def test_same_brief_is_never_sent_twice(self) -> None:
        self._notify()
        again, runner = self._notify(now=self.now + timedelta(minutes=5))
        self.assertFalse(again.sent)
        self.assertEqual("NO_CHANGE", again.reason)
        self.assertEqual([], runner.calls)

    def test_rapid_state_changes_are_rate_limited(self) -> None:
        self._notify()
        soon, runner = self._notify(brief_text="# brief v2\n", now=self.now + timedelta(seconds=20))
        self.assertFalse(soon.sent)
        self.assertEqual("RATE_LIMIT", soon.reason)
        self.assertEqual([], runner.calls)

    @mock.patch.object(notify_module, "DAILY_LIMIT", 24)  # U290: opt-in only; the default is unlimited
    def test_daily_limit_stops_a_flood(self) -> None:
        write_cursor(
            self.project,
            {
                "last_hash": "old",
                "last_sent_at": (self.now - timedelta(hours=1)).isoformat(timespec="seconds"),
                "sent_today": 24,
                "day": f"{self.now:%Y-%m-%d}",
            },
        )
        result, runner = self._notify()
        self.assertFalse(result.sent)
        self.assertEqual("DAILY_LIMIT", result.reason)
        self.assertEqual([], runner.calls)

    def test_no_daily_limit_by_default(self) -> None:
        # U290 (윤겸스 2026-11-01 "모든 한도를 없애라"): a busy day never silences a Codex notice.
        self.assertIsNone(notify_module.DAILY_LIMIT)
        write_cursor(
            self.project,
            {
                "last_hash": "old",
                "last_sent_at": (self.now - timedelta(hours=1)).isoformat(timespec="seconds"),
                "sent_today": 500,
                "day": f"{self.now:%Y-%m-%d}",
            },
        )
        result, runner = self._notify()
        self.assertTrue(result.sent, result.reason)
        self.assertEqual(1, len(runner.calls))

    def test_queue_failure_is_reported_not_swallowed(self) -> None:
        with self.assertRaises(NotifyRefused) as caught:
            self._notify(runner=FakeRunner(returncode=1))
        self.assertTrue(str(caught.exception).startswith("QUEUE_FAILED:"))
        self.assertEqual("", read_cursor(self.project)["last_hash"])

    def test_missing_thread_is_refused(self) -> None:
        with self.assertRaises(NotifyRefused) as caught:
            self._notify(thread="  ")
        self.assertEqual("MISSING_THREAD", str(caught.exception))

    def test_verdict_requested_explicit_no(self) -> None:
        result, runner = self._notify(verdict_requested=False, pending=["task1 waiting"])
        self.assertFalse(result.sent)
        self.assertEqual("ACK_ONLY", result.reason)
        self.assertEqual((), result.command)
        self.assertEqual("", result.message)
        self.assertEqual([], runner.calls)
        self.assertEqual("", read_cursor(self.project)["last_hash"])

    def test_ack_only_does_not_need_a_thread_or_wake_codex(self) -> None:
        result, runner = self._notify(thread="", verdict_requested=False)
        self.assertEqual((False, "ACK_ONLY"), (result.sent, result.reason))
        self.assertEqual([], runner.calls)

    def test_notify_refused_when_codex_absent_in_plan(self) -> None:
        coord_dir = self.project / ".coord"
        coord_dir.mkdir(parents=True, exist_ok=True)
        (coord_dir / "PLAN.md").write_text("- 상태: codex: LIMITED_6_PERCENT\n", encoding="utf-8")
        with self.assertRaises(NotifyRefused) as caught:
            self._notify(pending=["task1 waiting"])
        self.assertEqual("CODEX_ABSENT", str(caught.exception))

    def test_actor_headline_prefix_antigravity(self) -> None:
        result, runner = self._notify(actor="antigravity", headline="새로운 진행 보고")
        self.assertTrue(result.sent)
        self.assertIn("[안티그래비티에서 온 대화] 새로운 진행 보고", runner.calls[0][5])



class U15ResolveThreadTests(unittest.TestCase):
    """스레드를 손으로 넘기면 남의 작업 창에 배달된다. 프로젝트 기준으로 고르는지 본다."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project = self.root / "260916_agentic-ai-env-diet"
        self.project.mkdir()
        self.sessions = self.root / "sessions"
        (self.sessions / "2026" / "09").mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _session(self, name: str, session_id: str, cwd: str, mtime: float) -> Path:
        path = self.sessions / "2026" / "09" / name
        path.write_text(
            json.dumps({"session_id": session_id, "cwd": cwd}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.utime(path, (mtime, mtime))
        return path

    def test_picks_the_newest_session_for_this_project(self) -> None:
        self._session("old.jsonl", "aaaaaaaa-1111-2222-3333-444444444444", str(self.project), 1_000)
        self._session("new.jsonl", "bbbbbbbb-1111-2222-3333-444444444444", str(self.project), 2_000)
        self.assertEqual(
            "bbbbbbbb-1111-2222-3333-444444444444",
            resolve_thread(self.project, sessions_dir=self.sessions),
        )

    def test_sessions_of_other_projects_are_skipped(self) -> None:
        other = self.root / "260718_agentic-ai-platform-optimization"
        other.mkdir()
        self._session("other.jsonl", "cccccccc-1111-2222-3333-444444444444", str(other), 3_000)
        self._session("mine.jsonl", "dddddddd-1111-2222-3333-444444444444", str(self.project), 2_000)
        self.assertEqual(
            "dddddddd-1111-2222-3333-444444444444",
            resolve_thread(self.project, sessions_dir=self.sessions),
        )

    def test_no_match_returns_empty_so_the_caller_refuses(self) -> None:
        other = self.root / "other-project"
        other.mkdir()
        self._session("other.jsonl", "eeeeeeee-1111-2222-3333-444444444444", str(other), 3_000)
        self.assertEqual("", resolve_thread(self.project, sessions_dir=self.sessions))
        with self.assertRaises(NotifyRefused):
            notify(self.project, thread="", actor="claude", brief_text="x", headline="y")

    def test_missing_sessions_dir_is_not_an_error(self) -> None:
        self.assertEqual("", resolve_thread(self.project, sessions_dir=self.root / "nope"))

if __name__ == "__main__":
    unittest.main()
