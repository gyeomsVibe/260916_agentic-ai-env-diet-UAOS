"""S5 acceptance: participation mode (TRIO/DUO/SOLO/HALT) is decided before any card is dispatched.

Written test-first by Claude (contract author) from .work/sustain_20261107/S5_contract.md; the non-author pins the
SHA256 before any source write. Every case runs in a temp directory: no real presence, quota or home file is read.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from v7_harness.coord import participation as pm
from v7_harness.coord import presence

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ("codex", "claude", "antigravity")
LANES = ("IMPL_CODE", "VERIFY_AUDIT", "ARCH_DESIGN", "MERGE_RELEASE", "RECOVERY_OPS")


def states(**kw: str) -> dict[str, str]:
    return {t: kw.get(t, "UNKNOWN") for t in TOOLS}


def admitted(*tools: str) -> dict[str, bool]:
    return {t: t in tools for t in TOOLS}


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def s1_window(now: float, *, age: float = 0, max_age: float = 900, reset_in: float = 3 * 3600) -> dict:
    """The window shape S1's `window_fact` emits (observed_at/max_age_s/resets_at; no `expires_at`)."""
    return {"state": "FRESH", "admit_paid": True, "used_pct": 10.0, "observed_at": _iso(now - age),
            "max_age_s": max_age, "resets_at": _iso(now + reset_in), "age_s": int(age)}


def s1_account(tool: str, now: float, *, age: float = 0, five_max: float = 900, seven_max: float = 21600,
               reset_in: float = 3 * 3600) -> dict:
    if tool == "antigravity":
        return {"selected_pool": s1_window(now, age=age, max_age=five_max, reset_in=reset_in)}
    return {"evidence": "verified", "account_pool": f"{tool}:plan:pool:tag",
            "five_hour": s1_window(now, age=age, max_age=five_max, reset_in=reset_in),
            "seven_day": s1_window(now, age=age, max_age=seven_max, reset_in=5 * 86400)}


class A1Mode(unittest.TestCase):
    def test_trio_duo_solo_halt(self) -> None:
        act = states(codex="ACTIVE", claude="ACTIVE", antigravity="ACTIVE")
        self.assertEqual(pm.decide(act, admitted(*TOOLS))["mode"], "TRIO")
        self.assertEqual(pm.decide(act, admitted("claude", "antigravity"))["mode"], "DUO")
        self.assertEqual(pm.decide(act, admitted("claude"))["mode"], "SOLO")
        self.assertEqual(pm.decide(act, admitted())["mode"], "HALT")

    def test_executors_listed(self) -> None:
        d = pm.decide(states(codex="ACTIVE", claude="ACTIVE", antigravity="ACTIVE"), admitted("claude", "codex"))
        self.assertEqual(sorted(d["executors"]), ["claude", "codex"])
        self.assertEqual(d["roles"]["antigravity"], "JUDGE_ONLY")


