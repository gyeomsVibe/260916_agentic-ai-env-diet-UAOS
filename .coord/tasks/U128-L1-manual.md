```contract
work_id: U128-L1
worker: local
goal: rsi._cause names Ollama format failures NO_FILE_BLOCK and DICTATION_MISMATCH with the apply remedy instead of PROVIDER_ERROR (U128)
inputs:
- .work/u128_spec.md sha256=f104d15c80cccc809838ec69ed92f2ed30a2104c258065d4f7cfefbe1dc96393
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

# Work order: name the two Ollama format failures in the RSI cause table (U128)

- Target file: `v7_harness/rsi.py`
- Anchors: `REMEDIES`, `"NO_CHANGES"`, `GENERIC_CLASSES`, `_cause`

Make three ===EDIT blocks. Each SEARCH must be copied exactly from the file. Change nothing else.

Block 1. In the `REMEDIES` dict, right after the `"NO_CHANGES": (...)` entry line, add these four lines (4-space indent like the other entries):

    # U128: Ollama answered but dropped the ===EDIT frame (U125-L2, U125-L2R) or rewrote the dictated code (U126-L);
    # apply_after fixed all three, and copying known code through Ollama gains nothing over apply (U126 audit).
    "NO_FILE_BLOCK": ("manual_template", "Known code goes to worker: apply with apply_after this run; give Ollama a spec, not a copy"),
    "DICTATION_MISMATCH": ("manual_template", "Dictated code goes to worker: apply with apply_after this run; Ollama only rewrites it"),

Block 2. Right after the line `GENERIC_CLASSES = ("PROVIDER_ERROR", "EXECUTION_ERROR")`, add:

    # U128: worker phrases that name a cause without its key (the U125-L2 and U125-L2R ledger rows say only this).
    DETAIL_CAUSES = {"model returned no file block": "NO_FILE_BLOCK"}

Block 3. In `_cause`, after each of the two existing loops `for known in REMEDIES:` (the one inside
`if error_class in GENERIC_CLASSES:` and the one after `return str(error_class)`), add a second loop at the same
indent as that `for`:

    for phrase, cause in DETAIL_CAUSES.items():
        if phrase in detail:
            return cause

Use one SEARCH that covers from `        if error_class in GENERIC_CLASSES:` down to the `return known` of the second loop,
so both new loops land in one block. The first new loop goes before `return str(error_class)`; the second goes
before `return str(row.get("rework_class") ...`.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
