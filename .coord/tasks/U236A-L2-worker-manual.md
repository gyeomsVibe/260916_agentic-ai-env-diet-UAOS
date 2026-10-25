# U236A-L2: exact-model guard, slice 1 of 3 (claude_worker.py only)

Re-cut of U236A-L1 (REWORK: one pass over three files broke u38/u68 envelopes). Same rev-2 contract
(`.coord/tasks/U236A-L1-manual.md`); this slice touches only the worker adapter. Slices 2 (cli.py) and 3
(manual.py) follow with their own manuals.

```contract
work_id: U236A-L2
worker: local
goal: claude_worker --require-model fails closed when modelUsage keys differ from the pinned full model id
inputs:
- v7_harness/adapters/claude_worker.py sha256=e2fe98b551e26421ab3f8f08dfbeb293cc77d6d2d6fc93638bb90dc0b415079f
- tests/test_u236a_model_pin.py sha256=54441760f3e03595d249e5b257fb190e209e0937742cc52ecbfc053684321dd6
allow:
- v7_harness/adapters/claude_worker.py
context_allow:
- tests/test_u236a_model_pin.py
acceptance: python -m unittest tests.test_u236a_model_pin.WorkerGuardTests tests.test_u38_cost_gate_and_claude_worker tests.test_u68_claude_worker_utf8 tests.test_u44_claude_contract tests.test_u45_general_uaos
forbidden: editing or deleting tests; changing behavior without --require-model; edits outside allow; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 900 seconds
judge: codex
timeout_s: 900
remote_budget_tokens: 0
```

## Exact edits (apply verbatim; nothing else changes)

1. Insert this function right after the end of `cap_overshoot` (before `def main`):

```python
def model_mismatch(result: dict, pinned: str) -> str:
    """U236a: under --require-model every modelUsage key must be the pinned full id; anything else fails closed."""
    keys = sorted(str(key) for key in (result.get("modelUsage") or {}))
    return "" if keys == [pinned] else f"MODEL_MISMATCH: expected {pinned}, got {keys}"
```

2. In `main`, after the line `parser.add_argument("--max-budget-usd", dest="max_budget_usd", default=None)` add:

```python
    parser.add_argument("--require-model", dest="require_model", default=None)
```

3. Replace the whole inner `envelope` function with:

```python
    def envelope(status: str, response: str, usage: dict, error: str = "", extra: dict | None = None) -> int:
        # U68: ASCII escapes, not ensure_ascii=False. On Windows the pilot's pipe is cp949, and an answer holding
        # U+2014 raised UnicodeEncodeError after the paid call (U67-C1), leaving no envelope. JSON escapes decode back
        # to the same text under any stdout encoding.
        payload = {"status": status, "response": response, "usage": usage, "conversation_id": "claude-worker",
                   "error": error}
        payload.update(extra or {})
        print(json.dumps(payload, ensure_ascii=True))
        return 0 if status == "SUCCESS" else 1
```

4. Replace the last line of `main` (`return envelope("SUCCESS", ...` ) with:

```python
    extra = None
    if args.require_model:
        mismatch = model_mismatch(result, args.require_model)
        if mismatch:
            return envelope("FAILED", "", usage, mismatch)
        extra = {"resolved_models": sorted(str(key) for key in (result.get("modelUsage") or {}))}
    return envelope("SUCCESS", str(result.get("result") or "").strip()[:2000] or "(claude ended without a summary)", usage,
                    extra=extra)
```

## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
