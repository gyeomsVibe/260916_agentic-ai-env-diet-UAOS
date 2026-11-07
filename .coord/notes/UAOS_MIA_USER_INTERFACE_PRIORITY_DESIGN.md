# UAOS-RSI 사용자 컨트롤 인터페이스 계층 구조 및 3대 도구 연동 종합 설계서
**문서 ID**: `UAOS-MIA-UI-01`  
**작성일시**: 2026-10-03 (KST)  
**작성자**: Antigravity (MIA Strategic Architecture)  
**검토/판정**: Codex Conductor 협의용  

---

## 1. 기획 (Frame) — 사용자 컨트롤 인터페이스 계층 구조 전환 PRD

### 1.1 배경 및 문제 정의 (Background & Problem)
- **현재 상황**: UAOS-RSI에서 Codex가 Conductor(총괄 조율자), Claude Code가 Deputy(부관), Antigravity가 Contracted Executor/Auditor로 정의되어 있음.
- **사용자 경험 결함**: 사용자(윤겸스)와의 상호작용 접점(User Interface)이 Codex 대화창, Claude CLI, Antigravity 채팅창으로 분산되어, 사용자가 어디서 명령을 내리고 진행 상황을 한눈에 파악해야 하는지 혼선이 발생하고 메시지 누락 체감이 큼.
- **핵심 목표 (윤겸스 지시)**:
  1. **사용자 컨트롤 인터페이스(Human Touchpoint / Cockpit) 1순위 = Antigravity**.
  2. **사용자 토큰 제한/부재 시 2순위 = Claude Code**.
  3. **Claude Code도 제한/부재 시 3순위 = Codex**.
  4. 단, 백엔드 계획 조율/검증 게이트(Conductor/Judge)로서의 Codex 불변식은 훼손하지 않고 조화롭게 결합.

### 1.2 목표 성과 및 지표 (Success Metrics)
- **UI 일원화**: 윤겸스는 Antigravity 대화창 하나만으로 전체 시스템(Codex, Claude, Ollama)의 상태, 카드 진행률, 실시간 diff를 실시간 모니터링 및 제어.
- **무손실 장애 전환(Failover)**: Antigravity 토큰 소진 시 10초 이내에 Claude Code가 대화형 제어권을 인수하고, 복귀 시 100% 무손실 복구.
- **토큰 절감 극대화**: 상시 대시보드 및 초안 작성은 Ollama(0원) 및 로컬 추출 도구 우선 강제.

---

## 2. 큰계획 (Master Plan) — 아키텍처 및 계층 통신 토폴로지

### 2.1 역할 분리 원칙 (Separation of Concerns: Frontend vs Backend)
```
+---------------------------------------------------------------------------------+
|                     사용자 컨트롤 인터페이스 (Frontend / Cockpit)                  |
|  [1순위] Antigravity (풍부한 UI, 아티팩트, 대시보드, 생성형 시각화, 제어판)           |
|       │ (토큰 제한 / 부재 시 장애 전환)                                            |
|       ▼                                                                         |
|  [2순위] Claude Code (터미널 대화형 인터페이스, 빠른 diff 검토)                     |
|       │ (토큰 제한 / 부재 시 장애 전환)                                            |
|       ▼                                                                         |
|  [3순위] Codex (데스크톱 App 대화창 / 터미널 인터페이스)                             |
+---------------------------------------------------------------------------------+
                                      ▲  양방향 연동 (coord deliver / mailbox)
                                      ▼
+---------------------------------------------------------------------------------+
|                      운영체제 코어 및 지휘/검증 (Backend / Conductor)              |
|  [상시 지휘/게이트] Codex (마스터 플랜 수호, 고정 인수 테스트 판정, 브랜치 병합 관문)    |
|  [무료 계산기]     Ollama (요약, 맵, 초안, 린트, 0토큰 로컬 가속)                  |
|  [영구 원장/장부]   UAOS Mailbox / Ledger / RSI Usage Records (.coord/)          |
+---------------------------------------------------------------------------------+
```

### 2.2 장애 전환(Failover) 매트릭스
| 상태 시나리오 | 사용자 컨트롤 인터페이스 (UI) | 백엔드 지휘자 (Conductor) | 실행/작업자 (Workers) |
|---|---|---|---|
| **정상 상태 (Normal)** | **Antigravity (1순위)** | Codex (ACTIVE) | Ollama, apply, agy |
| **Antigravity 한도 도달** | **Claude Code (2순위)** | Codex (ACTIVE) | Ollama, apply, claude |
| **Antigravity & Claude 한도** | **Codex (3순위)** | Codex (ACTIVE) | Ollama, apply |
| **Codex 부재 시** | **Antigravity (1순위)** | Claude Code (대행) | Ollama, apply, agy |
| **Codex & Claude 둘 다 부재** | **Antigravity (1순위)** | Antigravity (임시 총괄) | Ollama, apply, agy |

