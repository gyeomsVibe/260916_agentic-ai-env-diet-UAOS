"""U134-A (rev3 amendment): a real turn start clears a stale MANUAL LIMITED/ABSENT lease of the same tool, never a provider one.

Receipt (2026-10-03, P1): a hand-written `coord presence --tool codex --state LIMITED --lease` from 2026-09-30 stayed
live for 3 days; presence dropped every Codex SessionStart/UserPromptSubmit heartbeat (U47-A1b), so the desk kept
saying codex=LIMITED while Codex answered in the app, and a Claude handoff never reached it.
A SessionStart or UserPromptSubmit heartbeat (`turn_start=True`) now replaces the lease and logs
LEASE_CLEARED_BY_TURN; a PostToolUse heartbeat is mid-turn and still cannot.
Codex REWORK (relay_a868ed76): a hook proves app activity, not recovered provider quota. A lease now records its source:
`provider` (judge.py from a 429 answer) is kept until it expires and logged once as LEASE_KEPT_PROVIDER; a lease with no
source (written before rev3) fails closed the same way; only `manual` (`coord presence --lease`) is cleared by a turn.
The Codex rollout refusal overlay (U57-A) still outranks the cleared lease. Fixed acceptance written by the judge.
"""

import ast
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import presence


class LeaseClearedByTurnTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        sessions = Path(self._tmp.name) / "codex-sessions"  # never the PC's real Codex logs
        sessions.mkdir()
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(sessions)})
        self._env.start()
        self.sessions = sessions
        presence.mark(self.project, "codex", "LIMITED", ttl_s=3 * 86400, lease=True, lease_source="manual")

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def _events(self):
        path = self.project / ".coord" / "presence" / "events.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.is_file() else []

    def test_a_turn_start_heartbeat_clears_a_stale_limited_lease(self):
        presence.mark(self.project, "codex", "ACTIVE", session="s1", turn_start=True)
        self.assertEqual("ACTIVE", presence.read(self.project, "codex")["state"])
        events = self._events()
        self.assertEqual(["LEASE_CLEARED_BY_TURN"], [e["kind"] for e in events])
        self.assertEqual(("codex", "LIMITED"), (events[0]["tool"], events[0]["cleared_state"]))

    def test_a_mid_turn_heartbeat_leaves_the_lease(self):
        presence.mark(self.project, "codex", "ACTIVE", session="s1")  # PostToolUse: turn_start defaults to False
        self.assertEqual("LIMITED", presence.read(self.project, "codex")["state"])
        self.assertEqual([], self._events())

    def test_a_turn_start_never_clears_another_tools_lease(self):
        presence.mark(self.project, "claude", "ACTIVE", session="s2", turn_start=True)
        self.assertEqual("LIMITED", presence.read(self.project, "codex")["state"])

    def test_an_absent_lease_is_cleared_too_and_a_limited_turn_clears_nothing(self):
        presence.mark(self.project, "claude", "ABSENT", ttl_s=3600, lease=True, lease_source="manual")
        presence.mark(self.project, "claude", "LIMITED", session="s3", turn_start=True)
        self.assertEqual("ABSENT", presence.read(self.project, "claude")["state"])  # only ACTIVE proves capacity
        presence.mark(self.project, "claude", "ACTIVE", session="s3", turn_start=True)
        self.assertEqual("ACTIVE", presence.read(self.project, "claude")["state"])

    def test_the_hook_payload_names_a_turn_start(self):
        for event, expected in (("SessionStart", True), ("UserPromptSubmit", True), ("PostToolUse", False),
                                ("Stop", False), (None, False)):
            payload = json.dumps({"session_id": "s", "hook_event_name": event} if event else {"session_id": "s"})
            self.assertEqual(expected, presence.hook_turn_start(payload), event)
        self.assertFalse(presence.hook_turn_start("not json"))
        self.assertFalse(presence.hook_turn_start(""))

    def test_the_cli_hook_clears_the_lease_on_session_start_only(self):
        from v7_harness import cli

        def run(event):
            stdin = io.StringIO(json.dumps({"session_id": "s9", "hook_event_name": event, "cwd": str(self.project)}))
            argv = ["coord", "presence", "--tool", "codex", "--state", "ACTIVE", "--from-hook", "--say", "none",
                    "--project", str(self.project)]
            if event == "PostToolUse":
                argv.append("--post-tool")
            with mock.patch("sys.stdin", stdin), mock.patch("sys.stdout", new_callable=io.StringIO), \
                    mock.patch.dict(os.environ, {"UAOS_WORKER": ""}):
                args = cli.build_parser().parse_args(argv)
                self.assertEqual(0, args.func(args))

        run("PostToolUse")
        self.assertEqual("LIMITED", presence.read(self.project, "codex")["state"])
        run("SessionStart")
        self.assertEqual("ACTIVE", presence.read(self.project, "codex")["state"])


    def test_a_live_provider_lease_survives_session_start(self):
        presence.mark(self.project, "claude", "LIMITED", ttl_s=3600, lease=True, lease_source="provider")
        presence.mark(self.project, "claude", "ACTIVE", session="p1", turn_start=True)
        presence.mark(self.project, "claude", "ACTIVE", session="p1", turn_start=True)
        self.assertEqual("LIMITED", presence.read(self.project, "claude")["state"])
        kinds = [e["kind"] for e in self._events() if e["tool"] == "claude"]
        self.assertEqual(["LEASE_KEPT_PROVIDER"], kinds)  # once per lease, not once per heartbeat

    def test_a_legacy_lease_without_source_fails_closed(self):
        presence.mark(self.project, "claude", "LIMITED", ttl_s=3600, lease=True)  # written before rev3
        presence.mark(self.project, "claude", "ACTIVE", session="p2", turn_start=True)
        self.assertEqual("LIMITED", presence.read(self.project, "claude")["state"])
        self.assertNotIn("LEASE_CLEARED_BY_TURN", [e["kind"] for e in self._events()])

    def test_the_lease_source_is_recorded_and_checked(self):
        presence.mark(self.project, "claude", "LIMITED", ttl_s=3600, lease=True, lease_source="provider")
        record = json.loads((self.project / ".coord" / "presence" / "claude.json").read_text(encoding="utf-8"))
        self.assertEqual("provider", record["lease_source"])
        with self.assertRaises(presence.PresenceRejected):
            presence.mark(self.project, "claude", "LIMITED", ttl_s=3600, lease=True, lease_source="hook")

    def test_a_refused_turn_after_a_manual_clear_still_reads_limited(self):
        start = time.time()
        presence.mark(self.project, "codex", "ACTIVE", session="r1", turn_start=True, now=start)
        self.assertEqual("ACTIVE", presence.read(self.project, "codex", now=start + 1)["state"])
        day = self.sessions / "2026" / "10" / "03"
        day.mkdir(parents=True, exist_ok=True)
        refusal = {"type": "event_msg", "payload": {"type": "task_complete", "completed_at": start + 2,
                   "error": {"codex_error_info": "usage_limit_exceeded", "message": "You've hit your usage limit."}}}
        (day / "rollout-2026-10-03T07-00-00-0199eeee-0000-7000-8000-000000000005.jsonl").write_text(
            json.dumps(refusal) + "\n", encoding="utf-8")
        self.assertEqual("LIMITED", presence.read(self.project, "codex", now=start + 3)["state"])

    def test_the_cli_manual_lease_is_marked_manual(self):
        from v7_harness import cli
        argv = ["coord", "presence", "--tool", "claude", "--state", "LIMITED", "--lease", "--ttl", "3600",
                "--project", str(self.project)]
        with mock.patch("sys.stdout", new_callable=io.StringIO):
            args = cli.build_parser().parse_args(argv)
            self.assertEqual(0, args.func(args))
        record = json.loads((self.project / ".coord" / "presence" / "claude.json").read_text(encoding="utf-8"))
        self.assertEqual("manual", record["lease_source"])

    def test_the_judge_writes_a_provider_lease(self):
        # judge.py records agy's 429 answer; every lease=True mark call there must name the provider source.
        tree = ast.parse((Path(__file__).resolve().parents[1] / "v7_harness" / "judge.py").read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "mark"
                 and any(k.arg == "lease" for k in n.keywords)]
        self.assertTrue(calls)
        for call in calls:
            source = [k.value for k in call.keywords if k.arg == "lease_source"]
            self.assertEqual(["provider"], [getattr(v, "value", None) for v in source])


if __name__ == "__main__":
    unittest.main()
