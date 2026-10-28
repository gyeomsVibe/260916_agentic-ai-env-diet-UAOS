# 3대 도구 대화창의 Codex 프로젝트 대화(Thread) 직접 편입 프로토콜

- 문서 번호: `docs/24`
- 버전: `v1.0.0`
- 확정 일시: `2026-09-24`
- 성격: **사용자 최고 의지(Mandate) — Antigravity 및 Claude Code 수행 프로세스의 Codex 프로젝트 대화 직결**

---

## 1. 개요 및 사용자 요구

### 1-1. 배경 (docs/24 스크린샷 참조)
Codex 데스크톱 앱의 프로젝트 사이드바(`260916_agentic-ai-env-diet_codex`)에는 `[U23] 디스크 우편함 S1`, `[B58] 조율 로그 manifest 격리` 등 작업별 전용 대화창(Thread)이 나열된다. 사용자는 이 목록에 Antigravity와 Claude Code의 수행 대화 및 결과 보고가 독립 대화창으로 직접 편입되어 언제든지 열람·관리되기를 지정하였다.

### 1-2. 대화창 명명 규약 (Naming Invariant)
Codex 프로젝트 사이드바에 등록되는 대화창의 제목은 반드시 각 도구의 식별 접두어를 포함한다:
- **Antigravity 수행 작업**: `[agy-<작업명>]` (예: `[agy-MIA 전략 레드팀 및 0원 전화기 모델]`)
- **Claude Code 수행 작업**: `[claude-<작업명>]` (예: `[claude-U15 조율 스트림 구현 S1~S4]`)

---

## 2. 연동 아키텍처 및 메커니즘

```
[Antigravity / Claude Code 작업 세션]
               │
               ▼
[v7_harness.coord.codex_session_bridge]
 ├── 1. Rollout JSONL 생성 (~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl)
 ├── 2. state_5.sqlite 등록 (threads 테이블 cwd 매핑)
 └── 3. session_index.jsonl 색인 갱신
               │
               ▼
[Codex Desktop 앱 사이드바 실시간 표시: 260916_agentic-ai-env-diet_codex]
 - [claude-U15 조율 스트림 구현 S1~S4]
 - [agy-MIA 전략 레드팀 및 0원 전화기 모델]
 - [U23] 디스크 우편함 S1
```

### 2-1. 데이터 구조
1. **Rollout 세션 파일 (`~/.codex/sessions/<YYYY>/<MM>/<DD>/rollout-<ts>-<uuid>.jsonl`)**:
   - `session_meta`: 작업공간 `cwd`(`D:\D_Workspace_NB\-agentic-ai-workspace\260916_agentic-ai-env-diet`), 소스(`external_agy` / `external_claude`), 모델 프로바이더 명시.
   - `task_started`, `user_message`, `assistant_message`, `task_complete` 단계별 정규 JSONL 구조 생성.
2. **로컬 메타데이터 DB (`~/.codex/state_5.sqlite`)**:
   - `threads` 테이블에 스레드 메타데이터(`name=f"[{actor}-{task}]"`, `cwd`, `rollout_path`, `tokens_used` 등)를 원자적으로 삽입(`INSERT ON CONFLICT DO UPDATE`).
   - `cwd`가 프로젝트 경로와 일치하므로 Codex Desktop이 `260916_agentic-ai-env-diet_codex` 프로젝트 아래에 자동으로 그룹화.
3. **세션 인덱스 (`~/.codex/session_index.jsonl`)**:
   - 데스크톱 앱과 CLI가 빠른 조회를 위해 참조하는 인덱스에 새 스레드 이름과 ID를 즉각 반영.

---

## 3. 운용 CLI

Antigravity 또는 Claude Code가 작업을 완결할 때 다음 명령어로 즉시 Codex 프로젝트 대화창에 세션을 발행한다:

```bash
python -m v7_harness.cli coord publish-thread \
  --actor agy \
  --task "MIA 전략 레드팀 및 0원 전화기 모델" \
  --prompt "사용자 지시문 내용" \
  --response "어시스턴트 수행 보고 내용"
```

---

## 4. 실측 등록 검증

2026-09-24 실측 등록 확인:
- `07644bec-0c56-4d51-b4e8-adb94dfad392` → `[agy-MIA 전략 레드팀 및 0원 전화기 모델]`
- `09f427db-4d0b-4fbf-a297-fe995ae379a0` → `[claude-U15 조율 스트림 구현 S1~S4]`
Codex Desktop `state_5.sqlite` 및 `session_index.jsonl`에 정상 등록되어 프로젝트 사이드바에 실시간 노출됨을 확인 완료.
