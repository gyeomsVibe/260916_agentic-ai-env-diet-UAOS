from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from v7_harness.adapters.ollama_worker import BLOCK_RE, EDIT_RE

DICTATION_CODE_LINE_LIMIT = 20  # a longer code patch costs the paid conductor more output tokens than a spec for a delegate; policy value, UNMEASURED until an A/B.

DELEGATE_WORKERS = frozenset({"ollama", "local", "cascade", "agy", "lane"})

# Code a shell or runtime executes; a dictated script is dictated code too (U98-D-R P1).
CODE_SUFFIXES = (".py", ".pyw", ".pyi", ".ps1", ".psm1", ".sh", ".bat", ".cmd", ".js", ".ts")

# Outcomes that mean the delegate really failed; APPROVE, PASS or no outcome never unlock apply (U98-D-R P1).
FAILED_OUTCOMES = frozenset({"FAIL", "FAILED", "BLOCKED", "UNUSABLE", "REWORK", "REJECTED"})

def _normalize(path: str) -> str:
    """Normalize the given path."""
    path = path.strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path

def _card(work_id: str) -> str:
    """Get the card from the work_id."""
    return str(work_id or "").split("-")[0]

def dictated_code_lines(text: str) -> int:
    """Count non-test Python lines in a manual dictated by the paid conductor."""
    lines = 0
    for m in BLOCK_RE.finditer(text):
        path = _normalize(m.group("path"))
        body = m.group("body")
        if path.lower().endswith(CODE_SUFFIXES) and not path.startswith("tests/"):
            lines += sum(1 for line in body.splitlines() if line.strip())
    for m in EDIT_RE.finditer(text):
        path = _normalize(m.group("path"))
        replace = m.group("replace")
        if path.lower().endswith(CODE_SUFFIXES) and not path.startswith("tests/"):
            lines += sum(1 for line in replace.splitlines() if line.strip())
    return lines

def _failed_delegate(project: Path, work_id: str, card: str) -> bool:
    """Check if a delegate run with the given work_id failed."""
    if not card or _card(work_id) != card:
        return False
    from v7_harness.coord.hook_context import shared_desk
    path = shared_desk(project) / ".coord" / "usage" / "runs.jsonl"
    if not path.exists():
        return False
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                if row.get("work_id") == work_id and row.get("worker") in DELEGATE_WORKERS and row.get("outcome") in FAILED_OUTCOMES:
                    return True
    except OSError:
        pass
    return False

def delegate_first_errors(text: str, contract: dict[str, Any], project: Path) -> list[str]:
    """Check if the dictated code exceeds the line limit or if apply_after is needed."""
    if contract.get("worker") != "apply":
        return []
    lines = dictated_code_lines(text)
    if lines <= DICTATION_CODE_LINE_LIMIT:
        return []
    after = str(contract.get("apply_after") or "").strip()
    if after and _failed_delegate(project, after, _card(contract.get("work_id"))):
        return []
    return [f"DELEGATE_FIRST: {lines} dictated code lines > {DICTATION_CODE_LINE_LIMIT}; write a spec for worker local (Ollama) or agy first, and apply only with apply_after: <work_id of that failed run>"]
