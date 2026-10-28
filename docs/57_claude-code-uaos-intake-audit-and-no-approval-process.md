# 47. Claude Code UAOS 편입 계약 점검과 무승인 진행 절차 (U46 제안, 2026-09-26)

- 작성: Claude Code(Codex LIMITED 중 대행 지휘). **Codex 복귀 시 재검토 대상**이다.
- 계기: 사용자 지시(2026-09-26 15:4x) "claude code UAOS 편입 수용계약이 완성되지 않았나? 검사하고 개선해줘 / 너는 못하는 것이 너무 많아 사용자 계획과 너무 벗어난다 / claude code 무승인 진행 절차 프로세스를 완성하라 / 안티그래비티 CLI를 이용해야지".
- 기준 문서: docs/40(U38 편입 설계, 개정 A), docs/37(작업자 표), docs/44(건설적 자율 릴레이).

## 0. 쉽게 말하면

Claude Code는 U38에서 UAOS의 "작업자"로는 가입했다. 하지만 **지휘자로 일할 때 필요한 세 가지 손**이 없었다.

1. 판정자(Antigravity)를 **스스로 깨우는 손**이 없다. 우편함에 편지만 두고, 사용자가 Antigravity 창에 "처리해"라고 말해 줘야 움직였다.
2. 판정이 끝난 변경을 **정식으로 커밋하는 길**이 병합(merge) 커밋에는 없다. 그래서 막혔고, 결국 Antigravity가 `Calculator-Exempt`(계산기 관문 면제 줄)로 우회했다.
3. **어디까지 묻지 않고 해도 되는지** 표가 없다. 그래서 매번 멈추거나, 반대로 선을 넘을 뻔했다.

이 문서는 세 손을 채우는 계약과, 그 계약 안에서 묻지 않고 끝까지 가는 절차를 적는다.

## 1. 편입 계약 점검 결과 (2026-09-26 실측)

| # | 계약 항목 | 판정 | 근거 |
|---|---|---|---|
| C1 | `worker: claude` 유료 작업자 | PASS(결함 3) | U45-G7 a001 실제 호출 54,154 토큰·$0.319. 결함 F5(외부 쓰기 오탐)·F6(상한 +6% 초과)·F7(work_id 불일치를 지출 뒤에 검사) |
| C2 | `pilot review --reviewer claude` 읽기 전용 검증 | UNKNOWN | 코드·선택지 있음(`cli.py` `p_pilot_review`), 실제 호출 0회 |
| C3 | P1 벨을 다음 프롬프트에 주입 | PASS(소음) | 훅이 매 프롬프트 "P1 waiting (7)"를 출력. 7건은 U45 범위 밖 오래된 목록이라 매번 같은 소리 = ACK_ONLY여야 할 반복 |
| C4 | 출석·승계(누가 지휘하나) | PASS | U45-G1a/G1b APPLIED, `coord presence` JSON에 `conductor`, 테스트 6/6 OK |
| C5 | **지휘자 Claude → 판정자 Antigravity 호출** | **FAIL** | 우편함 JUDGE_REQUEST만 있음. 15:39 요청은 사용자가 Antigravity에 전달해서야 처리됨. `agy` CLI(`C:/Users/Kimyoongyeom/AppData/Local/agy/bin/agy`, `-p --output-format json --json-schema` 지원)를 판정에 쓰는 경로가 없다 |
| C6 | **판정 끝난 변경의 커밋 경로** | **FAIL** | 계산기 관문은 APPLIED digest가 있는 파일 커밋만 통과. 병합 커밋(이미 커밋된 두 부모의 합)을 위한 길이 없다. 결과: 6e02901·1e5b316 둘 다 `Calculator-Exempt` 줄로 우회 |
| C7 | 장부에 "누가 시켰나"(delegator) | FAIL | F4. Claude 지휘 비율을 잴 수 없다 |
| C8 | 무승인 범위 표 | FAIL | 규칙 곳곳에 흩어짐. 아래 §3으로 한곳에 모음 |
| C9 | Claude 권한 설정과 사용자 계획의 일치 | 부분 | `~/.claude/settings.json`이 `gh pr merge *`를 허용 → "자동 병합 금지"와 충돌. 반대로 일상 UAOS 명령(`uaos`, `python -m v7_harness.cli`, `python -m unittest`, 분기 브랜치 커밋)은 허용 목록에 없음 |

### 1-1. 재점검 (2026-09-26 18:3x, U46-H·U47-O1 뒤)

