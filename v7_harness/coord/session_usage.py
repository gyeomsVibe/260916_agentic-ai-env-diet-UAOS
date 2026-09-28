"""U73: record the tokens a Claude Code session spent, read from its own transcript, as usage-ledger rows.

Seen 2026-09-28 (U72): pilot rows showed 0 paid tokens for U68-U72-L because the apply worker is free, while the
acting Claude session that designed, verified and reported every card left no row at all. The "no 3x cost
regression" gate was therefore UNKNOWN. The session transcript already holds each API call's usage; this module
sums it deterministically (no model call, no subprocess) and appends one `kind: session` row per recording.

Recording is incremental: a row covers only the calls after the latest row already recorded for the same session,
so recording at the end of every card attributes each stretch of the session to that card exactly once.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .usage_ledger import SECRET_PATTERNS, UsageRejected, _check_secrets, _ledger_lock, _rows

TOKEN_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
# Claude Code writes locally generated notices as assistant turns with this model; they are not API calls.
SYNTHETIC_MODEL = "<synthetic>"


def _codex_call(entry: dict[str, Any], state: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """U74-B: one Codex rollout `token_count` event whose cumulative total grew, as the delta since the last one.

    Codex writes cumulative `total_token_usage` and repeats the event without a new call; only a larger total is a
    call. Its `input_tokens` include the cached part, so the uncached input is input minus cached.
    """
    payload = entry.get("payload")
    info = payload.get("info") if isinstance(payload, dict) else None
    total = info.get("total_token_usage") if isinstance(info, dict) else None
    stamp = entry.get("timestamp")
    if not isinstance(total, dict) or not isinstance(stamp, str):
        return None
    counts = {key: total.get(key) for key in ("input_tokens", "cached_input_tokens", "cache_write_input_tokens",
                                                "output_tokens", "total_tokens")}
    if any(not isinstance(value, int) or isinstance(value, bool) for value in counts.values()):
        return None
    previous = state.get("total") or dict.fromkeys(counts, 0)
    if counts["total_tokens"] <= previous["total_tokens"]:
        return None
    state["total"] = counts
    delta = {key: counts[key] - previous[key] for key in counts}
    return f"codex-{counts['total_tokens']}", {
        "ts": stamp, "model": state.get("model"),
        "input_tokens": delta["input_tokens"] - delta["cached_input_tokens"],
        "output_tokens": delta["output_tokens"],
        "cache_creation_input_tokens": delta["cache_write_input_tokens"],
        "cache_read_input_tokens": delta["cached_input_tokens"],
    }


def _session_calls(transcript: Path) -> dict[str, dict[str, Any]]:
    """One entry per API call: a Claude Code message id (repeated once per content block, all with its usage) or a
    Codex rollout token_count event that grew the cumulative total."""
    calls: dict[str, dict[str, Any]] = {}
    codex: dict[str, Any] = {}
    with open(transcript, encoding="utf-8") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict):
                continue
            payload = entry.get("payload")
            if entry.get("type") == "turn_context" and isinstance(payload, dict) and payload.get("model"):
                codex["model"] = str(payload["model"])
                continue
            if entry.get("type") == "event_msg" and isinstance(payload, dict) and payload.get("type") == "token_count":
                call = _codex_call(entry, codex)
                if call:
                    calls[call[0]] = call[1]
                continue
            if entry.get("type") != "assistant":
                continue
            message = entry.get("message")
            if not isinstance(message, dict) or message.get("model") == SYNTHETIC_MODEL:
                continue
            usage, message_id, stamp = message.get("usage"), message.get("id"), entry.get("timestamp")
            if not isinstance(usage, dict) or not isinstance(message_id, str) or not isinstance(stamp, str):
                continue
            call = calls.setdefault(message_id, {"ts": stamp, "model": message.get("model"),
                                                 **{key: 0 for key in TOKEN_KEYS}})
            call["ts"] = min(call["ts"], stamp)
            for key in TOKEN_KEYS:
                value = usage.get(key)
                # The repeated blocks carry the same final usage; max() keeps a partial first block from undercounting.
                if isinstance(value, int) and not isinstance(value, bool) and value > call[key]:
                    call[key] = value
    return calls


def _recorded_until(ledger: Path, session_id: str) -> str:
    """The end of the latest window already recorded for this session ('' when none)."""
    until = ""
    for line in _rows(ledger):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("kind") == "session" and row.get("session_id") == session_id:
            until = max(until, str(row.get("window_end") or ""))
    return until


def _seconds(start: str, end: str) -> float:
    def parse(stamp: str) -> datetime:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00"))

    return round((parse(end) - parse(start)).total_seconds(), 3)


def record_session(project_root: Path, transcript: Path, *, work_id: str, actor: str | None = None,
                   apply: bool = False, lock_timeout_s: float = 10.0) -> dict[str, Any]:
    """Sum the session's calls after its last recorded window; with apply, append them as one ledger row.

    The read of the ledger, the window choice and the append all run under the ledger lock, so two recordings at
    once cannot count the same calls twice.
    """
    transcript = Path(transcript)
    if not work_id.strip():
        raise UsageRejected("work_id must be a non-empty string")
    if not transcript.is_file():
        raise UsageRejected(f"transcript not found: {transcript}")
    session_id = transcript.stem
    calls = _session_calls(transcript)
    # The transcript's own format names the tool: Codex rollouts yield codex-* calls.
    actor = actor or ("codex" if any(key.startswith("codex-") for key in calls) else "claude")
    with _ledger_lock(Path(project_root), lock_timeout_s) as ledger:
        since = _recorded_until(ledger, session_id)
        window = sorted((call for call in calls.values() if call["ts"] > since), key=lambda call: call["ts"])
        if not window:
            return {"ledger": str(ledger), "session_id": session_id, "since": since or None, "api_calls": 0,
                    "mode": "NOTHING_NEW", "appended": 0}
        models = sorted({str(call["model"]) for call in window if call["model"]}) or ["unknown"]
        row: dict[str, Any] = {
            "schema": "uaos-usage-v2", "work_id": work_id, "actor": actor, "worker": actor,
            "model": ",".join(models), "kind": "session", "collection_mode": "transcript",
            "wall_time_s": _seconds(window[0]["ts"], window[-1]["ts"]), "outcome": "MEASURED",
            "receipt": str(transcript), "independent_verifier": None, "rsi_eligible": False,
            # A session row is a cost measurement, not a worker attempt: RSI and admission read pilot/review rows.
            "exclusion_reason": "SESSION_COST_NOT_WORKER_ATTEMPT",
            "session_id": session_id, "window_start": window[0]["ts"], "window_end": window[-1]["ts"],
            "api_calls": len(window),
            **{key: sum(call[key] for call in window) for key in TOKEN_KEYS},
        }
        _check_secrets(row)
        if apply:
            row["ts"] = time.time()
            line = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
            if any(pattern.search(line) for pattern in SECRET_PATTERNS):
                raise UsageRejected("secret detected in usage record")
            with open(ledger, "ab") as handle:
                handle.write(line.encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
    return {"ledger": str(ledger), "since": since or None, "mode": "APPLY" if apply else "DRY_RUN",
            "appended": 1 if apply else 0, **{key: row[key] for key in (
                "session_id", "work_id", "model", "window_start", "window_end", "api_calls", "wall_time_s",
                *TOKEN_KEYS)}}
