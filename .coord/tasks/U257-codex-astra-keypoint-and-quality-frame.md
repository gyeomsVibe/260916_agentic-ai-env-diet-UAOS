# [U257] UAOS-RSI 기본 핵심 프레임(최대 성과·최상 품질) 및 Codex $20 Plus 아스트라 핵심 역량 집중·일반 승인 이관

## 0. 사전 근거자료조사 (Stage 0: Web Deep Research & Primary Sources)
- **검색 쿼리**: `OpenAI Codex CLI Plus 20 dollar subscription usage limits architectural review delegation multi-agent orchestration`
- **1차 출처 및 공개 저장소 증거**:
  1. OpenAI Codex CLI 공식 저장소 및 멀티에이전트/워크트리 아키텍처: https://github.com/openai/codex
  2. LangGraph Supervisor 계층형 멀티에이전트 라우팅(고비용 추론 모델은 상위 아키텍처/중재에만 배정하고 일반 검증은 피어 에이전트에 분산): https://github.com/langchain-ai/langgraph-supervisor-py
  3. Microsoft AutoGen 멀티에이전트 합의 및 역할 분리: https://github.com/microsoft/autogen
  4. ZDNet Korea — AI 코딩 에이전트 토큰 사용량 한도 및 구독제 비용 구조: https://zdnet.co.kr/view/?no=20261019165618
- **확인된 사실 (Facts)**:
  - $20/월 Plus 구독 기반의 Codex CLI는 5시간 롤링 윈도우 및 주간 캡(weekly cap)의 제약을 받으며, 고성능 추론 모델(Astra 등)을 일반 카드 리뷰·단순 승인에 반복 호출하면 수 분~수 시간 내에 `LIMITED`에 도달함.
  - 반면 핵심 아키텍처·보안 경계·전역 불변식 판정(`CODEX_EXCLUSIVE_KEYPOINTS`)에만 Codex를 투입하고, 일반 업무 승인(`ROUTINE_APPROVAL`)을 Claude Code와 Antigravity의 교차 승인(`author != judge`)으로 분산하면 $20 구독 안에서도 고성능 추론 모델을 안정적으로 지속 사용할 수 있음.

## 1~2. 기획 및 검증 (Stage 1~2: Frame & Verification Gate)
- **핵심 기본 프레임 (Founding Principle)**:
  - **"최대 성과를 목표로 3대 AI 도구 (Antigravity, Claude Code, Codex)의 부족한 토큰예산을 절약하는 3대 AI도구 '병렬'-협업-운영시스템, 하지만 결과물의 최상의 품질기준이 근본 존재이유이다."**
  - 사용량 제한 및 구독제 업그레이드의 재정적 부담을 해결하기 위해 UAOS-RSI를 만들었으나, 모든 프로세스의 근본 목적은 **최대 성과와 최상의 고품질 결과 도출**이다.
- **성공 신호 (Measurable Success Signal)**:
  1. `is_codex_exclusive_keypoint(phase)`가 핵심 키포인트(`architectural_core`, `security_boundary`, `rsi_canon`, `p1_escalation`, `final_quality_audit`, `tie_break`)를 판별해 Codex `ACTIVE` 시 Codex 판정을 보존함.
  2. 비핵심 일반 업무 승인(`REVIEW`)은 Codex가 `ACTIVE`이고 과부하 전(`active_load == 0`)이더라도 Claude Code / Antigravity(`author != judge`, `owner != judge`)로 자동 위임되어 Codex의 $20 Plus 아스트라 쿼터를 보존함.
  3. `verify_supreme_quality_gate(phase, judge_tool=...)`가 자기 승인(`SELF_APPROVAL_FORBIDDEN`), 인수 명령 누락(`MISSING_ACCEPT_CMD`), 인수 실패(`ACCEPT_GATE_FAILED`), 테스트 실패(`TESTS_FAILED`), 1차 출처 누락(`MISSING_PRIMARY_SOURCES`)을 거부하여 최상의 품질 기준을 강제함.

## 3~4. 큰계획 및 검증 (Stage 3~4: Master Plan & 4-Lens Review)
- **대안 비교**:
  - *대안 A (기존 U255)*: Codex가 과부하(`active_load >= 1` 또는 백로그 누적)일 때만 일반 리뷰를 오프로딩 -> 과부하에 도달하기 전까지 일상 리뷰가 Codex의 $20 Plus 아스트라 쿼터를 소모함.
  - *대안 B (채택 — U257)*: 모든 리뷰를 `CODEX_EXCLUSIVE_KEYPOINTS`와 `ROUTINE_APPROVAL`로 분류하여, 핵심 키포인트는 Codex에 집중 보존하고 일반 업무 승인은 선제적으로 Claude↔Antigravity 교차 승인(`verify_supreme_quality_gate` 강제)으로 라우팅함.
  - **판정**: `Go` (Value/Feasibility/Viability/Rollback 모두 충족).

## 5~8. 세부계획·계약·구현계획 및 검증 (Stage 5~8)
- **허용 수정 범위 (`allowed_files`)**:
  - `v7_harness/coord/agy_moderator.py`
  - `uaos_everywhere/uaos_global_rule_block.md`
  - `uaos_everywhere/adapters/codex.md`
  - `uaos_everywhere/adapters/claude.md`
  - `uaos_everywhere/adapters/antigravity.md`
  - `uaos_everywhere/skills/mia-strategic/SKILL.md`
  - `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`
  - `tests/test_u257_codex_keypoint_and_quality_frame.py`
- **안전 백업**: `.work/backup_20261027/`에 전역 규칙 파일 백업 완료.

## 9~10. 구현 및 최종 검증 (Stage 9~10: Implementation & Verification)
- `tests.test_u257_codex_keypoint_and_quality_frame` 및 기존 `tests.test_u255_agy_moderator_orchestrator` 전수 통과 확인 후 커밋·푸시·PR 병합·전역 런타임 재설치.
