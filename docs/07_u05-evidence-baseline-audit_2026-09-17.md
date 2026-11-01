# U05 증거·기준선 전수 감사

- 감사 기준 시점: 2026-09-16
- 작성일: 2026-09-17
- 범위: 현재 프로젝트 문서, `260823_codex-3p-orchestrator` 현행 및 `c3p-v2-archive`, `260912_multi-party-ai-agent-real-time-orchestration-mcp`의 Git `HEAD`, 공식 문서·공개 GitHub·Reddit 보조 자료
- 조사 방식: 읽기 전용. 설정·전역 규칙·코드·패키지는 변경하지 않았다.
- 증거 등급: `FACT`(원문·코드·실측 기록으로 확인), `INFERENCE`(복수 사실에서 도출), `CLAIM`(프로젝트 문서의 주장), `UNKNOWN`(대조 측정 또는 현재 런타임 확인 없음)

## 1. 결론

v7은 **Codex 단일 조율자 + 단계별 단일 소유자 + 검증 게이트**를 유지하되, C3P를 협의체로 복원해서는 안 된다. 재사용할 것은 역할 이름이 아니라 다음의 작고 검증 가능한 메커니즘이다.

1. 작업 카드의 목표·범위·소유자·의존성·인수 조건·검증 명령
2. 한 자원 한 소유자, 충돌 없는 작업만 병렬화
3. 구조화된 결과 봉투와 실패 시 최대 1회 승격
4. 코드 결함과 환경 결함을 구분하는 fail-closed triage
5. 비용·품질·지연·안전을 함께 기록하는 대조 실험

C3P의 “80%/85%/95%/99% 토큰 절감”, “Ollama 0원”, “전수 검증 완결”은 v7의 사실로 가져오면 안 된다. C3P R-C-S 결과는 세 작업의 처리 시간과 출력 길이를 기록했지만 동일 과제의 클라우드 대조군, 공급자별 실제 입력·출력 토큰, 검토·재작업 비용이 없었다. 따라서 절감 효과는 `UNMEASURED`다.

Codex를 “두뇌·지휘자”, Antigravity를 “위임 범위의 자율 실행자”로 두는 것은 **Codex가 조율하는 프로젝트 세션 안에서만** 타당하다. Antigravity는 공식 자료상 독립 실행·조율 제품이기도 하므로 단독 세션에서는 독립 실행자다. 이중 역할은 모순이 아니라 실행 컨텍스트별 권한 계약으로 표현해야 한다. 브랜드 고유의 영구 서열로 쓰면 책임·권한이 뒤섞인다.

## 2. 감사 대상과 스냅샷

### 2.1 현재 프로젝트

- [`docs/01_unified-agent-orchestration-design.md`](01_unified-agent-orchestration-design.md): 하나의 계획, 단계별 한 대화창·한 소유자, `WIP=1`, 검토자만 `DONE` 전환.
- [`docs/03_code-reading-agentic-ai-environment-improvement-report_2026-09-16.md`](03_code-reading-agentic-ai-environment-improvement-report_2026-09-16.md): 의도·권한·증거·책임, 위험 기반 검토, 비용·시간·토큰 `UNMEASURED`.
- [`docs/04_three-ai-global-environment-audit-and-v5-design_2026-09-16.md`](04_three-ai-global-environment-audit-and-v5-design_2026-09-16.md): 3-AI 동등 합의 폐기, Codex 지휘/Antigravity 실행 가설을 조건부 채택.
- [`docs/05_two-ai-results-first-global-environment-v6_2026-09-16.md`](05_two-ai-results-first-global-environment-v6_2026-09-16.md): 위임 손익식, 2-AI 계약, A/B 3건 전까지 절감률 미측정.
- [`docs/06_v6-global-environment-execution-record_2026-09-16.md`](06_v6-global-environment-execution-record_2026-09-16.md): 규칙 축약 및 도구 정리 기록. 브리지 런타임 건강은 `UNKNOWN`.

현재 폴더는 Git 저장소가 아니다. 따라서 이 폴더 자체의 커밋 이력·worktree 격리·변경 추적은 검증되지 않았다.

