# U96 card queue (handoff from the U95 session, 2026-09-30)

Why a new session: `card_cost --card U95-BT-ACTING` measured 9,157,043 tokens, which is 1.78x the baseline card average. It returned `next_card_allowed: false`. Token-thrift says to split the work, not continue it. A fresh session starts at about 30k context, against about 150k in this one.

State at handoff:
- origin/main is e9f09d5; PR #68 (U95-A/B/T) is merged.
- canon v7.1.0 is applied; its check exits 0.
- The runtime was reinstalled as 0.3.0-f3a8bd8c5806.
- The installer check (`--check`) exits 0; the Antigravity hook uses `--say agy`, and its brief names the mode.

Queue, in order. Each card needs a receipt, an apply manual, lint, dry run, apply, the full test suite, and a PR.

1. **U96-S: Antigravity stage containment.**
   - Receipt: U95-R wrote `.coord/notes/U95_token_thrift_research.md` into the worktree instead of `.coord/stage/U95-R`. See `.coord/notes/U95-R_audit.md`.
   - Pass condition: a research-kind pilot run that writes outside `.coord/stage/<task>/` is refused, with a test.
2. **U96-N: rename U63 `coord thrift`.**
   - Its NORMAL/THRIFT/HANDOFF_READY ladder calls the default state "NORMAL", which contradicts `v7_harness/coord/mode.py` (token-thrift is the default).
   - Rename the states, for example to AMPLE/LOW/HANDOFF_READY. Keep `tests/test_u63_thrift_mode.py` semantics, and update its names only through the manual.
3. **U96-D: trim the diet `AGENTS.md`.**
   - The Codex budget is 32 KiB; global 14,207 B plus project 18,403 B leaves a margin of 158 B.
   - Whether the global file counts toward `project_doc_max_bytes` is UNKNOWN (the docs do not say). Trim to at least 2 KiB of margin anyway.
4. **U95-E: measure the cache and compaction levers.**
   - Run an A/B with `python -m v7_harness.cost_meter` on two comparable cards before adopting any Codex config lever from `.coord/notes/U95_token_thrift_research.md`.

Codex re-review is owed for U95-A/B/T and the U95-R audit (acting judge: claude).

## Status 2026-09-30 (second session)

- U96-S, U96-N and U96-D are done in PR #69 (branch `claude/u96-queue`); the full suite passed 1267 tests. Codex re-review is owed for all three.
- U95-E is not started. It is blocked on two things: the A/B needs Codex ACTIVE to run the two comparable cards, and adopting a Codex config lever changes tool settings, which waits for 윤겸스.
- `card_cost --card U96-SND-ACTING` measured 12,031,135 tokens, 2.34x the baseline. It returned `next_card_allowed: false`, so a fresh session takes the next card.
