# 68 U134 켜져 있는 도구는 반드시 편지를 받는다 (낡은 임대·조용한 사서함·잘못된 스레드 제거)

## 1. 무슨 일이 있었나 (2026-10-03, P1, 윤겸스 보고)

Codex는 데스크톱 앱에서 대답하고 있었는데(스레드 `01a1006f-…`, 06:24Z SessionStart 훅 실행) Claude의 인계 편지 `relay_18758c37`을 끝내 보지 못했다. 원인은 네 겹이었다.

1. **낡은 임대(lease)**: 2026-09-30에 손으로 적은 `coord presence --tool codex --state LIMITED --lease`가 아직 살아 있었다. presence는 살아 있는 임대가 있으면 다른 상태의 심장 박동(heartbeat)을 모두 버린다(U47-A1b). 그래서 Codex 자신의 SessionStart·UserPromptSubmit 훅이 3일 동안 무시되었고, 책상(desk)은 계속 `codex=LIMITED`라고 말했다.
2. **조용한 사서함**: `coord deliver --target codex`는 LIMITED 대상에게 보내지 않고(U113) `mailbox_only` PUBLISHED, `ok=true`를 돌려주었다. 경고도 없고, Codex가 돌아와도 다시 보내는 장치가 없었다.
3. **watch는 턴을 못 연다**: Codex의 `coord watch`는 쉘에만 알린다. 쉬는 Codex 스레드는 `codex queue`나 사용자의 다음 입력으로만 편지를 본다.
4. **스레드 이름 오류**: `--thread handoff-20261003`(자유 문장)은 `No active session found`로 실패했다. 진짜 스레드 id만 통했다.

## 2. 바뀐 동작 네 가지

| 칸 | 전 | 후 | 코드 |
|---|---|---|---|
| A 턴 시작이 임대를 지운다 | 살아 있는 LIMITED/ABSENT 임대가 모든 박동을 버림 | SessionStart·UserPromptSubmit 훅의 ACTIVE 박동(`turn_start=True`)이 같은 도구의 LIMITED/ABSENT 임대를 바꾸고 `.coord/presence/events.jsonl`에 `LEASE_CLEARED_BY_TURN` 한 줄을 남긴다. PostToolUse(턴 중간)는 여전히 못 지운다 | `presence.mark`, `hook_turn_start` |
| B 돌아오면 한 번 보낸다 | 없음 | ACTIVE 박동이 `dispatch=True`(훅 경로)면 그 도구 앞으로 쌓인 편지를 한 통씩 정확히 한 번 보낸다 | `presence._dispatch_queued`, `deliver.dispatch_queued` |
| C 대기열 응답 | `mailbox_only` PUBLISHED | `QUEUED_UNTIL_ACTIVE`(대상 = 요청한 도구), 편지는 사서함에도 그대로 있다 | `deliver._queue_until_active` |
| D 스레드 대체 | 자유 문장 스레드는 실패 | 롤아웃(rollout) 파일이 없는 스레드는 이 프로젝트의 가장 새 Codex 스레드로 바꾸고 영수증에 `thread_fallback`을 남긴다. 프로젝트 스레드가 없으면 받은 값을 그대로 쓴다 | `deliver._codex_thread` |

## 3. 왜 이렇게 만들었나 (값과 설계의 이유)

- **턴 시작만 증거로 친다**: 턴이 실제로 시작되었다는 것은 지금 한도가 남아 있다는 뜻이다. PostToolUse는 이미 진행 중인 턴 안에서 울리고, Stop·SessionEnd는 새 사실을 말하지 않는다. LIMITED 박동은 용량을 증명하지 않으므로 ABSENT 임대도 지우지 못한다.
- **이벤트 기록은 잠금을 따로 쓴다**: `_tool_lock`은 재진입이 안 되는 `threading.Lock`을 품고 있어 안에서 다시 잡으면 멈춘다. 그래서 박동 잠금을 푼 뒤 `events.jsonl` 전용 잠금으로 한 줄을 붙인다. Windows는 동시 추가(append)에서 줄을 잃기 때문에 잠금 없이 쓰지 않는다.
- **한 번만 보낸다**: 대기 표시 파일 `<사서함>/delivery/queued/<도구>/<message_id>.json`을 `os.rename`으로 `.taking`으로 바꾼 쪽만 보낸다. 이름 바꾸기는 원자적이라 동시에 울린 두 박동 중 하나는 OSError를 받고 건너뛴다(시험에서 두 스레드를 실제로 동시에 돌려 1회 확인). 보낼 때는 같은 `message_id`로 `_deliver_unlocked`를 다시 써서 accepted·ack 영수증이 중복을 막는다.
- **3번까지 다시 시도**: 보내기가 실패하면(스레드 없음, CLI 오류) 표시 파일을 되돌리고 `attempts`를 올린다. 훅 종류(SessionStart, UserPromptSubmit, PostToolUse) 하나당 한 번꼴인 3번이 지나면 `.failed`로 치워, 매 박동마다 `codex queue`를 끝없이 쏘지 않는다.
- **훅은 기다리지 않는다**: 실제 훅에서는 분리된(detached) 파이썬 프로세스가 `dispatch_queued`를 실행한다. 대기열이 비어 있으면 폴더 하나만 확인하고 끝나므로 평소 훅 비용은 거의 0이다.
- **스레드가 살아 있는지**: Codex 스레드 id는 UUID이고 롤아웃 파일 이름 끝에 붙는다. `[0-9A-Za-z-]{8,64}` 모양이고 `~/.codex/sessions/*/*/*/rollout-*-<id>.jsonl`이 있으면 살아 있다고 본다. 시험은 `UAOS_CODEX_SESSIONS`로 실제 PC 기록을 건드리지 않는다.

