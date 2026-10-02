ACTIONABLE_DELTA verdict_requested=yes
WORK MANUAL U125-A (Antigravity design audit; author Claude, acting conductor while Codex LIMITED)
receipts: (1) the sentinel published 15 `rsi_review_*` letters (e.g. "RSI window 1 for ollama: pass 0.2") with no `requested_target`, so `watch._addressed` (v7_harness/coord/watch.py:96) never woke any conductor and none was handled. (2) `rsi.propose` (v7_harness/rsi.py:327) gives every cause the worker's last five work_ids as evidence: ollama UNREQUESTED_DELETION lists U124-L2, a PASS run.
design U125 (the smallest link of check -> classify -> card -> fix; no paid polling, the wake is event driven):
D1 `rsi.analyze` adds per worker `cause_work_ids` {cause: last five work_ids whose `_cause` is that cause}; `propose` uses it as evidence, falling back to `recent_work_ids` (HIGH_REWORK_RATE keeps the window).
D2 `rsi.rsi_review_messages(..., target=None)`: with a target the payload gains `requested_target` and `proposals` (id, cause, target, action, evidence of that worker's recurring proposals, at most 5). Without a target the payload is unchanged.
D3 `sentinel.run_sentinel_cycle`: target = `presence.conductor(read_all(root))["conductor"]` when it is codex, claude or antigravity; UNKNOWN or none keeps the letter mailbox-only (fail closed). Message ids still name the window, so a letter is never repeated.
exact edits (dictation for Ollama, 5 + 1 SEARCH/REPLACE blocks): D:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/.claude/worktrees/agentic-ai-diet-process-2e7a13/.work/u125_dictation_rsi.md and .../.work/u125_dictation_sentinel.md
judge tests (written before the run): tests/test_u125_rsi_review_wakes_conductor.py in the same worktree (5 tests: evidence per cause, letter with/without target, sentinel routes to the acting conductor, UNKNOWN desk fails closed). Judge reference copy: 32/32 OK with tests/test_u36_evidence_gated_rsi.
note: v7_harness/rsi.py is in EVALUATOR_PATTERNS, which bars the RSI loop from changing it; this is a human PLAN card with an independent review, not an RSI candidate, and it does not touch `gate`, `gate_from_ledger` or the policy bounds.
non-goals: auto-writing PLAN cards or code from a letter; changing REMEDIES; acking the 15 old letters (the conductor triages them by hand).
questions:
1. Can D3 wake the wrong tool or wake a tool repeatedly (e.g. a desk flip between cycles, or the same window)?
2. Does D1 change any gate result (`gate_from_ledger` reads `before_work_ids` from the candidate template built from `evidence`)?
3. Is anything in D2's payload unsafe for a session that treats letters as data (size, injection through work_id text)?
reply: PASS / REVISE (concrete changes) / FAIL, each point with file:line or a counterexample. Read only.
