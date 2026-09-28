"""U81: a deterministic apply refusal keeps its own cause in the ledger instead of looking like an Ollama outage.

Seen 2026-09-28 (U80): the apply worker refused with UNREQUESTED_DELETION, the engine reported
UNKNOWN_EFFECT_NEEDS_RECONCILIATION, the ledger row said PROVIDER_ERROR, and `rsi propose` advised checking the
Ollama service, which the apply worker never calls.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from v7_harness import rsi
from v7_harness.adapters import apply_worker
from v7_harness.pilot import PilotConfig, run_pilot

APPLY = [sys.executable, str(Path(apply_worker.__file__).resolve())]


class ApplyCauseTests(unittest.TestCase):
    def test_an_apply_refusal_is_recorded_as_its_own_cause(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / "proj"
            (source / ".coord").mkdir(parents=True)
            (source / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
            (source / "calc.py").write_text("def mul(a, b):\n    return a * b\n", encoding="utf-8")
            summary = run_pilot(PilotConfig(
                task_id="U81_DEL", title="rewrite", prompt="===FILE: calc.py===\nX = 1\n", source_dir=source,
                work_dir=root / "work", agy_command=APPLY, watch_roots=[], print_timeout_s=60,
                accept_cmd=f'"{sys.executable}" -c "pass"', allowed_scopes=["calc.py"],
            ))
            self.assertNotEqual("PASS", summary["verdict_hint"])
            self.assertIn("UNREQUESTED_DELETION:calc.py:mul", summary["error_detail"])
            row = json.loads((source / ".coord" / "usage" / "runs.jsonl").read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual("UNREQUESTED_DELETION", rsi._cause(row))

    def test_the_u80_ledger_row_proposes_the_manual_remedy(self) -> None:
        row = {"work_id": "U80", "worker": "apply", "outcome": "BLOCKED", "error_class": "PROVIDER_ERROR",
               "error_detail": "WorkerExecutionError: UNKNOWN_EFFECT_NEEDS_RECONCILIATION; worker: "
                               "UNREQUESTED_DELETION:tests/test_u76c_card_cost.py:test_exit_code_is_zero_only_on_pass"}
        self.assertEqual("UNREQUESTED_DELETION", rsi._cause(row))

    def test_a_plain_provider_error_stays_a_provider_error(self) -> None:
        row = {"outcome": "BLOCKED", "error_class": "PROVIDER_ERROR", "error_detail": "connection refused"}
        self.assertEqual("PROVIDER_ERROR", rsi._cause(row))

    def test_a_specific_error_class_is_not_overridden_by_its_detail(self) -> None:
        row = {"outcome": "REWORK", "error_class": "SCOPE_VIOLATION", "error_detail": "SYNTAX_ERROR:a.py:3"}
        self.assertEqual("SCOPE_VIOLATION", rsi._cause(row))


if __name__ == "__main__":
    unittest.main()
