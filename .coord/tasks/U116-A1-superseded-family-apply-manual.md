```contract
work_id: U116-A1
worker: apply
goal: A BLOCKED step is superseded by a later PASS of its retry family or its apply_after replacement
inputs:
- tests/test_u116_superseded_family.py sha256=f79b771c2e85ddf8ab75a5c4d055a568d8cf6f33d332c61530dce427a2464d99
- tests/test_u88_p1_superseded.py sha256=3442fc2dbd15222de8fe99b0e6b0f59fe7c7d392bdd82c173a30f7d30500dd26
- v7_harness/coord/sentinel.py sha256=f78ccbf3683585d35e7ae6bb8310717222f1450b2bb6d22bca66117a8dc2ef67
allow:
- v7_harness/coord/sentinel.py
acceptance: python -m unittest tests.test_u116_superseded_family tests.test_u88_p1_superseded tests.test_u23_mailbox tests.test_u32_sentinel_bell tests.test_u36_evidence_gated_rsi tests.test_u47_sentinel_reconciliation
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
apply_after: U116-L
```

## Instructions for the worker

Apply the blocks below exactly. (U116-L, Ollama, deleted the timestamp parse in `_passed_since` → NameError.)

===EDIT: v7_harness/coord/sentinel.py===
<<<<<<< SEARCH
def _last_pass_by_step(project_root: Path) -> dict[str, float]:
=======
def _family(step: str) -> str:
    """U116: retry family of a step: drop `-R<n>`, `-P`, `-agy`, then the digits after a lettered last segment.

    U113-D3 -> U113-D, U106-A2-P -> U106-A, U115-L2 -> U115-L; a card id such as U86 stays U86 (its digits follow `U`
    at the start, not a lettered `-X` segment), so a sibling step like U86-F1 (family U86-F) never clears U86.
    """
    import re

    step = re.sub(r"-(R\d+|P|agy)$", "", step)
    return re.sub(r"(-[A-Za-z]+)\d+$", r"\1", step)


def _apply_after_links(project_root: Path) -> dict[str, str]:
    """U116: work_id -> failed work_id it replaced, read from `.coord/tasks/*.md` contract manuals (U98-D)."""
    links: dict[str, str] = {}
    for manual in sorted((project_root / ".coord" / "tasks").glob("*.md")):
        try:
            head = manual.read_text(encoding="utf-8")[:2000]
        except OSError:
            continue
        fields = dict(line.split(":", 1) for line in head.splitlines() if line.startswith(("work_id:", "apply_after:")))
        if "work_id" in fields and "apply_after" in fields:
            links[fields["work_id"].strip()] = fields["apply_after"].strip()
    return links


def _last_pass_by_step(project_root: Path) -> dict[str, float]:
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/coord/sentinel.py===
<<<<<<< SEARCH
    passed: dict[str, float] = {}
    for row in rows:
=======
    passed: dict[str, float] = {}
    links = _apply_after_links(project_root)  # U116: an apply run also passes the delegate it replaced
    for row in rows:
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/coord/sentinel.py===
<<<<<<< SEARCH
        for step in {work_id, re.sub(r"-R\d+$", "", work_id)}:
=======
        linked = links.get(work_id)
        steps = {work_id, re.sub(r"-R\d+$", "", work_id), _family(work_id)}
        for step in steps | ({linked, _family(linked)} if linked else set()):
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/coord/sentinel.py===
<<<<<<< SEARCH
    if not isinstance(step, str) or step not in passed or not isinstance(stamp, str):
        return False
=======
    if not isinstance(step, str) or not isinstance(stamp, str):
        return False
    done = max(passed.get(step, 0.0), passed.get(_family(step), 0.0))  # U116: a later retry of its family counts
    if not done:
        return False
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/coord/sentinel.py===
<<<<<<< SEARCH
    return passed[step] > blocked_at
=======
    return done > blocked_at
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
