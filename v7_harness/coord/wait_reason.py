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


def _schedule_waits(project: Path, tool: str) -> list[str]:
    """U260: surface live REVIEW / peer-ACTIVE waits from `.coord/master_schedule.json` so the user always sees why work waits."""
    sched_path = Path(project) / ".coord" / "master_schedule.json"
    if not sched_path.is_file():
        return []
    try:
        sched = json.loads(sched_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    phases = sched.get("phases") if isinstance(sched, dict) else None
    if not isinstance(phases, list):
        return []
    out: list[str] = []
    for phase in phases:
        if not isinstance(phase, dict) or not phase.get("phase_id"):
            continue
        pid = str(phase["phase_id"])
        state = str(phase.get("state") or "")
        if state == "REVIEW":
            reviewer = str(phase.get("reviewer") or phase.get("waiting_on") or "peer")
            author = str(phase.get("author_tool") or phase.get("owner_tool") or "peer")
            out.append(f"{pid} 판정 대기 중: 판정자({reviewer})가 전체 테스트·검증 수행 중(작성: {author}) → 판정 즉시 병합·배포")
        elif state == "ACTIVE":
            owner = str(phase.get("owner_tool") or "")
            if owner and owner != tool:
                out.append(f"{pid} 작업 대기 중: 담당 도구({owner})가 구현·테스트 수행 중 → 완료 즉시 다음 단계 인계")
    return out


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
        if record.get("state") == "LIMITED":
            if isinstance(record.get("expires_at"), (int, float)):
                back = _dt.datetime.fromtimestamp(record["expires_at"], SEOUL).strftime("%H:%M")
                lines.append(f"{other} 사용량 한도로 멈춤 → {back} 복귀 예정")
            else:
                lines.append(f"{other} 사용량 한도(LIMITED)로 멈춤 → 남은 활성 도구 교차 승인으로 대체 진행")
    for card in _gate_stops(project, tool, moment):
        lines.append(f"{card} 진행 없이 다시 멈춰 자동 재시작 중단 → 다음 카드 대기")
    lines.extend(_schedule_waits(project, tool))
    return lines


def write_wait_status_report(project: Path, tool: str, *, now: float | None = None) -> dict[str, Any]:
    """U260: write human-readable `.coord/WAIT_STATUS.md` explaining exact wait reasons or confirming 100% completion."""
    moment = time.time() if now is None else now
    wait_lines = reasons(project, tool, now=moment)
    sched_path = Path(project) / ".coord" / "master_schedule.json"
    active_or_ready: list[str] = []
    done_count = 0
    if sched_path.is_file():
        try:
            sched = json.loads(sched_path.read_text(encoding="utf-8"))
            for ph in (sched.get("phases") or []):
                if not isinstance(ph, dict) or not ph.get("phase_id"):
                    continue
                st = str(ph.get("state") or "")
                if st in ("DONE", "DONE_SCOPED", "DONE_ELSEWHERE", "RETIRED", "SUPERSEDED"):
                    done_count += 1
                else:
                    active_or_ready.append(f"{ph['phase_id']}({st})")
        except (OSError, ValueError):
            pass
    all_done = len(active_or_ready) == 0
    headline = (
        f"✅ 모든 프로세스 완결 (완료 카드 {done_count}건, 잔여 진행 카드 0건 — 대기 작업 없음)"
        if all_done and not wait_lines
        else "⏸ 현재 대기·진행 사유: " + (" · ".join(wait_lines) if wait_lines else ", ".join(active_or_ready))
    )
    md_path = Path(project) / ".coord" / "WAIT_STATUS.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    body = [
        "# UAOS 실시간 대기·진행 상태 브리핑 (U260)",
        "",
        f"- **요약**: {headline}",
        f"- **전체 프로세스 완결 여부 (`all_done`)**: `{all_done}` (완료: {done_count}건, 잔여: {len(active_or_ready)}건)",
    ]
    if wait_lines:
        body.append("- **상세 대기 사유**:")
        for wl in wait_lines:
            body.append(f"  - {wl}")
    md_path.write_text(chr(10).join(body) + chr(10), encoding="utf-8")
    return {
        "ok": True,
        "all_done": all_done,
        "done_count": done_count,
        "remaining": active_or_ready,
        "reasons": wait_lines,
        "headline": headline,
        "report_path": str(md_path),
    }


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
