"""U164: a letter that hits Antigravity's daily cap waits in a backlog and is answered after the Seoul-day reset.

Receipt (2026-10-04 22:18, overnight unattended run; coord log 20261004T2218-claude-0001): the U157L commit gate needs
an answered Antigravity audit (U123), but the U120 auto-reply cap (DAILY_CAP=20) was spent. The letter was left
UNREAD "until a user turn in Antigravity" and nothing re-sent it after midnight, so all three tools waited on a user
who was asleep. 윤겸스 ordered (2026-10-04) that an unattended night never stalls on one blocked step.
Contract: .work/u164/contract_v2.md. A capped letter is parked once; any tool's ACTIVE heartbeat on a later day
dispatches the backlog inside the same cap, under a per-letter OS lock, with no paid polling.
v2 (Codex REWORK relay_c4abe46b): per-letter locks cannot hold a shared daily budget (two distinct letters at 19/20
ended at 21), so every paid call reserves its unit under one budget lock first (tests 10-12); an answer recorded
before a crash, a late re-park and malformed entries never cause a second answer or an endless retry (tests 13-15).
"""

from __future__ import annotations

import json
import multiprocessing
import os
import subprocess
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from v7_harness.coord import agy_dispatch, presence
from v7_harness.coord.deliver import deliver
from v7_harness.coord.mailbox import Mailbox
from v7_harness.coord.watch import watch_file

DAY1 = datetime(2026, 10, 4, 12, 0, tzinfo=agy_dispatch.SEOUL).timestamp()
DAY2 = DAY1 + 86400


def _envelope() -> bytes:
    return json.dumps({"status": "SUCCESS", "conversation_id": "conv-auto",
                       "usage": {"input_tokens": 25_000, "output_tokens": 900},
                       "response": "PASS: audited."}).encode("utf-8")


def _child_drain(project: str, calls: str, start, done) -> None:
    """A real separate process: waits for the start signal, then drains with a runner that records each agy call."""
    def runner(argv, **kwargs):
        if Path(argv[0]).stem != "agy":
            raise AssertionError(argv[0])
        Path(calls, f"{os.getpid()}-{time.time_ns()}").write_text("x", encoding="utf-8")
        time.sleep(0.5)  # hold the letter long enough for the other process to contend
        return SimpleNamespace(returncode=0, stdout=_envelope(), stderr=b"")

    with mock.patch("v7_harness.coord.deliver.shutil.which", side_effect=lambda name: name):
        start.wait(10)
        rows = agy_dispatch.drain_backlog(Path(project), now=DAY2, runner=runner)
    done.put([row.get("state") for row in rows])


def _child_dispatch(project: str, calls: str, message_id: str, start, done) -> None:
    """A real separate process on the normal route: one distinct letter dispatched on DAY2 (Codex probe, REWORK
    relay_c4abe46b: two distinct letters at 19/20 ended at 21)."""
    def runner(argv, **kwargs):
        if Path(argv[0]).stem == "agy":
            Path(calls, f"{os.getpid()}-{time.time_ns()}").write_text("x", encoding="utf-8")
            time.sleep(0.5)  # the paid call is slow; the other process decides its budget meanwhile
            return SimpleNamespace(returncode=0, stdout=_envelope(), stderr=b"")
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    with mock.patch("v7_harness.coord.deliver.shutil.which", side_effect=lambda name: name):
        start.wait(10)
        row = agy_dispatch.dispatch(Path(project), message_id=message_id, actor="claude",
                                    message=f"ACTIONABLE_DELTA audit {message_id}", runner=runner, now=DAY2)
    done.put(row.get("state"))


def _child_crash(project: str, message_id: str) -> None:
    """A real process that dies inside the paid call, after its budget was decided."""
    def runner(argv, **kwargs):
        os._exit(3)

    with mock.patch("v7_harness.coord.deliver.shutil.which", side_effect=lambda name: name):
        agy_dispatch.dispatch(Path(project), message_id=message_id, actor="claude", message="ACTIONABLE_DELTA crash",
                              runner=runner, now=DAY2)