class A2QuotaFailClosed(unittest.TestCase):
    def test_classify(self) -> None:
        self.assertEqual(pm.classify("ACTIVE", True), "EXECUTOR")
        for bad in (False, None, 1, "yes", {"ok": True}):
            self.assertEqual(pm.classify("ACTIVE", bad), "JUDGE_ONLY", bad)

    def test_admissions_only_exact_true(self) -> None:
        now = time.time()
        accounts = {t: s1_account(t, now) for t in TOOLS}
        answers = {"codex": False, "claude": True, "antigravity": 1}  # 1: truthy non-bool must not admit
        self.assertEqual(pm.admissions(accounts, admit=lambda tool, acct: answers[tool]),
                         {"codex": False, "claude": True, "antigravity": False})

    def test_admit_raises_or_unbound_pool(self) -> None:
        now = time.time()
        accounts = {t: s1_account(t, now) for t in TOOLS}

        def boom(tool, acct):
            raise RuntimeError("source broke")
        self.assertEqual(pm.admissions(accounts, admit=boom), admitted())
        self.assertEqual(pm.admissions(None, admit=lambda *a: True), admitted())
        # Default path = S1's producer; no dispatch pools bound -> POOL_UNBOUND (or pre-S1 signature) -> closed.
        self.assertEqual(pm.admissions(accounts), admitted())

    def test_missing_account_not_admitted(self) -> None:
        now = time.time()
        self.assertEqual(pm.admissions({"claude": s1_account("claude", now)}, admit=lambda *a: True),
                         {"codex": False, "claude": True, "antigravity": False})

    def test_admitted_without_derivable_expiry_fails_closed(self) -> None:
        # rev 3 item 2: S1 emits observed_at/max_age_s/resets_at per window, never `expires_at`.
        now = time.time()
        acct = s1_account("claude", now)
        del acct["seven_day"]["max_age_s"]
        self.assertEqual(pm.admissions({"claude": acct}, admit=lambda *a: True), admitted())
        bogus = {"expires_at": now + 999, "five_hour": {}, "seven_day": {}}
        self.assertEqual(pm.admissions({"claude": bogus}, admit=lambda *a: True), admitted())

    def test_account_expiry_from_s1_windows(self) -> None:
        now = 1_800_000_000.0
        acct = s1_account("codex", now, age=100, five_max=900, seven_max=21600, reset_in=300)
        # five_hour: min(observed+900=now+800, resets_at=now+300) = now+300.
        self.assertAlmostEqual(pm.account_expiry("codex", acct), now + 300, delta=1)
        ag = s1_account("antigravity", now, age=0, five_max=900)
        self.assertAlmostEqual(pm.account_expiry("antigravity", ag), now + 900, delta=1)
        nan = s1_account("claude", now)
        nan["five_hour"]["max_age_s"] = float("nan")
        self.assertIsNone(pm.account_expiry("claude", nan))


class A3PresenceNeverAssumed(unittest.TestCase):
    def test_unknown_idle_missing_not_present(self) -> None:
        for st in ("UNKNOWN", "IDLE", "", None, "weird"):
            self.assertEqual(pm.classify(st, True), "UNKNOWN", st)
        d = pm.decide({"claude": "ACTIVE"}, admitted(*TOOLS))
        self.assertEqual(d["mode"], "SOLO")
        self.assertEqual(d["roles"]["codex"], "UNKNOWN")
        self.assertNotIn("codex", d["judges"])

    def test_limited_absent_offline(self) -> None:
        self.assertEqual(pm.classify("LIMITED", True), "OFFLINE")
        self.assertEqual(pm.classify("ABSENT", True), "OFFLINE")


