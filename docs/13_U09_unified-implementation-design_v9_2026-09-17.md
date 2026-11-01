# U09 Codex–Antigravity 통합 구현 설계 v9

- 작성일: 2026-09-17
- 상태: `REVIEW CANDIDATE`
- 범위: 설계만 포함하며 구현·설치·Git 초기화·전역 수정·삭제·push·배포를 포함하지 않는다.
- 권위: 사용자 원문, 플랫폼/프로젝트 규칙, 로컬 실측, 공식 1차 근거가 우선한다. `docs/11`, `docs/12`는 비권위 참고 입력이다.
- 비용·토큰 절감: `UNMEASURED`

## 1. 결정 요약

v9는 Codex가 하나의 계획과 검증 게이트를 소유하고 Antigravity가 범위가 임대된 실행을 맡는 managed 모델을 유지한다. 제품별 영구 업무 구분은 폐기하고, 프로젝트 진단 결과로 파일·포트·DB·캐시·빌드 산출물·환경을 포함하는 동적 scope/resource lease를 발급한다.

연속 실행의 권위 상태는 로컬 SQLite에 저장하되, SQLite 자체를 IPC로 부르지 않는다. Windows 장수명 `coordd` broker가 Named Pipe로 명령을 받아 SQLite 쓰기를 독점한다. CLI와 선택적 MCP 어댑터는 같은 broker API의 클라이언트일 뿐이다. 이 선택은 “여러 CLI가 DB를 직접 쓰면서 단일 writer”라는 v8의 모순을 제거한다.

실행 격리는 다음과 같다.

- Git 프로젝트: 작업별 Codex managed worktree 또는 명시적으로 만든 별도 worktree/branch에서 실행하고 merge gate를 통과한 patch만 승격한다.
- 비Git 프로젝트: 원본의 deterministic manifest와 staging copy를 만들고 Antigravity는 staging에서만 실행한다. 원본과 staging의 검증된 patch manifest를 만든 뒤 scope·hash·검사를 통과한 변경만 승인된 promotion 단계에서 원본에 적용한다.
- `agy --add-dir`는 추가 workspace 접근 수단이지 보안 경계가 아니다. 실제 경계는 Antigravity `--sandbox`, 세분화 allow/deny 규칙, OS 파일 권한, staging/worktree 격리의 조합이다.
- `--dangerously-skip-permissions`는 기본 경로에서 금지한다. headless 권한 결함이 있으면 원본 권한을 넓히지 않고 격리 staging에서 fail-closed한다.

“연결 실패 0%”와 “100% 자동 복구”는 보장하지 않는다. 목표는 정의된 장애주입 범위에서 acknowledged state loss, duplicate externally-visible effect, false success, stale-worker promotion을 각각 0건으로 만드는 것이다. 그 범위 밖에서는 `UNKNOWN` 또는 `NEEDS_RECONCILIATION`으로 정직하게 중단한다.

## 2. 문제와 비목표

### 2.1 해결할 문제

1. Codex와 Antigravity가 서로 다른 계획을 만들거나 같은 자원을 동시에 수정한다.
2. 프로세스·CLI·대화가 끊겼을 때 소유권, 시도, 결과, 외부 부작용 여부가 모호하다.
3. 비Git 프로젝트에서 사후 diff만으로 원본 변경을 안전하게 되돌릴 수 없다.
4. SQLite 상태 저장과 프로세스 간 전달, 단일 writer와 다중 CLI 쓰기가 혼동돼 있다.
5. 제품 사용량·강점에 대한 운영 가정이 검증된 제품 사실처럼 굳어져 있다.
6. 짧은 요약이라는 명분으로 요구·오류·증거가 유실되거나 비밀값이 로그에 남을 수 있다.

### 2.2 비목표

- 네트워크·디스크·제품 API 장애 자체를 0으로 만드는 것
- Antigravity 결과를 증거 없이 자동 신뢰하는 것
- backend=Codex, frontend=Antigravity 같은 영구 역할 고정
- SQLite를 네트워크 DB나 IPC 프로토콜로 쓰는 것
- 비Git 원본을 자동 커밋하거나 사용자 승인 없이 Git 저장소로 바꾸는 것
- MCP를 삭제하거나 모든 프로젝트에 강제하는 것
- 실측 전 비용·토큰 절감률을 주장하는 것
- 외부 효과가 `UNKNOWN`인 작업을 자동 재시도하는 것

## 3. 사실·운영 전제·미검증 구분

| 항목 | 분류 | v9 처리 |
|---|---|---|
| Codex Plus 사용량이 Antigravity보다 적다 | 사용자 운영 전제 | 라우팅 가설로 사용하되 계정·기간별 telemetry로 재측정한다. 보편적 제품 사실로 쓰지 않는다. |
| Codex가 Security & Skeleton에 더 강하다 | 미검증 비교 가설 | 진단·설계·검토의 기본 선호일 뿐, 고정 권한이 아니다. 동일 fixture 결과로 교정한다. |
| Antigravity가 병렬 조율·프로토타이핑에 더 강하다 | 공식 기능 + 미검증 상대우위 | Agent Manager/CLI 기능은 사실, Codex 대비 우위는 벤치마크 전 미검증이다. |
| `agy 1.2.4`, `codex-cli 0.154.0` | 2026-09-17 로컬 실측 | capability record에 명령·버전·시각·help hash를 저장한다. |
| `--add-dir`가 경로를 추가한다 | 로컬 help 사실 | 제한이 아니라 접근 확대일 수 있으므로 sandbox로 간주하지 않는다. |
| SQLite WAL은 writer 하나만 허용한다 | 공식 SQLite 사실 | broker 단일 writer와 짧은 transaction으로 구현한다. |
| Antigravity headless 권한 문제가 있다 | 버전별 GitHub 이슈 | 현재 1.2.4 canary 전까지 `UNKNOWN`; 이슈 상태와 재현 버전을 함께 기록한다. |
| 비용·토큰 절감 | 미측정 | `UNMEASURED`; acceptance·시간·재작업까지 포함한 A/B 뒤 판정한다. |

R25의 “토 달지 않기”는 증거 기반 비판·안전 의무와 충돌하므로 구현 규칙에서 제거한다. 사용자 목표와 우선순위는 보존하지만 수단·수치·제품 가정은 반증 가능하게 검증한다.

## 4. Authority Matrix