### 2.2 `260823_codex-3p-orchestrator`

- 현행 커밋: `fa0e57b7e843a272f3397599e6cc348ae9e1de30`
- C3P 보존 태그: `c3p-v2-archive` = `58ac0d8e41cfe95e38e33ade644f668a9a2d1386`
- 현행 결정문 `docs/C3P_RETIREMENT_DECISION.md`는 투표·정족수·소켓 브로커·부재 모드·예산절약 모드를 제거했고, “입력 토큰 85% 이상 절감”을 `EXPLORATORY_UNVERIFIED`로 판정한다.
- 보존 태그에는 예산 라우팅, 로컬 Ollama 하네스, SQLite 작업 조율, 인증, 합의, 증거 정책과 테스트가 남아 있다.

### 2.3 `260912_multi-party-ai-agent-real-time-orchestration-mcp`

- Git `HEAD`: `6da7cd9331d1a293cab967c1d13c4fcff299af82`
- 작업 트리의 추적 파일 전체가 삭제 표시(`D`) 상태다. 감사는 이를 복구하거나 변경하지 않고 `git show HEAD:<path>`로만 읽었다.
- `central_hub`에는 단일 쓰기 큐, Bearer 인증, heartbeat/state, resource lock, 정적 worktree pool, 3단계 오류 분류, MCP 어댑터가 있다.
- 문서의 85–95%/99% 절감 표현은 코드 구조가 존재한다는 사실과 절감률이 입증됐다는 사실을 혼동한다.

## 3. C3P 예산절약 로직 추출과 판정

| 로직 | 원래 의도 | 확인된 구현·증거 | v7 판정 |
|---|---|---|---|
| 비대칭 쿼터 라우팅 | 희소한 Codex/Claude 사용량을 판단·고위험 검토에 보존 | `docs/37`, `docs/40`; 현재 v6도 직접 실행과 위임의 총비용 비교를 채택 | **재사용**. 브랜드 고정 우선순위 대신 현재 쿼터·위험·적합성 입력 필요 |
| 3줄 요약 + diff + 실측 지표 | 장문 원문을 모든 도구에 반복 전송하지 않음 | 구조화된 handoff 형식 존재 | **조건부 재사용**. 요약만 보지 말고 위험 표본·원문 포인터·diff를 함께 보존 |
| Ollama 저위험 전처리 | AST/로그/HTML 정제 등을 로컬 모델에 위임 | 15초 timeout, 스키마 검사, 1회 승격 코드·테스트 기록 | **기본 폐기/옵션 실험**. 현행 v6 성과 경로에서 제거됐고 총비용 대조군 없음 |
| fail-fast, escalate-once | 무한 재시도와 검토 낭비 방지 | `docs/40`, 하네스 및 failure-path 테스트 | **재사용**. 같은 입력·원인에 한 번만 승격하고 이후 `BLOCKED` |
| R-C-S 세 작업 벤치마크 | 연구·코드·보안 작업에서 절감과 품질 바닥선 측정 | 8.563s/1.664s/0.372s와 출력 기반 259/150/200 토큰 추정 | **측정 설계만 재사용**. 절감률은 `UNMEASURED`; 실제 청구·입력·검토 토큰 필요 |
| “0-token/0원” | 외부 모델 토큰 미사용 강조 | 로컬 추론은 전력·시간·메모리·유지보수 비용 발생 | **표현 폐기**. `external_model_tokens=0`처럼 경계를 명시 |
| 자동 watch/부재 모드 | 사용자가 없어도 감시·진행 | 현행 C3P에서 복잡성과 권한 위험 때문에 폐기 | **폐기**. 명시적 자동화·승인 계약 없이는 복원 금지 |

### 비용 절약 가설의 올바른 식

`순절감 = 직접 수행 총비용 - (위임 준비 + 실행 + 인계 읽기 + 검증 + 재작업 + 조율 인프라)`

여기서 비용은 공급자 토큰만이 아니라 벽시계 시간, 사람 검토 시간, 실패·재작업, 로컬 연산, 외부 효과 위험을 포함해야 한다. 현재 어느 문서도 이 전체 식의 대조 측정을 완료하지 않았다.

