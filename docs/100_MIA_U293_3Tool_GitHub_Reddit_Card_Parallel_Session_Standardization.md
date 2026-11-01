# [U293] MIA 전략절차 11단계 — 3대 AI 도구(Claude Code·Codex·Antigravity) 및 GitHub·Reddit 전수조사 기반 "카드별 병렬 세션 가동(Card-by-Card Parallel Session Execution)" 최적화·표준화 설계서

- **문서 번호**: `docs/100` (`U293` 정본, `U287`/`U292` 확장)
- **작성일**: 2026-11-02
- **작성자**: Antigravity (MIA Strategic 11-Stage Framework)
- **적용 대상**: `Claude Code`, `OpenAI Codex`, `Google Antigravity` (3대 AI 도구 전역 규칙 `v7.6.3` 및 라이브 런타임 `~/.uaos/uaos.py`)

---

## Stage 0. 사전 근거자료조사 (Web Deep Research & Local Transcript Forensics)

### 0-1. 3대 AI 도구 네이티브 "카드별 병렬 세션 가동" 실측 메커니즘 비교

| 구분 | Claude Code (Desktop & CLI) | OpenAI Codex (App & CLI) | Google Antigravity (IDE & CLI) |
|---|---|---|---|
| **1차 출처** | Anthropic Docs (`claude-code/sub-agents`, `common-workflows#worktrees`) 및 로컬 트랜스크립트 `926558e3.jsonl` 실측 | OpenAI Codex (`github.com/openai/codex`, `codex-rs/app-server` JSON-RPC) | Antigravity Subagent Spec (`invoke_subagent`, `send_message`, `agy -p`) |
| **부모-자식 UI 구조** | 부모 세션 내 `mcp__ccd_session__mark_chapter({"title": "카드별 병렬 세션 가동"})` 배너 + 사이드바 부모 트리 아래 자식 세션 중첩 표시 | 프로젝트 그룹 아래 스레드 목록(`[U##] <제목>`) 병렬 표시 | Agent Manager 내 부모 대화창 + 서브에이전트 카드(`conversation://<id>`) 병렬 표시 |
| **자식 세션 생성 API** | `mcp__ccd_session__start_session({"initiation": "user_asked", "title": "<U##> <제목>", "name": "<slug>", "context": "fresh", "use_worktree": true, "source_branch": "...", "prompt": "...", "background": "..."})` | `codex app-server` JSON-RPC: `thread/start` (`{"cwd": "<wt>"}`) → `turn/start` → `thread/name/set` (`{"name": "[U##] <제목>"}`) | `invoke_subagent(TypeName="self", Role="[U##] <제목>", Prompt="...", Workspace="branch" \| "share", Model="inherit")` |
| **반환 세션 식별자** | `local_<uuid>` (예: `local_b30fe6ed-a0e1-457c-ad56-715be55da702`) | `<thread_uuid>` (`~/.codex/sessions/.../rollout-*-<uuid>.jsonl`) | `<conversation_uuid>` (`agy -p --output-format json` → `conversation_id`) |
| **비동기 후속 통신** | `SendMessage({"to": "local_<uuid>", "summary": "...", "message": "..."})` | `codex queue --thread <thread_uuid>` / `turn/start` | `send_message(Recipient="<conversation_uuid>", Message="...")` |
| **파일·브랜치 격리** | `use_worktree: true` → `.claude/worktrees/<slug>` 자동 분기 | `$CODEX_HOME/worktrees` 또는 `.work/wt_<card>` 지정 | `Workspace="branch"` / `"share"` 또는 `.work/wt_<card>` |

### 0-2. GitHub 오픈소스 및 Reddit 커뮤니티 전수조사 (7대 아키텍처 대조)

1. **Vibe Kanban (`github.com/BloopAI/vibe-kanban`)**:
   - **장점**: 칸반 카드(`In Progress` 진입)마다 독립 Git Worktree와 에이전트 세션을 1:1 매핑하고, 완료 시 Diff/PR 뷰어로 즉시 연결.
   - **한계**: 단일 도구 위주이거나 수동 사람 병합(Human-in-the-loop merge)에 의존하여 에이전트 간 자동 교차 판정(`author != judge`)이 없음.
2. **Crystal / Nimbalyst (`github.com/stravu/crystal`)**:
   - **장점**: 데스크톱 좌측 사이드바 트리에 복수의 Claude Code / Codex 세션을 워크트리별로 띄워 병렬 진행 상황을 한눈에 시각화.
   - **한계**: 세션 간 메시지 전달이 수동이며, 컨텍스트가 커질 때 자동 회전(Context-cap rotation)이 없음.