class A4AuthorNeverJudge(unittest.TestCase):
    def _check(self, d: dict) -> None:
        self.assertFalse(d["self_approval"])
        self.assertEqual(set(d["lanes"]), set(LANES))
        for lane, plan in d["lanes"].items():
            if plan["owner"] is not None:
                self.assertNotEqual(plan["owner"], plan["judge"], lane)
                self.assertIn(plan["owner"], d["executors"], lane)
            if plan["judge"] is not None:
                self.assertIn(plan["judge"], d["judges"], lane)

    def test_all_combinations(self) -> None:
        options = ("ACTIVE", "LIMITED", "UNKNOWN")
        for c in options:
            for cl in options:
                for ag in options:
                    for mask in range(8):
                        adm = {t: bool(mask >> i & 1) for i, t in enumerate(TOOLS)}
                        self._check(pm.decide(states(codex=c, claude=cl, antigravity=ag), adm))

    def test_solo_alone_defers(self) -> None:
        d = pm.decide(states(claude="ACTIVE", codex="LIMITED"), admitted("claude"))
        self.assertEqual(d["mode"], "SOLO")
        for lane, plan in d["lanes"].items():
            self.assertEqual(plan["owner"], "claude", lane)
            self.assertIsNone(plan["judge"], lane)
            self.assertEqual(plan["verdict"], "DEFERRED_TO_RETURNING", lane)

    def test_solo_with_judge_only_is_keypoint_only(self) -> None:
        # Revision 2 / D-R1: a JUDGE_ONLY judge spends a RED/unknown account, so it judges keypoints only.
        d = pm.decide(states(claude="ACTIVE", antigravity="ACTIVE"), admitted("claude"))
        for lane, plan in d["lanes"].items():
            self.assertEqual(plan["judge"], "antigravity", lane)
            self.assertEqual(plan["verdict"], "KEYPOINT_ONLY", lane)

    def test_executor_judge_preferred_over_judge_only(self) -> None:
        d = pm.decide(states(codex="ACTIVE", claude="ACTIVE", antigravity="ACTIVE"), admitted("claude", "antigravity"))
        for lane, plan in d["lanes"].items():
            self.assertIn(plan["judge"], ("claude", "antigravity"), lane)
            self.assertEqual(plan["verdict"], "LIVE", lane)

    def test_halt(self) -> None:
        d = pm.decide(states(claude="ACTIVE"), admitted())
        self.assertEqual(d["mode"], "HALT")
        for plan in d["lanes"].values():
            self.assertIsNone(plan["owner"])
            self.assertEqual(plan["verdict"], "HALTED")

    def test_trio_preferences(self) -> None:
        d = pm.decide(states(codex="ACTIVE", claude="ACTIVE", antigravity="ACTIVE"), admitted(*TOOLS))
        self.assertEqual(d["lanes"]["IMPL_CODE"]["owner"], "antigravity")
        self.assertEqual(d["lanes"]["MERGE_RELEASE"]["owner"], "antigravity")
        self.assertEqual(d["lanes"]["ARCH_DESIGN"]["owner"], "claude")


class A5MeasuredToday(unittest.TestCase):
    def test_codex_red_agy_unknown(self) -> None:
        d = pm.decide(states(codex="ACTIVE", claude="ACTIVE", antigravity="ACTIVE"), admitted("claude"))
        self.assertEqual(d["mode"], "SOLO")
        self.assertEqual(d["roles"]["codex"], "JUDGE_ONLY")
        self.assertEqual(d["roles"]["antigravity"], "JUDGE_ONLY")
        for lane, plan in d["lanes"].items():
            self.assertEqual(plan["owner"], "claude", lane)
            self.assertIn(plan["judge"], ("codex", "antigravity"), lane)
            self.assertEqual(plan["verdict"], "KEYPOINT_ONLY", lane)


