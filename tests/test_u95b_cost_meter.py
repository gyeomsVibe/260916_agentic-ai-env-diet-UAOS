"""U95-B: the cost meter reproduces per-call context, compactions and rewrites from fixed transcript fixtures."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from v7_harness.cost_meter import CLAUDE_WEIGHTS, claude_calls, codex_calls, main, summarize


def _claude_line(mid: str, read: int, write: int, out: int, ts: str) -> str:
    usage = {"cache_read_input_tokens": read, "cache_creation_input_tokens": write, "input_tokens": 2,
             "output_tokens": out}
    return json.dumps({"type": "assistant", "timestamp": ts, "message": {"id": mid, "usage": usage}})


def _codex_line(total: int, last_in: int, cached: int, out: int, pct: float, ts: str) -> str:
    usage = {"input_tokens": last_in, "cached_input_tokens": cached, "output_tokens": out}
    return json.dumps({"timestamp": ts, "type": "event_msg", "payload": {
        "type": "token_count", "info": {"total_token_usage": {"input_tokens": total}, "last_token_usage": usage},
        "rate_limits": {"primary": {"used_percent": pct, "window_minutes": 300}}}})


class CostMeterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, name: str, lines: list[str]) -> Path:
        path = self.dir / name
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_claude_counts_each_message_once_and_finds_the_compaction(self) -> None:
        path = self._write("c.jsonl", [
            _claude_line("m1", 100_000, 1_000, 500, "2026-09-30T01:00:00Z"),
            _claude_line("m1", 100_000, 1_000, 500, "2026-09-30T01:00:00Z"),  # same message, second block
            _claude_line("m2", 200_000, 1_000, 500, "2026-09-30T01:01:00Z"),
            json.dumps({"type": "user", "message": {"content": "tool result"}}),
            _claude_line("m3", 0, 80_000, 500, "2026-09-30T01:02:00Z"),  # after compaction: cache rewritten
            _claude_line("m4", 80_000, 2_000, 500, "2026-09-30T01:03:00Z"),
        ])
        report = summarize(claude_calls(path), CLAUDE_WEIGHTS)
        self.assertEqual(4, report["calls"])
        self.assertEqual(1, report["compactions"])
        self.assertEqual(80_002, report["floor_after_compaction"])
        self.assertEqual(1, report["cache_rewrites"])
        self.assertEqual(380_000, report["cache_read"])
        self.assertEqual(int(380_000 + 84_000 * 12.5 + 8 * 10 + 2_000 * 50), report["read_equivalent"])

    def test_claude_window_counts_one_card_only(self) -> None:
        path = self._write("c.jsonl", [
            _claude_line("m1", 10, 0, 1, "2026-09-30T01:00:00Z"),
            _claude_line("m2", 20, 0, 1, "2026-09-30T02:00:00Z"),
            _claude_line("m3", 30, 0, 1, "2026-09-30T03:00:00Z"),
        ])
        calls = claude_calls(path, since="2026-09-30T01:30:00Z", until="2026-09-30T02:30:00Z")
        self.assertEqual([22], [call["context"] for call in calls])

    def test_codex_skips_repeated_totals_and_reports_the_window(self) -> None:
        path = self._write("x.jsonl", [
            _codex_line(44_000, 44_000, 0, 300, 7.0, "2026-09-28T05:35:03Z"),
            _codex_line(44_000, 44_000, 0, 300, 7.0, "2026-09-28T05:35:04Z"),  # repeated, nothing spent
            _codex_line(88_500, 44_500, 43_900, 600, 8.0, "2026-09-28T05:35:19Z"),
        ])
        calls, window = codex_calls(path)
        self.assertEqual(2, len(calls))
        self.assertEqual(600, calls[1]["input"])
        self.assertEqual([7.0, 7.0, 8.0], window)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(0, main(["--codex", str(path)]))
        report = json.loads(out.getvalue())
        self.assertEqual([7.0, 8.0], report["window_5h_percent"])
        self.assertEqual(44_250, report["mean_context"])

    def test_empty_transcript_reports_zero_calls(self) -> None:
        path = self._write("e.jsonl", ["not json", json.dumps({"type": "user"})])
        self.assertEqual({"calls": 0}, summarize(claude_calls(path)))


if __name__ == "__main__":
    unittest.main()