3. **Claude Squad (`github.com/smtg-ai/claude-squad`)**:
   - **장점**: 터미널/백그라운드에서 다수의 에이전트 인스턴스를 독립 브랜치로 동시 구동.
   - **한계**: 동일 분류의 우편함/릴레이 폭주 시 묶음 처리(Lane Coalescing)가 없어 알림 폭풍 발생.
4. **Reddit `r/ClaudeAI` · `r/ClaudeCode` · `r/ChatGPTCoding` 실전 패턴**:
   - **합의된 최선책 (Planner–Builder–Gatekeeper)**:
     1) **부모 지휘 세션(Planner/Conductor)**은 직접 코드를 수정하지 않고 현황 파악·권한 배분·체크리스트 관리만 수행하여 컨텍스트를 가볍게 유지한다.
     2) **자식 카드 세션(Builder/Reviewer)**은 반드시 `context="fresh"` + `use_worktree=True`로 시작하며, 좁고 명확한 단일 카드(또는 강결합 소규모 카드 쌍 `U276+U284`)만 담당한다.
     3) **비작성자 통합 관문(Gatekeeper)**: 자식 세션은 코드를 작성·테스트하고 PR을 열거나 판정 편지(`coord deliver --verdict-requested`)만 보내며, 절대 스스로 `main`에 병합하지 않는다.

### 0-3. 포렌식으로 발견된 실전 결함 3건 및 해결책

1. **결함 1 (`local_<uuid>` 거부 결함)**:
   - Claude Desktop의 `mcp__ccd_session__start_session`이 반환하는 `local_b30fe6ed-a0e1-457c-ad56-715be55da702` 형식의 세션 ID를 기존 `windows.py:_claude_session_id`에 전달하면 `SESSION_ID_RE`가 `local_` 접두어를 거부하여 `ValueError`가 발생함.
   - **해결**: `normalize_claude_session_id`를 도입해 `local_<uuid>`와 `<uuid>`를 모두 허용하고, 정규화된 `<uuid>`를 `id`로, 원본 `local_<uuid>`를 `native_id`로 함께 기록한다.
2. **결함 2 (동일 레인 카드 간 창 ID 공유 결함)**:
   - 기존 `open_or_reuse_card_parallel_windows`가 미개설 카드에 `lane_win["id"]`를 그대로 할당하여, 같은 레인(`IMPL_CODE`)의 `U287`, `U290`, `U291`, `U292`가 모두 똑같은 세션 ID를 갖게 되어 `session_busy()` 충돌을 유발함.
   - **해결**: `deterministic_card_session_uuid(project, card, tool, generation)`로 **모든 카드(`(card, tool)`)마다 고유한 카드 전용 세션 UUID**를 생성하고, 레인 전용 창 ID는 `lane_window_id` 필드에 별도 바인딩하는 **2계층(Dual-Layer: Card Session ↔ Process Lane)** 구조를 확립한다.
3. **결함 3 (Claude Desktop 자식 세션 ↔ `.coord/windows/<card>.json` 자동 동기화 부재)**:
   - Claude Desktop이 `mcp__ccd_session__start_session`으로 자식 세션 4개를 띄워도 `.coord/windows/<card>.json`에 수동 등록하지 않으면 다른 도구(Antigravity, Codex)가 해당 카드의 실제 자식 세션 ID를 알 수 없음.
   - **해결**: `sync_claude_desktop_card_sessions(project)`가 `~/.claude/projects/*/*.jsonl`에서 `mcp__ccd_session__start_session` 호출 및 결과를 자동 스캔하여, 단일 카드(`U291`)는 물론 복합 카드 제목(`U276+U284`)까지 파싱해 `.coord/windows/<card>.json`에 `id`, `native_id`, `parent_session_id`, `name`, `title`, `lane_id`를 원자적으로 동기화한다.

---

## Stage 1 ~ 4. 기획 및 큰계획 (4대 렌즈 아키텍처 설계)

### 핵심 표준 아키텍처: **UAOS-RSI Dual-Layer Card & Lane Parallel Session OS (`U293`)**

