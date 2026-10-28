# U146 논스톱 연쇄: 세 도구가 사용자 지시 없이 다음 카드로 이어 달리는 방법

> 상태: U146-A 구현(Claude 대행 지휘, Codex LIMITED — Codex 재검토 대상). U146-B(임대·예산·Codex/Antigravity 자동 관문)는 다음 카드다.

## 1. 왜 필요한가 (영수증)

2026-10-04 U141-A 진행 중 윤겸스는 단계마다 "계속"을 직접 입력해야 했다("중간에 사용자 지시 받지 말라고 몇번 말했나?").
원인은 두 가지였다.

- **S2 카드 끝 정지:** 카드·PR을 마치면 도구가 "다음:" 보고를 쓰고 턴을 끝냈다. 다음 카드를 고르는 결정적(deterministic) 출처가 없었다.
- **S3 판정 대기 정지:** Codex 판정(verdict)을 기다리는 카드가 있으면 그 뒤 카드도 시작하지 않았다.

## 2. 구성 요소

| 부품 | 파일 | 하는 일 |
|---|---|---|
| 다음 카드 출처 | `v7_harness/coord/next_card.py` | 메인 체크아웃의 `.coord/master_schedule.json`만 읽고 `NEXT`·`HANDOFF`·`WAIT`·`HUMAN`·`DONE` 중 하나를 돌려준다 |
| 종료 관문 | `v7_harness/coord/stop_gate.py` `gate` | 내 몫의 NEXT가 있으면 턴 종료를 한 번 막는다 |
| push 허가 확인 | `v7_harness/coord/stop_gate.py` `push_check` | `.coord/grants/push.json`이 허락한 기능 브랜치만 ALLOW |
| 명령 | `uaos coord next`, `coord stop-gate`, `coord push-check` | 위 세 함수를 셸에서 부른다 |
| Claude 훅 | `.claude/settings.json` `Stop` | 턴이 끝날 때마다 `coord stop-gate --tool claude` 실행 |

## 3. 일정 파일 읽는 법

`phases`의 각 항목은 `phase_id`, `state`, `owner_tool`, `depends_on`을 가진다.

- 의존 카드가 `DONE` 또는 `REVIEW`이면 충족이다. `REVIEW`는 판정만 기다리므로 그 위에 쌓아 시작할 수 있다(S3 해결).
- 후보는 `READY`·`PLANNED`이면서 의존이 모두 충족된 카드다. `ACTIVE`는 이미 누가 달리고 있으므로 후보가 아니다.
- `owner_tool`이 나 또는 `all`이면 내 카드(`NEXT`), 아니면 넘길 카드(`HANDOFF`)다. 내 카드가 먼저다.
- 후보가 없으면: 남은 카드가 전부 `HUMAN`이면 `HUMAN`, 남은 것이 없으면 `DONE`, 그 밖에는 `WAIT`.

## 4. 레드팀이 추가한 안전장치

- **R2 push 허가:** 허가 파일이 없거나 깨졌거나 `enabled`가 아니면 DENY. main·master, 강제 push, 패턴 밖 브랜치도 DENY. `coord push-check`는 DENY면 종료 코드 3을 내서 `uaos coord push-check ... && git push` 사슬을 멈춘다. 병합은 여전히 사람만 한다.
- **R3 선점(claim):** `--claim`은 `.coord/next/claims/<카드>.json`을 배타 생성(O_EXCL)으로 만든다. 다른 살아 있는 프로세스(생성 시각까지 일치)가 가진 카드는 건너뛰고, 죽은 선점은 교체한다.
- **R4 판정 대기 쌓기 상한:** REVIEW 사슬이 3단(`MAX_REVIEW_STACK`)이면 더 쌓지 않고 Codex 판정을 기다린다. 기반 하나가 거절되면 위의 카드가 모두 재작업되기 때문이다.
- **R5 정본 하나:** 작업 트리(worktree)마다 다른 일정을 보지 않도록 git 공통 디렉터리의 부모(메인 체크아웃)에서 읽는다.
- **진척 없는 반복 차단(Antigravity 감사 relay_5d1e13d0 [HIGH]):** 막기 한 번은 전체 문맥을 다시 읽는 유료 턴이다. 커밋·일정 상태 변경·새 pilot 실행이 없으면 두 번째부터는 `.coord/log/stop_gate.jsonl`에 BLOCKED를 남기고 종료를 허용한다. 장부 줄·결과 파일·로그는 진척으로 치지 않는다.

## 5. U146-B로 닫은 한계

- **R6 세션 임대:** U146a-R(PR #112)에서 선점이 Stop 훅의 세션 ID에 묶이고 `CLAIM_TTL_S`(7200초) 뒤 만료된다.
- **세 도구 자동 관문:** 전역 설치가 Claude(`~/.claude/settings.json`)·Codex(`~/.codex/hooks.json`)·Antigravity(`~/.gemini/config/hooks.json`)의 Stop 훅에 `uaos coord stop-gate --tool <도구> --from-hook`을 넣는다. 이 저장소처럼 프로젝트 `.claude/settings.json`에 자기 관문 훅이 있으면 Claude 전역 훅은 비켜서서 한 번의 종료는 한 번만 막힌다(Antigravity 감사 relay_45d07985). 프로젝트는 훅 입력(`cwd`, `workspacePaths`)에서 찾고, UAOS 프로젝트 밖이나 pilot 작업자(`UAOS_WORKER`) 안에서는 아무것도 출력하지 않는다. 세션은 `session_id`(Claude·Codex) 또는 `conversationId`(Antigravity)다. 붙잡는 답은 Codex `{"decision": "block"}`(https://learn.chatgpt.com/docs/hooks), Antigravity `{"decision": "continue"}`(https://antigravity.google/docs/hooks)이고, Antigravity가 `fullyIdle: false`로 멈추면 붙잡지 않는다.
- **헤드리스 실행은 세션이 아니다:** pilot agy 작업자·검토·판정·Antigravity 자동 답장·병합 위임은 모두 `UAOS_WORKER=1`로 띄우므로 Stop 관문이 붙잡지 않는다(pilot agy 작업자 누락은 Antigravity 감사 relay_3e404354로 보강).
- **R7 예산:** 붙잡기 한 번은 전체 문맥을 다시 읽는 유료 턴이다. 자기 책상 상태가 LIMITED인 도구는 선점도 붙잡기도 하지 않는다.
- **허가 만료:** `.coord/grants/push.json`에 `expires_at`(오프셋 있는 ISO 8601 또는 epoch 초)이 있으면 그 시각부터 DENY다. 오프셋 없는 시각, 참/거짓, 읽을 수 없는 값도 DENY이고, `expires_at`이 없는 허가는 뜻이 그대로다.
- **남은 위험:** Antigravity IDE 1.107(Windows)에서 Stop 훅이 실행되지 않는다는 보고가 있다(https://discuss.ai.google.dev/t/stop-and-posttooluse-hooks-in-agents-hooks-json-never-fire-antigravity-ide-1-107-0-windows/178288). 설치 뒤 받는 쪽 확인은 `.coord/presence/stop_gate_antigravity.json` 또는 `.coord/log/stop_gate.jsonl`의 antigravity 줄로 한다.

## 6. 되돌리기

- 관문 끄기: `.claude/settings.json`에서 `Stop` 항목 제거.
- push 상시 허가 취소: `.coord/grants/push.json`의 `enabled`를 `false`로 하거나 파일 삭제.
