# 40. Claude Code를 UAOS 파이프라인에 참여시키는 설계 (U38 제안, 2026-09-25)

- 상태: **구현됨(2026-09-25, 사용자 지시 "claude code UAOS 정식 가입")**. 이번 과정은 Claude 주도·Codex 보조, 무승인 진행이다.
  - B85 예산 관문 `1d9bcc0`, U38 작업자·검증자·P1 대행 `dc474aa`, 계약의 `model:` 칸.
  - 테스트 `tests/test_u38_cost_gate_and_claude_worker.py`는 가짜 `claude`로 네트워크 없이 돈다. 돌연변이 5종(`--bare` 제거, 환경 정리 제거, `.coord` 쓰기 차단 제거, 작성자 검사 제거, 검토 도구 거부 제거)을 모두 잡는다.
  - **아직 실제 유료 실행은 0회다.** 첫 실행은 사용자 PC에서 Codex가 매뉴얼 `U38-C1`로 한다(메모 76).
  - 구현 중 설계에서 바뀐 점이 둘 있다. 작업자 표기는 요약 파일이 아니라 `runs/<task>/worker` 파일에 둔다(요약 키 수 제한). 작성자를 알 수 없으면 검토를 거부한다(fail-closed).
- 판정: Codex.
- 선행 조건:
  - B85(원격 예산 관문)를 먼저 고친다. 유료 작업자가 하나 더 늘기 때문이다.
  - B83 fail-closed를 푸시한다.
- 근거 코드: `v7_harness/adapters/lane_worker.py`. 이 저장소는 이미 `claude -p`(헤드리스 실행)를 도구 제한·테스트 보호·최대 턴 수·JSON 사용량 출력과 함께 쓴다. 단, 모델은 로컬 Ollama로 돌려 두었다. 이번 설계는 그 검증된 호출을 **유료 Claude 계정 쪽으로** 돌리는 것이 핵심이다.

## 개정 A (2026-09-25, Codex 보조 감사 반영) — 먼저 읽을 것

Codex가 사용자 PC의 Claude Code 2.1.281과 실제 `claude --help`·인증 상태로 설계를 검증했다. 그 결과 아래 본문의 일부가 바뀌었다. **이 절이 본문보다 우선한다.**

| # | 감사 결과 | 바뀐 설계 | 코드·테스트 |
|---|---|---|---|
| A1 | `--bare`는 OAuth·키체인을 읽지 않고 API 키만 받는다. 사용자 PC는 claude.ai(Pro) 로그인이라 **인증에 실패한다**. UAOS는 비밀값을 읽거나 넣지 않는다 | 작업자·검증자 모두 `--safe-mode --restricted --permission-prompts none` + 도구 허용 목록을 쓴다. **`--bare`는 쓰지 않는다.** 이 조합이 훅 억제·루트 격리·설정/출석 무기록을 실제로 보장하는지는 **가설**이다. 가짜 CLI 테스트와, 따로 승인된 실제 유료 호출 1회로 증명한다. UAOS 자체 훅은 `UAOS_WORKER`로 이미 무기록이다 | `claude_worker.ISOLATION`, argv에 `--bare`가 없는지 확인하는 테스트 |
| A2 | 예산 옵션은 UNKNOWN이 아니었다. `--max-budget-usd`가 있다 | 계약에 `remote_budget_usd`를 **필수**로 둔다(lint `REMOTE_WITHOUT_USD_CAP`). 이 값이 `--max-budget-usd`로 전달되는 지출 전 상한이다. 값이 없으면 작업자가 시작 자체를 거부한다(`NO_USD_CAP`). 사후 토큰 관문(B85)도 유지한다. 달러를 토큰에서 추정하지 않고, 토큰 종류와 `total_cost_usd`는 따로 기록한다 | `test_the_claude_worker_refuses_to_start_without_a_dollar_cap` 외 |
| A3 | 매뉴얼 없는 `--prompt`로 유료 작업자를 부르면 예산 관문을 **우회**했다. 승인도 마찬가지였다 | 유료 작업자(agy·claude)는 매뉴얼 필수(`REMOTE_WITHOUT_MANUAL`). 매뉴얼 없는 cascade의 유료 승격은 거부한다. 승인은 **기록된** `cost_gate=WITHIN`이 있어야 한다. 승인 호출이 어떤 작업자·플래그를 대든 상관없다(`runs/<task>/worker`와 현재 명령 모두 확인) | `test_a_paid_worker_without_a_manual_is_refused`, `test_approval_needs_a_persisted_within_gate_whatever_the_flags` |
| A4 | 신원이 섞였다 | **클라우드 Claude = 현재 파이프라인 주도·계획자(PR 채널)**, **로컬 Claude CLI 하위 프로세스 = 유료 작업자.** `worker: claude`는 이미 실행 중인 클라우드 세션에 연결되거나 그 세션을 재사용하지 않는다 | — |
| A5 | 자동화 안의 `judge: user`는 인증되지 않은 문자열이다(B83과 같은 부류) | 자동 승인의 경계가 될 수 없다. 경계는 **실제 사람의 GitHub 검토·병합**이다. 검증자(`pilot review`) 출력도 경계가 아니다 | — |
| A6 | 유료 검토에도 같은 상한이 필요하다 | `pilot review`에 `--budget-usd`를 필수로 두고, 토큰 예산·장부·한도 공유 보호(LIMITED)도 작업자와 같게 한다 | `test_a_paid_review_needs_a_dollar_cap` |
| A7 | 다음 프롬프트 때 P1 알림은 괜찮다 | 유지한다. 자동 재개와 유료 폴링 금지도 유지한다 | — |
| A8 | Windows 30분 PR 모니터가 작업 스케줄러에서 exit 1이었다 | Codex가 수리했다(`updatedAt`만 보는 ASCII 안전 조회, exit 0). 무인 운영의 전제 조건으로 기록한다 | Codex 보고 |
| A9 | 사용자의 배정 규칙 | U39 상태 기계: 결정적 → Ollama 1회(FORMAT_ONLY만 1회 더) → Antigravity 1회(상한 120k) → 판정. 원격이 실패하면 과제를 쪼개고 로컬로 돌아가지 않는다 | `v7_harness/routing.py`, docs/41 |

