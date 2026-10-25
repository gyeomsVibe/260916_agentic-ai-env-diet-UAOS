# U239-L1: Always-On RSI Value Evaluator (`evaluate_roi_metrics`)

```contract
work_id: U239-L1
worker: local
goal: Add evaluate_roi_metrics in v7_harness/invocation.py to compute first_pass_yield and local_offload_ratio from the invocation journal
inputs:
- v7_harness/invocation.py sha256=69d6e958bda80d518f59146d2761e40f2eebdc74514a53d55a820a8e39cdd8c5
- tests/test_u239_rsi_evaluator.py sha256=12a3c4a313fef9255e2c582a2a54c31f5e287697dc8adb13ee893ad3835212a3
allow:
- v7_harness/invocation.py
context_allow:
- tests/test_u239_rsi_evaluator.py
acceptance: C:\Python314\python.exe -m unittest tests.test_u239_rsi_evaluator tests.test_u229_independent_invocation tests.test_u229_claude_journal_worker tests.test_u229_olla_embed_journal
forbidden: editing or deleting tests; edits outside allow; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 300 seconds
judge: claude
timeout_s: 300
remote_budget_tokens: 0
```

## Exact edit in `v7_harness/invocation.py`: keep `_proposal` and add `evaluate_roi_metrics`, verbatim

```python
def _proposal(rows):
    fingerprint = hashlib.sha256(json.dumps(rows, sort_keys=True).encode("utf-8")).hexdigest()
    return {"schema": "uaos-invocation-review-v1", "fingerprint": fingerprint,
            "attempts": len(rows), "outcomes": dict(Counter(row["outcome"] for row in rows)),
            "models": dict(Counter(row["model"] for row in rows)),
            "errors": dict(Counter(row["error_class"] for row in rows if row["error_class"])),
            "token_unknown_attempts": sum(row["input_tokens"] is None or row["output_tokens"] is None for row in rows),
            "acceptance": "UNVERIFIED", "quota_saving": "UNMEASURED", "automatic_adoption": False,
            "auto_adopt": False,
            "next_action": "REVIEW_FIXED_ACCEPTANCE_AND_CAUSES_BEFORE_ROUTING_OR_POLICY_CHANGE"}


def evaluate_roi_metrics(db=None, *, window=100):
    rows = _review_rows(db, window)
    total = len(rows)
    succeeded = sum(row["outcome"] == "SUCCEEDED" for row in rows)
    local_calls = sum(row["model"] == LOCAL_MODEL for row in rows)
    paid_calls = total - local_calls
    return {
        "schema": "uaos-rsi-roi-v1",
        "window_attempts": total,
        "succeeded_attempts": succeeded,
        "first_pass_yield": (succeeded / total) if total else 0.0,
        "local_calls": local_calls,
        "paid_calls": paid_calls,
        "local_offload_ratio": (local_calls / total) if total else 0.0,
        "quota_saving": "UNMEASURED",
        "auto_adopt": False,
    }
```
