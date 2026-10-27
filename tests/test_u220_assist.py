"""U220 fixed acceptance: idle peers take a saturated owner's ready implement cards (work stealing).

Receipt (2026-10-19): Codex ran one 16-minute turn while three UAOS relays waited unconsumed in its steer queue and
Claude and Antigravity idled on HANDOFF. 윤겸스 ordered that the other tools help when Codex is the bottleneck.
"""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import next_card as N


NO_RESOURCES = object()


def phase(pid, state="READY", owner="codex", deps=(), resources=None, **extra):
    """A phase that declares its own file and an acceptance command by default (U220-R: an assist needs declared,
    disjoint resources; U220-R2: and a contract)."""
    declared = {} if resources is NO_RESOURCES else {"resources": resources or [f"{pid.lower()}.py"]}
    return {"phase_id": pid, "state": state, "owner_tool": owner, "depends_on": list(deps), **declared,
            "acceptance_cmd": "python -m unittest", **extra}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".coord").mkdir()
        self.now = time.time()
        for tool in ("codex", "claude", "antigravity"):
            self.presence(tool, "ACTIVE")
        # The real Codex rollout log on this machine must not turn the fixture's codex LIMITED.
        quota = mock.patch("v7_harness.coord.presence.codex_quota_block", return_value=None)
        quota.start()
        self.addCleanup(quota.stop)

    def presence(self, tool, state, sessions=None):
        folder = self.root / ".coord" / "presence"
        folder.mkdir(parents=True, exist_ok=True)
        record = {"tool": tool, "state": state, "expires_at": self.now + 3600, "observed_at": None,
                  "sessions": sessions or {f"{tool}-live": self.now + 3600}}
        (folder / f"{tool}.json").write_text(json.dumps(record), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def schedule(self, *phases):
        path = self.root / ".coord" / "master_schedule.json"
        path.write_text(json.dumps({"schedule_id": "T", "phases": list(phases)}), encoding="utf-8")

    def live_claim(self, card, tool, session="busy-session", age=60.0, **extra):
        claims = self.root / ".coord" / "next" / "claims"
        claims.mkdir(parents=True, exist_ok=True)
        record = {"session": session, "tool": tool, "at": self.now - age, **extra}
        (claims / f"{card}.json").write_text(json.dumps(record), encoding="utf-8")

    def letter(self, mid, target="codex", age=N.ASSIST_AGE_S + 60, wake="ACTIONABLE", acked=False, **extra):
        box = self.root / ".coord" / "mailbox"
        (box / "inbox").mkdir(parents=True, exist_ok=True)
        (box / "delivery" / "accepted").mkdir(parents=True, exist_ok=True)
        body = {"actor": "claude", "requested_target": target, "wake_class": wake, "message": "x", **extra}
        (box / "inbox" / f"{mid}.json").write_text(json.dumps({"message_id": mid, "payload": body}), encoding="utf-8")
        stamp = int((self.now - age) * 1e9)
        (box / "delivery" / "accepted" / f"{mid}.json").write_text(
            json.dumps({"state": "DISPATCHED", "timestamp_ns": stamp}), encoding="utf-8")
        if acked:
            (box / "ack").mkdir(parents=True, exist_ok=True)
            (box / "ack" / f"{mid}.json").write_text("{}", encoding="utf-8")

    def step(self, tool="claude", **kw):
        return N.next_step(self.root, tool, now=self.now, **kw)


class Saturation(Base):
    def test_owner_busy_on_a_live_claim_lets_a_peer_assist(self):
        self.schedule(phase("A"), phase("B"))
        self.live_claim("A", "codex")
        out = self.step()
        self.assertEqual(("NEXT", "B", "codex", "codex"), (out["state"], out["card"], out["owner"], out["assist_for"]))

    def test_owner_with_an_old_letter_backlog_lets_a_peer_assist(self):
        self.schedule(phase("A"))
        self.letter("relay_a1")
        self.letter("relay_a2")
        out = self.step()
        self.assertEqual(("NEXT", "A", "codex"), (out["state"], out["card"], out["assist_for"]))

    def test_idle_owner_keeps_its_card(self):
        self.schedule(phase("A"))
        out = self.step()
        self.assertEqual(("HANDOFF", "A", "codex"), (out["state"], out["card"], out["owner"]))
        self.assertNotIn("assist_for", out)

    def test_one_old_letter_is_not_a_backlog(self):
        self.schedule(phase("A"))
        self.letter("relay_a1")
        self.assertEqual("HANDOFF", self.step()["state"])

    def test_fresh_acked_answered_or_quiet_letters_do_not_count(self):
        self.schedule(phase("A"))
        self.letter("relay_new1", age=30)
        self.letter("relay_new2", age=30)
        self.letter("relay_ack", acked=True)
        self.letter("relay_quiet", wake="ACK_ONLY")
        self.letter("relay_other", target="antigravity")
        self.letter("relay_asked")
        self.letter("relay_reply", target="claude", age=10, in_reply_to="relay_asked")
        self.assertEqual("HANDOFF", self.step()["state"])

    def test_stale_letters_from_a_gone_session_are_not_a_backlog(self):
        # Real inbox 2026-10-19: 43 letters to claude older than a day; they mark no live owner busy.
        self.schedule(phase("A"))
        self.letter("relay_old1", age=N.CLAIM_TTL_S + 60)
        self.letter("relay_old2", age=N.CLAIM_TTL_S + 60)
        self.assertEqual("HANDOFF", self.step()["state"])

    def test_a_claim_held_by_a_helper_is_not_owner_saturation(self):
        # Antigravity audit relay_812e5614: match the claim's runner, not the card's owner, so a stolen card does not
        # make the owner look busy.
        self.schedule(phase("A"), phase("B"))
        self.live_claim("A", "antigravity", assist_for="codex")
        self.assertEqual("HANDOFF", self.step()["state"])

    def test_a_lapsed_owner_claim_is_not_saturation(self):
        self.schedule(phase("A"), phase("B"))
        self.live_claim("A", "codex", age=N.CLAIM_TTL_S + 1)
        self.assertEqual("HANDOFF", self.step()["state"])


class Boundaries(Base):
    def setUp(self):
        super().setUp()
        self.live_claim("BUSY", "codex")

    def assert_not_stolen(self, card):
        self.schedule(phase("BUSY", "ACTIVE"), card)
        out = self.step()
        self.assertNotIn("assist_for", out)
        self.assertNotEqual("NEXT", out["state"])

    def test_assist_false_is_never_stolen(self):
        self.assert_not_stolen(phase("A", assist=False))

    def test_verdict_review_judge_and_merge_cards_are_never_stolen(self):
        for pid in ("A-verdict", "A-review", "A-judge", "A-merge"):
            with self.subTest(pid=pid):
                self.assert_not_stolen(phase(pid))
        self.assert_not_stolen(phase("A", note="merge PR #200 after the judge"))

    def test_human_only_and_session_bound_cards_are_never_stolen(self):
        self.assert_not_stolen(phase("A", note="deploy the release"))
        self.assert_not_stolen(phase("A", human="approve spend"))
        self.assert_not_stolen(phase("A", owner_session="codex-thread-1"))

    def test_own_card_wins_over_assist(self):
        self.schedule(phase("BUSY", "ACTIVE"), phase("A"), phase("MINE", owner="claude"))
        out = self.step()
        self.assertEqual(("NEXT", "MINE"), (out["state"], out["card"]))
        self.assertNotIn("assist_for", out)

    def test_owner_never_assists_itself(self):
        self.schedule(phase("BUSY", "ACTIVE"), phase("A", owner="antigravity"))
        self.live_claim("BUSY", "antigravity")
        self.assertNotIn("assist_for", N.next_step(self.root, "antigravity", now=self.now))

    def test_unmet_dependency_is_not_stolen(self):
        self.assert_not_stolen(phase("A", deps=["BUSY"]))


class Claims(Base):
    def test_assist_claim_records_the_helper_and_the_owner(self):
        self.schedule(phase("A"), phase("B"))
        self.live_claim("A", "codex")
        out = self.step(claim=True, session="claude-1")
        self.assertEqual(("NEXT", "B", True), (out["state"], out["card"], out["claimed"]))
        record = json.loads((self.root / ".coord" / "next" / "claims" / "B.json").read_text(encoding="utf-8"))
        self.assertEqual(("claude-1", "claude", "codex"), (record["session"], record["tool"], record["assist_for"]))

    def test_two_helpers_racing_get_one_claim(self):
        self.schedule(phase("A"), phase("B"))
        self.live_claim("A", "codex")
        results, gate = {}, threading.Barrier(2)

        def run(tool):
            gate.wait()
            results[tool] = N.next_step(self.root, tool, claim=True, session=f"{tool}-s", now=self.now)

        threads = [threading.Thread(target=run, args=(t,)) for t in ("claude", "antigravity")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        winners = [t for t, r in results.items() if r.get("claimed")]
        self.assertEqual(1, len(winners), results)


class CodexRevise(Base):
    """Codex REVISE relay_43bbc628: resource and cross-card claim exclusions, current bound evidence, locked recheck."""

    def setUp(self):
        super().setUp()
        self.live_claim("A", "codex")

    def test_a_card_without_declared_resources_is_not_stolen(self):
        self.schedule(phase("A", "ACTIVE"), phase("B", resources=NO_RESOURCES))
        self.assertEqual("HANDOFF", self.step()["state"])

    def test_a_card_sharing_a_resource_with_a_running_card_is_not_stolen(self):
        self.schedule(phase("A", "ACTIVE", resources=["next_card.py"]), phase("B", resources=["next_card.py", "b.py"]))
        self.assertEqual("HANDOFF", self.step()["state"])

    def test_a_running_card_without_declared_resources_blocks_every_assist(self):
        self.schedule(phase("A", "ACTIVE", resources=NO_RESOURCES), phase("B"))
        self.assertEqual("HANDOFF", self.step()["state"])

    def test_a_helper_session_holding_a_claim_takes_no_second_card(self):
        self.schedule(phase("A", "ACTIVE"), phase("B"), phase("Z", "ACTIVE", owner="antigravity"))
        self.live_claim("Z", "claude", session="claude-1")
        out = self.step(claim=True, session="claude-1")
        self.assertFalse(out.get("claimed"), out)
        self.assertFalse((self.root / ".coord" / "next" / "claims" / "B.json").exists())

    def test_an_owner_that_is_not_active_now_is_not_saturated(self):
        for state in ("LIMITED", "ABSENT", "IDLE"):
            with self.subTest(state=state):
                self.presence("codex", state)
                self.schedule(phase("A", "ACTIVE"), phase("B"))
                self.assertEqual("HANDOFF", self.step()["state"])

    def test_letters_bound_to_a_gone_native_session_are_not_current_evidence(self):
        (self.root / ".coord" / "next" / "claims" / "A.json").unlink()
        self.schedule(phase("A"))
        self.letter("relay_g1", native_receiver="codex-gone")
        self.letter("relay_g2", native_receiver="codex-gone")
        self.assertEqual("HANDOFF", self.step()["state"])
        self.letter("relay_l1", native_receiver="codex-live")
        self.letter("relay_l2", native_receiver="codex-live")
        self.assertEqual("codex", self.step().get("assist_for"))

    def race(self, *runners):
        results, gate = [None] * len(runners), threading.Barrier(len(runners))

        def run(i, fn):
            gate.wait()
            results[i] = fn()

        threads = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(runners)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return results

    def test_owner_and_helper_racing_for_one_card_get_one_claim(self):
        self.schedule(phase("A", "ACTIVE"), phase("B"))
        owner = lambda: N.next_step(self.root, "codex", claim=True, session="codex-2", now=self.now)
        helper = lambda: N.next_step(self.root, "claude", claim=True, session="claude-1", now=self.now)
        for _ in range(5):
            (self.root / ".coord" / "next" / "claims" / "B.json").unlink(missing_ok=True)
            results = self.race(owner, helper)
            self.assertEqual(1, sum(bool(r.get("claimed")) and r.get("card") == "B" for r in results), results)

    def test_two_helpers_on_cards_sharing_a_resource_get_one_claim(self):
        # Without the recheck under the lock both would pass the unlocked read and claim B and C.
        self.schedule(phase("A", "ACTIVE"), phase("B", resources=["shared.py"]), phase("C", resources=["shared.py"]))
        for _ in range(5):
            for card in ("B", "C"):
                (self.root / ".coord" / "next" / "claims" / f"{card}.json").unlink(missing_ok=True)
            results = self.race(
                lambda: N.next_step(self.root, "claude", claim=True, session="claude-1", now=self.now),
                lambda: N.next_step(self.root, "antigravity", claim=True, session="agy-1", now=self.now))
            self.assertEqual(1, sum(bool(r.get("claimed")) for r in results), results)


SPAWN = """
import json, sys, time
from unittest import mock
from v7_harness.coord import next_card as N
root, tool, session, now, start = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4]), float(sys.argv[5])
with mock.patch("v7_harness.coord.presence.codex_quota_block", return_value=None):
    while time.time() < start:
        pass
    print(json.dumps(N.next_step(root, tool, claim=True, session=session, now=now)))
"""


class CodexRevise2(Base):
    """Codex REVISE relay_52c2dbec: one step per platform, fail-closed admission, current evidence only, and changes
    that land while a helper decides."""

    def setUp(self):
        super().setUp()
        self.live_claim("A", "codex")

    def claims(self):
        return sorted(p.stem for p in (self.root / ".coord" / "next" / "claims").glob("*.json"))

    def test_one_platform_never_runs_two_steps(self):
        # A second session of the same helper tool on a different card is refused (not only the same session).
        self.schedule(phase("A", "ACTIVE"), phase("B"), phase("Z", "ACTIVE", owner="antigravity"))
        self.live_claim("Z", "claude", session="claude-other")
        self.assertFalse(self.step(claim=True, session="claude-1").get("claimed"))
        self.assertEqual(["A", "Z"], self.claims())

    def test_worktree_and_branch_are_resources(self):
        self.schedule(phase("A", "ACTIVE", branch="feat/x"), phase("B", branch="feat/x"))
        self.assertEqual("HANDOFF", self.step()["state"])
        self.schedule(phase("A", "ACTIVE", branch="feat/x"), phase("B", branch="feat/y"))
        self.assertEqual("B", self.step().get("card"))

    def test_allowed_files_count_as_resources(self):
        self.schedule(phase("A", "ACTIVE", resources=NO_RESOURCES, allowed_files=["x.py"]),
                      phase("B", resources=NO_RESOURCES, allowed_files=["x.py"]))
        self.assertEqual("HANDOFF", self.step()["state"])

    def test_admission_fails_closed(self):
        bad = {
            "no contract": phase("B", acceptance_cmd=""),
            "missing contract": {k: v for k, v in phase("B").items() if k != "acceptance_cmd"},
            "exhausted cap": phase("B", caps={"tokens": {"used": 5, "limit": 5}}),
            "malformed cap": phase("B", caps={"tokens": 5}),
            "malformed deps": phase("B", depends_on="A"),
            "protected history": phase("B", blocker_reason="waits on owner"),
            "gate failed": phase("B", gate_failed=True),
            "malformed resources": phase("B", resources=["ok.py", ""]),
            "empty worktree": phase("B", worktree=""),
        }
        for name, card in bad.items():
            with self.subTest(name=name):
                self.schedule(phase("A", "ACTIVE"), card)
                self.assertNotIn("assist_for", self.step())

    def test_duplicate_ids_fail_closed(self):
        self.schedule(phase("A", "ACTIVE"), phase("B"), phase("B", resources=["other.py"]))
        self.assertNotIn("assist_for", self.step())

    def test_helper_unknown_to_the_desk_takes_nothing(self):
        self.schedule(phase("A", "ACTIVE"), phase("B"))
        for state in ("LIMITED", "ABSENT", "IDLE"):
            with self.subTest(state=state):
                self.presence("claude", state)
                self.assertNotIn("assist_for", self.step())
        (self.root / ".coord" / "presence" / "claude.json").unlink()
        self.assertNotIn("assist_for", self.step())

    def test_a_running_pilot_in_this_checkout_blocks_assist(self):
        self.schedule(phase("A", "ACTIVE"), phase("B"))
        (self.root / ".work").mkdir()
        (self.root / ".work" / "QUIET_LOCK").write_text("x", encoding="utf-8")
        self.assertNotIn("assist_for", self.step())

    def test_acks_replies_superseded_and_future_letters_are_not_evidence(self):
        (self.root / ".coord" / "next" / "claims" / "A.json").unlink()
        self.schedule(phase("A"))
        self.letter("relay_k1", kind="ACK")
        self.letter("relay_r1", in_reply_to="relay_x")
        self.letter("relay_s1")
        self.letter("relay_s2", age=N.ASSIST_AGE_S + 30, supersedes=["relay_s1"])
        self.letter("relay_f1", age=-3600)
        self.assertEqual("HANDOFF", self.step()["state"])
        self.letter("relay_c1")
        self.assertEqual("codex", self.step().get("assist_for"))

    def change_while_deciding(self, change):
        """Run `change` between the helper's unlocked decision and its locked claim (the second claims read)."""
        real, calls = N._live_claims, []

        def spy(*a, **kw):
            calls.append(1)
            if len(calls) == 2:
                change()
            return real(*a, **kw)

        with mock.patch.object(N, "_live_claims", spy):
            out = self.step(claim=True, session="claude-1")
        self.assertGreaterEqual(len(calls), 2)
        return out

    def test_changes_before_the_claim_refuse_it(self):
        changes = {
            "owner claims the card": lambda: self.live_claim("B", "codex", session="codex-2", age=0),
            "dependency reopens": lambda: self.schedule(phase("A", "ACTIVE"), phase("D", "READY"),
                                                        phase("B", deps=["D"])),
            "cap exhausted": lambda: self.schedule(phase("A", "ACTIVE"),
                                                   phase("B", caps={"t": {"used": 1, "limit": 1}})),
            "card leaves READY": lambda: self.schedule(phase("A", "ACTIVE"), phase("B", "REVIEW")),
            "owner finishes": lambda: (self.root / ".coord" / "next" / "claims" / "A.json").unlink(),
            "conflicting resource claimed": lambda: (self.schedule(phase("A", "ACTIVE"), phase("B"),
                                                                   phase("Q", owner="antigravity",
                                                                         resources=["b.py"])),
                                                     self.live_claim("Q", "antigravity", session="agy-1", age=0)),
        }
        for name, change in changes.items():
            with self.subTest(name=name):
                for p in (self.root / ".coord" / "next" / "claims").glob("*.json"):
                    p.unlink()
                self.live_claim("A", "codex")
                self.schedule(phase("A", "ACTIVE"), phase("B"))
                out = self.change_while_deciding(change)
                self.assertFalse(out.get("claimed"), out)
                record = self.root / ".coord" / "next" / "claims" / "B.json"
                self.assertFalse(record.exists() and json.loads(record.read_text(encoding="utf-8"))["tool"] == "claude")

    def test_ack_before_the_claim_refuses_it(self):
        (self.root / ".coord" / "next" / "claims" / "A.json").unlink()
        self.schedule(phase("B"))
        self.letter("relay_q1")
        self.letter("relay_q2")

        def ack():
            (self.root / ".coord" / "mailbox" / "ack").mkdir(parents=True, exist_ok=True)
            for mid in ("relay_q1", "relay_q2"):
                (self.root / ".coord" / "mailbox" / "ack" / f"{mid}.json").write_text("{}", encoding="utf-8")

        self.assertFalse(self.change_while_deciding(ack).get("claimed"))

    def spawn(self, *runners):
        """Real parallel processes released together by a shared start time (not threads of one interpreter)."""
        import os
        import subprocess
        import sys
        start = time.time() + 2.0
        env = {**os.environ, "PYTHONPATH": str(Path(N.__file__).resolve().parents[2])}
        procs = [subprocess.Popen([sys.executable, "-c", SPAWN, str(self.root), tool, session, str(self.now), str(start)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
                 for tool, session in runners]
        outs = [p.communicate(timeout=60) for p in procs]
        for p, (_, err) in zip(procs, outs):
            self.assertEqual(0, p.returncode, err)
        return [json.loads(o.strip().splitlines()[-1]) for o, _ in outs]

    def test_spawned_helpers_on_cards_sharing_a_resource_get_one_claim(self):
        self.schedule(phase("A", "ACTIVE"), phase("B", resources=["shared.py"]), phase("C", resources=["shared.py"]))
        results = self.spawn(("claude", "claude-1"), ("antigravity", "agy-1"))
        self.assertEqual(1, sum(bool(r.get("claimed")) for r in results), results)

    def test_spawned_sessions_of_one_helper_get_one_claim(self):
        self.schedule(phase("A", "ACTIVE"), phase("B"), phase("C"))
        results = self.spawn(("claude", "claude-1"), ("claude", "claude-2"))
        self.assertEqual(1, sum(bool(r.get("claimed")) for r in results), results)

    def test_spawned_owner_and_helper_on_one_card_get_one_claim(self):
        self.schedule(phase("A", "ACTIVE"), phase("B"))
        results = self.spawn(("codex", "codex-2"), ("claude", "claude-1"))
        self.assertEqual(1, sum(bool(r.get("claimed")) and r.get("card") == "B" for r in results), results)


class CodexRework3(Base):
    """Codex REWORK relay_9dbab448: four counterexamples that changed state after the decision or named one resource
    twice. Maintained reproductions of the frozen independent gate (u220_independent_admission_gate.py)."""

    def setUp(self):
        super().setUp()
        self.schedule(phase("A", "ACTIVE"), phase("B"))
        self.live_claim("A", "codex")

    def refused_when_changed_before_claim(self, change):
        real = N._claim

        def changed(*args, **kwargs):
            change()
            return real(*args, **kwargs)

        with mock.patch.object(N, "_claim", side_effect=changed):
            out = self.step(claim=True, session="claude-1")
        self.assertFalse(out.get("claimed", False), out)

    def test_quiet_lock_taken_before_the_claim_refuses_it(self):
        def lock():
            (self.root / ".work").mkdir(exist_ok=True)
            (self.root / ".work" / "QUIET_LOCK").write_text("pilot", encoding="utf-8")
        self.refused_when_changed_before_claim(lock)

    def test_helper_leaving_active_before_the_claim_refuses_it(self):
        for state in ("ABSENT", "LIMITED"):
            with self.subTest(state=state):
                self.refused_when_changed_before_claim(lambda: self.presence("claude", state))
                self.presence("claude", "ACTIVE")

    def test_one_file_named_in_two_cases_is_one_resource(self):
        f = self.root / "shared.py"
        f.write_text("x", encoding="utf-8")
        alias = str(f).upper().replace("\\", "/")
        self.schedule(phase("A", "ACTIVE", resources=[str(f)]), phase("B", resources=[alias]))
        if Path(alias).exists():  # a case-insensitive file system names one file
            self.assertFalse(self.step(claim=True, session="claude-1").get("claimed", False))

    def test_an_assist_in_flight_blocks_an_own_card_of_the_same_tool(self):
        self.assertTrue(self.step(claim=True, session="claude-1").get("claimed"))
        self.schedule(phase("A", "ACTIVE"), phase("B"), phase("C", owner="claude"))
        out = self.step(claim=True, session="claude-2")
        self.assertFalse(out.get("claimed", False), out)
        live = [json.loads(p.read_text(encoding="utf-8")) for p in (self.root / ".coord/next/claims").glob("*.json")]
        self.assertEqual(1, sum(r.get("tool") == "claude" for r in live))

    def test_own_cards_without_an_assist_keep_their_session_contract(self):
        self.schedule(phase("C", owner="claude"), phase("D", owner="claude"))
        self.assertTrue(self.step(claim=True, session="claude-1").get("claimed"))
        self.assertTrue(self.step(claim=True, session="claude-1").get("claimed"))  # the own session renews


class CodexRework4(Base):
    """Codex relay_11836ec0 (REWORK_RESOURCE_IDENTITY): resources are typed identities resolved against one base, and
    unknown bases, kinds or aliases refuse."""

    def assist(self, a, b):
        self.schedule(phase("A", "ACTIVE", **a), phase("B", **b))
        self.live_claim("A", "codex")
        return self.step(claim=True, session="claude-1").get("claimed", False)

    def test_absolute_and_project_relative_names_of_one_file_conflict(self):
        f = self.root / "shared.py"
        f.write_text("x", encoding="utf-8")
        self.assertFalse(self.assist({"resources": [str(f)]}, {"resources": ["shared.py"]}))

    def test_typed_and_untyped_names_of_one_file_conflict(self):
        self.assertFalse(self.assist({"resources": ["file:pkg/a.py"]}, {"resources": ["pkg/./a.py"]}))

    def test_a_directory_covers_its_files_and_a_glob_its_prefix(self):
        self.assertFalse(self.assist({"resources": ["pkg"]}, {"resources": ["pkg/a.py"]}))
        self.assertFalse(self.assist({"resources": ["pkg/*.py"]}, {"resources": ["pkg/b.py"]}))

    def test_a_worktree_is_the_base_of_its_phase_files(self):
        self.assertFalse(self.assist({"resources": ["wt/a.py"]}, {"worktree": "wt", "resources": ["a.py"]}))

    def test_unknown_kind_or_base_refuses(self):
        outside = Path(tempfile.gettempdir()) / "u220_elsewhere.py"
        for label, b in {"unknown kind": {"resources": ["queue:jobs"]},
                         "outside the project": {"resources": [str(outside)]},
                         "escaping the project": {"resources": ["../x.py"]},
                         "non-numeric port": {"resources": ["port:http"]}}.items():
            with self.subTest(label):
                self.assertFalse(self.assist({}, b))

    def test_disjoint_typed_resources_still_assist(self):
        self.assertTrue(self.assist({"resources": ["a.py", "db:main", "port:8080"]},
                                    {"resources": ["b.py", "db:other", "port:8081"]}))
        self.assertFalse(self.assist({"resources": ["a.py", "db:Main"]}, {"resources": ["b.py", "db:main"]}))
        self.assertFalse(self.assist({"resources": ["a.py", "port:08080"]}, {"resources": ["b.py", "port:8080"]}))

    def test_a_symlink_and_its_target_conflict(self):
        (self.root / "real.py").write_text("x", encoding="utf-8")
        try:
            (self.root / "link.py").symlink_to(self.root / "real.py")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks need a privilege here")
        self.assertFalse(self.assist({"resources": ["real.py"]}, {"resources": ["link.py"]}))


class CodexRework5(Base):
    """Codex relay_c4e218ff (cross-kind containment): file and worktree share one physical-path domain; branch, db and
    port stay opaque names compared within their own kind."""

    assist = CodexRework4.assist

    def test_a_file_under_a_claimed_worktree_conflicts_and_the_reverse(self):
        (self.root / "pkg").mkdir()
        (self.root / "pkg" / "a.py").write_text("x", encoding="utf-8")
        self.assertFalse(self.assist({"resources": ["worktree:pkg"]}, {"resources": ["file:pkg/a.py"]}))
        self.assertFalse(self.assist({"resources": ["file:pkg/a.py"]}, {"resources": ["worktree:pkg"]}))

    def test_a_worktree_resource_conflicts_with_a_phase_in_that_worktree(self):
        self.assertFalse(self.assist({"resources": ["worktree:wt"]}, {"worktree": "wt", "resources": ["b.py"]}))

    def test_names_in_different_domains_stay_disjoint(self):
        self.assertTrue(self.assist({"resources": ["x.py", "db:x"]}, {"resources": ["branch:x.py", "port:8080"]}))


if __name__ == "__main__":
    unittest.main()
