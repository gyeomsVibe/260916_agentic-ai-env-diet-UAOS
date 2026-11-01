# 260916 agentic-ai-env-diet 전수 분석 보고서 v8

- 작성일: 2026-09-17
- 범위: `docs/00`~`docs/10`, `.coord/`, `AGENTS.md`, `proposals/`, `v7_harness/`, `tests/`, Codex·Antigravity 전역 설정, `antigravity-bridge` 구현, `agy`·`codex` CLI 실측, 공식 문서·GitHub·Reddit 조사
- 원칙: 사용자 제안은 **확정 전제**다. 이 보고서는 제안을 빠짐없이 구현하기 위한 보강만 다룬다.
- 후속 산출물: [`12_codex-implementation-directive_2026-09-17.md`](12_codex-implementation-directive_2026-09-17.md) — Codex 구현 설계 지시문

---

## 1. 결론

1. 사용자 제안은 **26개 요구(R01~R26)**로 분해된다(§3). 현재 문서·구현이 완전히 충족한 요구는 6개, 부분 충족은 12개, 미착수는 8개다(§4).
2. 가장 큰 공백은 세 가지다.
   - **연결:** Codex↔Antigravity 연결이 아직 MCP 브리지(화면 텍스트 복원 방식)다. SQLite 연결(R15)은 설계만 있고 구현이 없다.
   - **권한:** 디렉터리 기준 권한(R19)과 `AGENTS-CONSENSUS.md`(R18)가 U08에서 채택되지 않았다. v8에서 복원한다.
   - **자동화:** 자동 연결(R14), `[U##]` 대화창 자동 생성·고정(R11~R13), 효율 검증(R21)이 구현되지 않았다.
3. 해법은 **v7 하네스를 확장한 SQLite 런처**다. 새 허브를 만들지 않는다. Codex와 Antigravity는 DB를 직접 쓰지 않고 런처 명령만 호출한다. DB가 계획 실행·대화창·권한·사용량·증거의 런타임 정본이 된다.
4. 실측으로 `agy -p --output-format json`은 비TTY에서 동작한다. 결과로 `status`, `conversation_id`, 토큰 `usage`를 돌려주므로 SQLite 연결의 기술 기반이 확인됐다.

---

## 2. 확정 전제 (사용자 제안 — 재검토하지 않음)

| # | 전제 |
|---|---|
| P1 | 사용자는 Codex·Antigravity·Claude Code를 구독 중이다. 이 로직은 Codex·Antigravity 2도구로 운영하고 Claude Code는 계획에서 제외한다. |
| P2 | Codex Plus 사용량은 Antigravity보다 적고, Antigravity 사용량은 풍부하다. |
| P3 | Codex = 조율자·지휘자·두뇌. Antigravity = Codex의 도우미·일꾼·하위 에이전트. Codex가 사용자 지시 없이 자율적으로 부린다. |
| P4 | 성과·결과가 최우선이다. Antigravity 결과가 만족되면 Antigravity가 Codex를 대신한다. |
| P5 | 두 도구는 사용자에게서 무승인 권한을 받았다. |
| P6 | Codex는 설계 구조·예외 진단(Security & Skeleton)에 강하고, Antigravity는 병렬 서브에이전트·동적 라우팅·프로토타이핑(Multi-agent Orchestration)에 강하다. |
| P7 | 연결은 MCP가 아니라 로컬 SQLite DB로 한다. |

실측 보조 사실: 2026-09-16 Codex Plus 5시간 창 사용량 77%→92%, 주간 47%→49%(docs/04, 05). P2와 일치한다.

---

## 3. 사용자 제안 요구 분해 (R01~R26)

원문: `docs/# (사용자 제안사항) 260916_agentic-ai-env-diet.md` 및 이 대화창의 추가 지시.

### 블록 1 — 전역 환경 다이어트와 역할
| ID | 요구 |
|---|---|
| R01 | 두 도구(Antigravity, Codex)의 전역 룰·skills·메모리·바이브 자가진단·MCP를 읽고 충돌 지점을 찾는다. |
| R02 | 불필요하거나 무겁고 과한 지침을 삭제·최적화해 가볍게 만든다. |
| R03 | 사용자의 AI 사용 습관에 맞춰 두 도구의 규칙·전역 룰·skills를 재작성한다. |
| R04 | Claude Code는 계획에서 제외한다. |
| R05 | Codex는 조율자·지휘자·두뇌, Antigravity는 도우미·일꾼인 하위 에이전트다. Codex가 사용자 지시 없이 필요할 때 자율적으로 부린다. |
| R06 | 환각·토큰 낭비 방지 Safety Guard를 둔다. |
| R07 | Codex의 제한된 사용량을 살리고 풍부한 Antigravity 사용량을 써서, Codex 한도에 발목 잡히지 않고 프로젝트를 완수하는 최대 효율 로직을 설계한다. |
| R08 | 성과·결과 최우선. Antigravity가 대신 수행해 결과가 만족되면 Antigravity를 Codex 대신 쓰는 결과주의 로직이다. |
| R09 | /CRITIC /REDTEAM /SELFREFINE 기반 **예산절약 극대화 성과·결과주의** 로직을 설계에 포함한다(최우선 목적). |

### 블록 2 — 단일 계획과 대화창
| ID | 요구 |
|---|---|
| R10 | Codex와 Antigravity가 따로 작업하지 않고 하나의 계획으로 한몸처럼 수행한다. GitHub·Reddit 딥리서치로 설계를 정제한다. 두 도구는 무승인 권한을 가진다. |
| R11 | 사용자 지시창이 아니라 각 프로젝트 창에서, 수행 작업마다 대화창 하나를 만들어 계획 순서대로 작업한다. |
| R12 | 각 대화창에 짧은 통일 접두어를 붙여 토큰을 절약한다. |
| R13 | Codex 조율로 Antigravity가 수행하는 작업은 "Codex 프로젝트 안의 단계별 전용 대화창"으로 취급한다. 실제 수행은 단계별 전용 대화창에서 계획 순서대로 단일 소유자가 한다. Codex로 시작하면 Antigravity는 Codex의 일부이자 도구다. |
| R14 | Codex로 시작하면 Codex와 Antigravity가 자동 연결된다. Antigravity 2.0이나 IDE를 쓰면 Antigravity 단독 사용이고, 필요하면 Antigravity에서 Codex를 호출할 수 있다. |

