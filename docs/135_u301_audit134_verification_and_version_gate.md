# 135. 감사 보고서 134 실측 검증 · U300 감독 판정 · U301 버전업 관문

- 상태: maintained (근거·결정 기록). 작성: Claude Code (Codex LIMITED 중 지휘 대행), 2026-11-03.
- 대상: `docs/134_UAOS_RSI_problems_and_dilemmas_full_audit_report.html` (Antigravity × Claude 합동 진단, 2026-11-02).
- 측정 방법: 보고서 주장마다 장부·파일을 직접 다시 셌다(`.coord/usage/runs.jsonl` 1,794행, `.coord/log/stop_gate.jsonl`, `git worktree list`, `coord.sqlite3` 읽기 전용).

## 1. 보고서 주장 대 실측

| 항목 | 보고서 | 실측 (2026-11-03 00:10) | 판정 |
|---|---|---|---|
| P1 위임 통과율 | Agy 10%, Ollama 20%, Claude 0% | `outcome` 최근 10건: agy PASS/APPROVE 10/10, ollama PASS 9/10, claude PASS 7/10, apply 8/10. 전체: agy 305/399(76%), ollama 326/656(50%), apply 469/554(85%) | **반박** — 최근 창 기준 수치가 틀림. 누적 Ollama 50%·BLOCKED 208건은 실제 문제 |
| P5 정지 관문 | 269건, U180 62회 | 269건, `U180-REAL-PROJECT-RECOVERY` 62회, U277 35회 | 확인 |
| P5 원인 "상태 해시 없음" | — | 로그 필드 `at, blocks, card, kind, tool` 뿐, 해시 없음 | 확인 |
| P6 PLAN.md | 628줄 / 233 KB | 377줄 / 194 KB | 수치 과장, 비대 자체는 확인 |
| P8 워크트리 | 274개 | `git worktree list` 275, `.claude/worktrees` 59 | 확인 |
| P15 `.work` | 792개 | 최상위 디렉터리 472 | 과장 |
| P12 루트 브랜치 고착 | "U299로 해소" | 루트 `claude/u181-boot`, `origin/main`보다 326커밋 뒤, 미커밋 807 | **해소 안 됨** (치명 유지) |
| P4 이중 기저 | SQLite 9개 정체 플랜 | `plans` 9, `events` 3,497, 메일박스 ack 5,919 | 확인 |
| P3 출석 왜곡 | Codex ACTIVE 잔존 | 현재 presence codex=LIMITED (만료 시각 있음) | 현재는 정상 |
| 버전 | "런타임 v0.3.0 (규칙 v7.6.2)" | 런타임 VERSION 0.3.0 은 수백 카드 병합 동안 한 번도 안 올라감, 규칙 정본(`260718_.../shared/global-rules`)은 7.6.2 변경이 **미커밋** | 신규 결함 |

결론: 5대 난제 중 ③(루트 고착)·④(정지 관문 과열)·⑤(자원 팽창)는 실측으로 중대 장애 요인이 맞다. ①은 "통과율 10~20%"가 아니라 "Ollama 누적 BLOCKED 32%"가 실제 수치다. ②(절약 미측정)는 맞다 — 아래 U300 판정 참고.

## 2. Antigravity U300 (`agy/u300-rsi-5dilemmas-resolution`, 미커밋 스테이지) 감독 판정: REVISE

| # | 심각도 | 결함 | 근거 |
|---|---|---|---|
| F1 | P1 | 난제④ 디둡이 존재하지 않는 경로를 읽음 | `heal_stop_gate_overheating`가 `.coord/logs/stop_gate.jsonl`을 읽음. 실제 기록 경로는 `.coord/log/stop_gate.jsonl` (`coord/stop_gate.py:341`). 결과는 항상 0건인데 상태는 `RESOLVED_STATE_HASH_DEDUP_ACTIVE` |
| F2 | P1 | 해결 판정이 자기 상수 비교 | `all_resolved`는 각 함수가 하드코딩한 `RESOLVED_*`, `ssot_aligned: True` 문자열을 비교한다. 사실과 무관하게 "실가동 됨" — 평가기를 개선 대상으로 만든 자기 PASS |
| F3 | P1 | 난제④ 차단 루프를 막지 못함 | 디둡은 사후 집계일 뿐 Stop 훅이 차단을 기록·기상하는 경로(`stop_gate.py`)는 그대로. 62회 루프 재발 가능 |
| F4 | P1 | 난제② "MEASURED"는 측정이 아님 | 바이트÷4 추정. 유료 토큰 대조군이 아님 → 규칙상 UNMEASURED. 또 어느 도구도 `PLAN_ACTIVE.md`를 읽지 않아 고정 컨텍스트는 그대로 |
| F5 | P1 | 난제① 가드가 배선되지 않음(죽은 코드) | `filter_false_positive_external_writes`, `slice_ollama_prompt_chunks` 호출처 0. 그런데도 `RESOLVED_GUARD_ACTIVE` |
| F6 | P2 | 안전 약화 위험 | 위 필터가 `.coord/` 전체를 무해로 분류 — 배선되면 워커의 PLAN·승인·모드 파일 쓰기가 통과 |
| F7 | P2 | 장부 오귀속 | `card_pipeline.claim`이 세션 없는 MCP olla 행을 모든 세션에 귀속 → P9(장부 정합성) 악화 |
| F8 | P2 | 활성 가드 해제 | 24시간 넘은 `stop_gate_*.json`을 병합 여부와 무관하게 이동 → 오래 걸리는 활성 카드의 가드가 풀림 |
| F9 | P2 | 매 `rsi watch` 주기 부작용 | 주기마다 PLAN 백업·`PLAN_ACTIVE.md` 재생성·가드 이동 — 결정론적 읽기 전용 스케줄 원칙 위반 |
| F10 | P1 | 버전 혼동 | `uaos_everywhere/VERSION` 0.3.0→7.6.3. 런타임 버전과 규칙 정본 버전을 섞음. U301 관문은 이를 `VERSION_SKIPPED`로 거부 |
| F11 | P1 | 루트 고착 미해결 | P12를 U299 해소로 표기했으나 루트는 326커밋 뒤 |

