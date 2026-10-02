```contract
work_id: U123-L
worker: local
goal: commit gate enforces Antigravity audit -> Ollama fix -> Antigravity review for v7_harness code (U123, user order 2026-10-02)
inputs:
- v7_harness/calculator_gate.py sha256=b1a0ff8f2b34cb68e8ba39562387acd3769c9e9f8426296cef1beb9977899172
allow:
- v7_harness/calculator_gate.py
acceptance: python -m unittest tests.test_u123_order_gate tests.test_u21_calculator tests.test_u34_precision_harness tests.test_u75_merge_gate tests.test_u22_worker_limits
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Task: change v7_harness/calculator_gate.py so a v7_harness/*.py commit passes only after "Antigravity audits -> Ollama fixes -> Antigravity reviews". Edit only this file. Keep every existing function name and the merge-parent route (parent_digests) unchanged.

1. Below GATED_PREFIX add these module constants, each with a short comment saying why:
   LOCAL_AUTHORS = frozenset({"ollama", "local", "cascade"})
   REVIEWERS = ("agy", "codex")
   FAILED_OUTCOMES = frozenset({"FAIL", "FAILED", "BLOCKED", "UNUSABLE", "REWORK", "REJECTED"})
   AUDIT_RE = re.compile(r"^Audit:\s*(relay_[0-9a-f]+)\s*$", re.MULTILINE)

2. Add a function `_review_ok(task_dir: Path, bundle_id, ledger_rows) -> bool`:
   - For each reviewer in REVIEWERS read JSON from task_dir / f"review_{reviewer}.json"; skip it on any read or parse error or if it is not a dict.
   - It counts only when record["verdict"] == "PASS", bundle_id is a non-empty str, and record["bundle_id"] == bundle_id.
   - Then return True if record.get("author_worker") is in LOCAL_AUTHORS.
   - Otherwise return True only if some row in ledger_rows (dicts) has: str(row.get("work_id") or "").split("-")[0] == task_dir.name.split("-")[0], row.get("worker") in LOCAL_AUTHORS, row.get("outcome") in FAILED_OUTCOMES, and int(row.get("input_tokens") or 0) > 0 (the Ollama model really ran).
   - Return False when no reviewer file qualifies.

3. Change `applied_digests(pilot_dir: Path)` to `applied_digests(pilot_dir: Path, ledger_rows=())`. After the existing `promotion != "APPLIED"` skip, also `continue` when `not _review_ok(task_dir, summary.get("bundle_id"), ledger_rows)`.

4. Change `check(staged, message, pilot_dir, parents=None)` to `check(staged, message, pilot_dir, parents=None, ledger_rows=None)`:
   - Delete the Calculator-Exempt block (exempt_pattern and its loop) completely; the exemption no longer covers code.
   - Call `applied_digests(directory, ledger_rows or [])`.
   - Change the violation text to f"{path}: not an APPLIED pilot bundle with an independent PASS review (Ollama author, or a real failed Ollama run of the card) or equal to a merge parent".
   - Update the module docstring: replace the Calculator-Exempt sentence with one saying the bundle needs an independent PASS review and the commit needs an `Audit: relay_<id>` line (U123).

5. Add a function `audit_errors(message: str, gated_paths: list[str], agy_auto_path: Path) -> list[str]`:
   - Return [] when gated_paths is empty.
   - m = AUDIT_RE.search(message); if there is no match return one error string starting "AUDIT_FIRST: " that tells to add an `Audit: relay_<id>` line naming an answered Antigravity audit reply.
   - Read agy_auto_path line by line as JSON (skip blank or bad lines); on OSError return one "AUDIT_FIRST: " error that the ledger is missing.
   - Return [] if any row has row.get("state") == "ANSWERED" and row.get("reply_id") == m.group(1); else return one "AUDIT_FIRST: " error naming the unknown id.

6. In `main`:
   - After computing pilot_dirs, load ledger rows: `from v7_harness.coord.hook_context import shared_desk`, desk = shared_desk(Path(".")), read desk / ".coord" / "usage" / "runs.jsonl" line by line as JSON dicts (skip bad lines; missing file means []).
   - parents = parent_digests(list(staged)); violations = check(staged, message, pilot_dirs, parents, ledger_rows=rows).
   - new_code = [p for p, body in staged.items() if _digest(body) not in parents.get(p, set())]
   - violations += audit_errors(message, new_code, desk / ".coord" / "mailbox" / "delivery" / "agy_auto.jsonl")
   - Change the delegate hint print to: 'order: Antigravity audit letter (ACTIONABLE_DELTA) -> pilot run --worker local -> pilot review --reviewer agy -> --approve; commit with "Audit: relay_<reply id>"'

Reply with ===FILE: v7_harness/calculator_gate.py=== containing the whole new file, then ===END===.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
