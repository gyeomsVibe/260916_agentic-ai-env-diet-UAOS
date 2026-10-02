"""U21 계산기 원칙: --worker auto 배정과 커밋 관문."""

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from v7_harness import cli
from v7_harness.calculator_gate import check


class AutoRoutingTest(unittest.TestCase):
    def _run(self, prompt, verdicts):
        calls, out = [], StringIO()

        def fake_run(config):
            calls.append((config.task_id, config.agy_command[-1]))
            return {"task_id": config.task_id, "state": "SUCCEEDED", "verdict_hint": verdicts[len(calls) - 1]}

        with mock.patch("v7_harness.pilot.run_pilot", fake_run), redirect_stdout(out):
            cli.main([
                "pilot", "run", "--task", "A1", "--source", ".", "--prompt", prompt,
                "--worker", "auto", "--work-dir", ".work/_auto_test",
            ])
        s = out.getvalue()
        return calls, json.loads(s[s.index("{"):])

    def _run_err(self, err, escalate_to="lane"):
        calls = []

        def fake_run(config):
            calls.append(config.task_id)
            if len(calls) == 1:
                return {"task_id": config.task_id, "state": "FAILED", "verdict_hint": "BLOCKED", "error_class": err}
            return {"task_id": config.task_id, "state": "SUCCEEDED", "verdict_hint": "PASS"}

        with mock.patch("v7_harness.pilot.run_pilot", fake_run), redirect_stdout(StringIO()):
            cli.main([
                "pilot", "run", "--task", "E1", "--source", ".", "--prompt", "x",
                "--worker", "cascade", "--work-dir", ".work/_auto_test", "--escalate-to", escalate_to,
            ])
        return calls

    def test_specific_prompt_goes_local_then_agy(self):
        specific = (
            "Edit only `v7_harness/adapters/ollama_worker.py`, function `_apply`. Rename the variable `body` to `text`. "
            "Do not change anything else."
        )
        calls, s = self._run(specific, ["REWORK", "PASS"])
        self.assertTrue(calls[0][1].endswith("ollama_worker.py"))
        # B85 rework: the paid second stage needs a manual; without one the escalation is refused, not run.
        self.assertEqual(1, len(calls))
        self.assertEqual("REFUSED:REMOTE_WITHOUT_MANUAL", s["escalation"])
        self.assertEqual(s["routed_by"]["worker"], "cascade")
        self.assertTrue(s["routed_by"]["specificity"] >= 60)

    def test_vague_prompt_goes_agy(self):
        vague = "코드를 적절히 개선해줘"
        calls, s = self._run(vague, ["PASS"])
        # Routed to agy, and refused before any call because a paid worker needs a manual (B85 rework).
        self.assertEqual(calls, [])
        self.assertEqual(("REMOTE_WITHOUT_MANUAL", "agy"), (s["error_class"], s["worker"]))

    def test_local_failure_escalates(self):
        # A worker failure still moves on once (U39); to the local-model lane here, since a paid stage needs a manual.
        for err in ("PROVIDER_ERROR", "TIMEOUT", "EXECUTION_ERROR"):
            self.assertEqual(self._run_err(err), ["E1", "E1-lane"])
            self.assertEqual(self._run_err(err, escalate_to="agy"), ["E1"])

    def test_other_blocked_does_not_escalate(self):
        for err in ("SOURCE_DIVERGED", "EXTERNAL_WRITE", "ACCEPT_INFRA", "ACCEPT_NOT_RUN"):
            self.assertEqual(self._run_err(err), ["E1"])


class CalculatorGateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pd = Path(self._tmp.name)
        self._make_run("T1", "APPLIED", {"v7_harness/x.py": b"A = 1\n"})
        self._make_run("T2", "DRY_RUN_PASSED", {"v7_harness/y.py": b"B = 1\n"})

    def tearDown(self):
        self._tmp.cleanup()

    def _make_run(self, task, promotion, files):
        (self.pd / "runs" / task).mkdir(parents=True, exist_ok=True)
        (self.pd / "runs" / task / "summary.json").write_text(
            json.dumps({"promotion": promotion, "bundle_id": "b" * 64, "changed_files": list(files)}),
            encoding="utf-8",
        )
        # U123: a bundle counts only with an independent PASS for the same bundle by an Ollama author.
        (self.pd / "runs" / task / "review_agy.json").write_text(
            json.dumps({"verdict": "PASS", "bundle_id": "b" * 64, "author_worker": "ollama"}), encoding="utf-8")
        for p, body in files.items():
            f = self.pd / "stage" / task / p
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(body)

    def test_crlf_matches_lf(self):
        self.assertEqual(check({"v7_harness/x.py": b"A = 1\r\n"}, "feat: x", self.pd), [])

    def test_content_mismatch_violates(self):
        v = check({"v7_harness/x.py": b"A = 2\n"}, "feat: x", self.pd)
        self.assertEqual(len(v), 1)
        self.assertTrue("v7_harness/x.py" in v[0])

    def test_only_applied_bundles_count(self):
        self.assertEqual(len(check({"v7_harness/y.py": b"B = 1\n"}, "feat: y", self.pd)), 1)

    def test_unapplied_new_file_violates(self):
        self.assertEqual(len(check({"v7_harness/new.py": b"C\n"}, "feat", self.pd)), 1)

    def test_calculator_exempt_reason_no_longer_passes(self):
        # U123 (윤겸스 2026-10-02): the exemption line skipped the audit/Ollama/review order; it no longer covers code.
        self.assertEqual(
            len(check({"v7_harness/x.py": b"A = 2\n"}, "fix\n\nCalculator-Exempt: pilot down, see PLAN\n", self.pd)),
            1,
        )

    def test_calculator_exempt_empty_reason_fails(self):
        self.assertEqual(
            len(check({"v7_harness/x.py": b"A = 2\n"}, "fix\n\nCalculator-Exempt:   \n", self.pd)),
            1,
        )

    def test_non_gated_files_pass(self):
        self.assertEqual(
            check({"tests/test_a.py": b"x\n", "docs/a.md": b"y\n", "v7_harness/README.md": b"z\n"}, "docs", self.pd),
            [],
        )

    def test_empty_staged_passes(self):
        self.assertEqual(check({}, "empty", self.pd), [])


if __name__ == "__main__":
    unittest.main()
