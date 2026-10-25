# U237D: user-desk window titles converge on the full, per-window title in all three tools

Card id: assigned as U237; renamed U237D on 2026-10-26 because Antigravity's branch `agy/u237-haiku-worker-pool`
(commit aeec1ff) already holds `.coord/results/U237.md` and `.coord/tasks/U237-L1-manual.md`. The first three
slices ran as work ids U237-A1, U237-L1 (REWORK), U237-L1R, U237-L1B; later slices use U237D-*.

Author: claude, deputy conductor while Codex is LIMITED (Codex re-review owed). Base: origin/main 60b63bc,
runtime 0.3.0-532129a3276c. Judge: claude (deputy); review `pilot review --reviewer agy`; audit Antigravity.

## Receipts (measured 2026-10-25, 윤겸스 report)

1. Codex: thread 01a17325 is `CONVERGED` in `.coord/presence/user_windows.json` with desired
   `[사용자 대화창구-261025-2] 창구·호출기록 개선`, but `state_5.sqlite threads.name` is only the prefix. Cause:
   `user_window._shows` compares only the `TITLE_RE` prefix, and the prefix-era `reconcile` (it also runs on relay
   prompts that the native path skips) marks the entry converged, after which nothing repairs the suffix.
   The "mojibake" in `~/.codex/session_index.jsonl` was a cp949 console artifact: read as UTF-8, 13:00:19 is
   Codex's own auto title `사용자 창구 인계 및 계획 진행` and 13:01:17 the prefix-only rename the prefix-era
   instruction asked for. No encoding fix is needed.
2. Claude: `_claude_title` reads `%APPDATA%/Claude/claude-code-sessions/*/*/local_*.json`, gone since the desktop
   app became an MSIX package. Readback is always UNKNOWN, so desks 46c52914 and c3a04094 went `BLOCKED` while
   the session transcript (`transcript_path` in every hook event) holds 82 `{"type":"custom-title",
   "customTitle":...,"sessionId":...}` records, the last one `[사용자 대화창구-261025-2] 모델고정·호출기록 착지`
   (the window named itself).
3. All tools: the suffix is the one project-wide accepted topic, so every window shows `창구·호출기록 개선`.

## Decision (deputy; Codex re-review owed)

- Convergence compares the full desired title (`_shows`: exact equality). The prefix-era `reconcile` leaves
  desks that the native adapter manages (`adapter_version` set) to `desk_title.reconcile_title`.
- Claude readback: the last `custom-title` record of this session in the hook event's `transcript_path` (tail
  4 MiB; the record is re-appended every turn), then the old app store as a second source.
- UNKNOWN readback never yields `BLOCKED`: after the bounded budget it is `UNVERIFIED` (quiet, re-read every
  prompt); only a known other title after the budget is `BLOCKED`.
- Claude repair path: emit 1 is hook `sessionTitle` only (U229 acceptance); from emit 2 the explicit
  `set_session_title` instruction is added, since `sessionTitle` landed late.
- Per-window topic (suffix): `entry.topic`, set once by that window only. Sources in order: its own declaration
  (first non-declaration sentence, URLs/paths/brackets removed, cut at a word to 16 chars); a title the window
  gave itself (prefix + valid topic other than the shared one) is adopted; else the shared accepted topic is
  shown as a fallback and is not stored. Ollama `local_draft` is not called inside the hook: the hook has a 10 s
  budget and a proposal needs deterministic validation anyway; a later card may add an off-hook proposer.
- `ADAPTER_VERSION` becomes `U237_NATIVE2`, so every existing desk (BLOCKED ones included) gets one fresh budget.

Alternatives: (B) keep the shared topic and only fix convergence: rejected, receipt 3 stays. (C) let Ollama
name every window in the hook: rejected, latency and nondeterminism inside a 10 s hook.

## Allowed files

- `v7_harness/coord/user_window.py`, `v7_harness/coord/desk_title.py` (implementation, via pilot bundles).
- `tests/test_u237_desk_titles.py` (new fixed acceptance, judge-owned), `tests/test_u207_desk_title_handoff.py`
  (one assertion superseded by the decision above: UNKNOWN-only cap state `BLOCKED` -> `UNVERIFIED`).
- `cli.py` is not changed: its existing claude branch already strips `USER WINDOW:` lines from `on_prompt` and
  appends `native["instruction"]`, which now carries the repair line. U229B2's `cli.py` hunk is untouched.

## Fixed acceptance (written first, red before implementation: 7 failures, 3 errors)

`python -m unittest tests.test_u237_desk_titles tests.test_u207_desk_title_handoff tests.test_u229_independent_title tests.test_u229_title_worker tests.test_u234_title_consensus tests.test_u150_user_window`

Covers: Codex prefix-only name never converges (and a later relay prompt does not converge it); Claude
transcript readback (exact session only, missing file UNKNOWN) and convergence; UNKNOWN never BLOCKED, known
mismatch after budget BLOCKED; Claude repair instruction from emit 2; old BLOCKED entry gets a fresh budget;
topic extraction; per-window topics over the shared one for codex/antigravity (agy store write gets the full
title) with fallback for claude; another window's declaration never changes a topic; self-named title adopted,
invalid one not; 8 parallel hooks keep the emit cap; 6 parallel declarations across 3 tools keep every entry
and topic. Fake stores only. Full suite `python -m unittest discover -s tests -t .` exit 0, log in `.work/u237/`.

## Slices

- U237-A1 `worker: apply` (`U237D-A1-apply-manual.md`): the one-line `ADAPTER_VERSION` constant (top-level
  assignment; the splicer replaces only whole functions, U236A-L2 SPLICE_UNSUPPORTED). PASS, approved.
- U237-L1 / U237-L1R `worker: local` (`U237D-L1-manual.md`, `U237D-L1R-manual.md`): transcript readback and
  `_shows`. L1 REWORK came from the author's slice acceptance (it held a test needing L1B); L1R PASS, approved.
- U237-L1B `worker: local` (`U237D-L1B-manual.md`): topic extraction, `_full_title`, `_take_emit`, `reconcile`,
  `on_prompt`. PASS, approved.
- U237D-L2 `worker: local` (`U237D-L2-manual.md`): whole functions in `desk_title.py`; full fixed acceptance.

## Stop rules

Two failures with the same cause on a slice: re-cut smaller once, then `apply_after`. Input hash mismatch,
edits outside allow, empty output: FAILED. Any change to the fixed acceptance after dispatch voids PASS.
No write to real Codex/Claude/Antigravity stores in tests. No commit without `card audit --card U237`.
