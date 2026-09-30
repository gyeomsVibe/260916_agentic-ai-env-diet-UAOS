```contract
work_id: U98-D-A2
worker: apply
goal: The project rule text stops calling apply the 0-token default for code and states the delegation-first gate.
inputs:
- CLAUDE.md sha256=74551945a7c0bd78ce43d1415123688f3da89679adc653d22b856fe19cc33eb1
- AGENTS.md sha256=98ccd9e16551d47de2e709e15ac7734939c8a079d1f51940f6dd56ddcaa4ff5c
allow:
- CLAUDE.md
- AGENTS.md
acceptance: python -m unittest tests.test_u96d_agents_budget tests.test_u98d_delegate_first
forbidden: edits outside allow; editing or weakening tests; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the blocks exactly. Receipt: both rule files told the conductor to send decided code to `worker: apply` as the 0-token route, which is how 174 apply rows beat 31 delegate rows (U98-D). AGENTS.md must stay within the U96-D byte budget.

===EDIT: CLAUDE.md===
<<<<<<< SEARCH
코드를 이미 정했으면 `worker: apply`(0토큰).
=======
코드는 명세로 Ollama(`worker: local`)·agy에 먼저 맡긴다. `worker: apply`는 테스트 외 파이썬 20줄 이하이거나 `apply_after: <실패한 위임 work_id>`일 때만 lint를 통과한다(U98-D).
>>>>>>> REPLACE
===END===

===EDIT: AGENTS.md===
<<<<<<< SEARCH
지휘자가 코드를 이미 정했으면 `worker: apply`(모델 없음·0토큰).
=======
코드는 명세로 Ollama·agy에 먼저; apply는 20줄 이하나 `apply_after`만(U98-D).
>>>>>>> REPLACE
===END===
