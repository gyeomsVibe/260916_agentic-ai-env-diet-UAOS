# Cockpit Tools (`D:\D_Program Files (x86)\Cockpit Tools`) 전수조사 및 UAOS-RSI 벤치마킹 보고서

> **조사 일시**: 2026-10-27 14:43 KST | **참조 자료실 등록(U250)**: [`.work/library/cockpit-tools`](file:///D:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/.work/library/cockpit-tools) (`acc057d`, 4,239 files)
> **1차 출처**:
> - 로컬 설치본: `D:\D_Program Files (x86)\Cockpit Tools\cockpit-tools.exe` (61.2 MB, Tauri 2 + Rust + WebView2)
> - 로컬 런타임 데이터: `C:\Users\Kimyoongyeom\.antigravity_cockpit\` (SQLite 3종 + JSON 상태 파일)
> - 공식 오픈소스 저장소: [jlcodes99/cockpit-tools](https://github.com/jlcodes99/cockpit-tools)

---

## 1. 정체 및 아키텍처 전수 해부

`D:\D_Program Files (x86)\Cockpit Tools`에 설치된 프로그램은 오픈소스 멀티 AI IDE 계정·할당량·인스턴스 통합 관리기인 **[Cockpit Tools (`jlcodes99/cockpit-tools`)](https://github.com/jlcodes99/cockpit-tools)** 입니다.

| 계층 | 구성 요소 | 실측 데이터 및 역할 |
| :--- | :--- | :--- |
| **설치 바이너리** | `D:\D_Program Files (x86)\Cockpit Tools\cockpit-tools.exe` | 61,288,960 B (Tauri 2.x Rust 백엔드 + React/TypeScript 프론트엔드), 12종 플랫폼 아이콘(`antigravity-menu.png`, `codex.svg`, `cursor-menu.png` 등) |
| **로컬 데이터 허브** | `C:\Users\Kimyoongyeom\.antigravity_cockpit\` | **3대 도구(Antigravity, Claude, Codex)의 계정·쿼터·세션 사용량을 로컬에서 0토큰으로 이미 수집 중** |
| **실측 SQLite 원장** | `codex_session_usage.sqlite` | `session_log_sync`(40개 세션 로그 파일 오프셋 추적) + `session_usage_events`(**2,164건 이벤트**, 입력 336,388,149 tok / 캐시 301,997,568 tok / 출력 1,080,132 tok 실측 저장 완료) |
| **프록시/요청 원장** | `codex_local_access_logs.sqlite`, `quota-pool-state.json` | 요청별 `input_tokens`, `cached_tokens`, `reasoning_tokens`, `latency_ms`, `error_category` 기록 스키마 보유 |
| **Rust 핵심 모듈** | [`src-tauri/src/modules/`](file:///D:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/.work/library/cockpit-tools/src-tauri/src/modules) | 총 180여 개 `.rs` 모듈 (플로팅 카드, 트레이 계기판, 쿼터 파서, 세션 증분 동기화, 원자적 파일 쓰기 등) |

---

## 2. UAOS-RSI가 즉시 흡수·이식할 수 있는 6대 핵심 기술 자산

> [!IMPORTANT]
> 앞서 질문하신 **"대시보드인가, 위젯인가?"**에 대한 완벽한 실증 해답이 바로 `Cockpit Tools`의 **3계층 UI 아키텍처(메인 대시보드 창 + Always-on-Top 플로팅 카드 위젯 + 시스템 트레이 요약)**에 구현되어 있습니다.

### ① 듀얼 하이브리드 UI: `floating_card_window.rs` (플로팅 위젯) + `tray.rs` (시스템 트레이)
- **Cockpit Tools 구조**:
  - 메인 대시보드 창이 닫혀도(`destroy_main_window_to_tray`) 백그라운드에서 살아남아 **Always-on-Top 초소형 플로팅 카드 위젯**([`floating_card_window.rs`](file:///D:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/.work/library/cockpit-tools/src-tauri/src/modules/floating_card_window.rs))과 트레이 메뉴([`tray.rs`](file:///D:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/.work/library/cockpit-tools/src-tauri/src/modules/tray.rs))로 실시간 잔여 쿼터만 노출합니다.
- **UAOS-RSI 이식 가치**:
  - 평소에는 작업 화면을 가리지 않는 **5-Chip 인라인/플로팅 HUD 위젯**으로 품질 게이트(PASS/BLOCKED)와 5h 잔여율만 보여주고, 클릭 시 상세 대시보드를 여는 구조로 직결됩니다.

### ② 0토큰 증분 로그 수집기: `codex_session_usage.sqlite` (`session_log_sync`)
- **Cockpit Tools 구조**:
  - 파일 전체를 매번 다시 읽지 않고 `file_path`, `last_modified`, `last_size`, `last_line_offset`을 SQLite에 저장해 **바이트 오프셋 이후로 추가된 줄만 0토큰으로 파싱**합니다.
  - 이미 사용자 PC의 `.antigravity_cockpit/codex_session_usage.sqlite`에 2,164건(3.36억 입력 토큰, **캐시 히트율 89.8%**)의 정확한 Codex 실측 데이터가 쌓여 있습니다.
- **UAOS-RSI 이식 가치**:
  - UAOS-RSI의 [`capacity_planner.py`](file:///D:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/v7_harness/coord/capacity_planner.py)가 `.antigravity_cockpit/codex_session_usage.sqlite`를 읽기 전용(RO)으로 연결하면, 추정치가 아닌 **100% 실측 세션 토큰·캐시 히트율**을 0토큰으로 즉시 가져올 수 있습니다.

### ③ 해시 검증형 원자적 쓰기 및 자동 복구: `atomic_write.rs`
- **Cockpit Tools 구조**:
  - [`atomic_write.rs`](file:///D:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/.work/library/cockpit-tools/src-tauri/src/modules/atomic_write.rs)의 `write_string_atomic_if_hash_matches`, `parse_json_with_auto_restore`, `quarantine_file` 함수는 멀티 프로세스 동시 접근 시 해시가 다르면 덮어쓰기를 거부하고, JSON 파싱 실패 시 `.bak` 파일에서 자동 복구합니다.
- **UAOS-RSI 이식 가치**:
  - Windows에서 3대 도구가 동시에 상태 파일이나 원장을 갱신할 때 발생하는 `WinError 32` 및 파일 깨짐을 방지하는 CAS(Compare-And-Swap) 패턴으로 [`v7_harness`](file:///D:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/v7_harness)에 즉시 이식 가능합니다.

### ④ 멀티 인스턴스 세션 가시성 복구 및 스레드 동기화: `codex_thread_sync.rs`
- **Cockpit Tools 구조**:
  - [`codex_thread_sync.rs`](file:///D:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/.work/library/cockpit-tools/src-tauri/src/modules/codex_thread_sync.rs) 및 [`codex_session_visibility_sqlite_repair.rs`](file:///D:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/.work/library/cockpit-tools/src-tauri/src/modules/codex_session_visibility_sqlite_repair.rs)는 여러 작업창/인스턴스 간에 누락된 Codex 세션 히스토리와 SQLite 인덱스를 무손실 수리·동기화합니다.
- **UAOS-RSI 이식 가치**:
  - 카드별 전용 창(`coord window --card U##`) 실행 후 사용자 총괄 창에서 세션 결과를 모아 볼 때 가시성 누락을 막는 핵심 레퍼런스입니다.

### ⑤ 쿼터 리셋 시각 기반 결정론적 기상 스케줄러: `codex_wakeup_scheduler.rs`
- **Cockpit Tools 구조**:
  - [`codex_wakeup_scheduler.rs`](file:///D:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/.work/library/cockpit-tools/src-tauri/src/modules/codex_wakeup_scheduler.rs)는 유료 폴링 없이 쿼터 리셋 타임스탬프(`calculate_next_run_at`)를 계산해 정확한 리셋 시각에만 워커를 깨웁니다.
- **UAOS-RSI 이식 가치**:
  - UAOS-RSI의 5번째 칩(`⑤리셋자동재개:ON`)과 결합해 5h 한도 도달 시 정확히 리셋 시각에 다음 `READY` 카드를 재개하는 트리거 정밀도를 높입니다.

---

## 3. 주의·격리 대상 (채택 제외 항목)

> [!CAUTION]
> `Cockpit Tools` 내부의 계정 쿠키·OAuth 토큰 강제 주입(`trae_account_token_injection.rs`, `claude_account_cookie_snapshot.rs`, 외부 중계소 `apikey_fun_links.rs`)은 UAOS-RSI **Safety 규칙(자격증명·비밀 접근 및 변경 금지, 유료 외부 API 과금 차단)**에 위배되므로 **절대 채택하지 않고 격리**합니다. 오직 **읽기 전용 사용량 SQLite 연동, 플로팅 HUD 위젯 UX, CAS 원자적 파일 쓰기** 3가지만 순수 로직으로 추출합니다.
