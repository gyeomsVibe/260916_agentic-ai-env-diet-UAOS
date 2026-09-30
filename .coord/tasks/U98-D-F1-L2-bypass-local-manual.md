```contract
work_id: U98-D-F1-L2
worker: local
goal: Close three delegation-gate bypasses in v7_harness/delegation.py: other code suffixes and case, non-failure outcomes, and failed rows of another card.
inputs:
- v7_harness/delegation.py sha256=fb3e66637b338e0fceb7b8a2b960f315b3f8fd6bfd27792606961a769bd1efc9
- tests/test_u98d_f1_bypass.py sha256=ec6336fc1c33bb291d128c90c4e7572dd0f9421715e7cb14a130eb421a24c341
allow:
- v7_harness/delegation.py
context_allow:
- v7_harness/delegation.py
- tests/test_u98d_f1_bypass.py
acceptance: python -m unittest tests.test_u98d_f1_bypass.F1BypassTests.test_other_code_suffixes_and_case_count tests.test_u98d_f1_bypass.F1BypassTests.test_paths_are_normalized_before_the_tests_exemption tests.test_u98d_f1_bypass.F1BypassTests.test_only_real_failure_outcomes_count tests.test_u98d_f1_bypass.F1BypassTests.test_failed_run_must_belong_to_the_same_card tests.test_u98d_delegate_first
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

## Task (U98-D-F1): close three bypasses in `v7_harness/delegation.py`

Rewrite the whole file `v7_harness/delegation.py` with a ===FILE block. Keep everything that is not listed below: the imports, `DICTATION_CODE_LINE_LIMIT = 20` with its comment, `DELEGATE_WORKERS`, the three functions and their docstrings, and the exact `DELEGATE_FIRST:` message text.

Changes:

1. Add a constant after `DELEGATE_WORKERS`, with the comment line `# Code a shell or runtime executes; a dictated script is dictated code too (U98-D-R P1).` above it:
   `CODE_SUFFIXES = (".py", ".pyw", ".pyi", ".ps1", ".psm1", ".sh", ".bat", ".cmd", ".js", ".ts")`

2. Add a constant, with the comment line `# Outcomes that mean the delegate really failed; APPROVE, PASS or no outcome never unlock apply (U98-D-R P1).` above it:
   `FAILED_OUTCOMES = frozenset({"FAIL", "FAILED", "BLOCKED", "UNUSABLE", "REWORK", "REJECTED"})`

3. Add a function `_normalize(path: str) -> str` with a one-line docstring. It returns `path.strip().replace("\\", "/")`, then removes every leading `"./"` in a `while` loop.

4. Add a function `_card(work_id: str) -> str` with a one-line docstring. It returns `str(work_id or "").split("-")[0]`.

5. In `dictated_code_lines`, for both loops: set `path = _normalize(m.group("path"))`. Count the block only when `path.lower().endswith(CODE_SUFFIXES)` and `not path.startswith("tests/")`.

6. Change `_failed_delegate` to take a third parameter: `_failed_delegate(project: Path, work_id: str, card: str) -> bool`.
   - At the start, return False when `card` is empty or `_card(work_id) != card`.
   - Replace the check `row.get("outcome") != "PASS"` with `row.get("outcome") in FAILED_OUTCOMES`.

7. In `delegate_first_errors`, call `_failed_delegate(Path(project), after, _card(contract.get("work_id")))`.

Do not change any other file.

### The previous attempt (U98-D-F1-L1) was rejected for one defect

It replaced the two existing constants instead of adding to them. `DICTATION_CODE_LINE_LIMIT` and `DELEGATE_WORKERS` disappeared, so the import failed. The constants section at the top of the new file must hold all four constants, in this order:
DICTATION_CODE_LINE_LIMIT, DELEGATE_WORKERS, CODE_SUFFIXES, FAILED_OUTCOMES.
Put each comment on its own line above its constant, and separate top-level functions by two blank lines.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
