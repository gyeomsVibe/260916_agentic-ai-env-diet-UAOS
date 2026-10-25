# U229B2-A1 (judge claude, deputy for LIMITED codex; Codex re-review owed): `invoke` and `usage` CLI dispatch

Card manual: `.coord/tasks/U229B2-card-manual.md`. Slice 7: a 7-line hunk inside the 2,500-line `cli.py` `main`,
which the Ollama splicer cannot replace as a whole top-level function without re-emitting the whole `main` (U236A-L2
SPLICE_UNSUPPORTED on fragments), so this non-test change under 20 lines goes through `worker: apply` (U98-D).
`invoke` and `usage` are dispatched before argparse to the modules' own parsers (`v7_harness.invocation.main`,
`v7_harness.usage_accounting.main`).

```contract
work_id: U229B2-A1
worker: apply
goal: the harness CLI dispatches `invoke` to v7_harness.invocation.main and `usage` to v7_harness.usage_accounting.main
inputs:
- v7_harness/cli.py sha256=ecadff99ffb7626d60bdfff4dc28fab1b2869f9475abe01c403ea3cf6d3ab885
- v7_harness/invocation.py sha256=62fb6ac1d9eb7b623f26e63f2a0605cfc2aaa0944294bbebc5ecc3396fabadc9
allow:
- v7_harness/cli.py
acceptance: python -m unittest tests.test_u229_claude_journal_worker tests.test_u229_independent_invocation tests.test_u229_olla_embed_journal tests.test_u236a_model_pin tests.test_u38_cost_gate_and_claude_worker tests.test_u68_claude_worker_utf8 tests.test_cli tests.test_u232_usage_accounting
forbidden: editing or deleting tests; edits outside allow; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 900 seconds
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "coord_subcommand", None) in _DESK_COMMANDS and getattr(args, "project", None):
=======
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "invoke":
        from .invocation import main as invocation_main
        return invocation_main(arguments[1:])
    if arguments and arguments[0] == "usage":
        from .usage_accounting import main as usage_main
        return usage_main(arguments[1:])
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "coord_subcommand", None) in _DESK_COMMANDS and getattr(args, "project", None):
>>>>>>> REPLACE
===END===

## Output

- Reply with the ===EDIT block only. No explanations. Do not claim success; the acceptance command decides.
