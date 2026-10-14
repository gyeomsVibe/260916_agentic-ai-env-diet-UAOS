"""U190-B: the sentinel cycle consumes a P1 retry-exhaustion record, zero paid tokens (frozen acceptance).

Receipt (Codex PASS relay_68d51290, REVISE relay_9936ff5e and relay_55791b4f; inventory
.work/u189/prereq_inventory.md B): no registered consumer reads an exhausted P1 retry, so an exhausted alert is
printed and forgotten and the receiver idles. The record producer is U189 (parked); this card freezes the record
schema and its consumer.

Contract, per tool in desk_sync.TOOLS, every run_sentinel_cycle (result["exhaustion"][tool]); also callable as
sentinel.consume_exhaustion(project, box, current_keys) -> {tool: report}:
- Record `.coord/presence/p1_retry_exhausted_<tool>.json`, schema u190b-exhausted-v1 {schema, tool, wake_base,
  event_fingerprint (64 hex, wake_base == "wake_" + its first 24), event_keys [str], attempts, desk {thread,
  generation} | null, at}. Missing -> NONE; unparseable or off-schema -> CORRUPT; the consumer never writes, moves
  or deletes a record file.
- Episode identity (record_id) is the immutable alert epoch: sha256 of the compact sorted-key JSON of {schema, tool,
  wake_base, event_fingerprint, event_keys sorted and unique, desk}. `at`, `attempts`, key order and whitespace are
  cosmetic: a rewrite changing only them is the same episode and buys no second handoff or resume. A producer
  (U189) opens a new episode only by a new fingerprint, key set or desk.
- Each tool is consumed under one OS file lock `.coord/presence/p1_exhaustion.lock` (stream._try_lock), which a
  producer takes too. Every marker is published crash-safely and exclusively (sentinel._create_exclusive: True
  created, False already there, OSError failed): a process killed while writing it leaves no final marker file,
  and a marker is never overwritten or deleted.
- A marker establishes nothing unless complete and exact: consumed {schema u190b-consumed-v1, tool, record_id,
  wake_base, event_fingerprint, event_keys (sorted unique), desk, resolved_by in NEW_DESK|RECEIPT|ALERT_CHANGED,
  at}; handoff {schema u190b-handoff-v1, tool, record_id, wake_base, receiver == record desk, letter_id, at} AND
  the letter, found in inbox, claimed or ack, whose payload equals the exact payload this episode queues. An
  existing consumed marker that fails this is status MARKER_INVALID; a handoff file or letter that fails it is
  handoff HANDOFF_INVALID. Both keep every byte, resume nothing and send nothing.
- Resume, once per record_id and only on a genuine change (never count or time), in this order: NEW_DESK
  (desk_identity PROJECT_BOUND and != record desk), RECEIPT (the published wake letter wake_base, inbox or acked,
  carries exactly the record's event_fingerprint, and the u189-wake-seen-v1 receipt at
  wake_seen/<tool>/<thread>/<wake_base>.json names this tool, the record's desk thread+generation, wake_base and
  exactly that fingerprint), ALERT_CHANGED (the cycle's P1 key set != event_keys). Resume = exclusive marker
  p1_retry_consumed/<tool>/<record_id>.json {resolved_by, event_keys, ...}; later cycles report CONSUMED.
  A failed marker is RESET_FAILED and the next cycle tries again.
- Otherwise EXHAUSTED. Only a PROJECT_BOUND desk gets a handoff: one ACTIONABLE letter handoff_<record_id 24>_<tool>
  bound to that thread+generation, then the exclusive p1_handoff/<tool>/<record_id>.json naming the same receiver
  and letter: QUEUED once (queued, not proof the receiver acted), then ALREADY_QUEUED. Any other desk status,
  UNBOUND_EXISTS included, is UNDELIVERABLE: nothing written or sent. A failed publish or handoff file is
  HANDOFF_FAILED; the retry never sends a second letter.
- A same-generation repaired consumer has no observable trigger: repaired_consumer is "UNKNOWN", never resumes.
Keys: mailbox_p1:<message id>, stale_lock:<reason>, needs_reconciliation:<task>.
Parallel tests use real processes (spawn + barrier).
"""
from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import desk_sync, presence, sentinel
from v7_harness.coord.mailbox import Mailbox
from v7_harness.coord.sentinel import run_sentinel_cycle

THREAD = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


