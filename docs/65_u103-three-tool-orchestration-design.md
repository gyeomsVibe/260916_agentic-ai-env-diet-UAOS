# U103 — 3대 도구 오케스트레이션 설계: 공통 알림, Ollama 대등화, Antigravity 상시 역할

작성: Claude (Codex 부재 중 대행 판정, **Codex 복귀 재검토 대상**) · 2026-10-01
관련 카드: PLAN `U103` · 테스트 `tests/test_u103_desk_delta.py`, `tests/test_u103_olla_parity.py`

## 0. 한 줄 요약

UAOS-RSI는 한 프로젝트, 한 도구용 스크립트가 아니라 **어느 프로젝트에서든 세 도구(Claude Code·Codex·Antigravity)가 같은 규칙으로
움직이는 운영체제**다. 이번 카드는 세 군데의 "Claude만, 이 프로젝트만" 결함을 고쳤고, Antigravity를 대기석에서 상시 검증 역할로 옮기는
설계를 정한다.

## 1. 사용자 지적과 확인된 사실 (2026-10-01)

| 지적 | 확인한 사실 (근거) |
|---|---|
| "자기 편지 숨김이 너만 적용됐다" | 변경 알림 훅 `uaos_everywhere/hooks/codex_delta.py`는 Claude 설정에만 수동 등록돼 있었고, 경로가 이 프로젝트로 고정(`ROOT = D:/…/260916_…`)돼 있었다. Codex의 프롬프트 훅은 `--say none`이라 아무것도 알리지 않았고, Antigravity는 자기 앞으로 온 편지 번호만 받았다. |
| "Antigravity만 Ollama를 쓴다" | `olla stats`: antigravity 요약본(digest) 20회·통째 읽기 거부 17회, codex 요약본 0회. Antigravity에는 `olla-guard` 훅 묶음이 있다. 턴 첫 호출에 "로컬 모델 도구를 써라" 한 줄을 넣고, **8,000토큰 이상 파일을 통째로 읽으려 하면 거부하고 요약본으로 안내**한다. Claude·Codex에는 이 거부 관문이 없었다(설치기가 한 번도 등록하지 않음: `git log -S hook-read` 결과 없음). |
| "왜 Antigravity를 대기만 시키나" | 작업트리 실행 기록 57건 중 apply 42, local 10, **agy 3**. 이 3건은 모두 연구 과제였고, 셋 다 예산 초과나 차단으로 끝났다. U95-R은 314만 토큰(상한 30만)에 EXTERNAL_WRITE, U98-D-R은 SOURCE_DIVERGED, U99-R은 40.9만 토큰(상한 20만)이었다. 편지는 claude→codex 75통, claude→antigravity 5통이었고, Antigravity가 보낸 "대기 중" 편지가 9통이었다. 반대로 범위가 정해진 읽기 전용 검증 U102-V는 **1회에 통과**했다(9/9·10/10, 반례 포함). |

결론: 원인은 도구의 능력이 아니라 **설계**였다. 역할 표가 없었고, 경계 없는 연구만 맡겼고, 알림이 한쪽으로만 흘렀다.

## 2. 외부 근거 (웹 조사)

- Anthropic, "How we built our multi-agent research system" (2025-06): 지휘자-작업자 구조에서 병렬 하위 에이전트가 연구 시간을 최대 90% 줄였다. 대신 토큰은 단일 에이전트의 약 4배, 다중 에이전트는 약 15배를 쓴다. **공유 문맥이 크거나 의존성이 많은 코딩에는 부적합**하다고 명시한다. 위임문에는 목표·출력 형식·도구·경계가 있어야 한다.
  https://www.anthropic.com/engineering/multi-agent-research-system
- Cemri et al., "Why Do Multi-Agent LLM Systems Fail?" (MAST, arXiv 2503.13657, 추적 1,642건): 실패 1·2위는 단계 반복(15.7%)과 추론-행동 불일치(13.2%)다. 종료 조건 모름(12.4%), 과제 명세 불이행(11.8%), **검증 없음·불완전(8.2%)과 잘못된 검증(9.1%)**이 뒤를 잇는다. 검증이 독립 역할로 있어야 하는 근거다.
  https://arxiv.org/abs/2503.13657
- Cognition, "Don't Build Multi-Agents" (2025-06): 행동에는 암묵적 결정이 실려 있으므로 **쓰기 작업자는 하나**여야 한다. 잘 정의된 질문에 답하는 읽기 전용 보조는 효과가 있다.
  https://cognition.ai/blog/dont-build-multi-agents