class Base(unittest.TestCase):
    def setUp(self):
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
        beat = watch_file(self.project, "claude")
        beat.parent.mkdir(parents=True, exist_ok=True)
        beat.write_text(json.dumps({"tool": "claude", "token": "t", "pid": 1, "expires_at": time.time() + 3600,
                                    "wakes_session": True}), encoding="utf-8")
        self.calls = []
        self.fail_runs = False

    def tearDown(self):
        self._which.stop()
        self._env.stop()
        self._tmp.cleanup()

    def runner(self, argv, **kwargs):
        self.calls.append(list(argv))
        if Path(argv[0]).stem != "agy":
            raise AssertionError(f"only agy may run here: {argv[0]}")
        if self.fail_runs:
            return SimpleNamespace(returncode=1, stdout=b"", stderr=b"boom")
        return SimpleNamespace(returncode=0, stdout=_envelope(), stderr=b"")

    @property
    def ledger(self) -> Path:
        return self.project / ".coord" / "mailbox" / "delivery" / "agy_auto.jsonl"

    @property
    def backlog(self) -> Path:
        return self.project / ".coord" / "mailbox" / "delivery" / "agy_backlog"

    def fill_cap(self, ts: float, count: int = agy_dispatch.DAILY_CAP) -> None:
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        with open(self.ledger, "a", encoding="utf-8") as handle:
            for _ in range(count):
                handle.write(json.dumps({"ts": ts, "state": "ANSWERED"}) + "\n")

    def park(self, message: str, *, card: str = "") -> dict:
        return agy_dispatch.dispatch(self.project, message_id="relay_" + str(abs(hash(message)))[:12], actor="claude",
                                     message=message, runner=self.runner, now=DAY1, card=card)

    def parked(self) -> list:
        return sorted(p.name for p in self.backlog.glob("*.json")) if self.backlog.is_dir() else []

    def replies(self) -> list:
        box = Mailbox(self.project / ".coord" / "mailbox")
        found = []
        for mid in box.list_inbox():
            letter = box.read_message(mid)
            if letter and letter["payload"].get("actor") == "antigravity":
                found.append(letter["payload"]["message"])
        return found


