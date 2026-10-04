"""U166 frozen acceptance: merges go Antigravity -> Codex by house rule, and a long wait is a failure that is rerouted.

Receipts (2026-10-05): Claude's `gh pr merge` was denied (R21) and Claude listed merges as user work although
Antigravity merged #124-#127 headless; Claude then ended a turn "until Codex returns" with Antigravity ACTIVE.
"""

from __future__ import annotations

import io
import json
import multiprocessing
import os
import subprocess
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from v7_harness.coord import merge_route, stall

ROOT = Path(__file__).resolve().parents[1]
HEAD = "a" * 40
NOW = 2_000_000_000.0
VERDICT = "relay_" + "1" * 32


def _view(state="OPEN", mergeable="MERGEABLE", head=HEAD, branch="claude/u1-x"):
    return {"state": state, "mergeable": mergeable, "headRefOid": head, "headRefName": branch,
            "url": "https://x/pull/7"}


def _letter(root: Path, actor="codex", message=f"U1 PASS on head {HEAD}", relay=VERDICT, sub="inbox") -> None:
    folder = root / ".coord" / "mailbox" / sub
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{relay}.json").write_text(json.dumps({"actor": actor, "message": message}), encoding="utf-8")


class FakeRunner:
    """`gh pr view` answers from `views` in order (the last one repeats); merger calls are recorded."""

    def __init__(self, views, merge_effect=None):
        self.views = list(views)
        self.calls = []
        self.merge_effect = merge_effect or {}

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        if argv[:3] == ["gh", "pr", "view"]:
            view = self.views.pop(0) if len(self.views) > 1 else self.views[0]
            return subprocess.CompletedProcess(argv, 0, json.dumps(view).encode(), b"")
        effect = self.merge_effect.get(argv[0])
        if isinstance(effect, Exception):
            raise effect
        return subprocess.CompletedProcess(argv, effect if isinstance(effect, int) else 0, b"{}", b"")

    def tools(self):
        return [argv[0] for argv, _ in self.calls if argv[0] != "gh"]


DESK_ALL = {t: {"state": "ACTIVE"} for t in ("codex", "claude", "antigravity")}


class MergeRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _letter(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def _merge(self, runner, desk=DESK_ALL, head=HEAD, pr=7, verdict=VERDICT):
        return merge_route.merge(self.root, pr, head, verdict, runner=runner, now=NOW, desk=desk)

    def test_order_is_antigravity_then_codex_and_claude_is_never_a_merger(self):
        self.assertEqual(("antigravity", "codex"), merge_route.MERGERS)
        with self.assertRaises(merge_route.MergeRefused):
            merge_route.tool_argv("claude", 7, HEAD, self.root)

    def test_gate_refuses_before_any_tool_is_called(self):
        for view in (_view(state="MERGED"), _view(mergeable="CONFLICTING"), _view(head="b" * 40)):
            runner = FakeRunner([view])
            row = self._merge(runner)
            self.assertEqual("REFUSED", row["state"], view)
            self.assertEqual([], runner.tools())
        # Malformed arguments never reach gh, a prompt or a path (relay_45a03503 defect 2: injection).
        for kwargs in ({"head": "abc"}, {"pr": "7; gh repo delete"}, {"pr": True}, {"pr": 0},
                       {"verdict": "relay_../../x"}, {"verdict": "relay_" + "2" * 32}):
            runner = FakeRunner([_view()])
            self.assertEqual("REFUSED", self._merge(runner, **kwargs)["state"], kwargs)
            self.assertEqual([], runner.tools(), kwargs)

    def test_the_verdict_is_an_independent_judge_letter_on_this_head_not_a_trailer(self):
        cases = [
            ("claude", f"PASS {HEAD}", "claude/u1-x"),            # Claude is not a judge tool
            ("codex", f"PASS {HEAD}", "codex/u1-x"),              # the author judged its own PR
            ("agy", f"APPROVE {HEAD}", "antigravity/u1-x"),       # agy is Antigravity: still the author
            ("codex", f"REVISE then PASS {HEAD}", "claude/u1-x"),  # the first verdict word decides
            ("codex", f"PASS {'b' * 40}", "claude/u1-x"),         # a verdict on another head
            ("codex", "PASS", "claude/u1-x"),                     # no head at all
            ("codex", f"PASS {HEAD}", "feature/u1-x"),            # unknown author: independence is UNKNOWN
        ]
        for actor, message, branch in cases:
            _letter(self.root, actor=actor, message=message)
            runner = FakeRunner([_view(branch=branch)])
            self.assertEqual("REFUSED", self._merge(runner)["state"], (actor, message, branch))
            self.assertEqual([], runner.tools())
        _letter(self.root, actor="antigravity", message=f"[agy-auto] re relay_x: PASS on {HEAD}", sub="ack")
        (self.root / ".coord" / "mailbox" / "inbox" / f"{VERDICT}.json").unlink()
        runner = FakeRunner([_view(branch="codex/u1-x"), _view(state="MERGED", branch="codex/u1-x")])
        self.assertEqual("MERGED", self._merge(runner)["state"])

    def test_antigravity_merges_first_with_match_head_and_worker_env(self):
        runner = FakeRunner([_view(), _view(state="MERGED")])
        row = self._merge(runner)
        self.assertEqual(("MERGED", "antigravity"), (row["state"], row["merged_by"]))
        self.assertEqual(["agy"], runner.tools())
        argv, kwargs = [c for c in runner.calls if c[0][0] == "agy"][0]
        self.assertIn(f"--match-head-commit {HEAD}", " ".join(argv))
        self.assertNotIn("--dangerously-skip-permissions", argv)
        self.assertEqual("1", kwargs["env"]["UAOS_WORKER"])

    def test_codex_merges_when_antigravity_leaves_the_pr_open(self):
        runner = FakeRunner([_view(), _view(), _view(state="MERGED")], merge_effect={"agy": 1})
        row = self._merge(runner)
        self.assertEqual(("MERGED", "codex"), (row["state"], row["merged_by"]))
        self.assertEqual(["agy", "codex"], runner.tools())
        argv = [c[0] for c in runner.calls if c[0][0] == "codex"][0]
        self.assertIn("workspace-write", argv)
        self.assertFalse(any("danger" in a for a in argv))

    def test_a_crashed_antigravity_falls_through_to_codex(self):
        runner = FakeRunner([_view(), _view(), _view(state="MERGED")], merge_effect={"agy": OSError("gone")})
        self.assertEqual("codex", self._merge(runner)["merged_by"])

    def test_an_away_antigravity_is_skipped(self):
        desk = {**DESK_ALL, "antigravity": {"state": "LIMITED"}}
        runner = FakeRunner([_view(), _view(state="MERGED")])
        row = self._merge(runner, desk=desk)
        self.assertEqual(["codex"], runner.tools())
        self.assertEqual("codex", row["merged_by"])

    def test_a_tool_report_is_not_proof_only_the_pr_state_is(self):
        runner = FakeRunner([_view()])  # both tools exit 0, the PR stays OPEN
        row = self._merge(runner)
        self.assertEqual("FAILED_ALL_ROUTES", row["state"])
        self.assertEqual(["agy", "codex"], runner.tools())
        rows = (self.root / ".coord" / "merges.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual("FAILED_ALL_ROUTES", json.loads(rows[-1])["state"])

    def test_a_closed_pr_stops_the_route(self):
        runner = FakeRunner([_view(), _view(state="CLOSED")])
        self.assertEqual("FAILED_ALL_ROUTES", self._merge(runner)["state"])
        self.assertEqual(["agy"], runner.tools())


def _desk(**states):
    base = {t: {"state": "UNKNOWN"} for t in ("codex", "claude", "antigravity")}
    base.update({t: {"state": s} for t, s in states.items()})
    return base


def _queue(root: Path, target: str, name: str, actor: str, message: str, age_s: float) -> Path:
    folder = root / ".coord" / "mailbox" / "delivery" / "queued" / target
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.json"
    path.write_text(json.dumps({"actor": actor, "message": message, "message_id": name}), encoding="utf-8")
    os.utime(path, (NOW - age_s, NOW - age_s))
    return path


def _schedule(root: Path, phases) -> Path:
    path = root / ".coord" / "master_schedule.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schedule_id": "T", "phases": phases}), encoding="utf-8")
    os.utime(path, (NOW, NOW))  # written "now" in the test clock: a phase's age starts here at the latest
    return path


