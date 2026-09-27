"""U38: an independent, read-only review of a pilot bundle by Claude Code (`pilot review`). docs/40 §2-2.

The review is evidence for the judge, never a verdict. On one OS account every actor name can be forged (B83), so
a reviewer's PASS cannot stand in for Codex's or the user's approval; it is written with "advisory": true. A reviewer
never reviews its own worker's bundle, and it runs under the same budget gate as a paid worker (B85).
"""

from __future__ import annotations

import difflib
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

# U46-J1: agy lets a conductor wake Antigravity through its CLI instead of a mailbox letter a person must relay.
REVIEWERS = ("claude", "agy")
SCHEMA_HINT = ('{"verdict": "PASS" or "REWORK", "counterexamples": ["..."], '
               '"evidence_lines": ["path:line quote", "..."]}')
MAX_DIFF_CHARS = 60_000
FINAL_ANSWER = ("Stop reading. Answer now with the one JSON verdict object from what you have already read: "
                + SCHEMA_HINT)
# Windows caps a whole command line at 32,767 characters (WinError 206 on the U44-FIX4 review). Past
# ARGV_PROMPT_CHARS (adapters/long_prompt.py) the request goes on standard input, which claude -p reads with the short
# argv prompt (live: 46,529 chars).
STDIN_PROMPT = "The full review request (contract and diff) is on standard input. Follow it."


class ReviewRefused(Exception):
    pass


def bundle_diff(source: Path, staging: Path, changed: list[str]) -> str:
    parts = []
    for rel in changed:
        before = (source / rel).read_text(encoding="utf-8", errors="replace").splitlines(True) if (source / rel).is_file() else []
        after = (staging / rel).read_text(encoding="utf-8", errors="replace").splitlines(True) if (staging / rel).is_file() else []
        parts.extend(difflib.unified_diff(before, after, f"a/{rel}", f"b/{rel}"))
    return "".join(parts)


def review_prompt(task_id: str, manual_text: str, diff: str, spill_path: str | Path | None = None) -> str:
    # U52: a plain diff[:MAX] cut the tail silently while the prompt called the diff complete; the gate keeps head and
    # tail, marks the cut, and the prompt says the diff is partial so the reviewer reads the changed files instead.
    from .output_gate import gate_output

    gated = gate_output(diff, MAX_DIFF_CHARS, spill_path)
    scope = ("The diff below is PARTIAL (see the U52 OUTPUT CUT marker): read the changed files in the current "
             "directory for the omitted part before judging it. " if gated.truncated else
             "The diff below is the complete change: judge from it. ")
    return (f"[{task_id}] Review this change against its contract. {scope}"
            "Read a file only to confirm one specific counterexample, and answer within a few turns.\n\n"
            f"## Contract\n{manual_text}\n\n## Diff\n```diff\n{gated.text}\n```\n\n"
            f"Reply with exactly one JSON object: {SCHEMA_HINT}")


def merge_usage(first: dict[str, int], second: dict[str, int]) -> dict[str, int]:
    merged = {key: first.get(key, 0) + second.get(key, 0) for key in set(first) | set(second) if key != "cost_microusd"}
    if "cost_microusd" in first or "cost_microusd" in second:
        # claude reports a resumed session's running total (U44 live: 251,432 then 268,659), so take the larger.
        merged["cost_microusd"] = max(first.get("cost_microusd", 0), second.get("cost_microusd", 0))
    return merged


