# U230: MIA 11단계 전략 실행 — 무승인 논스톱 티키타카(Tiki-Taka) 전수검토 및 전면 개편

## Stage 0. 사전 근거자료조사 (Web Deep Research & Source Audit)
- **웹 1차 출처 리서치**:
  - Claude Code Headless CLI (`claude -p`, `--resume`, `--output-format json`, `--allowedTools`): [Anthropic Claude Code Hooks & Headless Docs](https://code.claude.com/docs/en/hooks), [GitHub anthropics/claude-code](https://github.com/anthropics/claude-code)
  - OpenAI Codex CLI App-Server & Queue (`codex exec`, `codex queue --thread`): [OpenAI Codex Developers Docs](https://developers.openai.com/codex/app-server), [GitHub openai/codex](https://github.com/openai/codex)
  - UAOS 저장소 및 U229 병합 PR: [gyeomsVibe/260916_agentic-ai-env-diet-UAOS](https://github.com/gyeomsVibe/260916_agentic-ai-env-diet-UAOS) · [PR #187](https://github.com/gyeomsVibe/260916_agentic-ai-env-diet-UAOS/pull/187)
- **전수검토를 통해 적발한 5대 근본 결함 (왜 사용자가 복붙해야 했는가?)**:
  1. **RC1 (`v7_harness/judge.py` L187, L297)**: `run_judge()`가 `shared_desk()`를 거치지 않고 `Path(project or source).resolve()`에서 `read_all()`을 호출함. Git worktree(`.claude/worktrees/...`)에서 `pilot judge` 실행 시 worktree 내부에는 `.coord/presence/codex.json`이 없으므로 무조건 `codex: UNKNOWN`이 반환되어 `CODEX_JUDGES: codex is UNKNOWN`으로 거부됨.
  2. **RC2 (`v7_harness/coord/presence.py` L233-239)**: `read()`가 `expires_at <= moment`(기본 TTL 1시간 만료)일 때 `codex_quota_block()`(롤아웃 로그의 `usage_limit_exceeded` 리셋 시각)을 확인하기 전에 먼저 `UNKNOWN`을 반환함. 결과적으로 5시간/주간 한도에 걸린 Codex가 1시간 뒤 `LIMITED`에서 `UNKNOWN`으로 변해 대행 지휘권(`conductor`)과 대행 판정(`judge`)이 동시에 마비됨.
  3. **RC3 (`v7_harness/cli.py` L2392 & `v7_harness/coord/windows.py` L173)**: `_DESK_COMMANDS`에 `"window"`가 누락되어 worktree에서 `coord window --tool auto` 실행 시 `shared_desk`의 출석부를 읽지 못하고, `_open_antigravity`가 `done.stdout`을 단순 `json.loads()`로 파싱하여 비JSON 경고나 실패 시 `JSONDecodeError`로 중단됨.
  4. **RC4 (`v7_harness/coord/deliver.py` L90, L224, L1009, L1115, L1279, L1330)**: `coord deliver --wake-class ACTIONABLE` 또는 `--verdict PASS`로 발송해도 `_deliver_unlocked()`는 본문 문자열에 리터럴 `ACTIONABLE_DELTA`가 있는지만 검사(`_requires_wake(message)`)하여 `QUEUED_INTERACTIVE`로 잠재우고 Claude를 깨우지 않음. 또한 `claude-session.json`의 이전 세션이 `--resume` 중 타임아웃(120s)되어도 세션 파일을 초기화하지 않아 이후 모든 전달이 연속 타임아웃됨.
  5. **RC5 (`v7_harness/card_pipeline.py` L342)**: `card audit`가 `runs/{card}-*/review_agy.json`만 검사하고 `runs/{card}/review_agy.json`, `runs/{card}*/judge_agy.json`(`APPROVE`), 및 `.coord/mailbox/`의 Antigravity 공식 판정 서신(`actor=="antigravity"`, `card==card`, `verdict in AGY_VERDICTS`)을 인정하지 않아 감사 통과 후에도 커밋 관문이 막힘.

## Stage 1~2. 기획 (Frame) 및 기획 검증 (Gate 1~2: PASS)
- **목표**: 사용자의 수동 복사·붙여넣기 개입을 0건으로 제거하고, worktree·한도초과·세션만료 상황에서도 3대 도구 간 전달·감사·판정·커밋이 무승인 논스톱으로 완결되게 개편.
- **측정 가능한 성공 신호**:
  - RC1~RC5 회귀 테스트(`tests/test_u230_nonstop_tikitaka.py`) 및 기존 관련 테스트 100% PASS (exit 0).
  - `~/.uaos/runtime/`에 신규 런타임 설치 및 `uaos --version` 무결성 검증 통과.
- **비목표 (Non-goals)**: Safety 사람 전용 목록(데이터 영구 삭제, 실서버 배포, 유료 결제, 권한 변경) 우회 금지.

## Stage 3~4. 큰계획 (Master Plan) 및 아키텍처 검증 (Gate 3~4: Go)
| 대안 | Value | Feasibility | Viability | Risk / Rollback | 판정 |
|---|---|---|---|---|---|
| **Alt A (채택)**: 5대 병목(`judge`, `presence`, `deliver`, `windows`, `card_pipeline`, `cli`) 정밀 패치 + 런타임 즉시 배포 | 5대 복붙 유발 원인을 근본 제거 | 기존 인터페이스·고정 테스트 100% 호환 | 모든 worktree·세션에 즉시 적용 | `uaos runtime --apply --rollback` 즉시 복구 가능 | **GO** |
| **Alt B**: 외부 데몬 프로세스 신설 | 구조 복잡도 증가 | Windows 프로세스 고아 위험 | 관리 포인트 증가 | 데몬 장애 시 전체 중단 | No-Go |

## Stage 5~8. 세부계획·구현계획 및 사전 안전 게이트 (Gate 5~8: PASS)
- **허용 파일 (`allow`)**:
  - `v7_harness/judge.py`
  - `v7_harness/coord/presence.py`
  - `v7_harness/coord/deliver.py`
  - `v7_harness/coord/windows.py`
  - `v7_harness/card_pipeline.py`
  - `v7_harness/cli.py`
  - `tests/test_u230_nonstop_tikitaka.py`
- **백업 완료**: `.work/backup_20261025/`에 수정 대상 원본 6개 파일 백업 완료.
