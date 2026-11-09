# [U299] 3대 도구 도우미·추론 모델 자동 오케스트레이션 및 카드별 병렬 세션 가동 표준화 — RSI 자가개선 상시 세션 기록·스케줄링 및 워크스페이스 정제 실가동 설계서

- **카드 ID**: `U299`
- **작성 도구**: `Antigravity` (`Claude Code` 비작성자 교차 판정 및 합의)
- **전역 규칙 버전**: `v7.6.2` (`~/.uaos/uaos.py` 라이브 런타임 연동)
- **상시 RSI 세션 경로**: `.coord/rsi/sessions/U299-HELPER-THINKING-CARD-PARALLEL-OS/`

---

## 1. 배경 및 전수조사 요약 (MIA 11단계 전략 프레임워크)

Codex 사용량 제한(`LIMITED`) 중 `Claude Code`와 `Antigravity`의 상호 합의 무승인 대행 체제에서 워크스페이스(`D:\D_Workspace_NB\-agentic-ai-workspace\260916_agentic-ai-env-diet`)와 이전·중단 카드별 병렬 세션(`U276~U298`), 마스터 스케줄(`.coord/master_schedule.json`), 세부 스케줄(`.coord/sub_process_schedule.json`)을 전수 감사하여 다음 5대 핵심 과제를 도출·해결하였다.

| 구분 | 발견된 문제점 (`P1~P16`) | 해결 설계 및 구현 (`D1~D13` / `U299`) |
|---|---|---|
| **1. 카드별 병렬 세션 & 도우미·추론 모델 결합** | `build_card_parallel_launch_spec`(`card_sessions.py`)이 카드별 격리 워크트리·세션 스펙만 생성하고, `helper_thinking_router.py`(`select_optimal_helper_and_thinking`)의 도우미·추론 모델 및 추론 강도(`Low`/`Medium`/`High`) 선정 결과를 런처 스펙에 직접 주입하지 않음 (`P14`). | `build_card_parallel_launch_spec` 내부에 `select_optimal_helper_and_thinking`을 직결하여 `helper_thinking_selection` 및 도구별 네이티브 런처 설정을 자동 바인딩. |
| **2. 마스터 스케줄 빈 ID(`sched_`) 및 병합 완료 카드 잔류** | `.coord/master_schedule.json`의 `phase_id` 키만 있는 항목이 `collect_pending_processes`에서 빈 `sched_` 항목으로 생성되고, 이미 병합 완료된 13개 카드(`U276, U280, U284, U287, U290, U291, U292, U293, U294, U295, U296, U297, U298`)의 창과 요청(`.coord/requests/`)이 `OPEN`으로 남아 `STOP_UNGUARDED` 오탐 유발 (`P13`, `P15`). | `collect_pending_processes`에서 `phase.get("id") or phase.get("phase_id")`를 읽도록 수정하고, `reconcile_merged_card_windows_and_schedule`로 병합 완료 카드 창을 `MERGED_RELEASED`로 전환 및 잔류 요청을 `.coord/requests/closed/`로 무삭제 아카이빙. |
| **3. 워크스페이스 누적 덤프·가비지 전수 분류** | `.work/` 하위 790개 디렉터리, `git worktree` 274개, `.claude/worktrees` 59개, `.coord/presence/stop_gate_*` 26개 등 누적 가비지가 분류 없이 방치됨 (`P1`, `P12`). | Safety 인간 전용 삭제 경계를 엄수(`deleted_count=0`)하면서 `build_workspace_garbage_manifest`로 활성 보호 대상(`active_protected`)과 회수 후보(`pilot_staging_candidates`, `worktree_candidates`)를 `.coord/rsi/workspace_garbage_manifest.json`에 정밀 기록. |
| **4. 3대 도구 도우미·추론 모델 + 병렬 세션 불변식 자동 검증** | 3대 도구(`Codex`, `Antigravity`, `Claude Code`) × 5대 레인(`IMPL_CODE`, `VERIFY_AUDIT`, `ARCH_DESIGN`, `MERGE_RELEASE`, `RECOVERY_OPS`) × 5단계 세부 공정(`SP1~SP5`)의 도우미·추론 강도 자동 선정과 카드별 워크트리 격리 스펙을 일괄 검증하는 헬스체크 부재. | `verify_helper_parallel_os_health`를 구현하여 3대 도구 모델 라인업·추론 강도(`Low`/`Medium`/`High`), `1 Card = 1 Fresh Worktree Session`, 스케줄 무결성을 결정론적으로 검증. |
| **5. RSI 자가개선 상시 세션 기록 및 정기 스케줄링** | `uaos rsi watch` 주기 실행 시 `U299-HELPER-THINKING-CARD-PARALLEL-OS` 상시 세션을 자동 갱신하는 파이프라인이 없고 Windows 작업 스케줄러(`UAOS_RSI_Watch_39af1fc5`)가 미등록(`TASK_MISSING`) 상태 (`P14`). | `sync_and_record_helper_parallel_rsi_session`을 `coord lanes --action sync-helper-parallel-rsi`와 `cmd_rsi_watch`에 통합하고, Windows 작업 스케줄러(`uaos rsi schedule --action install --apply`)에 등록하여 상시 자동 갱신 완결. |

