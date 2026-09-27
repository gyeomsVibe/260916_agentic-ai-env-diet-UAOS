"""U52: tool-output token gate (docs/49 §5 U-TOK-1)."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from v7_harness import judge
from v7_harness.output_gate import gate_output
from v7_harness.review import MAX_DIFF_CHARS, review_prompt


class GateOutputTest(unittest.TestCase):
    def test_short_text_passes_unchanged(self) -> None:
        result = gate_output("ok\n", 100)
        self.assertEqual(result.text, "ok\n")
        self.assertFalse(result.truncated)

    def test_long_text_keeps_head_and_tail_and_marks_the_cut(self) -> None:
        text = "HEAD" + "x" * 10_000 + "TAIL"
        result = gate_output(text, 1000)
        self.assertTrue(result.truncated)
        self.assertTrue(result.text.startswith("HEAD"))
        self.assertTrue(result.text.endswith("TAIL"))
        self.assertIn("U52 OUTPUT CUT", result.text)
        self.assertIn(hashlib.sha256(text.encode()).hexdigest()[:12], result.text)
        self.assertEqual(result.original_chars, len(text))

    def test_codex_counterexample_total_stays_within_the_cap(self) -> None:
        # Red on U52-S1b: gate_output('x'*10000, 1000) returned 1096 characters.
        self.assertLessEqual(len(gate_output("x" * 10_000, 1000).text), 1000)

    def test_cap_holds_for_every_size_including_caps_smaller_than_the_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spill = Path(tmp) / "a-long-spill-folder-name" / "full.log"
            for cap in (1, 5, 50, 100, 130, 200, 500, 1000, 4000):
                for size in (cap + 1, cap * 2, cap * 10 + 7, 123_457):
                    for path in (None, spill):
                        result = gate_output("y" * size, cap, path)
                        self.assertLessEqual(len(result.text), cap, (cap, size, path))
                        self.assertTrue(result.truncated)

    def test_spill_file_holds_the_full_text(self) -> None:
        text = "a" * 5000
        with tempfile.TemporaryDirectory() as tmp:
            spill = Path(tmp) / "sub" / "full.log"
            result = gate_output(text, 400, spill)
            self.assertEqual(spill.read_text(encoding="utf-8"), text)
            self.assertIn(str(spill), result.text)

    def test_same_input_gives_same_output(self) -> None:
        text = "line\n" * 3000
        self.assertEqual(gate_output(text, 500).text, gate_output(text, 500).text)

    def test_non_positive_cap_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            gate_output("x", 0)


class ReviewPromptTest(unittest.TestCase):
    def test_small_diff_is_called_complete(self) -> None:
        prompt = review_prompt("T1", "contract", "+one line\n")
        self.assertIn("complete change", prompt)
        self.assertNotIn("PARTIAL", prompt)

    def test_oversized_diff_is_called_partial_keeps_its_tail_and_the_cap(self) -> None:
        diff = "+head\n" + "+x\n" * (MAX_DIFF_CHARS // 2) + "+LAST_HUNK\n"
        with tempfile.TemporaryDirectory() as tmp:
            prompt = review_prompt("T1", "contract", diff, Path(tmp) / "review.diff")
            self.assertIn("PARTIAL", prompt)
            self.assertNotIn("complete change", prompt)
            self.assertIn("+LAST_HUNK", prompt)  # the old diff[:MAX] cut dropped this silently
            self.assertEqual((Path(tmp) / "review.diff").read_text(encoding="utf-8"), diff)
            shown = prompt.split("```diff\n", 1)[1].rsplit("\n```", 1)[0]
            self.assertLessEqual(len(shown), MAX_DIFF_CHARS)


MANUAL = """```contract
work_id: T1
worker: apply
goal: g
allow:
- a.py
acceptance: python -c "pass"
judge: antigravity
remote_budget_tokens: 0
```
"""


class JudgeRequestTest(unittest.TestCase):
    """Production caller: the acceptance log a paid judge reads. Red on U52-S1b, which kept only log[-4000:]: the first
    failure at the head of a long log vanished without a mark."""

    def test_paid_judge_request_keeps_head_tail_and_the_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work, source, stage = root / "work", root / "src", root / "stage"
            runs = work / "runs" / "T1"
            for folder in (runs, source, stage):
                folder.mkdir(parents=True)
            (source / "a.py").write_text("X = 1\n", encoding="utf-8")
            (stage / "a.py").write_text("X = 2\n", encoding="utf-8")
            (runs / "worker").write_text("claude", encoding="utf-8")
            log = runs / "acceptance.log"
            log.write_text("FIRST_FAILURE in test_a\n" + "noise line\n" * 2000 + "LAST_LINE FAILED (failures=1)\n",
                           encoding="utf-8")
            (runs / "summary.json").write_text(json.dumps(
                {"agy_workspace": str(stage), "changed_files": ["a.py"], "bundle_id": "b1",
                 "promotion": "DRY_RUN_PASSED", "acceptance_exit": 0, "acceptance_log_path": str(log)}),
                encoding="utf-8")
            manual = root / "m.md"
            manual.write_text(MANUAL, encoding="utf-8")

            def runner(argv, **kwargs):
                class Done:
                    stdout, stderr, returncode = b"{}", b"", 1
                return Done()

            judge.run_judge(task_id="T1", work_dir=work, source=source, manual_path=manual, budget=10_000,
                            runner=runner, approver=lambda *a, **k: None, desk={"codex": {"state": "ABSENT"}})
            request = (runs / "judge_agy_request.md").read_text(encoding="utf-8")
            shown = request.split("last lines)\n```\n", 1)[1].split("\n```", 1)[0]
            self.assertIn("FIRST_FAILURE", shown)
            self.assertIn("LAST_LINE", shown)
            self.assertIn("U52 OUTPUT CUT", shown)
            self.assertLessEqual(len(shown), judge.ACCEPTANCE_TAIL_CHARS)


if __name__ == "__main__":
    unittest.main()
