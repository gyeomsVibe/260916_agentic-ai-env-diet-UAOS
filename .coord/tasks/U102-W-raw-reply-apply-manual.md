```contract
work_id: U102-W
worker: apply
goal: Keep the Ollama worker's raw reply in the run record when its blocks are rejected.
inputs:
- tests/test_u102w_raw_reply.py sha256=3b3fb363c3ca58b7c6d5944bdc0243f828e52e314e6a473b851500f921d92bca
allow:
- v7_harness/adapters/ollama_worker.py
context_allow:
- tests/test_u102w_raw_reply.py
acceptance: python -m unittest tests.test_u102w_raw_reply tests.test_u16_local_worker tests.test_u17_lane_worker tests.test_u21_calculator tests.test_u22_worker_limits tests.test_u34_precision_harness tests.test_u38_cost_gate_and_claude_worker tests.test_u46_followup_fixes tests.test_u47_n1_newline_preserved tests.test_u47_n1d_mixed_endings tests.test_u47_n2_crlf_reply tests.test_u47_olla_record tests.test_u50_context_admission tests.test_u68l_worker_envelopes_ascii 
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the blocks below exactly (judge-dictated, 4 lines, U98-D apply limit is 20).

A failed local run kept `response: ""`, so the judge could not see why U101-L1 and U101-L2 failed. The raw reply now stays in the run record's `response` whenever the model answered but its blocks were rejected.

===EDIT: v7_harness/adapters/ollama_worker.py===
<<<<<<< SEARCH
    if "===FILE:" not in text and "===EDIT:" not in text:
        return envelope("ERROR", "", usage, "model returned no file block")
    try:
        written = _apply(text, workspace, task=args.prompt)
    except ValueError as exc:
        return envelope("ERROR", "", usage, str(exc))
    if not written:
        return envelope("ERROR", "", usage, "no file written")
=======
    # U102-W: keep the raw reply on every rejection; an empty record hid the U101-L2 cause (constants above __future__).
    if "===FILE:" not in text and "===EDIT:" not in text:
        return envelope("ERROR", text, usage, "model returned no file block")
    try:
        written = _apply(text, workspace, task=args.prompt)
    except ValueError as exc:
        return envelope("ERROR", text, usage, str(exc))
    if not written:
        return envelope("ERROR", text, usage, "no file written")
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
