# U08 전역 연결·비용 최적화 감사와 연속 실행 계약

- 기준일: 2026-09-16 (로컬 실측: 2026-09-17)
- 상태: `REVIEW CANDIDATE`
- 결정: `PIVOT` — 물리 연결 실패 0%가 아니라 **증거 손실 0건과 안전한 자동 폴백**을 목표로 하며, 로컬 SQLite durable coordination plane을 우선안으로 선택한다.
- 범위: Codex/Antigravity 전역 rules·skills·memory·vibe diagnosis·MCP, 두 로컬 참조 프로젝트, 공개 공식자료·GitHub·Reddit 보조 근거
- 비범위: 삭제·덮어쓰기·설치·전역 설정 변경·push·배포·결제·계정/권한/자격증명 변경

## 1. 결과 요약

현 환경은 `agy` CLI와 `antigravity-bridge`의 기본 연결은 살아 있지만, 장애 뒤에도 작업·소유권·증거를 보존하는 연속 실행 시스템은 아니다. 브리지는 비동기 job JSON, 프로세스 heartbeat, timeout, 결과 polling을 제공한다. 반면 idempotency key, 원자적/추가 전용 checkpoint, lease/fencing token, 재시작 reconciliation, 오류 분류, bounded retry, circuit breaker, quota-aware routing, proof receipt는 없다.

따라서 브리지 성공을 작업 성공으로 취급하지 않고, `.coord`의 단일 계획과 U07의 context lease·intent ledger·proof receipt를 조율 정본으로 유지한다. 런타임 상태는 한 로컬 머신의 로컬 디스크에 둔 SQLite 상태 원장+내구성 inbox/outbox로 보존한다. Antigravity 연결이 끊기면 같은 작업 ID와 checkpoint에서 Codex가 이어받되, 외부 부작용 가능성이 있는 명령은 자동 재실행하지 않는다.

## 2. MIA 4단계 결정

### 2.1 Frame

- 사용자 문제: Antigravity 연결·quota·프로세스가 실패할 때 작업이 사라지거나 중복 실행되고, 성공처럼 보이는 것을 막는다.
- 성공 신호: acknowledged checkpoint 이후 작업/소유권/증거 손실 0건, 중복 부작용 0건, 자동 폴백 성공률과 복구시간을 측정 가능하게 만든다.
- 비목표: 네트워크/CLI/API 자체의 장애율 0%, 특정 공급자 역할의 영구 고정, 측정 없는 비용 절감 주장.

### 2.2 Review — 대안과 4대 렌즈

| 대안 | 가치 | 실현성 | 지속성 | 위험 | 판정 |
|---|---:|---:|---:|---:|---|
| 브리지 자동 재시도만 추가 | 중 | 높음 | 낮음 | 비멱등 중복 실행, quota 폭주 | No-Go |
| Antigravity 실패 즉시 Codex 재실행 | 중 | 높음 | 중 | checkpoint 없는 이중 쓰기 | No-Go |
| 로컬 SQLite durable plane + bounded retry + checkpoint 기반 Codex 폴백 | 높음 | 중 | 높음 | DB 운영·장애주입 필요 | Go |
| Ollama를 상시 3번째 실행자로 복구 | 낮음 | 낮음 | 낮음 | 현재 미설치·미실행, 품질 미측정 | No-Go now |

### 2.3 Execute

이 문서에 최소 계약, 상태기계, 오류 분류, SQLite 스키마, SLO, 장애주입 테스트, 가역적 후보 diff를 고정한다. 전역 파일과 브리지 코드는 수정하지 않는다.

### 2.4 Verify

로컬 구조·Git 객체·CLI·정적 구문·공식 링크를 확인했다. 실제 위임, quota 소진, 프로세스 kill, 재부팅 복구는 외부 부작용/사용량을 만들 수 있어 이번 단계에서는 테스트 계획만 확정했으며 결과는 `UNKNOWN`이다.

## 3. 증거 지도