class Backlog(Base):
    def test_1_a_capped_letter_is_parked_once_without_an_agy_call(self):
        self.fill_cap(DAY1)
        row = self.park("ACTIONABLE_DELTA audit request U157L", card="U157L")
        self.assertEqual("CAP_REACHED_BACKLOG", row["state"])
        self.assertEqual([], self.calls)
        files = self.parked()
        self.assertEqual(1, len(files))
        data = json.loads((self.backlog / files[0]).read_text(encoding="utf-8"))
        self.assertEqual(("claude", "U157L"), (data["actor"], data["card"]))
        self.assertIn("audit request U157L", data["message"])

    def test_1b_the_real_deliver_route_parks_and_says_so(self):
        self.fill_cap(time.time())
        result = deliver(self.project, message="ACTIONABLE_DELTA verdict_requested=yes audit X", actor="claude",
                         target="antigravity", runner=self.runner)
        self.assertIn("CAP_REACHED_BACKLOG", result.output)
        self.assertEqual(1, len(self.parked()))

    def test_2_a_drain_on_the_same_day_waits(self):
        self.fill_cap(DAY1)
        self.park("ACTIONABLE_DELTA audit A")
        self.assertEqual([], agy_dispatch.drain_backlog(self.project, now=DAY1 + 3600, runner=self.runner))
        self.assertEqual([], self.calls)
        self.assertEqual(1, len(self.parked()))

    def test_3_the_next_seoul_day_answers_and_mails_the_sender(self):
        self.fill_cap(DAY1)
        self.park("ACTIONABLE_DELTA audit B")
        rows = agy_dispatch.drain_backlog(self.project, now=DAY2, runner=self.runner)
        self.assertEqual(["ANSWERED"], [row["state"] for row in rows])
        self.assertEqual(1, len(self.calls))
        self.assertEqual([], self.parked())
        self.assertTrue(any("PASS: audited." in text for text in self.replies()))
        answered = [json.loads(line) for line in self.ledger.read_text(encoding="utf-8").splitlines()
                    if json.loads(line).get("state") == "ANSWERED" and json.loads(line).get("message_id")]
        self.assertEqual(1, len(answered))

    def test_4_the_drain_stays_inside_the_new_day_cap(self):
        self.fill_cap(DAY1)
        for name in ("C1", "C2", "C3"):
            self.park(f"ACTIONABLE_DELTA audit {name}")
        self.fill_cap(DAY2, agy_dispatch.DAILY_CAP - 1)
        rows = agy_dispatch.drain_backlog(self.project, now=DAY2, runner=self.runner)
        self.assertEqual(1, len([row for row in rows if row["state"] == "ANSWERED"]))
        self.assertEqual(1, len(self.calls))
        self.assertEqual(2, len(self.parked()))

    def test_5_a_failing_letter_is_retried_then_parked_as_failed(self):
        self.fill_cap(DAY1)
        self.park("ACTIONABLE_DELTA audit D")
        self.fail_runs = True
        for _ in range(3):
            agy_dispatch.drain_backlog(self.project, now=DAY2, runner=self.runner)
        self.assertEqual([], self.parked())
        self.assertEqual(1, len(list(self.backlog.glob("*.failed"))))
        before = len(self.calls)
        agy_dispatch.drain_backlog(self.project, now=DAY2, runner=self.runner)
        self.assertEqual(before, len(self.calls))

    def test_6_the_same_letter_parked_twice_is_one_entry(self):
        self.fill_cap(DAY1)
        self.park("ACTIONABLE_DELTA audit E")
        self.park("ACTIONABLE_DELTA audit E")
        self.assertEqual(1, len(self.parked()))

    def test_8_an_active_heartbeat_on_the_new_day_drains(self):
        self.fill_cap(DAY1)
        self.park("ACTIONABLE_DELTA audit F")
        presence.mark(self.project, "codex", "ACTIVE", dispatch=True, runner=self.runner, now=DAY2)
        self.assertEqual(1, len(self.calls))
        self.assertEqual([], self.parked())

    def test_9_a_heartbeat_with_an_empty_backlog_starts_nothing(self):
        with mock.patch("v7_harness.coord.agy_dispatch.drain_backlog") as drain, \
                mock.patch("subprocess.Popen") as popen:
            presence.mark(self.project, "codex", "ACTIVE", dispatch=True, now=DAY2)
        drain.assert_not_called()
        popen.assert_not_called()


class Parallel(Base):
    def test_7_two_real_processes_answer_one_parked_letter_once(self):
        self.fill_cap(DAY1)
        self.park("ACTIONABLE_DELTA audit G")
        calls = Path(self._tmp.name) / "calls"
        calls.mkdir()
        ctx = multiprocessing.get_context("spawn")
        start, done = ctx.Event(), ctx.Queue()
        processes = [ctx.Process(target=_child_drain, args=(str(self.project), str(calls), start, done))
                     for _ in range(2)]
        for process in processes:
            process.start()
        start.set()
        for process in processes:
            process.join(60)
            self.assertEqual(0, process.exitcode)
        states = [done.get(timeout=5) for _ in processes]
        self.assertEqual(1, len(list(calls.iterdir())), states)
        self.assertEqual([], self.parked())

    def test_10_two_real_processes_with_distinct_letters_share_one_daily_budget(self):
        self.fill_cap(DAY2, agy_dispatch.DAILY_CAP - 1)
        calls = Path(self._tmp.name) / "calls"
        calls.mkdir()
        ctx = multiprocessing.get_context("spawn")
        start, done = ctx.Event(), ctx.Queue()
        processes = [ctx.Process(target=_child_dispatch, args=(str(self.project), str(calls), f"relay_{n}aa", start,
                                                               done)) for n in (1, 2)]
        for process in processes:
            process.start()
        start.set()
        for process in processes:
            process.join(60)
            self.assertEqual(0, process.exitcode)
        states = sorted(done.get(timeout=5) for _ in processes)
        self.assertEqual(["ANSWERED", "CAP_REACHED_BACKLOG"], states)
        self.assertEqual(1, len(list(calls.iterdir())), states)
        self.assertEqual(agy_dispatch.DAILY_CAP, agy_dispatch._today_count(self.project, DAY2))
        self.assertEqual(1, len(self.parked()))

    def test_12_a_process_that_dies_inside_the_paid_call_still_spends_its_budget(self):
        self.fill_cap(DAY2, agy_dispatch.DAILY_CAP - 1)
        process = multiprocessing.get_context("spawn").Process(target=_child_crash,
                                                                 args=(str(self.project), "relay_crash1"))
        process.start()
        process.join(60)
        self.assertEqual(3, process.exitcode)
        self.assertEqual(agy_dispatch.DAILY_CAP, agy_dispatch._today_count(self.project, DAY2))
        row = agy_dispatch.dispatch(self.project, message_id="relay_after1", actor="claude",
                                    message="ACTIONABLE_DELTA after", runner=self.runner, now=DAY2)
        self.assertEqual("CAP_REACHED_BACKLOG", row["state"])
        self.assertEqual([], self.calls)


