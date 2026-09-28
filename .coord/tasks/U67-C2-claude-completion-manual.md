```contract
work_id: U67-C2
worker: claude
goal: Act as bounded deputy for the ordered U68-U72 project completion sequence while preserving single ownership, token budgets, and approval boundaries.
inputs:
- .coord/PROJECT_MANUAL.md sha256=1d08eed081334383bf6c5680683868c191ff483e557083a695ae56b850bac791
- .coord/PLAN.md sha256=c3fb52ef75dab95616271947539396bf97ad33facec77bda766b0614016e22fc
- docs/55_u67-nonstop-token-budget-completion-plan.md sha256=6b25e274882c313604ddbcebb92f600adc2965670b8696947bdf8f45b0a4137a
- v7_harness/adapters/claude_worker.py sha256=1f5fa8ce418e6a2ee01aa74c029dbd3b17499e885d979faf7345cedfd6feee49
- tests/test_u38_cost_gate_and_claude_worker.py sha256=9c9c9b52abaa13cde8b04ee2d5d1f9dd753dec8b5c4f87b84636e3ce4851851a
- v7_harness/coord/thrift.py sha256=e832fbaad81aa173cd6ded8f6ae8ab62c50af00ca64ed0688a90b2a64a3e7dba
- v7_harness/coord/deliver.py sha256=aada355dca62ecdd5fcca0f6b07a6d3d7da953d235f517934a63e7ced2a2c82a
allow:
- .coord/PLAN.md
- .coord/tasks/U68*
- docs/55_u67-nonstop-token-budget-completion-plan.md
- docs/56*
- v7_harness/adapters/claude_worker.py
- tests/test_u38_cost_gate_and_claude_worker.py
acceptance: C:/Python314/python.exe -m unittest -v tests.test_u38_cost_gate_and_claude_worker tests.test_u44_claude_contract tests.test_u63_thrift_mode tests.test_u64f_no_double_wake
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 1200
remote_budget_tokens: 120000
remote_budget_usd: 0.25
```

## Instructions for the worker

You are the deputy for the U67 completion sequence, not the final judge. Follow the project manual transmitted below and the ordered U68 through U72 cards in docs/55.

Start only when Codex explicitly routes one dependency-ready card or Codex is LIMITED/ABSENT under verified presence. Never take more than one card at a time. Before every local, apply, or Antigravity worker call, publish and lint a new hash-fixed contract and include the project manual in full. Prefer deterministic commands first. Use Ollama only for a currently QUALIFIED task type and model digest; JSON extraction on qwen2.5-coder:7b is currently REJECTED after two same-cause format failures.

For each card, finish choose -> execute -> fixed acceptance -> card/ledger update. Return FACT / EVIDENCE / NEXT ONE ACTION. ACK_ONLY, unchanged state, empty output, and liveness never wake another paid model. Stop at deletion, push, deploy, public posting, payment, or account/credential/permission/system-setting changes unless that exact action has fresh user approval.

Do not mark the project complete before U72 has ten valid controlled samples, P1 zero, full regression exit 0, no 3x wall-time regression, no test fitting, and complete paid/local usage receipts. Savings remain UNMEASURED until then.

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
