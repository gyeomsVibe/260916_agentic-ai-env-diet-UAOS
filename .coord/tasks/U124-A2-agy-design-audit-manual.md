ACTIONABLE_DELTA verdict_requested=yes
WORK MANUAL U124-A2 (Antigravity design re-audit; author Claude, acting conductor)
context: you answered U124-A with REVISE (relay_6aaf0fdb): force find-and-replace for existing .py files. User order (2026-10-02): "use Ollama the way Antigravity does". Your U23 runs dictated 5-line SEARCH/REPLACE blocks and Ollama only copied them.
new receipt U124-L (just now): Claude dictated two exact edit blocks for `v7_harness/adapters/ollama_worker.py` (488 lines, whole file in context, 7,606 in / 1,078 out tokens, 170 s). Ollama did not copy them. It re-emitted the whole `_apply` function in the fenced-definition format, dropped 3 lines (the `_guard` call and the write-after-validation loop header), changed one character in a Korean comment, appended the new function at end of file, and skipped the second block. Acceptance passed because it only tested the new helper. The bundle is rejected and will not be approved.
revised design U124:
R1 `_rules_for(named)`: any existing .py file in context -> EDIT_RULES (your recommendation); other files keep the 150-line rule.
R2 dictation check in `ollama_worker._apply`: split today's body into a planning step (blocks -> new contents in memory) and the guard/write step. When the task itself contains ===EDIT or ===FILE blocks (dictation; placeholder path excluded), plan them deterministically against the current files to get the expected contents. Every dictated path must then equal the model's planned content after CRLF normalisation, and the model may touch no other path. Else raise DICTATION_MISMATCH:<path>:<first differing line number>. The existing one free repair retry feeds that error back. Nothing is written on mismatch.
R3 tasks without dictated blocks (specs) are unchanged.
non-goals: model change; narrowing context to slices around each SEARCH (next card if copying keeps failing).
questions:
1. Does R2 fully close the U124-L failure (silent dropped lines, wrong position, skipped block)?
2. Can a dictated task still pass R2 while it is wrong, for example when the dictation itself does not apply (SEARCH not found), or through a ===FILE block vs an EDIT block on the same path?
3. Is the fenced-definition format still needed when dictation exists, or should R2 ignore it?
reply: PASS / REVISE (concrete changes) / FAIL, each point with file:line or a counterexample. Read only.
