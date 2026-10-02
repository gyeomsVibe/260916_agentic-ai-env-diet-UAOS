```contract
work_id: U128-L3
worker: apply
apply_after: U128-L1
goal: rsi._cause names Ollama format failures NO_FILE_BLOCK and DICTATION_MISMATCH with the apply remedy instead of PROVIDER_ERROR (U128)
inputs:
- .work/u128_apply.md sha256=70d1bd3f2a922433e5505aa077355acd7e12f14384ef956e1ed1d68ced9294ee
allow:
- v7_harness/rsi.py
acceptance: python -m unittest tests.test_u128_ollama_format_cause tests.test_u81_apply_cause tests.test_u36_evidence_gated_rsi tests.test_u125_rsi_review_wakes_conductor tests.test_u73_session_usage tests.test_u74_closure
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

# Work order: U128 exact apply (after the failed Ollama runs U128-L1 and U128-L2): Ollama format failures get their own RSI cause

- Target file: `v7_harness/rsi.py`

===EDIT: v7_harness/rsi.py===
<<<<<<< SEARCH
    "NO_CHANGES": ("manual_template", "State one concrete verb and the exact file; read-only tasks need --allow-no-changes"),
=======
    "NO_CHANGES": ("manual_template", "State one concrete verb and the exact file; read-only tasks need --allow-no-changes"),
    # U128: Ollama answered but dropped the ===EDIT frame (U125-L2, U125-L2R) or rewrote the dictated code (U126-L);
    # apply_after fixed all three, and copying known code through Ollama gains nothing over apply (U126 audit).
    "NO_FILE_BLOCK": ("manual_template", "Known code goes to worker: apply with apply_after this run; give Ollama a spec, not a copy"),
    "DICTATION_MISMATCH": ("manual_template", "Dictated code goes to worker: apply with apply_after this run; Ollama only rewrites it"),
>>>>>>> REPLACE

===EDIT: v7_harness/rsi.py===
<<<<<<< SEARCH
GENERIC_CLASSES = ("PROVIDER_ERROR", "EXECUTION_ERROR")
=======
GENERIC_CLASSES = ("PROVIDER_ERROR", "EXECUTION_ERROR")
# U128: worker phrases that name a cause without its key (the U125-L2 and U125-L2R ledger rows say only this).
DETAIL_CAUSES = {"model returned no file block": "NO_FILE_BLOCK"}
>>>>>>> REPLACE

===EDIT: v7_harness/rsi.py===
<<<<<<< SEARCH
        if error_class in GENERIC_CLASSES:
            for known in REMEDIES:
                if known not in GENERIC_CLASSES and known in detail:
                    return known
        return str(error_class)
    for known in REMEDIES:
        if known in detail:
            return known
=======
        if error_class in GENERIC_CLASSES:
            for known in REMEDIES:
                if known not in GENERIC_CLASSES and known in detail:
                    return known
            for phrase, cause in DETAIL_CAUSES.items():
                if phrase in detail:
                    return cause
        return str(error_class)
    for known in REMEDIES:
        if known in detail:
            return known
    for phrase, cause in DETAIL_CAUSES.items():
        if phrase in detail:
            return cause
>>>>>>> REPLACE


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
