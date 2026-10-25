# U240-L2: All-Package Project Finisher & Doc Hub Sync (`sync_project_hub`)

```contract
work_id: U240-L2
worker: local
goal: Add sync_project_hub in v7_harness/card_pipeline.py to synchronize docs/00_DOCUMENT_INDEX.md and docs/00_DOCUMENT_HUB.html at card/project finish
inputs:
- v7_harness/card_pipeline.py sha256=5d2b0a4b94a25a2a7ee3d966ca2828a6a2a2d28f5f12b765cfa411b6952e1c54
- tests/test_u240_project_finisher.py sha256=f4b513ac56c0a9dbe2bc5aa0aac60f5420e14b845d28ea42d303f184ccf139f8
allow:
- v7_harness/card_pipeline.py
context_allow:
- tests/test_u240_project_finisher.py
acceptance: C:\Python314\python.exe -m unittest tests.test_u240_project_finisher tests.test_u114_windows tests.test_u129_window_router tests.test_u135_result_relay tests.test_u221_done_truthful
forbidden: editing or deleting tests; edits outside allow; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 300 seconds
judge: claude
timeout_s: 300
remote_budget_tokens: 0
```

## Exact edit in `v7_harness/card_pipeline.py`: keep `write_result` and add `sync_project_hub`, verbatim

```python
def write_result(checkout, card, pr, mergeable, tests, blocker) -> dict[str, Any]:
    """U135: the result goes in the card's own checkout; a card worktree may not write the base checkout."""
    line = result_line(card, pr, mergeable, tests, blocker)
    path = Path(checkout) / ".coord" / "results" / f"{card}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {card} result ({datetime.date.today().isoformat()})\n\n{line}\n", encoding="utf-8")
    return {"ok": True, "path": str(path), "line": line}


def sync_project_hub(checkout) -> dict[str, Any]:
    """U240: synchronize docs/00_DOCUMENT_INDEX.md and docs/00_DOCUMENT_HUB.html at card or project finish."""
    from v7_harness.docs_manager import ensure_doc_index, ensure_docs_dir, sync_doc_index

    root = Path(checkout)
    index_md = ensure_doc_index(root)
    sync_doc_index(root)
    hub_html = ensure_docs_dir(root) / "00_DOCUMENT_HUB.html"
    return {"ok": True, "index_md": str(index_md), "hub_html": str(hub_html)}
```
