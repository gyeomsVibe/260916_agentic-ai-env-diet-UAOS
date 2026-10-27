from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord import capacity_planner as CP


class TestU274SubProcessScheduleArchitecture(unittest.TestCase):
    def test_1_predictive_exhaustion_burn_rate_and_preemptive_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            (root / ".coord" / "usage").mkdir(parents=True, exist_ok=True)
            (root / ".coord" / "presence").mkdir(parents=True, exist_ok=True)
            now = 1793078000.0
            for t in ("codex", "claude", "antigravity"):
                (root / ".coord" / "presence" / f"{t}.json").write_text(
                    json.dumps({"tool": t, "state": "ACTIVE", "heartbeat_at": now}),
                    encoding="utf-8",
                )
            # Codex used 6.5M / 7.0M in 5h (~92.9% -> IMMINENT_EXHAUSTION)
            # Claude used 11.2M / 15.0M in 5h (~74.7% -> PRE_HANDOFF_WARNING)
            # Antigravity used 10.0M / 75.0M in 5h (~13.3% -> SAFE)
            runs = [
                {
                    "work_id": "U274-codex",
                    "actor": "codex",
                    "worker": "codex",
                    "timestamp": now - 600,
                    "input_tokens": 5500000,
                    "output_tokens": 1000000,
                },
                {
                    "work_id": "U274-claude",
                    "actor": "claude",
                    "worker": "claude",
                    "timestamp": now - 600,
                    "input_tokens": 10000000,
                    "output_tokens": 300000,
                },
                {
                    "work_id": "U274-agy",
                    "actor": "antigravity",
                    "worker": "agy",
                    "timestamp": now - 600,
                    "input_tokens": 9000000,
                    "output_tokens": 1000000,
                },
            ]
            (root / ".coord" / "usage" / "runs.jsonl").write_text(
                "\n".join(json.dumps(r) for r in runs) + "\n",
                encoding="utf-8",
            )
            snap = CP.collect_capacity_snapshot(root, home=home, now=now, persist=True)
            eng = snap["engines"]
            self.assertEqual(eng["codex"]["predictive_exhaustion"]["exhaustion_risk"], "IMMINENT_EXHAUSTION")
            self.assertTrue(eng["codex"]["predictive_exhaustion"]["preemptive_handoff_recommended"])
            self.assertEqual(eng["claude"]["predictive_exhaustion"]["exhaustion_risk"], "PRE_HANDOFF_WARNING")
            self.assertTrue(eng["claude"]["predictive_exhaustion"]["preemptive_handoff_recommended"])
            self.assertEqual(eng["antigravity"]["predictive_exhaustion"]["exhaustion_risk"], "SAFE")
            self.assertFalse(eng["antigravity"]["predictive_exhaustion"]["preemptive_handoff_recommended"])
            self.assertEqual(eng["ollama"]["predictive_exhaustion"]["exhaustion_risk"], "UNLIMITED_LOCAL")

    def test_2_sub_process_schedule_5stage_dag_and_disjoint_5_3_2_lanes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            (root / ".coord" / "usage").mkdir(parents=True, exist_ok=True)
            (root / ".coord" / "presence").mkdir(parents=True, exist_ok=True)
            now = 1793078000.0
            for t in ("codex", "claude", "antigravity"):
                (root / ".coord" / "presence" / f"{t}.json").write_text(
                    json.dumps({"tool": t, "state": "ACTIVE", "heartbeat_at": now}),
                    encoding="utf-8",
                )
            (root / ".coord" / "master_schedule.json").write_text(
                json.dumps({
                    "phases": [
                        {"phase_id": "U274-A", "state": "READY", "owner": "claude", "reviewer": "antigravity"},
                        {"phase_id": "U274-B", "state": "REVIEW", "owner": "antigravity", "reviewer": "codex"},
                    ]
                }),
                encoding="utf-8",
            )
            snap = CP.collect_capacity_snapshot(root, home=home, now=now, persist=True)
            sub_sched = snap["sub_process_schedule"]
            self.assertEqual(sub_sched["schema"], "uaos-sub-process-schedule-v1")
            self.assertEqual(sub_sched["total_active_cards"], 2)
            self.assertEqual(sub_sched["total_sub_processes"], 10)
            self.assertTrue((root / ".coord" / "sub_process_schedule.json").is_file())
            for cs in sub_sched["card_sub_schedules"]:
                self.assertNotEqual(cs["assigned_executor"], cs["assigned_verifier"])
                self.assertEqual(len(cs["sub_processes"]), 5)
                sp3 = cs["sub_processes"][2]
                self.assertEqual(sp3["disjoint_lanes"]["code_lane"]["allow"], ["v7_harness/*.py"])
                self.assertEqual(sp3["disjoint_lanes"]["test_doc_lane"]["allow"], ["tests/*", "docs/*"])

    def test_3_autonomous_fluid_rebalance_on_imminent_exhaustion(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            (root / ".coord" / "usage").mkdir(parents=True, exist_ok=True)
            (root / ".coord" / "presence").mkdir(parents=True, exist_ok=True)
            now = 1793078000.0
            for t in ("codex", "claude", "antigravity"):
                (root / ".coord" / "presence" / f"{t}.json").write_text(
                    json.dumps({"tool": t, "state": "ACTIVE", "heartbeat_at": now}),
                    encoding="utf-8",
                )
            # Make codex near exhaustion (6.8M / 7M)
            (root / ".coord" / "usage" / "runs.jsonl").write_text(
                json.dumps({
                    "work_id": "U274-heavy",
                    "actor": "codex",
                    "worker": "codex",
                    "timestamp": now - 300,
                    "input_tokens": 6000000,
                    "output_tokens": 800000,
                }) + "\n",
                encoding="utf-8",
            )
            (root / ".coord" / "master_schedule.json").write_text(
                json.dumps({
                    "phases": [
                        {"phase_id": "U274-KEY", "state": "READY", "owner": "codex", "codex_exclusive": True},
                    ]
                }),
                encoding="utf-8",
            )
            res = CP.sync_autonomous_schedules(root, home=home, now=now)
            self.assertTrue(res["ok"])
            self.assertGreaterEqual(len(res["fluid_rebalance_events"]), 1)
            ev = res["fluid_rebalance_events"][0]
            self.assertEqual(ev["from_tool"], "codex")
            self.assertIn(ev["to_tool"], ("antigravity", "claude"))
            updated_master = json.loads((root / ".coord" / "master_schedule.json").read_text(encoding="utf-8"))
            self.assertEqual(updated_master["phases"][0]["owner"], ev["to_tool"])

    def test_4_terminal_and_html_dashboards_render_sub_process_dag(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            (root / ".coord" / "usage").mkdir(parents=True, exist_ok=True)
            (root / ".coord" / "presence").mkdir(parents=True, exist_ok=True)
            now = 1793078000.0
            for t in ("codex", "claude", "antigravity"):
                (root / ".coord" / "presence" / f"{t}.json").write_text(
                    json.dumps({"tool": t, "state": "ACTIVE", "heartbeat_at": now}),
                    encoding="utf-8",
                )
            (root / ".coord" / "master_schedule.json").write_text(
                json.dumps({"phases": [{"phase_id": "U274-DAG", "state": "READY", "owner": "antigravity"}]}),
                encoding="utf-8",
            )
            snap = CP.collect_capacity_snapshot(root, home=home, now=now, persist=True)
            term = CP.render_terminal_dashboard(snap)
            self.assertIn("[세부스케줄]", term)
            self.assertIn("SP1:ollama", term)
            out_html = root / "dash.html"
            CP.render_html_dashboard(snap, out_html)
            html_str = out_html.read_text(encoding="utf-8")
            self.assertIn("세부 프로세스 DAG", html_str)


if __name__ == "__main__":
    unittest.main()