| 주장 | 판정 | 등급 | 근거 |
|---|---|---|---|
| 현재 프로젝트는 비Git이며 독립 worktree를 만들 수 없다 | FACT | L1 로컬 실측 | 루트 `git status` exit 128 |
| `260912` 작업트리는 HEAD 파일 전체가 삭제 표시다 | FACT | L1 로컬 실측 | `git status --short --branch`; 사용자 변경 보존 |
| C3P 협의체/예산절약은 외부 표준이 아니라 로컬 명칭이다 | FACT | L1 | `260823`의 `C3P_RETIREMENT_DECISION.md`, `260912` HEAD의 README/docs |
| 85% 이상 토큰 절감 | UNVERIFIED | L3 내부 주장 | `260912` README에 수치가 있으나 A/B receipt 없음 |
| 비용·토큰 절감 | UNMEASURED | L1 정책 | 전역 규칙과 U07 benchmark가 `UNMEASURED`로 기록 |
| `agy` CLI가 현재 호출 가능하다 | FACT | L1 | v1.2.4, version/agents/models exit 0 |
| 브리지가 최소 정적 기동 조건을 충족한다 | FACT | L1 | `node --check index.js` exit 0, npm script check exit 0 |
| 브리지 heartbeat가 durable lease다 | FALSE | L1 코드 | 로그 notification일 뿐 expiry/fencing/owner 검증 없음 |
| 브리지 job 저장이 손실 방지 원장이다 | FALSE | L1 코드 | 임시 디렉터리 JSON을 `writeFileSync`로 덮어쓰고 예외를 무시 |
| Antigravity는 멀티에이전트 조율을 지원한다 | FACT | L2 공식 | Google Codelab의 central command center/parallel agents/workflows |
| Codex는 보안·스켈레톤만 담당해야 한다 | UNVERIFIED POLICY | L2+추론 | Codex 공식 자료도 다중 agent/worktree를 지원; 배타적 제품 역할 근거 없음 |
| Ollama가 현재 복구 가치가 있다 | NO-GO NOW | L1 | command 없음, process 없음, 11434 미수신; 호출 경로는 폐기된 HEAD 구현에만 존재 |

등급: L1=로컬 직접 실측/코드, L2=공식 1차 자료, L3=저장소 내부 문서 또는 커뮤니티 보조, L4=추론.

## 4. 전역 환경 감사

### 4.1 규칙·스킬·메모리

- Codex 전역 규칙 v6와 Antigravity 전역 규칙은 모두 29줄의 얇은 공통 규칙이며 프로젝트 세부는 가까운 정본으로 넘긴다. 방향은 적절하다.
- 프로젝트 정본은 `docs/01_unified-agent-orchestration-design.md`; `AGENTS.md`와 `.agents/rules/unified-codex-antigravity.md`는 어댑터다. 별도 `shared-specs.md`나 `AGENTS-CONSENSUS.md`를 만들면 정본이 늘어나므로 채택하지 않는다.
- 스킬은 Codex 6개(시스템 디렉터리 포함), shared agents 11개, Antigravity 14개다. 공통 개발 스킬 11개가 `.agents`와 Antigravity에 겹치지만 소비자별 설치 경로이므로 이름 중복만으로 삭제하지 않는다. 내용 hash/로더 우선순위가 달라질 때만 동기화 대상으로 삼는다.
- 메모리는 3개 상위 파일에 과거 C3P 예산절약과 현재 폐기 결정을 함께 담고 있다. 경로/시간 scope가 있으나 요약에 과거 호출법이 남아 현재 정본처럼 재사용될 위험이 있다. 후보 조치: 메모리 삭제가 아니라 `status=historical`, `superseded_by=260823/.../C3P_RETIREMENT_DECISION.md`, `valid_until=2026-09-15` 메타데이터를 추가한다.

### 4.2 MCP·vibe diagnosis

- Codex 설정에서 확인된 실제 상위 MCP는 `node_repl`, `antigravity-bridge`다. `[mcp_servers.node_repl.env]`는 별도 서버가 아니라 하위 설정이다.
- Antigravity `mcp_config.json`의 파서 기준 등록 서버는 0개였다. 과거 brain 문서의 `vibe-clinic`, `notebooklm` 등록 주장은 현재 설정 증거가 아니다.
- `mia-vaccine-test`는 Codex와 Antigravity 양쪽에 있고 vibe-clinic 연계를 설명하지만, 현재 호출 가능한 MCP 인벤토리와 맞지 않는다. 진단 규칙은 보존하되 MCP availability preflight 실패 시 로컬 진단 파일/일반 테스트로 명시적 downgrade해야 한다.

### 4.3 브리지 충돌·결함

