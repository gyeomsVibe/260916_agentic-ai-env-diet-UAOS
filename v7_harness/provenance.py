"""U276 + U284: resolve the true author tool of a pilot run or a commit, read-only.

Every independent signal is collected: one tool -> RESOLVED, several -> CONFLICT, none -> UNKNOWN. The broker
lease owner is hard-coded "antigravity" (pilot.py) and summary agy_* fields appear for every worker, so neither is
author evidence (receipts: .work/u276_u284/RECEIPTS.md, PR #171/#160 prefix codex with Claude-only commits).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TOOLS = {"agy": "antigravity", "antigravity": "antigravity", "claude": "claude", "codex": "codex",
         "local": "ollama", "ollama": "ollama"}
PREFIX_TOOLS = ("agy", "antigravity", "claude", "codex")  # same prefixes as calculator_gate.author_tool
CLAUDE_TRAILER_RE = re.compile(r"^Co-Authored-By:\s*Claude\b", re.IGNORECASE | re.MULTILINE)
AUTHOR_TOOL_RE = re.compile(r"^Author-Tool:\s*(\S+)\s*$", re.IGNORECASE | re.MULTILINE)


def normalize_tool(name) -> str | None:
    """A tool name, or None for anything that is not an author tool (apply, custom, user, coordinator)."""
    return TOOLS.get(str(name or "").strip().lower())


def commit_trailer_tools(messages) -> set[str]:
    """Tools named by commit trailers: `Co-Authored-By: Claude ...` and an explicit `Author-Tool: <tool>`."""
    tools: set[str] = set()
    for message in messages:
        text = str(message or "")
        if CLAUDE_TRAILER_RE.search(text):
            tools.add("claude")
        for match in AUTHOR_TOOL_RE.finditer(text):
            tool = normalize_tool(match.group(1))
            if tool:
                tools.add(tool)
    return tools


def _state(tools: set[str]) -> tuple[str | None, str]:
    if len(tools) == 1:
        return next(iter(tools)), "RESOLVED"
    return None, ("CONFLICT" if tools else "UNKNOWN")


def resolve_commit_author(branch, messages) -> tuple[str | None, str]:
    """U284: branch prefix plus commit trailers; PR #171 (codex/ branch, Claude-only commits) is CONFLICT."""
    tools = commit_trailer_tools(messages)
    raw = str(branch or "").strip()
    if "/" in raw and raw.split("/", 1)[0].lower() in PREFIX_TOOLS:
        tools.add(normalize_tool(raw.split("/", 1)[0]))
    return _state(tools)


def _read_worker(value, sources: dict, key: str) -> bool:
    """Add the normalized worker under *key*; True when the worker is `apply` (its author is the delegator)."""
    if str(value or "").strip().lower() == "apply":
        return True
    tool = normalize_tool(value)
    if tool:
        sources.setdefault(key, set()).add(tool)
    return False


def resolve_run_author(run_dir, ledger_rows) -> dict:
    """U276: author of one historical pilot run from its worker file, summary.json `worker` and matching `pilot`
    ledger rows (by work_id or receipt path). Read-only; review rows and lease owners are never author evidence."""
    run_dir = Path(run_dir)
    task = run_dir.name
    sources: dict[str, set[str]] = {}
    try:
        _read_worker((run_dir / "worker").read_text(encoding="utf-8"), sources, "worker_file")
    except OSError:
        pass
    try:
        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        summary = None
    if isinstance(summary, dict):
        _read_worker(summary.get("worker"), sources, "summary")
    marker = f".coord/pilot/runs/{task}/"
    for row in ledger_rows:
        if not isinstance(row, dict) or row.get("kind") != "pilot":
            continue
        receipt = str(row.get("receipt") or "").replace("\\", "/")
        if row.get("work_id") != task and marker not in receipt:
            continue
        if _read_worker(row.get("worker"), sources, "ledger"):
            tool = normalize_tool(row.get("delegator"))
            if tool:
                sources.setdefault("ledger", set()).add(tool)
    author, state = _state(set().union(*sources.values()) if sources else set())
    return {"task": task, "author": author, "state": state, "sources": {k: sorted(v) for k, v in sources.items()}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m v7_harness.provenance")
    parser.add_argument("command", choices=["runs"])
    parser.add_argument("--pilot-dir", type=Path, default=Path(".coord/pilot"))
    parser.add_argument("--ledger", type=Path, default=Path(".coord/usage/runs.jsonl"))
    args = parser.parse_args(argv)
    rows = []
    try:
        for line in args.ledger.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    counts = {"RESOLVED": 0, "UNKNOWN": 0, "CONFLICT": 0}
    runs = args.pilot_dir / "runs"
    for run_dir in sorted(p for p in runs.iterdir() if p.is_dir()) if runs.is_dir() else []:
        result = resolve_run_author(run_dir, rows)
        counts[result["state"]] += 1
        print(json.dumps(result, ensure_ascii=True))
    print(json.dumps({"summary": counts}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
