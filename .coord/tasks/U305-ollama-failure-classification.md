# U305 — Ollama worker failure classification (stop journaling output failures as PROVIDER_ERROR)

- Author: antigravity (user desk 2026-11-04). Judge: claude (author != judge). Lane: RECOVERY_OPS.
- Receipt (real-use failure, seen 4x on 2026-11-04 in `.coord/usage/runs.jsonl`):
  - U304-A-L4 `worker: ollama unreachable: timed out` -> PROVIDER_ERROR (correct: environment)
  - U304-A-L2 `model returned no file block` -> PROVIDER_ERROR (wrong: worker output, NO_FILE_BLOCK)
  - U304B-L3C `SPLICE_UNSUPPORTED:If` -> PROVIDER_ERROR (wrong: SPLICE_UNSUPPORTED)
  - U304-A-L2R `DICTATION_MISMATCH:...` -> PROVIDER_ERROR (wrong: DICTATION_MISMATCH)
- Effect: `rsi report` window 57 says "recurring PROVIDER_ERROR -> check Ollama service" (rsi.py:88) while the service was up;
  the real remedy per global rule is "re-cut PROMPT_TOO_LARGE/DICTATION_MISMATCH/NO_FILE_BLOCK". RSI evidence is mislabelled.

## Decision
Map the worker's own failure token to its class when the ollama worker reports one of
`NO_FILE_BLOCK`, `DICTATION_MISMATCH`, `SPLICE_UNSUPPORTED`, `SPLICE_SYNTAX`, `PROMPT_TOO_LARGE`; keep PROVIDER_ERROR only for
unreachable / timeout / HTTP failures. Evaluators (rsi.py thresholds, tests of other cards) are not changed.

## Fixed acceptance
`python -m pytest -q tests/test_u305_ollama_failure_class.py` exit 0, plus existing tests that import the touched module pass.
Test cases: each of the 4 receipt details above maps to the expected class; unknown text stays PROVIDER_ERROR.

## Non-goals
No change to rsi thresholds, no Ollama queue/serialization change (separate card if timeouts recur).
