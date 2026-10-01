# U106 frame: balance between operating-system work and task work (for the research worker)

Decision to make: how UAOS-RSI splits work between the paid commanders (Claude Code, Codex), the paid
remote worker (Antigravity) and the free local model (Ollama), so the same subscription budget finishes
much longer real automation workflows.

Measured facts (this project, 2026-10-01):
- 105 cards so far built the operating system itself; no user deliverable workflow was measured.
- One Claude Code conversation spent 60,290,944 tokens in 417 paid calls (~145k context per call); the
  usage ledger recorded only 1,053,284 Claude tokens, so the main cost was invisible.
- Ledger totals: codex 16.5M (22 runs), antigravity 8.4M (48 runs, 23 BLOCKED, 14 PASS),
  ollama 98k (46 runs, 19 PASS), deterministic apply 0 tokens (195 runs, 159 PASS).
- First headless Antigravity implementation (U105) passed at 604,187 tokens, but the router's advice
  "use local (Ollama)" was ignored because the commander wrote `worker: agy` by hand; `auto` routing
  (dictated code -> apply, specific -> Ollama then Antigravity, else Antigravity) exists but is not the default.

Hypotheses (one verdict each: SUPPORTED, REFUTED, MIXED or UNKNOWN):
- H1: In multi-agent LLM systems coordination/orchestration overhead is a large share of total tokens, and
  a strong orchestrator doing worker-level edits itself costs more than delegating them.
- H2: Model cascades/routers (cheap or local model first, escalate on a failed check) cut cost a lot at
  small quality loss.
- H3: Small local code models (about 7-32B) succeed on tightly specified edits/extraction and fail mainly
  on underspecified tasks; specification quality predicts success.
- H4: Executable tests (not self-reports or LLM judges alone) are what make delegation to cheaper workers safe.
- H5: Per-call fixed context dominates the cost of agentic sessions; cutting the number of long-context
  calls (and context size) saves more than shortening outputs.
- H6: Adding process/governance machinery beyond need lowers delivered output ("coordination tax");
  practitioners recommend a simple single-orchestrator/worker split with a fixed ratio or rule.
