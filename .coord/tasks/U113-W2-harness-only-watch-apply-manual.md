```contract
work_id: U113-W2
worker: apply
goal: Local and apply workers watch only their stage, so other apps rewriting their own config no longer block a run
inputs:
- v7_harness/cli.py sha256=30d8fb95b65fab8e447d328d77038e19a7442a6dbcd59393e7dd2f53ce110634
- tests/test_u113_desk_truth.py sha256=7a1fe3a2678849376adbd5d6cba49bf6144445346b5a313f859558ed74eac508
allow:
- v7_harness/cli.py
acceptance: python -m unittest tests.test_u113_desk_truth.HarnessOnlyWorkersWatchTheStage tests.test_u46_followup_fixes
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the blocks below exactly.

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
def mandatory_watch_roots(work_dir: Path, source_dir: Path) -> list[Path]:
=======
# U113: these workers never touch the file system; the harness writes their stage. Watching home and temp for them
# only caught other apps rewriting their own config (Codex config.toml in U113-D a001, Claude settings in U106-A2-agy).
HARNESS_ONLY_WORKERS = ("local", "apply")


def mandatory_watch_roots(work_dir: Path, source_dir: Path, worker: str = "agy") -> list[Path]:
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
    work = work_dir.resolve()
    return list(dict.fromkeys([
=======
    work = work_dir.resolve()
    if worker in HARNESS_ONLY_WORKERS:
        return [(work_dir / "stage").resolve()]
    return list(dict.fromkeys([
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
    mandatory_roots = mandatory_watch_roots(work_dir, source_dir)
=======
    mandatory_roots = mandatory_watch_roots(work_dir, source_dir, chosen)
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
