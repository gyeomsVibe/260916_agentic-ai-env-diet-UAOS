# [U09] Codex 구현 설계 지시문 — v8 Codex–Antigravity 통합

> 이 문서 전체를 Codex 새 대화창 `[U09] v8 설계 확정`에 붙여 넣는다.

---

## 0. 역할과 금지

너는 이 프로젝트의 **조율자·지휘자·두뇌**다. 작업 경로: `D:\D_Workspace_NB\-agentic-ai-workspace\260916_agentic-ai-env-diet`

**절대 금지**
- 아래 §1 확정 전제를 재검토·반박하거나 대안으로 바꾸지 마라. 사용량 판단 포함이다. 사용자는 3도구를 구독 중이며 경험으로 결정했다.
- §2 요구(R01~R26)를 하나라도 누락·축소·병합 삭제하지 마라.
- 한 번에 모든 단계를 실행하지 마라. 한 대화창에서 한 단계만 수행하고, 단계 끝에 사용자에게 다음 단계 진행을 한 줄로 물어라(R24).
- 긴 설명을 하지 마라. 보고는 §8 형식 7줄 이내로 하고, 상세는 파일에 남겨라.

**권한:** 범위 안의 조사·편집·테스트·재작업은 무승인으로 수행한다. 삭제·push·배포·결제·계정/권한/자격증명 변경·전역 설정 파일 수정은 행동 직전 사용자 확인을 받는다.

---

## 1. 확정 전제

| # | 전제 |
|---|---|
| P1 | 운영 도구는 Codex·Antigravity 2개다. Claude Code는 계획에서 제외한다. |
| P2 | Codex Plus 사용량은 적고 Antigravity 사용량은 풍부하다. |
| P3 | Codex = 조율자·지휘자·두뇌. Antigravity = Codex의 도우미·일꾼·하위 에이전트. Codex가 사용자 지시 없이 자율적으로 부린다. |
| P4 | 성과·결과 최우선. Antigravity 결과가 인수 기준을 만족하면 Antigravity가 Codex를 대신한다. |
| P5 | 두 도구는 사용자로부터 무승인 권한을 받았다. |
| P6 | Codex는 Security & Skeleton(설계 구조·예외 진단)에 강하고, Antigravity는 Multi-agent Orchestration(병렬 서브에이전트·동적 라우팅·프로토타이핑)에 강하다. |
| P7 | Codex–Antigravity 연결은 MCP가 아니라 로컬 SQLite DB로 한다. |

---

## 2. 필수 요구 (R01~R26) — 전부 구현·설계에 반영

| ID | 요구 | 반영 위치(설계 기준) |
|---|---|---|
| R01 | 두 도구의 전역 룰·skills·메모리·바이브 자가진단·MCP 충돌 지점 탐지 | 보고서 §6.3 C1~C10 재확인 |
| R02 | 불필요·무거운·과한 지침 삭제·경량화 | S6 |
| R03 | 사용자 AI 사용 습관에 맞춰 두 도구 규칙·전역 룰·skills 재작성 | S6, 보고서 §11 |
| R04 | Claude Code 계획 제외 | 전 단계 |
| R05 | Codex 지휘·두뇌, Antigravity 하위 에이전트, 무지시 자율 위임 | 라우터·`delegate` |
| R06 | 환각·토큰 낭비 Safety Guard | 보고서 §7 전부 |
| R07 | Codex 사용량 보존, Antigravity 사용량 최대 활용, Codex 한도에 막히지 않는 완수 로직 | 보고서 §8.4 |
| R08 | 결과 만족 시 Antigravity가 Codex 대신 수행(결과주의) | §8.4 6번 |
| R09 | CRITIC·REDTEAM·SELFREFINE 예산절약 극대화 결과주의 루프 | §8.4 3~5번 |
| R10 | 단일 계획으로 두 도구가 한몸처럼 수행, 무승인 권한 | DB `plan` + `render` |
| R11 | 프로젝트 안에서 작업마다 대화창 하나, 계획 순서대로 | `conversations` 테이블 |
| R12 | 짧은 통일 접두어 `[U##]` | 런처 자동 부착 |
| R13 | Antigravity 작업 = Codex 프로젝트의 단계별 전용 대화창, 단일 소유자, Codex로 시작 시 Antigravity는 Codex의 도구 | managed 모드 |
| R14 | Codex 시작 시 자동 연결 / Antigravity IDE·2.0은 단독 / Antigravity에서 Codex 호출 가능 | `connect`, standalone 모드, `ask-codex` |
| R15 | MCP 대신 SQLite로 연결 실패 없이 100% 유연한 연결 | §8.1~8.3 L1~L16 |
| R16 | 맹점·난제 CRITIC·STEPBYSTEP·REDTEAM + DEEPDIVE·ALT3·OPTIMIZE 반영 | 보고서 §5.3·§8.7, 구현 중 발견 시 추가 |
| R17 | Security & Skeleton / Multi-agent Orchestration 강점 기반 역할 정의 | 보고서 §5.4 → `AGENTS-CONSENSUS.md` |
| R18 | Codex가 먼저 프로젝트 진단 → `AGENTS-CONSENSUS.md`(또는 `shared-specs.md`) 작성, 병렬 분업·권한·중복 방지 | `[U01] 진단` 단계 템플릿 |
| R19 | 디렉터리 기준 권한 엄격 분리(backend/ Codex, frontend/ Antigravity, 루트 공유 명세) | `scopes` + `--add-dir` + diff 강제 |
| R20 | 전면 자동화 | 연결·위임·판정·다음 단계 자동 |
| R21 | 예상 효율 향상 검증 | S5 A/B |
| R22 | 극한 로컬 벤치마크 | S4 X01~X22 |
| R23 | 2026-09-16 기준 최신 자료로 설계 보강 | 보고서 §5 |
| R24 | 한 대화창에 한 단계, 역질문으로 진행 | §5 단계 게이트 |
| R25 | 사용자 제안에 토 달지 않고 보강만 | §0 금지 |
| R26 | SQLite vs MCP 비교·판단 | 보고서 §8.6 (결정: SQLite 주 경로) |

