# 사용자 대화창구 마스터 일정 — 2026-10-18

유지 산출물. Codex native desk: `01a14d49-1f61-7f01-9825-53eaa9b70f20`, ca18. 사용자의 이번 선언과 무승인 계속 진행 지시를 적용한다. 플랫폼 통제와 검증 실패는 우회하지 않는다. 일정은 추정 시각 대신 선행 관문 순서다.

## 출석과 협의

- 사용자 책상 generation7과 현재 thread가 일치한다. 앱 제목은 `[사용자 대화창구-261018-1]`로 변경했다. 이전 책상은 handed_off_to 현재 thread다.
- Codex ACTIVE 조율자. Claude 답장 `relay_039beac1c8206ef3c21856189f5ba779`와 수정안 `relay_3c4bfa0b6502c59b4a3b7c7899eddd95`를 수신했다. Antigravity 답장 `relay_600be7ec673a11e1ee4b3c52d52634a5`는 현재 책상 수신과 읽기 전용 역할을 확인했다. AGY 답장은 파일 검사를 하지 못했으므로 제품 증거로 쓰지 않는다.
- 이전 Codex 책상 인계 `relay_8069d4a3cf5ec525c9b965349b8aaeb3`를 수신했다. 기존 Claude 작성자 소유권은 유지한다. legacy Claude `7fe8c052`는 실행자가 아니며 그 ACK를 현 수행자 수신으로 쓰지 않는다.
- Claude 초안 MASTER_PLAN_20261018은 REVISE: 자동 호출로 AGY turn이 생겼다는 사실만으로 무과금/강제 예산/중복 방지/세 도구 전달이 증명되지는 않는다. 이미 끝낸 U208 capability 조사를 무조건 반복하지 않는다.

## 이전 프로세스와 이번 독립 확인

| 프로세스 | 현재 근거 | 이번 판정 |
|---|---|---|
| 기존 P1~P5, U196, U203/205/206/207 | 이전 계획·설치 영수증 | 역사 기록으로 유지, 전체 재인증 아님 |
| U180-D5 | PR169, 이전 설치 독립 인수42/126파일 | 완료 기록 유지, 일반 라우팅 보증으로 확대하지 않음 |
| U209-R2 | PR171 MERGED head4201f7c1, merge72db228d; 현재 runtime3354d2136a7b의 stall.py SHA55f4081a | 새 책상이 설치본 frozen4와 실제 parallel8을 재실행하여 모두 exit0 |
| U211/U212 | PR172/173 MERGED, merge f7fb4728/474db62b | GitHub 현재 상태 확인. 이 책상의 개별 기능 재인수는 미실행 |
| U210-L3 | 이전 책상 receiver-scope fixture exit1, 3도구 모두 foreign card-window 오수신 | 후보68b73b35 REVISE 유지. 최신 후보/설치본과 혼동하지 않음 |
| U208 | STOP/SAFETY_GATE, native enforced bound와 idempotency UNKNOWN | 구현 금지 유지, 기존 capability 자료를 먼저 재사용 |
| U185/U191 | 4 PARKED, 2 BLOCKED | 새 고정 계약·예산·수신자 증명 전 자동 해제하지 않음 |

U209 원래 fixture SHA `ab1d9342bf423238c29a01ebe7f3252bf64d1a191ff67610d4ec2d83f6630dfa`; 설치 source SHA `55f4081a9111708e206f04ff6decda41cacfcb8c8013dc90bd9b03418e48d13f`. 이 책상의 테스트 로그는 `.work/installed_frozen4.log`, `.work/installed_parallel8.log`다. 전체 회귀는 이번에 재실행하지 않았다.

## 확정할 실행 순서

| 순서 | 소유자/독립 판정 | 다음 행동 | 고정 관문 및 중단 |
|---|---|---|---|
| R0 | Codex / 기존 비작성자 증거 | 출석·책상·U209 복귀 재인수 | 완료: 명시 책상, 실제 답장, 설치 frozen4/parallel8 exit0. U211/U212 기능 판정은 별도 |
| R1 | 현재 Claude 조율 세션 / Codex | 기존 U210 작성자와 최신 후보·계약·수신 범위를 읽기 전용으로 결합하여 한 번 반환 | 새 paid worker0, source write0. 원래 fixture12bed06c/후보 hash/owner/window를 제시. 다른 창 편지 read/act/ACK 금지. 해당 작성자는 유지하고 중복 실행 금지 |
| R2 | Codex / 비작성자 필요 | R1 증거로 최신 후보가 영향을 받는지 판정, 필요 시 단계 전용 작성자에게 작은 수정 계약 | 기존 후보는 REVISE. 정확한 새 bundle, 동결 반례, 일반 편지 positive control 모두 통과 전 승격 금지 |
| R3 | Codex 조율 / 확인된 작성자와 비작성자 | 공유 user_window.py/test 변경의 U207-C 소유권 충돌 해소 | 기존 diff 보존. 소유자 UNKNOWN이면 제품·공유 PLAN 편집/커밋 금지; 별도 자체 문서만 작성 |
| R4 | Codex / Claude 증거 정리 | U208 기존 capability 자료와 새 실측을 대조 | native 강제 cap·payload/session/generation 수신·crash-safe idempotency 전부 필요. 하나라도 UNKNOWN이면 STOP 유지. 재유료 probe 없음 |
| R5 | 단계 전용 단일 작성자 / 비작성자 | U191-U185-FREEZE의 pre-dispatch 비용 관문과 fresh 계약 고정 | 입력 SHA/허용경로/수신자/원문 인수/시간·토큰 강제 상한·판정자. 기존 거부 감사 재사용 금지 |
| R6 | Codex 조율 / 비작성자 | R5 통과 뒤 U185 계약별 해제, 이후 U191 실제 프로젝트 defect map | installed receipt-refusal 인수, 원래 결함별 수정·테스트 연결. 자동 전면 unpark 없음 |
| 각 릴리스 | 기존 작성자 / 비작성자 exact-head 판정 | PR→Antigravity 우선 병합→설치→검사 | live head·CI·설치 원본 hash·drift[] 모두 확인. 실패는 원인 보존, 기준 완화 금지 |

