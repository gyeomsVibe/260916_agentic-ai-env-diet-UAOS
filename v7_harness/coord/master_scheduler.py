"""UAOS-RSI Master Task Scheduler (마스터 작업 스케줄러).

3대 AI 도구(Codex, Claude Code, Antigravity)가 사용자 개입이나 복붙 없이
MIA 6단계 전략절차에 따라 티키타카(Tiki-Taka)로 끝까지 무승인 논스톱 완결할 수 있도록
프로세스 일정, 단계별 소유권, 선행 의존성, 완료 게이트를 총괄 제어하는 오케스트레이션 엔진.

언제 쓰는가 (When to Use):
1. 다단계 프로젝트/프로세스 착수 시 (단일 작업 카드가 아닌 다중 카드 파이프라인).
2. 도구 한도 소진/부재 후 복귀 시 (현재 진행 상태 및 차기 행동 0초 복원).
3. 단계 완료 후 타 도구로 작업 인계 시 (티키타카 소유권 전환 및 다음 단계 자동 언락).
4. 교착(Deadlock) 및 대기 상태 발생 시 (차단 원인 진단 및 자율 우회 경로 가동).

MIA 6단계 워크플로우 연계 (Workflow Integration):
- Step 0 (선행 딥리서치): 1차 출처 증거를 schedule의 research_evidence로 핀닝.
- Step 1 (기획/Frame): 성공 지표 및 마일스톤 등록.
- Step 2 (큰계획/Master Plan): Phase별 담당 도구(owner) 및 의존성(depends_on) 확정.
- Step 3 (중간점검/Mid-Check): 자원/토큰 예산 점검 및 Gate 판정.
- Step 4 (세부계획/Detailed Plan): 파일 범위(allow) 및 고정 인수 테스트 바인딩.
- Step 5 (최종점검/Final Check): 전체 인수 통과 및 최종 보고 생성.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

ToolType = Literal["codex", "claude", "antigravity", "all"]
PhaseState = Literal["PLANNED", "READY", "ACTIVE", "VERIFYING", "DONE", "BLOCKED"]


@dataclass
class PhaseItem:
    phase_id: str
    title: str
    owner_tool: ToolType
    mia_stage: str
    depends_on: list[str] = field(default_factory=list)
    state: PhaseState = "PLANNED"
    allowed_files: list[str] = field(default_factory=list)
    acceptance_cmd: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    blocker_reason: str = ""
    updated_at: str = ""


@dataclass
class MasterSchedule:
    schedule_id: str
    title: str
    goal: str
    current_phase_id: str
    phases: list[PhaseItem] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    max_turns_per_tikitaka: int = 5
    sound_notify_on_step: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MasterSchedule:
        phases = [PhaseItem(**p) for p in data.get("phases", [])]
        data_copy = dict(data)
        data_copy["phases"] = phases
        return cls(**data_copy)


def _play_ring() -> None:
    """Windows 시스템 알림음 송출 (U143)."""
    if os.name == "nt":
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            pass


class MasterTaskScheduler:
    """3대 도구 티키타카 무승인 논스톱 실행을 조율하는 마스터 스케줄러."""

    def __init__(self, project_root: Path | str = ".") -> None:
        self.project_root = Path(project_root).resolve()
        self.schedule_dir = self.project_root / ".coord"
        self.schedule_file = self.schedule_dir / "master_schedule.json"

    def init_default_schedule(self, schedule_id: str = "U144-MASTER", title: str = "3-Tool Seamless Pipeline") -> MasterSchedule:
        """기본 5단계 마스터 작업 스케줄 생성."""
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        phases = [
            PhaseItem(
                phase_id="P1-COMMS",
                title="통신 및 사서함 신뢰성 완전 복구 (F1 검증, F2 락 복구, U143 사운드)",
                owner_tool="antigravity",
                mia_stage="Step 4. 세부계획",
                depends_on=[],
                state="ACTIVE",
                allowed_files=["v7_harness/coord/deliver.py", "v7_harness/isolation/manifest.py"],
                acceptance_cmd="python -m unittest tests.test_u134_thread_fallback tests.test_u134_judge_counterexamples",
                updated_at=now,
            ),
            PhaseItem(
                phase_id="P2-UI-PRIORITY",
                title="사용자 컨트롤 인터페이스 1순위 안티그래비티 전환 및 장애전환",
                owner_tool="antigravity",
                mia_stage="Step 2. 큰계획",
                depends_on=["P1-COMMS"],
                state="READY",
                allowed_files=["docs/19_unified-agent-orchestration-design.md", "AGENTS.md"],
                updated_at=now,
            ),
            PhaseItem(
                phase_id="P3-MIA-STANDARDIZATION",
                title="MIA 전략스킬 6단계 표준 정본화 및 전역 도구 배포",
                owner_tool="all",
                mia_stage="Step 1. 기획",
                depends_on=["P1-COMMS"],
                state="READY",
                allowed_files=["C:/Users/Kimyoongyeom/.gemini/config/plugins/mia-modular-intelligence-architect/skills/mia-strategic/SKILL.md"],
                updated_at=now,
            ),
            PhaseItem(
                phase_id="P4-TIKI-TAKA-PIPELINE",
                title="3대 도구 티키타카 무승인 논스톱 오케스트레이션 가동",
                owner_tool="codex",
                mia_stage="Step 3. 중간점검",
                depends_on=["P1-COMMS", "P2-UI-PRIORITY", "P3-MIA-STANDARDIZATION"],
                state="PLANNED",
                allowed_files=[".coord/notes/U144_TIKI_TAKA_3TOOL_PIPELINE.md"],
                updated_at=now,
            ),
            PhaseItem(
                phase_id="P5-BUDGET-RSI-CLOSEOUT",
                title="토큰 예산 절약 및 RSI 장부 종합 검수 및 완결 보고",
                owner_tool="codex",
                mia_stage="Step 5. 최종점검",
                depends_on=["P4-TIKI-TAKA-PIPELINE"],
                state="PLANNED",
                allowed_files=[".coord/usage/runs.jsonl", ".coord/PLAN.md"],
                updated_at=now,
            ),
        ]
        schedule = MasterSchedule(
            schedule_id=schedule_id,
            title=title,
            goal="3대 도구(Antigravity, Codex, Claude Code) 티키타카 무승인 논스톱 완결",
            current_phase_id="P1-COMMS",
            phases=phases,
            created_at=now,
            updated_at=now,
            max_turns_per_tikitaka=5,
            sound_notify_on_step=True,
        )
        self.save_schedule(schedule)
        return schedule

    def load_schedule(self) -> MasterSchedule | None:
        """디스크에서 마스터 스케줄 로드."""
        if not self.schedule_file.exists():
            return None
        try:
            data = json.loads(self.schedule_file.read_text(encoding="utf-8"))
            return MasterSchedule.from_dict(data)
        except Exception:
            return None

    def save_schedule(self, schedule: MasterSchedule) -> None:
        """마스터 스케줄을 원자적으로 디스크에 저장."""
        self.schedule_dir.mkdir(parents=True, exist_ok=True)
        schedule.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        temp = self.schedule_file.with_suffix(".tmp")
        temp.write_text(json.dumps(schedule.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        temp.replace(self.schedule_file)

    def advance_phase(self, completed_phase_id: str, evidence: dict[str, Any] | None = None) -> PhaseItem | None:
        """한 Phase가 완료되었을 때 이를 DONE 처리하고 다음 종속 단계를 자동으로 READY/ACTIVE로 전환 (티키타카)."""
        schedule = self.load_schedule()
        if not schedule:
            return None

        found = False
        for p in schedule.phases:
            if p.phase_id == completed_phase_id:
                p.state = "DONE"
                p.evidence = evidence or {}
                p.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
                found = True
                break

        if not found:
            return None

        # 다음 활성화할 Phase 탐색 (선행 의존성이 모두 DONE인 것 중 첫 번째)
        next_phase: PhaseItem | None = None
        for p in schedule.phases:
            if p.state in ("PLANNED", "READY"):
                deps_done = all(
                    any(other.phase_id == d and other.state == "DONE" for other in schedule.phases)
                    for d in p.depends_on
                )
                if deps_done:
                    p.state = "ACTIVE"
                    p.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
                    schedule.current_phase_id = p.phase_id
                    next_phase = p
                    break

        self.save_schedule(schedule)

        if next_phase is not None:
            self._emit_schedule_wake(
                target=next_phase.owner_tool,
                phase_id=next_phase.phase_id,
                delta=f"ACTIONABLE_DELTA PHASE_ACTIVE {next_phase.phase_id}: {next_phase.title}",
                updated_at=next_phase.updated_at,
            )

        if schedule.sound_notify_on_step:
            _play_ring()

        return next_phase

    def _emit_schedule_wake(self, *, target: str, phase_id: str, delta: str, updated_at: str) -> None:
        """U253: emit a structured ACTIONABLE envelope to `.coord/mailbox` on phase transitions."""
        try:
            import hashlib
            from v7_harness.coord.mailbox import Mailbox

            resolved_target = "codex" if target == "all" else target
            digest = hashlib.sha256(f"sched-wake:{resolved_target}:{phase_id}:{updated_at}:{delta}".encode("utf-8")).hexdigest()
            msg_id = f"relay_{digest[:32]}"
            mb_dir = self.schedule_dir / "mailbox"
            mb_dir.mkdir(parents=True, exist_ok=True)
            box = Mailbox(mb_dir)
            box.publish(
                msg_id,
                {
                    "kind": "HANDOFF",
                    "actor": "scheduler",
                    "requested_target": resolved_target,
                    "card": phase_id,
                    "wake_class": "ACTIONABLE",
                    "delta": delta[:200],
                    "message": delta,
                    "digest": digest,
                },
            )
        except Exception:
            pass

    def mark_blocked(self, phase_id: str, reason: str) -> None:
        """특정 Phase가 차단되었을 때 이유를 기록하고 상태를 BLOCKED로 전환."""
        schedule = self.load_schedule()
        if not schedule:
            return
        blocked_phase: PhaseItem | None = None
        for p in schedule.phases:
            if p.phase_id == phase_id:
                p.state = "BLOCKED"
                p.blocker_reason = reason
                p.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
                blocked_phase = p
                break
        self.save_schedule(schedule)
        if blocked_phase is not None:
            self._emit_schedule_wake(
                target="codex",
                phase_id=blocked_phase.phase_id,
                delta=f"ACTIONABLE_DELTA PHASE_BLOCKED {blocked_phase.phase_id}: {reason}",
                updated_at=blocked_phase.updated_at,
            )

    def get_summary_report(self) -> dict[str, Any]:
        """간결한 현재 진행 요약 보고서 반환."""
        schedule = self.load_schedule()
        if not schedule:
            return {"status": "NO_SCHEDULE"}
        return {
            "schedule_id": schedule.schedule_id,
            "current_phase": schedule.current_phase_id,
            "phases": [
                {"id": p.phase_id, "state": p.state, "owner": p.owner_tool, "title": p.title}
                for p in schedule.phases
            ],
            "updated_at": schedule.updated_at,
        }
