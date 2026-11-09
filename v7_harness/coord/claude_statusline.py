"""U303-B: Claude Code statusLine recorder — the only local source of Claude's measured rate limits.

Claude Code (2.1.x) pipes one JSON object to the statusLine command on every refresh. For Pro/Max logins it
carries `rate_limits.five_hour` and `rate_limits.seven_day` with `used_percentage` and `resets_at` (epoch s),
plus `model.display_name` (docs: https://code.claude.com/docs/en/statusline). This script appends one compact
row to `~/.uaos/usage/claude_rate_limits.jsonl` when the values changed, and prints a one-line status.

Zero paid tokens, no network, no credential is read. Rows are deduplicated against the last row so a busy
session does not grow the file; the file is trimmed to MAX_ROWS (each row ~220 B, 4000 rows ~ 0.9 MB).
Install: settings.json `"statusLine": {"type": "command", "command": "python ~/.uaos/uaos.py coord statusline-claude"}`.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

MAX_ROWS = 4000  # ~ 14 days at one change per 5 minutes; keeps calibration pairs without an unbounded file
OUT = Path.home() / ".uaos" / "usage" / "claude_rate_limits.jsonl"


def _num(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def row_from_payload(payload: dict, now: float) -> dict | None:
    rl = payload.get("rate_limits") or {}
    five, seven = rl.get("five_hour") or {}, rl.get("seven_day") or {}
    model = payload.get("model") or {}
    effort = payload.get("effort")
    if isinstance(effort, dict):
        effort = effort.get("level") or effort.get("value")
    row = {
        "ts": round(now, 3),
        "five_hour_used_pct": _num(five.get("used_percentage")),
        "five_hour_resets_at": _num(five.get("resets_at")),
        "seven_day_used_pct": _num(seven.get("used_percentage")),
        "seven_day_resets_at": _num(seven.get("resets_at")),
        "model": model.get("display_name") or model.get("id") if isinstance(model, dict) else model,
        "effort": effort,
    }
    if row["five_hour_used_pct"] is None and row["seven_day_used_pct"] is None:
        return None
    return row


def _same(a: dict, b: dict) -> bool:
    keys = ("five_hour_used_pct", "five_hour_resets_at", "seven_day_used_pct", "seven_day_resets_at", "model", "effort")
    return all(a.get(k) == b.get(k) for k in keys)


LOCK_WAIT_S = 3.0  # Claude's statusLine refresh is debounced to ~300 ms; 3 s covers ten queued sessions
LOCK_STALE_S = 10.0  # a lock older than this belongs to a killed process (one write takes milliseconds)


def _lock(out: Path) -> Path | None:
    lock = out.with_suffix(".lock")
    deadline = time.time() + LOCK_WAIT_S
    while True:
        try:
            os.close(os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return lock
        except (FileExistsError, PermissionError):  # Windows: a lock being deleted refuses O_EXCL with EACCES
            try:
                if time.time() - lock.stat().st_mtime > LOCK_STALE_S:
                    lock.unlink()
                    continue
            except OSError:
                continue
            if time.time() > deadline:
                return None
            time.sleep(0.01)


def record(payload: dict, out: Path = OUT, now: float | None = None) -> bool:
    """Append a row when it differs from the last one. Returns True when a row was written.

    Concurrent Claude sessions serialize on an O_EXCL lock file, so no row is lost to a racing replace.
    """
    row = row_from_payload(payload, time.time() if now is None else now)
    if row is None:
        return False
    row["source"] = STATUSLINE_SOURCE  # S1: only a named producer counts as provider evidence (relay_acd9ea77)
    out.parent.mkdir(parents=True, exist_ok=True)
    lock = _lock(out)
    if lock is None:
        return False
    try:
        return _append_locked(out, row)
    finally:
        lock.unlink(missing_ok=True)


DESKTOP_SOURCE = "claude_desktop_get_usage"  # S1: the desktop app has no statusLine; its get_usage reading feeds here
STATUSLINE_SOURCE = "claude_statusline_rate_limits"  # rows copied from Claude Code's own statusLine stdin payload


def record_desktop(five_pct: float, five_resets, week_pct: float, week_resets, out: Path | None = None,
                   now: float | None = None) -> bool:
    """S1: append one row from the desktop app's usage reading (same format as the statusLine rows + source)."""
    from .quota_sources import _epoch

    out = OUT if out is None else out
    row = {"ts": round(time.time() if now is None else now, 3),
           "five_hour_used_pct": _num(five_pct), "five_hour_resets_at": _epoch(five_resets),
           "seven_day_used_pct": _num(week_pct), "seven_day_resets_at": _epoch(week_resets),
           "model": None, "effort": None, "source": DESKTOP_SOURCE}
    out.parent.mkdir(parents=True, exist_ok=True)
    lock = _lock(out)
    if lock is None:
        return False
    try:
        _append_locked(out, row, dedupe=False)
        return True
    finally:
        lock.unlink(missing_ok=True)


def _append_locked(out: Path, row: dict, dedupe: bool = True) -> bool:
    lines = out.read_text(encoding="utf-8").splitlines() if out.is_file() else []
    if lines and dedupe:  # a desktop reading is a new observation time even at the same %, so it is kept
        try:
            if _same(json.loads(lines[-1]), row):
                return False
        except ValueError:
            pass
    lines.append(json.dumps(row, separators=(",", ":")))
    tmp = out.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text("\n".join(lines[-MAX_ROWS:]) + "\n", encoding="utf-8")
    os.replace(tmp, out)  # a reader never sees a half-written file
    return True


def status_text(payload: dict) -> str:
    row = row_from_payload(payload, time.time()) or {}
    model = (payload.get("model") or {}).get("display_name") if isinstance(payload.get("model"), dict) else ""
    parts = [model or "Claude"]
    if row.get("five_hour_used_pct") is not None:
        parts.append(f"5h {row['five_hour_used_pct']:.0f}%")
    if row.get("seven_day_used_pct") is not None:
        parts.append(f"7d {row['seven_day_used_pct']:.0f}%")
    return " · ".join(parts)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
    except ValueError:
        payload = {}
    if isinstance(payload, dict):
        try:
            record(payload)
        except OSError:
            pass  # the status line must never break Claude's UI
        sys.stdout.write(status_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
