ACTIONABLE_DELTA verdict_requested=yes
WORK MANUAL U123-A (Antigravity design audit before implementation; author Claude, acting conductor)
goal: find loopholes in the design below. User order (2026-10-02): every code change must follow "Antigravity audits -> Ollama fixes -> Antigravity reviews", mechanically, so the paid conductor cannot skip it again.
receipts: (1) U122: Claude trimmed a 21-line patch to 20 lines to fit the `worker: apply` dictation limit and skipped Ollama and Antigravity. (2) U122-F1: an Ollama run failed PROMPT_TOO_LARGE before the model was called (input_tokens 0); under today's rules that failed row would unlock `apply_after` dictation. (3) commit gate `v7_harness/calculator_gate.py` accepts any APPLIED pilot bundle (apply included) with no independent review, and a `Calculator-Exempt: <reason>` commit line skips the gate entirely (30 commits since 09-25). (4) an audit letter without the ACTIONABLE_DELTA token was silently not dispatched to Antigravity.
design:
G1 lint (`v7_harness/delegation.py`): DICTATION_CODE_LINE_LIMIT 20 -> 0, so any non-test code dictated to `worker: apply` needs `apply_after: <failed delegate work_id>` of the same card.
G2 lint: that failed delegate row only counts if the delegate really ran (ledger input_tokens > 0); PROMPT_TOO_LARGE and other pre-call failures no longer unlock apply.
G3 commit gate: a staged v7_harness/*.py matches only a bundle whose run folder also holds review_agy.json or review_codex.json with verdict PASS and the same bundle_id (written by `pilot review` before --approve). Merge-parent equality (U75) stays.
G4 commit gate: `Calculator-Exempt` no longer bypasses G3 for v7_harness/*.py.
G5 deliver: a claude/codex letter to antigravity with no wake token returns unread "AGY_NOT_SENT ..." instead of an empty string, so the sender sees it was not dispatched.
out of scope now: an automatic post-merge audit letter (next card if this passes).
check: (a) any remaining path for Claude to land v7_harness code without an Ollama attempt and an independent PASS? (b) can a review file be forged or reused for another bundle? (c) does G4 or G3 deadlock a real situation (agy daily cap 20, Codex LIMITED until 10-04)? (d) anything that should block merge of PR #95 now?
allowed output: one JSON object only, no file links or paths: {"verdict":"PASS|FAIL","findings":[{"severity":"P1|P2|P3","gap":"concrete path -> what slips through","fix":"one line"}]}. Max 1200 chars.
forbidden: editing, creating or deleting any file; running commands; network; secrets.
cost cap: one turn, 35,000 tokens. judge: Claude checks each finding against the code before acting.
