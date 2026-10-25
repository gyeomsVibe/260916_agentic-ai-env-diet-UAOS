"""U241 & U241B fixed acceptance: Antigravity Primary User-Facing Control UX/UI, TTL Presence, owner_tool, and Auto-Trigger."""
import json
from pathlib import Path
import tempfile
import unittest


class U241ControlUxTests(unittest.TestCase):
    def _setup_fake_project(self, root: Path) -> Path:
        coord = root / ".coord"
        (coord / "presence" / "pending_wake" / "antigravity").mkdir(parents=True)
        (coord / "results").mkdir(parents=True)
        for tool, state, exp in [
            ("antigravity", "ACTIVE", 2000.0),
            ("codex", "ACTIVE", 900.0),
            ("claude", "ACTIVE", 2000.0),
        ]:
            (coord / "presence" / f"{tool}.json").write_text(
                json.dumps({"tool": tool, "state": state, "observed_at": 800.0, "expires_at": exp}),
                encoding="utf-8",
            )
        (coord / "presence" / "pending_wake" / "antigravity" / "w1.json").write_text(
            json.dumps({"target": "antigravity", "message_id": "relay_test1", "pid": 12345}),
            encoding="utf-8",
        )
        schedule = {
            "desk_thread": "580b0c75-603a-4448-9f1a-e6ce3a66ce8e",
            "phases": [
                {"phase_id": "U239C", "title": "RSI Grain & Window Fix", "state": "DONE", "owner_tool": "ollama"},
                {"phase_id": "U237E", "title": "Topic URL/Path Sanitizer", "state": "DONE", "owner_tool": "claude"},
                {"phase_id": "U241B", "title": "Antigravity Main Control UX/UI Auto-Trigger", "state": "ACTIVE", "owner_tool": "antigravity"},
            ],
        }
        (coord / "master_schedule.json").write_text(json.dumps(schedule, ensure_ascii=False), encoding="utf-8")
        return root

    def test_collect_snapshot_enforces_ttl_presence_and_primary_user_desk(self):
        from v7_harness.control_ux import collect_control_ux_snapshot

        with tempfile.TemporaryDirectory() as tmp:
            root = self._setup_fake_project(Path(tmp))
            snap = collect_control_ux_snapshot(root, now=1000.0)
            self.assertEqual(snap["schema"], "uaos-control-ux-v1")
            self.assertEqual(snap["primary_user_desk"], "antigravity")
            self.assertIn("사용자와의 메인 대화창구", snap["user_desk_role"])
            self.assertEqual(snap["tools"]["antigravity"]["state"], "ACTIVE")
            self.assertEqual(snap["tools"]["antigravity"]["observed_at"], 800.0)
            self.assertEqual(snap["tools"]["codex"]["state"], "UNKNOWN")
            self.assertEqual(snap["tools"]["codex"]["observed_at"], 800.0)
            self.assertIn("ollama", snap["workers"])
            self.assertIn("haiku", snap["workers"])
            self.assertGreaterEqual(len(snap["background_tasks"]), 1)
            self.assertEqual(snap["schedule_summary"]["total"], 3)
            self.assertEqual(snap["schedule_summary"]["done"], 2)
            self.assertEqual(snap["schedule_summary"]["active"], 1)

    def test_render_control_ux_html_renders_canonical_owner_tool_and_agy_desk_banner(self):
        from v7_harness.control_ux import collect_control_ux_snapshot, render_control_ux_html

        with tempfile.TemporaryDirectory() as tmp:
            root = self._setup_fake_project(Path(tmp))
            snap = collect_control_ux_snapshot(root, now=1000.0)
            out_file = root / "docs" / "00_CONTROL_UX_DASHBOARD.html"
            html = render_control_ux_html(snap, out_file)
            self.assertTrue(out_file.is_file())
            self.assertIn("uaos-control-ux-v1", html)
            self.assertIn("사용자와의 메인 대화창구", html)
            self.assertIn("<td>ollama</td>", html)
            self.assertIn("<td>claude</td>", html)
            self.assertIn("<td>antigravity</td>", html)
            self.assertIn("U241B", html)
            self.assertIn("relay_test1", html)

    def test_auto_trigger_on_declaration_and_status_requests(self):
        from v7_harness.control_ux import auto_render_control_ux, should_auto_render_control_ux

        self.assertTrue(should_auto_render_control_ux("이제부터 이 대화창이 사용자 대상 대화창구이다."))
        self.assertTrue(should_auto_render_control_ux("현재 진행상황을 알려줘"))
        self.assertTrue(should_auto_render_control_ux("진행상황을 브리핑해라."))
        self.assertFalse(should_auto_render_control_ux("단순 코드 리뷰 요청"))

        with tempfile.TemporaryDirectory() as tmp:
            root = self._setup_fake_project(Path(tmp))
            out_path = root / "docs" / "00_CONTROL_UX_DASHBOARD.html"
            res = auto_render_control_ux(
                root,
                "antigravity",
                "현재 진행상황을 알려줘",
                output_path=out_path,
                now=1000.0,
            )
            self.assertTrue(res["triggered"])
            self.assertEqual(res["primary_user_desk"], "antigravity")
            self.assertTrue(out_path.is_file())
            content = out_path.read_text(encoding="utf-8")
            self.assertIn("사용자와의 메인 대화창구", content)


if __name__ == "__main__":
    unittest.main()