### 블록 3 — SQLite 연결
| ID | 요구 |
|---|---|
| R15 | Antigravity 연결을 MCP 대신 로컬 SQLite DB로 만들고, 연결 실패 없이 100% 유연하게 연결되도록 보완·개선 로직을 조사·설계한다. |
| R16 | /CRITIC /STEPBYSTEP /REDTEAM으로 그 로직의 맹점·오류·구현 난제를 GitHub·Reddit 딥리서치로 찾고, /DEEPDIVE /ALT3 /OPTIMIZE로 수정·개선한다. |

### 블록 4 — 역할 검증과 공유 명세
| ID | 요구 |
|---|---|
| R17 | "Codex = Security & Skeleton, Antigravity = Multi-agent Orchestration" 강점을 검증해 역할을 정의한다. |
| R18 | Codex로 시작하면 Codex가 프로젝트를 면밀히 진단하고, 먼저 두 도구를 동시 병렬로 쓸 때의 분업·협업·권한·작업 중복 방지를 조율하는 `shared-specs.md` 또는 `AGENTS-CONSENSUS.md`를 작성한다. |
| R19 | 작업 중복을 원천 차단하기 위해 디렉터리 기준 권한(Scoped Permission)을 엄격히 분리한다. 예: `backend/` Codex 전담, `frontend/` Antigravity 전담, 루트에 공유 명세서. |

### 블록 5 — 자동화와 검증
| ID | 요구 |
|---|---|
| R20 | 전면 자동화한다. |
| R21 | 예상 효율 향상을 검증한다. |
| R22 | 극한 테스트를 견디는 로컬 벤치마크 실행 계획을 세운다. |
| R23 | 사용자 요구를 2026-09-16 기준 최신 자료(GitHub·Reddit)로 다시 점검해 로직 설계안을 최적화·보강한다. |

### 블록 6 — 진행 방식과 이 대화창의 추가 지시
| ID | 요구 |
|---|---|
| R24 | 한 번에 모두 실행하지 않고, 역질문으로 한 대화창에 한 단계씩 진행한다. |
| R25 | 사용자 제안(사용량 판단 포함)에 토를 달지 않고 보강·개선만 한다. |
| R26 | SQLite 방식과 MCP 방식을 비교 분석하고 판단을 보고서에 포함한다. |

---

## 4. 요구별 현재 충족 상태 (전수 추적)

| ID | 상태 | 근거 | 남은 일 |
|---|---|---|---|
| R01 | 충족 | docs/04·05 P0 충돌(force-push, auto-merge, Antigravity 과권한), skills 중복, memory 오염, MCP 중복 | v8 역할 반영 후 재감사 |
| R02 | 충족 | docs/06: 전역 룰 50→29줄, 래퍼 skills 10종·워크플로 6개·MCP 4종·Ollama 제거, 자동 memory 끔 | 남은 충돌 2건(§6.3) 정리 |
| R03 | 부분 | 29줄 전역 룰은 있으나 v8 역할(자동 연결·SQLite·디렉터리 권한)이 없음 | Codex·Antigravity 전역 룰·skills 재작성 |
| R04 | 충족 | docs/05·06에서 Claude 라우팅 제거 | 유지 |
| R05 | 부분 | Codex 전역 룰 "Codex 역할" 절, docs/01 | 자율 위임 트리거를 런처 명령으로 구체화 |
| R06 | 부분 | proof receipt·증거 없는 DONE 금지 | 봉투 6중 판정·범위 diff·토큰 가드 구현(§7) |
| R07 | 부분 | docs/05 사용량별 라우팅 | Antigravity 우선 실행 라우터 구현 |
| R08 | 부분 | docs/05 "PASS면 DONE" | 인수 기준 충족 시 자동 채택 로직 구현 |
| R09 | 부분 | 렌즈 사용 원칙만 존재 | CRITIC·REDTEAM·SELFREFINE를 검토 루프 단계로 구현(§8.4) |
| R10 | 부분 | docs/01 단일 계획, `.coord/PLAN.md` | 단일 계획을 DB와 연결 |
| R11 | 부분 | 카드·단계 규칙 존재 | 단계별 대화창 자동 생성·기록 |
| R12 | 충족 | `[U##]` 접두어 규칙 | 런처가 자동 부착 |
| R13 | 부분 | AGENTS.md 고정 규칙 | `conversation_id` 고정으로 실제 구현 |
| R14 | 미착수 | — | `connect` 자동 연결, `ask-codex` 역호출 |
| R15 | 미착수 | docs/09 설계·SQL 후보만 | SQLite 런처 구현 |
| R16 | 충족(이 보고서) | §6·§8 | 구현 중 발견 사항 추가 반영 |
| R17 | 부분 | 공식 자료로 두 도구 강점 확인(§5.4) | 역할표를 `AGENTS-CONSENSUS.md`에 고정 |
| R18 | 미착수 | U08에서 미채택 | v8에서 복원·구현 |
| R19 | 미착수 | U08에서 미채택 | `scopes` 테이블 + 런처 강제 |
| R20 | 미착수 | v7 하네스는 판정만 자동화 | 연결·위임·검증·다음 단계 자동화 |
| R21 | 미착수 | 전부 `UNMEASURED` | usage 기록 + A/B 실험 |
| R22 | 부분 | docs/09 F01~F24 계획 | 실제 테스트 구현·실행(§9) |
| R23 | 충족(이 보고서) | §5 조사 | 유지 |
| R24 | 운영 규칙 | 이 대화 방식 | 지시문에 단계 게이트 명시 |
| R25 | 반영 | 전제 §2 | 지시문에 금지 조항 |
| R26 | 충족 | §8 | 유지 |

