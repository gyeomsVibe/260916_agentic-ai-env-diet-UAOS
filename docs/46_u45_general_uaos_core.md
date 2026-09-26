# [U45] 범용 UAOS 예산·매뉴얼 핵심화 및 3도구 전역규칙 정제

- 상태: DONE (Antigravity 완결 대행 2026-09-26 · Codex 복귀 재검토 대상)
- 버전: `uaos_everywhere/VERSION` `0.2.0` (SemVer minor feature bump)
- 소유자: Antigravity (Codex 한도 도달에 따른 사용자 지시 무승인 완결 대행)

---

## 1. 개요 및 7대 핵심 목표 달성

U45는 특정 프로젝트에 국한되지 않고 모든 소프트웨어 프로젝트에 적용 가능한 범용 협업 운영 체계(Unified Agent Operating System)의 핵심 코어를 정식화한다.

1. **상태기계 예산 라우팅 (State-Machine Budget Routing)**:
   - 잔여율 퍼센트를 토큰으로 임의 환산하지 않음.
   - 실제 활성 상태(ACTIVE / LIMITED / ABSENT) 및 리셋 창(window) 기준 결정론적 라우팅.
2. **선행 2계층 매뉴얼 시스템 (Two-Tier Manual Hierarchy)**:
   - 프로젝트 시작 시: `.coord/PROJECT_MANUAL.md` (큰그림 아키텍처 및 승인 경계)
   - 작업 위임 시: `.coord/tasks/<TASK>.md` (계약 매뉴얼: 입력 해시, 허용 파일, 고정 인수, 원격 예산 상한)
3. **3단계 권한대행 체계 및 복귀 인계 (3-Tier Proxy & Resume Chain)**:
   - 1차: Codex 조율·판정
   - 2차: Codex 부재 시 Claude Code 부지휘자 대행
   - 3차: 둘 다 부재/한도 시 Antigravity 총괄 독자행동 대행
   - 복귀 시: `.coord/codex_return_checklist.md` 및 `coord inbox`로 인계 검증 후 지휘 복귀.
4. **올라마 계산기 원칙 (Ollama as Zero-Cost Local Calculator)**:
   - 유료 API 토큰 0원, 좁고 기계적인 치환/분류 전담.
   - 설계·판정·승인 권한 0 (인수 테스트 및 원문 대조만 판정).
5. **비파괴 보존 정책 (Deletion-Free Retention Planner)**:
   - `.coord/usage`, `.coord/pilot/runs`, `.coord/stream` 등 누적 기록을 age/count/bytes로 분류.
   - 기본은 `DRY_RUN` 매니페스트 해시 생성; 실제 삭제(`execute_delete=True`)는 항상 거부(`FRESH_DELETE_APPROVAL_REQUIRED`).
6. **SemVer 0.2.0 자동화 및 README 멱등 갱신**:
   - `uaos_everywhere/VERSION` 0.2.0 갱신.
   - README 최상단 갱신 섹션 유지.
7. **3도구 전역규칙 최소 핵심화 (Refined Invariants)**:
   - 공통 핵심 불변식(Common Invariants)을 일치시키고 도구별 어댑터를 간결화.
