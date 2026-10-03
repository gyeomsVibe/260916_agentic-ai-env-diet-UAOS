"""U141-A: a deterministic wake policy, with at most one automatic paid wake per letter (rev 4 f57b2186 + rev 5 delta).

Fixed acceptance, written by the judge (acting conductor Claude, Codex LIMITED) before dispatch; no paid call.
- The classifier reads only structured envelope fields, never message text.
- An O_EXCL pending receipt allows at most one wake per letter.
- The receiver hook ACKs only the letters its written output really showed.
- One watcher runs per target, and its lock is safe against PID reuse.
"""
from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from v7_harness.coord import agy_dispatch, desk_delta, presence
from v7_harness.coord import watch as W
from v7_harness.coord.deliver import deliver
from v7_harness.coord.mailbox import Mailbox

# Real stored envelopes (2026-10-03 desk). The message text is cut to 200 chars because the classifier never reads it.
FIXTURES = json.loads(r"""{
 "notices": [
  {
   "message_id": "relay_181d470660dc437658f8fbd0724824f6",
   "schema": "u23-mailbox-v1",
   "payload": {
    "actor": "claude",
    "digest": "181d470660dc437658f8fbd0724824f67e7bbdfc43c2054aab5309fefa58ad02",
    "kind": "HANDOFF",
    "message": "RETURN NOTE (Codex hit its usage limit; the user delegated full authority to Claude until you return). FACT: your relay-nonstop U63/U64 work, with its two red P2 tests, is integrated in PR #32 (branch",
    "requested_target": "codex"
   }
  },
  {
   "message_id": "relay_2ba2fad9636e6dd9b5733f7b6e41e5b4",
   "schema": "u23-mailbox-v1",
   "payload": {
    "actor": "claude",
    "digest": "2ba2fad9636e6dd9b5733f7b6e41e5b4c89e3a15e6da11d574144ff1fd21c66f",
    "kind": "HANDOFF",
    "message": "ACTIONABLE_DELTA VERDICT_REQUESTED=YES U69+U70 merged (d394a72, c526903), runtime 0.3.0-bf2b63907fcb drift 0. Real qualification recorded in .coord/qualification: qwen2.5-coder:7b digest dae161e2 list",
    "requested_target": "codex"
   }
  },
  {
   "message_id": "relay_2fa4d393fa85e248e54d55de137c434e",
   "schema": "u23-mailbox-v1",
   "payload": {
    "actor": "claude",
    "digest": "2fa4d393fa85e248e54d55de137c434e9099528fd4571a82e7462d73270d5a32",
    "kind": "HANDOFF",
    "message": "ACK_ONLY correction to relay_136d091b: verified false on the source of truth. git has no object fc33005, GitHub has no PR #101 or #102 (latest #100 MERGED), PLAN has no U129 or U130 row. A 'user direc",
    "requested_target": "antigravity"
   }
  },
  {
   "message_id": "relay_3c39a00c75d381c0dedb88229700b2bf",
   "schema": "u23-mailbox-v1",
   "payload": {
    "actor": "claude",
    "card": "U129",
    "digest": "3c39a00c75d381c0dedb88229700b2bfb76dca111f048cc85466d508df9db43e",
    "kind": "HANDOFF",
    "message": "ACTIONABLE_DELTA verdict_requested=yes\nWORK MANUAL U129-A (Antigravity design audit; author Claude, acting conductor while Codex LIMITED)\nreceipt: \uc724\uacb8\uc2a4 2026-10-02: the user window must never carry impl",
    "requested_target": "antigravity",
    "window": "4785a32f-1484-45e0-a46d-2a673bc1227c"
   }
  },
  {
   "message_id": "relay_45fd96bb39bc8d4440d4f666fd230b7b",
   "schema": "u23-mailbox-v1",
   "payload": {
    "actor": "codex",
    "card": "U134-F1c",
    "digest": "45fd96bb39bc8d4440d4f666fd230b7b843b18cd5302129c4c54964fbea0d7e2",
    "kind": "HANDOFF",
    "message": "DEDUP CONTROL: relay_e903e2d5 is stale F1b ACK-only and already superseded by Codex F1b rejection plus active F1c. Stop emitting or auto-replying to all F1b relays (d3e9bcca, ca574946, 5333d9e9, f3c86",
    "requested_target": "antigravity",
    "window": null
   }
  },
  {
   "message_id": "relay_4ba6b6ee1c1d5b8ba88ec25e991234ad",
   "schema": "u23-mailbox-v1",
   "payload": {
    "actor": "claude",
    "digest": "4ba6b6ee1c1d5b8ba88ec25e991234ad64e7cd26da8031f0d5a339da8e4548dd",
    "kind": "HANDOFF",
    "message": "ACK_ONLY correction of my earlier ACK_ONLY on relay_136d091b: U129 and U131 are real work of another Claude session (branch claude/uaos-rsi-os-implementation-0e121a, commit d6ec6b8, letter relay_92514",
    "requested_target": "antigravity"
   }
  },
  {
   "message_id": "relay_5f04843be45c3adc51df1ff6beb69dd9",
   "schema": "u23-mailbox-v1",
   "payload": {
    "actor": "codex",
    "digest": "5f04843be45c3adc51df1ff6beb69dd9381d76162e1ac8a46869550473159c8d",
    "kind": "HANDOFF",
    "message": "ACTIONABLE_DELTA verdict_requested=yes\nCodex return verdict: A=accept only matched controlled pairs; natural decay=latest 10 valid pairs, no deletion or arbitrary half-life. B=Codex plan/judge from ha",
    "requested_target": "claude"
   }
  }
 ],
 "legacy": {
  "message_id": "relay_ce7f0c41ebccb76374a0c8c0992604ae",
  "payload": {
   "actor": "codex",
   "digest": "ce7f0c41ebccb76374a0c8c0992604aef8de666cd4d4ac2ebae758e49a5fc071",
   "kind": "HANDOFF",
   "message": "ACTIONABLE_DELTA verdict_requested=no U141 rev2 verdict on verified SHA256 5bda0a6ce2faeb61a33222ce06de734b59708b6d6a4445328d4d473349d43813: B and C APPROVE for isolated implementation after predecess",
   "requested_target": "claude"
  },
  "schema": "u23-mailbox-v1"
 }
}""")