- Antigravity 자체 분석(`.coord/notes/UAOS_Multi_Agent_Orchestration_Deep_Analysis.md`, 본 저장소 main 작업본)도 같은 결론을 낸다: Builder는 Claude, Critic·Validator·Researcher는 Antigravity(행당 40k 예산).
  - 주의: 이 문서가 MAST에 있다고 적은 "Pipeline Bubble / Idle Stalling" 실패 모드는 논문의 14개 실패 모드 목록에 없다. 인용하지 않는다.

## 3. 결정: 역할 표 (단일 작성자 + 상시 독립 검증)

| 역할 | 도구 | 쓰기 | 언제 | 예산·관문 |
|---|---|---|---|---|
| 지휘·판정 | Codex(활동 시) → Claude(Codex 부재 시) | 설계·매뉴얼만 | 카드 시작·끝 | 자기 산출물 판정 금지 |
| 구현(Builder) | 지휘 도구가 발행한 pilot 작업자: Ollama(`worker: local`) → apply(≤20줄) | 소스 트리의 유일한 작성자 | 카드마다 | 고정 인수 테스트 |
| **검증(Validator/Critic)** | **Antigravity, 읽기 전용** | 자기 보고서만(main 작업본 `.coord/notes/`) | **PR이 열릴 때마다 자동 편지** | 고정 인수 재실행 + 반례 3개 이상, 1회 ≤ 직전 동형 작업의 3배 |
| 연구(Researcher) | Antigravity, 읽기 전용 | 보고서만 | 카드 기획 단계 | 결과 행당 40k 토큰 × 행 수(3~5행)로 상한을 정한다 |
| 계산기 | Ollama(olla) | 없음(제안만) | 요약·지도·초안 | 원문 대조 후 채택 |

- 병렬화는 **읽기 전용 쪽에서만** 한다. 카드 N을 구현하는 동안 Antigravity는 카드 N-1의 PR을 검증하거나 카드 N+1의 연구를 한다(Cognition·Anthropic 근거).
- Antigravity는 소스 작업트리에 쓰지 않는다. 2026-10-01에 Antigravity가 Claude 작업트리 `.coord/notes/`에 쓴 파일 때문에 pilot 실행 2회가 SOURCE_DIVERGED로 멈췄다(U103-A2). 이 규칙은 우편함으로 통보했다(relay_ee583704…).

## 4. 이번 카드에서 바뀐 것 (U103)

1. **공통 변경 알림(desk delta)** — `v7_harness/coord/desk_delta.py` (Ollama 작성, 뼈대형 매뉴얼로 1회 통과)
   - 호출한 도구(claude·codex·antigravity, 별칭 agy)를 기준으로 **자기 것만 빼고** 보여 준다. 편지 이름·`payload.actor`·커밋 서명 줄(`Co-Authored-By: Claude|Codex|Antigravity`)로 가린다.
   - 프로젝트 경로를 코드에 고정하지 않는다. 훅이 받은 프로젝트를 쓰고, 커서는 그 프로젝트의 `.coord/presence/desk_delta_<도구>_<세션>.json`(git 무시)에 둔다.
   - 항목 순서는 PLAN 상태 변화 → 다른 도구 편지 → 커밋·미커밋 변경·임대(lease)·새 보고서 파일 → pilot 실행 이벤트(한 줄로 개수만) 순이다. 최대 12줄이다.
   - 실측(2026-10-01, 이 프로젝트): 처음에는 Codex가 받은 27개 항목 중 26개가 Claude의 pilot 실행 이벤트여서 커밋이 잘렸다. 이벤트를 한 줄로 묶어 해결했다(U103-A3).
2. **세 도구 훅 연결** — `coord presence --from-hook --delta`. 설치기가 세 도구의 "지시마다" 훅에 붙인다.
   - Claude UserPromptSubmit(`--say p1 --delta`): 일반 문자열 한 줄
   - Codex UserPromptSubmit(`--say none --delta`): 일반 문자열. Codex는 이 출력을 개발자 문맥으로 받는다.
   - Antigravity PreInvocation(`--say agy --delta`): 기존 `injectSteps` JSON 안에 넣고, 턴의 첫 호출(invocationNum 0)에만 넣는다.
   - 새 소식이 없으면 아무것도 출력하지 않는다(0토큰).
3. **Ollama 대등화** — 설치기는 `olla`가 PATH에 있을 때만 다음을 등록한다.
   - Claude PreToolUse(Read) → `olla hook-read`: 8,000토큰 이상 통째 읽기를 거부하고 `local_read_map`으로 안내한다. 그보다 작은 큰 파일은 알림만 준다.
   - Codex PreToolUse(Bash) → `olla hook-shell`: `cat`·`Get-Content` 등으로 파일을 통째로 출력하면 거부하고 `olla digest`로 안내한다(신규, U103-O1R).
   - **Antigravity의 `olla-guard` 묶음은 건드리지 않는다**(테스트로 고정).
   - 퇴역했던 "매 지시 265토큰 주입"은 되살리지 않았다. 거부 관문은 큰 파일을 읽을 때만 말한다.

