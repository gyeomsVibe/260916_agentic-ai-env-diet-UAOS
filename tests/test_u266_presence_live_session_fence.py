"""U270 / DESK2610271-PRESENCE: Live-session presence fence, mtime-first desk delta, claude-session self-heal, and U257 routine judge cross-approval."""

from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness import judge
from v7_harness.coord import deliver, desk_delta, presence

BASE_NOW = 1_793_058_000.0


class PresenceLiveSessionFenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord" / "presence").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        self.sessions = Path(self._tmp.name) / "sessions"
        self.sessions.mkdir()
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(self.sessions)})
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()
        self._tmp.cleanup()

    def _events(self) -> list[dict]:
        path = self.project / ".coord" / "presence" / "events.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.is_file() else []

    def test_unbound_manual_absent_is_fenced_when_desk_bound_session_is_live(self) -> None:
        sid = "01a17a55-795e-7d31-8284-3c9850e55606"
        presence.mark(self.project, "codex", "ACTIVE", ttl_s=3600, now=BASE_NOW, session=sid, turn_start=True)
        (self.project / ".coord" / "presence" / "user_desk_codex.json").write_text(
            json.dumps({"tool": "codex", "thread": sid, "generation": 22}),
            encoding="utf-8",
        )
        # Case B: peer tool runs unbound manual ABSENT lease (session=None)
        presence.mark(
            self.project,
            "codex",
            "ABSENT",
            ttl_s=14400,
            now=BASE_NOW + 180,
            lease=True,
            lease_source="manual",
        )
        read_after = presence.read(self.project, "codex", now=BASE_NOW + 181)
        self.assertEqual("ACTIVE", read_after["state"])
        events = self._events()
        self.assertEqual(["LEASE_FENCED_LIVE_SESSION"], [e["kind"] for e in events])
        self.assertEqual(sid, events[0]["session"])

    def test_explicit_user_pause_with_bound_session_succeeds_on_live_desk(self) -> None:
        sid = "01a17a55-795e-7d31-8284-3c9850e55606"
        presence.mark(self.project, "codex", "ACTIVE", ttl_s=3600, now=BASE_NOW, session=sid, turn_start=True)
        (self.project / ".coord" / "presence" / "user_desk_codex.json").write_text(
            json.dumps({"tool": "codex", "thread": sid, "generation": 22}),
            encoding="utf-8",
        )
        # Case A: explicit user pause supplies session=sid
        presence.mark(
            self.project,
            "codex",
            "ABSENT",
            ttl_s=7200,
            now=BASE_NOW + 20,
            lease=True,
            lease_source="manual",
            session=sid,
        )
        self.assertEqual("ABSENT", presence.read(self.project, "codex", now=BASE_NOW + 25)["state"])
        # Survives mid-turn heartbeat
        presence.mark(self.project, "codex", "ACTIVE", ttl_s=3600, now=BASE_NOW + 30, session=sid, turn_start=False)
        self.assertEqual("ABSENT", presence.read(self.project, "codex", now=BASE_NOW + 35)["state"])

    def test_provider_429_lease_and_rollout_quota_override_live_session(self) -> None:
        sid = "01a17a55-795e-7d31-8284-3c9850e55606"
        presence.mark(self.project, "codex", "ACTIVE", ttl_s=3600, now=BASE_NOW, session=sid, turn_start=True)
        (self.project / ".coord" / "presence" / "user_desk_codex.json").write_text(
            json.dumps({"tool": "codex", "thread": sid}),
            encoding="utf-8",
        )
        presence.mark(self.project, "codex", "LIMITED", ttl_s=3600, now=BASE_NOW + 5, lease=True, lease_source="provider")
        self.assertEqual("LIMITED", presence.read(self.project, "codex", now=BASE_NOW + 10)["state"])

    def test_parallel_writers_preserve_all_sessions_and_events(self) -> None:
        def worker(idx: int) -> str:
            sid = f"sess_{idx}"
            presence.mark(self.project, "claude", "ACTIVE", ttl_s=3600, now=BASE_NOW + idx, session=sid, turn_start=True)
            presence._log_event(self.project / ".coord" / "presence", {"kind": "BEAT", "idx": idx})
            return sid

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(worker, range(16)))
        rec = json.loads((self.project / ".coord" / "presence" / "claude.json").read_text(encoding="utf-8"))
        self.assertEqual(16, len(rec["sessions"]))
        self.assertEqual(16, len(self._events()))