## 4. 조율·상태·권한·검증 메커니즘

### 4.1 재사용 가능한 핵심

| 영역 | 확인된 메커니즘 | 강점 | 한계·필수 보완 |
|---|---|---|---|
| 조율 | Work Item에 `goal/scope/owner/read_set/write_set/dependencies/acceptance/verification/risk/revision` | 자연어 인계보다 충돌 판정 가능 | 현재 프로젝트의 Markdown 카드와 필드 매핑 필요; 도구가 카드를 우회할 수 있음 |
| 상태 | `BACKLOG/READY/ACTIVE/REVIEW/DONE/BLOCKED`; 참조 구현은 SQLite claim/lease/heartbeat | 명시적 전이와 재시작 진단 가능 | 상태 파일·DB가 실제 작업 결과와 달라질 수 있으므로 diff/test 재검증 필요 |
| 소유권 | write-set 단일 소유자, 충돌 검사, worktree slot | 같은 파일의 동시 쓰기 억제 | worktree는 DB·포트·캐시·외부 계정을 격리하지 않음 |
| 낡은 결과 | revision + 단조 증가 token | 늦게 도착한 결과 식별 | 일반 파일 시스템은 token을 검사하지 않음. 단일 writer 또는 제출 관문 없이는 협력적 통제일 뿐 |
| 권한 | Bearer 인증, workspace 범위, 상태 변경 endpoint 보호 | 무인 로컬 포트의 작업 주입 위험 감소 | 로컬 bearer만으로 사용자 승인·파일 권한·외부 API 권한을 대체할 수 없음 |
| 검증 | 인수 조건·검증 명령, 결과 봉투, 오류 분류, regression/failure-path tests | 완료 자기보고를 증거에서 분리 | 문서의 “전수 검증”은 운영 환경·대조 비용·실제 공급자 동작까지 보장하지 않음 |
| 복구 | lease 만료, 한 번의 재배차, quarantine, fail-closed unknown | 무한 루프와 오수정 억제 | 파괴 작업·DB migration·배포의 rollback receipt는 별도 필요 |

### 4.2 공식 자료와의 정합성