```
[최상위(부모) 기본 사용자 대상 대화창 (Topmost Default User-Facing Window: "[YYMMDD-N] 대화창 대표 타이틀")]
  ├─ 자동 개설·선점 로직: user_window.claim + ensure_topmost_user_window → .coord/presence/user_windows.json (PRIMARY)
  │    - 예(Claude Code 최상위): "[261102-1] Codex 사용량 제한 대응" (sessionId=local_9538324b..., cliSessionId=926558e3...)
  │    - 예(Antigravity 최상위): "[261102-2] 카드별 병렬 세션 가동 표준화 설계" (conversationId=e83f605a...)
  ├─ 챕터 마커: "카드별 병렬 세션 가동" (mcp__ccd_session__mark_chapter / UI Header)
  ├─ 1계층(하위): 카드별 독립 자식 세션 (.coord/windows/<U##>.json, "[U##] 핵심 제목" 유지·사용자창 선점 제외)
  │    ├─ [U291 PR #256 비작성자 판정] (id=b30fe6ed..., native_id=local_b30fe6ed..., context=fresh, wt=u291-review)
  │    ├─ [U290 일일 상한 제거 PR 완결] (id=9958fb7b..., native_id=local_9958fb7b..., context=fresh, wt=u290-pr)
  │    ├─ [U287 통합 도우미 원격측정 계약] (id=6ab5c561..., native_id=local_6ab5c561..., context=fresh, wt=u287-telemetry)
  │    └─ [U276+U284 파일럿·작성자 출처 확인] (id=03c35125..., native_id=local_03c35125..., context=fresh, wt=u276-provenance)
  └─ 2계층: 5대 프로세스 분류 레인 멀티플렉서 (.coord/windows/lanes/<LANE>.json)
       ├─ IMPL_CODE      (구현·코드작성 전용창)
       ├─ VERIFY_AUDIT   (검증·반례감사 전용창)
       ├─ ARCH_DESIGN    (기획·설계·리서치 전용창)
       ├─ MERGE_RELEASE  (병합·배포·결과집계 전용창)
       └─ RECOVERY_OPS   (장애복구·병목해소 전용창)
```

---

## Stage 5 ~ 8. 세부계획 및 구현 명세 (`v7_harness/coord/card_sessions.py`)

0. **`ensure_topmost_user_window(project: Path, tool: str, thread: str, *, representative_title: str = "", ...) -> dict[str, Any]`**:
   - 카드별 병렬 세션 가동 트리에서 **가장 위에 위치한 최상위(부모) 대화창을 기본적으로 사용자 대상 대화창(`PRIMARY`)**으로 선점하고, 기존 사용자 대상 대화창 개설 로직(`user_window.claim` + `extract_representative_title` + 네이티브 저장소 동기화)으로 **`[YYMMDD-N] <대화창 대표 타이틀>`** 형식을 강제한다.
   - 하위 자식 카드 세션(`titleSource == "tool"` 또는 `[U##]`/`U##` 제목, `.coord/windows/*.json` 등록 세션)은 `is_child_card_session`으로 자동 식별하여 사용자 대상 대화창 선점에서 원천 배제(`CHILD_CARD_SESSION`)한다.
1. **`normalize_claude_session_id(raw_id: str) -> tuple[str, str]`**:
   - 입력이 `local_<uuid>` 또는 `<uuid>`일 때 `(canonical_uuid, "local_" + canonical_uuid)`를 반환하고, 잘못된 형식은 `ValueError`로 차단.
2. **`deterministic_card_session_uuid(project: Path, card: str, tool: str, generation: int = 0) -> str`**:
   - `(project, card, tool, generation)` 시드 기반 고유 UUIDv4/v5 형식을 생성하여 카드 간 세션 ID 충돌을 원천 제거.
3. **`extract_cards_from_text(text: str) -> list[str]`**:
   - `"U291 PR #256 비작성자 판정"` → `["U291"]`, `"U276+U284 파일럿·작성자 출처 확인"` → `["U276", "U284"]` 등 단일·복합 카드 ID를 정밀 추출.
4. **`build_card_parallel_launch_spec(...) -> dict[str, Any]`**:
   - 카드 ID, 핵심 제목, 역할(`implement`, `review`, `pr`, `provenance`), 브랜치, 허용 파일, 인수 명령을 입력받아 3대 도구(`claude_desktop`, `antigravity`, `codex`)가 즉시 실행할 수 있는 표준화된 `(prompt, background, native_calls)` 명세를 생성.
5. **`sync_claude_desktop_card_sessions(project: Path, transcripts_root: Path | None = None) -> dict[str, Any]`**:
   - Claude Desktop 트랜스크립트에서 `mcp__ccd_session__start_session` 호출과 `Started session ... (session_id: local_<uuid>, name: <slug>)` 응답을 매칭하여 `.coord/windows/<card>.json`에 실시간 바인딩.
6. **`orchestrate_card_parallel_batch(project: Path, cards: Sequence[str | dict[str, Any]], ...) -> dict[str, Any]`**:
   - 복수 카드에 대해 (1) Claude Desktop 트랜스크립트 자동 동기화, (2) 3대 도구 고유 카드 창 + 5대 분류 레인 창 프로비저닝, (3) 3대 도구 네이티브 병렬 실행 명세 일괄 생성을 원스톱 수행.

---

## Stage 9 ~ 10. 구현, 백신 테스트, 자율 병합 및 런타임 실가동

- `tests/test_u293_card_parallel_sessions.py`를 통해 단위·동시성·백신 테스트 전수 검증 후 자율 병합 및 전역 규칙(`v7.6.3`)·런타임(`~/.uaos/uaos.py`) 배포 완료.
