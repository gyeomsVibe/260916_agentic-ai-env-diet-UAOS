# U147: Codex 편지는 사용자 창으로 가고, 3도구 상태판으로 지금 누가 일하는지 본다

## 왜 만들었나 (실패 영수증, 2026-10-04)
- Claude가 Codex에 보낸 편지 relay_54d2ee83·relay_cf68f9ce는 DISPATCHED였지만, 윤겸스가 보던 Codex 창(01a102e7)에는 아무 반응이 없었다.
- 실제로는 백그라운드 Codex 창(01a1006f)에 들어갔고, 그 창이 9초 만에 "중복 처리"라고 답했다.
- **근본 원인**: `deliver.py`는 `--thread`가 없으면 "가장 최근에 기록된" Codex 세션 파일(rollout)을 골랐다.
  - 편지를 받은 창은 그 순간 파일이 갱신되어 다시 "가장 최근"이 된다.
  - 그래서 한 번 다른 창으로 간 편지는 이후에도 계속 그 창으로만 갔다(되먹임 고리).
- 윤겸스는 세 도구가 PC 앱에서 지금 일하는 중인지 볼 방법이 없었다. 상태판은 설계 문서만 있고 구현이 없었다.

## 무엇이 바뀌나
1. **편지는 사용자 창으로 간다** (`v7_harness/coord/deliver.py`)
   - `last_human_input(rollout)`: 사람이 직접 입력한 마지막 시각을 찾는다.
     - 사람 입력으로 치지 않는 것: `[UAOS relay`, `[DATA]`, `# AGENTS.md`, `<...>`로 시작하는 주입 문장.
   - **지정된 사용자 창(user desk)이 먼저다** (U147-D, 아래 4번).
   - 지정된 창이 아직 없을 때만 `_newest_verified_thread`가 처음 한 번 추정한다(bootstrap).
     - 이 프로젝트로 검증된 창 가운데 사람이 마지막으로 입력한 창을 고른다.
     - 사람 입력이 하나도 없으면 예전처럼 가장 최근에 기록된 창을 고른다.
     - 세션 파일이 500개(`ROUTE_SCAN_MAX`)를 넘으면 추정하지 않는다. 편지는 보내지 않고 우편함에 남는다(NO_VERIFIED_THREAD).
   - 배달 영수증(`delivery/accepted/<id>.json`)에 실제로 보낸 창 `thread`를 남긴다. 잘못 배달되면 바로 보인다.
2. **3도구 상태판** (`v7_harness/coord/board.py`, 유료 토큰 0)
   - 각 앱이 직접 쓰는 기록만 읽는다. 도구가 스스로 보고하는 상태는 쓰지 않는다.

     | 도구 | 읽는 기록 | 판단 기준 |
     |---|---|---|
     | Codex | `~/.codex/sessions` rollout의 task_started / task_complete | 시작 뒤 완료가 없으면 "작업 중", 사용자 창 표시 |
     | Claude Code | `~/.claude/projects/<프로젝트>*/*.jsonl` | 120초 안에 기록되었으면 "최근 기록" |
     | Antigravity | 앱 `~/.gemini/antigravity/brain/*/…/transcript_full.jsonl`, CLI(pilot 검토·감사) `~/.gemini/antigravity-cli/brain/…` | 120초 안에 기록되었으면 "최근 기록(전체 프로젝트)" |
     | 우편함 | 최근 편지 6통, 도구별 대기 편지 수 | 편지마다 받은 창 표시 |

3. **앱 안의 한 줄 알림** (`board.status_line`, `cli.py coord presence --delta`, 유료 토큰 0)
   - 각 도구의 기존 훅(UserPromptSubmit·PostToolUse)이 사용자에게 한 줄을 보여 준다.
     - 예: `[UAOS] 📬 새 편지 1통: Codex verdict PASS | Codex 작업 중 · Antigravity 대기`
   - 출력 필드는 `systemMessage`다. 사용자 화면에만 보이고 모델 문맥에는 들어가지 않는다.
   - 언제 보이나:
     - 편지가 오면 항상 보인다.
     - 다른 두 도구의 상태(작업 중/대기)가 바뀔 때만 다시 보인다. 시각은 넣지 않아 같은 상태로는 반복되지 않는다.
   - 도구별 지원:
     - Claude Code: `systemMessage`를 보여 준다.
     - Codex: 훅 출력 형식이 Claude와 같다. 실제 화면 표시는 설치 뒤 Codex 창에서 확인해야 한다(**UNKNOWN**).
     - Antigravity: 사용자에게 보이는 훅 필드가 확인되지 않았다(**UNKNOWN**). 기존처럼 모델 쪽 줄만 넣는다.

