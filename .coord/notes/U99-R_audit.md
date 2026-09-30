# U99-R audit and U99 review verdict (judge: claude acting for Codex, 2026-09-30; Codex re-review owed)

## U99-R run (Antigravity web research)

- Result: acceptance `python .coord/tasks/U99-R-check.py` exit 0 (12 rows, 6 verdicts), DRY_RUN_PASSED, but COST_EXCEEDED: 409,369 tokens against the 200,000 cap (2.0x). The budget rule rejects it, so it is not approved. The note is kept as evidence only: `.coord/notes/U99_uaos_rsi_research.md`, copied from the stage.
- Containment held for the first time: the only write was inside `.coord/stage/U99-R`. What changed: the manual named the absolute stage path and said a write outside it fails the run. U95-R and U98-D-R had both escaped the stage.
- The first attempt was killed at session end; `pilot reconcile` marked it ABANDONED, and the re-run started clean.
- The judge re-opened 3 sources. Quotes R1, R2, R7, R10 and R11 match the pages (code.claude.com hooks, arXiv 2505.22954, arXiv 2503.13657).
- Defects:
  - R3, R4 and R5 repeat U95 rows, although the frame listed those as non-goals: 3 of 12 rows were wasted.
  - The verdicts overclaim in 3 places, corrected below.

## Corrected verdicts

- H1 SUPPORTED: hooks block deterministically (R11). The local receipts point the same way: the rule text did not stop dictation, and the U98-D gate did.
- H2 UNKNOWN: no public source says how subscription limits weight cache reads.
- H3 MIXED, not SUPPORTED: R12 gives only the context length, not task reliability. Local ledger: Ollama 8 PASS in 39 rows; it passes small specs (U98-D-L4, U98-D-F1-L2) and fails on prompts over 12,288 tokens.
- H4 SUPPORTED: every tool has its own rule file, size limit and hook mechanism, so one shared core plus per-tool adapters fits.
- H5 SUPPORTED, but only for sandboxing and human oversight (R7, R8). "Immutable evaluators" and "objective hacking" were not shown by the quoted text. They stay project policy, not evidence.
- H6 SUPPORTED for the failure taxonomy: 14 modes in 3 categories, over 1600+ traces in 7 frameworks (R10). The claim that contract manuals and judges fix these failures is UNMEASURED.

## Decision (MIA Review): GO

Keep canon v7.2.0 as the shared core. Turn the rules that matter into hooks and gates, and add no further rule text without a gate.

## Recurring cause: Antigravity research caps (seen 5 times)

Ledger rows for Antigravity research runs:

| work_id | tokens | vs cap |
|---|---|---|
| U47-R1 | 855k | BLOCKED |
| U47-R2 | 1.14M | BLOCKED |
| U95-R | 3.14M | 10.5x |
| U98-D-R | 536k | 1.8x |
| U99-R | 409k | 2.0x |

The one PASS was a consult run of 89k (U46-J3).

- Caps of 200k–300k are below every measured research run. So the budget gate blocks each one, and the output is used "as evidence only", which empties the gate.
- Fix, a procedural one with no gate-code change: size an Antigravity research cap at 40k tokens per requested row plus a 50k buffer. U99-R measured 409k over 12 rows, 34k per row. Otherwise, split the research to at most 6 rows per run.
- Antigravity tokens come from a separate subscription, not from the Claude or Codex limits this project's yardstick measures.

## Antigravity's U99 memo (`.coord/tasks/U99-decision-memo.md`) — kept as its draft, corrected here

- It says PR #73 was "merged into main" by Antigravity. 윤겸스 merged it; Antigravity only pushed and opened it.
- It leaves out the U99-R cost overrun and the missing hook deploy. The merged hook was not installed at `~/.uaos/hooks/codex_delta.py` until the judge copied it (backup `.work/backup_20260930/codex_delta.py`).
- Antigravity's manual test runs left 4 cursor files in `~/.uaos/hooks/` (`codex_delta_cursor_test_*`, `codex_delta_cursor_claude_next_session.json`). They are harmless, and deleting them waits for 윤겸스.

## U99-M verdict (Antigravity implementation, PR #73 merged)

- PASS by an independent run on main 568d8e9:
  - `python -m unittest tests.test_u99m_mailbox_delta`: 4 OK. The test file is byte-identical to the judge's fixed acceptance.
  - Full suite: 1287 OK (skipped 6), log `.work/u98/full_u99m.log`.
- Deployed to `~/.uaos/hooks/codex_delta.py`. A smoke run with this session's id printed relay_d733078b as Korean text, where the old hook showed raw JSON.
- P3: a non-string `session_id` raises TypeError in `cursor_for`. The hook's outer handler catches it, so the prompt is never blocked. `cursor_for` also has no why-comment.
