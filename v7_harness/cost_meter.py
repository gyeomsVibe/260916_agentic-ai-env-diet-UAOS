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