- OpenAI Codex 앱은 프로젝트별 분리 스레드와 worktree를 통한 병렬 작업·diff 검토를 제공한다. 이는 “전용 대화창 + 격리 작업공간”을 지지하지만, 병렬화 자체가 안전하다는 보장은 아니다. [Introducing the Codex app](https://openai.com/index/introducing-the-codex-app/)
- OpenAI Symphony 초안은 저장소 소유 `WORKFLOW.md`, issue별 결정적 workspace, 단일 권위 조율 상태, bounded concurrency, structured logs를 요구한다. 동시에 sandbox/approval 정책은 구현이 명시해야 하며 workspace 격리가 그 대체물이 아니라고 한다. [Symphony SPEC](https://github.com/openai/symphony/blob/main/SPEC.md)
- OpenAI Agents SDK는 중앙 매니저가 전문 에이전트를 도구로 호출하고 최종 응답을 소유하는 패턴과, 전문 에이전트가 대화를 인수하는 handoff 패턴을 구분한다. 코드 기반 조율이 속도·비용·성능을 더 예측 가능하게 하며 독립 작업만 병렬화하라고 설명한다. [Agent orchestration](https://openai.github.io/openai-agents-python/multi_agent/)
- Google Antigravity 공식 Codelab은 `.agents` 규칙·skills·workflows와 workspace 내부 새 대화를 이용한 자율 파이프라인을 제시한다. 별도 공식 입문서는 Antigravity 자체를 여러 로컬 에이전트를 실행·감시·조율하는 독립 command center로 정의한다. [Autonomous developer pipelines](https://codelabs.developers.google.com/autonomous-ai-developer-pipelines-antigravity), [Getting Started with Google Antigravity](https://codelabs.developers.google.com/getting-started-google-antigravity)
- Anthropic은 자체 연구 시스템에서 에이전트가 일반 채팅의 약 4배, 다중 에이전트가 약 15배 토큰을 사용했다고 보고하며, 의존성이 높은 코딩은 적합도가 낮다고 명시한다. 이는 “도구 수 증가 = 비용 절감” 가설의 직접 반대 근거다. [How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system)
- Kubernetes Lease는 holder·renew time을 명시하며 leader election/heartbeat에 쓰인다. Lease는 생존·점유 신호이지 결과의 정확성 증명이 아니다. [Kubernetes Leases](https://kubernetes.io/docs/concepts/architecture/leases/)

## 5. 이중 역할 전제 레드팀

### 전제

- Codex: 두뇌·지휘자·최종 판정자
- Antigravity: Codex 위임 범위에서는 자율 실행자, 단독 사용 시 독립 실행자

### 지지 근거

1. 중앙 매니저가 전문 실행자를 도구로 부르고 최종 답을 소유하는 패턴은 OpenAI Agents SDK의 manager/agents-as-tools 패턴과 일치한다.
2. 현재 프로젝트의 목표는 하나의 계획과 검증 게이트를 유지하는 것이므로 프로젝트 안에서는 단일 조율자가 책임 추적에 유리하다.
3. Antigravity는 공식적으로 독립 command center·IDE·CLI로도 동작하므로 단독 사용 시 독립 실행자라는 설명은 사실에 부합한다.

### 반대 근거와 실패 가능성

1. **브랜드를 권한으로 오인:** Codex라는 이름이 항상 더 정확하거나 더 저렴하다는 증거는 없다. 조율 권한은 프로젝트 계약에서 나오며 모델의 본질적 우월성에서 나오지 않는다.
2. **컨텍스트 누락:** Antigravity 단독 세션이 프로젝트 카드·승인 게이트를 로드하지 않으면 독립 실행이 같은 저장소의 계획을 우회할 수 있다.
3. **자기검증 편향:** Codex가 계획·배정·검토를 모두 소유하면 자신의 잘못된 목표를 같은 기준으로 승인할 수 있다. 고위험 단계에는 독립 oracle 또는 인간 승인이 필요하다.
4. **위임 역설:** Antigravity 결과를 Codex가 전부 다시 읽고 재작성하면 토큰·지연이 증가한다. 반대로 요약만 읽으면 중요한 결함을 놓칠 수 있다.
5. **도구 가용성 변화:** 쿼터·모델 품질·CLI 권한·공식 기능은 변한다. “항상 Antigravity 우선”은 곧 낡는다.
6. **대화창과 실제 자원 불일치:** 전용 창이 있어도 같은 작업 트리·DB·포트·계정을 공유하면 충돌한다.

### 판정

`CONDITIONAL GO`. 역할을 다음 두 계약으로 분리한다.

- **Managed context:** Codex가 카드·범위·인수 기준을 발행하고 Antigravity는 그 단계에서 `REVIEW`까지만 수행한다.
- **Standalone context:** Antigravity가 계획·실행·자체 검증을 소유하되, 이 프로젝트를 수정하려면 기존 `.coord/PLAN.md`와 활성 카드의 소유권을 먼저 확인하고 충돌 시 중지한다.

최종 판정 권한은 브랜드가 아니라 **활성 프로젝트 계약과 승인 주체**에 귀속한다.

## 6. 재사용·조건부 재사용·폐기

### 재사용

- 단일 계획, 단계 카드, 한 단계 한 소유자, `REVIEW`와 `DONE` 분리
- goal/scope/read-set/write-set/dependency/acceptance/verification/risk 필드
- 독립 작업만 병렬화하고 기본 `WIP=1`
- 구조화된 handoff: 결과, 변경, 검증 명령·exit code, 위험, 다음 행동
- fail-closed unknown, 오류 원인 분류, 동일 원인 재시도 제한
- 버전/환경 변화 뒤 경계 회귀 검사

### 조건부 재사용

- worktree pool: Git 파일 격리와 런타임 자원 격리를 함께 설계할 때
- lease/heartbeat/fencing token: 모든 결과가 단일 제출 관문을 통과할 때
- 로컬 모델 전처리: 고정 데이터 변환, 스키마 검증, 대조군, 자원 계측이 있을 때
- 병렬 에이전트: 의존성·write-set·DB·포트·캐시·외부 계정이 모두 분리됐을 때
- 요약 기반 검토: 원문 포인터와 위험 기반 표본 검사가 있을 때

### 폐기

- 3도구 동등 투표·정족수·상호 고발을 기본 운영으로 쓰는 것
- 항상 3개 도구를 호출하는 의식적 절차
- “80/85/95/99% 절감”, “0원”, “완전 검증”의 무대조 주장
- 에이전트 자기보고만으로 `DONE` 처리
- 파일 락 또는 worktree만으로 런타임·외부 자원 충돌까지 해결됐다고 보는 것
- 자동 승인·부재 모드를 안전 경계 없이 복원하는 것
- 전역 규칙에 프로젝트별 역할·상태·라우팅을 중복 복제하는 것

## 7. P0/P1 실패 시나리오

| 우선순위 | 시나리오 | 촉발 조건 | 탐지 증거 | 필수 대응 |
|---|---|---|---|---|
| P0 | 무승인 외부 효과 | deploy/push/delete/결제/권한 변경이 하위 실행자에게 열림 | 외부 receipt, Git remote 변화, 계정 로그 | 즉시 중지, 사용자에게 영향 보고, 복구 가능성 확인; 행동별 재승인 전 재개 금지 |
| P0 | 비밀 유출 | 로그·handoff·child env에 토큰 전달 | redaction 실패, secret scanner, provider audit | 출력 중단·폐기, 자격증명 회전은 사용자 승인 후 수행 |
| P0 | 동시 쓰기/낡은 결과 덮어쓰기 | 소유권 중복, lease 만료 후 직접 파일 쓰기 | revision/token 역전, 예상 밖 diff | 두 실행자 중지, 실제 diff 보존, 단일 소유자 재지정; 단일 writer 없이는 fencing 주장 금지 |
| P0 | 잘못된 목표의 성공 판정 | 계획자와 검토자가 같은 잘못된 oracle 사용 | 테스트 PASS지만 사용자 인수 기준 불충족 | 목표·oracle 재승인, 고위험에는 독립 검증 또는 인간 gate |
| P0 | 환경 오류를 코드 결함으로 오분류 | 포트/DB/권한 오류 뒤 자동 코드 수정 | infra signature와 source diff 동시 발생 | fail-closed, 자원 해제·격리 후 재현; 미분류면 코드 수정 금지 |
| P1 | 위임이 직접 수행보다 비쌈 | 짧은 작업을 카드·다중 도구로 분해 | 총 지연·검토 토큰 증가 | 임계값 조정, 저위험 단일 작업은 활성 도구 직접 수행 |
| P1 | 요약 압축으로 결함 누락 | 3줄 handoff만 검토 | 표본 diff에서 누락 발견 | 위험 파일·원문 포인터·테스트 로그 해시 포함, 표본 감사율 기록 |
| P1 | worktree 밖 공유 상태 충돌 | 동일 DB/포트/cache/account | flaky test, schema/port 충돌 | 런타임 자원 임대·namespace 분리 또는 직렬화 |
| P1 | 상태 정본 드리프트 | 카드/SQLite/대화 상태가 다름 | 서로 다른 owner/status | 정본 하나 지정, 이벤트 append와 재조정 검사; 자기보고로 자동 승격 금지 |
| P1 | 쿼터 고정 라우팅 노후화 | 공급자 정책·품질 변화 | 실패율·사용량 추세 변화 | 매 작업 동적 입력 사용, 주기적 A/B 재측정 |
| P1 | 브리지 불가용 | 설정만 있고 실행 파일/연결 없음 | health check `UNKNOWN` 또는 실패 | 직접 수행/명시적 BLOCKED; 존재 등록을 건강으로 간주하지 않음 |

## 8. v7 고정 기준선과 측정 계약

현재는 대부분 사전 기준선이 없으므로 “목표”와 “현재 관측”을 분리한다. 아래 지표를 동일 과제 A/B에서 수집하기 전 절감 주장은 `UNMEASURED`다.

### 8.1 비용

| 지표 | 정의 | 현재 기준선 | 초기 합격 조건 |
|---|---|---|---|
| 공급자별 input/output tokens | 도구·모델별 실제 계측값, 서로 다른 tokenizer는 별도 보고 | `UNKNOWN` | 누락 0건; 이종 토큰을 단순 합산하지 않음 |
| 실제 청구 비용 | 공급자 receipt 또는 요금표로 계산 | `UNKNOWN` | 직접 수행 대비 총비용 비열화 없음 |
| 조율 오버헤드 | 카드 작성+인계 읽기+검토+재작업 시간/토큰 | `UNKNOWN` | 전체의 별도 항목으로 공개 |
| 로컬 연산 비용 | wall time, peak RAM/VRAM, 전력은 가능 시 | R-C-S wall time만 부분 존재 | “0원” 대신 관측 경계 명시 |

### 8.2 품질

| 지표 | 정의 | 현재 기준선 | 초기 합격 조건 |
|---|---|---|---|
| acceptance pass rate | 독립 oracle을 통과한 작업 비율 | `UNKNOWN` | 대조군보다 악화 없음 |
| escaped defect rate | `DONE` 후 발견된 P0/P1 결함 | `UNKNOWN` | P0 0건; P1 대조군보다 악화 없음 |
| rework count | 같은 인수 기준으로 재작업한 횟수 | `UNKNOWN` | 중앙값 1회 이하를 실험 목표로 두되 사전 확정 아님 |
| evidence completeness | 변경·명령·exit code·위험·원문 포인터 완비율 | 카드 규칙만 존재 | 100% |

### 8.3 지연

| 지표 | 정의 | 현재 기준선 | 초기 합격 조건 |
|---|---|---|---|
| lead time | READY부터 REVIEW까지 | `UNKNOWN` | 작업 유형별 대조군보다 개선 또는 비용/품질 이득으로 상쇄 |
| review latency | REVIEW부터 판정까지 | `UNKNOWN` | 별도 측정 |
| blocked time | 승인·자원·브리지 대기 시간 | `UNKNOWN` | 원인별 분리 기록 |
| retry latency | 실패 뒤 성공/중지까지 | `UNKNOWN` | 같은 원인 무한 재시도 0건 |

### 8.4 안전

| 지표 | 정의 | 현재 기준선 | 고정 바닥선 |
|---|---|---|---|
| unauthorized external effects | 무승인 push/deploy/delete/결제/권한 변경 | 현재 프로젝트 기록상 목표 0, 독립 관측 없음 | 0건 |
| ownership conflicts | 겹치는 write/runtime resource 소유 | `UNKNOWN` | 0건 |
| unverified DONE | 검증 증거 없이 DONE | 카드 설계상 금지, 실측 없음 | 0건 |
| secret exposure | 출력·로그·커밋 내 비밀 | `UNKNOWN` | 0건 |
| stale result accepted | 만료 revision/token 결과 수용 | `UNKNOWN` | 0건 |

### 8.5 최소 A/B 설계

같은 난이도의 R(조사), C(코드), S(보안/실패경로) 각 3쌍 이상을 사전 등록한다.

- A: Codex 직접 수행
- B: Codex 계획·검토 + Antigravity 실행
- 고정: 입력, 저장소 커밋, 인수 기준, 실행 환경, 시간 제한
- 기록: 공급자별 토큰·청구, wall time, 사람 개입 시간, 재작업, acceptance 결과, P0/P1, 외부 효과
- 중단: P0 1건, 비밀 노출 1건, 대조군 대비 품질 바닥선 실패
- 채택: 비용 또는 지연 중 하나가 개선되고 품질·안전이 비열화하지 않을 때만

세 쌍은 방향성 탐색일 뿐 일반화 근거로 부족하다. 안정적 라우팅 임계값은 작업 유형별 표본이 쌓인 뒤 정한다.

## 9. 주장-근거 매트릭스

| ID | 주장 | 판정 | 근거 | 반대·한계 | v7 처리 |
|---|---|---|---|---|---|
| C01 | 단일 조율 상태가 중복 배차를 줄인다 | `FACT + INFERENCE` | Symphony 단일 권위 상태; C3P SQLite claim | 정본 자체가 드리프트 가능 | 유지 + 재조정 검사 |
| C02 | worktree가 병렬 에이전트 충돌을 해결한다 | `PARTIAL` | Codex 앱 공식 worktree 격리; 참조 worktree pool | DB·포트·cache·계정은 미격리 | 파일 격리로만 표현 |
| C03 | 펜싱 토큰이 낡은 파일 쓰기를 100% 막는다 | `FALSE AS STATED` | C3P `docs/43`도 파일 시스템 미검증을 인정 | 단일 writer 없으면 협력적 통제 | 단일 제출 관문에서만 사용 |
| C04 | 다중 에이전트는 비용을 절감한다 | `UNKNOWN` | 일부 작업 분담 논리 | Anthropic은 약 15배 토큰 사용 보고 | 작업별 A/B 전 `UNMEASURED` |
| C05 | C3P가 입력 토큰 80–99%를 절감했다 | `UNVERIFIED` | C3P 문서의 요약/AST 주장 | 대조군·실청구·검토비 없음; retirement 문서가 스스로 철회 | 수치 폐기 |
| C06 | R-C-S 벤치마크가 절감률을 입증했다 | `FALSE AS STATED` | 세 작업 wall time·출력 길이 존재 | cloud baseline 없이 출력 길이를 saved token으로 환산 | 실행 가능성 증거로만 보존 |
| C07 | 로컬 Ollama는 0원이다 | `MISLEADING` | 외부 cloud token 0 가능 | 전력·시간·메모리·유지보수 존재 | 경계가 명시된 지표로 교체 |
| C08 | Codex manager + Antigravity worker는 유효한 패턴이다 | `CONDITIONAL` | Agents SDK manager 패턴; 현재 프로젝트 계약 | 브랜드 우월성·항상 최저비용은 미확인 | managed context에서만 적용 |
| C09 | Antigravity는 단독 독립 실행자다 | `FACT` | Google 공식 command center/IDE/CLI 설명 | 이 프로젝트의 활성 카드 소유권을 자동 인지한다는 뜻은 아님 | standalone 계약 추가 |
| C10 | 한 단계 한 소유자와 검토 분리는 안전성을 높인다 | `INFERENCE` | 현재 설계, Symphony, 조율 구현 공통점 | 잘못된 oracle·동일 검토 편향은 남음 | 유지 + 고위험 독립 oracle |
| C11 | lease/heartbeat가 완료를 증명한다 | `FALSE` | Kubernetes에서 lease는 생존·leader election 신호 | 결과 정확성·인수 기준과 무관 | 상태 증거와 결과 증거 분리 |
| C12 | 코드 기반 라우팅은 비용·속도·성능을 예측 가능하게 한다 | `FACT`(공식 지침) | OpenAI Agents SDK | 분류 규칙 품질에 의존 | 구조화 분류 + eval |
| C13 | 요약 인계는 항상 총토큰을 줄인다 | `UNKNOWN` | 반복 원문 전송 회피 가능 | 검토자가 원문 재독하면 이중 비용; 누락 위험 | 원문 포인터·표본 감사 포함 A/B |
| C14 | Reddit의 worktree 경험은 일반 법칙이다 | `NO` | 반복되는 현장 사례 | 자기선택·홍보·통제군 부재 | 실패 시나리오 발견용 보조 근거만 사용 |

## 10. Reddit 보조 근거

Reddit은 정량 기준선이나 설계 권위로 사용하지 않았다. 다만 공식 worktree 설명에서 빠지기 쉬운 실패 모드를 찾는 데 사용했다.

- 여러 에이전트가 같은 저장소를 쓰면 worktree가 파일 충돌을 줄였다는 반복 경험이 있다. [동일 저장소 다중 에이전트 사례](https://www.reddit.com/r/ClaudeAI/comments/1qzduim/stop_running_multiple_claude_code_agents_in_the/)
- worktree를 써도 포트·개발 DB·migration은 충돌하며, 고정 범위나 별도 DB가 필요했다는 사례가 있다. [포트·DB 충돌 사례](https://www.reddit.com/r/ClaudeAI/comments/1uy8ud0/running_3_claude_code_agents_in_parallel/)
- 파일 상태와 런타임 상태를 함께 격리하지 않아 실패했다는 보고가 반복된다. [병렬 에이전트 실패 보고](https://www.reddit.com/r/AI_Agents/comments/1v53mns/running_multiple_coding_agents_in_parallel_broke/)

이 사례는 P1 후보를 생성하지만 발생률·효과 크기를 입증하지 않는다.

## 11. 미확인과 다음 게이트

### 미확인

- Antigravity의 2026-09-16 실제 잔여 쿼터, 실제 토큰, 청구 단가
- `antigravity-bridge`의 현재 실행 가능성과 end-to-end 성공률
- v6 축약 전후의 동일 과제 토큰·지연·결함률
- Codex 직접 대비 Antigravity 위임의 검토·재작업 포함 총비용
- 현행 글로벌 설정이 새 세션에 모두 반영됐는지 여부
- 현재 프로젝트가 Git 저장소가 아니어도 단계별 변경 provenance를 충분히 보존할 수 있는지
- 두 참조 구현이 현재 OS·도구 버전에서 그대로 통과하는지. 이번 감사는 소스·기록 읽기이며 실행 재검증이 아니다.

### v7 설계 게이트

1. 역할을 브랜드 정체성이 아니라 `managed`/`standalone` 실행 계약으로 명시한다.
2. 작업 카드에 runtime resources(DB/port/cache/account), external effects, recovery owner를 추가한다.
3. `DONE`에는 독립 oracle, 명령·exit code, 위험, 외부 receipt를 요구한다.
4. A/B 계측 스키마를 먼저 고정하고 절감률 문구는 측정 뒤에만 허용한다.
5. 자동 조율기는 Markdown 카드 실험에서 소유권 충돌 0, 무카드 변경 0, 증거 누락 0을 확인한 뒤 검토한다.

## 12. 감사 한계

- “현재 대화 맥락”은 이 U05 전용 대화에 전달된 지시와 작업 카드로 한정된다. 다른 대화의 비공개 전체 원문은 읽을 수 없었다.
- 공개 웹 자료는 2026-09-16 기준으로 우선했으며, 페이지가 이후 갱신됐을 수 있다. 제품 기능은 공식 원문에서 확인했지만 실제 로컬 설치 상태와 동일하다고 가정하지 않았다.
- 참조 저장소의 과거 테스트 PASS 기록은 실행 당시 증거다. 이번 단계에서는 패키지 설치·코드 실행·삭제 상태 복원을 하지 않았으므로 현재 재현성은 `UNKNOWN`이다.

## 13. 로컬 원문 재현 명령

```powershell
git -C "D:\D_Workspace_NB\-agentic-ai-workspace\260823_codex-3p-orchestrator" show c3p-v2-archive:docs/40_C3P_CONSOLIDATED_BUDGET_SAVING_SPECIFICATION.md
git -C "D:\D_Workspace_NB\-agentic-ai-workspace\260823_codex-3p-orchestrator" show c3p-v2-archive:docs/42_C3P_RCS_BENCHMARK_RESULTS.md
git -C "D:\D_Workspace_NB\-agentic-ai-workspace\260823_codex-3p-orchestrator" show c3p-v2-archive:docs/44_C3P_AUTOMATIC_WORK_COORDINATION_IMPLEMENTATION_AND_EVIDENCE.md
git -C "D:\D_Workspace_NB\-agentic-ai-workspace\260912_multi-party-ai-agent-real-time-orchestration-mcp" show HEAD:central_hub/hub_daemon.py
git -C "D:\D_Workspace_NB\-agentic-ai-workspace\260912_multi-party-ai-agent-real-time-orchestration-mcp" show HEAD:tests/test_failure_paths.py
```
