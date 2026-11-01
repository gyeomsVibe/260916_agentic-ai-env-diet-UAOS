from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

from v7_harness import cli
from v7_harness.coord import user_window as uw
from v7_harness.coord.card_sessions import (
    build_card_parallel_launch_spec,
    ensure_topmost_user_window,
    extract_cards_from_text,
    is_child_card_session,
    normalize_claude_session_id,
    orchestrate_card_parallel_batch,
    sync_claude_desktop_card_sessions,
)
from v7_harness.coord.presence import mark
from v7_harness.coord.process_lanes import open_or_reuse_card_parallel_windows
from v7_harness.coord.windows import _claude_session_id, open_window, session_busy, window_entry


class TestU293CardParallelSessions(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "project"
        (self.project / ".coord").mkdir(parents=True, exist_ok=True)
        (self.project / ".coord" / "PLAN.md").write_text("# UAOS Test Plan\n", encoding="utf-8")
        mark(self.project, "claude", "ACTIVE", ttl_s=3600)
        mark(self.project, "antigravity", "ACTIVE", ttl_s=3600)
        mark(self.project, "codex", "LIMITED", ttl_s=3600, lease=True, lease_source="manual")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_normalize_claude_session_id_and_open_window_accepts_local_prefix(self) -> None:
        raw_local = "local_b30fe6ed-a0e1-457c-ad56-715be55da702"
        bare, native = normalize_claude_session_id(raw_local)
        self.assertEqual(bare, "b30fe6ed-a0e1-457c-ad56-715be55da702")
        self.assertEqual(native, "local_b30fe6ed-a0e1-457c-ad56-715be55da702")
        self.assertEqual(_claude_session_id(raw_local), bare)
        self.assertEqual(_claude_session_id(bare.upper()), bare)

        with self.assertRaises(ValueError):
            normalize_claude_session_id("local_not-a-uuid")

        opened = open_window(
            self.project,
            "U291",
            "claude",
            "PR #256 비작성자 판정",
            "",
            session_id=raw_local,
        )
        self.assertEqual(opened["id"], bare)
        self.assertEqual(opened.get("native_id"), raw_local)
        self.assertFalse(opened["reused"])

    def test_open_or_reuse_card_parallel_windows_assigns_unique_uuid_per_card(self) -> None:
        res = open_or_reuse_card_parallel_windows(
            self.project,
            ["U287", "U290", "U291", "U292"],
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["cards_provisioned"], 4)

        claude_ids = {
            card: res["cards"][card]["tools"]["claude"]["window_id"]
            for card in ("U287", "U290", "U291", "U292")
        }
        self.assertEqual(len(set(claude_ids.values())), 4)
        for card, wid in claude_ids.items():
            self.assertIsNone(session_busy(self.project, wid, card))

    def test_sync_claude_desktop_card_sessions_binds_all_spawned_child_sessions(self) -> None:
        transcripts_root = Path(self._tmp.name) / "claude_config" / "projects"
        proj_dir = transcripts_root / "D--D-Workspace-NB-260916-agentic-ai-env-diet"
        proj_dir.mkdir(parents=True, exist_ok=True)
        transcript = proj_dir / "926558e3-548e-4cff-94b3-8fac32aacc94.jsonl"

        desktop_root = Path(self._tmp.name) / "claude_desktop_sessions" / "org" / "ws"
        desktop_root.mkdir(parents=True, exist_ok=True)
        parent_session_file = desktop_root / "local_9538324b-ca9a-4629-9caf-48d4dc0dffcb.json"
        parent_session_file.write_text(
            json.dumps(
                {
                    "sessionId": "local_9538324b-ca9a-4629-9caf-48d4dc0dffcb",
                    "cliSessionId": "926558e3-548e-4cff-94b3-8fac32aacc94",
                    "title": "Codex 사용량 제한 대응",
                    "titleSource": "user",
                    "previousTitles": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        child_session_file = desktop_root / "local_b30fe6ed-a0e1-457c-ad56-715be55da702.json"
        child_session_file.write_text(
            json.dumps(
                {
                    "sessionId": "local_b30fe6ed-a0e1-457c-ad56-715be55da702",
                    "cliSessionId": "a86bf3f2-7de7-4c08-8a36-e3cf34c4f994",
                    "title": "U291 PR #256 비작성자 판정",
                    "titleSource": "tool",
                    "worktreePath": "D:\\D_Workspace_NB\\-agentic-ai-workspace\\260916_agentic-ai-env-diet\\.claude\\worktrees\\competent-panini-d22daa",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        rows = [
            {
                "type": "assistant",
                "sessionId": "926558e3-548e-4cff-94b3-8fac32aacc94",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_01",
                            "name": "mcp__ccd_session__mark_chapter",
                            "input": {"title": "카드별 병렬 세션 가동"},
                        },
                        {
                            "type": "tool_use",
                            "id": "toolu_u291",
                            "name": "mcp__ccd_session__start_session",
                            "input": {
                                "initiation": "user_asked",
                                "title": "U291 PR #256 비작성자 판정",
                                "name": "u291-review",
                                "context": "fresh",
                                "use_worktree": True,
                            },
                        },
                        {
                            "type": "tool_use",
                            "id": "toolu_u290",
                            "name": "mcp__ccd_session__start_session",
                            "input": {
                                "initiation": "user_asked",
                                "title": "U290 일일 상한 제거 PR 완결",
                                "name": "u290-pr",
                                "context": "fresh",
                                "use_worktree": True,
                            },
                        },
                        {
                            "type": "tool_use",
                            "id": "toolu_u287",
                            "name": "mcp__ccd_session__start_session",
                            "input": {
                                "initiation": "user_asked",
                                "title": "U287 통합 도우미 원격측정 계약",
                                "name": "u287-telemetry",
                                "context": "fresh",
                                "use_worktree": True,
                            },
                        },
                        {
                            "type": "tool_use",
                            "id": "toolu_u276",
                            "name": "mcp__ccd_session__start_session",
                            "input": {
                                "initiation": "user_asked",
                                "title": "U276+U284 파일럿·작성자 출처 확인",
                                "name": "u276-provenance",
                                "context": "fresh",
                                "use_worktree": True,
                            },
                        },
                    ]
                },
            },
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_u291",
                            "content": "Started session \"U291 PR #256 비작성자 판정\" (session_id: local_b30fe6ed-a0e1-457c-ad56-715be55da702, name: u291-review). It is running in the background.",
                        },
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_u290",
                            "content": "Started session \"U290 일일 상한 제거 PR 완결\" (session_id: local_9958fb7b-2046-401a-ac6c-be0d70918d64, name: u290-pr). It is running in the background.",
                        },
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_u287",
                            "content": "Started session \"U287 통합 도우미 원격측정 계약\" (session_id: local_6ab5c561-0ab1-48cc-87fb-1573e0987636, name: u287-telemetry). It is running in the background.",
                        },
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_u276",
                            "content": "Started session \"U276+U284 파일럿·작성자 출처 확인\" (session_id: local_03c35125-b7eb-4498-ad9b-d44bdf52c946, name: u276-provenance). It is running in the background.",
                        },
                    ]
                },
            },
        ]
        transcript.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")

        self.assertEqual(extract_cards_from_text("U276+U284 파일럿·작성자 출처 확인"), ["U276", "U284"])

        fixed_now = datetime(2026, 11, 2, 3, 15, 0)
        res = sync_claude_desktop_card_sessions(
            self.project,
            transcripts_root=transcripts_root,
            claude_sessions_root=desktop_root.parent.parent,
            now=fixed_now,
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["synced_count"], 5)

        u291_entry = window_entry(self.project, "U291", "claude")
        self.assertEqual(u291_entry["id"], "b30fe6ed-a0e1-457c-ad56-715be55da702")
        self.assertEqual(u291_entry["native_id"], "local_b30fe6ed-a0e1-457c-ad56-715be55da702")
        self.assertEqual(u291_entry["cli_session_id"], "a86bf3f2-7de7-4c08-8a36-e3cf34c4f994")
        self.assertEqual(u291_entry["lane_id"], "VERIFY_AUDIT")

        u276_entry = window_entry(self.project, "U276", "claude")
        u284_entry = window_entry(self.project, "U284", "claude")
        self.assertEqual(u276_entry["id"], "03c35125-b7eb-4498-ad9b-d44bdf52c946")
        self.assertEqual(u284_entry["id"], "03c35125-b7eb-4498-ad9b-d44bdf52c946")

        # Verify topmost parent session automatically became the default user window `[261102-1] Codex 사용량 제한 대응`
        topmost_map = res.get("topmost_user_windows") or {}
        self.assertIn("926558e3-548e-4cff-94b3-8fac32aacc94", topmost_map)
        top_entry = topmost_map["926558e3-548e-4cff-94b3-8fac32aacc94"]
        self.assertTrue(top_entry["ok"])
        self.assertTrue(top_entry["is_default_user_window"])
        self.assertEqual(top_entry["prefix"], "[261102-1]")
        self.assertEqual(top_entry["representative_title"], "Codex 사용량 제한 대응")
        self.assertEqual(top_entry["full_title"], "[261102-1] Codex 사용량 제한 대응")
        self.assertEqual(top_entry["store_status"], "RENAMED")
        self.assertEqual(uw.desk_role(self.project, "claude", "926558e3-548e-4cff-94b3-8fac32aacc94"), "PRIMARY")

        updated_parent = json.loads(parent_session_file.read_text(encoding="utf-8"))
        self.assertEqual(updated_parent["title"], "[261102-1] Codex 사용량 제한 대응")
        self.assertIn("Codex 사용량 제한 대응", updated_parent["previousTitles"])

        # Verify child card sessions are NEVER claimed or renamed as topmost `[YYMMDD-N]` user windows
        updated_child = json.loads(child_session_file.read_text(encoding="utf-8"))
        self.assertEqual(updated_child["title"], "U291 PR #256 비작성자 판정")
        self.assertTrue(
            is_child_card_session(
                self.project,
                "local_b30fe6ed-a0e1-457c-ad56-715be55da702",
                claude_sessions_root=desktop_root.parent.parent,
            )
        )
        refused = ensure_topmost_user_window(
            self.project,
            "claude",
            "local_b30fe6ed-a0e1-457c-ad56-715be55da702",
            representative_title="U291 PR #256 비작성자 판정",
            claude_sessions_root=desktop_root.parent.parent,
        )
        self.assertFalse(refused["ok"])
        self.assertEqual(refused["reason"], "CHILD_CARD_SESSION")

    def test_build_launch_spec_and_cli_orchestrate_cards(self) -> None:
        spec = build_card_parallel_launch_spec(
            self.project,
            "U276+U284",
            title="파일럿·작성자 출처 확인",
            role="provenance",
            parent_session_id="926558e3-548e-4cff-94b3-8fac32aacc94",
            parent_title="Codex 사용량 제한 대응",
        )
        self.assertTrue(spec["ok"])
        self.assertEqual(spec["chapter_title"], "카드별 병렬 세션 가동")
        self.assertEqual(spec["cards"], ["U276", "U284"])
        self.assertTrue(spec["topmost_user_window"]["is_default_user_window"])
        self.assertEqual(spec["topmost_user_window"]["representative_title"], "Codex 사용량 제한 대응")
        self.assertRegex(spec["topmost_user_window"]["full_title"], r"^\[\d{6}-\d+\] Codex 사용량 제한 대응$")
        claude_start = spec["native_launchers"]["claude_desktop"]["start_session"]["input"]
        self.assertEqual(claude_start["context"], "fresh")
        self.assertTrue(claude_start["use_worktree"])
        agy_sub = spec["native_launchers"]["antigravity"]["invoke_subagent"]["input"]
        self.assertEqual(agy_sub["Workspace"], "branch")

        batch = orchestrate_card_parallel_batch(
            self.project,
            ["U291", "U290", "U287"],
            actor="antigravity",
            parent_session_id="e83f605a-9f01-4c63-a7d3-c143cd316bc1",
            parent_title="카드별 병렬 세션 가동 표준화 설계",
            sync_desktop=False,
        )
        self.assertTrue(batch["ok"])
        self.assertEqual(batch["cards_provisioned"], 3)
        self.assertEqual(len(batch["launch_specs"]), 3)
        self.assertIn("e83f605a-9f01-4c63-a7d3-c143cd316bc1", batch["topmost_user_windows"])
        top_agy = batch["topmost_user_windows"]["e83f605a-9f01-4c63-a7d3-c143cd316bc1"]
        self.assertRegex(top_agy["full_title"], r"^\[\d{6}-\d+\] 카드별 병렬 세션 가동 표준화 설계$")

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main([
                "coord",
                "lanes",
                "--project",
                str(self.project),
                "--action",
                "orchestrate-cards",
                "--card",
                "U291,U290,U287",
                "--session-id",
                "e83f605a-9f01-4c63-a7d3-c143cd316bc1",
                "--title",
                "카드별 병렬 세션 가동 표준화 설계",
            ])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["cards_provisioned"], 3)


if __name__ == "__main__":
    unittest.main()