---

## 3. 중간점검 (Mid-Check) — 현재 시스템 3대 점검 결과

### 3.1 토큰예산절약 모드 (Token Thrift Mode) 검수 결과
- **판정**: **정상 가동 중 (ACTIVE & ENFORCED)**.
- **근거**:
  1. 전역 규칙 정본에 따라 `.coord/mode.json`이 존재하지 않는 기본 상태 자체가 **영구 토큰 절약 모드(Token-Thrift Default)**로 강제됨.
  2. `coord thrift --tool antigravity --remaining-percent 100` 실행 완료 (`AMPLE`, 정책 `RESEARCH_RESERVE`).
  3. 반복 루프 및 기계적 구현은 유료 LLM 대신 `worker: apply`, `pilot run --worker local` (Ollama qwen2.5-coder:7b)로 우선 배정.

### 3.2 3대 도구 통신-연결 신뢰성 검수 결과
- **판정**: **근본 결함 식별 및 U134-R F1 수정 완료, 안정화 진행 중**.
- **원인 분석**:
  1. **스레드 분기 오류**: 직전 `resolve_thread`가 동일 폴더명을 가진 다른 프로젝트의 스레드로 잘못 배달하여 메시지가 사용자 화면에 나타나지 않음 -> **`deliver.py` 단독 수정으로 엄격한 UUID 및 워크트리 역추적 검증 구현 완결 (`tests.test_u134_thread_fallback` 16/16 통과, 51개 전수 회귀 통과)**.
  2. **Codex 데스크톱 훅 대기**: Codex 훅 미허용 시 세션 출석 및 실시간 폴링이 지연되던 문제 확인 -> 사용자 승인 연계.
  3. **알림 부재**: 수신 시 시스템 사운드가 부재하여 대기 시간 증가 -> `U143` 시스템 사운드 즉시 호출(`winsound.MessageBeep`) 연계 예정.

### 3.3 RSI 오류 기록 및 학습 장부 검수 결과
- **판정**: **오류 기록 및 원장 누적 정상 작동 중 (380개 표본 축적)**.
- **RSI 보고서 실측 데이터 (`rsi report`)**:
  - 총 표본 수: 380개
  - 작업자별 현황:
    - `apply`: 257회 (통과율 90%, 결함 원인: `UNREQUESTED_DELETION` 1회)
    - `ollama`: 75회 기록, 실제 로컬 추론 197회 (499,412 토큰, 벽시계 14,617초) 정상 기록.
    - `agy`: 38회 (결함 원인: `EXTERNAL_WRITE` 5회, `SOURCE_DIVERGED` 2회 등 원인별 격리 보존).
    - `claude`: 8회 (`EXTERNAL_WRITE` 4회, `PROVIDER_ERROR` 1회 등).
  - 결론: 도구별 실패 영수증과 반복 패턴(`recurring causes`)이 RSI 장부에 오차 없이 집계되고 있음.

---

## 4. 세부계획 (Detailed Plan) — 구현 로드맵 및 프로토콜 명세

### 4.1 단계별 실행 로드맵
1. **[F1 단계: 완결] 스레드 신원 및 작업공간 검증**: `deliver.py` 6대 규칙 구현 및 51개 회귀 통과 완료.
2. **[F2 단계] OS 라이프타임 락 기반 큐 고착 복구**: 프로세스 중단 시에도 메시지 유실 없이 1회 안전 배달 보장.
3. **[U143 단계] 시스템 사운드(WinSound) 및 실시간 알림**: 편지 도착 시 Windows 기본 알림음(Ring) 1회 즉시 송출.
4. **[UI-1단계] Antigravity 1순위 컨트롤 패널 훅 설치**: Antigravity 대화창 시작 시 전체 3도구 상태 및 진행 중인 카드를 자동 렌더링.
5. **[UI-2단계] 3단계 장애 전환 릴레이 자동 라우팅**: Antigravity 부재 감지 시 Claude로 사용자 알림 및 인계 프로토콜 가동.

---

## 5. 최종점검 (Final Check) — Codex 협의 및 불변식 검증

- **안전 불변식 준수**: Safety 사람 전용 목록(삭제, 푸시, 배포, 결제, 권한 변경) 엄수.
- **단일 작성자 규칙 준수**: 소스 트리 수정은 단일 소유자 격리 수행.
- **Conductor 승인 절차**: 본 설계를 Conductor Codex에게 공식 릴레이(`coord deliver`)로 제출하여 협의 및 판정 획득.