- 실제 유료 호출은 아직 0회다.
- 첫 호출 전에 Codex가 Windows 재검증과 `claude --help`에서 `--safe-mode`·`--restricted`·`--permission-prompts`·`--max-budget-usd`가 있는지 확인한다(메모 77).

---

## 0. 쉽게 말하면 (ELI10)

- 지금 Claude Code는 팀에서 **부대장**(계획·판정)이고 출석부에도 이름이 있다. 하지만 **작업 줄(pipeline)에 손으로 참여하지는 않는다**.
  - 파일럿(격리된 사본에서 일하고 검사를 통과해야 반영되는 절차)에 넣을 수 있는 작업자는 apply(복사기), Ollama(계산기), Antigravity(원격 친구), lane(로컬 모델을 Claude Code 방식으로 움직임)뿐이다.
  - 급한 알림(P1) 벨도 Codex에게만 울린다.
- 이 설계는 Claude Code에게 파이프라인 안의 자리 네 개를 준다.
  1. **작업자**: 계약서를 받아 격리 사본에서 코드를 고친다.
  2. **검증자**: 다른 작업자의 결과를 읽기만 하며 반례를 찾는다.
  3. **알림 수신자**: Codex가 없을 때 급한 일을 이어받는다.
  4. **기록자**: 출석·사용량·결과를 남긴다.
- 대신 규칙이 두 개 붙는다.
  - 자기가 한 일은 자기가 판정하지 못한다.
  - 유료 토큰은 계약서에 적힌 예산 안에서만 쓴다.

## 1. 현재 상태 — 어디에 참여하고 어디서 빠져 있나

| 파이프라인 단계 | Codex | Claude Code(현재) | Antigravity | Ollama |
|---|---|---|---|---|
| 계획·PLAN 카드 | ✔ 지휘 | ✔ Codex 부재 시 대행 | 제안만 | ✗ |
| 계약 매뉴얼 작성 | ✔ | ✔ | ✗ | ✗ |
| **파일럿 작업자**(`pilot run --worker`) | ✗ | **✗ 없음**(lane은 Claude CLI를 쓰지만 로컬 모델) | ✔ `agy` | ✔ `local`, `apply` |
| 독립 검증(verifier) | ✔ | 사람 손으로만(대화 중 수동) | ✔ | ✗ |
| 판정(judge)·승인 | ✔ | Codex 부재 시 | ✗ | ✗ |
| P1 벨 수신 | ✔ `codex queue` | **✗ 없음**(세션 시작 한 줄 요약만) | ✗ | ✗ |
| 출석부 | 훅 | ✔ 훅(U37) | 훅 | — |
| 사용량 장부 | 수동 | 수동 | pilot 자동 | pilot 자동 |