def _consume_in_child(root: str, keys: list[str], start, results) -> None:
    try:
        start.wait(60)
        box = Mailbox(Path(root) / ".coord" / "mailbox")
        results.put(json.dumps(sentinel.consume_exhaustion(Path(root), box, set(keys))["codex"]))
    except Exception as exc:  # noqa: BLE001 - the parent asserts on the text
        results.put(json.dumps({"status": "CHILD_ERROR", "error": repr(exc)}))


def _crash_at_marker(root: str, keys: list[str], final: str) -> None:
    """Kill this process (exit 9) at the first step that writes or publishes the final marker path itself.

    Opening the final path for writing dies just after the open created it (no byte written), exactly what a power
    cut does to a direct writer; a link/rename/replace onto it dies before the publication step.
    """
    import sys

    target = os.path.normcase(os.path.abspath(final))
    dying = []

    def same(path: object) -> bool:
        try:
            return os.path.normcase(os.path.abspath(os.fsdecode(path))) == target
        except (TypeError, ValueError):
            return False

    def hook(event: str, args: tuple) -> None:
        if dying:
            return
        if event == "open" and same(args[0]):
            mode, flags = args[1], args[2]
            writes = (isinstance(mode, str) and any(c in mode for c in "wxa+")) or (
                mode is None and isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT))
            if writes:
                dying.append(True)
                os.close(os.open(final, os.O_CREAT | os.O_WRONLY))
                os._exit(9)
        elif event in ("os.link", "os.rename", "os.replace") and len(args) > 1 and same(args[1]):
            os._exit(9)

    sys.addaudithook(hook)
    box = Mailbox(Path(root) / ".coord" / "mailbox")
    sentinel.consume_exhaustion(Path(root), box, set(keys))
    os._exit(0)


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.root = base / "project"
        (self.root / ".coord" / "mailbox").mkdir(parents=True)
        (self.root / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        self.codex_home = base / "codex_sessions"
        self.claude_home = base / "claude_home"
        self.agy_home = base / "agy_home"
        env = {"UAOS_CODEX_SESSIONS": str(self.codex_home), "CLAUDE_CONFIG_DIR": str(self.claude_home),
               "UAOS_AGY_APP_HOME": str(self.agy_home), presence.CODEX_SESSIONS_ENV: str(self.codex_home)}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.box = Mailbox(self.root / ".coord" / "mailbox")
        self.box.publish("b_a", {"kind": "BLOCKED", "step": "A", "is_p1": True})
        run_sentinel_cycle(self.root, self.box, "codex")  # publishes the real P1 wake the record refers to
        (self.wake,) = [m for m in self.box.list_inbox() if m.startswith("wake_")]
        self.fingerprint = self.box.read_message(self.wake)["payload"]["event_fingerprint"]

    # fixtures ---------------------------------------------------------------------------------------------------
    @property
    def presence_dir(self) -> Path:
        return self.root / ".coord" / "presence"

    def desk(self, tool: str, thread: str = THREAD, generation: int = 1) -> None:
        path = self.presence_dir / f"user_desk_{tool}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"thread": thread, "generation": generation, "source": "test"}), encoding="utf-8")
        if tool == "codex":
            day = self.codex_home / "2026" / "10" / "14"
            day.mkdir(parents=True, exist_ok=True)
            meta = {"type": "session_meta", "payload": {"id": thread, "session_id": thread, "cwd": str(self.root)}}
            (day / f"rollout-2026-10-14T06-00-00-{thread}.jsonl").write_text(json.dumps(meta) + "\n", encoding="utf-8")
        elif tool == "claude":
            folder = self.claude_home / "projects" / "D--project"
            folder.mkdir(parents=True, exist_ok=True)
            rows = [{"type": "user", "sessionId": thread}, {"type": "user", "sessionId": thread, "cwd": str(self.root)}]
            (folder / f"{thread}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        else:
            (self.agy_home / "brain" / thread).mkdir(parents=True, exist_ok=True)

    def record_path(self, tool: str) -> Path:
        return self.presence_dir / f"p1_retry_exhausted_{tool}.json"

    def exhausted(self, tool: str, desk: object = "bound", *, raw: str | None = None, **changes: object) -> Path:
        path = self.record_path(tool)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"schema": "u190b-exhausted-v1", "tool": tool, "wake_base": self.wake,
                  "event_fingerprint": self.fingerprint, "event_keys": ["mailbox_p1:b_a"], "attempts": 3,
                  "desk": {"thread": THREAD, "generation": 1} if desk == "bound" else desk, "at": time.time()}
        record.update(changes)
        path.write_text(raw if raw is not None else json.dumps(record), encoding="utf-8")
        return path

    def record_id(self, tool: str) -> str:
        data = json.loads(self.record_path(tool).read_text(encoding="utf-8"))
        episode = {key: data[key] for key in ("schema", "tool", "wake_base", "event_fingerprint", "desk")}
        episode["event_keys"] = sorted(set(data["event_keys"]))
        return hashlib.sha256(json.dumps(episode, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    def receipt(self, tool: str = "codex", filed_as: str | None = None, **changes: object) -> Path:
        record = {"schema": "u189-wake-seen-v1", "message_id": self.wake, "tool": tool, "session": THREAD,
                  "generation": 1, "event_fingerprint": self.fingerprint, "seen_at": time.time()}
        record.update(changes)
        path = self.presence_dir / "wake_seen" / tool / THREAD / f"{filed_as or self.wake}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record), encoding="utf-8")
        return path

    def cycle(self, tool: str = "codex") -> dict:
        result = run_sentinel_cycle(self.root, self.box, tool)
        self.assertEqual(result["paid_api_calls"], 0)
        return result["exhaustion"][tool]

    def letters(self) -> list[str]:
        folders = (self.box.inbox_dir, self.box.claimed_dir, self.box.ack_dir)
        return sorted(json.loads(p.read_text(encoding="utf-8"))["message_id"]
                      for d in folders for p in d.glob("handoff_*.json"))

    def handoff_file(self, tool: str, record_id: str) -> Path:
        return self.presence_dir / "p1_handoff" / tool / f"{record_id}.json"

    def consumed_file(self, tool: str, record_id: str) -> Path:
        return self.presence_dir / "p1_retry_consumed" / tool / f"{record_id}.json"


class Registration(Base):
    def test_every_cycle_reports_all_three_tools(self) -> None:
        result = run_sentinel_cycle(self.root, self.box, "codex")
        self.assertEqual(sorted(result["exhaustion"]), ["antigravity", "claude", "codex"])
        for tool in ("antigravity", "claude", "codex"):
            self.assertEqual(result["exhaustion"][tool]["status"], "NONE")


class Handoff(Base):
    def test_a_bound_desk_gets_exactly_one_receiver_bound_handoff(self) -> None:
        for tool in ("codex", "claude"):
            with self.subTest(tool=tool):
                self.setUp()
                self.desk(tool)
                record = self.exhausted(tool)
                before, record_id = record.read_bytes(), self.record_id(tool)
                letter = f"handoff_{record_id[:24]}_{tool}"
                first = self.cycle(tool)
                self.assertEqual((first["status"], first["handoff"]), ("EXHAUSTED", "QUEUED"))
                inbox_after_first = sorted(self.box.list_inbox())
                for _ in range(4):
                    later = self.cycle(tool)
                    self.assertEqual((later["status"], later["handoff"]), ("EXHAUSTED", "ALREADY_QUEUED"))
                self.assertEqual(sorted(self.box.list_inbox()), inbox_after_first, "no unchanged wake loop")
                self.assertEqual(self.letters(), [letter])
                body = self.box.read_message(letter)["payload"]
                self.assertEqual((body["requested_target"], body["wake_class"], body["wake_base"]),
                                 (tool, "ACTIONABLE", self.wake))
                self.assertEqual(body["receiver"], {"thread": THREAD, "generation": 1})
                durable = json.loads(self.handoff_file(tool, record_id).read_text(encoding="utf-8"))
                self.assertEqual((durable["tool"], durable["receiver"], durable["letter_id"]),
                                 (tool, {"thread": THREAD, "generation": 1}, letter))
                self.assertEqual(record.read_bytes(), before, "a handoff never touches the record")

    def test_an_unbound_or_unverified_desk_is_never_delivered(self) -> None:
        cases = (("antigravity", "desk", "UNBOUND_EXISTS"), ("codex", "none", "ABSENT"),
                 ("claude", "none", "ABSENT"), ("codex", "record_only", "UNVERIFIED"))
        for tool, setup, desk_status in cases:
            with self.subTest(tool=tool, setup=setup):
                self.setUp()
                if setup == "desk":
                    self.desk(tool)
                elif setup == "record_only":
                    path = self.presence_dir / f"user_desk_{tool}.json"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps({"thread": THREAD, "generation": 1, "source": "t"}), encoding="utf-8")
                self.exhausted(tool, desk=None if setup != "record_only" else "bound")
                for _ in range(3):
                    state = self.cycle(tool)
                    self.assertEqual((state["status"], state["handoff"], state["desk_status"]),
                                     ("EXHAUSTED", "UNDELIVERABLE", desk_status))
                self.assertEqual(self.letters(), [])
                self.assertFalse((self.presence_dir / "p1_handoff").exists())

    def test_a_failed_publish_is_typed_kept_and_retried_once(self) -> None:
        self.desk("codex")
        self.exhausted("codex")
        real = Mailbox.publish

        def refuse_handoff(box: Mailbox, message_id: str, payload: object) -> Path:
            if message_id.startswith("handoff_"):
                raise OSError("disk full")
            return real(box, message_id, payload)

        with mock.patch.object(Mailbox, "publish", refuse_handoff):
            state = self.cycle()
        self.assertEqual((state["status"], state["handoff"]), ("EXHAUSTED", "HANDOFF_FAILED"))
        self.assertEqual(self.letters(), [])
        self.assertFalse(self.handoff_file("codex", self.record_id("codex")).exists())
        self.assertEqual(self.cycle()["handoff"], "QUEUED")
        self.assertEqual(self.cycle()["handoff"], "ALREADY_QUEUED")
        self.assertEqual(len(self.letters()), 1)

    def test_a_failed_handoff_file_after_publish_never_sends_twice(self) -> None:
        self.desk("codex")
        self.exhausted("codex")
        real = sentinel._create_exclusive

        def refuse_handoff_file(path: Path, data: dict) -> bool:
            if "p1_handoff" in path.parts:
                raise OSError("disk full")
            return real(path, data)

        with mock.patch.object(sentinel, "_create_exclusive", refuse_handoff_file):
            self.assertEqual(self.cycle()["handoff"], "HANDOFF_FAILED")
        self.assertEqual(len(self.letters()), 1)
        self.assertEqual(self.cycle()["handoff"], "QUEUED")
        self.assertEqual(self.cycle()["handoff"], "ALREADY_QUEUED")
        self.assertEqual(len(self.letters()), 1)
        self.assertTrue(self.handoff_file("codex", self.record_id("codex")).is_file())


class Resume(Base):
    def assert_consumed_once(self, tool: str, trigger: str) -> None:
        record = self.record_path(tool)
        before, record_id = record.read_bytes(), self.record_id(tool)
        state = self.cycle(tool)
        self.assertEqual((state["status"], state["trigger"]), ("RESUMED", trigger))
        marker = json.loads(self.consumed_file(tool, record_id).read_text(encoding="utf-8"))
        self.assertEqual((marker["resolved_by"], marker["event_keys"], marker["wake_base"]),
                         (trigger, ["mailbox_p1:b_a"], self.wake))
        marker_bytes = self.consumed_file(tool, record_id).read_bytes()
        for _ in range(3):
            later = self.cycle(tool)
            self.assertEqual((later["status"], later["resolved_by"]), ("CONSUMED", trigger))
        self.assertEqual(record.read_bytes(), before, "the original evidence is never touched")
        self.assertEqual(self.consumed_file(tool, record_id).read_bytes(), marker_bytes, "a marker is never rewritten")

    def test_an_unchanged_exhausted_state_never_resumes(self) -> None:
        self.desk("codex")
        self.exhausted("codex")
        for _ in range(6):
            self.assertEqual(self.cycle()["status"], "EXHAUSTED")
        self.assertFalse((self.presence_dir / "p1_retry_consumed").exists())

    def test_a_new_desk_generation_resumes_once(self) -> None:
        self.desk("codex")
        self.exhausted("codex")
        self.cycle()
        self.desk("codex", generation=2)
        self.assert_consumed_once("codex", "NEW_DESK")

    def test_a_desk_bound_after_an_unbound_exhaustion_resumes_once(self) -> None:
        self.exhausted("claude", desk=None)
        self.assertEqual(self.cycle("claude")["handoff"], "UNDELIVERABLE")
        self.desk("claude")
        self.assert_consumed_once("claude", "NEW_DESK")

    def test_an_exact_receipt_resumes_once(self) -> None:
        self.desk("codex")
        self.exhausted("codex")
        self.cycle()
        self.receipt()
        self.assert_consumed_once("codex", "RECEIPT")

    def test_an_inexact_receipt_does_not_resume(self) -> None:
        def variants():
            altered = self.fingerprint[:24] + ("0" if self.fingerprint[24] != "0" else "1") + self.fingerprint[25:]
            yield "same prefix altered suffix", {"event_fingerprint": altered}
            yield "another event set", {"event_fingerprint": "f" * 64, "message_id": "wake_" + "f" * 24}
            yield "another session", {"session": OTHER}
            yield "another generation", {"generation": 2}
            yield "bool generation", {"generation": True}
            yield "another tool", {"tool": "claude"}
            yield "another schema", {"schema": "other"}

        for name, change in variants():
            with self.subTest(case=name):
                self.setUp()
                self.desk("codex")
                self.exhausted("codex")
                self.receipt(**change)
                self.assertEqual(self.cycle()["status"], "EXHAUSTED")
        for content in ("", "{not json", "[]"):
            with self.subTest(content=content):
                self.setUp()
                self.desk("codex")
                self.exhausted("codex")
                self.receipt().write_text(content, encoding="utf-8")
                self.assertEqual(self.cycle()["status"], "EXHAUSTED")
        with self.subTest(case="filed under another tool"):
            self.setUp()
            self.desk("codex")
            self.exhausted("codex")
            elsewhere = self.presence_dir / "wake_seen" / "claude" / THREAD / f"{self.wake}.json"
            elsewhere.parent.mkdir(parents=True)
            self.receipt().replace(elsewhere)
            self.assertEqual(self.cycle()["status"], "EXHAUSTED")

    def test_a_receipt_without_the_published_wake_does_not_resume(self) -> None:
        with self.subTest(case="never published"):  # deleting the real wake would only make the cycle republish it
            self.desk("codex")
            never = "d" * 64
            self.exhausted("codex", wake_base=f"wake_{never[:24]}", event_fingerprint=never)
            self.receipt(filed_as=f"wake_{never[:24]}", message_id=f"wake_{never[:24]}", event_fingerprint=never)
            self.assertEqual(self.cycle()["status"], "EXHAUSTED")
        with self.subTest(case="published with another fingerprint"):
            self.setUp()
            self.desk("codex")
            self.exhausted("codex")
            self.receipt()
            path = self.box.inbox_dir / f"{self.wake}.json"
            letter = json.loads(path.read_text(encoding="utf-8"))
            letter["payload"]["event_fingerprint"] = "e" * 64
            path.write_text(json.dumps(letter), encoding="utf-8")
            self.assertEqual(self.cycle()["status"], "EXHAUSTED")

    def test_an_acked_published_wake_still_counts(self) -> None:
        self.desk("codex")
        self.exhausted("codex")
        claim = self.box.claim(self.wake, "codex-desk")
        self.box.ack(claim)
        self.receipt()
        self.assert_consumed_once("codex", "RECEIPT")

    def test_an_unbound_desk_receipt_does_not_resume(self) -> None:
        self.desk("antigravity")
        self.exhausted("antigravity")
        self.receipt(tool="antigravity")
        self.assertEqual(self.cycle("antigravity")["status"], "EXHAUSTED")

    def test_a_changed_alert_set_resumes_once(self) -> None:
        self.desk("codex")
        self.exhausted("codex")
        self.cycle()
        self.box.publish("b_c", {"kind": "BLOCKED", "step": "C", "is_p1": True})
        self.assert_consumed_once("codex", "ALERT_CHANGED")

    def test_a_failed_marker_is_typed_and_retried_once(self) -> None:
        self.desk("codex")
        self.exhausted("codex")
        self.box.publish("b_c", {"kind": "BLOCKED", "step": "C", "is_p1": True})
        real = sentinel._create_exclusive

        def refuse_marker(path: Path, data: dict) -> bool:
            if "p1_retry_consumed" in path.parts:
                raise OSError("disk full")
            return real(path, data)

        with mock.patch.object(sentinel, "_create_exclusive", refuse_marker):
            self.assertEqual(self.cycle()["status"], "RESET_FAILED")
        self.assertFalse((self.presence_dir / "p1_retry_consumed").exists())
        self.assert_consumed_once("codex", "ALERT_CHANGED")

    def test_a_same_generation_repaired_consumer_is_unknown_not_resumed(self) -> None:
        self.desk("codex")
        self.exhausted("codex")
        for _ in range(3):
            state = self.cycle()
            self.assertEqual((state["status"], state["repaired_consumer"]), ("EXHAUSTED", "UNKNOWN"))

    def test_a_producer_replacement_mid_consumption_is_never_touched(self) -> None:
        for trigger in ("handoff", "resume"):
            with self.subTest(trigger=trigger):
                self.setUp()
                self.desk("codex")
                self.exhausted("codex")
                old_id = self.record_id("codex")
                if trigger == "resume":
                    self.box.publish("b_c", {"kind": "BLOCKED", "step": "C", "is_p1": True})
                newer = None
                real = desk_sync.desk_identity

                def replace_then_read(project: Path, tool: str):
                    nonlocal newer
                    if newer is None:  # the producer writes a new exhaustion after the consumer read its snapshot
                        newer = self.exhausted("codex", event_keys=["mailbox_p1:b_a", "mailbox_p1:b_c"],
                                               attempts=4).read_bytes()
                    return real(project, tool)

                with mock.patch.object(desk_sync, "desk_identity", replace_then_read):
                    state = self.cycle()
                self.assertEqual(self.record_path("codex").read_bytes(), newer, "the newer record survives")
                if trigger == "resume":
                    self.assertEqual(state["status"], "RESUMED")
                    self.assertTrue(self.consumed_file("codex", old_id).is_file())
                else:
                    self.assertEqual(state["handoff"], "QUEUED")
                    self.assertTrue(self.handoff_file("codex", old_id).is_file())
                new_id = self.record_id("codex")
                self.assertFalse(self.consumed_file("codex", new_id).exists())
                self.assertIn(self.cycle()["status"], ("EXHAUSTED", "RESUMED"))


class Parallel(Base):
    def run_children(self, count: int = 8) -> list[dict]:
        ctx = multiprocessing.get_context("spawn")
        start, results = ctx.Barrier(count), ctx.Queue()
        keys = sorted(sentinel._event_keys([{"kind": "mailbox_p1", "message_id": m} for m in self.p1_ids]))
        procs = [ctx.Process(target=_consume_in_child, args=(str(self.root), keys, start, results))
                 for _ in range(count)]
        for proc in procs:
            proc.start()
        rows = [json.loads(results.get(timeout=120)) for _ in procs]
        for proc in procs:
            proc.join(120)
            self.assertEqual(proc.exitcode, 0)
        self.assertEqual([r for r in rows if r["status"] == "CHILD_ERROR"], [])
        return rows

    def test_parallel_consumers_queue_exactly_one_handoff(self) -> None:
        self.p1_ids = ["b_a"]
        self.desk("codex")
        self.exhausted("codex")
        rows = self.run_children()
        self.assertEqual(sorted(r["handoff"] for r in rows), ["ALREADY_QUEUED"] * 7 + ["QUEUED"])
        self.assertEqual(len(self.letters()), 1)
        self.assertEqual(len(list((self.presence_dir / "p1_handoff" / "codex").glob("*.json"))), 1)

    def test_parallel_consumers_resume_exactly_once(self) -> None:
        self.p1_ids = ["b_a", "b_c"]
        self.desk("codex")
        self.exhausted("codex")
        rows = self.run_children()
        self.assertEqual(sorted(r["status"] for r in rows), ["CONSUMED"] * 7 + ["RESUMED"])
        self.assertEqual(len(list((self.presence_dir / "p1_retry_consumed" / "codex").glob("*.json"))), 1)


class Markers(Base):
    """REVISE relay_55791b4f: a marker file's existence alone never establishes CONSUMED or ALREADY_QUEUED."""

    def consumed_marker(self, **changes: object) -> dict:
        marker = {"schema": "u190b-consumed-v1", "tool": "codex", "record_id": self.record_id("codex"),
                  "wake_base": self.wake, "event_fingerprint": self.fingerprint, "event_keys": ["mailbox_p1:b_a"],
                  "desk": {"thread": THREAD, "generation": 1}, "resolved_by": "ALERT_CHANGED", "at": 1.0}
        marker.update(changes)
        return marker

    def handoff_marker(self, **changes: object) -> dict:
        record_id = self.record_id("codex")
        marker = {"schema": "u190b-handoff-v1", "tool": "codex", "record_id": record_id, "wake_base": self.wake,
                  "receiver": {"thread": THREAD, "generation": 1}, "letter_id": f"handoff_{record_id[:24]}_codex",
                  "at": 1.0}
        marker.update(changes)
        return marker

    def test_an_invalid_consumed_marker_establishes_nothing(self) -> None:
        def contents():
            yield from ("", '{"schema": "u190b-consumed', "{}", "[]")
            for change in ({"schema": "other"}, {"tool": "claude"}, {"record_id": "0" * 64},
                           {"wake_base": "wake_" + "0" * 24}, {"event_fingerprint": "e" * 64}, {"event_keys": []},
                           {"desk": {"thread": THREAD, "generation": 2}}, {"desk": None}, {"resolved_by": None},
                           {"resolved_by": "COUNT"}):
                yield json.dumps(self.consumed_marker(**change))

        for content in contents():
            with self.subTest(content=content):
                self.setUp()
                self.desk("codex")
                self.exhausted("codex")
                self.box.publish("b_c", {"kind": "BLOCKED", "step": "C", "is_p1": True})  # a genuine trigger exists
                marker = self.consumed_file("codex", self.record_id("codex"))
                marker.parent.mkdir(parents=True)
                marker.write_text(content, encoding="utf-8")
                before = marker.read_bytes()
                for _ in range(2):
                    self.assertEqual(self.cycle()["status"], "MARKER_INVALID")
                self.assertEqual(marker.read_bytes(), before, "invalid evidence is kept byte for byte")
                self.assertEqual([p.name for p in marker.parent.iterdir()], [marker.name])
                self.assertEqual(self.letters(), [])
        with self.subTest(content="exact"):
            self.setUp()
            self.desk("codex")
            self.exhausted("codex")
            marker = self.consumed_file("codex", self.record_id("codex"))
            marker.parent.mkdir(parents=True)
            marker.write_text(json.dumps(self.consumed_marker()), encoding="utf-8")
            state = self.cycle()
            self.assertEqual((state["status"], state["resolved_by"]), ("CONSUMED", "ALERT_CHANGED"))

    def test_an_invalid_handoff_file_or_letter_queues_nothing(self) -> None:
        def file_cases():
            yield from ("", '{"schema": "u190b-handoff', "{}", "[]")
            for change in ({"schema": "other"}, {"tool": "claude"}, {"record_id": "0" * 64},
                           {"wake_base": "wake_" + "0" * 24}, {"receiver": {"thread": THREAD, "generation": 2}},
                           {"receiver": {"thread": OTHER, "generation": 1}}, {"letter_id": "handoff_other_codex"}):
                yield json.dumps(self.handoff_marker(**change))

        for content in file_cases():
            with self.subTest(content=content):
                self.setUp()
                self.desk("codex")
                self.exhausted("codex")
                self.assertEqual(self.cycle()["handoff"], "QUEUED")
                path = self.handoff_file("codex", self.record_id("codex"))
                path.write_text(content, encoding="utf-8")
                before = path.read_bytes()
                for _ in range(2):
                    self.assertEqual(self.cycle()["handoff"], "HANDOFF_INVALID")
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(len(self.letters()), 1)
        with self.subTest(case="exact file, letter gone"):
            self.setUp()
            self.desk("codex")
            self.exhausted("codex")
            self.cycle()
            (self.box.inbox_dir / f"{self.handoff_marker()['letter_id']}.json").unlink()
            self.assertEqual(self.cycle()["handoff"], "HANDOFF_INVALID")
            self.assertEqual(self.letters(), [])
        with self.subTest(case="letter under the id with another receiver, no file"):
            self.setUp()
            self.desk("codex")
            self.exhausted("codex")
            letter = self.handoff_marker()["letter_id"]
            self.box.publish(letter, {"kind": "P1_RETRY_EXHAUSTED", "requested_target": "codex",
                                      "receiver": {"thread": OTHER, "generation": 1}})
            for _ in range(2):
                self.assertEqual(self.cycle()["handoff"], "HANDOFF_INVALID")
            self.assertFalse((self.presence_dir / "p1_handoff").exists())
            self.assertEqual(self.letters(), [letter])

    def test_a_claimed_or_acked_handoff_letter_stays_queued(self) -> None:
        self.desk("codex")
        self.exhausted("codex")
        self.assertEqual(self.cycle()["handoff"], "QUEUED")
        claim = self.box.claim(self.handoff_marker()["letter_id"], "codex-desk")
        self.assertEqual(self.cycle()["handoff"], "ALREADY_QUEUED")
        self.box.ack(claim)
        self.assertEqual(self.cycle()["handoff"], "ALREADY_QUEUED")
        self.assertEqual(len(self.letters()), 1)

    def test_a_process_killed_while_writing_a_marker_leaves_none(self) -> None:
        for part in ("consumed", "handoff"):
            with self.subTest(part=part):
                self.setUp()
                self.desk("codex")
                self.exhausted("codex")
                keys = ["mailbox_p1:b_a"]
                final = self.handoff_file("codex", self.record_id("codex"))
                if part == "consumed":
                    self.box.publish("b_c", {"kind": "BLOCKED", "step": "C", "is_p1": True})
                    keys.append("mailbox_p1:b_c")
                    final = self.consumed_file("codex", self.record_id("codex"))
                ctx = multiprocessing.get_context("spawn")
                proc = ctx.Process(target=_crash_at_marker, args=(str(self.root), keys, str(final)))
                proc.start()
                proc.join(120)
                self.assertEqual(proc.exitcode, 9, "the child died while writing the marker")
                self.assertFalse(final.exists(), "an interrupted write exposes no final marker")
                state = self.cycle()
                if part == "consumed":
                    self.assertEqual((state["status"], state["trigger"]), ("RESUMED", "ALERT_CHANGED"))
                    self.assertEqual(self.cycle()["status"], "CONSUMED")
                else:
                    self.assertEqual(state["handoff"], "QUEUED")
                    self.assertEqual(self.cycle()["handoff"], "ALREADY_QUEUED")
                    self.assertEqual(len(self.letters()), 1)

    def test_a_cosmetic_rewrite_is_the_same_episode(self) -> None:
        def rewrite() -> None:
            path = self.record_path("codex")
            data = json.loads(path.read_text(encoding="utf-8"))
            data.update(at=data["at"] + 100, attempts=data["attempts"] + 5)
            path.write_text(json.dumps(dict(reversed(list(data.items()))), indent=2), encoding="utf-8")

        self.desk("codex")
        self.exhausted("codex")
        first_id = self.record_id("codex")
        self.assertEqual(self.cycle()["handoff"], "QUEUED")
        rewrite()
        self.assertEqual(self.record_id("codex"), first_id)
        self.assertEqual(self.cycle()["handoff"], "ALREADY_QUEUED")
        self.assertEqual(len(self.letters()), 1)
        self.box.publish("b_c", {"kind": "BLOCKED", "step": "C", "is_p1": True})
        self.assertEqual(self.cycle()["status"], "RESUMED")
        rewrite()
        self.assertEqual(self.cycle()["status"], "CONSUMED")
        self.assertEqual(len(list((self.presence_dir / "p1_retry_consumed" / "codex").glob("*.json"))), 1)


class RecordDefects(Base):
    def test_a_corrupt_record_is_kept_and_reported(self) -> None:
        def raws():
            good = {"schema": "u190b-exhausted-v1", "tool": "codex", "wake_base": self.wake,
                    "event_fingerprint": self.fingerprint, "event_keys": ["mailbox_p1:b_a"], "attempts": 3,
                    "desk": None, "at": 1.0}
            yield from ("", "{not json", "[]")
            for change in ({"schema": "other"}, {"tool": "claude"}, {"wake_base": "wake_xyz"},
                           {"wake_base": "wake_" + "0" * 24}, {"event_fingerprint": "x" * 64},
                           {"event_fingerprint": None}, {"event_keys": "mailbox_p1:b_a"}, {"event_keys": [1]},
                           {"desk": {"thread": "x", "generation": 1}}, {"desk": {"thread": THREAD, "generation": True}}):
                yield json.dumps({**good, **change})

        for raw in raws():
            with self.subTest(raw=raw):
                self.setUp()
                self.desk("codex")
                record = self.exhausted("codex", raw=raw)
                before = record.read_bytes()
                self.assertEqual(self.cycle()["status"], "CORRUPT")
                self.assertEqual(record.read_bytes(), before)
                self.assertEqual(self.letters(), [])


if __name__ == "__main__":
    unittest.main()
