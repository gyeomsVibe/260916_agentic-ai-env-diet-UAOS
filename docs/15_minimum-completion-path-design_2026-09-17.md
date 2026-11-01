# 최소 완성 경로 고효율 구현 설계 v10

- 작성일: 2026-09-17
- 작성: Claude (사용자 지시 "최소 완성 경로로 바꿔 고효율 최적화 구현 설계")
- 상태: `PROPOSAL` — Codex 조율자 확인 후 PLAN에 반영
- 대체 대상: `docs/13` §16의 U15~U17 순서(U15 recovery/security → U16 benchmark → U17 rollout)
- 유지: 사용자 제안 전제(R01~R26), `docs/01` 운영 원칙, U10~U13 산출물

---

## 0. 한 줄 결론

**"완벽한 부품"을 더 만들지 않는다.** 이미 만든 U10~U14 부품을 한 줄로 연결해 **실제 작업 1건을 Codex 조율 → Antigravity 실행 → 검증 → 반영까지 끝까지 돌리고**, 같은 작업의 Codex 단독 사용량과 비교한 뒤 전역 규칙에 반영한다. 남은 강화 항목은 파일럿이 돈 뒤 백로그에서 처리한다.

---

## 1. 왜 바꾸나 (실측 근거)

| 관찰 | 수치 |
|---|---|
| 소요 | U09~U14 여섯 단계에 약 16시간(2026-09-17 01시~17시) |
| 재작업 | 단계당 독립 검증 2~3회, U11·U12·U13·U14 모두 1회 이상 REWORK |
| 실제 위임 | **0건.** 부품·안전장치만 존재 |
| Codex | 06:49 UTC 사용량 한도 도달로 조율 중단 |
| 절감 효과 | 여전히 `UNMEASURED` (R21 미충족) |

원인: 검증이 깊어질수록 새 P2·P3가 계속 발견되는데, "P1 없음"과 "모든 결함 없음"을 구분하는 종료 규칙이 없었다.

---

## 2. 완료 정의 (Definition of Done)

아래 4가지를 모두 만족하면 이 프로젝트의 1차 목표를 완료로 본다.

| # | 완료 조건 | 사용자 요구 |
|---|---|---|
| D1 | Codex 한 번의 명령으로 실제 작업 1건이 SQLite 원장 기록 → staging 복사 → **실제 `agy` 실행** → 봉투·범위·외부쓰기 검증 → patch bundle → **승인 후 원본 반영**까지 끝난다 | R05·R07·R08·R10·R13·R15·R20 |
| D2 | Codex는 전문을 읽지 않고 7줄 요약 JSON만 받아 DONE/재작업을 판정한다 | R06·R07·R09 |
| D3 | 같은 작업을 Codex 단독으로 수행한 A와 비교해 Codex 사용량·시간·품질이 기록된다 | R21 |
| D4 | Codex·Antigravity 전역 규칙과 프로젝트 `AGENTS.md`에 사용법이 반영돼, 새 Codex 세션이 자동으로 이 경로를 쓴다 | R01~R03·R14·R20 |

---

## 3. 과잉 검증 방지 종료 규칙 (가장 중요)

1. **P1만 차단한다.** P1은 "정상 경로에서 거짓 성공·범위 밖 쓰기·권한 우회·데이터 손실이 실제로 재현되는 결함"으로 한정한다.
2. **P2·P3는 자동 백로그.** 발견 즉시 `.coord/BACKLOG.md`에 한 줄 기록하고 현재 단계를 막지 않는다.
3. **단계당 독립 검증은 최대 2회.** 1차 REWORK 뒤 2차 검증에서 **1차 목록의 P1이 해결됐는지만** 확인한다. 2차에서 새로 나온 항목은 P1 정의에 해당할 때만 차단하고, 그 외는 백로그로 보낸다.
4. **검증 시간 상한.** 독립 검증 1회는 Antigravity 호출 1회(10분)로 끝낸다.
5. **재작업 범위 고정.** 재작업은 검증 결과에 적힌 항목만 고치고 새 기능을 넣지 않는다.