빈 칸 세 개(작업자, 자동 검증, 벨 수신)가 이 설계의 대상이다.

## 2. 설계 — Claude Code의 네 자리

```mermaid
flowchart LR
    M[계약 매뉴얼<br/>worker: claude] --> L{pilot manual lint<br/>예산·판정자 검사}
    L --> P[pilot run<br/>격리 사본]
    P --> W[claude_worker<br/>claude -p --bare<br/>Read/Edit/Write/Glob/Grep<br/>tests 쓰기 금지]
    W --> G[결정적 관문<br/>문법·삭제·범위·인수·cost_gate]
    G --> V[claude 검증자 또는 Codex<br/>읽기 전용 반례 검토]
    V --> J{판정자 Codex/사용자<br/>작성자 ≠ 판정자}
    J --> R[반영 + 장부 worker=claude]
    S[교환원 P1] -- Codex ACTIVE --> CQ[codex queue]
    S -- Codex 부재 + Claude ACTIVE --> CH[Claude 다음 프롬프트에<br/>P1 한 줄 주입(훅)]
```

### 2-1. 작업자 `worker: claude` (핵심)

| 항목 | 설계 | 근거·이유 |
|---|---|---|
| 호출 | `claude -p <매뉴얼 전문> --bare --tools Read,Edit,Write,Glob,Grep --allowedTools 같음 --disallowedTools <tests 쓰기 금지> --permission-mode acceptEdits --max-turns N --output-format json --model <계약의 model>` | `lane_worker.py`와 같은 플래그. 이 저장소에서 벤치로 검증됐다(`lane_command`) |
| 셸(Bash) | **금지** | 인수 명령은 파일럿이 직접 돌린다. 셸이 있으면 사본 밖을 건드릴 수 있다(lane의 결론 그대로) |
| 테스트 보호 | `Edit/Write(tests/**)`·`test_*` 금지 | 벤치의 주된 실패 원인이 테스트 변조였다 |
| 모델 | 계약에 `model:` 칸(예: 가벼운 편집은 Haiku, 설계가 섞인 편집은 Sonnet) | 비용·품질 대비는 **UNMEASURED**. A/B로 정한다(§4) |
| 환경 변수 | lane과 **반대**다. `ANTHROPIC_BASE_URL`·`ANTHROPIC_AUTH_TOKEN` 재지정을 지우고 유료 계정으로 가게 한다. `CLAUDECODE`·`CLAUDE_CODE_SESSION_ID` 같은 부모 세션 표식도 지우고 `UAOS_WORKER=claude`를 넣는다 | 부모 Claude 세션 안에서 부를 때 생기는 문제 두 가지를 막는다. (1) 스트림·장부가 작업자를 "claude(지휘자)"로 오인한다. (2) 중첩 실행이 거부될 수 있다(UNKNOWN, 버전별로 확인) |
| 설정 격리 | `--bare`로 훅·CLAUDE.md 자동 로딩을 끈다. 인수에 "격리 사본 diff에 `.coord/presence`·`.coord/stream` 변경 없음"을 넣는다 | 사본 안에도 `.coord/PLAN.md`가 있어, 훅이 돌면 U37 출석 훅이 사본에 출석 파일을 써서 **범위 위반**이 된다. `--bare`의 정확한 범위는 설치 버전에서 확인한다 |
| 사용량 | JSON의 `usage.input_tokens`·`output_tokens`·`cache_creation_input_tokens`·`cache_read_input_tokens`와 `total_cost_usd`를 장부에 기록한다(`worker: claude`, `model`) | B85의 교훈: 입력 토큰만 세면 적게 잡힌다. 캐시 토큰도 따로 남긴다 |
| 예산 | `remote_budget_tokens` **필수**(lint 오류 `REMOTE_WITHOUT_BUDGET`). 사후 관문은 B85의 `cost_gate`(초과면 BLOCKED, 승인 거부). 지출 전 상한은 `--max-turns`와 `timeout_s` | B85: 예산 칸이 있어도 cascade가 아니면 무시됐다. 토큰 수를 직접 막는 CLI 옵션이 있는지는 UNKNOWN이다(`claude --help`로 확인) |
| 판정자 | `WORKER_TOOL["claude"] = "claude"`로 두어 판정자는 codex 또는 user만 가능하다(`SELF_JUDGE`) | docs/31 §3 "작성자는 유일한 검증자가 될 수 없다" |
| 계정 공유 | 작업자 Claude와 대화 중인 부지휘자 Claude는 **같은 구독 한도**를 쓴다. 출석이 `LIMITED`면 claude 작업자를 거부한다 | 작업자가 한도를 다 쓰면 부지휘자가 멈춘다 |

