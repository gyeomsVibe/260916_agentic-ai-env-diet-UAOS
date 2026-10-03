# 67 U130 기본 카드 파이프라인: 모든 카드에 Ollama와 Antigravity를 넣는 운영체제 관문

> 초안: Ollama `local_draft`(2026-10-02), 판정자 Claude가 사실 확인·정정. 근거 파일: `.work/cards/U130_research.md`, `.work/cards/U130_frame.md`.

## 1. 왜 만들었나

윤겸스는 같은 지시를 일곱 번 했다(09-18 Antigravity 구동, 09-19 pilot 구현, 09-23 Ollama 계산기·agy/local 위임, 09-28 한도 압박 시 Ollama, 09-30 U98-D, 10-02 U123 우회, 10-02 이 카드): "계획에 Ollama와 Antigravity를 항상 넣는 운영체제를 만들어 다시 말하지 않게 하라." 원인은 다섯 가지였다.

- R1 위치: "20줄 넘는 코드는 Ollama·Antigravity 먼저"가 Claude 어댑터에만 있었다. 기본 지휘자 Codex의 어댑터는 순서 없이 나열했고 Antigravity 어댑터에는 없었다.
- R2 시점: 강제는 끝(U98-D 매뉴얼 lint, U123 커밋 관문)에만 있었다. 계획·카드를 여는 순간에는 아무것도 요구하지 않았다.
- R3 자유 형식 카드: `uaos coord window --prompt-file`은 아무 매뉴얼이나 받았다. U129 매뉴얼은 조사·설계를 유료 Claude 창에 두고 Ollama 단계가 없었다.
- R4 기억에 의존: 지시가 Claude 기억(memory) 여섯 곳에만 있어 Codex·Antigravity는 보지 못했다.
- R5 조용한 창 실패: `claude --bg` 창이 로그인 만료로 3.4초 만에 죽어도 아무도 몰랐다. U129가 `claude --bg` 실행 자체를 없앴으므로(보이는 데스크톱 세션만 기록) 이 카드는 U129 설계를 그대로 쓴다.

## 2. 네 단계 틀

`uaos card new`가 쓰는 매뉴얼에는 아래 네 칸이 있고, 각 칸에 기본 작업자(`Workers:` 줄)가 적혀 있다.

| 단계 | 기본 작업자 | 산출물 |
|---|---|---|
| Stage 1 Research(조사) | 지휘자가 웹 검색 → Ollama `local_draft`가 출처마다 한 줄 요약 → Antigravity가 출처 목록 감사 | `.work/cards/<카드>_research.md` |
| Stage 2 MIA(판단) | 지휘자가 Frame/Review/결정 → 300줄 넘는 파일은 Ollama `local_read_map` 먼저 → Antigravity 설계 감사 | `.work/cards/<카드>_frame.md` |
| Stage 3 Execute(실행) | Ollama(`pilot run`, `worker: local`) 먼저 → 다파일·Ollama 실패는 Antigravity → `worker: apply`는 U98-D일 때만 | pilot 실행 `<카드>-L<n>` |
| Stage 4 Verify(검증) | 고정 인수 + 전체 테스트 → Antigravity 검토(`pilot review --reviewer agy`) → 커밋 메시지는 Ollama `local_draft` | `uaos card audit` 통과 후 PR |

## 3. 명령

카드 매뉴얼과 카드 기록(`.coord/cards/<카드>.json`, 시작 시각)을 만든다. 이미 있으면 덮어쓰지 않는다.

```bash
uaos card new --card U130 --title "제목"
```

이 세션의 Ollama 호출(`~/.cache/olla/usage.jsonl`) 가운데 카드 시작 이후의 실제 모델 호출만 장부(`.coord/usage/runs.jsonl`)에 `<카드>-olla-<n>` 행으로 옮긴다. 한 호출은 한 카드만 가져간다.

```bash
uaos card claim --card U130 --session <세션 id>
```

Ollama나 Antigravity를 못 쓴 칸을 증거와 함께 기록한다.

```bash
uaos card skip --card U130 --slot ollama --reason OLLAMA_DOWN --evidence "..."
```

카드에 실제 Ollama 호출과 Antigravity 감사·검토(또는 인정된 건너뛰기)가 있는지 보고, 없으면 0이 아닌 값으로 끝난다.

```bash
uaos card audit --card U130
```

## 4. 관문

- 커밋 관문(`.githooks/commit-msg` → `calculator_gate`): `v7_harness/`나 `uaos_everywhere/` 아래 새 `.py`가 들어간 커밋은 카드(`Card: U##` 줄, 없으면 `u<숫자>` 브랜치)의 감사가 통과해야 한다. 실패하면 `CARD_AUDIT:` 줄이 빠진 칸을 알려 준다.
- `uaos coord window`: 네 단계 칸이나 `Workers:` 줄이 빠진 매뉴얼로는 창을 열지 않는다(종료 코드 2).
- `uaos rsi ship --card U##`: 감사가 통과하지 않으면 PR을 만들지 않는다.

## 5. 건너뛰기 규칙

- `OLLAMA_DOWN`: 기록하는 순간 `http://127.0.0.1:11434/api/tags` 확인이 실패해야 한다(Ollama가 켜져 있으면 `OLLAMA_UP`으로 거부).
- `AGY_LIMITED`: 책상(presence)의 Antigravity 상태가 `LIMITED`나 `ABSENT`여야 한다.
- `TASK_CLASS`: 20자 이상의 증거가 필요하고, 카드가 `.py`를 바꾸면 Ollama 칸에는 인정되지 않는다(코드를 바꾸면서 "Ollama가 못 하는 일"이라고 주장할 수 없다).

## 6. Antigravity 감사 반영

- relay_92fa8200(카드 대화, REVISE): 가져가기 시각 제한, 코드 카드의 TASK_CLASS 무효, `uaos_everywhere/` 포함, 검토 파일은 종결 판정(PASS/REVISE/FAIL)만 인정 — 모두 반영.
- relay_25e176ee(Antigravity 앱, PASS+강화): 시각 제한 반영. 50자+판정자 서명, `.coord/tasks/*.md` 관문, "자율 작업 당김" 제안은 근거(실사용 실패 영수증)가 없어 U131 후보로 보류.

## 7. 출처

- S1 FrugalGPT: https://arxiv.org/abs/2305.05176
- S2 RouteLLM: https://arxiv.org/abs/2406.18665
- S3 Claude Code hooks: https://code.claude.com/docs/en/hooks
- S4 Codex AGENTS.md: https://developers.openai.com/codex/guides/agents-md
- S5 git hooks: https://git-scm.com/docs/githooks
- S6 Ollama API: https://github.com/ollama/ollama/blob/main/docs/api.md
- S7 Antigravity CLI headless: https://antigravity.google/docs/cli/headless