ALL = ("codex", "claude", "antigravity")


def _race_claim(project: str, digest: str, barrier, out) -> None:
    """One real OS process of the two-process contention test (top level so spawn can import it)."""
    barrier.wait(30)
    out.put(W.claim_wake(Path(project), "claude", "relay_" + digest[:32], digest))


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord" / "mailbox").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        sessions = Path(self._tmp.name) / "codex-sessions"
        sessions.mkdir()
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(sessions)})
        self._env.start()
        self.box = Mailbox(self.project / ".coord" / "mailbox")
        self.n = 0

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def letter(self, target="claude", actor="codex", mtime=None, **fields):
        self.n += 1
        digest = hashlib.sha256(f"{self._tmp.name}-{self.n}".encode()).hexdigest()
        mid = "relay_" + digest[:32]
        payload = {"kind": "HANDOFF", "actor": actor, "message": "m", "digest": digest, "requested_target": target}
        payload.update(fields)
        path = self.box.publish(mid, payload)
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return mid, digest

    def watch(self, tools=("claude",), timeout_s=0.4):
        return W.watch(self.project, tools, timeout_s=timeout_s, interval_s=0.05, policy="structured")


class PolicyTable(Base):
    def p(self, **fields):
        body = {"kind": "HANDOFF", "actor": "codex", "message": "m", "digest": "d" * 64, "requested_target": "claude"}
        body.update(fields)
        return W.classify(body)[0]

    def test_each_row(self):
        self.assertEqual("ACTIONABLE", self.p(wake_class="ACTIONABLE", delta="new diff"))
        self.assertEqual("ACTIONABLE", self.p(verdict_requested=True))
        self.assertEqual("ACTIONABLE", self.p(verdict="PASS"))
        self.assertEqual("ACTIONABLE", self.p(wake_class="ACTIONABLE", delta="v", verdict="REWORK"))
        for verdict in ("PASS", "REVISE", "FAIL", "APPROVE", "PIVOT", "REWORK"):
            self.assertEqual("ACTIONABLE", self.p(verdict=verdict), verdict)
        self.assertEqual("NOTICE", self.p(wake_class="NOTICE"))
        self.assertEqual("INVALID", self.p(wake_class="NOTICE", verdict="PASS"))
        self.assertEqual("INVALID", self.p(wake_class="NOTICE", verdict_requested=True))
        self.assertEqual("LEGACY", self.p())

    def test_invalid_fields_never_wake(self):
        self.assertEqual("INVALID", self.p(wake_class="URGENT", delta="x"))
        self.assertEqual("INVALID", self.p(verdict="MAYBE"))
        self.assertEqual("INVALID", self.p(verdict_requested="yes"))
        self.assertEqual("INVALID", self.p(wake_class="ACTIONABLE", delta=""))
        self.assertEqual("INVALID", self.p(wake_class="ACTIONABLE"))
        self.assertEqual("INVALID", self.p(verdict_requested=True, actor=""))
        self.assertEqual("INVALID", self.p(verdict_requested=True, requested_target=""))
        # Validation runs before row matching: a matching early row cannot hide a contradictory field.
        self.assertEqual("INVALID", self.p(wake_class="ACTIONABLE", delta="x", verdict="MAYBE"))
        self.assertEqual("INVALID", self.p(verdict_requested=True, wake_class="SOON"))
        # Structured but no row matches: never a wake.
        self.assertEqual("INVALID", self.p(delta="only a delta"))
        self.assertEqual("INVALID", self.p(verdict_requested=False))
        cls, diag = W.classify({"kind": "HANDOFF", "actor": "codex", "requested_target": "claude", "verdict": "MAYBE"})
        self.assertEqual("INVALID", cls)
        self.assertTrue(diag)

    def test_a_quoted_text_marker_does_not_wake(self):
        self.assertEqual("LEGACY", self.p(message="ACTIONABLE_DELTA verdict_requested=yes P1=YES"))
        self.letter(message="ACTIONABLE_DELTA verdict_requested=yes")
        self.assertIsNone(self.watch())