1. `use_antigravity` 설명은 auto approve 기본값을 `true`라 하지만 구현 상수는 `false`다.
2. job ID는 시간+난수이며 caller idempotency key가 없다.
3. `writeJob`은 비원자 덮어쓰기이고 오류를 삼킨다.
4. heartbeat는 로그뿐이며 `lastHeartbeatAt`, lease expiry, fencing token이 없다.
5. 프로세스 재시작 뒤 JSON의 `running`을 `ORPHANED`로 바꾸는 reconciliation이 없다.
6. `error` 문자열만 있어 auth/quota/transient/permanent/unsafe-unknown을 구분하지 못한다.
7. retry/circuit breaker/quota switch가 없다.
8. `done`은 출력 존재/검증/해시/허용 범위 준수를 증명하지 않는다.
9. cleanup은 파괴적 도구이며 receipt 보존기간/참조 여부와 연결되지 않는다.

## 5. 최소 연속 실행 계약 v0.1

### 5.1 Dispatch envelope

```json
{
  "contract_version": "0.1",
  "task_id": "U08",
  "attempt_id": "U08-a001",
  "idempotency_key": "sha256(task_id+scope_hash+intent_hash)",
  "mode": "managed|standalone|imported",
  "owner": "codex|antigravity",
  "scope": {"paths": [], "git_ref": null, "db": [], "ports": [], "external": []},
  "lease": {"lease_id": "...", "fencing_token": 1, "expires_at": "..."},
  "checkpoint_in": "sha256-or-null",
  "budgets": {"max_attempts": 3, "max_elapsed_ms": 900000, "quota_floor_pct": 10},
  "approval_boundary": ["delete", "overwrite", "push", "deploy", "payment", "account_or_permission"],
  "acceptance_hash": "sha256(acceptance-contract)"
}
```

### 5.2 역할 모드

| 모드 | 조율 정본 | 실행 권한 | 완료 권한 |
|---|---|---|---|
| managed | Codex `.coord/PLAN.md`+card | Antigravity는 lease 범위만 | Codex 검토만 `DONE` |
| standalone | Antigravity workspace-local plan | 해당 workspace 범위 | standalone verifier; managed 상태 변경 금지 |
| imported | 원 소유자 checkpoint를 읽기 전용 수입 | 새 lease 발급 전 쓰기 금지 | 원 정본과 reconciliation 후 결정 |

### 5.3 상태 기계

```text
READY -> PREFLIGHT -> LEASED -> RUNNING -> CHECKPOINTED -> VERIFYING -> SUCCEEDED
             |           |         |             |            |
             v           v         v             v            v
          REJECTED    EXPIRED    DEGRADED      FALLBACK      FAILED_SAFE
                                   |              |
                                   +-> RETRY_WAIT-+

RUNNING --lost heartbeat--> SUSPECT --grace elapsed--> ORPHANED
ORPHANED --safe checkpoint + fence bump--> FALLBACK(Codex)
ORPHANED --side effect unknown--> NEEDS_RECONCILIATION (자동 재실행 금지)
```

불변식: `(task_id, idempotency_key)`당 유효 owner/lease는 하나, fencing token은 단조 증가, checkpoint와 receipt는 append-only, `SUCCEEDED`는 proof receipt 검증 뒤만 허용한다.

### 5.4 오류 분류와 복구

| 분류 | 예 | 자동 행동 | 재시도 |
|---|---|---|---|
| TRANSIENT_TRANSPORT | stdio 끊김, timeout | checkpoint 확인 후 jitter backoff | 최대 2회 |
| WORKER_CRASH | agy 프로세스 종료 | lease 만료→ORPHANED→Codex 폴백 | 1회 reconnect 후 |
| AUTH | 인증 만료 | circuit open, 기존 증거 보존 | 자동 재시도 없음 |
| QUOTA | rate/quota exhausted | 신규 Antigravity 위임 차단, Codex budget 가능 시 폴백 | reset 시각 뒤 half-open |
| CAPABILITY | 모델/agent/도구 없음 | negotiated capability로 재계획 | 동일 요청 재시도 없음 |
| VALIDATION | 빈 출력, hash/acceptance 불일치 | 실패 receipt, 같은 owner에 보완 | 최대 1회 |
| SCOPE_CONFLICT | lease path/db/port 충돌 | fail closed | 범위 재분할 전 없음 |
| SIDE_EFFECT_UNKNOWN | push/API write 중 연결 단절 | reconciliation 대기 | 자동 재실행 금지 |
| PERMANENT | 잘못된 입력/지원 불가 | FAILED_SAFE | 없음 |

### 5.5 preflight와 capability negotiation

