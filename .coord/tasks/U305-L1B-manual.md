```contract
work_id: U305-L1B
worker: local
goal: In v7_harness/adapters/agy.py, update `_classify_provider_error` so Ollama output failures return their specific class instead of PROVIDER_ERROR.
inputs:
- v7_harness/adapters/agy.py sha256=744ff0db0b79d1aadea3935a41c498cb4b904a48549a2c64cbcc958c0a629a0d
allow:
- v7_harness/adapters/agy.py
acceptance: C:\Python314\python.exe -m unittest tests/test_u305_ollama_failure_class.py -k test_classify_provider_error_maps_ollama_output_failures
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

In `v7_harness/adapters/agy.py`, edit function `_classify_provider_error(text: str) -> str`:
Right after the `TRANSIENT_CAPACITY` check (`if any(token in lowered for token in ("503", "no capacity", "unavailable")): return "TRANSIENT_CAPACITY"`) and before `return "PROVIDER_ERROR"`:
1. If `"model returned no file block"` is in `lowered`, return `"NO_FILE_BLOCK"`.
2. Loop `for prefix in ("DICTATION_MISMATCH", "SPLICE_UNSUPPORTED", "SPLICE_SYNTAX", "PROMPT_TOO_LARGE"):` and if `prefix.casefold() in lowered:`, return `prefix`.
Keep all existing checks in `_classify_provider_error` unchanged.

## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