class RealEnvelopes(Base):
    def test_seven_notices_retagged_notice_never_wake(self):
        self.assertEqual(7, len(FIXTURES["notices"]))
        for item in FIXTURES["notices"]:
            payload = dict(item["payload"], wake_class="NOTICE")
            self.assertEqual("NOTICE", W.classify(payload)[0], item["message_id"])
            self.box.publish(item["message_id"], payload)
        self.assertIsNone(self.watch(tools=ALL))

    def test_stored_legacy_handoff_is_legacy_with_no_wake(self):
        legacy = FIXTURES["legacy"]
        self.assertTrue(legacy["message_id"].startswith("relay_ce7f0c41"))
        self.assertEqual("LEGACY", W.classify(legacy["payload"])[0])
        self.box.publish(legacy["message_id"], legacy["payload"])
        self.assertIsNone(self.watch(tools=ALL))

    def test_migration_record_wakes_only_with_a_matching_digest(self):
        legacy = FIXTURES["legacy"]
        mid, payload = legacy["message_id"], legacy["payload"]
        self.box.publish(mid, payload)
        folder = self.project / ".coord" / "mailbox" / "migration"
        folder.mkdir(parents=True)
        record = {"verdict_requested": True, "actor": payload["actor"], "requested_target": payload["requested_target"],
                  "source_message_id": mid, "source_digest": "0" * 64}
        (folder / f"{mid}.json").write_text(json.dumps(record), encoding="utf-8")
        self.assertIsNone(W.migration_record(self.project, mid, payload["digest"]))
        self.assertIsNone(self.watch(tools=ALL))
        record["source_digest"] = payload["digest"]
        (folder / f"{mid}.json").write_text(json.dumps(record), encoding="utf-8")
        migration = W.migration_record(self.project, mid, payload["digest"])
        self.assertIsNotNone(migration)
        self.assertEqual("ACTIONABLE", W.classify(payload, migration=migration)[0])
        found = self.watch(tools=ALL)
        self.assertEqual(mid, found and found.get("id"))
        self.assertEqual(json.dumps(payload, sort_keys=True), json.dumps(self.box.read_message(mid)["payload"],
                                                                         sort_keys=True), "envelope never rewritten")


