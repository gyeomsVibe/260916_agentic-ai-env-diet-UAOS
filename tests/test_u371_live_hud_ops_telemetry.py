"""U371: live ops telemetry (regime, schedule, auto-attach) in mobile_hud."""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from v7_harness.coord.mobile_hud import _collect_ops_telemetry, build_mobile_status, render_mobile_html


def _tree(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


class TestU371LiveHudOpsTelemetry(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        (self.root / ".coord").mkdir()

    def _write(self, rel: str, doc) -> None:
        p = self.root / ".coord" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")

    def test_peer_silent_limit_exhausted_regime(self) -> None:
        t = _collect_ops_telemetry(self.root)
        self.assertIsInstance(t["regime"], str)
        self.assertTrue(t["regime"])
        self.assertEqual(set(t), {"regime", "schedule", "auto_attach"})

    def test_message_flood_aggregate_performance(self) -> None:
        self._write("auto_attach/queue.json",
                    [{"state": "PENDING" if i % 2 else "WAITING", "priority": "P1", "mia_tier": "T2"}
                     for i in range(600)])
        for i in range(300):
            self._write(f"auto_attach/verdicts/v{i}.json", {"state": "REQUESTED"})
        start = time.perf_counter()
        t = _collect_ops_telemetry(self.root)
        self.assertLess(time.perf_counter() - start, 10.0)
        self.assertEqual(t["auto_attach"]["total_cards"], 600)
        self.assertEqual(t["auto_attach"]["state_counts"]["PENDING"], 300)
        self.assertEqual(t["auto_attach"]["priorities"]["P1"], 600)

    def test_wait_cycle_deadlock_safe_reporting(self) -> None:
        self._write("auto_attach/queue.json", [
            {"state": "WAITING", "deps": ["B"]}, {"state": "WAITING", "deps": ["A"]}])
        t = _collect_ops_telemetry(self.root)
        self.assertEqual(t["auto_attach"]["state_counts"], {"WAITING": 2})

    def test_crash_mid_write_torn_json_handling(self) -> None:
        self._write("master_schedule.json", '{"current_phase_id": "P1", "phas')
        self._write("auto_attach/queue.json", '[{"state": "PEN')
        t = _collect_ops_telemetry(self.root)
        self.assertEqual(t["schedule"], {"current_phase_id": None, "active_cards_count": 0, "active_cards": []})
        self.assertEqual(t["auto_attach"]["total_cards"], 0)

    def test_duplicate_delivery_cached_responses(self) -> None:
        self._write("auto_attach/queue.json", [{"state": "PENDING"}])
        self.assertEqual(_collect_ops_telemetry(self.root), _collect_ops_telemetry(self.root))

    def test_stale_state_aged_records_display(self) -> None:
        self._write("master_schedule.json", {"current_phase_id": "OLD", "phases": [
            {"phase_id": "OLD", "state": "ACTIVE"}]})
        t = _collect_ops_telemetry(self.root)
        self.assertEqual(t["schedule"]["current_phase_id"], "OLD")
        self.assertEqual(t["schedule"]["active_cards"], ["OLD"])

    def test_conductor_down_regime_reflection(self) -> None:
        self._write("master_schedule.json", {"current_phase_id": "P2", "phases": [
            {"phase_id": "P2", "state": "RUNNING"}, {"phase_id": "P3", "state": "DONE"}, "junk"]})
        self._write("sub_process_schedule.json", {"active_cards": ["U9"]})
        t = _collect_ops_telemetry(self.root)
        self.assertEqual(t["schedule"]["active_cards"], ["P2", "U9"])
        self.assertEqual(t["schedule"]["active_cards_count"], 2)

    def test_user_absent_zero_scratch_pollution(self) -> None:
        before = _tree(self.root)
        t = _collect_ops_telemetry(self.root)
        self.assertEqual(_tree(self.root), before)
        self.assertEqual(t["auto_attach"]["total_cards"], 0)
        self.assertEqual(t["auto_attach"]["open_verdicts"], 0)

    def test_status_and_html_contain_ops(self) -> None:
        data = build_mobile_status(self.root)
        self.assertIn("ops_telemetry", data)
        data["ops_telemetry"]["regime"] = "<script>x</script>"
        html = render_mobile_html(data)
        self.assertNotIn("<script>x</script>", html)
        self.assertIn("&lt;script&gt;", html)


if __name__ == "__main__":
    unittest.main()