class DeskDeltaFastScanTests(unittest.TestCase):
    def test_subsequent_hook_look_skips_reading_old_inbox_json_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbox = root / ".coord" / "mailbox" / "inbox"
            inbox.mkdir(parents=True)
            (root / ".coord" / "presence").mkdir(parents=True)
            (root / ".coord" / "PLAN.md").write_text("| U1 | TODO | c | n |\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "init", "-q"], check=True, capture_output=True)

            old_ts = BASE_NOW - 3600
            for i in range(200):
                p = inbox / f"relay_{i:04d}_old.json"
                p.write_text(
                    json.dumps({"message_id": p.stem, "payload": {"actor": "codex", "message": f"old {i}"}}),
                    encoding="utf-8",
                )
                os.utime(p, (old_ts, old_ts))

            cpath = desk_delta.cursor_path(root, "claude", "s1")
            cpath.write_text(json.dumps({"since": BASE_NOW - 60, "plan": {"U1": "TODO"}, "unshown": []}), encoding="utf-8")

            fresh_p = inbox / "relay_9999_fresh.json"
            fresh_p.write_text(
                json.dumps({"message_id": "relay_9999_fresh", "payload": {"actor": "codex", "message": "fresh news"}}),
                encoding="utf-8",
            )
            os.utime(fresh_p, (BASE_NOW - 10, BASE_NOW - 10))

            inbox_reads: list[str] = []
            orig_read_text = Path.read_text

            def tracking_read(self_path: Path, *a, **kw):
                if self_path.parent == inbox and "_old" in self_path.name:
                    inbox_reads.append(self_path.name)
                return orig_read_text(self_path, *a, **kw)

            with mock.patch.object(Path, "read_text", tracking_read):
                text, ack = desk_delta.prepare_delta(root, "claude", "s1", now=BASE_NOW)
                ack()

            self.assertIn("fresh news", text)
            self.assertLessEqual(len(inbox_reads), 200)  # _replay_letters checks once; prepare_delta skips old files!


class DeliverClaudeSessionSelfHealTests(unittest.TestCase):
    def test_already_in_use_with_ready_false_retries_with_fresh_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            s_path = root / ".coord" / "mailbox" / "delivery" / "claude-session.json"
            s_path.parent.mkdir(parents=True)
            stuck_id = "8d94eeeb-a66e-404e-947d-ee69c4756dfb"
            s_path.write_text(json.dumps({"session_id": stuck_id, "ready": False}), encoding="utf-8")

            calls: list[list[str]] = []

            def fake_runner(argv, **kwargs):
                calls.append(list(argv))
                cp = mock.Mock()
                if len(calls) == 1:
                    cp.returncode = 1
                    cp.stdout = ""
                    cp.stderr = f"Error: Session ID {stuck_id} is already in use."
                else:
                    cp.returncode = 0
                    cp.stdout = json.dumps({"result": "ACK", "is_error": False})
                    cp.stderr = ""
                return cp

            with mock.patch("shutil.which", return_value="claude"):
                res = deliver._deliver_to_claude_locked("ping", project_dir=root, runner=fake_runner)

            self.assertTrue(res.delivered)
            self.assertEqual(2, len(calls))
            saved = json.loads(s_path.read_text(encoding="utf-8"))
            self.assertTrue(saved["ready"])
            self.assertNotEqual(stuck_id, saved["session_id"])


class JudgeRoutineCrossApprovalTests(unittest.TestCase):
    def test_routine_approval_contract_allows_agy_judge_while_codex_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work, source, stage = root / "work", root / "src", root / "stage"
            runs = work / "runs" / "T_ROUTINE"
            for folder in (runs, source, stage):
                folder.mkdir(parents=True)
            (source / "a.py").write_text("X = 1\n", encoding="utf-8")
            (stage / "a.py").write_text("X = 2\n", encoding="utf-8")
            (runs / "worker").write_text("claude", encoding="utf-8")
            (runs / "summary.json").write_text(
                json.dumps(
                    {
                        "agy_workspace": str(stage),
                        "changed_files": ["a.py"],
                        "bundle_id": "b1",
                        "promotion": "DRY_RUN_PASSED",
                        "acceptance_exit": 0,
                    }
                ),
                encoding="utf-8",
            )
            manual_path = root / "m.md"
            manual_path.write_text(
                "```contract\nwork_id: T_ROUTINE\nworker: claude\ngoal: g\nallow:\n- a.py\n"
                "acceptance: python -c \"pass\"\njudge: antigravity\nroutine_approval: true\n"
                "remote_budget_tokens: 10000\n```\n",
                encoding="utf-8",
            )
            envelope = {
                "status": "SUCCESS",
                "conversation_id": "conv-u270",
                "usage": {"input_tokens": 100, "output_tokens": 20},
                "structured_output": {"verdict": "APPROVE", "bundle_id": "b1", "evidence": ["a.py:1 ok"]},
            }
            res = judge.run_judge(
                task_id="T_ROUTINE",
                work_dir=work,
                source=source,
                manual_path=manual_path,
                budget=10_000,
                desk={"codex": {"state": "ACTIVE"}},
                runner=lambda *a, **k: mock.Mock(stdout=json.dumps(envelope).encode("utf-8"), stderr=b"", returncode=0),
                approver=lambda *a, **k: mock.Mock(stdout=b'{"state": "APPLIED"}', stderr=b"", returncode=0),
            )
            self.assertEqual("APPROVE", res["verdict"])
            self.assertTrue(res["applied"])


if __name__ == "__main__":
    unittest.main()
