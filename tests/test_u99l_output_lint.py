"""U99-L: measure the language of Claude's user-visible text from a transcript, 0 model tokens (MIA success signal S3).

Receipt (윤겸스, several times up to 2026-09-30): English progress lines between tool calls. Canon v7.2.0 added rule
text, but U99 decided rules that matter need a measurement or a gate (H1). This counter gives a baseline first.
Fixed acceptance written by the judge (claude) before the code; the code is delegated to Ollama.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.output_lint import lint_text, lint_transcript


class LintTextTests(unittest.TestCase):
    def test_korean_and_english_prose_lines(self) -> None:
        result = lint_text("결과는 정상입니다\nThe run is still going on here\n")
        self.assertEqual({"lines": 2, "korean": 1, "english": 1}, result)

    def test_code_fences_and_blank_lines_are_skipped(self) -> None:
        text = "```bash\nprint('hello world from code')\n```\n\n   \n요약입니다"
        self.assertEqual({"lines": 1, "korean": 1, "english": 0}, lint_text(text))

    def test_korean_line_with_english_terms_counts_as_korean(self) -> None:
        self.assertEqual({"lines": 1, "korean": 1, "english": 0}, lint_text("캐시(cache) read tokens are high"))

    def test_short_or_symbol_lines_are_neither(self) -> None:
        self.assertEqual({"lines": 3, "korean": 0, "english": 0}, lint_text("OK\n- `a/b.py:12`\nPR #74"))


class LintTranscriptTests(unittest.TestCase):
    def test_only_assistant_text_blocks_count(self) -> None:
        rows = [
            {"type": "user", "message": {"role": "user", "content": "Please do this in English words"}},
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "진행 중입니다"},
                {"type": "tool_use", "name": "Bash", "input": {"command": "echo this is a long command"}},
                {"type": "text", "text": "Now I will run the full tests"},
            ]}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "결과: 통과"}]}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.jsonl"
            path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\nnot json\n",
                            encoding="utf-8")
            result = lint_transcript(path)
        self.assertEqual(2, result["messages"])
        self.assertEqual(3, result["lines"])
        self.assertEqual(2, result["korean"])
        self.assertEqual(1, result["english"])
        self.assertAlmostEqual(1 / 3, result["english_share"], places=3)

    def test_synthetic_rows_are_not_claude_text(self) -> None:
        # Receipt U99-L2 baseline: 2 of 3 "English" lines in session 1c575909 were the client's
        # "You've hit your session limit" notice, stored as an assistant row with model <synthetic>.
        rows = [
            {"type": "assistant", "isApiErrorMessage": True,
             "message": {"model": "<synthetic>", "content": [{"type": "text", "text": "You have hit your session limit today"}]}},
            {"type": "assistant", "message": {"model": "<synthetic>", "content": [{"type": "text", "text": "No response was requested here at all"}]}},
            {"type": "assistant", "message": {"model": "claude-opus-5-5", "content": [{"type": "text", "text": "결과: 통과"}]}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.jsonl"
            path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
            result = lint_transcript(path)
        self.assertEqual({"messages": 1, "lines": 1, "korean": 1, "english": 0}, {k: result[k] for k in ("messages", "lines", "korean", "english")})

    def test_missing_file_gives_zero_counts(self) -> None:
        result = lint_transcript(Path("no/such/transcript.jsonl"))
        self.assertEqual(0, result["messages"])
        self.assertEqual(0.0, result["english_share"])


if __name__ == "__main__":
    unittest.main()
