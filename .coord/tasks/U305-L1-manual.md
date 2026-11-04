```contract
work_id: U305-L1
worker: local
goal: In v7_harness/adapters/agy.py, make _classify_provider_error return specific Ollama output failure classes instead of PROVIDER_ERROR.
inputs:
- v7_harness/adapters/agy.py sha256=744ff0db0b79d1aadea3935a41c498cb4b904a48549a2c64cbcc958c0a629a0d
allow:
- v7_harness/adapters/agy.py
acceptance: C:\Python314\python.exe -m unittest tests/test_u305_ollama_failure_class.py -k "classify or parse"
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the block below exactly, in order.

===EDIT: v7_harness/adapters/agy.py===
<<<<<<< SEARCH
    if any(token in lowered for token in ("503", "no capacity", "unavailable")):
        return "TRANSIENT_CAPACITY"
    return "PROVIDER_ERROR"
=======
    if any(token in lowered for token in ("503", "no capacity", "unavailable")):
        return "TRANSIENT_CAPACITY"
    if "model returned no file block" in lowered:
        return "NO_FILE_BLOCK"
    for prefix in ("DICTATION_MISMATCH", "SPLICE_UNSUPPORTED", "SPLICE_SYNTAX", "PROMPT_TOO_LARGE"):
        if prefix.casefold() in lowered:
            return prefix
    return "PROVIDER_ERROR"
>>>>>>> REPLACE
===END===

## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
