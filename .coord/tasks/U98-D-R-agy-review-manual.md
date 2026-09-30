```contract
work_id: U98-D-R
worker: agy
goal: Independent adversarial read-only review of the U98-D delegation-first gate: find ways to apply more than 20 lines of non-test code by worker apply without a real failed delegate run.
inputs:
- v7_harness/delegation.py sha256=fb3e66637b338e0fceb7b8a2b960f315b3f8fd6bfd27792606961a769bd1efc9
- v7_harness/manual.py sha256=603ca443ab6942ed06a8d22cad0519ea6df360cb23655f216e7118dd1ffdd390
- tests/test_u98d_delegate_first.py sha256=b9de05f5a55e15e4f8ac9132304c78c1cb3a81e3ab5099718279e57a610bd0ca
- .coord/tasks/U98-D-R-check.py sha256=3f0bb0414db8ba753a8927ea0d384854430767a9585be9060df2b69967cbec98
allow:
- .coord/notes/U98-D-agy-review.md
acceptance: python .coord/tasks/U98-D-R-check.py
forbidden: editing, creating or deleting any file except the one allowed file and scratch files under .coord/stage/U98-D-R; editing U98-D-R-check.py; appending to .coord/usage/runs.jsonl; git of any kind; network; installing anything; reading or printing .env files, keys, tokens, credentials, cookies or session values; approving your own output
stop: the acceptance command passes; or two failures with the same cause; or the token budget is reached (write what you have)
judge: claude
timeout_s: 1500
remote_budget_tokens: 300000
```

## Instructions for the worker

## Why (context for the worker)

Receipt: from 2026-09-26 to 09-30 the ledger held 174 `worker: apply` runs against 14 Ollama and 17 Antigravity runs. The paid conductor wrote all code itself and sent it to `apply`, so the delegates were skipped. Card U98-D adds a gate:
- `v7_harness/delegation.py` counts dictated non-test Python lines in a manual. Ollama wrote this file (run U98-D-L4).
- `v7_harness/manual.py` `lint()` now calls `delegate_first_errors`. A `worker: apply` manual with more than 20 such lines gets the error `DELEGATE_FIRST`, unless `apply_after: <work_id>` names a failed delegate run in `.coord/usage/runs.jsonl`.
- `pilot run` calls lint, so the gate also blocks runs.

You are the independent reviewer. The author (claude) may not judge its own gate.

## Task: adversarial read-only review

Try to get more than 20 lines of non-test code applied by `worker: apply` without a real failed delegate run. For each attack, say whether the gate stops it. Candidates to check (add your own):
1. Paths the counter skips: `.pyi`, upper-case `.PY`, `./v7_harness/x.py`, backslash paths, `tests/` prefixes used for non-test code, and non-Python code such as `.ps1`, `.js`, `.sh`.
2. Splitting one change across several apply manuals of 20 lines each.
3. Forging `apply_after`: can the conductor append a failed `ollama` row to the ledger itself? Does anything tie the row to a real pilot run?
4. Routes around lint: `pilot run` without `--manual`, `worker: auto` or `cascade` falling back to apply, and `worker: claude`.
5. Correctness: EDIT counting, blank lines, and a malformed or missing ledger.

You may run read-only commands and scratch Python in `.coord/stage/U98-D-R/`, for example `python -m v7_harness.cli pilot manual lint --manual <scratch manual> --source .`.

## Output

Write exactly one file, `.coord/notes/U98-D-agy-review.md`, containing:
- One line `VERDICT: PASS` or `VERDICT: FAIL`. Use FAIL if any P1 or P2 bypass works.
- A table with one row per finding: `| P1 | v7_harness/delegation.py:18 | attack | expected vs observed |`. P1 means the gate is bypassed with no effort, P2 means bypassed with some effort, P3 is minor.
- Every command you ran, with its exit code.

Then stop. Keep it short: the cap is 300,000 tokens, and the previous Antigravity run overran its cap by 10.5 times.


## Output

- Edit the files under `allow` directly with your file tools. Your reply is not applied: ===FILE / ===EDIT blocks in it are ignored. End with one line saying what you changed. Do not claim success; the acceptance command decides.
