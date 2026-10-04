```contract
work_id: U148-C1
worker: local
goal: U148 Antigravity's PreInvocation hook keeps the payload key names as evidence and registers nothing, written by Ollama from a spec
inputs:
- v7_harness/cli.py sha256=SHA_CLI
allow:
- v7_harness/cli.py
acceptance: python -m unittest tests.test_u148_hook_registers_nothing.HookRegistersNothingTest.test_no_payload_registers_a_desk tests.test_u148_agy_desk_visible.AgyDeskTest.test_cli_later_call_bad_id_and_worker_register_nothing tests.test_u148_agy_desk_visible.AgyDeskTest.test_first_call_registers_nothing_and_keeps_the_key_names tests.test_u147_user_window_board tests.test_u147_route_counterexamples
forbidden: edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 900
```

Card U148 REPLAN (Codex codex_u148_c1_human_origin_gate_unmet: no payload field proves a human turn, so the hook
never writes the user desk). Dictation: copy the two edit blocks below exactly, in this order, and change nothing
else. They sit next to `is_human_prompt` in v7_harness/cli.py. The first run failed its preflight
(PROMPT_TOO_LARGE ~58292 > 12288: the whole deliver.py was an input and loose anchors kept most of cli.py), so this
run drops deliver.py and anchors only on that one name.

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
                    from .coord.deliver import is_human_prompt, register_user_desk
=======
                    from .coord.deliver import agy_desktop_conversation, is_human_prompt, register_user_desk
>>>>>>> REPLACE

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
                        register_user_desk(project, args.tool, hook_session(stdin_text) or "",
                                           source="UserPromptSubmit")
=======
                        register_user_desk(project, args.tool, hook_session(stdin_text) or "",
                                           source="UserPromptSubmit")
                    elif args.tool == "antigravity" and isinstance(event, dict) \
                            and event.get("invocationNum", 0) == 0 \
                            and agy_desktop_conversation(event.get("conversationId")):
                        # U148: Antigravity has no UserPromptSubmit, and nothing in its PreInvocation payload proves
                        # a human turn (Codex review: subagents, restarts and continuations look the same), so the
                        # hook never writes the desk; coord presence --desk-thread does (U148-C2). The key names
                        # (never values) are the evidence a future human-origin field would need.
                        keys = project / ".coord" / "presence" / "agy_hook_keys.json"
                        keys.parent.mkdir(parents=True, exist_ok=True)
                        keys.write_text(json.dumps(sorted(event)), encoding="utf-8")
>>>>>>> REPLACE
