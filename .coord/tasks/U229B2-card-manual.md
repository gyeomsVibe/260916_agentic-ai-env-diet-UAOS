# U229B2: invocation journal (B2 release), re-landed on U236a through pilot slices

Author: claude (user desk, deputy while Codex is LIMITED). Codex re-review owed.

## Why

The B2 journal was written directly in `.work/wt_u229_b_journal` (base ba2a884) and the commit gate refused it
(source not from an APPLIED pilot bundle). Antigravity REVISE (relay_bd24f651) asked to rebase onto U236a first and
to resend the audit with the actual diff and test output. The rebase is done: `U229B2-reference-source.patch`
(490 lines, 5 source files) applies on `claude/u229-b2-journal` (base U236a 18fb281), with one merged conflict in
`claude_worker.main` (`envelope` keeps U236a's `extra` and B2's journal finish; MODEL_MISMATCH also sets
`journal_failure = "MODEL_MISMATCH"`). With it applied, the focus acceptance below passed, exit 0.

## Goal, done, non-goals

- Goal: the 5 source changes in the reference patch land on `claude/u229-b2-journal` through pilot bundles.
- Done: every source hunk APPLIED by a pilot bundle with an independent PASS review; acceptance exit 0; full suite
  `python -m unittest discover -s tests -t .` exit 0 (log in `.work/`); Antigravity audit with the real diff and test
  output; `card audit --card U229B2` ok; commit with `Card: U229B2` and `Audit: relay_<id>`; push; PR to main;
  RESULT line to the user desk.
- Non-goals: any change beyond the reference patch; test edits; paid model calls beyond agy review.

## Fixed acceptance (frozen, committed before any worker)

- `tests/test_u229_claude_journal_worker.py` sha256=6b5721c9b4371eb26cc21c0a046851ad11ae3453f1162c3df5a33e9261779b69
- `tests/test_u229_independent_invocation.py` sha256=e755fafb36ca36a071835f67ab52e259eaf40563d8ad38e84cfdf2f8f7e1201c
- `tests/test_u229_olla_embed_journal.py` sha256=05c693f9beb392f0eeac936a5df82c151721136d631ea1e94397c5ef0b7806d2
- Command: `python -m unittest tests.test_u229_claude_journal_worker tests.test_u229_independent_invocation tests.test_u229_olla_embed_journal tests.test_u236a_model_pin tests.test_u38_cost_gate_and_claude_worker tests.test_u68_claude_worker_utf8 tests.test_cli`

## Slices (Ollama `worker: local` first; whole top-level functions only)

The splicer replaces or adds whole top-level functions; statement fragments fail SPLICE_UNSUPPORTED (U236A-L2). Each
slice dictates verbatim functions from the reference patch, `judge: claude`, then `pilot review --reviewer agy
--budget 120000 --timeout 600`, then `pilot run ... --approve <bundle>`. A failed id is never reused.

1. `v7_harness/invocation.py` (new file, about 250 lines): skeleton (imports, constants, `InvocationError`) then
   functions in 2-3 slices. Split again on PROMPT_TOO_LARGE.
2. `v7_harness/adapters/claude_worker.py`: imports, `_journal_start`, `_journal_usage`, `_journal_finish`,
   `_journal_abort`, whole `main`.
3. `v7_harness/adapters/ollama_worker.py`: rename `_generate` to `_generate_raw`, new `_generate` wrapper.
4. `v7_harness/olla.py`: rename `_post` to `_post_raw`, new `_post` wrapper.
5. `v7_harness/cli.py`: 7-line hunk inside `main` -> `worker: apply` (U98-D, under 20 lines).

Import-line edits that are not whole functions go through `worker: apply` when under 20 lines.

## Stop

Two failures with the same cause: re-cut once, then `apply_after: <failed id>`; edits outside allow; input hash
mismatch; any test edit. Report BLOCKED with evidence to the user desk instead of bypassing the commit gate.
