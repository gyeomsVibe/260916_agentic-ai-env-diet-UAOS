# U09 후보 — 사용자 제안 보강·개선 설계 v8

- 작성일: 2026-09-17
- 상태: `PROPOSAL` (조율 정본 `.coord/PLAN.md`는 Codex 소유이므로 변경하지 않음)
- 원칙: 사용자 제안은 확정 전제다. 이 문서는 그 제안이 **실패 없이 돌아가도록 구현을 보강**하는 것만 다룬다.
- 적용 렌즈: CRITIC · STEPBYSTEP · REDTEAM · DEEPDIVE · ALT3 · OPTIMIZE (구현 난제·맹점에만 적용)

## 0. 확정 전제 (사용자 제안, 재검토 대상 아님)

1. 사용자는 Codex·Antigravity·Claude Code를 구독 중이며, 이 로직은 Codex와 Antigravity 2도구로 운영한다.
2. Codex Plus 사용량은 Antigravity보다 적다. Antigravity 사용량을 적극적으로 써서 Codex 사용량을 살린다.
3. Codex는 조율자·지휘자·두뇌다. Antigravity는 Codex의 하위 실행자이며, Codex는 사용자 지시 없이 필요할 때 자율적으로 Antigravity에 작업을 맡긴다.
4. 결과·성과가 최우선이다. Antigravity 결과가 인수 기준을 만족하면 Antigravity가 Codex 대신 작업한다.
5. Codex로 시작하면 Antigravity와 자동 연결된다. Antigravity 단독 사용 시 필요하면 Codex를 호출할 수 있다.
6. 작업마다 프로젝트 안에 짧은 통일 접두어 `[U##]` 대화창을 만들고 계획 순서대로 진행한다.
7. Codex가 먼저 프로젝트를 진단하고 `AGENTS-CONSENSUS.md`(또는 `shared-specs.md`)와 디렉터리 기준 권한을 정한다.
8. 연결은 MCP가 아니라 로컬 SQLite DB로 하며, 끊기지 않고 유연하게 이어져야 한다.
9. 전면 자동화, 예상 효율 향상 검증, 극한 로컬 벤치마크를 포함한다.
10. 환각·토큰 낭비 방지 Safety Guard를 둔다.

## 1. 현재 구현 상태 (L1 로컬 실측)

| 항목 | 실측 |
|---|---|
| v7 하네스 | `v7_harness` 9모듈, `pytest` 37 passed. 실제 위임 경로와는 아직 연결되지 않음 |
| 조율 상태 | U08 `REVIEW`(Verdict `PENDING`) |
| 브리지 | `antigravity-bridge/index.js` 878줄. `agy --print` 텍스트를 node-pty 화면 복원으로 읽음. `--output-format json` 미사용 |
| `agy` 헤드리스 JSON | 비TTY 서브프로세스에서 exit 0, 25초, `status=SUCCESS`, `conversation_id`, `usage` 반환 확인 |
| `codex exec` | 존재. `resume`, `fork` 지원 → Antigravity에서 Codex 호출 경로로 사용 가능 |
| 프로젝트 | 비Git |

## 2. 보강 포인트 — 제안을 실패 없이 돌리기 위한 구현 난제와 해결