## 4. 허용 범위 밖 변경 한 곳 (cli.py)

카드 매뉴얼의 허용 파일에는 `cli.py`가 없다. 그러나 훅 입력(`hook_event_name`)은 `cmd_coord_presence --from-hook`에서만 읽히므로, 그곳에서 `turn_start=hook_turn_start(stdin) and not --post-tool`, `dispatch=True`를 넘기는 두 줄과, `coord deliver`가 `QUEUED_UNTIL_ACTIVE`를 실패(종료 코드 1)로 보지 않게 하는 한 단어를 바꿨다. 고정 인수 시험 `test_the_cli_hook_clears_the_lease_on_session_start_only`가 이 경로를 요구한다.

## 5. 함께 고친 기존 시험

`tests/test_u113_desk_truth.py`, `tests/test_u115_card_window_route.py`는 LIMITED/ABSENT 대상에게 `("mailbox_only", "PUBLISHED")`를 기대했다. C가 바로 이 응답을 바꾸는 요구이므로 `(<도구>, "QUEUED_UNTIL_ACTIVE")`로 고쳤다. 두 파일은 카드 매뉴얼의 허용 목록 밖이지만, 사용자 창이 목표 C에 맞는 변경으로 인정해 허용 목록에 이 이유와 함께 추가했다(2026-10-03). "보내지 않는다"(runner 호출 0회)와 "사서함에 남는다" 검사는 그대로다. 자동 판별(대상 없음)의 `mailbox_only`는 바뀌지 않았다(U61, U71 시험).

분리 프로세스 발송(`presence.py`의 `subprocess.Popen`)은 새 실행 지점이므로 U54 방화벽 감사가 다시 하라고 요구했다. `docs/51`에 FIXED_PLAN 판정 한 줄(실행 파일은 지금 파이썬, 스크립트는 상수, 프로젝트 경로와 도구 이름만 값)을 더하고 `tests/test_u54_s2_caller_review.py`의 검토 목록을 갱신했으며, `python -m v7_harness.firewall_audit --write`로 `docs/50`을 다시 만들었다(다른 카드가 옮긴 `agy_dispatch.py`·`windows.py` 줄 번호도 함께 맞춰짐).

## 6. 한계

- Claude 대상 카드 편지는 대기열에서 나갈 때 카드 창(세션) 대신 기본 경로(감시자 대기 또는 헤드리스)로 간다. 창을 넣으면 `message_id`가 바뀌어 중복 방지가 깨지기 때문이다.
- Antigravity는 바뀌지 않았다: 여전히 U120 헤드리스 자동 응답 경로를 쓴다. Antigravity 훅 입력에는 `hook_event_name`이 없을 수 있어 A(임대 지우기)가 동작하지 않을 수 있다. Antigravity 설계 감사(relay_fa9c73db, PASS)가 `--turn-start` 플래그를 권했지만, 실사용 실패 영수증이 아직 없어 후보로만 남긴다.
- 정전·강제 종료로 `.taking` 파일이 남으면 그 편지는 다시 보내지지 않는다. 같은 감사가 정리(sentinel) 단계를 권했으며, 이것도 영수증이 생기면 카드로 연다.

## 7. 위임 기록 (pilot)

- U134-L1 Ollama(`worker: local`) presence.py: 인수 16개 통과, 입력 2,384·출력 1,502토큰. 다만 새 상수 3개의 이유 주석을 빠뜨려 L4에서 보충했다.
- U134-L2 Ollama deliver.py: 실패. 응답이 출력 상한 8,192토큰에서 `deliver` 중간에 잘렸다(입력 11,927). 같은 실행 중 판정자가 이 문서와 매뉴얼을 소스에 써서 SOURCE_DIVERGED도 함께 났다(잡파일은 실행 중 소스 밖에 둘 것).
- U134-L4 정확 적용(`worker: apply`, `apply_after: U134-L2`) deliver.py·presence.py·cli.py: 인수 82개 통과, Antigravity 코드 검토 PASS(입력 30,366·출력 6,027), 승인 적용.
- 설계 감사: Antigravity relay_fa9c73db PASS(입력 23,956·출력 2,446).

## 8. 확인 명령

```bash
python -m unittest tests.test_u134_lease_cleared_by_turn tests.test_u134_dispatch_on_active tests.test_u134_thread_fallback -v
```
