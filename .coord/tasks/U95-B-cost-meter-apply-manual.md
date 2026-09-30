```contract
work_id: U95-B
worker: apply
goal: Add a deterministic cost meter that reads a Claude Code or Codex transcript and reports calls, context per call, compactions, cache rewrites, read-equivalent cost and Codex 5-hour window use, so U95 levers are judged by measurement.
inputs:
- .coord/PLAN.md sha256=2a0edb6d723dcd14515716cc5304d383f10072d501d50a49c42284d7712378b6
allow:
- v7_harness/cost_meter.py
- tests/test_u95b_cost_meter.py
- .coord/PLAN.md
acceptance: python -m unittest tests.test_u95b_cost_meter
forbidden: design changes; edits outside allow; weakening or deleting existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the EDIT and FILE blocks exactly.

Receipt (2026-09-30, U95 frame): the token-thrift success signal needs read-equivalent tokens per card, but the only
numbers so far came from one-off scripts in chat. Measured with those scripts: Claude re-reads 137k–147k tokens per
call; Codex long sessions 139k–141k per call, and one Codex session of 306 calls used 18% of its 5-hour window.

===FILE: v7_harness/cost_meter.py===
"""U95-B: measure what a Claude Code or Codex session paid, per call, from the tool's own transcript (0 tokens).

Seen 2026-09-30: both tools re-read about 140k tokens of context on every paid call, and the 5-hour window ran out
inside one conversation. The U95 levers (fewer calls, a smaller context floor, earlier compaction, fewer cache
rewrites) are judged by this meter on the same card before and after, never by a claim.

Usage: python -m v7_harness.cost_meter (--claude PATH | --codex PATH) [--since ISO] [--until ISO]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

# Read-equivalent weights: Anthropic list prices per million tokens for Opus-class models (input 5, cache write 6.25,
# cache read 0.50, output 25 USD), divided by the cache-read price. How plan limits weigh them is UNKNOWN (U95 frame).
CLAUDE_WEIGHTS = {"cache_read": 1.0, "cache_write": 12.5, "input": 10.0, "output": 50.0}
# A call whose context is below 60% of the previous one followed a compaction (observed drops: 215k to 72-86k).
COMPACTION_RATIO = 0.6
# A cache write above 20k tokens is a rewrite (compaction or expired cache), not the turn's own delta (1-10k).
REWRITE_TOKENS = 20_000


def _lines(path: Path) -> Iterable[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                yield data


def _in_window(stamp: str, since: str | None, until: str | None) -> bool:
    # ISO-8601 UTC stamps from one writer sort as text; both tools write "YYYY-MM-DDTHH:MM:SS(.fff)Z".
    return (not since or stamp >= since) and (not until or stamp <= until)


def claude_calls(path: Path, since: str | None = None, until: str | None = None) -> list[dict[str, int]]:
    """One row per paid call. Claude Code writes one line per content block with the same message id and usage,
    so a message id counts once; a row without usage (tool results, summaries) is not a call."""
    seen: set[str] = set()
    calls: list[dict[str, int]] = []
    for data in _lines(path):
        message = data.get("message")
        if data.get("type") != "assistant" or not isinstance(message, dict):
            continue
        usage = message.get("usage")
        key = str(message.get("id") or "")
        if not isinstance(usage, dict) or not key or key in seen:
            continue
        if not _in_window(str(data.get("timestamp") or ""), since, until):
            continue
        seen.add(key)
        row = {"cache_read": int(usage.get("cache_read_input_tokens") or 0),
               "cache_write": int(usage.get("cache_creation_input_tokens") or 0),
               "input": int(usage.get("input_tokens") or 0),
               "output": int(usage.get("output_tokens") or 0)}
        row["context"] = row["cache_read"] + row["cache_write"] + row["input"]
        if row["context"]:
            calls.append(row)
    return calls


def codex_calls(path: Path, since: str | None = None, until: str | None = None) -> tuple[list[dict[str, int]], list[float]]:
    """Calls from Codex token_count events, plus the 5-hour window percentages seen. Codex repeats an event when
    nothing was spent, so an unchanged running total is skipped; input_tokens already includes the cached part."""
    calls: list[dict[str, int]] = []
    window: list[float] = []
    previous: Any = None
    for data in _lines(path):
        payload = data.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "token_count":
            continue
        if not _in_window(str(data.get("timestamp") or ""), since, until):
            continue
        info = payload.get("info") or {}
        total = info.get("total_token_usage")
        last = info.get("last_token_usage")
        primary = (payload.get("rate_limits") or {}).get("primary") or {}
        if isinstance(primary.get("used_percent"), (int, float)):
            window.append(float(primary["used_percent"]))
        if not isinstance(last, dict) or total == previous:
            continue
        previous = total
        cached = int(last.get("cached_input_tokens") or 0)
        context = int(last.get("input_tokens") or 0)
        calls.append({"cache_read": cached, "cache_write": int(last.get("cache_write_input_tokens") or 0),
                      "input": context - cached, "output": int(last.get("output_tokens") or 0), "context": context})
    return calls, window


def summarize(calls: list[dict[str, int]], weights: dict[str, float] | None = None) -> dict[str, Any]:
    if not calls:
        return {"calls": 0}
    contexts = [call["context"] for call in calls]
    after = [contexts[i] for i in range(1, len(contexts)) if contexts[i] < contexts[i - 1] * COMPACTION_RATIO]
    report: dict[str, Any] = {
        "calls": len(calls),
        "mean_context": sum(contexts) // len(contexts),
        "max_context": max(contexts),
        "compactions": len(after),
        "floor_after_compaction": min(after) if after else None,
        "cache_rewrites": sum(1 for call in calls if call["cache_write"] > REWRITE_TOKENS),
    }
    for key in ("cache_read", "cache_write", "input", "output"):
        report[key] = sum(call[key] for call in calls)
    if weights:
        report["read_equivalent"] = int(sum(report[key] * weight for key, weight in weights.items()))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cost_meter", description="Per-call cost of one Claude Code or Codex session")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--claude", type=Path, help="Claude Code transcript (~/.claude/projects/<dir>/<id>.jsonl)")
    source.add_argument("--codex", type=Path, help="Codex rollout (~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl)")
    parser.add_argument("--since", help="first ISO timestamp to count, for one card inside a longer session")
    parser.add_argument("--until", help="last ISO timestamp to count")
    args = parser.parse_args(argv)
    if args.claude:
        report = {"tool": "claude", **summarize(claude_calls(args.claude, args.since, args.until), CLAUDE_WEIGHTS)}
    else:
        calls, window = codex_calls(args.codex, args.since, args.until)
        report = {"tool": "codex", **summarize(calls)}
        # Codex weights are not published for this model; the window percentage is the tool's own budget meter.
        report["window_5h_percent"] = [window[0], window[-1]] if window else None
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
===FILE: tests/test_u95b_cost_meter.py===
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
===EDIT: .coord/PLAN.md===
<<<<<<< SEARCH
`tests/test_u95a_antigravity_briefing.py` |
=======
`tests/test_u95a_antigravity_briefing.py` |
| U95-B | REVIEW (Claude 설계, Codex 복귀 시 재검토) | claude(설계) · apply(0토큰) | 영수증: 토큰 절약 성공 신호(카드당 읽기 환산 토큰)를 잴 도구가 없어 채팅 속 일회용 스크립트로만 측정함(Claude 호출당 13.7만~14.7만, Codex 13.9만~14.1만, Codex 306회 호출에 5시간 한도 18%). 조치: 도구 자신의 기록(transcript)에서 호출 수·호출당 컨텍스트·압축·캐시 재작성·읽기 환산 비용·Codex 5시간 한도 %를 재는 `python -m v7_harness.cost_meter`. — `v7_harness/cost_meter.py`, `tests/test_u95b_cost_meter.py` |
>>>>>>> REPLACE
===END===

## Output

- Reply with ===EDIT and ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.
