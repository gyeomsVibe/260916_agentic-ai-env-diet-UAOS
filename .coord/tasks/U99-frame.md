# U99 frame: can UAOS-RSI be the enforced global operating system of Codex, Claude Code and Antigravity?

Author: claude (acting conductor, Codex ABSENT), 2026-09-30. MIA step 1 (Frame). Codex re-review owed.

## Decision

Keep UAOS-RSI as the canonical global rule set of all three tools (canon v7.2.0, merged) and decide what to change next:
- Go: the evidence shows the rule set is enforceable and pays off per finished step; the next cards turn the remaining text-only rules into gates.
- Pivot: some rules can't be enforced or measured; drop or move them to project scope.
- No-Go: the cost of the shared core outweighs its effect.

## Goal and yardstick (user premise, fixed)

The same subscription budget must buy 윤겸스 a much longer, more complex automation workflow. Yardstick: today one conversation drains a 5-hour or weekly limit before one process is done. Default mode: token-thrift.

## Success signals (measurable)

- S1 paid tokens per finished card (ledger `card_cost`), claude median: 3.24M in 36 rows now. Target: lower median at an equal or better PASS rate, measured over the next 10 cards.
- S2 delegated share: code over 20 lines written by Ollama or Antigravity. Now: 0 cards before U98-D, 2 cards after (U98-D, U98-D-F1).
- S3 rule compliance measured by a deterministic check, not by self-report: for example the share of Korean user-visible lines, and progress lines per turn.
- S4 delegate reliability: Ollama PASS rate per run (RSI window 0.2) and Antigravity cap overruns (2 of the last 2 review runs).

## Non-goals

- No new UAOS feature without a real-use failure receipt.
- No change to evaluators (tests, ledgers, gate code) as an improvement target.
- No re-research of the token levers already sourced in `.coord/notes/U95_token_thrift_research.md` (caching prices, Tool Search, subagents, Codex project_doc_max_bytes and auto-compact, reasoning effort, FrugalGPT, RouteLLM, Lost in the Middle, LIFBench, SWE-agent, MemGPT).

## Evidence map

Facts (ledger `.coord/usage/runs.jsonl`, 2026-09-30):
- apply 178 rows (145 PASS, 17 REWORK, 16 BLOCKED).
- agy 46 rows (11 PASS, 20 BLOCKED, 6 UNUSABLE); 2 recent review runs overran their caps (10.5x, 1.8x) and wrote outside the stage.
- ollama 39 rows (8 PASS, 8 BLOCKED, 5 REWORK); recurring causes: CODE, PROMPT_TOO_LARGE (7B, 12,288-token prompt).
- claude 36 rows, median 3.24M tokens, 97.4% cache reads; codex 22 rows, median 12.8M, 96.8% cache reads.
- The user saw rule violations after rules were written (English progress lines, the conductor dictating all code): text alone did not change behavior; the U98-D lint gate did.

Hypotheses:
- H1 Rule text is followed unreliably in long contexts; hooks, config values and code gates are needed for rules that matter.
- H2 Paid cost ≈ calls × context; how subscription limits weight cache reads is UNKNOWN (not found in U95-R).
- H3 A local 7B coder works for small spec-to-code tasks when a fixed test gate judges the result.
- H4 Each tool has its own global-rule mechanism and size limit; one shared core plus per-tool adapters fits all three.
- H5 Self-improvement is safe only when evidence-gated: fixed evaluators, sandboxed trials, human merge (objective hacking risk).
- H6 Multi-agent systems fail mostly on specification and verification, so contract manuals and independent judges address the main failure modes.

Unknowns to reduce by research (U99-R): H2 limit accounting, H4 per-tool limits and hook support, H5 literature, H6 failure taxonomy, H3 small-model evidence.
