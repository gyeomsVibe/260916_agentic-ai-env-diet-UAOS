```contract
work_id: U182-A1
worker: apply
apply_after: U182-L1
goal: U182 - a project folder nested in a larger git repository keeps its own .coord as the coord root
inputs:
- v7_harness/coord/next_card.py sha256=1ab2687c7d4be00f25793220c93a47468b998f70a2006324709b7484dfc9cdc8
allow:
- v7_harness/coord/next_card.py
context_allow:
- v7_harness/coord/next_card.py
acceptance: python -m unittest tests.test_u182_nested_project_root tests.test_u166_merge_route_no_wait tests.test_u180_projects_registry tests.test_u180c_schedule_boundary tests.test_u146a_next_card tests.test_u146a_r2_claim_lock tests.test_u146a_r_ownership
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: antigravity
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Card U182. The Ollama run U182-L1 failed (SPLICE_SYNTAX). Dictation: copy the edit block below exactly.

Receipt (2026-10-11): the Lotto project is a folder inside another git repository. `coord_root` returned that
repository's top (the git common dir's parent), which holds no .coord, so `coord next` answered DONE "no schedule" to
all three tools although the project's own plan had a READY step. A worktree's top folder always holds `.git` (a file
or a folder), so a folder with its own .coord and no `.git` is a nested project and keeps its own schedule.

===EDIT: v7_harness/coord/next_card.py===
<<<<<<< SEARCH
    """R5: all worktrees agree on one schedule, kept in the main checkout (the git common dir's parent)."""
    try:
=======
    """R5: all worktrees agree on one schedule, kept in the main checkout (the git common dir's parent)."""
    project = Path(project)
    # U182: a worktree's top folder always holds `.git`; a folder that has its own .coord but no `.git` is a project
    # nested inside a larger repository (Lotto receipt 2026-10-11) and keeps its own schedule and mailbox.
    if (project / ".coord").is_dir() and not (project / ".git").exists():
        return project
    try:
>>>>>>> REPLACE

## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
