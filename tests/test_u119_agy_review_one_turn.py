"""U119-R: a headless Antigravity review is one turn on the real diff, so it fits its token cap.

Receipt (2026-10-01): two `pilot review --reviewer agy` runs on U118-A came back UNUSABLE over the cost gate
(69,219 tokens at a 30k cap, 395,104 at 100k). Measured cause: the review ran after `--approve`, so the source already
equalled the staged copy and the diff in the request was EMPTY; Antigravity then searched the files over many turns,
each re-reading its ~25k-token base context (floor measured: "Reply OK" = 25,012 tokens). The same request inlined
with "do not call any tool" and the real content took one turn: 28,008 tokens. So an empty diff is refused before
any paid call, and a diff that fits the command line goes inline with a no-tool instruction (the request file stays
as the audit copy; a PARTIAL diff keeps the file route because the reviewer must read the omitted part).
Fixed acceptance written by the judge (claude) first; no paid call.
"""

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness import review


class Done:
    def __init__(self, envelope):
        self.stdout = json.dumps(envelope).encode("utf-8")
        self.stderr = b""
        self.returncode = 0


class AgyReviewOneTurn(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.work, self.source, self.stage = root / "work", root / "src", root / "stage"
        self.runs = self.work / "runs" / "T1"
        for folder in (self.runs, self.source, self.stage):
            folder.mkdir(parents=True)
        (self.source / "a.py").write_text("X = 1\n", encoding="utf-8")
        (self.stage / "a.py").write_text("X = 2\n", encoding="utf-8")
        (self.runs / "worker").write_text("apply", encoding="utf-8")
        (self.runs / "summary.json").write_text(json.dumps(
            {"agy_workspace": str(self.stage), "changed_files": ["a.py"], "bundle_id": "b1"}), encoding="utf-8")
        self.calls = []
        self.kwargs = []

    def tearDown(self):
        self._tmp.cleanup()

    def run_agy(self, argv, **kwargs):
        self.calls.append(argv)
        self.kwargs.append(kwargs)
        return Done({"status": "SUCCESS", "conversation_id": "c", "usage": {"input_tokens": 1, "output_tokens": 1},
                     "response": '{"verdict": "PASS", "counterexamples": []}'})

    def review(self):
        return review.run_review(task_id="T1", work_dir=self.work, source=self.source, manual_text="contract",
                                 reviewer="agy", budget=40_000, runner=self.run_agy)

    def test_an_empty_diff_is_refused_before_any_paid_call(self):
        (self.source / "a.py").write_text("X = 2\n", encoding="utf-8")  # already applied
        with self.assertRaises(review.ReviewRefused) as caught:
            self.review()
        self.assertIn("EMPTY_DIFF", str(caught.exception))
        self.assertEqual([], self.calls)

    def test_a_fitting_diff_goes_inline_with_a_no_tool_instruction(self):
        self.assertEqual("PASS", self.review()["verdict"])
        prompt = self.calls[0][self.calls[0].index("-p") + 1]
        self.assertIn("+X = 2", prompt)
        self.assertIn("Do not call any tool", prompt)
        self.assertIn("already ran the acceptance command", prompt)
        self.assertTrue((self.runs / "review_agy_request.md").is_file())
        # U119-R2 live receipt: in the run folder agy ignored "no tool" (view_file 55, run_command 10 incl. the
        # acceptance unittest; 73,063 tokens). In an empty folder the same inline request took one turn (28,008).
        box = self.runs / "agy_box"
        self.assertEqual(str(box), self.kwargs[0]["cwd"])
        self.assertEqual([], list(box.iterdir()))
        self.assertLess(len(" ".join(self.calls[0])), 32_767)

    def test_a_diff_quoting_the_partial_phrase_still_goes_inline(self):
        # U119-R3 live receipt: the R2 diff contained the literal 'The diff below is PARTIAL' and fell back to the
        # file route (5 steps, 55,062 tokens). Only the prompt's own leading sentence may decide.
        (self.stage / "a.py").write_text('MARK = "The diff below is PARTIAL"\n', encoding="utf-8")
        self.review()
        prompt = self.calls[0][self.calls[0].index("-p") + 1]
        self.assertIn("Do not call any tool", prompt)

    def test_a_partial_diff_keeps_the_file_route(self):
        (self.stage / "a.py").write_text("".join(f"Y{i} = {i}\n" for i in range(9000)), encoding="utf-8")
        self.review()
        prompt = self.calls[0][self.calls[0].index("-p") + 1]
        self.assertIn("review_agy_request.md", prompt)
        self.assertNotIn("Do not call any tool", prompt)


if __name__ == "__main__":
    unittest.main()
