```contract
work_id: U148-C2
worker: apply
apply_after: U148-C2
goal: U148 an explicit, maintained registration moves Antigravity's user desk, written by Ollama from a spec
inputs:
- v7_harness/cli.py sha256=SHA_CLI
allow:
- v7_harness/cli.py
acceptance: python -m unittest tests.test_u148_agy_desk_visible tests.test_u148_hook_registers_nothing tests.test_u147_user_window_board tests.test_u147_route_counterexamples
forbidden: edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 900
```

Card U148 (Codex review: explicit maintained registration is the fallback that moves a desk). Dictation: copy the
two edit blocks below exactly, in this order, and change nothing else. They sit next to `cmd_coord_presence` and
`from_hook` in v7_harness/cli.py; only those two names anchor the context, so the assembled prompt stays small
(the sibling run U148-C1 failed its preflight on loose anchors). Model attempt U148-C2 (preflight 3900, input 5729,
output 259) returned the right lines as bare fenced blocks with no edit headers ("model returned no file block", the
cause rsi.py maps to worker: apply with apply_after), so this run applies the blocks exactly.

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
    p_coord_presence.set_defaults(func=cmd_coord_presence)
=======
    # U148: a hook never moves an OK Antigravity desk (Codex review); this explicit registration does.
    p_coord_presence.add_argument("--desk-thread", default=None,
                                  help="U148: record this Antigravity desktop conversation id as the user's desk")
    p_coord_presence.set_defaults(func=cmd_coord_presence)
>>>>>>> REPLACE

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
    if getattr(args, "from_hook", False):
=======
    if getattr(args, "desk_thread", None) is not None:
        from .coord.deliver import agy_desktop_conversation, register_user_desk

        # Only a conversation of the Antigravity desktop app can be the user's Antigravity desk.
        ok = args.tool == "antigravity" and agy_desktop_conversation(args.desk_thread) \
            and register_user_desk(Path(args.project), "antigravity", args.desk_thread, source="explicit")
        print(json.dumps({"ok": bool(ok), "tool": args.tool, "desk_thread": args.desk_thread}))
        return 0 if ok else 2
    if getattr(args, "from_hook", False):
>>>>>>> REPLACE
