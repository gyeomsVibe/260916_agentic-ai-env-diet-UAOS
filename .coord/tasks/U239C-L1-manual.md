# U239C-L1 Contract Manual — RSI Value Evaluator Grain `(project, work_id)` and True First-Attempt History

```contract
work_id: U239C-L1
worker: local
goal: Replace evaluate_roi_metrics in v7_harness/invocation.py so first_pass_yield keys work items by (project, work_id) and evaluates first-ever attempt outcome from full attempts history
inputs:
  - v7_harness/invocation.py sha256=dc2cad1ca92356c55965673592e3d0369c4614dfab489e4b8286d5596d282283
  - tests/test_u239_rsi_evaluator.py sha256=12a3c4a313fef9255e2c582a2a54c31f5e287697dc8adb13ee893ad3835212a3
  - tests/test_u239b_rsi_counterexamples.py sha256=64a41d6b4379b327a48061b2c52c31c9bcf9d838234e1151c391f8da60cc6c58
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

## Task Specification (Replace `def evaluate_roi_metrics`)

Replace `def evaluate_roi_metrics(db=None, *, window=100):` in `v7_harness/invocation.py` with the following implementation:

```python
def evaluate_roi_metrics(db=None, *, window=100):
    rows = _review_rows(db, window)
    total = len(rows)
    succeeded = sum(row["outcome"] == "SUCCEEDED" for row in rows)
    with _connect(db) as con:
        hist = con.execute("SELECT project, work_id, outcome FROM attempts ORDER BY started_at ASC, id ASC").fetchall()
    first_ever = {}
    for r in hist:
        first_ever.setdefault((r["project"], r["work_id"]), r["outcome"])
    work_keys = {(row["project"], row["work_id"]) for row in rows}
    local_calls = paid_calls = unknown_route_calls = 0
    for row in rows:
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
    first_succeeded = sum(first_ever.get(k) == "SUCCEEDED" for k in work_keys)
    return {
        "schema": "uaos-rsi-roi-v1",
        "window_attempts": total,
        "succeeded_attempts": succeeded,
        "first_pass_yield": (first_succeeded / len(work_keys)) if work_keys else 0.0,
        "local_calls": local_calls,
        "paid_calls": paid_calls,
        "unknown_route_calls": unknown_route_calls,
        "local_offload_ratio": (local_calls / total) if total else 0.0,
        "quota_saving": "UNMEASURED",
        "auto_adopt": False,
    }
```