계약 매뉴얼 예시:

````text
```contract
work_id: U38-DEMO
worker: claude
model: claude-haiku-4-5-20251001
goal: Rename helper `fmt_ts` to `format_timestamp` in `v7_harness/coord/stream.py` and its call sites.
inputs:
- v7_harness/coord/stream.py sha256=<hex>
allow:
- v7_harness/coord/stream.py
acceptance: python -m unittest tests.test_u15_stream_append tests.test_u33_pilot_autolog_default
forbidden: edits outside allow; editing tests; Bash; network
stop: two failures with the same cause; input hash mismatch; cost_gate not WITHIN
judge: codex
timeout_s: 600
remote_budget_tokens: 60000
```
````

### 2-2. 검증자 `claude review` (읽기 전용)

- 명령(제안): `pilot review --task <ID> --reviewer claude`
  - 번들 diff와 매뉴얼을 `claude -p --tools Read,Glob,Grep`에 넘긴다.
  - JSON 스키마(`{"verdict": "PASS|REWORK", "counterexamples": [...], "evidence_lines": [...]}`)로 받는다.
- **판정권이 없다.** 결과는 `review.json`에 **증거 후보**로만 저장되고, 판정자(Codex/사용자)가 본다. B83의 결론과 같다. 같은 계정 안의 이름표는 인증이 아니다.
- 작성자가 claude인 번들은 claude가 검증하지 않는다. lint와 `pilot review`가 모두 거부한다.

### 2-3. 알림 수신 — Codex가 없을 때의 P1

| 상황 | 동작 | 비용 |
|---|---|---|
| Codex ACTIVE | 기존대로 `codex queue`로 벨 | 0(로컬) |
| Codex 부재·UNKNOWN, Claude ACTIVE | Claude의 **다음 프롬프트**에 한 줄을 주입한다. UserPromptSubmit 훅이 우편함에 P1이 있을 때만 `P1 waiting: <reason> — coord inbox`를 출력하고, 없으면 출력하지 않는다 | P1이 있을 때만 수십 토큰 |
| 둘 다 부재 | 우편함에 보관. 사람이 돌아오면 세션 시작 요약에 표시(U37) | 0 |

- **하지 않는 것**: 쉬고 있는 Claude 세션을 깨우려고 `claude -p --resume <세션>`으로 턴을 여는 방식. 유료 턴을 자동으로 여는 것이라 "유료 모델 폴링 금지"와 B77 취지에 어긋난다. 필요하면 사용자 승인 항목으로 따로 올린다.
- 판단: Claude Code에는 `codex queue`처럼 쉬는 세션에 메시지를 넣는 로컬 입구가 확인되지 않았다(UNKNOWN). 그래서 "다음 프롬프트 때 알림"이 비용 0에 가장 가깝다.

### 2-4. 기록자

- 출석: U37 훅(완료).
- 스트림: `detect_actor`가 `UAOS_WORKER=claude`를 보면 `claude-worker`로 기록해 지휘자 Claude와 구분한다.
- 장부: `worker: claude` 행은 파일럿이 자동으로 남긴다(U27·U36의 `error_class` 포함). RSI 보고(`rsi report`)는 작업자별로 나뉘므로 추가 코드가 필요 없다.

## 3. 레드팀 — 이 설계가 깨지는 방식과 대책

