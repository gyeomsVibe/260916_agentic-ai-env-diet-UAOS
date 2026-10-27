# U229B2-L3 (judge claude, deputy for LIMITED codex; Codex re-review owed): invocation journal review path and CLI

Card manual: `.coord/tasks/U229B2-card-manual.md`. Slice 3 of `v7_harness/invocation.py`: the evidence-only review
(`_review_rows`, `_proposal`, `review`) and the module CLI (`_parser`, `main`), added as whole new top-level
functions. `main` keeps provider execution parked (`run`/`pair` fail with EXECUTOR_PARKED_UNVERIFIED_TREE_CONTAINMENT).

```contract
work_id: U229B2-L3
worker: local
goal: add the evidence-only invocation review and the parked-executor module CLI to v7_harness/invocation.py
inputs:
- v7_harness/invocation.py sha256=5994925192cbda0b902f7bbe4897056e8b2058bf7cd1e94ad2d959ae12411221
- tests/test_u229_independent_invocation.py sha256=e755fafb36ca36a071835f67ab52e259eaf40563d8ad38e84cfdf2f8f7e1201c
allow:
- v7_harness/invocation.py
context_allow:
- tests/test_u229_independent_invocation.py
acceptance: python -m unittest tests.test_u229_independent_invocation
forbidden: editing or deleting tests; edits outside allow; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 900 seconds
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Exact edits: five whole new top-level functions, verbatim, in this order

```python
def _review_rows(db, window):
    if type(window) is not int or not 1 <= window <= 1000:
        raise InvocationError("INVALID_REVIEW_WINDOW")
    with _connect(db) as con:
        rows = con.execute("SELECT * FROM attempts ORDER BY started_at DESC,id LIMIT ?", (window,)).fetchall()
    return [dict(row) for row in reversed(rows)]


def _proposal(rows):
    fingerprint = hashlib.sha256(json.dumps(rows, sort_keys=True).encode("utf-8")).hexdigest()
    return {"schema": "uaos-invocation-review-v1", "fingerprint": fingerprint,
            "attempts": len(rows), "outcomes": dict(Counter(row["outcome"] for row in rows)),
            "models": dict(Counter(row["model"] for row in rows)),
            "errors": dict(Counter(row["error_class"] for row in rows if row["error_class"])),
            "token_unknown_attempts": sum(row["input_tokens"] is None or row["output_tokens"] is None for row in rows),
            "acceptance": "UNVERIFIED", "quota_saving": "UNMEASURED", "automatic_adoption": False,
            "auto_adopt": False,
            "next_action": "REVIEW_FIXED_ACCEPTANCE_AND_CAUSES_BEFORE_ROUTING_OR_POLICY_CHANGE"}


def review(db=None, output=None, *, window=100):
    proposal = _proposal(_review_rows(db, window))
    selected = Path(output) if output else Path(db or DEFAULT_DB).parent / "invocation-reviews"
    directory = selected.parent if selected.suffix.lower() == ".json" else selected
    directory.mkdir(parents=True, exist_ok=True)
    target = selected if selected.suffix.lower() == ".json" else directory / (proposal["fingerprint"] + ".json")
    try:
        with target.open("x", encoding="utf-8") as handle:
            json.dump(proposal, handle, sort_keys=True, indent=2)
    except FileExistsError:
        if json.loads(target.read_text(encoding="utf-8")) != proposal:
            raise InvocationError("REVIEW_FINGERPRINT_COLLISION")
    return {**proposal, "artifact": str(target)}


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "pair", "review"))
    parser.add_argument("--input", type=Path, help="JSON request file; raw prompts are never journalled")
    parser.add_argument("--db", type=Path)
    parser.add_argument("--output", type=Path, help="Review artifact directory")
    parser.add_argument("--window", type=int, default=100)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        if args.action == "review":
            result = review(args.db, args.output, window=args.window)
        else:
            raise InvocationError("EXECUTOR_PARKED_UNVERIFIED_TREE_CONTAINMENT")
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(json.dumps({"outcome": "FAILED", "error_class": _exception(exc)}))
        return 1
```

## Output

- Reply with one ===EDIT: v7_harness/invocation.py=== block holding the five whole top-level functions above in a
  ```python fence, copied character for character. No explanations. Do not claim success; the acceptance command
  decides.
