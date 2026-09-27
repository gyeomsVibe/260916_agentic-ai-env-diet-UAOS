# Unified Codex–Antigravity Execution

이 프로젝트의 모든 작업은 [`docs/01_unified-agent-orchestration-design.md`](docs/01_unified-agent-orchestration-design.md)를 단일 원본으로 따른다.

## 고정 규칙

- Codex는 프로젝트 조율자이며 하나의 마스터 계획, 작업 순서, 승인 게이트를 관리한다.
- 실제 수행은 프로젝트 안의 단계별 전용 대화창에서만 한다. 사용자 지시창이나 총괄 대화창에서 구현을 대신하지 않는다.
- 각 수행 단계에는 대화창 하나와 단일 소유자 한 명만 둔다. Antigravity가 수행할 때도 Codex 프로젝트의 해당 단계 전용 대화창을 맡은 실행자로 취급한다.
- 단계 대화창 제목은 짧은 접두어 `[U##]`로 시작한다. `##`는 마스터 계획의 두 자리 순번이다. 예: `[U03] 인증 오류 수정`.
- 활성 단계는 기본적으로 하나다. 선행 단계가 검증 게이트를 통과한 뒤 다음 단계를 연다.
- 두 도구가 같은 단계, 파일 범위, 브랜치, 작업트리, 데이터베이스, 포트 또는 외부 자원을 동시에 수정하지 않는다.
- 모든 인계는 말로만 하지 않고 해당 작업 카드에 결과, 변경 범위, 검증 증거, 미해결 위험, 다음 행동을 기록한다.
- 완료 보고만으로 완료 처리하지 않는다. 검토자가 인수 조건과 검증 증거를 확인한 뒤 `DONE`으로 전환한다.
- 컨텍스트는 현재 목표·승인 경계·활성 카드와 직접 의존 자료만 로딩한다. 오래된 문서·로그·폐기 결정은 권위와 유효성을 확인하기 전에는 규칙으로 사용하지 않는다.
- 사용자 보고는 결과·변경·검증·위험·다음 자동 행동만 간결하게 제시하고 상세 증거는 카드나 산출물에 보존한다.
- 사용자가 해야 할 일이 없으면 질문하지 않고 다음 `READY` 단계를 자동 진행한다. 목표·범위 변경과 명시적 승인 대상만 사용자에게 묻는다.
- 삭제, 덮어쓰기, 배포, 푸시, 결제, 계정·권한·자격증명 변경은 사용자에게 그 행동별 명시적 승인을 받는다.
- 구현·수정 작업은 Antigravity에 SQLite 경로로 위임한다: `python -m v7_harness.cli pilot run --task <ID> --source <dir> --prompt-file <md> --accept-cmd "<인수 테스트>" --work-dir .coord/pilot`
- **계약 매뉴얼 위임(U34, 2026-09-25)**: Ollama·Antigravity 위임은 `pilot manual new`로 만든 ```contract 매뉴얼을 `pilot manual lint`로 통과시킨 뒤 `pilot run --manual <파일>`로 한다. 허용 범위 밖 변경·요청 밖 삭제·문법 오류는 자동 거부되고, 승인은 계약의 판정자만 한다. 지휘자가 코드를 이미 정했으면 `worker: apply`(모델 없음·0토큰). 세부: `docs/37`.
- **출석·음성사서함(U32b)**: 세션 시작 시 `python -m v7_harness.cli coord presence --tool <codex|claude|antigravity> --state ACTIVE`를 실행하고, `coord inbox`로 쌓인 보고를 읽은 뒤 처리한 것은 `coord ack --id <ID>`로 표시한다. 새 편지를 기다릴 때는 `coord watch --target <자기 도구>`를 백그라운드로 켜 두고(U57, 0토큰, 새 편지 도착 시 exit 0, 시간 초과 exit 3), 다른 도구에게는 `coord deliver`로 보낸다. 사용자에게 전달·복사·승인을 부탁하지 않는다.
- 작업자는 둘이다. `--worker agy`(원격, 계정 한도 소모)와 `--worker local`(이 PC의 Ollama, 한도 없음). Codex가 과제마다 고른다. 고르는 기준(벤치 실측 근거, `docs/16` 벤치 v2): **바꿀 내용을 프롬프트에 구체적으로 적을 수 있으면 `local`**. 파일 크기(483줄)와 파일 수(3개 리팩터)는 한계가 아니었고, 실제로 갈린 축은 **지시의 모호함**이다. "적절히 개선"처럼 판단을 요구하는 과제와 설계·탐색은 `agy`. 로컬 기본 모델은 `qwen2.5-coder:7b`(모호한 지시까지 통과한 유일한 모델). 원격 작업자가 `QUOTA`로 막히면 같은 과제를 `local`로 1회 재시도하고 그 사실을 기록한다. 어느 쪽이든 판정은 동일한 인수 게이트가 한다(`ollama/01_작동원리와_운영_Ollama는_어떻게_돌아가나.md` §7-1).
- **계산기 원칙(사용자 지정, 2026-09-23; U30 보정)**: Claude Code·Codex·Antigravity(지휘자)에게 Ollama는 유료 API 토큰을 쓰지 않는 전자계산기다. 다만 로컬 추론 시간·토큰·전력은 든다. 지휘자는 먼저 결정적 도구로 끝낼 수 있는지 살피고, 필요한 기계적 구현은 고정 인수와 제한된 매뉴얼을 붙여 `pilot run --worker local`에 맡긴다. 모호한 설계는 지휘자가 구체화하거나 별도 예산 판단 뒤 Antigravity에 맡긴다. `--worker auto`의 REWORK→원격 자동 승격은 U30 비용·품질 관문과 충돌하므로 사용하지 않는다. 로컬 실패를 원격 재시도의 자동 허가로 보지 않는다. 커밋 관문 `.githooks/commit-msg`(`v7_harness/calculator_gate.py`)가 APPLIED pilot 결과가 아닌 `v7_harness/*.py` 변경을 막고, 예외는 커밋 메시지 `Calculator-Exempt: <이유>` 줄로만 남긴다(`docs/01` §16).
- **올라마 = '생각 없는 전자계산기이자 3대 도구의 토큰절약도구' 영구 고정(사용자 지정, 2026-09-23, 2026-09-24 재확인; U30 보정)**: 올라마는 스스로 계획·판정·승인하지 않는 로컬 계산기다. 지휘자는 구체성 80점 이상의 작업명령서(`docs/24`)를 입력 해시·출력 형식·허용 경로·원문 인용·고정 인수와 함께 전달한다. 4대 불변식: (1) **판정권 배제**: 결정론적 인수 테스트(Acceptance Gate)와 원문 대조만이 판정한다. (2) **기계 작업 위임**: 결정적 추출이 더 싸고 정확하면 모델을 호출하지 않는다. 그 밖의 좁은 요약·변환·반복 편집은 Ollama를 우선 검토한다. (3) **실패 격리**: 출력은 독립 검증 전 반영하지 않으며, 같은 원인 2회 실패 시 경로를 바꾼다. (4) **3대 도구 공통 의무**: Codex·Claude Code·Antigravity 모두 호출 비용과 검증 비용을 비교하고 실패까지 기록한다. 무조건 호출하거나 비용 0원이라고 단정하는 것도 설계 결함이다.
- **올라마 = '원할 때 언제든지 쓰는 유선 전화기' 아키텍처 모델(사용자 지정, 2026-09-24)**: 올라마는 평소에 대기하다가 필요할 때 지휘자가 다이얼을 걸어 즉시 응답을 받는 통화료 0원의 유선 전화기다. 디스크 기반 우편함(`.coord/mailbox/`, `docs/23`, `docs/24`)은 '음성사서함(Voicemail)'으로 기능하여 지휘자 부재 중 비동기 메시지를 100% 무손실 보존한다. 로컬 올라마 기반 상주 감시관(Sentinel)은 24/7 교환원으로서 상태 감시·잠금 점검·로그 트리아지를 0원에 전담하고, P1 차단 결함 또는 사용자 승인 대상 발생 시에만 지휘자의 벨을 울려(Wake-on-P1 Ringing) 1회 선별 기상시킨다. 유료 LLM의 주기적 상주 폴링(cron)은 통화료가 계속 나가는 위성전화를 켜놓는 낭비이므로 3대 도구 전체에서 영구 금지한다.
- **Codex 활성 대화창 실시간 편입 및 U15 정본 규약(사용자 지정, 2026-09-24 환원)**: Codex 앱 재시작이나 새로고침 없는 실시간 반영을 위해 U15 정본 전달기(`coord notify` / `codex queue`)를 단일 표준으로 고정한다. Antigravity와 Claude Code의 수행 보고는 현재 프로젝트 활성 대화창(`resolve_thread`)으로 즉시 배달되며, 메시지 첫머리는 `[안티그래비티에서 온 대화]`, `[클로드에게서 온 대화]` 표식을 달아 기존 대화창에 즉각 표시된다. Electron 데스크톱 앱의 UI 실시간 갱신이 불가능한 정적 SQLite/세션 직접 생성은 실시간 통신에서 제외한다(`docs/tasks/U15-coordination-stream.md`).
- **Codex 부재 중 대화창 메시지 발송 전면 금지 및 큐 오염 차단(사용자 강력 지정, 2026-09-24)**: Codex가 사용 제한·부재(`LIMITED` 또는 `ABSENT`) 상태일 때, Codex 대화창 및 메시지 큐(`codex queue`, `coord notify`)로의 메시지 발송은 예외 없이 **전면 거부(HARD REFUSE: `CODEX_ABSENT`)**된다. 한도 초과 상태인 Codex 대화창에 메시지를 전송하여 한도 에러 화면을 유발하거나 큐를 오염시키는 일체의 시도를 원천 차단하며, 모든 작업 상황은 디스크 우편함(`.coord/mailbox/`) 및 브리핑 파일에만 기록한다.

- 비용 절감 위임의 기본 경로는 `Codex 작업 계약 1회 → 결정적 control layer → Antigravity pilot → Codex 증거 판정 1회`로 한다. 토큰 대리지표와 실제 계정 사용 한도 절감은 구분하고, 후자는 직접 측정 전까지 `UNMEASURED`로 기록한다.
- **Claude Code는 Codex 활동 중에는 Codex의 지휘를 받는 부관(비서)이고, Codex 부재 중에는 대신 지휘하는 동등한 부지휘자다(사용자 지정, 2026-09-21 / 독립 분리 철회 2026-09-23).** Codex 부재 중(한도·정지·무응답)에는 Codex의 모든 권한(계획·작업자 선택·bundle 승인·PLAN 판정)을 대행한다. 대행 중 만든 변경은 반영하되 Codex 복귀 시 재검토 대상으로 표시한다.
- **Antigravity의 임시 대행 및 독자행동 권한(사용자 지정, 2026-09-23)**: Codex와 Claude Code 둘 다 사용 제한·부재(한도 소진, 정지, 무응답) 상태일 때, Antigravity는 Codex·Claude Code의 총괄 조율·계획·수행 권한을 임시 위임받아 독자행동(Autonomous Action)을 수행한다. 조율 계획(`PLAN.md`), 아키텍처 문서, 훅 및 도구 설정을 독자적으로 갱신하고 프로세스를 마무리하되, 영구 안전 한계(데이터 삭제, 원격 push, 배포, 결제, 권한 변경)는 준수하며 Codex 복귀 시 재검토 목록에 모든 근거를 기록한다. 평상시 Antigravity IDE는 원본 직접 수정을 지양하고 읽기 전용 자문·독립 검증·파일럿 실행을 수행한다.
- `pilot run` 또는 control layer 실행 중에는 source 원본을 단일 쓰기 소유자에게만 맡기고, relay·상태 점검·자문 메모를 포함한 보조 프로세스는 원본에 쓰지 않는다. 보조 산출물은 `.work/`에 기록하며 원본 변경이 감지되면 `SOURCE_DIVERGED`로 차단하고 작성자를 식별한 뒤 새 실행으로 검증한다.
- pilot 소유자는 실행 직전에 `.work/QUIET_LOCK`을 원자적으로 만들고 `owner`, `task`, `started_at`, `pid`를 기록한다. 유효한 lock이 있으면 새 실행과 원본 쓰기를 시작하지 않으며, 모든 보조 기록은 `.work/notes/`에 둔다. 소유자는 종료 후 lock을 정리하고, PID가 없거나 60분을 넘긴 고착 lock만 Codex가 해제 사실을 기록한 뒤 정리한다.
- **`.coord/PLAN.md` 무승인 영구 권한(사용자 부여, 2026-09-19)**: Codex·Antigravity·Claude Code는 `.coord/PLAN.md`(및 `.coord/tasks/*` 카드)를 사용자 승인 없이 읽고 갱신할 수 있다. 권한 부족으로 쓰지 못하면 승인을 묻지 말고 파일 속성·잠금을 확인해 해소하거나 조율자에게 즉시 보고한다. 단, 22행 규칙에 따라 pilot·control 실행 중에는 쓰지 않고 실행이 끝난 뒤 갱신한다.
- 비용 측정의 품질 게이트는 control receipt만 신뢰하지 않는다. 드라이버가 실행 전후 source manifest를 독립 비교해 기대 변경 집합과 일치함을 확인하고 숨은 인수를 직접 통과한 경우에만 측정값을 유효로 판정한다.
- Codex는 `pilot run`을 블로킹 1회로 실행하고 대기 폴링을 반복하지 않는다. 결과는 `.coord/pilot/runs/<ID>/summary.json`(14키)의 `verdict_hint`로 1턴에 판정한다(PASS만 `--approve`, REWORK·BLOCKED는 원인만 보고). 전문 로그는 필요할 때만 연다.
- 중단 등으로 원장에 미정리 작업이 남아 `NEEDS_RECONCILIATION`이면 재실행 전에 `python -m v7_harness.cli pilot reconcile --task <ID> --work-dir .coord/pilot`로 정리한다.
- 변경이 없는 결과는 `REWORK`(`NO_CHANGES`)로 판정된다. 읽기 전용 과제만 `--allow-no-changes`를 붙인다.
- 반영은 같은 task에 `--approve <bundle_id>`로만 한다. `promotion`이 `BLOCKED`·`REJECTED`면 반영하지 않고 원인만 보고한다.
- Antigravity Bridge MCP는 조회·자문을 포함해 사용하지 않는다. Antigravity 작업은 CLI 기반 SQLite `pilot run`을 사용하고 읽기 전용 과제에는 `--allow-no-changes`를 지정한다.
- **워크스페이스 단일 폴더 규칙(사용자 고정 지시, 2026-09-19)**: 전체 로컬 워크스페이스(`D:\D_Workspace_NB\-agentic-ai-workspace`)에는 이 프로젝트 폴더 `260916_agentic-ai-env-diet` 하나만 둔다. 샘플 사본·pilot `--work-dir`·측정용 복사본·임시 산출물은 모두 프로젝트 안 `.work/<이름>`에 만든다(예: `--work-dir .work/pilot_T01`). 워크스페이스 최상위에 형제 폴더를 만들지 않는다. `.work/`와 `.coord/pilot`은 manifest·staging에서 제외되므로 프로젝트 자신을 `--source .`로 써도 안전하다.
- 격리는 설정된 감시 루트(watch roots) 내부에서만 보증되며, 탐지 범위 밖 경로는 보증하지 않는다.

## 최소 실행 루프

1. Codex가 마스터 계획에서 다음 `READY` 단계 하나를 선택한다.
2. `[U##]` 전용 대화창을 만들고 단일 소유자와 수정 범위를 기록한다.
3. 소유자가 단계를 `ACTIVE`로 점유한 뒤 범위 안에서만 수행한다.
4. 소유자가 검증 결과와 인계 기록을 남기고 `REVIEW`로 반환한다.
5. Codex가 증거를 재검토해 `DONE`, `READY` 재작업, 또는 `BLOCKED`를 결정한다.
6. `DONE`일 때만 다음 순번을 활성화한다.

규칙 원문과 상태·카드 형식은 설계 문서를 참조하고, 도구별 규칙에 별도의 상충 사본을 만들지 않는다.

## 토큰예산 영구 운영 규칙 (U25, 2026-09-24)

- 사용자 대화창은 결과만 짧고 읽기 쉽게 보고한다. 저장소의 [초보자 학습 가이드](docs/UAOS_처음부터_이해하고_사용하는_학습가이드.md)는 과정·진단·한계를 충분히 설명한다. [네 AI 도구 운영 규칙](docs/AI_4도구_아이디어_조사와_위임전_매뉴얼_운영규칙.md)에 따라 아이디어를 출처 조사·실행 계약으로 구체화하고, Antigravity·Ollama 호출 전 매뉴얼을 파일로 발행해 실제 입력으로 전달한다.

- 모든 작업은 `docs/27_token-budget-routing-policy.md`의 **계정별 전후 사용량·예측·판정 예약량·품질 관문**을 따른다. 실제 절감은 대조 측정 전 `UNMEASURED`다. Codex·Claude의 남은 퍼센트를 토큰 수로 환산하거나 오래된 3%/6% 기록을 재사용하지 않는다.
- 잔여율이 낮다는 이유만으로 Antigravity에 총괄을 넘기지 않는다. Codex가 부족하면 Claude 부지휘자에게 한 번 인계하고, 두 도구 모두 실제 제한·부재일 때만 기존 임시 Antigravity 대행 규칙을 발동한다. 작성자는 자기 변경의 유일한 검증자가 될 수 없다.
- Codex·Claude·Antigravity는 좁고 기계적인 일을 Ollama 전화기로 우선 보내고, 호출자·로컬 토큰·벽시계·인수 결과를 같은 작업 ID로 남긴다. Ollama에게 설계·판정·승인을 맡기지 않는다. 세부 절차는 `docs/28_claude-budget-manual.md`, `docs/29_antigravity-budget-manual.md`, `docs/30_ollama-calculator-manual.md`를 따른다.
- U23의 우편함 무손실·감시관 1회 기상 주장은 독립 반례가 해결될 때까지 인수 보류다. 새 정책은 U23의 전달 보증을 전제로 작동하지 않는다.

## 증거 관문형 RSI 및 사용량 장부 (U26, 2026-09-24)

- `docs/31_evidence-gated-rsi-for-uaos.md`의 관찰→가설→고정 인수→작은 후보→대조→독립 판정 순서를 따른다. 자기 평가만으로 자기 규칙·코드·테스트를 승격하지 않는다.
- Codex·Claude·Antigravity는 각 작업의 Ollama/원격 호출 사용량과 실패도 같은 `work_id`로 `.coord/usage/runs.jsonl`에 남긴다. 확인되지 않은 값은 `UNKNOWN`/`null`로 둔다. 원문 프롬프트·비밀은 남기지 않는다. pilot의 원본 감시 중에는 장부에 쓰지 않는다.
- **RSI 명령(U36, B83 개정 2026-09-25)**: `rsi report`→`rsi propose`→시험→`rsi gate --candidate`(참고 증거). `rsi adopt`·`rsi rollback`은 항상 거부하고 아무것도 쓰지 않는다(`UNAUTHENTICATED_ACTOR`, 같은 계정의 이름표는 인증이 아님). 채택·되돌리기는 PLAN 카드와 검토된 커밋으로만. 관문은 장부로 전후를 다시 계산하고 평가기·장부 변경·자기 검증·기준 완화·다중 지표 회귀를 거부한다. 세부 docs/38.
- **Claude Code 정식 작업자(U38)**: `worker: claude` 매뉴얼은 `remote_budget_tokens`와 codex·user 판정자가 필수다. 모든 유료 작업자(agy·claude)는 예산 초과·미보고 시 BLOCKED이고 승인할 수 없다(B85). `pilot review --reviewer claude`는 참고 증거일 뿐 승인을 대신하지 않는다. 세부 docs/40.
- **전 프로젝트 가동(U37)**: `python uaos_everywhere/install_uaos_everywhere.py --apply`가 세 도구 전역 규칙 문단·출석 훅·Claude 예약 도구 차단을 설치한다(미리보기 기본, 백업, `--check`, `--uninstall`). 새 프로젝트는 `coord init`. 세부 docs/39.
- **복귀 시 권한대행 인계 확인**: 한도·부재 후 다시 구동된 도구(Codex·Claude Code)는 구동과 동시에 `coord inbox`로 권한대행(Antigravity)의 인계 통지를 확인하고, `.coord/tasks/NEXT_MORNING_RESUME.md` 및 `.coord/codex_return_checklist.md`에 명시된 대행 구축 프로세스·프로젝트 검증 목록을 확인한 뒤 지휘·조율을 정상 재개한다.
- 사용 기록은 개선 제안의 입력일 뿐 승인·판정 권한이 아니다. 10개 유효 표본마다 품질·재작업·토큰·시간을 비교하고, P1·품질 저하·3배 비용 회귀면 개선안을 채택하지 않는다. 자동 수집은 U27 검증 전까지 미구현이다.