1. 조율 정본·카드 상태·현재 owner 확인.
2. Git 여부와 dirty state 확인; 비Git이면 deterministic manifest hash를 checkpoint로 사용.
3. `agy --version`, requested model/agent, sandbox/permission mode, bridge contract version 확인.
4. quota 정보가 없으면 `UNKNOWN`; 충분하다고 가정하지 않는다.
5. requested capabilities와 worker capabilities의 교집합만 lease에 기록.
6. path/db/port/branch/external resource lease 충돌 시 시작하지 않는다.
7. checkpoint와 acceptance hash를 먼저 durable store에 기록한 뒤 dispatch한다.

## 5.6 SQLite durable coordination plane

SQLite는 Codex와 Antigravity가 직접 대화하는 transport가 아니다. 조율자가 command를 outbox에 커밋하고 worker launcher가 이를 claim해 Antigravity를 실행하며, 결과를 inbox/event/checkpoint/receipt로 다시 커밋하는 로컬 내구성 원장이다. DB 커밋이 메시지의 권위이고 MCP/stdio는 교체 가능한 전달 어댑터다.

### 배치와 연결 정책

- 단일 Windows 머신의 NTFS 로컬 디스크만 지원한다. 네트워크 드라이브, SMB/NFS, OneDrive/Dropbox/동기화 폴더, 이동식 디스크는 fail closed한다.
- DB, `-wal`, `-shm`은 같은 로컬 디렉터리에 두고 해당 디렉터리는 현재 사용자와 실행 서비스 계정만 접근하도록 ACL 후보를 제시한다. ACL 변경은 별도 승인 대상이다.
- 연결마다 `foreign_keys=ON`, `busy_timeout=5000ms`를 설정한다. timeout 뒤 무한 대기하지 않고 `DB_BUSY`로 분류해 bounded retry한다.
- `journal_mode=WAL`; 연속 실행 원장의 전원 손실 내구성이 중요하므로 초기 기본은 `synchronous=FULL`이다. `NORMAL`은 벤치마크에서 성능 이득과 전원 손실 허용을 명시적으로 승인한 뒤에만 후보로 둔다.
- WAL은 reader/writer 동시성을 개선하지만 writer는 한 번에 하나다. 모든 쓰기는 조율자 내 단일 writer queue로 직렬화하고 트랜잭션을 짧게 유지한다.
- claim/renew/complete는 `BEGIN IMMEDIATE` 안의 조건부 `UPDATE ... WHERE fencing_token=? AND state=?`와 `changes()==1` 확인으로 원자화한다. 네트워크 호출·모델 실행·파일 hash 계산은 트랜잭션 밖에서 한다.
- 자동 checkpoint는 기본값을 관찰하고, writer queue가 유휴이며 장기 reader가 없을 때 `wal_checkpoint(PASSIVE)`를 수행한다. `TRUNCATE`는 운영 중 강제하지 않는다.

### 필수 스키마와 데이터 최소화

가역적 후보 DDL은 `proposals/u08-sqlite-coordination-schema.sql`이다. `schema_meta`, `agents`, `tasks`, `attempts`, `leases`, `commands`, append-only `events`, `checkpoints`, `proof_receipts`, `budgets`, 통합 `deliveries(direction=outbox|inbox)`를 포함한다.

- DB에 넣는 것: opaque ID, 상태, hash, 상대 artifact reference, 짧은 오류 분류, 시각, quota/circuit 상태.
- 넣지 않는 것: API key/token/cookie/자격증명, 전체 프롬프트, 전체 모델 출력, 환경변수 덤프, 소스 전문, 불필요한 로그, 개인정보.
- 큰 artifact는 workspace 내부 파일로 두고 DB에는 경로·크기·SHA-256만 저장한다. artifact도 lease scope를 벗어나면 참조하지 않는다.
- events/proof receipt는 append-only다. mutable 현재 상태(tasks/leases/deliveries)는 event와 같은 트랜잭션에서 갱신한다.
- 보존 기본 후보: active/needs_reconciliation 무기한, succeeded/failed receipt 30일, heartbeat/detail event 7일. 정리는 참조 무결성·backup 성공·별도 사용자 승인 뒤 chunk 단위로 수행한다.

### 원자적 프로토콜

```text
enqueue: BEGIN IMMEDIATE
  INSERT task ON CONFLICT(idempotency_key) DO NOTHING
  INSERT command/delivery ON CONFLICT(idempotency_key) DO NOTHING
  INSERT event(command_enqueued)
COMMIT

claim: BEGIN IMMEDIATE
  UPDATE tasks SET owner=?, fencing_token=fencing_token+1, state='leased'
    WHERE task_id=? AND state IN ('ready','retry_wait','fallback')
  INSERT lease(... new fencing_token ...)
  UPDATE delivery SET state='claimed', claim_expires_at=? WHERE state='pending'
COMMIT

renew/complete: BEGIN IMMEDIATE
  UPDATE lease/task/delivery ...
    WHERE task_id=? AND owner=? AND fencing_token=? AND expires_at>now
  require changes()==1
  INSERT checkpoint/event/proof_receipt
COMMIT
```

