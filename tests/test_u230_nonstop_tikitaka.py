"""U230: MIA 11-stage overhaul for nonstop Tiki-Taka without user copy-paste (RC1-RC5)."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from v7_harness import card_pipeline as cp, cli, judge
from v7_harness.coord import presence, windows
from v7_harness.coord.deliver import deliver
from v7_harness.coord.watch import watch_file


class NonstopTikiTakaTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_rc1_judge_reads_shared_desk_from_linked_worktree(self):
        main_desk = self.root / "main"
        wt = self.root / "wt"
        (main_desk / ".git" / "worktrees" / "wt").mkdir(parents=True)
        (main_desk / ".coord").mkdir(parents=True)
        (main_desk / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        wt.mkdir(parents=True)
        (wt / ".git").write_text(f"gitdir: {(main_desk / '.git' / 'worktrees' / 'wt').as_posix()}\n", encoding="utf-8")
        presence.mark(main_desk, "codex", "LIMITED")

        work, stage = self.root / "work", self.root / "stage"
        runs = work / "runs" / "T1"
        for folder in (runs, stage):
            folder.mkdir(parents=True)
        (wt / "a.py").write_text("X = 1\n", encoding="utf-8")
        (stage / "a.py").write_text("X = 2\n", encoding="utf-8")
        (runs / "worker").write_text("claude", encoding="utf-8")
        (runs / "summary.json").write_text(
            json.dumps({"agy_workspace": str(stage), "changed_files": ["a.py"], "bundle_id": "b1",
                        "promotion": "DRY_RUN_PASSED", "acceptance_exit": 0}),
            encoding="utf-8",
        )
        manual = self.root / "m.md"
        manual.write_text(
            "```contract\nwork_id: T1\nworker: apply\ngoal: g\nallow:\n- a.py\n"
            'acceptance: python -c "pass"\njudge: antigravity\nremote_budget_tokens: 0\n```\n',
            encoding="utf-8",
        )
        envelope = {"status": "SUCCESS", "conversation_id": "conv-u230",
                    "usage": {"input_tokens": 100, "output_tokens": 20},
                    "structured_output": {"verdict": "APPROVE", "bundle_id": "b1", "evidence": ["a.py:1 ok"]}}
        rec = judge.run_judge(
            task_id="T1", work_dir=work, source=wt, manual_path=manual, budget=10_000, apply=False,
            runner=lambda argv, **kw: SimpleNamespace(stdout=json.dumps(envelope).encode("utf-8"), stderr=b"", returncode=0),
        )
        self.assertEqual("APPROVE", rec["verdict"])
        self.assertIn("LIMITED", rec["codex_state"])

    def test_rc2_codex_quota_block_survives_expired_heartbeat_ttl(self):
        desk = self.root / "desk"
        sessions = self.root / "sessions" / "2026" / "10" / "25"
        sessions.mkdir(parents=True)
        now = 1_792_860_000.0
        presence.mark(desk, "codex", "ACTIVE", ttl_s=60, now=now)
        rollout = sessions / "rollout-1-01a16e0b-721a-76a2-855f-e222db218289.jsonl"
        rollout.write_text(
            json.dumps({
                "payload": {
                    "type": "task_complete",
                    "completed_at": now + 10,
                    "error": {"codex_error_info": "usage_limit_exceeded", "message": "try again at Oct 29th, 2026 2:13 PM"},
                }
            }) + "\n",
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(self.root / "sessions")}):
            info = presence.read(desk, "codex", now=now + 7200)
        self.assertEqual("LIMITED", info["state"])

    def test_rc3_window_in_desk_commands_and_agy_json_fallback(self):
        self.assertIn("window", cli._DESK_COMMANDS)
        cid, tokens = windows._open_antigravity(
            self.root, "prompt",
            runner=lambda *a, **kw: SimpleNamespace(
                returncode=0,
                stdout='Warning: noisy prefix\n{"conversation_id": "c-42", "usage": {"input_tokens": 123}}\n',
            ),
        )
        self.assertEqual(("c-42", 123), (cid, tokens))

    def test_rc4_deliver_wants_turn_wakes_claude_and_rotates_stale_session(self):
        proj = self.root / "proj"
        (proj / ".coord").mkdir(parents=True)
        presence.mark(proj, "claude", "ACTIVE")
        beat = watch_file(proj, "claude")
        beat.parent.mkdir(parents=True, exist_ok=True)
        beat.write_text(json.dumps({"tool": "claude", "token": "t", "pid": 1, "expires_at": time.time() + 300,
                                    "wakes_session": False}), encoding="utf-8")
        session_file = proj / ".coord" / "mailbox" / "delivery" / "claude-session.json"
        session_file.parent.mkdir(parents=True, exist_ok=True)
        session_file.write_text(json.dumps({"session_id": "stale-uuid", "ready": True}), encoding="utf-8")

        calls = []

        def timeout_then_ok(argv, **kwargs):
            calls.append(list(argv))
            if len(calls) == 1:
                raise subprocess.TimeoutExpired(argv, 120)
            return SimpleNamespace(returncode=0, stdout=json.dumps({"result": "ACK"}), stderr="")

        with mock.patch("v7_harness.coord.deliver.shutil.which", side_effect=lambda n: n):
            r1 = deliver(proj, message="Audit complete", actor="antigravity", target="claude",
                         wake_class="ACTIONABLE", delta="audit pass", runner=timeout_then_ok)
            self.assertTrue(r1.reason.startswith("DELIVERY_FAILED"))
            self.assertFalse(session_file.exists())
            r2 = deliver(proj, message="Audit complete retry", actor="antigravity", target="claude",
                         wake_class="ACTIONABLE", delta="audit pass 2", runner=timeout_then_ok)
            self.assertEqual("DISPATCHED", r2.reason)
            self.assertIn("--session-id", calls[1])

    def test_rc5_card_audit_accepts_task_dir_judge_and_mailbox_verdict(self):
        desk = self.root / "desk"
        ledger = desk / ".coord" / "usage" / "runs.jsonl"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(json.dumps({"work_id": "U230-L1", "worker": "ollama", "input_tokens": 100}) + "\n",
                          encoding="utf-8")
        inbox = desk / ".coord" / "mailbox" / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        (inbox / "relay_test123.json").write_text(
            json.dumps({"payload": {"actor": "antigravity", "card": "U230", "verdict": "PASS"}}),
            encoding="utf-8",
        )
        out = cp.audit(desk, "U230")
        self.assertTrue(out["ok"], out)
        self.assertTrue(any("agy letter relay_test123 PASS" in x for x in out["agy"]))

    def test_rc6_rc7_queued_interactive_clears_pending_and_native_accepts_unbound_card(self):
        from v7_harness.coord.watch import _native_eligible
        from v7_harness.coord import windows
        proj = self.root / "proj_rc6"
        (proj / ".coord" / "presence").mkdir(parents=True)
        presence.mark(proj, "claude", "ACTIVE")
        (proj / ".coord" / "presence" / "user_desk_claude.json").write_text(
            json.dumps({"thread": "desk-s1", "at": time.time() - 10}), encoding="utf-8"
        )
        windows.record_window(proj, "U231", "antigravity", "agy-conv-1")
        beat = watch_file(proj, "claude")
        beat.write_text(json.dumps({"tool": "claude", "token": "t", "pid": 1, "expires_at": time.time() + 300,
                                    "wakes_session": True}), encoding="utf-8")
        res = deliver(proj, message="ACTIONABLE_DELTA: merged", actor="antigravity", target="claude",
                      card="U231", wake_class="ACTIONABLE", verdict="PASS", delta="merged")
        self.assertEqual("QUEUED_INTERACTIVE", res.reason)
        pending = proj / ".coord" / "mailbox" / "delivery" / "pending" / f"{res.message_id}.json"
        self.assertFalse(pending.exists())
        letter = json.loads((proj / ".coord" / "mailbox" / "inbox" / f"{res.message_id}.json").read_text(encoding="utf-8"))
        self.assertTrue(_native_eligible(proj, res.message_id, letter["payload"], "desk-s1", time.time()))


if __name__ == "__main__":
    unittest.main()
