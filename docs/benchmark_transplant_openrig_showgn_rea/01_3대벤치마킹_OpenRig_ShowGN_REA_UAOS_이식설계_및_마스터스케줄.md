# 3대 벤치마킹 저장소(`OpenRig` · `Show GN` · `REA`) UAOS-RSI 이식 설계 및 3대 도구 합의 마스터 스케줄

- **폴더 및 문서 경로**: `docs/benchmark_transplant_openrig_showgn_rea/01_3대벤치마킹_OpenRig_ShowGN_REA_UAOS_이식설계_및_마스터스케줄.md`
- **작성 및 합의 주체**: **Codex (총괄 조율·판정) · Claude Code (부지휘·심층 구현) · Antigravity (계약 실행·출처/설계 감사·사용자 창구)** + **Ollama (`qwen2.5-coder:7b` 0토큰 로컬 계산기)**
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

## 1. 3대 벤치마킹 저장소 핵심 로직 선별 및 3대 도구 맞춤형 변환 설계

| 구분 | 원본 프로젝트의 한계 (2도구 또는 상시 무거운 로드) | UAOS-RSI 3대 도구 오케스트레이터로의 선별·변환 이식 (`v7_harness/benchmark_logic_transplant.py`) |
|---|---|---|
| **1. OpenRig**<br>(`mvschwarz/openrig`) | - Claude Code + Codex **2대 도구만 지원**<br>- Linux/macOS/WSL2 `tmux` 터미널 멀티플렉서에 강결합 | - **`build_three_tool_seat_registry()`**: Windows 네이티브 **3대 유료 도구(`Codex`·`Claude`·`Antigravity`) + 1 무료 계산기(`Ollama`)의 4-좌석(Seat) 선언적 레지스트리**로 확장<br>- `workshop`의 **Non-Interruptive(무승인 자율 진행) 모드**를 Safety 사람 전용 목록과 결합 |
| **2. Show GN**<br>(`UnrealFactory/AgentCodeGUI`) | - Claude + Codex **2엔진 수동 클릭 데스크톱 GUI** | - **`build_five_chip_telemetry_snapshot()`**: 작업 바 **5대 상시 칩(`1_todos_schedule`, `2_three_tool_seats`, `3_background_watchers`, `4_changed_files_diff`, `5_quota_and_reset_timer`)**을 자율 관제 스냅샷으로 이식<br>- **한도 소진 시 3→2→1 즉시 재계획(`replan_on_quota_limit`) + `reset_at` 자동 복귀 + 5초 전면 대기 선점(`preempt_foreground_wait`)** |
| **3. REA**<br>(`morluto/rea` v6.8.0) | - 50+ 바이너리 역공학 MCP 도구를 상시 로드하면 **호출당 ~14,000 유료 토큰**이 고정 소모됨 | - **`select_rea_analysis_tier()` (2계층 하이브리드 라우터)**:<br>  - **Tier 1 (상시 기본 분석로직, 스키마 추가 비용 0토큰)**: 4계층 증거 분리(`evidence_ledger.py`), 요약 우선 페이징(`analysis_view.py`), 유한 오라클 동치 검증(`process_supervisor.py`)<br>  - **Tier 2 (온디맨드 역설계 브리지, 역설계 타깃 시에만 100% 가동)**: `.exe`/`.dll`/`.asar`/`.apk`/`.sqlite`/`.work/library/` 분석 시에만 `rea_bridge.py` + `.work/library/rea` 본래 기능 전체 가동 |

---

## 2. 3대 도구 합의 마스터 스케줄 (`U245` ~ `U251` 전 단계 구현·검증·배포 완료)

| 단계 ID | 단계명 (직관적 모듈 매핑) | 구현 파일 (`v7_harness/`) | 검증 테스트 (`tests/`) | 상태 |
|---|---|---|---|---|
| **`U245`** | REA Tier-1 4계층 증거 원장 & 1차 출처 필수 관문 | [`v7_harness/evidence_ledger.py`](file:///d:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/v7_harness/evidence_ledger.py) | [`tests/test_u245_evidence_citation_gate.py`](file:///d:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/tests/test_u245_evidence_citation_gate.py) | `DONE` (PASS) |
| **`U246`** | REA Tier-1 요약 우선 번들 보존 & 페이지네이션 뷰 | [`v7_harness/analysis_view.py`](file:///d:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/v7_harness/analysis_view.py) | [`tests/test_u246_analysis_view.py`](file:///d:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/tests/test_u246_analysis_view.py) | `DONE` (PASS) |
| **`U247`** | REA Tier-2 온디맨드 정적 역설계 브리지 (`STATIC_ONLY`) | [`v7_harness/rea_bridge.py`](file:///d:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/v7_harness/rea_bridge.py) | [`tests/test_u247_rea_static_bridge.py`](file:///d:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/tests/test_u247_rea_static_bridge.py) | `DONE` (PASS) |
| **`U248`** | REA Tier-1 2단계 프로세스 종료 감독 & 오라클 동치 검증 | [`v7_harness/process_supervisor.py`](file:///d:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/v7_harness/process_supervisor.py) | [`tests/test_u248_process_finalization.py`](file:///d:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/tests/test_u248_process_finalization.py) | `DONE` (PASS) |
| **`U249`** | 3→2→1 한도 페일오버 · 5초 전면대기 선점 · 스케줄 자연 종료 | [`v7_harness/coord/failover_closeout.py`](file:///d:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/v7_harness/coord/failover_closeout.py) | [`tests/test_u249_failover_preemption_closeout.py`](file:///d:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/tests/test_u249_failover_preemption_closeout.py) | `DONE` (PASS) |
| **`U250`** | 참조·벤치마킹 자료실(`.work/library`) 전역 규칙 & 저장소 관리기 | [`v7_harness/library_store.py`](file:///d:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/v7_harness/library_store.py) | [`tests/test_u250_reference_library_rule.py`](file:///d:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/tests/test_u250_reference_library_rule.py) | `DONE` (PASS) |
| **`U251`** | 3대 벤치마킹(`OpenRig`·`ShowGN`·`REA`) 통합 이식 오케스트레이터 | [`v7_harness/benchmark_logic_transplant.py`](file:///d:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/v7_harness/benchmark_logic_transplant.py) | [`tests/test_u251_benchmark_logic_transplant.py`](file:///d:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/tests/test_u251_benchmark_logic_transplant.py) | `DONE` (PASS) |