R1만 다음 실행 가능한 읽기 작업으로 인계한다. 공유 master_schedule.json의 기존 phase/owner/STOP은 이 문서로 변경하지 않는다. 사용자 질문·수동 전달은 필요 없다. 새 결과가 없으면 유료 반복 호출하지 않는다.

## MIA와 근거

0. 공식 [Git status](https://git-scm.com/docs/git-status)에서 HEAD/index/worktree 차이와 porcelain의 기계 판독 계약을 확인했다. 실제 ca18은 초기 clean, 공유 원본은 기존 dirty다.
1–2. 성공 신호: 새 책상 일치, 두 도구 실제 답장, 유지 일정, 설치본 고정 인수, 다음 단일 소유자 인계. 새 기능 추가는 비목표다.
3–4. 전면 병렬 수정은 소유권 충돌, 과거 READY 재실행은 STOP 재개 위험, 기존 작성자 유지+읽기 증거+순차 관문은 복구 가능하므로 세 번째 대안을 선택한다.
5–8. 허용 쓰기: 이 책상 자체 일정·영수증·`.work` 및 명시 사서함. 공유 dirty 파일은 건드리지 않는다. 워커 구현은 별도 lint 계약 전 금지한다.
9–10. 설치본 독립 인수와 실제 GitHub 상태를 대조했다. 미실행은 UNKNOWN이다. 긴 파일 로컬 맵은300초 timeout, 로컬 초안은 아직 미수신으로 완료 증거가 아니다.

## 비용·편지·감시

- 첫 AGY 출석 알림은 자동 wrapper를 실행하여22871토큰을 소비했다. 명령 성공을 무과금이라고 보고하지 않는다. 후속 발송에는 paid subprocess를 거부하는 runner를 사용한다. 계정 한도 절감은 UNMEASURED다.
- 오래된 U82 편지 `relay_daff48aecfab7ce701d994efaa683d4b`는 읽었고 역사적 복귀 검토로 분류한다. 당시 DONE/PR54/timeout 주장은 현재 승인이나 재실행 명령이 아니다. 이 처분을 저장한 뒤 해당 편지만 ACK한다. 타 수신자 편지는 ACK하지 않는다.
- watcher는 로컬 결정적 감시다. 기존 watcher가 NEW_LETTER로 종료했으므로 재무장하고 PID/로그를 기록한다. watcher 생존은 native turn 시작이나 수신 완료의 증거가 아니다.

## 협의·독립 재현 갱신
Claude AGREE relay_bd98e7dfd106b253a76e48349453a815, AGY AGREE relay_d743a7050ae8cbe96b032c20229145ec. R1 packet을 읽고 GitHub PR170 MERGED(head d34e62f0, merge24df696c)를 별도로 확인했다. 현재 설치 stop_gate.py도68b73b35이며 원래 fixture12bed06c를 실행해 exit1/foreign-window3FAIL, 일반 편지 positive control PASS를 확인했다. 따라서 R2는 전체 revert 대신 현재 작성자의 작은 fix-forward 계약 준비를 우선한다. STOP hook의 타 창 편지 지시만 바로잡으며 권한·안전 관문은 유지한다. 새 구현/승격은 아직 하지 않았다.
로컬 초안은 수신했으나 shared dirty 파일을 clean하라는 근거 없는 행동이 포함되어 폐기했다. 최종 일정은 원문 대조로 작성했다. U82 ACK는 기본 root와 명시 root에서 각각 NOT_IN_INBOX/exit1로 실패해 더 재시도하지 않았다. 이 책상은 ACK 성공을 주장하지 않는다. U83은 역사 편지로 읽었으며 현재 승인으로 사용하지 않는다.


R2 contract review1: REVISE_NO_IMPLEMENTATION_GO。未知 native session에서 타 카드 read/act/ACK를 유지하는 규칙은 거부한다. tool-global hold guard의 세션 격리와 기존 수신 범위 helper/경로 검증, 원문 reviewer fixture 보존, 원래 작성자 실제 binding이 필요하다. Claude에 한 번 수정 패킷을 요청했으며 source_writer=null, 신규 paid subprocess cap0 유지. 상세 .work/r2_contract_verdict.json. 이 단계는 기능 수정을 완료한 상태가 아니다.