4. **지정된 사용자 창 (U147-D, Codex 검토 relay_6dfa9184·relay_ef4ac44f)**
   - 왜 바꿨나: 추정만으로는 같은 원인의 실패가 두 번 났다.
     - 1차: "최근 12개"만 보면, 사용자 창 뒤에 편지만 받는 창이 12개 넘게 생길 때 사용자 창이 빠졌다.
     - 2차: "최근 7일, 최대 500개"로 늘려도, 편지만 받는 창이 500개면 다시 빠졌다. 7일 제한은 조용한 창도 버렸다.
     - 그래서 상한을 키우지 않고, 사용자 창을 **명시적으로 등록**하는 방식으로 바꿨다.
   - 등록 규칙(수명 주기):
     - 언제: 각 도구의 `UserPromptSubmit` 훅이 **사람이 직접 친 입력**을 받을 때.
       - 주입 문장(`[UAOS relay`, `[DATA]`, `# AGENTS.md`, `<...>`)으로는 등록되지 않는다.
     - 무엇을: 훅 입력의 `session_id`. Codex에서는 이것이 창(thread) UUID다(2026-10-04 presence 기록으로 확인).
     - 어디에: `.coord/presence/user_desk_<도구>.json`. 도구마다 파일이 따로라 서로 덮어쓰지 않는다.
       - 임시 파일에 쓴 뒤 `os.replace`로 바꾼다. 읽는 쪽은 반쯤 쓴 기록을 보지 않는다.
     - 바뀔 때: 사용자가 다른 창에서 입력하면 그 창으로 바뀐다. 같은 창이면 다시 쓰지 않는다.
     - 순서: 훅은 **먼저 등록하고, 그다음 ACTIVE 표시**를 한다(Codex 검토 relay_48fb8d38).
       - ACTIVE 표시는 기다리던 편지를 보낸다. 거꾸로 하면 새 창의 첫 입력 때 대기 편지가 옛 창으로 갔다.
   - 배달 규칙:
     - `--thread`가 올바르면 그 창. 카드 창 경로(U115)도 그대로다.
     - 아니면 지정된 사용자 창. 배달할 때마다 UUID·세션 파일·프로젝트 경로를 다시 확인한다.
     - 확인에 실패하면(파일 없음, 다른 프로젝트) **USER_DESK_STALE로 멈춘다**. 추정한 다른 창으로 보내지 않는다.
       - 편지는 우편함에 남고, 사용자가 다음에 입력하면 새 창이 등록된다.
     - 기록 파일이 **없을 때(ABSENT)만** 추정(bootstrap)을 쓴다.
       - 파일이 있는데 읽을 수 없거나(깨진 JSON, 읽기 실패) 올바른 UUID가 없으면(INVALID) 역시 USER_DESK_STALE로 멈춘다.
       - 깨진 기록 때문에 지정 창의 편지가 추정한 다른 창으로 새지 않게 하려는 것이다.
     - 사용자 창으로 보내다 실패해도 다른 창으로 다시 보내지 않는다.
   - 상태판은 편지가 실제로 갈 창(`_codex_thread(project, "")`)을 "사용자 창"으로 표시한다.
   - 반례 2 (U147-R): Claude·Antigravity의 상태는 파일 기록 시각으로 추정한 것인데 "작업 중"으로 보였다.
     - 고친 뒤: 둘은 "최근 기록"으로 표시한다. "작업 중"은 앱이 직접 남긴 시작·완료 기록이 있는 Codex만 쓴다.
     - Antigravity 대화 기록에는 프로젝트 폴더가 적혀 있지 않다(2026-10-04 확인). 그래서 "(전체 프로젝트)"를 붙인다.
   - 반례 테스트는 고정 테스트와 따로 `tests/test_u147_route_counterexamples.py`에 둔다.

## 쓰는 법
```
python -m v7_harness.coord.board --project <프로젝트>              # 한 번 출력
python -m v7_harness.coord.board --project <프로젝트> --watch 5    # .work/board/index.html 을 5초마다 갱신
```
- `--watch`로 만든 페이지는 브라우저에서 5초마다 저절로 새로고침된다.

## 한계
- Claude와 Antigravity의 "최근 기록"은 파일이 기록된 시각일 뿐, 실행 중이라는 증거가 아니다.
  - 2분 넘게 한 줄도 쓰지 않고 생각하면 "대기"로 보인다.
- Antigravity 대화는 프로젝트별로 나누지 않는다(전체 프로젝트). 최근 24시간 대화를 보여 준다.
- Codex 훅 입력에 `prompt` 필드가 없으면 자동 등록이 되지 않는다. 그때는 추정(bootstrap)만 동작한다(**UNKNOWN**, 설치 뒤 확인).
- 앱이 `systemMessage`를 사용자 화면에 실제로 보여 주는지는 Claude 외에는 확인되지 않았다(**UNKNOWN**).
- `uaos coord board` 명령은 아직 없다. `cli.py`는 #111·#112가 수정 중이라 겹치지 않게 모듈 실행만 제공한다.

## 검증
- 고정 인수 `tests/test_u147_user_window_board.py` 6개
  - 주입 문장 제외
  - 사용자 창 배달 + 영수증의 thread
  - 사람 입력이 없을 때 예전 동작
  - 상태판의 작업 중 판정
  - 앱 안 한 줄: 편지는 항상, 상태는 바뀔 때만
  - 훅이 `systemMessage`로 사용자에게 보여 주고, 변화가 없으면 조용함
- 반례 테스트 `tests/test_u147_route_counterexamples.py` (고정 테스트와 별도)
  - 편지만 받는 창 15개 뒤에도 사용자 창으로 배달
  - 상한 초과(500개) 때: 지정 창이 없으면 보내지 않고 멈춤, 지정 창이 있으면 그 창으로 배달
  - 지정 창이 더 최근 사람 입력보다 우선, 낡은 지정 창은 멈춤, 실패해도 다른 창으로 재전송 안 함
  - 훅은 사람 입력만 등록(relay·DATA는 무시)
  - 깨진 JSON·dict 아님·thread가 문자열 아님·UUID 아님·읽기 실패는 INVALID로 멈춤, 파일 없음만 추정 허용
  - 옛 창 등록 + 대기 편지 + 새 창의 사람 입력 → 대기 편지는 새 창으로
  - "최근 기록"·"(전체 프로젝트)" 표시, Antigravity CLI 기록 경로