---

## 5. 조사 결과 (DEEPDIVE)

### 5.1 로컬 실측 (L1)

| 항목 | 결과 |
|---|---|
| `agy --version` | 1.2.4 |
| `agy -p "Reply with exactly: PONG" --output-format json --mode plan` (비TTY) | exit 0, 25초, `{"conversation_id":"c4a8eb55-…","status":"SUCCESS","response":"PONG","duration_seconds":18.3,"num_turns":1,"usage":{"input_tokens":17239,"output_tokens":1191,"thinking_tokens":1189,"cache_read_tokens":0,"total_tokens":18430}}` |
| `agy` 헤드리스 플래그 | `--output-format json\|stream-json`, `--json-schema`, `--conversation <id>`, `--continue`, `--add-dir`, `--mode plan\|accept-edits`, `--sandbox`, `--dangerously-skip-permissions`, `--print-timeout`, `--effort`, `--agent` |
| `codex exec` | 0.154.0. 비대화 실행, `resume`, `fork`, `review`, `-c` 설정 덮어쓰기 |
| Codex 설정 | `model = gpt-5.6-sol`, `reasoning = low`, `windows.sandbox = "elevated"`, MCP `antigravity-bridge`, `node_repl` |
| `antigravity-bridge` | 878줄. node-pty로 `agy --print` 텍스트 화면 복원. `--output-format json` 미사용. job 상태는 `%TEMP%/agy_jobs/*.json` 덮어쓰기(예외 무시). 이어가기는 전역 `last_conversation.json`. 기본 `--dangerously-skip-permissions` |
| v7 하네스 | 9모듈. context lease, intent ledger, proof receipt, workflow invariants, snapshot, reporter, stage evaluator, benchmark hook, cli. `pytest` 37 passed |
| 프로젝트 | 비Git. `.coord/PLAN.md` U08 `REVIEW`, U03 `BLOCKED`, U04 `READY` |

설계에 쓸 수치: 위임 1회당 Antigravity 측 입력 약 1.7만 토큰, 대기 약 25초가 든다. 이 비용은 Antigravity 사용량에서 나가며 Codex 사용량에는 영향이 없다. Codex 측 비용은 런처 명령 호출과 요약 읽기뿐이다.

### 5.2 공식 자료 (L2)

- **Antigravity 헤드리스:** JSON 봉투에 `conversation_id`, `status`, `response`, `error`, `usage`, `structured_output`이 들어 있다. 워크스페이스 파일 작업은 기본 허용, shell은 기본 거부, 기본 타임아웃은 5분이다.
- **Antigravity 제품:** Agent Manager로 여러 에이전트 병렬 실행·감독, workspace `.agents` 규칙·skills·workflows를 지원한다. P6의 Multi-agent Orchestration 강점과 일치한다.
- **Antigravity Plans:** Pro·Ultra는 5시간마다 갱신되는 쿼터와 주간 한도를 가지며, AI Credits로 초과분을 사용할 수 있다.
- **OpenAI Codex 앱:** 프로젝트별 스레드, worktree 격리, diff 검토를 제공한다.
- **OpenAI Symphony SPEC:** 저장소 소유 workflow, 작업별 workspace, 단일 권위 조율 상태를 요구한다. R10 단일 계획과 일치한다.
- **OpenAI Agents SDK:** 매니저가 전문 에이전트를 도구로 호출하고 최종 응답을 소유하는 패턴을 제시한다. R05 Codex 지휘·Antigravity 하위 에이전트와 일치한다.
- **SQLite:** WAL은 같은 호스트에서 reader·writer 동시성을 제공하되 writer는 하나다. 네트워크 파일시스템은 지원하지 않는다. `BEGIN IMMEDIATE`, `busy_timeout`, Online Backup API를 쓸 수 있다.

### 5.3 GitHub·커뮤니티 (L3) — 구현 난제

| 출처 | 내용 | 설계 반영 |
|---|---|---|
| agy #1012 (open) | print-timeout 시 부분 출력과 exit 0/SUCCESS | 봉투 6중 판정, stderr 경고 검사 |
| agy #318, #947 | 비TTY에서 print 모드가 멈추거나 종료하지 않음 | 런처 이중 타임아웃, 자식 트리 종료 |
| agy #76 | 비TTY에서 stdout 누락 | JSON 봉투 파싱 실패 = 실패, 재개 |
| agy #548 | print 모드가 `permissions.allow` 무시 | `--add-dir` 범위 고정 + 사후 diff |
| agy #7 | headless 호출자의 conversation id 재개 요구 | 1.2.4 JSON에 `conversation_id` 존재 확인(L1) → `--conversation`으로 고정 |
| Codex subagent gotchas | 서브에이전트 결과 반환 누락 → 파일 기반 인계 권장, `max_threads`·`max_depth` 설정 권장 | 결과는 파일+DB, 반환 채널에 의존하지 않음 |
| hermes-agent PR #3385 | 여러 프로세스가 한 SQLite에 쓰면 WAL 잠금 경합으로 15~20초 정지 → 짧은 timeout + 지터 재시도 + BEGIN IMMEDIATE | 단일 writer 런처, 지터 재시도 |
| Zylos SQLite WAL 에이전트 패턴 | checkpoint starvation으로 WAL 비대화 → WAL 크기 감시, PASSIVE checkpoint | 유휴 시 PASSIVE checkpoint, WAL 크기 경고 |
| Beads (Yegge) | SQLite + JSONL export + git으로 에이전트 작업 추적, 워크트리별 에이전트 | DB 장애 대비 JSONL 병행, git 체크포인트 |
| Markdown 보드 사례(tick-md 등) | 사람이 읽는 단일 파일로 조율 투명성 확보 | `PLAN.md`·`AGENTS-CONSENSUS.md`를 DB에서 렌더링 |
| MCP Agent Mail, Concord MCP | 파일 claim·lease·evidence handoff | `scopes`·`attempts`·receipt 구조 |
| Reddit r/codex·r/AI_Agents·r/ClaudeAI | worktree로 파일 충돌은 줄지만 DB·포트 충돌은 남음, 카드별 소유권과 짧은 인계가 효과적 | `scopes`에 포트·DB 자원 포함 |
| Zylos 멀티에이전트 토큰 연구 | 오버헤드 대부분이 컨텍스트 전달에서 발생 | Codex에는 요약·위험 diff만 반환 |

