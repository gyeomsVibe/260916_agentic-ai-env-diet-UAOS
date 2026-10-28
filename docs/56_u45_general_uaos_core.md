# [U45] 범용 UAOS 예산·매뉴얼 핵심화 및 3도구 전역규칙 정제

- 상태: REVIEW (Codex 복귀 독립 재구성, 2026-09-26)
- 버전: `uaos_everywhere/VERSION` `0.3.0` (현재 0.2.0 후보에서 feature minor bump)
- 소유자: Codex. Antigravity의 `1e5b316`은 출발 후보이며 고정 관문으로 재검토했다.

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
6. **SemVer 0.3.0 자동화 및 README 멱등 갱신**:
   - `uaos_everywhere/VERSION` 0.3.0 갱신.
   - README 최상단 갱신 섹션 유지.
7. **3도구 전역규칙 최소 핵심화 (Refined Invariants)**:
   - 공통 핵심 불변식(Common Invariants)을 일치시키고 도구별 어댑터를 간결화.

## 2. Codex 복귀 재검토 결과

- 기존 `1e5b316`은 U45 계약 카드·외부 조사·세 작업자 영수증·역할 어댑터·fake/실제 HOME drift 검증이 없어 DONE을 회수했다.
- `v7_harness/budget_route.py`와 `coord route`는 `ACTIVE/LIMITED/ABSENT/UNKNOWN`만 사용한다. 잔여율·리셋 창을 토큰으로 바꾸는 입력 자체가 없다.
- `coord init`은 큰그림 프로젝트 매뉴얼과 실제 `.coord/PLAN.md` SHA-256이 박힌 lint 가능 계약을 만들며 두 번째 실행은 바이트를 바꾸지 않는다.
- 설치기는 byte-identical 공통 블록 뒤에 Codex·Claude·Antigravity 중 해당 역할 어댑터 하나만 붙인다. 각 어댑터는 3개 bullet이다.
- retention의 age/count/bytes 후보·복구 manifest·별도 최신 삭제 승인 관문은 U42 고정 인수와 함께 회귀한다. 실제 삭제는 0건이다.

## 3. 작업자 영수증과 판정

- Claude `U45_CLAUDE_ROLE_RULES`: 227,565 tokens, $0.306161, 101초. 180,000 token/$0.30 상한 초과와 외부쓰기 감지로 ABANDONED; 결과 미승인.
- [올라마] `U45_LOCAL_RULE_CLASSIFY`: 1,124/89 tokens, 약 16.4초, 검증기 경로 오류로 REWORK. R2: 932/165 tokens, 약 19.1초, 분류 혼입·철자 오류로 REWORK. 두 bundle 모두 미승인.
- Antigravity `U45_AGY_FINAL_REDTEAM`: 읽기 전용 1회가 206초 후 QUOTA(0 tokens), bundle 없음, ABANDONED. 보고서는 UNKNOWN이며 재호출하지 않았다.
- 생산 변경은 Codex가 실패 후보를 원문 대조한 뒤 결정적 패치로 재구성했다. focused 76/76, 전체 812/812(skipped 4), compileall·diff-check 0, fake/실제 HOME apply/check drift 0을 독립 실행했다.

## 4. 외부 근거와 한계

- OpenAI·Anthropic·Google 공식 문서, 원 논문, GitHub 구현, Reddit 일화성 반례는 `docs/research/U45-general-uaos-sources.md`에 분리했다.
- 공급자 계정 한도 절감은 통제된 전후 비교가 없어 `UNMEASURED`다. 로컬 토큰은 유료 토큰 절감량이 아니다.