stale worker의 fencing token이 현재 task token보다 작으면 파일/API write 전과 completion commit 모두 거부한다. SQLite 밖의 외부 시스템이 idempotency/fencing을 지원하지 않으면 결과를 `SIDE_EFFECT_UNKNOWN`으로 분류하고 자동 재실행하지 않는다.

### 무결성·backup·복구

1. 기동 preflight: DB 경로가 로컬인지 확인 → SQLite version/schema hash 확인 → `PRAGMA quick_check` → migration 상태 확인.
2. 정기/변경 전 backup: SQLite online backup API로 새 로컬 파일에 복제 → backup에서 `PRAGMA integrity_check`와 `foreign_key_check` → 원본과 backup의 schema version/hash 기록.
3. 손상 감지: writer circuit open, 새 위임 중단, 살아 있는 artifact/checkpoint를 보존하고 검증된 최신 backup을 별도 새 경로로 복원한다. 원본을 덮어쓰지 않는다.
4. migration: 단일 writer/lease drain → backup 검증 → `BEGIN IMMEDIATE` 안에서 forward-only migration과 `schema_meta` 갱신 → 검사 실패 시 rollback. migration SQL은 idempotent version gate를 가진다.
5. 복구 불가·disk full·지속 DB_BUSY: Codex-only fallback으로 새 쓰기를 최소 로컬 proof 파일에 append하고 Antigravity 신규 위임을 중단한다. DB와 파일 원장이 다시 조정되기 전에는 자동 병합하지 않는다.

### 브리지의 새 위치

| 선택 | 장점 | 단점 | 판정 |
|---|---|---|---|
| 현 MCP 브리지가 상태까지 계속 소유 | 변경 적음 | 비원자 JSON·재시작 손실·MCP 결합 | No-Go |
| SQLite core + MCP bridge adapter/worker launcher | 기존 도구 호환, 상태와 transport 분리 | adapter 구현 필요 | 우선 Go |
| SQLite core + 직접 `agy` launcher로 MCP 대체 | 단순한 런타임 경로 | 기존 MCP UI/도구 호환 상실 | 2차 비교 |

초기에는 bridge의 `use/result` 앞뒤를 SQLite adapter가 감싸고, bridge job ID는 attempt의 provider reference로만 저장한다. 안정화 후 direct launcher와 동일 장애주입 벤치마크를 비교해 더 단순한 경로를 선택한다.

## 6. SLO와 비용 라우팅

| 지표 | 초기 목표 | 측정식 |
|---|---:|---|
| acknowledged checkpoint loss | 0건/장애주입 100회 | ack 후 복구 불가 checkpoint 수 |
| duplicate side effects | 0건 | 동일 idempotency key의 중복 외부 write |
| ownership conflict | 0건 | 동시 유효 lease/fence 위반 |
| safe auto-recovery rate | >=99% | 안전 분류 장애 중 사용자 개입 없는 복구 비율 |
| recovery time p95 | <=120초 | failure_detected→new owner RUNNING |
| false success | 0건 | proof 불충족인데 SUCCEEDED인 건수 |
| quota circuit reaction p95 | <=15초 | quota signal→new delegation blocked |
| result correctness | baseline 대비 비열등(-2%p 이내) | 동일 fixture acceptance pass rate |
| cost/token saving | `UNMEASURED` until A/B | 동일 acceptance의 provider usage/receipt 비교 |

예산 라우터 우선순위는 `완료 가능성→정확도→안전→지연→비용`이다. 저비용 경로가 acceptance pass rate를 2%p 넘게 낮추거나 p95 지연을 2배 넘기면 중단한다. quota가 10% 이하이거나 reset 정보가 불명확하면 신규 Antigravity 작업을 차단하고 Codex 가능 예산을 확인한다. 두 공급자 모두 불가하면 checkpoint를 남기고 `BLOCKED_QUOTA`로 반환한다.

## 7. 장애주입 테스트 계획

모든 테스트는 임시 디렉터리·mock worker·가짜 quota 응답으로 먼저 수행한다.

