```contract
work_id: U123-A1
worker: apply
goal: commit gate enforces Antigravity audit -> Ollama fix -> Antigravity review order for v7_harness code (U123)
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
apply_after: U123-L2
```

## Instructions for the worker

Apply the blocks below exactly.

===EDIT: v7_harness/calculator_gate.py===
<<<<<<< SEARCH
내용이 같아야 한다. 예외는 커밋 메시지의 `Calculator-Exempt: <이유>` 줄로만 허용하고 이유가 커밋에 남는다.
"""
=======
내용이 같아야 하고, 그 묶음(bundle)에는 같은 bundle_id 의 독립 검토 PASS(Antigravity 또는 Codex)가 있어야 하며, 커밋에는
Antigravity 감사 답장을 가리키는 `Audit: relay_<id>` 줄이 있어야 한다(U123). `Calculator-Exempt` 예외는 코드에 더는 통하지 않는다.
"""
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/calculator_gate.py===
<<<<<<< SEARCH
GATED_PREFIX = "v7_harness/"
=======
GATED_PREFIX = "v7_harness/"
LOCAL_AUTHORS = frozenset({"ollama", "local", "cascade"})  # U123: the free Ollama routes that must write the fix first
REVIEWERS = ("agy", "codex")  # U123: independent reviewers; the conductor and the author never approve alone
FAILED_OUTCOMES = frozenset({"FAIL", "FAILED", "BLOCKED", "UNUSABLE", "REWORK", "REJECTED"})  # same set as delegation.py
AUDIT_RE = re.compile(r"^Audit:\s*(relay_[0-9a-f]+)\s*$", re.MULTILINE)  # U123: the Antigravity audit reply id


def _review_ok(task_dir: Path, bundle_id, ledger_rows) -> bool:
    """U123: PASS by an independent reviewer for this exact bundle; a non-Ollama author also needs a failed Ollama
    run of the same card that really called the model (U122-F1: PROMPT_TOO_LARGE had input_tokens 0)."""
    card = task_dir.name.split("-")[0]
    for reviewer in REVIEWERS:
        try:
            record = json.loads((task_dir / f"review_{reviewer}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(record, dict) or record.get("verdict") != "PASS":
            continue
        if not isinstance(bundle_id, str) or not bundle_id or record.get("bundle_id") != bundle_id:
            continue
        if record.get("author_worker") in LOCAL_AUTHORS:
            return True
        for row in ledger_rows:
            if (isinstance(row, dict) and str(row.get("work_id") or "").split("-")[0] == card
                    and row.get("worker") in LOCAL_AUTHORS and row.get("outcome") in FAILED_OUTCOMES
                    and int(row.get("input_tokens") or 0) > 0):
                return True
    return False
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/calculator_gate.py===
<<<<<<< SEARCH
def applied_digests(pilot_dir: Path) -> dict[str, set[str]]:
=======
def applied_digests(pilot_dir: Path, ledger_rows=()) -> dict[str, set[str]]:
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/calculator_gate.py===
<<<<<<< SEARCH
        if not isinstance(summary, dict) or summary.get("promotion") != "APPLIED":
            continue
=======
        if not isinstance(summary, dict) or summary.get("promotion") != "APPLIED":
            continue
        if not _review_ok(task_dir, summary.get("bundle_id"), ledger_rows):
            continue
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/calculator_gate.py===
<<<<<<< SEARCH
def check(staged: dict[str, bytes], message: str, pilot_dir: Path | list[Path],
          parents: dict[str, set[str]] | None = None) -> list[str]:
    exempt_pattern = re.compile(r"^Calculator-Exempt:\s*\S")
    for line in message.splitlines():
        if exempt_pattern.match(line):
            return []

    digests: dict[str, set[str]] = {path: set(found) for path, found in (parents or {}).items()}
    for directory in pilot_dir if isinstance(pilot_dir, list) else [pilot_dir]:
        for path, found in applied_digests(directory).items():
            digests.setdefault(path, set()).update(found)
    violations: list[str] = []
    for path, content in staged.items():
        if path.startswith(GATED_PREFIX) and path.endswith(".py"):
            if _digest(content) not in digests.get(path, set()):
                violations.append(f"{path}: not produced by an APPLIED pilot bundle or equal to a merge parent")
    return violations
=======
def check(staged: dict[str, bytes], message: str, pilot_dir: Path | list[Path],
          parents: dict[str, set[str]] | None = None, ledger_rows=None) -> list[str]:
    # U123: the Calculator-Exempt line no longer skips this check; it let code bypass the audit/Ollama/review order.
    digests: dict[str, set[str]] = {path: set(found) for path, found in (parents or {}).items()}
    for directory in pilot_dir if isinstance(pilot_dir, list) else [pilot_dir]:
        for path, found in applied_digests(directory, ledger_rows or []).items():
            digests.setdefault(path, set()).update(found)
    violations: list[str] = []
    for path, content in staged.items():
        if path.startswith(GATED_PREFIX) and path.endswith(".py"):
            if _digest(content) not in digests.get(path, set()):
                violations.append(f"{path}: not an APPLIED pilot bundle with an independent PASS review (Ollama "
                                  "author, or a real failed Ollama run of the card) or equal to a merge parent")
    return violations


def audit_errors(message: str, gated_paths: list[str], agy_auto_path: Path) -> list[str]:
    """U123: new v7_harness code names the answered Antigravity audit reply it follows (`Audit: relay_<id>`)."""
    if not gated_paths:
        return []
    match = AUDIT_RE.search(message)
    if match is None:
        return ["AUDIT_FIRST: add an `Audit: relay_<id>` line naming the answered Antigravity audit reply"]
    try:
        lines = Path(agy_auto_path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return [f"AUDIT_FIRST: no Antigravity reply ledger at {agy_auto_path}"]
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("state") == "ANSWERED" and row.get("reply_id") == match.group(1):
            return []
    return [f"AUDIT_FIRST: {match.group(1)} is not an answered Antigravity reply"]
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/calculator_gate.py===
<<<<<<< SEARCH
    violations = check(staged, message, pilot_dirs, parent_digests(list(staged)))
=======
    from v7_harness.coord.hook_context import shared_desk

    desk = shared_desk(Path("."))
    rows = []
    try:
        for line in (desk / ".coord" / "usage" / "runs.jsonl").read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    parents = parent_digests(list(staged))
    violations = check(staged, message, pilot_dirs, parents, ledger_rows=rows)
    new_code = [p for p, body in staged.items() if _digest(body) not in parents.get(p, set())]
    violations += audit_errors(message, new_code, desk / ".coord" / "mailbox" / "delivery" / "agy_auto.jsonl")
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/calculator_gate.py===
<<<<<<< SEARCH
            'delegate via: python -m v7_harness.cli pilot run --worker auto --task <ID> --source . --prompt-file <md> --accept-cmd "<test>" --work-dir .coord/pilot',
=======
            'order: Antigravity audit letter (ACTIONABLE_DELTA) -> pilot run --worker local -> pilot review '
            '--reviewer agy -> --approve; commit with "Audit: relay_<reply id>"',
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
