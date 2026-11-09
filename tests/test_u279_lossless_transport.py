"""U279 fixed acceptance: the topic-window transport (PR #252 coalescing) is lossless.

Codex's open gate on U279: coalescing may skip a paid turn, never a letter. Three properties are proven here:
(a) every coalesced NOTICE / ACK_ONLY letter stays durable in the mailbox and is retrievable and ackable by its id;
(b) an ACTIONABLE letter or a verdict request always reaches its receiver and is never merged into a neighbour,
    even when its text quotes an earlier ACK_ONLY status (Codex judge REVISE receipt in `_declines_turn`);
(c) real parallel senders (8 spawn processes x 25 letters, one topic) lose zero letters on Windows.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from v7_harness.coord import presence
from v7_harness.coord import watch as W
from v7_harness.coord.deliver import DeliverResult, _project_mailbox, _wants_wake, deliver
from v7_harness.coord.windows import record_window

TOPIC_THREAD = "0199dddd-0000-7000-8000-000000000279"
SUBCARDS = ("U279", "U279-R1", "PR252-U279", "U279_VERDICT")
PROCS, PER_PROC, ACTIONABLE_EVERY = 8, 25, 5  # 200 letters; every 5th is ACTIONABLE (40 paid dispatches)


def _register_rollout(sessions: Path, project: Path, thread_id: str) -> None:
    day = sessions / "2026" / "11" / "02"
    day.mkdir(parents=True, exist_ok=True)
    meta = {"type": "session_meta", "payload": {"id": thread_id, "session_id": thread_id, "cwd": str(project)}}
    (day / f"rollout-2026-11-02T00-00-00-{thread_id}.jsonl").write_text(json.dumps(meta) + "\n", encoding="utf-8")


class _MarkerRunner:
    """Fake `codex queue`: one marker file per call (concurrent appends to one file lose lines on Windows)."""

    def __init__(self, marker_dir: str):
        self.marker_dir = marker_dir

    def __call__(self, argv, **_kwargs):
        marker = Path(self.marker_dir) / f"{os.getpid()}_{uuid.uuid4().hex}.json"
        marker.write_text(json.dumps(list(argv)), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout=json.dumps({"result": "ok"}), stderr="")


def _letter(proc: int, seq: int) -> tuple[str, dict]:
    card = SUBCARDS[(proc + seq) % len(SUBCARDS)]
    if seq % ACTIONABLE_EVERY == 0:
        return (f"ACTIONABLE_DELTA p{proc} s{seq}: {card} slice ready",
                {"card": card, "wake_class": "ACTIONABLE", "delta": f"p{proc} s{seq} slice ready"})
    return (f"[agy-auto] p{proc} s{seq} {card} noted - ACK_ONLY (verdict_requested=no)",
            {"card": card, "wake_class": "NOTICE"})


def _sender(project: str, sessions: str, marker_dir: str, proc: int, start, results) -> None:
    os.environ[presence.CODEX_SESSIONS_ENV] = sessions
    rows = []
    try:
        with mock.patch("v7_harness.coord.deliver.shutil.which", side_effect=lambda name: name):
            start.wait(60)
            runner = _MarkerRunner(marker_dir)
            for seq in range(PER_PROC):
                message, fields = _letter(proc, seq)
                res = deliver(Path(project), message=message, actor="antigravity", target="codex",
                              runner=runner, **fields)
                rows.append((message, res.message_id, res.reason, ""))
    except Exception as exc:  # noqa: BLE001 - the parent asserts on the error text
        rows.append(("", "", "", repr(exc)))
    results.put(rows)


class LosslessBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        self.sessions = Path(self._tmp.name) / "codex-sessions"
        self.sessions.mkdir()
        self.markers = Path(self._tmp.name) / "markers"
        self.markers.mkdir()
        env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(self.sessions)})
        env.start()
        self.addCleanup(env.stop)
        which = mock.patch("v7_harness.coord.deliver.shutil.which", side_effect=lambda name: name)
        which.start()
        self.addCleanup(which.stop)
        for tool in ("codex", "claude", "antigravity"):
            presence.mark(self.project, tool, "ACTIVE")
        _register_rollout(self.sessions, self.project, TOPIC_THREAD)
        record_window(self.project, "U279", "codex", TOPIC_THREAD, now=100.0)
        self.box = _project_mailbox(self.project)
        self.runner = _MarkerRunner(str(self.markers))

    def calls(self) -> list[list[str]]:
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(self.markers.glob("*.json"))]

    def stored(self, message_id: str) -> dict:
        for folder in (self.box.inbox_dir, self.box.ack_dir):
            path = folder / f"{message_id}.json"
            if path.is_file():
                return json.loads(path.read_text(encoding="utf-8"))["payload"]
        self.fail(f"LETTER_LOST: {message_id} is in neither inbox nor ack")


class NoticesStayDurable(LosslessBase):
    def test_a_every_coalesced_notice_is_kept_and_ackable_by_id(self):
        sent = {}
        for i in range(30):
            card = SUBCARDS[i % len(SUBCARDS)]
            message = f"[agy-auto] re relay_req_{i}: {card} noted - ACK_ONLY (verdict_requested=no)"
            res = deliver(self.project, message=message, actor="antigravity", target="codex", card=card,
                          runner=self.runner, wake_class="NOTICE")
            self.assertEqual("QUEUED_NOTICE", res.reason)
            self.assertFalse(res.delivered)
            sent[res.message_id] = message
        ack_only = deliver(self.project, message="ACK_ONLY U279 status seen", actor="codex", target="claude",
                           card="U279-R1")
        self.assertEqual("QUEUED_ACK_ONLY", ack_only.reason)
        sent[ack_only.message_id] = "ACK_ONLY U279 status seen"

        self.assertEqual(31, len(sent))  # distinct letters never share an id, so none overwrites another
        self.assertEqual([], self.calls())  # coalescing skipped every paid turn
        self.assertTrue(set(sent) <= set(self.box.list_inbox()))
        for message_id, message in sent.items():
            self.assertEqual(message, self.stored(message_id)["message"])
            claim = self.box.claim(message_id, "u279-judge")
            self.assertIsNotNone(claim, message_id)
            self.assertTrue(self.box.ack(claim).is_file())
            self.assertTrue(self.box.has_message(message_id))
        self.assertFalse(set(sent) & set(self.box.list_inbox()))

    def test_a_resending_a_notice_is_idempotent_not_a_second_letter(self):
        first = deliver(self.project, message="[agy-auto] U279 noted - ACK_ONLY", actor="antigravity",
                        target="codex", card="U279", wake_class="NOTICE")
        again = deliver(self.project, message="[agy-auto] U279 noted - ACK_ONLY", actor="antigravity",
                        target="codex", card="U279", wake_class="NOTICE")
        self.assertEqual(first.message_id, again.message_id)
        self.assertEqual([first.message_id], self.box.list_inbox())


class ActionableNeverMerged(LosslessBase):
    def test_b_wake_rule_explicit_fields_win_over_quoted_ack_text(self):
        quoted = "ACTIONABLE_DELTA verdict_requested=yes: re-judge U279; previous status ACK_ONLY"
        self.assertTrue(_wants_wake("U279 slice ready", wake_class="ACTIONABLE"))
        self.assertTrue(_wants_wake("please judge U279", verdict_requested=True))
        self.assertTrue(_wants_wake(quoted, verdict_requested=True))
        self.assertTrue(_wants_wake(quoted, wake_class="ACTIONABLE"))
        self.assertTrue(_wants_wake("U279 verdict", verdict="PASS"))
        self.assertFalse(_wants_wake(quoted, wake_class="NOTICE"))
        self.assertFalse(_wants_wake(quoted, verdict_requested=False))

    def test_b_each_actionable_in_a_notice_burst_dispatches_once(self):
        actionable = []
        for round_ in range(3):
            for i in range(10):
                deliver(self.project, message=f"[agy-auto] r{round_} n{i} U279 noted - ACK_ONLY",
                        actor="antigravity", target="codex", card=SUBCARDS[i % 4], wake_class="NOTICE")
            res = deliver(self.project, message=f"ACTIONABLE_DELTA r{round_}: U279 slice {round_} ready",
                          actor="claude", target="codex", card=SUBCARDS[round_], runner=self.runner,
                          wake_class="ACTIONABLE", delta=f"slice {round_} ready")
            self.assertEqual("DISPATCHED", res.reason)
            actionable.append(res)
        verdict = deliver(self.project, actor="claude", target="codex", card="U279_VERDICT", runner=self.runner,
                          message="ACTIONABLE_DELTA verdict_requested=yes: re-judge U279; previous status ACK_ONLY",
                          verdict_requested=True)
        self.assertEqual("DISPATCHED", verdict.reason)
        actionable.append(verdict)

        calls = self.calls()
        self.assertEqual(len(actionable), len(calls))  # one paid turn per ACTIONABLE, zero per NOTICE
        sent_text = "\n".join(argv[argv.index("--message") + 1] for argv in calls)
        for res in actionable:
            self.assertIn(f"id={res.message_id}", sent_text)  # never folded into another letter's turn
            self.assertEqual("ACTIONABLE", W.classify(self.stored(res.message_id))[0])
            self.assertTrue((self.box.root / "delivery" / "accepted" / f"{res.message_id}.json").is_file())
        for argv in calls:
            self.assertEqual(TOPIC_THREAD, argv[argv.index("--thread") + 1])  # all coalesced into the topic window
        self.assertEqual(30 + len(actionable), len(self.box.list_inbox()))

    def test_b_a_verdict_request_quoting_ack_only_still_reaches_claude(self):
        sent = []

        def fake_claude(message, *args, **kwargs):
            sent.append(message)
            return DeliverResult(True, "claude", "SENT", (), "")

        message = "ACTIONABLE_DELTA verdict_requested=yes: re-judge U279; previous status ACK_ONLY"
        with mock.patch("v7_harness.coord.deliver._deliver_to_claude", side_effect=fake_claude):
            res = deliver(self.project, message=message, actor="codex", target="claude", verdict_requested=True)
        self.assertNotIn(res.reason, ("QUEUED_ACK_ONLY", "QUEUED_NOTICE"))
        self.assertEqual(1, len(sent))
        self.assertIn(message, sent[0])
        self.assertEqual("ACTIONABLE", W.classify(self.stored(res.message_id))[0])


class ParallelSendersLoseNothing(LosslessBase):
    def test_c_8_processes_x_25_letters_same_topic_lose_zero(self):
        ctx = multiprocessing.get_context("spawn")
        start, results = ctx.Barrier(PROCS), ctx.Queue()
        children = [ctx.Process(target=_sender, args=(str(self.project), str(self.sessions), str(self.markers),
                                                      proc, start, results)) for proc in range(PROCS)]
        for child in children:
            child.start()
        rows = [row for _ in children for row in results.get(timeout=300)]
        for child in children:
            child.join(60)
            self.assertEqual(0, child.exitcode)

        errors = [row[3] for row in rows if row[3]]
        self.assertEqual([], errors)
        self.assertEqual(PROCS * PER_PROC, len(rows))
        ids = {message_id: message for message, message_id, _reason, _ in rows}
        self.assertEqual(PROCS * PER_PROC, len(ids))  # 200 distinct letters, no id collision
        reasons = [reason for _m, _i, reason, _e in rows]
        expected_actionable = PROCS * len(range(0, PER_PROC, ACTIONABLE_EVERY))
        self.assertEqual(expected_actionable, reasons.count("DISPATCHED"))
        self.assertEqual(PROCS * PER_PROC - expected_actionable, reasons.count("QUEUED_NOTICE"))

        for message_id, message in ids.items():
            self.assertEqual(message, self.stored(message_id)["message"])
        self.assertEqual(sorted(ids), sorted(set(self.box.list_inbox()) & set(ids)))
        self.assertEqual([], self.box.list_bad())

        calls = self.calls()
        self.assertEqual(expected_actionable, len(calls))  # exactly one paid turn per ACTIONABLE letter
        sent_text = "\n".join(argv[argv.index("--message") + 1] for argv in calls)
        for message, message_id, reason, _ in rows:
            if reason == "DISPATCHED":
                self.assertIn(f"id={message_id}", sent_text)
                self.assertTrue((self.box.root / "delivery" / "accepted" / f"{message_id}.json").is_file())
        for argv in calls:
            self.assertEqual(TOPIC_THREAD, argv[argv.index("--thread") + 1])

        for message_id in ids:  # every letter is ackable by id afterwards
            claim = self.box.claim(message_id, "u279-judge")
            self.assertIsNotNone(claim, message_id)
            self.box.ack(claim)
        self.assertFalse(set(ids) & set(self.box.list_inbox()))


if __name__ == "__main__":
    unittest.main()
