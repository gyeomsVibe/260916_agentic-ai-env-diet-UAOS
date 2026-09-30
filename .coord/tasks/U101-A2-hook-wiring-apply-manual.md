```contract
work_id: U101-A2
worker: apply
goal: Drop merge commits and committed files from the absence brief and print it from the prompt hook with an audit order.
inputs:
- uaos_everywhere/hooks/absence_brief.py sha256=e2e99ff56d5b6ba0fe678e1e0c6891a03931d43ebcb2438650af60039803bf42
- uaos_everywhere/hooks/codex_delta.py sha256=0d8b60de686b34c03b8a5eaeb57edba7eb3c39458507fe4da07c60a19f50a1bb
- tests/test_u101_absence_brief.py sha256=9c954e7c13fa60ddb61430d9e41255300b9d3dcd386d2731676c12fe068c6a38
allow:
- uaos_everywhere/hooks/absence_brief.py
- uaos_everywhere/hooks/codex_delta.py
acceptance: python -m unittest tests.test_u101_absence_brief tests.test_u99m_mailbox_delta
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
apply_after: U101-L2
timeout_s: 300
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the blocks below exactly (judge-dictated under `apply_after: U101-L2`, the same card whose Ollama runs failed twice).

1. The first real run listed 11 merge commits and 18 manuals that git had already committed, so the other tool's changes were buried. This drops merges and lists only files that git does not track yet.
2. The prompt hook now prints these items, with an order to audit them.

===EDIT: uaos_everywhere/hooks/absence_brief.py===
<<<<<<< SEARCH
    for line in _git(root, "log", "--all", f"--since=@{int(since)}", "--invert-grep", f"--grep={SELF_TRAILER}",
                     "--format=%h %s"):
=======
    # Merges only land commits already listed; 11 of them buried the real changes on the first run (2026-09-30).
    for line in _git(root, "log", "--all", "--no-merges", f"--since=@{int(since)}", "--invert-grep",
                     f"--grep={SELF_TRAILER}", "--format=%h %s"):
>>>>>>> REPLACE
===END===

===EDIT: uaos_everywhere/hooks/absence_brief.py===
<<<<<<< SEARCH
    for folder in FILE_FOLDERS:
        base = root / folder
=======
    # A committed file is already news through its commit; only files git does not track yet are new here.
    tracked = set(_git(root, "ls-files", "--", *FILE_FOLDERS))
    for folder in FILE_FOLDERS:
        base = root / folder
>>>>>>> REPLACE
===END===

===EDIT: uaos_everywhere/hooks/absence_brief.py===
<<<<<<< SEARCH
                if path.is_file() and path.stat().st_mtime > since:
=======
                if path.is_file() and path.stat().st_mtime > since and f"{folder}/{path.name}" not in tracked:
>>>>>>> REPLACE
===END===

===EDIT: uaos_everywhere/hooks/codex_delta.py===
<<<<<<< SEARCH
    items.sort()
    cursor_path.parent.mkdir(parents=True, exist_ok=True)
=======
    items.sort()
    # U101: letters and PLAN rows missed direct commits, hand-written leases and uncommitted edits (U100 audit).
    try:
        from absence_brief import absence_items  # deployed next to this hook in ~/.uaos/hooks
    except ImportError:
        from uaos_everywhere.hooks.absence_brief import absence_items
    others = absence_items(ROOT, since)
    if others:
        print(f"OTHER TOOLS CHANGED since your last prompt ({len(others)} items): audit each before new work;"
              " the user must not have to ask (U101).")
        for line in others[:MAX_LINES]:
            print(f"- {line[:SNIPPET]}")
    cursor_path.parent.mkdir(parents=True, exist_ok=True)
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
