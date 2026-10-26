# 3대 벤치마킹 저장소(`OpenRig` · `AgentCodeGUI` · `REA`) UAOS-RSI 로직 선별 및 이식 설계서 (MIA 11단계 전략절차)

- **문서 번호**: `docs/94` (2026-10-26 정밀 선별·계산·이식 마스터 설계서)
- **작성 도구**: Antigravity (MIA 전략절차 11단계 프레임워크 발동)
- **대상 환경**: UAOS-RSI (**Codex · Claude Code · Antigravity 3대 도구 티키타카 무승인 논스톱-병렬-협업 멀티 에이전트 오케스트레이터** + **Ollama 0토큰 로컬 계산기**)
- **참조·벤치마킹 자료실 경로 (`U250` 전역 규칙)**:
  - [`D:\D_Workspace_NB\-agentic-ai-workspace\260916_agentic-ai-env-diet\.work\library\openrig`](file:///d:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/.work/library/openrig) (`fecffdc6`, 3,871 files)
  - [`D:\D_Workspace_NB\-agentic-ai-workspace\260916_agentic-ai-env-diet\.work\library\AgentCodeGUI`](file:///d:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/.work/library/AgentCodeGUI) (`c4dd55e`, 2,365 files)
  - [`D:\D_Workspace_NB\-agentic-ai-workspace\260916_agentic-ai-env-diet\.work\library\rea`](file:///d:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/.work/library/rea) (`1173c0a9d`, v6.8.0, 6,324 files)
- **1차 출처 필수 근거 링크 (Evidence Citation Invariant)**:
  - **OpenRig GitHub**: https://github.com/mvschwarz/openrig
  - **Show GN / AgentCodeGUI GitHub**: https://github.com/UnrealFactory/AgentCodeGUI
  - **REA GitHub**: https://github.com/morluto/rea
  - **REA 분석 기사 (ZDNet Korea)**: https://zdnet.co.kr/view/?no=20261019165618

---

## Stage 0. 사전 근거자료조사 (`.work/library` 3대 저장소 원문 대조)

| 벤치마킹 대상 | 원문 핵심 구조 (Observed Facts) | UAOS-RSI(3대 도구 Windows 네이티브 병렬 환경)와의 차이 |
|---|---|---|
| **1. OpenRig**<br>(`mvschwarz/openrig`) | - `rig.yaml`로 에이전트 팀(`Seat`, `Pod`, `Kernel Operator`, `Advisor`)을 선언적으로 정의<br>- `Seat` 테이블이 `runtime`, `model`, `context`, `state`를 실시간 추적<br>- `workshop` 번들의 **Non-interruptive mode**로 승인 프롬프트 병목 제거 | - OpenRig는 **Claude Code + Codex 2대 도구**만 지원하며 **macOS/Linux/WSL2 + `tmux`**에 강결합(네이티브 Windows 미지원)<br>- UAOS는 **Windows 네이티브 3대 도구(Codex·Claude·Antigravity) + Ollama 계산기** 구조 |
| **2. Show GN**<br>(`UnrealFactory/AgentCodeGUI`) | - **최대 6패널 동시 실행** 및 작업 바 **5대 상시 칩(`할 일`, `서브에이전트`, `백그라운드 셸`, `변경 파일/Diff-in-Place`, `컨텍스트·5시간/주간 한도 게이지`)**<br>- **한도 소진 시 계정/모델 전환 및 초기화 시각(`reset_at`) 자동 재개**<br>- 턴 진행 중 입력 메시지 **예약 큐(Auto-dequeue)** 및 인플레이스 계획 승인 카드 | - AgentCodeGUI는 **Claude + Codex 2엔진 데스크톱 GUI**로 사람이 패널을 직접 클릭·조작하는 구조<br>- UAOS는 **사람 개입 없이 3대 도구가 우편함·파일·훅으로 자율 티키타카**하는 무승인 논스톱 오케스트레이터 |
| **3. REA**<br>(`morluto/rea` v6.8.0) | - **50+ MCP 도구 & 131개 계약 모듈**로 Ghidra/IDA/Hopper/JADX/AST/SQLite를 단일 인터페이스로 통합<br>- **`AGENTS.md` 핵심 원칙**: ① `OBSERVED`/`DERIVED`/`INFERRED`/`UNKNOWN` 4계층 분리, ② 단방향 내부 의존성(`domain` ← `adapter` ← `workflow`), ③ 토큰 최우선 최적화(요약·페이징·증거 보존), ④ 프로세스 가족 생명주기 종료 검증, ⑤ 차등 오라클 검증(`verify_reconstruction`) | - REA 전체 MCP(50+ 바이너리 디컴파일러 도구)를 매 턴 상시 로딩하면 **고정 컨텍스트가 호출당 ~12,000~18,000 토큰 증가**하여 UAOS의 제1원칙(`Token-thrift`)과 충돌 |

---

## Stage 1~4. 기획 · 검증 · 큰계획 (3대 프로젝트별 선별·버림·변환 매트릭스)

### 1. OpenRig에서 UAOS-RSI(3대 도구 오케스트레이터)로 도입·이식할 로직
- **채택·변환 (Adopt & Transform)**:
  1. **`O-1` 3대 도구 선언적 Seat·Pod 레지스트리 (`Seat Table` 이식)**:
     - OpenRig의 `Seat(runtime, model, context, state, address)` 개념을 UAOS 3대 도구(`Codex` 지휘·판정석, `Claude Code` 부지휘·구현석, `Antigravity` 정밀실행·감사·창구석 + `Ollama` 0토큰 계산석)의 실시간 좌석표(`.coord/master_schedule.json` + `presence`)로 정식화.
  2. **`O-2` Non-Interruptive 자율 티키타카 권한 경계 (`workshop` 모드 변형)**:
     - OpenRig가 `workshop` 번들로 비생산적 승인 대기를 제거하듯, UAOS는 **Safety 사람 전용 목록(삭제·원격 main 푸시·배포·결제·권한 변경)** 외 모든 단계(코드 작성·교차 리뷰·기능 브랜치 푸시·런타임 배포·다음 카드 착수)를 3대 도구가 무승인 논스톱으로 직행.
- **기각 (Reject)**:
  - `tmux` 세션/창 강제 의존성 및 WSL2 전용 셸 래퍼 (Windows 네이티브 `coord window` 및 `.coord/mailbox`가 더 가볍고 0토큰으로 동작).

### 2. Show GN (AgentCodeGUI)에서 UAOS-RSI(3대 도구 오케스트레이터)로 도입·이식할 로직
- **채택·변환 (Adopt & Transform)**:
  1. **`G-1` 5대 핵심 칩(5-Chip Status Bar) 기반 관제 스냅샷 및 인플레이스 Diff 증거 (`control_ux.py` 확장)**:
     - AgentCodeGUI의 작업 바 5칩(`할 일/스케줄`, `3대 도구/서브에이전트 좌석`, `백그라운드 감시/셸`, `변경 파일 +/- 줄수 Diff`, `도구별 한도/컨텍스트 상태`)을 UAOS 컨트롤 UX 스냅샷(`v7_harness/coord/control_ux.py`) 및 카드 완료 번들(`.coord/results/<card>.md`)의 표준 5대 계기판 항목으로 채택.
  2. **`G-2` 한도 소진 즉시 우회 및 초기화 시각(`reset_at`) 기반 자동 복귀·재개 (`U249 failover_closeout.py` 결합)**:
     - AgentCodeGUI의 「한도 소진 시 타 계정/엔진 전환 + 초기화 시각 자동 재개」를 **3대 도구 티키타카 버전**으로 승격:
       - 3도구 중 1도구 `LIMITED` → **남은 2도구가 즉시 스케줄 재편(`TWO_TOOL_CONTINUITY`)**.
       - 2도구 `LIMITED` → **유일 생존 1도구가 단독 자율 완결(`SOLE_SURVIVOR_AUTONOMOUS`)** 후 복귀 도구의 `reset_at` 시점에 `needs_return_review` 큐를 자동 트리거.
  3. **`G-3` 비백그라운드 전면 대기 5초 선점 및 예약 작업 즉시 디큐 (`preempt_foreground_wait`)**:
     - AgentCodeGUI가 턴 중 도착한 메시지를 큐에 쌓고 즉시 처리하듯, UAOS는 백그라운드 감시(`coord watch`)가 아닌 **전면 대기가 5.0초(`FOREGROUND_WAIT_LIMIT_S = 5.0`)를 초과하면 즉시 전수 검토 후 다음 `READY` 카드를 선점**하거나 전 단계 완료 시 자연 종료(`SCHEDULE-CLOSEOUT`).
- **기각 (Reject)**:
  - 무거운 Rust/Tauri 상시 데스크톱 프로세스 및 수동 클릭형 질문/계획 승인 모달 (UAOS는 무승인 자율 티키타카 + 정적 HTML 관제 허브로 유료 토큰·메모리 소모 0 유지).

### 3. REA (Reverse Engineer Anything)는 UAOS-RSI의 '기본 분석로직'으로 삼을 만한가? (정량 계산 및 도입 결정)

#### (1) 정량 비용·효용 계산 (Quantitative Cost-Benefit Calculation)
- **가설 A (REA 전체 50+ MCP 도구를 UAOS 기본 분석로직으로 상시 탑재)**:
  - REA의 131개 계약 및 50+ MCP 도구 스키마를 3대 도구 세션에 기본(Always-on) 탑재할 경우:
    $$\text{고정 스키마 비용} \approx 50\text{ tools} \times 280\text{ tokens/tool} = 14,000\text{ paid tokens / call}$$
  - 카드 1개당 평균 15회 유료 호출 시 **카드당 약 210,000 유료 토큰이 스키마 재읽기로 낭비**됨 (`cost ≈ calls × context` 위반). 더욱이 일반 파이썬/TS 소스코드가 이미 존재하는 작업의 90%에서는 Ghidra/IDA/JADX 바이너리 역어셈블러가 불필요함. → **가설 A 기각 (No-Go)**.
- **가설 B (2계층 분리 도입: [Tier 1] REA의 '인식론적 분석·토큰 최적화 엔진'은 UAOS 기본 분석로직으로 영구 채택 + [Tier 2] '정적 역설계 브리지'는 조건부 호출 모듈로 탑재)**:
  - **Tier 1 (UAOS 기본 분석로직으로 전면 채택 — 고정 스키마 추가 비용 0 토큰)**:
    1. **4계층 증거 분리 (`OBSERVED` / `DERIVED` / `INFERRED` / `UNKNOWN`) + 1차 출처(기사·GitHub) 필수 관문 (`v7_harness/evidence_ledger.py`)**: 모든 MIA 0단계 리서치, 버그 진단, 코드 감사에서 관측 사실과 추론·미지수를 분리하고 `UNKNOWN` 해소 이력을 추적하는 것을 **UAOS-RSI의 기본 분석 표준**으로 삼음.
    2. **Summary-First 요약 우선 반환 + 페이지네이션/필드 투영 (`v7_harness/analysis_view.py`)**: 대용량 파일·로그·벤치마킹 저장소 분석 시 전체 본문을 유료 컨텍스트에 붓지 않고, `parent_evidence_id`가 달린 요약본을 먼저 반환한 뒤 필요한 `offset`/`limit`/`fields`만 슬라이스 조회(`source_complete` vs `page_exhausted` 분리) — **호출당 분석 토큰 75~90% 절감**.
    3. **경계 1회 정규화 및 단방향 의존성 (`AGENTS.md` §Architecture)**: 원시 데이터 파싱은 경계(결정론적 파서 또는 `olla` 계산기)에서 단 한 번 수행하고, 상위 3대 도구는 정규화된 구조체만 소비.
    4. **유한 의무 차등 검증 및 2단계 프로세스 종료 (`v7_harness/process_supervisor.py`)**: 리팩터링·이식 전후 입출력 동치성을 `verify_reconstruction`으로 검증하고, 하위 프로세스는 `SIGTERM → finalization_ms → SIGKILL`로 고아 프로세스 없이 정리.
  - **Tier 2 (조건부 정적 역설계 어댑터 — `v7_harness/rea_bridge.py`)**:
    - 외부 참조 저장소(`.work/library/<repo>`), 서드파티 패키지(ASAR/번들), SQLite WAL/스키마, 또는 소스 없는 아티팩트를 분석할 때만 `inspect_static_target`(`STATIC_ONLY` 강제) 및 `generate_contract_manual_from_rea`를 온디맨드로 호출. → **가설 B 최종 채택 (Go)**.

---

## Stage 5~10. 세부 구현 매핑 및 검증 현황 (`U245`~`U250` 실측 대조)

| 이식 ID | 출처 프로젝트 | 선별된 핵심 로직 | UAOS-RSI 구현·장착 모듈 | 검증 테스트 및 상태 |
|---|---|---|---|---|
| **`U245`** | **REA** (Tier 1 기본 분석로직) | `OBSERVED`/`DERIVED`/`INFERRED`/`UNKNOWN` 4계층 원장 + 기사·GitHub 1차 출처 필수 관문 | [`v7_harness/evidence_ledger.py`](file:///d:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/v7_harness/evidence_ledger.py) | [`tests/test_u245_evidence_citation_gate.py`](file:///d:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/tests/test_u245_evidence_citation_gate.py) (`PASS`) |
| **`U246`** | **REA** (Tier 1 기본 분석로직) | Summary-First 번들 보존(`parent_evidence_id`) + `offset`/`limit`/`fields` 슬라이스 투영 | [`v7_harness/analysis_view.py`](file:///d:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/v7_harness/analysis_view.py) | [`tests/test_u246_analysis_view.py`](file:///d:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/tests/test_u246_analysis_view.py) (`PASS`) |
| **`U247`** | **REA** (Tier 2 온디맨드 브리지) | `STATIC_ONLY` 정적 타깃/SQLite 검사 및 Clean-Room 계약 매뉴얼 생성기 | [`v7_harness/rea_bridge.py`](file:///d:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/v7_harness/rea_bridge.py) | [`tests/test_u247_rea_static_bridge.py`](file:///d:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/tests/test_u247_rea_static_bridge.py) (`PASS`) |
| **`U248`** | **REA** (Tier 1 기본 검증로직) | `SIGTERM → finalization_ms → SIGKILL` 종료 감독 + 유한 오라클 동치 검증(`verify_reconstruction`) | [`v7_harness/process_supervisor.py`](file:///d:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/v7_harness/process_supervisor.py) | [`tests/test_u248_process_finalization.py`](file:///d:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/tests/test_u248_process_finalization.py) (`PASS`) |
| **`U249`** | **OpenRig + AgentCodeGUI** (3대 도구 병렬 확장) | 3→2→1 한도 소진 즉시 재계획·단독 완결(`replan_on_quota_limit`) + 5초 전면 대기 선점(`preempt_foreground_wait`) + 스케줄 자연 종료(`finalize_schedule_closeout`) | [`v7_harness/coord/failover_closeout.py`](file:///d:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/v7_harness/coord/failover_closeout.py) | [`tests/test_u249_failover_preemption_closeout.py`](file:///d:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/tests/test_u249_failover_preemption_closeout.py) (`PASS`) |
| **`U250`** | **3대 저장소 공통** (`OpenRig`·`AgentCodeGUI`·`REA`) | `.work/library/<repo>` 단일 경로 읽기 전용 격리·검증·`README.md` 자동 색인 | [`v7_harness/library_store.py`](file:///d:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/v7_harness/library_store.py) | [`tests/test_u250_reference_library_rule.py`](file:///d:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/tests/test_u250_reference_library_rule.py) (`PASS`) |

---

## 부록: "REA 본래 역설계 로직 온디맨드(On-Demand)"의 정확한 뜻과 전체 기능 탑재의 타당성

### 1. '온디맨드(On-Demand, 필요시 즉시 호출)'란 무슨 뜻인가?
- **기능을 삭제하거나 축소하는 것이 아닙니다.** REA의 본래 역설계 기능 전체(50+ MCP 도구, 131개 계약: `.exe`/`.dll` 네이티브 바이너리 디컴파일, Electron `app.asar` 해부, APK/JADX/C# .NET CIL 분석, 네트워크 HAR/IPC 캡처 등)는 [`.work/library/rea`](file:///d:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/.work/library/rea)와 브리지에 **100% 온전히 보유**합니다.
- **차이는 '언제 켜느냐(로딩 시점)'입니다**:
  - **상시 기본 탑재(Always-On Eager Loading)**: 파이썬 몇 줄 고치거나 문서 쓰는 일반 대화에도 50개 바이너리 역어셈블러 도구 명세서(`docs/mcp-contracts.md` 96KB)와 Ghidra/IDA 엔진을 매번 메모리에 올리는 방식.
  - **온디맨드 탑재(On-Demand / Lazy Loading)**: 평소 일반 코딩 때는 토큰 0으로 대기시켜 두었다가, **"외부 프로그램·실행파일·패키지·웹앱을 역설계해서 재현하라"는 과제가 들어오는 순간에만 해당 역설계 도구군을 즉시 깨워 100% 가동**하는 방식(Antigravity의 Lazy MCP / CLI 브리지 방식과 동일).

### 2. 본래 기능을 '상시(매 턴마다)' 다 켜두는 것은 왜 낭비인가?
1. **유료 토큰 한도 급속 소진 (`cost ≈ calls × context`)**:
   - 50+ MCP 도구 스키마를 상시(Eager) 등록하면 매 호출마다 **약 14,000 유료 토큰**이 고정 컨텍스트로 재과금됩니다(15회 호출 시 약 21만 토큰 증발).
2. **외부 무거운 디컴파일러 프로세스 부하**:
   - REA 본래 기능은 Ghidra(Java VM + 기가바이트급 분석 DB), IDA Pro, JADX, Wireshark `tshark`, GDB 등을 하위 프로세스로 구동합니다. 소스코드가 이미 우리 폴더에 있는 일반 개발 작업(전체의 ~90%)에서는 이 무거운 엔진들을 매번 띄울 이유가 없습니다.

### 3. 그렇다면 REA 본래 기능 전체는 불필요한가? → **전혀 불필요하지 않습니다 (온디맨드 무기로는 필수)**
- **결론**: **"불필요해서 버리는 것(X)"이 아니라, "아껴두었다가 역설계 타깃이 등장할 때 100% 화력으로 쓰는 특수 중화기(O)"**입니다.
- **구체적 구분**:
  - **매일 모든 작업에 쓰는 기본 분석로직 (Tier 1 상시 가동)**: REA의 **4계층 증거 분리(`OBSERVED`/`DERIVED`/`INFERRED`/`UNKNOWN`)**, **요약 우선 페이징(`analysis_view.py`)**, **입출력 오라클 동치 검증(`verify_reconstruction`)**은 토큰을 오히려 75~90% 아껴주므로 **상시 기본 로직**으로 씁니다.
  - **외부 앱·바이너리·패키지 재현 시 쓰는 본래 역설계 기능 (Tier 2 온디맨드 가동)**: 소스 없는 상용 앱(Electron/실행파일/APK/웹번들)의 기능을 분석·이식할 때는 [`.work/library/rea`](file:///d:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/.work/library/rea)의 본래 기능 전체를 CLI/Lazy 브리지로 즉시 호출하여 100% 활용합니다.
