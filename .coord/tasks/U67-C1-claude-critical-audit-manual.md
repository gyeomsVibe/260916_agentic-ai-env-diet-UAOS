```contract
work_id: U67-C1
worker: claude
goal: Independently audit current UAOS completion and return the smallest ordered finish plan for nonstop token-budget operation.
inputs:
- .coord/PROJECT_MANUAL.md sha256=1d08eed081334383bf6c5680683868c191ff483e557083a695ae56b850bac791
- .coord/PLAN.md sha256=4cb7a1f628abc5bce59ef278d49cbcb5dd6507e8113a95cdaa731905cbb951fd
- docs/52_u63-token-budget-thrift-mode.md sha256=855efe711321d55886af1b6707aca87818013ba00922898b44d8832f37f608a7
- docs/53_u66-atomic-dispatch-intent.md sha256=db801bcffa7b1136dc3786bc16ff66a31c4e5e9508096c9b189972510011d0ce
- docs/54_u65g-single-global-rules-owner.md sha256=07e7ff4f5bef43c704c5443a5a3862cbb680faf7717787b859ef54d3f321de9b
- v7_harness/budget_route.py sha256=1ed3c34ab7c2efd4695099c87c5f0fb6300fb808e6949fbff73c297d00b2198d
- v7_harness/coord/thrift.py sha256=e832fbaad81aa173cd6ded8f6ae8ab62c50af00ca64ed0688a90b2a64a3e7dba
- v7_harness/coord/deliver.py sha256=aada355dca62ecdd5fcca0f6b07a6d3d7da953d235f517934a63e7ced2a2c82a
- v7_harness/coord/watch.py sha256=7eb50c9488483ac83ad8177502b24c5f0266cd396db049c58fd03b97b71d8c6e
- v7_harness/global_install.py sha256=d65f0566d2fb69239e2de6621354286fef68b6a06bba60e5857d97c136228ea3
allow:
- .coord/PROJECT_MANUAL.md
- .coord/PLAN.md
- docs/52_u63-token-budget-thrift-mode.md
- docs/53_u66-atomic-dispatch-intent.md
- docs/54_u65g-single-global-rules-owner.md
- v7_harness/budget_route.py
- v7_harness/coord/thrift.py
- v7_harness/coord/deliver.py
- v7_harness/coord/watch.py
- v7_harness/global_install.py
acceptance: C:/Python314/python.exe -m unittest -v tests.test_u63_thrift_mode tests.test_u64f_no_double_wake tests.test_u57_desk_signals tests.test_u65_deploy_three_tools tests.test_u37_install_everywhere
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 600
remote_budget_tokens: 12000
remote_budget_usd: 1
```

## Instructions for the worker

Read the pinned project state as an independent deputy. Do not edit any file and do not delegate.

Return exactly these sections in English: FACTS, CRITICAL GAPS, ORDERED FINISH PLAN, OLLAMA BOUNDARIES, VERDICT, NEXT ONE ACTION.

Audit for concurrency races, duplicate ownership, stale approvals, author-only verification, test fitting, paid wake duplication, unbounded context, false savings claims, missing portable fixtures, and any path that can stop without a user approval boundary. Separate verified facts, inferences, UNKNOWN, and UNMEASURED. Keep the response under 3500 characters.

## Project manual transmitted in full

# UAOS 프로젝트 완성 매뉴얼

- work_id: U67
- 목표: Codex·Claude Code·Antigravity가 단일 계획과 증거 관문으로 끝까지 이어지고, 결정적 도구와 자격을 통과한 Ollama를 먼저 써서 유료 토큰을 줄이는 UAOS를 완성한다.
- 단일 원장: `.coord/PLAN.md`; 현재 단계는 U67 비판 감사·완성 설계·실행 계약 발행이다.
- 소유권: Codex가 ACTIVE이면 계획·순서·최종 판정을 소유한다. 단계별 작성자는 한 명이며 작성자는 자기 변경의 유일한 검증자가 될 수 없다.
- 상태기계: Codex ACTIVE → Codex, 아니면 Claude ACTIVE → Claude, 둘 다 LIMITED/ABSENT일 때만 Antigravity ACTIVE → Antigravity. UNKNOWN은 대행 근거가 아니다.
- 연속성: `coord watch`와 디스크 우편함이 대기를 맡는다. ACK_ONLY·동일 상태·빈 출력은 유료 모델을 깨우지 않고, ACTIONABLE_DELTA·P1·실패 관문·승인 경계만 깨운다.
- 토큰 예산: 잔여율을 토큰으로 환산하지 않는다. NORMAL/THRIFT/HANDOFF_READY/LOCAL_LOCKDOWN 상태와 도구별 보존 정책을 사용하고 실제 절감은 통제 비교 전 `UNMEASURED`다.
- Ollama: 결정적 추출보다 이득인 해시 고정 기계 작업만 수행한다. 설계·승인·판정은 금지하며 출력은 원문 대조와 고정 인수 전까지 격리한다. 로컬 토큰·벽시계·실패를 기록한다.
- 위임: 모든 Claude·Antigravity·Ollama 호출 전에 프로젝트 매뉴얼과 입력 SHA-256·허용 파일·금지 행동·token/USD/time 상한·인수·중단 조건이 든 계약 매뉴얼을 파일로 발행하고 lint한 뒤 내용 전체를 전달한다.
- 검증: diff, 고정 인수, 테스트 해시, 장부, 원격 SHA가 작업자 보고보다 우선한다. 미실행은 UNKNOWN이고 예산 초과·범위 밖 쓰기·빈 산출물은 승인하지 않는다.
- 승인 경계: `.coord/PLAN.md`와 작업 카드의 로컬 갱신은 무승인이다. 삭제, remote push, deploy/public posting, 결제, 계정·자격증명·권한·시스템 설정 변경은 각각의 최신 명시 승인 없이는 금지한다. 과거 U45 승인은 U67로 이전되지 않는다.
- 중단: 입력 해시 불일치, 중복 소유권, 같은 원인 2회 실패(Ollama) 또는 3회 실패(일반 실행), 고정 인수 변경, 예산 초과, 범위 밖 쓰기, 승인 경계 도달.



## Output

- Edit the files under `allow` directly with your file tools. Your reply is not applied: ===FILE / ===EDIT blocks in it are ignored. End with one line saying what you changed. Do not claim success; the acceptance command decides.
