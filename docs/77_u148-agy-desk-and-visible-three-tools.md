# U148: Antigravity도 사용자 창을 갖고, 상태줄에 올라마·Antigravity 몫이 보인다

## 왜 만들었나 (실패 영수증, 2026-10-04)
윤겸스가 물었다.
1. "안티그래비티 사용자 창 등록 방식이 가동 안하니?"
2. "왜 안티그래비티를 제외하고 코덱스랑 클로드만 티키타카를 하니?"
3. "올라마를 토큰예산절약 모드로 사용하는 게 안 보인다."

조사해 보니 원인이 셋이었다.
- **1번 원인**: U147-D의 사용자 창 등록은 `UserPromptSubmit` 훅에서만 일어난다. Claude Code와 Codex에는 이 훅이
  있지만 Antigravity에는 없다. Antigravity가 부르는 훅은 `PreInvocation`(모델을 부르기 직전) 하나다.
  게다가 `USER_DESK_TOOLS`가 `("codex", "claude")`라서 Antigravity는 처음부터 빠져 있었다.
- **2번 원인**: Antigravity에게 보낸 편지는 깨움 표시(아래 "깨움 표시")가 있을 때만 헤드리스 Antigravity가
  답한다(U120). 표시가 없는 편지는 조용히 우편함에만 놓이고 아무도 읽지 않았다(relay_dd121587). 또 헤드리스가
  답을 해도 그 사실이 윤겸스가 보는 Antigravity 데스크톱 창이나 상태줄 어디에도 나오지 않았다.
- **3번 원인**: 올라마는 실제로 쓰였다(오늘 pilot_local 조각, read_map, digest 등). 하지만 사용 기록
  `~/.cache/olla/usage.jsonl`을 화면에 보여 주는 곳이 없었다.

## 무엇이 바뀌나
1. **Antigravity 사용자 창 등록** (`v7_harness/coord/deliver.py`, `v7_harness/cli.py`)
   - `USER_DESK_TOOLS`에 `antigravity`를 넣었다.
   - `agy_desktop_conversation(id)`: 대화 id가 데스크톱 앱의 대화인지 본다.
     - 앱은 `~/.gemini/antigravity/conversations/<id>.db`와 `brain/<id>/`를 만든다.
     - 헤드리스 CLI는 `~/.gemini/antigravity-cli/` 아래 따로 둔다. 그래서 CLI에만 있는 id는 사용자 창이 아니다.
     - 2026-10-04 확인: 2c573cc3(앱), ae1af179(CLI).
   - **훅은 사용자 창을 절대 쓰지 않는다**(Codex 검토 두 번: codex_u148_design_changes_human_origin_20261004,
     codex_u148_c1_human_origin_gate_unmet).
     - 처음 설계는 `PreInvocation` 훅의 첫 호출(`invocationNum` 0)에서 앱 대화를 사용자 창으로 등록했다.
     - 그러나 `invocationNum` 0은 하위 에이전트, 재시작, 자동 이어 하기에서도 생긴다. 페이로드의 어떤 값도
       "윤겸스가 이 창에서 직접 쳤다"를 증명하지 못한다. 빠진 prompt나 0을 사람으로 칠 수 없다.
     - 그래서 훅은 등록하지 않고, 깨진(INVALID) 기록도 고치지 않는다. 기존 등록을 읽기만 한다.
     - 대신 첫 호출마다 페이로드의 키 이름만(값은 절대 아님) `.coord/presence/agy_hook_keys.json`에 남긴다.
       앞으로 사람 입력을 증명하는 필드가 실제로 있는지 확인하는 증거다.
   - **등록과 옮기기는 명시 등록**으로만 한다(유지되는 경로):
     `python ~/.uaos/uaos.py coord presence --tool antigravity --desk-thread <대화 id> --project <루트>`
     - 앱 대화 id만 받는다(CLI 대화·잘못된 id·다른 도구는 종료 코드 2). 기록의 `source`는 `explicit`.
     - 사용자 창이 없거나 깨진 상태에서 앱 대화의 첫 호출이 오면, 훅 문장이 Antigravity 모델에게 이 명령을
       알려 준다. 조건은 "윤겸스가 직접 이 대화에 치고 있을 때만"이다. 사람 말을 직접 보는 것은 그 대화의
       모델뿐이라서 판단을 모델에게 맡기고, 훅은 추측하지 않는다.
   - Windows에서 두 프로세스가 같은 파일을 동시에 바꾸면 `os.replace`가 거부된다. 그래서 50ms 간격으로
     20번(최대 1초) 다시 시도하고, 끝내 안 되면 임시 파일을 지우고 False를 돌려준다(병렬 8프로세스 테스트).
