```contract
work_id: U119-R3
worker: apply
goal: agy review: refuse an empty diff before paying; inline a fitting request as one no-tool turn in an empty box
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
    argv = build_agy_command(AgyRequest(task_id=task_id, title="review", prompt=short, workspace=runs,
                                        isolation_mode="staging", print_timeout_s=timeout_s))
    done = runner(argv, cwd=str(runs), env={**os.environ, "UAOS_WORKER": "1"}, capture_output=True,
=======
             f"Do not edit any file. Reply with exactly one JSON object: {SCHEMA_HINT}")
    workspace = runs
    partial = prompt.startswith(f"[{task_id}] Review this change against its contract. The diff below is PARTIAL")
    if len(prompt) < 24_000 and not partial:
        # U119-R2: inline in an empty box = one turn (28,008 tokens measured vs a 25,012 floor). In the run folder agy
        # ignored "no tool" (view_file 55, run_command 10: 73,063). 24,000 chars fit the 32,767-char Windows line.
        # U119-R3: only the prompt's leading sentence marks a partial diff; a diff quoting the phrase fell back (55,062).
        workspace = runs / "agy_box"
        workspace.mkdir(exist_ok=True)
        short = prompt + ("\n\nAnswer in this single reply. Do not call any tool, read files or run commands: the judge "
                          "already ran the acceptance command and everything you need is above.")
    argv = build_agy_command(AgyRequest(task_id=task_id, title="review", prompt=short, workspace=workspace,
                                        isolation_mode="staging", print_timeout_s=timeout_s))
    done = runner(argv, cwd=str(workspace), env={**os.environ, "UAOS_WORKER": "1"}, capture_output=True,
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