def parse_verdict(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or data.get("verdict") not in ("PASS", "REWORK"):
        return None
    return {"verdict": data["verdict"],
            "counterexamples": [str(x)[:500] for x in data.get("counterexamples") or []][:20],
            "evidence_lines": [str(x)[:300] for x in data.get("evidence_lines") or []][:40]}


def run_review(*, task_id: str, work_dir: Path, source: Path, manual_text: str, reviewer: str, budget: int,
               budget_usd: float = 0.0, model: str | None = None, timeout_s: int = 600,
               runner: Any = subprocess.run) -> dict[str, Any]:
    from .adapters.claude_worker import DEFAULT_MODEL, review_command, usage_from, worker_env
    from .pilot import evaluate_cost_gate

    if reviewer not in REVIEWERS:
        raise ReviewRefused(f"UNKNOWN_REVIEWER:{reviewer}")
    if budget <= 0:
        raise ReviewRefused("REVIEW_WITHOUT_BUDGET: pass --budget > 0 (a review is a paid call)")
    if reviewer == "claude" and not budget_usd > 0:
        # agy has no dollar cap option; its review is held by the token budget gate alone (B85).
        raise ReviewRefused("REVIEW_WITHOUT_USD_CAP: pass --budget-usd > 0 (claude --max-budget-usd, before spending)")
    runs = Path(work_dir) / "runs" / task_id
    try:
        summary = json.loads((runs / "summary.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewRefused(f"NO_PILOT_SUMMARY:{runs / 'summary.json'} ({type(exc).__name__})") from exc
    try:
        author = (runs / "worker").read_text(encoding="utf-8").strip()
    except OSError:
        author = ""
    if not author:
        # Fail closed: without the author the rule "never review your own worker's bundle" cannot be checked.
        raise ReviewRefused(f"AUTHOR_UNKNOWN: {runs / 'worker'} is missing (bundle built before U38?)")
    if author == reviewer:
        raise ReviewRefused(f"REVIEWER_IS_AUTHOR:{reviewer} wrote this bundle")
    staging = Path(summary.get("agy_workspace") or "")
    changed = [str(x) for x in summary.get("changed_files") or []]
    if not changed or not staging.is_dir():
        raise ReviewRefused("NOTHING_TO_REVIEW: no changed files or no staged copy")

    # The spill goes in the run folder, never in staging: a file written there would become part of the bundle.
    prompt = review_prompt(task_id, manual_text, bundle_diff(Path(source), staging, changed), runs / "review.diff")
    started = time.monotonic()
    usage: dict[str, int] = {}
    error = ""
    verdict = None
    conversation_id = None
    try:
        if reviewer == "agy":
            usage, verdict, error, conversation_id = _agy_review(task_id, prompt, runs, timeout_s, runner)
            raise _Reviewed
        from .adapters.long_prompt import ARGV_PROMPT_CHARS

        via_stdin = len(prompt) > ARGV_PROMPT_CHARS
        done = runner(review_command(STDIN_PROMPT if via_stdin else prompt, model or DEFAULT_MODEL, budget_usd),
                      cwd=str(staging), env=worker_env(), capture_output=True, timeout=timeout_s,
                      **({"input": prompt.encode("utf-8")} if via_stdin else {}))
        result = json.loads(done.stdout.decode("utf-8", errors="replace"))
        if isinstance(result, dict):
            usage = usage_from(result)
            verdict = parse_verdict(str(result.get("result") or ""))
            left_usd = budget_usd - usage.get("cost_microusd", 0) / 1_000_000
            if (verdict is None and result.get("subtype") == "error_max_turns" and result.get("session_id")
                    and left_usd >= 0.01):
                # Out of turns before answering (U44-FIX3: 6 turns of reading, no verdict). One more turn in the same
                # session answers from what it already read (U44 live: 1 turn, 48k tokens) instead of a fresh review.
                done = runner(review_command(FINAL_ANSWER, model or DEFAULT_MODEL, left_usd,
                                             resume=str(result["session_id"])),
                              cwd=str(staging), env=worker_env(), capture_output=True, timeout=timeout_s)
                final = json.loads(done.stdout.decode("utf-8", errors="replace"))
                if isinstance(final, dict):
                    usage = merge_usage(usage, usage_from(final))
                    verdict = parse_verdict(str(final.get("result") or ""))
                    result = final
            if verdict is None:
                error = f"REVIEW_UNPARSED: the reviewer did not return the JSON verdict ({result.get('subtype')})"
        else:
            error = "REVIEW_NOT_JSON_OBJECT"
    except _Reviewed:
        pass
    except subprocess.TimeoutExpired:
        error = f"REVIEW_TIMEOUT:{timeout_s}s"
    except (OSError, ValueError) as exc:
        error = f"REVIEW_FAILED:{type(exc).__name__}: {exc}"[:300]
    cost_gate = evaluate_cost_gate(usage, budget)
    record = {
        "task_id": task_id, "reviewer": reviewer, "author_worker": author, "bundle_id": summary.get("bundle_id"),
        # Evidence for the judge, not a verdict (B83): the judge still approves or rejects the bundle.
        "advisory": True,
        "verdict": verdict["verdict"] if verdict and cost_gate == "WITHIN" else "UNUSABLE",
        "counterexamples": (verdict or {}).get("counterexamples", []),
        "evidence_lines": (verdict or {}).get("evidence_lines", []),
        "cost_gate": cost_gate, "usage": usage, "elapsed_s": int(time.monotonic() - started), "error": error,
    }
    if reviewer == "agy":
        record["judge_conversation_id"] = conversation_id
    out = runs / f"review_{reviewer}.json"
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    record["review_path"] = str(out)
    _record_usage(Path(source), task_id, reviewer, model or (DEFAULT_MODEL if reviewer == "claude" else "agy-default"),
                  usage, record, out)
    return record


class _Reviewed(Exception):
    """Leaves the claude call path once the agy review has run."""


def _agy_review(task_id: str, prompt: str, runs: Path, timeout_s: int,
                runner: Any) -> tuple[dict[str, int], dict[str, Any] | None, str, str | None]:
    """Antigravity reads the request from a file in the run folder (a diff can pass the 32,767-character Windows
    command line) and answers in JSON. No permission bypass: it can read, and only the pilot applies anything."""
    import os

    from .adapters.agy import AgyRequest, build_agy_command, parse_agy_result

    request = runs / "review_agy_request.md"
    request.write_text(prompt, encoding="utf-8")
    short = (f"Read {request.name} in this folder: a review request with the contract and the complete diff. "
             f"Do not edit any file. Reply with exactly one JSON object: {SCHEMA_HINT}")
    argv = build_agy_command(AgyRequest(task_id=task_id, title="review", prompt=short, workspace=runs,
                                        isolation_mode="staging", print_timeout_s=timeout_s))
    done = runner(argv, cwd=str(runs), env={**os.environ, "UAOS_WORKER": "1"}, capture_output=True,
                  timeout=timeout_s + 60)
    outcome = parse_agy_result(stdout=done.stdout or b"", stderr=done.stderr or b"", exit_code=done.returncode)
    usage = dict(outcome.usage)
    if not outcome.successful:
        return usage, None, f"REVIEW_FAILED:agy {outcome.error_class}", outcome.conversation_id
    envelope = json.loads(done.stdout.decode("utf-8", errors="replace"))
    text = envelope.get("response") if isinstance(envelope.get("response"), str) else json.dumps(
        envelope.get("structured_output"))
    verdict = parse_verdict(text)
    return (usage, verdict, "" if verdict else "REVIEW_UNPARSED: the reviewer did not return the JSON verdict (agy)",
            outcome.conversation_id)


def _record_usage(source: Path, task_id: str, reviewer: str, model: str, usage: dict[str, int], record: dict,
                  receipt: Path) -> None:
    """A review is a paid call; it goes in the ledger as kind "review" (RSI windows read kind "pilot" only)."""
    if not ((source / ".git").is_dir() or (source / ".coord" / "PLAN.md").is_file()):
        return
    from .coord.usage_ledger import record_usage

    entry = {
        "schema": "uaos-usage-v2", "work_id": f"{task_id}-review-{reviewer}", "actor": reviewer, "model": model,
        "kind": "review", "collection_mode": "automatic",
        "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
        # U46-J2: absolute, so the receipt resolves from any cwd (it was stored as ..\..\runs\...).
        "wall_time_s": None, "outcome": record["verdict"], "receipt": str(Path(receipt).resolve()),
        "independent_verifier": None,
        "rsi_eligible": False, "exclusion_reason": "ADVISORY_REVIEW", "worker": reviewer, "cost_gate": record["cost_gate"],
    }
    for extra in ("cache_creation_input_tokens", "cache_read_input_tokens", "cost_microusd"):
        if extra in usage:
            entry[extra] = usage[extra]
    try:
        record_usage(source, entry)
    except Exception as exc:  # noqa: BLE001 - the review file is the receipt; the ledger is best effort
        record["usage_ledger_error"] = f"{type(exc).__name__}: {exc}"[:200]