| 우선순위 | 권위 | 역할 | 쓰기 주체 | 충돌 처리 |
|---:|---|---|---|---|
| 1 | 플랫폼 정책·사용자 최신 지시 | 허용/금지, 목표, 승인 | 플랫폼/사용자 | 하위 자료를 즉시 무효화 |
| 2 | 가까운 `AGENTS.override.md`/`AGENTS.md` | 프로젝트 실행 규칙 | 승인된 변경 단계 | 상위와 충돌 시 상위 우선 |
| 3 | `docs/01_unified-agent-orchestration-design.md` | 프로젝트 운영 설계 정본 | 별도 설계 변경 단계 | v9는 구현 세부 파생 설계이며 docs/01을 자동 덮어쓰지 않음 |
| 4 | `.coord/PLAN.md`와 U카드 | 사람이 읽는 현재 계획·상태·인수 계약 | Codex 조율자/단계 소유자 | DB 상태와 다르면 자동 진행 중지 후 reconcile |
| 5 | SQLite event ledger/current projections | 런타임 시도·lease·delivery·budget·receipt | `coordd` 단일 writer | 상위 계획을 생성하지 않고 실행 상태만 투영 |
| 6 | 생성 manifest | 진단·scope·capability의 읽기용 파생물 | renderer | `GENERATED`, source hash, expiry 포함; 수동 편집 금지 |
| 7 | 모델 출력·GitHub 이슈·Reddit | 후보·경험 근거 | 없음 | 검증 없이 권위 상승 금지 |

`AGENTS-CONSENSUS.md`는 새 정본이 아니다. R18을 만족시키는 이름이 필요할 경우 `.coord/generated/AGENTS-CONSENSUS.md`로 생성하며, 헤더에 `DERIVED EXECUTION MANIFEST`, 생성 시각, source hashes, schema version, expiry를 넣는다. 내용은 프로젝트 진단·동적 lease·검증 명령을 보여 주며 docs/01이나 PLAN을 수정하지 않는다. source hash가 달라지면 stale로 표시하고 자동 실행을 막는다.

`PLAN.md`를 DB에서 일방적으로 render하지 않는다. 초기 구현에서는 PLAN/card가 계획 권위이고 DB는 동일 ID·revision을 가진 실행 projection이다. 양방향 수정이 탐지되면 `AUTHORITY_CONFLICT`로 fail-closed한다.

## 5. 운영 모드

| 모드 | 시작점 | 권위 계획 | 쓰기 조건 | 종료/수입 |
|---|---|---|---|---|
| `managed` | Codex 프로젝트 U카드 | docs/01 + PLAN/card | Codex가 발급한 유효 lease와 격리 workspace 필요 | Codex merge gate만 `DONE`/promotion 가능 |
| `standalone` | Antigravity IDE/2.0/CLI | 해당 workspace의 사용자 지시·로컬 규칙 | managed lease가 있는 원본에는 쓰지 않음 | 필요 시 결과 bundle을 `imported` 후보로 제출 |
| `imported` | 외부/standalone 결과 bundle | 원 계획은 읽기 전용 | 새 managed task/lease 발급 전 쓰기 금지 | provenance·scope·base hash·검사를 재검증 후 승격 |

Antigravity에서 Codex를 호출하는 `ask-codex`는 managed 작업이면 같은 task의 자식 질의다. standalone이면 읽기/자문만 허용하고 managed 상태를 바꾸지 않는다.

## 6. 구성요소와 데이터 흐름

```text
User / Codex coordinator
        |
        v
coordctl CLI ---- optional MCP adapter
        |         (same broker API, no state authority)
        +--------------+
                       v
             Windows Named Pipe
                       |
                       v
                coordd broker
         +-------------+-------------+
         |             |             |
         v             v             v
  SQLite ledger   worker launcher  renderer
  (local NTFS)    (Codex/agy)      (derived manifest)
                        |
                        v
              isolated worktree/staging
                        |
                        v
             verifier -> patch bundle
                        |
                        v
                 promotion gate
```

### 6.1 요청 흐름

1. Codex가 card revision, acceptance hash, dependency DAG를 확정한다.
2. `coordctl`이 schema-validated command를 Named Pipe로 보낸다.
3. broker가 idempotency key, budget, capability, resource conflict를 검사하고 같은 transaction에서 outbox와 event를 기록한다.
4. launcher가 delivery를 claim하고 lease/fencing token이 포함된 실행 envelope로 격리 workspace에서 worker를 시작한다.
5. worker 결과는 artifact bundle로 저장하고 DB에는 경로·size·SHA-256·schema validation만 기록한다.
6. verifier가 acceptance, scope, diff/manifest, security checks를 수행한다.
7. side-effect reconciliation과 최신 fence 확인 뒤에만 patch promotion 후보가 된다.
8. Codex가 증거를 검토해 card를 `REVIEW`에서 `DONE` 또는 재작업으로 전환한다.

## 7. SQLite/MCP 및 writer Decision Gate

### 7.1 writer 대안 비교

| 대안 | 구조 | 장점 | 치명 위험 | 판정 |
|---|---|---|---|---|
| A | 여러 CLI가 SQLite에 직접 연결, 짧은 `BEGIN IMMEDIATE` + fencing | daemon이 없어 단순, crash 복구 쉬움 | 모든 클라이언트에 schema/transaction 규율 복제, writer 경합, migration 시 조율 난도 | 보류: fallback prototype만 |
| B | 장수명 broker daemon + Windows Named Pipe + SQLite 단일 writer | 단일 writer가 실제로 보장됨, migration/budget/reconcile 중앙화, 클라이언트 단순 | broker lifecycle·Pipe ACL·재시작 설계 필요 | **GO: v9 core** |
| C | SQLite core + 선택 MCP transport | tool 발견성과 UI 통합 | MCP가 상태 권위나 별도 writer가 되면 split brain | transport 확장으로만 허용 |

최종 결정은 **B**다. C의 MCP는 B의 broker를 호출하는 선택적 transport adapter로만 허용한다. MCP adapter가 DB 파일을 직접 열거나 별도 상태를 저장하면 conformance 실패다. daemon을 구현할 수 없는 bootstrap 기간에는 A를 사용하지 않고 단일 foreground `coordctl run-once` 프로세스가 같은 broker core를 독점 실행한다.

SQLite는 상태 저장소이고 Named Pipe가 IPC다. DB는 동일 Windows host의 로컬 NTFS에 둔다. network share, OneDrive/Dropbox 등 sync 폴더, removable drive는 preflight에서 fail-closed한다. SQLite 공식 자료도 WAL에서 writer는 하나이며 network filesystem 사용에 주의를 요구한다.

### 7.2 기본 PRAGMA 후보

```text
journal_mode=WAL
synchronous=FULL
foreign_keys=ON
busy_timeout=1000
wal_autocheckpoint=<benchmark 결정>
```