## 5. 다음 카드 (근거 있는 것만)

- **U104 작업 중 알림**: 지금은 사용자 지시가 올 때만 변경 알림이 나온다. Claude가 긴 자율 작업을 하는 동안 온 편지는 턴이 끝나야 보인다. Antigravity 제안서(`UAOS_Urgent_Interrupt_Architecture_Proposal.md`)의 지적은 타당하다. 해결 후보는 PostToolUse에서 P1 편지만 알리는 방식이다(실패 처리로 도구를 막는 방식은 쓰지 않는다).
- **U105 PR마다 검증 편지 자동 발송**: 지금은 사람이 기억해서 보낸다. PR이 열리면 `coord deliver --target antigravity`로 검증 매뉴얼을 보내는 단계를 만든다.
- 커밋 서명 규칙: Codex·Antigravity가 커밋할 때 서명 줄을 붙이지 않아 49개 커밋은 누가 만들었는지 가릴 수 없다. 각 도구의 규칙 파일에 서명 줄을 넣는다(Codex 복귀 뒤 합의).

## 5-1. U104 (2026-10-01, 병합 뒤 첫 사용에서 나온 결함)

- **사건**: U103-V 검증 편지(relay_2d1f…, 00:48)가 Antigravity에게 보이지 않았습니다. Antigravity는 00:54에 "편지가 오면 착수"라고 답했고, 사용자가 Claude의 보고 줄을 Antigravity에 직접 붙여 넣었습니다.
- **원인(실측)**: Antigravity 훅은 자기 앞 미처리 편지 12통 중 **파일 이름순 앞 5통**만 보여 줬습니다. 앞 5통은 모두 9/26자였고, 새 편지는 11번째였습니다. Claude는 보낸 쪽 `ok: true`만 확인했고, 받는 쪽 훅 출력은 확인하지 않았습니다.
- **수정**: 편지를 최신순으로 보여 주고, 가장 새 편지의 본문 160자를 함께 보여 줍니다(`hook_context.agy_letters/agy_line`). 실제 우편함으로 확인한 결과, 첫 항목이 relay_2d1f였고 본문도 표시됐습니다.
- **세 도구 설정 대조(Claude 대행, 값은 비밀이 없는 항목만 확인)**:

| 항목 | Claude Code | Codex | Antigravity |
|---|---|---|---|
| 규칙 | CLAUDE.md(정본 v7.3.0) | AGENTS.md(같은 정본) | GEMINI.md(같은 정본) |
| 출석·변경 알림 훅 | SessionStart·UPS `--say p1 --delta` | SessionStart·UPS `--say none --delta` | PreInvocation `--say agy --delta` |
| olla MCP | 등록·allow 3개 | 등록·`default_tools_approval_mode=approve` | 등록 |
| olla 통째 읽기 관문 | PreToolUse(Read) `olla hook-read` | PreToolUse(Bash) `olla hook-shell` | `olla-guard` 묶음(불변) |
| 편지로 깨우기 | `coord watch` 백그라운드(세션 깨움) | 교환원(sentinel) | **없음**: 사용자 지시가 올 때만 훅이 읽음 |
| 헤드리스 호출 | `worker: claude` | `codex exec` | `pilot run --worker agy`, `pilot review --reviewer agy` |

- **결론**: Antigravity는 편지만으로는 깨어나지 않습니다. 사용자 없이 일을 맡기려면 헤드리스 경로(`pilot review --reviewer agy`, `--worker agy`)를 써야 합니다. 편지는 사용자가 Antigravity 창에서 지시할 때 읽히는 보조 경로입니다.
- **첫 헤드리스 검토 실측(U104-A1)**: 108초, 172,760토큰(입력 162,380, 캐시 읽기 555,630 별도), 반례 0건. 상한 60,000을 넘어 판정은 UNUSABLE(참고 증거로도 쓰지 않음) 처리됐습니다. Antigravity 1회 호출의 고정 입력이 약 16만 토큰이므로, 검토 상한은 이 실측의 약 1.2배인 **200,000**으로 잡습니다. 표본이 1건뿐이므로 다음 3회 실측으로 다시 정합니다.

## 6. 측정 상태

- 토큰 절감: **UNMEASURED**(미측정). 거부 관문의 효과는 다음 2주 `olla stats`의 codex·claude digest·deny 수로 본다.
- 알림 누락 해소: 테스트 18+건으로 형식을 고정했다. 실제 효과는 사용자가 "다른 도구가 뭘 했는지" 붙여 넣는 횟수로 본다.
