"""U329 gates: directive council, no infinite wait, wait-cycle break, stall.py silent-ACTIVE reroute. No network."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from v7_harness.coord import council, msg_triage, nowait, stall

REPO = Path(__file__).resolve().parents[1]
NOW = 2_000_000_000.0


def desk(**kw):
    """name=age_s -> ACTIVE with a beat that old; name=None -> LIMITED."""
    return {t: ({"state": "ACTIVE", "observed_at": NOW - age} if age is not None else {"state": "LIMITED"})
            for t, age in kw.items()}


class Tmp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / ".coord").mkdir()
        (self.root / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()


class NoWait(Tmp):
    def test_only_fresh_active_peers_are_awaited(self):
        plan = nowait.plan_wait(desk(claude=0, codex=5, antigravity=700 * 3600), "claude", NOW)
        self.assertEqual((["codex"], ["antigravity"]), (plan["wait_for"], plan["abstain"]))
        self.assertEqual(NOW + nowait.REPLY_DEADLINE_S, plan["deadline"])

    def test_unknown_age_fails_closed(self):
        self.assertFalse(nowait.peer_alive({"state": "ACTIVE"}, NOW))

    def test_deadline_turns_silence_into_abstention_and_zero_responders_flag(self):
        plan = nowait.plan_wait(desk(claude=0, codex=1, antigravity=1), "claude", NOW)
        self.assertFalse(nowait.settle(plan, [], NOW + 5)["done"])
        end = nowait.settle(plan, [], NOW + nowait.REPLY_DEADLINE_S)
        self.assertEqual((True, True, ["antigravity", "codex"]), (end["done"], end["zero_responders"], end["abstained"]))

    def test_wait_cycle_is_broken_by_authority_order(self):
        nowait.add_wait(self.root, "claude", "codex", "verdict", now=NOW)
        out = nowait.add_wait(self.root, "codex", "claude", "reply", now=NOW + 1)
        self.assertEqual(["claude", "codex"], sorted(out["broken"]["cycle"]))
        self.assertEqual("codex", out["broken"]["released"])
        graph = json.loads((self.root / nowait.GRAPH).read_text(encoding="utf-8"))
        self.assertEqual([("claude", "codex")], [(e["waiter"], e["on"]) for e in graph])
        self.assertEqual([], nowait.find_cycle(graph))

    def test_three_way_cycle_and_expired_edges_dropped(self):
        nowait.add_wait(self.root, "antigravity", "claude", "x", now=NOW)
        nowait.add_wait(self.root, "claude", "codex", "x", now=NOW)
        out = nowait.add_wait(self.root, "codex", "antigravity", "x", now=NOW)
        self.assertEqual("codex", out["broken"]["released"])
        later = nowait.add_wait(self.root, "claude", "antigravity", "y", now=NOW + 10 * nowait.REPLY_DEADLINE_S)
        self.assertIsNone(later["broken"])

    def test_published_is_not_ack_then_next_path_then_abstain(self):
        self.assertEqual("PUBLISHED", nowait.delivery_state(NOW, None, NOW + 3)["state"])
        late = nowait.delivery_state(NOW, None, NOW + 11)
        self.assertEqual(("ACK_OVERDUE", "window"), (late["state"], late["next"]))
        last = nowait.delivery_state(NOW, None, NOW + 11, tried=nowait.DELIVERY_PATHS)
        self.assertTrue(last["abstain"])
        self.assertEqual("ACKED", nowait.delivery_state(NOW, NOW + 2, NOW + 99)["state"])

    def test_same_cause_three_times_blocks_the_path(self):
        for i in range(2):
            self.assertEqual("RETRY", nowait.record_wait_failure(self.root, "U1", "letter", "no-ack", now=NOW + i)["log"])
        self.assertFalse(nowait.path_blocked(self.root, "U1", "letter"))
        self.assertEqual("BLOCKED", nowait.record_wait_failure(self.root, "U1", "letter", "no-ack", now=NOW + 3)["log"])
        self.assertTrue(nowait.path_blocked(self.root, "U1", "letter"))
        self.assertFalse(nowait.path_blocked(self.root, "U2", "letter"))


class Council(Tmp):
    def open(self, d, topic="Docs Layout", kind="policy", opener="claude", **kw):
        return council.open_council(self.root, topic=topic, directive="사용자 원문  그대로\n두 줄", opener=opener,
                                    desk=d, now=NOW, kind=kind, **kw)

    def test_silent_peers_abstain_up_front_and_council_decides_alone_marked_re_review(self):
        out = self.open(desk(claude=0, codex=700 * 3600, antigravity=None))
        self.assertEqual(["claude"], out["participants"])
        council.submit_draft(self.root, out["id"], "claude", "A")
        res = council.advance(self.root, out["id"], now=NOW + 1)
        self.assertEqual("DECIDED", res["state"])
        self.assertTrue(res["decision"]["re_review"])
        adr = (self.root / ".coord" / "decisions" / f"{out['id']}.md").read_text(encoding="utf-8")
        self.assertIn("사용자 원문  그대로", adr)
        self.assertIn("re_review: yes", adr)

    def test_zero_responders_conductor_decides_alone(self):
        out = self.open(desk(claude=0, codex=1, antigravity=1))
        res = council.advance(self.root, out["id"], now=NOW + council.ROUND_DEADLINE_S)
        self.assertEqual(("DECIDED", "conductor_alone", True),
                         (res["state"], res["decision"]["method"], res["decision"]["re_review"]))

    def test_alive_but_silent_peer_times_out_in_round_one_then_decides(self):
        out = self.open(desk(claude=0, codex=1, antigravity=1))
        council.submit_draft(self.root, out["id"], "claude", "A")
        self.assertEqual("ROUND1", council.advance(self.root, out["id"], now=NOW + 5)["state"])
        res = council.advance(self.root, out["id"], now=NOW + council.ROUND_DEADLINE_S)
        self.assertEqual("DECIDED", res["state"])
        self.assertEqual(["claude"], res["decision"]["responders"])
        self.assertEqual(["antigravity", "codex"], res["decision"]["abstained"])

    def test_independent_drafts_hidden_then_round_two_then_two_of_three(self):
        out = self.open(desk(claude=0, codex=1, antigravity=1))
        cid = out["id"]
        council.submit_draft(self.root, cid, "claude", "A")
        self.assertEqual({}, council.visible_drafts(self.root, cid, "codex"))
        council.submit_draft(self.root, cid, "codex", "A")
        council.submit_draft(self.root, cid, "antigravity", "B")
        self.assertEqual("ROUND2", council.advance(self.root, cid, now=NOW + 2)["state"])
        self.assertEqual(3, len(council.visible_drafts(self.root, cid, "codex")))
        for t in ("claude", "codex", "antigravity"):
            council.submit_critique(self.root, cid, t, "ok")
        res = council.advance(self.root, cid, now=NOW + 3)
        self.assertEqual(("consensus_2of3", "a"), (res["decision"]["method"], res["decision"]["outcome"]))
        self.assertFalse(res["decision"]["re_review"])

    def test_no_dissent_stops_early_without_round_two(self):
        out = self.open(desk(claude=0, codex=1, antigravity=1))
        for t in ("claude", "codex", "antigravity"):
            council.submit_draft(self.root, out["id"], t, "same")
        res = council.advance(self.root, out["id"], now=NOW + 1)
        self.assertEqual(("DECIDED", "early stop: no dissent"), (res["state"], res["decision"]["closed_by"]))

    def test_code_kind_decides_by_evidence_and_tie_goes_to_conductor(self):
        out = self.open(desk(claude=0, codex=1, antigravity=None), kind="code")
        council.submit_draft(self.root, out["id"], "claude", "X", evidence_score=2)
        council.submit_draft(self.root, out["id"], "codex", "Y", evidence_score=5)
        council.advance(self.root, out["id"], now=NOW + 1)
        res = council.advance(self.root, out["id"], now=NOW + council.ROUND_DEADLINE_S * 3)
        self.assertEqual(("evidence", "y"), (res["decision"]["method"], res["decision"]["outcome"].lower()))
        tie = self.open(desk(claude=0, codex=1, antigravity=None), topic="other", kind="code")
        council.submit_draft(self.root, tie["id"], "claude", "X", evidence_score=3)
        council.submit_draft(self.root, tie["id"], "codex", "Y", evidence_score=3)
        council.advance(self.root, tie["id"], now=NOW + 1)
        res = council.advance(self.root, tie["id"], now=NOW + council.ROUND_DEADLINE_S * 3)
        self.assertEqual(("conductor_tiebreak", "codex"), (res["decision"]["method"], res["decision"]["by"]))

    def test_one_council_per_topic_max_two_open_third_queued_and_promoted(self):
        d = desk(claude=0, codex=None, antigravity=None)
        a = self.open(d, topic="one")
        joined = self.open(d, topic="one")
        self.assertEqual((a["id"], True), (joined["id"], joined["joined"]))
        self.open(d, topic="two")
        third = self.open(d, topic="three")
        self.assertEqual("QUEUED", third["state"])
        council.submit_draft(self.root, a["id"], "claude", "A")
        council.advance(self.root, a["id"], now=NOW + 1)
        self.assertEqual("ROUND1", council.advance(self.root, third["id"], now=NOW + 2)["state"])

    def test_late_reply_is_an_adoption_candidate_not_a_reversal(self):
        out = self.open(desk(claude=0, codex=None, antigravity=None))
        council.submit_draft(self.root, out["id"], "claude", "A")
        council.advance(self.root, out["id"], now=NOW + 1)
        council.late_reply(self.root, out["id"], "codex", "better idea", receiver="claude", card="U1", now=NOW + 500)
        self.assertEqual("DECIDED", council.advance(self.root, out["id"], now=NOW + 501)["state"])
        self.assertEqual(1, len(msg_triage.load(self.root, "claude", "U1")))

    def test_hard_time_limit_forces_a_decision(self):
        out = self.open(desk(claude=0, codex=1, antigravity=1))
        council.submit_draft(self.root, out["id"], "claude", "A")
        council.submit_draft(self.root, out["id"], "codex", "B")
        council.advance(self.root, out["id"], now=NOW + council.ROUND_DEADLINE_S)  # -> ROUND2, nobody critiques
        res = council.advance(self.root, out["id"], now=NOW + council.COUNCIL_MAX_S)
        self.assertEqual("DECIDED", res["state"])

    def test_real_time_drive_with_silent_peers_finishes_within_a_timeout(self):
        """Subprocess with real clock and a 1 s round deadline: it must end, and the parent kills it at 50 s."""
        code = (
            "import sys, time; sys.path.insert(0, sys.argv[1]); from pathlib import Path\n"
            "from v7_harness.coord import council\n"
            "now = time.time(); root = Path(sys.argv[2])\n"
            "d = {t: {'state': 'ACTIVE', 'observed_at': now} for t in ('claude', 'codex', 'antigravity')}\n"
            "o = council.open_council(root, topic='live', directive='x', opener='claude', desk=d, now=now, deadline_s=1)\n"
            "council.submit_draft(root, o['id'], 'claude', 'A')\n"
            "r = council.drive(root, o['id'], tick=0.1, hard_timeout_s=40)\n"
            "print(r['state'], r['decision']['abstained'])\n")
        started = time.monotonic()
        proc = subprocess.run([sys.executable, "-c", code, str(REPO), str(self.root)], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                              timeout=50)
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertTrue(proc.stdout.startswith("DECIDED"), proc.stdout)
        self.assertLess(time.monotonic() - started, 40)


class StallSilentActive(Tmp):
    def setUp(self):
        super().setUp()
        path = self.root / ".coord" / "master_schedule.json"
        path.write_text(json.dumps({"schedule_id": "T", "phases": [
            {"phase_id": "U1-X", "state": "BLOCKED", "owner_tool": "codex", "owner_session": "t1"}]}), encoding="utf-8")
        os.utime(path, (NOW, NOW))
        self.start = NOW + stall.MAX_WAIT_S + 60

    def phase(self):
        return json.loads((self.root / ".coord" / "master_schedule.json").read_text(encoding="utf-8"))["phases"][0]

    def desk(self, now):
        # claude = the scanning tool (fresh); antigravity ACTIVE but silent for 700 h; codex the owner waited on (LIMITED)
        return {"claude": {"state": "ACTIVE", "observed_at": now},
                "antigravity": {"state": "ACTIVE", "observed_at": now - 700 * 3600},
                "codex": {"state": "LIMITED"}}

    def test_silent_active_peer_no_longer_blocks_reroute_after_agreement_deadline(self):
        first = stall.scan(self.root, "claude", now=self.start, desk=self.desk(self.start))
        self.assertEqual([], first["adopted"])  # ballot just opened: deadline not reached
        later = self.start + stall.AGREEMENT_DEADLINE_S
        res = stall.scan(self.root, "claude", now=later, desk=self.desk(later))
        self.assertEqual(1, len(res["adopted"]), res)
        self.assertEqual(["claude"], res["adopted"][0]["agreed_by"])
        self.assertEqual("claude", self.phase()["owner_tool"])
        self.assertIn("re-review", self.phase()["note"])

    def test_deadline_is_far_below_the_old_hour_long_timeout(self):
        self.assertLess(stall.AGREEMENT_DEADLINE_S * 10, stall.QUORUM_TIMEOUT_S)

    def test_a_fresh_idle_peer_is_still_awaited_until_the_quorum_timeout(self):
        def d(now):
            return {"claude": {"state": "ACTIVE", "observed_at": now}, "antigravity": {"state": "ACTIVE", "observed_at": now},
                    "codex": {"state": "LIMITED"}}
        stall.scan(self.root, "claude", now=self.start, desk=d(self.start))
        later = self.start + stall.AGREEMENT_DEADLINE_S + 30
        self.assertEqual([], stall.scan(self.root, "claude", now=later, desk=d(later))["adopted"])

    def test_a_peer_that_was_beating_when_the_vote_opened_is_not_abstained_when_it_goes_quiet(self):
        # u179 regression: a wait that outlives FRESH_SIGNAL_S is not a silent peer; only one quiet at the opening is.
        def d(now, seen):
            return {"claude": {"state": "ACTIVE", "observed_at": now}, "antigravity": {"state": "ACTIVE", "observed_at": seen},
                    "codex": {"state": "LIMITED"}}
        stall.scan(self.root, "claude", now=self.start, desk=d(self.start, self.start))
        later = self.start + stall.AGREEMENT_DEADLINE_S + 30  # antigravity's last beat is now older than FRESH_SIGNAL_S
        res = stall.scan(self.root, "claude", now=later, desk=d(later, self.start))
        self.assertEqual(([], []), (res["adopted"], res["stalled"][0]["abstained"]))


if __name__ == "__main__":
    unittest.main()


from v7_harness.coord import fswatch  # noqa: E402


class RealTimeGrade(Tmp):
    def test_presence_signal_valid_only_below_60_seconds(self):
        rec = {"state": "ACTIVE", "observed_at": NOW - 60}
        self.assertTrue(nowait.peer_alive(rec, NOW))
        self.assertFalse(nowait.peer_alive({"state": "ACTIVE", "observed_at": NOW - 61}, NOW))

    def test_ack_timeout_abstains_immediately_and_content_timeout_abstains(self):
        self.assertEqual(10, nowait.ACK_DEADLINE_S)
        self.assertEqual(120, nowait.REPLY_DEADLINE_S)
        self.assertEqual("ACK_OVERDUE", nowait.delivery_state(NOW, None, NOW + 10)["state"])  # no ACK in 10 s
        plan = nowait.plan_wait(desk(claude=0, codex=1, antigravity=1), "claude", NOW)
        end = nowait.settle(plan, [], NOW + 120)  # ACKed but no content in 120 s
        self.assertEqual(["antigravity", "codex"], end["abstained"])

    def test_council_total_cap_about_four_minutes(self):
        self.assertEqual(240, 2 * council.ROUND_DEADLINE_S)

    def test_fs_event_wakes_receiver_and_acks_with_p95_latency_well_under_10s(self):
        inbox, acks = self.root / "inbox", self.root / "ack"
        woke = []
        watcher = fswatch.InboxWatcher(inbox, acks, on_letter=lambda p, b: woke.append(b["n"])).start(max_s=40)
        try:
            for n in range(30):
                tmp = inbox / f"l{n}.tmp"
                tmp.write_text(json.dumps({"n": n, "sent_at": time.time()}), encoding="utf-8")
                os.replace(tmp, inbox / f"l{n}.json")
                time.sleep(0.03)
            end = time.monotonic() + 8
            while len(list(acks.glob("*.ack.json"))) < 30 and time.monotonic() < end:
                time.sleep(0.05)
        finally:
            watcher.stop()
        lat = [json.loads(p.read_text(encoding="utf-8"))["latency_s"] for p in acks.glob("*.ack.json")]
        self.assertEqual(30, len(lat))
        self.assertEqual(30, len(woke))
        p95 = fswatch.p95(lat)
        print(f"U329 arrival->ACK latency p95={p95:.3f}s max={max(lat):.3f}s n={len(lat)}")
        self.assertLessEqual(p95, nowait.ACK_DEADLINE_S)

    def test_silent_peer_process_never_pauses_and_late_reply_can_roll_back(self):
        started = time.monotonic()
        for i in range(5):  # five steps, every one "sent" to a peer that never answers
            out = nowait.send_optimistic(self.root, "U9", f"s{i}", "codex", f"ckpt-{i}", now=NOW + i)
            self.assertEqual((True, False), (out["continue"], out["waiting"]))
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(5, len(nowait.open_waits(self.root, "U9")))  # a ledger, not a wait
        better = nowait.late_reply_outcome(self.root, "U9", "s2", improves=True, now=NOW + 99)
        self.assertEqual("ckpt-2", better["rollback_to"])
        self.assertIsNone(nowait.late_reply_outcome(self.root, "U9", "s3", improves=False, now=NOW + 99)["rollback_to"])


class AuditFixes(Tmp):
    def test_signal_age_reads_a_real_presence_mark_record(self):
        from v7_harness.coord import presence

        presence.mark(self.root, "codex", "ACTIVE", now=NOW, ttl_s=3600)
        rec = presence.read(self.root, "codex", now=NOW + 30)
        self.assertIsInstance(rec["observed_at"], str)  # ISO-8601, as live presence writes it
        self.assertAlmostEqual(30, nowait.signal_age(rec, NOW + 30), delta=1)
        self.assertTrue(nowait.peer_alive(rec, NOW + 30))
        self.assertFalse(nowait.peer_alive(rec, NOW + 120))
        self.assertTrue(stall._silent(rec, NOW + 120))
        self.assertFalse(stall._silent(rec, NOW + 30))

    def test_safe_name_blocks_traversal_and_reserved_characters(self):
        for raw in ("../../evil", "a/b", "c:d", "x*y?", "..", ""):
            name = nowait.safe_name(raw)
            self.assertNotRegex(name, r"[\\/:*?\"<>|]")
            self.assertNotIn("..", name)
            self.assertTrue(name)
        msg_triage.submit(self.root, "claude", "../../evil", {"id": "m1", "sender": "codex", "text": "x"})
        self.assertFalse((self.root.parent / "evil.jsonl").exists())
        self.assertTrue(list((self.root / msg_triage.TRIAGE_DIR / "claude").glob("*evil*.jsonl")))

    def test_replace_retry_survives_a_transient_sharing_violation(self):
        src, dst = self.root / "s.tmp", self.root / "d.json"
        src.write_text("1", encoding="utf-8")
        real, calls = os.replace, []

        def flaky(a, b):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError("sharing violation")
            return real(a, b)

        os.replace = flaky
        try:
            nowait.replace_retry(src, dst)
        finally:
            os.replace = real
        self.assertEqual(3, len(calls))
        self.assertEqual("1", dst.read_text(encoding="utf-8"))

    def test_all_silent_and_no_voter_is_not_a_vacuous_quorum(self):
        path = self.root / ".coord" / "master_schedule.json"
        path.write_text(json.dumps({"schedule_id": "T", "phases": [
            {"phase_id": "U1-X", "state": "BLOCKED", "owner_tool": "codex", "owner_session": "t1"}]}), encoding="utf-8")
        os.utime(path, (NOW, NOW))
        start = NOW + stall.MAX_WAIT_S + 60

        def d(now):  # the scanning tool (codex) is not ACTIVE; both ACTIVE peers are silent: nobody can vote
            return {"claude": {"state": "ACTIVE", "observed_at": now - 700 * 3600},
                    "antigravity": {"state": "ACTIVE", "observed_at": now - 700 * 3600}, "codex": {"state": "LIMITED"}}

        stall.scan(self.root, "codex", now=start, desk=d(start))
        later = start + stall.AGREEMENT_DEADLINE_S + 1
        res = stall.scan(self.root, "codex", now=later, desk=d(later))
        self.assertEqual([], [a for a in res["adopted"] if not a.get("agreed_by")], res)

    def test_watcher_survives_a_raising_callback_and_ignores_bool_sent_at(self):
        inbox, acks = self.root / "in", self.root / "ack"
        inbox.mkdir()
        seen = []

        def boom(path, body):
            seen.append(path.name)
            raise RuntimeError("callback bug")

        w = fswatch.InboxWatcher(inbox, acks, on_letter=boom).start()
        try:
            (inbox / "a.json").write_text(json.dumps({"sent_at": True}), encoding="utf-8")
            (inbox / "b.json").write_text(json.dumps({"sent_at": time.time()}), encoding="utf-8")
            end = time.time() + 5
            while time.time() < end and len(list(acks.glob("*.ack.json"))) < 2:
                time.sleep(0.05)
        finally:
            w.stop()
        self.assertEqual(2, len(list(acks.glob("*.ack.json"))))  # the thread outlived the first raising callback
        self.assertIsNone(json.loads((acks / "a.ack.json").read_text(encoding="utf-8"))["latency_s"])
        self.assertGreaterEqual(w.callback_errors, 2)

    def test_second_critique_cannot_change_position_and_responders_use_authority_order(self):
        desk = {t: {"state": "ACTIVE", "observed_at": NOW} for t in ("codex", "claude", "antigravity")}
        c = council.open_council(self.root, topic="order", directive="d", opener="claude", desk=desk, now=NOW)["id"]
        for tool, pos in (("antigravity", "A"), ("claude", "A"), ("codex", "B")):  # dissent -> round 2 opens
            council.submit_draft(self.root, c, tool, pos, evidence_score=1)
        council.advance(self.root, c, now=NOW + 1)
        first = council.submit_critique(self.root, c, "claude", "ok", revised_position="A")
        again = council.submit_critique(self.root, c, "claude", "flip", revised_position="B", evidence_score=99)
        self.assertTrue(first["accepted"])
        self.assertFalse(again["accepted"])
        rec = json.loads(council._file(self.root, c).read_text(encoding="utf-8"))
        self.assertEqual("A", rec["drafts"]["claude"]["position"])
        out = council.advance(self.root, c, now=NOW + 2)
        responders = (out.get("decision") or rec.get("decision") or {}).get("responders")
        if responders:
            self.assertEqual(["codex", "claude", "antigravity"], responders)

    def test_conductor_fails_closed_when_nobody_is_active(self):
        for state in ("LIMITED", "ABSENT", "UNKNOWN"):
            self.assertEqual("none", nowait.conductor_of({t: {"state": state} for t in ("codex", "claude", "antigravity")}))
        self.assertEqual("claude", nowait.conductor_of({"codex": {"state": "LIMITED"}, "claude": {"state": "ACTIVE"}}))
        self.assertEqual("codex", nowait.conductor_of({"codex": {"state": "ACTIVE"}, "claude": {"state": "ACTIVE"}}))


class AuditRound3(Tmp):
    """AGY re-audit 261121-2: council tie-break, duplicate draft, temp leaks, drive clamp, multi-cycle, key escaping."""

    def _open_code(self, topic):
        desk = {t: {"state": "ACTIVE", "observed_at": NOW} for t in ("codex", "claude", "antigravity")}
        return council.open_council(self.root, topic=topic, directive="d", opener="claude", desk=desk, now=NOW,
                                    kind="code")["id"]

    def test_low_scoring_conductor_never_overrides_tied_high_scores(self):
        c = self._open_code("tie3")
        council.submit_draft(self.root, c, "codex", "low", evidence_score=1)  # codex is the conductor, but scores lowest
        council.submit_draft(self.root, c, "claude", "A", evidence_score=5)
        council.submit_draft(self.root, c, "antigravity", "B", evidence_score=5)
        council.advance(self.root, c, now=NOW + 1)
        res = council.advance(self.root, c, now=NOW + council.ROUND_DEADLINE_S * 3)
        self.assertNotEqual("low", res["decision"]["outcome"])
        self.assertIn(res["decision"]["by"], ("claude", "antigravity"))

    def test_tied_leaders_that_agree_decide_by_evidence_even_with_a_low_conductor(self):
        c = self._open_code("agree")
        council.submit_draft(self.root, c, "claude", "same", evidence_score=5)
        council.submit_draft(self.root, c, "antigravity", "same", evidence_score=5)
        council.submit_draft(self.root, c, "codex", "other", evidence_score=1)
        council.advance(self.root, c, now=NOW + 1)
        res = council.advance(self.root, c, now=NOW + council.ROUND_DEADLINE_S * 3)
        self.assertEqual(("evidence", "same"), (res["decision"]["method"], res["decision"]["outcome"]))

    def test_duplicate_draft_is_rejected_and_keeps_the_first(self):
        c = self._open_code("dup")
        self.assertTrue(council.submit_draft(self.root, c, "claude", "first", evidence_score=1)["accepted"])
        self.assertFalse(council.submit_draft(self.root, c, "claude", "second", evidence_score=9)["accepted"])
        rec = json.loads(council._file(self.root, c).read_text(encoding="utf-8"))
        self.assertEqual(("first", 1), (rec["drafts"]["claude"]["position"], rec["drafts"]["claude"]["score"]))

    def test_atomic_write_leaves_no_temp_file_on_failure(self):
        target = self.root / "x" / "a.json"
        real = nowait.replace_retry
        nowait.replace_retry = lambda s, d: (_ for _ in ()).throw(PermissionError("locked"))
        try:
            with self.assertRaises(PermissionError):
                nowait.atomic_write_text(target, "{}")
        finally:
            nowait.replace_retry = real
        self.assertEqual([], list(target.parent.glob("*.tmp")))

    def test_drive_clamps_sleep_to_the_hard_cap_and_survives_a_zero_tick(self):
        c = self._open_code("drive")
        clock = {"t": 0.0}
        slept = []

        def sleep(s):
            slept.append(s)
            clock["t"] += s

        out = council.drive(self.root, c, now_fn=lambda: NOW, sleep=sleep, tick=0, hard_timeout_s=0.05,
                            mono=lambda: clock["t"])
        self.assertEqual("ROUND1", out["state"])
        self.assertTrue(slept and all(s > 0 for s in slept) and sum(slept) <= 0.05 + 1e-9, slept)

    def test_one_new_edge_that_closes_two_cycles_leaves_an_acyclic_graph(self):
        d = {}
        # acyclic: claude->antigravity, claude->codex, codex->antigravity; the new antigravity->claude closes
        # claude->antigravity->claude AND claude->codex->antigravity->claude: two cycles, two breaking passes.
        for waiter, on in (("claude", "antigravity"), ("claude", "codex"), ("codex", "antigravity")):
            nowait.add_wait(self.root, waiter, on, "r", now=NOW)
        nowait.add_wait(self.root, "antigravity", "claude", "r", now=NOW)
        edges = json.loads((self.root / nowait.GRAPH).read_text(encoding="utf-8"))
        self.assertEqual([], nowait.find_cycle(edges), edges)

    def test_wait_failure_key_has_no_delimiter_collision(self):
        for _ in range(3):
            nowait.record_wait_failure(self.root, "U1|x", "letter", "c", now=NOW)
        self.assertTrue(nowait.path_blocked(self.root, "U1|x", "letter"))
        self.assertFalse(nowait.path_blocked(self.root, "U1", "x|letter"))

    def test_fswatch_ignores_receipts_when_the_ack_dir_is_the_inbox(self):
        from v7_harness.coord import fswatch

        inbox = self.root / "box"
        inbox.mkdir()
        (inbox / "a.json").write_text(json.dumps({"sent_at": NOW}), encoding="utf-8")
        w = fswatch.InboxWatcher(inbox, inbox, clock=lambda: NOW + 1)
        self.assertEqual(1, w._scan())
        self.assertEqual(0, w._scan())  # a.ack.json is a receipt, never re-ACKed as a letter