긴 busy wait 대신 1초 이내 실패와 bounded jitter retry를 사용한다. transaction 안에서는 조건부 상태 전이와 event/outbox 기록만 수행하며 subprocess·hash·network·모델 호출은 금지한다. checkpoint는 유휴 시 `PASSIVE`부터 시작하고 장기 reader/WAL 크기를 계측한다.

## 8. 논리 스키마

물리 DDL은 구현 단계에서 migration test와 함께 확정한다. 아래 테이블/필드는 필수 불변식을 나타낸다.

| 테이블 | 핵심 필드 | 목적 |
|---|---|---|
| `schema_migrations` | version, checksum, applied_at, app_version | forward migration과 호환성 |
| `capabilities` | actor, cli_version, help_hash, features_json, probed_at, expires_at | 실제 제품 능력·버전 기록 |
| `plans` | task_id, card_revision, status, depends_json, acceptance_hash | PLAN/card projection |
| `attempts` | attempt_id, task_id, parent_task_id, call_depth, max_hops, state, idempotency_key | 시도·재귀 경계 |
| `resources` | resource_id, kind, canonical_value | path/port/db/cache/artifact/env/external 자원 |
| `leases` | lease_id, attempt_id, resource_id, owner, fencing_token, expires_at, state | 배타/공유 lease와 fencing |
| `deliveries` | delivery_id, direction, dedupe_key, payload_ref, state, available_at, claimed_by | durable inbox/outbox, at-least-once 전달 |
| `events` | event_id, aggregate_id, kind, payload_hash, created_at | append-only 감사 이력 |
| `artifacts` | artifact_id, attempt_id, relative_path, size, sha256, media_type | 큰 결과의 외부 파일 참조 |
| `checkpoints` | checkpoint_id, attempt_id, base_manifest_hash, artifact_set_hash, fence | 복구 기준점 |
| `receipts` | receipt_id, attempt_id, acceptance_hash, checks_ref, verdict, signer | 검증 증거 |
| `effects` | effect_id, attempt_id, kind, idempotency_key, provider_ref, state | 외부 부작용 reconciliation |
| `budgets` | scope_id, provider, turns, tokens, elapsed_ms, quota_state | 사용량/한도/비용 계측 |
| `circuits` | provider, failure_class, state, opened_at, retry_after | 회로 차단기 |
| `conversations` | task_id, tool, conversation_id, last_confirmed_turn | 단계별 대화 연속성 |

### 8.1 필수 불변식

1. 동일 resource에 충돌하는 `ACTIVE` lease는 하나뿐이다.
2. fencing token은 resource별 단조 증가하고 stale token의 checkpoint, receipt, effect, promotion은 거부한다.
3. command/result 전달은 at-least-once다. consumer는 `dedupe_key`와 idempotent handler로 중복을 무해화한다.
4. 외부 시스템이 idempotency/fencing을 제공하지 않으면 효과 상태는 성공 응답 증거 전까지 `UNKNOWN`이며 자동 재시도하지 않는다.
5. `events`는 append-only다. current table 갱신과 event/outbox 기록은 같은 transaction이다.
6. `SUCCEEDED`는 acceptance hash가 일치하는 PASS receipt가 있어야 한다. `DONE`은 Codex가 card evidence를 검토한 뒤에만 가능하다.
7. schema/app capability가 호환되지 않으면 worker dispatch를 하지 않는다.
8. artifact path는 workspace-relative이며 canonicalization 후 lease root 밖이면 거부한다.
9. secret-bearing prompt/output/env 원문은 DB·event·receipt에 저장하지 않는다.
10. delivery ack는 처리 결과와 event가 commit된 뒤에만 기록한다.

## 9. 상태 기계와 lifecycle

```text
BACKLOG -> READY -> PREFLIGHT -> LEASED -> RUNNING -> VERIFYING -> REVIEW -> DONE
                       |          |            |          |
                       v          v            v          v
                    REJECTED    SUSPECT     RETRY_WAIT   READY(rework)
                                  |
                                  v
                               ORPHANED
                                  |
                   +--------------+--------------+
                   v                             v
          SAFE_TO_RESUME                  NEEDS_RECONCILIATION
                   |                             |
                   v                             v
               RUNNING                    BLOCKED/USER GATE
```

### 9.1 Windows process lifecycle

- broker는 single-instance mutex와 Named Pipe endpoint를 가진다. Pipe ACL은 현재 사용자 SID만 허용하는 것을 기본 후보로 하고 실제 ACL 변경은 구현 단계의 승인 범위를 따른다.
- 시작 순서: path safety → DB/backup 존재 확인 → SQLite/runtime version → schema checksum → `quick_check` → incomplete migration → stale lease/effect scan → pipe listen.
- launcher는 Windows Job Object로 worker process tree를 묶는 방안을 1차 후보로 검증한다. PID만 신뢰하지 않고 PID+creation time+attempt nonce를 저장한다.
- graceful stop: 신규 claim 차단 → delivery flush → worker에 bounded cancel → final event → DB close.
- crash/reboot: `RUNNING`을 즉시 재실행하지 않고 `SUSPECT`; process identity와 lease expiry를 확인해 `ORPHANED`; effect reconciliation 뒤에만 fence를 올려 resume한다.
- timeout 뒤 같은 conversation으로 재개할 때도 마지막 turn이 어떤 tool/effect를 시작했는지 먼저 대조한다. `UNKNOWN` 효과가 하나라도 있으면 자동 resume/retry를 금지한다.

### 9.2 DB/디스크 장애

JSONL이 같은 디스크에서 무조건 더 안전하다고 가정하지 않는다.

| 장애 | 동작 |
|---|---|
| `SQLITE_BUSY` | 짧은 bounded jitter retry; 예산 소진 시 신규 dispatch 중단 |
| disk full / ACL denied / read-only | DB와 같은 volume의 JSONL도 실패할 수 있으므로 fail-closed; 메모리 성공을 durable 성공으로 표시하지 않음 |
| corruption | writer circuit open, 원본 보존, 검증된 backup을 새 경로에 restore, integrity/FK/schema 검사 후 수동/정책 gate |
| sync/network folder 탐지 | 시작 거부 |
| recovery journal 쓰기 실패 | 상태를 `UNRECORDED_FAILURE`로 취급하고 새 side effect 금지; 운영자에게 최소 stderr/event-log 알림 |

별도 recovery journal은 가능하면 다른 검증된 로컬 volume에 append+flush할 수 있지만 완전한 보장은 아니다. journal은 DB 대체 정본이 아니며 복구 입력 후보다. backup은 SQLite Online Backup API로 새 파일에 만들고 `integrity_check`, `foreign_key_check`, schema checksum을 통과한 것만 `verified_backup`으로 등록한다.

