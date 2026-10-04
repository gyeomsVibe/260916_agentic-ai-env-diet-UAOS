"""U141-B: ordinary letters wake their receiver under the structured watch policy (frozen acceptance).

Receipt: Codex verdict relay_102c3527 (2026-10-04) reproduced on the U141-M2 stage that an ordinary
`ACTIONABLE_DELTA VERDICT_REQUESTED=YES` letter is LEGACY and a structured watcher returns None, and that the same
actor/target/body sent first as NOTICE and then as ACTIONABLE raises MailboxRejected. 37 of 139 addressed desk
letters carried a wake token only in their text. Frozen requirements: Codex U141-M-independent-verdict-20261004.md.
- The producer (`deliver`, sentinel) writes the structured fields; the watcher classifier never reads message text.
- Explicit fields win over inference; quoted data is never an instruction.
- Identity is versioned JSON over destination and every explicit structured field; inferred fields are a pure
  function of the message, which the identity already holds.
Processes in the parallel tests really run at once (spawn + barrier).
"""
from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import presence
from v7_harness.coord import watch as W
from v7_harness.coord.deliver import _digest, _project_mailbox, _requires_wake, deliver
from v7_harness.coord.mailbox import Mailbox
from v7_harness.coord.sentinel import run_sentinel_cycle

ORDINARY = "ACTIONABLE_DELTA VERDICT_REQUESTED=YES judge counterexample\nsecond line with evidence"


def _send(root, fields, start, results):
    try:
        start.wait(30)
        result = deliver(Path(root), actor="codex", message="ACK_ONLY identity tags", target="claude", **fields)
        results.put((result.message_id, ""))
    except Exception as exc:  # noqa: BLE001 - the parent asserts on the text
        results.put(("", repr(exc)))


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / ".coord" / "mailbox").mkdir(parents=True)
        (self.root / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        sessions = self.root / "codex-sessions"
        sessions.mkdir()
        env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(sessions)})
        env.start()
        self.addCleanup(env.stop)
        # LIMITED/ABSENT receivers: deliver queues and publishes, no paid route runs in a test.
        presence.mark(self.root, "claude", "LIMITED")
        presence.mark(self.root, "codex", "ABSENT")
        self.box = _project_mailbox(self.root)

    def payload(self, result):
        return json.loads((self.box.inbox_dir / f"{result.message_id}.json").read_text(encoding="utf-8"))["payload"]

    def watch(self, tool):
        return W.watch(self.root, (tool,), timeout_s=0.3, interval_s=0.05, policy="structured")


