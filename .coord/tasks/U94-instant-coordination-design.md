# [U94] MIA 전략절차: 3대 AI 에이전트 간 즉시 통신 및 지연 해소 설계서 (Decision Memo)

- 상태: PROPOSAL (Codex 부재 중 Claude 대행 협의안)
- 작성자: Antigravity (MIA 전략절차 가설검증 스킬 발동)
- 일자: 2026-09-30
- 대상: `v7_harness/coord/watch.py`, `v7_harness/coord/deliver.py`, `v7_harness/coord/presence.py`

---

## 1. 기획 (Frame)

### 1.1 현상 및 측정된 병목 (Observable Problem)
1. **디스크 감시자 30초 고정 폴링 지연**:
   - `v7_harness/coord/watch.py`의 `DEFAULT_INTERVAL_S = 30.0`초로 인해, 상대 에이전트가 편지를 발행해도 감시자가 이를 감지하고 프로세스를 반환할 때까지 **최대 30초의 데드타임** 발생.
2. **Cold Headless CLI 기동 오버헤드**:
   - `coord deliver`가 대화형 세션 부재 시 `claude -p`를 신규 서브프로세스로 기동. 프로세스 초기화, 토큰 사전 로딩, API 왕복으로 인해 **단일 호출당 20~60초 소요**.
3. **수신 타깃 비대칭 (Antigravity Direct Push 부재)**:
   - `coord deliver`의 `--target`이 `{codex, claude}`만 허용되어, Antigravity는 능동적 턴을 시작하지 않는 한 사서함 적체를 인지할 수 없음.
4. **Codex 부재 시 하드 거부 및 고립**:
   - Codex 한도 소진 시 `codex queue` 전송이 원천 차단(`CODEX_ABSENT`)되며, 지휘권 대행 전환 인지가 지연되면 작업이 중단됨.

### 1.2 목표 성과 지표 (Measurable Success Signals)
- **신호 감지 레이턴시**: 편지 파일 도착 후 감시자 기상까지 **30.0초 → 0.5초 이내**로 단축 (-98%).
- **토큰 소모**: 대기 및 감시 과정에서 유료 API 토큰 **0개(Zero Paid Tokens)** 불변식 유지.
- **안전성 및 가역성**: 실시간 신호 전달 실패 시 기존 원자적 파일 사서함(`.coord/mailbox/inbox`)으로 자동 롤백 (100% 무손실).

### 1.3 Non-Goals
- 외부 클라우드 메시징(Redis, AWS SQS, Pusher 등) 도입 금지 (오프라인 로컬 환경 원칙).
- 유료 모델을 활용한 주기적 폴링(cron) 루프 일체 금지.

---

## 2. 검토 (Review): 3대 대안 비교 분석

| 평가 기준 | 대안 1: OS 커널 디렉터리 변경 알림 (`ReadDirectoryChangesW`) | 대안 2: 하이브리드 IPC 신호 (`Named Pipe` / `Local Socket`) + 페이로드 디스크 보존 | 대안 3: 로컬 Ollama 센티넬 HTTP/SSE 데몬 상주 |
|---|---|---|---|
| **동작 원리** | `.coord/mailbox/inbox/` 폴더를 Windows 커널 API로 블로킹 감시 | 0원 로컬 소켓/파이프로 1바이트 핑(Ping) 즉시 발송, 본문은 사서함에서 읽기 | 백그라운드 Python/Ollama 서버가 SSE/WebSocket으로 브로드캐스트 |
| **Value (가치성)** | 폴링 주기 30초를 0.1초 이벤트 반응형으로 즉시 단축 | 에이전트 간 왕복 시간(RTT)을 서브초(<100ms) 단위로 단축 | 풍부한 이벤트 필터링 및 중앙 대시보드 제공 가능 |
| **Feasibility (실현가능성)** | **최고 (Go)**: 외부 라이브러리 없이 `ctypes` 또는 `win32file`로 즉시 구현 가능 | **높음 (Go)**: 표준 라이브러리(`socket`, `asyncio`)만으로 구현 가능 | **보통 (Pivot)**: 상주 데몬 관리, 포트 충돌, 프로세스 수명 주기 복잡성 |
| **Viability (지속가능성)** | 파일 사서함 체계와 100% 호환, CPU 사용률 0%에 수렴 | 기존 `coord deliver`와 `coord watch`의 드롭인(Drop-in) 보강 | 시스템 리소스(RAM/포트) 점유 및 비정상 종료 시 고착 위험 |
| **Risk (위험도)** | 윈도우 OS 의존성 (리눅스는 inotify 분기 필요) | 소켓 포트 충돌, 방화벽 팝업 위험 (Named Pipe는 윈도우 한정) | 데몬 다운 시 메시지 유실 위험, C3P/트리니티의 브로커 실패 재발 위험 |
| **Decision** | **Go (즉시 1단계 채택)** | **Go (2단계 고속화 채택)** | **No-Go (기각: 상주 브로커의 과거 실패 재현)** |

---

## 3. 실행 (Execute): 2단계 점진적 구현 설계

### 제1단계: `coord watch`의 커널 이벤트 감시자 도입 (즉시 적용)
1. **수정 대상**: `v7_harness/coord/watch.py`
2. **핵심 로직**:
   - 기존의 `time.sleep(30.0)` 루프를 Windows `ReadDirectoryChangesW` (또는 `ctypes.windll.kernel32`) 기반 비차단 이벤트 대기로 대체.
   - 새 파일 생성(`FILE_ACTION_ADDED`) 또는 이름 변경(`FILE_ACTION_RENAMED_NEW_NAME`) 이벤트 발생 시 즉시 디렉터리 스캔을 트리거하여 0.2초 이내 루프 탈출.
   - 커널 이벤트 지원 실패 시 기존 `time.sleep(2.0)`(폴링 간격 30초 -> 2초 축소)으로 안전한 폴백(Graceful Degradation).

### 제2단계: Signal-on-Local-Pipe, Payload-on-Disk 아키텍처
1. **수정 대상**: `v7_harness/coord/deliver.py` & `v7_harness/coord/watch.py`
2. **핵심 로직**:
   - `coord deliver`가 사서함에 JSON을 원자적으로 쓴 직후, 로컬 네임드 파이프(`\\.\pipe\uaos_coord_<tool>`)로 1바이트 펄스(`b"!"`) 전송.
   - 활성 감시자(`coord watch`)는 파이프 신호를 수신하는 즉시 exit 0으로 종료되어 상위 에이전트 턴을 10ms 이내에 즉각 깨움.
   - 파이프가 없거나 연결 거부(`FileNotFoundError`)되면, 디스크 사서함에 정상 기록된 상태이므로 제1단계 커널 이벤트 감시자가 즉각 백업 수신.

---

## 4. 검증 (Verify): 합격 관문 (Acceptance Gate)

1. **지연 시간 검증**:
   - `tests/test_instant_watch.py` 작성: 임의 메시지 발행 시 `coord watch`가 1.0초 이내에 종료되는지 측정.
2. **무손실 회귀 검증**:
   - 기존 회귀 스위트(`run_regression.py`) 전체 통과.
   - 파이프가 강제 중단되거나 커널 이벤트가 유실되어도 최대 2초 이내에 디스크 사서함 백업 스캔으로 편지가 처리되는지 확인.
