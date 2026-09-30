# U95 — Token-thrift as UAOS-RSI's default operating mode (Frame, maintained)

Author: Claude (acting conductor while Codex is ABSENT; mark for Codex re-review). Date: 2026-09-30.

## Decision

Make one budget buy a much longer and more complex automation workflow. Premise fixed by 윤겸스: with today's habits
Codex and Claude spend a 5-hour window and a weekly limit inside one conversation, so every rule and card is judged
against that. Token-thrift is the default mode of UAOS-RSI, for all three tools.

## Success signal (fixed before any change)

- Primary: read-equivalent tokens per completed card, from the tool's own transcripts (meter: U95-B), at least 30%
  below the baseline cards U93 and U94-R1, with the same gates (full unittest, fixed acceptance, independent verdict).
- Secondary: mean context per paid call at most 110k tokens (baseline 137k–147k); cache rewrites after idle at most
  2 per session (baseline 4–8).
- A saving without the controlled comparison stays UNMEASURED (global rule, Verification).

## Non-goals

- No per-prompt text injection for Claude or Codex: the 09-23 hooks cost about 265 tokens a prompt and 450–540 ms a
  call and saved 58.7k tokens in total (`.coord/runs/U17/mia_strategic_20260923.md`).
- No paid polling, no model downgrade, no new feature without a receipt.

## Evidence map (measured 2026-09-30, deterministic scripts, 0 paid tokens)

Facts:
1. Claude, last 6 sessions of this worktree, 1,605 paid calls: mean context per call 136.9k–147.4k tokens; cache reads
   are 97% or more of input; compaction fires near 215k (`CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=22` on a 1M model); the
   context right after a compaction is 71.7k–86.3k. Each call therefore re-reads the whole context once.
2. Cost split of the current session at API price ratios (read 0.1x, write 1.25x, output 5x of input): cache reads
   58%, cache writes 26%, output 15%. How `/usage` weights these is UNKNOWN.
3. Cache rewrites over 20k tokens: 4–8 per session (compactions plus cache expiry after idle; the default cache
   lifetime is 5 minutes).
4. Ollama calls made inside a turn since 09-23 (olla usage ledger): Antigravity 66 (ask 38, digest 17, prewarm 11),
   Claude 24, Codex 15. Pilot local runs: Claude 94, Codex 89, Antigravity 22. Antigravity also logged 367 hook-only
   events (plan hint 202, turn shape 165) that call no model: its olla hook injects a plan hint on every turn, while
   Claude's and Codex's hooks were retired on 09-23.
5. Antigravity's `deny_whole_read` guard refused 15 whole-file reads, about 316k tokens that never entered its context.
6. Global rules: CLAUDE.md 12.9 KB, AGENTS.md 13.2 KB (Codex also loads the 18.4 KB project AGENTS.md), GEMINI.md
   11.7 KB. All three already say "Token-thrift is default" (Scope section): the gap is enforcement, not wording.
7. Antigravity could not be addressed by UAOS at all (fixed in U95-A, 2026-09-30).
8. Headless Antigravity pilot runs: most recent remote runs ended BLOCKED (COST_EXCEEDED, QUOTA, EXTERNAL_WRITE) or
   UNUSABLE; local Ollama runs pass at about 2–4k local tokens in 115–435 s.

Hypotheses (each needs its own gate):
- H1 Calls per card is the largest lever: each call re-reads about 140k, so a 20-call step costs about 2.8M reads.
  Batching, `worker: apply`, and scripts remove calls entirely.
- H2 The post-compaction floor (72–86k) holds removable parts (tool schemas, deferred tool list, re-attached files,
  skills); cutting 20k saves about 14% on every call.
- H3 A lower compaction threshold (about 150k) cuts the mean context about 13% after counting the extra compactions
  (model estimate only).
- H4 Large tool outputs stay in context until compaction, so a read of N tokens costs about N x remaining calls x 0.1;
  a deny-only guard for whole-file reads (0 tokens when silent) moves those reads to Ollama maps or line ranges.
- H5 Codex has no `model_auto_compact_token_limit` and loads 31.6 KB of rules; the same levers apply once measured.

Unknowns: `/usage` weighting of cache reads; a longer cache lifetime option for Claude Code; Codex per-call context
(its session logs are not yet metered); Antigravity's compaction settings.

## Cards

| Card | Owner | Gate |
|---|---|---|
| U95-A Antigravity addressable and briefed | claude design, apply | DONE on branch: full suite 1248 OK |
| U95-B cost meter for Claude and Codex transcripts | claude design, apply | fixed fixtures; reproduces the facts above |
| U95-R research: levers and whether rules or config enforce them | antigravity (manual), claude spot-check | 5 sources re-opened by Claude |
| U95-C deny-only guard for large whole-file reads (Claude) | claude design, apply | test plus a before/after meter run |
| U95-D canon: token-thrift mode as measurable rules and config | claude draft, Codex re-review | platform tests, drift 0 |
| U95-E compaction and cache settings A/B | claude | meter delta on two comparable cards |

Order: A, B, R (parallel with B), C, D, E. Each card gets its own contract manual before any worker runs.