class ProducerInference(Base):
    def test_ordinary_letter_is_structured_and_wakes_once(self):
        result = deliver(self.root, actor="claude", message=ORDINARY, target="codex")
        body = self.payload(result)
        self.assertEqual(("ACTIONABLE", ""), W.classify(body))
        self.assertEqual("ACTIONABLE_DELTA VERDICT_REQUESTED=YES judge counterexample", body["delta"])
        self.assertEqual(result.message_id, self.watch("codex")["id"])
        self.assertIsNone(self.watch("codex"))  # the claimed receipt blocks a second wake

    def test_each_supported_token_wakes(self):
        for message in ("VERDICT_REQUESTED=YES review bundle 1", "P1=YES runtime broken", "ACTIONABLE_DELTA x"):
            with self.subTest(message=message):
                body = self.payload(deliver(self.root, actor="claude", message=message, target="codex"))
                self.assertEqual("ACTIONABLE", W.classify(body)[0])

    def test_ack_negated_and_incidental_tokens_never_wake(self):
        for message in ("ACK_ONLY ACTIONABLE_DELTA VERDICT_REQUESTED=YES seen", "NO ACTIONABLE_DELTA here",
                        "XACTIONABLE_DELTA and ACTIONABLE_DELTAS", "VERDICT_REQUESTED=NO thanks"):
            with self.subTest(message=message):
                body = self.payload(deliver(self.root, actor="claude", message=message, target="codex"))
                self.assertNotIn("wake_class", body)
                self.assertEqual("LEGACY", W.classify(body)[0])
        self.assertIsNone(self.watch("codex"))

    def test_quoted_tokens_are_data_not_instructions(self):
        quoted = ('FYI earlier letter said "ACTIONABLE_DELTA" but nothing new',
                  "FYI the flag `VERDICT_REQUESTED=YES` is documented",
                  "FYI “P1=YES” was the old wording",
                  "> ACTIONABLE_DELTA VERDICT_REQUESTED=YES\nquoted reply only, nothing new")
        for message in quoted:
            with self.subTest(message=message):
                self.assertFalse(_requires_wake(message))
                body = self.payload(deliver(self.root, actor="claude", message=message, target="codex"))
                self.assertNotIn("wake_class", body)
        self.assertIsNone(self.watch("codex"))
        self.assertTrue(_requires_wake('re "old wording": ACTIONABLE_DELTA new evidence'))

    def test_single_quote_and_fenced_blocks_are_data(self):
        # Codex U141-B2 verdict counterexamples: both used to wake.
        for message in ("FYI earlier letter said 'ACTIONABLE_DELTA' but nothing new",
                        "FYI earlier code:\n```\nACTIONABLE_DELTA\n```\nno new update",
                        "FYI log:\n~~~text\nVERDICT_REQUESTED=YES\n~~~\nold",
                        "FYI unclosed fence\n```\nP1=YES"):
            with self.subTest(message=message):
                self.assertFalse(_requires_wake(message))
                body = self.payload(deliver(self.root, actor="claude", message=message, target="codex"))
                self.assertNotIn("wake_class", body)
        self.assertIsNone(self.watch("codex"))

    def test_actionable_line_outside_quotes_still_wakes(self):
        for message in ("```\nold ACK_ONLY\n```\nACTIONABLE_DELTA new evidence",
                        "it's done, the tools' ACTIONABLE_DELTA is real",
                        "> P1=YES quoted\nVERDICT_REQUESTED=YES judge bundle 2",
                        "said 'old' then ACTIONABLE_DELTA fresh"):
            with self.subTest(message=message):
                self.assertTrue(_requires_wake(message))
                body = self.payload(deliver(self.root, actor="claude", message=message, target="codex"))
                self.assertEqual("ACTIONABLE", W.classify(body)[0])

    def test_auto_route_letter_gets_no_inferred_fields(self):
        # Without requested_target an ACTIONABLE envelope would be INVALID; the auto route dispatches directly instead.
        body = self.payload(deliver(self.root, actor="claude", message=ORDINARY))
        self.assertNotIn("wake_class", body)


class ExplicitFields(Base):
    def test_explicit_notice_suppresses_inference(self):
        result = deliver(self.root, actor="claude", message=ORDINARY, target="codex", wake_class="NOTICE")
        body = self.payload(result)
        self.assertEqual(("NOTICE", ""), W.classify(body))
        self.assertNotIn("delta", body)
        self.assertIsNone(self.watch("codex"))

    def test_explicit_false_and_missing_stay_distinct(self):
        missing = deliver(self.root, actor="claude", message="plain note", target="codex")
        false = deliver(self.root, actor="claude", message="plain note", target="codex", verdict_requested=False)
        self.assertNotEqual(missing.message_id, false.message_id)
        self.assertNotIn("verdict_requested", self.payload(missing))
        self.assertIs(False, self.payload(false)["verdict_requested"])
        self.assertNotIn("wake_class", self.payload(false))