| # | 공격·실패 | 대책 | 테스트 |
|---|---|---|---|
| 1 | claude 작업자가 자기 번들을 claude로 승인 | `SELF_JUDGE`(lint), `APPROVER_NOT_JUDGE`. 실행 도구를 알 수 없는 경우(`approver is None`)는 B85 항목 e에서 거부 | lint·approve 거부 |
| 2 | 부모 세션 표식 상속으로 기록 주체 오인·중첩 실행 | 환경 정리 + `UAOS_WORKER` | 자식 env에 `CLAUDECODE` 없음 |
| 3 | 사본 안에서 훅·CLAUDE.md가 돌아 출석 파일 기록 → 범위 위반 | `--bare`, 인수에 `.coord/presence` 변경 없음 확인 | 가짜 claude가 훅 흉내 → SCOPE_VIOLATION |
| 4 | 예산 초과 후 승인(B85) | B85 수정 선행, `cost_gate` 필수 | B85 매트릭스 1~5를 worker=claude로 반복 |
| 5 | 캐시 토큰 누락으로 과소 계상 | 네 종류 토큰 모두 기록, 예산은 합계 기준 | 가짜 JSON의 cache 토큰 합산 |
| 6 | 테스트 변조로 통과 | `--disallowedTools` 보호 + 파일럿 인수 + 고정 테스트 해시 | tests/ 쓰기 시도 → 거부 |
| 7 | 부지휘자와 같은 한도 소진 | 출석 `LIMITED`면 거부, 일일 claude 작업자 예산(정책값) | presence LIMITED → REFUSED |
| 8 | 유료 자동 깨우기로 폴링 부활 | 2-3의 "하지 않는 것"을 코드에 넣지 않음 | 교환원 테스트: claude로는 프로세스를 띄우지 않음 |
| 9 | 인증 없는 이름표(B83 교훈) | claude 검증 결과는 증거 후보일 뿐 판정권 없음 | `pilot review` 결과가 승인을 대신하지 못함 |

## 4. 효과 측정 계획 (주장하지 않고 재기)

- 같은 과제 10개를 `local`·`agy`·`claude(haiku)`·`claude(sonnet)`으로 A/B 한다. 2026-09-23 lane A/B와 같은 방식이다.
- 기록 항목: 통과율, 재작업률, 호출·토큰(캐시 포함), `total_cost_usd`, 50/80백분위 시간.
- 결과로 `auto`·`cascade`의 승격 순서를 정한다(예: `local → claude(haiku) → agy`). 그 전까지 승격 순서는 **바꾸지 않는다**.
- 계정 한도 절감은 여전히 `UNMEASURED`다.

## 5. 구현 카드 U38 (Codex 승인 대기)

| 순서 | 내용 | 파일 | 선행 |
|---|---|---|---|
| 1 | B85 비용 관문(모든 원격 작업자·승인 거부·합계 토큰) | `cli.py`, `manual.py` | Codex B83 푸시 |
| 2 | `adapters/claude_worker.py` 신규(lane과 같은 봉투 규격, 환경 정리, 캐시 토큰) | 새 파일 | — |
| 3 | 작업자 등록: `WORKERS`·`WORKER_TOOL`·`--worker`·`--escalate-to`·`manual new`에 `claude`, 계약 칸 `model` | `cli.py`, `manual.py` | 1 |
| 4 | 장부 `worker: claude`, 캐시 토큰·비용 필드 | `pilot.py` | 2 |
| 5 | `pilot review --reviewer claude`(읽기 전용, 증거 후보) | `cli.py` | 3 |
| 6 | P1을 Claude 다음 프롬프트에 주입(`coord presence --from-hook --say p1`) | `cli.py`, 설치기 훅 | U37 |
| 7 | 문서: docs/37 작업자 표, 초보자 문서, 전역 규칙 문단 | docs | 1~6 |

- **테스트**(가짜 `claude` 실행 파일로 네트워크 없이): §3의 1~9, B85 매트릭스를 worker=claude로 반복, lane 기존 테스트 회귀.
- **중지 조건**: lane·agy·local 기존 테스트의 동작이 바뀌면 멈춘다. 실제 유료 호출은 Codex 승인 뒤, 예산이 적힌 매뉴얼 1건으로만 한다.
- **사용자 PC에서 먼저 확인할 것**(UNKNOWN 해소):
  - `claude --version`
  - `claude --help`에 `--bare`, `--max-turns`, `--tools`, 예산 옵션이 있는지
  - 부모 세션 안에서 `claude -p` 중첩 실행이 되는지
