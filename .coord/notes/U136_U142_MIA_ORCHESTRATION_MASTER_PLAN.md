# [U136~U142] 3대 도구 상시 양방향 연동 및 MIA 복귀/근거수집/Ollama우선 총괄 마스터 설계서

- 발행일시: 2026-10-03 (사용자 MIA 전략절차 긴급 지시 반영)
- 주관: Antigravity (실행자·검증자) & Codex (정식 지휘자)
- 대상 도구: Codex (Conductor), Claude Code (Deputy, 현재 LIMITED 20:10까지 정지), Antigravity (Executor/Auditor), Ollama (Local Calculator)

---

## 1. 배경 및 문제 진단 (MIA Frame)

### 1.1 최근 발견된 근본 결함
1. **3대 도구 양방향 연결의 불안정성 (U134 결함 4건 및 U134-R 잔여)**:
   - 타 프로젝트 대화로의 편지 오배송 위험 (`F1: thread identity` 미완료).
   - 프로세스 중단 시 큐에 편지가 묶여 유실되는 결함 (`F2: queue recovery` 미완료).
   - 단순 ACK 및 무변화 알림이 유료 세션을 반복 기상시켜 토큰을 소진시키는 낭비 (`U141 A·B·C` 미완료).
2. **도구별 복귀 로직 부재 (U136)**:
   - 사용제한(Quota limit) 해제 후 복귀 시 즉시 출석 전파 미비.
   - Codex 복귀 시 지휘권이 급작스럽게 전환되거나 충돌하여 이전 작업 데이터 누락 발생 위험.
3. **착수 시 근거자료 수집 강제성 부재 (U137)**:
   - 카드가 열릴 때 6대 근거자료(원문, 실패 영수증, 기존 테스트 상태, 유사 사례, 제약사항, 복구안)를 체계적으로 수집하지 않고 직행하는 문제.
4. **Ollama 최우선 사용 로직의 허점 (U138)**:
   - `calculator_gate`가 단순히 "Ollama 호출 횟수(input_tokens > 0)"만 확인하여, 순서 자체(명세 -> Ollama 로컬 시도 -> 실패 영수증 확인 후 유료 승격)를 엄격히 강제하지 못함.
5. **도구 간 설정 비대칭 (U142)**:
   - 질문 금지, 거부 관문 등이 Claude에만 편중되어 있거나 Antigravity/Codex 설정과 어긋남.

---

## 2. 해결 아키텍처 및 세부 설계 (MIA Review & Plan)

### 2.1 [U134-R 잔여] 양방향 통신 무손실 안정화
- **F1 (스레드 소유권 식별)**: `v7_harness/coord/deliver.py`에서 편지 발송 대상 스레드가 현재 프로젝트 소유인지 검증 (`verify_thread_project`). 타 프로젝트 세션으로의 누출 차단.
- **F2 (큐 고착 복구)**: `v7_harness/coord/mailbox.py`에 고착된 편지(.taking 상태에서 프로세스 사망) 자동 복구 타이머 및 원자적 재배포 메커니즘 확립.
- **F5 (ACL 보안 격리)**: 파일 접근 권한 검증 분리.

### 2.2 [U141 A·B·C] 무의미한 세션 기상 차단 (토큰 누수 방지)
- **A (무알림 분리)**: `verdict_requested=no` 및 `ACK_ONLY` 편지는 우편함 적재만 수행하고 대화 세션을 깨우지 않음.
- **B (배치 릴레이)**: 단일 카드의 진행 과정 중 발생하는 상태 변경은 세션 제목(`session_title`)으로만 갱신.
- **C (P1/판정 전용 기상)**: 오직 `ACTIONABLE_DELTA` 및 판정 요구(`verdict_requested=yes`)만 지휘자 세션을 1회 기상.

### 2.3 [U139] 3도구 실시간 진행 현황판
- 각 도구 세션 목록에 현재 진행 상태 실시간 동기화 (예: `[U134] 3/4 실행 Ollama L2`).
- `.coord/status.json`을 단일 원본으로 하여 3도구 공통 CLI 및 UI 현황판 제공.