## 10. scope isolation과 patch promotion

### 10.1 동적 scope/resource lease

프로젝트 진단기는 구조·빌드·테스트·위험도를 읽고 작업별 최소 scope를 제안한다. 제품별 고정 lane은 없다.

```json
{
  "paths": [{"root":"src/api","mode":"rw"},{"root":"docs/spec.md","mode":"ro"}],
  "ports": [43121],
  "databases": ["tmp/U11/test.db"],
  "caches": ["tmp/U11/cache"],
  "build_artifacts": ["tmp/U11/dist"],
  "environment": [{"name":"APP_ENV","value_ref":"nonsecret:test"}],
  "external_effects": []
}
```

모든 경로는 realpath/canonical path로 비교하고 symlink/junction escape를 검사한다. 환경 변수는 allowlist로 새로 구성하며 credential을 “제거했으니 안전”하다고 주장하지 않는다. worker가 접근 가능한 파일·network·IPC·browser·credential broker 전체를 threat model에 포함한다.

### 10.2 Git 프로젝트

1. dirty state와 사용자 변경을 manifest로 보존한다.
2. 요청된 base에서 별도 worktree를 만든다. 생성·branch 정책은 단계 승인 범위와 사용자 지시를 따른다.
3. worker는 sandbox+lease scope 안에서만 작업한다.
4. base-to-result diff, changed-files report, generated artifacts, tests, secret scan을 대조한다.
5. merge gate가 PASS한 patch만 원 작업으로 승격한다. commit/push는 별도 권한이다.

### 10.3 비Git 프로젝트

1. 원본을 읽기 전용 source로 취급하고 file metadata+content hash manifest를 만든다.
2. 제외 규칙을 적용한 staging copy를 새 명시적 경로에 만든다. junction/symlink는 기본 거부한다.
3. worker는 staging만 수정한다. 원본 경로를 mount/add-dir 하지 않는다.
4. base copy와 result의 binary-aware patch bundle, deletes list, mode/metadata delta, artifact hashes를 생성한다.
5. 원본 manifest가 여전히 base와 일치하는지 확인한다. 바뀌었으면 `BASE_DIVERGED`로 중단한다.
6. scope·acceptance·보안 검사를 통과한 파일만 promotion 후보가 된다. 삭제·덮어쓰기는 사용자 승인 대상이면 gate에서 멈춘다.
7. 로컬 `git init/commit`은 보호 수단 후보일 뿐, 별도 승인 전 실행하지 않는다.

## 11. 오류·재시도·circuit·quota

| 분류 | 예 | 자동 행동 | 자동 재시도 |
|---|---|---|---|
| `TRANSIENT_TRANSPORT` | pipe/stdio 일시 단절 | delivery 재조회, checkpoint 확인 | jitter 포함 최대 2회 |
| `WORKER_CRASH` | 프로세스 종료 | lease expiry, reconcile, fence bump | 안전 증명 시 1회 |
| `TIMEOUT_PARTIAL` | exit 0+partial warning | 성공 거부, effects 확인 | 안전 증명 후 same conversation |
| `AUTH` | 로그인 만료 | provider circuit open | 없음 |
| `QUOTA` | 429/limit | 신규 dispatch 차단, reset time 기록 | reset 이후 half-open canary |
| `CAPABILITY` | flag/model/schema 없음 | 해당 route 비활성화 | 같은 요청 없음 |
| `VALIDATION` | 빈/깨진 envelope, hash mismatch | 실패 receipt | 수정 프롬프트 1회 |
| `SCOPE_CONFLICT` | path/port/DB 중복 | fail-closed | lease 재설계 전 없음 |
| `BASE_DIVERGED` | 원본 변경 | patch promotion 중단 | rebase/re-copy 결정 후 |
| `SIDE_EFFECT_UNKNOWN` | API write 응답 전 단절 | reconciliation 대기 | **없음** |
| `DB_UNAVAILABLE` | full/corrupt/ACL | writer circuit open, dispatch 중단 | 복구 검증 후 |
| `PERMANENT` | 잘못된 입력/지원 불가 | `FAILED_SAFE` | 없음 |

동일 root cause 3회면 circuit를 열고 `BLOCKED`로 반환한다. retry budget은 attempt 수뿐 아니라 elapsed time, model turns, token usage, tool calls를 함께 제한한다. quota 값이 없으면 `UNKNOWN`이며 충분하다고 간주하지 않는다. 라우팅 우선순위는 완료 가능성 → 정확도 → 안전 → 지연 → 사용량/비용이다.

## 12. 재귀 위임 방지

`ask-codex`와 반대 방향 위임 모두 envelope에 다음을 요구한다.

- `task_id`, `parent_task_id`, `root_task_id`
- `call_depth`, `max_hops`
- 호출자/피호출자와 `managed|standalone|imported`
- turn/token/elapsed/tool-call budget
- 요청 목적(`advice|review|execution`)과 허용 effect

기본 후보는 `max_hops=2`, 동일 tool 재진입 금지, `(root_task_id, caller, callee, intent_hash)` cycle detection이다. managed task에서 Antigravity가 `ask-codex(execution)`으로 Codex에게 작업을 되넘기고 Codex가 다시 Antigravity에 위임하는 고리는 차단한다. standalone 호출은 managed PLAN/card를 바꿀 수 없다.

## 13. security/threat model

### 13.1 자산과 경계

- 자산: 사용자 소스/문서, credential, 외부 계정, DB/event/receipt, patch bundle, 사용량.
- 신뢰 경계: 사용자↔Codex, coordctl↔Named Pipe, broker↔worker, worker↔filesystem/network/MCP/browser, staging↔원본 promotion.
- 공격/오류 주체: 악성 저장소 prompt, 모델 환각, stale worker, compromised plugin/MCP, path traversal, local same-user process, 공급자/CLI 버그.

### 13.2 필수 통제

1. prompt/repository text를 데이터로 취급하고 권한·계획 변경 명령으로 승격하지 않는다.
2. `--dangerously-skip-permissions` 기본 금지. 공식 sandbox와 최소 allow rules를 우선한다.
3. 로컬 1.2.4에서 `--sandbox`와 headless permission allow 동작을 canary로 확인하기 전 쓰기 자동화를 활성화하지 않는다.
4. sandbox 미지원/버그면 staging copy + OS ACL/프로세스 격리 + network deny로 축소하고, 그마저 증명 못하면 plan/read-only만 허용한다.
5. Named Pipe peer와 message size/schema를 검증하고 replay nonce/dedupe를 적용한다.
6. secrets는 자식 env allowlist, log redaction, artifact scan으로 방어한다. credential 부재 하나만으로 안전 판정하지 않는다.
7. push/deploy/payment/account/permission/credential/delete/overwrite는 최신 프로젝트 승인 규칙을 따른다.
8. stale fence의 DB commit뿐 아니라 원본 promotion과 외부 effect도 거부한다.

