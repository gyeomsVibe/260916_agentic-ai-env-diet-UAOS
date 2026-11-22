"""U334 freeze-tag: mocked adapters, no network, no paid call. Times are fixed epochs (no sleeping)."""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from v7_harness.coord import freeze_tag as ft
from v7_harness.coord import stall

NOW = 2_000_000_000.0
RESET = NOW + 3600


def _window(used, resets, state="FRESH"):
    return {"state": state, "used_pct": used, "resets_at": resets and
            __import__("datetime").datetime.fromtimestamp(resets, __import__("datetime").timezone.utc).isoformat()}


def _account(used=100.0, resets=RESET):
    return {"evidence": "provider_payload", "source": "mock", "five_hour": _window(used, resets),
            "seven_day": _window(10.0, NOW + 86400)}


def _desk(**s):
    return {t: {"state": v} for t, v in s.items()}


def _ran(stdout, seen=None):
    """A mocked subprocess.run: records argv, exits 0 with the given stdout (no real tool is started)."""
    def run(argv, **kw):
        if seen is not None:
            seen.append(list(argv))
        return type("Done", (), {"returncode": 0, "stdout": stdout})()
    return run


class FakeAdapter:
    def __init__(self, revives_after=0, broken=False):
        self.calls, self.signals, self.revives_after, self.broken, self.beat = 0, 0, revives_after, broken, 0

    def baseline(self, project):
        return {"beat": self.beat}

    def resume(self, project, phase):
        self.calls += 1
        if self.broken:
            raise RuntimeError("adapter broken")
        if self.calls > self.revives_after:
            self.beat += 1  # the tool really shows a new heartbeat only after this resume

    def signal(self, project, baseline):
        self.signals += 1
        return self.beat > baseline["beat"]


