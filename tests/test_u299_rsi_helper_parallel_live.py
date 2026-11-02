from __future__ import annotations

import io
import json
import multiprocessing
import os
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stdout
from pathlib import Path

from v7_harness import cli
from v7_harness.coord import requests as req_mod
from v7_harness.coord.agy_moderator import AntigravityModerator
from v7_harness.coord.card_sessions import build_card_parallel_launch_spec
from v7_harness.coord.presence import mark
from v7_harness.coord.process_lanes import (
    CANONICAL_HELPER_PARALLEL_RSI_SESSION_ID,
    build_workspace_garbage_manifest,
    collect_pending_processes,
    derive_merged_cards_from_ledger,
    open_or_reuse_card_parallel_windows,
    reconcile_merged_card_windows_and_schedule,
    sync_and_record_helper_parallel_rsi_session,
    verify_helper_parallel_os_health,
)
from v7_harness.coord.stream import _exclusive


def _mp_watcher_worker(project_str: str, codex_dir_str: str, iterations: int) -> None:
    os.environ["UAOS_CODEX_SESSIONS"] = codex_dir_str
    proj = Path(project_str)
    for _ in range(iterations):
        sync_and_record_helper_parallel_rsi_session(proj, publish_mailbox_notices=False)


def _mp_moderator_writer_worker(project_str: str, codex_dir_str: str, iterations: int) -> None:
    os.environ["UAOS_CODEX_SESSIONS"] = codex_dir_str
    proj = Path(project_str)
    mod = AntigravityModerator(proj)
    lock_path = mod._schedule_lock()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    for seq in range(1, iterations + 1):
        with _exclusive(lock_path):
            sched = json.loads(mod.schedule_path.read_text(encoding="utf-8"))
            history = list(sched.get("moderator_writes") or [])
            history.append(seq)
            sched["moderator_writes"] = history
            sched["last_moderator_seq"] = seq
            tmp = mod.schedule_path.with_suffix(f".mod.{os.getpid()}.{seq}.tmp")
            tmp.write_text(json.dumps(sched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp, mod.schedule_path)


class TestU299RsiHelperParallelLive(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.codex_sessions_dir = Path(self._tmp.name) / "codex_sessions"
        self.codex_sessions_dir.mkdir(parents=True, exist_ok=True)
        self._codex_env_patcher = unittest.mock.patch.dict(
            "os.environ", {"UAOS_CODEX_SESSIONS": str(self.codex_sessions_dir)}
        )
        self._codex_env_patcher.start()
        self.project = Path(self._tmp.name) / "project"
        (self.project / ".coord").mkdir(parents=True, exist_ok=True)
        (self.project / ".coord" / "PLAN.md").write_text("# UAOS Test Plan\n", encoding="utf-8")
        mark(self.project, "claude", "ACTIVE", ttl_s=3600)
        mark(self.project, "antigravity", "ACTIVE", ttl_s=3600)
        mark(self.project, "codex", "LIMITED", ttl_s=3600, lease=True, lease_source="manual")

    def tearDown(self) -> None:
        self._codex_env_patcher.stop()
        self._tmp.cleanup()

    def test_launch_spec_embeds_3tool_helper_and_thinking_selection(self) -> None:
        spec = build_card_parallel_launch_spec(
            self.project,
            "U299",
            title="3대 도구 도우미·추론 모델 자동 오케스트레이션",
            tool="antigravity",
            role="impl",
            allowed_files=["v7_harness/coord/process_lanes.py", "v7_harness/cli.py"],
        )
        self.assertTrue(spec["ok"])
        sel = spec["helper_thinking_selection"]
        self.assertEqual(sel["tool"], "antigravity")
        self.assertEqual(sel["calculator_model"], "qwen2.5-coder:7b")
        self.assertEqual(sel["designated_helper_model"], "gemini-3.8-flash")
        self.assertIn(sel["helper_thinking_level"], ("Low", "Medium", "High"))
        self.assertEqual(sel["designated_reasoning_model"], "gemini-4-argon")
        self.assertEqual(sel["reasoning_thinking_level"], "High")

    def test_derive_merged_cards_from_ledger_and_preserve_open_gate_phases(self) -> None:
        open_or_reuse_card_parallel_windows(self.project, ["U279", "U287", "U296", "U299"])
        # Record merged verdicts in .coord/merges.jsonl and .coord/mailbox/ack/
        ack_dir = self.project / ".coord" / "mailbox" / "ack"
        ack_dir.mkdir(parents=True, exist_ok=True)
        (ack_dir / "relay_pass_u296.json").write_text(
            json.dumps({"message_id": "relay_pass_u296", "payload": {"card": "U296", "verdict": "PASS"}}),
            encoding="utf-8",
        )
        (ack_dir / "relay_pass_u279_old.json").write_text(
            json.dumps({"message_id": "relay_pass_u279_old", "payload": {"card": "U279", "verdict": "PASS"}}),
            encoding="utf-8",
        )
        (self.project / ".coord" / "merges.jsonl").write_text(
            json.dumps({"pr": 266, "state": "MERGED", "verdict": "relay_pass_u296"}) + "\n"
            + json.dumps({"pr": 240, "state": "MERGED", "verdict": "relay_pass_u279_old"}) + "\n",
            encoding="utf-8",
        )

        # In master_schedule.json, U287 is DONE, while U279 is READY (open non-merge gate)
        sched_path = self.project / ".coord" / "master_schedule.json"
        original_schedule_text = json.dumps(
            {
                "phases": [
                    {
                        "phase_id": "U279",
                        "state": "READY",
                        "owner_tool": "claude",
                        "title": "Lossless topic window transport design",
                    },
                    {
                        "phase_id": "U287",
                        "state": "DONE",
                        "owner_tool": "antigravity",
                        "title": "Parallel 3-tool orchestration",
                    },
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        sched_path.write_text(original_schedule_text, encoding="utf-8")

        req_mod.register(
            self.project,
            request_id="relay_merged_u296",
            requester="claude",
            target="antigravity",
            card="U296",
        )
        req_mod.register(
            self.project,
            request_id="relay_open_u279",
            requester="claude",
            target="antigravity",
            card="U279",
        )

        derived = derive_merged_cards_from_ledger(self.project)
        self.assertIn("U296", derived)
        self.assertIn("U287", derived)
        # U279 must NOT be treated as merged because its phase in master_schedule.json is READY
        self.assertNotIn("U279", derived)

        res = reconcile_merged_card_windows_and_schedule(self.project)
        self.assertTrue(res["ok"])
        self.assertTrue(res["schedule_read_only"])
        self.assertIn("U287", res["released_windows"])
        self.assertIn("U296", res["released_windows"])
        self.assertNotIn("U279", res["released_windows"])
        self.assertIn("relay_merged_u296", res["archived_merged_requests"])
        self.assertNotIn("relay_open_u279", res["archived_merged_requests"])

        # F1 invariant: master_schedule.json on disk is 100% untouched by watcher reconciliation
        self.assertEqual(sched_path.read_text(encoding="utf-8"), original_schedule_text)

        # Merged request archived in closed/, U279 request still open
        self.assertTrue((self.project / ".coord" / "requests" / "closed" / "relay_merged_u296.json").is_file())
        self.assertEqual(len(req_mod.open_for(self.project, "claude")), 1)

        # Pending processes must have sched_U279 (never blank sched_)
        grouped = collect_pending_processes(self.project)
        all_ids = [it.item_id for items in grouped.values() for it in items]
        self.assertIn("sched_U279", all_ids)
        self.assertNotIn("sched_", all_ids)

    def test_workspace_garbage_manifest_is_deletion_free(self) -> None:
        (self.project / ".work" / "pilot_old_1").mkdir(parents=True, exist_ok=True)
        (self.project / ".work" / "wt_old_card").mkdir(parents=True, exist_ok=True)
        (self.project / ".work" / "backup_20261102").mkdir(parents=True, exist_ok=True)
        (self.project / ".work" / "cards").mkdir(parents=True, exist_ok=True)
        (self.project / ".claude" / "worktrees" / "test-wt-1").mkdir(parents=True, exist_ok=True)

        manifest = build_workspace_garbage_manifest(self.project)
        self.assertEqual(manifest["schema"], "uaos-workspace-garbage-manifest-v1")
        self.assertEqual(manifest["deleted_count"], 0)
        self.assertEqual(manifest["summary"]["work_pilot_staging_candidates_count"], 1)
        self.assertEqual(manifest["summary"]["work_worktree_candidates_count"], 1)
        self.assertEqual(manifest["summary"]["work_backup_snapshots_count"], 1)
        self.assertEqual(manifest["summary"]["claude_worktrees_count"], 1)
        self.assertTrue((self.project / ".coord" / "rsi" / "workspace_garbage_manifest.json").is_file())
        self.assertTrue((self.project / ".work" / "pilot_old_1").is_dir())
        self.assertTrue((self.project / ".work" / "wt_old_card").is_dir())

    def test_verify_health_and_sync_helper_parallel_rsi_session_and_watch_failure_logging(self) -> None:
        (self.project / ".coord" / "master_schedule.json").write_text(
            json.dumps(
                {
                    "phases": [
                        {
                            "phase_id": "U299",
                            "state": "ACTIVE",
                            "owner_tool": "antigravity",
                            "reviewer": "claude",
                            "title": "3대 도구 도우미·추론 모델 자동 오케스트레이션 및 카드별 병렬 세션 가동 표준화",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (self.project / ".coord" / "sub_process_schedule.json").write_text(
            json.dumps(
                {
                    "card_sub_schedules": [
                        {
                            "phase_id": "U299",
                            "card_state": "ACTIVE",
                            "assigned_executor": "antigravity",
                            "assigned_verifier": "claude",
                            "sub_processes": [
                                {"sub_id": "U299:SP1_RESEARCH_DRAFT", "stage_name": "SP1_RESEARCH_DRAFT"},
                                {"sub_id": "U299:SP2_MIA_DESIGN_AUDIT", "stage_name": "SP2_MIA_DESIGN_AUDIT"},
                                {"sub_id": "U299:SP3_CODE_EXECUTION", "stage_name": "SP3_CODE_EXECUTION"},
                                {"sub_id": "U299:SP4_INDEPENDENT_VERIFY", "stage_name": "SP4_INDEPENDENT_VERIFY"},
                                {"sub_id": "U299:SP5_MERGE_AND_RUNTIME", "stage_name": "SP5_MERGE_AND_RUNTIME"},
                            ],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        health = verify_helper_parallel_os_health(self.project)
        self.assertTrue(health["ok"])
        self.assertTrue(health["three_tool_helper_selection_ok"])
        self.assertTrue(health["card_parallel_worktree_spec_ok"])
        self.assertTrue(health["schedule_blank_id_free"])

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main([
                "coord",
                "lanes",
                "--project",
                str(self.project),
                "--action",
                "record-rsi-session",
                "--session-id",
                CANONICAL_HELPER_PARALLEL_RSI_SESSION_ID,
                "--actor",
                "antigravity",
            ])
        self.assertEqual(rc, 0)
        out = json.loads(buf.getvalue())
        self.assertTrue(out["ok"])
        self.assertEqual(out["session_id"], CANONICAL_HELPER_PARALLEL_RSI_SESSION_ID)
        self.assertEqual(out["operational_status"], "LIVE_OPERATING")
        self.assertEqual(out["live_declaration_ko"], "실가동 됨")

        session_dir = self.project / ".coord" / "rsi" / "sessions" / CANONICAL_HELPER_PARALLEL_RSI_SESSION_ID
        self.assertTrue((session_dir / "SESSION.json").is_file())
        self.assertTrue((session_dir / "CONTINUATION.json").is_file())
        self.assertTrue((session_dir / "REPORT.md").is_file())
        self.assertTrue((session_dir / "HEALTH_TELEMETRY.json").is_file())

        # CLI `rsi watch` success records `u299_rsi_session.ok == True`
        (self.project / ".coord" / "usage").mkdir(parents=True, exist_ok=True)
        (self.project / ".coord" / "usage" / "user_error_reports.jsonl").write_text("", encoding="utf-8")
        watch_buf = io.StringIO()
        with redirect_stdout(watch_buf):
            w_rc = cli.main(["rsi", "watch", "--project", str(self.project)])
        self.assertEqual(w_rc, 0)
        watch_payload = json.loads(watch_buf.getvalue())
        self.assertIn(watch_payload["status"], ("ACK_ONLY", "ACTIONABLE_DELTA"))
        self.assertTrue(watch_payload["u299_rsi_session"]["ok"])

        # F2: When sync_and_record_helper_parallel_rsi_session raises an exception,
        # cmd_rsi_watch records u299_rsi_session.ok=False + coord log BLOCKED and preserves exit code 0
        with unittest.mock.patch(
            "v7_harness.coord.process_lanes.sync_and_record_helper_parallel_rsi_session",
            side_effect=RuntimeError("synthetic_u299_sync_failure"),
        ):
            fail_buf = io.StringIO()
            with redirect_stdout(fail_buf):
                f_rc = cli.main(["rsi", "watch", "--project", str(self.project)])
        self.assertEqual(f_rc, 0)
        fail_payload = json.loads(fail_buf.getvalue())
        self.assertFalse(fail_payload["u299_rsi_session"]["ok"])
        self.assertIn("synthetic_u299_sync_failure", fail_payload["u299_rsi_session"]["error"])
        from v7_harness.coord.stream import read_events

        events = read_events(self.project)
        blocked_u299 = [e for e in events if e.get("kind") == "BLOCKED" and e.get("step") == "U299"]
        self.assertGreaterEqual(len(blocked_u299), 1)

    def test_parallel_watcher_sync_and_moderator_schedule_write_no_lost_fields(self) -> None:
        """F5: Really-parallel multiprocessing test: watcher sync + moderator schedule write in separate OS processes."""
        sched_path = self.project / ".coord" / "master_schedule.json"
        sched_path.write_text(
            json.dumps(
                {
                    "custom_header_field": "PRESERVE_ME",
                    "moderator_writes": [],
                    "last_moderator_seq": 0,
                    "phases": [
                        {
                            "phase_id": "U279",
                            "state": "READY",
                            "owner_tool": "claude",
                            "title": "Lossless transport",
                        },
                        {
                            "phase_id": "U298",
                            "state": "DONE",
                            "owner_tool": "antigravity",
                            "title": "Watch target",
                        },
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        iterations = 6
        p_watcher = multiprocessing.Process(
            target=_mp_watcher_worker,
            args=(str(self.project), str(self.codex_sessions_dir), iterations),
        )
        p_moderator = multiprocessing.Process(
            target=_mp_moderator_writer_worker,
            args=(str(self.project), str(self.codex_sessions_dir), iterations),
        )
        p_watcher.start()
        p_moderator.start()
        p_watcher.join(timeout=60)
        p_moderator.join(timeout=60)

        self.assertEqual(p_watcher.exitcode, 0)
        self.assertEqual(p_moderator.exitcode, 0)

        final_sched = json.loads(sched_path.read_text(encoding="utf-8"))
        self.assertEqual(final_sched.get("custom_header_field"), "PRESERVE_ME")
        self.assertEqual(final_sched.get("last_moderator_seq"), iterations)
        self.assertEqual(final_sched.get("moderator_writes"), list(range(1, iterations + 1)))
        phases_by_id = {p["phase_id"]: p for p in final_sched["phases"]}
        self.assertEqual(phases_by_id["U279"]["state"], "READY")


if __name__ == "__main__":
    unittest.main()