### 5.4 R17 역할 검증 결과

| 강점 주장 | 확인 근거 | 역할 정의 |
|---|---|---|
| Codex — 설계 구조·예외 진단(Security & Skeleton) | Codex 앱 worktree·diff 검토, `codex exec review`, 샌드박스·승인 정책 | 프로젝트 진단, 아키텍처 골격, 인터페이스·명세, 보안·예외 경로 검토, 최종 판정, `backend/` 전담 |
| Antigravity — 병렬 서브에이전트·동적 라우팅·프로토타이핑 | 공식 Agent Manager 병렬 에이전트, 헤드리스 CLI, `--agent` 프로필 | 대량 구현, 병렬 조사, 프로토타입, 테스트 실행·수정 반복, `frontend/` 전담 |

---

## 6. 기존 문서·구현 전수 분석

### 6.1 문서별 기여와 v8 처리

| 문서 | 핵심 기여 | v8 처리 |
|---|---|---|
| 00 | 충돌 해결·다이어트·맞춤형·자율성 목적 정의 | 목적으로 유지 |
| 01(md) | 단일 계획, `[U##]`, 단계별 단일 소유자, 상태 기계, 작업 카드 | 정본 유지 + 디렉터리 권한 병렬 허용 추가 |
| 01·02(html) | Intent/Permission/Evidence, R0~R3, Cost Firewall, Verification Receipt | Safety Guard에 통합 |
| 03 | 위임 모드, 카드 5필드, 30초 질문 | 카드 필드로 유지 |
| 04 | P0 설정 충돌, skills·memory·MCP 다이어트 | 적용 완료(06) |
| 05 | 2-AI 계약, 사용량별 라우팅, 위임 손익 | 라우터 규칙으로 구현 |
| 06 | 전역 정리 실행 기록 | 현재 기준선 |
| 07 | C3P 재사용 메커니즘, 측정 스키마, managed/standalone | 측정·모드 유지 |
| 08 | 컨텍스트 계층, intent ledger, proof ladder, 7줄 보고, 자동 진행 | Safety Guard·보고 규칙 |
| 09 | 연속 실행 계약, 오류 분류, SQLite plane, F01~F24 | SQLite 설계 기반, 스키마 통합 |
| 10 | 보강 G1~G9, SQLite vs MCP | 이 보고서로 대체·확장 |

### 6.2 U08과 사용자 제안의 차이 (복원 대상)

| U08 결정 | 사용자 제안 | v8 |
|---|---|---|
| `shared-specs.md`·`AGENTS-CONSENSUS.md` 미채택(정본 증가 우려) | R18 작성 | **채택.** 정본 증가는 DB 렌더링으로 해결 |
| 디렉터리 브랜드 전담 미채택 | R19 엄격 분리 | **채택.** `scopes` 테이블로 강제 |
| "연결 실패 0%가 아니라 증거 손실 0" | R15 100% 유연한 연결 | **연결 연속성 100%**로 정의: 어떤 장애 뒤에도 같은 작업·대화·체크포인트로 자동 재개(§8.3) |
| Antigravity→Codex 호출 공식 근거 없음 | R14 호출 가능 | **채택.** `codex exec` 로컬 확인 → `ask-codex` |

### 6.3 남은 충돌·결함 목록

| # | 충돌·결함 | 처리 |
|---|---|---|
| C1 | Codex 전역 룰 "Antigravity 위임은 `antigravity-bridge`만 사용" ↔ R15 SQLite | 전역 룰을 런처 우선으로 재작성 |
| C2 | `mia-vaccine-test`가 삭제된 vibe-clinic MCP를 참조 | MCP 없을 때 로컬 진단으로 전환하는 문구로 수정 |
| C3 | 브리지 `use_antigravity` 설명의 auto_approve 기본값과 구현 상수 불일치(docs/09) | 브리지는 조회용으로 강등, 설명만 교정 |
| C4 | 브리지 전역 `last_conversation` 이어가기 → 단계 대화 섞임 | 런처에서 `--conversation` 고정 |
| C5 | 브리지 job JSON 비원자 덮어쓰기·예외 무시·재시작 복구 없음 | SQLite로 대체 |
| C6 | 메모리에 과거 C3P 호출법이 현재처럼 남음 | `status=historical` 메타데이터 추가 |
| C7 | `.coord/PLAN.md`에 U03 `BLOCKED`·U04 `READY`가 역사 기록으로 남음 | `SUPERSEDED`로 정리 |
| C8 | docs/01 `WIP=1` ↔ R18·R19 동시 병렬 사용 | 같은 scope 안에서는 WIP=1, 서로 다른 scope끼리는 병렬 |
| C9 | 프로젝트 비Git → 무승인 자율 편집 복구 수단 없음 | 로컬 Git + 자동 체크포인트 |
| C10 | v7 하네스가 실제 위임 경로와 미연결 | `delegate` 명령에 통합 |

---

## 7. Safety Guard 설계 (R06·R09)

### 7.1 환각 방지

