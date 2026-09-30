```contract
work_id: U103-A1
worker: apply
goal: coord presence --from-hook --delta adds the desk delta for the hook's own tool, in each tool's output format.
inputs:
- tests/test_u103_desk_delta.py sha256=63f63dd71af86c1a509e78b67874ff8098869c54f0f53fa6e37b3514b176a50c
- v7_harness/coord/desk_delta.py sha256=894759c7c1609ee9d5a25da69649473b5cbab2d90498d583c6170a6dce329eaa
allow:
- v7_harness/cli.py
context_allow:
- tests/test_u103_desk_delta.py
acceptance: python -m unittest tests.test_u103_desk_delta tests.test_u95a_antigravity_briefing tests.test_u58_session_presence
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the blocks below exactly (judge-dictated, 16 lines). `coord presence --from-hook --delta` appends the U103 desk delta for the hook's own tool, in that tool's output format: a plain line for Claude and Codex, the injectSteps message for Antigravity (first call of a turn only).

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
    # U57-D: the acting conductor had to write a Codex quota lease through Python (2026-09-27); the lease itself
=======
    # U103: the delta hook ran only for Claude and only in one project; each tool's hook now asks for its own.
    p_coord_presence.add_argument("--delta", action="store_true", default=False,
                                  help="With --from-hook: add what the other tools changed since this tool last looked")
    # U57-D: the acting conductor had to write a Codex quota lease through Python (2026-09-27); the lease itself
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
        elif say in ("brief", "p1") and line:
=======
        elif say in ("brief", "p1", "none") and line:
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
                line = ""  # U46-P1: an unchanged P1 set is ACK_ONLY; it was repeated on every prompt
=======
                line = ""  # U46-P1: an unchanged P1 set is ACK_ONLY; it was repeated on every prompt
            if say == "none":
                line = ""  # `none` prints nothing of its own; only a U103 desk delta may speak
            if getattr(args, "delta", False) and args.tool:
                from .coord.desk_delta import delta_text

                event = json.loads(stdin_text) if stdin_text.strip() else {}
                event = event if isinstance(event, dict) else {}
                if event.get("invocationNum", 0) == 0:  # Antigravity: later calls of the same turn read nothing
                    session = hook_session(stdin_text) or str(event.get("conversationId") or "") or None
                    line = "\n".join(part for part in (line, delta_text(project, args.tool, session)) if part)
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
