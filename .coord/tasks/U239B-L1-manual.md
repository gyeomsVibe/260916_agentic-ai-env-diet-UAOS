# U239B-L1: Corrective RSI Value Evaluator (`evaluate_roi_metrics` provider & first-attempt semantics)

```contract
work_id: U239B-L1
worker: local
goal: Replace evaluate_roi_metrics in v7_harness/invocation.py to classify local/paid/unknown via provider metadata and compute first_pass_yield from first attempt per work_id
inputs:
- v7_harness/invocation.py sha256=cf770b04c7d988c9bacf0fd68265f023b82b64fb5564e7f358b96eced601c26e
- tests/test_u239_rsi_evaluator.py sha256=12a3c4a313fef9255e2c582a2a54c31f5e287697dc8adb13ee893ad3835212a3
- tests/test_u239b_rsi_counterexamples.py sha256=ececc48328aa2405248e85fde776ae370828906c725e0ead662239deeffae547
allow:
- v7_harness/invocation.py
context_allow:
- tests/test_u239b_rsi_counterexamples.py
acceptance: C:\Python314\python.exe -m unittest tests.test_u239_rsi_evaluator tests.test_u239b_rsi_counterexamples tests.test_u229_independent_invocation tests.test_u229_claude_journal_worker tests.test_u229_olla_embed_journal
forbidden: editing or deleting tests; edits outside allow; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 300 seconds
judge: claude
timeout_s: 300
remote_budget_tokens: 0
```

## Exact edit in `v7_harness/invocation.py`: replace `evaluate_roi_metrics`, verbatim

```python
def evaluate_roi_metrics(db=None, *, window=100):
    rows = _review_rows(db, window)
    total = len(rows)
    succeeded = sum(row["outcome"] == "SUCCEEDED" for row in rows)
    first_by_work = {}
    local_calls = paid_calls = unknown_route_calls = 0
    for row in rows:
        first_by_work.setdefault(row["work_id"], row)
        try:
            meta = json.loads(row.get("metadata") or "{}")
        except ValueError:
            meta = {}
        provider = meta.get("provider") if isinstance(meta, dict) else None
        model = str(row.get("model") or "")
        if provider == "ollama" or model in (LOCAL_MODEL, "qwen2.5:1.5b", "nomic-embed-text"):
            local_calls += 1
        elif provider == "claude_cli_unverified" or model == HAIKU or model.startswith("claude-"):
            paid_calls += 1
        else:
            unknown_route_calls += 1
    first_succeeded = sum(r["outcome"] == "SUCCEEDED" for r in first_by_work.values())
    return {
        "schema": "uaos-rsi-roi-v1",
        "window_attempts": total,
        "succeeded_attempts": succeeded,
        "first_pass_yield": (first_succeeded / len(first_by_work)) if first_by_work else 0.0,
        "local_calls": local_calls,
        "paid_calls": paid_calls,
        "unknown_route_calls": unknown_route_calls,
        "local_offload_ratio": (local_calls / total) if total else 0.0,
        "quota_saving": "UNMEASURED",
        "auto_adopt": False,
    }
```
