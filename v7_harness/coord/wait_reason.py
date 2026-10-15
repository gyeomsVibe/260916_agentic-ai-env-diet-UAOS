"""U201: one Korean line telling the user why work waits or stopped when a tool's turn ends.

Receipt (2026-10-16): parked Antigravity letters waited from 00:00 to 00:40 and no window said why. Claude Code and
Codex show a Stop hook's `systemMessage` to the user (https://code.claude.com/docs/en/hooks,
https://learn.chatgpt.com/docs/hooks.md); Antigravity's Stop hook has no user-facing field
(https://antigravity.google/docs/hooks), so its result is left as it is.
"""

from __future__ import annotations

import datetime as _dt
import json
import time
from pathlib import Path
from typing import Any

# Tools whose Stop hook shows `systemMessage` to the user (Stage 0 sources above).
SHOWS_SYSTEM_MESSAGE = ("claude", "codex")
TOOLS = ("codex", "claude", "antigravity")
# A gate stop older than one hour is history, not the reason this turn ends.
RECENT_GATE_S = 3600
SEOUL = _dt.timezone(_dt.timedelta(hours=9))


def _parked(project: Path) -> int:
    """Antigravity letters waiting in the daily-cap backlog (U164); `.failed` and `.lock` files are not letters."""
    folder = Path(project) / ".coord" / "mailbox" / "delivery" / "agy_backlog"
    return len(list(folder.glob("*.json"))) if folder.is_dir() else 0


def _gate_stops(project: Path, tool: str, moment: float) -> list[str]:
    """Cards this tool's Stop gate gave up on within the last hour (U146-A BLOCKED rows)."""
    try:
        text = (Path(project) / ".coord" / "log" / "stop_gate.jsonl").read_text(encoding="utf-8")
    except OSError:
        return []
    cards: list[str] = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get("tool") != tool or row.get("kind") != "BLOCKED":
            continue
        at, card = row.get("at"), str(row.get("card") or "")
        if isinstance(at, (int, float)) and moment - at <= RECENT_GATE_S and card and card not in cards:
            cards.append(card)
    return cards


def reasons(project: Path, tool: str, *, now: float | None = None) -> list[str]:
    """Why work waits or stopped, one Korean line per cause, from files only (zero paid tokens)."""
    from .agy_dispatch import DAILY_CAP
    from .presence import read

    moment = time.time() if now is None else now
    lines: list[str] = []
    parked = _parked(project)
    if parked:
        lines.append(f"Antigravity 답장 {parked}건 대기: 오늘 자동 답장 한도({DAILY_CAP}건) 소진 → 다음 날 첫 도구 턴에 자동 처리")
    for other in TOOLS:
        record = read(project, other, now=moment) if other != tool else {}
        if record.get("state") == "LIMITED" and isinstance(record.get("expires_at"), (int, float)):
            back = _dt.datetime.fromtimestamp(record["expires_at"], SEOUL).strftime("%H:%M")
            lines.append(f"{other} 사용량 한도로 멈춤 → {back} 복귀 예정")
    for card in _gate_stops(project, tool, moment):
        lines.append(f"{card} 진행 없이 다시 멈춰 자동 재시작 중단 → 다음 카드 대기")
    return lines


def stop_output(result: dict[str, Any] | None, project: Path, tool: str, *,
                now: float | None = None) -> dict[str, Any] | None:
    """The Stop hook's JSON: the gate's own decision, plus the reasons as `systemMessage` where the user sees it."""
    if tool not in SHOWS_SYSTEM_MESSAGE:
        return result
    lines = reasons(project, tool, now=now)
    if not lines:
        return result
    out = dict(result or {})
    out["systemMessage"] = "⏸ 대기·멈춤 이유: " + " · ".join(lines)
    return out
