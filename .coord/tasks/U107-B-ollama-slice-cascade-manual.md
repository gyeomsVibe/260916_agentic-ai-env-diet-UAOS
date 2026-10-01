```contract
work_id: U107-B
worker: cascade
goal: When the whole-file prompt is over the local window, send the local model exact windows around the identifiers the task names (spec below) instead of failing with PROMPT_TOO_LARGE.
inputs:
- v7_harness/adapters/ollama_worker.py sha256=4b4d2b167f3b6c205ba44db51fec7180d11b198f2c7e719c9f2c165b75135bcf
- tests/test_u107_ollama_slice.py sha256=648810d027b1078e63dd9309f3f043027d8b7e3db96b014b9fff0943abdfa88a
allow:
- v7_harness/adapters/ollama_worker.py
acceptance: python -m unittest tests.test_u107_ollama_slice tests.test_u22_worker_limits tests.test_u16_local_worker tests.test_u50_context_admission tests.test_u102w_raw_reply tests.test_u47_olla_record
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 1800
remote_budget_tokens: 800000
```

## Instructions for the worker

## Spec (edit only `v7_harness/adapters/ollama_worker.py`)

Today `main()` pastes every admitted file whole into the prompt and returns `PROMPT_TOO_LARGE` when
`len(prompt.encode("utf-8")) // 3 > NUM_CTX - NUM_PREDICT`. Make it send windows of the big files instead.

1. Add module constants with a one-line reason comment each:
   - `SLICE_WINDOWS = (25, 10, 3)`  # lines kept on each side of an anchor; try wider first, shrink until it fits
   - `ANCHOR_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")`
2. Add `def task_anchors(task: str) -> list[str]`: for every backtick span in the task (``re.findall(r"`([^`\n]+)`", task)``)
   that is not a path (contains no "/" and does not end in .py/.md/.txt/.json), collect every `ANCHOR_RE` match;
   return them de-duplicated in first-seen order.
3. Add `def slice_text(name: str, text: str, anchors: list[str], radius: int) -> str | None`:
   - lines = text.splitlines(keepends=True); hit lines = indexes whose line contains any anchor as a whole word
     (`re.search(rf"\b{re.escape(a)}\b", line)`). No hit -> return None.
   - Keep the union of [i - radius, i + radius] clipped to the file, merge overlapping/adjacent ranges.
   - Render: header `\n===CURRENT FILE: {name} (partial: {len(lines)} lines, only the lines below are shown; the rest is omitted)===\n`,
     then for each kept range the exact original lines joined, and between ranges / before the first / after the
     last range, when lines are skipped, one line `... lines {a}-{b} omitted ...\n` (1-based, inclusive).
4. In `main()`, after `named = admitted_context(...)[:4]`, build `whole = "".join(f"\n===CURRENT FILE: {name}===\n{text}\n" ...)`
   exactly as today. Compute the prompt with `whole`. Only if its estimate is over `limit`:
   - anchors = task_anchors(args.prompt); for radius in SLICE_WINDOWS: build context where each file whose own whole
     block is over 1/4 of `limit` tokens (bytes // 3) is replaced by `slice_text(...)` (keep the whole block when
     slice_text returns None), force `rules = EDIT_RULES`, rebuild the prompt, recompute the estimate; stop at the
     first radius that fits. Log `_log("context_sliced", work_id=..., radius=radius, before=<whole estimate>, after=<estimate>)` when it fits.
   - If no radius fits (or there are no anchors), fall through to the existing PROMPT_TOO_LARGE return unchanged.
   Move the `limit` computation above this logic; keep the rest of `main()` unchanged. Never change `_apply`.
5. Small prompts must stay byte-identical to today (no slicing, same rules choice).


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