class Identity(Base):
    def test_notice_then_actionable_is_two_letters(self):
        notice = deliver(self.root, actor="codex", message="ACK_ONLY identity tags", target="claude",
                         wake_class="NOTICE")
        actionable = deliver(self.root, actor="codex", message="ACK_ONLY identity tags", target="claude",
                             wake_class="ACTIONABLE", delta="new review")
        self.assertNotEqual(notice.message_id, actionable.message_id)

    def test_same_complete_request_is_idempotent(self):
        first = deliver(self.root, actor="codex", message="m1", target="claude", wake_class="ACTIONABLE", delta="d")
        again = deliver(self.root, actor="codex", message="m1", target="claude", wake_class="ACTIONABLE", delta="d")
        self.assertEqual(first.message_id, again.message_id)
        self.assertEqual(1, sum(1 for m in self.box.list_inbox() if m == first.message_id))

    def test_untagged_targeted_letter_keeps_the_v2_identity(self):
        # Codex's accepted MSGID repair (3ca0406a): a letter that stores no structured field keeps its published id.
        # (Revised after U141-B2 REWORK: a waking letter stores inferred fields, so this pins a plain note.)
        plain = "plain progress note, nothing to judge"
        key = json.dumps(["uaos-relay-v2", "codex", plain, "", "", "codex"], ensure_ascii=False,
                         separators=(",", ":"))
        result = deliver(self.root, actor="codex", message=plain, target="codex")
        self.assertEqual(hashlib.sha256(key.encode("utf-8")).hexdigest(), result.digest)

    def test_inferred_letter_identity_equals_explicit_same_fields(self):
        first = ORDINARY.splitlines()[0]
        inferred = deliver(self.root, actor="claude", message=ORDINARY, target="codex")
        explicit = deliver(self.root, actor="claude", message=ORDINARY, target="codex", wake_class="ACTIONABLE",
                           delta=first)
        self.assertEqual(inferred.message_id, explicit.message_id)  # same stored payload, idempotent
        self.assertEqual(_digest("claude", ORDINARY, "", None, "codex", {"wake_class": "ACTIONABLE", "delta": first}),
                         inferred.digest)

    def test_pre_inference_v2_letter_never_collides_with_its_retry(self):
        # Codex U141-B2 counterexample: a v2 envelope stored before inference, then the same request retried, raised
        # MailboxRejected under the shared v2 id. Each stored state (inbox, claimed, acked) must keep its letter.
        from v7_harness.coord.deliver import _payload
        for state in ("inbox", "claimed", "acked"):
            with self.subTest(state=state):
                message = f"ACTIONABLE_DELTA retry after upgrade ({state})"
                old_digest = _digest("codex", message, target="claude")
                old_id = "relay_" + old_digest[:32]
                old_payload = _payload("codex", message, old_digest, "claude")
                self.box.publish(old_id, old_payload)
                if state != "inbox":
                    claim = self.box.claim(old_id, "claude")
                    self.assertIsNotNone(claim)
                    if state == "acked":
                        self.box.ack(claim)
                retry = deliver(self.root, actor="codex", message=message, target="claude")
                self.assertNotEqual(old_id, retry.message_id)
                self.assertEqual("ACTIONABLE", W.classify(self.payload(retry))[0])
                stored = [self.box.ack_dir / f"{old_id}.json", self.box.inbox_dir / f"{old_id}.json",
                          *self.box._claimed_files(old_id)]
                self.assertTrue(any(path.exists() for path in stored))  # the old letter is not lost
                self.assertFalse((self.box.ack_dir / f"{retry.message_id}.json").exists())  # no inherited ACK

    def test_explicit_identity_is_versioned_and_unambiguous(self):
        fields = {"wake_class": "ACTIONABLE", "delta": "d"}
        a = _digest("a", "b\0c", "", None, "claude", fields)
        b = _digest("a\0b", "c", "", None, "claude", fields)
        self.assertNotEqual(a, b)
        self.assertNotEqual(_digest("a", "m", "", None, "claude", {"delta": "x\0y"}),
                            _digest("a", "m", "", None, "claude", {"delta": "x", "verdict": "y"}))
        self.assertNotEqual(_digest("a", "m", "", None, "claude", fields), _digest("a", "m", "", None, "claude"))
        self.assertNotEqual(_digest("a", "m", "", None, None, fields), _digest("a", "m"))

    def test_parallel_processes_same_and_changed_metadata(self):
        ctx = multiprocessing.get_context("spawn")
        same = {"wake_class": "ACTIONABLE", "delta": "same"}
        variants = [same, same, same, same, {"wake_class": "NOTICE"}, {"wake_class": "ACTIONABLE", "delta": "x"},
                    {"verdict_requested": True}, {"verdict_requested": False}]
        start, results = ctx.Barrier(len(variants)), ctx.Queue()
        procs = [ctx.Process(target=_send, args=(str(self.root), fields, start, results)) for fields in variants]
        for proc in procs:
            proc.start()
        rows = [results.get(timeout=90) for _ in procs]
        for proc in procs:
            proc.join(90)
            self.assertEqual(0, proc.exitcode)
        self.assertEqual([], [err for _, err in rows if err])
        self.assertEqual(5, len({mid for mid, _ in rows}))


class SentinelRoute(Base):
    def test_sentinel_p1_wakes_its_recipient_once(self):
        self.box.publish("blocked1", {"kind": "BLOCKED", "step": "U99", "is_p1": True})
        self.assertTrue(run_sentinel_cycle(self.root, self.box, "claude")["p1_wake_emitted"])
        (wake_id,) = [m for m in self.box.list_inbox() if m.startswith("wake_")]
        body = self.box.read_message(wake_id)["payload"]
        self.assertEqual(("claude", True), (body["recipient"], body["p1_alert"]))
        self.assertEqual("ACTIONABLE", W.classify(body)[0])
        self.assertEqual(wake_id, self.watch("claude")["id"])
        self.assertFalse(run_sentinel_cycle(self.root, self.box, "claude")["p1_wake_emitted"])
        self.assertIsNone(self.watch("claude"))


if __name__ == "__main__":
    unittest.main()
