```contract
work_id: U98-D-L2
worker: local
goal: Add the delegation-first gate: lint refuses a worker apply manual that dictates more than 20 non-test Python lines unless apply_after names a failed delegate run in the ledger.
inputs:
- v7_harness/manual.py sha256=9702fa5fbb470a57a15a806e62c44031a089ef020aa4801dd7dc752153842a38
- tests/test_u98d_delegate_first.py sha256=b9de05f5a55e15e4f8ac9132304c78c1cb3a81e3ab5099718279e57a610bd0ca
- v7_harness/adapters/ollama_worker.py sha256=0d1c6a24721c32fc041395210cd80b5af95750f880f96f42ee9631922680c3db
allow:
- v7_harness/delegation.py
- v7_harness/manual.py
context_allow:
- tests/test_u98d_delegate_first.py
acceptance: python -m unittest tests.test_u98d_delegate_first tests.test_u34_precision_harness tests.test_u36_evidence_gated_rsi tests.test_u38_cost_gate_and_claude_worker tests.test_u44_claude_contract tests.test_u45_general_uaos tests.test_u46_followup_fixes
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

## Task (U98-D delegation-first gate)

L2: the first run (L1) was refused before any model call, PROMPT_TOO_LARGE (~14,130 tokens > 12,288), so this run shows only the test file as context.

Receipt: from 2026-09-26 to 09-30 the ledger `.coord/usage/runs.jsonl` holds 174 `apply` rows against 14 Ollama and 17 Antigravity rows. The paid conductor dictated all code to `worker: apply`, so the delegate routes were skipped.

Make exactly two changes.

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

### Change 2: edit `v7_harness/manual.py`

`manual.py` has more than 150 lines, so use an EDIT block. Find this exact line inside `lint()`:

        report.errors.append("NO_BLOCKS_FOR_APPLY: worker apply needs ===FILE/===EDIT blocks in the manual")

Replace it with that same line followed by these two new lines. They have the same indentation as the `if worker == "apply" and not blocks:` line above it, i.e. 4 spaces:

    from v7_harness.delegation import delegate_first_errors
    report.errors.extend(delegate_first_errors(text, contract, project))

Do not change anything else in `manual.py`.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
