"""U272: RSI auto-cards must rest on real evidence.

Receipt (2026-10-27): five RSI-U251-AUTO-* cards reached READY with observation_count 2 from two scheduler
runs 3 minutes apart over the same ledger and seat state, and their accept_cmd was green before any change.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness import rsi
from v7_harness.benchmark_logic_transplant import record_u251_operational_telemetry_and_schedule_rsi

NOW = 1800000000.0


def _project(tmp: str, causes: list[str]) -> Path:
    root = Path(tmp)
    for sub in ("presence", "usage", "rsi"):
        (root / ".coord" / sub).mkdir(parents=True, exist_ok=True)
    (root / ".coord" / "master_schedule.json").write_text(json.dumps({"phases": []}), encoding="utf-8")
    for tool, state in (("codex", "LIMITED"), ("claude", "ACTIVE"), ("antigravity", "ACTIVE")):
        (root / ".coord" / "presence" / f"{tool}.json").write_text(
            json.dumps({"tool": tool, "state": state, "observed_at": "2026-10-27T01:00:00+00:00",
                        "expires_at": NOW + 7200, "lease": True}),
            encoding="utf-8",
        )
    rows = [
        {"kind": "pilot", "work_id": f"U272-{cause}-{i}", "worker": "ollama", "outcome": "BLOCKED",
         "error_class": cause, "input_tokens": 500, "output_tokens": 0, "ts": NOW - 60 + i}
        for cause in causes for i in range(3)
    ]
    (root / ".coord" / "usage" / "runs.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return root


def _run(root: Path, now: float) -> dict:
    return record_u251_operational_telemetry_and_schedule_rsi(
        root, foreground_wait_s=8.5, acting_tool="antigravity", auto_schedule=True, now=now,
    )


def _auto_phases(root: Path) -> dict[str, dict]:
    sched = json.loads((root / ".coord" / "master_schedule.json").read_text(encoding="utf-8"))
    return {p["phase_id"]: p for p in sched["phases"] if str(p.get("phase_id", "")).startswith("RSI-U251-AUTO-")}


class U272RsiAutocardEvidenceTests(unittest.TestCase):
    def test_same_evidence_within_one_hour_is_one_observation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _project(tmp, ["NO_FILE_BLOCK"])
            _run(root, NOW)
            res = _run(root, NOW + 180.0)
            for phase in _auto_phases(root).values():
                self.assertEqual(phase["self_healing_spec"]["observation_count"], 1, phase["phase_id"])
            self.assertTrue(res["scheduled_self_healing_cards"])
            self.assertTrue(all(c["action"] == "SAME_EPISODE" for c in res["scheduled_self_healing_cards"]))

    def test_same_evidence_after_one_hour_is_a_second_observation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _project(tmp, ["NO_FILE_BLOCK"])
            _run(root, NOW)
            first = set(_auto_phases(root))
            res = _run(root, NOW + 3600.0)
            again = [c for c in res["scheduled_self_healing_cards"] if c["phase_id"] in first]
            self.assertTrue(again)
            phases = _auto_phases(root)
            for card in again:
                self.assertEqual(card["action"], "UPDATED_EXISTING", card["phase_id"])
                self.assertEqual(phases[card["phase_id"]]["self_healing_spec"]["observation_count"], 2, card["phase_id"])

    def test_ledger_cause_with_remedy_on_file_is_reported_not_scheduled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _project(tmp, ["PROVIDER_ERROR", "U272_UNSEEN_CAUSE"])
            res = _run(root, NOW)
            reported = {p["anomaly_code"] for p in res["rsi_ledger_proposals"]}
            self.assertIn("LEDGER_PROVIDER_ERROR", reported)
            self.assertIn("LEDGER_U272_UNSEEN_CAUSE", reported)
            phases = _auto_phases(root)
            self.assertNotIn("RSI-U251-AUTO-LEDGER_PROVIDER_ERROR", phases)
            self.assertIn("RSI-U251-AUTO-LEDGER_U272_UNSEEN_CAUSE", phases)

    def test_external_write_has_a_remedy_on_file(self) -> None:
        target, action = rsi.REMEDIES["EXTERNAL_WRITE"]
        self.assertEqual(target, "environment")
        self.assertIn(".work/", action)


if __name__ == "__main__":
    unittest.main()
