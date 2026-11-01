# [U292 / U287] MIA 전략절차 11단계 — 3대 AI 도구 공통 "카드별·분류별 병렬 대화창 가동(Card & Process-Lane Parallel Window Execution)" UAOS-RSI 운영체제 정본화, 전역 규칙 고정, 런타임 실가동 및 단독 RSI 업그레이드 세션 기록

- **Date**: 2026-11-01
- **Card ID**: `U292` (통합 `U287` / `U279` 병렬 대화창 멀티플렉싱 OS 정본화)
- **Author**: Antigravity (Co-executing with Claude Code while `codex = LIMITED`)
- **Status**: `ACTIVE -> DONE`
- **Target Scope**:
  - `v7_harness/coord/process_lanes.py` (카드별·분류별 병렬 대화창 프로비저닝 `open_or_reuse_card_parallel_windows`, 병렬 디스패치 `multiplex_and_dispatch_parallel`, 단독 RSI 업그레이드 세션 생성·3도구 브로드캐스트 `record_rsi_upgrade_session`, 최신 RSI 세션 요약 `latest_rsi_upgrade_session`)
  - `v7_harness/coord/desk_delta.py` (`.coord/rsi/sessions/*/SESSION.json` 3대 도구 자동 감지 및 `DESK DELTA` 주입)
  - `v7_harness/coord/hook_context.py` (`brief_line` 및 `agy_line`에 최신 RSI 업그레이드 세션 3도구 가시성 연결)
  - `v7_harness/cli.py` (`uaos coord lanes --action record-rsi-session | provision-cards | dispatch | handoff | status | clear-obstacles`)
  - `uaos_everywhere/uaos_global_rule_block.md` 및 `260718_agentic-ai-platform-optimization/shared/global-rules/` (`core.md`, `GLOBAL_RULES.ko.md`, `VERSION` `7.6.2`, `dist/*`, `~/.gemini/GEMINI.md`, `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`)
  - `tests/test_u287_process_lane_parallel_windows.py`

---

## Stage 0. 사전 근거자료조사 (Web Deep Research)

1. **Anthropic Claude Code CLI — Session Resumption, Forking & Parallel Headless Execution**:
   - **출처**: Anthropic Official Docs (`https://docs.anthropic.com/en/docs/claude-code/cli-usage`, `https://docs.anthropic.com/en/docs/claude-code/sdk`)
   - **핵심 메커니즘**: `claude -p --resume <session-uuid>` 및 `--session-id <uuid>`는 `~/.claude/projects/<project-slug>/<uuid>.jsonl` 트랜스크립트 파일에 세션별 락을 건다. 단일 세션 UUID로 모든 릴레이를 직렬 전송하면 Head-of-Line (HoL) 블로킹과 `Session ID is already in use` 충돌이 발생하지만, **프로세스 분류 레인(`IMPL_CODE`, `VERIFY_AUDIT`, `ARCH_DESIGN`, `MERGE_RELEASE`, `RECOVERY_OPS`) 및 카드(`U##`)별로 독립 세션 UUID와 개별 턴 락(`claude-lane-<LANE>.turn.lock`, `claude-win-<SESSION>.turn.lock`)을 분리**하면 다수의 대화창이 충돌 없이 병렬로 고속 메시지 교환을 수행할 수 있다.
2. **OpenAI Codex App-Server JSON-RPC — Multi-Thread Parallelism**:
   - **출처**: OpenAI Codex CLI (`codex app-server` JSON-RPC `thread/start`, `turn/start`, `thread/name/set`)
   - **핵심 메커니즘**: Codex는 `threadId` 단위로 독립적인 롤아웃(`~/.codex/sessions/YYYY/MM/DD/rollout-*-<threadId>.jsonl`)을 유지하므로, 카드별(`.coord/windows/<card>.json`) 및 분류 레인별(`.coord/windows/lanes/<lane>.json`) 전용 스레드를 분리하고 `MAX_LANE_TURNS = 12` / `MAX_LANE_ROLLOUT_BYTES = 180,000` 도달 시 자동 회전(`ensure_fresh_lane_window`)하면 컨텍스트 비대화 없이 병렬 티키타카가 가능하다.
3. **GitHub CLI Atomic Merge (`gh pr merge --match-head-commit <SHA>`)**:
   - **출처**: GitHub CLI Official Manual (`https://cli.github.com/manual/gh_pr_merge`)
   - **핵심 메커니즘**: 판정된 커밋 SHA를 `--match-head-commit`으로 고정하여 `MERGE_RELEASE` 레인에서 사람 대기 없이 원자적 병합 후 즉시 `~/.uaos/runtime/`에 런타임을 재설치(`runtime_install.install`)한다.

---

## Stage 1. 기획 (Framing & Problem Definition)

