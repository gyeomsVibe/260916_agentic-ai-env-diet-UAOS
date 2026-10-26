"""U201: when a tool's turn ends while work waits or has stopped, the user sees why, in one Korean line.

Receipt (2026-10-16): Antigravity letters sat in the cap backlog from 00:00 to 00:40 and the Claude session showed
nothing, so 윤겸스 could not tell why everything had stopped. Stage 0: Claude Code and Codex Stop hooks show
`systemMessage` to the user (https://code.claude.com/docs/en/hooks, https://learn.chatgpt.com/docs/hooks.md);
Antigravity's Stop hook documents only `decision`/`reason` (https://antigravity.google/docs/hooks), so its result
is left as it is."""
import inspect
import json
import tempfile
import time
import unittest
from pathlib import Path

from v7_harness import cli
from v7_harness.coord import wait_reason

NOW = 1792080000.0  # 2026-10-16 01:00 KST


class WaitReason(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        (self.project / ".coord" / "presence").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def park(self, count: int) -> None:
        folder = self.project / ".coord" / "mailbox" / "delivery" / "agy_backlog"
        folder.mkdir(parents=True, exist_ok=True)
        for index in range(count):
            (folder / f"relay_{index:032x}.json").write_text("{}", encoding="utf-8")
        (folder / "relay_old.failed").write_text("{}", encoding="utf-8")
        (folder / "relay_0.lock").write_text("", encoding="utf-8")

    def presence(self, tool: str, state: str, expires_at: float) -> None:
        (self.project / ".coord" / "presence" / f"{tool}.json").write_text(json.dumps(
            {"tool": tool, "state": state, "observed_at": "2026-10-15T15:00:00+00:00", "expires_at": expires_at}),
            encoding="utf-8")

    def gate_log(self, tool: str, card: str, at: float) -> None:
        log = self.project / ".coord" / "log" / "stop_gate.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"kind": "BLOCKED", "tool": tool, "card": card, "blocks": 1, "at": at}) + "\n")

    def test_nothing_waits_nothing_is_said(self):
        self.assertEqual([], wait_reason.reasons(self.project, "claude", now=NOW))
        self.assertIsNone(wait_reason.stop_output(None, self.project, "claude", now=NOW))

    def test_parked_antigravity_letters_are_named_with_the_cap(self):
        self.park(2)
        lines = wait_reason.reasons(self.project, "claude", now=NOW)
        self.assertEqual(1, len(lines), lines)
        self.assertIn("Antigravity 답장 2건", lines[0])
        self.assertIn("한도", lines[0])

    def test_a_limited_tool_is_named_with_its_return_time(self):
        self.presence("codex", "LIMITED", NOW + 1800)  # 01:30 KST
        lines = wait_reason.reasons(self.project, "claude", now=NOW)
        self.assertEqual(1, len(lines), lines)
        self.assertIn("codex", lines[0])
        self.assertIn("01:30", lines[0])

    def test_own_presence_and_active_tools_are_not_reasons(self):
        self.presence("claude", "LIMITED", NOW + 1800)
        self.presence("antigravity", "ACTIVE", NOW + 1800)
        self.assertEqual([], wait_reason.reasons(self.project, "claude", now=NOW))

    def test_a_recent_gate_stop_is_named_and_an_old_one_is_not(self):
        self.gate_log("claude", "U300", NOW - 120)
        self.gate_log("claude", "U299", NOW - 7200)
        self.gate_log("codex", "U298", NOW - 60)
        lines = wait_reason.reasons(self.project, "claude", now=NOW)
        self.assertEqual(1, len(lines), lines)
        self.assertIn("U300", lines[0])

    def test_claude_and_codex_get_a_system_message_and_keep_the_decision(self):
        self.park(1)
        for tool in ("claude", "codex"):
            alone = wait_reason.stop_output(None, self.project, tool, now=NOW)
            self.assertTrue(alone["systemMessage"].startswith("⏸"), alone)
            self.assertNotIn("decision", alone)
            held = wait_reason.stop_output({"decision": "block", "reason": "NEXT U1"}, self.project, tool, now=NOW)
            self.assertEqual("block", held["decision"])
            self.assertEqual("NEXT U1", held["reason"])
            self.assertIn("Antigravity 답장 1건", held["systemMessage"])

    def test_antigravity_result_is_left_as_it_is(self):
        self.park(1)
        self.assertIsNone(wait_reason.stop_output(None, self.project, "antigravity", now=NOW))
        held = {"decision": "continue", "reason": "NEXT U1"}
        self.assertEqual(held, wait_reason.stop_output(dict(held), self.project, "antigravity", now=NOW))

    def test_the_stop_hook_uses_it(self):
        source = inspect.getsource(cli.cmd_coord_stop_gate)
        self.assertIn("stop_output(", source)
        # A cp949 Windows console cannot print "⏸"; the pilot raised UnicodeEncodeError, which the hook's fail-open
        # handler would swallow, so the hook prints ASCII-escaped JSON.
        self.assertNotIn("ensure_ascii=False", source)

    def test_default_now_is_the_clock(self):
        self.presence("codex", "LIMITED", time.time() + 600)
        self.assertEqual(1, len(wait_reason.reasons(self.project, "claude")))

    def test_u260_schedule_review_and_active_waits_and_status_report_visible(self):
        sched = {
            "schedule_id": "U260",
            "phases": [
                {"phase_id": "U259", "state": "REVIEW", "author_tool": "antigravity", "reviewer": "claude", "waiting_on": "quota-reset"},
                {"phase_id": "U260", "state": "ACTIVE", "owner_tool": "antigravity", "waiting_on": "implementation"},
            ],
        }
        (self.project / ".coord" / "master_schedule.json").write_text(json.dumps(sched), encoding="utf-8")
        lines = wait_reason.reasons(self.project, "claude", now=NOW)
        self.assertEqual(2, len(lines), lines)
        self.assertIn("U259 판정 대기 중(state=REVIEW, 작성=antigravity, 판정자=claude, 대기사유=quota-reset)", lines[0])
        self.assertNotIn("전체 테스트·검증 수행 중", lines[0])
        self.assertNotIn("즉시 병합·배포", lines[0])
        self.assertIn("U260 작업 대기 중(state=ACTIVE, 담당=antigravity, 대기사유=implementation)", lines[1])
        rep = wait_reason.write_wait_status_report(self.project, "claude", now=NOW)
        self.assertEqual("WAITING", rep["state"])
        self.assertFalse(rep["all_done"])
        self.assertTrue(Path(rep["report_path"]).is_file())

    def test_u260_missing_invalid_or_empty_schedule_never_claims_all_done(self):
        sched_file = self.project / ".coord" / "master_schedule.json"
        # 1) Missing master_schedule.json
        rep_missing = wait_reason.write_wait_status_report(self.project, "claude", now=NOW)
        self.assertEqual("UNKNOWN", rep_missing["state"])
        self.assertFalse(rep_missing["all_done"])
        self.assertFalse(rep_missing["ok"])
        # 2) Invalid JSON
        sched_file.write_text("{invalid json", encoding="utf-8")
        rep_invalid = wait_reason.write_wait_status_report(self.project, "claude", now=NOW)
        self.assertEqual("UNKNOWN", rep_invalid["state"])
        self.assertFalse(rep_invalid["all_done"])
        # 3) Empty phases
        sched_file.write_text(json.dumps({"schedule_id": "EMPTY", "phases": []}), encoding="utf-8")
        rep_empty = wait_reason.write_wait_status_report(self.project, "claude", now=NOW)
        self.assertEqual("UNKNOWN", rep_empty["state"])
        self.assertFalse(rep_empty["all_done"])
        # 4) Valid all-DONE schedule with no active waits -> ALL_DONE
        sched_file.write_text(
            json.dumps({"schedule_id": "DONE", "phases": [{"phase_id": "U259", "state": "DONE"}]}),
            encoding="utf-8",
        )
        rep_done = wait_reason.write_wait_status_report(self.project, "claude", now=NOW)
        self.assertEqual("ALL_DONE", rep_done["state"])
        self.assertTrue(rep_done["all_done"])

    def test_u258_claude_can_judge_agy_pr_and_same_head_peer_verdict_required(self):
        from v7_harness.coord import merge_route
        head = "c" * 40
        other_head = "d" * 40
        vid = "relay_" + "9" * 32
        inbox = self.project / ".coord" / "mailbox" / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        (inbox / f"{vid}.json").write_text(
            json.dumps({"actor": "claude", "message": f"PASS on head {head}"}),
            encoding="utf-8",
        )
        res = merge_route.require_same_head_peer_verdict(
            self.project, branch="agy/u260-wait", head=head, verdict_relay=vid
        )
        self.assertTrue(res["ok"])
        # Refused when author == judge
        with self.assertRaises(merge_route.MergeRefused):
            merge_route.require_same_head_peer_verdict(
                self.project, branch="claude/u260-wait", head=head, verdict_relay=vid
            )
        # Refused when head mismatches
        with self.assertRaises(merge_route.MergeRefused):
            merge_route.require_same_head_peer_verdict(
                self.project, branch="agy/u260-wait", head=other_head, verdict_relay=vid
            )
        # Refused when verdict is missing
        with self.assertRaises(merge_route.MergeRefused):
            merge_route.require_same_head_peer_verdict(
                self.project, branch="agy/u260-wait", head=head, verdict_relay="relay_" + "0" * 32
            )


if __name__ == "__main__":
    unittest.main()