---

## 3. 먼저 읽을 것 (이것만 읽어라)

1. `docs/11_full-analysis-report_v8_2026-09-17.md` — **설계 정본.** §7·§8·§9·§10·§11·§12 필독
2. `.coord/PLAN.md`
3. `AGENTS.md`
4. `v7_harness/cli.py`, `v7_harness/proof_receipt.py`, `v7_harness/workflow_invariants.py`, `v7_harness/snapshot.py`
5. `proposals/u08-sqlite-coordination-schema.sql` (참고만)

`docs/00`~`10`은 보고서 §6에서 이미 전수 분석했다. 필요한 절만 경로로 찾아 읽어라.

---

## 4. 확정된 설계 결정 (그대로 구현)

1. **연결:** v7 하네스를 확장한 SQLite CLI 런처가 주 경로다. DB writer는 런처 하나다. Codex·Antigravity는 명령만 호출한다. MCP 브리지는 삭제하지 않고 조회용으로 둔다.
2. **Antigravity 호출:** `agy -p "[U##] …" --output-format json --json-schema <schema> --conversation <id> --add-dir <소유 scope> --print-timeout 10m`. 최초 호출에서 받은 `conversation_id`를 저장한다. `--continue`는 금지한다.
3. **Codex 역호출:** `ask-codex` → `codex exec` / `codex exec resume <id>`.
4. **스키마:** 보고서 §8.2의 7테이블 `plan, scopes, conversations, attempts, usage, receipts, events`. PRAGMA는 WAL, synchronous=FULL, foreign_keys=ON, busy_timeout=5000.
5. **판정:** 봉투 6중 판정 + `changed_files`와 git diff 대조 + scope 검사(§7.1).
6. **연속성:** L1~L16 전부 구현. 같은 원인 3회면 `blocked`.
7. **병렬:** 같은 scope는 WIP=1, 다른 scope는 동시 실행. `shared` 경로는 Codex만 수정하고, Antigravity는 `spec_change_requests`로 요청한다.
8. **결과주의 루프:** §8.4 1~7번. 인수 기준 충족 결과는 Codex가 재작성하지 않는다.
9. **Codex 입력 상한:** 요약 JSON(7줄) + 위험 diff 경로. 전문 로그 금지.
10. **사람이 읽는 파일:** `PLAN.md`와 `AGENTS-CONSENSUS.md`는 DB에서 `render`로 생성한다.
11. **체크포인트:** 위임 전후 로컬 git 커밋(원격 없음).

### 명령 계약

| 명령 | 입력 | 출력 |
|---|---|---|
| `connect` | — | 한 줄 상태, orphaned 자동 재개 수 |
| `diagnose --init` | 프로젝트 경로 | `AGENTS-CONSENSUS.md` 초안 + `scopes` 초기값 |
| `plan add/set` | task_id, lane, depends_on, acceptance, verification | DB 반영 |
| `delegate start` | task_id, scope, prompt 파일, schema | attempt_id (즉시) |
| `delegate wait` | task_id 또는 attempt_id, `--max` 초 | 요약 JSON |
| `delegate status` | task_id | 상태·usage·재시도 수 |
| `ask-codex` | task_id, 질문 | 답 + session id |
| `render` | — | `PLAN.md`, `AGENTS-CONSENSUS.md` 갱신 |
| `bench` | 시나리오 ID·반복 수 | 결과 표 |
| `usage report` | 기간·task | 도구별 토큰·시간 표 |

### 요약 JSON 스키마 (Codex 반환·Antigravity 보고 공통)