## 14. context/output budget

“Codex 7줄”은 표현 형식일 뿐 안전한 한도가 아니다. v9는 schema와 byte/token 예산으로 제한한다.

### 14.1 기본 envelope budget 후보

- JSON UTF-8 최대 16 KiB
- 추정 입력 최대 4,000 tokens; tokenizer가 없으면 byte 한도를 강제하고 token은 `UNKNOWN`
- `result` 2 KiB, `risks` 8개, `checks` 20개, `changed_files` 200개까지
- 초과 내용은 workspace artifact로 저장하고 path+size+SHA-256만 전달
- 전문 log/source/diff는 기본 전달 금지; 위험 구간과 검증 실패 주변만 별도 artifact reference

이 수치는 구현 초기 안전 후보이며 A/B에서 acceptance 저하가 있으면 조정한다. 항상 포함할 필드는 task/attempt/fence/schema/version/result/checks/risks/effects/usage/evidence refs이다.

### 14.2 redaction

- key 이름과 값 패턴을 함께 검사한다: token, api_key, secret, password, cookie, authorization, private key.
- command/path/error 문자열도 redaction 대상이다. URL query, home/user name, credential-bearing path, environment interpolation을 정규화한다.
- 원문은 저장 전에 redaction하고 redacted hash와 redaction count를 기록한다. 비밀값 자체의 hash도 fingerprint로 남기지 않는다.
- 구조화 실패나 size 초과를 임의 truncate해 성공 처리하지 않고 `OUTPUT_BUDGET_EXCEEDED`로 반환한다.

## 15. migration과 rollback

### 15.1 도입 순서

1. read-only capability/diagnostic probe와 v9 schema fixture
2. broker core를 foreground mock mode로 실행; 실제 worker 없음
3. SQLite migration/backup/recovery와 Named Pipe auth test
4. mock worker로 durable delivery, lease/fencing, retry/circuit test
5. 격리 staging에서 Antigravity read-only/fixture edit canary
6. Git worktree와 비Git patch promotion dry-run
7. 실제 저위험 프로젝트 opt-in
8. 전역 규칙 변경은 별도 사용자 승인 후

### 15.2 migration

- broker가 신규 claim을 막고 active lease를 drain한다.
- verified online backup을 새 경로에 만든다.
- app version/schema compatibility를 검사한다.
- checksum이 고정된 forward migration을 단일 transaction으로 적용한다.
- `quick_check`, `foreign_key_check`, invariant query, fixture replay를 통과해야 reopen한다.

### 15.3 rollback

schema down-migration을 안전하다고 가정하지 않는다. 실패하면 기존 DB를 덮어쓰지 않고 broker를 중지하고 verified backup을 새 경로에 복원한 뒤 이전 app version과 함께 reopen한다. 진행 중 effect는 먼저 reconcile한다. feature flag로 MCP adapter, actual worker, auto-promotion을 각각 끌 수 있어야 한다. 전역 규칙은 versioned backup/diff가 있고 별도 승인된 단계에서만 되돌린다.

## 16. 단계별 구현 계획 후보

아래는 다음 카드 제안이며 이 U09에서 생성하거나 실행하지 않는다.

| 후보 | 목표 | 핵심 산출물 | gate |
|---|---|---|---|
| U10 | capability·schema contract | versioned JSON schema, DDL/migrations, authority validator | schema/invariant tests |
| U11 | broker/IPC core | foreground broker, Named Pipe protocol, single writer | crash/replay/auth tests |
| U12 | durable execution | deliveries, lease/fence, budgets/circuits, worker launcher mock | at-least-once/idempotency tests |
| U13 | isolation/promotion | Git worktree adapter, nonGit staging, patch bundle/promotion dry-run | escape/divergence/delete gates |
| U14 | Antigravity/Codex adapters | sandboxed agy adapter, Codex review/ask adapter, recursion guard | local-version canaries |
| U15 | recovery/security | backup/restore, effect reconciliation, redaction, threat tests | fault/security suite |
| U16 | benchmark | mock fault matrix + real low-risk canaries + A/B | success thresholds below |
| U17 | opt-in rollout | derived manifest/renderer, pilot, runbook | user-approved global changes only |

기본 WIP=1이다. 병렬화는 DAG상 독립이고 path/port/DB/cache/build artifact/environment/external effect가 모두 격리됐으며 merge gate가 정의된 경우에만 허용한다.

## 17. 테스트 피라미드와 fault injection

### 17.1 피라미드

| 층 | 비중 후보 | 범위 |
|---|---:|---|
| unit/property | 60% | 상태 전이, canonical path, dedupe, fence, budget, redaction, schema |
| component | 25% | broker+SQLite, Named Pipe, migrations, backup, mock launcher |
| integration | 10% | worktree/staging, patch promotion, actual CLI envelope |
| E2E/canary | 5% | 저위험 fixture 프로젝트에서 managed/standalone/imported |

### 17.2 필수 fault matrix

| ID | 주입 | 통과 조건 |
|---|---|---|
| F01 | enqueue commit 전/후 broker kill | ack된 command 손실 0, 미ack는 중복 무해 |
| F02 | delivery 10회 재전달 | effect/attempt 1회 |
| F03 | lease 만료 후 stale worker 완료 | DB commit·promotion 모두 거부 |
| F04 | timeout 직전 외부 write | `NEEDS_RECONCILIATION`, 자동 retry 0 |
| F05 | exit 0 + 빈/partial envelope | false success 0 |
| F06 | headless permission soft-deny/hang | watchdog 종료, 원본 변경 0 |
| F07 | sandbox escape path/junction | dispatch 또는 promotion 거부 |
| F08 | 비Git 원본 동시 변경 | `BASE_DIVERGED`, 자동 overwrite 0 |
| F09 | 같은 path/port/DB/cache lease | 두 번째 claim 거부 |
| F10 | long reader/WAL growth | bounded latency, 경고, unsafe truncate 0 |
| F11 | DB busy convoy | bounded jitter 후 성공/명시 실패, 무한 대기 0 |
| F12 | disk full | durable success 0, 신규 effect 중단 |
| F13 | DB corruption | 원본 보존, verified backup만 복원 |
| F14 | backup corruption | restore 후보 제외 |
| F15 | ACL/pipe spoof | unauthorized request 거부 |
| F16 | schema/app mismatch | dispatch 0 |
| F17 | secret in command/path/error | 출력·DB·artifact index 노출 0 |
| F18 | recursive ask-codex cycle | max_hops/cycle에서 차단 |
| F19 | quota/auth/capability change | 정확한 circuit와 silent downgrade 0 |
| F20 | crash/reboot/PID reuse | creation time+nonce로 orphan 판정 |
| F21 | network/sync DB path | startup fail-closed |
| F22 | generated manifest stale | execution blocked until regenerate |
| F23 | merge gate test failure | promotion 0 |
| F24 | MCP adapter loss | DB 상태 보존, CLI 경로 영향 0 |

