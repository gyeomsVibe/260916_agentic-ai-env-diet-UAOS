```contract
work_id: U119-R
worker: apply
goal: agy review: refuse an empty diff before paying; inline a fitting request as one no-tool turn
inputs:
- v7_harness/review.py sha256=21a2e7fb9d1178f165d585e9dca5580dbc439724bf1eef344c9e717091668bbd
allow:
- v7_harness/review.py
acceptance: python -m unittest tests.test_u119_agy_review_one_turn tests.test_u46_agy_review
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the blocks below exactly.

===EDIT: v7_harness/review.py===
<<<<<<< SEARCH
    prompt = review_prompt(task_id, manual_text, bundle_diff(Path(source), staging, changed), runs / "review.diff")
=======
    diff = bundle_diff(Path(source), staging, changed)
    if not diff.strip():
        # U119-R: after --approve the source equals the staged copy; an empty-diff agy review searched files (395,104).
        raise ReviewRefused("EMPTY_DIFF: the source already equals the staged copy; review before --approve")
    prompt = review_prompt(task_id, manual_text, diff, runs / "review.diff")
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/review.py===
<<<<<<< SEARCH
             f"Do not edit any file. Reply with exactly one JSON object: {SCHEMA_HINT}")
=======
             f"Do not edit any file. Reply with exactly one JSON object: {SCHEMA_HINT}")
    if len(prompt) < 24_000 and "The diff below is PARTIAL" not in prompt:
        # U119-R: inline = one turn (28,008 tokens measured vs a 25,012 floor); each file-read turn re-reads the floor.
        # 24,000 chars leaves room under the 32,767-character Windows command line for the other arguments.
        short = prompt + "\n\nAnswer in this single reply. Do not call any tool: everything you need is above."
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
