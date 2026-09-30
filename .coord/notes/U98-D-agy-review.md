# U98-D Independent Adversarial Review: Delegation-First Gate

VERDICT: FAIL

## Findings

| Severity | Location | Attack | Expected vs Observed |
| P1 | v7_harness/cli.py:307 | CLI execution without --manual (`pilot run --worker apply --prompt ...`) | Expected: `pilot run` enforces `delegate_first_errors` or requires `--manual` for `worker: apply`. Observed: `cli.py` only mandates `--manual` for `REMOTE_WORKERS` (`agy`, `claude`). Invoking `pilot run --worker apply` with `--prompt` or `--prompt-file` skips `lint()` entirely, allowing arbitrary code dictation without any delegate attempt. |
| P1 | v7_harness/delegation.py:18 | Case sensitivity in file extension (`.PY`, `.Py`) | Expected: Counter checks `path.lower().endswith(".py")`. Observed: `path.endswith(".py")` is case-sensitive. On Windows (case-insensitive filesystem), targeting `sample.PY` bypasses `dictated_code_lines` (counts 0 lines), passes lint, and `apply_worker.py` overwrites `sample.py` with unlimited lines. |
| P1 | v7_harness/delegation.py:44 | Replay of historical or successful entries via `apply_after` | Expected: `apply_after` verifies the referenced run belongs to the current task/contract and actually failed. Observed: `_failed_delegate` checks only if `work_id` exists in `runs.jsonl` with `outcome != "PASS"`. Any historic run (e.g. `U42_R1_LOCAL_IMPL`) or even successful judge runs (`U47-O1-judge-agy` with `outcome: "APPROVE"`) can be cited repeatedly to bypass the gate indefinitely. |
| P1 | v7_harness/delegation.py:18 | Non-Python automation scripts (`.ps1`, `.sh`, `.bat`, `.pyw`, `.js`) | Expected: Delegation gate limits dictation of all non-test executable code. Observed: `dictated_code_lines` checks only `.endswith(".py")`. Critical executable automation code (PowerShell `.ps1`, shell `.sh`, batch `.bat`, windowed Python `.pyw`) counts as 0 lines, allowing unlimited lines to be dictated to `worker: apply`. |
| P2 | v7_harness/delegation.py:54 | Multi-manual splitting across sequential apply runs | Expected: Line limit is enforced cumulatively across tasks, cards, or time windows. Observed: `dictated_code_lines` only counts lines in the single active manual. A conductor can split a 100-line change into 5 sequential 20-line `apply` manuals without invoking any delegate. |
| P2 | v7_harness/delegation.py:19 | Semicolon packing / single-line multi-statement code | Expected: Gate limits code volume by statements, tokens, or character count. Observed: Counter only counts physical non-empty lines (`line.strip()`). 100 statements chained with semicolons on a single line count as 1 line, bypassing the 20-line threshold. |
| P2 | v7_harness/delegation.py:18 | Code placement under `tests/` prefix | Expected: Gate verifies that code under `tests/` contains actual tests rather than production logic. Observed: `not path.startswith("tests/")` unconditionally exempts any file starting with `tests/`. Non-test business logic or utility modules placed in `tests/` can be dictated without limit. |
| P2 | v7_harness/manual.py:226 | Worker redirection to `worker: claude` with dictated blocks | Expected: Gate restricts dictating full implementations into manuals regardless of worker. Observed: `delegate_first_errors` returns immediately if `worker != "apply"` (`delegation.py:52`). Full code blocks can be dictated to `worker: claude` without `DELEGATE_FIRST` errors. |
| P3 | v7_harness/delegation.py:18 | Windows backslash paths in test files (`tests\test_sample.py`) | Expected: Path normalized to forward slashes before prefix test. Observed: Windows backslashes fail `path.startswith("tests/")`, causing genuine test files to be counted as non-test code (false-positive rejection). |

## Commands Executed

| Command | Exit Code | Purpose |
|---------|-----------|---------|
| `python -c "import glob; [print(f) for f in glob.glob('v7_harness/**/*.py', recursive=True)]"` | 0 | Listed harness implementation files |
| `python -c "import re; [print(...) for f in ['v7_harness/pilot.py', 'v7_harness/cli.py'] ...]"` | 0 | Analyzed manual and lint integration points in CLI |
| `python -c "import inspect; from v7_harness.isolation.security import check_scope_confinement; print(...)"` | 0 | Inspected path confinement and canonicalization logic |
| `python -c "import inspect; from v7_harness.isolation.security import validate_safe_relative_path; print(...)"` | 0 | Inspected relative path validation rules |
| `python -c "import inspect; from v7_harness.coord.hook_context import shared_desk; print(...)"` | 0 | Inspected shared desk resolution for ledger path |
| `python -c "from v7_harness.delegation import dictated_code_lines ..."` | 0 | Tested case sensitivity, .ps1, and tests/ prefix counting |
| `python -c "from pathlib import Path; import json ... runs.jsonl ..."` | 0 | Inspected historical runs and outcomes in repo ledger |
| `python -c "from v7_harness.delegation import _failed_delegate ..."` | 0 | Verified outcome != 'PASS' flaw with APPROVE outcome |
| `python .coord/stage/U98-D-R/scratch_probe.py` | 0 | Validated uppercase .PY, .ps1, semicolon packing, apply_after reuse, and CLI parser behavior |
| `python .coord/tasks/U98-D-R-check.py` | 0 | Verified review document format and acceptance check |