class Recovery(Base):
    def parked_id(self) -> str:
        return self.parked()[0][:-len(".json")]

    def test_11_a_runner_exception_is_a_failure_that_spends_the_budget(self):
        self.fill_cap(DAY2, agy_dispatch.DAILY_CAP - 1)

        def broken(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, 1)

        row = agy_dispatch.dispatch(self.project, message_id="relay_slow1", actor="claude",
                                    message="ACTIONABLE_DELTA slow", runner=broken, now=DAY2)
        self.assertEqual("FAILED", row["state"])
        self.assertEqual(agy_dispatch.DAILY_CAP, agy_dispatch._today_count(self.project, DAY2))

    def test_13_an_answer_recorded_before_a_crash_is_not_answered_again(self):
        self.fill_cap(DAY1)
        self.park("ACTIONABLE_DELTA audit H")
        message_id = self.parked_id()
        with open(self.ledger, "a", encoding="utf-8") as handle:  # the answer landed, the unlink never ran
            handle.write(json.dumps({"ts": DAY2, "message_id": message_id, "state": "ANSWERED",
                                     "reply_id": "relay_0123abcd"}) + "\n")
        rows = agy_dispatch.drain_backlog(self.project, now=DAY2 + 60, runner=self.runner)
        self.assertEqual([], self.calls, rows)
        self.assertEqual([], self.parked())

    def test_14_a_late_repark_of_an_answered_letter_is_never_answered_again(self):
        self.fill_cap(DAY1)
        self.park("ACTIONABLE_DELTA audit J")
        message_id = self.parked_id()
        agy_dispatch.drain_backlog(self.project, now=DAY2, runner=self.runner)
        self.assertEqual(1, len(self.calls))
        self.fill_cap(DAY2)
        agy_dispatch.dispatch(self.project, message_id=message_id, actor="claude", message="ACTIONABLE_DELTA audit J",
                              runner=self.runner, now=DAY2 + 60)
        agy_dispatch.drain_backlog(self.project, now=DAY2 + 86400, runner=self.runner)
        self.assertEqual(1, len(self.calls))
        self.assertEqual([], self.parked())

    def test_15_malformed_backlog_entries_are_set_aside_once(self):
        self.backlog.mkdir(parents=True)
        (self.backlog / "relay_bad1.json").write_text("{not json", encoding="utf-8")
        (self.backlog / "relay_bad2.json").write_text("{}", encoding="utf-8")
        (self.backlog / "relay_bad3.json").write_text("[1, 2]", encoding="utf-8")
        agy_dispatch.drain_backlog(self.project, now=DAY2, runner=self.runner)
        self.assertEqual([], self.calls)
        self.assertEqual([], self.parked())
        self.assertEqual(3, len(list(self.backlog.glob("*.failed"))))
        self.assertFalse(agy_dispatch.backlog_ready(self.project, DAY2))


if __name__ == "__main__":
    unittest.main()