- **결정 사항 (Decision)**:
  1. 클로드에게 내린 지시(*"안티그래비티와의 밀린 프로세스를 개별 독립 대화창을 생성해서 병렬로 빠른 메시지 교환을 실현해. 이게 UAOS 로직이다. 이를 기본 운용원칙으로 채택하고, 각 해당 관련 프로세스를 모아 빠른 프로세스 진행 로직을 만들어라"*)를 3대 AI 도구(`Antigravity`, `Claude Code`, `Codex`) 공통의 **UAOS-RSI 기본 운영체제 로직**으로 격상한다.
  2. 이를 3대 도구 전역 규칙(`v7.6.2`: `~/.gemini/GEMINI.md`, `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md` 및 `uaos_global_rule_block.md`)에 영구 고정하고, 라이브 런타임(`~/.uaos/uaos.py`)에 즉시 반영하여 실가동한다.
  3. 본 업그레이드를 `.coord/rsi/sessions/U292-CARD-LANE-PARALLEL-WINDOWS-20261101/`에 단독 RSI 자가개선-업그레이드 세션으로 기록하고 `desk_delta`·`hook_context`·우편함 릴레이를 통해 3대 도구 모두가 즉시 열람·준수하게 만든다.
- **측정 가능한 성공 신호 (Measurable Success Signal)**:
  1. 5대 프로세스 분류 레인(`IMPL_CODE`, `VERIFY_AUDIT`, `ARCH_DESIGN`, `MERGE_RELEASE`, `RECOVERY_OPS`) 및 활성 카드별 전용 대화창이 3대 도구 모두에 프로비저닝되고, 밀린 프로세스가 병렬 스레드풀(`ThreadPoolExecutor`)로 동시 디스패치되어 HoL 블로킹이 0건임이 단위·동시성·백신 테스트로 증명됨.
  2. `sync-global-rules.ps1 -Mode Apply` 및 `-Mode Check`가 3대 도구 모두 `PASS` / `ALIGNED` (`exit 0`, Antigravity `<= 14,000`자 준수).
  3. `python -m v7_harness.runtime_install --apply` 및 `python uaos_everywhere/install_uaos_everywhere.py --apply` 후 `--check`가 `drift = []` (`exit 0`).
  4. `.coord/rsi/sessions/U292-CARD-LANE-PARALLEL-WINDOWS-20261101/SESSION.json` 및 `REPORT.md`가 생성되고, `desk_delta.absence_items()` 및 `hook_context.brief_line()`에서 3대 도구 모두에게 자동 노출됨.
- **비목표 (Non-Goals)**:
  - Safety 사람 전용 목록(데이터 삭제, 미승인 강제 push, 외부 유료 과금, 계정/자격증명 변경)의 우회.
  - `core.md` 내 고정된 `## Method: MIA strategic procedure` 섹션의 SHA-256 해시(`3ec4585fbd329a0582f597d6d35b6f1607022799979e1b20327190352f05055c`) 변경.

---

## Stage 2. 검증 (Verification Gate 1 — Framing Check)

- **실측 확인**:
  - `~/.gemini/GEMINI.md`, `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`는 `260718_agentic-ai-platform-optimization/shared/global-rules/` 정본 생성기가 관리하므로, `uaos_global_rule_block.md`만 수정해서는 3대 도구 전역 규칙 파일에 반영되지 않음(`install_uaos_everywhere.py`가 `_is_canon_generated` 파일 수정 건너뜀).
  - 따라서 **정본 저장소(`shared/global-rules/core.md` + `GLOBAL_RULES.ko.md` + `VERSION 7.6.2`)와 `uaos_global_rule_block.md`를 동시에 갱신**해야 3대 도구 전역 룰에 완벽히 고정됨 (**Decision: GO**).

---

## Stage 3. 큰계획 (Macro Plan — Architecture & 3 Alternatives)

- **Alt 1 (단일 전역 세션에 배치 메시지만 전송)**: 대화창은 1개만 두고 텍스트만 묶어서 전송.
  - *기각*: 느린 구현(`IMPL_CODE`) 턴이 도는 동안 빠른 판정(`VERIFY_AUDIT`)이나 긴급 복구(`RECOVERY_OPS`)가 락 대기(`claude-session.turn.lock`)에 막혀 병목이 재발함.
- **Alt 2 (무제한 카드별 대화창 난립)**: 메시지마다 무조건 새 대화창 생성.
  - *기각*: 콜드 스타트 고정 문맥(~140k 토큰) 반복 과금으로 예산 고갈.
