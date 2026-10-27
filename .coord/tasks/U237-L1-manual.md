# U237-L1: Haiku 5.5 + Ollama 3-tool shared worker pool selector (`select_pool_worker`)

```contract
work_id: U237-L1
worker: local
goal: Add select_pool_worker in v7_harness/worker_routing.py to return local qwen2.5-coder:7b or bounded uaos-haiku-worker subagent with exact model pinning
inputs:
- v7_harness/worker_routing.py sha256=bde0cd12524a0037ff1c3e47e43fbf36c667c540c426f876fd94a7d80129e1ef
- tests/test_u237_haiku_worker_pool.py sha256=268c7c849b73647e95f39f2d64d1debd511bd708f57b5e5be02cd620b0b8dae3
allow:
- v7_harness/worker_routing.py
context_allow:
- tests/test_u237_haiku_worker_pool.py
acceptance: C:\Python314\python.exe -m unittest tests.test_u225_worker_routing tests.test_u237_haiku_worker_pool
forbidden: editing or deleting tests; edits outside allow; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 300 seconds
judge: claude
timeout_s: 300
remote_budget_tokens: 0
```

## Exact edit in `v7_harness/worker_routing.py`: keep `_remote` and add `select_pool_worker`, verbatim

```python
def _remote(task, availability, total):
    if not task['allow_remote'] or availability.get('haiku') is not True:
        return _answer(None, 'NO_EXPLICIT_AVAILABLE_HAIKU_ROUTE', 'BLOCKED')
    if (not _integer(task.get('budget_tokens'), 1) or not _positive(task.get('budget_usd'))
            or not _positive(task.get('timeout_s'))):
        return _answer(None, 'REMOTE_POSITIVE_CAPS_REQUIRED', 'BLOCKED')
    if task['input_tokens'] <= 0 or task['output_tokens'] <= 0 or total > task['budget_tokens']:
        return _answer(None, 'REMOTE_TOTAL_TOKEN_CAP', 'BLOCKED')
    try:
        estimated = forecast(calls=1, input_tokens=task['input_tokens'], output_tokens=task['output_tokens'])
    except (OverflowError, ValueError):
        return _answer(None, 'INVALID_PRICE_SCENARIO', 'BLOCKED')
    if estimated['estimated_usd'] > task['budget_usd']:
        return _answer(None, 'REMOTE_ESTIMATED_USD_CAP', 'BLOCKED')
    result = _answer('claude', 'EXPLICIT_CAPPED_HAIKU_REQUIRES_PILOT_ADMISSION', model=HAIKU)
    result.update(estimated)
    return result


def select_pool_worker(task: dict, availability: dict) -> dict:
    """Resolve 3-tool worker pool dispatch spec (local Ollama coder vs bounded Haiku 5.5 subagent)."""
    decision = dict(plan(task, availability))
    worker = decision.get('worker')
    if worker == 'local':
        decision['model'] = 'qwen2.5-coder:7b'
        decision['subagent'] = None
        decision['require_exact_model'] = False
        decision['model_pin'] = 'none'
    elif worker == 'claude' and decision.get('model') == HAIKU:
        decision['subagent'] = 'uaos-haiku-worker'
        decision['require_exact_model'] = True
        decision['model_pin'] = 'exact'
    else:
        decision['subagent'] = None
        decision['require_exact_model'] = False
        decision['model_pin'] = 'none'
    return decision
```