| 가드 | 동작 |
|---|---|
| 봉투 6중 판정 | ① exit 0 ② JSON `status=SUCCESS` ③ `error` 없음 ④ 응답·`structured_output` 비어 있지 않음 ⑤ stderr에 timeout/partial 경고 없음 ⑥ 카드 검증 명령 exit 0 |
| 구조화 출력 | 결과 보고를 `--json-schema`(result, changed_files, checks[{cmd, exit}], risks, next)로 강제 |
| 자기보고 불신 | `changed_files`는 실제 git diff와 대조, 불일치 시 실패 |
| 범위 검사 | 변경 경로가 `scopes`의 소유 경로 밖이면 `SCOPE` 실패, 체크포인트로 복원 |
| 컨텍스트 계층 | Tier0(목표·승인 경계·활성 카드)만 상시 전달, 나머지는 경로 포인터 |
| 사실 구분 | 보고에 FACT/ASSUMPTION/UNKNOWN 표기 |

### 7.2 토큰 낭비 방지

| 가드 | 동작 |
|---|---|
| Codex 요약 반환 | 런처가 결과를 7줄 이내 JSON 요약 + 위험 diff 경로로만 Codex에 반환 |
| 폴링 제거 | `delegate wait`가 블로킹 대기. 도구 스키마 상주 없음 |
| 대화 재사용 | 같은 단계는 같은 `conversation_id`로 이어서 컨텍스트 재주입 방지 |
| 무한 재시도 차단 | 같은 원인 3회 → `BLOCKED` |
| 중복 실행 차단 | `idempotency_key UNIQUE` |
| 짧은 접두어 | `[U##]` 고정 |
| 사용량 원장 | 호출마다 usage 기록, 단계·도구별 누적 표시 |

### 7.3 비가역 행동 경계

정상 범위의 조사·편집·테스트·재작업·다음 단계 진행은 무승인이다(P5). 삭제·push·배포·결제·계정/권한/자격증명 변경은 현행 Codex 전역 룰대로 행동 직전에 사용자 확인을 받는다. 자식 프로세스 환경에서는 자격증명 변수를 제거하고, Git remote 변화를 감지하면 즉시 중지한다.

---

## 8. 연결 설계 — SQLite 로컬 DB (R15·R16·R26)

### 8.1 구조

```text
Codex 세션 시작
  └─ AGENTS.md 지시 → python -m v7_harness.cli connect
       ├─ DB 열기·스키마 검사·quick_check
       ├─ agy --version / codex --version
       ├─ running 인데 프로세스 없음 → orphaned → 자동 재개
       └─ 한 줄 상태 출력 ("connected: agy 1.2.4, active U11, 0 orphaned")

Codex(지휘)
  └─ delegate start --task U11 --scope frontend/ --schema result.json
       ├─ DB: attempt(running, idempotency_key, pid, start_time)
       ├─ git 체크포인트 커밋
       ├─ agy -p "[U11] …" --output-format json --json-schema … \
       │        --conversation <U11 id | 최초 생성> --add-dir frontend/ --print-timeout 10m
       ├─ 봉투 6중 판정 + 범위 diff
       ├─ DB: state, usage, events, receipt / 신규 conversation_id 저장
       └─ 요약 JSON 파일 기록
  └─ delegate wait --task U11 --max 540 → 요약 JSON 반환
  └─ Codex 판정: PASS → DONE → 다음 READY 단계 자동 시작

Antigravity 단독(IDE / 2.0)
  └─ ask-codex --task U11 "질문" → codex exec (resume <id>) → DB 기록 → 답 반환
```

런처가 DB의 유일한 writer다. Codex·Antigravity는 명령만 호출한다.

### 8.2 스키마

```sql
PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000;

CREATE TABLE plan          (task_id TEXT PRIMARY KEY, seq INT, title TEXT, lane TEXT,          -- codex | antigravity
                            status TEXT CHECK (status IN ('BACKLOG','READY','ACTIVE','REVIEW','DONE','BLOCKED','SUPERSEDED')),
                            depends_on TEXT, acceptance TEXT, verification TEXT, updated_at TEXT);
CREATE TABLE scopes        (path_prefix TEXT PRIMARY KEY, owner TEXT CHECK (owner IN ('codex','antigravity','shared')),
                            resources TEXT);                                                      -- ports, db, etc. JSON
CREATE TABLE conversations (task_id TEXT REFERENCES plan, tool TEXT CHECK (tool IN ('codex','antigravity')),
                            conversation_id TEXT, title TEXT, PRIMARY KEY (task_id, tool));
CREATE TABLE attempts      (attempt_id TEXT PRIMARY KEY, task_id TEXT REFERENCES plan, executor TEXT,
                            idempotency_key TEXT UNIQUE, pid INT, process_start_time TEXT,
                            state TEXT CHECK (state IN ('running','succeeded','failed','timeout','wait','orphaned','blocked')),
                            error_class TEXT, retry_count INT DEFAULT 0,
                            checkpoint_before TEXT, checkpoint_after TEXT, started_at TEXT, ended_at TEXT);
CREATE TABLE usage         (attempt_id TEXT REFERENCES attempts, tool TEXT, input_tokens INT, output_tokens INT,
                            thinking_tokens INT, cache_read_tokens INT, duration_s REAL);
CREATE TABLE receipts      (attempt_id TEXT REFERENCES attempts, check_cmd TEXT, exit_code INT, output_sha256 TEXT, at TEXT);
CREATE TABLE events        (seq INTEGER PRIMARY KEY AUTOINCREMENT, attempt_id TEXT, at TEXT, kind TEXT, detail TEXT);
```

- `PLAN.md`와 `AGENTS-CONSENSUS.md`는 `render` 명령이 DB에서 생성한다. 사람이 읽는 화면과 DB 정본이 어긋나지 않는다.
- DB에는 프롬프트·응답 전문·비밀을 넣지 않는다. 산출물은 파일로 두고 경로·SHA-256만 저장한다.

### 8.3 "연결 실패 없는 100% 유연한 연결" 보완 로직

연결 100%를 **"어떤 장애가 나도 같은 작업·대화·체크포인트로 사람 개입 없이 이어진다"**로 구현한다.