| # | 이전 | 지금 | 근거 |
|---|---|---|---|
| C1 | PASS(결함 3) | PASS | F5·F6·F7 적용(b4c0fba), 테스트 test_u46_followup_fixes |
| C2 | UNKNOWN | 결정 | 실호출 1회(18:29, U47-O1, sonnet-5): 경로 작동, 6턴 69초 $0.176, 그러나 94,953 토큰(캐시 읽기 62,408 포함) > 예산 80k → UNUSABLE. 검토 1회 최소비용이 ~95k이므로 예산 기본값을 120k로 올리거나 캐시 읽기를 별도 계산할지 결정 필요(U47-C2 카드) → 결정(2026-09-28, 사용자 위임·Claude 대행): 캐시 읽기는 계속 전액 계산하고, 검토 권장값을 `--budget 120000 --budget-usd 0.25`로 둔다(94,953×1.25≈118.7k, $0.176×1.4≈$0.25). `--budget`은 필수 인자 그대로. |
| C3 | PASS(소음) | PASS | P1 같은 지문 무음(U46-P1, b4c0fba) |
| C5 | FAIL | PASS | `pilot judge --judge agy` 실사용 1회: U47-O1 APPROVE, 65,078 토큰, 35초, 사람 전달 0회 |
| C6 | FAIL | FAIL | U46-G1 미구현(Codex·사용자 결정). b4c0fba가 면제 줄 사용 → U47-X1 재검토 |
| C7 | FAIL | PASS | 장부 `delegator` 필드(U45-F4, b4c0fba) |
| C8 | FAIL | PASS | §3 표 + docs/48 §4 예산 규칙 |
| C9 | 부분 | PASS | U46-S1 적용(16:02) |

통과 7/9(C4 포함), 부분 1(C2: 예산 기준), 실패 1(C6: 관문 결정).

## 2. 개선 설계

### 2-1. C5 해결 — `pilot judge --judge agy` (판정자를 CLI로 깨운다)

- 흐름: 파일럿이 먼저 인수 명령을 **직접** 돌린다 → 결과·diff·매뉴얼 전문을 담아 `agy -p ... --output-format json --json-schema <판정 스키마>`를 1회 호출 → Antigravity가 `{"verdict": "APPROVE|REJECT", "bundle_id", "evidence": [...]}`만 돌려준다 → 파일럿이 `verdict=APPROVE`이고 bundle_id가 일치할 때만 `--approve`를 실행하고 `coord_actor=antigravity`, `judge_conversation_id`, 판정 JSON 해시를 장부에 남긴다.
- 왜 이렇게: Antigravity는 셸 권한 없이 **읽고 판단만** 한다(`--dangerously-skip-permissions` 불필요, 원본 쓰기 없음). 승인 실행은 결정적 코드가 하므로 "Claude가 Antigravity 이름을 빌려 쓰는" 위조가 아니고, 판정 근거(대화 ID·JSON)가 남는다.
- 관문: 매뉴얼의 `judge`가 `antigravity`이고 작성자와 다를 것, B85 비용 관문(판정 토큰도 `remote_budget_tokens`에서 차감), 판정 1회(재시도 없음, 실패는 우편함으로 되돌림), 대기 폴링 없음(한 번 부르고 끝).
- 금지: Bridge MCP, 판정 없이 승인, 판정자=작성자.
- **기본 로직(사용자 결정 2026-09-26, U46-J4 APPLIED 16:21)**: 이 경로는 **Codex 부재 중 권한대행 절차**다.
  - Codex가 `ACTIVE`이거나 상태를 모르면(`UNKNOWN`, 심박 만료) → **Codex가 판정**한다. `pilot judge`는 `CODEX_JUDGES`로 거부한다.
  - Codex가 `LIMITED`·`ABSENT`로 기록돼 있으면 → 대행 Claude가 번들을 만들고 `pilot judge --judge agy`로 Antigravity에 **번들당 한 번** 전달한다. APPROVE면 하네스가 기존 `--approve` 관문을 실행한다. 사람이 우편함 편지를 옮길 필요가 없다.
  - Antigravity·Ollama가 쓴 번들은 대행 Claude가 판정한다(판정자≠작성자). Claude가 쓴 번들만 Antigravity가 판정한다.
  - Codex 복귀 후, 부재 중에 `pilot judge`로 적용된 번들(`runs/<task>/judge_agy.json`)을 Codex가 다시 검토한다.
  - U46-J4 자체는 Claude가 썼으므로 첫 판정은 Antigravity 우편함 편지로 받았다(부트스트랩, 16:21 APPLIED).

### 2-2. C6 해결 — 병합 커밋 경로 (관문 코드 변경이라 Codex·사용자 결정)

