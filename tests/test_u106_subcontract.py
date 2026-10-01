"""U106-A2: the commander picks the fitting worker, and Antigravity subcontracts to Ollama when it is picked.

Receipt (윤겸스, 2026-10-01): "너와 코덱스가 해당 프로세스 작업에 올라마, 안티그래비티 중 알맞은 도구 선택 할 수 있게 하고,
안티그래비티를 선택해서 프로세스를 수행할 때 재하청 주듯이 안티그래비티가 올라마를 사용하여 작업을 하게 … 올라마를 수족처럼
자유롭게 쓰는 로직은 그대로". Facts (~/.cache/olla/usage.jsonl, 2026-10-01): the headless Antigravity runs U105-A1
(604,187 tokens) and U106-R (661,672 tokens) logged only hook events (hint_plan, turn_shape) and zero olla tool calls
(digest/ask/find), although the olla MCP tools are registered and allowed for the CLI (`mcp(olla/*)`); in the desktop
window the same account called them 58 times. The tools were there; the headless prompt never asked for them.
Rules fixed here:
- `build_agy_command` puts a short subcontract preamble before the task when `AgyRequest.subcontract` is true
  (default false, so review/judge callers and the non-agy workers that reuse the builder are unchanged);
  `pilot run` sets it only for the real agy binary.
- `count_olla_calls` counts olla work events per caller inside a run's time window; pilot writes it to
  `<runs_dir>/olla_calls.json` so each Antigravity run shows whether it subcontracted.
- A paid worker on code work passes lint with either `paid_after` (a failed local run) or `paid_reason` (the
  commander's recorded reason, at least 3 words): the commander chooses by fit, but never silently.
- `pilot run` defaults to `--worker auto`; `pilot manual new` writes `--paid-after` / `--paid-reason`.
Written by the judge (claude) before the implementation; the worker must not edit it.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.adapters.agy import AgyRequest, OLLA_SUBCONTRACT, OLLA_WORK_EVENTS, build_agy_command, count_olla_calls
from v7_harness.manual import lint

SPEC = b"sample spec\n"
SPEC_SHA = hashlib.sha256(SPEC).hexdigest()


def request(**extra: object) -> AgyRequest:
    return AgyRequest(task_id="T7", title="sample", prompt="do the task", workspace=Path("."),
                      isolation_mode="staging", **extra)


class SubcontractPreambleTests(unittest.TestCase):
    def test_preamble_names_the_three_olla_tools(self) -> None:
        for tool in ("local_read_map", "local_draft", "local_search"):
            self.assertIn(tool, OLLA_SUBCONTRACT)

    def test_preamble_is_short_fixed_context(self) -> None:
        # Every paid call re-reads the prompt; the preamble must stay a few lines (U106 frame H5).
        self.assertLess(len(OLLA_SUBCONTRACT), 1200)

    def test_subcontract_request_puts_preamble_before_the_task(self) -> None:
        prompt = build_agy_command(request(subcontract=True))[2]
        self.assertIn(OLLA_SUBCONTRACT, prompt)
        self.assertTrue(prompt.startswith("[T7] sample\n"), prompt[:40])
        self.assertLess(prompt.index(OLLA_SUBCONTRACT), prompt.index("do the task"))

    def test_default_request_is_unchanged(self) -> None:
        self.assertEqual("[T7] sample\ndo the task", build_agy_command(request())[2])


class OllaCountTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / "usage.jsonl"
        rows = [
            {"ts": "2026-10-01T10:00:00", "event": "digest", "caller": "antigravity"},
            {"ts": "2026-10-01T10:05:00", "event": "ask", "caller": "antigravity"},
            {"ts": "2026-10-01T10:06:00", "event": "find", "caller": "unknown"},
            {"ts": "2026-10-01T10:07:00", "event": "hint_plan", "caller": "antigravity"},
            {"ts": "2026-10-01T10:08:00", "event": "digest_prewarm", "caller": "antigravity"},
            {"ts": "2026-10-01T09:59:59", "event": "digest", "caller": "antigravity"},
            {"ts": "2026-10-01T11:00:01", "event": "ask", "caller": "claude"},
        ]
        self.log.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_counts_work_events_per_caller_inside_the_window(self) -> None:
        counts = count_olla_calls(self.log, "2026-10-01T10:00:00", "2026-10-01T11:00:00")
        self.assertEqual({"antigravity": {"digest": 1, "ask": 1}, "unknown": {"find": 1}}, counts)

    def test_hook_and_prewarm_events_are_not_work(self) -> None:
        self.assertEqual(frozenset({"digest", "ask", "find", "edit"}), OLLA_WORK_EVENTS)

    def test_missing_log_is_empty(self) -> None:
        self.assertEqual({}, count_olla_calls(Path(self.tmp.name) / "none.jsonl", "2026-10-01T00:00:00",
                                              "2026-10-02T00:00:00"))


def manual(extra: str = "") -> str:
    return (
        "```contract\n"
        "work_id: T7-A1\n"
        "worker: agy\n"
        "goal: add a sample constant for the paid-reason gate test\n"
        "inputs:\n"
        f"- spec.md sha256={SPEC_SHA}\n"
        "allow:\n"
        "- v7_harness/sample.py\n"
        "acceptance: python -m unittest tests.test_sample\n"
        "forbidden: edits outside allow\n"
        "stop: two failures with the same cause\n"
        "judge: claude\n"
        "timeout_s: 60\n"
        "remote_budget_tokens: 500000\n"
        "remote_budget_usd: 1\n"
        f"{extra}"
        "```\n\n"
        "## Instructions for the worker\n\n"
        "1. In `v7_harness/sample.py` add `LIMIT = 3` must be an int.\n"
    )


class PaidReasonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        (self.project / "spec.md").write_bytes(SPEC)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _local_first(self, text: str) -> list[str]:
        return [e for e in lint(text, self.project).errors if e.startswith("LOCAL_FIRST")]

    def test_a_recorded_reason_lets_the_commander_pick_the_paid_worker(self) -> None:
        self.assertEqual([], self._local_first(manual("paid_reason: needs reasoning across five modules\n")))

    def test_a_placeholder_reason_is_refused(self) -> None:
        for reason in ("", "x", "because fast"):
            self.assertTrue(self._local_first(manual(f"paid_reason: {reason}\n")), reason)

    def test_error_names_both_ways_out(self) -> None:
        errors = self._local_first(manual())
        self.assertTrue(errors and "paid_after" in errors[0] and "paid_reason" in errors[0], errors)


class CliTests(unittest.TestCase):
    def test_pilot_run_defaults_to_auto(self) -> None:
        from v7_harness.cli import build_parser

        args = build_parser().parse_args(["pilot", "run", "--task", "T7", "--source", ".", "--prompt", "x"])
        self.assertEqual("auto", args.worker)

    def test_manual_new_writes_paid_after_and_paid_reason(self) -> None:
        from v7_harness.cli import main

        with tempfile.TemporaryDirectory() as temp:
            for flag, value, line in (("--paid-after", "T7-L1", "paid_after: T7-L1"),
                                      ("--paid-reason", "needs reasoning across five modules",
                                       "paid_reason: needs reasoning across five modules")):
                out = Path(temp) / f"m{flag}.md"
                code = main(["pilot", "manual", "new", "--out", str(out), "--source", temp, "--work-id", "T7-A2",
                             "--worker", "agy", "--goal", "sample", "--allow", "v7_harness/sample.py",
                             "--accept", "python -m unittest tests.test_sample", "--judge", "claude",
                             "--remote-budget", "500000", flag, value])
                self.assertIn(code, (0, 1))  # 1 = written, lint may still object (no ledger row here)
                self.assertIn(line, out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
