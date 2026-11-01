"""U287: the one telemetry record for helper workers (Ollama, Haiku 5.5, GPT-6 Luna, Gemini 3.8 Flash Low).

Rows go into the desk usage ledger (`uaos-usage-v2`, U72-L) so the RSI ledger and `coord capacity` read the same
numbers. This module never imports the HUD (U286); the HUD only displays `summarize()` output. Prompt text is never
stored: `input_hash` stands in for it (global journal rule). Field names follow the OpenTelemetry GenAI conventions
(separate input/output tokens, exact request model).
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from .usage_ledger import UsageRejected, ledger_file, record_usage

TELEMETRY = "uaos-helper-telemetry-v1"
# lane -> (exact pinned model, or None when any local Ollama model is allowed; budget engine the call is billed to)
LANES = {"ollama": (None, "ollama"), "haiku": ("claude-haiku-5-5", "haiku"), "luna": ("gpt-6-luna", "codex"),
         "flash": ("gemini-3.8-flash-low", "antigravity")}
CALLERS = ("codex", "claude", "antigravity")
FORBIDDEN_KEYS = ("prompt", "messages", "content", "completion", "response_text")
OUTCOMES = ("PASS", "FAIL", "BLOCKED", "REWORK", "TIMEOUT", "ERROR")
_HASH = re.compile(r"[0-9a-f]{64}")


def _tokens(value: Any) -> bool:
    return value is None or (isinstance(value, int) and not isinstance(value, bool) and value >= 0)


def build_helper_record(*, work_id: str, lane: str, model: str, caller: str, project: str, input_hash: str,
                        input_tokens: int | None, output_tokens: int | None, wall_time_s: float | None, outcome: str,
                        receipt: str, error: str | None = None, gate: str | None = None,
                        independent_verifier: str | None = None, ts: float | None = None,
                        **extra: Any) -> dict[str, Any]:
    """Validate one helper attempt and return its ledger row; raise UsageRejected on any contract breach."""
    for key in extra:
        if key in FORBIDDEN_KEYS:
            raise UsageRejected(f"HELPER_RAW_TEXT_FORBIDDEN: {key}")
    if lane not in LANES:
        raise UsageRejected("HELPER_UNKNOWN_LANE")
    if caller not in CALLERS:
        raise UsageRejected("HELPER_UNKNOWN_CALLER")
    pinned, engine = LANES[lane]
    if not isinstance(model, str) or not model.strip() or (pinned is not None and model != pinned):
        raise UsageRejected("HELPER_MODEL_MISMATCH")
    if not isinstance(input_hash, str) or not _HASH.fullmatch(input_hash):
        raise UsageRejected("HELPER_INPUT_HASH_INVALID")
    if not (_tokens(input_tokens) and _tokens(output_tokens)):
        raise UsageRejected("HELPER_TOKENS_INVALID")
    if outcome not in OUTCOMES:
        raise UsageRejected("HELPER_OUTCOME_INVALID")
    # Author != judge: only a different, named verifier makes the row RSI evidence.
    eligible = isinstance(independent_verifier, str) and bool(independent_verifier) and independent_verifier != caller
    measured = input_tokens is not None and output_tokens is not None
    row = dict(extra)
    row.update(schema="uaos-usage-v2", telemetry=TELEMETRY, kind="helper", collection_mode="helper_contract",
               work_id=work_id, actor=caller, caller=caller, project=project, helper_lane=lane, budget_engine=engine,
               model=model, input_hash=input_hash, input_tokens=input_tokens, output_tokens=output_tokens,
               token_status="MEASURED" if measured else "UNKNOWN", wall_time_s=wall_time_s, outcome=outcome,
               error=error, gate=gate, receipt=receipt, independent_verifier=independent_verifier,
               rsi_eligible=eligible, exclusion_reason=None if eligible else "PENDING_INDEPENDENT_VERIFICATION")
    if ts is not None:
        row["ts"] = ts
    return row


def record_helper(project_root: Path, **kwargs: Any) -> Path:
    """Validate and append one helper attempt to the desk usage ledger."""
    return record_usage(Path(project_root), build_helper_record(**kwargs))


def read_helper_records(project_root: Path) -> list[dict[str, Any]]:
    """Helper contract rows of the desk ledger, in file order; other and unreadable rows are skipped."""
    path = ledger_file(Path(project_root))
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("telemetry") == TELEMETRY:
            rows.append(row)
    return rows


def summarize(rows: list[dict[str, Any]], *, now: float | None = None, window_s: float = 86400.0) -> dict[str, Any]:
    """Per-lane calls, measured tokens, UNKNOWN-token calls and failures inside the window (default 24 h)."""
    moment = time.time() if now is None else float(now)
    lanes = {lane: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "unknown_token_calls": 0, "failures": 0}
             for lane in LANES}
    for row in rows:
        ts = row.get("ts")
        if isinstance(ts, bool) or not isinstance(ts, (int, float)) or ts < moment - window_s or ts > moment + 60:
            continue
        bucket = lanes.get(row.get("helper_lane"))
        if bucket is None:
            continue
        bucket["calls"] += 1
        if row.get("token_status") == "MEASURED":
            bucket["input_tokens"] += int(row.get("input_tokens") or 0)
            bucket["output_tokens"] += int(row.get("output_tokens") or 0)
        else:
            bucket["unknown_token_calls"] += 1
        if row.get("outcome") != "PASS":
            bucket["failures"] += 1
    return {"schema": TELEMETRY + "-summary", "window_s": window_s,
            "total_calls": sum(b["calls"] for b in lanes.values()), "lanes": lanes}