---

## 4. 재사용 자산과 연결 지도

| 부품 | 모듈 | 파일럿에서의 역할 | 상태 |
|---|---|---|---|
| 계약·스키마 | `v7_harness/contracts/**` (U10) | 명령·봉투·결과 스키마 | DONE |
| 단일 writer 원장 | `broker/core.py` `BrokerCore` (U11) | SQLite 소유, enqueue/delivery | DONE — **Named Pipe는 파일럿에서 미사용** |
| 실행 수명주기 | `execution/engine.py` `DurableExecutionEngine`, `lease.py`, `circuit.py` (U12) | claim→worker(트랜잭션 밖)→commit, fence, 재시도 한도 | DONE |
| 프로세스 격리 | `execution/launcher.py` Job Object·타임아웃 (U12) | 실제 agy 프로세스 트리 종료 | DONE — **mock 전용, 실제 실행기 필요** |
| staging·검증 | `isolation/staging.py`, `security.py`, `manifest.py`, `promotion.py` (U13) | 복사, 외부 쓰기 감시, patch bundle, dry-run | DONE — **`apply_promotion`은 금지 stub** |
| 어댑터 | `adapters/**` (U14) | agy·codex 명령 조립, 결과 판정, 재귀 방지 | REWORK (P1) |

**설계 결정:** v9 §7이 허용한 bootstrap 방식인 **foreground `run-once` 단일 프로세스**로 파일럿을 돌린다. 한 프로세스가 `BrokerCore`를 소유하고 끝나면 종료한다. Named Pipe 상주 broker와 MCP 어댑터는 파일럿 통과 뒤로 미룬다. 단일 writer 원칙은 프로세스 잠금(U11 `_ExclusiveFileLock`)으로 그대로 지켜진다.

---

## 5. 단계 설계 (U14 → M1~M3)

### M1 = U14 P1 재작업 (목표 30~40분)

고칠 것 — Antigravity V1·V2가 공통 재현한 P1과 Claude 병행 탐침 결과만:

| # | 결함 | 수정 |
|---|---|---|
| 1 | caller/callee/mode/intent/purpose 대소문자 우회 | `casefold()` 후 허용 enum 검사, 미등록 값은 `AdapterPolicyError` |
| 2 | session_id·conversation_id·model 인자 주입 | 정규식 `^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`, 선행 `-` 거부 |
| 3 | task_id·title 제어 문자로 `[U##]` 위조 | `\x00-\x1f\x7f` 전부 거부 (agy·codex 공통) |
| 4 | `timed out` 문구 미탐지 | 정규식 `time[d]?\s*out` + `partial` (casefold) |
| 5 | 대화 ID 교차 연결 | 역방향 `conversation_id → (task, tool)` 유일성 |
| 6 | usage NaN/Infinity/bool/음수 | 유한 음이 아닌 정수만, 아니면 `VALIDATION` |

- 각 항목마다 회귀 테스트 1개 이상 추가
- 백로그로 보낼 것: `--flag=value` 도움말 파싱, 형제 호출 오인 차단, depth 0 메시지, `/login` 과분류
- A1(staging 라벨 위조)은 M2 배선에서 해결한다(아래 M2-3)
- 게이트: `test_u14_adapters` + `test_u1[0-4]*.py` + compileall exit 0, Antigravity V2는 위 6개 해결 여부만 확인

### M2 = 실전 파일럿 (U15+U16 통합, 목표 1~2시간)

**M2-1. 실제 실행기 `AgyProcessLauncher`** (`v7_harness/execution/agy_launcher.py`)
- U12 `MockSubprocessLauncher`와 같은 `launch()` 인터페이스로 실제 `agy` 실행
- Job Object 편입, `print_timeout + 60초` 런처 타임아웃, 초과 시 프로세스 트리 종료
- stdout·stderr를 `.coord/runs/<task>/<attempt>.{json,err}`에 저장하고 U14 `parse_agy_result`로 판정
- `conversation_id`를 `ConversationRegistry` + SQLite에 저장, 같은 단계 재시도는 같은 대화로

