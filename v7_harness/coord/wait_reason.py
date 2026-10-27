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


def _phase_title(project: Path, phase: dict[str, Any] | None, card_id: str) -> str:
    """U267: resolve a phase or card's concise Korean core title from the phase row or `.coord/cards/` / `.work/cards/`."""
    if isinstance(phase, dict):
        for key in ("title", "name", "summary", "topic"):
            val = phase.get(key)
            if isinstance(val, str) and val.strip():
                from ..card_pipeline import clean_core_title, is_bare_id_label

                cleaned = clean_core_title(val)
                if cleaned and not is_bare_id_label(cleaned):
                    return cleaned
    from ..card_pipeline import card_title

    return card_title(project, card_id)


def _schedule_waits(project: Path, tool: str) -> list[str]:
    """U263: surface live REVIEW / peer-ACTIVE waits from `.coord/master_schedule.json` using observed fields only."""
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
        title = _phase_title(project, phase, pid)
        prefix = f"[{title}] " if title else ""
        if state == "REVIEW":
            reviewer = str(phase.get("reviewer") or "unspecified")
            author = str(phase.get("author_tool") or phase.get("owner_tool") or "unspecified")
            waiting_on = str(phase.get("waiting_on") or "verdict-pending")
            out.append(f"{prefix}{pid} 판정 대기 중(state=REVIEW, 작성={author}, 판정자={reviewer}, 대기사유={waiting_on})")
        elif state == "ACTIVE":
            owner = str(phase.get("owner_tool") or "")
            if owner and owner != tool:
                waiting_on = str(phase.get("waiting_on") or "in-progress")
                out.append(f"{prefix}{pid} 작업 대기 중(state=ACTIVE, 담당={owner}, 대기사유={waiting_on})")
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
                lines.append(f"{other} 사용량 한도로 멈춤(state=LIMITED, 복귀시각 미정)")
    for card in _gate_stops(project, tool, moment):
        title = _phase_title(project, None, card)
        prefix = f"[{title}] " if title else ""
        lines.append(f"{prefix}{card} 진행 없이 다시 멈춰 자동 재시작 중단 → 다음 카드 대기")
    lines.extend(_schedule_waits(project, tool))
    return lines


DONE_STATES = ("DONE", "DONE_SCOPED", "DONE_ELSEWHERE", "RETIRED", "SUPERSEDED")
ACTIVE_STATES = ("READY", "ACTIVE", "REVIEW", "WAITING", "BLOCKED", "IN_PROGRESS", "PENDING", "QUEUED")


def write_wait_status_report(project: Path, tool: str, *, now: float | None = None) -> dict[str, Any]:
    """U263: write human-readable `.coord/WAIT_STATUS.md` explaining observed wait reasons or completion state."""
    moment = time.time() if now is None else now
    wait_lines = reasons(project, tool, now=moment)
    sched_path = Path(project) / ".coord" / "master_schedule.json"
    active_or_ready: list[str] = []
    done_count = 0
    schedule_valid = False
    has_malformed = False
    if sched_path.is_file():
        try:
            sched = json.loads(sched_path.read_text(encoding="utf-8"))
            phases = sched.get("phases") if isinstance(sched, dict) else None
            if isinstance(phases, list) and len(phases) > 0:
                for idx, ph in enumerate(phases):
                    if not isinstance(ph, dict):
                        has_malformed = True
                        active_or_ready.append(f"INVALID_ROW_{idx}(non-dict)")
                        continue
                    pid = ph.get("phase_id")
                    st = ph.get("state")
                    pid_ok = isinstance(pid, str) and bool(pid.strip())
                    st_ok = isinstance(st, str) and st.strip() in (DONE_STATES + ACTIVE_STATES)
                    if not pid_ok or not st_ok:
                        has_malformed = True
                        label_id = pid.strip() if pid_ok else f"INVALID_ROW_{idx}"
                        label_st = st.strip() if isinstance(st, str) and st.strip() else "missing-state"
                        active_or_ready.append(f"{label_id}({label_st})")
                        continue
                    st_clean = st.strip()
                    if st_clean in DONE_STATES:
                        done_count += 1
                    else:
                        title = _phase_title(project, ph, pid.strip())
                        label = f"{title}({pid.strip()}, {st_clean})" if title else f"{pid.strip()}({st_clean})"
                        active_or_ready.append(label)
                schedule_valid = not has_malformed and (done_count + len(active_or_ready) > 0)
        except (OSError, ValueError):
            schedule_valid = False
    if not schedule_valid:
        status_state = "UNKNOWN"
        all_done = False
        headline = "❓ 일정 상태 미확인(UNKNOWN): 유효한 .coord/master_schedule.json 일정이 없습니다"
    else:
        all_done = done_count > 0 and len(active_or_ready) == 0 and len(wait_lines) == 0
        status_state = "ALL_DONE" if all_done else "WAITING"
        headline = (
            f"✅ 모든 프로세스 완결 (완료 카드 {done_count}건, 잔여 진행 카드 0건 — 대기 작업 없음)"
            if all_done
            else "⏸ 현재 대기·진행 사유: " + (" · ".join(wait_lines) if wait_lines else ", ".join(active_or_ready))
        )
    md_path = Path(project) / ".coord" / "WAIT_STATUS.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    body = [
        "# UAOS 실시간 대기·진행 상태 브리핑 (U263)",
        "",
        f"- **상태 (`state`)**: `{status_state}`",
        f"- **요약**: {headline}",
        f"- **전체 프로세스 완결 여부 (`all_done`)**: `{all_done}` (완료: {done_count}건, 잔여: {len(active_or_ready)}건)",
    ]
    if wait_lines:
        body.append("- **상세 대기 사유**:")
        for wl in wait_lines:
            body.append(f"  - {wl}")
    md_path.write_text(chr(10).join(body) + chr(10), encoding="utf-8")
    return {
        "ok": schedule_valid,
        "state": status_state,
        "all_done": all_done,
        "done_count": done_count,
        "remaining": active_or_ready,
        "reasons": wait_lines,
        "headline": headline,
        "report_path": str(md_path),
    }


def stop_output(result: dict[str, Any] | None, project: Path, tool: str, *,
                now: float | None = None) -> dict[str, Any] | None:
    """The Stop hook's JSON: writes `.coord/WAIT_STATUS.md` for all tools, plus `systemMessage` where supported."""
    try:
        write_wait_status_report(project, tool, now=now)
    except OSError:
        pass
    if tool not in SHOWS_SYSTEM_MESSAGE:
        return result
    lines = reasons(project, tool, now=now)
    if not lines:
        return result
    out = dict(result or {})
    out["systemMessage"] = "⏸ 대기·멈춤 이유: " + " · ".join(lines)
    return out
