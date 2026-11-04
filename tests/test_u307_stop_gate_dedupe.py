"""U307: Fix duplicate Claude Stop hook output (project_owns_gate) and all-DONE schedule false LIMITED wait."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord import stop_gate, wait_reason

REPO = Path(__file__).resolve().parents[1]
NOW = 1793773200.0


class U307StopGateDedupeTests(unittest.TestCase):
    def test_project_owns_gate_true_when_other_hooks_use_from_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            claude_dir = root / ".claude"
            claude_dir.mkdir(parents=True)
            settings = {
                "hooks": {
                    "SessionStart": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python -m v7_harness.cli coord presence --tool claude --state ACTIVE --from-hook",
                                }
                            ]
                        }
                    ],
                    "Stop": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python -m v7_harness.cli coord stop-gate --project . --tool claude",
                                }
                            ]
                        }
                    ],
                }
            }
            (claude_dir / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
            self.assertTrue(stop_gate.project_owns_gate(root, "claude"))
        self.assertTrue(stop_gate.project_owns_gate(REPO, "claude"))

    def test_project_owns_gate_false_when_stop_hook_is_from_hook_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            claude_dir = root / ".claude"
            claude_dir.mkdir(parents=True)
            settings = {
                "hooks": {
                    "Stop": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python ~/.uaos/uaos.py coord stop-gate --tool claude --from-hook",
                                }
                            ]
                        }
                    ]
                }
            }
            (claude_dir / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
            self.assertFalse(stop_gate.project_owns_gate(root, "claude"))

    def test_all_done_schedule_does_not_report_peer_limited_wait(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".coord" / "presence").mkdir(parents=True)
            (project / ".coord" / "presence" / "codex.json").write_text(
                json.dumps(
                    {
                        "tool": "codex",
                        "state": "LIMITED",
                        "observed_at": "2026-11-04T05:00:00+00:00",
                        "expires_at": NOW + 3600,
                    }
                ),
                encoding="utf-8",
            )
            sched = {
                "schedule_id": "U307",
                "phases": [
                    {"phase_id": "U304-D", "state": "DONE"},
                    {"phase_id": "U305", "state": "DONE"},
                ],
            }
            (project / ".coord" / "master_schedule.json").write_text(
                json.dumps(sched), encoding="utf-8"
            )
            self.assertEqual([], wait_reason.reasons(project, "claude", now=NOW))
            self.assertIsNone(wait_reason.stop_output(None, project, "claude", now=NOW))
            rep = wait_reason.write_wait_status_report(project, "claude", now=NOW)
            self.assertEqual("ALL_DONE", rep["state"])
            self.assertTrue(rep["all_done"])

    def test_active_schedule_still_reports_peer_limited_wait(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".coord" / "presence").mkdir(parents=True)
            (project / ".coord" / "presence" / "codex.json").write_text(
                json.dumps(
                    {
                        "tool": "codex",
                        "state": "LIMITED",
                        "observed_at": "2026-11-04T05:00:00+00:00",
                        "expires_at": NOW + 3600,
                    }
                ),
                encoding="utf-8",
            )
            sched = {
                "schedule_id": "U307",
                "phases": [
                    {"phase_id": "U304-D", "state": "DONE"},
                    {"phase_id": "U307", "state": "READY", "owner_tool": "codex"},
                ],
            }
            (project / ".coord" / "master_schedule.json").write_text(
                json.dumps(sched), encoding="utf-8"
            )
            lines = wait_reason.reasons(project, "claude", now=NOW)
            self.assertTrue(any("codex 사용량 한도로 멈춤" in line for line in lines), lines)


if __name__ == "__main__":
    unittest.main()