class A6SnapshotAndGate(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "proj"
        self.home = Path(self._tmp.name) / "home"
        (self.project / ".coord").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        self.home.mkdir()
        self.now = time.time()
        presence.mark(self.project, "claude", "ACTIVE", now=self.now)
        presence.mark(self.project, "antigravity", "ACTIVE", now=self.now)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _snap(self, admit, **acct_kw) -> dict:
        accounts = {t: s1_account(t, self.now, **acct_kw) for t in TOOLS}
        return pm.snapshot(self.project, home=self.home, now=self.now, admit=admit, accounts=accounts)

    def test_snapshot_written_with_expiry(self) -> None:
        d = self._snap(lambda *a: True)
        self.assertEqual(d["mode"], "DUO")
        path = self.project / pm.SNAPSHOT
        self.assertTrue(path.is_file())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["mode"], d["mode"])
        self.assertEqual(pm.TTL_S, 900)
        self.assertLessEqual(data["expires_at"] - data["decided_at"], pm.TTL_S + 0.001)
        self.assertEqual(data["roles"]["codex"], "UNKNOWN")

    def test_expiry_never_outlives_inputs(self) -> None:
        # D-R3: a presence heartbeat expiring in 60 s caps the decision at 60 s, not 900 s.
        presence.mark(self.project, "claude", "ACTIVE", now=self.now, ttl_s=60)
        d = self._snap(lambda *a: True)
        self.assertLessEqual(d["expires_at"], self.now + 60 + 0.001)
        # rev 3 item 2: an S1 window observed 800 s ago with max age 900 caps the decision at +100 s.
        presence.mark(self.project, "claude", "ACTIVE", now=self.now, ttl_s=3600)
        d = self._snap(lambda *a: True, age=800)
        self.assertLessEqual(d["expires_at"], self.now + 100 + 1)
        # rev 3 item 3: NaN / inf are ignored as inputs, never extend or poison the expiry.
        d2 = pm.decide_with_expiry(states(claude="ACTIVE"), {"claude": True}, now=self.now,
                                   input_expiries=[float("nan"), float("inf"), self.now + 30])
        self.assertEqual(d2["expires_at"], self.now + 30)

    def test_empty_home_is_halt(self) -> None:
        # Default admission (S1 producer, no pools bound) over a temp home with no quota source.
        d = pm.snapshot(self.project, home=self.home, now=self.now)
        self.assertEqual(d["mode"], "HALT")
        self.assertEqual(d["roles"]["claude"], "JUDGE_ONLY")

    def test_gate(self) -> None:
        # D-R2: no snapshot fails closed.
        self.assertEqual(pm.gate_dispatch(self.project, "claude", now=self.now),
                         {"allowed": False, "reason": "NO_SNAPSHOT"})
        path = self.project / pm.SNAPSHOT
        path.write_text(json.dumps({"mode": "SOLO", "roles": {"claude": "EXECUTOR", "antigravity": "JUDGE_ONLY",
                                                                "codex": "UNKNOWN"},
                                    "decided_at": self.now, "expires_at": self.now + pm.TTL_S}), encoding="utf-8")
        self.assertTrue(pm.gate_dispatch(self.project, "claude", now=self.now)["allowed"])
        for tool in ("antigravity", "codex"):
            self.assertFalse(pm.gate_dispatch(self.project, tool, now=self.now)["allowed"], tool)
        # D-R1: judge purpose — JUDGE_ONLY only for a keypoint, EXECUTOR always, UNKNOWN never.
        self.assertTrue(pm.gate_dispatch(self.project, "claude", purpose="judge", now=self.now)["allowed"])
        self.assertFalse(pm.gate_dispatch(self.project, "antigravity", purpose="judge", now=self.now)["allowed"])
        # rev 3 item 1: a keypoint needs a reservation that the reservation check confirms with exact True.
        self.assertEqual(pm.gate_dispatch(self.project, "antigravity", purpose="judge", keypoint=True,
                                          now=self.now)["reason"], "NO_RESERVATION")
        for ok in (lambda t, r: False, lambda t, r: 1, lambda t, r: 1 / 0, None):
            self.assertFalse(pm.gate_dispatch(self.project, "antigravity", purpose="judge", keypoint=True,
                                              reservation={"id": "r1"}, reservation_ok=ok, now=self.now)["allowed"])
        self.assertTrue(pm.gate_dispatch(self.project, "antigravity", purpose="judge", keypoint=True,
                                         reservation={"id": "r1"}, reservation_ok=lambda t, r: True,
                                         now=self.now)["allowed"])
        self.assertFalse(pm.gate_dispatch(self.project, "antigravity", purpose="judge", keypoint=True,
                                          reservation=None, reservation_ok=lambda t, r: True,
                                          now=self.now)["allowed"])
        self.assertFalse(pm.gate_dispatch(self.project, "codex", purpose="judge", keypoint=True,
                                          reservation={"id": "r"}, reservation_ok=lambda t, r: True,
                                          now=self.now)["allowed"])
        # rev 3 item 3: now == expires_at refuses; NaN / missing expiry refuses.
        self.assertFalse(pm.gate_dispatch(self.project, "claude", now=self.now + pm.TTL_S)["allowed"])
        self.assertTrue(pm.gate_dispatch(self.project, "claude", now=self.now + pm.TTL_S - 1)["allowed"])
        for bad in ("NaN", None, "Infinity"):
            raw = json.dumps({"mode": "SOLO", "roles": {"claude": "EXECUTOR"}, "decided_at": self.now,
                              "expires_at": bad}).replace('"NaN"', "NaN").replace('"Infinity"', "Infinity")
            path.write_text(raw, encoding="utf-8")
            self.assertFalse(pm.gate_dispatch(self.project, "claude", now=self.now)["allowed"], bad)
        path.write_text("{not json", encoding="utf-8")
        self.assertFalse(pm.gate_dispatch(self.project, "claude", now=self.now)["allowed"])