**M2-2. 파이프라인 명령 `pilot`** (`python -m v7_harness.cli pilot run --task P01 --source <dir> --prompt-file <md>`)

```text
1. run-once 잠금 획득(BrokerCore) → enqueue(idempotency_key)
2. NonGitStagingAdapter.create_staging(source → .coord/stage/P01-a001)
3. snapshot_watch_roots([HOME, TEMP])
4. engine.execute(): lease·fence 발급 → AgyProcessLauncher(staging) → 결과 commit
5. watch.assert_unchanged()  (외부 쓰기면 UNKNOWN, 반영 금지)
6. workspace.create_patch_bundle() → dry_run_promotion()
7. .coord/runs/P01/summary.json (7줄 요약) 출력 후 종료
```

**M2-3. A1 해결 — staging 판정을 문자열에서 객체로**
- `build_agy_command`에 넘기는 `isolation_mode`를 `StagingWorkspace` 인스턴스에서만 파생
- 파이프라인 밖에서 `skip_permissions=True`를 직접 쓰는 경로는 제공하지 않는다

**M2-4. 실제 반영 `apply_promotion`**
- 현재 금지 stub을 실제 구현으로 교체한다. 조건: dry-run 결과가 충돌 0·범위 위반 0·삭제 없음이고, **`--approve <bundle_id>`를 명시**해야 한다
- 반영 전 원본 base manifest를 다시 계산해 dry-run 시점과 같아야 한다(동시 수정 방지)
- 삭제·이름변경 포함 bundle은 파일럿에서 거부한다(백로그)