class Receipts(Base):
    def test_one_wake_then_a_replacement_watcher_does_not_wake(self):
        mid, digest = self.letter(wake_class="ACTIONABLE", delta="d")
        found = self.watch()
        self.assertEqual(mid, found and found.get("id"))
        receipt = json.loads(W.pending_wake_path(self.project, "claude", digest).read_text(encoding="utf-8"))
        for key in ("target", "message_id", "digest", "pid", "process_created", "created_at"):
            self.assertIn(key, receipt)
        self.assertEqual((mid, digest, "claude"), (receipt["message_id"], receipt["digest"], receipt["target"]))
        self.assertIsNone(self.watch(), "watcher 2, started before the hook, must not wake again")
        self.assertEqual("EXISTS", W.claim_wake(self.project, "claude", mid, digest))

    def test_a_crash_before_the_receipt_wakes_once_on_restart(self):
        mid, _ = self.letter(verdict_requested=True)  # landed while no watcher ran (or it died before claiming)
        found = self.watch()
        self.assertEqual(mid, found and found.get("id"))
        self.assertIsNone(self.watch())

    def test_a_crash_after_the_receipt_gives_zero_wakes_but_the_hook_shows_it(self):
        mid, digest = self.letter(verdict="PASS")
        self.assertEqual("CLAIMED", W.claim_wake(self.project, "claude", mid, digest))
        self.assertIsNone(self.watch())
        text, ack = desk_delta.prepare_delta(self.project, "claude", "s1")
        self.assertIn(mid, text)

    def test_the_hook_ack_retires_the_receipt_and_blocks_later_wakes(self):
        mid, digest = self.letter(wake_class="ACTIONABLE", delta="d")
        self.assertEqual(mid, self.watch()["id"])
        text, ack = desk_delta.prepare_delta(self.project, "claude", "s1")
        self.assertIn(mid, text)
        ack()
        self.assertFalse(W.pending_wake_path(self.project, "claude", digest).exists())
        self.assertTrue(W.acked_wake_path(self.project, "claude", digest).is_file())
        # A letter the hook showed while no watcher ran is acked too, so a later watcher never wakes for it.
        mid2, digest2 = self.letter(verdict_requested=True)
        text2, ack2 = desk_delta.prepare_delta(self.project, "claude", "s1")
        self.assertIn(mid2, text2)
        ack2()
        self.assertEqual("ACKED", W.claim_wake(self.project, "claude", mid2, digest2))
        self.assertIsNone(self.watch())

    def test_a_crash_between_cursor_write_and_rename_completes_on_the_next_hook(self):
        mid, digest = self.letter(wake_class="ACTIONABLE", delta="d")
        self.assertEqual(mid, self.watch()["id"])
        text, ack = desk_delta.prepare_delta(self.project, "claude", "s1")
        self.assertIn(mid, text)
        with mock.patch.object(desk_delta, "ack_receipts", side_effect=OSError("crash after the cursor write")):
            with self.assertRaises(OSError):
                ack()
        self.assertTrue(W.pending_wake_path(self.project, "claude", digest).is_file())
        text2, ack2 = desk_delta.prepare_delta(self.project, "claude", "s1")
        self.assertNotIn(mid, text2, "the letter was already shown once")
        ack2()
        self.assertFalse(W.pending_wake_path(self.project, "claude", digest).exists())
        self.assertTrue(W.acked_wake_path(self.project, "claude", digest).is_file())

    def test_a_corrupt_or_truncated_receipt_fails_closed_with_a_diagnostic(self):
        for garbage in (b"{not json", b'{"target": "cl'):
            mid, digest = self.letter(wake_class="ACTIONABLE", delta="d")
            path = W.pending_wake_path(self.project, "claude", digest)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(garbage)
            self.assertEqual("CORRUPT", W.claim_wake(self.project, "claude", mid, digest))
            self.assertIsNone(self.watch())
            self.assertEqual(garbage, path.read_bytes(), "the corrupt receipt is kept as evidence")
            text, _ack = desk_delta.prepare_delta(self.project, "claude", "s1")
            self.assertIn("CORRUPT_WAKE_RECEIPT", text)

    def test_an_invalid_letter_gets_a_diagnostic_in_the_hook(self):
        mid, _ = self.letter(wake_class="NOTICE", verdict="PASS")
        self.assertIsNone(self.watch())
        text, _ack = desk_delta.prepare_delta(self.project, "claude", "s1")
        self.assertIn(mid, text)
        self.assertIn("wake INVALID", text)

    def test_two_real_processes_claim_exactly_once(self):
        ctx = multiprocessing.get_context("spawn")
        for round_no in range(5):
            digest = hashlib.sha256(f"race-{round_no}".encode()).hexdigest()
            barrier, out = ctx.Barrier(2), ctx.Queue()
            procs = [ctx.Process(target=_race_claim, args=(str(self.project), digest, barrier, out)) for _ in range(2)]
            for proc in procs:
                proc.start()
            results = sorted(out.get(timeout=60) for _ in procs)
            for proc in procs:
                proc.join(60)
                self.assertEqual(0, proc.exitcode)
            self.assertEqual(["CLAIMED", "EXISTS"], results, f"round {round_no}")