WRITER = r"""
import sys, time
from pathlib import Path
from v7_harness.coord import participation as pm
from v7_harness.coord import presence
from tests.test_s5_participation_mode import s1_account
project, home, t0, revoke = Path(sys.argv[1]), Path(sys.argv[2]), float(sys.argv[3]), sys.argv[4] == "1"
go = float(sys.argv[5])
accounts = {t: s1_account(t, t0) for t in ("codex", "claude", "antigravity")}
while time.time() < go:
    time.sleep(0.005)
for i in range(20):
    # The revoker decides later (t0 + 100) with no admission; the others keep writing older admitting decisions.
    when = t0 + 100 if revoke else t0 + i * 0.01
    pm.snapshot(project, home=home, now=when, accounts=accounts,
                admit=(lambda *a: False) if revoke else (lambda *a: True))
"""

# rev 3 item 4: a dispatcher that passed the gate holds the guard while it "sends"; a revoking writer started during
# the send must land only after the send finished, and a gate checked after the revocation must refuse.
RACE_DISPATCHER = r"""
import sys, time
from pathlib import Path
from v7_harness.coord import participation as pm
project, marks = Path(sys.argv[1]), Path(sys.argv[2])
with pm.dispatch_guard(project):
    allowed = pm.gate_dispatch(project, "claude")["allowed"]
    (marks / "in_flight").write_text(str(time.time()), encoding="utf-8")
    time.sleep(1.5)
    (marks / "sent").write_text(f"{time.time()} {allowed}", encoding="utf-8")
"""
RACE_WRITER = r"""
import sys, time
from pathlib import Path
from v7_harness.coord import participation as pm
from tests.test_s5_participation_mode import s1_account
project, marks = Path(sys.argv[1]), Path(sys.argv[2])
while not (marks / "in_flight").exists():
    time.sleep(0.005)
now = time.time()
pm.snapshot(project, home=project, now=now, admit=lambda *a: False,
            accounts={t: s1_account(t, now) for t in ("codex", "claude", "antigravity")})
(marks / "revoked").write_text(str(time.time()), encoding="utf-8")
"""