def _stall_phases(root: Path):
    data = json.loads((root / ".coord" / "master_schedule.json").read_text(encoding="utf-8"))
    return [p for p in data["phases"] if str(p.get("phase_id", "")).startswith("STALL-")]


def _scan_worker(root: str, tool: str, barrier) -> None:
    barrier.wait()
    stall.scan(Path(root), tool, now=NOW, desk=_desk(codex="LIMITED", claude="ACTIVE", antigravity="ACTIVE"))


class StallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".coord").mkdir()
        (self.root / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_short_wait_is_not_a_stall(self):
        _queue(self.root, "codex", "relay_a", "claude", "VERDICT_REQUESTED=YES please", stall.MAX_WAIT_S - 60)
        result = stall.scan(self.root, "claude", now=NOW, desk=_desk(codex="LIMITED", claude="ACTIVE"))
        self.assertEqual([], result["stalled"])

    def test_a_stalled_verdict_goes_to_antigravity_and_is_adopted_when_all_active_tools_agree(self):
        _schedule(self.root, [])
        _queue(self.root, "codex", "relay_v", "claude", "ACTIONABLE_DELTA VERDICT_REQUESTED=YES review U1",
               stall.MAX_WAIT_S + 60)
        desk = _desk(codex="LIMITED", claude="ACTIVE", antigravity="ACTIVE")
        first = stall.scan(self.root, "claude", now=NOW, desk=desk)
        self.assertEqual(1, len(first["stalled"]))
        entry = first["stalled"][0]
        self.assertEqual(("verdict", "codex", "antigravity"), (entry["kind"], entry["waiting_on"], entry["owner"]))
        self.assertEqual([], first["adopted"])  # Antigravity has not agreed yet
        self.assertEqual([], _stall_phases(self.root))
        second = stall.scan(self.root, "antigravity", now=NOW + 5, desk=desk)
        self.assertEqual(1, len(second["adopted"]))
        phase = _stall_phases(self.root)[0]
        self.assertEqual(("READY", "antigravity"), (phase["state"], phase["owner_tool"]))
        self.assertEqual(["antigravity", "claude"], phase["agreed_by"])
        third = stall.scan(self.root, "claude", now=NOW + 10, desk=desk)
        self.assertEqual([], third["adopted"])
        self.assertEqual(1, len(_stall_phases(self.root)))  # adopted once

    def test_an_absent_tool_is_excluded_from_the_agreement(self):
        _schedule(self.root, [{"phase_id": "U9", "state": "BLOCKED", "owner_tool": "codex", "depends_on": [],
                               "waiting_on": "codex-impl"}])
        desk = _desk(codex="ABSENT", claude="ACTIVE")  # Antigravity UNKNOWN: an expired heartbeat is no voter
        stall.scan(self.root, "claude", now=NOW, desk=desk)
        result = stall.scan(self.root, "claude", now=NOW + stall.MAX_WAIT_S + 1, desk=desk)
        self.assertEqual("claude", result["stalled"][0]["owner"])
        self.assertEqual(1, len(result["adopted"]))
        self.assertEqual(["claude"], result["adopted"][0]["agreed_by"])
        # The waiting phase itself is reassigned, so Codex cannot take the same step again when it returns.
        phases = json.loads((self.root / ".coord" / "master_schedule.json").read_text(encoding="utf-8"))["phases"]
        self.assertEqual(1, len(phases))
        self.assertEqual(("U9", "READY", "claude"), (phases[0]["phase_id"], phases[0]["state"], phases[0]["owner_tool"]))
        self.assertNotIn("waiting_on", phases[0])
        self.assertEqual("codex", phases[0]["rerouted_from"]["owner_tool"])
        again = stall.scan(self.root, "claude", now=NOW + stall.MAX_WAIT_S + 2, desk=desk)
        self.assertEqual(([], []), (again["stalled"], again["adopted"]))

    def test_an_old_wait_is_a_failure_at_first_sight_and_a_new_wait_after_adoption_is_rerouted_again(self):
        blocked = {"phase_id": "U7", "state": "BLOCKED", "owner_tool": "codex", "depends_on": [],
                   "waiting_on": "codex-impl"}
        path = _schedule(self.root, [blocked])
        old = NOW - stall.MAX_WAIT_S - 60
        os.utime(path, (old, old))  # the schedule has not changed for 31 minutes
        desk = _desk(codex="LIMITED", claude="ACTIVE")
        first = stall.scan(self.root, "claude", now=NOW, desk=desk)
        self.assertEqual(["phase:U7"], [p["source"] for p in first["adopted"]])
        declared = {**blocked, "phase_id": "U6", "waiting_since": NOW - stall.MAX_WAIT_S - 5}
        _schedule(self.root, [declared])  # written now, but the phase declares when its wait began
        self.assertEqual(["phase:U6"], [p["source"] for p in stall.scan(self.root, "claude", now=NOW,
                                                                         desk=desk)["adopted"]])
        later = NOW + 3600
        path = _schedule(self.root, [blocked])  # U7 waits again, an hour after it was rerouted
        os.utime(path, (later, later))
        self.assertEqual([], stall.scan(self.root, "claude", now=later + 60, desk=desk)["adopted"])
        again = stall.scan(self.root, "claude", now=later + stall.MAX_WAIT_S + 1, desk=desk)
        self.assertEqual(["phase:U7"], [p["source"] for p in again["adopted"]])

    def test_a_status_letter_and_a_human_only_phase_are_never_rerouted(self):
        _schedule(self.root, [
            {"phase_id": "DEL-1", "state": "HUMAN", "owner_tool": "all", "depends_on": [],
             "human": "merge #3, then delete the old release branch"},
            {"phase_id": "REL-1", "state": "HUMAN", "owner_tool": "all", "depends_on": [], "human": "배포 승인"},
        ])
        _queue(self.root, "codex", "relay_s", "antigravity", "status note: U1 done", stall.MAX_WAIT_S + 60)
        desk = _desk(codex="LIMITED", claude="ACTIVE", antigravity="ACTIVE")
        stall.scan(self.root, "claude", now=NOW, desk=desk)
        later = stall.scan(self.root, "claude", now=NOW + stall.MAX_WAIT_S + 1, desk=desk)
        self.assertEqual(([], [], []), (later["stalled"], later["blocked"], later["adopted"]))

    def test_a_stale_vote_or_a_vote_for_another_route_does_not_count(self):
        _schedule(self.root, [])
        _queue(self.root, "codex", "relay_t", "claude", "VERDICT_REQUESTED=YES", stall.MAX_WAIT_S + 1)
        desk = _desk(codex="LIMITED", claude="ACTIVE", antigravity="ACTIVE")
        stall.scan(self.root, "claude", now=NOW, desk=desk)
        late = stall.scan(self.root, "antigravity", now=NOW + stall.MAX_WAIT_S + 5, desk=desk)
        self.assertEqual([], late["adopted"])  # Claude's vote expired before Antigravity's arrived
        self.assertEqual(["antigravity"], late["stalled"][0]["voters"])
        _schedule(self.root, [{"phase_id": "U8", "state": "BLOCKED", "owner_tool": "antigravity", "depends_on": [],
                               "waiting_on": "antigravity-impl"}])
        stall.scan(self.root, "codex", now=NOW, desk=desk)  # first sight of U8
        t = NOW + stall.MAX_WAIT_S + 10
        first = stall.scan(self.root, "codex", now=t, desk=_desk(codex="ACTIVE", antigravity="ACTIVE"))
        self.assertEqual("codex", [e for e in first["stalled"] if e["item"] == "phase:U8"][0]["owner"])
        everyone = _desk(codex="ACTIVE", claude="ACTIVE", antigravity="ACTIVE")
        moved = stall.scan(self.root, "claude", now=t + 1, desk=everyone)  # owner is now Claude: a new ballot
        entry = [e for e in moved["stalled"] if e["item"] == "phase:U8"][0]
        self.assertEqual(("claude", ["claude"]), (entry["owner"], entry["voters"]))
        self.assertNotIn("phase:U8", [p["source"] for p in moved["adopted"]])

    def test_a_verdict_never_goes_to_its_author_and_no_route_is_a_block(self):
        _schedule(self.root, [])
        _queue(self.root, "codex", "relay_b", "antigravity", "VERDICT_REQUESTED=YES", stall.MAX_WAIT_S + 1)
        result = stall.scan(self.root, "claude", now=NOW, desk=_desk(codex="LIMITED", claude="ACTIVE",
                                                                      antigravity="ACTIVE"))
        self.assertEqual([], result["stalled"])
        self.assertEqual("relay_b", result["blocked"][0]["item"].split(":")[-1])

    def test_a_human_merge_phase_stalls_from_first_sight_and_routes_to_the_merger(self):
        _schedule(self.root, [{"phase_id": "MERGE-1", "state": "HUMAN", "owner_tool": "all", "depends_on": [],
                               "human": "merge #9 after PASS", "pr": "#9"}])
        desk = _desk(codex="LIMITED", claude="ACTIVE")
        self.assertEqual([], stall.scan(self.root, "claude", now=NOW, desk=desk)["stalled"])
        later = stall.scan(self.root, "claude", now=NOW + stall.MAX_WAIT_S + 1, desk=desk)
        self.assertEqual([], later["stalled"])  # Antigravity is not ACTIVE and Codex is away: no merger
        self.assertEqual("merge", later["blocked"][0]["kind"])
        desk = _desk(codex="LIMITED", claude="ACTIVE", antigravity="ACTIVE")
        routed = stall.scan(self.root, "claude", now=NOW + stall.MAX_WAIT_S + 2, desk=desk)
        entry = routed["stalled"][0]
        self.assertEqual("antigravity", entry["owner"])
        self.assertIn("coord merge --pr 9", entry["action"])
        self.assertIn("--verdict", entry["action"])

    def test_a_corrupt_schedule_is_reported_and_never_rewritten(self):
        path = self.root / ".coord" / "master_schedule.json"
        path.write_text("{not json", encoding="utf-8")
        _queue(self.root, "codex", "relay_c", "claude", "note", stall.MAX_WAIT_S + 1)
        result = stall.scan(self.root, "claude", now=NOW, desk=_desk(codex="LIMITED", claude="ACTIVE"))
        self.assertIsNotNone(result["error"])
        self.assertEqual("{not json", path.read_text(encoding="utf-8"))

    def test_parallel_scans_adopt_one_phase(self):
        _schedule(self.root, [])
        _queue(self.root, "codex", "relay_p", "claude", "VERDICT_REQUESTED=YES", stall.MAX_WAIT_S + 1)
        ctx = multiprocessing.get_context("spawn")
        barrier = ctx.Barrier(8)
        procs = [ctx.Process(target=_scan_worker, args=(str(self.root), ("claude", "antigravity")[i % 2], barrier))
                 for i in range(8)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(60)
            self.assertEqual(0, p.exitcode)
        self.assertEqual(1, len(_stall_phases(self.root)))

    def test_hook_lines_tell_the_owner_to_act_only_after_agreement_and_once(self):
        _schedule(self.root, [])
        _queue(self.root, "codex", "relay_h", "claude", "VERDICT_REQUESTED=YES", stall.MAX_WAIT_S + 1)
        desk = _desk(codex="LIMITED", claude="ACTIVE", antigravity="ACTIVE")
        with mock.patch("v7_harness.coord.presence.read_all", return_value=desk):
            text = stall.hook_lines(self.root, "antigravity", now=NOW)
            self.assertIn("WAIT IS FAILURE", text)
            self.assertIn("proposed reroute → antigravity", text)
            self.assertNotIn("you take it now", text)  # Claude has not agreed yet
            self.assertEqual("", stall.hook_lines(self.root, "antigravity", now=NOW))
            adopted = stall.hook_lines(self.root, "claude", now=NOW + 1)
            self.assertIn("ADOPTED (U166)", adopted)
            self.assertNotIn("you take it now", adopted)  # Claude is not the owner
            told = stall.hook_lines(self.root, "antigravity", now=NOW + 2)
            self.assertIn("REROUTED (U166)", told)
            self.assertIn("you take it now", told)
            self.assertEqual("", stall.hook_lines(self.root, "antigravity", now=NOW + 3))


class HookAndRuleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".coord").mkdir()
        (self.root / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_per_prompt_hook_of_every_tool_prints_the_stall(self):
        from v7_harness.cli import main
        from v7_harness.coord.presence import mark

        _schedule(self.root, [])
        path = _queue(self.root, "codex", "relay_k", "claude", "VERDICT_REQUESTED=YES", 0)
        old = time.time() - stall.MAX_WAIT_S - 60
        os.utime(path, (old, old))
        mark(self.root, "codex", "LIMITED", ttl_s=3600, lease=True)
        for tool in ("claude", "antigravity", "codex"):
            mark(self.root, "antigravity", "ACTIVE", ttl_s=3600)
            mark(self.root, "claude", "ACTIVE", ttl_s=3600)
            argv = ["coord", "presence", "--tool", tool, "--from-hook", "--project", str(self.root), "--say",
                    "none", "--delta"]
            out = io.StringIO()
            payload = {"hook_event_name": "UserPromptSubmit", "prompt": "hello", "session_id": f"s-{tool}",
                       "cwd": str(self.root)}
            with redirect_stdout(out), mock.patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": "", "UAOS_WORKER": ""}), \
                    mock.patch("v7_harness.coord.hook_context.read_stdin", return_value=json.dumps(payload)):
                self.assertEqual(0, main(argv))
            self.assertIn("U166", out.getvalue(), tool)

    def test_cli_stall_exits_1_on_a_real_block(self):
        from v7_harness.cli import main

        _schedule(self.root, [])
        _queue(self.root, "codex", "relay_z", "antigravity", "VERDICT_REQUESTED=YES", 0)
        old = time.time() - stall.MAX_WAIT_S - 60
        os.utime(self.root / ".coord/mailbox/delivery/queued/codex/relay_z.json", (old, old))
        with redirect_stdout(io.StringIO()), mock.patch("v7_harness.coord.presence.read_all",
                                                        return_value=_desk(codex="LIMITED", claude="ACTIVE",
                                                                           antigravity="ACTIVE")):
            self.assertEqual(1, main(["coord", "stall", "--project", str(self.root), "--tool", "claude"]))

    def test_rules_and_all_three_adapters_carry_the_house_rule(self):
        block = (ROOT / "uaos_everywhere" / "uaos_global_rule_block.md").read_text(encoding="utf-8")
        for phrase in ("uaos coord merge", "1순위 Antigravity", "2순위 Codex", "WAIT IS FAILURE", "uaos coord stall"):
            self.assertIn(phrase, block)
        for tool in ("claude", "codex", "antigravity"):
            text = (ROOT / "uaos_everywhere" / "adapters" / f"{tool}.md").read_text(encoding="utf-8")
            self.assertIn("U166", text, tool)


if __name__ == "__main__":
    unittest.main()
