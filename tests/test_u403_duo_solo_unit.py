"""U403: any 2 tools are a complete unit; one tool alone can finish an emergency card (user doc 261127, R2).

Receipt: 2026-11-28 Antigravity LIMITED froze 8 card windows; in DUO_CODEX_CLAUDE a Codex-authored card had no judge
(WAIT_FOR_JUDGE) and every SOLO regime could only park work. These tests fix the acceptance: each DUO routes author +
non-author peer judge + merger, SOLO finishes only an explicit emergency card with a reference-only fresh-session judge,
a mandatory re-review on return and a build/reinstall/test tail, and UNKNOWN never counts as alive (fail closed).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NOW = 1_800_000_000.0
CARD = {"card": "U990", "allowed_files": ["v7_harness/coord/situational_ops.py"]}
EMERGENCY = dict(CARD, card="U991", emergency=True)
KEY = {"card": "U992", "allowed_files": ["v7_harness/calculator_gate.py"]}
DUOS = {"DUO_CLAUDE_AGY": ("claude", "antigravity"), "DUO_CODEX_AGY": ("codex", "antigravity"),
        "DUO_CODEX_CLAUDE": ("codex", "claude")}
SOLOS = {"SOLO_CLAUDE": "claude", "SOLO_AGY": "antigravity", "SOLO_CODEX": "codex"}


def _desk(codex: str, claude: str, agy: str) -> dict:
    rec = lambda s: {"state": s, "observed_at": NOW - 10.0}  # noqa: E731
    return {"codex": rec(codex), "claude": rec(claude), "antigravity": rec(agy)}


class DuoUnitTests(unittest.TestCase):
    def test_every_duo_completes_a_card_for_either_author(self) -> None:
        from v7_harness.coord.situational_ops import work_steal_route

        for regime, members in DUOS.items():
            for author in members:
                with self.subTest(regime=regime, author=author):
                    route = work_steal_route(regime, dict(CARD, author=author))
                    self.assertIn(route["action"], ("RUN", "RUN_DUO_PEER"))
                    judge = route["judge"] or route["peer_judge"]
                    self.assertIn(judge, members)
                    self.assertNotEqual(judge, author)
                    self.assertIn(route["merger"], members)

    def test_codex_authored_card_in_duo_codex_claude_is_peer_judged_and_rereviewed(self) -> None:
        from v7_harness.coord.situational_ops import work_steal_route

        route = work_steal_route("DUO_CODEX_CLAUDE", dict(CARD, author="codex"))
        self.assertEqual((route["action"], route["judge"], route["peer_judge"]), ("RUN_DUO_PEER", "", "claude"))
        self.assertEqual(route["rereview"], "REQUIRED_ON_RETURN")

    def test_formal_judge_route_is_unchanged(self) -> None:
        from v7_harness.coord.situational_ops import work_steal_route

        route = work_steal_route("DUO_CODEX_CLAUDE", CARD)
        self.assertEqual((route["action"], route["judge"], route["peer_judge"]), ("RUN", "codex", ""))


class SoloEmergencyTests(unittest.TestCase):
    def test_each_solo_finishes_an_emergency_card_end_to_end(self) -> None:
        from v7_harness.coord.situational_ops import SELF_TEST_TAIL, work_steal_route

        for regime, tool in SOLOS.items():
            with self.subTest(regime=regime):
                route = work_steal_route(regime, dict(EMERGENCY, author="someone_absent"))
                self.assertEqual(route["action"], "SOLO_EMERGENCY_FINISH")
                self.assertEqual(route["author"], tool)
                self.assertEqual(route["judge"], "")  # never a formal self-approval
                self.assertEqual(route["reference_judge"], f"{tool}:fresh_session")
                self.assertEqual(route["rereview"], "REQUIRED_ON_RETURN")
                self.assertEqual(route["self_test_tail"], SELF_TEST_TAIL)
                self.assertEqual(SELF_TEST_TAIL, ("build", "reinstall", "test"))

    def test_solo_without_emergency_flag_still_waits(self) -> None:
        from v7_harness.coord.situational_ops import work_steal_route

        for regime in SOLOS:
            self.assertEqual(work_steal_route(regime, CARD)["action"], "WAIT_FOR_JUDGE")
            self.assertEqual(work_steal_route(regime, dict(CARD, emergency="yes"))["action"], "WAIT_FOR_JUDGE")

    def test_solo_keypoint_still_queues_for_codex(self) -> None:
        from v7_harness.coord.situational_ops import work_steal_route

        for regime in ("SOLO_CLAUDE", "SOLO_AGY"):
            self.assertEqual(work_steal_route(regime, dict(KEY, emergency=True))["action"], "QUEUE_FOR_CODEX")

    def test_emergency_flag_is_ignored_when_a_peer_is_alive(self) -> None:
        from v7_harness.coord.situational_ops import work_steal_route

        self.assertEqual(work_steal_route("DUO_CODEX_CLAUDE", EMERGENCY)["action"], "RUN")
        self.assertEqual(work_steal_route("TRIO", EMERGENCY)["action"], "RUN")


class AuthorReassignTests(unittest.TestCase):
    """R2 HOLD 1: an author that is not alive in the regime never keeps the card (Codex verdict 2026-11-28)."""

    def test_absent_author_is_reassigned_to_first_live_tool_in_every_regime(self) -> None:
        from v7_harness.coord.situational_ops import AUTHOR_ORDER, work_steal_route, _members

        for regime in list(DUOS) + list(SOLOS) + ["TRIO"]:
            members = _members(regime)
            for absent in sorted({"codex", "claude", "antigravity"} - members):
                with self.subTest(regime=regime, absent=absent):
                    route = work_steal_route(regime, dict(CARD, author=absent))
                    self.assertEqual(route["author"], next(t for t in AUTHOR_ORDER if t in members))
                    self.assertEqual(route["author_reassigned_from"], absent)
                    self.assertNotEqual(route["judge"] or route["peer_judge"], route["author"])

    def test_duo_codex_claude_with_antigravity_author_runs_under_claude(self) -> None:
        from v7_harness.coord.situational_ops import work_steal_route

        route = work_steal_route("DUO_CODEX_CLAUDE", dict(CARD, author="antigravity"))
        self.assertEqual((route["action"], route["author"], route["judge"]), ("RUN", "claude", "codex"))
        self.assertEqual(route["author_reassigned_from"], "antigravity")

    def test_live_author_is_kept_and_not_marked(self) -> None:
        from v7_harness.coord.situational_ops import work_steal_route

        for regime, members in DUOS.items():
            for author in members:
                route = work_steal_route(regime, dict(CARD, author=author))
                self.assertEqual((route["author"], route["author_reassigned_from"]), (author, ""))
        self.assertEqual(work_steal_route("DUO_CODEX_CLAUDE", CARD)["author_reassigned_from"], "")

    def test_keypoint_queue_and_solo_finish_also_reassign(self) -> None:
        from v7_harness.coord.situational_ops import work_steal_route

        route = work_steal_route("DUO_CLAUDE_AGY", dict(KEY, author="codex"))
        self.assertEqual((route["action"], route["author"], route["author_reassigned_from"]),
                         ("QUEUE_FOR_CODEX", "claude", "codex"))
        route = work_steal_route("SOLO_AGY", dict(EMERGENCY, author="claude"))
        self.assertEqual((route["author"], route["author_reassigned_from"]), ("antigravity", "claude"))


class RegimeEntryPointTests(unittest.TestCase):
    """R2 HOLD 2: `coord regime --card <ID> [--emergency]` is the deterministic call path for the route."""

    def test_route_from_presence_fails_closed_without_observed_at(self) -> None:
        from v7_harness.coord.situational_ops import route_from_presence

        for presence in (None, {}, "corrupt", {"claude": {"state": "ACTIVE"}}, {"claude": "ACTIVE"}):
            with self.subTest(presence=presence):
                out = route_from_presence(presence, EMERGENCY, now=NOW)
                self.assertEqual((out["regime"], out["alive"]), ("LOCAL_ONLY", []))
                self.assertEqual(out["route"]["action"], "LOCAL_ONLY_HOLD")

    def test_route_from_presence_matches_detect_regime(self) -> None:
        from v7_harness.coord.situational_ops import route_from_presence

        out = route_from_presence(_desk("ACTIVE", "ACTIVE", "LIMITED"), dict(CARD, author="antigravity"), now=NOW)
        self.assertEqual((out["regime"], out["alive"]), ("DUO_CODEX_CLAUDE", ["claude", "codex"]))
        self.assertEqual((out["route"]["author"], out["route"]["author_reassigned_from"]), ("claude", "antigravity"))
        out = route_from_presence(_desk("UNKNOWN", "ACTIVE", "LIMITED"), EMERGENCY, now=NOW)
        self.assertEqual(out["route"]["action"], "SOLO_EMERGENCY_FINISH")

    def test_cli_prints_route_json_from_the_presence_file(self) -> None:
        import contextlib
        import io
        import json
        import tempfile
        import time
        from unittest import mock

        from v7_harness.cli import main

        now = time.time()
        desk = {"codex": {"state": "LIMITED", "observed_at": now}, "claude": {"state": "ACTIVE", "observed_at": now},
                "antigravity": {"state": "LIMITED", "observed_at": now}}
        # R3: exit 0 now also needs the canonical admission; this fixture admits the live executor (claude).
        with tempfile.TemporaryDirectory() as tmp, mock.patch("v7_harness.coord.presence.read_all", return_value=desk), \
                mock.patch("v7_harness.coord.quota_sources.measured_accounts", return_value=None), \
                mock.patch("v7_harness.coord.participation.admissions",
                           return_value={"codex": False, "claude": True, "antigravity": False}):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = main(["coord", "regime", "--project", tmp, "--card", "U993", "--author", "codex", "--emergency"])
            out = json.loads(buf.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual((out["regime"], out["route"]["card"]), ("SOLO_CLAUDE", "U993"))
            self.assertEqual(out["route"]["action"], "SOLO_EMERGENCY_FINISH")
            self.assertEqual(out["route"]["author_reassigned_from"], "codex")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = main(["coord", "regime", "--project", tmp, "--card", "U994"])
            out = json.loads(buf.getvalue())
            self.assertEqual((code, out["route"]["action"]), (1, "WAIT_FOR_JUDGE"))


class RegimeAdmissionTests(unittest.TestCase):
    """R3 REVISE: a presence route is a suggestion; `coord regime` exits 0 only with a canonical admission."""

    def _run(self, desk_states: tuple, admitted=None, *, admit_error=None, accounts_error=None, snapshot=None,
             author="codex", emergency=False):
        import contextlib
        import io
        import json
        import tempfile
        import time
        from unittest import mock

        from v7_harness.cli import main

        now = time.time()
        desk = {t: {"state": s, "observed_at": now} for t, s in zip(("codex", "claude", "antigravity"), desk_states)}
        patches = [mock.patch("v7_harness.coord.presence.read_all", return_value=desk),
                   mock.patch("v7_harness.coord.quota_sources.measured_accounts",
                              side_effect=accounts_error, return_value=None)]
        if admitted is not None or admit_error is not None:
            patches.append(mock.patch("v7_harness.coord.participation.admissions",
                                      side_effect=admit_error, return_value=admitted))
        if snapshot is not None:
            patches.append(mock.patch("v7_harness.coord.participation.snapshot", return_value=snapshot))
        argv = ["coord", "regime", "--card", "U995", "--author", author] + (["--emergency"] if emergency else [])
        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = main(argv[:2] + ["--project", tmp] + argv[2:])
            self.assertFalse((Path(tmp) / ".coord" / "participation.json").exists())  # read-only check
        return code, json.loads(buf.getvalue())

    def test_halt_denies_execution_despite_fresh_presence(self) -> None:
        code, out = self._run(("ACTIVE", "ACTIVE", "LIMITED"), {"codex": False, "claude": False, "antigravity": False})
        self.assertEqual(out["route"]["action"], "RUN_DUO_PEER")
        self.assertEqual((code, out["admissions_consulted"], out["ready"]), (1, True, False))
        self.assertEqual((out["admission"]["mode"], out["admission"]["reason"]), ("HALT", "HALT"))

    def test_judge_only_author_or_judge_denies_execution(self) -> None:
        code, out = self._run(("ACTIVE", "ACTIVE", "LIMITED"), {"codex": False, "claude": True, "antigravity": False})
        self.assertEqual((code, out["admission"]["reason"]), (1, "AUTHOR_JUDGE_ONLY"))
        code, out = self._run(("ACTIVE", "ACTIVE", "LIMITED"), {"codex": True, "claude": False, "antigravity": False})
        self.assertEqual(out["route"]["peer_judge"], "claude")
        self.assertEqual((code, out["admission"]["reason"]), (1, "JUDGE_JUDGE_ONLY"))

    def test_admitted_executor_route_returns_zero(self) -> None:
        code, out = self._run(("ACTIVE", "ACTIVE", "LIMITED"), {"codex": True, "claude": True, "antigravity": False})
        self.assertEqual((code, out["ready"], out["admission"]["reason"]), (0, True, "EXECUTOR_ADMITTED"))
        self.assertEqual(out["admission"]["author_role"], "EXECUTOR")

    def test_missing_or_failed_admission_data_fails_closed(self) -> None:
        both = ("ACTIVE", "ACTIVE", "LIMITED")
        code, out = self._run(both, accounts_error=OSError("no quota files"))  # real admissions on no data
        self.assertEqual((code, out["admission"]["mode"]), (1, "HALT"))
        code, out = self._run(both, admit_error=RuntimeError("producer"))
        self.assertEqual((code, out["admission"]["reason"]), (1, "ADMISSION_ERROR:RuntimeError"))
        for snap, reason in (({"mode": "DUO"}, "ADMISSION_ERROR:ValueError"),
                             ({"mode": "DUO", "roles": {"codex": "EXECUTOR", "claude": "EXECUTOR"},
                               "expires_at": 0.0}, "DECISION_EXPIRED"),
                             ({"mode": "DUO", "roles": {"codex": "EXECUTOR", "claude": "EXECUTOR"},
                               "expires_at": float("nan")}, "DECISION_EXPIRED")):
            with self.subTest(reason=reason):
                code, out = self._run(both, snapshot=snap)
                self.assertEqual((code, out["admission"]["reason"]), (1, reason))

    def test_non_runnable_route_stays_nonzero_even_when_admitted(self) -> None:
        code, out = self._run(("LIMITED", "ACTIVE", "LIMITED"), {"codex": False, "claude": True, "antigravity": False},
                              author="claude")
        self.assertEqual((code, out["route"]["action"], out["ready"]), (1, "WAIT_FOR_JUDGE", False))


class FailClosedTests(unittest.TestCase):
    def test_unknown_peers_are_absent_and_unknown_alone_holds(self) -> None:
        from v7_harness.coord.situational_ops import regime_plan

        plan = regime_plan(_desk("UNKNOWN", "ACTIVE", "LIMITED"), [EMERGENCY], now=NOW)
        self.assertEqual(plan["regime"], "SOLO_CLAUDE")
        self.assertEqual(plan["routes"][0]["action"], "SOLO_EMERGENCY_FINISH")
        plan = regime_plan(_desk("UNKNOWN", "UNKNOWN", "UNKNOWN"), [EMERGENCY, CARD], now=NOW)
        self.assertEqual([r["action"] for r in plan["routes"]], ["LOCAL_ONLY_HOLD", "LOCAL_ONLY_HOLD"])
        plan = regime_plan(_desk("UNKNOWN", "ACTIVE", "UNKNOWN"), [CARD], now=NOW)
        self.assertEqual(plan["routes"][0]["action"], "WAIT_FOR_JUDGE")


if __name__ == "__main__":
    unittest.main()
