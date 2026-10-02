```contract
work_id: U124-L
worker: local
goal: existing .py files always get find-and-replace rules in the Ollama worker; Ollama copies two dictated edits, Antigravity U23 style (U124)
inputs:
- v7_harness/adapters/ollama_worker.py sha256=1df20171a36ef67b5dc03ee256874d14fb0792c33cbb3b718941d2fb2a1c1340
allow:
- v7_harness/adapters/ollama_worker.py
acceptance: python -m unittest tests.test_u124_edit_rules_for_py tests.test_u109_def_splice tests.test_u22_worker_limits
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

# Work order: existing .py files always use find-and-replace (U124)

- Target file: `v7_harness/adapters/ollama_worker.py`
- Anchor: `EDIT_MODE_MIN_LINES`

Apply the two edits below to the file exactly. Copy them as written. Change nothing else.

===EDIT: v7_harness/adapters/ollama_worker.py===
<<<<<<< SEARCH
SLICE_WINDOWS = (25, 10, 3)  # lines kept on each side of an anchor; try wider first, shrink until it fits
=======
SLICE_WINDOWS = (25, 10, 3)  # lines kept on each side of an anchor; try wider first, shrink until it fits


def _rules_for(named: list[tuple[str, str]]) -> str:
    """U124: an existing .py file always gets find-and-replace. A whole-file rewrite let the 7B model drop untouched
    functions (U123-L and U123-L2 lost two helpers of a 140-line file). Other files keep the length rule."""
    if any(name.endswith(".py") for name, _text in named):
        return EDIT_RULES
    longest = max((len(text.splitlines()) for _name, text in named), default=0)
    return EDIT_RULES if longest >= EDIT_MODE_MIN_LINES else FORMAT_RULES

>>>>>>> REPLACE

===EDIT: v7_harness/adapters/ollama_worker.py===
<<<<<<< SEARCH
    longest = max((len(text.splitlines()) for _name, text in named), default=0)
    rules = EDIT_RULES if longest >= EDIT_MODE_MIN_LINES else FORMAT_RULES
=======
    rules = _rules_for(named)
>>>>>>> REPLACE


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
