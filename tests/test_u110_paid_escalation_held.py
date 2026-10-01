"""U110: a failed local run never spends paid tokens on its own; the run that pays names its worker.

2026-09-30..10-01: cascades escalated to Antigravity automatically, ~7.6M paid tokens over 9 runs, most of them
FAILED or blocked. A paid stage now needs `--escalate-to agy|claude` on that run; without it the local result is
held for the judge, who can fix it with a small apply, split the card, or pay knowingly.
"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from tests.test_u38_cost_gate_and_claude_worker import RemoteBudgetContractTests
from v7_harness.cli import main


class HeldEscalationTests(unittest.TestCase):
    def _run(self, *extra: str) -> tuple[list[str], dict]:
        calls: list[str] = []

        def fake_run(config):
            calls.append(config.agy_command[-1])
            return {"task_id": config.task_id, "state": "SUCCEEDED", "verdict_hint": "REWORK",
                    "agy_usage": {"input_tokens": 100, "output_tokens": 50}}

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "m.md").write_text(RemoteBudgetContractTests()._manual(
                root, work_id="H1", worker="cascade", remote_budget_tokens=120000), encoding="utf-8")
            out = io.StringIO()
            with mock.patch("v7_harness.pilot.run_pilot", fake_run), redirect_stdout(out), redirect_stderr(io.StringIO()):
                main(["pilot", "run", "--task", "H1", "--source", d, "--manual", str(root / "m.md"), *extra])
        return calls, json.loads(out.getvalue())

    def test_failed_local_run_is_held_without_a_named_paid_worker(self):
        calls, summary = self._run()
        self.assertEqual(1, len(calls))
        self.assertTrue(calls[0].endswith("ollama_worker.py"))
        self.assertEqual(["local:SEMANTIC", "held"], summary["route"])
        self.assertTrue(summary["escalation"].startswith("HELD:"), summary["escalation"])

    def test_named_paid_worker_still_escalates(self):
        calls, summary = self._run("--escalate-to", "agy")
        self.assertEqual(2, len(calls))
        self.assertEqual("agy", calls[1])
        self.assertEqual("remote:SEMANTIC", summary["route"][1])


if __name__ == "__main__":
    unittest.main()
