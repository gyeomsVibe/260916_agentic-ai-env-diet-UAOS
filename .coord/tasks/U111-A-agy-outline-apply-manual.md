```contract
work_id: U111-A
worker: apply
goal: Antigravity's whole-file view_file deny carries the same exact outline as the Claude and Codex denies
inputs:
- v7_harness/olla.py sha256=3d1b205b34ed5d9874c13ed68d736b658806d104aeafc6fd7b631ea34529742d
- tests/test_u108_map_first.py sha256=3e5e3b760df4a007c5b16adbf9573f15ab825d4a8962a75055813ddcb79372f3
allow:
- v7_harness/olla.py
acceptance: python -m unittest tests.test_u108_map_first tests.test_u17_olla tests.test_u103_olla_parity tests.test_u47_o3_guard_cleanup
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the block below exactly.

===EDIT: v7_harness/olla.py===
<<<<<<< SEARCH
                return {"decision": "deny", "reason": (f"Whole-file view of ~{tokens:,} tokens refused; find the lines with "
                                                       f"the olla digest or grep, then view with StartLine/EndLine. {hint}")}
=======
                # U111: Antigravity gets the same exact outline as Claude's Read and Codex's shell denies (U108).
                return {"decision": "deny", "reason": (f"Whole-file view of ~{tokens:,} tokens refused; find the lines with "
                                                       f"the olla digest or grep, then view with StartLine/EndLine. {hint}"
                                                       + _outline_note(Path(str(args.get("AbsolutePath") or ""))))}
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