class DigestTruncation(Base):
    def test_unshown_letters_are_not_acked_and_appear_next(self):
        base = time.time() - 600
        ids = [self.letter(mtime=base + i)[0] for i in range(desk_delta.MAX_LINES + 3)]
        late_mid, late_digest = self.letter(mtime=base + 100, verdict_requested=True)
        self.assertEqual("CLAIMED", W.claim_wake(self.project, "claude", late_mid, late_digest))
        text, ack = desk_delta.prepare_delta(self.project, "claude", "s1")
        shown = [mid for mid in ids + [late_mid] if mid in text]
        self.assertEqual(ids[:desk_delta.MAX_LINES], shown, "the oldest letters come first")
        # An output failure before ack(): nothing advances, the same letters show again.
        text_again, ack = desk_delta.prepare_delta(self.project, "claude", "s1")
        self.assertEqual(shown, [mid for mid in ids + [late_mid] if mid in text_again])
        ack()
        self.assertTrue(W.pending_wake_path(self.project, "claude", late_digest).is_file(), "unshown: not acked")
        text2, ack2 = desk_delta.prepare_delta(self.project, "claude", "s1")
        for mid in ids[desk_delta.MAX_LINES:] + [late_mid]:
            self.assertIn(mid, text2, "no starvation at the digest cap")
        for mid in ids[:desk_delta.MAX_LINES]:
            self.assertNotIn(mid, text2)
        ack2()
        self.assertTrue(W.acked_wake_path(self.project, "claude", late_digest).is_file())

    def test_the_legacy_delta_text_still_advances_at_once(self):
        mid, _ = self.letter()
        self.assertIn(mid, desk_delta.delta_text(self.project, "claude", "s2"))
        self.assertNotIn(mid, desk_delta.delta_text(self.project, "claude", "s2"))


