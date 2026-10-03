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

## 5. 알려진 한계 (U146-B로 넘김)

- 선점은 프로세스 ID로 판단한다. `coord next --claim`을 셸에서 한 번 부르면 그 프로세스가 곧 끝나므로 다음 호출에서는 죽은 선점으로 보인다. 세션 단위 임대(lease, R6)는 U146-B에서 들어온다.
- Codex·Antigravity에는 아직 자동 관문이 없다. 지금은 규칙 문구(어댑터)로 `coord next`를 부르게 하고, 훅·감시기는 U146-B에서 들어온다.

## 6. 되돌리기

- 관문 끄기: `.claude/settings.json`에서 `Stop` 항목 제거.
- push 상시 허가 취소: `.coord/grants/push.json`의 `enabled`를 `false`로 하거나 파일 삭제.