---

## 2. 3대 도구 도우미 모델·추론 강도(Thinking Level) 자동 선정 표준 매트릭스

1. **공통 0유료 토큰 계산기**:
   - `Ollama CLI` (`qwen2.5-coder:7b`): `local_read_map`, `local_search`, `local_draft`, `20~30줄 코드 슬라이스`를 전담(목표 비중 50%).
2. **도구별 전용 도우미 모델(목표 비중 30%) 및 주력 추론 모델(목표 비중 20%)**:
   - **Codex**: 도우미 `GPT-6 Luna` (`gpt-6-luna`, 보조 `gpt-5.6-luna`/`gpt-5.6-terra`) + 주력 추론 `GPT-6.1 Sol/Terra`, `GPT-6 Astra` (`reasoning_effort`: `low` / `medium` / `high`).
   - **Antigravity**: 도우미 `Gemini 3.8 Flash` (`gemini-3.8-flash`, 보조 `gemini-3.7-flash`/`gemini-3.6-flash`/`gpt-oss-120b`) + 주력 추론 `Gemini 4 Argon`, `Gemini 3.1 Pro`, `Claude Sonnet/Opus 5.5 (thinking)` (`thinking_level`: `LOW` / `MEDIUM` / `HIGH`).
   - **Claude Code**: 도우미 `Claude Haiku 5.5` (`claude-haiku-5-5`, 사전 상한 `12,000 tok`) + 주력 추론 `Claude Opus 5.5`, `Claude Sonnet 5.5` (`effort`: `low` / `medium` / `high`).

---

## 3. 상시 RSI 세션 및 CLI 운용 명령

- **상시 RSI 세션 즉시 동기화 및 기록**:
  ```bash
  python "$HOME/.uaos/uaos.py" coord lanes --project . --action sync-helper-parallel-rsi
  ```
- **정기 스케줄러 상태 확인 및 실행**:
  ```bash
  python "$HOME/.uaos/uaos.py" rsi schedule --project . --action status
  python "$HOME/.uaos/uaos.py" rsi watch --project .
  ```
- **생성·갱신 산출물**:
  - `.coord/rsi/sessions/U299-HELPER-THINKING-CARD-PARALLEL-OS/SESSION.json`
  - `.coord/rsi/sessions/U299-HELPER-THINKING-CARD-PARALLEL-OS/CONTINUATION.json`
  - `.coord/rsi/sessions/U299-HELPER-THINKING-CARD-PARALLEL-OS/REPORT.md`
  - `.coord/rsi/sessions/U299-HELPER-THINKING-CARD-PARALLEL-OS/HEALTH_TELEMETRY.json`
  - `.coord/rsi/workspace_garbage_manifest.json`
