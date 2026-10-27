"""Unit & Counterexample Tests for U269: U251 Operational Telemetry & RSI Self-Healing Evolution Scheduler."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.benchmark_logic_transplant import (
    U251_OPERATIONAL_TELEMETRY_LEDGER,
    collect_live_five_chip_telemetry,
    diagnose_u251_operational_anomalies,
    record_u251_operational_telemetry_and_schedule_rsi,
)
from v7_harness.cli import main as cli_main


class TestU269U251RsiOperationalEvolution(unittest.TestCase):
    def _make_project(self, tmp: str) -> Path:
        root = Path(tmp)
        (root / ".coord" / "presence").mkdir(parents=True, exist_ok=True)
        (root / ".coord" / "usage").mkdir(parents=True, exist_ok=True)
        (root / ".coord" / "rsi").mkdir(parents=True, exist_ok=True)
        return root

    def test_1_diagnose_anomalies_and_idempotent_auto_schedule(self) -> None:
        """Detect live U251 anomalies, write operational ledger receipt, and idempotently schedule self-healing cards."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_project(tmp)
            # Codex LIMITED (quota stop), Claude & Antigravity ACTIVE, 1 READY phase, 0 watchers
            (root / ".coord" / "master_schedule.json").write_text(
                json.dumps(
                    {
                        "topic": "5칩계기판·U251-RSI진화",
                        "phases": [
                            {
                                "phase_id": "U269",
                                "title": "U251 실사운용 기록 및 RSI 자가수정 스케줄링",
                                "state": "ACTIVE",
                                "owner": "codex",
                                "reviewer": "claude",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            now = 1800000000.0
            for tool, state in (("codex", "LIMITED"), ("claude", "ACTIVE"), ("antigravity", "ACTIVE")):
                (root / ".coord" / "presence" / f"{tool}.json").write_text(
                    json.dumps(
                        {
                            "tool": tool,
                            "state": state,
                            "observed_at": "2026-10-27T01:00:00+00:00",
                            "expires_at": now + 7200,
                            "lease": True,
                        }
                    ),
                    encoding="utf-8",
                )

            # Also seed 3 failed local runs in .coord/usage/runs.jsonl so RSI ledger proposal triggers
            runs_path = root / ".coord" / "usage" / "runs.jsonl"
            rows = [
                {
                    "kind": "pilot",
                    "work_id": f"U269-L{i}",
                    "worker": "ollama",
                    "outcome": "REWORK",
                    "error_class": "NO_FILE_BLOCK",
                    "input_tokens": 500,
                    "output_tokens": 120,
                    "ts": now - 60 + i,
                }
                for i in range(3)
            ]
            runs_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

            # 1st run with foreground_wait_s=8.5 (> 5.0s limit) and auto_schedule=True
            res1 = record_u251_operational_telemetry_and_schedule_rsi(
                root,
                target_path=".work/library/rea/README.md",
                foreground_wait_s=8.5,
                is_background_watcher=False,
                acting_tool="antigravity",
                auto_schedule=True,
                now=now,
            )
            self.assertTrue(res1["ok"])
            self.assertEqual(res1["schema"], "uaos.u251_rsi_evolution_report.v1")
            self.assertEqual(
                res1["rea_tier_routing"]["selected_tier"],
                "TIER_2_ON_DEMAND_REVERSE_ENGINEERING",
            )

            codes = {a["anomaly_code"] for a in res1["anomalies"]}
            self.assertIn("NO_LIVE_WATCHER_WHILE_WAITING", codes)
            self.assertIn("FAILOVER_DEGRADED_MODE", codes)
            self.assertIn("FOREGROUND_WAIT_PREEMPTED", codes)

            ledger_codes = {p["anomaly_code"] for p in res1["rsi_ledger_proposals"]}
            self.assertIn("LEDGER_NO_FILE_BLOCK", ledger_codes)

            # Verify operational telemetry ledger was written
            op_ledger = root / U251_OPERATIONAL_TELEMETRY_LEDGER
            self.assertTrue(op_ledger.is_file())
            ledger_lines = [json.loads(line) for line in op_ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(ledger_lines), 1)
            self.assertEqual(ledger_lines[0]["schema"], "uaos.u251_operational_telemetry.v1")

            # Verify self-healing phases were added to master_schedule.json with owner != reviewer
            sched = json.loads((root / ".coord" / "master_schedule.json").read_text(encoding="utf-8"))
            rsi_phases = [p for p in sched["phases"] if str(p.get("phase_id", "")).startswith("RSI-U251-AUTO-")]
            self.assertGreaterEqual(len(rsi_phases), 4)
            for p in rsi_phases:
                self.assertEqual(p["state"], "READY")
                self.assertNotEqual(p["owner"], p["reviewer"], "Self-judge is forbidden (U258/B83)")
                self.assertIn(p["owner"], ("claude", "antigravity"))
                self.assertTrue(p.get("title", "").startswith("[U251-RSI 자가수정]"))
                spec = p.get("self_healing_spec") or {}
                self.assertEqual(spec.get("observation_count"), 1)
                self.assertTrue(spec.get("accept_cmd"))

            # 2nd run: verify idempotency (no duplicate phases added; same evidence within 1 h stays one observation, U272)
            res2 = record_u251_operational_telemetry_and_schedule_rsi(
                root,
                target_path="v7_harness/cli.py",
                foreground_wait_s=8.5,
                is_background_watcher=False,
                acting_tool="antigravity",
                auto_schedule=True,
                now=now + 30.0,
            )
            sched2 = json.loads((root / ".coord" / "master_schedule.json").read_text(encoding="utf-8"))
            rsi_phases2 = [p for p in sched2["phases"] if str(p.get("phase_id", "")).startswith("RSI-U251-AUTO-")]
            self.assertEqual(len(rsi_phases2), len(rsi_phases))
            for p in rsi_phases2:
                self.assertEqual(p["self_healing_spec"]["observation_count"], 1)
            self.assertTrue(all(c["action"] == "SAME_EPISODE" for c in res2["scheduled_self_healing_cards"]))

    def test_2_quiet_lock_prevents_mutation(self) -> None:
        """Under .work/QUIET_LOCK, record_u251_operational_telemetry_and_schedule_rsi must not write schedule or ledger."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_project(tmp)
            (root / ".work").mkdir(parents=True, exist_ok=True)
            (root / ".work" / "QUIET_LOCK").write_text("{}", encoding="utf-8")
            (root / ".coord" / "master_schedule.json").write_text(
                json.dumps({"phases": [{"phase_id": "U269", "title": "test", "state": "READY", "owner": "codex"}]}),
                encoding="utf-8",
            )
            res = record_u251_operational_telemetry_and_schedule_rsi(
                root,
                foreground_wait_s=9.0,
                auto_schedule=True,
            )
            self.assertTrue(res["ok"])
            self.assertEqual(res["scheduled_self_healing_cards"], [])
            self.assertFalse((root / U251_OPERATIONAL_TELEMETRY_LEDGER).exists())

    def test_3_cli_coord_transplant_status_json_and_table(self) -> None:
        """CLI `coord transplant-status` exits 0 in both json and table modes and schedules self-healing cards."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_project(tmp)
            (root / ".coord" / "master_schedule.json").write_text(
                json.dumps(
                    {
                        "topic": "5칩계기판·U251-RSI진화",
                        "phases": [
                            {"phase_id": "U269", "title": "실사운용 테스트", "state": "READY", "owner": "antigravity"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            rc_json = cli_main(["coord", "transplant-status", "--project", str(root), "--auto-schedule", "--format", "json"])
            self.assertEqual(rc_json, 0)
            rc_tbl = cli_main(["coord", "transplant-status", "--project", str(root), "--format", "table"])
            self.assertEqual(rc_tbl, 0)


    def test_4_failover_reassignment_checklist_and_post_schedule_chip1_refresh(self) -> None:
        """When codex is LIMITED and claude+antigravity are ACTIVE, auto_schedule reassigns offline-owned phases,
        updates .coord/codex_return_checklist.md, deduplicates duplicate phase_ids, and refreshes Chip 1 remaining count."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_project(tmp)
            now = 1800000500.0
            for tool, state in (("codex", "LIMITED"), ("claude", "ACTIVE"), ("antigravity", "ACTIVE")):
                (root / ".coord" / "presence" / f"{tool}.json").write_text(
                    json.dumps(
                        {
                            "tool": tool,
                            "state": state,
                            "observed_at": "2026-10-27T06:00:00+00:00",
                            "expires_at": now + 7200,
                            "lease": True,
                        }
                    ),
                    encoding="utf-8",
                )
            (root / ".coord" / "master_schedule.json").write_text(
                json.dumps(
                    {
                        "topic": "5칩계기판·U251-RSI진화",
                        "phases": [
                            {"phase_id": "U275", "title": "Codex offline card", "state": "READY", "owner": "codex"},
                            {"phase_id": "DUP-DONE", "title": "dup1", "state": "DONE_ELSEWHERE", "owner": "claude"},
                            {"phase_id": "DUP-DONE", "title": "dup2", "state": "DONE_ELSEWHERE", "owner": "antigravity"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            res = record_u251_operational_telemetry_and_schedule_rsi(
                root,
                acting_tool="antigravity",
                auto_schedule=True,
                now=now,
            )
            c1 = res["five_chip_telemetry"]["chips"]["1_todos_schedule"]
            self.assertGreaterEqual(c1["remaining"], 2)
            self.assertFalse(c1["all_done"])
            sched = json.loads((root / ".coord" / "master_schedule.json").read_text(encoding="utf-8"))
            pids = [p["phase_id"] for p in sched["phases"]]
            self.assertEqual(pids.count("DUP-DONE"), 1)
            u275 = next(p for p in sched["phases"] if p["phase_id"] == "U275")
            self.assertIn(u275["owner"], ("claude", "antigravity"))
            self.assertEqual(u275["previous_owner"], "codex")
            self.assertNotEqual(u275["owner"], u275["reviewer"])
            chk = (root / ".coord" / "codex_return_checklist.md").read_text(encoding="utf-8")
            self.assertIn("U275 (codex->", chk)


if __name__ == "__main__":
    unittest.main()
