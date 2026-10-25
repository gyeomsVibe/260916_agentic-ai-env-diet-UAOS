# U229B2-L7 (judge claude, deputy for LIMITED codex; Codex re-review owed): `invoke` and `usage` CLI dispatch

Card manual: `.coord/tasks/U229B2-card-manual.md`. Slice 7, replacing U229B2-A1: A1 landed the same 7 lines through
`worker: apply`, but the commit gate accepts an apply bundle only after a real failed Ollama run of the card, and A1
wrongly assumed `cli.py` `main` was too long for the splicer. `main` is a 24-line top-level function, so Ollama
re-emits it whole. `invoke` and `usage` are dispatched before argparse to the modules' own parsers
(`v7_harness.invocation.main`, `v7_harness.usage_accounting.main`).

```contract
work_id: U229B2-L7
worker: local
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

## Exact edit: one whole top-level function, verbatim

Replace the whole top-level function `main` with:

```python
def main(argv: Optional[Sequence[str]] = None) -> int:
    # Windows 콘솔 기본(cp949)에서는 `coord brief` 등의 한국어가 깨진다. olla.main 과 같은 처리.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass
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
        from .coord.hook_context import shared_desk

        desk = shared_desk(args.project)
        if desk != Path(args.project):  # unchanged paths keep the caller's spelling
            args.project = str(desk)
    return args.func(args)
```

## Output

- Reply with one ===EDIT: v7_harness/cli.py=== block holding the whole top-level function above in a ```python
  fence, copied character for character. No explanations. Do not claim success; the acceptance command decides.