| # | 장애 | 보완 |
|---|---|---|
| L1 | 긴 작업이 Codex shell 타임아웃 초과 | `start`는 분리 실행 후 즉시 반환, `wait --max 540` 반복 |
| L2 | agy 멈춤·무출력(#318, #947) | 런처 타임아웃 = print-timeout + 60초 → `taskkill /T /F` → 같은 대화로 재개 |
| L3 | 타임아웃인데 exit 0(#1012) | stderr 경고 감지 → `timeout` → 재개 |
| L4 | stdout 누락·JSON 파싱 실패(#76) | 실패 처리 → 재개 |
| L5 | Codex 세션 종료·재시작 | DB 상태 유지 → 새 세션 `connect`에서 복원 |
| L6 | 런처 프로세스 강제 종료 | `running`+pid·start_time 불일치 → `orphaned` → 체크포인트에서 재개 |
| L7 | quota/429/rate 응답 | `wait` 상태, 체크포인트 보존, reset 뒤 같은 대화로 자동 재개 |
| L8 | 인증 만료 | `blocked(AUTH)`, 사용자 재로그인 안내 한 줄, 로그인 후 `connect`로 재개 |
| L9 | 같은 요청 중복 전송 | `idempotency_key`로 기존 attempt 반환 |
| L10 | DB 잠김 | 1초 timeout + 20~150ms 지터 재시도 15회 → 실패 시 JSONL 폴백 |
| L11 | DB 손상·디스크 오류 | `.coord/ledger-fallback.jsonl`에 append, 기동 시 백업 복원 후 JSONL 재반영 |
| L12 | WAL 비대화 | 유휴 시 `wal_checkpoint(PASSIVE)`, WAL 크기 경고 |
| L13 | Windows PID 재사용 | pid + process_start_time 동시 비교 |
| L14 | 대화 섞임 | `--continue` 금지, `--conversation <id>`만 사용 |
| L15 | Codex 샌드박스에서 분리 실행 불가 | 같은 DB를 쓰는 얇은 MCP 어댑터를 전달 경로로만 추가 (정본은 DB 유지) |
| L16 | agy JSON 형식 변경 | 스키마 검증 실패 → `VALIDATION` → 텍스트 모드 파서 폴백 1회 |

재시도 규칙: 같은 원인 연속 3회면 `blocked`로 기록하고 Codex에 보고한다. 외부 부작용 가능 명령(push·배포·외부 API write)은 자동 재실행하지 않는다.

### 8.4 예산절약 극대화 결과주의 루프 (R07·R08·R09)

```text
1. 라우터: 작업을 lane으로 배정
   - codex lane: 진단·골격·명세·보안·예외 경로·backend/·최종 판정
   - antigravity lane: 구현·조사·프로토타입·테스트 반복·frontend/·대량 작업
   - codex lane 작업도 구현량이 크면 Antigravity에 초안 위임 → Codex는 검토만
2. Antigravity 실행 → 봉투 6중 판정
3. SELFREFINE: 실패 시 같은 대화에서 Antigravity가 스스로 수정 (최대 2회)
4. CRITIC: 런처가 결정적 검사 결과 + 위험 diff 요약 생성 → Codex가 요약만 검토
5. REDTEAM: 보안·데이터·권한 경로가 바뀐 경우에만 Codex가 실패 시나리오 검토
6. 인수 기준 충족 → Antigravity 결과를 그대로 채택(Codex 재작성 금지) → DONE
7. 다음 READY 단계 자동 시작
```

Codex 사용량 보존 규칙:
- Codex는 구현 전문·로그 전문을 읽지 않는다.
- 검토 입력 상한은 요약 JSON + 위험 diff다.
- Codex 5시간 창 사용량이 높으면 codex lane 구현도 Antigravity 초안 위임으로 전환한다(docs/05 구간: 80% 이상이면 계획·경계·최종 검증만).

### 8.5 병렬 실행 규칙 (R18·R19)

- 같은 scope 안에서는 한 번에 한 단계(WIP=1)만 실행한다.
- 서로 다른 scope(`backend/`와 `frontend/`)의 단계는 동시에 실행한다.
- `shared` 경로(`AGENTS-CONSENSUS.md`, `shared-specs.md`, 인터페이스 계약)는 Codex만 수정한다. Antigravity는 변경 요청을 결과 JSON의 `spec_change_requests`로 제출한다.
- 포트·개발 DB 같은 런타임 자원도 `scopes.resources`에 lane별로 분리 기록한다.
- 두 lane의 합류는 계획에 명시된 통합 단계에서 Codex가 검증한다.

### 8.6 SQLite 방식 vs MCP 방식 비교

| 기준 | MCP 브리지(현재) | SQLite + CLI 런처(v8) | 우위 |
|---|---|---|---|
| 실패 지점 | MCP stdio·node 브리지·node-pty·agy 4곳 | shell·agy 2곳 | SQLite |
| 재시작 뒤 작업 | 고아화, 복구 없음 | DB 기반 orphaned 판정 → 자동 재개 | SQLite |
| 성공 판정 | 종료 코드 + 화면 텍스트 | 봉투 6중 판정 | SQLite |
| `[U##]` 대화창 | 전역 최근 대화 → 섞임 | 단계별 `conversation_id` 고정 | SQLite |
| 사용량 기록 | 불가 | 호출마다 토큰·시간 | SQLite |
| Codex 토큰 | 도구 스키마 상주 + 폴링 턴 | start·wait 호출 + 요약 | SQLite |
| 중복 실행 | job ID 시간+난수 | idempotency_key | SQLite |
| 디렉터리 권한 | 없음 | scopes + `--add-dir` + diff | SQLite |
| 복구 체크포인트 | 없음 | 위임 전후 git 커밋 | SQLite |
| 장시간 비동기 | 폴링에 자연스러움 | start/wait 분리로 대응 | MCP 약간 우위 |
| 도구 발견성 | 도구 목록 자동 노출 | `AGENTS.md`·전역 룰에 명시 | MCP |
| CLI 변경 영향 | 화면 형식에 매우 취약 | 공식 JSON 계약 + 폴백 파서 | SQLite |
| 구현 | 기존 878줄 JS + node-pty | v7 하네스 확장, Python 표준 라이브러리 | SQLite |

**판단: SQLite + CLI 런처를 주 연결로 채택한다.**
1. **R07 Codex 사용량 절약:** 폴링 턴과 도구 스키마 상주가 사라지고 Codex는 요약만 읽는다.
2. **R15 끊기지 않는 연결:** 상태가 DB에 남아 어느 프로세스가 재시작해도 같은 `[U##]` 대화로 이어진다.
3. **R08 결과주의:** 기계 판정으로 Antigravity 결과를 Codex 재작업 없이 채택할 수 있다.

MCP의 두 장점(발견성·비동기)은 각각 전역 룰 명시와 start/wait 분리로 흡수한다. 브리지는 삭제하지 않고 대화형 조회 도구로 둔다. L15 조건에서만 DB를 쓰는 얇은 MCP 전달 어댑터를 추가한다.

### 8.7 ALT3 — 구현 대안

| 대안 | 내용 | 판정 |
|---|---|---|
| A | docs/09 풀 스키마(11테이블, fencing, inbox/outbox) | 기능은 §8.2 7테이블로 충족. 확장 여지로 보존 |
| B | v7 하네스 확장 SQLite 런처(§8) | **채택** |
| C | 같은 DB를 쓰는 MCP 전달 어댑터 + B | L15 발생 시 추가 |

---

## 9. 극한 로컬 벤치마크 (R22)

mock `agy`·mock `codex`(지연·출력·종료 코드·stderr를 조절하는 가짜 실행 파일)로 먼저 수행한 뒤 실제 CLI canary로 확인한다.

| ID | 주입 | 통과 조건 |
|---|---|---|
| X01 | 타임아웃 + exit 0 + partial 경고 | `timeout` 기록 → 같은 대화 재개 → 성공 |
| X02 | 빈 응답 SUCCESS | 실패 판정, 거짓 성공 0 |
| X03 | 무출력 멈춤 | 타임아웃 → 자식 트리 종료 → 재개 |
| X04 | JSON 깨짐 | VALIDATION → 폴백 파서 → 재개 |
| X05 | 실행 중 런처 kill | orphaned → 재개 |
| X06 | 실행 중 Codex 세션 종료 | 새 세션 `connect`로 복원 |
| X07 | 같은 요청 10회 | 실행 1회 |
| X08 | quota 응답 | wait → reset 뒤 재개 |
| X09 | 인증 오류 | blocked(AUTH), 자동 재시도 0 |
| X10 | scope 밖 파일 수정 | SCOPE 실패 → 체크포인트 복원 |
| X11 | `changed_files` 허위 보고 | git diff 불일치로 실패 |
| X12 | DB 잠금 10초 | 무한 대기 0 → 재시도 또는 JSONL 폴백 |
| X13 | DB 손상 | 백업 복원 + JSONL 재반영, 기록 손실 0 |
| X14 | 디스크 쓰기 오류 | 거짓 커밋 0, JSONL 폴백 |
| X15 | backend·frontend 동시 위임 각 5건 | 경합 정지 0, 전부 기록, scope 충돌 0 |
| X16 | 같은 scope 동시 2건 | 두 번째 대기(WIP=1) |
| X17 | `ask-codex` 도중 종료 | 세션 id로 재개 |
| X18 | 같은 원인 연속 실패 | 3회째 blocked |
| X19 | WAL 장기 reader | writer 지속, PASSIVE checkpoint, 강제 TRUNCATE 0 |
| X20 | PID 재사용 모의 | start_time 불일치로 orphaned 정확 판정 |
| X21 | Git remote 변화 감지 | 즉시 중지 |
| X22 | 자식 env 자격증명 | 변수 제거 확인 |

통과 기준: 각 시나리오 20회(총 440회). 기록 손실 0, 중복 실행 0, 거짓 성공 0, scope 위반 채택 0, 자동 재개 성공률 100%(X09·X18·X21 제외).

실제 CLI canary: 조사 1, frontend 편집 1, 테스트 실행 1, `ask-codex` 1, 총 4건.

---

## 10. 효율 향상 검증 (R21)

| 항목 | 내용 |
|---|---|
| 과제 | 같은 인수 기준의 조사 1, 코드 구현 1, 테스트·수정 1 |
| A | Codex 단독 수행 |
| B | v8(Codex 지휘·판정 + Antigravity 실행, SQLite 런처) |
| 기록 | Codex 5시간 창 사용량 변화(%), Codex 턴 수, Antigravity usage 토큰, 벽시계 시간, 재작업 횟수, 인수 기준 통과, 사용자 개입 횟수 |
| 산출 | Codex 사용량 절감률 = (A 사용량 − B 사용량) / A 사용량, 품질 통과 동등 여부 |
| 보고 | 표 1개 + 결론 3줄, DB `usage`·`receipts`에서 자동 생성 |

---

## 11. 전역 룰·skills 재작성 방향 (R01~R03)

### Codex 전역 룰 추가·교체 항목
- 역할: 조율자·지휘자·두뇌. 구현 전문은 Antigravity에 자율 위임.
- 세션 시작 시 프로젝트에 `v7_harness`가 있으면 `connect` 실행.
- 위임은 `delegate start/wait`를 우선한다. 브리지는 조회용.
- 결과는 요약 JSON과 위험 diff만 읽는다. 인수 기준 충족 시 재작성하지 않는다.
- 새 프로젝트 시작 시 `[U01] 프로젝트 진단` → `AGENTS-CONSENSUS.md` → scopes 확정.
- 대화창 접두어 `[U##]`.

### Antigravity 전역 룰 추가·교체 항목
- managed(Codex 위임): 받은 scope·인수 기준만 수행, 결과는 JSON 스키마로 보고, `shared` 경로는 변경 요청만.
- standalone(IDE·2.0): 독립 실행. 해당 프로젝트에 `.coord`가 있으면 활성 단계 scope를 확인하고, 필요 시 `ask-codex` 호출.
- 대화 첫 줄 `[U##] 제목`.

### Skills·메모리·MCP
- `mia-vaccine-test`의 vibe-clinic 참조를 로컬 진단 폴백으로 수정(C2).
- 메모리의 C3P 과거 호출법에 `historical` 표시(C6).
- MCP: Codex는 `node_repl`, `antigravity-bridge`(조회용) 유지. 연결 주 경로는 SQLite 런처.

---

## 12. 실행 단계 (R24 — 한 대화창에 한 단계, 단계 끝에 사용자 확인)

| 단계 | 대화창 | 내용 | 산출물 |
|---|---|---|---|
| S0 | `[U09] v8 설계 확정` | 이 보고서와 지시문 확정, U08 DONE, U03·U04 SUPERSEDED | PLAN 갱신 |
| S1 | `[U10] 로컬 Git` | `git init`, `.gitignore`, 초기 커밋(원격 없음) | 커밋 해시 |
| S2 | `[U11] SQLite 런처 코어` | 스키마, `connect`, `delegate start/wait/status`, 봉투 판정, scopes, 체크포인트 | 코드 + 단위 테스트 |
| S3 | `[U12] 연속성 보완` | L1~L16 구현, `ask-codex`, `render` | 코드 + 테스트 |
| S4 | `[U13] 극한 벤치마크` | X01~X22 × 20회, canary 4건 | 결과 표 |
| S5 | `[U14] 효율 검증` | A/B 3과제 | 절감률 표 |
| S6 | `[U15] 전역 룰·skills 재작성` | §11, C1~C7 정리 | 전역 파일 diff, 새 세션 로딩 확인 |
| S7 | `[U16] 실프로젝트 파일럿` | `[U01] 진단`부터 v8 전 과정 1회 운영 | 운영 기록 |

---

## 13. 출처

### 로컬
- `agy --help`, `agy changelog`, `agy -p … --output-format json` 프로브, `codex --version`, `codex exec --help`
- `260718_agentic-ai-platform-optimization/mcp/antigravity-bridge/index.js`, `~/.codex/config.toml`, `~/.codex/AGENTS.md`
- 프로젝트 `.coord/`, `AGENTS.md`, `proposals/`, `v7_harness/`, `tests/`, `docs/00`~`10`

### 공식
- [Google Antigravity Headless mode](https://antigravity.google/docs/cli/headless/)
- [Google Antigravity Plans](https://antigravity.google/docs/plans/)
- [Getting Started with Google Antigravity](https://codelabs.developers.google.com/getting-started-google-antigravity)
- [Antigravity autonomous developer pipelines](https://codelabs.developers.google.com/autonomous-ai-developer-pipelines-antigravity)
- [OpenAI — Introducing the Codex app](https://openai.com/index/introducing-the-codex-app/)
- [OpenAI Symphony SPEC](https://github.com/openai/symphony/blob/main/SPEC.md)
- [OpenAI Agents SDK — orchestration](https://openai.github.io/openai-agents-python/multi_agent/)
- [SQLite WAL](https://sqlite.org/wal.html) · [PRAGMA](https://sqlite.org/pragma.html) · [Transactions](https://sqlite.org/lang_transaction.html) · [Backup API](https://sqlite.org/backup.html)

### GitHub·커뮤니티
- [agy #1012](https://github.com/google-antigravity/antigravity-cli/issues/1012) · [#548](https://github.com/google-antigravity/antigravity-cli/issues/548) · [#318](https://github.com/google-antigravity/antigravity-cli/issues/318) · [#947](https://github.com/google-antigravity/antigravity-cli/issues/947) · [#76](https://github.com/google-antigravity/antigravity-cli/issues/76) · [#7](https://github.com/google-antigravity/antigravity-cli/issues/7)
- [Codex CLI subagent gotchas](https://codex.danielvaughan.com/2026/03/29/subagent-gotchas-known-issues/) · [Codex CLI multi-agent](https://www.morphllm.com/codex-multi-agent)
- [hermes-agent PR #3385](https://github.com/NousResearch/hermes-agent/pull/3385) · [Zylos SQLite WAL for agents](https://zylos.ai/research/2026-02-20-sqlite-wal-mode-ai-agent-systems/) · [Zylos token-efficient multi-agent](https://zylos.ai/research/2026-06-05-token-efficient-multi-agent-communication/)
- [Beads](https://betterstack.com/community/guides/ai/beads-issue-tracker-ai-agents/) · [tick-md](https://purplehorizons.io/blog/tick-md-multi-agent-coordination-markdown) · [Markdown 에이전트 조율](https://dev.to/battyterm/i-let-ai-agents-manage-themselves-with-a-markdown-file-5547)
- [MCP Agent Mail](https://glama.ai/mcp/servers/@Dicklesworthstone/mcp_agent_mail/blob/5fa08841bb5783e805d166bec4754a72b6dc1ac8/README.md) · [awesome-agent-orchestrators](https://github.com/andyrewlee/awesome-agent-orchestrators) · [codex-subagents-mcp](https://github.com/leonardsellem/codex-subagents-mcp)
- [Reddit — agent handoff](https://www.reddit.com/r/codex/comments/1v852jd/how_do_you_guys_handoff_work_between_agents/) · [Reddit — parallel agents broke](https://www.reddit.com/r/AI_Agents/comments/1v53mns/running_multiple_coding_agents_in_parallel_broke/) · [Reddit — 3 agents parallel port/DB](https://www.reddit.com/r/ClaudeAI/comments/1uy8ud0/running_3_claude_code_agents_in_parallel/)