- **Alt 3 (채택 — Card-by-Card + 5-Lane Process-Classification Parallel Window Multiplexing + Context-Cap Auto-Rotation)**:
  1. **카드별 독립 창 (`.coord/windows/<card>.json`) + 5대 분류 레인 창 (`.coord/windows/lanes/<lane>.json`) 이원 결합**:
     - 각 카드는 고유 창을 갖되, 관련 프로세스들을 5대 표준 분류 레인(`IMPL_CODE`, `VERIFY_AUDIT`, `ARCH_DESIGN`, `MERGE_RELEASE`, `RECOVERY_OPS`)으로 클러스터링하여 레인별 전용 대화창과 레인별 독립 락(`claude-lane-<LANE>.turn.lock`)으로 병렬 실행한다.
  2. **동일 분류 버스트 응집 (`coalesce_relays_by_lane`) + 에코 스톰 차단**:
     - 동일 분류의 밀린 릴레이는 전용 대화창 1턴으로 묶어 처리하고, 수신 확인 에코는 즉시 드롭한다.
  3. **컨텍스트 비대화 자동 회전 (`ensure_fresh_lane_window`)**:
     - 12턴 또는 180KB 초과 시 자동으로 새 세대(`generation + 1`) 창으로 회전하여 토큰 비용을 절감한다.
  4. **단독 RSI 자가개선 세션 기록 및 3도구 가시화 (`record_rsi_upgrade_session`)**:
     - `.coord/rsi/sessions/<SESSION_ID>/`에 `SESSION.json` (`uaos-rsi-session-v1`), `REPORT.md`, `CONTINUATION.json`을 생성하고 `desk_delta`와 `hook_context`가 이를 3대 도구 모두에게 자동 브로드캐스트한다.

---

## Stage 4. 검증 (Verification Gate 2 — 4-Lens Review)

- **Value**: 3대 도구 간 병렬 메시지 교환 속도를 극대화하면서 콜드 스타트 토큰 낭비를 막음.
- **Feasibility**: `Antigravity` 전역 규칙 글자 수 상한(`14,000`자, 현재 `13,931`자) 내에 들어오도록 `core.md`의 비필수 수식어를 정교하게 압축하면서 `- Windows:` 규칙에 카드별·분류별 병렬 대화창 및 RSI 세션 공유 규칙을 삽입 가능.
- **Risk & Security**: 필수 검사 문구 9종과 Method 섹션 SHA-256 해시를 100% 보존하여 `sync-global-rules.ps1` 오프라인 하네스 검사를 무결 통과 (**Decision: GO**).

---

## Stage 5. 세부계획 (Detailed Specification)

1. **`v7_harness/coord/process_lanes.py` 확장**:
   - `open_or_reuse_card_parallel_windows(project, cards, *, tools=TOOLS)`: 복수의 카드(`U##`)를 각 카드의 프로세스 분류 레인에 매핑하고 카드별·레인별 대화창을 병렬 프로비저닝.
   - `record_rsi_upgrade_session(project, *, session_id, title, summary_ko, rules_version, runtime_version, actor="antigravity", extra=None)`:
     - `.coord/rsi/sessions/<session_id>/SESSION.json`, `REPORT.md`, `CONTINUATION.json` 원자적 기록.
     - `.coord/rsi/decisions.jsonl`에 `ADOPTED_OS_UPGRADE` 이벤트 추가.
     - 3대 도구(`codex`, `claude`, `antigravity`)가 모두 볼 수 있도록 우편함 공지 발행.
   - `latest_rsi_upgrade_session(project)`: 가장 최근 기록된 RSI 업그레이드 세션 메타데이터 반환.
2. **`v7_harness/coord/desk_delta.py` 및 `v7_harness/coord/hook_context.py` 확장**:
   - `desk_delta.absence_items()`가 `.coord/rsi/sessions/*/SESSION.json`의 신규/갱신 세션을 스캔하여 `rsi_session <session_id>: <title> (rules v<ver>, runtime <rver>)` 항목을 3대 도구 모두의 `DESK DELTA`에 표시.
   - `hook_context.brief_line()` 및 `agy_line()`에 최신 RSI 업그레이드 세션 ID를 표시하여 세션 시작 시 3대 도구가 즉시 인지.
3. **`v7_harness/cli.py` 확장**:
   - `uaos coord lanes --action record-rsi-session --session-id <ID> --title <TITLE> --message <SUMMARY>` 및 `--action provision-cards` 지원.
4. **전역 규칙 정본(`v7.6.2`) 및 런타임 반영**:
   - `shared/global-rules/VERSION` -> `7.6.2`
   - `shared/global-rules/core.md` 및 `GLOBAL_RULES.ko.md` 갱신 후 `sync-global-rules.ps1 -Mode Build` & `-Mode Apply` & `-Mode Check`.
   - `python -m v7_harness.runtime_install --apply` 및 `python uaos_everywhere/install_uaos_everywhere.py --apply` & `--check`.

---

## Stage 6 ~ 8. 계약·구현계획 사전 검증 (Verification Gates 3 & 4)

- **Gate 3 & 4**:
  - `sync-global-rules.ps1 -Mode SourceCheck`로 `Antigravity` 글자 수(`<= 14,000`자), `Method` 섹션 SHA-256 해시, 필수 구문 9종, 중복 줄 0건 통과 여부 확인.
  - `tests/test_u287_process_lane_parallel_windows.py`에 카드별 병렬 창 프로비저닝 및 단독 RSI 업그레이드 세션 생성·3도구 `desk_delta` 노출 검증 테스트 추가 후 실행 (**Decision: GO**).

---

## Stage 9 & 10. 구현 및 디버깅·최종검증 (Implementation & Final Verification)

- 아래 구현 및 테스트 실행으로 검증 완료.
