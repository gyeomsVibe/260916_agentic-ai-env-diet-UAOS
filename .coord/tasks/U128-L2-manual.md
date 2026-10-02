```contract
work_id: U128-L2
worker: local
goal: rsi._cause names Ollama format failures NO_FILE_BLOCK and DICTATION_MISMATCH with the apply remedy instead of PROVIDER_ERROR (U128, whole definitions)
inputs:
- .work/u128_spec2.md sha256=692f22b0d4ea050579a1d543c84e8b52e8aa025bba4031e758580fdc9d1db3f3
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

# Work order: name the two Ollama format failures in the RSI cause table (U128, whole-definition form)

- Target file: `v7_harness/rsi.py`
- Anchors: `REMEDIES`, `_cause`

Reply with the header line `===EDIT: v7_harness/rsi.py===` and ONE ```python fence. The fence holds exactly three
complete top-level definitions and nothing else (no loose statements, no `for` outside a function):

1. The whole `REMEDIES: dict[str, tuple[str, str]] = { ... }` assignment, every existing entry kept word for word, with
   these two entries added at the end of the dict:

       "NO_FILE_BLOCK": ("manual_template", "Known code goes to worker: apply with apply_after this run; give Ollama a spec, not a copy"),
       "DICTATION_MISMATCH": ("manual_template", "Dictated code goes to worker: apply with apply_after this run; Ollama only rewrites it"),

2. A new constant, with its comment line above it:

       # U128: worker phrases that name a cause without its key (the U125-L2 and U125-L2R ledger rows say only this).
       DETAIL_CAUSES = {"model returned no file block": "NO_FILE_BLOCK"}

3. The whole function `def _cause(row: dict[str, Any]) -> str | None:`, kept as it is today except two additions.
   Inside `if error_class in GENERIC_CLASSES:`, after its `for known in REMEDIES:` loop, add:

           for phrase, cause in DETAIL_CAUSES.items():
               if phrase in detail:
                   return cause

   After the second `for known in REMEDIES:` loop (the one after `return str(error_class)`), add at 4-space indent:

       for phrase, cause in DETAIL_CAUSES.items():
           if phrase in detail:
               return cause

   Keep its U81 comment lines and its final `return str(row.get("rework_class") or row.get("outcome") or "UNKNOWN")`.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