```json
{
  "task_id": "U11",
  "state": "succeeded|failed|timeout|wait|blocked",
  "result": "한 줄",
  "changed_files": ["frontend/..."],
  "checks": [{"cmd": "...", "exit": 0}],
  "risks": ["..."],
  "spec_change_requests": [],
  "next": "한 줄",
  "usage": {"input_tokens": 0, "output_tokens": 0},
  "evidence_path": ".coord/receipts/U11-a001.json"
}
```

### `AGENTS-CONSENSUS.md` 필수 섹션 (R17·R18·R19)

1. 프로젝트 진단 요약(구조·스택·빌드·테스트 명령·위험 영역)
2. 역할: Codex = Security & Skeleton(진단·골격·명세·보안·예외·최종 판정), Antigravity = Multi-agent Orchestration(구현·병렬 조사·프로토타입·테스트 반복)
3. Scoped Permission 표(경로·소유자·런타임 자원: 포트/DB)
4. 공유 명세·인터페이스 계약 위치와 변경 절차
5. 병렬 규칙(같은 scope WIP=1, 다른 scope 병렬, 합류 단계)
6. 인수 기준·검증 명령
7. 금지 행동과 승인 경계

---

## 5. 단계 진행 (한 대화창 = 한 단계)

각 단계는 새 대화창 `[U##] 제목`에서 수행한다. 끝나면 §8 형식으로 보고하고 `다음 단계 [U##] 진행할까요?` 한 줄만 묻는다.

| 단계 | 대화창 | 할 일 | 완료 기준 |
|---|---|---|---|
| S0 | `[U09] v8 설계 확정` | ① R01~R26 추적표를 `.coord/tasks/U09-v8-design.md`에 작성(각 R → 구현 모듈·테스트 ID·단계) ② U08 `DONE`(설계 참고), U03·U04 `SUPERSEDED` ③ U10~U16 카드 생성 ④ 누락 검사 | 추적표 26행 모두 채움, 빈칸 0 |
| S1 | `[U10] 로컬 Git` | 사용자 확인 후 `git init`, `.gitignore`(`__pycache__`, `.coord/*.db*`, receipts 원문), 초기 커밋 | `git status` exit 0 |
| S2 | `[U11] SQLite 런처 코어` | 스키마·`connect`·`plan`·`delegate start/wait/status`·봉투 판정·scope 검사·체크포인트·요약 JSON. 구현은 Antigravity에 위임하고 Codex는 요약 검토 | 신규 단위 테스트 PASS, 기존 37개 PASS |
| S3 | `[U12] 연속성·역호출·렌더` | L1~L16, `ask-codex`, `render`, `diagnose --init`, JSONL 폴백 | 각 L 항목 테스트 존재·PASS |
| S4 | `[U13] 극한 벤치마크` | mock agy·codex로 X01~X22 × 20회, 실제 canary 4건 | 기록 손실·중복·거짓 성공·scope 위반 채택 모두 0, 자동 재개 100%(X09·X18·X21 제외) |
| S5 | `[U14] 효율 검증` | 보고서 §10 A/B 3과제 | Codex 사용량 절감률 표 + 품질 동등 여부 |
| S6 | `[U15] 전역 룰·skills 재작성` | 보고서 §11 + C1~C7 적용. 전역 파일은 사용자 확인 후 수정 | 새 세션에서 `connect` 자동 실행·역할 로딩 확인 |
| S7 | `[U16] 실프로젝트 파일럿` | 실제 프로젝트 하나에서 `[U01] 진단` → 병렬 lane → 통합까지 v8 1회 운영 | 운영 기록 + 발견 보강 목록 |

각 단계의 구현 작업은 Antigravity에 `delegate`로 맡기고, Codex는 판정만 한다. 단, S2에서 `delegate`가 아직 없을 때는 기존 `antigravity-bridge`로 Antigravity에 구현을 맡긴다.

---

## 6. 누락 방지 자체 검사 (매 단계 종료 전 필수)

```text
[ ] 이번 단계와 연결된 R 항목이 추적표에서 "구현됨/테스트됨"으로 갱신됐다
[ ] §1 전제를 바꾸거나 반박한 문장이 산출물에 없다
[ ] R19 디렉터리 권한, R18 AGENTS-CONSENSUS, R14 자동 연결·역호출이 빠지지 않았다
[ ] 봉투 6중 판정과 scope 검사를 우회하는 경로가 없다
[ ] Codex가 읽은 입력이 요약 JSON + 위험 diff를 넘지 않았다
[ ] 테스트 명령과 exit code를 기록했다
[ ] 다음 단계 질문 한 줄로 끝냈다
```

---

## 7. 첫 행동 (지금 이 대화창)

1. §3 파일을 읽는다.
2. S0을 수행한다.
3. §8 형식으로 보고하고 `[U10] 로컬 Git 진행할까요?`라고 묻는다.

---

## 8. 보고 형식 (7줄 이내)

```text
결과: 
변경: 
검증: (명령 → exit)
요구 충족: R## …
위험: 
사용량: Codex 턴 n / Antigravity 토큰 n
다음: [U##] … 진행할까요?
```
