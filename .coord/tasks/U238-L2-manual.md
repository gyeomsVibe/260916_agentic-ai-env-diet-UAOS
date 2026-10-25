# U238-L2: Zero-Touch Project Doc Hub Bootstrap (`bootstrap_project_docs`)

```contract
work_id: U238-L2
worker: local
goal: Add bootstrap_project_docs in v7_harness/docs_manager.py to scaffold both 00_DOCUMENT_INDEX.md and 00_DOCUMENT_HUB.html idempotently
inputs:
- v7_harness/docs_manager.py sha256=c7925852663b24b5085838ef05abd789e013bc37e8f870f2ade5ef3ad3e9f421
- tests/test_u238_autoboot_init.py sha256=26d1e4b60bf1a6c44485b3218575e94bd6a6985f2a90bdf994ed4011f3fdf24c
allow:
- v7_harness/docs_manager.py
context_allow:
- tests/test_u238_autoboot_init.py
acceptance: C:\Python314\python.exe -m unittest tests.test_u238_autoboot_init tests.test_u233_unified_doc_hub tests.test_docs_manager tests.test_u222_docs_concurrency
forbidden: editing or deleting tests; edits outside allow; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 300 seconds
judge: claude
timeout_s: 300
remote_budget_tokens: 0
```

## Exact edit in `v7_harness/docs_manager.py`: keep `ensure_docs_dir` and add `bootstrap_project_docs`, verbatim

```python
def ensure_docs_dir(project_root: Path) -> Path:
    """Ensure the docs/ directory exists under project_root."""
    docs_dir = Path(project_root) / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    return docs_dir


def bootstrap_project_docs(project_root: Path) -> dict[str, object]:
    """Ensure docs/, 00_DOCUMENT_INDEX.md, and 00_DOCUMENT_HUB.html exist and are synchronized."""
    root = Path(project_root)
    index_path = ensure_doc_index(root)
    sync_doc_index(root)
    hub_path = ensure_docs_dir(root) / "00_DOCUMENT_HUB.html"
    return {"ok": True, "index_md": str(index_path), "hub_html": str(hub_path)}
```