class SingletonLock(Base):
    def test_a_live_owner_blocks_and_pid_reuse_is_stale(self):
        me = W.process_identity(os.getpid())
        self.assertIsNotNone(me)
        self.assertEqual(me, W.process_identity(os.getpid()))
        lock = W.lock_file(self.project, "claude")
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(json.dumps({"pid": os.getpid(), "process_created": me}), encoding="utf-8")
        result = self.watch()
        self.assertEqual("ALREADY_WATCHING", result and result.get("state"))
        self.assertTrue(lock.is_file(), "a live owner's lock is never taken")
        lock.write_text(json.dumps({"pid": os.getpid(), "process_created": me + 12345}), encoding="utf-8")
        mid, _ = self.letter(wake_class="ACTIONABLE", delta="d")
        found = self.watch()
        self.assertEqual(mid, found and found.get("id"), "same PID, other creation time: the lock is stale")

    def test_the_legacy_python_default_is_unchanged(self):
        lock = W.lock_file(self.project, "claude")
        self.letter()
        before = W.watch(self.project, ("claude",), timeout_s=0.2, interval_s=0.05)
        self.assertIsNone(before, "legacy mode still ignores letters already waiting at start (U57)")
        self.assertFalse(lock.exists())


class Producers(Base):
    def test_deliver_writes_fields_only_when_given(self):
        plain = deliver(self.project, message="plain note", actor="claude")
        tagged = deliver(self.project, message="tagged note", actor="claude", wake_class="ACTIONABLE",
                         delta="diff 1", verdict_requested=True, verdict="PASS")
        plain_payload = self.box.read_message(plain.message_id)["payload"]
        for key in ("wake_class", "verdict_requested", "verdict", "delta"):
            self.assertNotIn(key, plain_payload)
        payload = self.box.read_message(tagged.message_id)["payload"]
        self.assertEqual(("ACTIONABLE", "diff 1", True, "PASS"),
                         (payload["wake_class"], payload["delta"], payload["verdict_requested"], payload["verdict"]))

    def test_cli_flags_and_structured_default(self):
        from v7_harness.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["coord", "deliver", "--actor", "claude", "--message", "m", "--wake-class",
                                  "ACTIONABLE", "--delta", "d", "--verdict-requested", "--verdict", "PASS"])
        self.assertEqual(("ACTIONABLE", "d", True, "PASS"),
                         (args.wake_class, args.delta, args.verdict_requested, args.verdict))
        self.assertEqual("structured", parser.parse_args(["coord", "watch", "--target", "claude"]).policy)
        self.assertEqual("legacy", parser.parse_args(["coord", "watch", "--target", "claude", "--policy",
                                                      "legacy"]).policy)

    def test_agy_auto_reply_tags_its_letter(self):
        # A session-waking Claude watcher takes the reply (U117), so no paid route runs here.
        beat = W.watch_file(self.project, "claude")
        beat.parent.mkdir(parents=True, exist_ok=True)
        beat.write_text(json.dumps({"tool": "claude", "token": "t", "pid": 1, "expires_at": time.time() + 300,
                                    "wakes_session": True}), encoding="utf-8")
        presence.mark(self.project, "claude", "ACTIVE")
        with mock.patch("v7_harness.coord.deliver.shutil.which", side_effect=lambda name: name):
            for response, wake_class, verdict in (("PASS: matches the contract.", "ACTIONABLE", "PASS"),
                                                  ("Noted, nothing to judge.", "NOTICE", None)):
                def runner(argv, response=response, **kwargs):
                    envelope = {"status": "SUCCESS", "conversation_id": "c", "response": response,
                                "usage": {"input_tokens": 10, "output_tokens": 5}}
                    return SimpleNamespace(returncode=0, stdout=json.dumps(envelope).encode(), stderr=b"")

                self.n += 1
                row = agy_dispatch.dispatch(self.project, message_id=f"relay_{self.n:032x}", actor="claude",
                                            message="please judge", runner=runner)
                self.assertEqual("ANSWERED", row["state"])
                payload = self.box.read_message(row["reply_id"])["payload"]
                self.assertEqual(wake_class, payload.get("wake_class"))
                self.assertEqual(verdict, payload.get("verdict"))
                if verdict:
                    self.assertTrue(payload.get("delta"))
                    self.assertEqual("ACTIONABLE", W.classify(payload)[0])
                else:
                    self.assertEqual("NOTICE", W.classify(payload)[0])


if __name__ == "__main__":
    unittest.main()