- 제안: 병합 커밋의 `v7_harness/*.py` 내용이 **(두 부모 중 하나의 내용) 또는 (APPLIED digest)**로 전부 설명되면 계산기 관문 통과. 새 내용이 한 줄이라도 있으면 지금처럼 거부.
- 평가기(관문)는 자기개선 대상이 아니므로 Claude는 구현하지 않고 카드만 올린다. 그동안 Claude는 **면제 줄을 쓰지 않는다**(사용자 규칙).

### 2-3. C3·C7·C9

- C3: P1 훅은 지문(최근 P1 id 목록 해시)이 직전과 같으면 출력하지 않는다(ACK_ONLY).
- C7: 장부에 `delegator` 필드(F4).
- C9: §4의 권한 제안.

## 3. Claude Code 무승인 진행 절차 (한곳에 모은 표)

"무승인"은 **아래 표의 초록 칸 안에서** 묻지 않고 끝까지 간다는 뜻이다. 빨간 칸은 사용자 규칙("멈추고 물을 것")과 Claude 안전 규칙이라 권한 설정으로도 열리지 않는다.

| 구분 | 묻지 않고 한다 | 조건(관문) |
|---|---|---|
| 읽기·조사 | 저장소·우편함·장부 읽기, 웹 조사 | 비밀값 파일(auth.json 등)은 읽지 않음 |
| 계획 | PLAN 카드 추가·상태 변경(REVIEW까지) | DONE은 작성자와 다른 판정자 증거가 있을 때만 |
| 문서 | docs·`.coord/notes`·매뉴얼 작성·수정 | 덮어쓰기 전 `.work/backup_<날짜>/` |
| 코드 | 코드 결정 → `worker: apply` 번들 → DRY_RUN_PASSED | 승인은 판정자(§2-1)가 |
| 작업자 호출 | Ollama 1회, Antigravity(`pilot run --worker agy`) 1회, `worker: claude` 1회 | 계약 매뉴얼 전문 전달, 예산 명시, B85 |
| 판정자 호출 | `pilot judge --judge agy`(구현 후) / 그 전엔 우편함 | 폴링 없음 |
| 검증 | 테스트·관문 직접 실행 | 실패는 숨기지 않음 |
| 커밋 | 판정 끝난 번들의 커밋, **작업 브랜치**에서 | 계산기 관문 통과. 면제 줄 금지 |
| push·PR 생성 | 사용자가 그 과제에서 명시 승인했을 때(U45처럼) | 자동 병합 금지 |
| **멈추고 묻는다** | 삭제, 명시 승인 없는 push·배포, 병합, 결제, 계정·권한·자격증명·시스템 설정 변경, 관문 우회 | — |

막혔을 때의 순서: 다른 도구(Bash↔PowerShell↔Edit)로 → 다른 작업자(apply→Ollama→Antigravity)로 → 과제를 쪼개서 → 그래도 막히면 **막힌 지점 한 줄 + 대안**만 사용자에게. 관문·분류기 거부를 다른 도구나 다른 에이전트로 돌아가는 것은 "다른 경로"가 아니라 우회다.

## 4. 권한 설정 제안 (사용자가 적용)

Claude가 자기 권한 설정을 스스로 넓히는 것은 안전 규칙상 하지 않는다(보안 설정 변경). 아래를 사용자가 `~/.claude/settings.json`에 반영하면 일상 UAOS 작업의 확인 창이 줄어든다. 파일: `.coord/notes/U46_claude_permissions_proposal.json`.

- 추가(allow): UAOS·파일럿·테스트 명령, 작업 브랜치 커밋, 워크트리 목록.
- 삭제(allow에서 빼기): `Bash(gh pr merge *)`, `PowerShell(gh pr merge *)` — 자동 병합 금지와 충돌.
- 추가(deny): `Bash(git push --force *)`, `Bash(git push -f *)`.
- 이 설정으로도 바뀌지 않는 것: 자동 모드 분류기의 관문 우회 거부(의도된 안전장치).

## 5. 카드

| ID | 내용 | 소유 | 선행 |
|---|---|---|---|
| U46-J1 | `pilot judge --judge agy` (§2-1) + 가짜 agy 테스트 | Claude 구현(apply) · 판정 Antigravity(우편함, 마지막 1회) · Codex 재검토 | — |
| U46-G1 | 병합 커밋 계산기 관문 경로(§2-2) | Codex·사용자 결정 | — |
| U46-P1 | P1 훅 동일 지문 무음(C3) | Claude 구현 · Antigravity 판정 | J1 |
| U45-F4 | 장부 delegator | 기존 카드 | — |
| U46-S1 | 권한 제안 적용(§4) | 사용자 | — |
