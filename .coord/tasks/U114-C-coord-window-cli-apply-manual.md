```contract
work_id: U114-C
worker: apply
goal: One CLI command, coord window, opens or reuses a card's window in any of the three tools
inputs:
- v7_harness/cli.py sha256=d2cb64e627a1f10af20ea60a7ec42ab27a99e0232f112e594d0deb6c4f560fb1
- tests/test_u114_windows.py sha256=ce66ca4c9aa69e060468fda2a1d1aee5b22e08a6596b9a2ba6f0a38038b45f63
allow:
- v7_harness/cli.py
acceptance: python -m unittest tests.test_u114_windows tests.test_u113_desk_truth tests.test_m2_pilot
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the blocks below exactly.

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
    p_coord_pub.set_defaults(func=cmd_coord_publish_thread)
=======
    p_coord_pub.set_defaults(func=cmd_coord_publish_thread)
    # U114: one process (card) = one named window per tool; the manual's content is the window's first prompt.
    p_coord_win = p_coord_subs.add_parser("window", help="Open (or reuse) the card's dedicated window in one tool")
    p_coord_win.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_win.add_argument("--card", required=True, help="Card id, e.g. U114")
    p_coord_win.add_argument("--tool", required=True, choices=["codex", "claude", "antigravity"])
    p_coord_win.add_argument("--title", required=True, help="Window title after [card]")
    p_coord_win.add_argument("--prompt-file", required=True, help="Manual whose content opens the window")
    p_coord_win.set_defaults(func=cmd_coord_window)
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
def cmd_coord_publish_thread(args: argparse.Namespace) -> int:
=======
def cmd_coord_window(args: argparse.Namespace) -> int:
    """U114: exit 0 with the window id, 2 when the tool is LIMITED/ABSENT (no window waits there)."""
    from .coord import windows

    prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    result = windows.open_window(Path(args.project), args.card, args.tool, args.title, prompt)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("id") else 2


def cmd_coord_publish_thread(args: argparse.Namespace) -> int:
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
