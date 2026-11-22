"""U350 ideas intake: a bounded, append-only queue of raw user ideas in `.coord/intake/ideas.jsonl`.

It sits in front of `desk_router` (which turns a directive into cards) and beside `desk_ledger` (which records
directives already given). Rows here are pending ideas that nothing has routed yet.

C33: priority is deterministic. P0 only from an explicit user flag or an emergency keyword; a model hint is
recorded for audit but never decides (`classifier != promoter`), and anything unmatched is P1.
C34: appends run under one cross-process lock with fsync, so parallel writers on Windows lose no line; a full
queue writes an audited QUEUE_SHED row to `shed.jsonl` instead of truncating in silence.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from .desk_router import _Lock

IDEAS_REL = ".coord/intake/ideas.jsonl"
SHED_REL = ".coord/intake/shed.jsonl"
# 500 pending ideas is far above a day of user input seen on the desk; past it the router is not keeping up and
# shedding (audited) is safer than an unbounded file every reader must scan.
QUEUE_CAP = 500
PRIORITIES = ("P0", "P1", "P2")
_EDGE_L, _EDGE_R = r"(?<![A-Za-z0-9])", r"(?![A-Za-z0-9])"
_P0_RE = re.compile(_EDGE_L + r"(?:P0|emergency|urgent|outage)" + _EDGE_R + r"|긴급|장애", re.IGNORECASE)
_P2_RE = re.compile(_EDGE_L + r"(?:P2|someday|low[ -]priority)" + _EDGE_R + r"|나중에|언젠가", re.IGNORECASE)
_REQUIRED = {"seq": int, "text": str, "source": str, "priority": str, "at": (int, float)}


def classify(text: str, *, user_p0: bool = False, model_hint: str | None = None) -> str:
    """Deterministic P0/P1/P2. `model_hint` is deliberately unused for the decision (C33)."""
    del model_hint  # recorded by append_idea for audit only; a model never promotes or demotes
    if user_p0 or _P0_RE.search(text or ""):
        return "P0"
    if _P2_RE.search(text or ""):
        return "P2"
    return "P1"


def validate(row: Any) -> list[str]:
    """Schema problems of one ideas row; empty list means valid."""
    if not isinstance(row, dict):
        return ["row is not an object"]
    problems = [f"missing or bad {key}" for key, kind in _REQUIRED.items()
                if not isinstance(row.get(key), kind) or isinstance(row.get(key), bool)]
    if row.get("priority") not in PRIORITIES:
        problems.append(f"bad priority: {row.get('priority')!r}")
    return problems


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_bytes().decode("utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue  # a torn line from a crashed writer is skipped, never fatal
        if isinstance(row, dict):
            rows.append(row)
    return rows


def read_ideas(project: Path) -> list[dict[str, Any]]:
    return _read_jsonl(Path(project) / IDEAS_REL)


def read_shed(project: Path) -> list[dict[str, Any]]:
    return _read_jsonl(Path(project) / SHED_REL)


def _append_line(path: Path, row: dict[str, Any]) -> None:
    with open(path, "ab") as handle:
        if path.stat().st_size and path.read_bytes()[-1:] != b"\n":
            handle.write(b"\n")  # a torn last line must not swallow this row
        handle.write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())


def append_idea(project: Path, text: str, *, source: str, user_p0: bool = False, model_hint: str | None = None,
                cap: int = QUEUE_CAP, now: float | None = None) -> dict[str, Any]:
    """Append one idea under the intake lock; at `cap` pending rows, record QUEUE_SHED and return it instead."""
    if not source:
        raise ValueError("source is required")
    folder = Path(project) / ".coord" / "intake"
    folder.mkdir(parents=True, exist_ok=True)
    at = time.time() if now is None else now
    with _Lock(folder / ".intake.lock"):
        rows = read_ideas(project)
        if len(rows) >= cap:
            shed = {"event": "QUEUE_SHED", "shed": True, "text": text, "source": source, "cap": cap, "at": at}
            _append_line(Path(project) / SHED_REL, shed)
            return shed
        seq = max((r.get("seq", 0) for r in rows if isinstance(r.get("seq"), int)), default=0) + 1
        row = {"seq": seq, "text": text, "source": source, "priority": classify(text, user_p0=user_p0),
               "user_p0": bool(user_p0), "model_hint": model_hint, "at": at}
        _append_line(Path(project) / IDEAS_REL, row)
    return row
