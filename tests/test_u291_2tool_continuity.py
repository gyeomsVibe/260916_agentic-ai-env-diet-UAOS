"""U291: 3-Case 2-Tool Autonomous Judge, Merge & Live Runtime Activation Tests.

Verifies that when any 1 of the 3 AI tools (Antigravity, Claude Code, Codex) stops due to usage limits
(`LIMITED` / `ABSENT`), the remaining 2 tools (`ACTIVE`) can autonomously complete:
1. Non-author cross-judgement (`author != judge`) on contracts naming the away tool (`acting_for`):
   - Case 1 (`Antigravity + Claude`, `Codex LIMITED`): Claude authors -> Antigravity judges; Antigravity authors -> Claude judges.
   - Case 2 (`Claude + Codex`, `Antigravity LIMITED`): Claude authors -> Codex judges; Codex authors -> Claude judges.
   - Case 3 (`Antigravity + Codex`, `Claude LIMITED`): Antigravity authors -> Codex judges; Codex authors -> Antigravity judges.
   - Codex-exclusive keypoint contracts ALWAYS fail closed (`KEYPOINT_NEEDS_CODEX`) on non-Codex judges even under 2-tool quorum.
   - While Codex is `ACTIVE`, Claude is refused (`CODEX_JUDGES`) on non-routine contracts unless Codex authored the bundle.
2. PR Merge (`merge_route.merge`) + Live Runtime Activation (`sync_runtime_after_merge`) into `~/.uaos/runtime`,
   enforcing `RUNTIME_REINSTALL_HOLD`, non-empty 40-hex `head`, `HEAD == origin/main == head`, and keypoint hold.
3. Automatic quota-limit replanning at turn end (`stop_gate.gate` -> `failover_closeout.replan_on_quota_limit`),
   failing closed on `UNKNOWN` tool presence and preserving Codex-exclusive keypoints.
4. `--wakes-session` watcher preempting a `wakes_session=False` lock while keeping a live `wakes_session=True` lock.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness import judge
from v7_harness.coord import failover_closeout, merge_route, stop_gate, watch

MANUAL_TEMPLATE = """```contract
work_id: T291
worker: {worker}
goal: verify 2-tool continuity
allow:
- {allow_file}
acceptance: python -c "pass"
judge: {named_judge}
remote_budget_tokens: 0
```
"""

HEAD = "c" * 40
VERDICT_ID = "relay_" + "9" * 32


class _Done:
    def __init__(self, stdout: bytes = b"", returncode: int = 0):
        self.stdout = stdout
        self.stderr = b""
        self.returncode = returncode


class TestU291TwoToolContinuity(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.work = self.root / "work"
        self.source = self.root / "src"
        self.stage = self.root / "stage"
        self.runs = self.work / "runs" / "T291"
        for folder in (self.runs, self.source, self.stage):
            folder.mkdir(parents=True, exist_ok=True)
        (self.source / "a.py").write_text("X = 1\n", encoding="utf-8")
        (self.stage / "a.py").write_text("X = 2\n", encoding="utf-8")
        (self.runs / "summary.json").write_text(
            json.dumps(
                {
                    "agy_workspace": str(self.stage),
                    "changed_files": ["a.py"],
                    "bundle_id": "b291",
                    "promotion": "DRY_RUN_PASSED",
                    "acceptance_exit": 0,
                }
            ),
            encoding="utf-8",
        )
        self.manual = self.root / "manual.md"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _make_runner(self, judge_key: str, bundle_id: str = "b291"):
        def _run(argv, **kwargs):
            if judge_key == "codex":
                (self.runs / "judge_codex_last.json").write_text(
                    json.dumps({"verdict": "APPROVE", "bundle_id": bundle_id, "evidence": ["a.py:1 ok"]}),
                    encoding="utf-8",
                )
                events = (
                    json.dumps({"type": "thread.started", "thread_id": "th-codex"})
                    + "\n"
                    + json.dumps({"type": "turn.completed", "usage": {"input_tokens": 80, "output_tokens": 20}})
                    + "\n"
                )
                return _Done(events.encode("utf-8"), 0)
            if judge_key == "claude":
                envelope = {
                    "session_id": "sess-claude",
                    "usage": {"input_tokens": 90, "output_tokens": 25},
                    "structured_output": {"verdict": "APPROVE", "bundle_id": bundle_id, "evidence": ["a.py:1 ok"]},
                }
                return _Done(json.dumps(envelope).encode("utf-8"), 0)
            envelope = {
                "status": "SUCCESS",
                "conversation_id": "conv-agy",
                "usage": {"input_tokens": 100, "output_tokens": 20},
                "structured_output": {"verdict": "APPROVE", "bundle_id": bundle_id, "evidence": ["a.py:1 ok"]},
            }
            return _Done(json.dumps(envelope).encode("utf-8"), 0)

        return _run

    def _run_judge_case(
        self, *, author: str, named_judge: str, active_judge: str, desk: dict, allow_file: str = "a.py"
    ):
        for f in self.runs.glob("judge_*.json"):
            f.unlink(missing_ok=True)
        (self.runs / "worker").write_text(author, encoding="utf-8")
        self.manual.write_text(
            MANUAL_TEMPLATE.format(worker="apply", named_judge=named_judge, allow_file=allow_file),
            encoding="utf-8",
        )
        return judge.run_judge(
            task_id="T291",
            work_dir=self.work,
            source=self.source,
            manual_path=self.manual,
            judge=active_judge,
            budget=10_000,
            runner=self._make_runner(active_judge),
            approver=lambda argv, **kw: _Done(b'{"state": "APPLIED"}', 0),
            desk=desk,
        )

    def test_case_1_antigravity_and_claude_remaining_when_codex_limited(self):
        desk = {"codex": {"state": "LIMITED"}, "claude": {"state": "ACTIVE"}, "antigravity": {"state": "ACTIVE"}}
        rec_a = self._run_judge_case(author="claude", named_judge="codex", active_judge="agy", desk=desk)
        self.assertEqual("APPROVE", rec_a["verdict"])
        self.assertTrue(rec_a["applied"])
        self.assertEqual("codex", rec_a["acting_for"])

        rec_b = self._run_judge_case(author="agy", named_judge="codex", active_judge="claude", desk=desk)
        self.assertEqual("APPROVE", rec_b["verdict"])
        self.assertTrue(rec_b["applied"])
        self.assertEqual("codex", rec_b["acting_for"])

        with self.assertRaises(judge.JudgeRefused) as ctx:
            self._run_judge_case(author="claude", named_judge="codex", active_judge="claude", desk=desk)
        self.assertIn("JUDGE_IS_AUTHOR", str(ctx.exception))

    def test_codex_exclusive_keypoint_refuses_non_codex_judge_even_under_quorum(self):
        desk = {"codex": {"state": "LIMITED"}, "claude": {"state": "ACTIVE"}, "antigravity": {"state": "ACTIVE"}}
        for non_codex in ("agy", "claude"):
            with self.assertRaises(judge.JudgeRefused) as ctx:
                self._run_judge_case(
                    author="ollama",
                    named_judge="codex",
                    active_judge=non_codex,
                    desk=desk,
                    allow_file="v7_harness/coord/stop_gate.py",
                )
            self.assertIn("KEYPOINT_NEEDS_CODEX", str(ctx.exception))

    def test_case_2_claude_and_codex_remaining_when_antigravity_limited(self):
        desk = {"codex": {"state": "ACTIVE"}, "claude": {"state": "ACTIVE"}, "antigravity": {"state": "LIMITED"}}
        rec_a = self._run_judge_case(author="claude", named_judge="antigravity", active_judge="codex", desk=desk)
        self.assertEqual("APPROVE", rec_a["verdict"])
        self.assertTrue(rec_a["applied"])
        self.assertEqual("antigravity", rec_a["acting_for"])

        rec_b = self._run_judge_case(author="codex", named_judge="antigravity", active_judge="claude", desk=desk)
        self.assertEqual("APPROVE", rec_b["verdict"])
        self.assertTrue(rec_b["applied"])
        self.assertEqual("antigravity", rec_b["acting_for"])

        # While Codex is ACTIVE, Claude cannot judge a non-Codex-authored non-routine bundle
        with self.assertRaises(judge.JudgeRefused) as ctx:
            self._run_judge_case(author="agy", named_judge="antigravity", active_judge="claude", desk=desk)
        self.assertIn("CODEX_JUDGES", str(ctx.exception))

    def test_case_3_antigravity_and_codex_remaining_when_claude_limited(self):
        desk = {"codex": {"state": "ACTIVE"}, "claude": {"state": "LIMITED"}, "antigravity": {"state": "ACTIVE"}}
        rec_a = self._run_judge_case(author="agy", named_judge="claude", active_judge="codex", desk=desk)
        self.assertEqual("APPROVE", rec_a["verdict"])
        self.assertTrue(rec_a["applied"])
        self.assertEqual("claude", rec_a["acting_for"])

        rec_b = self._run_judge_case(author="codex", named_judge="claude", active_judge="agy", desk=desk)
        self.assertEqual("APPROVE", rec_b["verdict"])
        self.assertTrue(rec_b["applied"])
        self.assertEqual("claude", rec_b["acting_for"])

    def test_merge_route_and_runtime_sync_hold_and_strict_head_gates(self):
        repo_root = Path(__file__).resolve().parents[1]
        inbox = self.root / ".coord" / "mailbox" / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)

        def _write_verdict(actor: str) -> None:
            (inbox / f"{VERDICT_ID}.json").write_text(
                json.dumps({"actor": actor, "message": f"PASS on head {HEAD}"}),
                encoding="utf-8",
            )

        def _fake_runner(branch: str):
            views = [
                {"state": "OPEN", "mergeable": "MERGEABLE", "headRefOid": HEAD, "headRefName": branch, "url": "https://x/pull/9"},
                {"state": "MERGED", "mergeable": "MERGEABLE", "headRefOid": HEAD, "headRefName": branch, "url": "https://x/pull/9"},
            ]

            def _call(argv, **kwargs):
                if argv[:3] == ["gh", "pr", "view"]:
                    v = views.pop(0) if len(views) > 1 else views[0]
                    return subprocess.CompletedProcess(argv, 0, json.dumps(v).encode("utf-8"), b"")
                return subprocess.CompletedProcess(argv, 0, b"{}", b"")

            return _call

        _write_verdict("antigravity")
        r1 = merge_route.merge(
            self.root, 9, HEAD, VERDICT_ID,
            runner=_fake_runner("claude/u291-a"),
            desk={"codex": {"state": "LIMITED"}, "claude": {"state": "ACTIVE"}, "antigravity": {"state": "ACTIVE"}},
        )
        self.assertEqual(("MERGED", "antigravity"), (r1["state"], r1["merged_by"]))

        _write_verdict("claude")
        r2 = merge_route.merge(
            self.root, 9, HEAD, VERDICT_ID,
            runner=_fake_runner("codex/u291-b"),
            desk={"codex": {"state": "ACTIVE"}, "claude": {"state": "ACTIVE"}, "antigravity": {"state": "LIMITED"}},
        )
        self.assertEqual(("MERGED", "codex"), (r2["state"], r2["merged_by"]))

        # Empty head is strictly refused
        self.assertEqual("INVALID_OR_EMPTY_HEAD", merge_route.sync_runtime_after_merge(repo_root, head="")["reason"])

        # Runtime HOLD file is strictly respected
        hold_file = self.root / ".coord" / "presence" / "runtime_reinstall_hold.json"
        hold_file.parent.mkdir(parents=True, exist_ok=True)
        hold_file.write_text('{"hold": true}', encoding="utf-8")
        self.assertEqual("RUNTIME_REINSTALL_HOLD", merge_route.sync_runtime_after_merge(self.root, head=HEAD)["reason"])

    def test_stop_gate_and_failover_fail_closed_on_unknown_and_keypoints(self):
        with mock.patch("v7_harness.coord.failover_closeout.replan_on_quota_limit") as m_replan, \
             mock.patch("v7_harness.coord.presence.read", return_value={"state": "ACTIVE"}), \
             mock.patch("v7_harness.coord.stop_gate.letter_hold", return_value=None), \
             mock.patch("v7_harness.coord.next_card.next_step", return_value={"state": "DONE"}), \
             mock.patch("v7_harness.coord.failover_closeout.finalize_schedule_closeout") as m_close:
            stop_gate.gate(self.root, "claude", session="s-1", now=1000.0)
            m_replan.assert_called_once_with(self.root, now=1000.0)
            m_close.assert_called_once_with(self.root, tool="claude", now=1000.0)

        # UNKNOWN presence is never treated as away (never enters SOLE_SURVIVOR_AUTONOMOUS, and keypoint stays with codex)
        sched_p = self.root / ".coord" / "master_schedule.json"
        sched_p.parent.mkdir(parents=True, exist_ok=True)
        sched_p.write_text(
            json.dumps(
                {
                    "schedule_id": "S1",
                    "phases": [
                        {"phase_id": "P-KEYPOINT", "owner_tool": "codex", "state": "READY", "files": ["stop_gate.py"]},
                        {"phase_id": "P-AGY-UNKNOWN", "owner_tool": "antigravity", "state": "READY"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        res = failover_closeout.replan_on_quota_limit(
            self.root,
            desk={"codex": {"state": "LIMITED"}, "claude": {"state": "ACTIVE"}, "antigravity": {"state": "UNKNOWN"}},
            now=1000.0,
        )
        self.assertEqual("TWO_TOOL_CONTINUITY", res["mode"])
        self.assertEqual([], res["replanned"])

    def test_wakes_session_watcher_preempts_non_waking_but_keeps_live_waking_owner(self):
        lock_p = watch.lock_file(self.root, "antigravity")
        lock_p.parent.mkdir(parents=True, exist_ok=True)
        lock_p.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "process_created": watch.process_identity(os.getpid()),
                    "token": "old-orphan-token",
                    "wakes_session": False,
                }
            ),
            encoding="utf-8",
        )
        res_non_waking = watch.watch(
            self.root, ("antigravity",), timeout_s=0.0, interval_s=0.01, wakes_session=False, policy="structured"
        )
        self.assertEqual({"state": "ALREADY_WATCHING", "tool": "antigravity"}, res_non_waking)

        res_waking = watch.watch(
            self.root, ("antigravity",), timeout_s=0.0, interval_s=0.01, wakes_session=True, policy="structured"
        )
        self.assertIsNone(res_waking)

        # A live waking owner (wakes_session=True) is NOT preempted by another waking watcher
        lock_p.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "process_created": watch.process_identity(os.getpid()),
                    "token": "live-waking-token",
                    "wakes_session": True,
                }
            ),
            encoding="utf-8",
        )
        res_second_waking = watch.watch(
            self.root, ("antigravity",), timeout_s=0.0, interval_s=0.01, wakes_session=True, policy="structured"
        )
        self.assertEqual({"state": "ALREADY_WATCHING", "tool": "antigravity"}, res_second_waking)

    def test_cli_parses_claude_judge(self):
        from v7_harness.cli import build_parser

        args = build_parser().parse_args(
            ["pilot", "judge", "--task", "T1", "--work-dir", "w", "--manual", "m", "--judge", "claude"]
        )
        self.assertEqual("claude", args.judge)


if __name__ == "__main__":
    unittest.main()
