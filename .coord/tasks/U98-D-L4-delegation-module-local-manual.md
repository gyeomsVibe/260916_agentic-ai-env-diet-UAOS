```contract
work_id: U98-D-L4
worker: local
goal: Create v7_harness/delegation.py: count dictated non-test Python lines in a manual and refuse worker apply over 20 lines unless apply_after names a failed delegate run in the ledger.
inputs:
- tests/test_u98d_delegate_first.py sha256=b9de05f5a55e15e4f8ac9132304c78c1cb3a81e3ab5099718279e57a610bd0ca
allow:
- v7_harness/delegation.py
context_allow:
- tests/test_u98d_delegate_first.py
acceptance: python -m unittest tests.test_u98d_delegate_first.DelegateFirstTests.test_limit_is_twenty tests.test_u98d_delegate_first.DelegateFirstTests.test_edit_blocks_count_replace_lines_only
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

## Task (U98-D delegation-first gate)

Receipt: from 2026-09-26 to 09-30 the ledger `.coord/usage/runs.jsonl` holds 174 `apply` rows against 14 Ollama and 17 Antigravity rows. The paid conductor dictated all code to `worker: apply`, so the delegate routes were skipped.

Make exactly one change: create one new file. Another card hooks it into lint later.

### Change 1: create the new file `v7_harness/delegation.py`

It must contain:

1. `from __future__ import annotations`, then `import json`, `from pathlib import Path`, `from typing import Any`.
2. `from v7_harness.adapters.ollama_worker import BLOCK_RE, EDIT_RE`.
3. The constant `DICTATION_CODE_LINE_LIMIT = 20`, with a comment above it saying: a longer code patch costs the paid conductor more output tokens than a spec for a delegate; policy value, UNMEASURED until an A/B.
4. The constant `DELEGATE_WORKERS = frozenset({"ollama", "local", "cascade", "agy", "lane"})`.
5. Function `dictated_code_lines(text: str) -> int`:
   - For each match of `BLOCK_RE.finditer(text)`, take `m.group("path").strip()` and `m.group("body")`.
   - For each match of `EDIT_RE.finditer(text)`, take `m.group("path").strip()` and `m.group("replace")`. Do not count the `search` group.
   - Count a block only when its path ends with `.py` and does not start with `tests/`.
   - For a counted block, add the number of non-blank lines, i.e. lines where `line.strip()` is not empty.
   - Return the total.
6. Function `_failed_delegate(project: Path, work_id: str) -> bool`:
   - Import `shared_desk` inside the function: `from v7_harness.coord.hook_context import shared_desk`.
   - Read `shared_desk(project) / ".coord" / "usage" / "runs.jsonl"`. If the file is missing or unreadable (`OSError`), return False.
   - Parse each non-empty line with `json.loads` and skip lines that raise `ValueError` or that are not a dict.
   - Return True if any row has `row.get("work_id") == work_id`, `row.get("worker") in DELEGATE_WORKERS` and `row.get("outcome") != "PASS"`. Otherwise return False.
7. Function `delegate_first_errors(text: str, contract: dict[str, Any], project: Path) -> list[str]`:
   - If `contract.get("worker") != "apply"`, return `[]`.
   - Set `lines = dictated_code_lines(text)`. If `lines <= DICTATION_CODE_LINE_LIMIT`, return `[]`.
   - Set `after = str(contract.get("apply_after") or "").strip()`. If `after` is non-empty and `_failed_delegate(Path(project), after)` is True, return `[]`.
   - Otherwise return a list with one string, starting exactly with `DELEGATE_FIRST:`, then: ` {lines} dictated code lines > {DICTATION_CODE_LINE_LIMIT}; write a spec for worker local (Ollama) or agy first, and apply only with apply_after: <work_id of that failed run>`.
8. Every function has a one-line docstring.


### The previous attempt (U98-D-L3) was rejected by the judge for three defects. Avoid them:

1. No docstrings. Put a one-line docstring as the first statement of each of the three functions.
2. The error message ended with `apply_after: {after}`. It must end with the literal text `apply_after: <work_id of that failed run>`, not a variable.
3. A ledger line holding JSON that is not a dict (for example `[1, 2]`) crashed with AttributeError. After `row = json.loads(line)`, skip the row with `continue` when `not isinstance(row, dict)`.

Also put the policy comment on its own line above `DICTATION_CODE_LINE_LIMIT`, and separate top-level definitions by two blank lines.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
