"""Unit tests for U161 autonomous task pickup & work stealing on idle timeout."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from v7_harness.coord.mailbox import Mailbox
from v7_harness.coord.task_pickup import (
    pickup_task,
    request_task_from_conductor,
    scan_mailbox_for_tasks,
    scan_plan_for_ready_tasks,
)


class TestTaskPickup(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        (self.project / ".coord" / "mailbox").mkdir(parents=True, exist_ok=True)
        (self.project / ".coord" / "presence").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_scan_mailbox_finds_actionable_task(self):
        box = Mailbox(self.project / ".coord" / "mailbox")
        payload = {
            "actor": "claude",
            "requested_target": "antigravity",
            "wake_class": "ACTIONABLE",
            "delta": "audit request",
            "message": "Please audit this task.",
        }
        box.publish("relay_test_actionable_001", payload)
        task = scan_mailbox_for_tasks(self.project, "antigravity")
        self.assertIsNotNone(task)
        self.assertEqual("ACTIONABLE_LETTER", task["status"])
        self.assertEqual("relay_test_actionable_001", task["message_id"])

    def test_scan_mailbox_ignores_notice(self):
        box = Mailbox(self.project / ".coord" / "mailbox")
        payload = {
            "actor": "claude",
            "requested_target": "antigravity",
            "wake_class": "NOTICE",
            "message": "Just a notice",
        }
        box.publish("relay_test_notice_002", payload)
        task = scan_mailbox_for_tasks(self.project, "antigravity")
        self.assertIsNone(task)

    def test_scan_plan_finds_ready_cards(self):
        plan_path = self.project / ".coord" / "PLAN.md"
        plan_content = """# Plan
| ID | 상태 | 소유자 | 내용 |
|---|---|---|---|
| U160 | DONE | codex | Completed task |
| U161 | READY | antigravity | Auto task pickup implementation |
| U162 | READY | claude | Claude task |
"""
        plan_path.write_text(plan_content, encoding="utf-8")
        task = scan_plan_for_ready_tasks(self.project, "antigravity")
        self.assertIsNotNone(task)
        self.assertEqual("READY_CARD", task["status"])
        self.assertEqual("U161", task["card"])

    def test_pickup_task_idle_without_auto_request(self):
        result = pickup_task(self.project, "antigravity", auto_request=False)
        self.assertEqual("IDLE", result["status"])

    def test_pickup_task_auto_request_sends_to_conductor(self):
        # Create presence for codex as ACTIVE conductor
        (self.project / ".coord" / "presence" / "codex.json").write_text(
            json.dumps({"state": "ACTIVE", "observed_at": "2026-10-04T12:00:00Z"}), encoding="utf-8"
        )
        result = pickup_task(self.project, "antigravity", auto_request=True)
        self.assertEqual("TASK_REQUESTED", result["status"])
        self.assertEqual("codex", result["target"])
        self.assertTrue(result["message_id"].startswith("relay_"))


if __name__ == "__main__":
    unittest.main()