### G1. 위임 성공을 기계적으로 판정 (환각 방지 Safety Guard)
- 난제: 브리지는 화면 텍스트와 종료 코드만 본다. `agy`에는 print-timeout 때 부분 출력과 함께 exit 0을 내는 공개 버그(#1012)와, 비TTY 멈춤(#318, #947)·빈 응답 보고가 있다.
- 보강: `agy -p --output-format json`의 봉투로 판정한다. `status=SUCCESS`, `error` 없음, 응답 비어 있지 않음, stderr에 timeout/partial 경고 없음, 사후 diff가 허용 범위 안, 카드 검증 명령 exit 0. 여섯 가지를 모두 만족해야 성공이다. 결과 형식이 정해진 작업은 `--json-schema`로 강제한다.

### G2. `[U##]` 단계별 전용 대화창을 Antigravity에서 실제로 구현
- 난제: 브리지의 이어가기는 전역 "최근 대화"를 잡아 다른 단계 대화에 섞일 수 있다.
- 보강: SQLite에 `[U##] ↔ conversation_id`를 저장하고, 재개는 항상 `--conversation <id>`로 한다. 첫 프롬프트 첫 줄에 `[U##] 제목`을 넣어 Antigravity 대화 목록에서도 접두어로 식별되게 한다. Codex 쪽 단계 세션도 같은 테이블에 `codex exec` 세션 id로 기록한다.

### G3. Codex 시작 시 자동 연결
- 보강: 프로젝트 `AGENTS.md`에 "세션 시작 시 `python -m v7_harness.cli connect` 실행"을 둔다. 이 명령은 DB 열기·스키마 확인, `agy --version`, 진행 중·고아 작업 재조정을 한 번에 수행하고 한 줄 상태만 출력한다. Codex 토큰 소모는 명령 1회뿐이다.

### G4. Antigravity 단독 사용 시 Codex 호출
- 보강: `python -m v7_harness.cli ask-codex --task U## "질문"` → 내부에서 `codex exec`(필요 시 `resume <id>`) 실행. 결과와 세션 id를 DB에 기록한다. Codex가 호출되면 기존 계획 정본(`.coord/PLAN.md`)을 읽고 답하므로 계획이 둘로 갈라지지 않는다.

### G5. Codex 진단 → `AGENTS-CONSENSUS.md` + 디렉터리 기준 권한
- 보강: 첫 단계 `[U01] 프로젝트 진단`에서 Codex가 구조를 진단하고 `AGENTS-CONSENSUS.md`를 작성한다. 디렉터리 권한은 이 문서의 표를 정본으로 삼고, 런처가 DB `scopes` 테이블로 읽어 강제한다.

```markdown
## Scoped Permission
| 경로 | 소유자 | 비고 |
|---|---|---|
| backend/ | codex | |
| frontend/ | antigravity | |
| shared-specs / AGENTS-CONSENSUS.md | codex | 공유 명세 |
```

- 강제: Antigravity 위임 시 런처가 `--add-dir`에 Antigravity 소유 경로만 넣고, 사후 diff에서 소유 경로 밖 변경이 있으면 즉시 `SCOPE` 실패로 기록한다.

### G6. 자율 실행을 되돌릴 수 있게
- 난제: 프로젝트가 비Git이라 무승인 자율 편집의 복구 수단이 없다.
- 보강: 로컬 전용 `git init`(원격·push 없음)을 한 번 수행하고, 런처가 위임 전후로 자동 체크포인트 커밋을 남긴다. 사용자 승인 후 1회 실행한다.

### G7. 헤드리스 권한 한계 보완
- 난제: print 모드가 `permissions.allow`를 무시하고 멈춘다는 이슈(#548)가 있어, 브리지는 `--dangerously-skip-permissions`를 기본으로 쓴다.
- 보강: 무승인 자율 실행은 유지한다. 대신 런처가 기계적으로 강제한다. ① `--add-dir` 범위 고정 ② 자식 프로세스 환경변수에서 자격증명 제거 ③ 사후 diff 범위 검사 ④ push·배포·삭제 명령 흔적(Git remote 변화 등) 감지 시 즉시 중지.

### G8. Codex 검토 토큰 절약 (예산 절약 극대화)
- 보강: Codex가 결과 전문을 읽지 않게 한다. 런처가 결정적 검사(테스트·스키마·범위 diff) 결과와 변경 파일 목록, 위험 파일 diff만 짧은 JSON으로 요약해 Codex에 반환한다. Codex는 요약과 위험 diff만 보고 `DONE`·재작업을 판정한다.

### G9. SQLite 동시 쓰기 난제
- 난제: 여러 프로세스가 같은 SQLite에 쓰면 WAL 쓰기 잠금 경합으로 정지가 발생한 사례가 있다(hermes-agent).
- 보강: DB 쓰기는 런처 프로세스 한 곳에서만 한다. `journal_mode=WAL`, `busy_timeout=5000`, 짧은 `BEGIN IMMEDIATE`, 1초 단위 재시도에 무작위 지연을 둔다. Codex·Antigravity는 DB를 직접 쓰지 않고 런처 명령만 호출한다.

## 3. 연결 방식 비교 — SQLite 로컬 DB 방식 vs MCP 브리지 방식

### 3.1 구조

```text
[MCP 방식 — 현재]
Codex ──MCP stdio──> antigravity-bridge(node)
                        └─ node-pty로 `agy --print` 실행, 화면 복원
                        └─ %TEMP%/agy_jobs/<jobId>.json 덮어쓰기
Codex ──(반복 호출)──> antigravity_result(jobId) 폴링 → 텍스트

[SQLite 방식 — 제안]
Codex ──shell──> python -m v7_harness.cli delegate start --task U09 ...
                   ├─ SQLite: attempt 기록(running, idempotency_key)
                   ├─ `agy -p --output-format json --conversation <id> --add-dir <소유 경로>`
                   ├─ 봉투 검증 + 범위 diff + receipt + 체크포인트 커밋
                   └─ SQLite: 상태·usage·events 커밋
Codex ──shell──> delegate wait --task U09   # DB 조회 후 짧은 요약 JSON 반환
```

MCP 방식은 브리지 프로세스 메모리와 임시 JSON이 상태의 정본이다. SQLite 방식은 DB 커밋이 정본이고 전달 경로는 교체 가능한 부품이다.

### 3.2 비교표

| 기준 | MCP 브리지 | SQLite + CLI 런처 | 우위 |
|---|---|---|---|
| 실패 지점 | MCP stdio, 브리지 node, node-pty, agy 4곳 | shell, agy 2곳 | SQLite |
| Codex·브리지 재시작 뒤 | 진행 중 job 고아화, 복구 없음 | DB의 `running+pid`로 고아 판정 → `conversation_id`로 재개 | SQLite |
| 성공 판정 | 종료 코드 + 화면 텍스트 | JSON 상태·stderr·범위 diff·검증 명령 6중 확인 | SQLite |
| `[U##]` 전용 대화창 | 전역 최근 대화 이어가기 → 섞임 | 단계별 `conversation_id` 고정 | SQLite |
| 사용량 기록 | 불가 | 호출마다 input/output/thinking/cache 토큰·시간 누적 | SQLite |
| Codex 토큰 소모 | 도구 스키마 매 턴 상주 + 폴링마다 Codex 턴 | 시작 1회 + 대기 1회, 요약만 반환 | SQLite |
| 중복 실행 방지 | job ID 시간+난수 → 재전송 시 중복 | `idempotency_key UNIQUE` → 기존 attempt 반환 | SQLite |
| 장시간 작업 | 비동기 폴링에 자연스러움 | 시작·대기 분리로 대응(§3.3-1) | MCP 약간 우위 |
| 도구 발견성 | 도구 목록에 자동 표시 | `AGENTS.md`에 명령 명시 필요 | MCP |
| 디렉터리 권한 강제 | 없음 | `scopes` 테이블 + `--add-dir` + 사후 diff | SQLite |
| agy CLI 변경 영향 | 화면 형식 변화에 매우 취약 | 공식 JSON 계약 기반, 불일치 시 fail-closed | SQLite |
| 구현 | 이미 존재(878줄 JS + node-pty) | 약 400줄 Python 표준 라이브러리, v7 하네스 재사용 | SQLite(장기) |

### 3.3 SQLite 방식 보완 로직 — "끊기지 않고 유연하게"

1. **시작·대기 분리:** `delegate start`는 agy를 분리 실행하고 즉시 `attempt_id`를 반환한다. `delegate wait --max 540`은 DB만 보고 최대 9분 대기한다. 긴 작업도 Codex shell 타임아웃에 걸리지 않는다.
2. **프로세스 신원:** `pid + process_start_time`을 함께 저장해 Windows PID 재사용 오판을 막는다. 종료는 `taskkill /T /F`로 자식 트리까지 정리한다.
3. **이중 타임아웃:** 런처 타임아웃을 agy `--print-timeout`보다 60초 길게 둔다. agy가 타임아웃 경고와 함께 exit 0을 내도 `timeout`으로 기록한다.
4. **자동 재개:** `timeout`·연결 끊김은 같은 `conversation_id`로 "이전 작업을 이어서 완료" 프롬프트를 보내 자동 재개한다. 같은 원인이 연속 3회면 `BLOCKED`로 기록하고 Codex에 보고한다.
5. **일시 오류 대기:** quota/rate/429 계열 응답은 실패가 아니라 `WAIT`로 기록한다. 체크포인트를 보존하고 reset 시각 이후 같은 대화로 자동 재개한다.
6. **DB 장애 폴백:** DB 열기·쓰기 실패 시 `.coord/ledger-fallback.jsonl`에 append하고 다음 기동 때 DB로 반영한다. 기록은 한 건도 잃지 않는다. DB 경로는 로컬 NTFS만 허용한다.
7. **기동 재조정:** `connect` 실행 시 `running`인데 프로세스가 없으면 `orphaned`로 바꾸고 마지막 체크포인트에서 자동 재개한다.
8. **MCP 브리지 처리:** 프로젝트 위임 경로에서는 쓰지 않는다(이중 기록 방지). 삭제하지 않고 대화형 조회 도구로 남긴다.

### 3.4 스키마

```sql
CREATE TABLE tasks         (task_id TEXT PRIMARY KEY, title TEXT, status TEXT, acceptance_hash TEXT, created_at TEXT);
CREATE TABLE scopes        (path_prefix TEXT PRIMARY KEY, owner TEXT CHECK (owner IN ('codex','antigravity')));
CREATE TABLE conversations (task_id TEXT REFERENCES tasks, tool TEXT, conversation_id TEXT, PRIMARY KEY (task_id, tool));
CREATE TABLE attempts      (attempt_id TEXT PRIMARY KEY, task_id TEXT REFERENCES tasks, executor TEXT,
                            idempotency_key TEXT UNIQUE, pid INTEGER, process_start_time TEXT,
                            state TEXT CHECK (state IN ('running','succeeded','failed','timeout','wait','orphaned','blocked')),
                            started_at TEXT, ended_at TEXT, checkpoint_commit TEXT);
CREATE TABLE usage         (attempt_id TEXT REFERENCES attempts, input_tokens INT, output_tokens INT,
                            thinking_tokens INT, cache_read_tokens INT, duration_s REAL);
CREATE TABLE events        (seq INTEGER PRIMARY KEY AUTOINCREMENT, attempt_id TEXT, at TEXT, kind TEXT, detail_hash TEXT);
```

프롬프트·응답 전문·비밀값은 DB에 넣지 않는다. 산출물은 파일로 두고 DB에는 경로와 SHA-256만 저장한다.

### 3.5 판단 (Claude)

**SQLite + CLI 런처를 Codex–Antigravity 연결의 주 경로로 채택한다. `GO`.**

1. 사용자 목표인 Codex 사용량 절약에 직접 맞는다. 폴링 턴과 도구 스키마 상주가 없어지고, Codex는 요약만 읽는다.
2. 사용자 요구인 "끊기지 않는 연결"에 맞는다. 상태가 DB에 남으므로 Codex·Antigravity·런처 어느 쪽이 재시작해도 같은 `[U##]` 대화에서 이어진다.
3. 결과 우선 원칙에 맞는다. JSON 봉투와 범위 검사로 Antigravity 결과를 기계적으로 판정하므로, 인수 기준을 만족한 결과는 Codex 재작업 없이 그대로 채택된다.

구현 시 확인할 기술 항목은 하나다. Codex 샌드박스(`windows.sandbox = "elevated"`)에서 분리 실행한 자식 프로세스가 유지되는지 확인해야 한다. S3 첫 항목으로 확인하고, 유지되지 않으면 같은 DB를 쓰는 얇은 MCP 어댑터를 전달 경로로만 붙인다. DB 정본 구조는 그대로 둔다.

## 4. ALT3 — 구현 방식 대안

| 대안 | 내용 | 판정 |
|---|---|---|
| A. U08 풀 스키마 | 11테이블, fencing token, inbox/outbox | 기능은 §3.4 6테이블로 충족. 필요 시 확장 |
| B. v7 하네스 확장 SQLite 런처 | §3 설계 | **채택** |
| C. MCP 어댑터 + SQLite | 전달만 MCP, 정본은 DB | S3에서 분리 실행 불가 시 전환 |

## 5. STEPBYSTEP — 실행 순서 (한 대화창에 한 단계)

| 단계 | 대화창 | 내용 | 승인 필요 | 인수 기준 |
|---|---|---|---|---|
| S0 | `[U09] v8 확정` | 이 문서 확정, U08은 설계 참고로 DONE | 사용자 결정 | 방향 확정 |
| S1 | `[U10] 로컬 Git` | 로컬 `git init`, 초기 커밋(원격·push 없음) | 예 | `git status` exit 0 |
| S2 | `[U11] SQLite 런처` | `connect`·`delegate start/wait/status`·`ask-codex`, §3.4 스키마, G1·G5·G7·G8·G9 구현 | 아니오 | 신규 테스트 PASS |
| S3 | `[U12] 극한 로컬 테스트` | mock agy 장애주입 + 실제 agy canary | 아니오 | §6 기준 통과 |
| S4 | `[U13] 효율 검증` | 동일 과제 A: Codex 단독 / B: Codex 지휘 + Antigravity 실행 | 아니오 | §7 기록 |
| S5 | `[U14] 전역 반영` | 프로젝트 `AGENTS.md`·Codex 전역 규칙에 런처 사용법 반영 | 예(전역 파일) | 새 세션에서 `connect` 자동 실행 확인 |

## 6. 극한 로컬 벤치마크 (S3)

mock `agy`(지연·출력·종료 코드를 조절하는 가짜 실행 파일)로 먼저 수행하고, 통과 후 실제 agy canary 3건을 실행한다.

| ID | 주입 | 기대 |
|---|---|---|
| X01 | 타임아웃 + exit 0 + partial 경고 | `timeout` 기록, 같은 대화로 자동 재개 |
| X02 | 빈 응답 SUCCESS | 실패 판정, 성공 처리 0 |
| X03 | 실행 중 런처 강제 종료 | 재기동 시 `orphaned` → 자동 재개 |
| X04 | 실행 중 Codex 세션 종료 | DB 상태 유지, 새 세션 `connect`로 이어감 |
| X05 | 같은 요청 10회 전송 | 실행 1회 |
| X06 | quota/429 응답 | `wait` 후 자동 재개 |
| X07 | 소유 경로 밖 파일 수정 | `SCOPE` 실패, 체크포인트로 복원 |
| X08 | DB 잠금 10초 유지 | 무한 대기 0, 재시도 후 성공 또는 JSONL 폴백 |
| X09 | DB 파일 손상 | 기동 검사 실패, JSONL 폴백, 기록 손실 0 |
| X10 | 비TTY 멈춤(출력 없이 대기) | 런처 타임아웃 → 자식 트리 종료 → 재개 |
| X11 | 동시 위임 5건(서로 다른 소유 경로) | 쓰기 경합 정지 0, 전부 기록 |
| X12 | Antigravity→Codex `ask-codex` 도중 종료 | 세션 id로 재개 |

통과 기준: 각 시나리오 20회, 기록 손실 0, 중복 실행 0, 거짓 성공 0, 범위 밖 변경 채택 0.

## 7. 효율 검증 (S4)

- 과제: 조사 1, 코드 구현 1, 테스트·수정 1 (같은 인수 기준)
- A: Codex 단독 수행
- B: Codex 계획·판정 + Antigravity 실행 (런처 경유)
- 기록: Codex 사용량 변화(5시간 창 %), Antigravity `usage` 토큰, 벽시계 시간, 재작업 횟수, 인수 기준 통과 여부
- 보고: B의 Codex 사용량 감소분과 결과 품질을 표로 제시

## 8. Safety Guard 요약

| 위험 | 가드 |
|---|---|
| 환각 완료 보고 | G1 봉투 6중 판정, 검증 명령 exit 0 없이는 DONE 불가 |
| 대화 섞임 | G2 `conversation_id` 고정 |
| 범위 밖 수정 | G5·G7 `scopes` + `--add-dir` + 사후 diff |
| 되돌릴 수 없는 편집 | G6 위임 전후 자동 체크포인트 커밋 |
| Codex 토큰 낭비 | G8 요약·위험 diff만 반환, 폴링 없음 |
| 무한 재시도 | 같은 원인 3회 → BLOCKED |
| 비밀 유출 | 자식 env 자격증명 제거, DB·로그에 전문 미저장 |
| 비가역 외부 행동 | 삭제·push·배포·결제·권한 변경은 행동별 사용자 승인 |

## 9. 출처

로컬: `agy --help`, `agy -p --output-format json` 프로브, `codex exec --help`, `antigravity-bridge/index.js`, `~/.codex/config.toml`, `.coord/`, `pytest`.

- [Google Antigravity Headless mode](https://antigravity.google/docs/cli/headless/)
- [agy #1012 exit 0 with partial-output timeout](https://github.com/google-antigravity/antigravity-cli/issues/1012)
- [agy #548 print mode ignores permissions.allow](https://github.com/google-antigravity/antigravity-cli/issues/548)
- [agy #318 print hangs in non-TTY](https://github.com/google-antigravity/antigravity-cli/issues/318)
- [agy #947 headless process never exits](https://github.com/google-antigravity/antigravity-cli/issues/947)
- [Codex CLI subagent gotchas (파일 기반 결과 인계 권장)](https://codex.danielvaughan.com/2026/03/29/subagent-gotchas-known-issues/)
- [hermes-agent PR #3385: SQLite WAL write-lock contention](https://github.com/NousResearch/hermes-agent/pull/3385)
- [Zylos: SQLite WAL patterns for AI agent systems](https://zylos.ai/research/2026-02-20-sqlite-wal-mode-ai-agent-systems/)
- [Beads: SQLite + JSONL agent task tracker](https://betterstack.com/community/guides/ai/beads-issue-tracker-ai-agents/)
- [SQLite WAL](https://sqlite.org/wal.html)