| ID | 주입 | 기대 결과 |
|---|---|---|
| F01 | dispatch 직후 bridge 종료 | idempotency key로 중복 시작 없이 reconnect |
| F02 | job JSON 반만 기록 | checksum 실패, 이전 checkpoint 복원 |
| F03 | heartbeat 정지/프로세스 생존 | SUSPECT→lease expiry→fence bump |
| F04 | 완료 직전 worker kill | 마지막 ack checkpoint에서 Codex 폴백 |
| F05 | 동일 envelope 10회 전송 | 실행 1회, 나머지 동일 attempt 조회 |
| F06 | quota exhausted 응답 | circuit open, 신규 위임 0건 |
| F07 | auth 오류 | 자동 retry 0, 사용자 조치 필요 receipt |
| F08 | 모델 목록 변경 | capability mismatch로 재계획, silent downgrade 0 |
| F09 | path/db/port lease 충돌 | 두 번째 작업 fail closed |
| F10 | 외부 write 응답 전 연결 단절 | NEEDS_RECONCILIATION, 자동 재실행 0 |
| F11 | bridge 재시작 후 stale running JSON | ORPHANED로 reconciliation |
| F12 | 빈 출력 exit 0 | VALIDATION 실패, 성공 처리 0 |
| F13 | proof hash 변조 | VERIFYING에서 차단 |
| F14 | Codex quota도 부족 | BLOCKED_QUOTA, checkpoint 보존 |
| F15 | 비Git manifest 중 파일 변경 | stale checkpoint 감지, 인계 차단 |
| F16 | DB writer lock을 busy_timeout보다 길게 유지 | DB_BUSY, 무한 대기 0, bounded retry |
| F17 | commit 전/후 worker 프로세스 강제 종료 | 전부 rollback 또는 전부 commit, 반쪽 상태 0 |
| F18 | stale lease worker가 늦게 complete | fencing token 조건부 UPDATE 0행, 완료 거부 |
| F19 | delivery를 중복 claim/전달 | idempotency unique로 명령 실행 1회 |
| F20 | DB 파일 손상 사본으로 기동 | quick/integrity check 실패, circuit open, 원본 덮어쓰기 0 |
| F21 | 디스크 full/쓰기 I/O 오류 | commit 실패, false ack 0, Codex-only fallback |
| F22 | schema migration 중 DDL 오류 | transaction rollback, 이전 schema 사용 가능 |
| F23 | 장기 reader로 WAL checkpoint 방해 | writer 지속, 경고/재시도, 강제 TRUNCATE 0 |
| F24 | DB를 동기화/네트워크 경로로 지정 | preflight REJECTED |

최소 통과선은 F01–F24 각 20회, 총 480회에서 checkpoint loss/duplicate side effect/false success/ownership conflict 모두 0건이다.

## 8. 가역적 적용 후보 diff

브리지 원본 저장소에 기존 미확인 수정 5개가 있어 이번 단계에서 편집하지 않았다. 별도 승인·깨끗한 쓰기 범위가 확보되면 다음 순서로 작은 PR/단계로 나눈다.

1. 문서 계약 수정: `auto_approve` 도구 설명을 실제 기본값 `false`와 일치시킨다.
2. 별도 `coordination_store`에 후보 SQLite schema를 적용하고 schema hash/quick check를 기동 게이트로 둔다.
3. `idempotency_key` unique index와 동일 요청 재조회.
4. lease owner/expiry/monotonic fencing token/scoped resources를 조건부 transaction으로 구현.
5. startup reconciliation: stale `running`→`ORPHANED`; PID만으로 성공 판단 금지.
6. normalized error classifier와 retry budget/circuit breaker.
7. checkpoint/proof receipt를 U07 harness 형식으로 내보내고 `done`과 `verified`를 분리.
8. bridge를 DB adapter/worker launcher로 감싸고 direct `agy` launcher와 비교한다.
9. mock-worker SQLite 장애주입 480회 통과 후에만 실제 agy canary 1건 수행.

롤백은 각 모듈 feature flag를 끄고 기존 9개 MCP 도구 동작으로 복귀하되, 새 receipt 파일은 보존한다. cleanup은 참조되지 않은 만료 receipt만 대상으로 별도 사용자 승인 후 수행한다.

## 9. DEEPDIVE / REDTEAM / OPTIMIZE 판정

- DEEPDIVE: job persistence는 존재하지만 continuity가 아니다. 임시 JSON과 로그 heartbeat는 ownership·durability 증거가 아니다.
- REDTEAM: 무제한 retry, 자동 공급자 전환, 오래된 대화 continue는 각각 중복 부작용·비용 폭주·잘못된 컨텍스트 승계를 만든다.
- OPTIMIZE: 새 중앙 허브를 만들기보다 U07 harness를 durable envelope/receipt로 확장하고, bridge는 transport adapter로 축소한다. 단일 원본은 현재 `docs/01 + .coord`를 유지한다.