**M2-5. 파일럿 과제와 A/B**
- 과제 P01: 이 저장소 밖 **전용 샘플 프로젝트** `D:\D_Workspace_NB\-agentic-ai-workspace\260916_pilot_sample\`(소형 Python 모듈 + 테스트)에서 "함수 1개 추가 + 테스트 통과". 원본 손상 위험이 없고 인수 기준이 명확하다
- A: Codex 단독으로 같은 과제 수행
- B: Codex가 `pilot run` 1회 호출 + 요약 판정
- 기록(`.coord/runs/P01/ab.json`):
  - Codex: 5시간 창 사용률 전후, `codex exec --json` usage 합계, 턴 수
  - Antigravity: 봉투 `usage`
  - 벽시계 시간, 인수 테스트 exit, 재작업 횟수, 사람 개입 횟수
- 게이트: B가 인수 테스트 통과 + 거짓 성공 0 + 범위 밖 쓰기 0. 절감률은 수치 그대로 보고(목표치 강요 없음)

### M3 = 적용 (U17, 목표 30분, 사용자 승인 필요)

| 파일 | 추가 내용 (각 5줄 이내) |
|---|---|
| 프로젝트 `AGENTS.md` | 구현성 작업은 `pilot run`으로 Antigravity에 위임, Codex는 `summary.json`만 판정, 반영은 `--approve` |
| `~/.codex/AGENTS.md` | "`v7_harness`가 있는 프로젝트는 위 경로 우선, `antigravity-bridge`는 조회용" (C1 해소) |
| `~/.gemini/GEMINI.md` | managed 호출 시 staging 안에서만 작업, 결과는 JSON 스키마로 |
| `mia-vaccine-test` | vibe-clinic MCP 없으면 로컬 진단으로 전환 (C2 해소) |

- 게이트: 새 Codex 세션에서 "P02 과제 해줘" 한 줄로 `pilot run`이 자동 선택되는지 확인

---

## 6. 사용자 요구 추적 (R01~R26)

| 상태 | 요구 |
|---|---|
| 이미 충족 | R04(Claude 제외), R12(`[U##]`), R16·R23(조사·레드팀), R26(SQLite vs MCP 비교) |
| M1에서 충족 | R11(대화 고정), R14(재귀 방지·역호출 가드) |
| M2에서 충족 | R05·R07·R08·R10·R13·R15(실제 위임·결과주의·SQLite 연결), R06·R09(요약 판정·검증), R20(한 명령 자동화), R21(A/B), R22(실제 장애 1건 이상 관측 시 기록) |
| M3에서 충족 | R01~R03(전역 규칙 재작성), R17·R18·R19(역할·`AGENTS-CONSENSUS` 생성·디렉터리 권한은 M3 `AGENTS.md` 템플릿에 포함), R24(단계별 확인) |
| 사용자 지시 유지 | R25(전제 유지) |

---

## 7. 백로그 (파일럿 통과 후, 트리거 기반)

| 항목 | 출처 | 트리거 |
|---|---|---|
| 잠긴 파일 내용 교체 탐지(ChangeTime/USN) | U13 R1, 메모 06 | 파일럿에서 LOCKED 파일 관련 판정 불명 발생 시 |
| 예산 초과 파일 단위 증거 | U13 R2 | 실제 프로젝트 스냅샷이 예산 초과로 실패 시 |
| 재파싱 TOCTOU·OS ACL | U13 R3 | 다중 사용자·원격 실행 도입 시 |
| U14 P2·P3 4건 | Antigravity V1 | 해당 기능 사용 시 |
| Named Pipe 상주 broker·MCP 어댑터 | v9 §7 | 동시 위임 2건 이상 필요 시 |
| 백업·복구·장애 주입 매트릭스 F01~F24 | v9 §17 | 파일럿 3건 이상 누적 후 |
| 삭제·이름변경 반영 | M2-4 | 실제 과제에서 필요 시 |
| 병렬 lane(backend/frontend 동시) | R19 | 단일 경로 3건 안정 후 |

---

## 8. 예산·일정

| 단계 | 벽시계 | Codex 사용 | Antigravity 사용 | 사용자 승인 |
|---|---|---|---|---|
| M1 | 30~40분 | 판정 1회 | 초안 1회 + 검증 1회 | 없음 |
| M2 | 1~2시간 | A 과제 1회 + 판정 2회 | 구현 초안 1회 + 파일럿 B 1회 + 검증 1회 | 샘플 프로젝트 생성, 첫 `--approve` |
| M3 | 30분 | 판정 1회 + 신규 세션 확인 1회 | 없음 | 전역 규칙 파일 수정 |
| 합계 | **약 2.5~3.5시간** | 판정 위주 약 6회 | 약 6회 | 3회 |

---

## 9. 중단 기준

- M2 파일럿에서 거짓 성공 또는 범위 밖 쓰기 1건 → 즉시 중단하고 해당 부품만 P1 재작업
- 같은 원인으로 2회 실패 → `BLOCKED`, 사용자에게 선택지 보고
- Codex 사용량 한도 → Antigravity가 실행·독립 검증을 계속하고 카드에 재개 지점을 기록한다. DONE은 Codex 복귀 후 판정하거나, 사용자가 명시 승인한 경우에만 Antigravity 독립 검증 PASS로 확정한다.

## 10. 참여 도구 고정 (2026-09-17 사용자 지시)

- 이 계획의 참여 도구는 **Codex(조율자·두뇌·최종 판정)와 Antigravity(실행자·독립 검증자) 두 개뿐**이다.
- Claude Code는 이 계획의 역할·라우팅·게이트에 포함되지 않는다. U13·M1 등에서 사용자 지시로 한시 대행한 기록은 역사 기록으로만 보존하며, 이후 단계의 실행·검증·판정 경로로 사용하지 않는다.
- Claude Code는 사용자가 따로 호출하는 **독립 외부 도구**로만 쓰인다. 그 산출물은 참고 입력이며 Codex 판정을 대신하지 않는다.
