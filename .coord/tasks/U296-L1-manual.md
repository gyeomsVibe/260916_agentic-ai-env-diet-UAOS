```contract
work_id: U296-L1
worker: local
goal: In v7_harness/cli.py add --session to coord watch and coord deliver, and --wait to coord deliver, passing them on as in the SEARCH/REPLACE blocks
inputs:
- v7_harness/cli.py sha256=950246a4b96b3cc44074eeb6e5435a4ccfb1ad5933ca9ba7d1baea1c142828fb
allow:
- v7_harness/cli.py
acceptance: python -c "import subprocess,sys;o=subprocess.run([sys.executable,'-m','v7_harness.cli','coord','deliver','--help'],capture_output=True,text=True).stdout;sys.exit(0 if '--wait' in o and '--session' in o else 1)"
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: antigravity
timeout_s: 180
remote_budget_tokens: 0
```

## Instructions for the worker

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
                                 choices=["PASS", "REVISE", "FAIL", "APPROVE", "PIVOT", "REWORK"])
    p_coord_deliver.add_argument("--delta", default=None, help="U141-A: what changed; an ACTIONABLE letter needs one")
    p_coord_deliver.set_defaults(func=cmd_coord_deliver)
=======
                                 choices=["PASS", "REVISE", "FAIL", "APPROVE", "PIVOT", "REWORK"])
    p_coord_deliver.add_argument("--delta", default=None, help="U141-A: what changed; an ACTIONABLE letter needs one")
    p_coord_deliver.add_argument("--session", default="",
                                 help="U296: address the letter to one receiver session (same as --thread)")
    p_coord_deliver.add_argument("--wait", action="store_true",
                                 help="U296: wait for the Antigravity auto-answer (old behavior); default returns "
                                      "after PUBLISHED and the answer arrives as a letter")
    p_coord_deliver.set_defaults(func=cmd_coord_deliver)
>>>>>>> REPLACE

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
    # U141-A: structured (default) wakes only on an ACTIONABLE letter, once per letter, one watcher per target.
    p_coord_watch.add_argument("--policy", default="structured", choices=["structured", "legacy"])
    p_coord_watch.set_defaults(func=cmd_coord_watch)
    p_coord_listen = p_coord_subs.add_parser("listen", help="Fast Claude startup bootstrap; native Stop asyncRewake listener")
=======
    # U141-A: structured (default) wakes only on an ACTIONABLE letter, once per letter, one watcher per target.
    p_coord_watch.add_argument("--policy", default="structured", choices=["structured", "legacy"])
    p_coord_watch.add_argument("--session", default="",
                               help="U296: this session's id; one watcher per (target, session), and it takes only "
                                    "letters naming it (the main desk also takes unaddressed ones)")
    p_coord_watch.set_defaults(func=cmd_coord_watch)
    p_coord_listen = p_coord_subs.add_parser("listen", help="Fast Claude startup bootstrap; native Stop asyncRewake listener")
>>>>>>> REPLACE

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH

    result = deliver(Path(args.project), message=args.message, actor=args.actor,
                     target=args.target, thread=args.thread, card=args.card,
                     wake_class=getattr(args, "wake_class", None),
                     verdict_requested=getattr(args, "verdict_requested", None),
                     verdict=getattr(args, "verdict", None), delta=getattr(args, "delta", None))
    # U57-C: QUEUED_INTERACTIVE means a live `coord watch` holds the letter for the interactive session; not a failure.
    # U74-D: QUEUED_ACK_ONLY is an ACK_ONLY letter left in the inbox without a paid turn; also not a failure.
=======

    result = deliver(Path(args.project), message=args.message, actor=args.actor,
                     target=args.target, thread=args.thread or getattr(args, "session", ""), card=args.card,
                     wake_class=getattr(args, "wake_class", None),
                     verdict_requested=getattr(args, "verdict_requested", None),
                     verdict=getattr(args, "verdict", None), delta=getattr(args, "delta", None),
                     **({"agy_wait": bool(args.wait)} if hasattr(args, "wait") else {}))
    # U57-C: QUEUED_INTERACTIVE means a live `coord watch` holds the letter for the interactive session; not a failure.
    # U74-D: QUEUED_ACK_ONLY is an ACK_ONLY letter left in the inbox without a paid turn; also not a failure.
>>>>>>> REPLACE

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH

    found = watch(Path(args.project), tuple(args.target), timeout_s=args.timeout, interval_s=args.interval,
                  wakes_session=args.wakes_session, policy=getattr(args, "policy", "structured"))
    if found is not None and found.get("state") == "ALREADY_WATCHING":
        # U141-A: one watcher per target; a second one exits instead of waking the session a second time.
=======

    found = watch(Path(args.project), tuple(args.target), timeout_s=args.timeout, interval_s=args.interval,
                  wakes_session=args.wakes_session, policy=getattr(args, "policy", "structured"),
                  requester_session=getattr(args, "session", None) or None)
    if found is not None and found.get("state") == "ALREADY_WATCHING":
        # U141-A: one watcher per target; a second one exits instead of waking the session a second time.
>>>>>>> REPLACE


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