class Base(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.root = Path(self._t.name)
        (self.root / ".coord").mkdir()
        (self.root / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        self.sched = self.root / ".coord" / "master_schedule.json"
        self.sched.write_text(json.dumps({"phases": [
            {"phase_id": "U9-A", "state": "READY", "owner_tool": "codex", "owner_session": "t1", "checkpoint": "cp/A.json"},
            {"phase_id": "U9-B", "state": "DONE", "owner_tool": "codex"},
            {"phase_id": "U9-C", "state": "READY", "owner_tool": "codex", "action": "deploy to production"}]}),
            encoding="utf-8")

    def tearDown(self):
        self._t.cleanup()

    def freeze(self, tool="codex", resets=RESET, now=NOW):
        v = ft.detect(tool, _account(resets=resets), now=now)
        ft.record(self.root, v, now=now)
        return v

    def phases(self):
        return {p["phase_id"]: p for p in json.loads(self.sched.read_text(encoding="utf-8"))["phases"]}


class Detect(Base):
    def test_exhausted_fresh_window_is_frozen_with_reset(self):
        v = ft.detect("codex", _account(), now=NOW)
        self.assertEqual(("FROZEN", True, RESET), (v["verdict"], v["reset_known"], v["reset_at"]))

    def test_unverified_or_stale_is_unknown_not_frozen(self):
        acc = _account()
        acc["evidence"] = "operator_reported"
        self.assertEqual("UNKNOWN", ft.detect("claude", acc, now=NOW)["verdict"])
        acc = {"evidence": "provider_payload", "five_hour": _window(100.0, RESET, "STALE")}
        self.assertEqual("UNKNOWN", ft.detect("claude", acc, now=NOW)["verdict"])
        self.assertEqual("UNKNOWN", ft.detect("claude", None, now=NOW)["verdict"])

    def test_below_100_is_ok_and_percent_never_becomes_tokens(self):
        v = ft.detect("codex", _account(used=99.0), now=NOW)
        self.assertEqual("OK", v["verdict"])
        self.assertNotIn("tokens", json.dumps(v))

    def test_reset_unknown_and_clock_skew(self):
        acc = _account()
        acc["five_hour"]["resets_at"] = None
        v = ft.detect("codex", acc, now=NOW)
        self.assertEqual(("FROZEN", False, None), (v["verdict"], v["reset_known"], v["reset_at"]))
        far = ft.detect("codex", _account(resets=NOW + 30 * 86400), now=NOW)  # impossible reset = skewed clock
        self.assertFalse(far["reset_known"])

    def test_record_writes_state_and_presence_lease(self):
        self.freeze()
        row = ft.frozen_tools(self.root)["codex"]
        self.assertEqual(RESET, row["reset_at"])
        pres = json.loads((self.root / ".coord" / "presence" / "codex.json").read_text(encoding="utf-8"))
        self.assertEqual("LIMITED", pres["state"])


class Takeover(Base):
    def test_codex_frozen_cards_move_to_claude_with_checkpoint(self):
        self.freeze()
        res = ft.takeover(self.root, "codex", desk=_desk(claude="ACTIVE", antigravity="ACTIVE"), now=NOW)
        ft.ack(self.root, "claude", now=NOW + 1)  # claude answers: the owner is decided at once when first candidate acks
        res = ft.takeover(self.root, "codex", desk=_desk(claude="ACTIVE", antigravity="ACTIVE"), now=NOW + 2)
        ph = self.phases()
        self.assertEqual("claude", res["owner"])
        self.assertEqual("claude", ph["U9-A"]["owner_tool"])
        self.assertEqual("cp/A.json", ph["U9-A"]["resume_from"])
        self.assertEqual("FROZEN", ph["U9-A"]["rerouted_from"]["reason"])
        self.assertEqual("codex", ph["U9-B"]["owner_tool"])  # DONE card untouched
        self.assertEqual("codex", ph["U9-C"]["owner_tool"])  # human-only (deploy) stays

    def test_silent_peer_abstains_after_deadline(self):
        self.freeze()
        desk = _desk(claude="ACTIVE", antigravity="ACTIVE")
        first = ft.takeover(self.root, "codex", desk=desk, now=NOW)
        self.assertEqual(1, len(first["pending"]))
        self.assertEqual("codex", self.phases()["U9-A"]["owner_tool"])
        later = ft.takeover(self.root, "codex", desk=desk, now=NOW + ft.ABSTAIN_S)  # claude never answered
        self.assertEqual("claude", later["owner"])
        self.assertEqual("claude", self.phases()["U9-A"]["owner_tool"])

    def test_antigravity_only_when_codex_and_claude_are_away(self):
        self.assertEqual([], ft.candidates("codex", _desk(claude="LIMITED", antigravity="LIMITED"), {"codex"}))  # nobody left
        self.assertEqual([], ft.candidates("codex", _desk(claude="ACTIVE", antigravity="ACTIVE"), {"codex", "claude", "antigravity"}))
        self.assertEqual(["antigravity"], ft.candidates("codex", _desk(claude="LIMITED", antigravity="ACTIVE"), {"codex", "claude"}))
        self.assertEqual(["claude"], ft.candidates("codex", _desk(claude="ACTIVE", antigravity="ACTIVE"), {"codex"}))

    def test_stall_u166_silent_active_peer_cannot_hang_reroute(self):
        (self.root / ".coord" / "master_schedule.json").write_text(json.dumps({"phases": [
            {"phase_id": "U1-X", "state": "BLOCKED", "owner_tool": "codex", "waiting_on": "codex"}]}), encoding="utf-8")
        import os
        os.utime(self.sched, (NOW, NOW))
        desk = _desk(claude="ACTIVE", antigravity="ACTIVE")  # antigravity is silent: never votes
        r = stall.scan(self.root, "claude", now=NOW + stall.MAX_WAIT_S + 1, desk=desk, quorum_timeout_s=120)
        self.assertEqual([], r["adopted"])
        vfile = self.root / ".coord" / "stall" / "votes.json"
        opened = next(iter(json.loads(vfile.read_text(encoding="utf-8")).values()))["opened"]
        # the ballot records when the election opened; the timeout is measured from it, not from the last scan
        self.assertIsInstance(opened, (int, float))
        r = stall.scan(self.root, "claude", now=NOW + stall.MAX_WAIT_S + 130, desk=desk, quorum_timeout_s=120)
        self.assertEqual(1, len(r["adopted"]))


class Thaw(Base):
    def test_peer_revives_once_after_reset_with_second_signal(self):
        self.freeze()
        ad = FakeAdapter()
        desk = _desk(claude="ACTIVE", antigravity="ACTIVE")
        early = ft.thaw_due(self.root, "claude", {"codex": ad}, desk=desk, now=RESET + 5)  # inside the skew margin
        self.assertEqual("NOT_DUE", early[0]["result"])
        self.assertEqual(0, ad.calls)
        due = RESET + ft.SKEW_MARGIN_S
        out = ft.thaw_due(self.root, "claude", {"codex": ad}, desk=desk, now=due, sleep=lambda s: None)
        self.assertEqual("THAWED", out[0]["result"])
        self.assertEqual((1, 1), (ad.calls, ad.signals))  # second signal really checked
        again = ft.thaw_due(self.root, "antigravity", {"codex": ad}, desk=desk, now=due + 1, sleep=lambda s: None)
        self.assertEqual([], [o for o in again if o["tool"] == "codex"])  # duplicate revive: nothing left to revive
        self.assertEqual(1, ad.calls)
        self.assertIn("THAWED", [e["kind"] for e in ft.events(self.root)])

    def test_exit_zero_without_second_signal_is_not_a_revival(self):
        self.freeze()
        ad = FakeAdapter(revives_after=99)  # resume returns, tool never shows a heartbeat
        out = ft.thaw_due(self.root, "claude", {"codex": ad}, desk=_desk(claude="ACTIVE"), now=RESET + 60, sleep=lambda s: None)
        self.assertEqual("RETRY", out[0]["result"])
        self.assertIn("codex", ft.frozen_tools(self.root))
        self.assertEqual(ft.BACKOFF_BASE_S, ft.frozen_tools(self.root)["codex"]["next_attempt_at"] - (RESET + 60))

    def test_broken_adapter_backs_off_then_blocks_and_wakes_next_reset(self):
        self.freeze()
        ad = FakeAdapter(broken=True)
        desk = _desk(claude="ACTIVE")
        t = RESET + 60
        results = []
        for _ in range(6):
            results.append(ft.thaw_due(self.root, "claude", {"codex": ad}, desk=desk, now=t, sleep=lambda s: None)[0])
            t = max(t, ft.frozen_tools(self.root)["codex"]["next_attempt_at"]) + 1
            if results[-1]["result"] == "STORM_CAP":
                t = results[-1]["next_attempt_at"] + 1
        late = RESET + ft.REVIVE_DEADLINE_S + 100
        out = ft.thaw_due(self.root, "claude", {"codex": ad}, desk=desk, now=late, sleep=lambda s: None)
        row = ft.frozen_tools(self.root)["codex"]
        self.assertEqual("BLOCKED", out[0]["result"])
        self.assertGreater(row["next_attempt_at"], late)
        self.assertIn("BLOCKED", [e["kind"] for e in ft.events(self.root)])
        self.assertTrue(any(r["result"] in ("RETRY", "STORM_CAP") for r in results))

    def test_concurrent_claim_blocks_duplicate_revive(self):
        self.freeze()
        data = ft.load(self.root)
        data["tools"]["codex"]["claim"] = {"by": "antigravity", "at": RESET + 50}
        ft._save(self.root, data)
        ad = FakeAdapter()
        out = ft.thaw_due(self.root, "claude", {"codex": ad}, desk=_desk(claude="ACTIVE"), now=RESET + 70, sleep=lambda s: None)
        self.assertEqual("CLAIMED", out[0]["result"])
        self.assertEqual(0, ad.calls)

    def test_revive_storm_is_capped(self):
        self.freeze()
        ad = FakeAdapter(revives_after=99)
        desk = _desk(claude="ACTIVE")
        t = RESET + 60
        seen = []
        for _ in range(5):
            row = ft.frozen_tools(self.root)["codex"]
            t = max(t, row.get("next_attempt_at") or 0)
            seen.append(ft.thaw_due(self.root, "claude", {"codex": ad}, desk=desk, now=t, sleep=lambda s: None)[0]["result"])
        self.assertEqual(ft.MAX_ATTEMPTS_PER_HOUR, ad.calls)  # within one hour, no more than the cap
        self.assertIn("STORM_CAP", seen)

    def test_non_active_actor_cannot_revive(self):
        self.freeze()
        out = ft.thaw_due(self.root, "claude", {"codex": FakeAdapter()}, desk=_desk(claude="LIMITED"), now=RESET + 60)
        self.assertEqual("ACTOR_NOT_ACTIVE", out[0]["result"])

    def test_reset_unknown_probes_instead_of_never(self):
        v = ft.detect("codex", {"evidence": "provider_payload", "five_hour": {**_window(100.0, None)}}, now=NOW)
        ft.record(self.root, v, now=NOW)
        ad = FakeAdapter()
        d = _desk(claude="ACTIVE")
        self.assertEqual("NOT_DUE", ft.thaw_due(self.root, "claude", {"codex": ad}, desk=d, now=NOW + 60)[0]["result"])
        out = ft.thaw_due(self.root, "claude", {"codex": ad}, desk=d, now=NOW + ft.PROBE_UNKNOWN_S, sleep=lambda s: None)
        self.assertEqual("THAWED", out[0]["result"])


class AllFrozen(Base):
    def test_all_three_frozen_is_blocked_with_earliest_wake(self):
        self.freeze("codex", resets=NOW + 7200)
        self.freeze("claude", resets=NOW + 3600)
        self.assertIsNone(ft.blocked_check(self.root, desk=_desk(), now=NOW))  # agy not frozen yet
        self.freeze("antigravity", resets=NOW + 9000)
        info = ft.blocked_check(self.root, desk=_desk(), now=NOW)
        self.assertEqual("BLOCKED", info["state"])
        self.assertEqual(NOW + 3600 + ft.SKEW_MARGIN_S, info["wake_at"])
        self.assertEqual(NOW + 3600 + ft.SKEW_MARGIN_S, ft.next_wake(self.root, now=NOW))
        self.assertIn("BLOCKED", [e["kind"] for e in ft.events(self.root)])

    def test_all_frozen_unknown_resets_still_get_a_probe_wake(self):
        for t in ft.TOOLS:
            ft.record(self.root, {"tool": t, "verdict": "FROZEN", "reset_at": None, "reset_known": False, "reason": "x"}, now=NOW)
        info = ft.blocked_check(self.root, desk=_desk(), now=NOW)
        self.assertEqual(NOW + ft.PROBE_UNKNOWN_S, info["wake_at"])

    def test_scheduler_command_is_local_and_zero_paid(self):
        self.freeze()
        argv = ft.schtasks_argv(self.root, RESET, uaos="U.py", python="py")
        self.assertEqual(["schtasks", "/Create", "/F", "/TN"], argv[:4])
        xml = ft.task_xml(self.root, RESET, uaos="U.py", python="py")
        self.assertIn("--action thaw --actor scheduler", xml)
        self.assertNotIn("claude -p", xml)


class Collaboration(Base):
    def test_peer_tick_letters_every_other_tool(self):
        self.freeze()
        sent = []
        ft.takeover(self.root, "codex", desk=_desk(claude="ACTIVE", antigravity="ACTIVE"), now=NOW + 100)  # offer
        ft.ack(self.root, "claude", now=NOW + 101)
        ad = {"codex": FakeAdapter(revives_after=99)}
        out = ft.peer_tick(self.root, "claude", ad, desk=_desk(claude="ACTIVE", antigravity="ACTIVE"), now=NOW + 200,
                           accounts={"codex": _account(), "claude": _account(used=5), "antigravity": _account(used=5)},
                           notifier=lambda p, tgt, msg: sent.append(tgt), sleep=lambda s: None)
        self.assertIn("codex", ft.frozen_tools(self.root))
        self.assertEqual({"codex", "antigravity"}, set(sent))
        self.assertEqual("FROZEN", out["verdicts"]["codex"])

    def test_author_cannot_judge_own_card(self):
        self.assertEqual("OPEN", ft.collab_gate("claude", [])["gate"])
        self.assertEqual("OPEN", ft.collab_gate("claude", [{"by": "claude", "result": "PASS"}])["gate"])
        self.assertEqual("PASS", ft.collab_gate("claude", [{"by": "codex", "result": "PASS"}])["gate"])
        self.assertEqual("REWORK", ft.collab_gate("claude", [{"by": "codex", "result": "REVISE"}])["gate"])


class CodexRevise(Base):
    """Codex audit relay_c91b514: stale attempt, unrelated heartbeat, predicted reset."""

    def test_antigravity_not_candidate_when_senior_unknown(self):
        frozen = {"codex"}
        unknown = _desk(claude="UNKNOWN", antigravity="ACTIVE")
        self.assertEqual(ft.candidates("codex", unknown, frozen), [])
        limited = _desk(claude="LIMITED", antigravity="ACTIVE")
        self.assertEqual(ft.candidates("codex", limited, frozen), ["antigravity"])

    def test_older_active_record_is_not_a_signal(self):
        from v7_harness.coord import presence
        t0 = time.time()
        presence.mark(self.root, "claude", "ACTIVE", session="s", now=t0)
        ad = ft.CommandAdapter("claude")
        base = ad.baseline(self.root)
        base["observed_at"] = presence._epoch(base["observed_at"]) and (
            __import__("datetime").datetime.fromtimestamp(t0 + 100, __import__("datetime").timezone.utc).isoformat(timespec="seconds"))
        presence.mark(self.root, "claude", "ACTIVE", session="new", now=t0 + 5)  # older than the baseline stamp
        self.assertFalse(ad.signal(self.root, base))

    def test_deliver_letter_passes_delta_and_raises_on_failure(self):
        seen = {}

        def fake_run(argv, **kw):
            seen["argv"] = argv
            return type("R", (), {"returncode": 1})()

        orig = ft.subprocess.run
        ft.subprocess.run = fake_run
        try:
            with self.assertRaises(RuntimeError):
                ft.deliver_letter(self.root, "codex", "hello")
        finally:
            ft.subprocess.run = orig
        self.assertIn("--delta", seen["argv"])

    def test_malformed_readings_never_freeze_or_thaw(self):
        now = time.time()
        for bad in (float("nan"), True, "100", float("inf")):
            acct = {"evidence": ft.VERIFIED_EVIDENCE, "five_hour": {"state": "FRESH", "used_pct": bad}, "seven_day": None}
            self.assertEqual(ft.detect("claude", acct, now=now)["verdict"], "UNKNOWN", bad)
        acct = {"evidence": ft.VERIFIED_EVIDENCE, "five_hour": "x", "seven_day": None}
        self.assertEqual(ft.detect("claude", acct, now=now)["verdict"], "UNKNOWN")

    def test_active_429_lease_outranks_fresh_reading_and_expired_one_does_not(self):
        now = time.time()
        fresh = {"evidence": ft.VERIFIED_EVIDENCE, "five_hour": {"state": "FRESH", "used_pct": 10}, "seven_day": None}
        lease = {"state": "LIMITED", "lease_source": "provider", "expires_at": now + 600}
        self.assertEqual(ft.detect("claude", fresh, now=now, lease=lease)["verdict"], "FROZEN")
        lease["expires_at"] = now - 5
        self.assertEqual(ft.detect("claude", None, now=now, lease=lease)["verdict"], "UNKNOWN")

    def test_shorter_reset_does_not_clobber_longer_one(self):
        now = time.time()
        v = lambda r: {"tool": "claude", "verdict": "FROZEN", "reset_at": r, "reset_known": True, "reason": "x"}
        ft.record(self.root, v(now + 7 * 3600), now=now)
        ft.record(self.root, v(now + 3600), now=now)
        self.assertEqual(ft.load(self.root)["tools"]["claude"]["reset_at"], now + 7 * 3600)
        unknown = {"tool": "claude", "verdict": "FROZEN", "reset_at": None, "reset_known": False, "reason": "x"}
        ft.record(self.root, unknown, now=now)  # unknown reset over a known one: no crash, known value kept
        self.assertEqual(ft.load(self.root)["tools"]["claude"]["reset_at"], now + 7 * 3600)

    def test_stale_attempt_neither_clears_newer_claim_nor_commits(self):
        self.freeze()
        desk = _desk(claude="ACTIVE", antigravity="ACTIVE")

        class Racing(FakeAdapter):
            def resume(inner, project, phase):  # noqa: N805 - a second reviver steals the lapsed claim mid-attempt
                data = ft.load(self.root)
                data["tools"]["codex"]["claim"] = {"by": "antigravity", "at": RESET + 70, "id": "newer"}
                ft._save(self.root, data)
                super().resume(project, phase)

        out = ft.thaw_due(self.root, "claude", {"codex": Racing()}, desk=desk, now=RESET + 60, sleep=lambda s: None)
        self.assertEqual("STALE_ATTEMPT", out[0]["result"])
        row = ft.frozen_tools(self.root)["codex"]
        self.assertEqual("newer", row["claim"]["id"])  # the newer claim survives; no stale THAWED committed

    def test_unrelated_heartbeat_is_not_a_revival(self):
        import time
        from v7_harness.coord import presence
        t0 = time.time()
        presence.mark(self.root, "claude", "ACTIVE", session="old", now=t0)
        ad = ft.CommandAdapter("claude", runner=_ran('{"session_id": "resumed"}'))
        base = ad.baseline(self.root)
        ad.resume(self.root, {})
        presence.mark(self.root, "claude", "ACTIVE", session="old", now=t0 + 5)  # routine beat of an older session
        self.assertFalse(ad.signal(self.root, base))
        presence.mark(self.root, "claude", "ACTIVE", session="resumed", now=t0 + 10)
        self.assertTrue(ad.signal(self.root, base))
        ad2 = ft.CommandAdapter("claude", session="old")
        b2 = ad2.baseline(self.root)
        presence.mark(self.root, "claude", "ACTIVE", session="other", now=t0 + 20)  # tool-wide beat, not the named session
        self.assertFalse(ad2.signal(self.root, b2))

    def test_unnamed_resume_counts_only_the_session_it_started(self):
        # Codex REVISE P1 (relay_c91b5144): an unrelated new session of the same account must not pass as the revival
        import time
        from v7_harness.coord import presence
        t0 = time.time()
        presence.mark(self.root, "antigravity", "ACTIVE", session="old", now=t0)
        ad = ft.CommandAdapter("antigravity", runner=_ran('{"session_id": "mine", "result": "ok"}'))
        base = ad.baseline(self.root)
        ad.resume(self.root, {})
        presence.mark(self.root, "antigravity", "ACTIVE", session="unrelated", now=t0 + 5)
        self.assertFalse(ad.signal(self.root, base))
        presence.mark(self.root, "antigravity", "ACTIVE", session="mine", now=t0 + 10)
        self.assertTrue(ad.signal(self.root, base))
        silent = ft.CommandAdapter("antigravity", runner=_ran("done, no id"))
        b2 = silent.baseline(self.root)
        silent.resume(self.root, {})
        presence.mark(self.root, "antigravity", "ACTIVE", session="late", now=t0 + 20)
        self.assertFalse(silent.signal(self.root, b2))  # no correlatable id from the run: fail closed

    def test_codex_resume_reads_its_thread_id(self):
        seen = []
        ad = ft.CommandAdapter("codex", runner=_ran('{"type": "thread.started", "thread_id": "t-9"}\n{"type": "turn.completed"}\n', seen))
        ad.resume(self.root, {})
        self.assertIn("--json", seen[0])
        self.assertEqual("t-9", ad.resumed_session)

    def test_non_numeric_session_stamp_fails_closed(self):
        import time
        from v7_harness.coord import presence
        presence.mark(self.root, "claude", "ACTIVE", session="s", now=time.time())
        ad = ft.CommandAdapter("claude", session="s")
        self.assertFalse(ad.signal(self.root, {"observed_at": "x", "sessions": {"s": None}}))
        self.assertFalse(ad.signal(self.root, {"observed_at": "x", "sessions": {"s": True}}))  # bool is not a stamp
        presence_file = presence._path(self.root, "claude")
        rec = json.loads(presence_file.read_text(encoding="utf-8"))
        rec["sessions"] = {"s": "corrupt"}  # damaged live stamp
        presence_file.write_text(json.dumps(rec), encoding="utf-8")
        self.assertFalse(ad.signal(self.root, {"observed_at": "x", "sessions": {"s": 1}}))

    def test_scan_self_thaw_reaches_takeover_desk(self):
        # AGY review U334-D #1: codex self-thawed by this tick's scan must not be treated as LIMITED by takeover
        self.freeze()  # codex FROZEN
        ok = {"evidence": ft.VERIFIED_EVIDENCE, "five_hour": {"state": "FRESH", "used_pct": 10}, "seven_day": None}
        verdicts = ft.scan(self.root, now=RESET + 60, accounts={"codex": ok, "claude": None, "antigravity": None})
        desk = ft._desk_after_scan(self.root, _desk(codex="LIMITED", claude="LIMITED", antigravity="ACTIVE"), verdicts, RESET + 60)
        self.assertEqual("ACTIVE", desk["codex"]["state"])
        stale = ft._desk_after_scan(self.root, _desk(codex="LIMITED"), verdicts, RESET + 999)  # an older thaw is not this scan's
        self.assertEqual("LIMITED", stale["codex"]["state"])

    def test_actor_frozen_by_this_scan_cannot_revive(self):
        # AGY review U334-D #2: a desk read before the scan still says ACTIVE; the freeze row must win
        self.freeze()  # codex FROZEN
        ft.record(self.root, {"tool": "claude", "verdict": "FROZEN", "reset_at": None, "reset_known": False, "reason": "x"}, now=NOW)
        ad = FakeAdapter()
        out = ft.thaw_due(self.root, "claude", {"codex": ad}, desk=_desk(claude="ACTIVE"), now=RESET + 60, sleep=lambda s: None)
        self.assertEqual("ACTOR_NOT_ACTIVE", out[0]["result"])
        self.assertEqual(0, ad.calls)
        desk = ft._desk_after_scan(self.root, _desk(claude="ACTIVE"), {"claude": {"verdict": "FROZEN"}}, NOW)
        self.assertEqual("LIMITED", desk["claude"]["state"])

    def test_freeze_lands_on_a_desk_bound_live_session(self):
        # AGY review U334-E F1: the LIMITED mirror must not be fenced off by the live desk session it describes
        import time
        from v7_harness.coord import presence
        now = time.time()
        pdir = ft._root(self.root) / ".coord" / "presence"
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "user_desk_claude.json").write_text(json.dumps({"thread": "desk1"}), encoding="utf-8")
        presence.mark(ft._root(self.root), "claude", "ACTIVE", session="desk1", now=now)
        ft.record(self.root, {"tool": "claude", "verdict": "FROZEN", "reset_at": now + 3600, "reset_known": True,
                              "reason": "x"}, now=now)
        self.assertEqual("LIMITED", presence.read(ft._root(self.root), "claude", now=now + 1)["state"])
        self.assertNotIn("LEASE_FENCED_LIVE_SESSION", (pdir / "events.jsonl").read_text(encoding="utf-8")
                         if (pdir / "events.jsonl").exists() else "")

    def test_production_thaw_reads_the_live_clock(self):
        # AGY review U334-F: main()/peer_tick() with now=None must not pin thaw_due to the clock read at tick start
        seen: list = []
        saved = {k: getattr(ft, k) for k in ("thaw_due", "scan", "schedule", "default_adapters")}
        try:
            ft.thaw_due = lambda *a, **k: seen.append(k.get("now")) or []
            ft.scan = lambda *a, **k: {}
            ft.schedule = lambda *a, **k: {}
            ft.default_adapters = lambda: {}
            ft.main(self.root, "thaw", "scheduler", now=None)
            ft.peer_tick(self.root, "claude", {}, desk={}, now=None)
        finally:
            for k, v in saved.items():
                setattr(ft, k, v)
        self.assertEqual([None, None], seen)

    def test_thaw_keeps_the_live_session_table(self):
        # AGY review U334-E F2: marking a revived tool ACTIVE must not erase the sessions its own heartbeat registered
        import time
        from v7_harness.coord import presence
        now = time.time()
        presence.mark(ft._root(self.root), "claude", "ACTIVE", session="s1", now=now)
        ft._mark_presence(self.root, "claude", "ACTIVE", {}, now + 1)
        rec = json.loads(presence._path(ft._root(self.root), "claude").read_text(encoding="utf-8"))
        self.assertIn("s1", rec.get("sessions") or {})

    def test_claim_outlives_one_live_attempt(self):
        # AGY review U334-D #3: the claim must not lapse while one resume call plus its verification polls can still run
        self.assertGreater(ft.CLAIM_TTL_S, ft.RESUME_TIMEOUT_S + ft.VERIFY_POLLS * ft.VERIFY_POLL_S)
        seen = []
        ft.CommandAdapter("claude", runner=lambda argv, **kw: seen.append(kw) or _ran("{}")(argv)).resume(self.root, {})
        self.assertEqual(ft.RESUME_TIMEOUT_S, seen[0]["timeout"])

    def test_schtasks_has_no_locale_dependent_date_flag(self):
        # AGY REVISE relay_bc30edf9: /SD parses in the machine's date format; the job must come from the ISO XML only
        argv = ft.schtasks_argv(self.root, 1_800_000_030.0)
        self.assertFalse({"/SD", "/ST", "/SC"} & set(argv))
        self.assertEqual("/XML", argv[-2])
        stamp = ft.task_xml(self.root, 1_800_000_030.0, now=1_800_000_000.0).split("<StartBoundary>")[1].split("<")[0]
        self.assertRegex(stamp, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")

    def test_blocked_window_at_survives_reload(self):
        # AGY REVISE relay_bc30edf9: thaw_due must persist window_at so a new process keeps the 5 h phase
        self.freeze()
        late = RESET + ft.REVIVE_DEADLINE_S + 100
        ft.thaw_due(self.root, "claude", {"codex": FakeAdapter(broken=True)}, desk=_desk(claude="ACTIVE"), now=late,
                    sleep=lambda s: None)
        row = json.loads(json.dumps(ft.load(self.root)))["tools"]["codex"]  # what a fresh process reads from disk
        self.assertEqual(row["window_at"], row["next_attempt_at"])
        self.assertGreater(row["window_at"], late)

    def test_schtasks_never_rounds_into_the_past(self):
        from datetime import datetime
        wake = 1_800_000_030.0  # 30 s past a minute edge
        xml = ft.task_xml(self.root, wake, now=wake - 600)
        stamp = xml.split("<StartBoundary>")[1].split("<")[0]  # ISO, independent of the machine's date format
        self.assertGreaterEqual(datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S").timestamp(), wake)
        past = ft.task_xml(self.root, wake - 9999, now=wake)  # an overdue wake still lands in a future minute
        stamp = past.split("<StartBoundary>")[1].split("<")[0]
        self.assertGreaterEqual(datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S").timestamp(), wake + 60)

    def test_unknown_author_and_actor_fail_closed(self):
        self.assertEqual(ft.collab_gate("Claude", [{"by": "codex", "result": "PASS"}])["gate"], "OPEN")
        with self.assertRaises(ValueError):
            ft.main(self.root, "status", "Claude")

    def test_provider_lease_survives_record_and_two_scans(self):
        from v7_harness.coord import presence
        now = time.time()
        presence.mark(self.root, "claude", "LIMITED", ttl_s=3600, now=now, lease=True, lease_source="provider")
        fresh = {"claude": {"evidence": ft.VERIFIED_EVIDENCE, "five_hour": {"state": "FRESH", "used_pct": 10}, "seven_day": None}}
        for i in range(2):
            ft.scan(self.root, now=now + i, accounts=fresh)
        self.assertEqual(ft.load(self.root)["tools"]["claude"]["state"], "FROZEN")

    def test_failed_delivery_is_logged_not_counted_sent(self):
        def boom(project, target, message):
            raise RuntimeError("deliver exit 1")
        sent = ft.tell_peers(self.root, "claude", "x", boom)
        self.assertEqual([], sent)
        self.assertIn("NOTIFY_FAILED", [e["kind"] for e in ft.events(self.root)])

    def test_predicted_next_window_is_not_a_known_reset(self):
        self.freeze()
        ad = FakeAdapter(broken=True)
        late = RESET + ft.REVIVE_DEADLINE_S + 100
        out = ft.thaw_due(self.root, "claude", {"codex": ad}, desk=_desk(claude="ACTIVE"), now=late, sleep=lambda s: None)
        self.assertEqual("BLOCKED", out[0]["result"])
        row = ft.frozen_tools(self.root)["codex"]
        self.assertFalse(row["reset_known"])
        self.assertGreater(row["next_attempt_at"], late)

    def test_second_window_probe_is_a_retry_not_an_instant_blocked(self):
        self.freeze()
        ad = FakeAdapter(broken=True)
        desk = _desk(claude="ACTIVE")
        late = RESET + ft.REVIVE_DEADLINE_S + 100
        ft.thaw_due(self.root, "claude", {"codex": ad}, desk=desk, now=late, sleep=lambda s: None)
        row = ft.frozen_tools(self.root)["codex"]
        self.assertEqual(row["window_at"], row["next_attempt_at"])
        out = ft.thaw_due(self.root, "claude", {"codex": ad}, desk=desk, now=row["next_attempt_at"] + 1, sleep=lambda s: None)
        self.assertEqual("RETRY", out[0]["result"])  # phase kept: the first probe of a new window gets its retries

    def test_collab_gate_empty_author_fails_closed(self):
        for author in ("", None, "CLAUDE"):
            self.assertEqual(ft.collab_gate(author, [{"by": "codex", "result": "PASS"}])["gate"], "OPEN")


if __name__ == "__main__":
    unittest.main()
