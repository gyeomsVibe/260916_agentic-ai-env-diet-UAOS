ACTIONABLE_DELTA verdict_requested=yes
WORK MANUAL U127-A (Antigravity design audit; author Claude, acting conductor while Codex LIMITED)
receipts: the user reported that one-window-per-process (U114) was promised for all three tools and nothing changed. `.coord/windows/` holds one record (U115, claude only). Every U120 auto reply (v7_harness/coord/agy_dispatch.py `dispatch`) runs a fresh Antigravity conversation, so U124-A, U124-A2, U125-A and U126-A each got a separate conversation. Probe today: `agy -p --conversation af19c18f-2bf6-4a53-a1f9-1a96c366a6ac` (your U126-A audit) answered "U126-A: REVISE" in the same conversation, 53,072 input tokens against about 25,000 for a fresh turn.
design U127:
D1 windows.py gains `window_entry(project, card, tool) -> dict` and `record_window(project, card, tool, window_id, *, now=None, **extra)`, which writes one tool's entry into `.coord/windows/<card>.json` and keeps the others (U114 format; bad card id raises ValueError).
D2 `agy_dispatch.dispatch(..., card="")`: with a card whose antigravity entry has an id and `last_input_tokens < RESUME_MAX_INPUT` (100,000, the review budget) it passes `conversation_id` to `build_agy_command` (adds `--conversation <id>`). After a successful reply it records the returned conversation id with `last_input_tokens`. Past the cap the card starts a fresh conversation and the record moves to it.
D3 `deliver` passes its `card` to `dispatch` (it already validates the card id before publishing).
route: D1 by Ollama from a spec (.work/u127_spec_windows.md); D2+D3 (16 lines) dictated (.work/u127_dictation_dispatch.md), both under D:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/.claude/worktrees/agentic-ai-diet-process-2e7a13.
judge tests (before the run): tests/test_u127_agy_card_window.py, 7 tests (record keeps other tools, bad id refused, first card letter records, next letter resumes, heavy window starts fresh, other cards untouched, no card no record). Judge reference: OK with the U114, U115 and U120 tests.
non-goals: auto-opening paid Claude or Codex windows on deliver (each costs a paid turn; Codex LIMITED); routing the reply letter into the sender's card window; `pilot review --reviewer agy` resuming the card conversation (next card if this holds).
questions:
1. Failure modes of resuming: an expired or unknown conversation id, or two letters for one card at once (both resume; the last record write wins). Should a failed resume retry fresh, or is the existing UNREAD fallback enough?
2. Is 100,000 the right cap given 53,072 at the second turn? Each resumed turn grows the input.
3. Can a resumed conversation leak an earlier card's context (the box folder is shared across cards; the conversation is per card)?
reply: PASS / REVISE (concrete changes) / FAIL, each point with file:line or a counterexample. Read only.