“100%” 표현은 각 시나리오의 공개된 반복 수에서 통과한 비율에만 쓴다. 예: F01~F24 각 100회 중 2,400/2,400 통과. 이는 모든 현실 장애에 대한 100% 보장이 아니다.

## 18. 측정 계획

### 18.1 A/B 설계

- 동일한 fixture, base hash, acceptance, model/version, reasoning effort, 시간대/쿼터 상태를 가능한 한 고정한다.
- A: Codex 단독. B: Codex 조율+Antigravity 실행+v9 broker.
- 조사, 코드 변경, 테스트/수정의 세 유형을 최소 10쌍씩 수행하고 순서를 교차한다.

### 18.2 기록 지표

| 지표 | 정의 |
|---|---|
| acceptance pass | 동일 검증 계약의 PASS 비율 |
| Codex turns | 사용자/도구 포함 Codex turn 수 |
| available usage delta | 실행 전후 계정 UI/API의 available usage 변화; 정밀 token과 동일시하지 않음 |
| Antigravity usage | envelope의 input/output/thinking/cache tokens, 없으면 `UNKNOWN` |
| wall time | dispatch부터 verified result까지 |
| rework | acceptance 실패 후 추가 attempt 수 |
| coordination overhead | broker/검토/인계 시간과 bytes/tokens |
| failures | false success, duplicate effect, scope violation, manual intervention |

비교 전 절감 상태는 `UNMEASURED`다. B는 acceptance가 A보다 2%p 넘게 낮아지거나 critical safety failure가 1건이라도 발생하면 비용이 낮아도 채택하지 않는다. 표본이 작으면 효과 크기와 신뢰구간을 함께 보고 결론을 “방향성”으로 제한한다.

## 19. R01~R26 추적표

| ID | v9 반영 | 구현 모듈 후보 | 검증 |
|---|---|---|---|
| R01 | U08 감사 결과를 입력으로 유지 | U17 diagnostics | inventory diff |
| R02 | 삭제는 별도 승인, 먼저 중복/충돌을 측정해 최소화 | U17 rollout | before/after rule load |
| R03 | 사용자 습관은 managed 자동진행·간결 보고로 반영 | U17 adapters | fresh-session test |
| R04 | Claude Code 실행 경로 제외; docs/11·12는 참고만 | 전체 | route inventory |
| R05 | Codex coordinator/verifier, Antigravity leased executor | U12/U14 | authority tests |
| R06 | evidence, redaction, scope, effect guard | U10~U15 | F03/F04/F17/F23 |
| R07 | 사용량 전제는 telemetry 기반 동적 router | U12/U16 | A/B usage delta |
| R08 | acceptance PASS 결과는 재작성 없이 promotion 후보 | U13 | receipt/promotion test |
| R09 | critic/redteam/self-refine는 위험기반 gate와 bounded retry | U12/U15 | retry/budget/security tests |
| R10 | docs/01+PLAN/card 단일 계획, DB는 projection | U10/U17 | authority conflict test |
| R11 | 단계별 conversation ID와 card 연결 | U12/U14 | conversation isolation |
| R12 | `[U##]` 제목 유지, 절감 수치는 별도 측정 | U14 | title/schema test |
| R13 | managed Antigravity는 Codex 프로젝트 lease 실행자 | U12/U14 | owner/fence tests |
| R14 | managed 자동 연결; standalone/imported 분리; ask-codex guard | U11/U14 | mode/cycle tests |
| R15 | SQLite durable state + Named Pipe IPC; 정의된 fault 범위만 100% | U11/U16 | F01~F24 |
| R16 | A/B/C redteam 후 broker 선택, fail-closed 복구 | 본 문서/U16 | decision/fault review |
| R17 | 제품 기능과 상대 강점 가설 분리, 동적 배정 | U16 | task-type benchmark |
| R18 | derived `AGENTS-CONSENSUS` execution manifest | U17 renderer | source-hash/stale test |
| R19 | 동적 path+runtime resource lease; 고정 backend/frontend 폐기 | U12/U13 | F07/F09 |
| R20 | 안전 범위 자동화; 승인 행동은 gate | U11~U17 | E2E + approval tests |
| R21 | 다지표 A/B, `UNMEASURED`에서 시작 | U16 | measurement audit |
| R22 | 테스트 피라미드와 F01~F24 | U15/U16 | published receipts |
| R23 | 2026-09-17 공식/로컬/GitHub 상태 확인 | 본 문서 | link/version record |
| R24 | 한 단계 한 창은 유지, 질문은 범위 변경/승인만 | docs/01 운영 | progression test |
| R25 | 반박 금지 제거, 사용자 목표 보존+수단 검증 | 본 문서 | authority review |
| R26 | A/B/C 비교 후 B core, optional MCP adapter | U11/U14 | adapter authority test |

## 20. 미검증 목록

1. Antigravity 1.2.4의 Windows `--sandbox` 실제 격리 범위와 headless `permissions.allow` 동작은 `UNKNOWN`이다.
2. Google 문서의 Windows AppContainer 설명과 로컬 배포가 정확히 일치하는지는 canary가 필요하다.
3. `agy` conversation resume가 timeout/partial tool call 뒤 effect metadata를 충분히 제공하는지는 `UNKNOWN`이다.
4. Codex/Antigravity 계정 사용량을 자동·정밀하게 읽을 안정 API는 확인하지 않았다.
5. Windows Named Pipe ACL, Job Object, service/foreground lifecycle의 구체 API와 최소 지원 OS는 구현 spike가 필요하다.
6. 비Git binary file patch, junction, ADS, file mode/ACL 보존 정책은 fixture 검증이 필요하다.
7. 별도 recovery volume이 실제 환경에 있는지, flush semantics가 신뢰 가능한지는 `UNKNOWN`이다.
8. provider 외부 effect가 idempotency key나 조회 API를 제공하는지는 도구별 capability로 확인해야 한다.
9. SQLite broker가 예상 동시성에서 A보다 나은지 성능 수치는 `UNMEASURED`다.
10. Codex=Security & Skeleton, Antigravity=Multi-agent Orchestration의 상대 성과 우위는 `UNMEASURED`다.
11. 비용·토큰 절감률과 최적 WIP/byte/token budget은 `UNMEASURED`다.

