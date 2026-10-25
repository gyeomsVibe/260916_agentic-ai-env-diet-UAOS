# U233-A3: Restore `@_serialized_doc_write` on `register_new_doc` and `sync_doc_index`, and wire `cli.py`

```contract
work_id: U233-A3
worker: apply
goal: restore @_serialized_doc_write on register_new_doc and sync_doc_index, and wire docs shared_desk and --ext/--from-file in cli.py
inputs:
- v7_harness/docs_manager.py sha256=dfb974b4f68dbe619f749cb0b1b9ffcfa011879b8c92408cb95b42306d6831b4
- v7_harness/cli.py sha256=ecadff99ffb7626d60bdfff4dc28fab1b2869f9475abe01c403ea3cf6d3ab885
- tests/test_u233_unified_doc_hub.py sha256=e79b05ccfb2f6ef29077ac15ae0dc55e2b3f34ee3891e92a95a5e00ad8abf7a7
allow:
- v7_harness/docs_manager.py
- v7_harness/cli.py
acceptance: python -m unittest tests.test_u233_unified_doc_hub tests.test_u222_docs_cli tests.test_docs_manager tests.test_u222_docs_concurrency tests.test_b20_model_flag tests.test_b23_concurrency_summary tests.test_b25_db_unavailable tests.test_b41_bundle tests.test_cli tests.test_m2_pilot
forbidden: editing or deleting tests; edits outside allow; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 900 seconds
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

===EDIT: v7_harness/docs_manager.py===
<<<<<<< SEARCH
def register_new_doc(
=======
@_serialized_doc_write
def register_new_doc(
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/docs_manager.py===
<<<<<<< SEARCH
def sync_doc_index(project_root: Path) -> int:
=======
@_serialized_doc_write
def sync_doc_index(project_root: Path) -> int:
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "coord_subcommand", None) in _DESK_COMMANDS and getattr(args, "project", None):
=======
    parser = build_parser()
    args = parser.parse_args(argv)
    if (getattr(args, "coord_subcommand", None) in _DESK_COMMANDS or getattr(args, "docs_cmd", None)) and getattr(args, "project", None):
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
    p_new.add_argument("--category", default="", help="Document category")
    p_new.add_argument("--tool", default="", help="Authoring tool name")
    p_new.set_defaults(func=cmd_docs_new)
=======
    p_new.add_argument("--category", default="", help="Document category")
    p_new.add_argument("--tool", default="", help="Authoring tool name")
    p_new.add_argument("--ext", default="md", help="File extension (md or html)")
    p_new.add_argument("--from-file", dest="from_file", default=None, help="Copy body from existing file")
    p_new.set_defaults(func=cmd_docs_new)
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
    path = register_new_doc(project, title=args.title, slug=args.slug,
                            category=args.category, author_tool=args.tool)
=======
    src = Path(args.from_file) if getattr(args, "from_file", None) else None
    path = register_new_doc(project, title=args.title, slug=args.slug,
                            category=args.category, author_tool=args.tool,
                            ext=getattr(args, "ext", "md"), source_file=src)
>>>>>>> REPLACE
===END===

## Output

- Reply with the ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
