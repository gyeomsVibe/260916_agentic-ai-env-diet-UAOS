```contract
work_id: U106-A1
worker: cascade
goal: Code work goes to Ollama first; a paid worker only after a failed local run of the same card (U106).
inputs:
- tests/test_u106_local_first.py sha256=45f0de6ee6f525df447ada3c1f4530d7578a858e694e6232f986b22d44eb0462
- v7_harness/delegation.py sha256=3cb1537e9a7149f2f836b61abee10a1506e8a2ab87315d7e24e9e8a941e03834
- v7_harness/manual.py sha256=603ca443ab6942ed06a8d22cad0519ea6df360cb23655f216e7118dd1ffdd390
allow:
- v7_harness/delegation.py
- v7_harness/manual.py
acceptance: python -m unittest tests.test_u106_local_first.LocalFirstLintTests tests.test_u98d_delegate_first
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 1800
remote_budget_tokens: 800000
```

## Instructions for the worker

Card U106-A1. Goal: a paid worker (agy, claude) may not take code work until the free local model (Ollama) has tried and failed. The acceptance test `tests/test_u106_local_first.py` (class LocalFirstLintTests) is fixed; do not edit it.

Change exactly two files.

1. `v7_harness/delegation.py` - append at the end of the file:
   - A constant `LOCAL_WORKERS = frozenset({"ollama", "local", "cascade"})` with the comment `# U106: the free local routes; a paid worker takes code only after one of them failed.`
   - A constant `PAID_WORKERS = frozenset({"agy", "claude"})`.
   - A function `local_first_errors(contract: dict[str, Any], project: Path) -> list[str]` that must:
     1. return `[]` when `contract.get("worker")` is not in `PAID_WORKERS`;
     2. read `allow = contract.get("allow") or []` (a list of path strings); normalize each with `_normalize`; keep the paths that end with one of `CODE_SUFFIXES` and do not start with `tests/`; if none are left, return `[]` (docs, notes and research are exempt);
     3. read `after = str(contract.get("paid_after") or "").strip()`;
     4. return `[]` when `after` is set and `_failed_local(project, after, _card(contract.get("work_id")))` is true;
     5. otherwise return exactly one string: `"LOCAL_FIRST: code work goes to worker: cascade (Ollama first, escalates to the paid worker on a failed acceptance); a paid worker needs paid_after: <work_id of a failed Ollama/local/cascade run of this card>"`.
   - A function `_failed_local(project: Path, work_id: str, card: str) -> bool`, a copy of `_failed_delegate` with one difference: the row's `worker` must be in `LOCAL_WORKERS` instead of `DELEGATE_WORKERS`.

2. `v7_harness/manual.py`:
   - Replace the two lines
     `    from v7_harness.delegation import delegate_first_errors`
     `    report.errors.extend(delegate_first_errors(text, contract, project))`
     with
     `    from v7_harness.delegation import delegate_first_errors, local_first_errors`
     `    report.errors.extend(delegate_first_errors(text, contract, project))`
     `    report.errors.extend(local_first_errors(contract, project))  # U106: Ollama first for code work`

Check: `python -m unittest tests.test_u106_local_first.LocalFirstLintTests tests.test_u98d_delegate_first` must pass.
Forbidden: editing tests; any other file; network; git.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