## 21. 근거

### 공식 1차 자료

- SQLite, [Write-Ahead Logging](https://www.sqlite.org/wal.html) — WAL 동시성과 단일 writer
- SQLite, [Transactions](https://www.sqlite.org/lang_transaction.html) — deferred/immediate/exclusive transaction
- SQLite, [SQLite Over a Network](https://www.sqlite.org/useovernet.html) — network filesystem 위험과 같은 host proxy 권고
- SQLite, [Online Backup API](https://www.sqlite.org/backup.html) — live DB snapshot/backup
- SQLite, [Atomic Commit](https://www.sqlite.org/atomiccommit.html) — crash/locking 전제
- Google Antigravity, [Headless mode](https://www.antigravity.google/docs/cli/headless/) — JSON/headless/permission/timeout 계약과 위험 flag 경고
- Google Antigravity, [Sandbox](https://www.antigravity.google/docs/cli/sandbox/) — OS 격리와 permissions 연동
- Google Antigravity, [Permissions](https://www.antigravity.google/docs/cli-permissions) — scoped allow/deny/ask 규칙
- Google Codelabs, [Getting Started with Antigravity](https://codelabs.developers.google.com/getting-started-google-antigravity) — Agent Manager/프로젝트 운용
- OpenAI, [Introducing the Codex app](https://openai.com/index/introducing-the-codex-app/) — 프로젝트/작업·worktree·검토
- OpenAI, [Symphony SPEC](https://github.com/openai/symphony/blob/main/SPEC.md) — 단일 권위 orchestrator, 격리 workspace, reconciliation
- OpenAI Agents SDK, [Multi-agent orchestration](https://openai.github.io/openai-agents-python/multi_agent/) — manager/handoff 패턴

### 버전이 명시된 GitHub 근거

- Antigravity [#1012](https://github.com/google-antigravity/antigravity-cli/issues/1012): 1.2.2 partial timeout+exit 0, 2026-09-17 기준 open. 로컬 1.2.4에 자동 일반화하지 않는다.
- Antigravity [#548](https://github.com/google-antigravity/antigravity-cli/issues/548): Windows headless permissions.allow 문제, open. 공식 최신 문서와 충돌 가능하므로 1.2.4 canary가 필요하다.
- Antigravity [#318](https://github.com/google-antigravity/antigravity-cli/issues/318), [#76](https://github.com/google-antigravity/antigravity-cli/issues/76): 과거 non-TTY hang/stdout 문제, 현재 closed. 회귀 fixture로만 쓴다.
- Antigravity [#947](https://github.com/google-antigravity/antigravity-cli/issues/947): 1.1.26 복잡 prompt 종료 hang, open. watchdog 근거지만 현재 버전 재현 전 사실로 단정하지 않는다.
- Hermes Agent [PR #3385](https://github.com/NousResearch/hermes-agent/pull/3385): 다중 SQLite writer convoy를 `BEGIN IMMEDIATE`, 짧은 timeout+jitter, passive checkpoint로 완화한 merged 사례. SQLite 공식 보장의 대체물은 아니다.

### 커뮤니티 보조 자료

- Reddit의 agent handoff, shared worktree, port/DB 충돌 사례는 운영 위험 발견에만 사용한다. 정책·제품 capability·성공률의 근거로 사용하지 않는다.

## 22. 최종 인수 기준

이 설계의 후속 구현은 다음을 모두 만족해야 pilot 후보가 된다.

- authority conflict, duplicate effect, false success, stale promotion, scope escape가 정의된 fault suite에서 0건
- DB direct writer가 broker 외부에 0개
- Git/nonGit 모두 원본 promotion 전 base/fence/receipt 검증
- `SIDE_EFFECT_UNKNOWN` 자동 재시도 0건
- sandbox/permission capability가 미검증이면 쓰기 dispatch 0건
- R01~R26에 구현 test 또는 명시적 운영 evidence가 연결됨
- 비용·토큰 절감은 A/B 전까지 `UNMEASURED`

R24는 docs/01과 조정한다. 단계별 전용 대화창과 단일 소유자는 유지하되, 사용자가 해야 할 일이 없으면 다음 `READY` 단계를 자동 진행한다. 목표·범위 변경과 삭제·덮어쓰기·push·배포·결제·계정/권한/자격증명 등 명시 승인 행동만 질문한다.

## 23. Claude 지시문 처리표

`docs/11`, `docs/12`의 지시를 권위로 승격하지 않고 항목별로 판정했다.

| 항목 | 판정 | v9 처리와 이유 |
|---|---|---|
| 사용자 목표·R01~R26 전수 추적 | 유지 | 요구 누락 방지에 유효하며 §19에 재작성 |
| SQLite를 런타임 상태 정본으로 사용 | 수정 | SQLite는 durable state ledger, 계획 정본은 docs/01+PLAN/card; IPC는 Named Pipe |
| 런처 하나가 DB writer | 수정 | 여러 CLI 실행 파일이라는 표현 대신 장수명 broker가 실제 단일 writer를 독점 |
| 7테이블 축약 스키마 | 기각 | lease/fence, durable delivery, effect, budget/circuit, migration, capability가 빠져 불변식 증명 불가 |
| MCP를 조회용으로만 유지 | 수정 | 조회 전용이라는 제품 역할이 아니라 동일 broker API의 선택 transport; DB direct access 금지 |
| `--add-dir`로 scope 강제 | 기각 | 로컬 help상 추가 workspace 접근이며 sandbox/권한 경계가 아님 |
| `--dangerously-skip-permissions` 기반 자동화 | 기각 | 공식 경고와 충돌; sandbox+scoped rules, 실패 시 staging fail-closed |
| 비Git에서 사후 diff와 향후 git commit | 수정 | 별도 staging copy+patch promotion이 기본; git init/commit은 별도 승인 선택지 |
| backend=Codex, frontend=Antigravity | 기각 | 제품 브랜드 기반 영구 할당 대신 진단 기반 동적 resource lease |
| 단계별 conversation ID 고정, `--continue` 금지 | 유지 | 대화 섞임 방지에 유효; 다만 timeout 후 effect reconciliation 선행 |
| timeout 뒤 같은 conversation 자동 재개 | 수정 | `UNKNOWN` external effect가 없고 checkpoint/fence가 검증된 경우만 재개 |
| DB busy 뒤 같은 disk JSONL 폴백 | 기각 | disk-full/corruption/ACL에서 같이 실패할 수 있어 durable 성공을 보장하지 못함 |
| JSONL로 DB 손상 기록 무손실 복구 | 수정 | 별도 검증 volume journal은 보조 입력일 뿐; fail-closed와 verified backup이 우선 |
| PLAN/AGENTS-CONSENSUS DB render | 수정 | PLAN/card가 계획 권위; consensus는 source hash가 있는 파생 execution manifest |
| Codex 7줄 입력 | 수정 | schema+16KiB/4k-token 후보+artifact refs+redaction으로 정의 |
| Antigravity 우선 결과주의 | 수정 | acceptance·risk·capability·quota 기반 라우팅이며 상대 강점/절감은 측정 전 가설 |
| 매 단계 사용자 질문 | 기각 | docs/01에 따라 자동 진행; 범위 변경과 명시 승인 행동만 질문 |
| “사용자 제안 반박 금지” | 기각 | 목표는 보존하되 잘못된 수단·수치·제품 가정은 증거로 비판해야 함 |
| 100% 자동 재개/연결 | 수정 | 공개된 fault injection 반복 범위의 통과율에만 100% 표현 허용 |
| A/B에서 소비자 사용량 % 중심 결론 | 수정 | acceptance, turns, usage delta, AG usage, wall time, rework, overhead, safety를 함께 측정 |
| 기본 WIP=1, 독립 scope 병렬 예외 | 유지·보강 | 파일 외 port/DB/cache/artifact/env/effect와 DAG/merge gate까지 요구 |

## 24. 품질 게이트 결과와 Decision Log

### 24.1 CRITIC

| 공격 질문 | 발견 | 수정 |
|---|---|---|
| DB가 새 계획 정본이 되어 docs/01과 충돌하는가? | v8의 render 설계는 충돌 가능 | Authority Matrix에서 DB를 execution projection으로 낮추고 PLAN 자동 덮어쓰기를 금지 |
| 단일 writer가 실제로 하나인가? | “런처 하나”는 여러 CLI process를 막지 못함 | broker+Named Pipe로 writer ownership을 물리적으로 중앙화 |
| 제품 강점이 역할을 영구 고정하는가? | 사용자 선호와 제품 사실이 혼합됨 | capability/fixture 기반 동적 assignment로 변경 |
| 자동 진행과 매 단계 질문이 충돌하는가? | R24와 현 AGENTS가 충돌 | docs/01 우선으로 자동 진행, 승인/범위 변경만 질문 |
| 비Git diff가 보호 경계인가? | 원본 훼손 뒤 탐지에 불과 | pre-execution staging과 promotion gate로 이동 |

### 24.2 REDTEAM

| 공격 | 깨질 수 있는 불변식 | 방어/잔여 상태 |
|---|---|---|
| broker crash | acked delivery loss | enqueue/event atomic commit, restart replay; F01로 검증 전 `UNKNOWN` |
| stale lease | 구 owner가 완료/promotion | resource fence 조건을 DB commit·promotion 모두에 요구 |
| duplicate delivery | 중복 worker/effect | at-least-once+dedupe+idempotent consumer; 외부 idempotency 없으면 effect gate |
| unknown external effect | timeout 후 이중 write | `NEEDS_RECONCILIATION`, 자동 retry/resume 금지 |
| DB busy/corruption/disk full | 상태 손실/거짓 성공 | short retry, circuit open, verified backup, durable commit 없으면 성공 금지 |
| headless permission hang | 무한 worker/과권한 우회 | watchdog+Job Object 후보, dangerous flag 금지, staging fail-closed |
| recursive ask-codex | 무한 토큰/호출 | parent/depth/max_hops/cycle/budget/managed boundary |
| scope escape | 원본·비밀 접근 | canonical path, junction/symlink test, sandbox+ACL+staging |
| 병렬 port/DB/cache 충돌 | 상호 오염 | typed resource lease+DAG+merge gate; 증명 안 되면 WIP=1 |
| quota exhaustion | 반복 위임 폭주 | quota `UNKNOWN` 보수 처리, circuit, reset 후 half-open canary |

### 24.3 SELFREFINE 변경 기록

1. DB를 “런타임 정본”이라고만 표현해 생긴 권위 모호성을 `durable execution ledger/current projection`으로 좁혔다.
2. B와 C가 겹치던 선택지를 분리했다. writer topology는 B를 선택하고 MCP는 독립 adapter feature로 격하했다.
3. crash recovery에 conversation resume만 있던 모순을 effect reconciliation 선행 규칙으로 바꿨다.
4. JSONL 폴백의 무손실 주장을 제거하고 DB와 같은 failure domain이면 fail-closed하도록 했다.
5. product role lane을 dynamic lease로 바꾸고 P2/P6를 측정 가능한 가설로 낮췄다.
6. 7줄 제한을 삭제하고 byte/token/schema/redaction 계약으로 교체했다.

### 24.4 최종 Go/Pivot/No-Go

| 결정 | 대상 | 이유 |
|---|---|---|
| `GO` | v9 설계와 U10~U17 후보 순서 | 필수 요구·안전 경계·검증 계획이 연결됨. 구현 승인은 아님 |
| `GO WITH GATE` | broker single-writer + SQLite local ledger | mock/migration/fault test부터 시작하고 실제 worker는 뒤에서 opt-in |
| `PIVOT` | MCP 중심 연결 | 선택적 broker adapter로만 유지; 상태·writer 권위 없음 |
| `PIVOT` | 제품별 영구 업무 분리 | 진단·capability·resource lease 기반 동적 배정 |
| `PIVOT` | “100% 연결” | 명시된 장애주입 반복 범위의 100% 통과만 보고 |
| `NO-GO` | `--dangerously-skip-permissions` 기본 자동화 | 공식 경고, open headless 이슈, blast radius 확대 |
| `NO-GO` | 비Git 원본 직접 Antigravity 실행+사후 diff 보호 | 사후 탐지는 rollback/소유권 보호가 아님 |
| `NO-GO` | 같은 disk JSONL을 무조건 성공 fallback으로 취급 | 동일 disk/ACL/corruption failure domain |
| `NO-GO` | `UNKNOWN` 외부 효과 자동 retry | 중복 부작용 가능 |
| `NO-GO` | 7테이블 축약, 7줄 고정, R25 반박 금지 | 핵심 불변식·증거·안전 비판을 약화 |

구성요소 최소화 결론은 `coordctl + coordd + SQLite + worker adapters + verifier/promotion`이다. MCP, renderer, telemetry UI는 core가 아니며 필요한 경우에만 추가한다. 상태는 SQLite 한 곳에 두고 PLAN/card는 상위 계획 권위, 생성 manifest는 읽기용 파생물로 역할을 분리한다.