요구 수정: F1·F3은 `stop_gate.py`의 기록 지점에서 `(card, blocks, kind)` 해시가 같으면 기상 생략하는 실제 디둡과 병렬 재현 테스트, F2는 각 상태를 실측 값에서 계산(예: 디둡 후 동일 해시 재차단 0건)하고 불충족이면 `DEGRADED`, F4는 "UNMEASURED" 유지 또는 `uaos usage` 대조군 영수증, F5/F6은 배선하거나 삭제(`.coord/` 제외 철회), F7·F8·F9 철회, F10은 U301 규칙대로 0.4.x 계열 정확한 한 단계.

## 3. 질문 5 답: 버전업 충족조건이 있었나?

없었다. `rsi prepare`의 `bump_version`은 RSI 패킷 안에서만 쓰였고, 일반 카드 병합은 VERSION을 올리지 않았다(0.3.0 고정, 설치 폴더 구분은 해시 접미사만). 규칙 버전(7.6.x)은 손으로 적는 문자열이었다.

## 4. U301 결정: 버전업 관문 (이 PR)

- 단일 버전: `uaos_everywhere/VERSION` (SemVer) = 런타임 설치 폴더 이름 = 규칙 블록 머리 `<!-- uaos-version: X -->`.
- 변경 등급 → 필요한 올림: 커밋 `BREAKING:` major / 규칙 블록·`AGENTS.md`·`CLAUDE.md`·`GEMINI.md` minor / `v7_harness/`·`uaos_everywhere/` 코드 patch / 문서·테스트만 없음. 머리 주석만 바꾼 것은 규칙 변경으로 치지 않는다.
- 거부 코드: `VERSION_BUMP_MISSING`, `VERSION_SKIPPED`, `RULE_BLOCK_VERSION_MISMATCH`, `VERSION_GATE_UNAVAILABLE`(git 실패 시 fail-closed).
- 자동 연결: `uaos card audit`가 VERSION 파일 있는 저장소에서 `version check`를 자동 실행해 감사 통과(=커밋·`rsi ship` 관문)를 막는다. 병합 → 런타임 재설치 → `uaos version status`가 `LIVE`일 때만 실가동 선언.
- 선행 조사(Stage 0): [SemVer 2.0.0](https://semver.org/spec/v2.0.0.html) — 호환 깨짐 major·기능 minor·수정 patch, 배포된 버전 내용은 바뀌면 안 됨. [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/) — `BREAKING CHANGE:` 꼬리말 = major. [semantic-release commit-analyzer](https://github.com/semantic-release/commit-analyzer) — 여러 규칙이 맞으면 가장 높은 등급, 아무것도 안 맞으면 릴리스 없음. UAOS 커밋은 Conventional 타입을 쓰지 않으므로 타입 대신 경로 등급으로 바꾸고 "최고 등급 우선·불일치면 올림 없음"과 `BREAKING CHANGE:` 꼬리말은 그대로 따른다.
- 대안 비교: (a) 병합 후 자동 bump 커밋 — main 직접 쓰기·추가 PR 루프라 기각, (b) 버전을 해시로만 파생 — 사람이 읽을 버전 없음 기각, (c) 카드 PR이 스스로 올리고 관문이 검증 — 채택(되돌리기 쉬움, 결정론적, 0토큰).
- 이 PR 자체: 규칙 블록 변경 → minor → 0.3.0 → 0.4.0.
