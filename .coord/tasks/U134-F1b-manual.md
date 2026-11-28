```contract
work_id: U134-F1b
worker: apply
apply_after: U134-F1
goal: fail-closed validation of session_meta cwd before Path.resolve (U134-F1b)
inputs:
- tests/test_u134_thread_fallback.py sha256=a272923674c458ba9e06fc364f3c69b0276c5415006d931ddab2f005e597d944
- tests/test_u134_judge_counterexamples.py sha256=019608228ca494af4c798d735c066bf6a182401ef5b338d8f7f3dbf265d52ad3
- tests/test_u134_f1b_cwd.py sha256=496a3bbdeceaac1aeb02af5652cbfaf98e0b990825ad6100d29360e593dc5930
allow:
- v7_harness/coord/deliver.py
acceptance: python -m unittest tests.test_u134_thread_fallback tests.test_u134_judge_counterexamples tests.test_u134_f1b_cwd
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 900
remote_budget_tokens: 0
```

## Work Order: U134-F1b Fail-closed CWD Validation in Rollout Meta

Receipt: Codex relay_d60c4681 REJECT of bundle 0730b80e.
Order: Codex relay_9fb9eb51, relay_d3e9bcca, relay_d57c71ff.
Deputy Contract: Claude relay_2fd95211.
Base: stage .coord/pilot/stage/U134-F1 deliver.py 12a3d75d.

===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
    cwd_str = payload.get("cwd")
    cwd = Path(cwd_str).resolve() if cwd_str else None
    return chosen_id, cwd, "OK"
=======
    if "cwd" in payload:
        cwd_val = payload["cwd"]
        if not isinstance(cwd_val, str) or not cwd_val.strip():
            return "", None, "THREAD_UNVERIFIED"
        cwd = Path(cwd_val).resolve()
    else:
        cwd = None
    return chosen_id, cwd, "OK"
>>>>>>> REPLACE
