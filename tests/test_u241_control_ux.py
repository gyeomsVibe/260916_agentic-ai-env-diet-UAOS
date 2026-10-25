"""U241 fixed acceptance: Antigravity User-Facing Main Control UX/UI & 3-Tool Parallel/Background Visibility."""
import json
from pathlib import Path
import tempfile
import unittest


class U241ControlUxTests(unittest.TestCase):
    def _setup_fake_project(self, root: Path) -> Path:
        coord = root / ".coord"
        (coord / "presence" / "pending_wake" / "antigravity").mkdir(parents=True)
        (coord / "results").mkdir(parents=True)
        for tool, state in [("antigravity", "ACTIVE"), ("codex", "ACTIVE"), ("claude", "ACTIVE")]:
            (coord / "presence" / f"{tool}.json").write_text(
                json.dumps({"tool": tool, "state": state, "updated_at": "2026-10-26T01:10:00+09:00"}),
                encoding="utf-8",
            )
        (coord / "presence" / "pending_wake" / "antigravity" / "w1.json").write_text(
            json.dumps({"target": "antigravity", "message_id": "relay_test1", "pid": 12345}),
            encoding="utf-8",
        )
        schedule = {
            "desk_thread": "580b0c75-603a-4448-9f1a-e6ce3a66ce8e",
            "phases": [
                {"phase_id": "U239C", "title": "RSI Grain & Window Fix", "state": "DONE", "owner": "ollama"},
                {"phase_id": "U237E", "title": "Topic URL/Path Sanitizer", "state": "DONE", "owner": "claude"},
                {"phase_id": "U241", "title": "Antigravity Main Control UX/UI", "state": "ACTIVE", "owner": "antigravity"},
            ],
        }
        (coord / "master_schedule.json").write_text(json.dumps(schedule, ensure_ascii=False), encoding="utf-8")
        return root

    def test_collect_snapshot_surfaces_3tools_workers_and_background_tasks(self):
        from v7_harness.control_ux import collect_control_ux_snapshot

        with tempfile.TemporaryDirectory() as tmp:
            root = self._setup_fake_project(Path(tmp))
            snap = collect_control_ux_snapshot(root)
            self.assertEqual(snap["schema"], "uaos-control-ux-v1")
            self.assertIn("antigravity", snap["tools"])
            self.assertIn("codex", snap["tools"])
            self.assertIn("claude", snap["tools"])
            self.assertIn("ollama", snap["workers"])
            self.assertIn("haiku", snap["workers"])
            self.assertGreaterEqual(len(snap["background_tasks"]), 1)
            self.assertEqual(snap["schedule_summary"]["total"], 3)
            self.assertEqual(snap["schedule_summary"]["done"], 2)
            self.assertEqual(snap["schedule_summary"]["active"], 1)

    def test_render_control_ux_html_creates_dashboard_file_with_parallel_lanes(self):
        from v7_harness.control_ux import collect_control_ux_snapshot, render_control_ux_html

        with tempfile.TemporaryDirectory() as tmp:
            root = self._setup_fake_project(Path(tmp))
            snap = collect_control_ux_snapshot(root)
            out_file = root / "docs" / "00_CONTROL_UX_DASHBOARD.html"
            html = render_control_ux_html(snap, out_file)
            self.assertTrue(out_file.is_file())
            self.assertIn("uaos-control-ux-v1", html)
            self.assertIn("U239C", html)
            self.assertIn("U237E", html)
            self.assertIn("U241", html)
            self.assertIn("relay_test1", html)


if __name__ == "__main__":
    unittest.main()
