"""U329 gates: mid-card message triage, flood control, user exemption, real parallel appends. No network, no paid call."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord import msg_triage as mt

REPO = Path(__file__).resolve().parents[1]
T0 = 2_000_000_000.0
CARD = "U900"


def msg(i, sender="claude", ts=None, **kw):
    base = {"id": f"m{i}", "sender": sender, "text": f"unique text {i}", "ts": T0 + i if ts is None else ts}
    base.update(kw)
    return base


def recv(root, receiver, card, text, **kw):
    """receive_user_message as the native host path calls it: with the origin proof it authenticated."""
    mid = kw.get("native_event_id") or kw.get("msg_id")
    kw.setdefault("origin_proof", mt.origin_proof_for(root, mid, text, card))
    return mt.receive_user_message(root, receiver, card, text, **kw)


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._keys = tempfile.TemporaryDirectory()  # the signing key lives outside the workspace; tests get their own dir
        self._old_key_dir = os.environ.get("UAOS_TRIAGE_KEY_DIR")
        os.environ["UAOS_TRIAGE_KEY_DIR"] = self._keys.name

    def tearDown(self):
        if self._old_key_dir is None:
            os.environ.pop("UAOS_TRIAGE_KEY_DIR", None)
        else:
            os.environ["UAOS_TRIAGE_KEY_DIR"] = self._old_key_dir
        self._keys.cleanup()
        self._tmp.cleanup()

    def put(self, *messages, to="codex"):
        for m in messages:
            if m.get("kind") == "user":  # a genuine user message carries the host's provenance stamp
                m = {**m, "auth": mt.user_auth(self.root, m["id"], m["text"], CARD)}
            mt.submit(self.root, to, CARD, m)

    def run_triage(self, now=None, **kw):
        return mt.triage(self.root, "codex", CARD, now=T0 + 100 if now is None else now, **kw)


class Classification(Base):
    def test_four_classes(self):
        self.put(msg(1, tags=["SAFETY"]), msg(2, evidence="counterexample", cost_pct=5, sender="antigravity"),
                 msg(3, sender="antigravity", cost_pct=5), msg(4, card="U1", sender="antigravity"))
        d = self.run_triage()["decisions"]
        self.assertEqual(["P0", "ADOPT", "DEFER", "ACK"], [d[f"m{i}"]["class"] for i in range(1, 5)])

    def test_dedupe_merges_same_digest_and_redelivery_counts_once(self):
        self.put(msg(1, text="Same   Idea", evidence="e"), msg(2, text="same idea", sender="antigravity", evidence="e"),
                 msg(1, text="Same   Idea", evidence="e"))
        out = self.run_triage()
        self.assertEqual(2, len(out["decisions"]))
        self.assertEqual("duplicate", out["decisions"]["m2"]["why"])
        self.assertEqual("m1", out["decisions"]["m2"]["merged_into"])

    def test_reply_to_reply_never_preempts(self):
        self.put(msg(1, evidence="e", cost_pct=1), msg(2, reply_to="m1", evidence="e", cost_pct=1, sender="a"),
                 msg(3, reply_to="m2", evidence="e", cost_pct=1, sender="b"))
        d = self.run_triage()["decisions"]
        self.assertEqual("ADOPT", d["m2"]["class"])
        self.assertEqual("ACK", d["m3"]["class"])
        self.assertIn("reply-to-reply", d["m3"]["why"])

    def test_late_progress_only_small_fixes(self):
        self.put(msg(1, evidence="e", cost_pct=1), msg(2, evidence="e", cost_pct=1, small=True, sender="b"))
        d = self.run_triage(progress=0.85)["decisions"]
        self.assertEqual(("DEFER", "ADOPT"), (d["m1"]["class"], d["m2"]["class"]))

    def test_cost_over_twenty_percent_defers(self):
        self.put(msg(1, evidence="e", cost_pct=21))
        self.assertEqual("DEFER", self.run_triage()["decisions"]["m1"]["class"])

    def test_conflicting_proposals_go_to_conductor_not_adopted(self):
        self.put(msg(1, evidence="e", cost_pct=1, topic="t", stance="a"),
                 msg(2, sender="antigravity", evidence="e", cost_pct=1, topic="t", stance="b"))
        out = self.run_triage()
        self.assertEqual(["m1", "m2"], sorted(out["escalate"]))


class Budget(Base):
    def test_sender_limit_three_adopts_per_window(self):
        self.put(*[msg(i, evidence="e", cost_pct=1, ts=T0 + i) for i in range(1, 6)])
        classes = [self.run_triage()["decisions"][f"m{i}"]["class"] for i in range(1, 6)]
        self.assertEqual(["ADOPT"] * 3 + ["DEFER"] * 2, classes)

    def test_pivot_cap_one_per_card(self):
        self.put(msg(1, evidence="e", cost_pct=1, pivot=True), msg(2, sender="antigravity", evidence="e",
                                                                   cost_pct=1, pivot=True))
        self.run_triage()
        first = mt.judge_adoption(self.root, "codex", CARD, "m1", acceptance_gain=True, pivot=True)
        self.assertTrue(first["adopted"])
        second = mt.judge_adoption(self.root, "codex", CARD, "m2", acceptance_gain=True, pivot=True)
        self.assertEqual((False, "pivot cap reached"), (second["adopted"], second["why"]))
        self.assertEqual("DEFER", self.run_triage()["decisions"]["m2"]["class"])

    def test_pivot_cap_defers_new_candidates_after_first_pivot(self):
        self.put(msg(1, evidence="e", cost_pct=1, pivot=True))
        self.run_triage()
        mt.judge_adoption(self.root, "codex", CARD, "m1", acceptance_gain=True, pivot=True)
        self.put(msg(2, sender="antigravity", evidence="e", cost_pct=1, pivot=True, ts=T0 + 5))
        self.assertEqual("DEFER", self.run_triage()["decisions"]["m2"]["class"])

    def test_author_never_judges_and_no_gain_is_deferred(self):
        self.put(msg(1, sender="codex", evidence="e", cost_pct=1), msg(2, evidence="e", cost_pct=1))
        self.run_triage()
        self.assertEqual("author must not judge", mt.judge_adoption(self.root, "codex", CARD, "m1",
                                                                    acceptance_gain=True)["why"])
        self.assertFalse(mt.judge_adoption(self.root, "codex", CARD, "m2")["adopted"])


class Breaker(Base):
    def flood(self, n, start=0, step=10):
        self.put(*[msg(i, sender=("claude", "antigravity")[i % 2], ts=T0 + start + (i - 1) * step) for i in range(1, n + 1)])

    def test_enters_over_ten_in_window_only_p0_passes_and_exits_after_15_quiet_minutes(self):
        self.flood(12, step=10)
        self.put(msg(99, tags=["SECURITY"], ts=T0 + 125, sender="antigravity"))
        out = self.run_triage(now=T0 + 130)
        self.assertTrue(out["frozen"])
        self.assertEqual("P0", out["decisions"]["m99"]["class"])
        self.assertEqual("DEFER", out["decisions"]["m12"]["class"])
        still = mt.breaker(mt.load(self.root, "codex", CARD), T0 + 125 + mt.QUIET_S - 1)
        self.assertTrue(still["frozen_now"])
        self.assertFalse(mt.breaker(mt.load(self.root, "codex", CARD), T0 + 125 + mt.QUIET_S)["frozen_now"])

    def test_ten_messages_do_not_trip(self):
        self.flood(10, step=10)
        self.assertFalse(self.run_triage()["frozen"])

    def test_user_messages_are_exempt_verbatim_and_never_merged_or_frozen(self):
        self.flood(14, step=5)
        text = "  정확히  이 문장 그대로  "
        self.put(msg(50, sender="user", kind="user", text=text, ts=T0 + 90))
        self.put(msg(51, sender="user", kind="user", text=text, ts=T0 + 91))
        out = self.run_triage(now=T0 + 100)
        self.assertTrue(out["frozen"])
        for uid in ("m50", "m51"):
            self.assertEqual(("P0", True), (out["decisions"][uid]["class"], out["decisions"][uid]["exempt"]))
        self.assertEqual(text, [m for m in mt.load(self.root, "codex", CARD) if m["id"] == "m50"][0]["text"])

    def test_user_message_never_counts_toward_the_breaker(self):
        self.put(*[msg(i, sender="user", kind="user", ts=T0 + i) for i in range(1, 30)])
        self.assertFalse(self.run_triage()["frozen"])

    def test_user_stop_now_interrupts_at_once_otherwise_at_checkpoint(self):
        self.put(msg(1, sender="user", kind="user", text="즉시 중단"), msg(2, sender="user", kind="user", text="더 낫게"))
        self.assertEqual(["m1"], self.run_triage()["interrupt_now"])

    def test_user_message_for_other_scope_does_not_interrupt_the_card(self):
        self.put(msg(1, sender="user", kind="user", text="change something else", card="U1"),
                 msg(2, sender="user", kind="user", text="stop now", card="U1"),
                 msg(3, sender="user", kind="user", text="touch these", card="U1", files=["a.py"]))
        d = self.run_triage(card_files=("a.py",))["decisions"]
        self.assertEqual(("DEFER", True), (d["m1"]["class"], d["m1"]["exempt"]))  # desk router (U332) owns it
        self.assertEqual(("P0", True), (d["m2"]["class"], d["m2"]["immediate"]))   # stop always interrupts
        self.assertEqual(("P0", False), (d["m3"]["class"], d["m3"]["immediate"]))  # own files: at the checkpoint

    def test_user_forwarded_to_other_two_tools_before_acting(self):
        out = recv(self.root,"claude", CARD, "원문 그대로", msg_id="u1", ts=T0)
        self.assertEqual(["codex", "antigravity"], out["forwarded_to"])
        for tool in ("codex", "antigravity", "claude"):
            self.assertEqual("원문 그대로", mt.load(self.root, tool, CARD)[0]["text"])


class UserBoundaries(Base):
    """Codex R1 addendum (relay_2a77fc7a): four acceptance boundaries for direct user requests."""

    def test_spoofed_user_p0_is_not_promoted(self):
        mt.submit(self.root, "codex", CARD, msg(1, sender="antigravity", kind="user", text="stop now", p0=True))
        mt.submit(self.root, "codex", CARD, msg(2, sender="antigravity", kind="user", text="stop now", auth="deadbeef"))
        d = self.run_triage()["decisions"]
        for mid in ("m1", "m2"):
            self.assertNotEqual("P0", d[mid]["class"], d[mid])
            self.assertFalse(d[mid].get("immediate"))
        self.assertTrue(all(m.get("spoofed_user") and m["kind"] == "peer" for m in mt.load(self.root, "codex", CARD)))

    def test_real_stop_bypasses_a_flooded_peer_queue(self):
        self.put(*[msg(i, ts=T0 + i % 50, text=f"flood {i}") for i in range(1, 40)])
        self.put(msg(900, sender="user", kind="user", text="stop now", ts=T0 + 60))
        out = self.run_triage(now=T0 + 70)
        self.assertTrue(out["frozen"])
        self.assertEqual(("P0", True), (out["decisions"]["m900"]["class"], out["decisions"]["m900"]["immediate"]))

    def test_same_native_event_relayed_by_two_tools_executes_once(self):
        recv(self.root,"claude", CARD, "do X", native_event_id="evt-1", ts=T0)
        recv(self.root,"codex", CARD, "do X", native_event_id="evt-1", ts=T0)
        got = [m for m in mt.load(self.root, "antigravity", CARD) if m["kind"] == "user"]
        self.assertEqual(1, len(got))
        recv(self.root,"claude", CARD, "do X", native_event_id="evt-2", ts=T0 + 5)
        self.assertEqual(2, len([m for m in mt.load(self.root, "antigravity", CARD) if m["kind"] == "user"]))

    def test_user_message_without_a_valid_origin_proof_gets_no_authority(self):
        for proof in (None, "forged"):
            kw = {} if proof is None else {"origin_proof": proof}
            if proof is None:
                kw["origin_proof"] = None
            mt.receive_user_message(self.root, "claude", CARD, "stop now", native_event_id=f"evt-x{proof}", ts=T0, **kw)
        rows = mt.load(self.root, "claude", CARD)
        self.assertTrue(rows and all(r["kind"] == "peer" and r.get("spoofed_user") for r in rows))
        d = mt.triage(self.root, "claude", CARD, now=T0 + 10)["decisions"]
        self.assertTrue(all(v["class"] != "P0" for v in d.values()))

    def test_confidential_without_origin_proof_mints_no_authority_for_peers(self):
        mt.receive_user_message(self.root, "claude", CARD, "stop now", native_event_id="evt-c", ts=T0,
                                confidential=True, origin_proof=None)
        for tool in ("codex", "antigravity"):
            rec = mt.load(self.root, tool, CARD)[0]
            self.assertEqual(("peer", True), (rec["kind"], rec.get("spoofed_user")))
            self.assertNotIn("auth", rec)
            d = mt.triage(self.root, tool, CARD, now=T0 + 10)["decisions"]
            self.assertNotEqual("P0", d["evt-c"]["class"])

    def test_auth_is_bound_to_the_card_and_never_stored(self):
        auth = mt.user_auth(self.root, "u1", "do X", "U900")
        mt.submit(self.root, "codex", "U900", {"id": "u1", "sender": "user", "kind": "user", "text": "do X", "auth": auth,
                                               "p0": True})
        stored = mt.load(self.root, "codex", "U900")[0]
        self.assertEqual("user", stored["kind"])
        self.assertNotIn("auth", stored)  # nothing left to replay
        mt.submit(self.root, "codex", "U901", {"id": "u1", "sender": "user", "kind": "user", "text": "do X",
                                               "auth": auth, "p0": True, "tags": ["SAFETY"]})
        replay = mt.load(self.root, "codex", "U901")[0]
        self.assertEqual(("peer", True), (replay["kind"], replay.get("spoofed_user")))
        self.assertNotIn("tags", replay)

    def test_origin_proof_is_not_valid_as_auth_and_fields_cannot_collide(self):
        proof = mt.origin_proof_for(self.root, "e1", "t", "U900")
        self.assertNotEqual(proof, mt.user_auth(self.root, "e1", "t", "U900"))
        self.assertNotEqual(proof, mt.user_auth(self.root, "origin:e1", "t", "U900"))
        self.assertNotEqual(mt.user_auth(self.root, "a\nb", "c", "U"), mt.user_auth(self.root, "a", "b\nc", "U"))

    def test_signing_key_is_outside_the_workspace_full_length_and_race_safe(self):
        import threading

        keys = set()

        def go():
            keys.add(mt._key(self.root))

        threads = [threading.Thread(target=go) for _ in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(1, len(keys))
        self.assertEqual(mt.KEY_BYTES, len(next(iter(keys))))
        self.assertFalse((self.root / mt.TRIAGE_DIR / ".user_key").exists())
        self.assertFalse(Path(mt._key_file(self.root)).is_relative_to(self.root))

    def test_one_message_conflicting_with_two_escalates_all_three_with_separate_records(self):
        self.put(msg(1, evidence="e", sender="antigravity", conflicts_with=["m2", "m3"]),
                 msg(2, evidence="e", sender="claude"), msg(3, evidence="e", sender="antigravity"))
        d = self.run_triage()["decisions"]
        self.assertEqual({"ESCALATE"}, {d[i]["class"] for i in ("m1", "m2", "m3")})
        self.assertIsNot(d["m2"], d["m3"])

    def test_topic_escalation_does_not_hide_a_declared_conflict_with_it(self):
        self.put(msg(1, evidence="e", topic="t", stance="a"), msg(2, evidence="e", sender="antigravity", topic="t", stance="b"),
                 msg(3, evidence="e", sender="claude", conflicts_with=["m1"]))
        d = self.run_triage()["decisions"]
        self.assertEqual({"ESCALATE"}, {d[i]["class"] for i in ("m1", "m2", "m3")})

    def test_an_adopted_message_is_not_overwritten_by_a_later_conflict(self):
        self.put(msg(1, evidence="e", sender="antigravity", pivot=True))
        self.run_triage()
        mt.judge_adoption(self.root, "codex", CARD, "m1", acceptance_gain=True, pivot=True)
        self.put(msg(2, evidence="e", sender="claude", conflicts_with=["m1"]))
        d = self.run_triage(now=T0 + 200)["decisions"]
        self.assertEqual(("ADOPT", True), (d["m1"]["class"], d["m1"].get("adopted")))

    def test_user_adoption_is_recorded_and_idempotent(self):
        self.put(msg(1, kind="user", text="please change plan"))
        self.run_triage()
        first = mt.judge_adoption(self.root, "codex", CARD, "m1", acceptance_gain=True, pivot=False)
        again = mt.judge_adoption(self.root, "codex", CARD, "m1", acceptance_gain=True, pivot=False)
        self.assertEqual((True, True), (first["adopted"], again["adopted"]))
        self.assertTrue(mt.triage(self.root, "codex", CARD, now=T0 + 300)["decisions"]["m1"].get("adopted"))

    def test_judge_adoption_is_idempotent(self):
        self.put(msg(1, evidence="e", sender="antigravity", pivot=True), msg(2, evidence="e", sender="antigravity",
                                                                          pivot=True))
        self.run_triage()
        first = mt.judge_adoption(self.root, "codex", CARD, "m1", acceptance_gain=True, pivot=True)
        again = mt.judge_adoption(self.root, "codex", CARD, "m1", acceptance_gain=True, pivot=True)
        self.assertEqual((True, True), (first["adopted"], again["adopted"]))
        self.assertEqual(1, mt._state(self.root, "codex", CARD)["pivots"])  # not double-counted, not downgraded
        self.assertEqual(1, len((mt._paths(self.root, "codex", CARD)[0].with_suffix(".ledger.jsonl"))
                                .read_text(encoding="utf-8").splitlines()))

    def test_an_earlier_ack_or_defer_does_not_suppress_a_later_adopt_candidate(self):
        self.put(msg(1, text="same idea", sender="antigravity"),  # no evidence -> DEFER
                 msg(2, text="same idea", sender="claude", evidence="e"))
        d = self.run_triage()["decisions"]
        self.assertEqual("DEFER", d["m1"]["class"])
        self.assertEqual("ADOPT", d["m2"]["class"])

    def test_safety_p0_is_routed_before_the_duplicate_check(self):
        self.put(msg(1, text="same alert", sender="antigravity"), msg(2, text="same alert", tags=["SAFETY"]))
        d = self.run_triage()["decisions"]
        self.assertEqual("P0", d["m2"]["class"])  # not swallowed as a duplicate of m1

    def test_adoption_ledger_uses_the_sanitized_path(self):
        mt.submit(self.root, "codex", "../../evil", msg(1, sender="antigravity", evidence="e", cost_pct=1))
        mt.triage(self.root, "codex", "../../evil", now=T0 + 100)
        out = mt.judge_adoption(self.root, "codex", "../../evil", "m1", acceptance_gain=True)
        self.assertTrue(out.get("adopted"), out)
        self.assertFalse((self.root.parent / "evil.ledger.jsonl").exists())
        ledgers = list((self.root / mt.TRIAGE_DIR / "codex").glob("*.ledger.jsonl"))
        self.assertEqual(1, len(ledgers), ledgers)
        self.assertNotIn("..", ledgers[0].name)

    def test_confidential_text_stays_at_origin(self):
        secret = "the launch code is 1234"
        out = recv(self.root,"claude", CARD, secret, native_event_id="evt-3", ts=T0, confidential=True)
        self.assertTrue(out["opaque"])
        self.assertEqual(secret, mt.load(self.root, "claude", CARD)[0]["text"])
        for tool in ("codex", "antigravity"):
            rec = mt.load(self.root, tool, CARD)[0]
            self.assertNotIn("1234", json.dumps(rec))
            self.assertEqual("evt-3", rec["opaque_ref"])

    def test_receiver_lane_needs_no_peer_availability(self):
        real = mt.submit
        calls = []

        def flaky(project, to, card, message):
            calls.append(to)
            if to != "claude":
                raise OSError("peer lane unavailable")
            return real(project, to, card, message)

        mt.submit = flaky
        try:
            out = recv(self.root,"claude", CARD, "quick task", native_event_id="evt-4", ts=T0)
        finally:
            mt.submit = real
        self.assertEqual("claude", calls[0])  # the receiver's own durable record is written first
        self.assertEqual([], out["forwarded_to"])
        self.assertEqual("quick task", mt.load(self.root, "claude", CARD)[0]["text"])


class QueueCap(Base):
    def test_cap_50_archives_ack_defer_but_never_p0_adopt_user(self):
        keep = [msg(1, tags=["SAFETY"], ts=T0), msg(2, sender="antigravity", evidence="e", cost_pct=1, ts=T0 + 1),
                msg(3, sender="user", kind="user", ts=T0 + 2)]
        self.put(*keep)
        self.put(*[msg(i, ts=T0 + i, card="other") for i in range(10, 70)])
        self.run_triage(now=T0 + 100000)
        left = {m["id"] for m in mt.load(self.root, "codex", CARD)}
        self.assertLessEqual(len(left), mt.QUEUE_CAP)
        self.assertTrue({"m1", "m2", "m3"} <= left)


WORKER = """
import sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from v7_harness.coord import msg_triage as mt
root, who = Path(sys.argv[2]), sys.argv[3]
for i in range(34):
    mt.submit(root, 'codex', 'U900', {'id': f'{who}-{i}', 'sender': who, 'text': f'{who} says {i}', 'ts': 2_000_000_000.0 + i,
                                      'tags': ['SAFETY'] if i == 0 else []})
"""


class RealParallel(Base):
    def test_three_processes_34_messages_each_lose_no_line_and_no_p0(self):
        script = Path(self.root) / "worker.py"
        script.write_text(WORKER, encoding="utf-8")
        procs = [subprocess.Popen([sys.executable, str(script), str(REPO), str(self.root), who],
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                 for who in ("claude", "codex2", "antigravity")]
        for p in procs:
            self.assertEqual(0, p.wait(timeout=50))
        log = mt._paths(self.root, "codex", CARD)[0]
        lines = log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(102, len(lines))
        self.assertEqual(102, len({json.loads(x)["id"] for x in lines}))  # every line intact JSON, none lost
        out = self.run_triage(now=T0 + 40)
        p0 = [i for i, d in out["decisions"].items() if d["class"] == "P0"]
        self.assertEqual(sorted(f"{w}-0" for w in ("claude", "codex2", "antigravity")), sorted(p0))  # no P0 lost
        self.assertTrue(out["frozen"])  # 102 messages in 34 s: the breaker held the flood


if __name__ == "__main__":
    unittest.main()
