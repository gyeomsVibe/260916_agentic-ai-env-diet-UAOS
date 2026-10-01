"""U69: a paid call whose contract is below the observed floor is refused before it spends.

The numbers are the project's real ledger: the cheapest complete Claude review (U44-FIX5) counted 124,769 tokens and
$0.133923, and U67-C1 ran a review under a 12,000-token contract that then spent 485,172 tokens and $0.43.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from v7_harness.admission import admit, observed_floor
from v7_harness.cli import main
from v7_harness.manual import new_manual
from v7_harness.review import ReviewRefused, run_review

REVIEW_FIX5 = {"worker": "claude", "kind": "review", "input_tokens": 10, "output_tokens": 1897,
               "cache_creation_input_tokens": 23779, "cache_read_input_tokens": 99083, "cost_microusd": 133923}
REVIEW_FIX = {"worker": "claude", "kind": "review", "input_tokens": 20, "output_tokens": 8191,
              "cache_creation_input_tokens": 72346, "cache_read_input_tokens": 497581, "cost_microusd": 470850}
FLOOR_TOKENS = 124769


def _ledger(root: Path, *rows: dict) -> None:
    usage = root / ".coord" / "usage"
    usage.mkdir(parents=True, exist_ok=True)
    (usage / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows) + "{not json\n", encoding="utf-8")


class FloorTests(unittest.TestCase):
    def test_floor_is_the_cheapest_complete_row_of_that_worker_and_kind(self) -> None:
        rows = [REVIEW_FIX, REVIEW_FIX5,
                # Incomplete or foreign rows would pull the floor under any real call; they do not count.
                {**REVIEW_FIX5, "cache_read_input_tokens": None, "input_tokens": 1},
                {k: v for k, v in REVIEW_FIX5.items() if k != "cache_creation_input_tokens"},
                {**REVIEW_FIX5, "output_tokens": True},
                {**REVIEW_FIX5, "kind": "pilot", "cache_read_input_tokens": 0},
                {**REVIEW_FIX5, "worker": "agy", "cache_read_input_tokens": 0}]
        self.assertEqual({"tokens": FLOOR_TOKENS, "microusd": 133923, "samples": 2},
                         observed_floor(rows, "claude", "review"))
        self.assertIsNone(observed_floor(rows, "claude", "judge"))

    def test_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertEqual("ADMIT_UNMEASURED", admit(root, worker="claude", kind="review", budget_tokens=1)["decision"])
            _ledger(root, REVIEW_FIX, {**REVIEW_FIX5, "wall_time_s": 95.4})
            refused = admit(root, worker="claude", kind="review", budget_tokens=12000, budget_usd=0.05, timeout_s=60)
            self.assertEqual("REFUSE", refused["decision"])
            self.assertEqual([f"BUDGET_BELOW_FLOOR:tokens:12000<{FLOOR_TOKENS}", "BUDGET_BELOW_FLOOR:usd:0.05<0.133923",
                              "BUDGET_BELOW_FLOOR:seconds:60<95"], refused["reasons"])
            # Exactly the floor fits: the floor is a call that really happened within that spend.
            self.assertEqual("ADMIT", admit(root, worker="claude", kind="review", budget_tokens=FLOOR_TOKENS,
                                            budget_usd=0.133923, timeout_s=95)["decision"])
            # A zero dollar or time budget means "not set" (agy has no dollar cap), not "below the floor".
            self.assertEqual("ADMIT", admit(root, worker="claude", kind="review", budget_tokens=200000)["decision"])


class PilotRunAdmissionTests(unittest.TestCase):
    def _manual(self, root: Path, budget: int) -> Path:
        (root / "pkg").mkdir(exist_ok=True)
        (root / "pkg" / "config.py").write_text("TIMEOUT = 30\n", encoding="utf-8")
        path = root / "m.md"
        path.write_text(new_manual(root, work_id="U69_T", worker="agy", goal="Set TIMEOUT = 60 in `pkg/config.py`.",
                                   inputs=["pkg/config.py"], allow=["pkg/config.py"],
                                   acceptance="python -c \"import pkg.config\"", judge="codex",
                                   remote_budget_tokens=budget,
                                   # U106: a paid worker on code needs a recorded reason; this fixture tests admission.
                                   paid_reason="fixture exercises the admission gate"), encoding="utf-8")
        return path

    def _run(self, root: Path, *extra: str) -> tuple[int, str, mock.MagicMock]:
        out = io.StringIO()
        with mock.patch("v7_harness.pilot.run_pilot", return_value={"state": "SUCCEEDED", "verdict_hint": "PASS"}) as run, \
                mock.patch("v7_harness.cli.detect_actor", return_value="codex"), \
                redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = main(["pilot", "run", "--task", "U69_T", "--source", str(root), "--manual", str(self._manual(root, 12000)),
                         *extra])
        return code, out.getvalue(), run

    def test_a_budget_below_the_floor_never_starts_the_worker(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _ledger(root, {**REVIEW_FIX5, "worker": "agy", "kind": "pilot"})
            code, out, run = self._run(root)
            self.assertEqual(2, code)
            run.assert_not_called()
            report = json.loads(out)
            self.assertEqual(("ADMISSION_REFUSED", [f"BUDGET_BELOW_FLOOR:tokens:12000<{FLOOR_TOKENS}"]),
                             (report["error_class"], report["admission"]["reasons"]))

    def test_a_budget_at_or_above_the_floor_and_an_approval_replay_run(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _ledger(root, {**REVIEW_FIX5, "worker": "agy", "kind": "pilot", "cache_read_input_tokens": 0})
            code, _, run = self._run(root)  # floor 25,686 without cache reads, still above 12,000
            self.assertEqual(2, code)
            run.assert_not_called()
            _ledger(root, {"worker": "agy", "kind": "pilot", "input_tokens": 3000, "output_tokens": 500,
                           "cache_creation_input_tokens": 0, "cache_read_input_tokens": 4000})
            code, _, run = self._run(root)
            run.assert_called_once()
            # --approve replays a saved bundle and spends nothing, so it is not admitted again.
            _ledger(root, {**REVIEW_FIX5, "worker": "agy", "kind": "pilot"})
            code, _, run = self._run(root, "--approve", "b" * 64)
            run.assert_called_once()


class ReviewAdmissionTests(unittest.TestCase):
    def test_the_u67_c1_review_is_refused_before_the_call(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source, staging, runs = root / "src", root / "stage", root / "work" / "runs" / "U69_R"
            for folder in (source, staging, runs):
                folder.mkdir(parents=True)
            (source / "a.py").write_text("x = 1\n", encoding="utf-8")
            (staging / "a.py").write_text("x = 2\n", encoding="utf-8")
            (runs / "summary.json").write_text(json.dumps({"agy_workspace": str(staging), "changed_files": ["a.py"]}),
                                               encoding="utf-8")
            (runs / "worker").write_text("agy", encoding="utf-8")
            _ledger(source, REVIEW_FIX5)
            runner = mock.Mock(side_effect=AssertionError("the paid reviewer must not start"))
            with self.assertRaises(ReviewRefused) as caught:
                run_review(task_id="U69_R", work_dir=root / "work", source=source, manual_text="m", reviewer="claude",
                           budget=12000, budget_usd=0.5, runner=runner)
            self.assertEqual(f"ADMISSION_REFUSED:BUDGET_BELOW_FLOOR:tokens:12000<{FLOOR_TOKENS}", str(caught.exception))
            runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