2. **사용자 창은 헤드리스 답장을 듣는다** (`v7_harness/coord/hook_context.py`)
   - Antigravity 사용자 창 대화의 훅 문장에 오늘 헤드리스가 보낸 답장 수와 가장 최근 편지 id를 붙인다.
   - 검증된 것은 **훅 출력(hook context)에 이 문장이 들어간다**는 것까지다(시험으로 확인). 이 문장이 윤겸스 화면에도
     보이는지는 **관찰하지 못했다(UNKNOWN)**. Antigravity 검토(relay_39c3f5be)는 "모델 전용"이라고 했지만 헤드리스의
     자기 보고라 증거가 아니다. 그래서 문장은 모델에게 "다음 답의 첫 줄에 이 답장들을 한 줄로 말하라"고 시킨다.
   - 배달 상태: **배달 완료가 아니다.** 모델의 다음 답에 그 줄이 보이기 전까지는 **소비 대기(pending
     consumption)**다. 받는 쪽 훅 출력이 보여야 배달로 친다(전역 규칙).
3. **상태줄에 올라마·Antigravity 몫** (`v7_harness/coord/board.py`, `v7_harness/coord/agy_dispatch.py`)
   - Claude Code와 Codex의 상태줄 문장(`status_line`, 훅이 `systemMessage`로 내보냄) 끝에
     `· 올라마 오늘 N회 · Antigravity 답장 M통`이 붙는다. 문장 내용은 시험으로 확인했고, 앱 화면에 실제로
     보이는지는 아직 관찰하지 못했다(UNKNOWN).
   - 하루의 기준은 **Asia/Seoul**(UTC+9 고정)이다. 한국은 1988년 이후 일광 절약 시간이 없고, Windows 파이썬은
     tzdata 패키지가 없으면 시간대 DB가 없어서 고정 오프셋을 쓴다.
   - **올라마 호출**: 사용 기록에서 `ask, edit, digest, find, pilot_local, pilot_local_repair` 행만 센다.
     - 힌트·계획·턴 모양(`hint_plan`, `turn_shape` 등)은 모델 호출이 아니라서 안 센다.
     - 올라마는 호출 id를 남기지 않으므로 행 하나가 호출 하나다(중복 제거 없음).
     - 실패한 호출(`ERROR`)도 모델이 돌았으므로 센다. `PROMPT_TOO_LARGE`는 모델을 부르기 전의 사전 거절이라
       안 센다.
     - 10회가 넘으면 "10회 이상", "20회 이상"처럼 10 단위로 보여 준다. 매 호출마다 상태줄이 바뀌어
       알림이 늘어나는 것을 막기 위해서다.
   - **Antigravity 답장**: `.coord/mailbox/delivery/agy_auto.jsonl`의 `ANSWERED` 행. 같은 편지에 두 번 답했으면
     한 통으로 센다. `FAILED`는 답장이 아니다.
   - **토큰 절약량은 측정하지 않았다(UNMEASURED)**. 이 숫자는 호출 횟수이지 절약한 토큰이 아니다.

## 깨움 표시 (Antigravity에 편지를 보낼 때)
헤드리스 Antigravity는 아래 표시 중 하나가 있는 편지에만 답한다(하루 20통, 한 통에 약 28k 토큰).
`ACTIONABLE_DELTA`, `VERDICT_REQUESTED=YES`, `APPROVAL_REQUIRED`, `P1=YES`.
표시가 없으면 편지는 우편함에 놓이기만 하고 답이 오지 않는다.

## 아직 모르는 것 (UNKNOWN)
- 실제 데스크톱 페이로드에 `prompt`/`userPrompt`가 있는지: `agy_hook_keys.json`으로 수집 중.
- `ephemeralMessage`가 사용자에게 보이는지: Antigravity는 "모델 전용"이라고 답했다. 헤드리스의 자기 보고라
  증거가 아니다. 데스크톱에서 직접 관찰해야 한다.
- 배달 방식은 다음 차례에 끌어오기(pull)뿐이다. Antigravity 데스크톱 창을 밖에서 깨우는(push) 경로는 없다.

## 시험
`python -m unittest tests.test_u148_agy_desk_visible tests.test_u148_hook_registers_nothing`
- 앱 대화만 사용자 창이 될 수 있다. CLI·나중 호출·잘못된 id·pilot 작업자는 아무것도 쓰지 않는다.
- 어떤 페이로드도 등록하지 않는다: prompt 없음, invocationNum 없음, 재시작, 자동 이어 하기, 하위 에이전트,
  사람처럼 보이는 prompt. 깨진 기록은 명시 등록 전까지 INVALID로 남는다. 기존 등록은 바이트 하나 바뀌지 않는다.
- 사용자 창이 없을 때만 훅 문장이 명시 등록 방법을 알려 준다.
- 처음 고정했던 시험(sha a1712a8b) 가운데 재설계와 맞지 않는 것은 지우지 않고 `REPLAN` 표시와 함께 바꿨다.
- 병렬 8프로세스 24번 등록 뒤 기록 하나가 OK이고 임시 파일이 남지 않는다.
- 서울 기준 하루, 같은 편지 한 번, 사전 거절 제외, 깨진 기록은 0.

## 구현 경로
명세 → 올라마(`worker: local`) 조각 D1·A1·A2·B1·H1·C1·C2 → 판정자 시험 → Codex 판정. Antigravity는 설계를
검토했다(relay_39c3f5be).
