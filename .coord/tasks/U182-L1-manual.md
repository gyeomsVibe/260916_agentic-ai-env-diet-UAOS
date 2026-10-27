```contract
work_id: U182-L1
worker: local
goal: U182 - a project folder nested in a larger git repository keeps its own .coord as the coord root
inputs:
- v7_harness/coord/next_card.py sha256=1ab2687c7d4be00f25793220c93a47468b998f70a2006324709b7484dfc9cdc8
allow:
- v7_harness/coord/next_card.py
context_allow:
- v7_harness/coord/next_card.py
acceptance: python -m unittest tests.test_u182_nested_project_root tests.test_u166_merge_route_no_wait tests.test_u180_projects_registry tests.test_u146_nonstop_chain
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: antigravity
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Card U182. One small edit in `v7_harness/coord/next_card.py`, function `coord_root`. Change nothing else.

At the very start of `coord_root`, before the `try:` that runs git, add:

```python
    project = Path(project)
    # U182: a worktree's top folder always holds `.git`; a folder that has its own .coord but no `.git` is a project
    # nested inside a larger repository (Lotto receipt 2026-10-11) and keeps its own schedule and mailbox.
    if (project / ".coord").is_dir() and not (project / ".git").exists():
        return project
```

Use one ===EDIT block whose SEARCH is the docstring line of `coord_root` followed by the `    try:` line, and whose
REPLACE is those same two lines with the four new lines between them.

## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