### 2.4 [U140] 윈도우 로그인 시 3도구 CLI 자동 출석
- 윈도우 시작/로그인 시 Task Scheduler를 통해 3도구 CLI 출석(`uaos coord presence --tool <tool> --state ACTIVE`) 자동 실행.
- 앱 실행 여부와 무관하게 시스템 수준에서 에이전트 활성 상태 감지.

### 2.5 [U136] 도구별 맞춤형 복귀 프로토콜 (Gradual Conductor Handover)
- **Codex 복귀 프로토콜 (지휘권 3단계 이양)**:
  1. `1단계 (인계 확인, ACK)`: Codex가 켜지면 Antigravity가 진행 중인 전체 현황, 열린 카드, 미해결 위험을 패킷으로 인계. Codex는 이를 읽고 ACK 발송. (Antigravity 대행 유지)
  2. `2단계 (관찰 및 부분 승인)`: Codex가 인계된 내역을 검토하고 부분 승인 및 수정 지시를 내림. (Antigravity는 지휘자의 지시 하에 작업 수행)
  3. `3단계 (완전 지휘권 회복)`: 모든 인계 항목이 정리되면 Codex가 공식 Conductor로 복귀 완료 선언.
- **Claude 복귀 프로토콜**:
  - 부관/부지휘자 역할 복귀 -> 대기 중인 파일럿/검토 과제 인수.
- **Antigravity 복귀 프로토콜**:
  - 실행자/독립검증자 복귀 -> 대기 중인 계약 매뉴얼 수신.

### 2.6 [U137] 프로젝트 착수 시 6대 근거자료 수집 의무화
- `uaos card new` 시 6대 근거 수집 슬롯 자동 생성:
  1. 원문 요구사항 (User Request Citation)
  2. 실패/필요 영수증 (Failure Receipt / Ledger Trace)
  3. 기존 코드 및 테스트 상태 (Baseline State)
  4. 대안 및 선행 연구 (Alternatives & Research)
  5. 제약사항 및 위험 요소 (Constraints & Risks)
  6. 롤백 및 복구 계획 (Rollback & Recovery Plan)
- 위 6대 항목이 채워지지 않은 카드는 `card audit`에서 진행 거부 (`EVIDENCE_MISSING`).

### 2.7 [U138] Ollama 최우선 순서 강제 (Order-Enforced Calculator Gate)
- 순서 파이프라인 강제: `[명세/매뉴얼 발행] -> [Ollama 로컬 파일럿 1차 시도] -> [실패 영수증(input_tokens > 0) 검증] -> [유료 모델/Antigravity 승격 허용]`.
- Ollama 시도 영수증 없이 유료 모델이나 apply로 직행하는 커밋은 `calculator_gate`에서 원천 차단.

### 2.8 [U142] 3대 도구 공통 운영 규칙 및 질문 금지 표준화
- 질문 금지(Safety 사람 목록 외 무승인 논스톱 완결)를 Claude뿐 아니라 Codex, Antigravity 전역 어댑터에 완벽 동기화.

---

## 3. 실행 파이프라인 및 순서 (Roadmap)

1. **Phase 1: 통신 및 토큰 안정화**
   - `U134-R` (F1 thread identity, F2 queue recovery)
   - `U141 A·B·C` (불필요 알림 세션 기상 차단)
2. **Phase 2: 가시성 및 출석 체계**
   - `U139` (진행 현황판)
   - `U140` (윈도우 로그인 CLI 출석)
3. **Phase 3: 거버넌스 및 규칙 하드게이트**
   - `U136` (도구별 차별화 복귀 프로토콜: Codex 점진 지휘권 이양)
   - `U137` (착수 시 6대 근거 수집 강제)
   - `U138` (Ollama 선행 순서 강제)
   - `U142` (3도구 공통 무승인 규칙 표준화)

---

## 4. 무승인 논스톱 2도구(Codex-Antigravity) 협업 수칙
- Claude 부재(LIMITED, 20:10까지) 중 Codex(지휘자)와 Antigravity(실행자)가 1:1로 직결 진행.
- 모든 진행은 디스크 우편함(`coord deliver`)을 통해 데이터 누락 없이 무손실로 인계.
- Safety 사람 전용 목록(삭제, 푸시, 결제 등) 외에는 사용자 질문 없이 논스톱 완결.
