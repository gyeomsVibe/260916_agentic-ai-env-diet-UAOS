# U45 — 범용 UAOS 예산·매뉴얼 코어

- 상태: REVIEW (Codex 독립 인수 통과, 원격 push·PR 증거 대기)
- 기준선: `9ba28c4` (U42+U44), Antigravity 대행 커밋 `1e5b316`은 후보이며 독립 인수 전 DONE이 아니다.
- 소유자: Codex. Claude·Ollama·Antigravity는 아래 계약별 단일 작업자이며 최종 판정권이 없다.
- 승인: 이 U45의 전역 배포, commit, fetch, push, PR 생성. 금지: 자동 merge, 실제 삭제, 결제, 자격증명·권한 변경.

## 고정 목표

1. 잔여 퍼센트나 창을 토큰으로 환산하지 않는 `ACTIVE/LIMITED/ABSENT/UNKNOWN` 예산 상태기계.
2. 새 프로젝트의 큰그림 `.coord/PROJECT_MANUAL.md`와 위임별 작은그림 계약 매뉴얼을 먼저 발행하고 전체 내용을 호출에 포함.
3. Codex → Claude → Antigravity 대행과 복귀 시 독립 재검토.
4. Ollama는 좁은 기계 작업만 수행하고 로컬 토큰·벽시계·인수 결과를 기록.
5. retention은 age/count/bytes 후보·복구 manifest만 만들며 실제 삭제는 별도 최신 승인 없이는 거부.
6. 현재 `0.2.0`에서 feature SemVer bump와 README 최상단 멱등 갱신.
7. 세 도구 전역 규칙은 공통 최소 핵심과 짧은 역할 어댑터로 분리.

## 고정 관문

- red-first U45 테스트, U42/U44 회귀, 전체 unittest, compileall, `git diff --check`.
- 기존 고정 테스트 SHA-256 불변, 생산 코드의 test runner/test name/fixture 분기 0.
- fake HOME apply/check와 실제 HOME apply/check drift 0.
- 세 전역 설치 결과의 공통 불변식 일치, 역할 어댑터 최소 차이.
- 버전·README 업데이트와 `coord init` 멱등성.
- Claude·Ollama·Antigravity 각 1회 사용량 영수증과 원격 SHA.

## 조사 판정

- 공식 OpenAI 자료는 긴 `AGENTS.md`와 과도한 skill 설명이 컨텍스트와 준수도를 악화시킬 수 있어 필요한 규칙만 남기고 점진 공개하라고 권고한다.
- Anthropic 공식 자료는 짧고 구체적인 지침, 경로별 로딩, 중복 로딩 방지를 권고한다.
- Google 공식 Gemini CLI 자료는 `GEMINI.md`를 버전 가능한 playbook으로 취급한다.
- 논문·GitHub 구현은 선택적 위임과 부모 예산 귀속을 지지한다. Reddit 사례는 오케스트레이션 세금·무한 재시도·압축 뒤 계약 손실의 일화성 반례로만 사용한다.

## 호출 계약

- Claude: `U45_CLAUDE_ROLE_RULES`, 역할별 전역규칙 정제 1회, 토큰 180,000·USD 0.30·600초 상한.
- Ollama: `U45_LOCAL_RULE_CLASSIFY`, 공통/역할/프로젝트 특화 문장 기계 분류 1회, 900초 상한.
- Antigravity: `U45_AGY_FINAL_REDTEAM`, 마지막 읽기 전용 반례 1회, 토큰 120,000·600초 상한. 예산 초과 결과는 승인하지 않는다.

## 실행 영수증

- Claude: `U45_CLAUDE_ROLE_RULES`, 227,565 tokens, $0.306161, 101초, 상한 초과+외부쓰기 → ABANDONED/BLOCKED, 미승인.
- [올라마] 1차 `1124/89`, 약 16.4초, 검증기 격리 경로 실패. 2차 `932/165`, 약 19.1초, 분류 혼입·`CLAODE` 오타 → 두 결과 REWORK, 미승인.
- focused: U37+U42+U44+U45 76/76, compileall 0, diff-check 0.
- 설치: fake HOME apply/check 0·drift 0; 실제 HOME apply/check 0·drift 0; 백업 `C:\Users\Kimyoongyeom\.uaos-backups\20260926-192505`.
- 전체 회귀: 812/812 OK, skipped 4, 102.530초. U42/U44 고정 테스트 4개는 Git diff 0, 생산 코드 test-fitting 검색 0.
- Antigravity: `U45_AGY_FINAL_REDTEAM`은 206초 후 QUOTA, 0 tokens, bundle 없음, ABANDONED. 요청한 단 1회만 실행했고 advisory 결과는 UNKNOWN으로 남기며 재호출하지 않았다.
- 남은 원격 관문: 브랜치 commit/push, PR URL, 원격 branch SHA=HEAD 대조.
