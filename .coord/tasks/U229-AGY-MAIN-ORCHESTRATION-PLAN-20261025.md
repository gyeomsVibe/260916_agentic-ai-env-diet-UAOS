# Antigravity 사용자 메인 인터페이스 전환 및 3도구 협업 오케스트레이션 진행 계획표 (2026-10-25)

## 1. 운영 모드 전환 선언 (사용자 지시 반영)
- **메인 사용자 인터페이스(User Desk Main)**: **Antigravity** (`[사용자 대화창구-261025-1]`, thread: `96f7e6a1-6ad1-4b05-bdec-a214323ce91e`)
- **전환 사유**: Codex 및 Claude Code의 잔여 사용량(Quota) 임박으로 인해 사용자 직접 응대·총괄 브리핑·일정 조율 창구를 Antigravity로 일원화.
- **도구별 역할 재편**:
  1. **Antigravity (메인 인터페이스 · 총괄 조율 · 독립 감사 · 병합 1순위)**:
     - 사용자 창구 브리핑 및 오케스트레이션 지휘
     - 독립 코드/계약 감사(Audit) 및 고정 인수 게이트 판정
     - PR 병합(`coord merge`) 및 런타임 배포 검증
  2. **Claude Code (핵심 구현 · 최소 토큰 워커)**:
     - 대화형 소모를 멈추고, 핵심 구현(U234 등) 및 패치/커밋 단위의 짧고 결정적인 작업만 수행
     - 로컬 Ollama 계산기를 우선 활용한 뒤 결과물만 우편함(`coord deliver`)으로 보고
  3. **Codex (최종 아키텍처 승인 · 잔여 쿼터 보호 모드)**:
     - 상시 폴링/장문 응답 중단, 필수 아키텍처/릴리스 판정 시에만 최소 토큰으로 참여
  4. **Ollama (0토큰 로컬 전자계산기)**:
     - 코드 맵(`local_read_map`), 초안/요약(`local_draft`), 반복 변환 전담

## 2. 마스터 스케줄 협업 오케스트레이션 진행 계획표

| 단계 (Phase / Card) | 핵심 과업 | 담당 (Owner) | 검증/협업 (Judge / Peer) | 목표 산출물 및 완료 게이트 | 현재 상태 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Step 1: U234** (`U229-C`) | 타이틀 합의 작성기(`title_consensus.py`) 및 시맨틱 스케줄 해시 구현·감사 | 구현: Claude<br>감사: Antigravity | 고정 인수 5케이스 (`test_u229_consensus_acceptance.py`) | 5/5 PASS 확인 완료 (`.claude/worktrees/user-conversation-setup-6aa5f9`) → Antigravity 감사 APPROVE 통지 및 커밋 | **AUDIT PASS / 커밋 진행** |
| **Step 2: U229 Title Vote** | 3대 도구 실제 네이티브 타이틀 투표 (`coord title-vote`) 및 사이드바 반영 | 3대 도구 각 1표 (Antigravity 선도) | SQLite 쿼럼(3/3) 성립 확인 | `master_schedule.json` 무변경 상태에서 3도구 합의 토픽 등록 | **READY (U234 직후)** |
| **Step 3: U229 B2 Release** | B2 호출 원장·글로벌 정책 정식 커밋 및 런타임 재설치 | 구현 보존: Claude<br>릴리스: Antigravity | Codex/Antigravity 교차 검증 (`check drift=[]`) | `0.3.0` 정식 커밋·PR 병합 및 `~/.uaos/runtime` 동기화 | **READY** |
| **Step 4: U221 / U222 / U225** | 공통 워커 사용량 회계 통합 및 논스톱 쿼터 복구 카드 마감 | Antigravity 총괄 (로컬 테스트 우선) | 기존 영수증 대조 및 회귀 스위트 | 미결 통합 브랜치 정리 및 `master_schedule.json` DONE 갱신 | **QUEUED** |
| **Step 5: U230** | MIA 무승인 논스톱 티키타카 파이프라인 전면 가동 | Antigravity 주도 + 3도구 릴레이 | 스톱 게이트 및 자동 워처(0토큰) 무결성 | 사용자 개입 없는 카드 연쇄 실행 루프 완결 | **QUEUED** |

## 3. 참고 1차 출처 (근거 데이터)
- Python `sqlite3` 트랜잭션 제어: https://docs.python.org/3/library/sqlite3.html
- Python `os.replace` 원자적 파일 교체: https://docs.python.org/3/library/os.html#os.replace
- Git `git-worktree` 격리 작업 트리 명세: https://git-scm.com/docs/git-worktree
