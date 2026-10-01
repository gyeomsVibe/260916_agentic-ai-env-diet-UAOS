```contract
work_id: U106-A1-P
worker: apply
goal: Apply Antigravity's U106-A1-agy output unchanged; its staged files passed the acceptance but promotion was blocked by EXTERNAL_WRITE from the judge's own concurrent runs.
inputs:
- v7_harness/delegation.py sha256=3cb1537e9a7149f2f836b61abee10a1506e8a2ab87315d7e24e9e8a941e03834
- v7_harness/manual.py sha256=603ca443ab6942ed06a8d22cad0519ea6df360cb23655f216e7118dd1ffdd390
allow:
- v7_harness/delegation.py
- v7_harness/manual.py
acceptance: python -m unittest tests.test_u106_local_first.LocalFirstLintTests tests.test_u98d_delegate_first tests.test_u34_precision_harness tests.test_u45_general_uaos
forbidden: design changes; edits outside allow; editing or weakening tests; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
apply_after: U106-A1-agy
```

## Instructions for the worker

Apply the blocks below exactly. They are Antigravity's code from run U106-A1-agy (stage `.work/u106/wd_a1/stage/U106-A1-agy`), which passed `tests.test_u106_local_first.LocalFirstLintTests tests.test_u98d_delegate_first` (14 tests, exit 0) in its stage; the run was blocked only because the judge wrote into the source during it.

===EDIT: v7_harness/delegation.py===
<<<<<<< SEARCH
    return [f"DELEGATE_FIRST: {lines} dictated code lines > {DICTATION_CODE_LINE_LIMIT}; write a spec for worker local (Ollama) or agy first, and apply only with apply_after: <work_id of that failed run>"]
=======
    return [f"DELEGATE_FIRST: {lines} dictated code lines > {DICTATION_CODE_LINE_LIMIT}; write a spec for worker local (Ollama) or agy first, and apply only with apply_after: <work_id of that failed run>"]


LOCAL_WORKERS = frozenset({"ollama", "local", "cascade"})  # U106: the free local routes; a paid worker takes code only after one of them failed.
PAID_WORKERS = frozenset({"agy", "claude"})


def _failed_local(project: Path, work_id: str, card: str) -> bool:
    """Check if a local run with the given work_id failed."""
    if not card or _card(work_id) != card:
        return False
    from v7_harness.coord.hook_context import shared_desk
    path = shared_desk(project) / ".coord" / "usage" / "runs.jsonl"
    if not path.exists():
        return False
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                if row.get("work_id") == work_id and row.get("worker") in LOCAL_WORKERS and row.get("outcome") in FAILED_OUTCOMES:
                    return True
    except OSError:
        pass
    return False


def local_first_errors(contract: dict[str, Any], project: Path) -> list[str]:
    """Check if code work was attempted locally before routing to a paid worker."""
    if contract.get("worker") not in PAID_WORKERS:
        return []
    raw_allow = contract.get("allow") or []
    if isinstance(raw_allow, str):
        raw_allow = [raw_allow]
    normalized = [_normalize(str(p)) for p in raw_allow]
    code_paths = [p for p in normalized if p.lower().endswith(CODE_SUFFIXES) and not p.startswith("tests/")]
    if not code_paths:
        return []
    after = str(contract.get("paid_after") or "").strip()
    if after and _failed_local(project, after, _card(contract.get("work_id"))):
        return []
    return [
        "LOCAL_FIRST: code work goes to worker: cascade (Ollama first, escalates to the paid worker on a failed acceptance); a paid worker needs paid_after: <work_id of a failed Ollama/local/cascade run of this card>"
    ]
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/manual.py===
<<<<<<< SEARCH
    from v7_harness.delegation import delegate_first_errors
    report.errors.extend(delegate_first_errors(text, contract, project))
=======
    from v7_harness.delegation import delegate_first_errors, local_first_errors
    report.errors.extend(delegate_first_errors(text, contract, project))
    report.errors.extend(local_first_errors(contract, project))  # U106: Ollama first for code work
>>>>>>> REPLACE
===END===