class A10GateSendRevocationRace(unittest.TestCase):
    def test_revocation_waits_for_in_flight_send(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, marks = Path(tmp) / "p", Path(tmp) / "m"
            (project / ".coord").mkdir(parents=True)
            marks.mkdir()
            now = time.time()
            presence.mark(project, "claude", "ACTIVE", now=now, ttl_s=3600)
            pm.snapshot(project, home=project, now=now, admit=lambda *a: True,
                        accounts={t: s1_account(t, now) for t in TOOLS})
            env = {**os.environ, "PYTHONPATH": str(ROOT)}
            writer = subprocess.Popen([sys.executable, "-c", RACE_WRITER, str(project), str(marks)], env=env,
                                      cwd=str(ROOT), stderr=subprocess.PIPE)
            disp = subprocess.Popen([sys.executable, "-c", RACE_DISPATCHER, str(project), str(marks)], env=env,
                                    cwd=str(ROOT), stderr=subprocess.PIPE)
            for p in (disp, writer):
                _, err = p.communicate(timeout=120)
                self.assertEqual(p.returncode, 0, err.decode(errors="replace"))
            sent_at, allowed = (marks / "sent").read_text(encoding="utf-8").split()
            self.assertEqual(allowed, "True")
            self.assertGreaterEqual(float((marks / "revoked").read_text(encoding="utf-8")), float(sent_at))
            self.assertFalse(pm.gate_dispatch(project, "claude")["allowed"])
            self.assertEqual(list((project / pm.READERS).iterdir()), [])


class A7ParallelRevocation(unittest.TestCase):
    def test_later_revocation_survives_concurrent_older_writers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, home = Path(tmp) / "p", Path(tmp) / "h"
            (project / ".coord").mkdir(parents=True)
            home.mkdir()
            t0 = time.time()
            presence.mark(project, "claude", "ACTIVE", now=t0, ttl_s=3600)
            env = {**os.environ, "PYTHONPATH": str(ROOT)}
            go = str(time.time() + 3)
            procs = [subprocess.Popen([sys.executable, "-c", WRITER, str(project), str(home), str(t0),
                                       "1" if n == 0 else "0", go], env=env, cwd=str(ROOT),
                                      stderr=subprocess.PIPE) for n in range(4)]
            for p in procs:
                _, err = p.communicate(timeout=120)
                self.assertEqual(p.returncode, 0, err.decode(errors="replace"))
            data = json.loads((project / pm.SNAPSHOT).read_text(encoding="utf-8"))
            self.assertEqual(data["decided_at"], t0 + 100)
            self.assertEqual(data["roles"]["claude"], "JUDGE_ONLY")
            self.assertFalse(pm.gate_dispatch(project, "claude", now=t0 + 100)["allowed"])
            self.assertFalse((project / ".coord" / "participation.json.lock").exists())


class A8DispatchGate(unittest.TestCase):
    def test_barred_tool_sends_nothing(self) -> None:
        from v7_harness.coord import process_lanes as pl
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".coord").mkdir()
            (project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
            now = time.time()
            for t in TOOLS:
                presence.mark(project, t, "ACTIVE", now=now)
            (project / pm.SNAPSHOT).write_text(json.dumps({
                "mode": "HALT", "roles": {t: "JUDGE_ONLY" for t in TOOLS},
                "decided_at": now, "expires_at": now + pm.TTL_S}), encoding="utf-8")
            sent = []
            item = pl.ProcessItem(item_id="i1", source="direct", lane_id="IMPL_CODE", actor="claude",
                                  requested_target="antigravity", card="S5", summary="s", payload={}, priority=1)
            result = pl.dispatch_single_lane_batch(
                project, "IMPL_CODE", [item], actor="claude",
                custom_sender=lambda *a: sent.append(a) or {"ok": True, "reason": "SENT", "message_id": "m"})
            self.assertEqual(sent, [])
            self.assertFalse(result["ok"])
            self.assertEqual(result["state"], "PARTICIPATION_BLOCKED")

    def test_barred_pick_reroutes_to_admitted_executor(self) -> None:
        """Rev 4: SOLO with claude as the only EXECUTOR still dispatches when the lane would pick antigravity."""
        from v7_harness.coord import process_lanes as pl
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".coord").mkdir()
            (project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
            now = time.time()
            for t in TOOLS:
                presence.mark(project, t, "ACTIVE", now=now)
            (project / pm.SNAPSHOT).write_text(json.dumps({
                "mode": "SOLO", "roles": {"codex": "JUDGE_ONLY", "claude": "EXECUTOR", "antigravity": "JUDGE_ONLY"},
                "decided_at": now, "expires_at": now + pm.TTL_S}), encoding="utf-8")
            sent = []
            item = pl.ProcessItem(item_id="i2", source="direct", lane_id="IMPL_CODE", actor="claude",
                                  requested_target="antigravity", card="S5", summary="s", payload={}, priority=1)
            pl.dispatch_single_lane_batch(
                project, "IMPL_CODE", [item], actor="claude",
                custom_sender=lambda *a: sent.append(a) or {"ok": True, "reason": "SENT", "message_id": "m"})
            self.assertEqual(len(sent), 1)
            self.assertIn("claude", sent[0])
            self.assertNotIn("antigravity", [a for a in sent[0] if isinstance(a, str) and a in TOOLS])


    def _desk(self, tmp: str, roles: dict[str, str]) -> Path:
        project = Path(tmp)
        (project / ".coord").mkdir()
        (project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        now = time.time()
        for t in TOOLS:
            presence.mark(project, t, "ACTIVE", now=now)
        (project / pm.SNAPSHOT).write_text(json.dumps({
            "mode": "DUO", "roles": roles, "decided_at": now, "expires_at": now + pm.TTL_S}), encoding="utf-8")
        return project

    def test_failover_walks_past_barred_alternate(self) -> None:
        """Rev 5: primary antigravity fails delivery; codex (first alternate) is barred; claude still gets it."""
        from v7_harness.coord import process_lanes as pl
        with tempfile.TemporaryDirectory() as tmp:
            project = self._desk(tmp, {"codex": "JUDGE_ONLY", "claude": "EXECUTOR", "antigravity": "EXECUTOR"})
            sent = []

            def sender(lid, tool, window_id, envelope, items):
                sent.append(tool)
                return {"ok": tool != "antigravity", "reason": "SENT" if tool != "antigravity" else "FAILED",
                        "message_id": "m"}

            item = pl.ProcessItem(item_id="i3", source="direct", lane_id="IMPL_CODE", actor="claude",
                                  requested_target="antigravity", card="S5", summary="s", payload={}, priority=1)
            pl.dispatch_single_lane_batch(project, "IMPL_CODE", [item], actor="claude", custom_sender=sender)
            self.assertEqual(sent, ["antigravity", "claude"])

    def test_verify_batch_never_goes_to_its_author(self) -> None:
        """Rev 6: a VERIFY_AUDIT item authored by claude, requested for claude, is judged by another EXECUTOR."""
        from v7_harness.coord import process_lanes as pl
        with tempfile.TemporaryDirectory() as tmp:
            project = self._desk(tmp, {"codex": "EXECUTOR", "claude": "EXECUTOR", "antigravity": "JUDGE_ONLY"})
            sent = []
            item = pl.ProcessItem(item_id="i4", source="direct", lane_id="VERIFY_AUDIT", actor="claude",
                                  requested_target="claude", card="S5", summary="s", payload={}, priority=1)
            pl.dispatch_single_lane_batch(project, "VERIFY_AUDIT", [item], actor="claude",
                                          custom_sender=lambda lid, tool, *a: sent.append(tool) or
                                          {"ok": True, "reason": "SENT", "message_id": "m"})
            self.assertEqual(sent, ["codex"])

    def test_verify_batch_with_only_author_admitted_sends_nothing(self) -> None:
        from v7_harness.coord import process_lanes as pl
        with tempfile.TemporaryDirectory() as tmp:
            project = self._desk(tmp, {"codex": "JUDGE_ONLY", "claude": "EXECUTOR", "antigravity": "JUDGE_ONLY"})
            sent = []
            item = pl.ProcessItem(item_id="i5", source="direct", lane_id="VERIFY_AUDIT", actor="claude",
                                  requested_target="claude", card="S5", summary="s", payload={}, priority=1)
            result = pl.dispatch_single_lane_batch(project, "VERIFY_AUDIT", [item], actor="claude",
                                                   custom_sender=lambda *a: sent.append(a) or {"ok": True})
            self.assertEqual(sent, [])
            self.assertEqual(result["state"], "PARTICIPATION_BLOCKED")

    def test_handoff_to_barred_tools_sends_nothing(self) -> None:
        """Rev 5: a handoff is paid work for the receiver; with no admitted receiver nothing is delivered."""
        from v7_harness.coord import process_lanes as pl
        with tempfile.TemporaryDirectory() as tmp:
            project = self._desk(tmp, {"codex": "JUDGE_ONLY", "claude": "EXECUTOR", "antigravity": "JUDGE_ONLY"})
            result = pl.handoff_lane_result(project, lane_id="VERIFY_AUDIT", from_tool="claude", to_tool="codex",
                                            card="S5", summary="verdict please", verdict_requested=True)
            self.assertFalse(result["ok"])
            self.assertEqual(result["state"], "PARTICIPATION_BLOCKED")
            self.assertEqual(set(result["barred"]), {"codex", "antigravity"})
            inbox = project / ".coord" / "mailbox" / "inbox"
            self.assertEqual(list(inbox.glob("*.json")) if inbox.is_dir() else [], [])


class A11LockHeartbeat(unittest.TestCase):
    def test_waiting_writer_keeps_lock_past_stale_bound(self) -> None:
        """Rev 4: a writer waiting for an in-flight dispatch is alive; the stale bound never hands its lock away."""
        import threading
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".coord").mkdir()
            readers = project / pm.READERS
            readers.mkdir(parents=True)
            token = readers / "inflight"
            token.write_text("x", encoding="utf-8")
            old = pm.LOCK_STALE_S
            pm.LOCK_STALE_S = 0.2
            try:
                now = time.time()
                decision = {"mode": "HALT", "roles": {}, "decided_at": now, "expires_at": now + 60}
                writer = threading.Thread(target=pm.write, args=(project, decision))
                writer.start()
                time.sleep(0.8)  # four stale bounds while the writer still waits
                with self.assertRaises(TimeoutError):
                    with pm._lock(project, timeout_s=0.5):
                        pass
                token.unlink()
                writer.join(timeout=10)
                self.assertFalse(writer.is_alive())
                self.assertEqual(json.loads((project / pm.SNAPSHOT).read_text(encoding="utf-8"))["mode"], "HALT")
            finally:
                pm.LOCK_STALE_S = old


class A9Cli(unittest.TestCase):
    def test_participation_and_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".coord").mkdir()
            (project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
            presence.mark(project, "claude", "ACTIVE")
            env = {**os.environ, "PYTHONPATH": str(ROOT), "HOME": tmp, "USERPROFILE": tmp}
            out = subprocess.run([sys.executable, "-m", "v7_harness.cli", "coord", "participation",
                                  "--project", str(project), "--home", tmp],
                                 capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=120)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn(json.loads(out.stdout)["mode"], ("TRIO", "DUO", "SOLO", "HALT"))
            route = subprocess.run([sys.executable, "-m", "v7_harness.cli", "coord", "route", "--project", str(project)],
                                   capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=120)
            self.assertIn("participation", json.loads(route.stdout))

    def test_lanes_dispatch_without_pools_keeps_standing_snapshot(self) -> None:
        """Rev 4: a pool-less refresh would turn every tool JUDGE_ONLY; dispatch without --pool leaves it alone."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".coord").mkdir()
            (project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
            now = time.time()
            standing = json.dumps({"mode": "SOLO", "roles": {"codex": "JUDGE_ONLY", "claude": "EXECUTOR",
                                                              "antigravity": "JUDGE_ONLY"},
                                   "decided_at": now, "expires_at": now + pm.TTL_S})
            (project / pm.SNAPSHOT).write_text(standing, encoding="utf-8")
            env = {**os.environ, "PYTHONPATH": str(ROOT), "HOME": tmp, "USERPROFILE": tmp}
            subprocess.run([sys.executable, "-m", "v7_harness.cli", "coord", "lanes", "--action", "dispatch",
                            "--project", str(project)],
                           capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=120)
            self.assertEqual((project / pm.SNAPSHOT).read_text(encoding="utf-8"), standing)


if __name__ == "__main__":
    unittest.main()