## 9.1 SQLite와 MCP Decision Gate

비교 대상은 다음 세 가지다.

- **A — 현재 MCP 브리지 보강:** bridge 내부 JSON job store를 개선하고 MCP가 호출과 상태를 모두 소유한다.
- **B — SQLite + `coordctl` 완전 대체:** SQLite를 권위 원장으로 두고 `coordctl` poll/claim/renew/complete와 직접 `agy` launcher만 사용한다.
- **C — SQLite durable control plane + 선택적 MCP transport:** B의 권위 원장과 `coordctl`을 유지하되, 외부 도구 호출·MCP client 호환이 필요한 작업에만 MCP adapter를 쓴다.

평가 척도는 5=현재 요구에 가장 적합, 1=가장 부적합이다. 비용은 현재 PC에서 추가 서비스·인증·운영 부담이 적을수록 높은 점수다.

| 평가축 | A MCP 보강 | B SQLite+coordctl | C SQLite+선택 MCP | 근거/레드팀 판정 |
|---|---:|---:|---:|---|
| 로컬 단일 PC 적합성 | 3 | 5 | 5 | SQLite in-process와 로컬 stdio 모두 가능하나 B/C가 별도 서비스 없이 권위 상태를 보존 |
| 내구성·재시작 복구 | 2 | 5 | 5 | MCP lifecycle/session은 연결 계약이지 durable task ledger가 아님; SQLite transaction/WAL/backup이 우세 |
| 실시간 양방향 호출 | 5 | 2 | 5 | MCP stdio/Streamable HTTP는 JSON-RPC 양방향 호출·notification을 표준화; SQLite polling만으로는 push가 아님 |
| capability/version negotiation | 5 | 2 | 5 | MCP initialize에서 protocol version·capability·implementation info를 교환; B는 자체 schema/capability 계약 필요 |
| 멱등성·lease·fencing | 2 | 5 | 5 | MCP 기본 lifecycle은 이 불변식을 제공하지 않음; SQLite unique+조건부 UPDATE+transaction으로 직접 강제 |
| 감사성 | 3 | 5 | 5 | append-only events와 receipt를 단일 transaction에 묶는 B/C 우세 |
| 보안 표면 | 3 | 5 | 4 | B는 로컬 ACL/프로세스 경계만; HTTP MCP는 OAuth·Origin·localhost binding·token storage 표면 추가. stdio auth는 환경 의존 |
| 설치·운영 복잡도 | 3 | 5 | 4 | A는 bridge 기능 집중으로 복잡해지고, C는 adapter가 하나 더 있지만 책임 분리가 명확 |
| 네트워크·다중 호스트 확장 | 5 | 1 | 5 | SQLite WAL은 네트워크 FS 금지. MCP Streamable HTTP는 다중 연결·원격 auth 가능 |
| 성능 | 4 | 5 | 4 | 단일 PC의 짧은 상태 transaction은 SQLite가 작고 빠름; C는 외부 호출에 adapter hop 추가 |
| 장애 격리 | 2 | 5 | 5 | A의 bridge crash가 상태와 transport를 함께 위협; B/C는 DB commit과 launcher 실패를 분리 |
| 비용 | 3 | 5 | 4 | 모두 추가 모델 비용을 줄인다는 증거는 없음. B가 운영 구성요소 최소, C는 호환성 비용을 선택적으로 지불 |
| **합계 / 60** | **40** | **50** | **56** | C가 현재 요구와 향후 외부 도구 호환을 함께 만족 |

### Decision Gate

**결정: C — SQLite durable control plane + 선택적 MCP tool transport (`GO`)**

현재 단일 Windows PC에서는 SQLite+`coordctl`이 유일한 권위 상태 원장이다. task/attempt/lease/command/event/checkpoint/receipt/budget은 MCP session이나 bridge job JSON에 권위를 주지 않는다. `coordctl`은 DB를 읽고 쓰는 유일한 조율 CLI/라이브러리 경계이며 단일 writer queue를 소유한다.

MCP는 삭제하지 않는다. 다음 경우에만 선택적 adapter로 쓴다.

1. Codex MCP client가 Antigravity tool을 호출해야 할 때.
2. 표준 initialize 기반 capability/version negotiation이 필요할 때.
3. 진행 notification 또는 양방향 외부 tool request가 사용자 경험을 실제로 개선할 때.
4. 향후 다중 호스트가 요구되어 Streamable HTTP를 검토할 때. 이 경우 SQLite 파일을 공유하지 않고 각 host adapter가 별도 서버/API를 통해 authoritative writer에 접근한다.

MCP 호출 전 command/outbox가 SQLite에 commit되어야 하고, 호출 후 결과/inbox/checkpoint/receipt가 SQLite에 commit되어야 한다. MCP request/session/event ID는 provider reference일 뿐 idempotency key나 fencing token을 대체하지 않는다. 연결 종료는 작업 취소로 해석하지 않으며, MCP 공식 transport도 disconnection을 cancellation으로 간주하지 말라고 규정한다.

### 대안 탈락 사유와 전환 조건

- A 탈락: MCP의 lifecycle, capability negotiation, transport는 강하지만 durable ownership·lease·fencing·proof를 기본 제공하지 않는다. 이를 bridge 안에 모두 재구현하면 transport와 조율 상태가 다시 결합된다.
- B 보류: 현재 단일 PC만 보면 가장 단순하지만 MCP의 표준 tool discovery, version/capability negotiation, 양방향 notification을 버리는 비용이 크다.
- C 채택: B의 안전성과 A의 interoperability를 분리해 결합한다. MCP 미사용 시에도 전체 조율이 동작해야 한다.
- B로 축소: MCP adapter가 3개 실제 작업에서 완료율/복구시간 개선 없이 장애·운영비만 늘리면 제거 후보로 전환한다.
- 원격 DB로 확장: 다중 호스트 요구가 실제로 생기면 SQLite network share를 금지하고 PostgreSQL/서비스형 coordination plane을 별도 Decision Gate에서 평가한다.

공식 MCP 계약은 initialization→operation→shutdown lifecycle, version/capability negotiation, per-request timeout을 정의한다. 표준 transport는 stdio와 Streamable HTTP이며, HTTP는 resumability를 선택적으로 제공하지만 연결 단절 자체는 취소가 아니다. HTTP authorization은 선택적 OAuth 계층이고 stdio는 해당 흐름을 쓰지 않으며 환경에서 credential을 얻는다. 따라서 MCP는 호출 상호운용 계층으로 가치가 높지만 이 프로젝트의 durable state 원장 역할과 동일하지 않다.

## 10. 미검증·잔여 위험

- 실제 bridge MCP handshake/위임/재연결과 Antigravity quota 오류 형태: `UNKNOWN`.
- 공급자별 정확한 usage/cost API와 동일 작업 A/B 비용: `UNMEASURED`.
- 실제 멀티프로세스 lease 경합과 Windows 전원/프로세스 강제 종료 내구성: `UNKNOWN`.
- Antigravity standalone에서 Codex를 직접 호출하는 공식 capability: 확인된 공식 근거 없음.
- Reddit은 운영 사례를 찾는 보조 자료일 뿐 계약의 권위 근거로 사용하지 않았다.

## 11. 공개 근거

- OpenAI, Codex app 소개: https://openai.com/index/introducing-the-codex-app/
- OpenAI Symphony service specification: https://github.com/openai/symphony/blob/main/SPEC.md
- Google, Antigravity 시작하기: https://codelabs.developers.google.com/getting-started-google-antigravity
- Google, agents.md/skills.md 기반 autonomous pipeline: https://codelabs.developers.google.com/autonomous-ai-developer-pipelines-antigravity
- SQLite, Write-Ahead Logging: https://sqlite.org/wal.html
- SQLite, PRAGMA (foreign_keys, busy_timeout, synchronous, integrity_check): https://sqlite.org/pragma.html
- SQLite, transactions (`BEGIN IMMEDIATE`): https://sqlite.org/lang_transaction.html
- SQLite, Online Backup API: https://sqlite.org/backup.html
- MCP, Lifecycle and capability/version negotiation: https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle
- MCP, stdio and Streamable HTTP transports: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
- MCP, HTTP authorization: https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization

공식 근거가 지지하는 것은 두 제품 모두 조율·격리·장기 작업 기능을 가진다는 점과, SQLite WAL이 같은 호스트에서 reader/writer 동시성을 제공하되 단일 writer이고 네트워크 파일시스템을 지원하지 않는다는 점이다. 본 문서의 lease/idempotency/circuit-breaker 수치는 로컬 운영 설계이며 공식 제품 보장을 인용한 것이 아니다.
